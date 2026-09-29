<script setup lang="ts">
import { inject } from 'vue'
import LineIcon from '../components/LineIcon.vue'
import { workbenchKey } from '../workbench/useWorkbench'

const w = inject(workbenchKey)!
</script>

<template>
  <main class="login">
    <form class="card login-card" @submit.prevent="w.login">
      <div class="brand">
        <span class="logo" aria-hidden="true">母</span>
        <strong>母婴商品图工作台</strong>
      </div>
      <div>
        <h2>{{ w.production ? '生产账号登录' : '开发账号登录' }}</h2>
        <p class="hint">
          {{
            w.production
              ? '使用管理员分配的账号登录；忘记密码请联系管理员。'
              : '仅用于本机开发环境（dev-local），不能用于生产。'
          }}
        </p>
      </div>
      <p v-if="w.error" class="banner error" role="alert">
        <LineIcon name="alert" :size="14" />{{ w.error }}
      </p>
      <label class="form-row"
        ><span>账号</span
        ><input
          v-model="w.username"
          name="username"
          autocomplete="username"
          required
          :disabled="w.busy"
      /></label>
      <label class="form-row"
        ><span>密码</span
        ><input
          v-model="w.password"
          name="password"
          type="password"
          autocomplete="current-password"
          required
          :disabled="w.busy"
      /></label>
      <button class="btn primary" :disabled="w.busy">
        <span v-if="w.busy" class="spinner"></span>
        {{
          w.busy ? '登录中…' : w.production ? '登录生产账号' : '登录开发环境'
        }}
      </button>
      <p class="hint">有效期内刷新页面不会退出；点击退出后需重新登录。</p>
    </form>
  </main>
</template>
