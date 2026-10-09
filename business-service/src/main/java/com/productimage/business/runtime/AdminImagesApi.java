package com.productimage.business.runtime;

import com.fasterxml.jackson.databind.JsonNode;
import jakarta.servlet.http.HttpServletRequest;
import java.sql.Timestamp;
import org.springframework.context.annotation.Profile;
import org.springframework.http.ResponseEntity;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.web.bind.annotation.*;

/**
 * Image management for admins (ADR-20260930-F, user decision): admins may view and delete every
 * account's originals and generated results. This replaces the earlier "no admin read of other
 * projects" rule for images only; deletions follow the owner rules (an original used by a queued or
 * running task is kept; a result goes with the model output behind it) and are audited under the
 * admin's name.
 */
@RestController
@Profile("prod-local")
public class AdminImagesApi {
  private static final int PAGE = 60;
  private final ProductionAccounts accounts;
  private final JdbcTemplate jdbc;
  private final LocalObjectStore store;
  private final ProjectAssets assets;
  private final TaskService tasks;

  AdminImagesApi(
      ProductionAccounts accounts,
      JdbcTemplate jdbc,
      LocalObjectStore store,
      ProjectAssets assets,
      TaskService tasks) {
    this.accounts = accounts;
    this.jdbc = jdbc;
    this.store = store;
    this.assets = assets;
    this.tasks = tasks;
  }

  private String admin(HttpServletRequest request) {
    return accounts.manager(request.getHeader("Authorization"));
  }

  private static final String IMAGES =
      "SELECT a.id,a.kind,a.width,a.height,a.created_at,a.object_key,a.sha256,p.owner_id,NULL::text AS feature_type,'ORIGINAL' AS category "
          + "FROM assets a JOIN projects p ON p.id=a.project_id "
          + "WHERE a.kind IN ('PRODUCT','GIFT','REFERENCE') AND NOT EXISTS (SELECT 1 FROM deletions d WHERE d.target_id=a.id) "
          + "UNION ALL SELECT f.id,f.kind,f.width,f.height,f.created_at,f.object_key,f.sha256,p.owner_id,t.feature_type,'WORK' "
          + "FROM artifacts f JOIN generation_tasks t ON t.id=f.task_id JOIN projects p ON p.id=t.project_id "
          + "WHERE f.kind='COMPOSITE' AND NOT EXISTS (SELECT 1 FROM deletions d WHERE d.target_id=f.id)";

  /** ?category=ORIGINAL|WORK&owner=<user id>&offset=N, newest first, 60 per page. */
  @GetMapping("/api/v1/admin/images")
  ResponseEntity<JsonNode> list(
      @RequestParam String category,
      @RequestParam(required = false) String owner,
      @RequestParam(defaultValue = "0") int offset,
      HttpServletRequest request) {
    admin(request);
    if (!category.equals("ORIGINAL") && !category.equals("WORK") || offset < 0)
      throw new Problem(400, "INVALID_CONTRACT");
    var rows =
        jdbc.queryForList(
            "SELECT x.*,coalesce(c.username,u.deleted_username) AS owner FROM ("
                + IMAGES
                + ") x JOIN users u ON u.id=x.owner_id LEFT JOIN local_credentials c ON c.user_id=x.owner_id "
                + "WHERE x.category=? AND (?::text IS NULL OR x.owner_id=?) ORDER BY x.created_at DESC,x.id LIMIT ? OFFSET ?",
            category,
            owner,
            owner,
            PAGE + 1,
            offset);
    var result = Json.object();
    var items = result.putArray("items");
    rows.stream()
        .limit(PAGE)
        .forEach(
            row -> {
              var item =
                  items
                      .addObject()
                      .put("id", row.get("id").toString())
                      .put("kind", row.get("kind").toString())
                      .put("width", ((Number) row.get("width")).intValue())
                      .put("height", ((Number) row.get("height")).intValue())
                      .put("owner_id", row.get("owner_id").toString())
                      .put("owner", row.get("owner") == null ? "" : row.get("owner").toString())
                      .put(
                          "created_at", ((Timestamp) row.get("created_at")).toInstant().toString());
              if (row.get("feature_type") != null)
                item.put("feature_type", row.get("feature_type").toString());
            });
    if (rows.size() > PAGE) result.put("next_offset", offset + PAGE);
    else result.putNull("next_offset");
    return ResponseEntity.ok().header("Cache-Control", "no-store").body(result);
  }

  private java.util.Map<String, Object> image(String id) {
    var rows = jdbc.queryForList("SELECT * FROM (" + IMAGES + ") x WHERE x.id=?", id);
    if (rows.isEmpty()) throw new Problem(404, "NOT_FOUND");
    return rows.getFirst();
  }

  @GetMapping("/api/v1/admin/images/{id}/content")
  ResponseEntity<byte[]> content(@PathVariable String id, HttpServletRequest request) {
    admin(request);
    var row = image(id);
    byte[] bytes = store.read(row.get("object_key").toString());
    if (!Json.hash(bytes).equals(row.get("sha256")))
      throw new Problem(422, "OUTPUT_VALIDATION_FAILED");
    return ResponseEntity.ok()
        .header("Content-Type", "application/octet-stream")
        .header("Cache-Control", "no-store")
        .header("X-Content-Type-Options", "nosniff")
        .header("Content-Disposition", "attachment")
        .body(bytes);
  }

  @DeleteMapping("/api/v1/admin/images/{id}")
  ResponseEntity<Void> delete(@PathVariable String id, HttpServletRequest request) {
    String actor = admin(request);
    if ("ORIGINAL".equals(image(id).get("category"))) assets.delete(actor, id, true);
    else tasks.deleteArtifact(actor, id, true);
    return ResponseEntity.noContent().header("Cache-Control", "no-store").build();
  }
}
