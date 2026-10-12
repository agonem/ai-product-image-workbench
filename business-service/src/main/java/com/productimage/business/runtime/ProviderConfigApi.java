package com.productimage.business.runtime;

import com.fasterxml.jackson.databind.JsonNode;
import jakarta.servlet.http.HttpServletRequest;
import org.springframework.context.annotation.Profile;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

/**
 * Production administrator management of model interfaces, the models under them (ADR-20261012-AB)
 * and the outbound proxy.
 */
@RestController
@Profile("prod-local")
public class ProviderConfigApi {
  private final ProviderConfigService configs;
  private final ProductionAccounts accounts;

  ProviderConfigApi(ProviderConfigService configs, ProductionAccounts accounts) {
    this.configs = configs;
    this.accounts = accounts;
  }

  private JsonNode body(HttpServletRequest request) {
    return HttpInput.json(request, 4096);
  }

  private String admin(HttpServletRequest request) {
    return accounts.manager(request.getHeader("Authorization"));
  }

  private static ResponseEntity<Void> done() {
    return ResponseEntity.noContent().header("Cache-Control", "no-store").build();
  }

  @GetMapping("/api/v1/admin/provider-configs")
  ResponseEntity<JsonNode> list(HttpServletRequest request) {
    admin(request);
    return ResponseEntity.ok().header("Cache-Control", "no-store").body(configs.list());
  }

  @PostMapping("/api/v1/admin/provider-configs")
  ResponseEntity<JsonNode> create(HttpServletRequest request) {
    String actor = admin(request);
    return ResponseEntity.status(201)
        .header("Cache-Control", "no-store")
        .body(configs.create(actor, body(request)));
  }

  /** {name, kind, api_key, use_proxy, base_url? (third parties)} */
  @PostMapping("/api/v1/admin/model-interfaces")
  ResponseEntity<JsonNode> createInterface(HttpServletRequest request) {
    String actor = admin(request);
    return ResponseEntity.status(201)
        .header("Cache-Control", "no-store")
        .body(configs.createInterface(actor, body(request)));
  }

  /** Edit in place: {name?, base_url?, api_key?, use_proxy?}; the type never changes. */
  @PostMapping("/api/v1/admin/model-interfaces/{id}/settings")
  ResponseEntity<Void> interfaceSettings(@PathVariable String id, HttpServletRequest request) {
    String actor = admin(request);
    configs.updateInterface(actor, id, body(request));
    return done();
  }

  /** Only an interface without models (409 INTERFACE_IN_USE). */
  @DeleteMapping("/api/v1/admin/model-interfaces/{id}")
  ResponseEntity<Void> deleteInterface(@PathVariable String id, HttpServletRequest request) {
    configs.deleteInterface(admin(request), id);
    return done();
  }

  /**
   * Edit a model in place (ADR-20261009-Q, -AB): {name?, model?, provider_tag?, vision?, enabled?,
   * parameters?}.
   */
  @PostMapping("/api/v1/admin/provider-configs/{id}/settings")
  ResponseEntity<Void> settings(@PathVariable String id, HttpServletRequest request) {
    String actor = admin(request);
    configs.update(actor, id, body(request));
    return done();
  }

  /** {enabled}: kept for existing clients; same rules as settings. */
  @PostMapping("/api/v1/admin/provider-configs/{id}/status")
  ResponseEntity<Void> status(@PathVariable String id, HttpServletRequest request) {
    String actor = admin(request);
    JsonNode body = body(request);
    if (body.size() != 1 || !body.has("enabled")) throw new Problem(400, "INVALID_CONTRACT");
    configs.update(actor, id, body);
    return done();
  }

  @PostMapping("/api/v1/admin/provider-configs/{id}/default")
  ResponseEntity<Void> makeDefault(@PathVariable String id, HttpServletRequest request) {
    configs.makeDefault(admin(request), id);
    return done();
  }

  /** Delete for good; unfinished tasks move to the default model (ADR-20261009-Q). */
  @DeleteMapping("/api/v1/admin/provider-configs/{id}")
  ResponseEntity<Void> delete(@PathVariable String id, HttpServletRequest request) {
    configs.delete(admin(request), id);
    return done();
  }

  @GetMapping("/api/v1/admin/network-proxy")
  ResponseEntity<JsonNode> proxy(HttpServletRequest request) {
    admin(request);
    return ResponseEntity.ok().header("Cache-Control", "no-store").body(configs.proxy());
  }

  /** {proxy_url} */
  @PutMapping("/api/v1/admin/network-proxy")
  ResponseEntity<Void> setProxy(HttpServletRequest request) {
    String actor = admin(request);
    configs.setProxy(actor, body(request));
    return done();
  }

  @DeleteMapping("/api/v1/admin/network-proxy")
  ResponseEntity<Void> clearProxy(HttpServletRequest request) {
    configs.clearProxy(admin(request));
    return done();
  }
}
