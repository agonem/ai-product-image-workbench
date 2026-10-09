<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { giftCardBox, sellingProductZone } from '../workbench/generation'
import type { GiftCardSize, ProductPosition } from '../workbench/generation'
import type { Box, Feature, TextSpec } from '../workbench/model'
import PrivateImage from '../workbench/PrivateImage.vue'
import DropSelect from './DropSelect.vue'
import LineIcon from './LineIcon.vue'

type Zone = { left: number; top: number; width: number; height: number }
const props = defineProps<{
  feature: Feature
  width: number
  height: number
  /** Result layer (model output under the text, or the final image for scenes). */
  image: string | null
  /** Plan layer: the product image itself when no model is called. */
  backdrop?: string | null
  /** Gift card preview on the gift page (ADR-20261008-H). */
  giftCard?: {
    size: GiftCardSize
    label: string
    gift: string
    white: boolean
  } | null
  /** Selling page: where the model is asked to put the product. */
  productPosition?: ProductPosition
  imageAlt: string
  text: TextSpec | null
  textAlign: 'left' | 'center' | 'right'
  palette: { badge: string; badgeText: string; accent: string }
  product: string
  gift: string
  giftPosition: string
  hasResult: boolean
  generating: boolean
  failure: { message: string; code: string } | null
  canApply: boolean
  disabled: boolean
  api: <T>(path: string, init?: RequestInit) => Promise<T>
  /** Undo/redo live in the page (they cover every setting); the canvas offers the buttons. */
  canUndo?: boolean
  canRedo?: boolean
}>()
const mode = defineModel<'plan' | 'result'>('mode', { required: true })
const compare = defineModel<boolean>('compare', { required: true })
const box = defineModel<Box>('box', { required: true })
const emit = defineEmits<{
  apply: []
  moved: []
  retry: []
  overflow: [value: boolean]
  undo: []
  redo: []
}>()

const hasText = computed(() => props.feature === 'SELLING_POINT')
const textOn = ref(true),
  zoom = ref(1),
  split = ref(50)
// Layers (ADR-20260930-F): the text can be hidden or locked; guides and layout zones toggle.
const layers = ref({ locked: false, zones: true, guides: false })
const layerMenu = ref(false),
  layerRoot = ref<HTMLElement>()
function outsideLayers(event: PointerEvent) {
  if (!layerRoot.value?.contains(event.target as Node)) layerMenu.value = false
}
watch(layerMenu, (open) =>
  open
    ? document.addEventListener('pointerdown', outsideLayers, true)
    : document.removeEventListener('pointerdown', outsideLayers, true),
)
// Snap lines shown while the text box is dragged (share of the canvas; null = none).
const snap = ref<{ x: number | null; y: number | null }>({ x: null, y: null })
const SNAP_TARGETS = [0.05, 0.5, 0.95]
const SNAP_DISTANCE = 0.012
/** Moves a span so one of its edges or its centre lands on a guide when close enough. */
function snapSpan(
  start: number,
  size: number,
): { value: number; line: number | null } {
  let best: { shift: number; line: number } | null = null
  for (const edge of [start, start + size / 2, start + size])
    for (const target of SNAP_TARGETS) {
      const shift = target - edge
      if (
        Math.abs(shift) < SNAP_DISTANCE &&
        (!best || Math.abs(shift) < Math.abs(best.shift))
      )
        best = { shift, line: target }
    }
  return best
    ? { value: start + best.shift, line: best.line }
    : { value: start, line: null }
}
/** Snaps the far edge of a span (resizing). */
function snapEdge(
  start: number,
  size: number,
): { value: number; line: number | null } {
  for (const target of SNAP_TARGETS)
    if (Math.abs(start + size - target) < SNAP_DISTANCE)
      return { value: target - start, line: target }
  return { value: size, line: null }
}
const board = ref<HTMLElement>()
const showResult = computed(() => mode.value === 'result' && props.hasResult)
const zooms = [
  { value: 1, label: '适应画布' },
  { value: 1.25, label: '125%' },
  { value: 1.5, label: '150%' },
]
const pct = (zone: Zone) => ({
  left: `${zone.left}%`,
  top: `${zone.top}%`,
  width: `${zone.width}%`,
  height: `${zone.height}%`,
})

