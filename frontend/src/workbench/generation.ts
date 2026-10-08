import { validateContract } from '../contracts/validate.ts'
import type { Box, Feature, TextSpec } from './model.ts'

export const features: {
  id: Feature
  route: string
  no: string
  name: string
  lines: string[]
  tone: 'gift' | 'scene' | 'selling'
}[] = [
  {
    id: 'GIFT',
    route: 'gift',
    no: '01',
    name: '赠品主图',
    lines: ['商品与赠品同框，赠品位置可选', '背景可保持原图、纯色或按描述生成'],
    tone: 'gift',
  },
  {
    id: 'SCENE',
    route: 'scene',
    no: '02',
    name: '场景主图',
    lines: ['把商品放进真实使用场景', '支持预设场景与补充描述'],
    tone: 'scene',
  },
  {
    id: 'SELLING_POINT',
    route: 'selling',
    no: '03',
    name: '卖点主图',
    lines: ['每条卖点生成一张，标题共用', '可选风格，或保持原图直接加字'],
    tone: 'selling',
  },
]
export const featureByRoute = (route: string) =>
  features.find((item) => item.route === route)
export const featureName = (id: Feature) =>
  features.find((item) => item.id === id)!.name

// Convenience sizes only; none is claimed to be a marketplace rule (D-01).
export const canvasSizes = [
  { label: '800 × 800', ratio: '1:1', width: 800, height: 800 },
  { label: '750 × 1000', ratio: '3:4', width: 750, height: 1000 },
  { label: '1000 × 750', ratio: '4:3', width: 1000, height: 750 },
  { label: '720 × 1280', ratio: '9:16', width: 720, height: 1280 },
  { label: '1280 × 720', ratio: '16:9', width: 1280, height: 720 },
  { label: '800 × 1200', ratio: '2:3', width: 800, height: 1200 },
  { label: '1200 × 800', ratio: '3:2', width: 1200, height: 800 },
]
export const giftPositions = [
  { id: 'BOTTOM_RIGHT', name: '右下' },
  { id: 'BOTTOM_LEFT', name: '左下' },
  { id: 'RIGHT', name: '右侧' },
  { id: 'LEFT', name: '左侧' },
]
/** Gift card (ADR-20261008-H): card width as a share of the output width. */
export const giftCardSizes = [
  { id: 'S', name: '小', share: 0.22 },
  { id: 'M', name: '中', share: 0.28 },
  { id: 'L', name: '大', share: 0.34 },
] as const
export type GiftCardSize = (typeof giftCardSizes)[number]['id']
/** Where the model puts the product on the selling page; AUTO keeps away from the text. */
export const productPositions = [
  { id: 'AUTO', name: '自动' },
  { id: 'LEFT', name: '左侧' },
  { id: 'CENTER', name: '居中' },
  { id: 'RIGHT', name: '右侧' },
] as const
export type ProductPosition = (typeof productPositions)[number]['id']

/** Card rectangle in output pixels; the same rules as the Worker (image_service/giftcard.py). */
export function giftCardBox(
  size: GiftCardSize,
  label: boolean,
  width: number,
  height: number,
  position: string,
) {
  const share = giftCardSizes.find((item) => item.id === size)!.share
  const cw = Math.max(24, Math.round(share * width))
  const pad = Math.max(2, Math.round(cw * 0.08))
  const top = Math.max(3, Math.round(cw * 0.12))
  const imageHeight = Math.round(cw * 0.62)
  const labelHeight = label ? Math.round(cw * 0.2) : 0
  const ch = top + imageHeight + labelHeight + pad
  const margin = Math.round(0.04 * Math.min(width, height))
  const x =
    position === 'LEFT' || position === 'BOTTOM_LEFT'
      ? margin
      : width - margin - cw
  const y = position.startsWith('BOTTOM')
    ? height - margin - ch
    : Math.floor((height - ch) / 2)
  return {
    x,
    y,
    width: cw,
    height: ch,
    pad,
    top,
    imageHeight,
    labelHeight,
    badge: Math.max(3, Math.round(cw * 0.1)),
    corner: Math.max(2, Math.round(cw * 0.12)),
  }
}

