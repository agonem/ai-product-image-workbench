package com.productimage.business.runtime;

import com.fasterxml.jackson.databind.JsonNode;
import jakarta.servlet.http.HttpServletRequest;
import java.util.concurrent.Semaphore;
import org.springframework.context.annotation.Profile;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

@RestController
@Profile("runtime")
public class ProjectAssetApi {
  private final UserAuthenticator users;
  private final ProjectAssets assets;
  private final RuntimeSettings settings;
  private final CutoutService cutouts;
  // Bound simultaneous buffered image decodes independently of HTTP thread count.
  private final Semaphore uploads = new Semaphore(2);

  ProjectAssetApi(
      UserAuthenticator users,
      ProjectAssets assets,
      RuntimeSettings settings,
      CutoutService cutouts) {
    this.users = users;
    this.assets = assets;
    this.settings = settings;
    this.cutouts = cutouts;
  }

  private String actor(HttpServletRequest request) {
    return users.authenticate(request.getHeader("Authorization"));
  }

  @PostMapping("/api/v1/projects")
  ResponseEntity<JsonNode> create(HttpServletRequest request) {
    String actor = actor(request);
    return ResponseEntity.status(201)
        .header("Cache-Control", "no-store")
        .body(assets.create(actor, HttpInput.json(request, 2048)));
  }

  @GetMapping("/api/v1/projects")
  ResponseEntity<JsonNode> list(HttpServletRequest request) {
    return ResponseEntity.ok()
        .header("Cache-Control", "no-store")
        .body(assets.list(actor(request)));
  }

  @GetMapping("/api/v1/projects/{id}")
  ResponseEntity<JsonNode> project(@PathVariable String id, HttpServletRequest request) {
    return ResponseEntity.ok()
        .header("Cache-Control", "no-store")
        .body(assets.project(actor(request), id));
  }

  @PostMapping("/api/v1/projects/{id}/assets")
  ResponseEntity<JsonNode> upload(
      @PathVariable String id, @RequestParam String kind, HttpServletRequest request) {
    String actor = actor(request);
    assets.authorizeUpload(actor, id, kind);
    if (request.getParameterMap().size() != 1 || request.getParameterValues("kind").length != 1)
      throw new Problem(400, "INVALID_CONTRACT");
    if (!uploads.tryAcquire()) throw new Problem(429, "UPLOAD_BUSY");
    try {
      return ResponseEntity.status(201)
          .header("Cache-Control", "no-store")
          .body(
              assets.upload(
                  actor,
                  id,
                  kind,
                  request.getContentType(),
                  HttpInput.bytes(request, settings.maxBytes())));
    } finally {
      uploads.release();
    }
  }

  @GetMapping("/api/v1/assets/{id}")
  ResponseEntity<JsonNode> asset(@PathVariable String id, HttpServletRequest request) {
    return ResponseEntity.ok()
        .header("Cache-Control", "no-store")
        .body(assets.asset(actor(request), id));
  }

  @GetMapping("/api/v1/assets/{id}/content")
  ResponseEntity<byte[]> content(@PathVariable String id, HttpServletRequest request) {
    byte[] data = assets.content(actor(request), id);
    return ResponseEntity.ok()
        .header("Content-Type", "application/octet-stream")
        .header("Cache-Control", "no-store")
        .header("X-Content-Type-Options", "nosniff")
        .header("Content-Disposition", "attachment")
        .body(data);
  }

  @GetMapping("/api/v1/assets/{id}/approved-alpha")
  ResponseEntity<byte[]> approvedAlpha(@PathVariable String id, HttpServletRequest request) {
    return ResponseEntity.ok()
        .header("Content-Type", "application/octet-stream")
        .header("Cache-Control", "no-store")
        .header("X-Content-Type-Options", "nosniff")
        .body(assets.approvedAlpha(actor(request), id));
  }

  /** Creates a PENDING cutout candidate; never approves it. */
  @PostMapping("/api/v1/assets/{id}/cutouts")
  ResponseEntity<JsonNode> createCutout(@PathVariable String id, HttpServletRequest request) {
    String actor = actor(request);
    return ResponseEntity.status(201)
        .header("Cache-Control", "no-store")
        .body(cutouts.create(actor, id, HttpInput.json(request, 1024)));
  }

  @GetMapping("/api/v1/assets/{id}/cutouts")
  ResponseEntity<JsonNode> cutouts(@PathVariable String id, HttpServletRequest request) {
    return ResponseEntity.ok()
        .header("Cache-Control", "no-store")
        .body(cutouts.list(actor(request), id));
  }

  /** The owner's explicit decision on a PENDING candidate (APPROVED or REJECTED). */
  @PostMapping("/api/v1/assets/{id}/review")
  ResponseEntity<JsonNode> review(@PathVariable String id, HttpServletRequest request) {
    String actor = actor(request);
    return ResponseEntity.ok()
        .header("Cache-Control", "no-store")
        .body(cutouts.review(actor, id, HttpInput.json(request, 1024)));
  }
}
