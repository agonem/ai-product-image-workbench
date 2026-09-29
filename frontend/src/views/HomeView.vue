<script setup lang="ts">
import { computed, inject } from 'vue'
import { useRouter } from 'vue-router'
import FeatureIcon from '../components/FeatureIcon.vue'
import PrivateImage from '../workbench/PrivateImage.vue'
import { featureName, features } from '../workbench/generation'
import { workbenchKey } from '../workbench/useWorkbench'

const w = inject(workbenchKey)!
const router = useRouter()
const recent = computed(() =>
  w.history
    .filter((item) => item.generation_v4 && item.task.status === 'SUCCEEDED')
    .flatMap((item) =>
      item.task.artifacts.map((artifact) => ({ task: item.task, artifact })),
    )
    .slice(0, 8),
)
</script>

<template>
  <main class="page">
    <h1 class="page-title">选择功能开始生成</h1>
    <section class="feature-cards" aria-label="三个独立功能">
      <article
        v-for="item in features"
        :key="item.id"
        class="feature-card"
        :data-tone="item.tone"
      >
        <header>
          <span class="feature-no">{{ item.no }}</span>
          <h2>{{ item.name }}</h2>
        </header>
        <p v-for="line in item.lines" :key="line">{{ line }}</p>
        <button
          :aria-label="`${item.name} 立即生成`"
          @click="router.push(`/create/${item.route}`)"
        >
          立即生成 →
        </button>
        <FeatureIcon :tone="item.tone" />
      </article>
    </section>
    <section class="panel results">
      <div class="results-head">
        <h2>最近作品</h2>
        <router-link class="nav-link" to="/works">查看全部</router-link>
      </div>
      <div v-if="recent.length" class="result-strip">
        <article
          v-for="item in recent"
          :key="item.artifact.id"
          class="result-card"
        >
          <figure>
            <PrivateImage
              :path="`/artifacts/${item.artifact.id}/content`"
              :alt="`${featureName(item.task.feature_type)}结果`"
              :api="w.api"
            />
          </figure>
          <div class="meta">
            <span>{{ featureName(item.task.feature_type) }}</span>
            <span class="status-tag" data-status="SUCCEEDED">待人工审核</span>
          </div>
        </article>
      </div>
      <p v-else class="empty">还没有生成结果。选择上面的功能开始第一张图。</p>
    </section>
  </main>
</template>
