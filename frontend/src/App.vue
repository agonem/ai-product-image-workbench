<script setup lang="ts">
import { provide, reactive } from 'vue'
import SideNav from './components/SideNav.vue'
import TopBar from './components/TopBar.vue'
import LoginView from './views/LoginView.vue'
import { useWorkbench, workbenchKey } from './workbench/useWorkbench'

const w = reactive(useWorkbench())
provide(workbenchKey, w)
</script>

<template>
  <LoginView v-if="!w.token" />
  <div v-else class="app-shell">
    <SideNav />
    <div class="app-main">
      <TopBar />
      <p v-if="w.mockProvider" class="mode-banner">
        模拟模型验收模式 · 结果不是真实生成
      </p>
      <p v-if="w.error" class="message error" role="alert">{{ w.error }}</p>
      <p v-if="w.notice" class="message" role="status">{{ w.notice }}</p>
      <p v-if="w.loading" class="empty">正在读取项目素材与任务…</p>
      <main v-else-if="!w.project" class="page">
        <section class="panel empty">
          还没有项目。请在上方输入项目名称并创建项目，然后开始生成。
        </section>
      </main>
      <router-view v-else :key="w.project" />
    </div>
  </div>
</template>
