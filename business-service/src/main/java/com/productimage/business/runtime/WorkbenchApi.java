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
  private final GenerationPolicy generation;
  private final ProviderConfigService configs;

  public WorkbenchApi(
      JdbcTemplate jdbc,
      UserAuthenticator users,
      ProjectAccess access,
      ProjectAssets assets,
      TaskService tasks,
      GenerationPolicy generation,
      ProviderConfigService configs) {
    this.jdbc = jdbc;
    this.users = users;
    this.access = access;
    this.assets = assets;
    this.tasks = tasks;
    this.generation = generation;
    this.configs = configs;
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
                users instanceof ProductionAccounts ? "production-local" : "development-only");
    result.set("generation", generation.options());
    // Models the operator can pick on the generation pages (names only, no keys).
    result.set("models", configs.choices());
    return response(result);
  }

  @GetMapping("/api/v1/projects/{id}/assets")
  public ResponseEntity<JsonNode> assets(@PathVariable String id, HttpServletRequest request) {
    String actor = actor(request);
    access.require(actor, id);
    int offset = offset(request);
    var rows =
        jdbc.queryForList(
            "SELECT a.id FROM assets a WHERE a.project_id=? AND a.kind IN ('PRODUCT','GIFT','REFERENCE') AND NOT EXISTS (SELECT 1 FROM deletions d WHERE d.target_id=a.id) ORDER BY a.created_at DESC,a.id DESC LIMIT 21 OFFSET ?",
            id,
            offset);
    var result = Json.object();
    var items = result.putArray("items");
    for (var row : rows.stream().limit(20).toList())
      items.add(assets.asset(actor, row.get("id").toString()));
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
            "SELECT id FROM generation_tasks WHERE project_id=? ORDER BY created_at DESC,id DESC LIMIT 21 OFFSET ?",
            id,
            offset);
    var result = Json.object();
    var items = result.putArray("items");
    for (var row : rows.stream().limit(20).toList()) {
      var item = Json.object();
      item.set("task", tasks.get(actor, row.get("id").toString()));
      items.add(item);
    }
    if (rows.size() > 20 && offset <= 9980) result.put("next_offset", offset + 20);
    else result.putNull("next_offset");
    return response(result);
  }
}
