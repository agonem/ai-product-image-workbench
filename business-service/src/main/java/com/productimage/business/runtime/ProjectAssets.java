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

  /** Material categories (ADR-20261009-R): 商品图, 赠品图 and 参考图; any may fill any slot. */
  static final java.util.Set<String> KINDS = java.util.Set.of("PRODUCT", "GIFT", "REFERENCE");

  void authorizeUpload(String actor, String project, String kind) {
    access.require(actor, project);
    if (!KINDS.contains(kind)) throw new Problem(400, "INVALID_ASSET");
  }

  JsonNode upload(String actor, String project, String kind, byte[] data) {
    authorizeUpload(actor, project, kind);
    var checked = UploadValidation.validate(data, settings.maxBytes(), settings.maxPixels());
    String id = Json.id(), key = "originals/" + project + "/" + id + ".image";
    var info = store.putOriginal(key, data, checked.width(), checked.height());
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
            "SELECT a.* FROM assets a JOIN projects p ON p.id=a.project_id JOIN users u ON u.id=p.owner_id WHERE a.id=? AND p.owner_id=? AND u.status='ACTIVE' AND NOT EXISTS (SELECT 1 FROM deletions d WHERE d.target_id=a.id)",
            id,
            actor);
    if (rows.isEmpty()) throw new Problem(404, "NOT_FOUND");
    return rows.getFirst();
  }

  JsonNode asset(String actor, String id) {
    var row = owned(actor, id);
    var result =
        Json.object()
            .put("id", id)
            .put("project_id", row.get("project_id").toString())
            .put("kind", row.get("kind").toString())
            .put("sha256", row.get("sha256").toString())
            .put("width", ((Number) row.get("width")).intValue())
            .put("height", ((Number) row.get("height")).intValue())
            .put("review_status", row.get("review_status").toString())
            .put("content_url", "/api/v1/assets/" + id + "/content");
    if (row.get("source_artifact_id") != null)
      result.put("source_artifact_id", row.get("source_artifact_id").toString());
    return result;
  }

  record Imported(boolean created, JsonNode asset) {}

  /**
   * Reuses one of the owner's generated results as a new original (ADR-20260930-E). The bytes are
   * copied, so deleting the result or the new original never affects the other; asking again for
   * the same result and kind returns the copy that already exists.
   */
  Imported fromArtifact(String actor, String artifact, JsonNode body) {
    if (!body.isObject() || body.size() != 1 || !body.path("kind").isTextual())
      throw new Problem(400, "INVALID_CONTRACT");
    String kind = body.path("kind").asText();
    if (!KINDS.contains(kind)) throw new Problem(400, "INVALID_ASSET");
    var rows =
        jdbc.queryForList(
            "SELECT f.object_key,f.sha256,f.width,f.height,t.project_id FROM artifacts f JOIN generation_tasks t ON t.id=f.task_id JOIN projects p ON p.id=t.project_id JOIN users u ON u.id=p.owner_id WHERE f.id=? AND f.kind='COMPOSITE' AND p.owner_id=? AND u.status='ACTIVE' AND NOT EXISTS (SELECT 1 FROM deletions d WHERE d.target_id=f.id)",
            artifact,
            actor);
    if (rows.isEmpty()) throw new Problem(404, "NOT_FOUND");
    var row = rows.getFirst();
    var existing =
        jdbc.queryForList(
            "SELECT a.id FROM assets a WHERE a.source_artifact_id=? AND a.kind=? AND NOT EXISTS (SELECT 1 FROM deletions d WHERE d.target_id=a.id) ORDER BY a.created_at LIMIT 1",
            artifact,
            kind);
    if (!existing.isEmpty())
      return new Imported(false, asset(actor, existing.getFirst().get("id").toString()));
    byte[] bytes = store.read(row.get("object_key").toString());
    if (!Json.hash(bytes).equals(row.get("sha256"))) throw new Problem(422, "INVALID_ASSET");
    String project = row.get("project_id").toString();
    String id = Json.id(), key = "originals/" + project + "/" + id + ".image";
    var info =
        store.putOriginal(
            key,
            bytes,
            ((Number) row.get("width")).intValue(),
            ((Number) row.get("height")).intValue());
    return tx.execute(
        status -> {
          access.require(actor, project);
          jdbc.update(
              "INSERT INTO assets(id,project_id,kind,object_key,sha256,width,height,source_artifact_id) VALUES (?,?,?,?,?,?,?,?)",
              id,
              project,
              kind,
              key,
              info.sha256(),
              info.width(),
              info.height(),
              artifact);
          audit(actor, "ASSET_FROM_ARTIFACT", id);
          return new Imported(true, asset(actor, id));
        });
  }

  /**
   * The owner deletes an original (D-08). The row stays so history can say what was used; the bytes
   * are removed and every read path hides it. Not while a queued or running task uses it.
   */
  void delete(String actor, String id) {
    delete(actor, id, false);
  }

  /** {@code asAdmin}: an admin deletes anyone's original (ADR-20260930-F), same rules otherwise. */
  void delete(String actor, String id, boolean asAdmin) {
    String key =
        tx.execute(
            status -> {
              var rows =
                  jdbc.queryForList(
                      "SELECT a.object_key FROM assets a JOIN projects p ON p.id=a.project_id JOIN users u ON u.id=p.owner_id WHERE a.id=? AND (?::boolean OR (p.owner_id=? AND u.status='ACTIVE')) AND a.kind IN ('PRODUCT','GIFT','REFERENCE') AND NOT EXISTS (SELECT 1 FROM deletions d WHERE d.target_id=a.id) FOR UPDATE OF a",
                      id,
                      asAdmin,
                      actor);
              if (rows.isEmpty()) throw new Problem(404, "NOT_FOUND");
              if (jdbc.queryForObject(
                      "SELECT count(*) FROM generation_tasks WHERE (product_asset_id=? OR gift_asset_id=? OR worker_snapshot_json->'references' @> jsonb_build_array(jsonb_build_object('asset_id',?::text))) AND status IN ('QUEUED','RUNNING')",
                      Long.class,
                      id,
                      id,
                      id)
                  > 0) throw new Problem(409, "ASSET_IN_USE");
              jdbc.update(
                  "INSERT INTO deletions(target_id,target_kind,deleted_by) VALUES (?,'ASSET',?)",
                  id,
                  actor);
              audit(actor, "ASSET_DELETED", id);
              return rows.getFirst().get("object_key").toString();
            });
    store.delete(key);
  }

  byte[] content(String actor, String id) {
    var row = owned(actor, id);
    byte[] bytes = store.read(row.get("object_key").toString());
    if (!Json.hash(bytes).equals(row.get("sha256"))) throw new Problem(422, "INVALID_ASSET");
    return bytes;
  }

  byte[] approvedAlpha(String actor, String id) {
    var product = owned(actor, id);
    var rows =
        jdbc.queryForList(
            "SELECT id FROM assets WHERE project_id=? AND source_asset_id=? AND kind='ALPHA' AND review_status='APPROVED' ORDER BY created_at DESC,id DESC LIMIT 1",
            product.get("project_id"),
            id);
    if (rows.isEmpty()) throw new Problem(404, "NOT_FOUND");
    return content(actor, rows.getFirst().get("id").toString());
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
