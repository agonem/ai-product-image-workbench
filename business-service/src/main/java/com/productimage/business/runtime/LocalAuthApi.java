package com.productimage.business.runtime;

import com.fasterxml.jackson.databind.JsonNode;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
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
  ResponseEntity<JsonNode> login(HttpServletRequest request, HttpServletResponse response) {
    JsonNode result = accounts.login(HttpInput.json(request, 2048));
    response.addHeader("Set-Cookie", SessionCookies.issue(result, request));
    return ResponseEntity.ok().header("Cache-Control", "no-store").body(result);
  }

  @GetMapping("/api/v1/auth/me")
  ResponseEntity<JsonNode> me(HttpServletRequest request) {
    return ResponseEntity.ok()
        .header("Cache-Control", "no-store")
        .body(accounts.me(request.getHeader("Authorization")));
  }

  @PostMapping("/api/v1/auth/logout")
  ResponseEntity<Void> logout(HttpServletRequest request, HttpServletResponse response) {
    response.addHeader("Set-Cookie", SessionCookies.clear(request));
    accounts.logout(request.getHeader("Authorization"));
    return ResponseEntity.noContent().header("Cache-Control", "no-store").build();
  }
}
