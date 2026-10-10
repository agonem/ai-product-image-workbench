package com.productimage.business.runtime;

import com.fasterxml.jackson.databind.JsonNode;
import jakarta.servlet.http.HttpServletRequest;
import java.sql.Timestamp;
import java.util.HashSet;
import java.util.Map;
import org.springframework.context.annotation.Profile;
import org.springframework.http.ResponseEntity;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.web.bind.annotation.*;

/**
 * Conversations of the conversational generation page (ADR-20261008-I). A conversation groups the
 * owner's CUSTOM tasks in one project; each message is an ordinary v4 task created through {@code
 * POST /api/v4/generation-tasks}. Deleting a conversation keeps its tasks and images. Its canvas
 * layout (ADR-20261010-V) is kept per conversation and deleted with it.
 */
@RestController
@Profile("runtime")
public class ConversationApi {
  private final UserAuthenticator users;
  private final JdbcTemplate jdbc;
  private final TaskService tasks;

  ConversationApi(UserAuthenticator users, JdbcTemplate jdbc, TaskService tasks) {
    this.users = users;
    this.jdbc = jdbc;
    this.tasks = tasks;
  }

  private String actor(HttpServletRequest request) {
    return users.authenticate(request.getHeader("Authorization"));
  }

  private void ownProject(String actor, String project) {
    if (jdbc.queryForObject(
            "SELECT count(*) FROM projects p JOIN users u ON u.id=p.owner_id WHERE p.id=? AND p.owner_id=? AND u.status='ACTIVE'",
            Long.class,
            project,
            actor)
        != 1) throw new Problem(404, "NOT_FOUND");
  }

  private Map<String, Object> owned(String actor, String id) {
    var rows =
        jdbc.queryForList(
            "SELECT c.* FROM conversations c JOIN projects p ON p.id=c.project_id JOIN users u ON u.id=p.owner_id WHERE c.id=? AND p.owner_id=? AND u.status='ACTIVE'",
            id,
            actor);
    if (rows.isEmpty()) throw new Problem(404, "NOT_FOUND");
    return rows.getFirst();
  }

  private static com.fasterxml.jackson.databind.node.ObjectNode summary(Map<String, Object> row) {
    return Json.object()
        .put("id", row.get("id").toString())
        .put("title", row.get("title").toString())
        .put("created_at", ((Timestamp) row.get("created_at")).toInstant().toString())
        .put("updated_at", ((Timestamp) row.get("updated_at")).toInstant().toString());
  }

  @PostMapping("/api/v1/projects/{project}/conversations")
  ResponseEntity<JsonNode> create(@PathVariable String project, HttpServletRequest request) {
    String actor = actor(request);
    var body = HttpInput.json(request, 4096);
    var title = body.path("title");
    if (body.size() != 1
        || !title.isTextual()
        || title.asText().isBlank()
        || title.asText().codePointCount(0, title.asText().length()) > 40)
      throw new Problem(400, "INVALID_CONTRACT");
    ownProject(actor, project);
    String id = Json.id();
    jdbc.update(
        "INSERT INTO conversations(id,project_id,title) VALUES (?,?,?)",
        id,
        project,
        title.asText().strip());
    var row = jdbc.queryForMap("SELECT * FROM conversations WHERE id=?", id);
    return ResponseEntity.status(201)
        .header("Cache-Control", "no-store")
        .body(summary(row).put("turns", 0).putNull("cover"));
  }

  @GetMapping("/api/v1/projects/{project}/conversations")
  ResponseEntity<JsonNode> list(@PathVariable String project, HttpServletRequest request) {
    String actor = actor(request);
    ownProject(actor, project);
    var items = Json.MAPPER.createArrayNode();
    for (var row :
        jdbc.queryForList(
            "SELECT c.*,(SELECT count(*) FROM generation_tasks t WHERE t.conversation_id=c.id AND t.feature_type='CUSTOM') AS turns,(SELECT a.id FROM generation_tasks t JOIN artifacts a ON a.task_id=t.id AND a.attempt_id=t.current_attempt_id AND a.kind='COMPOSITE' WHERE t.conversation_id=c.id AND t.status='SUCCEEDED' AND NOT EXISTS (SELECT 1 FROM deletions d WHERE d.target_id=a.id) ORDER BY t.created_at DESC,a.ordinal LIMIT 1) AS cover FROM conversations c WHERE c.project_id=? ORDER BY c.updated_at DESC,c.id LIMIT 100",
            project)) {
      var item = summary(row).put("turns", ((Number) row.get("turns")).intValue());
      if (row.get("cover") == null) item.putNull("cover");
      else item.put("cover", row.get("cover").toString());
      items.add(item);
    }
    return ResponseEntity.ok()
        .header("Cache-Control", "no-store")
        .body(Json.object().set("items", items));
  }

