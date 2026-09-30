package com.productimage.business.runtime;

import com.fasterxml.jackson.databind.JsonNode;
import jakarta.servlet.http.HttpServletRequest;
import java.sql.Timestamp;
import java.time.ZoneId;
import org.springframework.context.annotation.Profile;
import org.springframework.core.env.Environment;
import org.springframework.http.ResponseEntity;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.web.bind.annotation.*;

/**
 * Data dashboard and operation log for admins (ADR-20260930-F). Counts cover current-version
 * generation tasks only (retypesets included); days follow REPORT_TIME_ZONE (default
 * Asia/Shanghai).
 */
@RestController
@Profile("prod-local")
public class AdminInsightsApi {
  private static final String V4 =
      "t.template_snapshot_json->'output_preset'->>'id'='" + GenerationPolicy.PRESET + "'";
  private static final int LOG_PAGE = 50;
  private final ProductionAccounts accounts;
  private final JdbcTemplate jdbc;
  private final String zone;

  AdminInsightsApi(ProductionAccounts accounts, JdbcTemplate jdbc, Environment env) {
    this.accounts = accounts;
    this.jdbc = jdbc;
    zone = ZoneId.of(env.getProperty("REPORT_TIME_ZONE", "Asia/Shanghai")).getId();
  }

  private void admin(HttpServletRequest request) {
    accounts.manager(request.getHeader("Authorization"));
  }

  private static long number(Object value) {
    return value == null ? 0 : ((Number) value).longValue();
  }

  /** ?days=1..90 (default 14): totals, per day, now queued/running, per model/user/entry. */
  @GetMapping("/api/v1/admin/metrics")
  ResponseEntity<JsonNode> metrics(
      @RequestParam(defaultValue = "14") int days, HttpServletRequest request) {
    admin(request);
    if (days < 1 || days > 90) throw new Problem(400, "INVALID_CONTRACT");
    String since =
        "(date_trunc('day', now() AT TIME ZONE ?) - (? - 1) * interval '1 day') AT TIME ZONE ?";
    var result = Json.object().put("days", days).put("time_zone", zone);
    var totals =
        jdbc.queryForMap(
            "SELECT count(*) AS tasks,count(*) FILTER (WHERE t.status='SUCCEEDED') AS succeeded,"
                + "count(*) FILTER (WHERE t.status='FAILED') AS failed,"
                + "(SELECT count(*) FROM artifacts f JOIN generation_tasks g ON g.id=f.task_id WHERE f.kind='COMPOSITE' AND f.created_at>="
                + since
                + " AND g.template_snapshot_json->'output_preset'->>'id'='"
                + GenerationPolicy.PRESET
                + "') AS images,"
                + "avg(extract(epoch FROM a.ended_at-a.started_at)) FILTER (WHERE t.status='SUCCEEDED') AS avg_seconds,"
                + "max(extract(epoch FROM a.ended_at-a.started_at)) FILTER (WHERE t.status='SUCCEEDED') AS max_seconds "
                + "FROM generation_tasks t LEFT JOIN task_attempts a ON a.id=t.current_attempt_id WHERE "
                + V4
                + " AND t.created_at>="
                + since,
            zone,
            days,
            zone,
            zone,
            days,
            zone);
    var total = result.putObject("totals");
    for (String key : new String[] {"tasks", "succeeded", "failed", "images"})
      total.put(key, number(totals.get(key)));
    total.put(
        "avg_seconds",
        totals.get("avg_seconds") == null
            ? 0
            : Math.round(((Number) totals.get("avg_seconds")).doubleValue()));
    total.put(
        "max_seconds",
        totals.get("max_seconds") == null
            ? 0
            : Math.round(((Number) totals.get("max_seconds")).doubleValue()));
    var now =
        jdbc.queryForMap(
            "SELECT count(*) FILTER (WHERE t.status='QUEUED') AS queued,count(*) FILTER (WHERE t.status='RUNNING') AS running FROM generation_tasks t WHERE "
                + V4);
    result
        .putObject("now")
        .put("queued", number(now.get("queued")))
        .put("running", number(now.get("running")));
    var daily = result.putArray("daily");
    for (var row :
        jdbc.queryForList(
            "SELECT to_char(d,'YYYY-MM-DD') AS day,"
                + "(SELECT count(*) FROM generation_tasks t WHERE "
                + V4
                + " AND (t.created_at AT TIME ZONE ?)::date=d) AS tasks,"
                + "(SELECT count(*) FROM generation_tasks t WHERE "
                + V4
                + " AND t.status='FAILED' AND (t.created_at AT TIME ZONE ?)::date=d) AS failed,"
                + "(SELECT count(*) FROM artifacts f JOIN generation_tasks g ON g.id=f.task_id WHERE f.kind='COMPOSITE' AND g.template_snapshot_json->'output_preset'->>'id'='"
                + GenerationPolicy.PRESET
                + "' AND (f.created_at AT TIME ZONE ?)::date=d) AS images "
                + "FROM generate_series((now() AT TIME ZONE ?)::date - (? - 1),(now() AT TIME ZONE ?)::date,interval '1 day') AS s(d) ORDER BY d",
            zone,
            zone,
            zone,
            zone,
            days,
            zone))
      daily
          .addObject()
          .put("day", row.get("day").toString())
          .put("tasks", number(row.get("tasks")))
          .put("failed", number(row.get("failed")))
          .put("images", number(row.get("images")));
    group(
        result.putArray("by_feature"),
        "SELECT t.feature_type AS name,count(*) AS tasks,count(*) FILTER (WHERE t.status='FAILED') AS failed FROM generation_tasks t WHERE "
            + V4
            + " AND t.created_at>="
            + since
            + " GROUP BY 1 ORDER BY 2 DESC",
        days);
    group(
        result.putArray("by_model"),
        "SELECT coalesce(v.name,'环境配置') AS name,count(*) AS tasks,count(*) FILTER (WHERE t.status='FAILED') AS failed FROM generation_tasks t LEFT JOIN provider_config_versions v ON v.id=t.provider_config_version WHERE "
            + V4
            + " AND t.created_at>="
            + since
            + " GROUP BY 1 ORDER BY 2 DESC LIMIT 20",
        days);
    group(
        result.putArray("by_user"),
        "SELECT coalesce(c.username,u.deleted_username,'—') AS name,count(*) AS tasks,count(*) FILTER (WHERE t.status='FAILED') AS failed FROM generation_tasks t JOIN projects p ON p.id=t.project_id JOIN users u ON u.id=p.owner_id LEFT JOIN local_credentials c ON c.user_id=p.owner_id WHERE "
            + V4
            + " AND t.created_at>="
            + since
            + " GROUP BY 1 ORDER BY 2 DESC LIMIT 20",
        days);
    return ResponseEntity.ok().header("Cache-Control", "no-store").body(result);
  }

