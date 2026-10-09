package com.productimage.workbench.database;

import static org.junit.jupiter.api.Assertions.*;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.sql.Connection;
import java.sql.DriverManager;
import java.sql.SQLException;
import java.util.List;
import java.util.UUID;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.Executors;
import org.flywaydb.core.Flyway;
import org.flywaydb.core.api.FlywayException;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

class DatabaseMigrationIT {
  private String url;
  private String user;
  private String password;
  private String schema;
  private Flyway flyway;

  @BeforeEach
  void migrateEmptySchema() throws SQLException {
    url = required("DB_TEST_URL");
    user = required("DB_TEST_USER");
    password = required("DB_TEST_PASSWORD");
    schema = "test_" + UUID.randomUUID().toString().replace("-", "");
    flyway = Flyway.configure().dataSource(url, user, password).schemas(schema).load();
    assertEquals(17, flyway.migrate().migrationsExecuted);
    sql("INSERT INTO users(id,status) VALUES ('u','ACTIVE'),('v','ACTIVE')");
    sql("INSERT INTO projects(id,owner_id,name) VALUES ('p','u','fixture'),('q','v','fixture')");
    sql(
        "INSERT INTO assets(id,project_id,kind,object_key,sha256,width,height) VALUES "
            + "('product','p','PRODUCT','fixtures/product','"
            + "a".repeat(64)
            + "',64,64),"
            + "('foreign','q','PRODUCT','fixtures/foreign','"
            + "b".repeat(64)
            + "',64,64)");
  }

  private static String required(String name) {
    String value = System.getenv(name);
    assertNotNull(value, name + " required: run python scripts/check_db.py");
    assertFalse(value.isBlank());
    return value;
  }

  private Connection connection() throws SQLException {
    var connection = DriverManager.getConnection(url, user, password);
    connection.setSchema(schema);
    return connection;
  }

  private void sql(String statement) throws SQLException {
    try (var connection = connection();
        var query = connection.createStatement()) {
      query.execute(statement);
    }
  }

  private long count(String table) throws SQLException {
    try (var connection = connection();
        var query = connection.createStatement();
        var result = query.executeQuery("SELECT count(*) FROM " + table)) {
      assertTrue(result.next());
      return result.getLong(1);
    }
  }

  private static String task(String id, String actor, String feature, String key, String hash) {
    return "INSERT INTO generation_tasks(id,project_id,product_asset_id,feature_type,created_by,idempotency_key,request_sha256,request_snapshot_json) VALUES ('"
        + id
        + "','p','product','"
        + feature
        + "','"
        + actor
        + "','"
        + key
        + "','"
        + hash
        + "','{}')";
  }

  private void seedTaskAndAttempt() throws SQLException {
    sql(task("t", "u", "SCENE", "key", "a".repeat(64)));
    sql("INSERT INTO task_attempts(id,task_id,attempt_no) VALUES ('attempt','t',1)");
    sql("UPDATE generation_tasks SET current_attempt_id='attempt' WHERE id='t'");
  }

  private void rejects(String state, String statement) {
    var error = assertThrows(SQLException.class, () -> sql(statement));
    assertEquals(state, error.getSQLState(), error::getMessage);
  }

  @Test
  void migrationIsRepeatableAndComplete() throws SQLException {
    assertEquals(0, flyway.migrate().migrationsExecuted);
    assertTrue(flyway.validateWithResult().validationSuccessful);
    for (String table :
        List.of(
            "users",
            "projects",
            "assets",
            "templates",
            "template_versions",
            "generation_tasks",
            "task_attempts",
            "artifacts",
            "outbox_events",
            "worker_receipts",
            "audit_events",
            "local_credentials",
            "local_sessions",
            "local_auth_throttle",
            "provider_config_versions",
            "provider_config_state")) {
      assertEquals(List.of("users", "projects", "assets").contains(table) ? 2 : 0, count(table));
    }
  }

