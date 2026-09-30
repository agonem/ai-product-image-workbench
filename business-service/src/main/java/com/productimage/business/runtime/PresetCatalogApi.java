package com.productimage.business.runtime;

import com.fasterxml.jackson.databind.JsonNode;
import jakarta.servlet.http.HttpServletRequest;
import org.springframework.context.annotation.Profile;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

/** Template management for admins (ADR-20260930-F): scene presets and selling-point styles. */
@RestController
@Profile("prod-local")
public class PresetCatalogApi {
  private final ProductionAccounts accounts;
  private final PresetCatalog catalog;

  PresetCatalogApi(ProductionAccounts accounts, PresetCatalog catalog) {
    this.accounts = accounts;
    this.catalog = catalog;
  }

  private String admin(HttpServletRequest request) {
    return accounts.manager(request.getHeader("Authorization"));
  }

  @GetMapping("/api/v1/admin/presets")
  ResponseEntity<JsonNode> list(HttpServletRequest request) {
    admin(request);
    return ResponseEntity.ok().header("Cache-Control", "no-store").body(catalog.admin());
  }

  /** {scenes, styles, note?}: saves and publishes a new version (201 {version}). */
  @PutMapping("/api/v1/admin/presets")
  ResponseEntity<JsonNode> save(HttpServletRequest request) {
    String actor = admin(request);
    int version = catalog.save(actor, HttpInput.json(request, 262144));
    return ResponseEntity.status(201)
        .header("Cache-Control", "no-store")
        .body(Json.object().put("version", version));
  }

  /** Publishes a copy of an earlier version; 0 restores the bundled defaults. */
  @PostMapping("/api/v1/admin/presets/{version}/restore")
  ResponseEntity<JsonNode> restore(@PathVariable int version, HttpServletRequest request) {
    String actor = admin(request);
    if (version < 0) throw new Problem(400, "INVALID_CONTRACT");
    return ResponseEntity.status(201)
        .header("Cache-Control", "no-store")
        .body(Json.object().put("version", catalog.restore(actor, version)));
  }
}
