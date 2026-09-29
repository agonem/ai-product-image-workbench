<script setup lang="ts">
import { inject } from 'vue'
import EmptyState from '../components/EmptyState.vue'
import ProviderPanel from '../workbench/ProviderPanel.vue'
import { workbenchKey } from '../workbench/useWorkbench'

const w = inject(workbenchKey)!
</script>

<template>
  <main class="page">
    <ProviderPanel
      v-if="w.production && w.identity?.role === 'ADMIN'"
      :api="w.api"
    />
    <section v-else class="card">
      <EmptyState art="model"
        >只有生产环境的管理员可以配置生成模型。</EmptyState
      >
    </section>
  </main>
</template>
