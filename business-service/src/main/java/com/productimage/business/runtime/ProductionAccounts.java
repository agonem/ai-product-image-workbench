package com.productimage.business.runtime;

import com.fasterxml.jackson.databind.JsonNode;
import java.nio.charset.StandardCharsets;
import java.security.SecureRandom;
import java.sql.Timestamp;
import java.util.Base64;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import org.springframework.core.env.Environment;
import org.springframework.dao.DuplicateKeyException;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.transaction.support.TransactionTemplate;

/** Database-backed production identities; independent of file-based development accounts. */
public final class ProductionAccounts implements UserAuthenticator {
  private final JdbcTemplate jdbc;
  private final TransactionTemplate tx;
  private final LocalObjectStore store;
  private final int seconds;
  private final int loginLimit;

  ProductionAccounts(
      Environment env, JdbcTemplate jdbc, TransactionTemplate tx, LocalObjectStore store) {
    this.jdbc = jdbc;
    this.tx = tx;
    this.store = store;
    // Default working day (8 h, user decision); 60 s - 24 h configurable.
    seconds = limit(env, "PROD_SESSION_SECONDS", 28800, 60, 86400);
    loginLimit = limit(env, "PROD_LOGIN_LIMIT", 60, 1, 600);
    tx.executeWithoutResult(
        status -> {
          managementLock();
          if (jdbc.queryForObject("SELECT count(*) FROM local_credentials", Long.class) == 0) {
            var seed = ProductionPasswords.bootstrap(env.getProperty("PROD_BOOTSTRAP_FILE", ""));
            String id = UUID.randomUUID().toString();
            insert(
                id,
                seed.path("username").asText(),
                seed.path("salt").asText(),
                seed.path("password_hash").asText(),
                "ADMIN");
            audit(id, "LOCAL_BOOTSTRAP", id);
          }
        });
  }

  private static int limit(Environment env, String key, int fallback, int min, int max) {
    int value = env.getProperty(key, Integer.class, fallback);
    if (value < min || value > max)
      throw new IllegalStateException("Invalid production authentication limit");
    return value;
  }

  private void managementLock() {
    // Serialize management before actor/target locks to protect the last active administrator.
    jdbc.execute("SELECT pg_advisory_xact_lock(7040401)");
  }

  private void insert(String id, String name, String salt, String hash, String role) {
    jdbc.update("INSERT INTO users(id,status) VALUES (?,'ACTIVE')", id);
    jdbc.update(
        "INSERT INTO local_credentials(user_id,username,salt,password_hash,role) VALUES (?,?,?,?,?)",
        id,
        name,
        salt,
        hash,
        role);
  }

  private void audit(String actor, String action, String resource) {
    jdbc.update(
        "INSERT INTO audit_events(id,actor_id,action,resource_id,correlation_id) VALUES (?,?,?,?,?)",
        UUID.randomUUID().toString(),
        actor,
        action,
        resource,
        UUID.randomUUID().toString());
  }

  private String key(String header) {
    if (header == null || !header.matches("Bearer [A-Za-z0-9_-]{43}"))
      throw new Problem(401, "UNAUTHORIZED");
    return Json.hash(header.substring(7).getBytes(StandardCharsets.UTF_8));
  }

  @Override
  public String authenticate(String header) {
    var ids =
        jdbc.queryForList(
            "SELECT s.user_id FROM local_sessions s JOIN users u ON u.id=s.user_id "
                + "WHERE s.token_hash=? AND s.expires_at>clock_timestamp() AND u.status='ACTIVE'",
            String.class,
            key(header));
    if (ids.isEmpty()) throw new Problem(401, "UNAUTHORIZED");
    return ids.getFirst();
  }

  private Map<String, Object> account(String id, boolean lock) {
    var rows =
        jdbc.queryForList(
            "SELECT c.*,u.status FROM local_credentials c JOIN users u ON u.id=c.user_id "
                + "WHERE c.user_id=?"
                + (lock ? " FOR UPDATE OF c,u" : ""),
            id);
    if (rows.isEmpty()) throw new Problem(404, "NOT_FOUND");
    return rows.getFirst();
  }

  private JsonNode safe(Map<String, Object> row) {
    return Json.object()
        .put("id", row.get("user_id").toString())
        .put("username", row.get("username").toString())
        .put("role", row.get("role").toString())
        .put("status", row.get("status").toString());
  }

  public JsonNode me(String header) {
    var row = account(authenticate(header), false);
    var expires =
        jdbc.queryForObject(
            "SELECT expires_at FROM local_sessions WHERE token_hash=?",
            Timestamp.class,
            key(header));
    return Json.object()
        .put("id", row.get("user_id").toString())
        .put("username", row.get("username").toString())
        .put("role", row.get("role").toString())
        .put("mode", "production-local")
        .put("expires_at", expires.toInstant().toString());
  }

