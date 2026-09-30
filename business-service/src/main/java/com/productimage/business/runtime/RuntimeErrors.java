package com.productimage.business.runtime;

import com.fasterxml.jackson.databind.JsonNode;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.context.annotation.Profile;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;

@RestControllerAdvice(
    assignableTypes = {
      RuntimeApi.class,
      LocalAuthApi.class,
      ProductionAuthApi.class,
      ProviderConfigApi.class,
      ProjectAssetApi.class,
      WorkbenchApi.class
    })
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
          case "UPLOAD_TYPE_UNSUPPORTED" -> "无法识别的图片格式，请在页面上传（会自动转换）或另存为 JPG/PNG";
          case "UPLOAD_CONTENT_REJECTED" -> "图片文件不完整或已损坏，请重新导出后上传";
          case "UPLOAD_BUDGET_EXCEEDED" -> "图片超过服务器的安全上限（文件或像素过大）";
          case "MODEL_UNAVAILABLE" -> "所选模型已停用或不存在，请重新选择";
          case "DEFAULT_MODEL" -> "默认模型不能停用，请先把其他模型设为默认";
          case "ASSET_IN_USE" -> "这张原图正在生成中使用，完成后再删除";
          case "ASSET_DELETED" -> "原图已删除，不能再用于生成或重试";
          case "PROVIDER_DISABLED" -> "图片生成已被管理员禁用；管理员启用供应商配置前无法提交生成任务";
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
