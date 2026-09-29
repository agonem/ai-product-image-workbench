package com.productimage.business.runtime;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.node.ObjectNode;
import com.productimage.workbench.contract.RequestFingerprint;
import java.sql.Timestamp;
import java.util.Map;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.transaction.support.TransactionTemplate;

public final class TaskService {
  private final JdbcTemplate jdbc;
  private final TransactionTemplate tx;
  private final SnapshotBuilder snapshots;
  private final LocalObjectStore store;
  private final RuntimeSettings settings;
  private final ProviderConfigService configs;

  TaskService(
      JdbcTemplate jdbc,
      TransactionTemplate tx,
      SnapshotBuilder snapshots,
      LocalObjectStore store,
      RuntimeSettings settings,
      ProviderConfigService configs) {
    this.jdbc = jdbc;
    this.tx = tx;
    this.snapshots = snapshots;
    this.store = store;
    this.settings = settings;
    this.configs = configs;
  }

  private void authorizeProject(String actor, String project) {
    if (jdbc.queryForObject(
            "SELECT count(*) FROM projects p JOIN users u ON u.id=p.owner_id WHERE p.id=? AND u.id=? AND u.status='ACTIVE'",
            Long.class,
            project,
            actor)
        != 1) throw new Problem(404, "NOT_FOUND");
  }

  public JsonNode create(String actor, String key, String raw) {
    return create(actor, key, raw, "task-create");
  }

  /** v4 whole-image generation for all three entries (ADR-20260929). */
  public JsonNode createGeneration(String actor, String key, String raw) {
    return create(actor, key, raw, "generation-v4-create");
  }

  /**
   * Re-render only the text of one successful v4 image from its stored model output. No model call
   * and no provider binding; the source task stays unchanged.
   */
  public JsonNode retypeset(String actor, String key, String sourceId, String raw) {
    JsonNode body = Json.parse(raw);
    Json.validate("generation-v4-retypeset", body);
    var row = owned(actor, sourceId, false);
    var source = Json.parse(row.get("worker_snapshot_json").toString());
    int ordinal = body.path("ordinal").asInt();
    int count = source.path("output").path("count").asInt();
    if (source.path("schema_version").asInt() != 4
        || !"SUCCEEDED".equals(row.get("status"))
        || ordinal >= count) throw new Problem(409, "TASK_CONFLICT");
    var bases =
        jdbc.queryForList(
            "SELECT id,object_key,sha256 FROM artifacts WHERE task_id=? AND attempt_id=? AND ordinal=? AND kind='BACKGROUND' AND NOT EXISTS (SELECT 1 FROM deletions d WHERE d.target_id=artifacts.id)",
            sourceId,
            row.get("current_attempt_id"),
            count + ordinal);
    if (bases.isEmpty()) throw new Problem(409, "TASK_CONFLICT");
    var base =
        Json.object()
            .put("asset_id", bases.getFirst().get("id").toString())
            .put("object_key", bases.getFirst().get("object_key").toString())
            .put("sha256", bases.getFirst().get("sha256").toString());
    var request =
        Json.object()
            .put("project_id", row.get("project_id").toString())
            .put("product_asset_id", row.get("product_asset_id").toString())
            .put("feature_type", row.get("feature_type").toString())
            .put("source_task_id", sourceId)
            .put("ordinal", ordinal);
    if (row.get("gift_asset_id") != null)
      request.put("gift_asset_id", row.get("gift_asset_id").toString());
    request.set("text", body.get("text"));
    return insert(
        actor,
        key,
        request,
        RequestFingerprint.sha256(request.toString()),
        () -> snapshots.buildRetypeset(source, sourceId, ordinal, base, body.get("text")));
  }

  private JsonNode create(String actor, String key, String raw, String contract) {
    JsonNode request = Json.parse(raw);
    Json.validate(contract, request);
    return insert(
        actor,
        key,
        request,
        RequestFingerprint.sha256(raw),
        () ->
            contract.startsWith("generation")
                ? snapshots.buildGeneration(request)
                : snapshots.build(request));
  }

