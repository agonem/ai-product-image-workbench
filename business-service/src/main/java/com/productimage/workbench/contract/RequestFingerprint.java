package com.productimage.workbench.contract;

import com.fasterxml.jackson.core.StreamReadFeature;
import com.fasterxml.jackson.databind.DeserializationFeature;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.json.JsonMapper;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.ArrayList;
import java.util.Collections;
import java.util.HexFormat;

/** Java is the sole producer of the v1 request fingerprint. Not RFC 8785. */
public final class RequestFingerprint {
  private static final JsonMapper MAPPER =
      JsonMapper.builder()
          .enable(StreamReadFeature.STRICT_DUPLICATE_DETECTION)
          .enable(DeserializationFeature.USE_BIG_DECIMAL_FOR_FLOATS)
          .enable(DeserializationFeature.USE_BIG_INTEGER_FOR_INTS)
          .enable(DeserializationFeature.FAIL_ON_TRAILING_TOKENS)
          .build();

  private RequestFingerprint() {}

  public static String sha256(String json) {
    try {
      JsonNode value = MAPPER.readTree(json);
      if (value == null || value.isNull() || value.isMissingNode()) {
        throw new IllegalArgumentException("Invalid request JSON");
      }
      StringBuilder canonical = new StringBuilder();
      append(value, canonical);
      return HexFormat.of()
          .formatHex(
              MessageDigest.getInstance("SHA-256")
                  .digest(canonical.toString().getBytes(StandardCharsets.UTF_8)));
    } catch (IOException | IllegalArgumentException ex) {
      // Parser diagnostics can contain request values. Do not propagate them.
      throw new IllegalArgumentException("Invalid request JSON");
    } catch (NoSuchAlgorithmException ex) {
      throw new IllegalStateException("SHA-256 is unavailable", ex);
    }
  }

  private static void append(JsonNode value, StringBuilder output) throws IOException {
    if (value.isObject()) {
      var names = new ArrayList<String>();
      value.fieldNames().forEachRemaining(names::add);
      Collections.sort(names);
      output.append('{');
      for (int index = 0; index < names.size(); index++) {
        if (index > 0) output.append(',');
        String name = names.get(index);
        requireUnicode(name);
        output.append(MAPPER.writeValueAsString(name)).append(':');
        append(value.get(name), output);
      }
      output.append('}');
    } else if (value.isArray()) {
      output.append('[');
      for (int index = 0; index < value.size(); index++) {
        if (index > 0) output.append(',');
        append(value.get(index), output);
      }
      output.append(']');
    } else if (value.isNumber()) {
      output.append(value.decimalValue().stripTrailingZeros().toString());
    } else {
      if (value.isTextual()) requireUnicode(value.textValue());
      output.append(MAPPER.writeValueAsString(value));
    }
  }

  private static void requireUnicode(String value) {
    for (int index = 0; index < value.length(); index++) {
      char current = value.charAt(index);
      if (Character.isHighSurrogate(current)) {
        if (++index >= value.length() || !Character.isLowSurrogate(value.charAt(index))) {
          throw new IllegalArgumentException("Invalid Unicode");
        }
      } else if (Character.isLowSurrogate(current)) {
        throw new IllegalArgumentException("Invalid Unicode");
      }
    }
  }
}
