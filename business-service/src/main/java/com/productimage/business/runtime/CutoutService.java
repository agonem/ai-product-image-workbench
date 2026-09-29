package com.productimage.business.runtime;

import com.fasterxml.jackson.databind.JsonNode;
import java.io.IOException;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.sql.Timestamp;
import java.time.Duration;
import java.util.Map;
import java.util.Set;
import java.util.concurrent.Semaphore;
import org.springframework.core.env.Environment;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.transaction.support.TransactionTemplate;

/**
 * Cutout candidates for human review (PRD-G02). Python computes a white-background alpha from the
 * original; Java stores it as a PENDING ALPHA asset of the same project. Only the owner's explicit
 * review marks it APPROVED; generation code keeps reading the latest APPROVED alpha only.
 */
public final class CutoutService {
  static final String ALGORITHM = "white-border-flood-v1";
  private static final Set<String> LOOPBACK = Set.of("127.0.0.1", "[::1]", "localhost");
  private static final int MAX_RESPONSE = 67108864;
  private final JdbcTemplate jdbc;
  private final TransactionTemplate tx;
  private final LocalObjectStore store;
  private final String url;
  private final String token;
  private final HttpClient http;
  // Bound concurrent CPU-heavy candidate requests independently of HTTP thread count.
  private final Semaphore running = new Semaphore(2);

  CutoutService(
      JdbcTemplate jdbc, TransactionTemplate tx, LocalObjectStore store, Environment env) {
    this.jdbc = jdbc;
    this.tx = tx;
    this.store = store;
    this.url = env.getProperty("IMAGE_SERVICE_URL", "").strip();
    this.token = env.getProperty("IMAGE_SERVICE_TOKEN", "");
    if (url.isBlank() != token.isBlank())
      throw new IllegalStateException("IMAGE_SERVICE_URL and IMAGE_SERVICE_TOKEN go together");
    if (!url.isBlank()) validate(url, token);
    this.http =
        HttpClient.newBuilder()
            .followRedirects(HttpClient.Redirect.NEVER)
            .connectTimeout(Duration.ofSeconds(5))
            .build();
  }

  /** HTTPS anywhere; plain HTTP only to a loopback image service on the same host. */
  static void validate(String url, String token) {
    if (!url.matches("https?://(\\[::1\\]|[A-Za-z0-9.-]+)(:[0-9]{1,5})?")
        || !token.matches("[\\x21-\\x7e]{32,512}"))
      throw new IllegalStateException("Image service needs a bare base URL and a 32+ char token");
    var host = URI.create(url).getHost();
    if (url.startsWith("http://") && (host == null || !LOOPBACK.contains(host)))
      throw new IllegalStateException("Plain HTTP is only allowed for a loopback image service");
  }

  private Map<String, Object> owned(String actor, String id) {
    var rows =
        jdbc.queryForList(
            "SELECT a.* FROM assets a JOIN projects p ON p.id=a.project_id JOIN users u ON u.id=p.owner_id WHERE a.id=? AND p.owner_id=? AND u.status='ACTIVE'",
            id,
            actor);
    if (rows.isEmpty()) throw new Problem(404, "NOT_FOUND");
    return rows.getFirst();
  }

  JsonNode create(String actor, String sourceId, JsonNode body) {
    if (!body.isObject()
        || body.size() != 1
        || !body.path("tolerance").isIntegralNumber()
        || body.path("tolerance").asInt() < 0
        || body.path("tolerance").asInt() > 32) throw new Problem(400, "INVALID_CONTRACT");
    int tolerance = body.path("tolerance").asInt();
    var source = owned(actor, sourceId);
    String kind = source.get("kind").toString();
    if (!kind.equals("PRODUCT") && !kind.equals("GIFT")) throw new Problem(422, "INVALID_ASSET");
    if (url.isBlank()) throw new Problem(503, "CUTOUT_SERVICE_UNAVAILABLE");
    byte[] original = store.read(source.get("object_key").toString());
    if (!Json.hash(original).equals(source.get("sha256"))) throw new Problem(422, "INVALID_ASSET");
    if (!running.tryAcquire()) throw new Problem(429, "CUTOUT_BUSY");
    byte[] alpha;
    try {
      alpha = candidate(original, tolerance);
    } finally {
      running.release();
    }
    int width = ((Number) source.get("width")).intValue();
    int height = ((Number) source.get("height")).intValue();
    if (!grayscalePng(alpha, width, height)) throw new Problem(503, "CUTOUT_SERVICE_UNAVAILABLE");
    String project = source.get("project_id").toString(), id = Json.id();
    var info = store.put("alphas/" + project + "/" + id + ".image", alpha);
    if (info.width() != width || info.height() != height)
      throw new Problem(503, "CUTOUT_SERVICE_UNAVAILABLE");
    return tx.execute(
        status -> {
          owned(actor, sourceId);
          jdbc.update(
              "INSERT INTO assets(id,project_id,kind,source_asset_id,object_key,sha256,width,height) VALUES (?,?,'ALPHA',?,?,?,?,?)",
              id,
              project,
              sourceId,
              info.objectKey(),
              info.sha256(),
              width,
              height);
          audit(
              actor,
              "CUTOUT_CANDIDATE_CREATED",
              id,
              Json.object()
                  .put("source_asset_id", sourceId)
                  .put("algorithm", ALGORITHM)
                  .put("tolerance", tolerance));
          return view(owned(actor, id));
        });
  }

