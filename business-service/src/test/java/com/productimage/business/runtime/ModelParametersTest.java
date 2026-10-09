package com.productimage.business.runtime;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

import org.junit.jupiter.api.Test;

/** ADR-20261009-Q: which parameters a model may store and which clarity options it supports. */
class ModelParametersTest {
  @Test
  void familiesMatchTheModelIdAndPurpose() {
    assertEquals(
        "gpt-image-2.5",
        ModelParameters.family("openai/gpt-image-2.5-sunburst", "IMAGE").path("id").asText());
    assertEquals("gpt-image", ModelParameters.family("gpt-image-2", "IMAGE").path("id").asText());
    assertEquals(
        "seedream",
        ModelParameters.family("bytedance-seed/seedream-5-0-pro", "IMAGE").path("id").asText());
    assertTrue(ModelParameters.family("google/gemini-2.5-flash-image", "IMAGE").isMissingNode());
    assertEquals(
        "text", ModelParameters.family("deepseek/deepseek-v4.1-flash", "TEXT").path("id").asText());
  }

  @Test
  void clarityFollowsTheFamily() {
    // ADR-20261009-R: the pages offer 1K / 2K where the family says how to ask for them.
    assertEquals(
        java.util.List.of("1K"), ModelParameters.resolutions("openai/gpt-image-2", "IMAGE"));
    assertEquals(
        java.util.List.of("1K", "2K"),
        ModelParameters.resolutions("google/gemini-3.1-flash-image", "IMAGE"));
    assertEquals(
        java.util.List.of("2K"),
        ModelParameters.resolutions("bytedance-seed/seedream-5-0-lite", "IMAGE"));
    assertTrue(ModelParameters.resolutions("google/gemini-2.5-flash-image", "IMAGE").isEmpty());
    String model = "bytedance-seed/seedream-5-0-pro";
    assertEquals("1K", ModelParameters.defaultResolution(model, "IMAGE", Json.parse("{}")));
    assertEquals(
        "2K",
        ModelParameters.defaultResolution(model, "IMAGE", Json.parse("{\"resolution\":\"2K\"}")));
    assertFalse(ModelParameters.resolutions("openai/gpt-image-2", "IMAGE").contains("2K"));
  }

  @Test
  void onlyListedParametersAndValuesAreStored() {
    ModelParameters.validate("openai/gpt-image-2", "IMAGE", Json.parse("{\"quality\":\"high\"}"));
    ModelParameters.validate("deepseek/x", "TEXT", Json.parse("{\"temperature\":\"0.2\"}"));
    ModelParameters.validate("google/gemini-2.5-flash-image", "IMAGE", Json.parse("{}"));
    for (String bad :
        new String[] {
          "{\"quality\":\"xhigh\"}", "{\"resolution\":\"2K\"}", "{\"quality\":3}", "[]"
        })
      assertThrows(
          Problem.class,
          () -> ModelParameters.validate("openai/gpt-image-2", "IMAGE", Json.parse(bad)),
          bad);
  }
}
