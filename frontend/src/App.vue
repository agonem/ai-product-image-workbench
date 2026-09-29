<script setup lang="ts">
import { provide, reactive } from 'vue'
import { useRoute } from 'vue-router'
import LineIcon from './components/LineIcon.vue'
import SideNav from './components/SideNav.vue'
import LoginView from './views/LoginView.vue'
import { useWorkbench, workbenchKey } from './workbench/useWorkbench'

const w = reactive(useWorkbench())
const route = useRoute()
provide(workbenchKey, w)
</script>

<template>
  <p v-if="w.restoring" class="loading-screen">正在恢复登录…</p>
  <LoginView v-else-if="!w.signedIn" />
  <div v-else class="app-shell">
    <SideNav />
    <div class="app-main">
      <p v-if="w.mockProvider" class="mode-banner">
        <LineIcon name="info" :size="14" />模拟模型验收模式 · 结果不是真实生成
      </p>
      <!-- Early in the DOM so assistive tech and tests meet the messages first. -->
      <div class="toasts">
        <div v-if="w.error" class="toast error" role="alert">
          <LineIcon name="alert" />
          <p>{{ w.error }}</p>
          <button
            type="button"
            class="icon-btn"
            aria-label="关闭提示"
            @click="w.dismissError()"
          >
            <LineIcon name="close" :size="14" />
          </button>
        </div>
        <div v-if="w.notice" class="toast" role="status">
          <LineIcon name="check" />
          <p>{{ w.notice }}</p>
        </div>
      </div>
      <p v-if="w.loading" class="loading-screen">正在读取素材与任务…</p>
      <router-view
        v-else-if="w.project || route.meta.project === false"
        :key="w.project"
      />
      <p v-else class="loading-screen">正在准备工作区…</p>
    </div>
  </div>
</template>