  private JsonNode insert(
      String actor,
      String key,
      JsonNode request,
      String hash,
      java.util.function.Supplier<ObjectNode> build) {
    Json.validate("idempotency-key", Json.MAPPER.getNodeFactory().textNode(key == null ? "" : key));
    return tx.execute(
        status -> {
          authorizeProject(actor, request.path("project_id").asText());
          var existing =
              jdbc.queryForList(
                  "SELECT id,request_sha256 FROM generation_tasks WHERE created_by=? AND feature_type=? AND idempotency_key=?",
                  actor,
                  request.path("feature_type").asText(),
                  key);
          if (!existing.isEmpty()) return existing(actor, existing.getFirst(), hash);
          ObjectNode worker = build.get();
          // Model tasks freeze the admin binding (or reject when an admin actively disabled
          // it); retries reuse the frozen column. Text-only re-renders call no model.
          String configVersion =
              worker.path("schema_version").asInt() >= 2 && !worker.has("base_image")
                  ? configs.sceneBinding()
                  : null;
          String id = Json.id();
          int inserted =
              jdbc.update(
                  "INSERT INTO generation_tasks(id,project_id,product_asset_id,gift_asset_id,feature_type,created_by,idempotency_key,request_sha256,request_snapshot_json,template_snapshot_json,worker_snapshot_json,provider_config_version) VALUES (?,?,?,?,?,?,?,?,?::jsonb,?::jsonb,?::jsonb,?) ON CONFLICT(created_by,feature_type,idempotency_key) DO NOTHING",
                  id,
                  request.path("project_id").asText(),
                  request.path("product_asset_id").asText(),
                  request.has("gift_asset_id") ? request.get("gift_asset_id").asText() : null,
                  request.path("feature_type").asText(),
                  actor,
                  key,
                  hash,
                  request.toString(),
                  worker.get("template_snapshot").toString(),
                  worker.toString(),
                  configVersion);
          if (inserted == 0)
            return existing(
                actor,
                jdbc.queryForMap(
                    "SELECT id,request_sha256 FROM generation_tasks WHERE created_by=? AND feature_type=? AND idempotency_key=?",
                    actor,
                    request.path("feature_type").asText(),
                    key),
                hash);
          enqueue(id, 1, worker);
          return get(actor, id);
        });
  }

  private JsonNode existing(String actor, Map<String, Object> row, String hash) {
    if (!hash.equals(row.get("request_sha256"))) throw new Problem(409, "TASK_CONFLICT");
    return get(actor, row.get("id").toString());
  }

  private void enqueue(String task, int number, JsonNode snapshot) {
    String attempt = Json.id(), event = Json.id();
    jdbc.update(
        "INSERT INTO task_attempts(id,task_id,attempt_no) VALUES (?,?,?)", attempt, task, number);
    ObjectNode payload = snapshot.deepCopy();
    int version = snapshot.path("schema_version").asInt(1);
    String type = "image.task.requested.v" + version;
    payload
        .put("schema_version", version)
        .put("event_type", type)
        .put("event_id", event)
        .put("task_id", task)
        .put("attempt_id", attempt)
        .put("correlation_id", task)
        .put("output_object_prefix", "outputs/" + task + "/" + attempt + "/");
    Json.validate(
        version == 4
            ? "generation-v4-request"
            : version == 3 ? "scene-v3-request" : version == 2 ? "scene-request" : "task-request",
        payload);
    jdbc.update(
        "INSERT INTO outbox_events(id,task_id,attempt_id,event_type,payload) VALUES (?,?,?,?,?::jsonb)",
        event,
        task,
        attempt,
        type,
        payload.toString());
    jdbc.update(
        "UPDATE generation_tasks SET current_attempt_id=?,status='QUEUED' WHERE id=?",
        attempt,
        task);
  }

  private Map<String, Object> owned(String actor, String id, boolean lock) {
    if (lock) {
      var locked =
          jdbc.queryForList(
              "SELECT t.id FROM generation_tasks t JOIN projects p ON p.id=t.project_id JOIN users u ON u.id=p.owner_id WHERE t.id=? AND p.owner_id=? AND u.status='ACTIVE' FOR UPDATE OF t",
              id,
              actor);
      if (locked.isEmpty()) throw new Problem(404, "NOT_FOUND");
    }
    // A fresh READ COMMITTED statement sees the attempt installed by the previous lock holder.
    var rows =
        jdbc.queryForList(
            "SELECT t.*,a.attempt_no,a.error_code,a.retryable FROM generation_tasks t JOIN projects p ON p.id=t.project_id JOIN users u ON u.id=p.owner_id JOIN task_attempts a ON a.id=t.current_attempt_id WHERE t.id=? AND p.owner_id=? AND u.status='ACTIVE'",
            id,
            actor);
    if (rows.isEmpty()) throw new Problem(404, "NOT_FOUND");
    return rows.getFirst();
  }

