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
    assertEquals(1, flyway.migrate().migrationsExecuted);
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
            "audit_events")) {
      assertEquals(List.of("users", "projects", "assets").contains(table) ? 2 : 0, count(table));
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
  }

  @Test
  void materialRolesCannotBeConfused() throws SQLException {
    sql(
        "INSERT INTO assets(id,project_id,kind,object_key,sha256,width,height) VALUES ('gift','p','GIFT','fixtures/gift','"
            + "c".repeat(64)
            + "',64,64)");
    sql(
        "INSERT INTO assets(id,project_id,kind,source_asset_id,object_key,sha256,width,height) VALUES ('alpha','p','ALPHA','product','fixtures/alpha','"
            + "d".repeat(64)
            + "',64,64)");
    rejects(
        "23514", task("bad", "u", "SCENE", "key", "a".repeat(64)).replace("'product'", "'gift'"));
    rejects(
        "23514", task("bad", "u", "SCENE", "key", "a".repeat(64)).replace("'product'", "'alpha'"));
    String giftTask =
        task("t", "u", "GIFT", "key", "a".repeat(64))
            .replace("request_snapshot_json)", "request_snapshot_json,gift_asset_id)")
            .replace("'{}')", "'{}','gift')");
    rejects("23514", giftTask.replace("'gift')", "'product')"));
    sql(giftTask);
    rejects(
        "23514",
        "INSERT INTO assets(id,project_id,kind,source_asset_id,object_key,sha256,width,height) VALUES ('nested','p','ALPHA','alpha','fixtures/nested','"
            + "e".repeat(64)
            + "',64,64)");
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
