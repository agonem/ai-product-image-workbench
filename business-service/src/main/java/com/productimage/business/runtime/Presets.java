package com.productimage.business.runtime;

import com.fasterxml.jackson.databind.JsonNode;
import java.io.IOException;
import java.util.Collection;
import java.util.LinkedHashMap;
import java.util.Map;

/**
 * One version of the scene presets and selling-point styles. Resolved copies are frozen into task
 * snapshots, so a later edit never changes what an earlier task used.
 */
final class Presets {
  private final String version;
  private final Map<String, JsonNode> scenes = new LinkedHashMap<>();
  private final Map<String, JsonNode> styles = new LinkedHashMap<>();

  Presets(String version, JsonNode config) {
    this.version = version;
    config.path("scenes").forEach(item -> scenes.put(item.path("id").asText(), item));
    config.path("styles").forEach(item -> styles.put(item.path("id").asText(), item));
    if (version.isBlank() || scenes.isEmpty() || styles.isEmpty())
      throw new IllegalStateException("Empty presets");
  }

  /** The defaults shipped with the application (contracts/presets.json). */
  static Presets bundled() {
    try (var input = Presets.class.getResourceAsStream("/contracts/presets.json")) {
      if (input == null) throw new IllegalStateException("Missing bundled presets");
      JsonNode presets = Json.MAPPER.readTree(input);
      return new Presets(presets.path("version").asText(), presets);
    } catch (IOException ex) {
      throw new IllegalStateException("Cannot load bundled presets", ex);
    }
  }

  String version() {
    return version;
  }

  Presets self() {
    return this;
  }

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

  Collection<JsonNode> scenes() {
    return scenes.values();
  }

  Collection<JsonNode> styles() {
    return styles.values();
  }
}
