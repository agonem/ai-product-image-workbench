<script setup lang="ts">
import { computed, ref } from 'vue'
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
}>()
const mode = defineModel<'plan' | 'result'>('mode', { required: true })
const compare = defineModel<boolean>('compare', { required: true })
const box = defineModel<Box>('box', { required: true })
const emit = defineEmits<{ apply: []; moved: []; retry: [] }>()

const hasText = computed(() => props.feature !== 'SCENE')
const textOn = ref(true),
  zoom = ref(1),
  split = ref(50)
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
  if (props.feature === 'GIFT')
    return side === 'center'
      ? { left: 30, top: 40, width: 40, height: 52 }
      : { left: side === 'left' ? 46 : 14, top: 24, width: 40, height: 58 }
  return side === 'center'
    ? { left: 29, top: 42, width: 42, height: 52 }
    : { left: side === 'left' ? 52 : 6, top: 22, width: 42, height: 60 }
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
// Same proportions as the Worker's typesetting (points 0.55 × title); approximate.
const titleEm = computed(
  () => `${((props.text?.size ?? 56) / Math.max(64, props.width)) * 100}cqw`,
)
const pointEm = computed(
  () =>
    `${((props.text?.size ?? 56) * 0.55 * 100) / Math.max(64, props.width)}cqw`,
)

let drag: { mode: 'move' | 'resize'; x: number; y: number; start: Box } | null =
  null
function down(kind: 'move' | 'resize', event: PointerEvent) {
  if (props.disabled || !textOn.value) return
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
  box.value =
    drag.mode === 'move'
      ? {
          ...start,
          x: round(Math.max(0, Math.min(1 - start.width, start.x + dx))),
          y: round(Math.max(0, Math.min(1 - start.height, start.y + dy))),
        }
      : {
          ...start,
          width: round(Math.max(0.12, Math.min(1 - start.x, start.width + dx))),
          height: round(
            Math.max(0.08, Math.min(1 - start.y, start.height + dy)),
          ),
        }
  emit('moved')
}
function up() {
  drag = null
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
  <div class="stage" :class="{ edit: hasText && textOn && !disabled }">
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
          v-if="hasText"
          type="button"
          class="tool"
          :aria-pressed="textOn"
          title="显示并编辑文字框"
          @click="textOn = !textOn"
        >
          <LineIcon name="text" /><span class="label">文字框</span>
        </button>
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
        <template v-else-if="!showResult">
          <div class="zone" :style="pct(productZone)">商品</div>
          <div v-if="feature === 'GIFT'" class="zone" :style="pct(giftZone)">
            赠品
          </div>
        </template>
        <div
          v-if="hasText && (text || (!showResult && textOn))"
          v-show="textOn || showResult"
          class="textbox"
          data-testid="text-layer"
          :style="layerStyle"
          @pointerdown="down('move', $event)"
          @pointermove="move"
          @pointerup="up"
          @pointercancel="up"
        >
          <template v-if="text">
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
          </template>
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
