package com.productimage.business.runtime;

import static org.junit.jupiter.api.Assertions.assertDoesNotThrow;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.util.List;
import org.junit.jupiter.api.Test;

/**
 * ADR-20261012-AB: which official parameters a model under an interface may store, and which
 * clarity options the pages offer for it.
 */
class ModelParametersTest {
  private static String set(String kind, String model, String purpose) {
    return ModelParameters.set(kind, model, purpose).path("id").asText();
  }

  @Test
  void setsMatchTheInterfaceTypeModelAndPurpose() {
    assertEquals(
        "openrouter-gpt-image-2.5", set("openrouter", "openai/gpt-image-2.5-flare", "IMAGE"));
    assertEquals("openrouter-gpt-image", set("openrouter", "openai/gpt-image-2", "IMAGE"));
    assertEquals(
        "openrouter-seedream", set("openrouter", "bytedance-seed/seedream-5-0-pro", "IMAGE"));
    assertEquals("openrouter-image", set("openrouter", "test/mock-model", "IMAGE"));
    assertEquals("openai-gpt-image", set("openai-compatible", "gpt-image-2-c", "IMAGE"));
    assertEquals("gemini-image", set("gemini", "gemini-3.1-flash-image", "IMAGE"));
    assertEquals("openrouter-text", set("openrouter", "deepseek/deepseek-v4.1-flash", "TEXT"));
    assertEquals("deepseek-text", set("deepseek", "deepseek-flash", "TEXT"));
    assertEquals("compatible-text", set("openai-compatible", "qwen", "TEXT"));
    assertTrue(ModelParameters.set("deepseek", "deepseek-flash", "IMAGE").isMissingNode());
    assertTrue(ModelParameters.serves("deepseek", "TEXT"));
    assertFalse(ModelParameters.serves("deepseek", "IMAGE"));
    assertTrue(ModelParameters.offered("openai-compatible"));
    assertFalse(ModelParameters.offered("gemini-compatible"));
  }

  @Test
  void clarityFollowsTheSetAndStartsAtTheFirstOffered() {
    // ADR-20261012-AB: clarity is chosen per task; the page starts at the first one offered.
    assertEquals(
        List.of("1K"), ModelParameters.resolutions("openrouter", "openai/gpt-image-2", "IMAGE"));
    assertEquals(
        List.of("1K", "2K"),
        ModelParameters.resolutions("openrouter", "google/gemini-3.1-flash-image", "IMAGE"));
    assertEquals(
        List.of("2K"),
        ModelParameters.resolutions("openrouter", "bytedance-seed/seedream-5-0-lite", "IMAGE"));
    assertTrue(
        ModelParameters.resolutions("openrouter", "google/gemini-2.5-flash-image", "IMAGE")
            .isEmpty());
    assertEquals(
        "1K",
        ModelParameters.defaultResolution(
            "openrouter", "bytedance-seed/seedream-5-0-pro", "IMAGE"));
    assertEquals(
        "2K",
        ModelParameters.defaultResolution(
            "openrouter", "bytedance-seed/seedream-5-0-lite", "IMAGE"));
  }

  @Test
  void onlyListedParametersInTheirTypeAndRange() {
    assertDoesNotThrow(
        () ->
            ModelParameters.validate(
                "openrouter",
                "openai/gpt-image-2",
                "IMAGE",
                Json.parse("{\"quality\":\"high\",\"background\":\"opaque\"}")));
    assertDoesNotThrow(
        () ->
            ModelParameters.validate(
                "openrouter",
                "deepseek/deepseek-v4.1-flash",
                "TEXT",
                Json.parse(
                    "{\"temperature\":0.7,\"max_tokens\":6000,\"reasoning.effort\":\"low\"}")));
    assertDoesNotThrow(
        () ->
            ModelParameters.validate(
                "deepseek",
                "deepseek-flash",
                "TEXT",
                Json.parse("{\"thinking.type\":\"disabled\",\"max_tokens\":4096}")));
    assertDoesNotThrow(
        () ->
            ModelParameters.validate(
                "openrouter",
                "bytedance-seed/seedream-5-0-pro",
                "IMAGE",
                Json.parse("{\"seed\":42}")));
    for (String bad :
        new String[] {
          "{\"quality\":\"xhigh\"}", // only GPT Image 2.5 has it
          "{\"resolution\":\"2K\"}", // clarity is per task now
          "{\"quality\":3}",
          "{\"background\":\"transparent\"}",
          "{\"prompt\":\"x\"}",
          "[]"
        })
      assertThrows(
          Problem.class,
          () ->
              ModelParameters.validate(
                  "openrouter", "openai/gpt-image-2", "IMAGE", Json.parse(bad)),
          bad);
    for (String bad :
        new String[] {
          "{\"temperature\":2.5}",
          "{\"temperature\":\"0.7\"}",
          "{\"max_tokens\":10.5}",
          "{\"max_tokens\":0}",
          "{\"reasoning.effort\":\"huge\"}",
          "{\"max_completion_tokens\":100}"
        })
      assertThrows(
          Problem.class,
          () -> ModelParameters.validate("openrouter", "deepseek/x", "TEXT", Json.parse(bad)),
          bad);
  }
}
