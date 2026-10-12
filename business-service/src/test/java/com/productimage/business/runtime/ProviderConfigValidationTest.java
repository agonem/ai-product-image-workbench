package com.productimage.business.runtime;

import static org.junit.jupiter.api.Assertions.assertDoesNotThrow;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

import org.junit.jupiter.api.Test;

/** ADR-20261012-AB: model interfaces hold key, address and proxy; models hold the rest. */
class ProviderConfigValidationTest {
  private static final String INTERFACE =
      "\"name\":\"主力\",\"api_key\":\"sk-x\",\"use_proxy\":false";
  private static final String MODEL = "\"interface_id\":\"i\",\"name\":\"主力\",\"enabled\":true";

  private static void interfaceAccepted(String fields) {
    String json = "{" + fields + "," + INTERFACE + "}";
    assertDoesNotThrow(() -> ProviderConfigService.validateInterface(Json.parse(json), true), json);
  }

  private static void interfaceRejected(String json) {
    assertThrows(
        Problem.class, () -> ProviderConfigService.validateInterface(Json.parse(json), true), json);
  }

  private static void modelAccepted(String kind, String fields) {
    String json = "{" + fields + "," + MODEL + "}";
    assertDoesNotThrow(() -> ProviderConfigService.validateModel(kind, Json.parse(json)), json);
  }

  private static void modelRejected(String kind, String fields) {
    String json = "{" + fields + "," + MODEL + "}";
    assertThrows(
        Problem.class, () -> ProviderConfigService.validateModel(kind, Json.parse(json)), json);
  }

  @Test
  void thirdPartyInterfacesNeedAnAddressHttpOnlyOnTheIntranet() {
    interfaceAccepted("\"kind\":\"openai-compatible\",\"base_url\":\"http://10.2.2.110:3000/v1\"");
    interfaceAccepted("\"kind\":\"openai-compatible\",\"base_url\":\"https://relay.example.com\"");
    // Public plain http, credentials in the address, or no address at all are refused.
    interfaceRejected(
        "{\"kind\":\"openai-compatible\",\"base_url\":\"http://8.8.8.8/v1\"," + INTERFACE + "}");
    interfaceRejected(
        "{\"kind\":\"openai-compatible\",\"base_url\":\"https://u:p@relay.example.com\","
            + INTERFACE
            + "}");
    interfaceRejected("{\"kind\":\"openai-compatible\"," + INTERFACE + "}");
    // Official types never take an address.
    interfaceRejected(
        "{\"kind\":\"openai\",\"base_url\":\"https://relay.example.com\"," + INTERFACE + "}");
  }

  @Test
  void theFiveOfferedInterfaceTypes() {
    for (String kind : new String[] {"openrouter", "openai", "deepseek", "gemini"})
      interfaceAccepted("\"kind\":\"" + kind + "\"");
    // The older Gemini-format third party is no longer created, but an existing one still edits.
    String legacy =
        "{\"kind\":\"gemini-compatible\",\"base_url\":\"https://relay.example.com\","
            + INTERFACE
            + "}";
    interfaceRejected(legacy);
    assertDoesNotThrow(() -> ProviderConfigService.validateInterface(Json.parse(legacy), false));
    interfaceRejected("{\"kind\":\"other\"," + INTERFACE + "}");
    interfaceRejected("{\"kind\":\"openai\",\"name\":\" \",\"api_key\":\"k\",\"use_proxy\":false}");
    interfaceRejected(
        "{\"kind\":\"openai\",\"name\":\""
            + "名".repeat(41)
            + "\",\"api_key\":\"k\",\"use_proxy\":false}");
    interfaceRejected(
        "{\"kind\":\"openai\",\"name\":\"n\",\"api_key\":\"k k\",\"use_proxy\":false}");
    interfaceRejected("{\"kind\":\"openai\",\"name\":\"n\",\"api_key\":\"k\"}");
    // Models' fields do not belong on the interface.
    interfaceRejected("{\"kind\":\"openai\",\"model\":\"gpt-image-2\"," + INTERFACE + "}");
  }

  @Test
  void modelsCarryOnlyTheirInterfaceTypesFields() {
    modelAccepted("openrouter", "\"model\":\"openai/gpt-image-2\",\"provider_tag\":\"openai\"");
    // An OpenRouter text model may leave routing to OpenRouter (ADR-20261008-L follow-up).
    modelAccepted(
        "openrouter",
        "\"model\":\"deepseek/deepseek-v4.1-flash\",\"purpose\":\"TEXT\",\"vision\":true");
    modelAccepted("openai", "\"model\":\"gpt-image-2\"");
    modelAccepted("gemini", "\"model\":\"gemini-2.5-flash-image\"");
    modelAccepted("deepseek", "\"model\":\"deepseek-flash\",\"purpose\":\"TEXT\",\"vision\":false");
    modelAccepted("openai-compatible", "\"model\":\"gpt-image-2-c\"");
    // DeepSeek draws no pictures; the image model on OpenRouter pins a provider; tags and
    // vision only where they belong; OpenRouter ids are vendor/model.
    modelRejected("deepseek", "\"model\":\"deepseek-flash\"");
    modelRejected("openrouter", "\"model\":\"openai/gpt-image-2\"");
    modelRejected("openrouter", "\"model\":\"no-slash\",\"provider_tag\":\"t\"");
    modelRejected("openai", "\"model\":\"gpt-image-2\",\"provider_tag\":\"x\"");
    modelRejected("openai", "\"model\":\"gpt-image-2\",\"vision\":true");
    modelRejected("openai", "\"model\":\"gpt image\"");
    modelRejected("openai", "\"model\":\"m\",\"purpose\":\"OTHER\"");
    // The key and address are the interface's now.
    modelRejected("openai", "\"model\":\"m\",\"api_key\":\"k\"");
    modelRejected("openai", "\"model\":\"m\",\"use_proxy\":true");
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