  @Test
  void upgradesV1WithoutLosingExistingRows() throws SQLException {
    String upgradeSchema = "upgrade_" + UUID.randomUUID().toString().replace("-", "");
    var baseline =
        Flyway.configure()
            .dataSource(url, user, password)
            .schemas(upgradeSchema)
            .target("1")
            .load();
    assertEquals(1, baseline.migrate().migrationsExecuted);
    try (var connection = DriverManager.getConnection(url, user, password);
        var query = connection.createStatement()) {
      connection.setSchema(upgradeSchema);
      query.execute("INSERT INTO users(id,status) VALUES ('existing','ACTIVE')");
      var upgrade =
          Flyway.configure().dataSource(url, user, password).schemas(upgradeSchema).load();
      assertEquals(16, upgrade.migrate().migrationsExecuted);
      assertEquals(0, upgrade.migrate().migrationsExecuted);
      try (var rows = query.executeQuery("SELECT status FROM users WHERE id='existing'")) {
        assertTrue(rows.next());
        assertEquals("ACTIVE", rows.getString(1));
      }
      assertTrue(upgrade.validateWithResult().validationSuccessful);
    }
  }

  @Test
  void productionCredentialConstraintsAndV2Upgrade() throws SQLException {
    sql(
        "INSERT INTO local_credentials(user_id,username,salt,password_hash,role) VALUES ('u','alice','"
            + "a".repeat(32)
            + "','"
            + "b".repeat(64)
            + "','ADMIN')");
    rejects(
        "23505",
        "INSERT INTO local_credentials(user_id,username,salt,password_hash,role) VALUES ('v','alice','"
            + "a".repeat(32)
            + "','"
            + "b".repeat(64)
            + "','USER')");
    rejects("23514", "UPDATE local_credentials SET role='ROOT' WHERE user_id='u'");
    rejects("23514", "UPDATE local_credentials SET password_hash='cleartext' WHERE user_id='u'");
    rejects(
        "23503",
        "INSERT INTO local_sessions(token_hash,user_id,expires_at) VALUES ('"
            + "c".repeat(64)
            + "','v',now())");
    String upgradeSchema = "v2_" + UUID.randomUUID().toString().replace("-", "");
    var old =
        Flyway.configure()
            .dataSource(url, user, password)
            .schemas(upgradeSchema)
            .target("2")
            .load();
    assertEquals(2, old.migrate().migrationsExecuted);
    try (var connection = DriverManager.getConnection(url, user, password);
        var query = connection.createStatement()) {
      connection.setSchema(upgradeSchema);
      query.execute("INSERT INTO users(id,status) VALUES ('legacy','DISABLED')");
      var current =
          Flyway.configure().dataSource(url, user, password).schemas(upgradeSchema).load();
      assertEquals(15, current.migrate().migrationsExecuted);
      assertEquals(0, current.migrate().migrationsExecuted);
      try (var rows =
          query.executeQuery(
              "SELECT status,(SELECT count(*) FROM local_credentials) FROM users WHERE id='legacy'")) {
        assertTrue(rows.next());
        assertEquals("DISABLED", rows.getString(1));
        assertEquals(0, rows.getLong(2));
      }
    }
  }

  @Test
  void alteredMigrationChecksumFails(@TempDir Path directory) throws IOException {
    try (var input =
        getClass().getResourceAsStream("/db/migration/V1__task_contract_baseline.sql")) {
      assertNotNull(input);
      Files.writeString(
          directory.resolve("V1__task_contract_baseline.sql"),
          new String(input.readAllBytes(), java.nio.charset.StandardCharsets.UTF_8)
              + "\n-- changed checksum\n");
    }
    var changed =
        Flyway.configure()
            .dataSource(url, user, password)
            .schemas(schema)
            .locations("filesystem:" + directory)
            .load();
    assertFalse(changed.validateWithResult().validationSuccessful);
    assertThrows(FlywayException.class, changed::migrate);
  }

  @Test
  void idempotencyScopeAndConflicts() throws SQLException {
    sql(task("t", "u", "SCENE", "key", "a".repeat(64)));
    rejects("23505", task("duplicate", "u", "SCENE", "key", "a".repeat(64)));
    rejects("23505", task("conflict", "u", "SCENE", "key", "b".repeat(64)));
    sql(task("other_user", "v", "SCENE", "key", "a".repeat(64)));
    sql(task("other_feature", "u", "SELLING_POINT", "key", "a".repeat(64)));
    assertEquals(3, count("generation_tasks"));
  }

