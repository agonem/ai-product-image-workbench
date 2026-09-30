package com.productimage.business.runtime;

import com.fasterxml.jackson.databind.JsonNode;
import java.sql.Timestamp;
import java.util.HashSet;
import java.util.UUID;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.transaction.support.TransactionTemplate;

/**
 * Admin-edited scene presets and selling-point styles (ADR-20260930-F). Saving publishes at once:
 * every save or rollback appends an immutable version and the newest one is in force. Without any
 * saved version the bundled defaults apply. Tasks freeze the copies they used, so history keeps the
 * exact prompts.
 */
final class PresetCatalog {
  private final JdbcTemplate jdbc;
  private final TransactionTemplate tx;
  private final Presets bundled = Presets.bundled();
  private volatile Presets cached;
  private volatile int cachedVersion = -1;

  PresetCatalog(JdbcTemplate jdbc, TransactionTemplate tx) {
    this.jdbc = jdbc;
    this.tx = tx;
  }

  private int latest() {
    Integer version =
        jdbc.queryForObject("SELECT max(version) FROM preset_catalog_versions", Integer.class);
    return version == null ? 0 : version;
  }

  private JsonNode config(int version) {
    var rows =
        jdbc.queryForList(
            "SELECT config::text AS config FROM preset_catalog_versions WHERE version=?", version);
    if (rows.isEmpty()) throw new Problem(404, "NOT_FOUND");
    return Json.parse(rows.getFirst().get("config").toString());
  }

  /** The presets in force (one small query; the parsed version is cached). */
  Presets current() {
    int version = latest();
    if (version == cachedVersion && cached != null) return cached;
    var presets = version == 0 ? bundled : new Presets("catalog-v" + version, config(version));
    cached = presets;
    cachedVersion = version;
    return presets;
  }

  private JsonNode bundledConfig() {
    var config = Json.object();
    var scenes = config.putArray("scenes");
    bundled.scenes().forEach(scenes::add);
    var styles = config.putArray("styles");
    bundled.styles().forEach(styles::add);
    return config;
  }

  /** Current catalogue with its prompts, plus the version history (newest first). */
  JsonNode admin() {
    int version = latest();
    var result = Json.object();
    var current = result.putObject("current");
    current.put("version", version).put("label", current().version());
    JsonNode config = version == 0 ? bundledConfig() : config(version);
    current.set("scenes", config.path("scenes"));
    current.set("styles", config.path("styles"));
    var history = result.putArray("history");
    for (var row :
        jdbc.queryForList(
            "SELECT v.version,v.note,v.restored_from,v.published_at,c.username,u.deleted_username,"
                + "jsonb_array_length(v.config->'scenes') AS scenes,jsonb_array_length(v.config->'styles') AS styles "
                + "FROM preset_catalog_versions v JOIN users u ON u.id=v.published_by "
                + "LEFT JOIN local_credentials c ON c.user_id=v.published_by ORDER BY v.version DESC LIMIT 100")) {
      var item =
          history
              .addObject()
              .put("version", ((Number) row.get("version")).intValue())
              .put("note", row.get("note").toString())
              .put("scene_count", ((Number) row.get("scenes")).intValue())
              .put("style_count", ((Number) row.get("styles")).intValue())
              .put("published_at", ((Timestamp) row.get("published_at")).toInstant().toString());
      Object name = row.get("username") != null ? row.get("username") : row.get("deleted_username");
      item.put("published_by", name == null ? "" : name.toString());
      if (row.get("restored_from") != null)
        item.put("restored_from", ((Number) row.get("restored_from")).intValue());
    }
    return result;
  }

  /** Saves and publishes a new version; ids must be unique within scenes and within styles. */
  int save(String actor, JsonNode body) {
    Json.validate("preset-catalog", body);
    for (String list : new String[] {"scenes", "styles"}) {
      var ids = new HashSet<String>();
      for (var item : body.path(list))
        if (!ids.add(item.path("id").asText())) throw new Problem(400, "INVALID_CONTRACT");
    }
    var config = Json.object();
    config.set("scenes", body.get("scenes"));
    config.set("styles", body.get("styles"));
    return append(actor, config, body.path("note").asText(""), null, "PRESETS_PUBLISHED");
  }

  /** Rolls back by publishing a copy of an earlier version (0 = the bundled defaults). */
  int restore(String actor, int version) {
    JsonNode config = version == 0 ? bundledConfig() : config(version);
    return append(
        actor,
        config,
        version == 0 ? "恢复默认预设" : "回退到版本 " + version,
        version == 0 ? null : version,
        "PRESETS_RESTORED");
  }

  private int append(String actor, JsonNode config, String note, Integer from, String action) {
    return tx.execute(
        status -> {
          jdbc.execute("SELECT pg_advisory_xact_lock(7040402)");
          int next = latest() + 1;
          jdbc.update(
              "INSERT INTO preset_catalog_versions(version,config,note,restored_from,published_by) VALUES (?,?::jsonb,?,?,?)",
              next,
              config.toString(),
              note,
              from,
              actor);
          jdbc.update(
              "INSERT INTO audit_events(id,actor_id,action,resource_id,correlation_id) VALUES (?,?,?,?,?)",
              UUID.randomUUID().toString(),
              actor,
              action,
              "catalog-v" + next,
              UUID.randomUUID().toString());
          return next;
        });
  }
}