// Layout guide only: the model composes the picture; nothing here is a preview of it.
const productZone = computed<Zone>(() => {
  const side = props.textAlign
  if (props.feature === 'SCENE')
    return { left: 28, top: 18, width: 44, height: 66 }
  // The gift page has no text (ADR-20261008-G).
  if (props.feature === 'GIFT')
    return { left: 18, top: 14, width: 50, height: 60 }
  return sellingProductZone(props.productPosition ?? 'AUTO', side)
})
// Same geometry as the Worker's card, in percent of the canvas.
const card = computed(() => {
  if (!props.giftCard) return null
  const box = giftCardBox(
    props.giftCard.size,
    !!props.giftCard.label,
    props.width,
    props.height,
    props.giftPosition,
  )
  const w = (value: number) => `${(value / props.width) * 100}%`
  const h = (value: number) => `${(value / props.height) * 100}%`
  return {
    frame: {
      left: w(box.x),
      top: h(box.y),
      width: w(box.width),
      height: h(box.height),
      borderRadius: `${(box.corner / box.width) * 100}% / ${(box.corner / box.height) * 100}%`,
    },
    picture: {
      left: `${(box.pad / box.width) * 100}%`,
      right: `${(box.pad / box.width) * 100}%`,
      top: `${(box.top / box.height) * 100}%`,
      height: `${(box.imageHeight / box.height) * 100}%`,
    },
    label: {
      top: `${((box.top + box.imageHeight) / box.height) * 100}%`,
      height: `${(box.labelHeight / box.height) * 100}%`,
      fontSize: `${(Math.round(box.width * 0.11) / props.width) * 100}cqw`,
    },
    badge: {
      width: `${((2 * box.badge) / box.width) * 100}%`,
    },
  }
})
const giftZone = computed<Zone>(() => {
  const [left, top] = {
    BOTTOM_RIGHT: [72, 72],
    BOTTOM_LEFT: [6, 72],
    RIGHT: [74, 40],
    LEFT: [4, 40],
  }[props.giftPosition] ?? [72, 72]
  return { left: left!, top: top!, width: 22, height: 22 }
})
const originals = computed(() =>
  props.gift
    ? {
        product: { left: 6, top: 10, width: 60, height: 80 },
        gift: { left: 68, top: 50, width: 26, height: 36 },
      }
    : { product: { left: 12, top: 10, width: 76, height: 80 }, gift: null },
)

const layerStyle = computed(() => ({
  left: `${box.value.x * 100}%`,
  top: `${box.value.y * 100}%`,
  width: `${box.value.width * 100}%`,
  height: `${box.value.height * 100}%`,
  textAlign: props.textAlign,
  justifyItems:
    props.textAlign === 'center'
      ? 'center'
      : props.textAlign === 'right'
        ? 'end'
        : 'start',
}))
// Same rules as the Worker's typesetting: points are 0.55 × the title, nothing wraps, and the
// whole block shrinks until it fits its box; below a 12px title the server refuses
// (TEXT_OVERFLOW, after the paid model call), so the page warns first. Browser fonts differ
// slightly from the deployment font, so this is an approximation.
const layer = ref<HTMLElement>(),
  content = ref<HTMLElement>()
const fit = ref(1),
  overflow = ref(false)
