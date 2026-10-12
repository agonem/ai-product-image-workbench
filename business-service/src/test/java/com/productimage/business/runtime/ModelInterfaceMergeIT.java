package com.productimage.business.runtime;

import static org.junit.jupiter.api.Assertions.*;

import java.util.UUID;
import org.flywaydb.core.Flyway;
import org.junit.jupiter.api.Test;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DataSourceTransactionManager;
import org.springframework.jdbc.datasource.DriverManagerDataSource;
import org.springframework.transaction.support.TransactionTemplate;

/**
 * ADR-20261012-AB: V21 moves every existing model under its own interface; the business service
 * then merges those of the same type, address, proxy setting and (decrypted) key into one.
 */
class ModelInterfaceMergeIT {
  private static String required(String name) {
    String value = System.getenv(name);
    assertNotNull(value, name + " required: run python scripts/check_db.py");
    return value;
  }

  @Test
  void migratedModelsShareOneInterfacePerKey() {
    String url = required("DB_TEST_URL"), user = required("DB_TEST_USER");
    String password = required("DB_TEST_PASSWORD");
    String schema = "merge_" + UUID.randomUUID().toString().replace("-", "");
    var v20 =
        Flyway.configure().dataSource(url, user, password).schemas(schema).target("20").load();
    assertEquals(20, v20.migrate().migrationsExecuted);
    var source = new DriverManagerDataSource(url, user, password);
    source.setSchema(schema);
    var jdbc = new JdbcTemplate(source);
    var tx = new TransactionTemplate(new DataSourceTransactionManager(source));
    byte[] master = new byte[32];
    master[0] = 7;
    byte[] other = new byte[32];
    jdbc.update("INSERT INTO users(id,status) VALUES ('admin','ACTIVE')");
    String insert =
        "INSERT INTO provider_config_versions(id,name,provider,model,provider_tag,base_url,api_key_cipher,api_key_mask,created_by,enabled,purpose,parameters,created_at) VALUES (?,?,?,?,?,?,?,?,'admin',true,?,?::jsonb,now()+(?*interval '1 second'))";
    // One OpenRouter key entered three times (each encrypted separately), a second OpenRouter
    // key, a relay, and one model whose key no longer decrypts.
    String same = "sk-or-" + "a".repeat(40), second = "sk-or-" + "b".repeat(40);
    Object[][] rows = {
      {
        "img",
        "gpt-image-2",
        "openrouter",
        "openai/gpt-image-2",
        "openai",
        null,
        same,
        "IMAGE",
        "{\"quality\":\"high\"}"
      },
      {
        "seed",
        "豆包5.0 Pro",
        "openrouter",
        "bytedance-seed/seedream-5-0-pro",
        "seed",
        null,
        same,
        "IMAGE",
        "{\"resolution\":\"2K\"}"
      },
      {
        "text",
        "改写",
        "openrouter",
        "deepseek/deepseek-v4.1-flash",
        null,
        null,
        same,
        "TEXT",
        "{\"temperature\":\"0.5\"}"
      },
      {"two", "第二个号", "openrouter", "openai/gpt-image-2", "openai", null, second, "IMAGE", "{}"},
      {
        "relay",
        "openlux/gpt-image-2",
        "openai-compatible",
        "gpt-image-2-c",
        null,
        "https://relay.example.com/v1",
        same,
        "IMAGE",
        "{}"
      },
      {"lost", "旧密钥", "openrouter", "openai/gpt-image-1", "openai", null, null, "IMAGE", "{}"},
    };
    int order = 0;
    for (Object[] row : rows) {
      String key = (String) row[6];
      String cipher =
          key == null
              ? ProviderCrypto.encrypt(other, "x".repeat(20))
              : ProviderCrypto.encrypt(master, key);
      jdbc.update(
          insert,
          row[0],
          row[1],
          row[2],
          row[3],
          row[4],
          row[5],
          cipher,
          ProviderCrypto.mask(key == null ? "x".repeat(20) : key),
          row[7],
          row[8],
          order++);
    }
    var latest = Flyway.configure().dataSource(url, user, password).schemas(schema).load();
    assertEquals(1, latest.migrate().migrationsExecuted);
    // V21: one interface per model, waiting to be merged; key and address moved over.
    assertEquals(
        6,
        jdbc.queryForObject(
            "SELECT count(*) FROM model_interfaces WHERE merge_pending", Long.class));
    assertEquals(
        "OpenRouter（gpt-image-2）",
        jdbc.queryForObject("SELECT name FROM model_interfaces WHERE id='mi-img'", String.class));
    assertEquals(
        "https://relay.example.com/v1",
        jdbc.queryForObject(
            "SELECT base_url FROM model_interfaces WHERE id='mi-relay'", String.class));
    // Parameters: clarity is gone, the text model's old behaviour is written out, typed.
    assertEquals(
        "{\"quality\": \"high\"}",
        jdbc.queryForObject(
            "SELECT parameters::text FROM provider_config_versions WHERE id='img'", String.class));
    assertEquals(
        "{}",
        jdbc.queryForObject(
            "SELECT parameters::text FROM provider_config_versions WHERE id='seed'", String.class));
    assertEquals(
        "{\"max_tokens\": 6000, \"temperature\": 0.5, \"reasoning.effort\": \"low\"}",
        jdbc.queryForObject(
            "SELECT parameters::text FROM provider_config_versions WHERE id='text'", String.class));
    assertTrue(
        jdbc.queryForObject(
            "SELECT vision FROM provider_config_versions WHERE id='text'", Boolean.class));
    assertFalse(
        jdbc.queryForObject(
            "SELECT vision FROM provider_config_versions WHERE id='img'", Boolean.class));

    // Without the master key nothing is merged.
    ProviderConfigService.mergeMigratedInterfaces(jdbc, tx, null);
    assertEquals(6, jdbc.queryForObject("SELECT count(*) FROM model_interfaces", Long.class));
    ProviderConfigService.mergeMigratedInterfaces(jdbc, tx, master);
    // The three models of the same key share the first interface; the second key, the relay and
    // the undecryptable one keep their own.
    assertEquals(
        1,
        jdbc.queryForObject(
            "SELECT count(DISTINCT interface_id) FROM provider_config_versions WHERE id IN ('img','seed','text')",
            Long.class));
    assertEquals(
        "mi-img",
        jdbc.queryForObject(
            "SELECT interface_id FROM provider_config_versions WHERE id='text'", String.class));
    assertEquals(4, jdbc.queryForObject("SELECT count(*) FROM model_interfaces", Long.class));
    // Three OpenRouter interfaces remain, so they keep the model in their names; the only
    // third-party one is named after its type.
    assertEquals(
        "OpenRouter（gpt-image-2）",
        jdbc.queryForObject("SELECT name FROM model_interfaces WHERE id='mi-img'", String.class));
    assertEquals(
        "OpenAI 协议第三方",
        jdbc.queryForObject("SELECT name FROM model_interfaces WHERE id='mi-relay'", String.class));
    assertEquals(
        0,
        jdbc.queryForObject(
            "SELECT count(*) FROM model_interfaces WHERE merge_pending", Long.class));
    // Runs once.
    jdbc.update("UPDATE model_interfaces SET name='改过的名字' WHERE id='mi-relay'");
    ProviderConfigService.mergeMigratedInterfaces(jdbc, tx, master);
    assertEquals(
        "改过的名字",
        jdbc.queryForObject("SELECT name FROM model_interfaces WHERE id='mi-relay'", String.class));
    // The merged interface still opens every model's key.
    var service = new ProviderConfigService(jdbc, tx, master);
    assertEquals(same, service.claimConfig("seed").path("api_key").asText());
    assertEquals("openrouter", service.claimConfig("seed").path("provider").asText());
    assertEquals(second, service.claimConfig("two").path("api_key").asText());
    assertEquals(
        "https://relay.example.com/v1", service.claimConfig("relay").path("base_url").asText());
  }
}
