package com.productimage.business.runtime;

import com.fasterxml.jackson.databind.JsonNode;
import java.util.HashSet;

/**
 * v4 receipt checks before atomically publishing a batch: every final image has the exact requested
 * size/format, every model output is distinct and bound to the frozen input hashes, and the
 * recorded crop is the deterministic cover-centre crop of the stored model output.
 */
final class GenerationOutputs {
  // The mock value exists only for isolated acceptance workers and is stored as such.
  private static final java.util.Set<String> MODEL_SOURCES =
      java.util.Set.of(
          "openrouter-images-api",
          "openai-images-api",
          "gemini-generate-content",
          "mock-acceptance-only");

  private GenerationOutputs() {}

  static void validate(LocalObjectStore store, String prefix, JsonNode request, JsonNode receipt) {
    var output = request.path("output");
    int count = output.path("count").asInt();
    int width = output.path("width").asInt(), height = output.path("height").asInt();
    boolean retypeset = request.has("base_image");
    // Keep-original selling images (ADR-20261008-G): every base is the same cropped original.
    boolean original = !retypeset && request.path("keep_original").asBoolean();
    if (receipt.path("artifacts").size() != count || receipt.path("generations").size() != count)
      invalid();
    var hashes = new HashSet<String>();
    for (int i = 0; i < count; i++) {
      var artifact = receipt.path("artifacts").get(i);
      var generation = receipt.path("generations").get(i);
      check(store, prefix, artifact, i, "COMPOSITE", output.path("format").asText());
      var base = generation.path("base");
      check(store, prefix, base, count + i, "BACKGROUND", null);
      var provenance = generation.path("provenance");
      var inputs = provenance.path("inputs");
      if (generation.path("ordinal").asInt(-1) != i
          || artifact.path("width").asInt() != width
          || artifact.path("height").asInt() != height
          || (!original && !hashes.add(base.path("sha256").asText()))
          || !provenance.path("sha256").equals(base.path("sha256"))
          || !inputs.path("product_sha256").equals(request.path("product_asset").path("sha256"))
          || (request.has("gift_asset")
              && !inputs.path("gift_sha256").equals(request.path("gift_asset").path("sha256")))
          || (request.has("edit_image")
              && !retypeset
              && !inputs.path("edit_sha256").equals(request.path("edit_image").path("sha256")))
          || (request.has("references") && !retypeset && !sameReferences(request, inputs))
          || provenance.path("text_rendered").asBoolean() != request.has("text")) invalid();
      if (retypeset) {
        // No model call: the stored base is exactly the frozen source image.
        if (!"retypeset".equals(provenance.path("output_source").asText())
            || !base.path("sha256").equals(request.path("base_image").path("sha256"))
            || !inputs.path("base_sha256").equals(request.path("base_image").path("sha256")))
          invalid();
      } else if (original) {
        if (!"original".equals(provenance.path("output_source").asText())
            || !provenance.path("source_transform").isObject()) invalid();
      } else if (!MODEL_SOURCES.contains(provenance.path("output_source").asText())
          || !provenance
              .path("correlation_id")
              .asText()
              .equals(request.path("attempt_id").asText() + "-" + i)
          || !provenance
              .path("parameters")
              .path("aspect_ratio")
              .equals(output.path("aspect_ratio"))) invalid();
      var transform = provenance.path("transform");
      int sw = base.path("width").asInt(), sh = base.path("height").asInt();
      double scale = Math.max((double) width / sw, (double) height / sh);
      int rw = (int) Math.ceil(sw * scale), rh = (int) Math.ceil(sh * scale);
      int x = (rw - width) / 2, y = (rh - height) / 2;
      if (!"cover-center-v1".equals(transform.path("strategy").asText())
          || !transform.path("source_size").equals(Json.parse("[" + sw + "," + sh + "]"))
          || !transform.path("resized_size").equals(Json.parse("[" + rw + "," + rh + "]"))
          || !transform.path("target_size").equals(Json.parse("[" + width + "," + height + "]"))
          || !transform
              .path("crop")
              .equals(Json.parse("[" + x + "," + y + "," + (x + width) + "," + (y + height) + "]")))
        invalid();
    }
  }

  private static boolean sameReferences(JsonNode request, JsonNode inputs) {
    var expected = Json.MAPPER.createArrayNode();
    request.path("references").forEach(item -> expected.add(item.path("sha256")));
    return expected.equals(inputs.path("reference_sha256"));
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
