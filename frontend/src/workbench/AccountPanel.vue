<script setup lang="ts">
import { onUnmounted, ref } from 'vue'
import { json } from '../api/workbench'

const props = defineProps<{
  role: 'ADMIN' | 'USER'
  api: <T>(path: string, init?: RequestInit) => Promise<T>
}>()
const emit = defineEmits<{ changed: [] }>()
type Account = { id: string; username: string; role: string; status: string }
const view = ref<'closed' | 'password' | 'accounts'>('closed')
const busy = ref(false),
  error = ref(''),
  notice = ref('')
const current = ref(''),
  next = ref(''),
  name = ref(''),
  initial = ref(''),
  newRole = ref('USER')
const accounts = ref<Account[]>([]),
  after = ref<string | null>(null)
const target = ref<Account | null>(null),
  replacement = ref('')
let alive = true
function setView(value: 'closed' | 'password' | 'accounts') {
  view.value = value
  current.value = next.value = initial.value = replacement.value = ''
  target.value = null
  error.value = notice.value = ''
}
function selectReset(account: Account | null) {
  target.value = account
  replacement.value = ''
}
onUnmounted(() => {
  alive = false
  current.value = next.value = initial.value = replacement.value = ''
  accounts.value = []
})
async function action(fn: () => Promise<void>) {
  if (busy.value) return
  busy.value = true
  error.value = ''
  notice.value = ''
  try {
    await fn()
  } catch (cause) {
    if (alive && cause instanceof Error && cause.message !== 'STALE')
      error.value = cause.message
  } finally {
    busy.value = false
    current.value = next.value = initial.value = replacement.value = ''
  }
}
async function load(more = false) {
  if (!alive || props.role !== 'ADMIN') return
  const result = await props.api<{
    items: Account[]
    next_after: string | null
  }>(
    '/admin/accounts' +
      (more && after.value ? '?after=' + encodeURIComponent(after.value) : ''),
  )
  if (!alive) return
  accounts.value = more ? [...accounts.value, ...result.items] : result.items
  after.value = result.next_after
}
function openAccounts() {
  if (props.role !== 'ADMIN') return
  view.value = 'accounts'
  target.value = null
  void action(() => load())
}
async function changePassword() {
  await action(async () => {
    await props.api(
      '/local-auth/password',
      json({ current_password: current.value, new_password: next.value }),
    )
    emit('changed')
  })
}
async function create() {
  await action(async () => {
    await props.api(
      '/admin/accounts',
      json({
        username: name.value,
        password: initial.value,
        role: newRole.value,
      }),
    )
    name.value = ''
    await load()
    notice.value = '账号已创建。'
  })
}
async function status(account: Account) {
  await action(async () => {
    await props.api(
      '/admin/accounts/' + account.id + '/status',
      json({ status: account.status === 'ACTIVE' ? 'DISABLED' : 'ACTIVE' }),
    )
    await load()
    notice.value = '状态已更新；该账号原有会话已撤销。'
  })
}
async function resetPassword() {
  if (!target.value) return
  const id = target.value.id
  await action(async () => {
    await props.api(
      '/admin/accounts/' + id + '/password',
      json({ new_password: replacement.value }),
    )
    target.value = null
    notice.value = '密码已重置；该账号所有会话已撤销。'
    await props.api('/local-auth/me')
  })
}
</script>

<template>
  <section class="account-section" aria-label="本地账号设置">
    <nav class="account-nav">
      <button class="secondary" :disabled="busy" @click="setView('password')">
        本人改密
      </button>
      <button
        v-if="role === 'ADMIN'"
        class="secondary"
        :disabled="busy"
        @click="openAccounts"
      >
        账号管理
      </button>
      <button
        v-if="view !== 'closed'"
        class="text-button"
        :disabled="busy"
        @click="setView('closed')"
      >
        收起账号设置
      </button>
    </nav>
    <div v-if="view !== 'closed'" class="panel account-panel">
      <p v-if="error" class="message error" role="alert">{{ error }}</p>
      <p v-if="notice" class="message" role="status">{{ notice }}</p>
      <form
        v-if="view === 'password'"
        class="fields"
        @submit.prevent="changePassword"
      >
        <h2>修改本人密码</h2>
        <p>修改后所有会话失效，需用新密码重新登录。新密码为 15–128 个字符。</p>
        <label
          >当前密码<input
            v-model="current"
            type="password"
            autocomplete="current-password"
            required
            :disabled="busy"
        /></label>
        <label
          >新密码<input
            v-model="next"
            type="password"
            autocomplete="new-password"
            minlength="15"
            maxlength="128"
            required
            :disabled="busy"
        /></label>
        <button :disabled="busy">保存新密码</button>
      </form>
      <template v-if="view === 'accounts' && role === 'ADMIN'">
        <h2>账号管理</h2>
        <p>
          管理账号不会授予跨项目读取素材或任务的权限。图片删除规则独立于账号管理，删除操作尚未开放。
        </p>
        <form class="account-create" @submit.prevent="create">
          <label
            >新账号名称<input
              v-model="name"
              pattern="[a-z0-9][a-z0-9_-]{0,63}"
              maxlength="64"
              autocomplete="off"
              required
              :disabled="busy"
          /></label>
          <label
            >初始密码<input
              v-model="initial"
              type="password"
              autocomplete="new-password"
              minlength="15"
              maxlength="128"
              required
              :disabled="busy"
          /></label>
          <label
            >账号角色<select v-model="newRole" :disabled="busy">
              <option value="USER">普通用户</option>
              <option value="ADMIN">管理员</option>
            </select></label
          >
          <button :disabled="busy">创建账号</button>
        </form>
        <p>
          停用、启用和重置都会撤销目标账号已有会话；至少保留一个启用的管理员。
        </p>
        <ul class="account-list">
          <li
            v-for="account in accounts"
            :key="account.id"
            data-testid="account-row"
          >
            <span
              ><strong>{{ account.username }}</strong> · {{ account.role }} ·
              {{ account.status }}</span
            >
            <div>
              <button
                class="secondary"
                :disabled="busy"
                @click="status(account)"
              >
                {{ account.status === 'ACTIVE' ? '停用' : '启用' }}
              </button>
              <button
                class="text-button"
                :disabled="busy"
                @click="selectReset(account)"
              >
                重置密码
              </button>
            </div>
          </li>
        </ul>
        <button
          v-if="after"
          class="secondary"
          :disabled="busy"
          @click="action(() => load(true))"
        >
          加载更多账号
        </button>
        <form v-if="target" class="fields" @submit.prevent="resetPassword">
          <h3>重置 {{ target.username }} 的密码</h3>
          <label
            >重置后的密码<input
              v-model="replacement"
              type="password"
              autocomplete="new-password"
              minlength="15"
              maxlength="128"
              required
              :disabled="busy"
          /></label>
          <button :disabled="busy">确认重置</button
          ><button
            type="button"
            class="secondary"
            :disabled="busy"
            @click="selectReset(null)"
          >
            取消重置
          </button>
        </form>
      </template>
    </div>
  </section>
</template>
