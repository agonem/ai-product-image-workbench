package com.productimage.business.runtime;

import com.fasterxml.jackson.databind.JsonNode;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.context.annotation.Profile;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;

@RestControllerAdvice(
    assignableTypes = {RuntimeApi.class, LocalAuthApi.class, ProjectAssetApi.class})
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
    } else if (error instanceof org.springframework.web.bind.ServletRequestBindingException
        || error
            instanceof
            org.springframework.web.method.annotation.MethodArgumentTypeMismatchException) {
      status = 400;
      code = "INVALID_CONTRACT";
    } else
      LOG.error(
          "runtime_request_failed correlation_id={} exception_type={}",
          correlation,
          error.getClass().getSimpleName());
    String message =
        switch (code) {
          case "UNAUTHORIZED" -> "登录信息无效或已过期";
          case "UPLOAD_TYPE_UNSUPPORTED" -> "请上传与声明类型一致的 PNG 或 JPEG";
          case "UPLOAD_CONTENT_REJECTED" -> "图片损坏或含未支持元数据，请使用无附加元数据的 PNG/JPEG";
          case "UPLOAD_BUDGET_EXCEEDED" -> "图片超过开发环境的大小或像素限制";
          default -> "请求未被接受，请检查输入或服务状态";
        };
    return ResponseEntity.status(status)
        .header("Cache-Control", "no-store")
        .body(
            Json.object()
                .put("code", code)
                .put("message", message)
                .put("correlation_id", correlation));
  }
}