  public JsonNode get(String actor, String id) {
    var row = owned(actor, id, false);
    var result =
        Json.object()
            .put("id", id)
            .put("feature_type", row.get("feature_type").toString())
            .put("status", row.get("status").toString())
            .put("attempt", ((Number) row.get("attempt_no")).intValue())
            .put("created_at", ((Timestamp) row.get("created_at")).toInstant().toString());
    var artifacts = result.putArray("artifacts");
    if (row.get("status").equals("SUCCEEDED")) {
      for (var artifact :
          jdbc.queryForList(
              "SELECT id,kind,width,height FROM artifacts WHERE task_id=? AND attempt_id=? AND kind='COMPOSITE' AND NOT EXISTS (SELECT 1 FROM deletions d WHERE d.target_id=artifacts.id) ORDER BY ordinal",
              id,
              row.get("current_attempt_id"))) {
        artifacts.add(
            Json.object()
                .put("id", artifact.get("id").toString())
                .put("kind", artifact.get("kind").toString())
                .put("width", ((Number) artifact.get("width")).intValue())
                .put("height", ((Number) artifact.get("height")).intValue()));
      }
    }
    if (row.get("status").equals("FAILED")) {
      String code = row.get("error_code").toString();
      result
          .putObject("error")
          .put("code", code)
          .put("message", safeMessage(code))
          .put("correlation_id", id);
    } else result.putNull("error");
    Json.validate("task-response", result);
    return result;
  }

  /** v4 task with its frozen output and the submitted inputs; results await human review. */
  public JsonNode getGeneration(String actor, String id) {
    var row = owned(actor, id, false);
    var snapshot = Json.parse(row.get("worker_snapshot_json").toString());
    if (snapshot.path("schema_version").asInt() != 4) throw new Problem(404, "NOT_FOUND");
    ObjectNode result = (ObjectNode) get(actor, id);
    result.set("output", snapshot.get("output"));
    result.set("request", Json.parse(row.get("request_snapshot_json").toString()));
    if (snapshot.has("source")) result.set("source", snapshot.get("source"));
    // Model outputs without text, so the page can preview text edits before a re-typeset.
    var bases = result.putArray("bases");
    if ("SUCCEEDED".equals(row.get("status")))
      for (var base :
          jdbc.queryForList(
              "SELECT id,width,height FROM artifacts WHERE task_id=? AND attempt_id=? AND kind='BACKGROUND' AND NOT EXISTS (SELECT 1 FROM deletions d WHERE d.target_id=artifacts.id) ORDER BY ordinal",
              id,
              row.get("current_attempt_id")))
        bases.add(
            Json.object()
                .put("id", base.get("id").toString())
                .put("width", ((Number) base.get("width")).intValue())
                .put("height", ((Number) base.get("height")).intValue()));
    result.put("review_status", "PENDING");
    return result;
  }

  public JsonNode retry(String actor, String id, int expected) {
    return tx.execute(
        status -> {
          var row = owned(actor, id, true);
          int current = ((Number) row.get("attempt_no")).intValue();
          if (current == expected + 1) return get(actor, id);
          if (current != expected
              || !row.get("status").equals("FAILED")
              || !Boolean.TRUE.equals(row.get("retryable"))
              || current >= settings.maxAttempts()) {
            throw new Problem(409, "TASK_CONFLICT");
          }
          if (row.get("worker_snapshot_json") == null) throw new Problem(409, "INVALID_CONTRACT");
          var snapshot = Json.parse(row.get("worker_snapshot_json").toString());
          // Scene v2/v3 were replaced by v4; a legacy task stays readable but is not re-run.
          int version = snapshot.path("schema_version").asInt(1);
          if (version == 2 || version == 3) throw new Problem(409, "TASK_CONFLICT");
          // A deleted original (or stored model output) cannot be sent again.
          for (String input :
              new String[] {
                String.valueOf(row.get("product_asset_id")),
                String.valueOf(row.get("gift_asset_id")),
                snapshot.path("base_image").path("asset_id").asText()
              })
            if (jdbc.queryForObject(
                    "SELECT count(*) FROM deletions WHERE target_id=?", Long.class, input)
                > 0) throw new Problem(409, "ASSET_DELETED");
          enqueue(id, current + 1, snapshot);
          return get(actor, id);
        });
  }

