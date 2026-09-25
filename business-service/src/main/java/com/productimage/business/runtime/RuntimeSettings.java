package com.productimage.business.runtime;

import java.nio.charset.StandardCharsets;
import java.nio.file.Path;
import java.security.MessageDigest;
import org.springframework.core.env.Environment;

public record RuntimeSettings(
    String userId,
    String apiToken,
    String workerToken,
    Path root,
    int leaseSeconds,
    int maxDeliveries,
    int backoffSeconds,
    int maxAttempts,
    int maxBytes,
    long maxPixels) {
  public static RuntimeSettings from(Environment env) {
    String host = env.getProperty("server.address", "127.0.0.1");
    if (!host.equals("127.0.0.1") && !host.equals("::1")) {
      throw new IllegalStateException("runtime profile requires loopback binding");
    }
    boolean local = java.util.Arrays.asList(env.getActiveProfiles()).contains("dev-local");
    if (local
        && (!"development".equals(env.getProperty("APP_ENV"))
            || java.util.Arrays.stream(env.getActiveProfiles())
                .anyMatch(
                    profile ->
                        !java.util.Set.of("dev-local", "runtime", "database").contains(profile)))) {
      throw new IllegalStateException("Local accounts require the isolated development profile");
    }
    String api = local ? null : env.getRequiredProperty("RUNTIME_API_TOKEN");
    String worker = env.getRequiredProperty("RUNTIME_WORKER_TOKEN");
    String user = local ? null : env.getRequiredProperty("RUNTIME_USER_ID");
    if (worker.length() < 32
        || (!local
            && (api.length() < 32
                || api.equals(worker)
                || !user.matches("[A-Za-z0-9][A-Za-z0-9_-]*")))) {
      throw new IllegalStateException("Invalid runtime credential configuration");
    }
    return new RuntimeSettings(
        user,
        api,
        worker,
        Path.of(env.getRequiredProperty("OBJECT_STORE_ROOT")),
        number(env, "WORK_LEASE_SECONDS", 60, 2, 3600),
        number(env, "WORK_MAX_DELIVERIES", 3, 1, 100),
        number(env, "WORK_BACKOFF_SECONDS", 2, 0, 300),
        number(env, "WORK_MAX_ATTEMPTS", 5, 1, 100),
        number(env, "OBJECT_MAX_BYTES", 10485760, 1, 67108864),
        number(env, "OBJECT_MAX_PIXELS", 16000000, 1, 100000000));
  }

  private static int number(Environment env, String key, int fallback, int min, int max) {
    int value = env.getProperty(key, Integer.class, fallback);
    if (value < min || value > max)
      throw new IllegalStateException("Invalid runtime limit: " + key);
    return value;
  }

  public void authorize(String header, boolean worker) {
    String credential = worker ? workerToken : apiToken;
    if (credential == null) throw new Problem(401, "UNAUTHORIZED");
    String expected = "Bearer " + credential;
    if (header == null
        || !MessageDigest.isEqual(
            expected.getBytes(StandardCharsets.UTF_8), header.getBytes(StandardCharsets.UTF_8)))
      throw new Problem(401, "UNAUTHORIZED");
  }
}