  public JsonNode login(JsonNode body) {
    ProductionPasswords.fields(body, "username", "password");
    // This statement commits even when the subsequent authentication transaction is rejected.
    int attempts =
        jdbc.queryForObject(
            "INSERT INTO local_auth_throttle(id,window_started,attempts) VALUES (1,clock_timestamp(),1) "
                + "ON CONFLICT(id) DO UPDATE SET attempts=CASE WHEN local_auth_throttle.window_started <= clock_timestamp()-interval '60 seconds' "
                + "THEN 1 ELSE least(local_auth_throttle.attempts+1,1000000) END, window_started=CASE "
                + "WHEN local_auth_throttle.window_started <= clock_timestamp()-interval '60 seconds' THEN clock_timestamp() ELSE local_auth_throttle.window_started END RETURNING attempts",
            Integer.class);
    if (attempts > loginLimit) throw new Problem(429, "LOGIN_RATE_LIMITED");
    String name = body.path("username").asText(), password = body.path("password").asText();
    if (name.length() > 64 || password.isEmpty() || password.length() > 128)
      throw new Problem(401, "UNAUTHORIZED");
    return tx.execute(
        status -> {
          var rows =
              jdbc.queryForList(
                  "SELECT c.*,u.status FROM local_credentials c JOIN users u ON u.id=c.user_id WHERE username=? FOR UPDATE OF c,u",
                  name);
          var row = rows.isEmpty() ? null : rows.getFirst();
          boolean valid =
              ProductionPasswords.matches(
                  password,
                  row == null ? "0".repeat(32) : row.get("salt").toString(),
                  row == null ? "0".repeat(64) : row.get("password_hash").toString());
          if (!valid || row == null || !"ACTIVE".equals(row.get("status")))
            throw new Problem(401, "UNAUTHORIZED");
          String id = row.get("user_id").toString();
          jdbc.update("DELETE FROM local_sessions WHERE expires_at<=clock_timestamp()");
          if (jdbc.queryForObject(
                  "SELECT count(*) FROM local_sessions WHERE user_id=?", Long.class, id)
              >= 20) throw new Problem(429, "SESSION_LIMIT_REACHED");
          byte[] bytes = new byte[32];
          new SecureRandom().nextBytes(bytes);
          String token = Base64.getUrlEncoder().withoutPadding().encodeToString(bytes);
          Timestamp expires =
              jdbc.queryForObject(
                  "INSERT INTO local_sessions(token_hash,user_id,expires_at) VALUES (?,?,clock_timestamp()+make_interval(secs=>?)) RETURNING expires_at",
                  Timestamp.class,
                  key("Bearer " + token),
                  id,
                  seconds);
          audit(id, "LOCAL_LOGIN", id);
          var response =
              Json.object()
                  .put("access_token", token)
                  .put("token_type", "Bearer")
                  .put("expires_at", expires.toInstant().toString())
                  .put("mode", "production-local");
          response.set(
              "user",
              Json.object()
                  .put("id", id)
                  .put("username", name)
                  .put("role", row.get("role").toString()));
          return response;
        });
  }

  String manager(String header) {
    String actor = authenticate(header);
    var row = account(actor, true);
    // Recheck after obtaining the account lock in case revocation won the race.
    authenticate(header);
    if (!"ADMIN".equals(row.get("role"))) throw new Problem(403, "FORBIDDEN");
    return actor;
  }

  public JsonNode list(String header, String after) {
    return tx.execute(
        status -> {
          managementLock();
          manager(header);
          if (after == null) afterValidation("");
          else afterValidation(after);
          var rows =
              jdbc.queryForList(
                  "SELECT c.user_id,c.username,c.role,u.status FROM local_credentials c JOIN users u ON u.id=c.user_id WHERE c.user_id>? ORDER BY c.user_id LIMIT 101",
                  after == null ? "" : after);
          var result = Json.object();
          var items = result.putArray("items");
          rows.stream().limit(100).forEach(row -> items.add(safe(row)));
          if (rows.size() > 100) result.put("next_after", rows.get(99).get("user_id").toString());
          else result.putNull("next_after");
          return result;
        });
  }

  private void afterValidation(String after) {
    if (!after.isEmpty() && !after.matches("[A-Za-z0-9][A-Za-z0-9_-]{0,127}"))
      throw new Problem(400, "INVALID_CONTRACT");
  }

  public JsonNode create(String header, JsonNode body) {
    try {
      return tx.execute(
          status -> {
            managementLock();
            String actor = manager(header);
            ProductionPasswords.fields(body, "username", "password", "role");
            String name = body.path("username").asText(), role = body.path("role").asText();
            ProductionPasswords.username(name);
            if (!List.of("USER", "ADMIN").contains(role))
              throw new Problem(400, "INVALID_CONTRACT");
            var password = ProductionPasswords.encode(body.path("password").asText());
            String id = UUID.randomUUID().toString();
            insert(id, name, password.salt(), password.hash(), role);
            audit(actor, "LOCAL_CREATE", id);
            return safe(account(id, false));
          });
    } catch (DuplicateKeyException ex) {
      throw new Problem(409, "ACCOUNT_CONFLICT");
    }
  }

