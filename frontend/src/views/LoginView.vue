<script setup lang="ts">
import { inject } from 'vue'
import { workbenchKey } from '../workbench/useWorkbench'

const w = inject(workbenchKey)!
</script>

<template>
  <main class="login-layout">
    <section class="login-intro">
      <h1>母婴商品图工作台</h1>
      <p>上传商品白底图，一键生成赠品主图、场景主图和卖点主图。</p>
      <ul>
        <li>商品原图永久保留，生成结果需人工核对后再使用</li>
        <li>营销文字与卖点按你输入的原文排版，不做改写</li>
        <li>只生成和下载，不会自动发布到任何平台</li>
      </ul>
    </section>
    <form class="panel login-card" @submit.prevent="w.login">
      <h2>{{ w.production ? '生产账号登录' : '开发账号登录' }}</h2>
      <p v-if="w.production">
        <small
          >使用管理员分配的本地账号。账号无默认密码；忘记密码请联系管理员。</small
        >
      </p>
      <p v-else>
        <small>仅用于本机开发环境（dev-local），不能用于生产。</small>
      </p>
      <p v-if="w.error" class="message error" role="alert">{{ w.error }}</p>
      <label
        >本地账号<input
          v-model="w.username"
          name="username"
          autocomplete="username"
          required
          :disabled="w.busy"
      /></label>
      <label
        >密码<input
          v-model="w.password"
          name="password"
          type="password"
          autocomplete="current-password"
          required
          :disabled="w.busy"
      /></label>
      <button :disabled="w.busy">
        {{
          w.busy ? '登录中…' : w.production ? '登录生产账号' : '登录开发环境'
        }}
      </button>
      <small>会话只保存在当前页面内存中，刷新后需重新登录。</small>
    </form>
  </main>
</template>
