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
  private final ScenePolicy scenes;

  SnapshotBuilder(JdbcTemplate jdbc, LocalObjectStore store, ScenePolicy scenes) {
    this.jdbc = jdbc;
    this.store = store;
    this.scenes = scenes;
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
    if (request.has("output")) {
      scenes.validate(request.get("output"));
      int version = request.path("output").has("width") ? 3 : 2;
      worker.put("schema_version", version);
      worker.set("output", request.get("output"));
      snapshot
          .putObject("output_preset")
          .put("id", "scene_v" + version)
          .set("config", request.get("output"));
    } else {
      var presets =
          jdbc.queryForList(
              "SELECT config_json FROM output_presets WHERE id=?",
              request.path("output_preset_id").asText());
      if (presets.isEmpty()) throw new Problem(422, "INVALID_LAYOUT");
      var preset = snapshot.putObject("output_preset");
      preset.set("id", request.get("output_preset_id"));
      preset.set("config", Json.parse(presets.getFirst().get("config_json").toString()));
    }
    worker.set("template_snapshot", snapshot);
    return worker;
  }

  private ObjectNode asset(String id, String project, String kind) {
    var rows =
        jdbc.queryForList(
            "SELECT * FROM assets WHERE id=? AND project_id=? AND kind=?", id, project, kind);
    if (rows.isEmpty()) throw new Problem(422, "INVALID_ASSET");
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
