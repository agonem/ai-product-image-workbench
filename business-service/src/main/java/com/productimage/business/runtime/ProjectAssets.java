package com.productimage.business.runtime;

import com.fasterxml.jackson.databind.JsonNode;
import java.util.Map;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.transaction.support.TransactionTemplate;

public final class ProjectAssets {
  private final JdbcTemplate jdbc;
  private final TransactionTemplate tx;
  private final ProjectAccess access;
  private final LocalObjectStore store;
  private final RuntimeSettings settings;

  ProjectAssets(
      JdbcTemplate jdbc,
      TransactionTemplate tx,
      ProjectAccess access,
      LocalObjectStore store,
      RuntimeSettings settings) {
    this.jdbc = jdbc;
    this.tx = tx;
    this.access = access;
    this.store = store;
    this.settings = settings;
  }

  JsonNode create(String actor, JsonNode body) {
    if (!body.isObject() || body.size() != 1 || !body.path("name").isTextual())
      throw new Problem(400, "INVALID_CONTRACT");
    String name = body.path("name").asText().strip();
    if (name.isEmpty()
        || name.length() > 120
        || name.codePoints().anyMatch(Character::isISOControl))
      throw new Problem(400, "INVALID_CONTRACT");
    return tx.execute(
        status -> {
          access.active(actor);
          String id = Json.id();
          jdbc.update("INSERT INTO projects(id,owner_id,name) VALUES (?,?,?)", id, actor, name);
          audit(actor, "PROJECT_CREATED", id);
          return Json.object().put("id", id).put("name", name);
        });
  }

  JsonNode list(String actor) {
    access.active(actor);
    var result = Json.MAPPER.createArrayNode();
    for (var row :
        jdbc.queryForList(
            "SELECT id,name FROM projects WHERE owner_id=? ORDER BY created_at DESC,id DESC LIMIT 100",
            actor)) {
      result.add(
          Json.object()
              .put("id", row.get("id").toString())
              .put("name", row.get("name").toString()));
    }
    return result;
  }

  JsonNode project(String actor, String id) {
    access.require(actor, id);
    var row = jdbc.queryForMap("SELECT name FROM projects WHERE id=?", id);
    return Json.object().put("id", id).put("name", row.get("name").toString());
  }

  void authorizeUpload(String actor, String project, String kind) {
    access.require(actor, project);
    if (!"PRODUCT".equals(kind) && !"GIFT".equals(kind)) throw new Problem(400, "INVALID_ASSET");
  }

  JsonNode upload(String actor, String project, String kind, String mime, byte[] data) {
    authorizeUpload(actor, project, kind);
    UploadValidation.validate(data, mime, settings.maxBytes(), settings.maxPixels());
    String id = Json.id(), key = "originals/" + project + "/" + id + ".image";
    var info = store.put(key, data);
    return tx.execute(
        status -> {
          access.require(actor, project);
          jdbc.update(
              "INSERT INTO assets(id,project_id,kind,object_key,sha256,width,height) VALUES (?,?,?,?,?,?,?)",
              id,
              project,
              kind,
              key,
              info.sha256(),
              info.width(),
              info.height());
          audit(actor, "ASSET_UPLOADED", id);
          return asset(actor, id);
        });
  }

  private Map<String, Object> owned(String actor, String id) {
    var rows =
        jdbc.queryForList(
            "SELECT a.* FROM assets a JOIN projects p ON p.id=a.project_id JOIN users u ON u.id=p.owner_id WHERE a.id=? AND p.owner_id=? AND u.status='ACTIVE'",
            id,
            actor);
    if (rows.isEmpty()) throw new Problem(404, "NOT_FOUND");
    return rows.getFirst();
  }

  JsonNode asset(String actor, String id) {
    var row = owned(actor, id);
    return Json.object()
        .put("id", id)
        .put("project_id", row.get("project_id").toString())
        .put("kind", row.get("kind").toString())
        .put("sha256", row.get("sha256").toString())
        .put("width", ((Number) row.get("width")).intValue())
        .put("height", ((Number) row.get("height")).intValue())
        .put("review_status", row.get("review_status").toString())
        .put("content_url", "/api/v1/assets/" + id + "/content");
  }

  byte[] content(String actor, String id) {
    var row = owned(actor, id);
    byte[] bytes = store.read(row.get("object_key").toString());
    if (!Json.hash(bytes).equals(row.get("sha256"))) throw new Problem(422, "INVALID_ASSET");
    return bytes;
  }

  private void audit(String actor, String action, String id) {
    jdbc.update(
        "INSERT INTO audit_events(id,actor_id,action,resource_id,correlation_id) VALUES (?,?,?,?,?)",
        Json.id(),
        actor,
        action,
        id,
        id);
  }
}
