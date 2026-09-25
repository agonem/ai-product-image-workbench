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
  LocalObjectStore localObjectStore(RuntimeSettings settings) {
    return new LocalObjectStore(settings.root(), settings.maxBytes(), settings.maxPixels());
  }

  @Bean
  SnapshotBuilder snapshotBuilder(JdbcTemplate jdbc, LocalObjectStore store) {
    return new SnapshotBuilder(jdbc, store);
  }

  @Bean
  TaskService taskService(
      JdbcTemplate jdbc,
      PlatformTransactionManager manager,
      SnapshotBuilder snapshots,
      LocalObjectStore store,
      RuntimeSettings settings) {
    return new TaskService(jdbc, new TransactionTemplate(manager), snapshots, store, settings);
  }

  @Bean
  DeliveryService deliveryService(
      JdbcTemplate jdbc,
      PlatformTransactionManager manager,
      LocalObjectStore store,
      RuntimeSettings settings) {
    return new DeliveryService(jdbc, new TransactionTemplate(manager), store, settings);
  }
}
