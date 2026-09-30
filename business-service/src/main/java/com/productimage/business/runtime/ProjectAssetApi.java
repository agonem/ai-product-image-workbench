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
  // Bound simultaneous buffered image decodes independently of HTTP thread count.
  private final Semaphore uploads = new Semaphore(2);

  ProjectAssetApi(UserAuthenticator users, ProjectAssets assets, RuntimeSettings settings) {
    this.users = users;
    this.assets = assets;
    this.settings = settings;
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
                  // The content decides the type; the declared Content-Type is not trusted.
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

  /** The owner deletes an original upload (D-08); history keeps a "deleted" placeholder. */
  @DeleteMapping("/api/v1/assets/{id}")
  ResponseEntity<Void> delete(@PathVariable String id, HttpServletRequest request) {
    assets.delete(actor(request), id);
    return ResponseEntity.noContent().header("Cache-Control", "no-store").build();
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
}
