<script setup lang="ts">
import {
  computed,
  nextTick,
  onMounted,
  onUnmounted,
  reactive,
  ref,
  watch,
} from 'vue'
import {
  fitView,
  nearScreen,
  zoomAt,
  type Placed,
  type View,
} from '../workbench/canvas'
import LineIcon from './LineIcon.vue'

// The result canvas (ADR-20261010-S): pictures placed by the page, dragged to pan, the wheel
// (or two fingers) to zoom, double-click to preview, "显示全部" to frame everything.
const props = withDefaults(
  defineProps<{
    items: Placed[]
    /** Keys framed again whenever they or their places change; empty = everything. */
    focus?: string[]
    label: string
  }>(),
  { focus: () => [] },
)
const emit = defineEmits<{ preview: [key: string] }>()

const root = ref<HTMLElement>()
const view = ref<View>({ x: 0, y: 0, scale: 1 })
const size = ref({ width: 0, height: 0 })
// Framing keeps clear of the toolbar on top (whatever height it wraps to) and the zoom bar.
const overlay = ref<HTMLElement>()
const reserved = ref({ top: 0, bottom: 52 })
const ready = ref(false),
  panning = ref(false)
// Pictures load once they come near the screen, then stay loaded.
const seen = reactive(new Set<string>())
// What was framed last; null once the user pans or zooms (a resize then keeps the view).
let framed: string[] | null = null

function rectsOf(keys: string[]) {
  const wanted = keys.length ? new Set(keys) : null
  return props.items
    .filter((item) => !wanted || wanted.has(item.key))
    .map((item) => item.rect)
}
function frame(keys: string[] = props.focus) {
  framed = keys
  const room = {
    width: size.value.width,
    height: size.value.height - reserved.value.top - reserved.value.bottom,
  }
  if (room.width <= 0 || room.height <= 0) return
  const fitted = fitView(rectsOf(keys), room, 24, 1)
  view.value = { ...fitted, y: fitted.y + reserved.value.top }
  ready.value = true
}
const signature = computed(() => JSON.stringify(rectsOf(props.focus)))
watch(signature, () => void nextTick(() => frame()))

function moved(next: View) {
  view.value = next
  framed = null
}
function centre() {
  return { x: size.value.width / 2, y: size.value.height / 2 }
}
const zoomBy = (factor: number) => moved(zoomAt(view.value, factor, centre()))
const actual = () => moved(zoomAt(view.value, 1 / view.value.scale, centre()))
const percent = computed(() => `${Math.round(view.value.scale * 100)}%`)

watch(
  [view, size, () => props.items],
  () => {
    if (!size.value.width) return
    for (const item of props.items)
      if (!seen.has(item.key) && nearScreen(item.rect, view.value, size.value))
        seen.add(item.key)
  },
  { immediate: true },
)

// Controls inside the canvas keep their own pointer and wheel behaviour.
const OWN =
  '[data-no-pan], input, textarea, select, a, [role="slider"], .menu, .ic-overlay, .ic-footer, .ic-zoom, .hover-actions'
function wheel(event: WheelEvent) {
  if ((event.target as Element).closest('.menu, .ic-overlay, .ic-footer'))
    return
  event.preventDefault()
  const unit =
    event.deltaMode === 1 ? 16 : event.deltaMode === 2 ? size.value.height : 1
  // Pinching on a touchpad arrives as a wheel with Ctrl held, in small steps.
  const speed = event.ctrlKey ? 0.01 : 0.0015
  const factor = Math.min(
    2,
    Math.max(0.5, Math.exp(-event.deltaY * unit * speed)),
  )
  const box = root.value!.getBoundingClientRect()
  moved(
    zoomAt(view.value, factor, {
      x: event.clientX - box.left,
      y: event.clientY - box.top,
    }),
  )
}

const pointers = new Map<number, { x: number; y: number }>()
let start = { x: 0, y: 0 },
  last = { x: 0, y: 0 },
  pinch: { distance: number; middle: { x: number; y: number } } | null = null,
  dragged = false
