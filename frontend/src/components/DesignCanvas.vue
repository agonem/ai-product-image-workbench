<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import type { Box, TextSpec } from '../workbench/model'
import PrivateImage from '../workbench/PrivateImage.vue'

const props = defineProps<{
  width: number
  height: number
  background: string
  image: string | null
  imageAlt: string
  hint: string
  text: TextSpec | null
  palette: { badge: string; badgeText: string; accent: string }
  disabled: boolean
  api: <T>(path: string, init?: RequestInit) => Promise<T>
}>()
const box = defineModel<Box>('box', { required: true })
const stage = ref<HTMLElement>()
const pixels = ref(480)
let observer: ResizeObserver | undefined
onMounted(() => {
  observer = new ResizeObserver(([entry]) => {
    if (entry) pixels.value = entry.contentRect.width
  })
  if (stage.value) observer.observe(stage.value)
})
onUnmounted(() => observer?.disconnect())

// Approximate on-screen preview; the server fits the same box exactly.
const scale = computed(() => pixels.value / Math.max(64, props.width))
const layerStyle = computed(() => ({
  left: `${box.value.x * 100}%`,
  top: `${box.value.y * 100}%`,
  width: `${box.value.width * 100}%`,
  height: `${box.value.height * 100}%`,
  justifyItems:
    props.text?.align === 'center'
      ? 'center'
      : props.text?.align === 'right'
        ? 'end'
        : 'start',
  textAlign: props.text?.align ?? 'left',
}))
const titleStyle = computed(() => ({
  color: props.text?.color,
  fontSize: `${Math.max(6, (props.text?.size ?? 40) * scale.value)}px`,
}))
const pointStyle = computed(() => ({
  background: props.palette.badge,
  color: props.palette.badgeText,
  fontSize: `${Math.max(5, (props.text?.size ?? 40) * 0.55 * scale.value)}px`,
}))

let drag: {
  mode: 'move' | 'resize'
  x: number
  y: number
  start: Box
} | null = null
function down(mode: 'move' | 'resize', event: PointerEvent) {
  if (props.disabled) return
  event.stopPropagation()
  drag = { mode, x: event.clientX, y: event.clientY, start: { ...box.value } }
  ;(event.currentTarget as HTMLElement).setPointerCapture(event.pointerId)
}
function move(event: PointerEvent) {
  if (!drag || !stage.value) return
  const bounds = stage.value.getBoundingClientRect()
  const dx = (event.clientX - drag.x) / bounds.width
  const dy = (event.clientY - drag.y) / bounds.height
  const start = drag.start
  if (drag.mode === 'move')
    box.value = {
      ...start,
      x: Math.max(0, Math.min(1 - start.width, start.x + dx)),
      y: Math.max(0, Math.min(1 - start.height, start.y + dy)),
    }
  else
    box.value = {
      ...start,
      width: Math.max(0.1, Math.min(1 - start.x, start.width + dx)),
      height: Math.max(0.06, Math.min(1 - start.y, start.height + dy)),
    }
}
function up() {
  drag = null
}
</script>

<template>
  <div
    ref="stage"
    class="canvas-stage"
    data-testid="design-stage"
    :style="{
      aspectRatio: `${Math.max(64, width)}/${Math.max(64, height)}`,
      background,
    }"
  >
    <PrivateImage
      v-if="image"
      :key="image"
      :path="image"
      :alt="imageAlt"
      :api="api"
    />
    <p v-else class="canvas-hint">{{ hint }}</p>
    <div
      v-if="text"
      class="text-layer"
      data-testid="text-layer"
      :style="layerStyle"
      @pointerdown="down('move', $event)"
      @pointermove="move"
      @pointerup="up"
      @pointercancel="up"
    >
      <div v-if="text.title" class="title" :style="titleStyle">
        {{ text.title }}
      </div>
      <span
        v-for="(point, index) in text.points ?? []"
        :key="index"
        class="pill"
        :style="pointStyle"
        ><i :style="{ background: palette.accent }">✓</i>{{ point }}</span
      >
      <span
        v-if="!disabled"
        class="resize-handle"
        aria-hidden="true"
        @pointerdown="down('resize', $event)"
        @pointermove="move"
        @pointerup="up"
        @pointercancel="up"
      ></span>
    </div>
    <span class="canvas-label">{{ width }} × {{ height }}</span>
  </div>
</template>
