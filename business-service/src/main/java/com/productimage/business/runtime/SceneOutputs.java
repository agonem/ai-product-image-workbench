package com.productimage.business.runtime;

import com.fasterxml.jackson.databind.JsonNode;
import java.util.HashSet;

/** Validate private intermediate objects before atomically publishing the batch. */
final class SceneOutputs {
  private SceneOutputs() {}

  static void validate(LocalObjectStore store, String prefix, JsonNode request, JsonNode receipt) {
    int count = request.path("output").path("count").asInt();
    var output = request.path("output");
    boolean local = request.path("schema_version").asInt() == 3;
    if (receipt.path("artifacts").size() != count
        || receipt.path("background_generations").size() != count) invalid();
    var hashes = new HashSet<String>();
    String[] ratio = output.path("aspect_ratio").asText().split(":");
    for (int i = 0; i < count; i++) {
      var artifact = receipt.path("artifacts").get(i);
      var generation = receipt.path("background_generations").get(i);
      check(store, prefix, artifact, i, "COMPOSITE", output.path("format").asText());
      check(
          store,
          prefix,
          generation.path("background"),
          count + i,
          "BACKGROUND",
          local ? null : output.path("format").asText());
      check(store, prefix, generation.path("shadow"), count * 2 + i, "ALPHA", "png");
      int width = artifact.path("width").asInt(), height = artifact.path("height").asInt();
      var provenance = generation.path("provenance");
      var parameters = provenance.path("parameters");
      if (generation.path("ordinal").asInt(-1) != i
          || !hashes.add(generation.path("background").path("sha256").asText())
          || width * Integer.parseInt(ratio[1]) != height * Integer.parseInt(ratio[0])
          || !provenance.path("product_sha256").equals(request.path("product_asset").path("sha256"))
          || !provenance
              .path("alpha_sha256")
              .equals(request.path("product_alpha_asset").path("sha256"))
          || !provenance.path("sha256").equals(generation.path("background").path("sha256"))
          || !provenance
              .path("correlation_id")
              .asText()
              .equals(request.path("attempt_id").asText() + "-" + i)
          || !parameters.path("aspect_ratio").equals(output.path("aspect_ratio"))
          || (!local
              && (!parameters.path("resolution").equals(output.path("resolution"))
                  || !parameters.path("output_format").equals(output.path("format"))))) invalid();
      if (local) {
        var transform = provenance.path("background_transform");
        var source = generation.path("background");
        int sw = source.path("width").asInt(), sh = source.path("height").asInt();
        double scale = Math.max((double) width / sw, (double) height / sh);
        int rw = (int) Math.ceil(sw * scale), rh = (int) Math.ceil(sh * scale);
        int x = (rw - width) / 2, y = (rh - height) / 2;
        if (width != output.path("width").asInt()
            || height != output.path("height").asInt()
            || !transform.path("source_size").equals(Json.parse("[" + sw + "," + sh + "]"))
            || !transform.path("resized_size").equals(Json.parse("[" + rw + "," + rh + "]"))
            || !transform.path("target_size").equals(Json.parse("[" + width + "," + height + "]"))
            || !transform
                .path("crop")
                .equals(
                    Json.parse("[" + x + "," + y + "," + (x + width) + "," + (y + height) + "]")))
          invalid();
      }
      for (String field : local ? new String[] {"shadow"} : new String[] {"background", "shadow"}) {
        if (generation.path(field).path("width").asInt() != width
            || generation.path(field).path("height").asInt() != height) invalid();
      }
    }
  }

  private static void check(
      LocalObjectStore store,
      String prefix,
      JsonNode value,
      int ordinal,
      String kind,
      String format) {
    String key = prefix + ordinal + ".image";
    if (value.path("ordinal").asInt(-1) != ordinal
        || !kind.equals(value.path("kind").asText())
        || !key.equals(value.path("object_key").asText())) invalid();
    byte[] bytes = store.read(key);
    var info = store.inspect(key, bytes);
    boolean png = bytes.length > 8 && bytes[0] == (byte) 137 && bytes[1] == 80;
    if ((format != null && png != format.equals("png"))
        || !info.sha256().equals(value.path("sha256").asText())
        || info.width() != value.path("width").asInt()
        || info.height() != value.path("height").asInt()) invalid();
  }

  private static void invalid() {
    throw new Problem(422, "OUTPUT_VALIDATION_FAILED");
  }
}