  private void group(com.fasterxml.jackson.databind.node.ArrayNode target, String sql, int days) {
    for (var row : jdbc.queryForList(sql, zone, days, zone))
      target
          .addObject()
          .put("name", row.get("name").toString())
          .put("tasks", number(row.get("tasks")))
          .put("failed", number(row.get("failed")));
  }

  /** ?actor=<user id>&action=<ACTION>&offset=N: newest first, 50 per page; ids only, no content. */
  @GetMapping("/api/v1/admin/audit")
  ResponseEntity<JsonNode> audit(
      @RequestParam(required = false) String actor,
      @RequestParam(required = false) String action,
      @RequestParam(defaultValue = "0") int offset,
      HttpServletRequest request) {
    admin(request);
    if (offset < 0 || (action != null && !action.matches("[A-Z0-9_]{1,64}")))
      throw new Problem(400, "INVALID_CONTRACT");
    var rows =
        jdbc.queryForList(
            "SELECT e.id,e.action,e.resource_id,e.occurred_at,e.actor_id,coalesce(c.username,u.deleted_username) AS actor "
                + "FROM audit_events e LEFT JOIN users u ON u.id=e.actor_id LEFT JOIN local_credentials c ON c.user_id=e.actor_id "
                + "WHERE (?::text IS NULL OR e.actor_id=?) AND (?::text IS NULL OR e.action=?) "
                + "ORDER BY e.occurred_at DESC,e.id DESC LIMIT ? OFFSET ?",
            actor,
            actor,
            action,
            action,
            LOG_PAGE + 1,
            offset);
    var result = Json.object();
    var items = result.putArray("items");
    rows.stream()
        .limit(LOG_PAGE)
        .forEach(
            row ->
                items
                    .addObject()
                    .put("id", row.get("id").toString())
                    .put("action", row.get("action").toString())
                    .put("resource_id", row.get("resource_id").toString())
                    .put("actor", row.get("actor") == null ? "" : row.get("actor").toString())
                    .put(
                        "occurred_at",
                        ((Timestamp) row.get("occurred_at")).toInstant().toString()));
    if (rows.size() > LOG_PAGE) result.put("next_offset", offset + LOG_PAGE);
    else result.putNull("next_offset");
    return ResponseEntity.ok().header("Cache-Control", "no-store").body(result);
  }
}
