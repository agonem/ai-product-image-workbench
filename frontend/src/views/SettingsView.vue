<script setup lang="ts">
import { inject } from 'vue'
import AccountPanel from '../workbench/AccountPanel.vue'
import { workbenchKey } from '../workbench/useWorkbench'

const w = inject(workbenchKey)!
</script>

<template>
  <main class="page">
    <h1 class="page-title">账号与安全</h1>
    <section v-if="w.production && w.identity" class="panel">
      <AccountPanel :role="w.identity.role" :api="w.api" @changed="w.expire" />
    </section>
    <p v-else class="panel empty">
      开发环境账号由本机配置文件管理，不在页面中修改。
    </p>
  </main>
</template>
