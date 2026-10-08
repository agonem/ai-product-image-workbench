package com.productimage.business.runtime;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.node.ObjectNode;
import java.sql.Timestamp;
import java.util.List;
import java.util.Map;
import org.springframework.jdbc.core.JdbcTemplate;

final class SnapshotBuilder {
  private final JdbcTemplate jdbc;
  private final LocalObjectStore store;
  private final GenerationPolicy generation;

  SnapshotBuilder(JdbcTemplate jdbc, LocalObjectStore store, GenerationPolicy generation) {
    this.jdbc = jdbc;
    this.store = store;
    this.generation = generation;
  }

  /**
   * v4 whole-image generation (ADR-20260929): originals are frozen as reference inputs by hash; no
   * cutout is required. Presets/styles are copied in so retries and history keep the exact prompt.
   */
  ObjectNode buildGeneration(JsonNode request) {
    generation.validate(request);
    // One catalogue version for every id in this request, even if an admin saves meanwhile.
    var presets = generation.presets();
    String project = request.path("project_id").asText();
    String feature = request.path("feature_type").asText();
    var worker = Json.object().put("schema_version", 4).put("feature_type", feature);
    worker.set(
        "product_asset", asset(request.path("product_asset_id").asText(), project, "PRODUCT"));
    if (feature.equals("GIFT")) {
      worker.set("gift_asset", asset(request.path("gift_asset_id").asText(), project, "GIFT"));
      worker.set("gift_position", request.get("gift_position"));
      if (request.has("background")) worker.set("background", request.get("background"));
      // A program-drawn gift card (ADR-20261008-H); on the original background no model is
      // needed at all, so the picture stays exactly as uploaded.
      if (request.has("gift_card")) {
        worker.set("gift_card", request.get("gift_card"));
        if ("ORIGINAL".equals(request.path("background").path("mode").asText()))
          worker.put("keep_original", true);
      }
    } else if (feature.equals("SCENE")) {
      ObjectNode scene;
      if (request.has("scene_preset")) {
        scene = (ObjectNode) presets.scene(request.path("scene_preset").asText());
        if (request.has("scene_prompt"))
          scene.put(
              "prompt",
              scene.path("prompt").asText() + ". " + request.path("scene_prompt").asText());
      } else scene = Json.object().put("prompt", request.path("scene_prompt").asText());
      worker.set("scene", scene);
    } else {
      // One image per selling point (ADR-20261008-G): the chosen style, or the product image
      // itself with no model call.
      worker.put("per_point", true);
      if (request.path("keep_original").asBoolean()) worker.put("keep_original", true);
      else worker.putArray("styles").add(presets.style(request.path("style").asText()));
      if (request.has("product_position"))
        worker.set("product_position", request.get("product_position"));
    }
    if (request.has("style_prompt")) worker.set("style_prompt", request.get("style_prompt"));
    if (request.has("text")) worker.set("text", request.get("text"));
    worker.put("presets_version", presets.version());
    worker.set("output", request.get("output"));
    freezeOutput(worker, request.get("output"));
    return worker;
  }

  /** Text-only re-render of one stored model output: no model call, same frozen inputs. */
  ObjectNode buildRetypeset(
      JsonNode source, String sourceTask, int ordinal, JsonNode base, JsonNode text) {
    GenerationPolicy.validateText(text);
    var worker = (ObjectNode) source.deepCopy();
    worker.set("text", text);
    worker.set("base_image", base);
    worker.putObject("source").put("task_id", sourceTask).put("ordinal", ordinal);
    if (worker.has("styles")) {
      // Per-point tasks share one style; legacy tasks had one style per image.
      boolean shared = worker.path("per_point").asBoolean();
      var style = worker.path("styles").get(shared ? 0 : ordinal).deepCopy();
      worker.putArray("styles").add(style);
    }
    // The re-render text is already this image's own text; nothing is split per point.
    worker.remove("per_point");
    var output = ((ObjectNode) worker.get("output").deepCopy()).put("count", 1);
    worker.set("output", output);
    freezeOutput(worker, output);
    return worker;
  }

  private static void freezeOutput(ObjectNode worker, JsonNode output) {
    var snapshot = worker.putObject("template_snapshot");
    snapshot.putArray("versions");
    snapshot.putObject("output_preset").put("id", GenerationPolicy.PRESET).set("config", output);
  }