export type Zone = { left: number; top: number; width: number; height: number }
/** Layout guide for the selling product (percent of the canvas); the model composes. */
export function sellingProductZone(
  position: ProductPosition,
  textAlign: 'left' | 'center' | 'right',
): Zone {
  if (position === 'LEFT') return { left: 6, top: 22, width: 42, height: 60 }
  if (position === 'RIGHT') return { left: 52, top: 22, width: 42, height: 60 }
  if (position === 'CENTER') return { left: 29, top: 26, width: 42, height: 60 }
  return textAlign === 'center'
    ? { left: 29, top: 42, width: 42, height: 52 }
    : { left: textAlign === 'left' ? 52 : 6, top: 22, width: 42, height: 60 }
}
/** Share of a zone (percent units) covered by the text box (canvas shares). */
export function zoneOverlap(zone: Zone, box: Box) {
  const left = Math.max(zone.left, box.x * 100)
  const right = Math.min(zone.left + zone.width, (box.x + box.width) * 100)
  const top = Math.max(zone.top, box.y * 100)
  const bottom = Math.min(zone.top + zone.height, (box.y + box.height) * 100)
  if (right <= left || bottom <= top) return 0
  return ((right - left) * (bottom - top)) / (zone.width * zone.height)
}

export const backgrounds = [
  { color: '#FFFFFF', name: '纯白' },
  { color: '#FFF6EC', name: '奶油' },
  { color: '#FDE8EA', name: '柔粉' },
  { color: '#EAF3FF', name: '天蓝' },
  { color: '#EAF6EC', name: '薄荷' },
  { color: '#F4F0E8', name: '燕麦' },
]
export const textColors = [
  { color: '#4A2E1F', name: '深棕' },
  { color: '#1E3A5F', name: '深蓝' },
  { color: '#C8573A', name: '橙红' },
  { color: '#FFFFFF', name: '白色' },
]
/** Title size as a share of the output width, so a level looks alike at every size. */
export const textLevels = [
  { name: '小', share: 0.055 },
  { name: '中', share: 0.07 },
  { name: '大', share: 0.09 },
]
export type TextPosition = 'TL' | 'TC' | 'TR'
export const textPositions: { id: TextPosition; name: string }[] = [
  { id: 'TL', name: '左上' },
  { id: 'TC', name: '居中' },
  { id: 'TR', name: '右上' },
]
const alignOf = { TL: 'left', TC: 'center', TR: 'right' } as const
const round = (value: number) => Math.round(value * 1000) / 1000

/** Starting text area for a position; the box stays draggable afterwards. */
export function presetBox(feature: Feature, position: TextPosition): Box {
  const selling = feature === 'SELLING_POINT'
  if (position === 'TC')
    return selling
      ? { x: 0.2, y: 0.05, width: 0.6, height: 0.36 }
      : { x: 0.21, y: 0.05, width: 0.58, height: 0.34 }
  const width = selling ? 0.42 : 0.46
  const x = position === 'TL' ? (selling ? 0.06 : 0.05) : 1 - width - 0.05
  return selling
    ? { x: round(x), y: 0.1, width, height: 0.6 }
    : { x: round(x), y: 0.06, width, height: 0.44 }
}

