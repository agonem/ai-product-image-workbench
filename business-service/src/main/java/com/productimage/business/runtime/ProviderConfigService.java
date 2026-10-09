package com.productimage.business.runtime;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.node.ObjectNode;
import java.net.URI;
import java.net.URISyntaxException;
import java.sql.Timestamp;
import java.util.HashSet;
import java.util.Map;
import java.util.Set;
import java.util.UUID;
import org.springframework.core.env.Environment;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.transaction.support.TransactionTemplate;

/**
 * Admin-managed model catalog (ADR-20260929-C): OpenRouter, official OpenAI and official Gemini.
 * Several models can be enabled; operators choose one per task and the admin marks a default. Since
 * ADR-20261009-Q (user decision) a model is edited in place - submitted tasks use the edited
 * settings - and can be deleted, its unfinished tasks moving to the default model. Keys and the
 * proxy URL are encrypted under the external master key and are never echoed or logged.
 */
public final class ProviderConfigService {
  // Third-party endpoints in the OpenAI or Gemini format are offered again (ADR-20260930-E).
  static final Set<String> PROVIDERS =
      Set.of("openrouter", "openai", "gemini", "openai-compatible", "gemini-compatible");
  private static final Set<String> BASE =
      Set.of("name", "provider", "model", "api_key", "enabled", "use_proxy");
  // IMAGE models generate pictures; TEXT models rewrite briefs for agents (ADR-20261008-L).
  static final Set<String> PURPOSES = Set.of("IMAGE", "TEXT");
  // Fields an edit may change; the purpose (picture or text) is fixed for a model's lifetime.
  private static final Set<String> EDITABLE =
      Set.of(
          "name",
          "enabled",
          "use_proxy",
          "provider",
          "model",
          "provider_tag",
          "base_url",
          "api_key",
          "parameters");
  private final JdbcTemplate jdbc;
  private final TransactionTemplate tx;
  private final byte[] master;

  ProviderConfigService(JdbcTemplate jdbc, TransactionTemplate tx, Environment env) {
    this.jdbc = jdbc;
    this.tx = tx;
    // The master key is only required once a secret is stored or read; absence disables
    // those operations safely instead of falling back to worker environment credentials.
    this.master =
        env.getProperty("PROVIDER_MASTER_KEY", "").isBlank()
                && env.getProperty("PROVIDER_MASTER_KEY_FILE", "").isBlank()
            ? null
            : ProviderCrypto.masterKey(
                env.getProperty("PROVIDER_MASTER_KEY", ""),
                env.getProperty("PROVIDER_MASTER_KEY_FILE", ""));
  }

  private String defaultId() {
    return defaultId("IMAGE");
  }

  /** The default per purpose: state row 'active' for pictures, 'text' for rewriting. */
  private String defaultId(String purpose) {
    var rows =
        jdbc.queryForList(
            "SELECT active_version_id FROM provider_config_state WHERE provider=?",
            purpose.equals("TEXT") ? "text" : "active");
    return rows.isEmpty() || rows.getFirst().get("active_version_id") == null
        ? null
        : rows.getFirst().get("active_version_id").toString();
  }

  /**
   * Model bound to a new generation task. An explicit choice must be an enabled model; without one
   * the admin's default applies. A deployment that never configured a model keeps the explicit
   * Worker environment path (development only); otherwise nothing falls back silently.
   */
  String binding(JsonNode requested) {
    if (requested != null && requested.isTextual()) {
      var chosen =
          jdbc.queryForList(
              "SELECT id FROM provider_config_versions WHERE id=? AND enabled AND NOT retired AND purpose='IMAGE'",
              requested.asText());
      if (chosen.isEmpty()) throw new Problem(422, "MODEL_UNAVAILABLE");
      return requested.asText();
    }
    if (jdbc.queryForObject(
            "SELECT count(*) FROM provider_config_versions WHERE purpose='IMAGE'", Long.class)
        == 0) return null;
    var fallback =
        jdbc.queryForList(
            "SELECT v.id FROM provider_config_state s JOIN provider_config_versions v ON v.id=s.active_version_id "
                + "WHERE s.provider='active' AND v.enabled AND NOT v.retired");
    if (fallback.isEmpty()) throw new Problem(503, "PROVIDER_DISABLED");
    return fallback.getFirst().get("id").toString();
  }

