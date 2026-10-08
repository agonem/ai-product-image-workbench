package com.productimage.business.runtime;

import static org.junit.jupiter.api.Assertions.*;

import com.fasterxml.jackson.databind.node.ObjectNode;
import org.junit.jupiter.api.Test;
import org.springframework.mock.env.MockEnvironment;

class GenerationPolicyTest {
  private static ObjectNode request(String feature) {
    return (ObjectNode)
        Json.parse(
            """
            {"feature_type":"%s","style":"warm",
             "text":{"points":["安全材质"],"color":"#112233","size":40,"align":"left",
                     "box":{"x":0.05,"y":0.05,"width":0.4,"height":0.5}},
             "output":{"aspect_ratio":"4:3","width":800,"height":600,"format":"png","count":1}}
            """
                .formatted(feature));
  }

  private static void rejected(GenerationPolicy policy, ObjectNode request) {
    var problem = assertThrows(Problem.class, () -> policy.validate(request));
    assertEquals("INVALID_LAYOUT", problem.code);
  }

  @Test
  void defaultsAllowOneToFourImagesWithExactRatio() {
    var policy = new GenerationPolicy(new MockEnvironment());
    assertDoesNotThrow(() -> policy.validate(request("SCENE")));
    var four = request("SCENE");
    ((ObjectNode) four.get("output")).put("count", 4);
    assertDoesNotThrow(() -> policy.validate(four));
    var five = request("SCENE");
    ((ObjectNode) five.get("output")).put("count", 5);
    rejected(policy, five);
    var ratio = request("SCENE");
    ((ObjectNode) ratio.get("output")).put("height", 601);
    rejected(policy, ratio);
    var pixels = request("SCENE");
    ((ObjectNode) pixels.get("output")).put("width", 2048).put("height", 2048);
    ((ObjectNode) pixels.get("output")).put("aspect_ratio", "1:1");
    assertDoesNotThrow(() -> policy.validate(pixels));
    var ratioNotDeployed = request("SCENE");
    ((ObjectNode) ratioNotDeployed.get("output")).put("aspect_ratio", "21:9");
    rejected(policy, ratioNotDeployed);
  }

  @Test
  void sellingPointsNeedOneImagePerPointAndTextInsideCanvas() {
    var policy = new GenerationPolicy(new MockEnvironment());
    assertDoesNotThrow(() -> policy.validate(request("SELLING_POINT")));
    var mismatch = request("SELLING_POINT");
    ((ObjectNode) mismatch.get("output")).put("count", 2);
    rejected(policy, mismatch);
    // Six points make six images: the per-entry limit (4) does not apply (ADR-20261008-G).
    var six = request("SELLING_POINT");
    var points = ((ObjectNode) six.get("text")).putArray("points");
    for (int i = 1; i <= 6; i++) points.add("卖点" + i);
    ((ObjectNode) six.get("output")).put("count", 6);
    assertDoesNotThrow(() -> policy.validate(six));
    ((ObjectNode) six.get("output")).put("count", 5);
    rejected(policy, six);
    var box = request("SELLING_POINT");
    ((ObjectNode) box.path("text").path("box")).put("x", 0.7);
    rejected(policy, box);
  }

  @Test
  void disabledDeploymentRejectsAndPresetsAreBundled() {
    var disabled =
        new GenerationPolicy(new MockEnvironment().withProperty("GENERATION_ENABLED", "false"));
    assertEquals(
        503, assertThrows(Problem.class, () -> disabled.validate(request("SCENE"))).status);
    var policy = new GenerationPolicy(new MockEnvironment());
    assertEquals("presets-v1", policy.version());
    assertEquals("婴儿房", policy.scene("nursery").path("name").asText());
    assertEquals("#4A2E1F", policy.style("warm").path("title_color").asText());
    assertThrows(Problem.class, () -> policy.scene("missing"));
    var options = policy.options();
    assertEquals(4, options.path("max_count").asInt());
    assertTrue(options.path("styles").get(0).has("badge_color"));
    assertFalse(options.toString().contains("prompt"));
  }
}
