<script setup lang="ts">
import { inject, onMounted, ref } from 'vue'
import type { Generation } from '../workbench/model'
import PrivateImage from '../workbench/PrivateImage.vue'
import { workbenchKey } from '../workbench/useWorkbench'
import ModalDialog from './ModalDialog.vue'

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
  <ModalDialog title="原图对照" wide @close="emit('close')">
    <p class="hint">
      请核对 Logo、包装文字、颜色、外形、数量与赠品外观；不一致时请重新生成。
    </p>
    <p v-if="problem" class="banner error" role="alert">{{ problem }}</p>
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
  </ModalDialog>
</template>
