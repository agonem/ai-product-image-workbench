package com.productimage.business.runtime;

import com.fasterxml.jackson.databind.JsonNode;
import jakarta.servlet.http.HttpServletRequest;
import org.springframework.context.annotation.Profile;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

@RestController
@Profile("dev-local")
public class LocalAuthApi {
  private final LocalAccounts accounts;

  LocalAuthApi(LocalAccounts accounts) {
    this.accounts = accounts;
  }

  @PostMapping("/api/v1/auth/login")
  ResponseEntity<JsonNode> login(HttpServletRequest request) {
    return ResponseEntity.ok()
        .header("Cache-Control", "no-store")
        .body(accounts.login(HttpInput.json(request, 2048)));
  }

  @GetMapping("/api/v1/auth/me")
  ResponseEntity<JsonNode> me(HttpServletRequest request) {
    return ResponseEntity.ok()
        .header("Cache-Control", "no-store")
        .body(
            Json.object()
                .put("id", accounts.authenticate(request.getHeader("Authorization")))
                .put("mode", "development-only"));
  }

  @PostMapping("/api/v1/auth/logout")
  ResponseEntity<Void> logout(HttpServletRequest request) {
    accounts.logout(request.getHeader("Authorization"));
    return ResponseEntity.noContent().header("Cache-Control", "no-store").build();
  }
}
