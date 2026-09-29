package com.productimage.business.runtime;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.node.ObjectNode;
import java.io.IOException;
import java.util.Arrays;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import org.springframework.core.env.Environment;

/**
 * v4 whole-image generation rules (ADR-20260929): deployment ratios/formats/count budget and the
 * versioned internal presets (scene presets, selling-point styles). Sizes and counts are local
 * technical budgets, never marketplace rules.
 */
final class GenerationPolicy {
  static final String PRESET = "generation_v4";
  private static final long MAX_PIXELS = 4_194_304L;
  private final boolean enabled;
  private final int maximum;
  private final List<String> ratios, formats;
  private final String version;
  private final Map<String, JsonNode> scenes = new LinkedHashMap<>();
  private final Map<String, JsonNode> styles = new LinkedHashMap<>();

  GenerationPolicy(Environment env) {
    enabled = env.getProperty("GENERATION_ENABLED", Boolean.class, true);
    maximum = env.getProperty("GENERATION_MAX_COUNT", Integer.class, 4);
    ratios = values(env, "GENERATION_ASPECT_RATIOS", "1:1,3:4,4:3,2:3,3:2,9:16,16:9");
    formats = values(env, "GENERATION_FORMATS", "png,jpeg");
    if (maximum < 1
        || maximum > 10
        || ratios.stream().anyMatch(v -> !v.matches("[1-9][0-9]?:[1-9][0-9]?"))
        || formats.stream().anyMatch(v -> !List.of("png", "jpeg").contains(v)))
      throw new IllegalArgumentException("Invalid generation deployment capabilities");
    try (var input = GenerationPolicy.class.getResourceAsStream("/contracts/presets.json")) {
      if (input == null) throw new IllegalStateException("Missing bundled presets");
      JsonNode presets = Json.MAPPER.readTree(input);
      version = presets.path("version").asText();
      presets.path("scenes").forEach(item -> scenes.put(item.path("id").asText(), item));
      presets.path("styles").forEach(item -> styles.put(item.path("id").asText(), item));
    } catch (IOException ex) {
      throw new IllegalStateException("Cannot load bundled presets", ex);
    }
    if (version.isBlank() || scenes.isEmpty() || styles.isEmpty())
      throw new IllegalStateException("Empty bundled presets");
  }

  private static List<String> values(Environment env, String key, String fallback) {
    var values =
        Arrays.stream(env.getProperty(key, fallback).split(","))
            .map(String::trim)
            .distinct()
            .toList();
    if (values.isEmpty() || values.contains(""))
      throw new IllegalArgumentException("Empty generation capability");
    return values;
  }

  String version() {
    return version;
  }

  /** Resolved preset/style copies are frozen into the task snapshot. */
  JsonNode scene(String id) {
    var scene = scenes.get(id);
    if (scene == null) throw new Problem(422, "INVALID_LAYOUT");
    return scene.deepCopy();
  }

  JsonNode style(String id) {
    var style = styles.get(id);
    if (style == null) throw new Problem(422, "INVALID_LAYOUT");
    return style.deepCopy();
  }

  void validate(JsonNode request) {
    if (!enabled) throw new Problem(503, "PROVIDER_DISABLED");
    var output = request.path("output");
    int count = output.path("count").asInt();
    long width = output.path("width").asLong(), height = output.path("height").asLong();
    String[] ratio = output.path("aspect_ratio").asText().split(":");
    if (!ratios.contains(output.path("aspect_ratio").asText())
        || !formats.contains(output.path("format").asText())
        || count < 1
        || count > maximum
        || width * Long.parseLong(ratio[1]) != height * Long.parseLong(ratio[0])
        || width * height > MAX_PIXELS) throw new Problem(422, "INVALID_LAYOUT");
    // Selling points: exactly one image per selected style, so no image is a repeat.
    if (request.path("feature_type").asText().equals("SELLING_POINT")
        && request.path("styles").size() != count) throw new Problem(422, "INVALID_LAYOUT");
    validateText(request.path("text"));
  }

  static void validateText(JsonNode text) {
    var box = text.path("box");
    if (!text.isMissingNode()
        && (box.path("x").asDouble() + box.path("width").asDouble() > 1.000001
            || box.path("y").asDouble() + box.path("height").asDouble() > 1.000001))
      throw new Problem(422, "INVALID_LAYOUT");
  }

  JsonNode options() {
    ObjectNode result =
        Json.object()
            .put("enabled", enabled)
            .put("max_count", maximum)
            .put("max_side", 2048)
            .put("max_pixels", MAX_PIXELS)
            .put("presets_version", version);
    ratios.forEach(result.putArray("aspect_ratios")::add);
    formats.forEach(result.putArray("formats")::add);
    var sceneList = result.putArray("scene_presets");
    scenes
        .values()
        .forEach(
            s ->
                sceneList
                    .addObject()
                    .put("id", s.path("id").asText())
                    .put("name", s.path("name").asText()));
    var styleList = result.putArray("styles");
    for (var style : styles.values()) {
      var item = styleList.addObject();
      for (String field :
          new String[] {
            "id", "name", "title_color", "badge_color", "badge_text_color", "accent_color"
          }) item.put(field, style.path(field).asText());
    }
    return result;
  }
}
