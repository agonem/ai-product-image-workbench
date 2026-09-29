package com.productimage.business.runtime;

import com.fasterxml.jackson.databind.JsonNode;
import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletRequestWrapper;
import jakarta.servlet.http.HttpServletResponse;
import java.io.IOException;
import java.time.Duration;
import java.time.Instant;
import java.util.ArrayList;
import java.util.Collections;
import java.util.Enumeration;
import org.springframework.context.annotation.Profile;
import org.springframework.http.ResponseCookie;
import org.springframework.stereotype.Component;
import org.springframework.web.filter.OncePerRequestFilter;

/**
 * Keeps the page signed in until the session expires: the login token also travels as an HttpOnly,
 * SameSite=Strict cookie limited to /api. Scripts cannot read it, and it only ever stands in for a
 * missing Authorization header on same-origin /api requests, so Worker endpoints and explicit
 * bearer clients behave exactly as before.
 */
@Component
@Profile({"dev-local", "prod-local"})
public class SessionCookies extends OncePerRequestFilter {
  static final String NAME = "wb_session";
  private static final String TOKEN = "[A-Za-z0-9_-]{43}";

  static String issue(JsonNode login, HttpServletRequest request) {
    long seconds =
        Math.max(
            0,
            Duration.between(Instant.now(), Instant.parse(login.path("expires_at").asText()))
                .getSeconds());
    return cookie(login.path("access_token").asText(), seconds, request);
  }

  static String clear(HttpServletRequest request) {
    return cookie("", 0, request);
  }

  private static String cookie(String value, long seconds, HttpServletRequest request) {
    return ResponseCookie.from(NAME, value)
        .httpOnly(true)
        .secure(request.isSecure())
        .sameSite("Strict")
        .path("/api")
        .maxAge(seconds)
        .build()
        .toString();
  }

  @Override
  protected boolean shouldNotFilter(HttpServletRequest request) {
    return !request.getRequestURI().startsWith("/api/")
        || request.getHeader("Authorization") != null;
  }

  @Override
  protected void doFilterInternal(
      HttpServletRequest request, HttpServletResponse response, FilterChain chain)
      throws ServletException, IOException {
    String token = null;
    if (request.getCookies() != null)
      for (var cookie : request.getCookies())
        if (NAME.equals(cookie.getName()) && cookie.getValue().matches(TOKEN))
          token = cookie.getValue();
    // Browsers label cross-site requests; those never borrow the session (defence in depth).
    String site = request.getHeader("Sec-Fetch-Site");
    if (token == null || (site != null && !site.equals("same-origin") && !site.equals("none"))) {
      chain.doFilter(request, response);
      return;
    }
    String header = "Bearer " + token;
    chain.doFilter(
        new HttpServletRequestWrapper(request) {
          @Override
          public String getHeader(String name) {
            return "Authorization".equalsIgnoreCase(name) ? header : super.getHeader(name);
          }

          @Override
          public Enumeration<String> getHeaders(String name) {
            return "Authorization".equalsIgnoreCase(name)
                ? Collections.enumeration(java.util.List.of(header))
                : super.getHeaders(name);
          }

          @Override
          public Enumeration<String> getHeaderNames() {
            var names = new ArrayList<>(Collections.list(super.getHeaderNames()));
            names.add("Authorization");
            return Collections.enumeration(names);
          }
        },
        response);
  }
}
