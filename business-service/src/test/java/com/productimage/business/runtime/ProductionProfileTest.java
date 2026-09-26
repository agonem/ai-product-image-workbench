package com.productimage.business.runtime;

import static org.junit.jupiter.api.Assertions.*;

import org.junit.jupiter.api.Test;
import org.springframework.mock.env.MockEnvironment;

class ProductionProfileTest {
  private MockEnvironment production() {
    var env = new MockEnvironment();
    env.setActiveProfiles("prod-local", "runtime", "database");
    return env.withProperty("APP_ENV", "production")
        .withProperty("server.address", "0.0.0.0")
        .withProperty("server.ssl.enabled", "true")
        .withProperty("RUNTIME_WORKER_TOKEN", "w".repeat(32))
        .withProperty("OBJECT_STORE_ROOT", ".artifacts/test-store");
  }

  @Test
  void productionUsesSeparateAuthenticationAndRequiresTls() {
    var settings = assertDoesNotThrow(() -> RuntimeSettings.from(production()));
    assertNull(settings.apiToken());
    assertNull(settings.userId());
    assertThrows(Problem.class, () -> settings.authorize("Bearer " + "w".repeat(32), false));
    assertThrows(
        IllegalStateException.class,
        () -> RuntimeSettings.from(production().withProperty("server.ssl.enabled", "false")));
  }

  @Test
  void productionCannotMixDevelopmentOrWrongEnvironment() {
    var mixed = production();
    mixed.setActiveProfiles("prod-local", "dev-local", "runtime", "database");
    assertThrows(IllegalStateException.class, () -> RuntimeSettings.from(mixed));
    assertThrows(
        IllegalStateException.class,
        () -> RuntimeSettings.from(production().withProperty("APP_ENV", "development")));
  }
}
