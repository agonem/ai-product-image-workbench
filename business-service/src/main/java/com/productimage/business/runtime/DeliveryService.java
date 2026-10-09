package com.productimage.business.runtime;

import com.fasterxml.jackson.databind.JsonNode;
import com.productimage.workbench.contract.RequestFingerprint;
import java.util.HashSet;
import java.util.Map;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.transaction.support.TransactionTemplate;

public final class DeliveryService {
  private final JdbcTemplate jdbc;
  private final TransactionTemplate tx;
  private final LocalObjectStore store;
  private final RuntimeSettings settings;
  private final ProviderConfigService configs;

  DeliveryService(
      JdbcTemplate jdbc,
      TransactionTemplate tx,
      LocalObjectStore store,
      RuntimeSettings settings,
      ProviderConfigService configs) {
    this.jdbc = jdbc;
    this.tx = tx;
    this.store = store;
    this.settings = settings;
    this.configs = configs;
  }

  @Scheduled(fixedDelayString = "${WORK_SWEEP_MILLIS:1000}")
  public void reap() {
    tx.executeWithoutResult(
        status -> {
          var rows =
              jdbc.queryForList(
                  "SELECT o.* FROM outbox_events o JOIN generation_tasks t ON t.current_attempt_id=o.attempt_id WHERE o.completed_at IS NULL AND o.lease_until<=now() AND o.publish_attempts>=? AND t.status IN ('QUEUED','RUNNING') FOR UPDATE OF o SKIP LOCKED",
                  settings.maxDeliveries());
          for (var row : rows) {
            fail(row, "GENERATION_FAILED", true);
            finish(row);
            audit(row, "LEASE_EXHAUSTED");
          }
        });
  }

  public JsonNode claim() {
    reap();
    return tx.execute(
        status -> {
          var rows =
              jdbc.queryForList(
                  "SELECT o.*,t.provider_config_version,t.text_config_version FROM outbox_events o JOIN generation_tasks t ON t.current_attempt_id=o.attempt_id WHERE o.completed_at IS NULL AND o.available_at<=now() AND (o.lease_until IS NULL OR o.lease_until<=now()) AND o.publish_attempts<? AND t.status IN ('QUEUED','RUNNING') ORDER BY o.created_at,o.id FOR UPDATE OF o SKIP LOCKED LIMIT 1",
                  settings.maxDeliveries());
          if (rows.isEmpty()) return null;
          var row = rows.getFirst();
          // A frozen binding must be deliverable or the attempt fails visibly; silently
          // dropping it would switch the task to worker environment credentials.
          JsonNode providerConfig = null, textConfig = null;
          if (row.get("provider_config_version") != null
              || row.get("text_config_version") != null) {
            try {
              if (row.get("provider_config_version") != null)
                providerConfig = configs.claimConfig(row.get("provider_config_version").toString());
              if (row.get("text_config_version") != null)
                textConfig = configs.claimConfig(row.get("text_config_version").toString());
            } catch (Problem ex) {
              fail(row, "PROVIDER_UNAVAILABLE", true);
              finish(row);
              audit(row, "PROVIDER_CONFIG_UNAVAILABLE");
              return null;
            }
          }
          String lease = Json.id();
          int delivery = ((Number) row.get("publish_attempts")).intValue() + 1;
          jdbc.update(
              "UPDATE outbox_events SET lease_token=?,lease_until=now()+(? * interval '1 second'),available_at=now()+(? * interval '1 second'),publish_attempts=publish_attempts+1,published_at=coalesce(published_at,now()) WHERE id=?",
              lease,
              settings.leaseSeconds(),
              settings.leaseSeconds() + settings.backoffSeconds() * delivery,
              row.get("id"));
          jdbc.update(
              "UPDATE task_attempts SET status='RUNNING',started_at=coalesce(started_at,now()) WHERE id=?",
              row.get("attempt_id"));
          jdbc.update(
              "UPDATE generation_tasks SET status='RUNNING' WHERE id=?", row.get("task_id"));
          var result =
              Json.object().put("lease_token", lease).put("lease_seconds", settings.leaseSeconds());
          result.set("request", Json.parse(row.get("payload").toString()));
          if (providerConfig != null) result.set("provider_config", providerConfig);
          if (textConfig != null) result.set("text_provider_config", textConfig);
          return result;
        });
  }