  /**
   * Text model for an agent rewrite (ADR-20261008-L): the text default when usable, otherwise the
   * first enabled text model; null when none is configured.
   */
  String textBinding() {
    String chosen = defaultId("TEXT");
    var rows =
        jdbc.queryForList(
            "SELECT id FROM provider_config_versions WHERE enabled AND NOT retired AND purpose='TEXT' ORDER BY (id=?) DESC,created_at,id LIMIT 1",
            chosen == null ? "" : chosen);
    return rows.isEmpty() ? null : rows.getFirst().get("id").toString();
  }

  /** Leased workers receive the decrypted binding; failures must not fall back silently. */
  JsonNode claimConfig(String versionId) {
    if (master == null) throw new Problem(503, "PROVIDER_UNAVAILABLE");
    var rows =
        jdbc.queryForList(
            "SELECT provider,model,provider_tag,base_url,api_key_cipher,use_proxy,parameters FROM provider_config_versions WHERE id=?",
            versionId);
    if (rows.isEmpty()) throw new Problem(503, "PROVIDER_UNAVAILABLE");
    var row = rows.getFirst();
    try {
      var config =
          Json.object()
              .put("provider", row.get("provider").toString())
              .put("model", row.get("model").toString());
      optional(config, "provider_tag", row.get("provider_tag"));
      optional(config, "base_url", row.get("base_url"));
      config.set("parameters", Json.parse(row.get("parameters").toString()));
      config.put("api_key", ProviderCrypto.decrypt(master, row.get("api_key_cipher").toString()));
      // Only models marked "use proxy" leave through it; without a saved proxy they go direct.
      if (Boolean.TRUE.equals(row.get("use_proxy"))) {
        var proxy = jdbc.queryForList("SELECT proxy_cipher FROM network_settings WHERE id='proxy'");
        if (!proxy.isEmpty())
          config.put(
              "proxy_url",
              ProviderCrypto.decrypt(master, proxy.getFirst().get("proxy_cipher").toString()));
      }
      return config;
    } catch (IllegalStateException ex) {
      throw new Problem(503, "PROVIDER_UNAVAILABLE");
    }
  }

  private static void optional(ObjectNode target, String field, Object value) {
    if (value != null) target.put(field, value.toString());
  }

  private static boolean validName(JsonNode name) {
    return name.isTextual()
        && !name.asText().isBlank()
        && name.asText().strip().length() <= 40
        && name.asText().codePoints().noneMatch(Character::isISOControl);
  }

  /** Exactly the fields of the chosen provider type, each in its allowed shape. */
  static void validate(JsonNode body) {
    String provider = body.path("provider").asText();
    if (!body.isObject() || !PROVIDERS.contains(provider))
      throw new Problem(400, "INVALID_CONTRACT");
    var expected = new HashSet<>(BASE);
    if (body.has("purpose")) expected.add("purpose");
    if (body.has("parameters")) expected.add("parameters");
    // OpenRouter image models pin a provider; a text model may leave routing to OpenRouter.
    boolean text = "TEXT".equals(body.path("purpose").asText());
    if (provider.equals("openrouter") && !(text && !body.has("provider_tag")))
      expected.add("provider_tag");
    if (provider.endsWith("-compatible")) expected.add("base_url");
    var names = new HashSet<String>();
    body.fieldNames().forEachRemaining(names::add);
    String model = body.path("model").asText();
    if (!names.equals(expected)
        || !validName(body.path("name"))
        || !body.path("enabled").isBoolean()
        || !body.path("use_proxy").isBoolean()
        || !body.path("model").isTextual()
        || !body.path("api_key").isTextual()
        || !model.matches("[A-Za-z0-9][A-Za-z0-9_./:-]{0,199}")
        || (provider.equals("openrouter") && !model.matches("[a-zA-Z0-9_-]+/[a-zA-Z0-9_.:-]+"))
        || (body.has("provider_tag")
            && !body.path("provider_tag").asText().matches("[a-zA-Z0-9_./-]{1,100}"))
        || (body.has("base_url")
            && !(body.path("base_url").isTextual() && validBaseUrl(body.path("base_url").asText())))
        || !validKey(body.path("api_key"))
        || (body.has("purpose") && !PURPOSES.contains(body.path("purpose").asText())))
      throw new Problem(400, "INVALID_CONTRACT");
    // Only the parameters this model supports, with listed values (ADR-20261009-Q).
    if (body.has("parameters"))
      ModelParameters.validate(model, body.path("purpose").asText("IMAGE"), body.get("parameters"));
  }