function measure() {
  const block = content.value,
    frame = layer.value
  if (!block || !frame || !props.text) {
    fit.value = 1
    overflow.value = false
    return
  }
  const naturalWidth = block.offsetWidth / fit.value,
    naturalHeight = block.offsetHeight / fit.value
  if (!naturalWidth || !naturalHeight || !frame.clientWidth) return
  const next = Math.min(
    1,
    frame.clientWidth / naturalWidth,
    frame.clientHeight / naturalHeight,
  )
  const minimum = 12 / Math.max(12, props.text.size)
  overflow.value = next < minimum
  const value = Math.max(next, minimum)
  if (Math.abs(value - fit.value) > 0.004) fit.value = value
}
const remeasure = () => void nextTick(measure)
watch(() => [props.text, box.value, props.width, zoom.value], remeasure)
watch(overflow, (value) => emit('overflow', value))
let observer: ResizeObserver | undefined
onMounted(() => {
  observer = new ResizeObserver(remeasure)
  if (board.value) observer.observe(board.value)
  void document.fonts?.ready.then(remeasure)
})
onUnmounted(() => {
  document.removeEventListener('pointerdown', outsideLayers, true)
  observer?.disconnect()
  emit('overflow', false)
})
const titleEm = computed(
  () =>
    `${((props.text?.size ?? 56) * fit.value * 100) / Math.max(64, props.width)}cqw`,
)
const pointEm = computed(
  () =>
    `${((props.text?.size ?? 56) * 0.55 * fit.value * 100) / Math.max(64, props.width)}cqw`,
)

let drag: { mode: 'move' | 'resize'; x: number; y: number; start: Box } | null =
  null
function down(kind: 'move' | 'resize', event: PointerEvent) {
  if (props.disabled || !textOn.value || layers.value.locked) return
  event.stopPropagation()
  drag = {
    mode: kind,
    x: event.clientX,
    y: event.clientY,
    start: { ...box.value },
  }
  ;(event.currentTarget as HTMLElement).setPointerCapture(event.pointerId)
}
function move(event: PointerEvent) {
  if (!drag || !board.value) return
  const bounds = board.value.getBoundingClientRect()
  const dx = (event.clientX - drag.x) / bounds.width
  const dy = (event.clientY - drag.y) / bounds.height
  if (!dx && !dy) return
  const start = drag.start
  const round = (value: number) => Math.round(value * 1000) / 1000
  if (drag.mode === 'move') {
    const x = snapSpan(
      Math.max(0, Math.min(1 - start.width, start.x + dx)),
      start.width,
    )
    const y = snapSpan(
      Math.max(0, Math.min(1 - start.height, start.y + dy)),
      start.height,
    )
    snap.value = { x: x.line, y: y.line }
    box.value = {
      ...start,
      x: round(Math.max(0, Math.min(1 - start.width, x.value))),
      y: round(Math.max(0, Math.min(1 - start.height, y.value))),
    }
  } else {
    const width = snapEdge(
      start.x,
      Math.max(0.12, Math.min(1 - start.x, start.width + dx)),
    )
    const height = snapEdge(
      start.y,
      Math.max(0.08, Math.min(1 - start.y, start.height + dy)),
    )
    snap.value = { x: width.line, y: height.line }
    box.value = {
      ...start,
      width: round(Math.max(0.12, Math.min(1 - start.x, width.value))),
      height: round(Math.max(0.08, Math.min(1 - start.y, height.value))),
    }
  }
  emit('moved')
}
function up() {
  drag = null
  snap.value = { x: null, y: null }
}
function slide(event: PointerEvent) {
  if (!board.value || (event.type === 'pointermove' && !event.buttons)) return
  if (event.type === 'pointerdown')
    (event.currentTarget as HTMLElement).setPointerCapture(event.pointerId)
  const bounds = board.value.getBoundingClientRect()
  split.value = Math.round(
    Math.max(
      4,
      Math.min(96, ((event.clientX - bounds.left) / bounds.width) * 100),
    ),
  )
}
function nudge(event: KeyboardEvent) {
  if (event.key === 'ArrowLeft') split.value = Math.max(4, split.value - 5)
  if (event.key === 'ArrowRight') split.value = Math.min(96, split.value + 5)
}
</script>

