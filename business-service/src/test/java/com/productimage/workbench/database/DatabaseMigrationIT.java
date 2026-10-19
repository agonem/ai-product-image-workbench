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
    assertEquals(22, flyway.migrate().migrationsExecuted);
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
            "generation_tasks",
            "task_attempts",
            "artifacts",
            "outbox_events",
            "worker_receipts",
            "audit_events",
            "local_credentials",
            "local_sessions",
            "local_auth_throttle",
            "models",
            "model_interfaces",
            "default_models")) {
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
      assertEquals(21, upgrade.migrate().migrationsExecuted);
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
      assertEquals(20, current.migrate().migrationsExecuted);
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
  void immutableSourcesAndSnapshots() throws SQLException {
    seedTaskAndAttempt();
    rejects("23514", "UPDATE assets SET object_key='replacement' WHERE id='product'");
    rejects(
        "23514",
        "UPDATE generation_tasks SET request_snapshot_json='{\"changed\":true}' WHERE id='t'");
    // V22: the v1 template tables are gone.
    rejects("42P01", "SELECT 1 FROM templates");
    rejects("42P01", "SELECT 1 FROM output_presets");
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
  void anyMaterialCategoryFillsAnySlot() throws SQLException {
    sql(
        "INSERT INTO assets(id,project_id,kind,object_key,sha256,width,height) VALUES ('gift','p','GIFT','fixtures/gift','"
            + "c".repeat(64)
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
    String giftTask =
        task("t", "u", "GIFT", "key", "a".repeat(64))
            .replace("request_snapshot_json)", "request_snapshot_json,gift_asset_id)")
            .replace("'{}')", "'{}','gift')");
    sql(
        giftTask
            .replace("'t'", "'swapped'")
            .replace("'key'", "'k4'")
            .replace("'gift')", "'product')"));
    sql(giftTask);
    // V22: cutout masks are gone.
    rejects(
        "23514",
        "INSERT INTO assets(id,project_id,kind,object_key,sha256,width,height) VALUES ('mask','p','ALPHA','fixtures/mask','"
            + "e".repeat(64)
            + "',64,64)");
  }

  private static final String INTERFACE =
      "INSERT INTO model_interfaces(id,name,kind,base_url,api_key_cipher,api_key_mask,created_by) VALUES ";

  @Test
  void providerConfigsAreEditedInPlaceAndDeletionUnbindsTasks() throws SQLException {
    sql(INTERFACE + "('i','OpenRouter','openrouter',NULL,'cipher','****st','u')");
    sql(
        "INSERT INTO models(id,interface_id,name,model,provider_tag,created_by) VALUES ('cfg','i','主力','test/model','openai','u')");
    // ADR-20261009-Q: model and parameters change in place; identity and purpose do not.
    sql("UPDATE models SET model='other/model',parameters='{\"quality\":\"high\"}' WHERE id='cfg'");
    rejects("23514", "UPDATE models SET purpose='TEXT' WHERE id='cfg'");
    rejects("23514", "UPDATE models SET created_by='x' WHERE id='cfg'");
    rejects("23514", "UPDATE models SET parameters='[]' WHERE id='cfg'");
    rejects("23503", "INSERT INTO default_models(purpose,model_id) VALUES ('IMAGE','missing')");
    sql("INSERT INTO default_models(purpose,model_id) VALUES ('IMAGE','cfg')");
    // One default pointer for the deployment: no second state row.
    rejects("23514", "INSERT INTO default_models(purpose,model_id) VALUES ('openrouter','cfg')");
    // Name and enabled are editable (the proxy setting is the interface's); there is no retired
    // never be enabled; only text models say whether they can look at images (V21).
    sql("UPDATE models SET name='备用',enabled=true WHERE id='cfg'");
    sql("UPDATE model_interfaces SET use_proxy=true,api_key_cipher='c2' WHERE id='i'");
    rejects("23514", "UPDATE models SET vision=true WHERE id='cfg'");
    rejects("42703", "UPDATE models SET retired=true WHERE id='cfg'");
    rejects("23514", "UPDATE models SET name=' ' WHERE id='cfg'");
    seedTaskAndAttempt();
    rejects(
        "23503",
        task("bound", "u", "SCENE", "cfgkey", "a".repeat(64))
            .replace("request_snapshot_json)", "request_snapshot_json,image_model_id)")
            .replace("'{}')", "'{}','missing')"));
    sql(
        task("bound", "u", "SCENE", "cfgkey", "a".repeat(64))
            .replace("request_snapshot_json)", "request_snapshot_json,image_model_id)")
            .replace("'{}')", "'{}','cfg')"));
    // A task can move to another model, and deleting a model unbinds the tasks still on it.
    sql(
        "INSERT INTO models(id,interface_id,name,model,provider_tag,created_by) VALUES ('spare','i','备用','test/spare','openai','u')");
    sql("UPDATE generation_tasks SET image_model_id='spare' WHERE id='bound'");
    sql("DELETE FROM models WHERE id='spare'");
    try (var connection = connection();
        var query = connection.createStatement();
        var rows =
            query.executeQuery("SELECT image_model_id FROM generation_tasks WHERE id='bound'")) {
      assertTrue(rows.next());
      assertNull(rows.getString(1));
    }
    // An interface with models cannot go; a chat message may note why it did not look first.
    rejects("23503", "DELETE FROM model_interfaces WHERE id='i'");
    rejects("23514", "UPDATE generation_tasks SET analysis_skipped='OTHER' WHERE id='bound'");
    sql("UPDATE generation_tasks SET analysis_skipped='NO_VISION' WHERE id='bound'");
  }

  @Test
  void interfacesCarryOnlyTheirOwnFields() throws SQLException {
    // ADR-20261012-AB: the five offered types, plus the older Gemini-format third party.
    sql(INTERFACE + "('o','n','openai',NULL,'c','****','u')");
    sql(INTERFACE + "('d','n','deepseek',NULL,'c','****','u')");
    sql(INTERFACE + "('g','n','gemini',NULL,'c','****','u')");
    sql(INTERFACE + "('oc','n','openai-compatible','http://10.2.2.110:3000/v1','c','****','u')");
    sql(INTERFACE + "('gc','n','gemini-compatible','https://relay.example.com','c','****','u')");
    rejects("23514", INTERFACE + "('x1','n','other',NULL,'c','****','u')");
    rejects("23514", INTERFACE + "('x2','n','openai-compatible',NULL,'c','****','u')");
    rejects("23514", INTERFACE + "('x3','n','openai','https://a.example','c','****','u')");
    rejects("23514", INTERFACE + "('x4','n','gemini-compatible','ftp://a.example','c','****','u')");
    rejects("23514", INTERFACE + "('x5',' ','openai',NULL,'c','****','u')");
    rejects("23503", INTERFACE + "('x6','n','openai',NULL,'c','****','nobody')");
    // Editable, still within the type's rules.
    sql("UPDATE model_interfaces SET base_url='https://b.example' WHERE id='oc'");
    rejects("23514", "UPDATE model_interfaces SET base_url='ftp://b.example' WHERE id='oc'");
    // A model needs an interface; ids and tags keep their shapes.
    String model = "INSERT INTO models(id,interface_id,name,model,provider_tag,created_by) VALUES ";
    sql(model + "('m','o','n','gpt-image-2',NULL,'u')");
    rejects("23503", model + "('m2','missing','n','gpt-image-2',NULL,'u')");
    rejects("23514", model + "('m3','o','n','gpt image',NULL,'u')");
    rejects("23514", model + "('m4','o','n','gpt-image-2','bad tag','u')");
  }

  @Test
  void withdrawingCanvasExportsTakesTheirItemsOffSavedCanvases() throws SQLException {
    // A layout saved while phase 3 was live (V19) keeps only results and message cards (V20).
    String upgradeSchema = "upgrade_" + UUID.randomUUID().toString().replace("-", "");
    var v19 =
        Flyway.configure()
            .dataSource(url, user, password)
            .schemas(upgradeSchema)
            .target("19")
            .load();
    assertEquals(19, v19.migrate().migrationsExecuted);
    try (var connection = DriverManager.getConnection(url, user, password);
        var query = connection.createStatement()) {
      connection.setSchema(upgradeSchema);
      query.execute("INSERT INTO users(id,status) VALUES ('u','ACTIVE')");
      query.execute("INSERT INTO projects(id,owner_id,name) VALUES ('p','u','fixture')");
      query.execute(
          "INSERT INTO conversations(id,project_id,title) VALUES ('c1','p','画布'),('c2','p','只有结果')");
      query.execute(
          "INSERT INTO conversation_canvases(conversation_id,layout,version) VALUES "
              + "('c1','{\"items\":[{\"id\":\"f:1\",\"frame\":{\"width\":800,\"height\":800,\"background\":\"#FFFFFF\"},\"x\":0,\"y\":0,\"width\":600,\"height\":600},"
              + "{\"id\":\"a:r1\",\"artifact_id\":\"r1\",\"x\":1,\"y\":2,\"width\":3,\"height\":4},"
              + "{\"id\":\"x:1\",\"text\":{\"content\":\"送\",\"size\":48,\"color\":\"#000000\",\"align\":\"left\"},\"x\":0,\"y\":0,\"width\":9,\"height\":9},"
              + "{\"id\":\"t:m1\",\"task_id\":\"m1\",\"x\":5,\"y\":6,\"width\":7,\"height\":8},"
              + "{\"id\":\"s:1\",\"asset_id\":\"g1\",\"x\":0,\"y\":0,\"width\":9,\"height\":9}],\"removed\":[\"r2\"]}',4),"
              + "('c2','{\"items\":[{\"id\":\"a:r3\",\"artifact_id\":\"r3\",\"x\":0,\"y\":0,\"width\":9,\"height\":9}],\"removed\":[]}',2)");
      var upgrade =
          Flyway.configure().dataSource(url, user, password).schemas(upgradeSchema).load();
      assertEquals(3, upgrade.migrate().migrationsExecuted);
      try (var rows =
          query.executeQuery(
              "SELECT conversation_id,layout->'items',layout->'removed',version FROM conversation_canvases ORDER BY conversation_id")) {
        assertTrue(rows.next());
        assertEquals(
            "[{\"x\": 1, \"y\": 2, \"id\": \"a:r1\", \"width\": 3, \"height\": 4, \"artifact_id\": \"r1\"}, "
                + "{\"x\": 5, \"y\": 6, \"id\": \"t:m1\", \"width\": 7, \"height\": 8, \"task_id\": \"m1\"}]",
            rows.getString(2));
        assertEquals("[\"r2\"]", rows.getString(3));
        assertEquals(5, rows.getInt(4));
        // A canvas without withdrawn items is left as it was.
        assertTrue(rows.next());
        assertEquals(2, rows.getInt(4));
        assertFalse(rows.next());
      }
    }
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
      assertEquals(15, upgrade.migrate().migrationsExecuted);
      try (var rows = query.executeQuery("SELECT purpose,model_id FROM default_models")) {
        assertTrue(rows.next());
        assertEquals("IMAGE", rows.getString(1));
        assertEquals("cfg", rows.getString(2));
        assertFalse(rows.next());
      }
      // V10: the previously active, enabled row becomes a named, enabled default model; V21
      // moves its type, address and proxy setting to its own interface.
      try (var rows =
          query.executeQuery(
              "SELECT i.kind,v.provider_tag,i.base_url,v.name,v.enabled,false,i.use_proxy FROM models v JOIN model_interfaces i ON i.id=v.interface_id")) {
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
    // V18: one canvas layout per conversation, an object with a positive version.
    sql(
        "INSERT INTO conversation_canvases(conversation_id,layout,version) VALUES ('c1','{\"items\":[],\"removed\":[]}',1)");
    rejects(
        "23505",
        "INSERT INTO conversation_canvases(conversation_id,layout,version) VALUES ('c1','{}',1)");
    rejects("23514", "UPDATE conversation_canvases SET layout='[]' WHERE conversation_id='c1'");
    rejects("23514", "UPDATE conversation_canvases SET version=0 WHERE conversation_id='c1'");
    rejects(
        "23503",
        "INSERT INTO conversation_canvases(conversation_id,layout,version) VALUES ('nobody','{}',1)");
    // V20: the withdrawn canvas export (V19, ADR-20261010-X) is gone again: every task has a
    // product image and only messages belong to a conversation.
    String compose =
        "INSERT INTO generation_tasks(id,project_id,product_asset_id,feature_type,created_by,idempotency_key,request_sha256,request_snapshot_json,conversation_id) VALUES ('%s','p',%s,'%s','u','%s','"
            + "f".repeat(64)
            + "','{}','c1')";
    rejects("23514", compose.formatted("export", "'product'", "COMPOSE", "export-key"));
    rejects("23502", compose.formatted("blank", "NULL", "CUSTOM", "blank-key"));
    rejects("23514", compose.formatted("scene-chat", "'product'", "SCENE", "scene-chat-key"));
    // Deleting the conversation keeps the task (and its images); the layout goes with it.
    sql("DELETE FROM conversations WHERE id='c1'");
    assertEquals(2, count("generation_tasks"));
    assertEquals(0, count("conversation_canvases"));
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
    rejects("23514", "INSERT INTO default_models(purpose) VALUES ('other')");
    sql("INSERT INTO default_models(purpose) VALUES ('TEXT')");
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
}