  @Test
  void concurrentSameKeyCreatesExactlyOneTask() throws Exception {
    var gate = new CountDownLatch(1);
    try (var executor = Executors.newFixedThreadPool(2)) {
      var futures =
          List.of("one", "two").stream()
              .map(
                  id ->
                      executor.submit(
                          () -> {
                            gate.await();
                            try {
                              sql(task(id, "u", "SCENE", "concurrent", "a".repeat(64)));
                              return "inserted";
                            } catch (SQLException ex) {
                              return ex.getSQLState();
                            }
                          }))
              .toList();
      gate.countDown();
      var outcomes = List.of(futures.get(0).get(), futures.get(1).get());
      assertEquals(1, outcomes.stream().filter("inserted"::equals).count());
      assertEquals(1, outcomes.stream().filter("23505"::equals).count());
      assertEquals(1, count("generation_tasks"));
    }
  }

  @Test
  void immutableSourcesSnapshotsAndPublishedVersions() throws SQLException {
    seedTaskAndAttempt();
    rejects("23514", "UPDATE assets SET object_key='replacement' WHERE id='product'");
    rejects(
        "23514",
        "UPDATE generation_tasks SET request_snapshot_json='{\"changed\":true}' WHERE id='t'");
    sql("INSERT INTO templates(id,type,name) VALUES ('template','scene','fixture')");
    sql(
        "INSERT INTO template_versions(id,template_id,version,config_json,created_by) VALUES ('version','template',1,'{}','u')");
    sql("UPDATE template_versions SET config_json='{\"draft\":true}' WHERE id='version'");
    sql("UPDATE template_versions SET published_by='u',published_at=now() WHERE id='version'");
    rejects("23514", "UPDATE template_versions SET config_json='{}' WHERE id='version'");
    rejects("23514", "DELETE FROM template_versions WHERE id='version'");
    rejects(
        "23514",
        "UPDATE template_versions SET published_at=null,published_by=null WHERE id='version'");
  }

  @Test
  void foreignKeysChecksAndAttemptNumberAreEnforced() throws SQLException {
    seedTaskAndAttempt();
    rejects(
        "23503",
        task("bad", "u", "SCENE", "other", "a".repeat(64)).replace("'product'", "'foreign'"));
    rejects("23514", task("bad", "u", "UNKNOWN", "other", "a".repeat(64)));
    rejects("23514", task("bad", "u", "SCENE", "bad key", "a".repeat(64)));
    rejects("23514", task("bad", "u", "SCENE", "other", "short"));
    rejects("23505", "INSERT INTO task_attempts(id,task_id,attempt_no) VALUES ('duplicate','t',1)");
    rejects("23514", "INSERT INTO task_attempts(id,task_id,attempt_no) VALUES ('zero','t',0)");
    sql(task("t2", "u", "SCENE", "other", "a".repeat(64)));
    rejects("23503", "UPDATE generation_tasks SET current_attempt_id='attempt' WHERE id='t2'");
  }

  @Test
  void artifactSlotsAreImmutableAndAttemptBound() throws SQLException {
    seedTaskAndAttempt();
    String insert =
        "INSERT INTO artifacts(id,task_id,attempt_id,ordinal,kind,object_key,sha256,width,height) VALUES ('artifact','t','attempt',0,'COMPOSITE','fixtures/result','"
            + "b".repeat(64)
            + "',64,64)";
    sql(insert);
    rejects(
        "23505",
        insert.replace("'artifact'", "'duplicate'").replace("fixtures/result", "fixtures/other"));
    rejects("23514", "UPDATE artifacts SET width=1 WHERE id='artifact'");
    rejects("23514", "DELETE FROM artifacts WHERE id='artifact'");
    rejects(
        "23514",
        insert
            .replace("'artifact'", "'zero'")
            .replace(",64,64)", ",0,64)")
            .replace(",0,'COMPOSITE'", ",1,'COMPOSITE'"));
    sql(task("t2", "u", "SCENE", "other", "a".repeat(64)));
    rejects(
        "23503",
        insert
            .replace("'artifact'", "'foreign'")
            .replace("'t'", "'t2'")
            .replace(",0,'COMPOSITE'", ",2,'COMPOSITE'")
            .replace("fixtures/result", "fixtures/foreign-result"));
  }