  /**
   * Third-party endpoint: https anywhere; plain http only to a literal private IPv4 address (10/8,
   * 172.16/12, 192.168/16), because keys and images would cross the network unencrypted. No
   * credentials, query or fragment; at most 300 characters. Same rule as the Worker.
   */
  static boolean validBaseUrl(String value) {
    if (value.length() > 300 || !value.matches("https?://[\\x21-\\x7e]+")) return false;
    try {
      var uri = new URI(value);
      String host = uri.getHost();
      if (host == null
          || uri.getRawUserInfo() != null
          || uri.getRawQuery() != null
          || uri.getRawFragment() != null
          || uri.getPort() > 65535) return false;
      if (uri.getScheme().equals("https")) return true;
      if (!host.matches("\\d{1,3}(\\.\\d{1,3}){3}")) return false;
      int[] ip = java.util.Arrays.stream(host.split("\\.")).mapToInt(Integer::parseInt).toArray();
      if (java.util.Arrays.stream(ip).anyMatch(part -> part > 255)) return false;
      return ip[0] == 10
          || (ip[0] == 172 && ip[1] >= 16 && ip[1] <= 31)
          || (ip[0] == 192 && ip[1] == 168);
    } catch (URISyntaxException ex) {
      return false;
    }
  }

  private static boolean validKey(JsonNode key) {
    return key.isTextual() && key.asText().matches("[\\x21-\\x7e]{1,4096}");
  }

  /**
   * Outbound proxy: http or https, optional credentials, host and port only (no path, query or
   * fragment). Credentials are allowed because company proxies often need them.
   */
  static boolean validProxy(String value) {
    if (value.length() > 300 || !value.matches("https?://[\\x21-\\x7e]+")) return false;
    try {
      var uri = new URI(value);
      return uri.getHost() != null
          && uri.getPort() <= 65535
          && (uri.getRawPath() == null
              || uri.getRawPath().isEmpty()
              || uri.getRawPath().equals("/"))
          && uri.getRawQuery() == null
          && uri.getRawFragment() == null;
    } catch (URISyntaxException ex) {
      return false;
    }
  }

  /** Masked form shown to administrators: scheme, host and port; credentials hidden. */
  static String proxyMask(String value) {
    try {
      var uri = new URI(value);
      return uri.getScheme()
          + "://"
          + (uri.getRawUserInfo() != null ? "****@" : "")
          + uri.getHost()
          + (uri.getPort() > 0 ? ":" + uri.getPort() : "");
    } catch (URISyntaxException ex) {
      throw new Problem(400, "INVALID_CONTRACT");
    }
  }

  private ObjectNode item(Map<String, Object> row) {
    String purpose = row.get("purpose").toString();
    return item(row, defaultId(purpose)).put("purpose", purpose);
  }

  private ObjectNode item(Map<String, Object> row, String defaultId) {
    var item =
        Json.object()
            .put("id", row.get("id").toString())
            .put("name", row.get("name").toString())
            .put("provider", row.get("provider").toString())
            .put("model", row.get("model").toString());
    optional(item, "provider_tag", row.get("provider_tag"));
    optional(item, "base_url", row.get("base_url"));
    item.set("parameters", Json.parse(row.get("parameters").toString()));
    return item.put("api_key_mask", row.get("api_key_mask").toString())
        .put("enabled", Boolean.TRUE.equals(row.get("enabled")))
        .put("use_proxy", Boolean.TRUE.equals(row.get("use_proxy")))
        .put("default", row.get("id").toString().equals(defaultId))
        .put("created_at", ((Timestamp) row.get("created_at")).toInstant().toString());
  }

  private static final String COLUMNS =
      "id,name,provider,model,provider_tag,base_url,api_key_mask,enabled,use_proxy,created_at,purpose,parameters";

