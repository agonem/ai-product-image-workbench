<script setup lang="ts">
import { computed, inject, ref } from 'vue'
import { useRouter } from 'vue-router'
import EmptyState from '../components/EmptyState.vue'
import FeatureIcon from '../components/FeatureIcon.vue'
import ImageViewer from '../components/ImageViewer.vue'
import LineIcon from '../components/LineIcon.vue'
import PrivateImage from '../workbench/PrivateImage.vue'
import { featureName, features } from '../workbench/generation'
import { workbenchKey } from '../workbench/useWorkbench'

const w = inject(workbenchKey)!
const router = useRouter()
const v4 = computed(() => w.history.filter((item) => item.generation_v4))
const recent = computed(() =>
  v4.value
    .filter((item) => item.task.status === 'SUCCEEDED')
    .flatMap((item) =>
      item.task.artifacts.map((artifact) => ({ task: item.task, artifact })),
    )
    .slice(0, 8),
)
const viewing = ref<number | null>(null)
const viewerItems = computed(() =>
  recent.value.map((item) => ({
    path: `/artifacts/${item.artifact.id}/content`,
    title: featureName(item.task.feature_type),
    detail: `${item.artifact.width} × ${item.artifact.height}`,
    download: () => w.download(item.artifact.id, `work-${item.artifact.id}`),
  })),
)
</script>

<template>
  <main class="page">
    <div class="page-head">
      <div class="intro">
        <h1>选择功能开始生成</h1>
        <p>上传商品白底图，生成赠品主图、场景主图和卖点主图。</p>
      </div>
    </div>
    <section class="feature-cards" aria-label="生成功能">
      <article
        v-for="item in features"
        :key="item.id"
        class="card feature-card lift"
      >
        <span class="badge"><LineIcon :name="item.tone" :size="20" /></span>
        <h2>
          {{ item.name }}<small class="num">{{ item.no }}</small>
        </h2>
        <div>
          <p v-for="line in item.lines" :key="line">{{ line }}</p>
        </div>
        <button
          type="button"
          class="btn primary sm"
          :aria-label="`${item.name} 立即生成`"
          @click="router.push(`/create/${item.route}`)"
        >
          立即生成<LineIcon name="arrow" :size="14" />
        </button>
        <FeatureIcon :tone="item.tone" />
      </article>
    </section>
    <section class="card chat-banner" aria-label="对话生图">
      <span class="badge"><LineIcon name="chat" :size="20" /></span>
      <div>
        <h2>对话生图</h2>
        <p>用自己的话描述画面，生成后接着说要怎么改，像聊天一样调整图片。</p>
      </div>
      <button
        type="button"
        class="btn primary sm"
        aria-label="对话生图 开始对话"
        @click="router.push('/chat')"
      >
        开始对话<LineIcon name="arrow" :size="14" />
      </button>
    </section>
    <section class="card">
      <div class="card-head">
        <h2><LineIcon name="grid" />最近作品</h2>
        <span class="spacer"></span>
        <router-link class="link-btn" to="/works">查看全部</router-link>
      </div>
      <div class="card-body">
        <div v-if="recent.length" class="image-grid">
          <article
            v-for="item in recent"
            :key="item.artifact.id"
            class="image-card lift"
          >
            <figure @click="viewing = recent.indexOf(item)">
              <PrivateImage
                :path="`/artifacts/${item.artifact.id}/content`"
                :alt="`${featureName(item.task.feature_type)}结果`"
                :api="w.api"
              />
            </figure>
            <div class="caption">
              <span>{{ featureName(item.task.feature_type) }}</span>
              <span class="spacer"></span>
              <span class="num muted"
                >{{ item.artifact.width }}×{{ item.artifact.height }}</span
              >
            </div>
          </article>
        </div>
        <EmptyState v-else
          >还没有生成结果，选择上面的功能开始第一张图。</EmptyState
        >
      </div>
    </section>
    <ImageViewer
      v-if="viewing !== null && viewerItems.length"
      :items="viewerItems"
      :start="viewing"
      @close="viewing = null"
    />
  </main>
</template>
