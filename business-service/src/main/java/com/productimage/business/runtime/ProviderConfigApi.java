package com.productimage.business.runtime;

import com.fasterxml.jackson.databind.JsonNode;
import jakarta.servlet.http.HttpServletRequest;
import org.springframework.context.annotation.Profile;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

/** Production administrator management of the OpenRouter background configuration. */
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

  @GetMapping("/api/v1/admin/provider-configs")
  ResponseEntity<JsonNode> list(HttpServletRequest request) {
    accounts.manager(request.getHeader("Authorization"));
    return ResponseEntity.ok().header("Cache-Control", "no-store").body(configs.list());
  }

  @PostMapping("/api/v1/admin/provider-configs")
  ResponseEntity<JsonNode> create(HttpServletRequest request) {
    String actor = accounts.manager(request.getHeader("Authorization"));
    return ResponseEntity.status(201)
        .header("Cache-Control", "no-store")
        .body(configs.create(actor, body(request)));
  }

  @PostMapping("/api/v1/admin/provider-configs/{id}/status")
  ResponseEntity<Void> status(@PathVariable String id, HttpServletRequest request) {
    String actor = accounts.manager(request.getHeader("Authorization"));
    configs.status(actor, id, body(request));
    return ResponseEntity.noContent().header("Cache-Control", "no-store").build();
  }

  /** Non-paid capability check only; never triggers any paid request. */
  @PostMapping("/api/v1/admin/provider-configs/{id}/check")
  ResponseEntity<JsonNode> check(@PathVariable String id, HttpServletRequest request) {
    String actor = accounts.manager(request.getHeader("Authorization"));
    return ResponseEntity.ok().header("Cache-Control", "no-store").body(configs.check(actor, id));
  }

  /** Single paid probe; requires the explicit confirmation phrase and is billed by provider. */
  @PostMapping("/api/v1/admin/provider-configs/{id}/test-generate")
  ResponseEntity<JsonNode> testGenerate(@PathVariable String id, HttpServletRequest request) {
    String actor = accounts.manager(request.getHeader("Authorization"));
    return ResponseEntity.ok()
        .header("Cache-Control", "no-store")
        .body(configs.testGenerate(actor, id, body(request)));
  }
}
