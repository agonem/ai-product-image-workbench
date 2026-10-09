package com.productimage.business.runtime;

import com.fasterxml.jackson.databind.JsonNode;
import java.io.IOException;
import java.util.regex.Pattern;

/**
 * Per-model parameters and clarity support (ADR-20261009-Q), from contracts/model-parameters.json.
 * A family is matched by purpose and model id; administrators may only store the listed values, and
 * the pages' "高清" options exist only where the family says how to request them.
 */
final class ModelParameters {
  private static final JsonNode CATALOG = load();

  private ModelParameters() {}

  private static JsonNode load() {
    try (var input =
        ModelParameters.class.getResourceAsStream("/contracts/model-parameters.json")) {
      if (input == null) throw new IllegalStateException("Missing model parameters");
      return Json.MAPPER.readTree(input);
    } catch (IOException ex) {
      throw new IllegalStateException("Cannot load model parameters", ex);
    }
  }

  /** Outputs with a longer side than this are the "高清" size and need a 2K-capable model. */
  static int standardMaxSide() {
    return CATALOG.path("standard_max_side").asInt();
  }

  /** The first family of this purpose whose pattern matches the model id, or a missing node. */
  static JsonNode family(String model, String purpose) {
    for (var family : CATALOG.path("families"))
      if (family.path("purpose").asText().equals(purpose)
          && Pattern.compile(family.path("match").asText()).matcher(model).find()) return family;
    return Json.MAPPER.missingNode();
  }

  /** Stored parameters: an object of listed keys, each with one of its listed string values. */
  static void validate(String model, String purpose, JsonNode parameters) {
    if (!parameters.isObject()) throw new Problem(400, "INVALID_CONTRACT");
    var allowed = family(model, purpose).path("parameters");
    parameters
        .properties()
        .forEach(
            entry -> {
              boolean listed = false;
              for (var value : allowed.path(entry.getKey()).path("values"))
                listed |= value.path("value").asText().equals(entry.getValue().asText());
              if (!entry.getValue().isTextual() || !listed)
                throw new Problem(400, "INVALID_CONTRACT");
            });
  }

  /** The page may offer "画质：高清" for this model. */
  static boolean highQuality(String model, String purpose) {
    return family(model, purpose).has("high");
  }

  /** The page may offer "尺寸：高清" for this model. */
  static boolean largeSize(String model, String purpose) {
    return family(model, purpose).has("large");
  }
}
