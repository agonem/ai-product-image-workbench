package com.productimage.business.runtime;

import com.fasterxml.jackson.databind.JsonNode;
import jakarta.servlet.http.HttpServletRequest;
import java.sql.Timestamp;
import java.util.Map;
import java.util.UUID;
import org.springframework.context.annotation.Profile;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.web.bind.annotation.*;

/**
 * Agents for conversational generation (ADR-20261008-L). Public agents (no owner) are kept by
 * administrators and offered to everyone; personal agents belong to one account. A task freezes the
 * agent's settings, so editing or deleting an agent never changes earlier results.
 */
@RestController
@Profile("runtime")
public class AgentApi {
  private static final int AVATAR_BYTES = 512 * 1024;
  private final UserAuthenticator users;
  private final JdbcTemplate jdbc;
  private final LocalObjectStore store;
  private final ProviderConfigService configs;

  AgentApi(
      UserAuthenticator users,
      JdbcTemplate jdbc,
      LocalObjectStore store,
      ProviderConfigService configs) {
    this.users = users;
    this.jdbc = jdbc;
    this.store = store;
    this.configs = configs;
  }

  private String actor(HttpServletRequest request) {
    return users.authenticate(request.getHeader("Authorization"));
  }

  private boolean admin(String actor) {
    return jdbc.queryForObject(
            "SELECT count(*) FROM local_credentials WHERE user_id=? AND role='ADMIN'",
            Long.class,
            actor)
        > 0;
  }

  /** Visible to the actor: public ones and their own. */
  private Map<String, Object> visible(String actor, String id) {
    var rows =
        jdbc.queryForList(
            "SELECT * FROM agents WHERE id=? AND (owner_id IS NULL OR owner_id=?)", id, actor);
    if (rows.isEmpty()) throw new Problem(404, "NOT_FOUND");
    return rows.getFirst();
  }

  /** Changeable by the actor: their own, or a public one when they are an administrator. */
  private Map<String, Object> editable(String actor, String id) {
    var row = visible(actor, id);
    if (row.get("owner_id") == null && !admin(actor)) throw new Problem(403, "FORBIDDEN");
    return row;
  }

  private static JsonNode item(Map<String, Object> row, String actor, boolean admin) {
    boolean shared = row.get("owner_id") == null;
    return Json.object()
        .put("id", row.get("id").toString())
        .put("name", row.get("name").toString())
        .put("description", row.get("description").toString())
        .put("instructions", row.get("instructions").toString())
        .put("public", shared)
        .put("editable", shared ? admin : actor.equals(row.get("owner_id").toString()))
        .put("avatar", row.get("avatar_key") != null)
        .put("updated_at", ((Timestamp) row.get("updated_at")).toInstant().toString());
  }

  private static boolean text(JsonNode value, int min, int max) {
    return value.isTextual()
        && value.asText().strip().codePointCount(0, value.asText().strip().length()) >= min
        && value.asText().strip().codePointCount(0, value.asText().strip().length()) <= max
        && value.asText().codePoints().noneMatch(c -> Character.isISOControl(c) && c != '\n');
  }

  /** {name, description, instructions} plus "public" when creating; nothing else. */
  private static void validate(JsonNode body, boolean creating) {
    var allowed = new java.util.HashSet<>(java.util.List.of("name", "description", "instructions"));
    if (creating) allowed.add("public");
    var names = new java.util.HashSet<String>();
    body.fieldNames().forEachRemaining(names::add);
    if (!body.isObject()
        || !allowed.containsAll(names)
        || !names.containsAll(java.util.List.of("name", "description", "instructions"))
        || !text(body.path("name"), 1, 20)
        || !text(body.path("description"), 0, 60)
        || !text(body.path("instructions"), 1, 2000)
        || (body.has("public") && !body.path("public").isBoolean()))
      throw new Problem(400, "INVALID_CONTRACT");
  }

  @GetMapping("/api/v1/agents")
  ResponseEntity<JsonNode> list(HttpServletRequest request) {
    String actor = actor(request);
    boolean admin = admin(actor);
    var items = Json.MAPPER.createArrayNode();
    for (var row :
        jdbc.queryForList(
            "SELECT * FROM agents WHERE owner_id IS NULL OR owner_id=? ORDER BY (owner_id IS NOT NULL),created_at,id LIMIT 200",
            actor)) items.add(item(row, actor, admin));
    var result = Json.object();
    result.set("items", items);
    result.put("text_model", configs.textBinding() != null).put("admin", admin);
    return ResponseEntity.ok().header("Cache-Control", "no-store").body(result);
  }

