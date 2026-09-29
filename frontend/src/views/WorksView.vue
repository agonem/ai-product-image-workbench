<script setup lang="ts">
import { computed, inject, ref } from 'vue'
import CompareDialog from '../components/CompareDialog.vue'
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
    <div class="workspace-head">
      <h1 class="page-title">我的作品</h1>
      <div class="chips" role="group" aria-label="按功能筛选">
        <button class="chip" :aria-pressed="filter === ''" @click="filter = ''">
          全部
        </button>
        <button
          v-for="item in features"
          :key="item.id"
          class="chip"
          :aria-pressed="filter === item.id"
          @click="filter = item.id"
        >
          {{ item.name }}
        </button>
      </div>
    </div>
    <section class="panel">
      <div v-if="works.length" class="result-strip">
        <article
          v-for="item in works"
          :key="item.artifact.id"
          class="result-card"
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
          <div class="meta">
            <span>{{ featureName(item.task.feature_type) }}</span>
            <span class="status-tag" data-status="SUCCEEDED">待人工审核</span>
            <div class="actions">
              <button
                class="text-button"
                @click="
                  comparing = { task: item.task.id, artifact: item.artifact.id }
                "
              >
                对照原图
              </button>
              <button
                class="text-button"
                :disabled="w.busy"
                @click="
                  w.download(item.artifact.id, `work-${item.artifact.id}`)
                "
              >
                下载
              </button>
              <button
                class="text-button danger"
                :disabled="w.busy"
                @click="remove(item.artifact.id)"
              >
                删除
              </button>
            </div>
          </div>
        </article>
      </div>
      <p v-else class="empty">还没有已完成的作品。</p>
      <button
        v-if="w.historyNext !== null"
        class="secondary"
        :disabled="w.busy"
        @click="w.refreshHistory(true)"
      >
        加载更多
      </button>
    </section>
    <CompareDialog
      v-if="comparing"
      :task="comparing.task"
      :artifact="comparing.artifact"
      @close="comparing = null"
    />
  </main>
</template>
