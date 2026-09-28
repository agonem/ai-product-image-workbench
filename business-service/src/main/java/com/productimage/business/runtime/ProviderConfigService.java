package com.productimage.business.runtime;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.node.ObjectNode;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.sql.Timestamp;
import java.time.Duration;
import java.util.UUID;
import org.springframework.core.env.Environment;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.transaction.support.TransactionTemplate;

/**
 * Admin-managed OpenRouter configuration. Versions are append-only; new tasks bind the active
 * enabled version, retries keep their frozen binding, and the key is never echoed or logged.
 */
public final class ProviderConfigService {
  private final JdbcTemplate jdbc;
  private final TransactionTemplate tx;
  private final byte[] master;
  private final String checkUrl;
  private final String checkToken;
  private final HttpClient http;

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
    this.checkUrl = env.getProperty("IMAGE_CHECK_URL", "").strip();
    this.checkToken = env.getProperty("IMAGE_CHECK_TOKEN", "");
    if (checkUrl.isBlank() != checkToken.isBlank()
        || (!checkUrl.isBlank()
            && !checkUrl.matches(
                "https?://[A-Za-z0-9.:\\[\\]-]+(:[0-9]{1,5})?(/[A-Za-z0-9._~-]*)*")))
      throw new IllegalStateException("Provider check requires a plain base URL and shared token");
    this.http =
        HttpClient.newBuilder()
            .followRedirects(HttpClient.Redirect.NEVER)
            .connectTimeout(Duration.ofSeconds(10))
            .build();
  }

  /**
   * Binding for new scene tasks. No state row keeps the explicit worker environment path; an
   * existing but disabled state rejects creation instead of silently falling back to environment
   * credentials, and queued or retrying tasks always keep their frozen binding.
   */
  String sceneBinding() {
    var rows =
        jdbc.queryForList(
            "SELECT active_version_id,enabled FROM provider_config_state WHERE provider='openrouter'");
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
            "SELECT provider,model,provider_tag,api_key_cipher FROM provider_config_versions WHERE id=?",
            versionId);
    if (rows.isEmpty()) throw new Problem(503, "PROVIDER_UNAVAILABLE");
    var row = rows.getFirst();
    try {
      return Json.object()
          .put("provider", row.get("provider").toString())
          .put("model", row.get("model").toString())
          .put("provider_tag", row.get("provider_tag").toString())
          .put("api_key", ProviderCrypto.decrypt(master, row.get("api_key_cipher").toString()));
    } catch (IllegalStateException ex) {
      throw new Problem(503, "PROVIDER_UNAVAILABLE");
    }
  }

  public JsonNode list() {
    var result = Json.object().put("provider", "openrouter");
    var state =
        jdbc.queryForList(
            "SELECT active_version_id,enabled FROM provider_config_state WHERE provider='openrouter'");
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
            "SELECT id,model,provider_tag,api_key_mask,created_at FROM provider_config_versions WHERE provider='openrouter' ORDER BY created_at,id")) {
      var item =
          Json.object()
              .put("id", row.get("id").toString())
              .put("model", row.get("model").toString())
              .put("provider_tag", row.get("provider_tag").toString())
              .put("api_key_mask", row.get("api_key_mask").toString())
              .put("created_at", ((Timestamp) row.get("created_at")).toInstant().toString());
      if (row.get("id").toString().equals(active)) item.put("active", true);
      items.add(item);
    }
    return result;
  }

  public JsonNode create(String actor, JsonNode body) {
    String provider = body.path("provider").asText();
    String model = body.path("model").asText();
    String tag = body.path("provider_tag").asText();
    String key = body.path("api_key").asText();
    if (body.size() != 5
        || !body.path("enabled").isBoolean()
        || !provider.equals("openrouter")
        || !model.matches("[a-zA-Z0-9_-]+/[a-zA-Z0-9_.:-]+")
        || !tag.matches("[a-zA-Z0-9_./-]{1,100}")
        || !key.matches("[\\x21-\\x7e]{1,4096}")) throw new Problem(400, "INVALID_CONTRACT");
    if (master == null) throw new Problem(503, "PROVIDER_UNAVAILABLE");
    return tx.execute(
        status -> {
          String id = UUID.randomUUID().toString();
          jdbc.update(
              "INSERT INTO provider_config_versions(id,provider,model,provider_tag,api_key_cipher,api_key_mask,created_by) VALUES (?,?,?,?,?,?,?)",
              id,
              provider,
              model,
              tag,
              ProviderCrypto.encrypt(master, key),
              ProviderCrypto.mask(key),
              actor);
          jdbc.update(
              "INSERT INTO provider_config_state(provider,active_version_id,enabled) VALUES ('openrouter',?,?) "
                  + "ON CONFLICT(provider) DO UPDATE SET active_version_id=EXCLUDED.active_version_id,enabled=EXCLUDED.enabled,updated_at=now()",
              id,
              body.path("enabled").asBoolean());
          audit(actor, "PROVIDER_CONFIG_CREATED", id);
          return Json.object()
              .put("id", id)
              .put("model", model)
              .put("provider_tag", tag)
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
                  "SELECT active_version_id FROM provider_config_state WHERE provider='openrouter' FOR UPDATE");
          if (rows.isEmpty() || !id.equals(rows.getFirst().get("active_version_id").toString()))
            throw new Problem(400, "INVALID_CONTRACT");
          jdbc.update(
              "UPDATE provider_config_state SET enabled=?,updated_at=now() WHERE provider='openrouter'",
              body.path("enabled").asBoolean());
          audit(actor, "PROVIDER_CONFIG_STATUS", id);
        });
  }

  /** Non-paid capability GET through the image service; the key is forwarded, never stored. */
  public JsonNode check(String actor, String id) {
    JsonNode config = claimConfig(id);
    if (checkUrl.isBlank()) throw new Problem(503, "PROVIDER_UNAVAILABLE");
    HttpRequest request;
    try {
      request =
          HttpRequest.newBuilder(URI.create(checkUrl + "/internal/v1/provider/check"))
              .timeout(Duration.ofSeconds(20))
              .header("Authorization", "Bearer " + checkToken)
              .header("Content-Type", "application/json")
              .POST(HttpRequest.BodyPublishers.ofString(Json.MAPPER.writeValueAsString(config)))
              .build();
    } catch (Exception ex) {
      throw new Problem(503, "PROVIDER_UNAVAILABLE");
    }
    HttpResponse<String> response;
    try {
      response = http.send(request, HttpResponse.BodyHandlers.ofString());
    } catch (Exception ex) {
      audit(actor, "PROVIDER_CONFIG_CHECK_FAILED", id);
      throw new Problem(503, "PROVIDER_UNAVAILABLE");
    }
    if (response.statusCode() != 200 || response.body().length() > 1048576)
      throw new Problem(503, "PROVIDER_UNAVAILABLE");
    JsonNode result;
    try {
      result = Json.parse(response.body());
    } catch (Exception ex) {
      throw new Problem(503, "PROVIDER_UNAVAILABLE");
    }
    audit(actor, "PROVIDER_CONFIG_CHECK", id);
    return result;
  }

  /**
   * Single PAID background probe for administrators. Requires the explicit confirmation phrase;
   * saving configurations, listing, or the non-paid check never reach it, and the returned test
   * image is not stored or published.
   */
  public JsonNode testGenerate(String actor, String id, JsonNode body) {
    if (body.size() != 2
        || !"PAID_TEST".equals(body.path("confirm").asText())
        || !body.path("aspect_ratio").asText().matches("[1-9][0-9]?:[1-9][0-9]?"))
      throw new Problem(400, "INVALID_CONTRACT");
    JsonNode config = claimConfig(id);
    if (checkUrl.isBlank()) throw new Problem(503, "PROVIDER_UNAVAILABLE");
    ObjectNode payload = (ObjectNode) config;
    payload
        .put(
            "prompt",
            "Internal paid connectivity test. Plain soft gradient background only; "
                + "no objects, products, people, logos or text.")
        .put("aspect_ratio", body.path("aspect_ratio").asText());
    HttpRequest request;
    try {
      request =
          HttpRequest.newBuilder(URI.create(checkUrl + "/internal/v1/provider/test"))
              .timeout(Duration.ofSeconds(240))
              .header("Authorization", "Bearer " + checkToken)
              .header("Content-Type", "application/json")
              .POST(HttpRequest.BodyPublishers.ofString(Json.MAPPER.writeValueAsString(payload)))
              .build();
    } catch (Exception ex) {
      throw new Problem(503, "PROVIDER_UNAVAILABLE");
    }
    HttpResponse<byte[]> response;
    try {
      response = http.send(request, HttpResponse.BodyHandlers.ofByteArray());
    } catch (Exception ex) {
      audit(actor, "PROVIDER_CONFIG_PAID_TEST_FAILED", id);
      throw new Problem(503, "PROVIDER_UNAVAILABLE");
    }
    if (response.statusCode() != 200 || response.body().length > 33554432)
      throw new Problem(503, "PROVIDER_UNAVAILABLE");
    JsonNode result;
    try {
      result = Json.parse(new String(response.body(), java.nio.charset.StandardCharsets.UTF_8));
    } catch (Exception ex) {
      throw new Problem(503, "PROVIDER_UNAVAILABLE");
    }
    audit(actor, "PROVIDER_CONFIG_PAID_TEST", id);
    return result;
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