  private Map<String, Object> row(String attempt) {
    var rows =
        jdbc.queryForList(
            "SELECT o.*,o.lease_until>now() AS live,t.current_attempt_id,t.status AS task_status FROM outbox_events o JOIN generation_tasks t ON t.id=o.task_id WHERE o.attempt_id=? FOR UPDATE OF o",
            attempt);
    if (rows.isEmpty()) throw new Problem(404, "NOT_FOUND");
    return rows.getFirst();
  }

  private boolean live(Map<String, Object> row, String token) {
    return token != null
        && token.equals(row.get("lease_token"))
        && Boolean.TRUE.equals(row.get("live"))
        && row.get("completed_at") == null
        && row.get("attempt_id").equals(row.get("current_attempt_id"));
  }

  private void requireLease(Map<String, Object> row, String token) {
    if (!live(row, token)) throw new Problem(410, "LEASE_EXPIRED");
  }

  public void heartbeat(String attempt, String token) {
    tx.executeWithoutResult(
        status -> {
          var row = row(attempt);
          requireLease(row, token);
          jdbc.update(
              "UPDATE outbox_events SET lease_until=now()+(? * interval '1 second'),available_at=now()+(? * interval '1 second') WHERE id=?",
              settings.leaseSeconds(),
              settings.leaseSeconds()
                  + settings.backoffSeconds() * ((Number) row.get("publish_attempts")).intValue(),
              row.get("id"));
        });
  }

  public void generationCall(String attempt, String token, int ordinal) {
    tx.executeWithoutResult(
        status -> {
          var row = row(attempt);
          requireLease(row, token);
          var request = Json.parse(row.get("payload").toString());
          int version = request.path("schema_version").asInt();
          int count = request.path("output").path("count").asInt();
          // Images 0..count-1 call the model unless the picture is kept; a white gift card's
          // own call (the gift re-shot on white, ADR-20261009-N) is ordinal count.
          boolean image =
              !request.path("keep_original").asBoolean() && ordinal >= 0 && ordinal < count;
          boolean gift = request.path("gift_reshoot").asBoolean() && ordinal == count;
          if (version != 4 || request.has("base_image") || !(image || gift))
            throw new Problem(400, "INVALID_CONTRACT");
          if (jdbc.update(
                  "INSERT INTO generation_call_fences(attempt_id,ordinal) VALUES (?,?) ON CONFLICT DO NOTHING",
                  attempt,
                  ordinal)
              != 1) throw new Problem(409, "TASK_CONFLICT");
        });
  }

  public byte[] asset(String attempt, String token, String assetId) {
    return tx.execute(
        status -> {
          var row = row(attempt);
          requireLease(row, token);
          var request = Json.parse(row.get("payload").toString());
          // Only references frozen into this attempt's snapshot are readable.
          var frozen = new java.util.ArrayList<JsonNode>();
          for (String field :
              new String[] {
                "product_asset", "product_alpha_asset", "gift_asset", "base_image", "edit_image"
              }) frozen.add(request.path(field));
          request.path("references").forEach(frozen::add);
          for (var asset : frozen) {
            if (asset.path("asset_id").asText().equals(assetId)) {
              byte[] bytes = store.read(asset.path("object_key").asText());
              if (!Json.hash(bytes).equals(asset.path("sha256").asText()))
                throw new Problem(422, "INVALID_ASSET");
              return bytes;
            }
          }
          throw new Problem(404, "NOT_FOUND");
        });
  }

  public JsonNode output(String attempt, String token, int ordinal, byte[] bytes) {
    if (ordinal < 0 || ordinal > 10000) throw new Problem(400, "INVALID_CONTRACT");
    return tx.execute(
        status -> {
          var row = row(attempt);
          requireLease(row, token);
          String key = prefix(row, token) + ordinal + ".image";
          var info = store.put(key, bytes);
          return Json.object()
              .put("object_key", key)
              .put("sha256", info.sha256())
              .put("width", info.width())
              .put("height", info.height());
        });
  }

