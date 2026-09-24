<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { fetchBusinessHealth } from './api/health'

const state = ref<'loading' | 'ready' | 'error'>('loading')

async function checkConnection() {
  state.value = 'loading'
  try {
    await fetchBusinessHealth()
    state.value = 'ready'
  } catch {
    state.value = 'error'
  }
}

onMounted(checkConnection)
</script>

<template>
  <main class="shell">
    <header class="page-header">
      <p class="eyebrow">母婴商品图工作台</p>
      <span class="badge">开发环境 · T01</span>
    </header>

    <section aria-labelledby="page-title" class="intro">
      <h1 id="page-title">从可靠的基础开始</h1>
      <p>本页用于检查本地开发环境。图片制作功能将在后续任务中逐步接入。</p>
    </section>

    <section aria-labelledby="connection-title" class="panel">
      <div>
        <h2 id="connection-title">业务服务连接</h2>
        <p>检查工作台与业务服务之间的连接。</p>
      </div>
      <div
        role="status"
        aria-live="polite"
        class="connection"
        :data-state="state"
      >
        <span class="status-dot" aria-hidden="true"></span>
        <div>
          <strong v-if="state === 'loading'">正在检查连接…</strong>
          <strong v-else-if="state === 'ready'">业务服务已连接</strong>
          <strong v-else>暂时无法连接业务服务</strong>
          <p v-if="state === 'ready'">基础接口响应正常，可以继续开发。</p>
          <p v-else-if="state === 'error'">
            请确认业务服务已启动，再重新检查。
          </p>
          <p v-else>通常只需几秒钟，请稍候。</p>
        </div>
      </div>
      <button :disabled="state === 'loading'" @click="checkConnection">
        {{ state === 'loading' ? '检查中…' : '重新检查连接' }}
      </button>
    </section>

    <aside class="scope" aria-labelledby="scope-title">
      <h2 id="scope-title">当前可用范围</h2>
      <p>本地服务启动、连接检查与基础代码检查。</p>
      <p>赠品图、场景图和卖点图将分别提供独立入口，目前尚未开放。</p>
    </aside>
    <footer>仅供本地开发验证 · 暂无上传、生成或发布功能</footer>
  </main>
</template>
