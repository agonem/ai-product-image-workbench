package com.productimage.business.runtime;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.fasterxml.jackson.databind.JsonNode;
import org.junit.jupiter.api.Test;

public class ProviderRelaySanitizerTest {
  @Test
  void capabilityWhitelistDropsInjectedCredentialsAndUnknownFields() {
    var upstream =
        Json.parse(
            """
            {
              "model": "vendor/model-1",
              "provider_tag": "openai",
              "api_key": "sk-LEAKED-VALUE",
              "api_key_file": "/etc/passwd",
              "input_modalities": ["text", 42, "image", "overly-long-entry-that-should-be-kept-anyway"],
              "output_modalities": ["image"],
              "endpoints": [
                {
                  "provider_tag": "openai",
                  "supported_parameters": {
                    "aspect_ratio": {"type": "enum", "values": ["1:1", "1:2"]},
                    "resolution": {"type": "enum", "values": ["1K"]},
                    "output_format": {"type": "enum", "values": ["png"]}
                  },
                  "secret_hint": "do-not-forward"
                }
              ]
            }
            """);
    JsonNode clean = ProviderRelaySanitizer.capabilities(upstream);
    assertFalse(clean.toString().contains("LEAKED"));
    assertFalse(clean.toString().contains("secret_hint"));
    assertFalse(clean.toString().contains("passwd"));
    assertEquals("vendor/model-1", clean.path("model").asText());
    var endpoint = clean.path("endpoints").get(0);
    assertEquals(3, endpoint.path("supported_parameters").size());
    assertEquals(
        "1:1",
        endpoint.path("supported_parameters").path("aspect_ratio").path("values").get(0).asText());
  }

  @Test
  void capabilityNonArrayOrOversizedContentIsCapped() {
    var upstream =
        Json.parse(
            """
            {
              "model": "m",
              "endpoints": "not-an-array",
              "input_modalities": ["ok", {"nested": "object"}]
            }
            """);
    JsonNode clean = ProviderRelaySanitizer.capabilities(upstream);
    assertEquals(0, clean.path("endpoints").size());
    assertEquals(1, clean.path("input_modalities").size());
  }

  @Test
  void paidTestEnforcesShapeAndImposesPendingStatus() {
    var payload =
        Json.parse(
            """
            {
              "sha256": "%s",
              "width": 8,
              "height": 8,
              "media_type": "image/png",
              "model": "vendor/model-1",
              "duration_ms": 7,
              "review_status": "APPROVED",
              "api_key": "sk-LEAKED-VALUE",
              "content_base64": "%s"
            }
            """
                .formatted("a".repeat(64), "iVBORw0KGgo="));
    JsonNode clean = ProviderRelaySanitizer.paidTest(payload);
    assertEquals("PENDING", clean.path("review_status").asText());
    assertFalse(clean.toString().contains("LEAKED"));
    assertEquals(8, clean.path("width").asInt());
  }

  @Test
  void paidTestRejectsBadShaOversizeOrUnknownMedia() {
    var base =
        """
        {"sha256": "%s", "width": 8, "height": 8, "media_type": "image/png", "content_base64": "aGk="}
        """;
    assertThrows(
        Problem.class,
        () -> ProviderRelaySanitizer.paidTest(Json.parse(base.formatted("z".repeat(64)))));
    assertThrows(
        Problem.class,
        () ->
            ProviderRelaySanitizer.paidTest(Json.parse(base.formatted("b".repeat(64) + "extra"))));
    assertThrows(
        Problem.class,
        () ->
            ProviderRelaySanitizer.paidTest(
                Json.parse(
                    base.replace("image/png", "application/octet-stream")
                        .formatted("a".repeat(64)))));
    assertTrue(
        ProviderRelaySanitizer.paidTest(Json.parse(base.formatted("a".repeat(64))))
                .path("duration_ms")
                .asLong()
            == 0);
  }

  @Test
  void nonObjectUpstreamFailsSafe() {
    assertThrows(Problem.class, () -> ProviderRelaySanitizer.capabilities(Json.parse("[]")));
    assertThrows(Problem.class, () -> ProviderRelaySanitizer.paidTest(Json.parse("\"x\"")));
  }
}