  private byte[] candidate(byte[] original, int tolerance) {
    HttpResponse<java.io.InputStream> response;
    try {
      response =
          http.send(
              HttpRequest.newBuilder(URI.create(url + "/internal/v1/cutout?tolerance=" + tolerance))
                  .timeout(Duration.ofSeconds(60))
                  .header("Authorization", "Bearer " + token)
                  .header("Content-Type", "application/octet-stream")
                  .POST(HttpRequest.BodyPublishers.ofByteArray(original))
                  .build(),
              HttpResponse.BodyHandlers.ofInputStream());
    } catch (IOException ex) {
      throw new Problem(503, "CUTOUT_SERVICE_UNAVAILABLE");
    } catch (InterruptedException ex) {
      Thread.currentThread().interrupt();
      throw new Problem(503, "CUTOUT_SERVICE_UNAVAILABLE");
    }
    byte[] body;
    try (var input = response.body()) {
      body = input.readNBytes(MAX_RESPONSE + 1);
    } catch (IOException ex) {
      throw new Problem(503, "CUTOUT_SERVICE_UNAVAILABLE");
    }
    if (body.length > MAX_RESPONSE) throw new Problem(503, "CUTOUT_SERVICE_UNAVAILABLE");
    if (response.statusCode() == 200) return body;
    // Only whitelisted diagnostic codes cross back; any other upstream content is dropped.
    String detail = "";
    try {
      detail =
          Json.parse(new String(body, java.nio.charset.StandardCharsets.UTF_8))
              .path("detail")
              .asText("");
    } catch (RuntimeException ex) {
      /* Non-JSON upstream error: treated as unavailable below. */
    }
    if (response.statusCode() == 413 && detail.equals("CUTOUT_BUDGET"))
      throw new Problem(413, "CUTOUT_BUDGET");
    if (response.statusCode() == 422 && detail.equals("CUTOUT_NO_FOREGROUND"))
      throw new Problem(422, "CUTOUT_NO_FOREGROUND");
    if (response.statusCode() == 422 && detail.equals("INVALID_ASSET"))
      throw new Problem(422, "INVALID_ASSET");
    throw new Problem(503, "CUTOUT_SERVICE_UNAVAILABLE");
  }

  /** Format check only (PNG signature + IHDR): 8-bit grayscale with the source dimensions. */
  static boolean grayscalePng(byte[] data, int width, int height) {
    byte[] signature = {(byte) 0x89, 'P', 'N', 'G', '\r', '\n', 0x1a, '\n'};
    if (data.length < 33) return false;
    for (int i = 0; i < 8; i++) if (data[i] != signature[i]) return false;
    if (data[12] != 'I' || data[13] != 'H' || data[14] != 'D' || data[15] != 'R') return false;
    var header = java.nio.ByteBuffer.wrap(data, 16, 8);
    return header.getInt() == width && header.getInt() == height && data[24] == 8 && data[25] == 0;
  }

  JsonNode list(String actor, String sourceId) {
    var source = owned(actor, sourceId);
    var result = Json.object();
    var items = result.putArray("items");
    for (var row :
        jdbc.queryForList(
            "SELECT * FROM assets WHERE project_id=? AND source_asset_id=? AND kind='ALPHA' ORDER BY created_at DESC,id DESC LIMIT 20",
            source.get("project_id"),
            sourceId)) items.add(view(row));
    return result;
  }

  /** Human decision on a PENDING candidate; decided candidates are never flipped silently. */
  JsonNode review(String actor, String alphaId, JsonNode body) {
    String decision = body.path("decision").asText("");
    if (!body.isObject()
        || body.size() != 1
        || !(decision.equals("APPROVED") || decision.equals("REJECTED")))
      throw new Problem(400, "INVALID_CONTRACT");
    return tx.execute(
        status -> {
          var alpha = owned(actor, alphaId);
          if (!alpha.get("kind").equals("ALPHA")) throw new Problem(422, "INVALID_ASSET");
          // The conditional update is the race guard: only one decision can leave PENDING.
          if (jdbc.update(
                  "UPDATE assets SET review_status=? WHERE id=? AND review_status='PENDING'",
                  decision,
                  alphaId)
              != 1) throw new Problem(409, "TASK_CONFLICT");
          audit(
              actor,
              decision.equals("APPROVED") ? "CUTOUT_APPROVED" : "CUTOUT_REJECTED",
              alphaId,
              Json.object().put("source_asset_id", alpha.get("source_asset_id").toString()));
          return view(owned(actor, alphaId));
        });
  }

  private JsonNode view(Map<String, Object> row) {
    String id = row.get("id").toString();
    return Json.object()
        .put("id", id)
        .put("project_id", row.get("project_id").toString())
        .put("kind", "ALPHA")
        .put("source_asset_id", row.get("source_asset_id").toString())
        .put("sha256", row.get("sha256").toString())
        .put("width", ((Number) row.get("width")).intValue())
        .put("height", ((Number) row.get("height")).intValue())
        .put("review_status", row.get("review_status").toString())
        .put("created_at", ((Timestamp) row.get("created_at")).toInstant().toString())
        .put("content_url", "/api/v1/assets/" + id + "/content");
  }

  private void audit(String actor, String action, String id, JsonNode details) {
    jdbc.update(
        "INSERT INTO audit_events(id,actor_id,action,resource_id,correlation_id,details) VALUES (?,?,?,?,?,?::jsonb)",
        Json.id(),
        actor,
        action,
        id,
        id,
        details.toString());
  }
}
