package com.productimage.business.runtime;

import com.fasterxml.jackson.databind.JsonNode;
import java.io.IOException;
import java.util.ArrayList;
import java.util.List;
import java.util.regex.Pattern;

/**
 * Model interfaces and their official parameters (ADR-20261012-AB), from
 * contracts/model-parameters.json. A set is matched by interface kind, purpose and model id; an
 * administrator may only store the parameters it lists, each in its type and range (blank ones are
 * not stored, so the vendor's default applies), and the pages offer the clarities (1K, 2K) the set
 * says how to request.
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

  /** The interface type's entry (label, purposes, offered), or a missing node. */
  static JsonNode kind(String kind) {
    return CATALOG.path("kinds").path(kind);
  }

  /** Whether new interfaces of this type may be created. */
  static boolean offered(String kind) {
    return kind(kind).path("offered").asBoolean();
  }

  /** Whether models of this purpose can be added to an interface of this type. */
  static boolean serves(String kind, String purpose) {
    for (var item : kind(kind).path("purposes")) if (item.asText().equals(purpose)) return true;
    return false;
  }

  /** The first set for this interface type and purpose whose pattern matches the model id. */
  static JsonNode set(String kind, String model, String purpose) {
    for (var set : CATALOG.path("sets")) {
      boolean forKind = false;
      for (var item : set.path("kinds")) forKind |= item.asText().equals(kind);
      if (forKind
          && set.path("purpose").asText().equals(purpose)
          && Pattern.compile(set.path("match").asText()).matcher(model).find()) return set;
    }
    return Json.MAPPER.missingNode();
  }

  /**
   * Stored parameters: an object of listed names, each value in its listed type - one of the values
   * (enum), a number in range (number) or a whole number in range (integer).
   */
  static void validate(String kind, String model, String purpose, JsonNode parameters) {
    if (!parameters.isObject() || parameters.size() > 20)
      throw new Problem(400, "INVALID_CONTRACT");
    var specs = set(kind, model, purpose).path("parameters");
    parameters
        .properties()
        .forEach(
            entry -> {
              JsonNode spec = null;
              for (var item : specs)
                if (item.path("name").asText().equals(entry.getKey())) spec = item;
              if (spec == null || !accepts(spec, entry.getValue()))
                throw new Problem(400, "INVALID_CONTRACT");
            });
  }

  private static boolean accepts(JsonNode spec, JsonNode value) {
    switch (spec.path("type").asText()) {
      case "enum" -> {
        if (!value.isTextual()) return false;
        for (var option : spec.path("values"))
          if (option.path("value").asText().equals(value.asText())) return true;
        return false;
      }
      case "number", "integer" -> {
        if (!value.isNumber()) return false;
        double number = value.asDouble();
        if (!Double.isFinite(number)) return false;
        if (spec.path("type").asText().equals("integer") && number != Math.rint(number))
          return false;
        return number >= spec.path("min").asDouble() && number <= spec.path("max").asDouble();
      }
      default -> {
        return false;
      }
    }
  }

  /** The clarities (e.g. ["1K", "2K"]) the pages may offer for this model; empty if unknown. */
  static List<String> resolutions(String kind, String model, String purpose) {
    var names = new ArrayList<String>();
    set(kind, model, purpose).path("resolutions").properties().forEach(e -> names.add(e.getKey()));
    return names;
  }

  /** The page's starting clarity: the first one the model offers (ADR-20261012-AB). */
  static String defaultResolution(String kind, String model, String purpose) {
    var offered = resolutions(kind, model, purpose);
    return offered.isEmpty() ? null : offered.getFirst();
  }
}