  @PostMapping("/api/v1/agents")
  ResponseEntity<JsonNode> create(HttpServletRequest request) {
    String actor = actor(request);
    var body = HttpInput.json(request, 16384);
    validate(body, true);
    boolean shared = body.path("public").asBoolean();
    if (shared && !admin(actor)) throw new Problem(403, "FORBIDDEN");
    if (!shared
        && jdbc.queryForObject("SELECT count(*) FROM agents WHERE owner_id=?", Long.class, actor)
            >= 50) throw new Problem(409, "AGENT_LIMIT");
    String id = "agent-" + UUID.randomUUID();
    jdbc.update(
        "INSERT INTO agents(id,owner_id,name,description,instructions,created_by) VALUES (?,?,?,?,?,?)",
        id,
        shared ? null : actor,
        body.path("name").asText().strip(),
        body.path("description").asText().strip(),
        body.path("instructions").asText().strip(),
        actor);
    return ResponseEntity.status(201)
        .header("Cache-Control", "no-store")
        .body(item(jdbc.queryForMap("SELECT * FROM agents WHERE id=?", id), actor, admin(actor)));
  }

  @PutMapping("/api/v1/agents/{id}")
  ResponseEntity<JsonNode> update(@PathVariable String id, HttpServletRequest request) {
    String actor = actor(request);
    var body = HttpInput.json(request, 16384);
    validate(body, false);
    editable(actor, id);
    jdbc.update(
        "UPDATE agents SET name=?,description=?,instructions=?,updated_at=now() WHERE id=?",
        body.path("name").asText().strip(),
        body.path("description").asText().strip(),
        body.path("instructions").asText().strip(),
        id);
    return ResponseEntity.ok()
        .header("Cache-Control", "no-store")
        .body(item(jdbc.queryForMap("SELECT * FROM agents WHERE id=?", id), actor, admin(actor)));
  }

  @DeleteMapping("/api/v1/agents/{id}")
  ResponseEntity<Void> delete(@PathVariable String id, HttpServletRequest request) {
    String actor = actor(request);
    var row = editable(actor, id);
    jdbc.update("DELETE FROM agents WHERE id=?", id);
    if (row.get("avatar_key") != null) store.delete(row.get("avatar_key").toString());
    return ResponseEntity.noContent().build();
  }

  /** A small PNG or JPEG (the page sends a 256 px square); the type comes from the content. */
  @PutMapping("/api/v1/agents/{id}/avatar")
  ResponseEntity<Void> avatar(@PathVariable String id, HttpServletRequest request) {
    String actor = actor(request);
    var row = editable(actor, id);
    byte[] data = HttpInput.bytes(request, AVATAR_BYTES);
    UploadValidation.validate(data, AVATAR_BYTES, 4_000_000);
    String key = "agents/" + UUID.randomUUID() + ".image";
    store.put(key, data);
    jdbc.update("UPDATE agents SET avatar_key=?,updated_at=now() WHERE id=?", key, id);
    if (row.get("avatar_key") != null) store.delete(row.get("avatar_key").toString());
    return ResponseEntity.noContent().build();
  }

  @DeleteMapping("/api/v1/agents/{id}/avatar")
  ResponseEntity<Void> clearAvatar(@PathVariable String id, HttpServletRequest request) {
    String actor = actor(request);
    var row = editable(actor, id);
    jdbc.update("UPDATE agents SET avatar_key=NULL,updated_at=now() WHERE id=?", id);
    if (row.get("avatar_key") != null) store.delete(row.get("avatar_key").toString());
    return ResponseEntity.noContent().build();
  }

  @GetMapping("/api/v1/agents/{id}/avatar")
  ResponseEntity<byte[]> avatarContent(@PathVariable String id, HttpServletRequest request) {
    var row = visible(actor(request), id);
    if (row.get("avatar_key") == null) throw new Problem(404, "NOT_FOUND");
    byte[] data = store.read(row.get("avatar_key").toString());
    boolean png = data.length > 8 && data[0] == (byte) 137 && data[1] == 80;
    return ResponseEntity.ok()
        .header("Cache-Control", "private, no-store")
        .header("X-Content-Type-Options", "nosniff")
        .contentType(png ? MediaType.IMAGE_PNG : MediaType.IMAGE_JPEG)
        .body(data);
  }
}