  public JsonNode list() {
    var result = Json.object();
    String defaultId = defaultId();
    if (defaultId == null) result.putNull("default_id");
    else result.put("default_id", defaultId);
    var items = result.putArray("items");
    for (var row :
        jdbc.queryForList(
            "SELECT "
                + COLUMNS
                + " FROM provider_config_versions WHERE NOT retired ORDER BY created_at,id"))
      items.add(item(row));
    String textDefault = defaultId("TEXT");
    if (textDefault == null) result.putNull("text_default_id");
    else result.put("text_default_id", textDefault);
    result.set("proxy", proxy());
    return result;
  }

  /**
   * Enabled models for the generation pages: names only, never keys or routing details, and the
   * clarities (1K / 2K) the pages may offer with the starting one (ADR-20261009-R).
   */
  public JsonNode choices() {
    var result = Json.MAPPER.createArrayNode();
    String defaultId = defaultId();
    for (var row :
        jdbc.queryForList(
            "SELECT id,name,provider,model,parameters FROM provider_config_versions WHERE enabled AND NOT retired AND purpose='IMAGE' ORDER BY created_at,id")) {
      String model = row.get("model").toString();
      var item =
          Json.object()
              .put("id", row.get("id").toString())
              .put("name", row.get("name").toString())
              .put("provider", row.get("provider").toString())
              .put("model", model)
              .put("default", row.get("id").toString().equals(defaultId));
      var offered = item.putArray("resolutions");
      ModelParameters.resolutions(model, "IMAGE").forEach(offered::add);
      String start =
          ModelParameters.defaultResolution(
              model, "IMAGE", Json.parse(row.get("parameters").toString()));
      if (start != null) item.put("resolution", start);
      result.add(item);
    }
    return result;
  }

  /** The clarities a bound model can be asked for (ADR-20261009-R). */
  java.util.List<String> resolutions(String versionId) {
    var rows =
        jdbc.queryForList(
            "SELECT model,purpose FROM provider_config_versions WHERE id=?", versionId);
    if (rows.isEmpty()) return java.util.List.of();
    return ModelParameters.resolutions(
        rows.getFirst().get("model").toString(), rows.getFirst().get("purpose").toString());
  }

  private void requireMaster() {
    if (master == null) throw new Problem(503, "PROVIDER_UNAVAILABLE");
  }

  private Map<String, Object> live(String id, boolean lock) {
    var rows =
        jdbc.queryForList(
            "SELECT * FROM provider_config_versions WHERE id=? AND NOT retired"
                + (lock ? " FOR UPDATE" : ""),
            id);
    if (rows.isEmpty()) throw new Problem(404, "NOT_FOUND");
    return rows.getFirst();
  }

  private void pointDefault(String id) {
    String purpose =
        jdbc.queryForObject(
            "SELECT purpose FROM provider_config_versions WHERE id=?", String.class, id);
    jdbc.update(
        "INSERT INTO provider_config_state(provider,active_version_id) VALUES (?,?) "
            + "ON CONFLICT(provider) DO UPDATE SET active_version_id=EXCLUDED.active_version_id,updated_at=now()",
        "TEXT".equals(purpose) ? "text" : "active",
        id);
  }

  public JsonNode create(String actor, JsonNode body) {
    validate(body);
    requireMaster();
    String key = body.path("api_key").asText();
    return tx.execute(
        status -> {
          String id = UUID.randomUUID().toString();
          jdbc.update(
              "INSERT INTO provider_config_versions(id,name,provider,model,provider_tag,base_url,api_key_cipher,api_key_mask,enabled,use_proxy,created_by,purpose,parameters) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?::jsonb)",
              id,
              body.path("name").asText().strip(),
              body.path("provider").asText(),
              body.path("model").asText(),
              body.has("provider_tag") ? body.path("provider_tag").asText() : null,
              body.has("base_url") ? body.path("base_url").asText() : null,
              ProviderCrypto.encrypt(master, key),
              ProviderCrypto.mask(key),
              body.path("enabled").asBoolean(),
              body.path("use_proxy").asBoolean(),
              actor,
              body.path("purpose").asText("IMAGE"),
              body.has("parameters") ? body.get("parameters").toString() : "{}");
          // The first usable model becomes the default so generation works right away.
          if (body.path("enabled").asBoolean()) {
            String current = defaultId(body.path("purpose").asText("IMAGE"));
            boolean usable =
                current != null
                    && jdbc.queryForObject(
                            "SELECT count(*) FROM provider_config_versions WHERE id=? AND enabled AND NOT retired",
                            Long.class,
                            current)
                        > 0;
            if (!usable) pointDefault(id);
          }
          audit(actor, "PROVIDER_CONFIG_CREATED", id);
          return item(
              jdbc.queryForMap(
                  "SELECT " + COLUMNS + " FROM provider_config_versions WHERE id=?", id));
        });
  }

