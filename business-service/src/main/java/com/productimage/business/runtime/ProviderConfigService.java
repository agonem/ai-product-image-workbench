package com.productimage.business.runtime;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.node.ObjectNode;
import java.net.URI;
import java.net.URISyntaxException;
import java.sql.Timestamp;
import java.util.Arrays;
import java.util.HashSet;
import java.util.Map;
import java.util.Set;
import java.util.UUID;
import org.springframework.core.env.Environment;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.transaction.support.TransactionTemplate;

/**
 * Admin-managed model configuration (OpenRouter, official OpenAI / Gemini, or third-party endpoints
 * in either format). Versions are append-only; new tasks bind the single active enabled version,
 * retries keep their frozen binding, and the key is never echoed or logged.
 */
public final class ProviderConfigService {
  static final Set<String> PROVIDERS =
      Set.of("openrouter", "openai", "gemini", "openai-compatible", "gemini-compatible");
  private static final Map<String, Set<String>> FIELDS =
      Map.of(
          "openrouter", Set.of("provider", "model", "provider_tag", "api_key", "enabled"),
          "openai", Set.of("provider", "model", "api_key", "enabled"),
          "gemini", Set.of("provider", "model", "api_key", "enabled"),
          "openai-compatible", Set.of("provider", "model", "base_url", "api_key", "enabled"),
          "gemini-compatible", Set.of("provider", "model", "base_url", "api_key", "enabled"));

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

  /**
   * Binding for new scene tasks. No state row keeps the explicit worker environment path; an
   * existing but disabled state rejects creation instead of silently falling back to environment
   * credentials, and queued or retrying tasks always keep their frozen binding.
   */
  String sceneBinding() {
    var rows =
        jdbc.queryForList(
            "SELECT active_version_id,enabled FROM provider_config_state WHERE provider='active'");
    if (rows.isEmpty()) return null;
    if (!Boolean.TRUE.equals(rows.getFirst().get("enabled")))
      throw new Problem(503, "PROVIDER_DISABLED");
    Object version = rows.getFirst().get("active_version_id");
    if (version == null) throw new Problem(503, "PROVIDER_UNAVAILABLE");
    return version.toString();
  }

  /** Leased workers receive the decrypted binding; failures must not fall back silently. */
  JsonNode claimConfig(String versionId) {
    if (master == null) throw new Problem(503, "PROVIDER_UNAVAILABLE");
    var rows =
        jdbc.queryForList(
            "SELECT provider,model,provider_tag,base_url,api_key_cipher FROM provider_config_versions WHERE id=?",
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
      return config.put(
          "api_key", ProviderCrypto.decrypt(master, row.get("api_key_cipher").toString()));
    } catch (IllegalStateException ex) {
      throw new Problem(503, "PROVIDER_UNAVAILABLE");
    }
  }

  private static void optional(ObjectNode target, String field, Object value) {
    if (value != null) target.put(field, value.toString());
  }

  /**
   * Third-party base URL: https anywhere, or http only to a literal private IPv4 address (intranet
   * relays; the key then crosses the LAN unencrypted). No credentials, query or fragment.
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
      int[] ip = Arrays.stream(host.split("\\.")).mapToInt(Integer::parseInt).toArray();
      if (Arrays.stream(ip).anyMatch(part -> part > 255)) return false;
      return ip[0] == 10
          || (ip[0] == 172 && ip[1] >= 16 && ip[1] <= 31)
          || (ip[0] == 192 && ip[1] == 168);
    } catch (URISyntaxException ex) {
      return false;
    }
  }

  /** Exactly the fields of the chosen provider type, each in its allowed shape. */
  static void validate(JsonNode body) {
    String provider = body.path("provider").asText();
    if (!body.isObject() || !PROVIDERS.contains(provider))
      throw new Problem(400, "INVALID_CONTRACT");
    var names = new HashSet<String>();
    body.fieldNames().forEachRemaining(names::add);
    String model = body.path("model").asText();
    if (!names.equals(FIELDS.get(provider))
        || !body.path("enabled").isBoolean()
        || !body.path("model").isTextual()
        || !body.path("api_key").isTextual()
        || !model.matches("[A-Za-z0-9][A-Za-z0-9_./:-]{0,199}")
        || (provider.equals("openrouter") && !model.matches("[a-zA-Z0-9_-]+/[a-zA-Z0-9_.:-]+"))
        || (body.has("provider_tag")
            && !body.path("provider_tag").asText().matches("[a-zA-Z0-9_./-]{1,100}"))
        || (body.has("base_url") && !validBaseUrl(body.path("base_url").asText()))
        || !body.path("api_key").asText().matches("[\\x21-\\x7e]{1,4096}"))
      throw new Problem(400, "INVALID_CONTRACT");
  }