  @Test
  void outboxAndReceiptIdentityIsUniqueAndBound() throws SQLException {
    seedTaskAndAttempt();
    String outbox =
        "INSERT INTO outbox_events(id,task_id,attempt_id,event_type,payload) VALUES ('event','t','attempt','image.task.requested.v1','{\"event_id\":\"event\",\"task_id\":\"t\",\"attempt_id\":\"attempt\",\"event_type\":\"image.task.requested.v1\",\"schema_version\":1}')";
    sql(outbox);
    rejects("23505", outbox.replace("event'", "another'").replace(":\"event\"", ":\"another\""));
    rejects("23514", "UPDATE outbox_events SET payload='{}' WHERE id='event'");
    String receipt =
        "INSERT INTO worker_receipts(event_id,task_id,attempt_id,event_type,payload_sha256,payload) VALUES ('receipt','t','attempt','image.task.completed.v1','"
            + "b".repeat(64)
            + "','{\"event_id\":\"receipt\",\"task_id\":\"t\",\"attempt_id\":\"attempt\",\"event_type\":\"image.task.completed.v1\",\"schema_version\":1}')";
    sql(receipt);
    rejects("23505", receipt);
    rejects(
        "23505",
        receipt
            .replace("receipt", "second_receipt")
            .replace("worker_second_receipts", "worker_receipts"));
    rejects(
        "23514",
        "UPDATE worker_receipts SET payload_sha256='"
            + "c".repeat(64)
            + "' WHERE event_id='receipt'");
    // V7: v4 envelopes are accepted, but their schema_version must still match the type.
    sql("INSERT INTO task_attempts(id,task_id,attempt_no) VALUES ('attempt4','t',2)");
    String v4 =
        "INSERT INTO outbox_events(id,task_id,attempt_id,event_type,payload) VALUES ('event4','t','attempt4','image.task.requested.v4','{\"event_id\":\"event4\",\"task_id\":\"t\",\"attempt_id\":\"attempt4\",\"event_type\":\"image.task.requested.v4\",\"schema_version\":4}')";
    sql(v4);
    rejects(
        "23514",
        v4.replace("event4", "event5").replace("\"schema_version\":4", "\"schema_version\":3"));
    rejects("23514", v4.replace("event4", "event6").replace("requested.v4", "requested.v5"));
  }

  @Test
  void anyMaterialCategoryFillsAnySlotButNeverAMask() throws SQLException {
    sql(
        "INSERT INTO assets(id,project_id,kind,object_key,sha256,width,height) VALUES ('gift','p','GIFT','fixtures/gift','"
            + "c".repeat(64)
            + "',64,64)");
    sql(
        "INSERT INTO assets(id,project_id,kind,source_asset_id,object_key,sha256,width,height) VALUES ('alpha','p','ALPHA','product','fixtures/alpha','"
            + "d".repeat(64)
            + "',64,64)");
    sql(
        "INSERT INTO assets(id,project_id,kind,object_key,sha256,width,height) VALUES ('ref','p','REFERENCE','fixtures/ref','"
            + "f".repeat(64)
            + "',64,64)");
    rejects(
        "23514",
        "INSERT INTO assets(id,project_id,kind,object_key,sha256,width,height) VALUES ('odd','p','OTHER','fixtures/odd','"
            + "9".repeat(64)
            + "',64,64)");
    // ADR-20261009-R: a 赠品图 or 参考图 may be the product and the product image the gift.
    sql(task("g", "u", "SCENE", "k1", "a".repeat(64)).replace("'product'", "'gift'"));
    sql(task("r", "u", "SCENE", "k2", "a".repeat(64)).replace("'product'", "'ref'"));
    rejects(
        "23514", task("bad", "u", "SCENE", "k3", "a".repeat(64)).replace("'product'", "'alpha'"));
    String giftTask =
        task("t", "u", "GIFT", "key", "a".repeat(64))
            .replace("request_snapshot_json)", "request_snapshot_json,gift_asset_id)")
            .replace("'{}')", "'{}','gift')");
    sql(
        giftTask
            .replace("'t'", "'swapped'")
            .replace("'key'", "'k4'")
            .replace("'gift')", "'product')"));
    rejects(
        "23514",
        giftTask
            .replace("'t'", "'masked'")
            .replace("'key'", "'k5'")
            .replace("'gift')", "'alpha')"));
    sql(giftTask);
    rejects(
        "23514",
        "INSERT INTO assets(id,project_id,kind,source_asset_id,object_key,sha256,width,height) VALUES ('nested','p','ALPHA','alpha','fixtures/nested','"
            + "e".repeat(64)
            + "',64,64)");
  }

