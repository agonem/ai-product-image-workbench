package com.productimage.business.runtime;

import static org.junit.jupiter.api.Assertions.assertDoesNotThrow;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

import org.junit.jupiter.api.Test;

class ProviderConfigValidationTest {
  private static final String COMMON =
      "\"name\":\"主力\",\"api_key\":\"sk-x\",\"enabled\":true,\"use_proxy\":false";

  private static void accepts(String fields) {
    String json = "{" + fields + "," + COMMON + "}";
    assertDoesNotThrow(() -> ProviderConfigService.validate(Json.parse(json)), json);
  }

  private static void rejects(String json) {
    assertThrows(Problem.class, () -> ProviderConfigService.validate(Json.parse(json)), json);
  }

  @Test
  void onlyOpenRouterOpenAiAndGeminiWithTheirOwnFields() {
    accepts(
        "\"provider\":\"openrouter\",\"model\":\"openai/gpt-image-2\",\"provider_tag\":\"openai\"");
    accepts("\"provider\":\"openai\",\"model\":\"gpt-image-2\"");
    accepts("\"provider\":\"gemini\",\"model\":\"gemini-2.5-flash-image\"");
    rejects(
        "{\"provider\":\"openai\",\"model\":\"gpt-image-2\",\"provider_tag\":\"x\","
            + COMMON
            + "}");
    rejects("{\"provider\":\"openrouter\",\"model\":\"openai/gpt-image-2\"," + COMMON + "}");
    rejects(
        "{\"provider\":\"openrouter\",\"model\":\"no-slash\",\"provider_tag\":\"t\","
            + COMMON
            + "}");
    // Third-party formats are not offered for now (ADR-20260929-C).
    rejects(
        "{\"provider\":\"openai-compatible\",\"model\":\"m\",\"base_url\":\"https://a.example\","
            + COMMON
            + "}");
    rejects("{\"provider\":\"other\",\"model\":\"m\"," + COMMON + "}");
    rejects("{\"provider\":\"openai\",\"model\":\"gpt image\"," + COMMON + "}");
    rejects(
        "{\"provider\":\"openai\",\"model\":\"m\",\"name\":\" \",\"api_key\":\"k\",\"enabled\":true,\"use_proxy\":false}");
    rejects(
        "{\"provider\":\"openai\",\"model\":\"m\",\"name\":\""
            + "名".repeat(41)
            + "\",\"api_key\":\"k\",\"enabled\":true,\"use_proxy\":false}");
    rejects(
        "{\"provider\":\"openai\",\"model\":\"m\",\"name\":\"n\",\"api_key\":\"k k\",\"enabled\":true,\"use_proxy\":false}");
    rejects(
        "{\"provider\":\"openai\",\"model\":\"m\",\"name\":\"n\",\"api_key\":\"k\",\"enabled\":true}");
  }

  @Test
  void proxyUrlsAllowCredentialsButNoPath() {
    assertTrue(ProviderConfigService.validProxy("http://proxy.company:3128"));
    assertTrue(ProviderConfigService.validProxy("https://user:secret@10.0.0.8:8443/"));
    assertFalse(ProviderConfigService.validProxy("socks5://proxy:1080"));
    assertFalse(ProviderConfigService.validProxy("http://proxy:3128/path"));
    assertFalse(ProviderConfigService.validProxy("http://proxy:3128?x=1"));
    assertFalse(ProviderConfigService.validProxy("http://"));
    assertFalse(ProviderConfigService.validProxy("http://" + "a".repeat(300)));
    assertEquals(
        "https://****@10.0.0.8:8443",
        ProviderConfigService.proxyMask("https://user:secret@10.0.0.8:8443/"));
    assertEquals("http://proxy.company", ProviderConfigService.proxyMask("http://proxy.company"));
  }
}
