package com.productimage.business.runtime;

import static org.junit.jupiter.api.Assertions.*;

import org.junit.jupiter.api.Test;

class FailureMessageTest {
  @Test
  void theWorkerDiagnosisNamesTheModelAndTheLikelyFix() {
    // The magic-wand failure of 2026-10-08: a text model pinned to a provider that lacks it.
    assertEquals(
        "魔法棒改写失败：文本模型不存在或路由标签不匹配（HTTP 404），请检查模型标识和路由标签",
        TaskService.safeMessage("PROVIDER_UNAVAILABLE", "TEXT_PROVIDER_HTTP_404"));
    // ADR-20261009-P: the look-first analysis says it was the analysis.
    assertEquals(
        "看图分析失败：文本模型不存在或路由标签不匹配（HTTP 404），请检查模型标识和路由标签",
        TaskService.safeMessage("PROVIDER_UNAVAILABLE", "VISION_PROVIDER_HTTP_404"));
    assertEquals(
        "出图模型的 API Key 无效或无权限（401）",
        TaskService.safeMessage("PROVIDER_UNAVAILABLE", "PROVIDER_HTTP_401"));
    assertEquals(
        "出图模型调用失败（HTTP 500）", TaskService.safeMessage("PROVIDER_UNAVAILABLE", "PROVIDER_HTTP_500"));
    // Without a usable diagnosis the generic message stays.
    assertEquals("生成服务未配置或暂不可用", TaskService.safeMessage("PROVIDER_UNAVAILABLE", ""));
    assertEquals("生成服务未配置或暂不可用", TaskService.safeMessage("PROVIDER_UNAVAILABLE", "<script>"));
  }
}
