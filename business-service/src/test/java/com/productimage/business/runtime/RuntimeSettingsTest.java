package com.productimage.business.runtime;

import static org.junit.jupiter.api.Assertions.*;

import org.junit.jupiter.api.Test;
import org.springframework.mock.env.MockEnvironment;

class RuntimeSettingsTest {
  private MockEnvironment configured() {
    return new MockEnvironment()
        .withProperty("RUNTIME_API_TOKEN", "a".repeat(32))
        .withProperty("RUNTIME_WORKER_TOKEN", "b".repeat(32))
        .withProperty("RUNTIME_USER_ID", "fixture_user")
        .withProperty("OBJECT_STORE_ROOT", ".artifacts/settings-test");
  }

  @Test
  void failsClosedForMissingSharedOrPublicCredentials() {
    assertThrows(IllegalStateException.class, () -> RuntimeSettings.from(new MockEnvironment()));
    assertThrows(
        IllegalStateException.class,
        () -> RuntimeSettings.from(configured().withProperty("server.address", "0.0.0.0")));
    assertThrows(
        IllegalStateException.class,
        () ->
            RuntimeSettings.from(
                configured().withProperty("RUNTIME_WORKER_TOKEN", "a".repeat(32))));
    assertThrows(
        IllegalStateException.class,
        () -> RuntimeSettings.from(configured().withProperty("RUNTIME_API_TOKEN", "short")));
    assertThrows(
        IllegalStateException.class,
        () -> RuntimeSettings.from(configured().withProperty("WORK_LEASE_SECONDS", "0")));
  }

  @Test
  void credentialsCannotCrossServiceBoundary() {
    var settings = RuntimeSettings.from(configured());
    assertDoesNotThrow(() -> settings.authorize("Bearer " + "a".repeat(32), false));
    assertDoesNotThrow(() -> settings.authorize("Bearer " + "b".repeat(32), true));
    assertThrows(Problem.class, () -> settings.authorize(null, false));
    assertThrows(Problem.class, () -> settings.authorize("Bearer " + "a".repeat(32), true));
    assertThrows(Problem.class, () -> settings.authorize("Bearer " + "b".repeat(32), false));
  }
}