  ObjectNode build(JsonNode request) {
    String project = request.path("project_id").asText();
    var worker = Json.object();
    worker.put("feature_type", request.path("feature_type").asText());
    worker.set("layout", request.get("layout"));
    ObjectNode product = asset(request.path("product_asset_id").asText(), project, "PRODUCT");
    worker.set("product_asset", product);
    var alphas =
        jdbc.queryForList(
            "SELECT id FROM assets WHERE project_id=? AND source_asset_id=? AND kind='ALPHA' AND review_status='APPROVED' ORDER BY created_at DESC,id DESC LIMIT 1",
            project,
            product.path("asset_id").asText());
    if (alphas.isEmpty()) throw new Problem(422, "CUTOUT_REVIEW_REQUIRED");
    worker.set(
        "product_alpha_asset", asset(alphas.getFirst().get("id").toString(), project, "ALPHA"));
    var snapshot = Json.object();
    var versions = snapshot.putArray("versions");
    String feature = request.path("feature_type").asText();
    if (feature.equals("GIFT")) {
      worker.set("gift_asset", asset(request.path("gift_asset_id").asText(), project, "GIFT"));
      versions.add(template(request.path("template_version_id").asText(), "layout"));
      if (request.has("manual_text")) worker.set("manual_text", request.get("manual_text"));
    } else if (feature.equals("SELLING_POINT")) {
      worker.set("selling_points", request.get("selling_points"));
      versions.add(template(request.path("layout_template_version_id").asText(), "layout"));
    } else {
      if (request.has("scene_template_version_id")) {
        var template = template(request.path("scene_template_version_id").asText(), "scene");
        var prompt = template.path("config").path("prompt");
        if (!prompt.isTextual() || prompt.asText().isBlank())
          throw new Problem(422, "INVALID_LAYOUT");
        worker.set("scene_template_prompt", prompt);
        versions.add(template);
      }
      for (String key : List.of("scene_custom_prompt", "style_custom_prompt")) {
        if (request.has(key)) worker.set(key, request.get(key));
      }
    }
    var presets =
        jdbc.queryForList(
            "SELECT config_json FROM output_presets WHERE id=?",
            request.path("output_preset_id").asText());
    if (presets.isEmpty()) throw new Problem(422, "INVALID_LAYOUT");
    var preset = snapshot.putObject("output_preset");
    preset.set("id", request.get("output_preset_id"));
    preset.set("config", Json.parse(presets.getFirst().get("config_json").toString()));
    worker.set("template_snapshot", snapshot);
    return worker;
  }

  private ObjectNode asset(String id, String project, String kind) {
    var rows =
        jdbc.queryForList(
            "SELECT * FROM assets WHERE id=? AND project_id=? AND kind=? FOR SHARE",
            id,
            project,
            kind);
    // The share lock serialises with an owner deletion; a deleted original cannot be used again.
    if (rows.isEmpty()
        || jdbc.queryForObject("SELECT count(*) FROM deletions WHERE target_id=?", Long.class, id)
            > 0) throw new Problem(422, "INVALID_ASSET");
    var row = rows.getFirst();
    var info =
        store.inspect(
            row.get("object_key").toString(), store.read(row.get("object_key").toString()));
    if (!info.sha256().equals(row.get("sha256"))
        || info.width() != ((Number) row.get("width")).intValue()
        || info.height() != ((Number) row.get("height")).intValue())
      throw new Problem(422, "INVALID_ASSET");
    return Json.object()
        .put("asset_id", id)
        .put("object_key", info.objectKey())
        .put("sha256", info.sha256());
  }

  private ObjectNode template(String id, String type) {
    List<Map<String, Object>> rows =
        jdbc.queryForList(
            "SELECT v.* FROM template_versions v JOIN templates t ON t.id=v.template_id WHERE v.id=? AND t.type=? AND v.published_at IS NOT NULL AND t.state<>'DISABLED'",
            id,
            type);
    if (rows.isEmpty()) throw new Problem(422, "INVALID_LAYOUT");
    var row = rows.getFirst();
    var result =
        Json.object()
            .put("id", id)
            .put("template_id", row.get("template_id").toString())
            .put("version", ((Number) row.get("version")).intValue())
            .put("published_by", row.get("published_by").toString())
            .put("published_at", ((Timestamp) row.get("published_at")).toInstant().toString());
    result.set("config", Json.parse(row.get("config_json").toString()));
    return result;
  }
}