  public JsonNode list() {
    var result = Json.object();
    var state =
        jdbc.queryForList(
            "SELECT active_version_id,enabled FROM provider_config_state WHERE provider='active'");
    boolean enabled = !state.isEmpty() && Boolean.TRUE.equals(state.getFirst().get("enabled"));
    String active =
        state.isEmpty() || state.getFirst().get("active_version_id") == null
            ? null
            : state.getFirst().get("active_version_id").toString();
    result.put("enabled", enabled);
    if (active == null) result.putNull("active_version_id");
    else result.put("active_version_id", active);
    var items = result.putArray("items");
    for (var row :
        jdbc.queryForList(
            "SELECT id,provider,model,provider_tag,base_url,api_key_mask,created_at FROM provider_config_versions ORDER BY created_at,id")) {
      var item =
          Json.object()
              .put("id", row.get("id").toString())
              .put("provider", row.get("provider").toString())
              .put("model", row.get("model").toString());
      optional(item, "provider_tag", row.get("provider_tag"));
      optional(item, "base_url", row.get("base_url"));
      item.put("api_key_mask", row.get("api_key_mask").toString())
          .put("created_at", ((Timestamp) row.get("created_at")).toInstant().toString());
      if (row.get("id").toString().equals(active)) item.put("active", true);
      items.add(item);
    }
    return result;
  }

  public JsonNode create(String actor, JsonNode body) {
    validate(body);
    String provider = body.path("provider").asText();
    String model = body.path("model").asText();
    String tag = body.has("provider_tag") ? body.path("provider_tag").asText() : null;
    String base = body.has("base_url") ? body.path("base_url").asText() : null;
    String key = body.path("api_key").asText();
    if (master == null) throw new Problem(503, "PROVIDER_UNAVAILABLE");
    return tx.execute(
        status -> {
          String id = UUID.randomUUID().toString();
          jdbc.update(
              "INSERT INTO provider_config_versions(id,provider,model,provider_tag,base_url,api_key_cipher,api_key_mask,created_by) VALUES (?,?,?,?,?,?,?,?)",
              id,
              provider,
              model,
              tag,
              base,
              ProviderCrypto.encrypt(master, key),
              ProviderCrypto.mask(key),
              actor);
          jdbc.update(
              "INSERT INTO provider_config_state(provider,active_version_id,enabled) VALUES ('active',?,?) "
                  + "ON CONFLICT(provider) DO UPDATE SET active_version_id=EXCLUDED.active_version_id,enabled=EXCLUDED.enabled,updated_at=now()",
              id,
              body.path("enabled").asBoolean());
          audit(actor, "PROVIDER_CONFIG_CREATED", id);
          var created = Json.object().put("id", id).put("provider", provider).put("model", model);
          optional(created, "provider_tag", tag);
          optional(created, "base_url", base);
          return created
              .put("api_key_mask", ProviderCrypto.mask(key))
              .put("enabled", body.path("enabled").asBoolean());
        });
  }

  public void status(String actor, String id, JsonNode body) {
    if (body.size() != 1 || !body.path("enabled").isBoolean())
      throw new Problem(400, "INVALID_CONTRACT");
    tx.executeWithoutResult(
        status -> {
          var rows =
              jdbc.queryForList(
                  "SELECT active_version_id FROM provider_config_state WHERE provider='active' FOR UPDATE");
          if (rows.isEmpty() || !id.equals(rows.getFirst().get("active_version_id").toString()))
            throw new Problem(400, "INVALID_CONTRACT");
          jdbc.update(
              "UPDATE provider_config_state SET enabled=?,updated_at=now() WHERE provider='active'",
              body.path("enabled").asBoolean());
          audit(actor, "PROVIDER_CONFIG_STATUS", id);
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
