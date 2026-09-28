package com.productimage.business.runtime;

import com.fasterxml.jackson.databind.JsonNode;
import jakarta.servlet.http.HttpServletRequest;
import org.springframework.context.annotation.Profile;
import org.springframework.http.ResponseEntity;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.web.bind.annotation.*;

/** Owner-scoped read models; authentication mode never broadens project permissions. */
@RestController
@Profile({"dev-local", "prod-local"})
public class WorkbenchApi {
  private final JdbcTemplate jdbc;
  private final UserAuthenticator users;
  private final ProjectAccess access;
  private final ProjectAssets assets;
  private final TaskService tasks;
  private final ScenePolicy scenes;

  public WorkbenchApi(
      JdbcTemplate jdbc,
      UserAuthenticator users,
      ProjectAccess access,
      ProjectAssets assets,
      TaskService tasks,
      ScenePolicy scenes) {
    this.jdbc = jdbc;
    this.users = users;
    this.access = access;
    this.assets = assets;
    this.tasks = tasks;
    this.scenes = scenes;
  }

  private String actor(HttpServletRequest request) {
    return users.authenticate(request.getHeader("Authorization"));
  }

  private int offset(HttpServletRequest request) {
    var params = request.getParameterMap();
    if (params.isEmpty()) return 0;
    if (params.size() != 1 || !params.containsKey("offset") || params.get("offset").length != 1)
      throw new Problem(400, "INVALID_CONTRACT");
    String value = params.get("offset")[0];
    if (!value.matches("0|[1-9][0-9]{0,4}")) throw new Problem(400, "INVALID_CONTRACT");
    int result = Integer.parseInt(value);
    if (result > 10000) throw new Problem(400, "INVALID_CONTRACT");
    return result;
  }

  private ResponseEntity<JsonNode> response(JsonNode value) {
    return ResponseEntity.ok().header("Cache-Control", "no-store").body(value);
  }

  @GetMapping("/api/v1/workbench/options")
  public ResponseEntity<JsonNode> options(HttpServletRequest request) {
    access.active(actor(request));
    if (!request.getParameterMap().isEmpty()) throw new Problem(400, "INVALID_CONTRACT");
    var result =
        Json.object()
            .put(
                "mode",
                users instanceof ProductionAccounts ? "production-local" : "development-only")
            .put("generation_available", false);
    result.set("scene", scenes.options());
    var templates = result.putArray("templates");
    for (var row :
        jdbc.queryForList(
            "SELECT v.id,t.name,t.type,v.version FROM template_versions v JOIN templates t ON t.id=v.template_id WHERE v.published_at IS NOT NULL AND t.state<>'DISABLED' AND (t.type<>'scene' OR (jsonb_typeof(v.config_json->'prompt')='string' AND length(trim(v.config_json->>'prompt'))>0)) ORDER BY t.name,v.version DESC,v.id LIMIT 200")) {
      templates.add(
          Json.object()
              .put("id", row.get("id").toString())
              .put("name", row.get("name").toString())
              .put("type", row.get("type").toString())
              .put("version", ((Number) row.get("version")).intValue()));
    }
    var presets = result.putArray("output_presets");
    for (var row : jdbc.queryForList("SELECT id FROM output_presets ORDER BY id LIMIT 200")) {
      String id = row.get("id").toString();
      presets.add(
          Json.object().put("id", id).put("test_fixture", id.equals("t05_transport_fixture")));
    }
    return response(result);
  }

  @GetMapping("/api/v1/projects/{id}/assets")
  public ResponseEntity<JsonNode> assets(@PathVariable String id, HttpServletRequest request) {
    String actor = actor(request);
    access.require(actor, id);
    int offset = offset(request);
    var rows =
        jdbc.queryForList(
            "SELECT a.id,EXISTS(SELECT 1 FROM assets b WHERE b.project_id=a.project_id AND b.source_asset_id=a.id AND b.kind='ALPHA' AND b.review_status='APPROVED') AS cutout_ready FROM assets a WHERE a.project_id=? AND a.kind IN ('PRODUCT','GIFT') ORDER BY a.created_at DESC,a.id DESC LIMIT 21 OFFSET ?",
            id,
            offset);
    var result = Json.object();
    var items = result.putArray("items");
    for (var row : rows.stream().limit(20).toList()) {
      var item =
          (com.fasterxml.jackson.databind.node.ObjectNode)
              assets.asset(actor, row.get("id").toString());
      item.put("cutout_ready", Boolean.TRUE.equals(row.get("cutout_ready")));
      items.add(item);
    }
    if (rows.size() > 20 && offset <= 9980) result.put("next_offset", offset + 20);
    else result.putNull("next_offset");
    return response(result);
  }

  @GetMapping("/api/v1/projects/{id}/tasks")
  public ResponseEntity<JsonNode> history(@PathVariable String id, HttpServletRequest request) {
    String actor = actor(request);
    access.require(actor, id);
    int offset = offset(request);
    var rows =
        jdbc.queryForList(
            "SELECT id,template_snapshot_json->'output_preset'->>'id' AS preset FROM generation_tasks WHERE project_id=? ORDER BY created_at DESC,id DESC LIMIT 21 OFFSET ?",
            id,
            offset);
    var result = Json.object();
    var items = result.putArray("items");
    for (var row : rows.stream().limit(20).toList()) {
      var item =
          Json.object()
              .put("test_fixture", "t05_transport_fixture".equals(row.get("preset")))
              .put(
                  "real_scene",
                  "scene_v2".equals(row.get("preset")) || "scene_v3".equals(row.get("preset")));
      item.set("task", tasks.get(actor, row.get("id").toString()));
      items.add(item);
    }
    if (rows.size() > 20 && offset <= 9980) result.put("next_offset", offset + 20);
    else result.putNull("next_offset");
    return response(result);
  }
}
