package com.productimage.workbench.contract;

import static org.junit.jupiter.api.Assertions.assertEquals;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.io.IOException;
import java.util.stream.Stream;
import java.util.stream.StreamSupport;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.MethodSource;

class ContractValidatorTest {
  static Stream<JsonNode> fixtures() throws IOException {
    try (var input =
        ContractValidatorTest.class.getResourceAsStream("/contract-fixtures/cases.json")) {
      return StreamSupport.stream(new ObjectMapper().readTree(input).spliterator(), false);
    }
  }

  @ParameterizedTest(name = "{index}: {0}")
  @MethodSource("fixtures")
  void validatesSharedFixture(JsonNode fixture) {
    assertEquals(
        fixture.get("valid").asBoolean(),
        new ContractValidator()
            .validate(fixture.get("contract").asText(), fixture.get("payload"))
            .isEmpty(),
        fixture.get("name").asText());
  }

  @org.junit.jupiter.api.Test
  void unknownContractAndSafeErrors() {
    var validator = new ContractValidator();
    var value = new ObjectMapper().createObjectNode().put("api_key", "dummy-sensitive-value");
    org.junit.jupiter.api.Assertions.assertThrows(
        IllegalArgumentException.class,
        () -> validator.validate("https://example.invalid/unregistered", value));
    var errors = validator.validate("generation-v4-create", value);
    org.junit.jupiter.api.Assertions.assertFalse(errors.isEmpty());
    org.junit.jupiter.api.Assertions.assertFalse(
        errors.toString().contains("dummy-sensitive-value"));
  }
}
