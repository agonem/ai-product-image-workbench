<script setup lang="ts">
import { computed, inject, ref } from 'vue'
import EmptyState from '../components/EmptyState.vue'
import ImageViewer from '../components/ImageViewer.vue'
import LineIcon from '../components/LineIcon.vue'
import PrivateImage from '../workbench/PrivateImage.vue'
import { confirmAction } from '../workbench/confirm'
import { assetKinds, kindName, type AssetKind } from '../workbench/model'
import { workbenchKey } from '../workbench/useWorkbench'

// Material categories (ADR-20261009-R): 商品图, 赠品图, 参考图 and the finished 作品图.
const w = inject(workbenchKey)!
const kind = ref<AssetKind | 'WORK'>('PRODUCT')
const items = computed(() =>
  kind.value === 'WORK' ? [] : w.assetsOf(kind.value),
)
const label = computed(() =>
  kind.value === 'WORK' ? '作品图' : kindName(kind.value),
)
const works = computed(() =>
  w.history
    .filter((item) => item.generation_v4 && item.task.status === 'SUCCEEDED')
    .flatMap((item) => item.task.artifacts),
)
const viewing = ref<number | null>(null)
const viewerItems = computed(() =>
  kind.value === 'WORK'
    ? works.value.map((artifact) => ({
        path: `/artifacts/${artifact.id}/content`,
        title: '作品图',
        detail: `${artifact.width} × ${artifact.height}`,
        download: () => w.download(artifact.id, `work-${artifact.id}`),
      }))
    : items.value.map((asset) => ({
        path: `/assets/${asset.id}/content`,
        title: asset.source_artifact_id
          ? `${label.value}（来自作品）`
          : label.value,
        detail: `${asset.width} × ${asset.height}`,
        download: () =>
          w.downloadFile(`/assets/${asset.id}/content`, `asset-${asset.id}`),
      })),
)
async function removeWork(id: string) {
  if (
    await confirmAction(
      '删除作品',
      '删除后不可恢复，也不能再免费修改这张图的文字。',
      '删除',
    )
  )
    await w.deleteArtifact(id)
}
async function remove(id: string) {
  if (
    await confirmAction(
      '删除原图',
      '删除后不可恢复，也不能再用它生成；用它生成过的结果仍保留。',
      '删除',
    )
  )
    await w.deleteAsset(id)
}
async function pick(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (file && kind.value !== 'WORK') await w.upload(file, kind.value)
}
</script>

<template>
  <main class="page">
    <div class="page-head">
      <div class="intro">
        <h1>素材管理</h1>
        <p>
          按商品图、赠品图、参考图和作品图分类；任何一类都能在生成页的任一位置选用。点击图片放大查看。
        </p>
      </div>
      <span class="spacer"></span>
      <div class="tabs" role="group" aria-label="素材类型">
        <button
          v-for="item in assetKinds"
          :key="item.id"
          type="button"
          :aria-pressed="kind === item.id"
          @click="kind = item.id"
        >
          {{ item.name }}
        </button>
        <button
          type="button"
          :aria-pressed="kind === 'WORK'"
          @click="kind = 'WORK'"
        >
          作品图
        </button>
      </div>
      <router-link v-if="kind === 'WORK'" class="btn" to="/works"
        >打开我的作品</router-link
      >
      <label v-else class="btn primary" :aria-disabled="w.busy"
        ><LineIcon name="up" :size="14" />上传{{ label
        }}<input
          class="sr-only"
          type="file"
          accept="image/*"
          :aria-label="`上传${label}`"
          :disabled="w.busy"
          @change="pick"
      /></label>
    </div>
    <section class="card">
      <div class="card-head">
        <h2><LineIcon name="box" />{{ label }}</h2>
        <span class="muted num"
          >{{ kind === 'WORK' ? works.length : items.length }} 张</span
        >
        <span class="spacer"></span>
        <span v-if="kind === 'WORK'" class="hint"
          >生成的结果图；在生成页选用时会复制一份作为所选位置的素材</span
        >
        <span v-else class="hint"
          >支持 JPG、PNG、WebP、GIF、BMP 等，单张最大 50MB；非 JPG/PNG
          会自动转为 PNG 保存</span
        >
      </div>
      <div class="card-body">
        <div v-if="kind === 'WORK' && works.length" class="image-grid">
          <article
            v-for="(artifact, index) in works"
            :key="artifact.id"
            class="image-card lift"
            data-testid="work-asset-card"
          >
            <figure @click="viewing = index">
              <PrivateImage
                :path="`/artifacts/${artifact.id}/content`"
                :alt="`作品 ${artifact.id}`"
                :api="w.api"
              />
            </figure>
            <div class="caption">
              <span class="num"
                >{{ artifact.width }} × {{ artifact.height }}</span
              >
              <span class="spacer"></span>
              <span class="muted num">{{ artifact.id.slice(0, 8) }}</span>
            </div>
            <div class="hover-actions">
              <button
                type="button"
                title="放大查看"
                aria-label="放大查看"
                @click="viewing = index"
              >
                <LineIcon name="zoomin" :size="14" />
              </button>
              <button
                type="button"
                title="下载"
                aria-label="下载"
                @click="w.download(artifact.id, `work-${artifact.id}`)"
              >
                <LineIcon name="dl" :size="14" />
              </button>
              <button
                type="button"
                class="danger"
                title="删除"
                :aria-label="`删除作品 ${artifact.id.slice(0, 8)}`"
                :disabled="w.busy"
                @click="removeWork(artifact.id)"
              >
                <LineIcon name="del" :size="14" />
              </button>
            </div>
          </article>
        </div>
        <EmptyState v-else-if="kind === 'WORK'" art="box"
          >还没有作品，生成完成后会出现在这里。</EmptyState
        >
        <div v-else-if="items.length" class="image-grid">
          <article
            v-for="asset in items"
            :key="asset.id"
            class="image-card lift"
            data-testid="asset-card"
          >
            <figure @click="viewing = items.indexOf(asset)">
              <PrivateImage
                :path="`/assets/${asset.id}/content`"
                :alt="`素材 ${asset.id}`"
                :api="w.api"
              />
            </figure>
            <div class="caption">
              <span class="num">{{ asset.width }} × {{ asset.height }}</span>
              <span v-if="asset.source_artifact_id" class="tag accent"
                >来自作品</span
              >
              <span class="spacer"></span>
              <span class="muted num">{{ asset.id.slice(0, 8) }}</span>
            </div>
            <div class="hover-actions">
              <button
                type="button"
                title="放大查看"
                aria-label="放大查看"
                @click="viewing = items.indexOf(asset)"
              >
                <LineIcon name="zoomin" :size="14" />
              </button>
              <button
                type="button"
                class="danger"
                title="删除"
                :aria-label="`删除素材 ${asset.id.slice(0, 8)}`"
                :disabled="w.busy"
                @click="remove(asset.id)"
              >
                <LineIcon name="del" :size="14" />
              </button>
            </div>
          </article>
        </div>
        <EmptyState v-else art="box"
          >还没有{{ label }}，点击右上角上传。</EmptyState
        >
      </div>
      <div v-if="kind !== 'WORK' && w.assetNext !== null" class="card-foot">
        <button
          type="button"
          class="btn sm"
          :disabled="w.busy"
          @click="w.moreAssets"
        >
          加载更多素材
        </button>
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
