package com.productimage.business.runtime;

import com.fasterxml.jackson.databind.JsonNode;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.context.annotation.Profile;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;

@RestControllerAdvice(assignableTypes = RuntimeApi.class)
@Profile("runtime")
public class RuntimeErrors {
  private static final Logger LOG = LoggerFactory.getLogger(RuntimeErrors.class);

  @ExceptionHandler(Exception.class)
  public ResponseEntity<JsonNode> handle(Exception error) {
    String correlation = Json.id();
    int status = 500;
    String code = "GENERATION_FAILED";
    if (error instanceof Problem problem) {
      status = problem.status;
      code = problem.code;
    } else
      LOG.error(
          "runtime_request_failed correlation_id={} exception_type={}",
          correlation,
          error.getClass().getSimpleName());
    return ResponseEntity.status(status)
        .body(
            Json.object()
                .put("code", code)
                .put("message", "请求未被接受，请检查输入或服务状态")
                .put("correlation_id", correlation));
  }
}