  @GetMapping("/api/v1/conversations/{id}")
  ResponseEntity<JsonNode> get(@PathVariable String id, HttpServletRequest request) {
    String actor = actor(request);
    var conversation = summary(owned(actor, id));
    var list = conversation.putArray("tasks");
    for (var task :
        jdbc.queryForList(
            "SELECT id FROM generation_tasks WHERE conversation_id=? ORDER BY created_at,id LIMIT 200",
            String.class,
            id)) list.add(tasks.getGeneration(actor, task));
    return ResponseEntity.ok().header("Cache-Control", "no-store").body(conversation);
  }

  /** Where the owner placed the conversation's pictures; version 0 when never saved. */
  @GetMapping("/api/v1/conversations/{id}/canvas")
  ResponseEntity<JsonNode> canvas(@PathVariable String id, HttpServletRequest request) {
    String actor = actor(request);
    owned(actor, id);
    var body = Json.object();
    var rows =
        jdbc.queryForList(
            "SELECT layout::text AS layout,version,updated_at FROM conversation_canvases WHERE conversation_id=?",
            id);
    if (rows.isEmpty()) body.put("version", 0).putNull("layout").putNull("updated_at");
    else {
      var row = rows.getFirst();
      body.put("version", ((Number) row.get("version")).intValue());
      body.set("layout", Json.parse(row.get("layout").toString()));
      body.put("updated_at", ((Timestamp) row.get("updated_at")).toInstant().toString());
    }
    return ResponseEntity.ok().header("Cache-Control", "no-store").body(body);
  }

  /**
   * Saves the layout over the version the client read (optimistic: another window's save makes this
   * one 409). Every picture or placeholder must belong to this conversation.
   */
  @PutMapping("/api/v1/conversations/{id}/canvas")
  ResponseEntity<JsonNode> saveCanvas(@PathVariable String id, HttpServletRequest request) {
    String actor = actor(request);
    var body = HttpInput.json(request, 262144);
    Json.validate("canvas-layout", body);
    owned(actor, id);
    var layout = body.get("layout");
    var ids = new HashSet<String>();
    for (var item : layout.get("items"))
      if (!ids.add(item.get("id").asText())) throw new Problem(400, "INVALID_CONTRACT");
    var pictures =
        new HashSet<>(
            jdbc.queryForList(
                "SELECT a.id FROM artifacts a JOIN generation_tasks t ON t.id=a.task_id WHERE t.conversation_id=? AND a.kind='COMPOSITE'",
                String.class,
                id));
    var messages =
        new HashSet<>(
            jdbc.queryForList(
                "SELECT id FROM generation_tasks WHERE conversation_id=?", String.class, id));
    for (var item : layout.get("items")) {
      if (item.has("artifact_id") && !pictures.contains(item.get("artifact_id").asText()))
        throw new Problem(400, "INVALID_CANVAS");
      if (item.has("task_id") && !messages.contains(item.get("task_id").asText()))
        throw new Problem(400, "INVALID_CANVAS");
    }
    // Pictures from the library (ADR-20261010-W): any original of the conversation's project.
    var originals =
        new HashSet<>(
            jdbc.queryForList(
                "SELECT a.id FROM assets a JOIN conversations c ON c.project_id=a.project_id WHERE c.id=? AND a.kind IN ('PRODUCT','GIFT','REFERENCE')",
                String.class,
                id));
    for (var item : layout.get("items"))
      if (item.has("asset_id") && !originals.contains(item.get("asset_id").asText()))
        throw new Problem(400, "INVALID_CANVAS");
    for (var removed : layout.get("removed"))
      if (!pictures.contains(removed.asText()) && !messages.contains(removed.asText()))
        throw new Problem(400, "INVALID_CANVAS");
    int version = body.get("version").intValue();
    int saved =
        version == 0
            ? jdbc.update(
                "INSERT INTO conversation_canvases(conversation_id,layout,version) VALUES (?,?::jsonb,1) ON CONFLICT (conversation_id) DO NOTHING",
                id,
                layout.toString())
            : jdbc.update(
                "UPDATE conversation_canvases SET layout=?::jsonb,version=version+1,updated_at=now() WHERE conversation_id=? AND version=?",
                layout.toString(),
                id,
                version);
    if (saved != 1) throw new Problem(409, "CANVAS_CONFLICT");
    var row =
        jdbc.queryForMap(
            "SELECT version,updated_at FROM conversation_canvases WHERE conversation_id=?", id);
    return ResponseEntity.ok()
        .header("Cache-Control", "no-store")
        .body(
            Json.object()
                .put("version", ((Number) row.get("version")).intValue())
                .put("updated_at", ((Timestamp) row.get("updated_at")).toInstant().toString()));
  }

  @DeleteMapping("/api/v1/conversations/{id}")
  ResponseEntity<Void> delete(@PathVariable String id, HttpServletRequest request) {
    String actor = actor(request);
    owned(actor, id);
    // Images stay in "my works" and the task history; only the grouping goes.
    jdbc.update("DELETE FROM conversations WHERE id=?", id);
    return ResponseEntity.noContent().build();
  }
}
