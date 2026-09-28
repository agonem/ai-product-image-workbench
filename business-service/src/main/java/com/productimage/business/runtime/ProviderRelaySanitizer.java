package com.productimage.business.runtime;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.node.ArrayNode;
import java.util.Base64;

/**
 * Field whitelists for relayed image-service responses. Upstream content is never trusted: anything
 * outside the whitelist (including any echoed credential) is dropped before the response reaches an
 * administrator or a log.
 */
final class ProviderRelaySanitizer {
  private static final int MAX_TEXT = 200;
  private static final int MAX_LIST = 32;
  private static final int MAX_ENDPOINTS = 16;
  private static final int MAX_PARAMS = 32;
  private static final int MAX_VALUES = 64;
  private static final int MAX_BASE64 = 14_000_000;

  private ProviderRelaySanitizer() {}

  private static String text(JsonNode node, String field) {
    String value = node.path(field).asText("");
    if (value.isEmpty() || value.length() > MAX_TEXT || !value.matches("[\\x21-\\x7e ]+"))
      return "";
    return value;
  }

  private static ArrayNode strings(ArrayNode out, JsonNode value) {
    var list = out.addArray();
    if (value.isArray()) {
      int kept = 0;
      for (var item : value) {
        if (kept >= MAX_LIST) break;
        if (item.isTextual() && item.asText().length() <= MAX_TEXT) {
          list.add(item.asText());
          kept++;
        }
      }
    }
    return list;
  }

  static JsonNode capabilities(JsonNode upstream) {
    if (!upstream.isObject()) throw new Problem(503, "PROVIDER_UNAVAILABLE");
    var out = Json.object();
    out.put("model", text(upstream, "model"));
    out.put("provider_tag", text(upstream, "provider_tag"));
    strings(out.putArray("input_modalities"), upstream.path("input_modalities"));
    strings(out.putArray("output_modalities"), upstream.path("output_modalities"));
    var endpoints = out.putArray("endpoints");
    if (upstream.path("endpoints").isArray()) {
      int kept = 0;
      for (var item : upstream.path("endpoints")) {
        if (kept >= MAX_ENDPOINTS) break;
        if (!item.isObject()) continue;
        var endpoint = Json.object().put("provider_tag", text(item, "provider_tag"));
        var parameters = endpoint.putObject("supported_parameters");
        var supported = item.path("supported_parameters");
        int paramCount = 0;
        if (supported.isObject()) {
          for (var field : supported.properties()) {
            if (paramCount >= MAX_PARAMS) break;
            var descriptor = field.getValue();
            if (!descriptor.isObject() || !descriptor.path("type").isTextual()) continue;
            var values =
                parameters.putObject(field.getKey()).put("type", descriptor.path("type").asText());
            var list = values.putArray("values");
            int valueCount = 0;
            if (descriptor.path("values").isArray()) {
              for (var value : descriptor.path("values")) {
                if (valueCount >= MAX_VALUES) break;
                if (value.isTextual() && value.asText().length() <= MAX_TEXT) {
                  list.add(value.asText());
                  valueCount++;
                }
              }
            }
            paramCount++;
          }
        }
        endpoints.add(endpoint);
        kept++;
      }
    }
    return out;
  }

  static JsonNode paidTest(JsonNode upstream) {
    if (!upstream.isObject()) throw new Problem(503, "PROVIDER_UNAVAILABLE");
    String sha = upstream.path("sha256").asText("");
    String encoded = upstream.path("content_base64").asText("");
    int width = upstream.path("width").asInt(0);
    int height = upstream.path("height").asInt(0);
    String media = upstream.path("media_type").asText("");
    if (!sha.matches("[0-9a-f]{64}")
        || width < 1
        || width > 8192
        || height < 1
        || height > 8192
        || !media.matches("image/(png|jpeg)")
        || encoded.isEmpty()
        || encoded.length() > MAX_BASE64) {
      throw new Problem(503, "PROVIDER_UNAVAILABLE");
    }
    try {
      Base64.getDecoder().decode(encoded);
    } catch (IllegalArgumentException ex) {
      throw new Problem(503, "PROVIDER_UNAVAILABLE");
    }
    var out = Json.object();
    out.put("sha256", sha).put("width", width).put("height", height).put("media_type", media);
    out.put("model", text(upstream, "model"));
    out.put("duration_ms", Math.max(0, upstream.path("duration_ms").asLong(0)));
    // The review status is imposed server-side, never taken from upstream.
    out.put("review_status", "PENDING");
    out.put("content_base64", encoded);
    return out;
  }
}
