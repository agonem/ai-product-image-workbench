<script setup lang="ts">
import { computed, inject, onUnmounted, ref, watch } from 'vue'
import { json } from '../api/workbench'
import { maskedPreview } from './cutout'
import type { Cutout } from './model'
import PrivateImage from './PrivateImage.vue'
import { workbenchKey } from './useWorkbench'

const props = defineProps<{
  asset: string
  label: string
  optional?: boolean
}>()
const w = inject(workbenchKey)!
const items = ref<Cutout[]>([])
const busy = ref(false),
  error = ref(''),
  tolerance = ref(12),
  preview = ref('')
let sequence = 0
const latest = computed(() => items.value[0])
const approved = computed(() =>
  items.value.find((item) => item.review_status === 'APPROVED'),
)
const status = computed(() => {
  if (!latest.value)
    return props.optional
      ? '未抠图：生成时按原图放置（可选抠图）'
      : '未抠图：需生成抠图并由你确认后才能用于生成'
  if (latest.value.review_status === 'PENDING') return '抠图候选待你确认'
  if (latest.value.review_status === 'APPROVED')
    return '已确认：生成时使用这份抠图'
  return approved.value
    ? '最新候选已拒绝；生成仍使用此前已确认的抠图'
    : '候选已拒绝：请调整容差重新生成'
})
function clearPreview() {
  if (preview.value) URL.revokeObjectURL(preview.value)
  preview.value = ''
}
async function load() {
  const current = ++sequence
  clearPreview()
  error.value = ''
  items.value = []
  if (!props.asset) return
  try {
    const page = await w.api<{ items: Cutout[] }>(
      `/assets/${props.asset}/cutouts`,
    )
    if (current !== sequence) return
    items.value = page.items
    const first = page.items[0]
    if (first?.review_status === 'PENDING') {
      const [original, alpha] = await Promise.all([
        w.api<Blob>(`/assets/${props.asset}/content`),
        w.api<Blob>(`/assets/${first.id}/content`),
      ])
      const url = await maskedPreview(original, alpha)
      if (current === sequence) preview.value = url
      else URL.revokeObjectURL(url)
    }
  } catch (cause) {
    if (current === sequence && cause instanceof Error)
      error.value = cause.message
  }
}
async function run(fn: () => Promise<void>) {
  if (busy.value || w.busy) return
  busy.value = true
  error.value = ''
  try {
    await fn()
  } catch (cause) {
    if (cause instanceof Error && cause.message !== 'STALE')
      error.value = cause.message
  } finally {
    busy.value = false
  }
}
function create() {
  return run(async () => {
    await w.api(
      `/assets/${props.asset}/cutouts`,
      json({ tolerance: tolerance.value }),
    )
    await load()
  })
}
function decide(decision: 'APPROVED' | 'REJECTED') {
  const candidate = latest.value
  if (!candidate) return
  return run(async () => {
    await w.api(`/assets/${candidate.id}/review`, json({ decision }))
    const owner = w.assets.find((item) => item.id === props.asset)
    if (owner && decision === 'APPROVED') owner.cutout_ready = true
    await load()
  })
}
watch(() => props.asset, load, { immediate: true })
onUnmounted(() => {
  sequence++
  clearPreview()
})
</script>

<template>
  <section class="cutout-panel" :aria-label="`${label}抠图确认`">
    <header>
      <strong>{{ label }}抠图</strong>
      <span
        class="cutout-status"
        :data-status="latest?.review_status ?? 'NONE'"
        data-testid="cutout-status"
        >{{ status }}</span
      >
    </header>
    <p v-if="error" class="message error" role="alert">{{ error }}</p>
    <div
      v-if="latest?.review_status === 'PENDING'"
      class="cutout-compare"
      data-testid="cutout-compare"
    >
      <figure>
        <PrivateImage
          :path="`/assets/${asset}/content`"
          :alt="`${label}原图`"
          :api="w.api"
        />
        <figcaption>原图</figcaption>
      </figure>
      <figure>
        <PrivateImage
          :path="`/assets/${latest.id}/content`"
          :alt="`${label}抠图蒙版`"
          :api="w.api"
        />
        <figcaption>蒙版（白色保留）</figcaption>
      </figure>
      <figure class="checkerboard">
        <img v-if="preview" :src="preview" :alt="`${label}透明预览`" />
        <span v-else role="status">生成预览…</span>
        <figcaption>透明预览</figcaption>
      </figure>
    </div>
    <p v-if="latest?.review_status === 'PENDING'" class="cutout-hint">
      请放大检查边缘、Logo、包装文字、细带和孔洞；确认后才会用于生成，拒绝不会删除原图。
    </p>
    <div class="asset-actions">
      <template v-if="latest?.review_status === 'PENDING'">
        <button
          type="button"
          :disabled="busy || w.busy"
          @click="decide('APPROVED')"
        >
          确认边缘可用
        </button>
        <button
          type="button"
          class="secondary"
          :disabled="busy || w.busy"
          @click="decide('REJECTED')"
        >
          不可用
        </button>
      </template>
      <label class="tolerance"
        >白底容差<input
          v-model.number="tolerance"
          type="number"
          min="0"
          max="32"
          step="1"
          :disabled="busy || w.busy"
      /></label>
      <button
        type="button"
        class="secondary"
        :disabled="busy || w.busy || !asset"
        @click="create"
      >
        {{ busy ? '处理中…' : latest ? '重新生成抠图候选' : '生成抠图候选' }}
      </button>
    </div>
    <small
      >按白底自动分离主体，只提供候选；是否可用由你确认。容差越大，越接近白色的边缘会被当作背景去掉。</small
    >
  </section>
</template>
