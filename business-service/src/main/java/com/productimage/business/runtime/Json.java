package com.productimage.business.runtime;

import com.fasterxml.jackson.core.StreamReadFeature;
import com.fasterxml.jackson.databind.DeserializationFeature;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.json.JsonMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import com.productimage.workbench.contract.ContractValidator;
import com.productimage.workbench.contract.RequestFingerprint;
import java.io.IOException;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.HexFormat;
import java.util.UUID;

final class Json {
  static final JsonMapper MAPPER =
      JsonMapper.builder()
          .enable(StreamReadFeature.STRICT_DUPLICATE_DETECTION)
          .enable(DeserializationFeature.USE_BIG_DECIMAL_FOR_FLOATS)
          .enable(DeserializationFeature.USE_BIG_INTEGER_FOR_INTS)
          .enable(DeserializationFeature.FAIL_ON_TRAILING_TOKENS)
          .build();
  static final ContractValidator VALIDATOR = new ContractValidator();

  private Json() {}

  static ObjectNode object() {
    return MAPPER.createObjectNode();
  }

  static String id() {
    return UUID.randomUUID().toString().replace("-", "");
  }

  static JsonNode parse(String input) {
    try {
      RequestFingerprint.sha256(input);
      return MAPPER.readTree(input);
    } catch (IOException | IllegalArgumentException ex) {
      throw new Problem(400, "INVALID_CONTRACT");
    }
  }

  static void validate(String name, JsonNode input) {
    if (!VALIDATOR.validate(name, input).isEmpty()) throw new Problem(400, "INVALID_CONTRACT");
  }

  static String hash(byte[] bytes) {
    try {
      return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(bytes));
    } catch (NoSuchAlgorithmException ex) {
      throw new IllegalStateException(ex);
    }
  }
}
