package com.productimage.business.runtime;

import com.fasterxml.jackson.databind.JsonNode;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.GeneralSecurityException;
import java.security.MessageDigest;
import java.security.SecureRandom;
import java.time.Clock;
import java.time.Instant;
import java.util.ArrayDeque;
import java.util.Base64;
import java.util.HashMap;
import java.util.HashSet;
import java.util.HexFormat;
import java.util.Map;
import javax.crypto.SecretKeyFactory;
import javax.crypto.spec.PBEKeySpec;
import org.springframework.core.env.Environment;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.transaction.support.TransactionTemplate;

/** Deliberately local-only: private file accounts and revocable, restart-ephemeral sessions. */
public final class LocalAccounts implements UserAuthenticator {
  private record Account(String user, byte[] salt, byte[] hash) {}

  private record Session(String user, Instant expires) {}

  private final Map<String, Account> accounts = new HashMap<>();
  private final Map<String, Session> sessions = new HashMap<>();
  private final ArrayDeque<Instant> attempts = new ArrayDeque<>();
  private final SecureRandom random = new SecureRandom();
  private final ProjectAccess access;
  private final Clock clock;
  private final int seconds;

  LocalAccounts(
      Environment env,
      JdbcTemplate jdbc,
      TransactionTemplate tx,
      ProjectAccess access,
      Clock clock) {
    this.access = access;
    this.clock = clock;
    seconds = env.getProperty("DEV_SESSION_SECONDS", Integer.class, 900);
    if (seconds < 2 || seconds > 3600)
      throw new IllegalStateException("Invalid development session lifetime");
    try (var input = Files.newInputStream(Path.of(env.getRequiredProperty("DEV_ACCOUNTS_FILE")))) {
      byte[] bytes = input.readNBytes(65537);
      if (bytes.length > 65536) throw new IllegalArgumentException();
      JsonNode values = Json.parse(new String(bytes, StandardCharsets.UTF_8));
      if (!values.isArray() || values.isEmpty() || values.size() > 100)
        throw new IllegalArgumentException();
      var users = new HashSet<String>();
      for (var value : values) {
        if (!value.isObject() || value.size() != 4) throw new IllegalArgumentException();
        String name = text(value, "username"), user = text(value, "user_id");
        String salt = text(value, "salt"), hash = text(value, "password_hash");
        if (!name.matches("[a-z0-9][a-z0-9_-]{0,63}")
            || !user.matches("[A-Za-z0-9][A-Za-z0-9_-]{0,127}")
            || !salt.matches("[0-9a-f]{32}")
            || !hash.matches("[0-9a-f]{64}")
            || accounts.containsKey(name)
            || !users.add(user)) throw new IllegalArgumentException();
        accounts.put(
            name, new Account(user, HexFormat.of().parseHex(salt), HexFormat.of().parseHex(hash)));
      }
    } catch (IOException | RuntimeException ex) {
      throw new IllegalStateException("Invalid or missing private development account file");
    }
    tx.executeWithoutResult(
        status ->
            accounts
                .values()
                .forEach(
                    account ->
                        jdbc.update(
                            "INSERT INTO users(id,status) VALUES (?,'ACTIVE') ON CONFLICT(id) DO NOTHING",
                            account.user())));
  }

  private static String text(JsonNode value, String field) {
    if (!value.path(field).isTextual()) throw new IllegalArgumentException();
    return value.path(field).asText();
  }

  static byte[] derive(char[] password, byte[] salt) {
    var spec = new PBEKeySpec(password, salt, 600000, 256);
    try {
      return SecretKeyFactory.getInstance("PBKDF2WithHmacSHA256").generateSecret(spec).getEncoded();
    } catch (GeneralSecurityException ex) {
      throw new IllegalStateException("Password hashing unavailable");
    } finally {
      spec.clearPassword();
      java.util.Arrays.fill(password, '\0');
    }
  }

  public synchronized JsonNode login(JsonNode body) {
    Instant now = clock.instant();
    while (!attempts.isEmpty() && !attempts.peekFirst().plusSeconds(60).isAfter(now))
      attempts.removeFirst();
    if (attempts.size() >= 30) throw new Problem(429, "LOGIN_RATE_LIMITED");
    attempts.addLast(now);
    if (!body.isObject()
        || body.size() != 2
        || !body.path("username").isTextual()
        || !body.path("password").isTextual()) {
      throw new Problem(400, "INVALID_CONTRACT");
    }
    String name = body.path("username").asText(), password = body.path("password").asText();
    if (name.length() > 64 || password.length() < 1 || password.length() > 128)
      throw new Problem(401, "UNAUTHORIZED");
    Account account = accounts.get(name);
    // Unknown users incur the same KDF work; never echo account names or passwords.
    byte[] candidate =
        derive(password.toCharArray(), account == null ? new byte[16] : account.salt());
    if (!MessageDigest.isEqual(candidate, account == null ? new byte[32] : account.hash())
        || account == null) {
      throw new Problem(401, "UNAUTHORIZED");
    }
    access.active(account.user());
    sessions.values().removeIf(session -> !session.expires().isAfter(now));
    if (sessions.size() >= 256) throw new Problem(429, "SESSION_LIMIT_REACHED");
    byte[] bytes = new byte[32];
    random.nextBytes(bytes);
    String token = Base64.getUrlEncoder().withoutPadding().encodeToString(bytes);
    Instant expires = now.plusSeconds(seconds);
    sessions.put(digest(token), new Session(account.user(), expires));
    var response =
        Json.object()
            .put("access_token", token)
            .put("token_type", "Bearer")
            .put("expires_at", expires.toString())
            .put("mode", "development-only");
    response.putObject("user").put("id", account.user());
    return response;
  }

  private static String digest(String token) {
    return Json.hash(token.getBytes(StandardCharsets.UTF_8));
  }

  private String sessionKey(String header) {
    if (header == null || !header.matches("Bearer [A-Za-z0-9_-]{43}"))
      throw new Problem(401, "UNAUTHORIZED");
    return digest(header.substring(7));
  }

  @Override
  public synchronized String authenticate(String header) {
    String key = sessionKey(header);
    Session session = sessions.get(key);
    if (session == null || !session.expires().isAfter(clock.instant())) {
      sessions.remove(key);
      throw new Problem(401, "UNAUTHORIZED");
    }
    access.active(session.user());
    return session.user();
  }

  public synchronized void logout(String header) {
    authenticate(header);
    sessions.remove(sessionKey(header));
  }
}
