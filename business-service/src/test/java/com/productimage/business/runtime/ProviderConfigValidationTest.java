package com.productimage.business.runtime;

import static org.junit.jupiter.api.Assertions.assertDoesNotThrow;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

import org.junit.jupiter.api.Test;

class ProviderConfigValidationTest {
  private static void accepts(String json) {
    assertDoesNotThrow(() -> ProviderConfigService.validate(Json.parse(json)), json);
  }

  private static void rejects(String json) {
    assertThrows(Problem.class, () -> ProviderConfigService.validate(Json.parse(json)), json);
  }

  @Test
  void eachProviderTypeTakesExactlyItsOwnFields() {
    accepts(
        "{\"provider\":\"openrouter\",\"model\":\"openai/gpt-image-2\",\"provider_tag\":\"openai\",\"api_key\":\"sk-x\",\"enabled\":true}");
    accepts(
        "{\"provider\":\"openai\",\"model\":\"gpt-image-2\",\"api_key\":\"sk-x\",\"enabled\":true}");
    accepts(
        "{\"provider\":\"gemini\",\"model\":\"gemini-2.5-flash-image\",\"api_key\":\"k\",\"enabled\":false}");
    accepts(
        "{\"provider\":\"openai-compatible\",\"model\":\"gpt-image-2\",\"base_url\":\"http://10.2.2.110:3000/v1\",\"api_key\":\"k\",\"enabled\":true}");
    accepts(
        "{\"provider\":\"gemini-compatible\",\"model\":\"gemini-2.5-flash-image\",\"base_url\":\"https://relay.example.com\",\"api_key\":\"k\",\"enabled\":true}");
    // Wrong or missing fields for the chosen type.
    rejects(
        "{\"provider\":\"openai\",\"model\":\"gpt-image-2\",\"provider_tag\":\"x\",\"api_key\":\"k\",\"enabled\":true}");
    rejects(
        "{\"provider\":\"openai\",\"model\":\"gpt-image-2\",\"base_url\":\"https://a.b\",\"api_key\":\"k\",\"enabled\":true}");
    rejects(
        "{\"provider\":\"openai-compatible\",\"model\":\"gpt-image-2\",\"api_key\":\"k\",\"enabled\":true}");
    rejects(
        "{\"provider\":\"openrouter\",\"model\":\"no-slash\",\"provider_tag\":\"t\",\"api_key\":\"k\",\"enabled\":true}");
    rejects("{\"provider\":\"other\",\"model\":\"m\",\"api_key\":\"k\",\"enabled\":true}");
    rejects("{\"provider\":\"openai\",\"model\":\"gpt image\",\"api_key\":\"k\",\"enabled\":true}");
    rejects(
        "{\"provider\":\"openai\",\"model\":\"gpt-image-2\",\"api_key\":\"k k\",\"enabled\":true}");
    rejects(
        "{\"provider\":\"openai\",\"model\":\"gpt-image-2\",\"api_key\":\"k\",\"enabled\":\"yes\"}");
  }

  @Test
  void httpIsOnlyAllowedForPrivateIpv4Addresses() {
    assertTrue(ProviderConfigService.validBaseUrl("https://api.example.com/v1"));
    assertTrue(ProviderConfigService.validBaseUrl("http://10.2.2.110:3000"));
    assertTrue(ProviderConfigService.validBaseUrl("http://172.16.0.5/v1beta"));
    assertTrue(ProviderConfigService.validBaseUrl("http://192.168.1.20:8080/v1"));
    assertFalse(ProviderConfigService.validBaseUrl("http://8.8.8.8/v1"));
    assertFalse(ProviderConfigService.validBaseUrl("http://172.32.0.1/v1"));
    assertFalse(ProviderConfigService.validBaseUrl("http://relay.internal/v1"));
    assertFalse(ProviderConfigService.validBaseUrl("http://127.0.0.1:3000"));
    assertFalse(ProviderConfigService.validBaseUrl("http://10.0.0.300/v1"));
    assertFalse(ProviderConfigService.validBaseUrl("https://user:pass@api.example.com"));
    assertFalse(ProviderConfigService.validBaseUrl("https://api.example.com/v1?key=x"));
    assertFalse(ProviderConfigService.validBaseUrl("ftp://10.0.0.1"));
    assertFalse(ProviderConfigService.validBaseUrl("https://" + "a".repeat(300) + ".com"));
  }
}