  /**
   * Edit a model in place (ADR-20261009-Q): any of name, enabled, use_proxy, provider, model,
   * provider_tag, base_url, a new api_key and parameters; a null tag or address removes it. The
   * result must pass the same checks as a new model. Submitted tasks use the edited settings. The
   * default cannot be disabled and the purpose never changes.
   */
  public void update(String actor, String id, JsonNode body) {
    if (!body.isObject() || body.isEmpty()) throw new Problem(400, "INVALID_CONTRACT");
    body.fieldNames()
        .forEachRemaining(
            field -> {
              if (!EDITABLE.contains(field)) throw new Problem(400, "INVALID_CONTRACT");
            });
    if (body.has("api_key")) requireMaster();
    tx.executeWithoutResult(
        status -> {
          var row = live(id, true);
          String purpose = row.get("purpose").toString();
          var merged =
              Json.object()
                  .put("name", row.get("name").toString())
                  .put("provider", row.get("provider").toString())
                  .put("model", row.get("model").toString())
                  .put("enabled", Boolean.TRUE.equals(row.get("enabled")))
                  .put("use_proxy", Boolean.TRUE.equals(row.get("use_proxy")))
                  .put("purpose", purpose)
                  // Stands in for the stored key during the checks; never written.
                  .put("api_key", "unchanged");
          merged.set("parameters", Json.parse(row.get("parameters").toString()));
          // A new provider type brings its own routing fields; old ones do not carry over.
          if (!body.has("provider")) {
            optional(merged, "provider_tag", row.get("provider_tag"));
            optional(merged, "base_url", row.get("base_url"));
          }
          // Another model family has other parameters; unless new ones are given, start empty.
          if (body.has("model")
              && !body.has("parameters")
              && !ModelParameters.family(body.path("model").asText(), purpose)
                  .path("id")
                  .equals(ModelParameters.family(row.get("model").toString(), purpose).path("id")))
            merged.set("parameters", Json.object());
          body.properties()
              .forEach(
                  entry -> {
                    if (entry.getValue().isNull()
                        && Set.of("provider_tag", "base_url").contains(entry.getKey()))
                      merged.remove(entry.getKey());
                    else merged.set(entry.getKey(), entry.getValue());
                  });
          validate(merged);
          if (!merged.path("enabled").asBoolean() && id.equals(defaultId(purpose)))
            throw new Problem(409, "DEFAULT_MODEL");
          jdbc.update(
              "UPDATE provider_config_versions SET name=?,provider=?,model=?,provider_tag=?,base_url=?,enabled=?,use_proxy=?,parameters=?::jsonb WHERE id=?",
              merged.path("name").asText().strip(),
              merged.path("provider").asText(),
              merged.path("model").asText(),
              merged.has("provider_tag") ? merged.path("provider_tag").asText() : null,
              merged.has("base_url") ? merged.path("base_url").asText() : null,
              merged.path("enabled").asBoolean(),
              merged.path("use_proxy").asBoolean(),
              merged.get("parameters").toString(),
              id);
          if (body.has("api_key"))
            jdbc.update(
                "UPDATE provider_config_versions SET api_key_cipher=?,api_key_mask=? WHERE id=?",
                ProviderCrypto.encrypt(master, body.path("api_key").asText()),
                ProviderCrypto.mask(body.path("api_key").asText()),
                id);
          audit(actor, "PROVIDER_CONFIG_UPDATED", id);
        });
  }

