package com.productimage.business.runtime;

import com.fasterxml.jackson.databind.JsonNode;
import java.util.Arrays;
import java.util.List;
import org.springframework.core.env.Environment;

/** Explicit deployment capabilities; never a claim about marketplace requirements. */
final class ScenePolicy {
  private final boolean enabled;
  private final int maximum;
  private final List<String> ratios, resolutions, formats;

  ScenePolicy(Environment env) {
    enabled = env.getProperty("SCENE_ENABLED", Boolean.class, false);
    maximum = env.getProperty("SCENE_MAX_COUNT", Integer.class, 3);
    ratios = values(env, "SCENE_ASPECT_RATIOS", "1:1");
    resolutions = values(env, "SCENE_RESOLUTIONS", "1K");
    formats = values(env, "SCENE_FORMATS", "png,jpeg");
    if (maximum < 3
        || maximum > 100
        || ratios.stream().anyMatch(v -> !v.matches("[1-9][0-9]?:[1-9][0-9]?"))
        || resolutions.stream().anyMatch(v -> !List.of("512", "1K", "2K").contains(v))
        || formats.stream().anyMatch(v -> !List.of("png", "jpeg").contains(v)))
      throw new IllegalArgumentException("Invalid scene deployment capabilities");
  }

  private static List<String> values(Environment env, String key, String fallback) {
    var values =
        Arrays.stream(env.getProperty(key, fallback).split(","))
            .map(String::trim)
            .distinct()
            .toList();
    if (values.isEmpty() || values.contains(""))
      throw new IllegalArgumentException("Empty scene capability");
    return values;
  }

  void validate(JsonNode output) {
    if (!enabled) throw new Problem(422, "PROVIDER_UNAVAILABLE");
    if (!ratios.contains(output.path("aspect_ratio").asText())
        || (!output.has("width") && !resolutions.contains(output.path("resolution").asText()))
        || !formats.contains(output.path("format").asText())
        || output.path("count").asInt() < 1
        || output.path("count").asInt() > maximum) throw new Problem(422, "INVALID_LAYOUT");
    if (output.has("width")) {
      int w = output.path("width").asInt(), h = output.path("height").asInt();
      String[] ratio = output.path("aspect_ratio").asText().split(":");
      if (w < 64
          || h < 64
          || w > 2048
          || h > 2048
          || w * Integer.parseInt(ratio[1]) != h * Integer.parseInt(ratio[0]))
        throw new Problem(422, "INVALID_LAYOUT");
    }
  }

  JsonNode options() {
    var result = Json.object().put("enabled", enabled).put("max_count", maximum);
    ratios.forEach(result.putArray("aspect_ratios")::add);
    resolutions.forEach(result.putArray("resolutions")::add);
    formats.forEach(result.putArray("formats")::add);
    return result;
  }
}
