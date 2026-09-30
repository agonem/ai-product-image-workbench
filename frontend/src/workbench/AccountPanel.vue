<script setup lang="ts">
import { onMounted, onUnmounted, ref } from 'vue'
import { json } from '../api/workbench'
import LineIcon from '../components/LineIcon.vue'
import ModalDialog from '../components/ModalDialog.vue'
import { confirmAction } from './confirm'

// Admin-only account management: list, create, enable/disable, reset password, delete.
const props = defineProps<{
  api: <T>(path: string, init?: RequestInit) => Promise<T>
  /** The signed-in admin, who cannot delete themself. */
  me: string
}>()
type Account = { id: string; username: string; role: string; status: string }
const busy = ref(false),
  error = ref(''),
  notice = ref('')
const accounts = ref<Account[]>([]),
  after = ref<string | null>(null)
const creating = ref(false),
  name = ref(''),
  initial = ref(''),
  newRole = ref('USER')
const target = ref<Account | null>(null),
  replacement = ref('')
let alive = true
onMounted(() => void action(() => load()))
onUnmounted(() => {
  alive = false
  initial.value = replacement.value = ''
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
    initial.value = replacement.value = ''
  }
}
async function load(more = false) {
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
function openCreate() {
  name.value = initial.value = ''
  newRole.value = 'USER'
  creating.value = true
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
    creating.value = false
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
    notice.value = '状态已更新；该账号原有登录已失效。'
  })
}
/** Deletes an account and its images (ADR-20260930-E); the name can be used again. */
async function remove(account: Account) {
  const ok = await confirmAction(
    `删除账号 ${account.username}`,
    '删除后该账号立即退出且无法再登录，账号名可以重新创建；它上传的原图和生成的图片会一并删除，不可恢复。',
    '删除账号',
  )
  if (!ok) return
  await action(async () => {
    await props.api('/admin/accounts/' + account.id, { method: 'DELETE' })
    await load()
    notice.value = `账号 ${account.username} 已删除，其图片已一并删除。`
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
    notice.value = '密码已重置；该账号所有登录已失效。'
    // Resetting one's own password ends this session too.
    await props.api('/local-auth/me')
  })
}
</script>

<template>
  <div class="page-head">
    <div class="intro">
      <h1>账号管理</h1>
      <p>
        停用、启用、重置密码和删除都会让该账号已有的登录失效；至少保留一个启用的管理员。
      </p>
    </div>
    <span class="spacer"></span>
    <button
      type="button"
      class="btn primary"
      :disabled="busy"
      @click="openCreate"
    >
      <LineIcon name="plus" :size="14" />新建账号
    </button>
  </div>
  <p v-if="error && !creating && !target" class="banner error" role="alert">
    <LineIcon name="alert" :size="14" />{{ error }}
  </p>
  <p v-if="notice" class="banner ok" role="status">
    <LineIcon name="check" :size="14" />{{ notice }}
  </p>
  <section class="card" aria-label="账号列表">
    <div class="table-wrap">
      <table class="table">
        <thead>
          <tr>
            <th>账号</th>
            <th>角色</th>
            <th>状态</th>
            <th style="text-align: right">操作</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="account in accounts"
            :key="account.id"
            data-testid="account-row"
          >
            <td>
              <span class="name"
                ><span class="avatar sm" aria-hidden="true">{{
                  account.username.slice(0, 1).toUpperCase()
                }}</span
                >{{ account.username
                }}<small v-if="account.id === me">（当前登录）</small></span
              >
            </td>
            <td>{{ account.role === 'ADMIN' ? '管理员' : '普通用户' }}</td>
            <td>
              <span
                class="tag"
                :class="account.status === 'ACTIVE' ? 'ok' : 'danger'"
                ><span class="dot"></span
                >{{ account.status === 'ACTIVE' ? '已启用' : '已停用' }}</span
              >
            </td>
            <td>
              <div class="actions">
                <button
                  type="button"
                  class="link-btn"
                  :class="{ danger: account.status === 'ACTIVE' }"
                  :disabled="busy"
                  @click="status(account)"
                >
                  {{ account.status === 'ACTIVE' ? '停用' : '启用' }}
                </button>
                <button
                  type="button"
                  class="link-btn"
                  :disabled="busy"
                  @click="((target = account), (replacement = ''))"
                >
                  重置密码
                </button>
                <button
                  v-if="account.id !== me"
                  type="button"
                  class="link-btn danger"
                  :disabled="busy"
                  @click="remove(account)"
                >
                  删除
                </button>
              </div>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
    <div v-if="after" class="card-foot">
      <button
        type="button"
        class="btn sm"
        :disabled="busy"
        @click="action(() => load(true))"
      >
        加载更多账号
      </button>
    </div>

    <ModalDialog v-if="creating" title="新建账号" @close="creating = false">
      <form id="create-account" class="form-grid" @submit.prevent="create">
        <p v-if="error" class="banner error" role="alert">
          <LineIcon name="alert" :size="14" />{{ error }}
        </p>
        <label class="form-row"
          ><span>新账号名称</span
          ><input
            aria-label="新账号名称"
            aria-describedby="account-name-hint"
            v-model="name"
            pattern="[a-z0-9][a-z0-9_\-]{0,63}"
            maxlength="64"
            autocomplete="off"
            required
            :disabled="busy"
          /><small id="account-name-hint"
            >小写字母、数字、下划线或短横线。</small
          ></label
        >
        <label class="form-row"
          ><span>初始密码</span
          ><input
            aria-label="初始密码"
            aria-describedby="initial-password-hint"
            v-model="initial"
            type="password"
            autocomplete="new-password"
            minlength="6"
            maxlength="15"
            required
            :disabled="busy"
          /><small id="initial-password-hint">6–15 个字符。</small></label
        >
        <label class="form-row"
          ><span>账号角色</span
          ><select v-model="newRole" :disabled="busy">
            <option value="USER">普通用户</option>
            <option value="ADMIN">管理员</option>
          </select></label
        >
      </form>
      <template #footer>
        <button type="button" class="btn" @click="creating = false">
          取消
        </button>
        <button
          type="submit"
          form="create-account"
          class="btn primary"
          :disabled="busy"
        >
          创建账号
        </button>
      </template>
    </ModalDialog>

    <ModalDialog
      v-if="target"
      :title="`重置 ${target.username} 的密码`"
      @close="target = null"
    >
      <form
        id="reset-password"
        class="form-grid"
        @submit.prevent="resetPassword"
      >
        <p v-if="error" class="banner error" role="alert">
          <LineIcon name="alert" :size="14" />{{ error }}
        </p>
        <label class="form-row"
          ><span>重置后的密码</span
          ><input
            aria-label="重置后的密码"
            aria-describedby="reset-password-hint"
            v-model="replacement"
            type="password"
            autocomplete="new-password"
            minlength="6"
            maxlength="15"
            required
            :disabled="busy"
          /><small id="reset-password-hint"
            >6–15 个字符；重置后该账号需要用新密码重新登录。</small
          ></label
        >
      </form>
      <template #footer>
        <button type="button" class="btn" @click="target = null">取消</button>
        <button
          type="submit"
          form="reset-password"
          class="btn primary"
          :disabled="busy"
        >
          确认重置
        </button>
      </template>
    </ModalDialog>
  </section>
</template>
