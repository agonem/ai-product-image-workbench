<script setup lang="ts">
import { computed, inject, onMounted, ref } from 'vue'
import EmptyState from '../components/EmptyState.vue'
import LineIcon from '../components/LineIcon.vue'
import { actionLabels } from '../workbench/audit'
import { workbenchKey } from '../workbench/useWorkbench'

type Entry = {
  id: string
  action: string
  resource_id: string
  actor: string
  occurred_at: string
}
type Account = { id: string; username: string }
// Operation log for admins (ADR-20260930-F): who did what and when; no request content.
const w = inject(workbenchKey)!
const admin = computed(() => w.production && w.identity?.role === 'ADMIN')
const entries = ref<Entry[]>([]),
  next = ref<number | null>(null)
const accounts = ref<Account[]>([])
const actor = ref(''),
  action = ref('')
const busy = ref(false),
  error = ref('')
const time = (value: string) => new Date(value).toLocaleString('zh-CN')
async function load(more = false) {
  busy.value = true
  error.value = ''
  try {
    const query = new URLSearchParams()
    if (actor.value) query.set('actor', actor.value)
    if (action.value) query.set('action', action.value)
    if (more && next.value !== null) query.set('offset', String(next.value))
    const page = await w.api<{ items: Entry[]; next_offset: number | null }>(
      `/admin/audit?${query}`,
    )
    entries.value = more ? [...entries.value, ...page.items] : page.items
    next.value = page.next_offset
  } catch (cause) {
    if (cause instanceof Error && cause.message !== 'STALE')
      error.value = cause.message
  } finally {
    busy.value = false
  }
}
onMounted(async () => {
  if (!admin.value) return
  void load()
  try {
    accounts.value = (
      await w.api<{ items: Account[] }>('/admin/accounts')
    ).items
  } catch {
    // The filter simply lists no accounts; the log itself still loads.
  }
})
</script>

<template>
  <main class="page">
    <div class="page-head">
      <div class="intro">
        <h1>操作日志</h1>
        <p>
          账号、图片、模型与模板的操作记录；只记录谁在何时做了什么，不含图片与文字内容。
        </p>
      </div>
    </div>
    <section v-if="!admin" class="card">
      <EmptyState art="clock"
        >只有生产环境的管理员可以查看操作日志。</EmptyState
      >
    </section>
    <template v-else>
      <div class="filter-bar">
        <label class="form-row inline"
          ><span>操作人</span
          ><select
            v-model="actor"
            aria-label="操作人"
            :disabled="busy"
            @change="load()"
          >
            <option value="">全部</option>
            <option v-for="item in accounts" :key="item.id" :value="item.id">
              {{ item.username }}
            </option>
          </select></label
        >
        <label class="form-row inline"
          ><span>动作</span
          ><select
            v-model="action"
            aria-label="动作"
            :disabled="busy"
            @change="load()"
          >
            <option value="">全部</option>
            <option
              v-for="(label, code) in actionLabels"
              :key="code"
              :value="code"
            >
              {{ label }}
            </option>
          </select></label
        >
        <span class="spacer"></span>
        <button type="button" class="btn" :disabled="busy" @click="load()">
          <LineIcon name="refresh" :size="14" />刷新
        </button>
      </div>
      <p v-if="error" class="banner error" role="alert">
        <LineIcon name="alert" :size="14" />{{ error }}
      </p>
      <section class="card">
        <div v-if="entries.length" class="table-wrap">
          <table class="table">
            <thead>
              <tr>
                <th>时间</th>
                <th>操作人</th>
                <th>动作</th>
                <th>对象</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="entry in entries"
                :key="entry.id"
                data-testid="audit-row"
              >
                <td class="num">{{ time(entry.occurred_at) }}</td>
                <td>{{ entry.actor || '系统' }}</td>
                <td>
                  {{ actionLabels[entry.action] ?? entry.action }}
                  <small class="mono">{{ entry.action }}</small>
                </td>
                <td class="mono">{{ entry.resource_id.slice(0, 18) }}</td>
              </tr>
            </tbody>
          </table>
        </div>
        <EmptyState v-else-if="!busy" art="clock"
          >没有符合条件的记录。</EmptyState
        >
        <div v-if="next !== null" class="card-foot">
          <button
            type="button"
            class="btn sm"
            :disabled="busy"
            @click="load(true)"
          >
            加载更多
          </button>
        </div>
      </section>
    </template>
  </main>
</template>