export interface GenerationDraft {
  product: string
  gift: string
  /** Chosen model id; empty means the admin's default (or none configured). */
  model: string
  size: number
  count: number
  giftPosition: string
  /** ORIGINAL keeps the product photo's own background (ADR-20260930-E). */
  backgroundMode: 'ORIGINAL' | 'SOLID' | 'CUSTOM'
  backgroundColor: string
  backgroundPrompt: string
  /** Gift shown in a program-drawn card (ADR-20261008-H). */
  giftCard: boolean
  giftCardSize: GiftCardSize
  /** Optional words under the gift in the card (text content, not kept in templates). */
  giftLabel: string
  scenePreset: string
  scenePrompt: string
  /** Selling points use one style (the first entry); ADR-20261008-G. */
  styles: string[]
  /** Selling points: no model call, the text goes on the product image itself. */
  keepOriginal: boolean
  productPosition: ProductPosition
  title: string
  points: string
  textColor: string
  textLevel: number
  /** Last chosen preset; empty once the box was dragged or resized. */
  textPosition: TextPosition | ''
  textAlign: 'left' | 'center' | 'right'
  textBox: Box
}

export function newDraft(feature: Feature = 'GIFT'): GenerationDraft {
  return {
    product: '',
    gift: '',
    model: '',
    size: 0,
    count: 1,
    giftPosition: 'BOTTOM_RIGHT',
    backgroundMode: 'SOLID',
    backgroundColor: '#FFFFFF',
    backgroundPrompt: '',
    giftCard: false,
    giftCardSize: 'M',
    giftLabel: '',
    scenePreset: 'nursery',
    scenePrompt: '',
    styles: ['warm'],
    keepOriginal: false,
    productPosition: 'AUTO',
    title: '',
    points: '',
    textColor: '#4A2E1F',
    textLevel: 1,
    textPosition: 'TL',
    textAlign: 'left',
    textBox: presetBox(feature, 'TL'),
  }
}

export function placeText(
  feature: Feature,
  draft: GenerationDraft,
  position: TextPosition,
) {
  draft.textPosition = position
  draft.textAlign = alignOf[position]
  draft.textBox = presetBox(feature, position)
}

/** Manual text is used verbatim; blank lines are dropped, nothing is rewritten. */
export function pointLines(draft: GenerationDraft) {
  return draft.points.split('\n').filter((line) => line.trim())
}

export function titleSize(draft: GenerationDraft, width: number) {
  const share = (textLevels[draft.textLevel] ?? textLevels[1]!).share
  return Math.min(240, Math.max(12, Math.round(share * width)))
}

export function textSpec(
  draft: GenerationDraft,
  width = canvasSizes[draft.size]!.width,
): TextSpec | null {
  const points = pointLines(draft)
  const title = draft.title.trim() ? draft.title : undefined
  if (!title && !points.length) return null
  return {
    ...(title ? { title } : {}),
    ...(points.length ? { points } : {}),
    color: draft.textColor,
    size: titleSize(draft, width),
    align: draft.textAlign,
    box: { ...draft.textBox },
  }
}

/** Nothing is generated by a model: the product image itself is the picture. */
export function callsNoModel(feature: Feature, draft: GenerationDraft) {
  return feature === 'SELLING_POINT'
    ? draft.keepOriginal
    : feature === 'GIFT' &&
        draft.giftCard &&
        draft.backgroundMode === 'ORIGINAL'
}

/** One selling image's text: the shared title and point ``index`` (ADR-20261008-G). */
export function pointText(
  text: TextSpec | null,
  index: number,
): TextSpec | null {
  const points = text?.points
  if (!text || !points?.length) return text
  return { ...text, points: [points[Math.min(index, points.length - 1)]!] }
}

/** The point that needs the most room (CJK counts double), for the plan preview. */
export function widestPoint(points: string[]) {
  const width = (line: string) =>
    [...line].reduce(
      (sum, char) => sum + (/[\u2E80-\uFFEF]/.test(char) ? 1 : 0.55),
      0,
    )
  let best = 0
  points.forEach((line, index) => {
    if (width(line) > width(points[best] ?? '')) best = index
  })
  return best
}