<template>
  <div
    class="stage"
    :class="{ edit: hasText && textOn && !disabled && !layers.locked }"
  >
    <div class="stage-bar">
      <div class="seg" role="group" aria-label="画布内容">
        <button
          type="button"
          :aria-pressed="!showResult"
          @click="((mode = 'plan'), (compare = false))"
        >
          构图预览
        </button>
        <button
          type="button"
          :aria-pressed="showResult"
          :disabled="!hasResult"
          @click="mode = 'result'"
        >
          生成结果
        </button>
      </div>
      <div class="tools">
        <button
          type="button"
          class="tool icon-only"
          aria-label="撤销"
          title="撤销（Ctrl+Z）"
          :disabled="!canUndo"
          @click="emit('undo')"
        >
          <LineIcon name="undo" />
        </button>
        <button
          type="button"
          class="tool icon-only"
          aria-label="重做"
          title="重做（Ctrl+Y）"
          :disabled="!canRedo"
          @click="emit('redo')"
        >
          <LineIcon name="redo2" />
        </button>
        <button
          v-if="hasText"
          type="button"
          class="tool"
          :aria-pressed="textOn"
          title="显示并编辑文字框"
          @click="textOn = !textOn"
        >
          <LineIcon name="text" /><span class="label">文字框</span>
        </button>
        <div
          ref="layerRoot"
          class="dd layer-menu"
          @keydown.esc="layerMenu = false"
        >
          <button
            type="button"
            class="tool"
            aria-haspopup="true"
            :aria-expanded="layerMenu"
            title="图层与参考线"
            @click="layerMenu = !layerMenu"
          >
            <LineIcon name="layers" /><span class="label">图层</span>
          </button>
          <div v-if="layerMenu" class="menu" role="group" aria-label="图层">
            <label v-if="hasText" class="menu-item check"
              ><input v-model="textOn" type="checkbox" />显示文字</label
            >
            <label v-if="hasText" class="menu-item check"
              ><input
                v-model="layers.locked"
                type="checkbox"
              />锁定文字位置</label
            >
            <label class="menu-item check"
              ><input
                v-model="layers.zones"
                type="checkbox"
              />显示构图区域</label
            >
            <label class="menu-item check"
              ><input
                v-model="layers.guides"
                type="checkbox"
              />显示参考线</label
            >
          </div>
        </div>
        <button
          type="button"
          class="tool"
          :aria-pressed="compare && showResult"
          :disabled="!showResult || !image"
          title="拖动中间的滑块对照原图与生成结果"
          @click="compare = !compare"
        >
          <LineIcon name="cmp" /><span class="label">对照原图</span>
        </button>
        <div class="zoom">
          <DropSelect
            v-model="zoom"
            label="缩放"
            :options="zooms"
            variant="tool"
          />
        </div>
        <span class="size-label">{{ width }} × {{ height }}</span>
      </div>
    </div>
    <div class="artwrap">
      <div
        ref="board"
        class="artboard"
        data-testid="design-stage"
        :style="{
          '--ratio': `${Math.max(64, width)} / ${Math.max(64, height)}`,
          '--zoom': zoom,
        }"
      >
        <template v-if="showResult && image">
          <PrivateImage
            :key="image"
            class="base"
            :path="image"
            :alt="imageAlt"
            :api="api"
          />
        </template>
        <template v-else-if="!showResult && backdrop">
          <PrivateImage
            :key="backdrop"
            class="base"
            :path="backdrop"
            alt="商品图（保持原图）"
            :api="api"
            missing="原图已删除"
          />
        </template>
        <template v-else-if="!showResult && layers.zones">
          <div class="zone" :style="pct(productZone)">商品</div>
          <div
            v-if="feature === 'GIFT' && !card"
            class="zone"
            :style="pct(giftZone)"
          >
            赠品
          </div>
        </template>
        <div
          v-if="hasText && (text || (!showResult && textOn))"
          v-show="textOn || showResult"
          ref="layer"
          class="textbox"
          :class="{ overflow }"
          data-testid="text-layer"
          :data-overflow="overflow"
          :style="layerStyle"
          @pointerdown="down('move', $event)"
          @pointermove="move"
          @pointerup="up"
          @pointercancel="up"
        >
          <div v-if="text" ref="content" class="tb-content">
            <div
              v-if="text.title"
              class="ttl"
              :style="{ color: text.color, fontSize: titleEm }"
            >
              {{ text.title }}
            </div>
            <div
              v-if="text.points?.length"
              class="pills"
              :style="{
                fontSize: pointEm,
                alignItems:
                  textAlign === 'center'
                    ? 'center'
                    : textAlign === 'right'
                      ? 'flex-end'
                      : 'flex-start',
              }"
            >
              <span
                v-for="(point, index) in text.points"
                :key="index"
                class="pill"
                :style="{ background: palette.badge, color: palette.badgeText }"
                ><i :style="{ background: palette.accent }">✓</i
                >{{ point }}</span
              >
            </div>
          </div>
          <span v-else class="zone" style="inset: 0">文字</span>
          <span
            class="grip"
            aria-hidden="true"
            @pointerdown="down('resize', $event)"
            @pointermove="move"
            @pointerup="up"
            @pointercancel="up"
          ></span>
        </div>
        <template v-if="showResult && compare && image">
          <div
            class="original"
            data-testid="compare-original"
            :style="{ clipPath: `inset(0 ${100 - split}% 0 0)` }"
          >
            <div class="piece" :style="pct(originals.product)">
              <PrivateImage
                :path="`/assets/${product}/content`"
                alt="商品原图"
                :api="api"
                missing="原图已删除"
              />
            </div>
            <div
              v-if="originals.gift"
              class="piece"
              :style="pct(originals.gift)"
            >
              <PrivateImage
                :path="`/assets/${gift}/content`"
                alt="赠品原图"
                :api="api"
                missing="原图已删除"
              />
            </div>
            <span class="tagline">原图</span>
          </div>
          <div
            class="split"
            role="slider"
            tabindex="0"
            aria-label="对照分隔线"
            aria-valuemin="4"
            aria-valuemax="96"
            :aria-valuenow="split"
            :style="{ left: `${split}%` }"
            @pointerdown="slide"
            @pointermove="slide"
            @keydown="nudge"
          ></div>
        </template>
        <div
          v-if="card && !showResult"
          class="gift-card"
          data-testid="gift-card"
          :style="card.frame"
        >
          <span class="gc-badge" :style="card.badge" aria-hidden="true"
            ><LineIcon name="plus" :size="12"
          /></span>
          <div
            class="gc-picture"
            :class="{ white: giftCard?.white }"
            :style="card.picture"
          >
            <PrivateImage
              v-if="giftCard?.gift"
              :path="`/assets/${giftCard.gift}/content`"
              alt="赠品原图"
              :api="api"
              missing="原图已删除"
            />
            <small v-if="giftCard?.white" class="gc-note"
              >纯白·生成时 AI 重拍</small
            >
          </div>
          <span v-if="giftCard?.label" class="gc-label" :style="card.label">{{
            giftCard.label
          }}</span>
        </div>
        <div v-if="layers.guides" class="guides" aria-hidden="true">
          <i class="v" style="left: 33.333%"></i
          ><i class="v" style="left: 50%"></i
          ><i class="v" style="left: 66.667%"></i
          ><i class="h" style="top: 33.333%"></i
          ><i class="h" style="top: 50%"></i
          ><i class="h" style="top: 66.667%"></i>
          <span class="safe"></span>
        </div>
        <i
          v-if="snap.x !== null"
          class="snap v"
          data-testid="snap-line"
          :style="{ left: `${snap.x * 100}%` }"
        ></i>
        <i
          v-if="snap.y !== null"
          class="snap h"
          :style="{ top: `${snap.y * 100}%` }"
        ></i>
        <div v-if="generating && !showResult" class="generating" role="status">
          <span class="spinner"></span>正在生成…
        </div>
      </div>
      <div v-if="showResult && failure" class="failure">
        <LineIcon name="alert" />
        <strong>生成失败</strong>
        <span>{{ failure.message }}（{{ failure.code }}）</span>
        <button
          type="button"
          class="btn sm"
          :disabled="disabled"
          @click="emit('retry')"
        >
          <LineIcon name="redo" :size="14" />重试
        </button>
      </div>
      <div v-if="showResult && hasText && image" class="corner">
        <span class="note"
          >拖动虚线框调整文字位置，改完点右侧按钮，只重排文字、不重新生成。</span
        >
        <span class="spacer"></span>
        <button
          type="button"
          class="btn primary"
          :disabled="disabled || !canApply"
          @click="emit('apply')"
        >
          <LineIcon name="check" :size="14" />应用文字修改
        </button>
      </div>
    </div>
  </div>
</template>
