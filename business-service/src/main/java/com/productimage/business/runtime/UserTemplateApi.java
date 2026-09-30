package com.productimage.business.runtime;

import com.fasterxml.jackson.databind.JsonNode;
import jakarta.servlet.http.HttpServletRequest;
import java.sql.Timestamp;
import java.util.List;
import java.util.UUID;
import org.springframework.context.annotation.Profile;
import org.springframework.http.ResponseEntity;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.web.bind.annotation.*;

/**
 * Personal templates (ADR-20260930-F): each account saves its own create-page settings (no images)
 * under a name per entry and applies them later. Nobody else can see or change them. Saving under
 * an existing name replaces that template.
 */
@RestController
@Profile("runtime")
public class UserTemplateApi {
  private final UserAuthenticator users;
  private final JdbcTemplate jdbc;

  UserTemplateApi(UserAuthenticator users, JdbcTemplate jdbc) {
    this.users = users;
    this.jdbc = jdbc;
  }

  private String actor(HttpServletRequest request) {
    return users.authenticate(request.getHeader("Authorization"));
  }

  private static JsonNode item(java.util.Map<String, Object> row) {
    var item =
        Json.object()
            .put("id", row.get("id").toString())
            .put("name", row.get("name").toString())
            .put("feature_type", row.get("feature_type").toString())
            .put("updated_at", ((Timestamp) row.get("updated_at")).toInstant().toString());
    item.set("settings", Json.parse(row.get("settings").toString()));
    return item;
  }

  @GetMapping("/api/v1/templates")
  ResponseEntity<JsonNode> list(
      @RequestParam(name = "feature", required = false) String feature,
      HttpServletRequest request) {
    String actor = actor(request);
    if (feature != null && !List.of("GIFT", "SCENE", "SELLING_POINT").contains(feature))
      throw new Problem(400, "INVALID_CONTRACT");
    var items = Json.MAPPER.createArrayNode();
    for (var row :
        jdbc.queryForList(
            "SELECT id,name,feature_type,settings::text AS settings,updated_at FROM user_templates WHERE owner_id=? AND (?::text IS NULL OR feature_type=?) ORDER BY updated_at DESC,id LIMIT 200",
            actor,
            feature,
            feature)) items.add(item(row));
    return ResponseEntity.ok()
        .header("Cache-Control", "no-store")
        .body(Json.object().set("items", items));
  }

  /** {name, feature_type, settings}: 201 when new, 200 when a same-name template is replaced. */
  @PostMapping("/api/v1/templates")
  ResponseEntity<JsonNode> save(HttpServletRequest request) {
    String actor = actor(request);
    var body = HttpInput.json(request, 16384);
    Json.validate("user-template", body);
    String name = body.path("name").asText().strip();
    String feature = body.path("feature_type").asText();
    String settings = body.path("settings").toString();
    var existing =
        jdbc.queryForList(
            "SELECT id FROM user_templates WHERE owner_id=? AND feature_type=? AND name=?",
            actor,
            feature,
            name);
    boolean created = existing.isEmpty();
    String id = created ? UUID.randomUUID().toString() : existing.getFirst().get("id").toString();
    try {
      if (created)
        jdbc.update(
            "INSERT INTO user_templates(id,owner_id,feature_type,name,settings) VALUES (?,?,?,?,?::jsonb)",
            id,
            actor,
            feature,
            name,
            settings);
    } catch (org.springframework.dao.DuplicateKeyException ex) {
      // Saved twice at the same moment: the other request created it; replace that one.
      created = false;
      id =
          jdbc.queryForObject(
              "SELECT id FROM user_templates WHERE owner_id=? AND feature_type=? AND name=?",
              String.class,
              actor,
              feature,
              name);
    }
    if (!created)
      jdbc.update(
          "UPDATE user_templates SET settings=?::jsonb,updated_at=now() WHERE id=? AND owner_id=?",
          settings,
          id,
          actor);
    var row =
        jdbc.queryForMap(
            "SELECT id,name,feature_type,settings::text AS settings,updated_at FROM user_templates WHERE id=?",
            id);
    return ResponseEntity.status(created ? 201 : 200)
        .header("Cache-Control", "no-store")
        .body(item(row));
  }

  @DeleteMapping("/api/v1/templates/{id}")
  ResponseEntity<Void> delete(@PathVariable String id, HttpServletRequest request) {
    String actor = actor(request);
    if (jdbc.update("DELETE FROM user_templates WHERE id=? AND owner_id=?", id, actor) == 0)
      throw new Problem(404, "NOT_FOUND");
    return ResponseEntity.noContent().header("Cache-Control", "no-store").build();
  }
}
