<script setup lang="ts">
import { computed, inject, ref } from 'vue'
import PrivateImage from '../workbench/PrivateImage.vue'
import { workbenchKey } from '../workbench/useWorkbench'

const w = inject(workbenchKey)!
const kind = ref<'PRODUCT' | 'GIFT'>('PRODUCT')
const items = computed(() => (kind.value === 'PRODUCT' ? w.products : w.gifts))
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
    <div class="workspace-head">
      <h1 class="page-title">素材管理</h1>
      <div class="chips" role="group" aria-label="素材类型">
        <button
          class="chip"
          :aria-pressed="kind === 'PRODUCT'"
          @click="kind = 'PRODUCT'"
        >
          商品白底图
        </button>
        <button
          class="chip"
          :aria-pressed="kind === 'GIFT'"
          @click="kind = 'GIFT'"
        >
          赠品图
        </button>
      </div>
    </div>
    <section class="panel fields">
      <label class="upload-tile secondary" style="padding: 12px"
        >＋ 上传{{
          kind === 'PRODUCT' ? '商品白底图' : '赠品图'
        }}（PNG/JPEG）<input
          type="file"
          accept="image/png,image/jpeg"
          :aria-label="`上传${kind === 'PRODUCT' ? '商品白底图' : '赠品图'}`"
          :disabled="w.busy"
          @change="pick"
      /></label>
      <small
        >原图按上传内容保存，不会被修改。实际内容、尺寸与资源预算由服务端校验。</small
      >
      <div v-if="items.length" class="asset-grid">
        <article v-for="asset in items" :key="asset.id" class="asset-card">
          <figure>
            <PrivateImage
              :path="`/assets/${asset.id}/content`"
              :alt="`素材 ${asset.id}`"
              :api="w.api"
            />
          </figure>
          <p>
            <span
              >{{ asset.width }}×{{ asset.height }} ·
              {{ asset.id.slice(0, 8) }}</span
            >
            <button
              class="text-button danger"
              :disabled="w.busy"
              :aria-label="`删除素材 ${asset.id.slice(0, 8)}`"
              @click="remove(asset.id)"
            >
              删除
            </button>
          </p>
        </article>
      </div>
      <p v-else class="empty">还没有这类素材。</p>
      <button
        v-if="w.assetNext !== null"
        class="secondary"
        :disabled="w.busy"
        @click="w.moreAssets"
      >
        加载更多素材
      </button>
    </section>
  </main>
</template>
