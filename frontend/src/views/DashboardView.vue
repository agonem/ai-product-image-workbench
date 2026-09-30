<script setup lang="ts">
import { computed, inject, onMounted, ref } from 'vue'
import DailyChart from '../components/DailyChart.vue'
import EmptyState from '../components/EmptyState.vue'
import LineIcon from '../components/LineIcon.vue'
import { featureName } from '../workbench/generation'
import type { Feature } from '../workbench/model'
import { workbenchKey } from '../workbench/useWorkbench'

type Row = { name: string; tasks: number; failed: number }
type Metrics = {
  days: number
  totals: {
    tasks: number
    succeeded: number
    failed: number
    images: number
    avg_seconds: number
    max_seconds: number
  }
  now: { queued: number; running: number }
  daily: { day: string; tasks: number; failed: number; images: number }[]
  by_feature: Row[]
  by_model: Row[]
  by_user: Row[]
}
// Data dashboard for admins (ADR-20260930-F).
const w = inject(workbenchKey)!
const admin = computed(() => w.production && w.identity?.role === 'ADMIN')
const days = ref(14)
const data = ref<Metrics | null>(null)
const busy = ref(false),
  error = ref('')
async function load() {
  busy.value = true
  error.value = ''
  try {
    data.value = await w.api<Metrics>(`/admin/metrics?days=${days.value}`)
  } catch (cause) {
    if (cause instanceof Error && cause.message !== 'STALE')
      error.value = cause.message
  } finally {
    busy.value = false
  }
}
onMounted(() => {
  if (admin.value) void load()
})
function pick(value: number) {
  days.value = value
  void load()
}
const rate = computed(() => {
  const t = data.value?.totals
  return t && t.tasks ? Math.round((t.succeeded / t.tasks) * 100) : 0
})
const seconds = (value: number) =>
  value >= 60 ? `${Math.floor(value / 60)} 分 ${value % 60} 秒` : `${value} 秒`
const failRate = (row: Row) =>
  row.tasks ? `${Math.round((row.failed / row.tasks) * 100)}%` : '—'
const tables = computed(() =>
  data.value
    ? [
        {
          title: '按功能',
          rows: data.value.by_feature.map((row) => ({
            ...row,
            name: featureName(row.name as Feature),
          })),
        },
        { title: '按模型', rows: data.value.by_model },
        { title: '按账号', rows: data.value.by_user },
      ]
    : [],
)
</script>

<template>
  <main class="page">
    <div class="page-head">
      <div class="intro">
        <h1>数据看板</h1>
        <p>生成任务、图片数量、成功率与耗时；按天、功能、模型和账号统计。</p>
      </div>
      <span class="spacer"></span>
      <div v-if="admin" class="tabs" role="group" aria-label="统计范围">
        <button
          v-for="value in [7, 14, 30]"
          :key="value"
          type="button"
          :aria-pressed="days === value"
          :disabled="busy"
          @click="pick(value)"
        >
          近 {{ value }} 天
        </button>
      </div>
    </div>
    <section v-if="!admin" class="card">
      <EmptyState art="model"
        >只有生产环境的管理员可以查看数据看板。</EmptyState
      >
    </section>
    <template v-else>
      <p v-if="error" class="banner error" role="alert">
        <LineIcon name="alert" :size="14" />{{ error }}
      </p>
      <div v-if="data" class="stat-grid">
        <div class="stat" data-testid="stat-tasks">
          <small>生成任务</small><b class="num">{{ data.totals.tasks }}</b>
          <span class="muted">失败 {{ data.totals.failed }}</span>
        </div>
        <div class="stat">
          <small>生成图片</small><b class="num">{{ data.totals.images }}</b>
          <span class="muted">张</span>
        </div>
        <div class="stat">
          <small>成功率</small><b class="num">{{ rate }}%</b>
          <span class="muted">成功 {{ data.totals.succeeded }}</span>
        </div>
        <div class="stat">
          <small>平均耗时</small
          ><b class="num">{{ seconds(data.totals.avg_seconds) }}</b>
          <span class="muted">最长 {{ seconds(data.totals.max_seconds) }}</span>
        </div>
        <div class="stat" data-testid="stat-now">
          <small>当前排队 / 生成中</small
          ><b class="num">{{ data.now.queued }} / {{ data.now.running }}</b>
          <span class="muted">实时</span>
        </div>
      </div>
      <section v-if="data" class="card">
        <div class="card-head">
          <h2><LineIcon name="clock" />每日任务</h2>
          <span class="spacer"></span>
          <span class="legend"><i class="sw-bar"></i>任务</span>
          <span class="legend"><i class="sw-bar failed"></i>失败</span>
        </div>
        <div class="card-body">
          <DailyChart :days="data.daily" />
        </div>
      </section>
      <div v-if="data" class="table-grid">
        <section v-for="table in tables" :key="table.title" class="card">
          <div class="card-head">
            <h2>{{ table.title }}</h2>
          </div>
          <div class="table-wrap">
            <table class="table">
              <thead>
                <tr>
                  <th>名称</th>
                  <th style="text-align: right">任务</th>
                  <th style="text-align: right">失败率</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="row in table.rows" :key="row.name">
                  <td>{{ row.name }}</td>
                  <td class="num" style="text-align: right">{{ row.tasks }}</td>
                  <td class="num" style="text-align: right">
                    {{ failRate(row) }}
                  </td>
                </tr>
                <tr v-if="!table.rows.length">
                  <td colspan="3" class="muted">这段时间没有任务</td>
                </tr>
              </tbody>
            </table>
          </div>
        </section>
      </div>
      <p v-if="busy && !data" class="loading-screen">正在统计…</p>
    </template>
  </main>
</template>
