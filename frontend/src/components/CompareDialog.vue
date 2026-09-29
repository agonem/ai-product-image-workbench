<script setup lang="ts">
import { inject, onMounted, ref } from 'vue'
import type { Generation } from '../workbench/model'
import PrivateImage from '../workbench/PrivateImage.vue'
import { workbenchKey } from '../workbench/useWorkbench'

const props = defineProps<{ task: string; artifact: string }>()
const emit = defineEmits<{ close: [] }>()
const w = inject(workbenchKey)!
const detail = ref<Generation | null>(null)
const problem = ref('')
onMounted(async () => {
  try {
    detail.value = await w.api<Generation>(`/v4/generation-tasks/${props.task}`)
  } catch {
    problem.value = '读取任务信息失败，请刷新后重试。'
  }
})
</script>

<template>
  <dialog
    class="compare"
    open
    aria-label="原图对照"
    @keydown.esc="emit('close')"
  >
    <div class="results-head">
      <h2>原图对照 · 待人工审核</h2>
      <button class="secondary" @click="emit('close')">关闭</button>
    </div>
    <p>
      <small
        >生成模型可能细微改变商品。请逐项核对：Logo
        与包装文字、颜色、外形结构、数量、赠品外观。不一致时请重新生成，不要直接使用。</small
      >
    </p>
    <p v-if="problem" class="message error">{{ problem }}</p>
    <div class="compare-grid">
      <figure v-if="detail?.request?.product_asset_id">
        <PrivateImage
          :path="`/assets/${detail.request.product_asset_id}/content`"
          alt="商品原图"
          :api="w.api"
          missing="原图已删除"
        />
        <figcaption>商品原图</figcaption>
      </figure>
      <figure v-if="detail?.request?.gift_asset_id">
        <PrivateImage
          :path="`/assets/${detail.request.gift_asset_id}/content`"
          alt="赠品原图"
          :api="w.api"
          missing="原图已删除"
        />
        <figcaption>赠品原图</figcaption>
      </figure>
      <figure>
        <PrivateImage
          :path="`/artifacts/${artifact}/content`"
          alt="生成结果"
          :api="w.api"
        />
        <figcaption>生成结果</figcaption>
      </figure>
    </div>
  </dialog>
</template>
