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
  between,
  fitView,
  nearScreen,
  overlaps,
  toWorld,
  zoomAt,
  type Placed,
  type Rect,
  type View,
} from '../workbench/canvas'
import LineIcon from './LineIcon.vue'

// The result canvas (ADR-20261010-S): pictures placed by the page, dragged to pan, the wheel
// (or two fingers) to zoom, double-click to preview, "显示全部" to frame everything.
// Editable (ADR-20261010-V, the conversation page): with the select tool a drag on a picture
// moves the selection and a drag on empty space draws a selection box; the hand tool, a held
// Space or the middle button pan. The page owns the layout: it hears `move` and `command`.
export type CanvasCommand =
  | 'remove'
  | 'duplicate'
  | 'copy'
  | 'paste'
  | 'undo'
  | 'redo'
const props = withDefaults(
  defineProps<{
    items: Placed[]
    /** Keys framed again whenever they or their places change; empty = everything. */
    focus?: string[]
    /** When given, framing follows this value instead of the places (moving keeps the view). */
    frameOn?: string
    label: string
    editable?: boolean
    selected?: string[]
    tool?: 'select' | 'hand'
  }>(),
  { focus: () => [], selected: () => [], tool: 'select' },
)
const emit = defineEmits<{
  preview: [key: string]
  move: [keys: string[], dx: number, dy: number]
  command: [name: CanvasCommand]
  'update:selected': [keys: string[]]
  'update:tool': [tool: 'select' | 'hand']
  resize: [key: string, width: number, height: number]
}>()

const root = ref<HTMLElement>()
const view = ref<View>({ x: 0, y: 0, scale: 1 })
const size = ref({ width: 0, height: 0 })
// Framing keeps clear of the toolbar on top (whatever height it wraps to) and the zoom bar.
const overlay = ref<HTMLElement>()
const reserved = ref({ top: 0, bottom: 52 })
const ready = ref(false),
  panning = ref(false),
  spaceHeld = ref(false)
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
const signature = computed(() =>
  props.frameOn !== undefined
    ? props.frameOn
    : JSON.stringify(rectsOf(props.focus)),
)
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

const selectedSet = computed(() => new Set(props.selected))
const movable = computed(
  () =>
    new Set(props.items.filter((item) => item.movable).map((item) => item.key)),
)
const hand = computed(
  () => !props.editable || props.tool === 'hand' || spaceHeld.value,
)

// Controls inside the canvas keep their own pointer and wheel behaviour. Buttons in a caption
// (a board's "导出图片", a message's "详情") act without selecting: a settings bar opening on
// selection could otherwise cover the button before the click ends.
const OWN =
  '[data-no-pan], input, textarea, select, a, [role="slider"], .menu, .ic-overlay, .ic-footer, .ic-zoom, .hover-actions, .cell-caption button'
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

type Point = { x: number; y: number }
const pointers = new Map<number, Point>()
let start: Point = { x: 0, y: 0 },
  last: Point = { x: 0, y: 0 },
  pinch: { distance: number; middle: Point } | null = null,
  dragged = false,
  // What the current press does once it moves: pan, move the selection or draw a box.
  mode: 'pan' | 'drag' | 'box' | 'resize' | null = null,
  active = false,
  boxBase: string[] = []
// While dragging pictures: which ones and by how much (world units), shown before the drop.
const dragging = ref<Set<string>>(new Set())
const offset = reactive({ x: 0, y: 0 })
// The selection box on screen, relative to the canvas.
const box = ref<Rect | null>(null)
// While resizing one item with its corner handle: the new size (world units) before the drop.
const sizing = ref<{ key: string; width: number; height: number } | null>(null)
let sizingStart: Rect & { ratio: boolean } = {
  x: 0,
  y: 0,
  width: 1,
  height: 1,
  ratio: true,
}
// The one selected item that can be resized shows the handle.
const handled = computed(() => {
  if (!props.editable || props.selected.length !== 1) return null
  const item = props.items.find((entry) => entry.key === props.selected[0])
  return item?.resize ? item : null
})
const sizeOf = (item: Placed) =>
  sizing.value?.key === item.key
    ? { width: sizing.value.width, height: sizing.value.height }
    : { width: item.rect.width, height: item.rect.height }
