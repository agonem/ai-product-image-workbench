package com.productimage.business.runtime;

import com.fasterxml.jackson.databind.JsonNode;
import java.io.IOException;
import java.util.ArrayList;
import java.util.List;
import java.util.regex.Pattern;

/**
 * Per-model parameters and clarity (ADR-20261009-Q, -R), from contracts/model-parameters.json. A
 * family is matched by purpose and model id; administrators may only store the listed values, and
 * the pages offer the clarities (1K, 2K) the family says how to request.
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

  /** The clarities (e.g. ["1K", "2K"]) the pages may offer for this model; empty if unknown. */
  static List<String> resolutions(String model, String purpose) {
    var names = new ArrayList<String>();
    family(model, purpose).path("resolutions").properties().forEach(e -> names.add(e.getKey()));
    return names;
  }

  /** The page's starting clarity: the model's stored resolution if offered, else the first. */
  static String defaultResolution(String model, String purpose, JsonNode stored) {
    var offered = resolutions(model, purpose);
    String chosen = stored.path("resolution").asText();
    return offered.contains(chosen) ? chosen : offered.isEmpty() ? null : offered.getFirst();
  }
}
