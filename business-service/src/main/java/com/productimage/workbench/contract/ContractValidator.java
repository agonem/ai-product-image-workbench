package com.productimage.workbench.contract;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.networknt.schema.JsonSchema;
import com.networknt.schema.JsonSchemaFactory;
import com.networknt.schema.SchemaLocation;
import com.networknt.schema.SchemaValidatorsConfig;
import com.networknt.schema.SpecVersion.VersionFlag;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

public final class ContractValidator {
  private static final Map<String, JsonSchema> CONTRACTS = load();

  private static Map<String, JsonSchema> load() {
    var documents = new HashMap<String, String>();
    var ids = new HashMap<String, String>();
    var mapper = new ObjectMapper();
    for (String name :
        List.of(
            "common",
            "task-create",
            "idempotency-key",
            "task",
            "task-completed",
            "task-failed",
            "task-response",
            "scene-create",
            "scene-request",
            "scene-completed",
            "scene-failed",
            "scene-v3-create",
            "scene-v3-request",
            "scene-v3-completed",
            "scene-v3-failed",
            "generation-v4-create",
            "generation-v4-retypeset",
            "generation-v4-request",
            "generation-v4-completed",
            "generation-v4-failed",
            "preset-catalog",
            "user-template")) {
      try (var input =
          ContractValidator.class.getResourceAsStream("/contracts/" + name + ".schema.json")) {
        if (input == null) throw new IllegalStateException("Missing bundled schema");
        String document = new String(input.readAllBytes(), StandardCharsets.UTF_8);
        String id = mapper.readTree(document).get("$id").asText();
        documents.put(id, document);
        if (!name.equals("common")) ids.put(name.equals("task") ? "task-request" : name, id);
      } catch (IOException ex) {
        throw new IllegalStateException("Cannot load bundled contracts", ex);
      }
    }
    var factory =
        JsonSchemaFactory.getInstance(
            VersionFlag.V202012,
            builder ->
                builder.schemaLoaders(
                    loaders ->
                        loaders.schemas(
                            id -> {
                              String document = documents.get(id);
                              if (document == null)
                                throw new IllegalArgumentException("Unregistered schema");
                              return document;
                            })));
    var config = SchemaValidatorsConfig.builder().formatAssertionsEnabled(true).build();
    var result = new HashMap<String, JsonSchema>();
    ids.forEach((name, id) -> result.put(name, factory.getSchema(SchemaLocation.of(id), config)));
    return Map.copyOf(result);
  }

  public List<String> validate(String name, JsonNode value) {
    JsonSchema schema = CONTRACTS.get(name);
    if (schema == null) throw new IllegalArgumentException("Unknown contract");
    return schema.validate(value).stream()
        .map(error -> error.getSchemaLocation() + ": " + error.getType())
        .sorted()
        .toList();
  }
}