const twoFingers = () => {
  const [a, b] = [...pointers.values()] as [Point, Point]
  return {
    distance: Math.max(1, Math.hypot(a.x - b.x, a.y - b.y)),
    middle: { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 },
  }
}
function local(point: Point): Point {
  const area = root.value!.getBoundingClientRect()
  return { x: point.x - area.left, y: point.y - area.top }
}
function reset() {
  sizing.value = null
  mode = null
  active = false
  panning.value = false
  dragging.value = new Set()
  offset.x = offset.y = 0
  box.value = null
}
function down(event: PointerEvent) {
  dragged = false
  const middleButton = event.pointerType === 'mouse' && event.button === 1
  if (event.pointerType === 'mouse' && event.button !== 0 && !middleButton)
    return
  const target = event.target as Element
  if (!middleButton && target.closest(OWN)) return
  pointers.set(event.pointerId, { x: event.clientX, y: event.clientY })
  if (pointers.size === 2) {
    // Two fingers always pan and zoom; whatever one finger started is dropped.
    reset()
    pinch = twoFingers()
    panning.value = true
    for (const id of pointers.keys()) root.value?.setPointerCapture(id)
    return
  }
  if (pointers.size > 2) return
  start = last = { x: event.clientX, y: event.clientY }
  if (target.closest('.ic-handle') && handled.value) {
    mode = 'resize'
    sizingStart = {
      ...handled.value.rect,
      ratio: handled.value.resize === 'ratio',
    }
    sizing.value = {
      key: handled.value.key,
      width: sizingStart.width,
      height: sizingStart.height,
    }
    return
  }
  const key = (target.closest('.ic-item') as HTMLElement | null)?.dataset.key
  const onPicture = !!key && movable.value.has(key)
  if (middleButton || hand.value) mode = 'pan'
  else if (onPicture) {
    if (event.shiftKey || event.ctrlKey || event.metaKey) {
      // Add to or take from the selection; no drag.
      emit(
        'update:selected',
        selectedSet.value.has(key)
          ? props.selected.filter((item) => item !== key)
          : [...props.selected, key],
      )
      mode = null
      return
    }
    const keys = selectedSet.value.has(key) ? props.selected : [key]
    if (!selectedSet.value.has(key)) emit('update:selected', keys)
    dragging.value = new Set(keys)
    mode = 'drag'
  } else if (event.pointerType === 'touch') mode = 'pan'
  else {
    mode = 'box'
    boxBase =
      event.shiftKey || event.ctrlKey || event.metaKey
        ? [...props.selected]
        : []
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
    const area = root.value!.getBoundingClientRect()
    const zoomed = zoomAt(view.value, now.distance / pinch.distance, {
      x: now.middle.x - area.left,
      y: now.middle.y - area.top,
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
  if (!mode) return
  if (!active) {
    // A click that wobbles a little is still a click.
    if (Math.hypot(point.x - start.x, point.y - start.y) < 4) return
    active = true
    dragged = true
    if (mode === 'pan') panning.value = true
    root.value?.setPointerCapture(event.pointerId)
  }
  if (mode === 'pan')
    moved({
      ...view.value,
      x: view.value.x + point.x - last.x,
      y: view.value.y + point.y - last.y,
    })
  else if (mode === 'resize' && sizing.value) {
    const width = Math.max(
      24,
      sizingStart.width + (point.x - start.x) / view.value.scale,
    )
    const height = sizingStart.ratio
      ? (width * sizingStart.height) / sizingStart.width
      : Math.max(
          24,
          sizingStart.height + (point.y - start.y) / view.value.scale,
        )
    sizing.value = { ...sizing.value, width, height }
  } else if (mode === 'drag') {
    offset.x += (point.x - last.x) / view.value.scale
    offset.y += (point.y - last.y) / view.value.scale
  } else if (mode === 'box') {
    box.value = between(local(start), local(point))
    const area = toWorld(box.value, view.value)
    const hits = props.items
      .filter((item) => item.movable && overlaps(area, item.rect))
      .map((item) => item.key)
    emit('update:selected', [...new Set([...boxBase, ...hits])])
  }
  last = { x: point.x, y: point.y }
}
function up(event: PointerEvent) {
  if (!pointers.delete(event.pointerId)) return
  pinch = null
  const rest = [...pointers.values()][0]
  if (rest) {
    // One finger left after a pinch keeps panning.
    last = start = { ...rest }
    mode = 'pan'
    active = true
    return
  }
  if (mode === 'resize' && active && sizing.value)
    emit(
      'resize',
      sizing.value.key,
      Math.round(sizing.value.width),
      Math.round(sizing.value.height),
    )
  else if (mode === 'drag' && active && (offset.x || offset.y))
    emit(
      'move',
      [...dragging.value],
      Math.round(offset.x),
      Math.round(offset.y),
    )
  // A click on empty space clears the selection (or keeps it while Shift is held).
  else if (mode === 'box' && !active) emit('update:selected', boxBase)
  reset()
}
// A drag never counts as a click on the picture it started on.
function swallow(event: MouseEvent) {
  if (!dragged) return
  dragged = false
  event.stopPropagation()
  event.preventDefault()
}
const typing = (target: EventTarget | null) =>
  !!(target as Element | null)?.closest(
    'input, textarea, select, [contenteditable]',
  )
function key(event: KeyboardEvent) {
  if (props.editable ? typing(event.target) : event.target !== root.value)
    return
  const command = event.ctrlKey || event.metaKey
  const name = event.key.toLowerCase()
  if (props.editable) {
    if (event.key === ' ') {
      spaceHeld.value = true
      event.preventDefault()
      return
    }
    const commands: Record<string, CanvasCommand> = {
      d: 'duplicate',
      c: 'copy',
      v: 'paste',
      y: 'redo',
    }
    if (command && name === 'a') {
      emit('update:selected', [...movable.value])
      event.preventDefault()
      return
    }
    if (command && name === 'z') {
      emit('command', event.shiftKey ? 'redo' : 'undo')
      event.preventDefault()
      return
    }
    if (command && commands[name]) {
      emit('command', commands[name]!)
      event.preventDefault()
      return
    }
    if (command || event.altKey) return
    if (name === 'v' || name === 'h') {
      emit('update:tool', name === 'v' ? 'select' : 'hand')
      return
    }
    if (
      (event.key === 'Delete' || event.key === 'Backspace') &&
      props.selected.length
    ) {
      emit('command', 'remove')
      event.preventDefault()
      return
    }
    if (event.key === 'Escape' && props.selected.length) {
      emit('update:selected', [])
      return
    }
  } else if (command || event.altKey) return
  const arrows: Record<string, [number, number]> = {
    ArrowLeft: [-1, 0],
    ArrowRight: [1, 0],
    ArrowUp: [0, -1],
    ArrowDown: [0, 1],
  }
  const by = arrows[event.key]
  if (by && props.editable && props.selected.length) {
    // Arrow keys nudge the selection; without one they pan.
    const step = event.shiftKey ? 50 : 10
    emit('move', [...props.selected], by[0] * step, by[1] * step)
  } else if (by)
    moved({
      ...view.value,
      x: view.value.x - by[0] * 80,
      y: view.value.y - by[1] * 80,
    })
  else if (event.key === '+' || event.key === '=') zoomBy(1.25)
  else if (event.key === '-') zoomBy(0.8)
  else if (event.key === '0') frame([])
  else return
  event.preventDefault()
}
function keyUp(event: KeyboardEvent) {
  if (event.key !== ' ' || !spaceHeld.value) return
  spaceHeld.value = false
  event.preventDefault()
}

let observer: ResizeObserver | undefined
onMounted(() => {
  root.value?.addEventListener('wheel', wheel, { passive: false })
  observer = new ResizeObserver(() => {
    if (!root.value) return
    const next = {
      width: root.value.clientWidth,
      height: root.value.clientHeight,
    }
    const resized =
      next.width !== size.value.width || next.height !== size.value.height
    size.value = next
    const bar = overlay.value?.offsetHeight ?? 0
    reserved.value = { top: bar ? bar + 10 : 0, bottom: 52 }
    // A settings bar appearing over an editable canvas must not move what is being edited.
    if (!ready.value || (framed && (resized || !props.editable)))
      frame(framed ?? props.focus)
  })
  if (root.value) observer.observe(root.value)
  if (overlay.value) observer.observe(overlay.value)
})
onUnmounted(() => {
  root.value?.removeEventListener('wheel', wheel)
  observer?.disconnect()
})
/** The world point at the middle of the visible canvas (where new things are put). */
function worldCentre() {
  return {
    x: (size.value.width / 2 - view.value.x) / view.value.scale,
    y: (size.value.height / 2 - view.value.y) / view.value.scale,
  }
}
defineExpose({ frame, worldCentre })
</script>

<template>
  <div
    ref="root"
    class="ic"
    :class="{
      panning,
      editable,
      hand: editable && hand,
    }"
    role="region"
    :aria-label="label"
    tabindex="0"
    data-testid="canvas"
    :data-tool="editable ? (hand ? 'hand' : 'select') : undefined"
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
    @keyup="keyUp"
    @blur.capture="spaceHeld = false"
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
        :class="{
          movable: editable && item.movable,
          selected: editable && selectedSet.has(item.key),
        }"
        :data-key="item.key"
        :style="{
          left: `${item.rect.x}px`,
          top: `${item.rect.y}px`,
          width: `${sizeOf(item).width}px`,
          height: `${sizeOf(item).height}px`,
          transform: dragging.has(item.key)
            ? `translate(${offset.x}px, ${offset.y}px)`
            : undefined,
        }"
        @dblclick="emit('preview', item.key)"
      >
        <slot :item="item" :near="seen.has(item.key)" />
      </div>
      <div
        v-if="handled && !dragging.size"
        class="ic-handle"
        data-testid="canvas-resize"
        aria-hidden="true"
        :style="{
          left: `${handled.rect.x + sizeOf(handled).width}px`,
          top: `${handled.rect.y + sizeOf(handled).height}px`,
        }"
      ></div>
    </div>
    <div
      v-if="box"
      class="ic-box"
      data-testid="canvas-box"
      :style="{
        left: `${box.x}px`,
        top: `${box.y}px`,
        width: `${box.width}px`,
        height: `${box.height}px`,
      }"
    ></div>
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
