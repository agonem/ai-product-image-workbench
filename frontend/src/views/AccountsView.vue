<script setup lang="ts">
import { inject } from 'vue'
import EmptyState from '../components/EmptyState.vue'
import AccountPanel from '../workbench/AccountPanel.vue'
import { workbenchKey } from '../workbench/useWorkbench'

const w = inject(workbenchKey)!
</script>

<template>
  <main class="page">
    <AccountPanel
      v-if="w.production && w.identity?.role === 'ADMIN'"
      :api="w.api"
      :me="w.identity.id"
    />
    <section v-else class="card">
      <EmptyState art="model">只有生产环境的管理员可以管理账号。</EmptyState>
    </section>
  </main>
</template>
