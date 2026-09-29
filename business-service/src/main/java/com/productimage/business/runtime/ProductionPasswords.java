package com.productimage.business.runtime;

import com.fasterxml.jackson.databind.JsonNode;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.MessageDigest;
import java.security.SecureRandom;
import java.util.HexFormat;

/** Password encoding shared with the offline bootstrap tool; never stores cleartext. */
final class ProductionPasswords {
  record Encoded(String salt, String hash) {}

  private ProductionPasswords() {}

  static void fields(JsonNode body, String... fields) {
    if (!body.isObject() || body.size() != fields.length)
      throw new Problem(400, "INVALID_CONTRACT");
    for (String field : fields)
      if (!body.path(field).isTextual()) throw new Problem(400, "INVALID_CONTRACT");
  }

  static void username(String name) {
    if (!name.matches("[a-z0-9][a-z0-9_-]{0,63}")) throw new Problem(400, "INVALID_CONTRACT");
  }

  /** New passwords (bootstrap, change, reset, create): 6-15 characters by user decision. */
  static final int MIN_LENGTH = 6, MAX_LENGTH = 15;

  static Encoded encode(String password) {
    if (password.length() < MIN_LENGTH || password.length() > MAX_LENGTH)
      throw new Problem(400, "INVALID_CONTRACT");
    byte[] salt = new byte[16];
    new SecureRandom().nextBytes(salt);
    return new Encoded(
        HexFormat.of().formatHex(salt),
        HexFormat.of().formatHex(LocalAccounts.derive(password.toCharArray(), salt)));
  }

  static boolean matches(String password, String salt, String hash) {
    if (password.isEmpty() || password.length() > 128) return false;
    return MessageDigest.isEqual(
        LocalAccounts.derive(password.toCharArray(), HexFormat.of().parseHex(salt)),
        HexFormat.of().parseHex(hash));
  }

  static JsonNode bootstrap(String path) {
    try (var input = Files.newInputStream(Path.of(path))) {
      byte[] bytes = input.readNBytes(4097);
      if (bytes.length > 4096) throw new IllegalArgumentException();
      var value = Json.parse(new String(bytes, StandardCharsets.UTF_8));
      fields(value, "username", "salt", "password_hash");
      username(value.path("username").asText());
      if (!value.path("salt").asText().matches("[0-9a-f]{32}")
          || !value.path("password_hash").asText().matches("[0-9a-f]{64}"))
        throw new IllegalArgumentException();
      return value;
    } catch (Exception ex) {
      throw new IllegalStateException("Missing or invalid private production bootstrap file");
    }
  }
}
