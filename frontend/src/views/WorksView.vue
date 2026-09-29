<script setup lang="ts">
import { computed, inject, ref } from 'vue'
import CompareDialog from '../components/CompareDialog.vue'
import EmptyState from '../components/EmptyState.vue'
import LineIcon from '../components/LineIcon.vue'
import PrivateImage from '../workbench/PrivateImage.vue'
import { featureName, features } from '../workbench/generation'
import type { Feature } from '../workbench/model'
import { workbenchKey } from '../workbench/useWorkbench'

const w = inject(workbenchKey)!
const filter = ref<Feature | ''>('')
const comparing = ref<{ task: string; artifact: string } | null>(null)
function remove(artifact: string) {
  if (confirm('确定删除这张生成结果？删除后不可恢复，也不能再免费改字。'))
    void w.deleteArtifact(artifact)
}
const time = (value: string) =>
  new Date(value).toLocaleString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
const works = computed(() =>
  w.history
    .filter(
      (item) =>
        item.generation_v4 &&
        item.task.status === 'SUCCEEDED' &&
        (!filter.value || item.task.feature_type === filter.value),
    )
    .flatMap((item) =>
      item.task.artifacts.map((artifact) => ({ task: item.task, artifact })),
    ),
)
</script>

<template>
  <main class="page">
    <div class="page-head">
      <h1>我的作品</h1>
      <div class="seg" role="group" aria-label="按功能筛选">
        <button
          type="button"
          :aria-pressed="filter === ''"
          @click="filter = ''"
        >
          全部
        </button>
        <button
          v-for="item in features"
          :key="item.id"
          type="button"
          :aria-pressed="filter === item.id"
          @click="filter = item.id"
        >
          {{ item.name }}
        </button>
      </div>
    </div>
    <section class="card">
      <div class="card-body">
        <div v-if="works.length" class="image-grid">
          <article
            v-for="item in works"
            :key="item.artifact.id"
            class="image-card lift"
            data-testid="result-card"
            :data-task="item.task.id"
          >
            <figure>
              <PrivateImage
                :path="`/artifacts/${item.artifact.id}/content`"
                :alt="`${featureName(item.task.feature_type)}作品`"
                :api="w.api"
              />
            </figure>
            <div class="caption">
              <span>{{ featureName(item.task.feature_type) }}</span>
              <span class="spacer"></span>
              <span class="muted num">{{ time(item.task.created_at) }}</span>
            </div>
            <div class="hover-actions">
              <button
                type="button"
                title="对照原图"
                aria-label="对照原图"
                @click="
                  comparing = { task: item.task.id, artifact: item.artifact.id }
                "
              >
                <LineIcon name="cmp" :size="14" />
              </button>
              <button
                type="button"
                title="下载"
                aria-label="下载"
                :disabled="w.busy"
                @click="
                  w.download(item.artifact.id, `work-${item.artifact.id}`)
                "
              >
                <LineIcon name="dl" :size="14" />
              </button>
              <button
                type="button"
                class="danger"
                title="删除"
                aria-label="删除"
                :disabled="w.busy"
                @click="remove(item.artifact.id)"
              >
                <LineIcon name="del" :size="14" />
              </button>
            </div>
          </article>
        </div>
        <EmptyState v-else>还没有已完成的作品。</EmptyState>
      </div>
      <div v-if="w.historyNext !== null" class="card-foot">
        <button
          type="button"
          class="btn sm"
          :disabled="w.busy"
          @click="w.refreshHistory(true)"
        >
          加载更多
        </button>
      </div>
    </section>
    <CompareDialog
      v-if="comparing"
      :task="comparing.task"
      :artifact="comparing.artifact"
      @close="comparing = null"
    />
  </main>
</template>
