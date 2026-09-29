package com.productimage.business.runtime;

import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.context.annotation.Profile;
import org.springframework.core.env.Environment;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.scheduling.annotation.EnableScheduling;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.support.TransactionTemplate;

@Configuration
@Profile("runtime")
@EnableScheduling
public class RuntimeConfiguration {
  @Bean
  RuntimeSettings runtimeSettings(Environment env) {
    return RuntimeSettings.from(env);
  }

  @Bean
  ProjectAccess projectAccess(JdbcTemplate jdbc) {
    return new ProjectAccess(jdbc);
  }

  @Bean
  @Profile("!dev-local & !prod-local")
  UserAuthenticator staticUserAuthenticator(RuntimeSettings settings, ProjectAccess access) {
    return header -> {
      settings.authorize(header, false);
      access.active(settings.userId());
      return settings.userId();
    };
  }

  @Bean
  @Profile("dev-local")
  LocalAccounts localAccounts(
      Environment env,
      RuntimeSettings settings,
      JdbcTemplate jdbc,
      PlatformTransactionManager manager,
      ProjectAccess access) {
    return new LocalAccounts(
        env, jdbc, new TransactionTemplate(manager), access, java.time.Clock.systemUTC());
  }

  @Bean
  @Profile("prod-local")
  ProductionAccounts productionAccounts(
      Environment env,
      RuntimeSettings settings,
      JdbcTemplate jdbc,
      PlatformTransactionManager manager) {
    return new ProductionAccounts(env, jdbc, new TransactionTemplate(manager));
  }

  @Bean
  LocalObjectStore localObjectStore(RuntimeSettings settings) {
    return new LocalObjectStore(settings.root(), settings.maxBytes(), settings.maxPixels());
  }

  @Bean
  ProjectAssets projectAssets(
      JdbcTemplate jdbc,
      PlatformTransactionManager manager,
      ProjectAccess access,
      LocalObjectStore store,
      RuntimeSettings settings) {
    return new ProjectAssets(jdbc, new TransactionTemplate(manager), access, store, settings);
  }

  @Bean
  CutoutService cutoutService(
      JdbcTemplate jdbc,
      PlatformTransactionManager manager,
      LocalObjectStore store,
      Environment env) {
    return new CutoutService(jdbc, new TransactionTemplate(manager), store, env);
  }

  @Bean
  ScenePolicy scenePolicy(Environment env) {
    return new ScenePolicy(env);
  }

  @Bean
  SnapshotBuilder snapshotBuilder(JdbcTemplate jdbc, LocalObjectStore store, ScenePolicy scenes) {
    return new SnapshotBuilder(jdbc, store, scenes);
  }

  @Bean
  ProviderConfigService providerConfigService(
      JdbcTemplate jdbc, PlatformTransactionManager manager, Environment env) {
    return new ProviderConfigService(jdbc, new TransactionTemplate(manager), env);
  }

  @Bean
  TaskService taskService(
      JdbcTemplate jdbc,
      PlatformTransactionManager manager,
      SnapshotBuilder snapshots,
      LocalObjectStore store,
      RuntimeSettings settings,
      ProviderConfigService configs) {
    return new TaskService(
        jdbc, new TransactionTemplate(manager), snapshots, store, settings, configs);
  }

  @Bean
  DeliveryService deliveryService(
      JdbcTemplate jdbc,
      PlatformTransactionManager manager,
      LocalObjectStore store,
      RuntimeSettings settings,
      ProviderConfigService configs) {
    return new DeliveryService(jdbc, new TransactionTemplate(manager), store, settings, configs);
  }
}
