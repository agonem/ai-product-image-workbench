<script setup lang="ts">
import { computed, inject, onMounted, onUnmounted, ref } from 'vue'
import PrivateImage from '../workbench/PrivateImage.vue'
import { workbenchKey } from '../workbench/useWorkbench'
import LineIcon from './LineIcon.vue'

export type ViewerItem = {
  path: string
  title: string
  detail?: string
  download?: () => void
}
// Full-screen image viewer (ADR-20260930-E): fit, zoom, previous/next, download.
const props = defineProps<{ items: ViewerItem[]; start: number }>()
const emit = defineEmits<{ close: [] }>()
const w = inject(workbenchKey)!
const dialog = ref<HTMLDialogElement>(),
  stage = ref<HTMLElement>()
const index = ref(Math.min(props.start, props.items.length - 1))
const zoom = ref(1)
const natural = ref({ width: 0, height: 0 }),
  room = ref({ width: 0, height: 0 })
const item = computed(() => props.items[index.value]!)
// 100% = the whole picture fits the window (never enlarged beyond its own pixels when fitting).
const size = computed(() => {
  const { width, height } = natural.value
  if (!width || !height || !room.value.width) return {}
  const fit = Math.min(room.value.width / width, room.value.height / height, 1)
  return {
    width: `${Math.round(width * fit * zoom.value)}px`,
    height: `${Math.round(height * fit * zoom.value)}px`,
  }
})
let observer: ResizeObserver | undefined
onMounted(() => {
  dialog.value?.showModal()
  observer = new ResizeObserver(([entry]) => {
    if (entry)
      room.value = {
        width: entry.contentRect.width,
        height: entry.contentRect.height,
      }
  })
  if (stage.value) observer.observe(stage.value)
})
onUnmounted(() => observer?.disconnect())
function loaded(event: Event) {
  const image = event.target as HTMLImageElement
  if (image.tagName === 'IMG')
    natural.value = { width: image.naturalWidth, height: image.naturalHeight }
}
function step(delta: number) {
  const count = props.items.length
  index.value = (index.value + delta + count) % count
  zoom.value = 1
  natural.value = { width: 0, height: 0 }
}
function zoomBy(delta: number) {
  zoom.value = Math.min(
    4,
    Math.max(0.25, Math.round((zoom.value + delta) * 4) / 4),
  )
}
function key(event: KeyboardEvent) {
  if (event.key === 'ArrowLeft' && props.items.length > 1) step(-1)
  else if (event.key === 'ArrowRight' && props.items.length > 1) step(1)
  else if (event.key === '+' || event.key === '=') zoomBy(0.25)
  else if (event.key === '-') zoomBy(-0.25)
  else if (event.key === '0') zoom.value = 1
  else return
  event.preventDefault()
}
</script>

<template>
  <dialog
    ref="dialog"
    class="viewer"
    aria-label="图片查看"
    @cancel.prevent="emit('close')"
    @keydown="key"
  >
    <div class="viewer-bar">
      <strong>{{ item.title }}</strong>
      <span class="num muted-light"
        >{{ index + 1 }} / {{ items.length
        }}<template v-if="item.detail"> · {{ item.detail }}</template></span
      >
      <span class="spacer"></span>
      <button
        type="button"
        aria-label="缩小"
        title="缩小（-）"
        @click="zoomBy(-0.25)"
      >
        <LineIcon name="minus" />
      </button>
      <button
        type="button"
        class="num"
        aria-label="适应窗口"
        title="适应窗口（0）"
        @click="zoom = 1"
      >
        {{ Math.round(zoom * 100) }}%
      </button>
      <button
        type="button"
        aria-label="放大"
        title="放大（+）"
        @click="zoomBy(0.25)"
      >
        <LineIcon name="zoomin" />
      </button>
      <button v-if="item.download" type="button" @click="item.download()">
        <LineIcon name="dl" />下载
      </button>
      <button
        type="button"
        aria-label="关闭"
        title="关闭（Esc）"
        @click="emit('close')"
      >
        <LineIcon name="close" />
      </button>
    </div>
    <div ref="stage" class="viewer-stage" @load.capture="loaded">
      <PrivateImage
        :key="item.path"
        :path="item.path"
        :alt="item.title"
        :api="w.api"
        :style="size"
      />
    </div>
    <template v-if="items.length > 1">
      <button
        type="button"
        class="viewer-step prev"
        aria-label="上一张"
        @click="step(-1)"
      >
        <LineIcon name="prev" :size="20" />
      </button>
      <button
        type="button"
        class="viewer-step next"
        aria-label="下一张"
        @click="step(1)"
      >
        <LineIcon name="next" :size="20" />
      </button>
    </template>
  </dialog>
</template>