  private String prefix(Map<String, Object> row, String token) {
    return Json.parse(row.get("payload").toString()).path("output_object_prefix").asText()
        + token
        + "/";
  }

  public JsonNode receipt(String attempt, String token, String raw) {
    JsonNode receipt = Json.parse(raw);
    String type = receipt.path("event_type").asText();
    // Scene v2/v3 were replaced by v4: legacy attempts may still report failure, never success.
    if (!type.matches("image\\.task\\.(completed\\.v[14]|failed\\.v[1234])")) {
      throw new Problem(400, "INVALID_CONTRACT");
    }
    boolean completed = type.contains(".completed.");
    boolean scene = !type.endsWith(".v1");
    boolean generation = type.endsWith(".v4");
    Json.validate(
        (generation
                ? "generation-v4-"
                : type.endsWith(".v3") ? "scene-v3-" : scene ? "scene-" : "task-")
            + (completed ? "completed" : "failed"),
        receipt);
    String hash = RequestFingerprint.sha256(raw);
    return tx.execute(
        status -> {
          var row = row(attempt);
          var workerRequest = Json.parse(row.get("payload").toString());
          if (workerRequest.path("schema_version").asInt()
              != receipt.path("schema_version").asInt()) throw new Problem(409, "TASK_CONFLICT");
          String task = row.get("task_id").toString();
          if (!attempt.equals(receipt.path("attempt_id").asText())
              || !task.equals(receipt.path("task_id").asText())
              || !task.equals(receipt.path("correlation_id").asText()))
            throw new Problem(409, "TASK_CONFLICT");
          var duplicates =
              jdbc.queryForList(
                  "SELECT * FROM worker_receipts WHERE event_id=?",
                  receipt.path("event_id").asText());
          if (!duplicates.isEmpty()) {
            var previous = duplicates.getFirst();
            if (!previous.get("event_id").equals(receipt.path("event_id").asText())
                || !previous.get("payload_sha256").equals(hash)
                || token == null
                || !token.equals(previous.get("lease_token")))
              throw new Problem(409, "TASK_CONFLICT");
            return Json.object().put("disposition", previous.get("disposition").toString());
          }
          if (!live(row, token)) {
            if (token != null
                && token.equals(row.get("lease_token"))
                && row.get("attempt_id").equals(row.get("current_attempt_id"))
                && jdbc.queryForObject(
                        "SELECT count(*) FROM worker_receipts WHERE attempt_id=?",
                        Long.class,
                        attempt)
                    > 0) {
              throw new Problem(409, "TASK_CONFLICT");
            }
            audit(row, "STALE_RECEIPT_IGNORED");
            return Json.object().put("disposition", "IGNORED");
          }
          // Lock the task before validating/registering all outputs and changing its state.
          jdbc.queryForMap("SELECT id FROM generation_tasks WHERE id=? FOR UPDATE", task);
          String disposition = "APPLIED";
          if (completed) {
            try {
              if (generation)
                GenerationOutputs.validate(store, prefix(row, token), workerRequest, receipt);
              else validateArtifacts(row, token, receipt);
            } catch (Problem ex) {
              if (ex.status == 503) throw ex;
              disposition = "REJECTED";
            }
            if (disposition.equals("APPLIED")) {
              var registered = new java.util.ArrayList<JsonNode>();
              receipt.path("artifacts").forEach(registered::add);
              // v4 model outputs are registered too so text can be re-rendered later without
              // another model call; task results still list only COMPOSITE images.
              if (generation)
                receipt.path("generations").forEach(item -> registered.add(item.path("base")));
              for (var artifact : registered) {
                jdbc.update(
                    "INSERT INTO artifacts(id,task_id,attempt_id,ordinal,kind,object_key,sha256,width,height) VALUES (?,?,?,?,?,?,?,?,?)",
                    Json.id(),
                    task,
                    attempt,
                    artifact.path("ordinal").intValue(),
                    artifact.path("kind").asText(),
                    artifact.path("object_key").asText(),
                    artifact.path("sha256").asText(),
                    artifact.path("width").intValue(),
                    artifact.path("height").intValue());
              }
              jdbc.update(
                  "UPDATE task_attempts SET status='SUCCEEDED',ended_at=now(),provider_info=?::jsonb WHERE id=?",
                  generation
                      ? Json.object().set("generations", receipt.path("generations")).toString()
                      : receipt.path("background_generation").isNull()
                          ? null
                          : receipt.path("background_generation").toString(),
                  attempt);
              jdbc.update("UPDATE generation_tasks SET status='SUCCEEDED' WHERE id=?", task);
            } else fail(row, "OUTPUT_VALIDATION_FAILED", true);
          } else
            fail(
                row,
                receipt.path("error").path("code").asText(),
                receipt.path("error").path("retryable").asBoolean(),
                receipt.path("error").path("safe_message").asText());
          jdbc.update(
              "INSERT INTO worker_receipts(event_id,task_id,attempt_id,event_type,payload_sha256,payload,lease_token,disposition,processed_at) VALUES (?,?,?,?,?,?::jsonb,?,?,now())",
              receipt.path("event_id").asText(),
              task,
              attempt,
              type,
              hash,
              receipt.toString(),
              token,
              disposition);
          finish(row);
          return Json.object().put("disposition", disposition);
        });
  }

