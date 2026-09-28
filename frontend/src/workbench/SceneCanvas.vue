<script setup lang="ts">
import { computed, onUnmounted, ref, watch } from 'vue'
import type { Box } from './model'
const props = defineProps<{
  product: string
  width: number
  height: number
  disabled: boolean
  api: <T>(path: string, init?: RequestInit) => Promise<T>
}>()
const box = defineModel<Box>('box', { required: true })
const subject = ref(''),
  status = ref(''),
  stage = ref<HTMLElement>()
let sequence = 0
function clear() {
  if (subject.value) URL.revokeObjectURL(subject.value)
  subject.value = ''
}
watch(
  () => props.product,
  async (id) => {
    const current = ++sequence
    clear()
    status.value = ''
    if (!id) return
    let original: ImageBitmap | undefined, alpha: ImageBitmap | undefined
    try {
      const blobs = await Promise.all([
        props.api<Blob>(`/assets/${id}/content`),
        props.api<Blob>(`/assets/${id}/approved-alpha`),
      ])
      original = await createImageBitmap(blobs[0])
      alpha = await createImageBitmap(blobs[1])
      if (original.width !== alpha.width || original.height !== alpha.height)
        throw new Error('size')
      const canvas = document.createElement('canvas')
      canvas.width = original.width
      canvas.height = original.height
      const context = canvas.getContext('2d')!
      context.drawImage(alpha, 0, 0)
      const mask = context.getImageData(0, 0, canvas.width, canvas.height)
      context.clearRect(0, 0, canvas.width, canvas.height)
      context.drawImage(original, 0, 0)
      const pixels = context.getImageData(0, 0, canvas.width, canvas.height)
      let left = canvas.width,
        top = canvas.height,
        right = 0,
        bottom = 0
      for (let y = 0; y < canvas.height; y++)
        for (let x = 0; x < canvas.width; x++) {
          const i = (y * canvas.width + x) * 4
          pixels.data[i + 3] = Math.round(
            (pixels.data[i + 3]! * mask.data[i]!) / 255,
          )
          if (pixels.data[i + 3]) {
            left = Math.min(left, x)
            top = Math.min(top, y)
            right = Math.max(right, x + 1)
            bottom = Math.max(bottom, y + 1)
          }
        }
      if (right <= left || bottom <= top) throw new Error('empty')
      context.putImageData(pixels, 0, 0)
      const cropped = document.createElement('canvas')
      cropped.width = right - left
      cropped.height = bottom - top
      cropped
        .getContext('2d')!
        .drawImage(
          canvas,
          left,
          top,
          right - left,
          bottom - top,
          0,
          0,
          cropped.width,
          cropped.height,
        )
      const blob = await new Promise<Blob>((resolve, reject) =>
        cropped.toBlob((b) => (b ? resolve(b) : reject(new Error('encode')))),
      )
      if (current === sequence) subject.value = URL.createObjectURL(blob)
    } catch {
      if (current === sequence)
        status.value = '已审核主体预览不可用，请确认素材和 alpha。'
    } finally {
      original?.close()
      alpha?.close()
    }
  },
  { immediate: true },
)
onUnmounted(() => {
  sequence++
  clear()
})
const style = computed(() => ({
  left: `${box.value.x * 100}%`,
  top: `${box.value.y * 100}%`,
  width: `${box.value.width * 100}%`,
  height: `${box.value.height * 100}%`,
}))
let drag: { x: number; y: number; box: Box } | null = null
function down(event: PointerEvent) {
  if (props.disabled) return
  drag = { x: event.clientX, y: event.clientY, box: { ...box.value } }
  ;(event.currentTarget as HTMLElement).setPointerCapture(event.pointerId)
}
function move(event: PointerEvent) {
  if (!drag || !stage.value || props.disabled) return
  const bounds = stage.value.getBoundingClientRect()
  box.value = {
    ...drag.box,
    x: Math.max(
      0,
      Math.min(
        1 - drag.box.width,
        drag.box.x + (event.clientX - drag.x) / bounds.width,
      ),
    ),
    y: Math.max(
      0,
      Math.min(
        1 - drag.box.height,
        drag.box.y + (event.clientY - drag.y) / bounds.height,
      ),
    ),
  }
}
function scale(event: Event) {
  const value = Number((event.target as HTMLInputElement).value)
  const factor = value / box.value.width
  const height = Math.min(1, box.value.height * factor)
  const width = value * (height / (box.value.height * factor))
  box.value = {
    x: Math.min(box.value.x, 1 - width),
    y: Math.min(box.value.y, 1 - height),
    width,
    height,
  }
}
</script>
<template>
  <div class="scene-editor panel">
    <div class="section-heading">
      <h2>2. 编辑设计</h2>
      <span class="badge">位置预览 · 非生成结果</span>
    </div>
    <div
      ref="stage"
      class="scene-stage"
      :style="{ aspectRatio: `${Math.max(64, width)}/${Math.max(64, height)}` }"
      data-testid="scene-stage"
    >
      <div
        v-if="subject"
        class="subject-placement"
        :style="style"
        @pointerdown="down"
        @pointermove="move"
        @pointerup="drag = null"
        @pointercancel="drag = null"
        data-testid="subject-placement"
      >
        <img
          :src="subject"
          alt="原图 RGB 与已审核 alpha 的主体位置预览"
          draggable="false"
        />
      </div>
      <p v-else class="canvas-status">
        {{ status || '选择已审核商品后调整位置' }}
      </p>
      <span class="canvas-label">{{ width }} × {{ height }} · 背景待生成</span>
    </div>
    <label
      >等比例缩放<input
        type="range"
        min="0.05"
        max="1"
        step="0.01"
        :value="box.width"
        :disabled="disabled || !subject"
        @input="scale"
    /></label>
    <small>拖动商品调整位置，也可输入右侧数字。主体原图不被覆盖。</small>
  </div>
</template>