  /**
   * The owner deletes one generated result (D-08) together with the model output behind it, so the
   * image is really gone and can no longer be re-typeset. Rows stay for history and audit.
   */
  public void deleteArtifact(String actor, String id) {
    java.util.List<String> keys =
        tx.execute(
            status -> {
              var rows =
                  jdbc.queryForList(
                      "SELECT a.attempt_id,a.ordinal FROM artifacts a JOIN generation_tasks t ON t.id=a.task_id JOIN projects p ON p.id=t.project_id JOIN users u ON u.id=p.owner_id WHERE a.id=? AND a.kind='COMPOSITE' AND p.owner_id=? AND u.status='ACTIVE' AND NOT EXISTS (SELECT 1 FROM deletions d WHERE d.target_id=a.id) FOR UPDATE OF t",
                      id,
                      actor);
              if (rows.isEmpty()) throw new Problem(404, "NOT_FOUND");
              Object attempt = rows.getFirst().get("attempt_id");
              int count =
                  jdbc.queryForObject(
                      "SELECT count(*) FROM artifacts WHERE attempt_id=? AND kind='COMPOSITE'",
                      Integer.class,
                      attempt);
              var targets =
                  jdbc.queryForList(
                      "SELECT id,object_key FROM artifacts WHERE attempt_id=? AND (id=? OR (kind='BACKGROUND' AND ordinal=?)) AND NOT EXISTS (SELECT 1 FROM deletions d WHERE d.target_id=artifacts.id)",
                      attempt,
                      id,
                      count + ((Number) rows.getFirst().get("ordinal")).intValue());
              var removed = new java.util.ArrayList<String>();
              for (var target : targets) {
                jdbc.update(
                    "INSERT INTO deletions(target_id,target_kind,deleted_by) VALUES (?,'ARTIFACT',?)",
                    target.get("id"),
                    actor);
                jdbc.update(
                    "INSERT INTO audit_events(id,actor_id,action,resource_id,correlation_id) VALUES (?,?,?,?,?)",
                    Json.id(),
                    actor,
                    "ARTIFACT_DELETED",
                    target.get("id"),
                    id);
                removed.add(target.get("object_key").toString());
              }
              return removed;
            });
    keys.forEach(store::delete);
  }

  public byte[] content(String actor, String id) {
    var rows =
        jdbc.queryForList(
            "SELECT a.object_key,a.sha256 FROM artifacts a JOIN generation_tasks t ON t.id=a.task_id JOIN projects p ON p.id=t.project_id JOIN users u ON u.id=p.owner_id WHERE a.id=? AND p.owner_id=? AND u.status='ACTIVE' AND NOT EXISTS (SELECT 1 FROM deletions d WHERE d.target_id=a.id)",
            id,
            actor);
    if (rows.isEmpty()) throw new Problem(404, "NOT_FOUND");
    byte[] bytes = store.read(rows.getFirst().get("object_key").toString());
    if (!Json.hash(bytes).equals(rows.getFirst().get("sha256")))
      throw new Problem(422, "OUTPUT_VALIDATION_FAILED");
    return bytes;
  }

  static String safeMessage(String code) {
    return switch (code) {
      case "CUTOUT_REVIEW_REQUIRED" -> "请先审核商品边缘";
      case "INVALID_ASSET", "UNAUTHORIZED_ASSET" -> "输入素材不可用";
      case "INVALID_LAYOUT", "TEXT_OVERFLOW" -> "请检查布局或文字";
      case "PROVIDER_UNAVAILABLE" -> "生成服务未配置或暂不可用";
      case "OUTPUT_VALIDATION_FAILED" -> "产物校验失败";
      case "INVALID_CONTRACT" -> "任务协议校验失败";
      case "TASK_CONFLICT" -> "任务请求冲突";
      case "ASSET_DELETED" -> "原图已删除";
      default -> "任务执行失败，请检查配置后重试";
    };
  }
}
