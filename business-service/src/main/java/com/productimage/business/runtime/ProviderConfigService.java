package com.productimage.business.runtime;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.node.ObjectNode;
import java.net.URI;
import java.net.URISyntaxException;
import java.sql.Timestamp;
import java.util.HashMap;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.Set;
import java.util.UUID;
import org.springframework.core.env.Environment;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.transaction.support.TransactionTemplate;

/**
 * Admin-managed model catalog. Since ADR-20261012-AB (user decision) it has two levels, as in Dify:
 * model interfaces (OpenRouter, official OpenAI / DeepSeek / Gemini, OpenAI-protocol third parties)
 * hold the key, address and proxy setting once, and the models under them hold the model id,
 * purpose and the official parameters the admin filled in. Several models can be enabled; operators
 * choose one per task and the admin marks a default per purpose. Models and interfaces are edited
 * in place - submitted tasks use the edited settings (ADR-20261009-Q). Keys and the proxy URL are
 * encrypted under the external master key and are never echoed or logged.
 */
public final class ProviderConfigService {
  // IMAGE models generate pictures; TEXT models analyse images and rewrite briefs.
  static final Set<String> PURPOSES = Set.of("IMAGE", "TEXT");
  private static final Set<String> INTERFACE_FIELDS =
      Set.of("name", "kind", "api_key", "use_proxy");
  private static final Set<String> INTERFACE_EDITABLE =
      Set.of("name", "base_url", "api_key", "use_proxy");
  private static final Set<String> MODEL_FIELDS =
      Set.of("interface_id", "name", "model", "enabled");
  private static final Set<String> MODEL_OPTIONAL =
      Set.of("purpose", "provider_tag", "vision", "parameters");
  // Fields an edit may change; the purpose and the interface are fixed for a model's lifetime.
  private static final Set<String> MODEL_EDITABLE =
      Set.of("name", "model", "provider_tag", "vision", "enabled", "parameters");
  private final JdbcTemplate jdbc;
  private final TransactionTemplate tx;
  private final byte[] master;

  ProviderConfigService(JdbcTemplate jdbc, TransactionTemplate tx, Environment env) {
    this(
        jdbc,
        tx,
        // The master key is only required once a secret is stored or read; absence disables
        // those operations safely instead of falling back to worker environment credentials.
        env.getProperty("PROVIDER_MASTER_KEY", "").isBlank()
                && env.getProperty("PROVIDER_MASTER_KEY_FILE", "").isBlank()
            ? null
            : ProviderCrypto.masterKey(
                env.getProperty("PROVIDER_MASTER_KEY", ""),
                env.getProperty("PROVIDER_MASTER_KEY_FILE", "")));
  }

  ProviderConfigService(JdbcTemplate jdbc, TransactionTemplate tx, byte[] master) {
    this.jdbc = jdbc;
    this.tx = tx;
    this.master = master;
  }

  private String defaultId() {
    return defaultId("IMAGE");
  }

  /** The default per purpose: state row 'active' for pictures, 'text' for text models. */
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
   * Text model for the look-first analysis and the magic wand (ADR-20261008-L): the text default
   * when usable, otherwise the first enabled text model; null when none is configured.
   */
  String textBinding() {
    String chosen = defaultId("TEXT");
    var rows =
        jdbc.queryForList(
            "SELECT id FROM provider_config_versions WHERE enabled AND NOT retired AND purpose='TEXT' ORDER BY (id=?) DESC,created_at,id LIMIT 1",
            chosen == null ? "" : chosen);
    return rows.isEmpty() ? null : rows.getFirst().get("id").toString();
  }

  /** Whether a text model can look at images (ADR-20261012-AB). */
  boolean vision(String versionId) {
    return Boolean.TRUE.equals(
        jdbc.queryForObject(
            "SELECT vision FROM provider_config_versions WHERE id=?", Boolean.class, versionId));
  }