  @Test
  void providerConfigsAreEditedInPlaceAndDeletionUnbindsTasks() throws SQLException {
    sql(
        "INSERT INTO provider_config_versions(id,name,provider,model,provider_tag,api_key_cipher,api_key_mask,created_by) VALUES ('cfg','主力','openrouter','test/model','openai','cipher','****st','u')");
    // ADR-20261009-Q: model, key and parameters change in place; identity and purpose do not.
    sql(
        "UPDATE provider_config_versions SET model='other/model',api_key_cipher='c2',parameters='{\"quality\":\"high\"}' WHERE id='cfg'");
    rejects("23514", "UPDATE provider_config_versions SET purpose='TEXT' WHERE id='cfg'");
    rejects("23514", "UPDATE provider_config_versions SET created_by='x' WHERE id='cfg'");
    rejects("23514", "UPDATE provider_config_versions SET parameters='[]' WHERE id='cfg'");
    rejects(
        "23503",
        "INSERT INTO provider_config_state(provider,active_version_id) VALUES ('active','missing')");
    sql("INSERT INTO provider_config_state(provider,active_version_id) VALUES ('active','cfg')");
    // One default pointer for the deployment: no second state row.
    rejects(
        "23514",
        "INSERT INTO provider_config_state(provider,active_version_id) VALUES ('openrouter','cfg')");
    // Name, enabled and proxy routing are editable; a retired row can never be enabled.
    sql("UPDATE provider_config_versions SET name='备用',enabled=true,use_proxy=true WHERE id='cfg'");
    rejects("23514", "UPDATE provider_config_versions SET retired=true WHERE id='cfg'");
    rejects("23514", "UPDATE provider_config_versions SET name=' ' WHERE id='cfg'");
    seedTaskAndAttempt();
    rejects(
        "23503",
        task("bound", "u", "SCENE", "cfgkey", "a".repeat(64))
            .replace("request_snapshot_json)", "request_snapshot_json,provider_config_version)")
            .replace("'{}')", "'{}','missing')"));
    sql(
        task("bound", "u", "SCENE", "cfgkey", "a".repeat(64))
            .replace("request_snapshot_json)", "request_snapshot_json,provider_config_version)")
            .replace("'{}')", "'{}','cfg')"));
    // A task can move to another model, and deleting a model unbinds the tasks still on it.
    sql(
        "INSERT INTO provider_config_versions(id,name,provider,model,provider_tag,api_key_cipher,api_key_mask,created_by) VALUES ('spare','备用','openrouter','test/spare','openai','cipher','****st','u')");
    sql("UPDATE generation_tasks SET provider_config_version='spare' WHERE id='bound'");
    sql("DELETE FROM provider_config_versions WHERE id='spare'");
    try (var connection = connection();
        var query = connection.createStatement();
        var rows =
            query.executeQuery(
                "SELECT provider_config_version FROM generation_tasks WHERE id='bound'")) {
      assertTrue(rows.next());
      assertNull(rows.getString(1));
    }
  }

  @Test
  void providerFormatsCarryOnlyTheirOwnFields() throws SQLException {
    String insert =
        "INSERT INTO provider_config_versions(id,name,provider,model,provider_tag,base_url,api_key_cipher,api_key_mask,created_by) VALUES ";
    sql(insert + "('o','n','openai','gpt-image-2',NULL,NULL,'c','****','u')");
    sql(insert + "('g','n','gemini','gemini-2.5-flash-image',NULL,NULL,'c','****','u')");
    sql(
        insert
            + "('oc','n','openai-compatible','gpt-image-2',NULL,'http://10.2.2.110:3000/v1','c','****','u')");
    sql(
        insert
            + "('gc','n','gemini-compatible','gemini-2.5-flash-image',NULL,'https://relay.example.com','c','****','u')");
    rejects("23514", insert + "('x1','n','other','m',NULL,NULL,'c','****','u')");
    rejects("23514", insert + "('x2','n','openai','gpt-image-2','tag',NULL,'c','****','u')");
    rejects("23514", insert + "('x3','n','openrouter','test/model',NULL,NULL,'c','****','u')");
    rejects("23514", insert + "('x4','n','openrouter','no-slash','tag',NULL,'c','****','u')");
    rejects("23514", insert + "('x5','n','openai-compatible','m',NULL,NULL,'c','****','u')");
    rejects("23514", insert + "('x6','n','openai','m',NULL,'https://a.example','c','****','u')");
    rejects(
        "23514",
        insert + "('x7','n','gemini-compatible','m',NULL,'ftp://a.example','c','****','u')");
    // Editable since ADR-20261009-Q, still within the format's rules.
    sql("UPDATE provider_config_versions SET base_url='https://b.example' WHERE id='oc'");
    rejects(
        "23514", "UPDATE provider_config_versions SET base_url='ftp://b.example' WHERE id='oc'");
  }

