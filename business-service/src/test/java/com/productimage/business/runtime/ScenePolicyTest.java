package com.productimage.business.runtime;

import static org.junit.jupiter.api.Assertions.*;

import org.junit.jupiter.api.Test;
import org.springframework.mock.env.MockEnvironment;

class ScenePolicyTest {
  @Test
  void disabledByDefaultAndStrictWhenEnabled() {
    var output =
        Json.parse(
            "{\"aspect_ratio\":\"1:1\",\"resolution\":\"1K\",\"format\":\"png\",\"count\":3}");
    assertThrows(Problem.class, () -> new ScenePolicy(new MockEnvironment()).validate(output));
    var policy = new ScenePolicy(new MockEnvironment().withProperty("SCENE_ENABLED", "true"));
    assertDoesNotThrow(() -> policy.validate(output));
    var changed = output.deepCopy();
    ((com.fasterxml.jackson.databind.node.ObjectNode) changed).put("count", 4);
    assertThrows(Problem.class, () -> policy.validate(changed));
    ((com.fasterxml.jackson.databind.node.ObjectNode) changed)
        .put("count", 3)
        .put("format", "webp");
    assertThrows(Problem.class, () -> policy.validate(changed));
  }
}
