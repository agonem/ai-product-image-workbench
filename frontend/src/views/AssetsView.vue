<script setup lang="ts">
import { computed, inject, ref } from 'vue'
import EmptyState from '../components/EmptyState.vue'
import LineIcon from '../components/LineIcon.vue'
import PrivateImage from '../workbench/PrivateImage.vue'
import { workbenchKey } from '../workbench/useWorkbench'

const w = inject(workbenchKey)!
const kind = ref<'PRODUCT' | 'GIFT'>('PRODUCT')
const items = computed(() => (kind.value === 'PRODUCT' ? w.products : w.gifts))
const label = computed(() => (kind.value === 'PRODUCT' ? '商品图' : '赠品图'))
function remove(id: string) {
  if (confirm('确定删除这张原图？删除后不可恢复；用它生成过的结果仍保留。'))
    void w.deleteAsset(id)
}
async function pick(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (file) await w.upload(file, kind.value)
}
</script>

<template>
  <main class="page">
    <div class="page-head">
      <h1>素材管理</h1>
      <div class="seg" role="group" aria-label="素材类型">
        <button
          type="button"
          :aria-pressed="kind === 'PRODUCT'"
          @click="kind = 'PRODUCT'"
        >
          商品图
        </button>
        <button
          type="button"
          :aria-pressed="kind === 'GIFT'"
          @click="kind = 'GIFT'"
        >
          赠品图
        </button>
      </div>
      <span class="spacer"></span>
      <label class="btn primary" :aria-disabled="w.busy"
        ><LineIcon name="up" :size="14" />上传{{ label
        }}<input
          class="sr-only"
          type="file"
          accept="image/png,image/jpeg"
          :aria-label="`上传${label}`"
          :disabled="w.busy"
          @change="pick"
      /></label>
    </div>
    <section class="card">
      <div class="card-head">
        <h2><LineIcon name="box" />{{ label }}</h2>
        <span class="muted num">{{ items.length }} 张</span>
        <span class="spacer"></span>
        <span class="hint">支持 PNG / JPEG，原图按上传内容保存</span>
      </div>
      <div class="card-body">
        <div v-if="items.length" class="image-grid">
          <article
            v-for="asset in items"
            :key="asset.id"
            class="image-card lift"
            data-testid="asset-card"
          >
            <figure>
              <PrivateImage
                :path="`/assets/${asset.id}/content`"
                :alt="`素材 ${asset.id}`"
                :api="w.api"
              />
            </figure>
            <div class="caption">
              <span class="num">{{ asset.width }} × {{ asset.height }}</span>
              <span class="spacer"></span>
              <span class="muted num">{{ asset.id.slice(0, 8) }}</span>
            </div>
            <div class="hover-actions">
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
      <div v-if="w.assetNext !== null" class="card-foot">
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
  </main>
</template>