const twoFingers = () => {
  const [a, b] = [...pointers.values()] as [
    { x: number; y: number },
    { x: number; y: number },
  ]
  return {
    distance: Math.max(1, Math.hypot(a.x - b.x, a.y - b.y)),
    middle: { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 },
  }
}
function down(event: PointerEvent) {
  dragged = false
  const middleButton = event.pointerType === 'mouse' && event.button === 1
  if (event.pointerType === 'mouse' && event.button !== 0 && !middleButton)
    return
  if (!middleButton && (event.target as Element).closest(OWN)) return
  pointers.set(event.pointerId, { x: event.clientX, y: event.clientY })
  if (pointers.size === 2) {
    pinch = twoFingers()
    panning.value = true
    for (const id of pointers.keys()) root.value?.setPointerCapture(id)
  } else if (pointers.size === 1) {
    start = last = { x: event.clientX, y: event.clientY }
  }
}
function move(event: PointerEvent) {
  const point = pointers.get(event.pointerId)
  if (!point) return
  // The button was released outside the canvas before the drag began.
  if (event.pointerType === 'mouse' && !event.buttons) return up(event)
  point.x = event.clientX
  point.y = event.clientY
  if (pointers.size >= 2 && pinch) {
    const now = twoFingers()
    const box = root.value!.getBoundingClientRect()
    const zoomed = zoomAt(view.value, now.distance / pinch.distance, {
      x: now.middle.x - box.left,
      y: now.middle.y - box.top,
    })
    moved({
      ...zoomed,
      x: zoomed.x + now.middle.x - pinch.middle.x,
      y: zoomed.y + now.middle.y - pinch.middle.y,
    })
    pinch = now
    dragged = true
    return
  }
  if (!panning.value) {
    // A click that wobbles a little is still a click.
    if (Math.hypot(point.x - start.x, point.y - start.y) < 4) return
    panning.value = true
    dragged = true
    root.value?.setPointerCapture(event.pointerId)
  }
  moved({
    ...view.value,
    x: view.value.x + point.x - last.x,
    y: view.value.y + point.y - last.y,
  })
  last = { x: point.x, y: point.y }
}
function up(event: PointerEvent) {
  if (!pointers.delete(event.pointerId)) return
  pinch = null
  const rest = [...pointers.values()][0]
  if (rest) last = start = { ...rest }
  else panning.value = false
}
// A drag never counts as a click on the picture it started on.
function swallow(event: MouseEvent) {
  if (!dragged) return
  dragged = false
  event.stopPropagation()
  event.preventDefault()
}
function key(event: KeyboardEvent) {
  if (event.target !== root.value) return
  const step = 80
  const shift: Record<string, [number, number]> = {
    ArrowLeft: [step, 0],
    ArrowRight: [-step, 0],
    ArrowUp: [0, step],
    ArrowDown: [0, -step],
  }
  const by = shift[event.key]
  if (by)
    moved({ ...view.value, x: view.value.x + by[0], y: view.value.y + by[1] })
  else if (event.key === '+' || event.key === '=') zoomBy(1.25)
  else if (event.key === '-') zoomBy(0.8)
  else if (event.key === '0') frame([])
  else return
  event.preventDefault()
}

let observer: ResizeObserver | undefined
onMounted(() => {
  root.value?.addEventListener('wheel', wheel, { passive: false })
  observer = new ResizeObserver(() => {
    if (!root.value) return
    size.value = {
      width: root.value.clientWidth,
      height: root.value.clientHeight,
    }
    const bar = overlay.value?.offsetHeight ?? 0
    reserved.value = { top: bar ? bar + 10 : 0, bottom: 52 }
    if (!ready.value || framed) frame(framed ?? props.focus)
  })
  if (root.value) observer.observe(root.value)
  if (overlay.value) observer.observe(overlay.value)
})
onUnmounted(() => {
  root.value?.removeEventListener('wheel', wheel)
  observer?.disconnect()
})
defineExpose({ frame })
</script>

<template>
  <div
    ref="root"
    class="ic"
    :class="{ panning }"
    role="region"
    :aria-label="label"
    tabindex="0"
    data-testid="canvas"
    :style="{ backgroundPosition: `${view.x}px ${view.y}px` }"
    @pointerdown="down"
    @pointermove="move"
    @pointerup="up"
    @pointercancel="up"
    @lostpointercapture="up"
    @mousedown="$event.button === 1 && $event.preventDefault()"
    @click.capture="swallow"
    @dragstart.prevent
    @keydown="key"
  >
    <div
      class="ic-world"
      :class="{ hidden: !ready && items.length }"
      data-testid="canvas-world"
      :data-scale="view.scale.toFixed(3)"
      :style="{
        transform: `translate(${view.x}px, ${view.y}px) scale(${view.scale})`,
        '--canvas-scale': view.scale,
      }"
    >
      <div
        v-for="item in items"
        :key="item.key"
        class="ic-item"
        :data-key="item.key"
        :style="{
          left: `${item.rect.x}px`,
          top: `${item.rect.y}px`,
          width: `${item.rect.width}px`,
          height: `${item.rect.height}px`,
        }"
        @dblclick="emit('preview', item.key)"
      >
        <slot :item="item" :near="seen.has(item.key)" />
      </div>
    </div>
    <div v-if="!items.length" class="ic-empty"><slot name="empty" /></div>
    <div ref="overlay" class="ic-overlay"><slot name="overlay" /></div>
    <div class="ic-footer"><slot name="footer" /></div>
    <div class="ic-zoom" role="group" aria-label="画布缩放">
      <button
        type="button"
        class="icon-btn"
        aria-label="缩小"
        title="缩小（滚轮向下）"
        @click="zoomBy(0.8)"
      >
        <LineIcon name="minus" :size="15" />
      </button>
      <button
        type="button"
        class="ic-percent num"
        aria-label="缩放比例"
        title="恢复 100%"
        data-testid="canvas-zoom"
        @click="actual"
      >
        {{ percent }}
      </button>
      <button
        type="button"
        class="icon-btn"
        aria-label="放大"
        title="放大（滚轮向上）"
        @click="zoomBy(1.25)"
      >
        <LineIcon name="zoomin" :size="15" />
      </button>
      <button
        type="button"
        class="btn sm"
        title="缩放到能看到全部内容（快捷键 0）"
        @click="frame([])"
      >
        <LineIcon name="grid" :size="14" />显示全部
      </button>
    </div>
  </div>
</template>
