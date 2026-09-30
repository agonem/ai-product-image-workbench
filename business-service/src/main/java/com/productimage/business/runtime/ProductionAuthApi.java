package com.productimage.business.runtime;

import com.fasterxml.jackson.databind.JsonNode;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import org.springframework.context.annotation.Profile;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

@RestController
@Profile("prod-local")
public class ProductionAuthApi {
  private final ProductionAccounts accounts;

  ProductionAuthApi(ProductionAccounts accounts) {
    this.accounts = accounts;
  }

  private String token(HttpServletRequest request) {
    return request.getHeader("Authorization");
  }

  private JsonNode body(HttpServletRequest request) {
    return HttpInput.json(request, 2048);
  }

  private ResponseEntity<JsonNode> ok(JsonNode value) {
    return ResponseEntity.ok().header("Cache-Control", "no-store").body(value);
  }

  private ResponseEntity<Void> done() {
    return ResponseEntity.noContent().header("Cache-Control", "no-store").build();
  }

  @PostMapping("/api/v1/local-auth/login")
  ResponseEntity<JsonNode> login(HttpServletRequest request, HttpServletResponse response) {
    JsonNode result = accounts.login(body(request));
    response.addHeader("Set-Cookie", SessionCookies.issue(result, request));
    return ok(result);
  }

  @GetMapping("/api/v1/local-auth/me")
  ResponseEntity<JsonNode> me(HttpServletRequest request) {
    return ok(accounts.me(token(request)));
  }

  @PostMapping("/api/v1/local-auth/logout")
  ResponseEntity<Void> logout(HttpServletRequest request, HttpServletResponse response) {
    // The browser forgets the cookie even when the session was already gone.
    response.addHeader("Set-Cookie", SessionCookies.clear(request));
    accounts.logout(token(request));
    return done();
  }

  @PostMapping("/api/v1/local-auth/password")
  ResponseEntity<Void> password(HttpServletRequest request) {
    accounts.password(token(request), null, body(request));
    return done();
  }

  @GetMapping("/api/v1/admin/accounts")
  ResponseEntity<JsonNode> list(HttpServletRequest request) {
    if (request.getParameterMap().keySet().stream().anyMatch(k -> !k.equals("after"))
        || (request.getParameterValues("after") != null
            && request.getParameterValues("after").length != 1))
      throw new Problem(400, "INVALID_CONTRACT");
    return ok(accounts.list(token(request), request.getParameter("after")));
  }

  @PostMapping("/api/v1/admin/accounts")
  ResponseEntity<JsonNode> create(HttpServletRequest request) {
    return ResponseEntity.status(201)
        .header("Cache-Control", "no-store")
        .body(accounts.create(token(request), body(request)));
  }

  @PostMapping("/api/v1/admin/accounts/{id}/status")
  ResponseEntity<Void> status(@PathVariable String id, HttpServletRequest request) {
    accounts.status(token(request), id, body(request));
    return done();
  }

  /** Deletes an account and its images (ADR-20260930-E). */
  @org.springframework.web.bind.annotation.DeleteMapping("/api/v1/admin/accounts/{id}")
  ResponseEntity<Void> delete(@PathVariable String id, HttpServletRequest request) {
    accounts.delete(token(request), id);
    return done();
  }

  @PostMapping("/api/v1/admin/accounts/{id}/password")
  ResponseEntity<Void> reset(@PathVariable String id, HttpServletRequest request) {
    accounts.password(token(request), id, body(request));
    return done();
  }
}
