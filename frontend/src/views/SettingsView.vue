<script setup lang="ts">
import { computed, inject, onUnmounted, ref } from 'vue'
import { json } from '../api/workbench'
import LineIcon from '../components/LineIcon.vue'
import { workbenchKey } from '../workbench/useWorkbench'

const w = inject(workbenchKey)!
const admin = computed(() => w.identity?.role === 'ADMIN')
const current = ref(''),
  next = ref(''),
  confirmation = ref('')
const busy = ref(false),
  error = ref('')
let alive = true
const until = computed(() =>
  w.sessionExpires ? new Date(w.sessionExpires).toLocaleString('zh-CN') : '',
)
onUnmounted(() => {
  alive = false
  current.value = next.value = confirmation.value = ''
})
async function changePassword() {
  if (busy.value) return
  error.value = ''
  if (next.value !== confirmation.value) {
    error.value = '两次输入的新密码不一致。'
    return
  }
  busy.value = true
  try {
    await w.api(
      '/local-auth/password',
      json({ current_password: current.value, new_password: next.value }),
    )
    // Every session of this account is revoked; sign in again with the new password.
    w.expire()
  } catch (cause) {
    if (alive && cause instanceof Error && cause.message !== 'STALE')
      error.value = cause.message
  } finally {
    busy.value = false
    current.value = next.value = confirmation.value = ''
  }
}
</script>

<template>
  <main class="page">
    <div class="page-head">
      <div class="intro">
        <h1>我的账号</h1>
        <p>账号信息与登录密码。</p>
      </div>
    </div>

    <section v-if="!w.production" class="card">
      <div class="card-body">
        <p class="banner">
          <LineIcon
            name="info"
            :size="14"
          />开发环境账号由本机配置文件管理，不在页面中修改。
        </p>
      </div>
    </section>

    <template v-else>
      <section class="card">
        <div class="card-head">
          <h2><LineIcon name="user" />账号信息</h2>
        </div>
        <div class="card-body">
          <div class="profile">
            <span class="avatar lg" aria-hidden="true">{{
              (w.identity?.username ?? 'U').slice(0, 1).toUpperCase()
            }}</span>
            <dl>
              <div>
                <dt>账号</dt>
                <dd>{{ w.identity?.username }}</dd>
              </div>
              <div>
                <dt>角色</dt>
                <dd>
                  <span class="tag" :class="{ accent: admin }">{{
                    admin ? '管理员' : '运营'
                  }}</span>
                </dd>
              </div>
              <div v-if="until">
                <dt>本次登录有效至</dt>
                <dd class="num">{{ until }}</dd>
              </div>
            </dl>
          </div>
        </div>
      </section>
      <section class="card">
        <div class="card-head">
          <h2><LineIcon name="shield" />修改密码</h2>
        </div>
        <form class="card-body narrow" @submit.prevent="changePassword">
          <p v-if="error" class="banner error" role="alert">
            <LineIcon name="alert" :size="14" />{{ error }}
          </p>
          <label class="form-row"
            ><span>当前密码</span
            ><input
              v-model="current"
              type="password"
              autocomplete="current-password"
              required
              :disabled="busy"
          /></label>
          <label class="form-row"
            ><span>新密码</span
            ><input
              aria-label="新密码"
              aria-describedby="new-password-hint"
              v-model="next"
              type="password"
              autocomplete="new-password"
              minlength="6"
              maxlength="15"
              required
              :disabled="busy"
            /><small id="new-password-hint"
              >6–15 个字符。修改后所有登录失效，需要用新密码重新登录。</small
            ></label
          >
          <label class="form-row"
            ><span>确认新密码</span
            ><input
              v-model="confirmation"
              type="password"
              autocomplete="new-password"
              minlength="6"
              maxlength="15"
              required
              :disabled="busy"
          /></label>
          <div>
            <button class="btn primary" :disabled="busy">保存新密码</button>
          </div>
        </form>
      </section>
    </template>
  </main>
</template>
