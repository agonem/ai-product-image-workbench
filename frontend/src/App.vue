<script setup lang="ts">
import { provide, reactive } from 'vue'
import { useRoute } from 'vue-router'
import SideNav from './components/SideNav.vue'
import LoginView from './views/LoginView.vue'
import { useWorkbench, workbenchKey } from './workbench/useWorkbench'

const w = reactive(useWorkbench())
const route = useRoute()
provide(workbenchKey, w)
</script>

<template>
  <p v-if="w.restoring" class="empty">正在恢复登录…</p>
  <LoginView v-else-if="!w.signedIn" />
  <div v-else class="app-shell">
    <SideNav />
    <div class="app-main">
      <p v-if="w.mockProvider" class="mode-banner">
        模拟模型验收模式 · 结果不是真实生成
      </p>
      <p v-if="w.error" class="message error" role="alert">{{ w.error }}</p>
      <p v-if="w.notice" class="message" role="status">{{ w.notice }}</p>
      <p v-if="w.loading" class="empty">正在读取素材与任务…</p>
      <router-view
        v-else-if="w.project || route.meta.project === false"
        :key="w.project"
      />
      <p v-else class="empty">正在准备工作区…</p>
    </div>
  </div>
</template>
