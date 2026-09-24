package com.productimage.workbench.contract;

import static org.junit.jupiter.api.Assertions.*;

import org.junit.jupiter.api.Test;

class RequestFingerprintTest {
  @Test
  void canonicalizesObjectsAndNumbers() {
    assertEquals(
        RequestFingerprint.sha256("{\"b\":1.0,\"a\":{\"z\":-0.0,\"x\":1e2}}"),
        RequestFingerprint.sha256("{\"a\":{\"x\":100,\"z\":0},\"b\":1}"));
    assertTrue(RequestFingerprint.sha256("{}").matches("[0-9a-f]{64}"));
  }

  @Test
  void preservesMeaningfulDifferences() {
    assertNotEquals(RequestFingerprint.sha256("[1,2]"), RequestFingerprint.sha256("[2,1]"));
    assertNotEquals(
        RequestFingerprint.sha256("{\"prompt\":\"a \"}"),
        RequestFingerprint.sha256("{\"prompt\":\"a\"}"));
    assertNotEquals(
        RequestFingerprint.sha256("{\"x\":9007199254740992}"),
        RequestFingerprint.sha256("{\"x\":9007199254740993}"));
  }

  @Test
  void rejectsAmbiguousOrInvalidJson() {
    for (String json : new String[] {"{\"x\":1,\"x\":2}", "{} {}", "NaN", "", "null"}) {
      assertThrows(IllegalArgumentException.class, () -> RequestFingerprint.sha256(json));
    }
  }

  @Test
  void rejectsUnpairedSurrogatesBeforeUtf8Encoding() {
    String invalid = Character.toString((char) 0xd800);
    assertThrows(
        IllegalArgumentException.class,
        () -> RequestFingerprint.sha256("{\"x\":\"" + invalid + "\"}"));
    assertThrows(
        IllegalArgumentException.class, () -> RequestFingerprint.sha256("{\"" + invalid + "\":1}"));
    assertNotEquals(
        RequestFingerprint.sha256("{\"x\":\"😀\"}"), RequestFingerprint.sha256("{\"x\":\"?\"}"));
  }
}