/** Continue editing from exactly what was rendered for a result. */
export function adoptText(
  feature: Feature,
  draft: GenerationDraft,
  text: TextSpec,
  width: number,
) {
  const share = text.size / Math.max(1, width)
  let level = 0
  textLevels.forEach((item, index) => {
    if (
      Math.abs(item.share - share) < Math.abs(textLevels[level]!.share - share)
    )
      level = index
  })
  const match = textPositions.find((item) => {
    const box = presetBox(feature, item.id)
    return (
      alignOf[item.id] === text.align &&
      (['x', 'y', 'width', 'height'] as const).every(
        (key) => Math.abs(box[key] - text.box[key]) < 0.001,
      )
    )
  })
  Object.assign(draft, {
    title: text.title ?? '',
    points: (text.points ?? []).join('\n'),
    textColor: text.color,
    textLevel: level,
    textPosition: match?.id ?? '',
    textAlign: text.align,
    textBox: { ...text.box },
  })
}

export function buildGeneration(
  feature: Feature,
  project: string,
  draft: GenerationDraft,
): Record<string, unknown> {
  if (!draft.product) throw new Error('请先选择或上传商品图。')
  if (feature === 'GIFT' && !draft.gift)
    throw new Error('请先选择或上传赠品图。')
  if (feature === 'SCENE' && !draft.scenePreset && !draft.scenePrompt.trim())
    throw new Error('请选择场景或填写场景描述。')
  if (feature === 'SELLING_POINT') {
    if (!draft.keepOriginal && !draft.styles.length)
      throw new Error('请选择一种风格或“保持原图”。')
    if (!pointLines(draft).length)
      throw new Error('请输入至少一条卖点（每行一条）。')
  }
  const box = draft.textBox
  if (
    feature === 'SELLING_POINT' &&
    (box.x + box.width > 1.000001 || box.y + box.height > 1.000001)
  )
    throw new Error('文字区域必须在画布范围内。')
  const size = canvasSizes[draft.size]!
  const value: Record<string, unknown> = {
    project_id: project,
    feature_type: feature,
    product_asset_id: draft.product,
    output: {
      aspect_ratio: size.ratio,
      width: size.width,
      height: size.height,
      // The pages offer PNG only (ADR-20260929-C); the contract still accepts JPEG.
      format: 'png',
      // Selling points: one image per point (ADR-20261008-G).
      count:
        feature === 'SELLING_POINT' ? pointLines(draft).length : draft.count,
    },
  }
  const original = feature === 'SELLING_POINT' && draft.keepOriginal
  // Keep-original images call no model, so none is chosen.
  if (draft.model && !callsNoModel(feature, draft)) value.model_id = draft.model
  if (feature === 'GIFT') {
    // The gift page carries no text since ADR-20261008-G; text is added on the selling page.
    value.gift_asset_id = draft.gift
    value.gift_position = draft.giftPosition
    value.background =
      draft.backgroundMode === 'CUSTOM'
        ? { mode: 'CUSTOM', prompt: draft.backgroundPrompt }
        : draft.backgroundMode === 'ORIGINAL'
          ? { mode: 'ORIGINAL' }
          : { mode: 'SOLID', color: draft.backgroundColor }
    if (draft.giftCard) {
      const label = draft.giftLabel.trim()
      if ([...label].length > 10) throw new Error('方框文字最多 10 个字。')
      value.gift_card = {
        size: draft.giftCardSize,
        ...(label ? { label } : {}),
      }
    }
  } else if (feature === 'SCENE') {
    if (draft.scenePreset) value.scene_preset = draft.scenePreset
    if (draft.scenePrompt.trim()) value.scene_prompt = draft.scenePrompt
  } else {
    if (original) value.keep_original = true
    else {
      value.style = draft.styles[0]
      if (draft.productPosition !== 'AUTO')
        value.product_position = draft.productPosition
    }
    value.text = textSpec(draft, size.width)
  }
  if (validateContract('generation-v4-create', value).length)
    throw new Error(
      '请检查输入：标题不超过 60 字、卖点每条不超过 20 字且最多 6 条、描述不超过 300 字。',
    )
  return value
}
