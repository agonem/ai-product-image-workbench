package com.productimage.business;

import static org.assertj.core.api.Assertions.assertThat;

import com.fasterxml.jackson.databind.JsonNode;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.web.client.TestRestTemplate;
import org.springframework.http.HttpStatus;

@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT)
class HealthContractTest {
  @Autowired private TestRestTemplate http;

  @Test
  void healthMatchesThePublicV1Contract() {
    var response = http.getForEntity("/api/v1/health", JsonNode.class);
    assertThat(response.getStatusCode()).isEqualTo(HttpStatus.OK);
    var body = response.getBody();
    assertThat(body).isNotNull();
    assertThat(body.size()).isEqualTo(3);
    assertThat(body.path("status").asText()).isEqualTo("UP");
    assertThat(body.path("service").asText()).isEqualTo("business-service");
    assertThat(body.path("api_version").asText()).isEqualTo("v1");
  }

  @Test
  void doesNotPretendTaskCreationIsImplemented() {
    var response = http.postForEntity("/api/v1/tasks", null, String.class);
    assertThat(response.getStatusCode()).isEqualTo(HttpStatus.NOT_FOUND);
  }
}
