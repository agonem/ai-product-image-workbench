<script setup lang="ts">
import { inject } from 'vue'
import { useRouter } from 'vue-router'
import EmptyState from '../components/EmptyState.vue'
import LineIcon from '../components/LineIcon.vue'
import { featureName, features, taskLink } from '../workbench/generation'
import type { HistoryItem, Task } from '../workbench/model'
import { statusLabels } from '../workbench/model'
import { workbenchKey } from '../workbench/useWorkbench'

const w = inject(workbenchKey)!
const router = useRouter()
const time = (value: string) => new Date(value).toLocaleString('zh-CN')
const tone: Record<Task['status'], string> = {
  QUEUED: 'accent',
  RUNNING: 'accent',
  FAILED: 'danger',
  SUCCEEDED: 'ok',
}
function open(item: HistoryItem) {
  void router.push(taskLink(item.task.feature_type, item.task.id))
}
</script>

<template>
  <main class="page">
    <div class="page-head">
      <div class="intro">
        <h1>任务记录</h1>
        <p>
          所有生成与改字任务；点“查看”回到对应页面，失败的任务可在那里重试。
        </p>
      </div>
      <span class="spacer"></span>
      <button
        type="button"
        class="btn"
        :disabled="w.busy"
        @click="w.refreshHistory()"
      >
        <LineIcon name="refresh" :size="14" />刷新
      </button>
    </div>
    <section class="card">
      <div v-if="w.history.length" class="table-wrap">
        <table class="table">
          <thead>
            <tr>
              <th>功能</th>
              <th>提交时间</th>
              <th>执行次数</th>
              <th>图片</th>
              <th>状态</th>
              <th style="text-align: right">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="item in w.history"
              :key="item.task.id"
              class="history-item"
              :data-task="item.task.id"
            >
              <td>
                <span class="name"
                  ><LineIcon
                    :name="
                      features.find((f) => f.id === item.task.feature_type)
                        ?.tone ??
                      (item.task.feature_type === 'CUSTOM' ? 'chat' : 'grid')
                    "
                  />{{ featureName(item.task.feature_type)
                  }}<small v-if="!item.generation_v4">（旧版任务）</small></span
                >
                <small v-if="item.task.error"
                  >{{ item.task.error.message }}（{{
                    item.task.error.code
                  }}）</small
                >
              </td>
              <td class="num">{{ time(item.task.created_at) }}</td>
              <td class="num">第 {{ item.task.attempt }} 次</td>
              <td class="num">{{ item.task.artifacts.length }} 张</td>
              <td>
                <span
                  class="tag"
                  :class="item.test_fixture ? '' : tone[item.task.status]"
                  ><span class="dot"></span
                  >{{
                    item.test_fixture
                      ? '开发/测试任务'
                      : statusLabels[item.task.status]
                  }}</span
                >
              </td>
              <td>
                <div class="actions">
                  <button
                    v-if="item.generation_v4"
                    type="button"
                    class="link-btn"
                    @click="open(item)"
                  >
                    查看
                  </button>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <EmptyState v-else art="clock">还没有任务。</EmptyState>
      <div v-if="w.historyNext !== null" class="card-foot">
        <button
          type="button"
          class="btn sm"
          :disabled="w.busy"
          @click="w.refreshHistory(true)"
        >
          加载更早任务
        </button>
      </div>
    </section>
  </main>
</template>
