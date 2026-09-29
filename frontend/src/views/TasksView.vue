<script setup lang="ts">
import { inject } from 'vue'
import { useRouter } from 'vue-router'
import { featureName, features } from '../workbench/generation'
import type { HistoryItem } from '../workbench/model'
import { statusLabels } from '../workbench/model'
import { workbenchKey } from '../workbench/useWorkbench'

const w = inject(workbenchKey)!
const router = useRouter()
const time = (value: string) => new Date(value).toLocaleString('zh-CN')
function open(item: HistoryItem) {
  const route = features.find((f) => f.id === item.task.feature_type)!.route
  void router.push({ path: `/create/${route}`, query: { task: item.task.id } })
}
</script>

<template>
  <main class="page">
    <div class="workspace-head">
      <h1 class="page-title">任务记录</h1>
      <button class="secondary" :disabled="w.busy" @click="w.refreshHistory()">
        刷新
      </button>
    </div>
    <section class="panel">
      <div v-if="w.history.length">
        <div
          v-for="item in w.history"
          :key="item.task.id"
          class="task-row history-item"
        >
          <div>
            <strong>{{
              item.generation_v4
                ? featureName(item.task.feature_type)
                : `${featureName(item.task.feature_type)}（旧版任务）`
            }}</strong>
            <small>
              · {{ time(item.task.created_at) }} · 第 {{ item.task.attempt }} 次
              · {{ item.task.artifacts.length }} 张</small
            >
            <p v-if="item.task.error">
              <small
                >{{ item.task.error.message }}（{{
                  item.task.error.code
                }}）</small
              >
            </p>
          </div>
          <span class="status-tag" :data-status="item.task.status">{{
            item.test_fixture ? '开发/测试任务' : statusLabels[item.task.status]
          }}</span>
          <button
            v-if="item.generation_v4"
            class="text-button"
            @click="open(item)"
          >
            查看
          </button>
          <span v-else></span>
        </div>
      </div>
      <p v-else class="empty">这个项目还没有任务。</p>
      <button
        v-if="w.historyNext !== null"
        class="secondary"
        :disabled="w.busy"
        @click="w.refreshHistory(true)"
      >
        加载更早任务
      </button>
    </section>
  </main>
</template>