  private void validateArtifacts(Map<String, Object> row, String token, JsonNode receipt) {
    var ordinals = new HashSet<Integer>();
    var keys = new HashSet<String>();
    for (var artifact : receipt.path("artifacts")) {
      if (!artifact.path("ordinal").canConvertToInt()
          || !artifact.path("width").canConvertToInt()
          || !artifact.path("height").canConvertToInt())
        throw new Problem(422, "OUTPUT_VALIDATION_FAILED");
      int ordinal = artifact.path("ordinal").intValue();
      String key = artifact.path("object_key").asText();
      if (!ordinals.add(ordinal)
          || !keys.add(key)
          || !key.equals(prefix(row, token) + ordinal + ".image")) {
        throw new Problem(422, "OUTPUT_VALIDATION_FAILED");
      }
      var info = store.inspect(key, store.read(key));
      if (!info.sha256().equals(artifact.path("sha256").asText())
          || info.width() != artifact.path("width").intValue()
          || info.height() != artifact.path("height").intValue())
        throw new Problem(422, "OUTPUT_VALIDATION_FAILED");
    }
    var background = receipt.path("background_generation");
    if (!background.isNull() && !keys.contains(background.path("output_object_key").asText())) {
      throw new Problem(422, "OUTPUT_VALIDATION_FAILED");
    }
  }

  private void fail(Map<String, Object> row, String code, boolean retryable) {
    fail(row, code, retryable, "");
  }

  /** The Worker's allowlisted diagnosis (e.g. PROVIDER_HTTP_404) refines the message. */
  private void fail(Map<String, Object> row, String code, boolean retryable, String diagnosis) {
    jdbc.update(
        "UPDATE task_attempts SET status='FAILED',started_at=coalesce(started_at,now()),ended_at=now(),error_code=?,safe_message=?,retryable=? WHERE id=?",
        code,
        TaskService.safeMessage(code, diagnosis),
        retryable,
        row.get("attempt_id"));
    jdbc.update(
        "UPDATE generation_tasks SET status='FAILED' WHERE id=? AND current_attempt_id=?",
        row.get("task_id"),
        row.get("attempt_id"));
  }

  private void finish(Map<String, Object> row) {
    jdbc.update("UPDATE outbox_events SET completed_at=now() WHERE id=?", row.get("id"));
  }

  private void audit(Map<String, Object> row, String action) {
    jdbc.update(
        "INSERT INTO audit_events(id,action,resource_id,correlation_id) VALUES (?,?,?,?)",
        Json.id(),
        action,
        row.get("attempt_id"),
        row.get("task_id"));
  }
}