  @Test
  void upgradesKeepTheActiveOpenRouterConfiguration() throws SQLException {
    String upgradeSchema = "upgrade_" + UUID.randomUUID().toString().replace("-", "");
    var v7 =
        Flyway.configure()
            .dataSource(url, user, password)
            .schemas(upgradeSchema)
            .target("7")
            .load();
    assertEquals(7, v7.migrate().migrationsExecuted);
    try (var connection = DriverManager.getConnection(url, user, password);
        var query = connection.createStatement()) {
      connection.setSchema(upgradeSchema);
      query.execute("INSERT INTO users(id,status) VALUES ('admin','ACTIVE')");
      query.execute(
          "INSERT INTO provider_config_versions(id,provider,model,provider_tag,api_key_cipher,api_key_mask,created_by) VALUES ('cfg','openrouter','openai/gpt-image-2','openai','c','****','admin')");
      query.execute(
          "INSERT INTO provider_config_state(provider,active_version_id,enabled) VALUES ('openrouter','cfg',true)");
      var upgrade =
          Flyway.configure().dataSource(url, user, password).schemas(upgradeSchema).load();
      assertEquals(10, upgrade.migrate().migrationsExecuted);
      try (var rows =
          query.executeQuery("SELECT provider,active_version_id FROM provider_config_state")) {
        assertTrue(rows.next());
        assertEquals("active", rows.getString(1));
        assertEquals("cfg", rows.getString(2));
        assertFalse(rows.next());
      }
      // V10: the previously active, enabled row becomes a named, enabled default model.
      try (var rows =
          query.executeQuery(
              "SELECT provider,provider_tag,base_url,name,enabled,retired,use_proxy FROM provider_config_versions")) {
        assertTrue(rows.next());
        assertEquals("openrouter", rows.getString(1));
        assertEquals("openai", rows.getString(2));
        assertEquals(null, rows.getString(3));
        assertEquals("openai/gpt-image-2", rows.getString(4));
        assertTrue(rows.getBoolean(5));
        assertFalse(rows.getBoolean(6));
        assertFalse(rows.getBoolean(7));
      }
    }
  }

  @Test
  void deletionsAreFinalAndAttributed() throws SQLException {
    sql("INSERT INTO deletions(target_id,target_kind,deleted_by) VALUES ('product','ASSET','u')");
    rejects(
        "23505",
        "INSERT INTO deletions(target_id,target_kind,deleted_by) VALUES ('product','ASSET','u')");
    rejects(
        "23514", "INSERT INTO deletions(target_id,target_kind,deleted_by) VALUES ('x','TASK','u')");
    rejects(
        "23503",
        "INSERT INTO deletions(target_id,target_kind,deleted_by) VALUES ('y','ARTIFACT','nobody')");
    rejects("23514", "UPDATE deletions SET deleted_by='v' WHERE target_id='product'");
    rejects("23514", "DELETE FROM deletions WHERE target_id='product'");
    // The original row itself stays for history.
    assertEquals(2, count("assets"));
  }

  @Test
  void deletedAccountsKeepTheirFormerNameAndCopiedAssetsTheirSource() throws SQLException {
    // V11: DELETED always carries the former login name, and only DELETED does.
    rejects("23514", "UPDATE users SET status='DELETED' WHERE id='v'");
    sql("UPDATE users SET status='DELETED',deleted_username='bob' WHERE id='v'");
    rejects("23514", "UPDATE users SET status='ACTIVE' WHERE id='v'");
    rejects("23514", "UPDATE users SET status='GONE' WHERE id='u'");
    // A copied asset's source result is part of its immutable identity.
    rejects("23514", "UPDATE assets SET source_artifact_id='missing' WHERE id='product'");
    rejects(
        "23503",
        "INSERT INTO assets(id,project_id,kind,object_key,sha256,width,height,source_artifact_id) VALUES ('copy','p','PRODUCT','fixtures/copy','"
            + "c".repeat(64)
            + "',64,64,'missing')");
  }