  public void status(String header, String id, JsonNode body) {
    tx.executeWithoutResult(
        status -> {
          managementLock();
          String actor = manager(header);
          ProductionPasswords.fields(body, "status");
          String next = body.path("status").asText();
          if (!List.of("ACTIVE", "DISABLED").contains(next))
            throw new Problem(400, "INVALID_CONTRACT");
          var row = account(id, true);
          if ("DISABLED".equals(next)
              && "ADMIN".equals(row.get("role"))
              && "ACTIVE".equals(row.get("status"))
              && jdbc.queryForObject(
                      "SELECT count(*) FROM local_credentials c JOIN users u ON u.id=c.user_id WHERE c.role='ADMIN' AND u.status='ACTIVE'",
                      Long.class)
                  <= 1) throw new Problem(409, "LAST_ADMIN_REQUIRED");
          jdbc.update("UPDATE users SET status=? WHERE id=?", next, id);
          jdbc.update("DELETE FROM local_sessions WHERE user_id=?", id);
          audit(actor, "LOCAL_STATUS", id);
        });
  }

  /**
   * An admin deletes an account (ADR-20260930-E): it is signed out and can never sign in again, its
   * login name becomes free, and its originals and generated images are deleted (deletion records
   * first, files after commit). Projects, tasks and audit rows stay for history. An account with
   * queued or running tasks is refused so no image appears after the deletion.
   */
  public void delete(String header, String id) {
    java.util.List<String> keys =
        tx.execute(
            status -> {
              managementLock();
              String actor = manager(header);
              if (actor.equals(id)) throw new Problem(409, "SELF_DELETE");
              var row = account(id, true);
              if ("ADMIN".equals(row.get("role"))
                  && "ACTIVE".equals(row.get("status"))
                  && jdbc.queryForObject(
                          "SELECT count(*) FROM local_credentials c JOIN users u ON u.id=c.user_id WHERE c.role='ADMIN' AND u.status='ACTIVE'",
                          Long.class)
                      <= 1) throw new Problem(409, "LAST_ADMIN_REQUIRED");
              if (jdbc.queryForObject(
                      "SELECT count(*) FROM generation_tasks t JOIN projects p ON p.id=t.project_id WHERE p.owner_id=? AND t.status IN ('QUEUED','RUNNING')",
                      Long.class,
                      id)
                  > 0) throw new Problem(409, "ACCOUNT_BUSY");
              var removed = new java.util.ArrayList<String>();
              for (var image :
                  jdbc.queryForList(
                      "SELECT a.id,a.object_key,'ASSET' AS kind FROM assets a JOIN projects p ON p.id=a.project_id WHERE p.owner_id=? AND NOT EXISTS (SELECT 1 FROM deletions d WHERE d.target_id=a.id) "
                          + "UNION ALL SELECT f.id,f.object_key,'ARTIFACT' FROM artifacts f JOIN generation_tasks t ON t.id=f.task_id JOIN projects p ON p.id=t.project_id WHERE p.owner_id=? AND NOT EXISTS (SELECT 1 FROM deletions d WHERE d.target_id=f.id)",
                      id,
                      id)) {
                jdbc.update(
                    "INSERT INTO deletions(target_id,target_kind,deleted_by) VALUES (?,?,?)",
                    image.get("id"),
                    image.get("kind"),
                    actor);
                removed.add(image.get("object_key").toString());
              }
              jdbc.update("DELETE FROM local_sessions WHERE user_id=?", id);
              jdbc.update("DELETE FROM local_credentials WHERE user_id=?", id);
              jdbc.update(
                  "UPDATE users SET status='DELETED',deleted_username=? WHERE id=?",
                  row.get("username"),
                  id);
              audit(actor, "LOCAL_DELETE", id);
              return removed;
            });
    keys.forEach(store::delete);
  }

  public void password(String header, String target, JsonNode body) {
    tx.executeWithoutResult(
        status -> {
          managementLock();
          String actor = target == null ? authenticate(header) : manager(header);
          String id = target == null ? actor : target;
          var row = account(id, true);
          authenticate(header);
          if (target == null) {
            ProductionPasswords.fields(body, "current_password", "new_password");
            if (!ProductionPasswords.matches(
                body.path("current_password").asText(),
                row.get("salt").toString(),
                row.get("password_hash").toString())) throw new Problem(401, "UNAUTHORIZED");
          } else ProductionPasswords.fields(body, "new_password");
          var encoded = ProductionPasswords.encode(body.path("new_password").asText());
          jdbc.update(
              "UPDATE local_credentials SET salt=?,password_hash=? WHERE user_id=?",
              encoded.salt(),
              encoded.hash(),
              id);
          jdbc.update("DELETE FROM local_sessions WHERE user_id=?", id);
          audit(actor, target == null ? "LOCAL_PASSWORD" : "LOCAL_RESET", id);
        });
  }

  public void logout(String header) {
    tx.executeWithoutResult(
        status -> {
          String actor = authenticate(header);
          jdbc.update("DELETE FROM local_sessions WHERE token_hash=?", key(header));
          audit(actor, "LOCAL_LOGOUT", actor);
        });
  }
}
