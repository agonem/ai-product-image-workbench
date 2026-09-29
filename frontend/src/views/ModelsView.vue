<script setup lang="ts">
import { inject } from 'vue'
import ProviderPanel from '../workbench/ProviderPanel.vue'
import { workbenchKey } from '../workbench/useWorkbench'

const w = inject(workbenchKey)!
</script>

<template>
  <main class="page">
    <h1 class="page-title">模型配置</h1>
    <section v-if="w.production && w.identity?.role === 'ADMIN'" class="panel">
      <ProviderPanel :api="w.api" />
    </section>
    <p v-else class="panel empty">只有生产环境的管理员可以配置生成模型。</p>
  </main>
</template>