  /**
   * Delete a model for good (ADR-20261009-Q). The default of its purpose cannot be deleted. Its
   * queued, running and failed tasks move to the default (or another enabled model of the same
   * purpose) so they finish or retry there; finished tasks keep their receipts and lose the link.
   */
  public void delete(String actor, String id) {
    tx.executeWithoutResult(
        status -> {
          var row = live(id, true);
          String purpose = row.get("purpose").toString();
          if (id.equals(defaultId(purpose))) throw new Problem(409, "DEFAULT_MODEL");
          var replacements =
              jdbc.queryForList(
                  "SELECT id FROM provider_config_versions WHERE enabled AND NOT retired AND purpose=? AND id<>? ORDER BY (id=?) DESC,created_at,id LIMIT 1",
                  purpose,
                  id,
                  String.valueOf(defaultId(purpose)));
          String replacement =
              replacements.isEmpty() ? null : replacements.getFirst().get("id").toString();
          String column =
              purpose.equals("TEXT") ? "text_config_version" : "provider_config_version";
          jdbc.update(
              "UPDATE generation_tasks SET "
                  + column
                  + "=? WHERE "
                  + column
                  + "=? AND status IN ('QUEUED','RUNNING','FAILED')",
              replacement,
              id);
          jdbc.update("DELETE FROM provider_config_versions WHERE id=?", id);
          audit(actor, "PROVIDER_CONFIG_DELETED", id);
        });
  }

  public void makeDefault(String actor, String id) {
    tx.executeWithoutResult(
        status -> {
          if (!Boolean.TRUE.equals(live(id, true).get("enabled")))
            throw new Problem(409, "MODEL_UNAVAILABLE");
          pointDefault(id);
          audit(actor, "PROVIDER_CONFIG_DEFAULT", id);
        });
  }

  /** New key, in place (ADR-20261009-Q): submitted tasks use it too. */
  public JsonNode rotate(String actor, String id, JsonNode body) {
    if (!body.isObject() || body.size() != 1 || !validKey(body.path("api_key")))
      throw new Problem(400, "INVALID_CONTRACT");
    requireMaster();
    String key = body.path("api_key").asText();
    return tx.execute(
        status -> {
          live(id, true);
          jdbc.update(
              "UPDATE provider_config_versions SET api_key_cipher=?,api_key_mask=? WHERE id=?",
              ProviderCrypto.encrypt(master, key),
              ProviderCrypto.mask(key),
              id);
          audit(actor, "PROVIDER_CONFIG_ROTATED", id);
          return item(
              jdbc.queryForMap(
                  "SELECT " + COLUMNS + " FROM provider_config_versions WHERE id=?", id));
        });
  }

  public JsonNode proxy() {
    var rows =
        jdbc.queryForList("SELECT proxy_mask,updated_at FROM network_settings WHERE id='proxy'");
    if (rows.isEmpty()) return Json.object().put("configured", false);
    return Json.object()
        .put("configured", true)
        .put("mask", rows.getFirst().get("proxy_mask").toString())
        .put("updated_at", ((Timestamp) rows.getFirst().get("updated_at")).toInstant().toString());
  }

  public void setProxy(String actor, JsonNode body) {
    if (!body.isObject()
        || body.size() != 1
        || !body.path("proxy_url").isTextual()
        || !validProxy(body.path("proxy_url").asText())) throw new Problem(400, "INVALID_CONTRACT");
    requireMaster();
    String url = body.path("proxy_url").asText();
    tx.executeWithoutResult(
        status -> {
          jdbc.update(
              "INSERT INTO network_settings(id,proxy_cipher,proxy_mask,updated_by) VALUES ('proxy',?,?,?) "
                  + "ON CONFLICT(id) DO UPDATE SET proxy_cipher=EXCLUDED.proxy_cipher,proxy_mask=EXCLUDED.proxy_mask,"
                  + "updated_by=EXCLUDED.updated_by,updated_at=now()",
              ProviderCrypto.encrypt(master, url),
              proxyMask(url),
              actor);
          audit(actor, "NETWORK_PROXY_SET", "proxy");
        });
  }

  public void clearProxy(String actor) {
    tx.executeWithoutResult(
        status -> {
          jdbc.update("DELETE FROM network_settings WHERE id='proxy'");
          audit(actor, "NETWORK_PROXY_CLEARED", "proxy");
        });
  }

  private void audit(String actor, String action, String resource) {
    jdbc.update(
        "INSERT INTO audit_events(id,actor_id,action,resource_id,correlation_id) VALUES (?,?,?,?,?)",
        UUID.randomUUID().toString(),
        actor,
        action,
        resource,
        UUID.randomUUID().toString());
  }
}
