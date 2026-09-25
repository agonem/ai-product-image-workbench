package com.productimage.business.runtime;

import com.fasterxml.jackson.databind.JsonNode;
import jakarta.servlet.http.HttpServletRequest;
import java.io.IOException;
import java.nio.ByteBuffer;
import java.nio.charset.CharacterCodingException;
import java.nio.charset.StandardCharsets;
import org.springframework.context.annotation.Profile;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

@RestController
@Profile("runtime")
public class RuntimeApi {
  private final TaskService tasks;
  private final DeliveryService deliveries;
  private final RuntimeSettings settings;
  private final UserAuthenticator users;

  public RuntimeApi(
      TaskService tasks,
      DeliveryService deliveries,
      RuntimeSettings settings,
      UserAuthenticator users) {
    this.users = users;
    this.tasks = tasks;
    this.deliveries = deliveries;
    this.settings = settings;
  }

  private void auth(HttpServletRequest request, boolean worker) {
    settings.authorize(request.getHeader("Authorization"), worker);
  }

  private byte[] bytes(HttpServletRequest request, int maximum) {
    try {
      byte[] value = request.getInputStream().readNBytes(maximum + 1);
      if (value.length > maximum) throw new Problem(413, "INVALID_CONTRACT");
      return value;
    } catch (IOException ex) {
      throw new Problem(400, "INVALID_CONTRACT");
    }
  }

  private String json(HttpServletRequest request) {
    try {
      return StandardCharsets.UTF_8
          .newDecoder()
          .decode(ByteBuffer.wrap(bytes(request, 262144)))
          .toString();
    } catch (CharacterCodingException ex) {
      throw new Problem(400, "INVALID_CONTRACT");
    }
  }

  @PostMapping("/api/v1/tasks")
  public ResponseEntity<JsonNode> create(HttpServletRequest request) {
    String actor = users.authenticate(request.getHeader("Authorization"));
    return ResponseEntity.accepted()
        .body(tasks.create(actor, request.getHeader("Idempotency-Key"), json(request)));
  }

  @GetMapping("/api/v1/tasks/{id}")
  public JsonNode get(@PathVariable String id, HttpServletRequest request) {
    String actor = users.authenticate(request.getHeader("Authorization"));
    return tasks.get(actor, id);
  }

  @PostMapping("/api/v1/tasks/{id}/retry")
  public ResponseEntity<JsonNode> retry(@PathVariable String id, HttpServletRequest request) {
    String actor = users.authenticate(request.getHeader("Authorization"));
    var body = Json.parse(json(request));
    if (!body.isObject()
        || body.size() != 1
        || !body.path("attempt").isIntegralNumber()
        || !body.path("attempt").canConvertToInt()
        || body.path("attempt").intValue() < 1) {
      throw new Problem(400, "INVALID_CONTRACT");
    }
    return ResponseEntity.accepted().body(tasks.retry(actor, id, body.path("attempt").intValue()));
  }

  @GetMapping("/api/v1/artifacts/{id}/content")
  public ResponseEntity<byte[]> content(@PathVariable String id, HttpServletRequest request) {
    String actor = users.authenticate(request.getHeader("Authorization"));
    return file(tasks.content(actor, id));
  }

  @PostMapping("/internal/v1/work/claim")
  public ResponseEntity<JsonNode> claim(HttpServletRequest request) {
    auth(request, true);
    var claim = deliveries.claim();
    return claim == null ? ResponseEntity.noContent().build() : ResponseEntity.ok(claim);
  }

  @PostMapping("/internal/v1/work/{attempt}/heartbeat")
  public ResponseEntity<Void> heartbeat(@PathVariable String attempt, HttpServletRequest request) {
    auth(request, true);
    deliveries.heartbeat(attempt, request.getHeader("X-Lease-Token"));
    return ResponseEntity.noContent().build();
  }

  @GetMapping("/internal/v1/work/{attempt}/assets/{asset}")
  public ResponseEntity<byte[]> asset(
      @PathVariable String attempt, @PathVariable String asset, HttpServletRequest request) {
    auth(request, true);
    return file(deliveries.asset(attempt, request.getHeader("X-Lease-Token"), asset));
  }

  @PutMapping("/internal/v1/work/{attempt}/outputs/{ordinal}")
  public JsonNode output(
      @PathVariable String attempt, @PathVariable int ordinal, HttpServletRequest request) {
    auth(request, true);
    if (!"application/octet-stream".equalsIgnoreCase(request.getContentType())) {
      throw new Problem(415, "INVALID_CONTRACT");
    }
    return deliveries.output(
        attempt, request.getHeader("X-Lease-Token"), ordinal, bytes(request, settings.maxBytes()));
  }

  @PostMapping("/internal/v1/work/{attempt}/receipt")
  public JsonNode receipt(@PathVariable String attempt, HttpServletRequest request) {
    auth(request, true);
    return deliveries.receipt(attempt, request.getHeader("X-Lease-Token"), json(request));
  }

  private ResponseEntity<byte[]> file(byte[] value) {
    return ResponseEntity.ok()
        .header("Content-Type", "application/octet-stream")
        .header("Cache-Control", "no-store")
        .header("X-Content-Type-Options", "nosniff")
        .header("Content-Disposition", "attachment")
        .body(value);
  }
}