  @Test
  void presetVersionsAreAppendOnlyAndTemplateNamesPerOwner() throws SQLException {
    // V12: a published catalogue version can never change or disappear.
    sql("INSERT INTO preset_catalog_versions(version,config,published_by) VALUES (1,'{}','u')");
    rejects("23514", "UPDATE preset_catalog_versions SET note='x' WHERE version=1");
    rejects("23514", "DELETE FROM preset_catalog_versions WHERE version=1");
    rejects(
        "23503",
        "INSERT INTO preset_catalog_versions(version,config,published_by,restored_from) VALUES (2,'{}','u',9)");
    // One template name per owner and entry; other owners or entries may reuse it.
    sql(
        "INSERT INTO user_templates(id,owner_id,feature_type,name,settings) VALUES ('t1','u','GIFT','常用','{}')");
    rejects(
        "23505",
        "INSERT INTO user_templates(id,owner_id,feature_type,name,settings) VALUES ('t2','u','GIFT','常用','{}')");
    sql(
        "INSERT INTO user_templates(id,owner_id,feature_type,name,settings) VALUES ('t3','v','GIFT','常用','{}'),('t4','u','SCENE','常用','{}')");
    rejects(
        "23514",
        "INSERT INTO user_templates(id,owner_id,feature_type,name,settings) VALUES ('t5','u','GIFT',' ','{}')");
  }

  @Test
  void conversationsGroupCustomTasksAndLetThemOutliveTheConversation() throws SQLException {
    // V13: CUSTOM tasks may belong to a conversation; other entries never do.
    sql("INSERT INTO conversations(id,project_id,title) VALUES ('c1','p','木桌绿植')");
    rejects("23514", "INSERT INTO conversations(id,project_id,title) VALUES ('c2','p',' ')");
    sql(task("custom", "u", "CUSTOM", "custom-key", "c".repeat(64)));
    sql("UPDATE generation_tasks SET conversation_id='c1' WHERE id='custom'");
    sql(task("scene", "u", "SCENE", "scene-key", "d".repeat(64)));
    rejects("23514", "UPDATE generation_tasks SET conversation_id='c1' WHERE id='scene'");
    rejects("23514", task("other", "u", "OTHER", "other-key", "e".repeat(64)));
    // Deleting the conversation keeps the task (and its images).
    sql("DELETE FROM conversations WHERE id='c1'");
    assertEquals(2, count("generation_tasks"));
  }

  @Test
  void agentsArePublicOrPersonalAndModelsHaveAPurpose() throws SQLException {
    // V14: three public agents ship with the release; personal ones carry an owner.
    assertEquals(3, count("agents"));
    sql("INSERT INTO agents(id,owner_id,name,instructions) VALUES ('mine','u','我的设计师','温暖自然')");
    rejects("23514", "INSERT INTO agents(id,name,instructions) VALUES ('blank',' ','x')");
    rejects("23514", "INSERT INTO agents(id,name,instructions) VALUES ('empty','名字',' ')");
    rejects(
        "23503", "INSERT INTO agents(id,owner_id,name,instructions) VALUES ('x','nobody','n','i')");
    // Picture and text models each have their own default row.
    rejects("23514", "INSERT INTO provider_config_state(provider) VALUES ('other')");
    sql("INSERT INTO provider_config_state(provider) VALUES ('text')");
  }

  @Test
  void proxySettingIsASingleEncryptedRow() throws SQLException {
    sql(
        "INSERT INTO network_settings(id,proxy_cipher,proxy_mask,updated_by) VALUES ('proxy','c','http://proxy:3128','u')");
    rejects(
        "23514",
        "INSERT INTO network_settings(id,proxy_cipher,proxy_mask,updated_by) VALUES ('other','c','m','u')");
    rejects("23503", "UPDATE network_settings SET updated_by='nobody' WHERE id='proxy'");
  }

  @Test
  void publishedPointerRequiresPublishedVersion() throws SQLException {
    sql("INSERT INTO templates(id,type,name) VALUES ('template','scene','fixture')");
    rejects("23514", "UPDATE templates SET state='PUBLISHED' WHERE id='template'");
    sql(
        "INSERT INTO template_versions(id,template_id,version,config_json,created_by) VALUES ('version','template',1,'{}','u')");
    rejects(
        "23514",
        "UPDATE templates SET published_version_id='version',state='PUBLISHED' WHERE id='template'");
    sql("UPDATE template_versions SET published_by='u',published_at=now() WHERE id='version'");
    sql(
        "UPDATE templates SET published_version_id='version',state='PUBLISHED' WHERE id='template'");
    sql("UPDATE templates SET state='DISABLED' WHERE id='template'");
  }
}