  /** Leased workers receive the decrypted binding; failures must not fall back silently. */
  JsonNode claimConfig(String versionId) {
    if (master == null) throw new Problem(503, "PROVIDER_UNAVAILABLE");
    var rows =
        jdbc.queryForList(
            "SELECT i.kind,v.model,v.provider_tag,i.base_url,i.api_key_cipher,i.use_proxy,v.parameters "
                + "FROM provider_config_versions v JOIN model_interfaces i ON i.id=v.interface_id WHERE v.id=?",
            versionId);
    if (rows.isEmpty()) throw new Problem(503, "PROVIDER_UNAVAILABLE");
    var row = rows.getFirst();
    try {
      var config =
          Json.object()
              .put("provider", row.get("kind").toString())
              .put("model", row.get("model").toString());
      optional(config, "provider_tag", row.get("provider_tag"));
      optional(config, "base_url", row.get("base_url"));
      config.set("parameters", Json.parse(row.get("parameters").toString()));
      config.put("api_key", ProviderCrypto.decrypt(master, row.get("api_key_cipher").toString()));
      // Only interfaces marked "use proxy" leave through it; without a saved proxy they go direct.
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

  private static boolean thirdParty(String kind) {
    return kind.endsWith("-compatible");
  }

  private static Set<String> names(JsonNode body) {
    var names = new HashSet<String>();
    body.fieldNames().forEachRemaining(names::add);
    return names;
  }

  /**
   * A model interface: exactly its type's fields in their shapes. Only the offered types can be
   * created; a stored older type (gemini-compatible) still validates on edit.
   */
  static void validateInterface(JsonNode body, boolean creating) {
    String kind = body.path("kind").asText();
    if (!body.isObject() || ModelParameters.kind(kind).isMissingNode())
      throw new Problem(400, "INVALID_CONTRACT");
    var expected = new HashSet<>(INTERFACE_FIELDS);
    if (thirdParty(kind)) expected.add("base_url");
    if (!names(body).equals(expected)
        || (creating && !ModelParameters.offered(kind))
        || !validName(body.path("name"))
        || !body.path("use_proxy").isBoolean()
        || !validKey(body.path("api_key"))
        || (body.has("base_url")
            && !(body.path("base_url").isTextual()
                && validBaseUrl(body.path("base_url").asText()))))
      throw new Problem(400, "INVALID_CONTRACT");
  }

  /**
   * A model under an interface of this type: exactly the model fields, each in its shape. DeepSeek
   * serves text only; OpenRouter ids are vendor/model and its image models pin a provider (a text
   * model may leave routing to OpenRouter); other types have no routing tag. Only the parameters
   * the matching set lists, with valid values (ADR-20261012-AB).
   */
  static void validateModel(String kind, JsonNode body) {
    if (!body.isObject()) throw new Problem(400, "INVALID_CONTRACT");
    var names = names(body);
    var allowed = new HashSet<>(MODEL_FIELDS);
    allowed.addAll(MODEL_OPTIONAL);
    String purpose = body.path("purpose").asText("IMAGE");
    String model = body.path("model").asText();
    boolean openrouter = kind.equals("openrouter");
    if (!names.containsAll(MODEL_FIELDS)
        || !allowed.containsAll(names)
        || !body.path("interface_id").isTextual()
        || !validName(body.path("name"))
        || !body.path("enabled").isBoolean()
        || !body.path("model").isTextual()
        || !model.matches("[A-Za-z0-9][A-Za-z0-9_./:-]{0,199}")
        || !PURPOSES.contains(purpose)
        || (body.has("purpose") && !body.path("purpose").isTextual())
        || !ModelParameters.serves(kind, purpose)
        || (openrouter && !model.matches("[a-zA-Z0-9_-]+/[a-zA-Z0-9_.:-]+"))
        || (body.has("provider_tag") && !openrouter)
        || (openrouter && purpose.equals("IMAGE") && !body.has("provider_tag"))
        || (body.has("provider_tag")
            && !body.path("provider_tag").asText().matches("[a-zA-Z0-9_./-]{1,100}"))
        || (body.has("vision") && (!body.path("vision").isBoolean() || !purpose.equals("TEXT"))))
      throw new Problem(400, "INVALID_CONTRACT");
    if (body.has("parameters"))
      ModelParameters.validate(kind, model, purpose, body.get("parameters"));
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
    var item =
        Json.object()
            .put("id", row.get("id").toString())
            .put("interface_id", row.get("interface_id").toString())
            .put("name", row.get("name").toString())
            // The interface's type, address, key mask and proxy setting, read-only here.
            .put("provider", row.get("kind").toString())
            .put("model", row.get("model").toString());
    optional(item, "provider_tag", row.get("provider_tag"));
    optional(item, "base_url", row.get("base_url"));
    item.set("parameters", Json.parse(row.get("parameters").toString()));
    return item.put("api_key_mask", row.get("api_key_mask").toString())
        .put("purpose", purpose)
        .put("vision", Boolean.TRUE.equals(row.get("vision")))
        .put("enabled", Boolean.TRUE.equals(row.get("enabled")))
        .put("use_proxy", Boolean.TRUE.equals(row.get("use_proxy")))
        .put("default", row.get("id").toString().equals(defaultId(purpose)))
        .put("created_at", ((Timestamp) row.get("created_at")).toInstant().toString());
  }

  private static ObjectNode interfaceItem(Map<String, Object> row) {
    var item =
        Json.object()
            .put("id", row.get("id").toString())
            .put("name", row.get("name").toString())
            .put("kind", row.get("kind").toString());
    optional(item, "base_url", row.get("base_url"));
    return item.put("api_key_mask", row.get("api_key_mask").toString())
        .put("use_proxy", Boolean.TRUE.equals(row.get("use_proxy")))
        .put("created_at", ((Timestamp) row.get("created_at")).toInstant().toString());
  }

  private static final String MODEL_COLUMNS =
      "v.id,v.interface_id,v.name,i.kind,v.model,v.provider_tag,i.base_url,i.api_key_mask,v.enabled,i.use_proxy,v.created_at,v.purpose,v.vision,v.parameters";
  private static final String MODEL_FROM =
      " FROM provider_config_versions v JOIN model_interfaces i ON i.id=v.interface_id";
  private static final String INTERFACE_COLUMNS =
      "id,name,kind,base_url,api_key_mask,use_proxy,created_at";

  private ObjectNode modelItem(String id) {
    return item(jdbc.queryForMap("SELECT " + MODEL_COLUMNS + MODEL_FROM + " WHERE v.id=?", id));
  }

  public JsonNode list() {
    var result = Json.object();
    String defaultId = defaultId();
    if (defaultId == null) result.putNull("default_id");
    else result.put("default_id", defaultId);
    String textDefault = defaultId("TEXT");
    if (textDefault == null) result.putNull("text_default_id");
    else result.put("text_default_id", textDefault);
    var interfaces = result.putArray("interfaces");
    for (var row :
        jdbc.queryForList(
            "SELECT " + INTERFACE_COLUMNS + " FROM model_interfaces ORDER BY created_at,id"))
      interfaces.add(interfaceItem(row));
    var items = result.putArray("items");
    for (var row :
        jdbc.queryForList(
            "SELECT "
                + MODEL_COLUMNS
                + MODEL_FROM
                + " WHERE NOT v.retired ORDER BY v.created_at,v.id")) items.add(item(row));
    result.set("proxy", proxy());
    return result;
  }

  /**
   * Enabled models for the generation pages: names only, never keys or routing details, and the
   * clarities (1K / 2K) the pages may offer with the starting one (ADR-20261012-AB: the first the
   * model offers; clarity is no longer a model setting).
   */
  public JsonNode choices() {
    var result = Json.MAPPER.createArrayNode();
    String defaultId = defaultId();
    for (var row :
        jdbc.queryForList(
            "SELECT v.id,v.name,i.kind,v.model"
                + MODEL_FROM
                + " WHERE v.enabled AND NOT v.retired AND v.purpose='IMAGE' ORDER BY v.created_at,v.id")) {
      String kind = row.get("kind").toString();
      String model = row.get("model").toString();
      var item =
          Json.object()
              .put("id", row.get("id").toString())
              .put("name", row.get("name").toString())
              .put("provider", kind)
              .put("model", model)
              .put("default", row.get("id").toString().equals(defaultId));
      var offered = item.putArray("resolutions");
      ModelParameters.resolutions(kind, model, "IMAGE").forEach(offered::add);
      String start = ModelParameters.defaultResolution(kind, model, "IMAGE");
      if (start != null) item.put("resolution", start);
      result.add(item);
    }
    return result;
  }

  /** The clarities a bound model can be asked for (ADR-20261009-R). */
  java.util.List<String> resolutions(String versionId) {
    var rows =
        jdbc.queryForList(
            "SELECT i.kind,v.model,v.purpose" + MODEL_FROM + " WHERE v.id=?", versionId);
    if (rows.isEmpty()) return java.util.List.of();
    var row = rows.getFirst();
    return ModelParameters.resolutions(
        row.get("kind").toString(), row.get("model").toString(), row.get("purpose").toString());
  }

  private void requireMaster() {
    if (master == null) throw new Problem(503, "PROVIDER_UNAVAILABLE");
  }

  private Map<String, Object> live(String id, boolean lock) {
    var rows =
        jdbc.queryForList(
            "SELECT v.*,i.kind"
                + MODEL_FROM
                + " WHERE v.id=? AND NOT v.retired"
                + (lock ? " FOR UPDATE OF v" : ""),
            id);
    if (rows.isEmpty()) throw new Problem(404, "NOT_FOUND");
    return rows.getFirst();
  }

  private Map<String, Object> liveInterface(String id, boolean lock) {
    var rows =
        jdbc.queryForList(
            "SELECT * FROM model_interfaces WHERE id=?" + (lock ? " FOR UPDATE" : ""), id);
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

  /** New model interface: its key is stored encrypted once for all its models. */
  public JsonNode createInterface(String actor, JsonNode body) {
    validateInterface(body, true);
    requireMaster();
    String key = body.path("api_key").asText();
    return tx.execute(
        status -> {
          String id = UUID.randomUUID().toString();
          jdbc.update(
              "INSERT INTO model_interfaces(id,name,kind,base_url,api_key_cipher,api_key_mask,use_proxy,created_by) VALUES (?,?,?,?,?,?,?,?)",
              id,
              body.path("name").asText().strip(),
              body.path("kind").asText(),
              body.has("base_url") ? body.path("base_url").asText() : null,
              ProviderCrypto.encrypt(master, key),
              ProviderCrypto.mask(key),
              body.path("use_proxy").asBoolean(),
              actor);
          audit(actor, "MODEL_INTERFACE_CREATED", id);
          return interfaceItem(
              jdbc.queryForMap(
                  "SELECT " + INTERFACE_COLUMNS + " FROM model_interfaces WHERE id=?", id));
        });
  }

  /**
   * Edit an interface in place: name, address (third parties), a new key, proxy setting. Its type
   * never changes. Every model under it, and their submitted tasks, use the new settings at once.
   */
  public void updateInterface(String actor, String id, JsonNode body) {
    if (!body.isObject() || body.isEmpty() || !INTERFACE_EDITABLE.containsAll(names(body)))
      throw new Problem(400, "INVALID_CONTRACT");
    if (body.has("api_key")) requireMaster();
    tx.executeWithoutResult(
        status -> {
          var row = liveInterface(id, true);
          var merged =
              Json.object()
                  .put("name", row.get("name").toString())
                  .put("kind", row.get("kind").toString())
                  .put("use_proxy", Boolean.TRUE.equals(row.get("use_proxy")))
                  // Stands in for the stored key during the checks; never written.
                  .put("api_key", "unchanged");
          optional(merged, "base_url", row.get("base_url"));
          body.properties().forEach(entry -> merged.set(entry.getKey(), entry.getValue()));
          validateInterface(merged, false);
          jdbc.update(
              "UPDATE model_interfaces SET name=?,base_url=?,use_proxy=?,updated_at=now() WHERE id=?",
              merged.path("name").asText().strip(),
              merged.has("base_url") ? merged.path("base_url").asText() : null,
              merged.path("use_proxy").asBoolean(),
              id);
          if (body.has("api_key"))
            jdbc.update(
                "UPDATE model_interfaces SET api_key_cipher=?,api_key_mask=? WHERE id=?",
                ProviderCrypto.encrypt(master, body.path("api_key").asText()),
                ProviderCrypto.mask(body.path("api_key").asText()),
                id);
          audit(actor, "MODEL_INTERFACE_UPDATED", id);
        });
  }

  /** Delete an interface that has no models left (409 INTERFACE_IN_USE otherwise). */
  public void deleteInterface(String actor, String id) {
    tx.executeWithoutResult(
        status -> {
          liveInterface(id, true);
          if (jdbc.queryForObject(
                  "SELECT count(*) FROM provider_config_versions WHERE interface_id=?",
                  Long.class,
                  id)
              > 0) throw new Problem(409, "INTERFACE_IN_USE");
          jdbc.update("DELETE FROM model_interfaces WHERE id=?", id);
          audit(actor, "MODEL_INTERFACE_DELETED", id);
        });
  }

  private String interfaceKind(JsonNode interfaceId) {
    if (!interfaceId.isTextual()) throw new Problem(400, "INVALID_CONTRACT");
    var rows =
        jdbc.queryForList("SELECT kind FROM model_interfaces WHERE id=?", interfaceId.asText());
    if (rows.isEmpty()) throw new Problem(400, "INVALID_CONTRACT");
    return rows.getFirst().get("kind").toString();
  }

  public JsonNode create(String actor, JsonNode body) {
    if (!body.isObject()) throw new Problem(400, "INVALID_CONTRACT");
    return tx.execute(
        status -> {
          String kind = interfaceKind(body.path("interface_id"));
          validateModel(kind, body);
          String id = UUID.randomUUID().toString();
          String purpose = body.path("purpose").asText("IMAGE");
          jdbc.update(
              "INSERT INTO provider_config_versions(id,interface_id,name,model,provider_tag,enabled,created_by,purpose,vision,parameters) VALUES (?,?,?,?,?,?,?,?,?,?::jsonb)",
              id,
              body.path("interface_id").asText(),
              body.path("name").asText().strip(),
              body.path("model").asText(),
              body.has("provider_tag") ? body.path("provider_tag").asText() : null,
              body.path("enabled").asBoolean(),
              actor,
              purpose,
              body.path("vision").asBoolean(false),
              body.has("parameters") ? body.get("parameters").toString() : "{}");
          // The first usable model becomes the default so generation works right away.
          if (body.path("enabled").asBoolean()) {
            String current = defaultId(purpose);
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
          return modelItem(id);
        });
  }

  /**
   * Edit a model in place (ADR-20261009-Q): any of name, model, provider_tag, vision, enabled and
   * parameters; a null tag removes it. The result must pass the same checks as a new model.
   * Submitted tasks use the edited settings. The default cannot be disabled; the purpose and the
   * interface never change.
   */
  public void update(String actor, String id, JsonNode body) {
    if (!body.isObject() || body.isEmpty() || !MODEL_EDITABLE.containsAll(names(body)))
      throw new Problem(400, "INVALID_CONTRACT");
    tx.executeWithoutResult(
        status -> {
          var row = live(id, true);
          String purpose = row.get("purpose").toString();
          String kind = row.get("kind").toString();
          var merged =
              Json.object()
                  .put("interface_id", row.get("interface_id").toString())
                  .put("name", row.get("name").toString())
                  .put("model", row.get("model").toString())
                  .put("enabled", Boolean.TRUE.equals(row.get("enabled")))
                  .put("purpose", purpose);
          if (purpose.equals("TEXT")) merged.put("vision", Boolean.TRUE.equals(row.get("vision")));
          optional(merged, "provider_tag", row.get("provider_tag"));
          merged.set("parameters", Json.parse(row.get("parameters").toString()));
          // Another model family has other parameters; unless new ones are given, start empty.
          if (body.has("model")
              && !body.has("parameters")
              && !ModelParameters.set(kind, body.path("model").asText(), purpose)
                  .path("id")
                  .equals(
                      ModelParameters.set(kind, row.get("model").toString(), purpose).path("id")))
            merged.set("parameters", Json.object());
          body.properties()
              .forEach(
                  entry -> {
                    if (entry.getValue().isNull() && entry.getKey().equals("provider_tag"))
                      merged.remove(entry.getKey());
                    else merged.set(entry.getKey(), entry.getValue());
                  });
          validateModel(kind, merged);
          if (!merged.path("enabled").asBoolean() && id.equals(defaultId(purpose)))
            throw new Problem(409, "DEFAULT_MODEL");
          jdbc.update(
              "UPDATE provider_config_versions SET name=?,model=?,provider_tag=?,enabled=?,vision=?,parameters=?::jsonb WHERE id=?",
              merged.path("name").asText().strip(),
              merged.path("model").asText(),
              merged.has("provider_tag") ? merged.path("provider_tag").asText() : null,
              merged.path("enabled").asBoolean(),
              merged.path("vision").asBoolean(false),
              merged.get("parameters").toString(),
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

  private static final Map<String, String> KIND_LABELS =
      Map.of(
          "openrouter", "OpenRouter",
          "openai", "OpenAI 官方",
          "deepseek", "DeepSeek 官方",
          "gemini", "Gemini 官方",
          "openai-compatible", "OpenAI 协议第三方",
          "gemini-compatible", "Gemini 格式第三方");

  /** Runs once the service exists: see {@link #mergeMigratedInterfaces(JdbcTemplate, ...)}. */
  void mergeMigratedInterfaces() {
    mergeMigratedInterfaces(jdbc, tx, master);
  }

  /**
   * V21 gave every existing model its own interface, because keys only compare decrypted. With the
   * master key, the interfaces it made are merged when type, address, proxy setting and key are the
   * same - as if the admin had entered the key once - and one left alone for its type is named
   * after the type (ADR-20261012-AB). Without the master key nothing changes; models work either
   * way. Runs once: the marks are cleared.
   */
  static void mergeMigratedInterfaces(JdbcTemplate jdbc, TransactionTemplate tx, byte[] master) {
    if (master == null) return;
    tx.executeWithoutResult(
        status -> {
          var rows =
              jdbc.queryForList(
                  "SELECT id,kind,base_url,use_proxy,api_key_cipher FROM model_interfaces WHERE merge_pending ORDER BY created_at,id FOR UPDATE");
          if (rows.isEmpty()) return;
          var kept = new LinkedHashMap<String, String>();
          for (var row : rows) {
            String key;
            try {
              key = ProviderCrypto.decrypt(master, row.get("api_key_cipher").toString());
            } catch (IllegalStateException ex) {
              continue; // left as it is: its own interface still works with its own key
            }
            String group =
                String.join(
                    "\n",
                    row.get("kind").toString(),
                    String.valueOf(row.get("base_url")),
                    String.valueOf(row.get("use_proxy")),
                    key);
            String into = kept.putIfAbsent(group, row.get("id").toString());
            if (into != null) {
              jdbc.update(
                  "UPDATE provider_config_versions SET interface_id=? WHERE interface_id=?",
                  into,
                  row.get("id"));
              jdbc.update("DELETE FROM model_interfaces WHERE id=?", row.get("id"));
            }
          }
          var perKind = new HashMap<String, Integer>();
          for (var row :
              jdbc.queryForList("SELECT kind,count(*) AS n FROM model_interfaces GROUP BY kind"))
            perKind.put(row.get("kind").toString(), ((Number) row.get("n")).intValue());
          for (String id : kept.values()) {
            String kind =
                jdbc.queryForObject(
                    "SELECT kind FROM model_interfaces WHERE id=?", String.class, id);
            if (perKind.getOrDefault(kind, 0) == 1)
              jdbc.update(
                  "UPDATE model_interfaces SET name=? WHERE id=?", KIND_LABELS.get(kind), id);
          }
          jdbc.update("UPDATE model_interfaces SET merge_pending=false WHERE merge_pending");
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
