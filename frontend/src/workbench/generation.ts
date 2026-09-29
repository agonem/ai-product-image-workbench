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
    name: '赠品+文字主图',
    lines: [
      '在商品主图中添加赠品和营销文字',
      '支持调整赠品位置、文字内容与样式',
    ],
    tone: 'gift',
  },
  {
    id: 'SCENE',
    route: 'scene',
    no: '02',
    name: '场景主图',
    lines: ['将商品放入不同场景，生成多种风格', '支持预设场景和自定义描述'],
    tone: 'scene',
  },
  {
    id: 'SELLING_POINT',
    route: 'selling',
    no: '03',
    name: '卖点主图',
    lines: ['基于同一商品生成不同卖点主图', '支持多种风格，每种风格一张'],
    tone: 'selling',
  },
]
export const featureByRoute = (route: string) =>
  features.find((item) => item.route === route)
export const featureName = (id: Feature) =>
  features.find((item) => item.id === id)!.name

// Convenience sizes only; none is claimed to be a marketplace rule (D-01).
export const canvasSizes = [
  { label: '800 × 800（1:1）', ratio: '1:1', width: 800, height: 800 },
  { label: '750 × 1000（3:4）', ratio: '3:4', width: 750, height: 1000 },
  { label: '1000 × 750（4:3）', ratio: '4:3', width: 1000, height: 750 },
  { label: '800 × 1200（2:3）', ratio: '2:3', width: 800, height: 1200 },
  { label: '1200 × 800（3:2）', ratio: '3:2', width: 1200, height: 800 },
  { label: '720 × 1280（9:16）', ratio: '9:16', width: 720, height: 1280 },
  { label: '1280 × 720（16:9）', ratio: '16:9', width: 1280, height: 720 },
]
export const giftPositions = [
  { id: 'BOTTOM_RIGHT', name: '右下' },
  { id: 'BOTTOM_LEFT', name: '左下' },
  { id: 'RIGHT', name: '右侧' },
  { id: 'LEFT', name: '左侧' },
]
export const swatches = [
  '#FFFFFF',
  '#FFF6EC',
  '#FDE8EA',
  '#EAF3FF',
  '#EAF6EC',
  '#F4F0E8',
]

export interface GenerationDraft {
  product: string
  gift: string
  size: number
  format: 'png' | 'jpeg'
  count: number
  giftPosition: string
  backgroundMode: 'SOLID' | 'GRADIENT' | 'CUSTOM'
  backgroundColor: string
  backgroundPrompt: string
  scenePreset: string
  scenePrompt: string
  stylePrompt: string
  styles: string[]
  title: string
  points: string
  textColor: string
  textSize: number
  textAlign: 'left' | 'center' | 'right'
  textBox: Box
}

export function newDraft(): GenerationDraft {
  return {
    product: '',
    gift: '',
    size: 0,
    format: 'png',
    count: 1,
    giftPosition: 'BOTTOM_RIGHT',
    backgroundMode: 'SOLID',
    backgroundColor: '#FFFFFF',
    backgroundPrompt: '',
    scenePreset: 'nursery',
    scenePrompt: '',
    stylePrompt: '',
    styles: ['warm'],
    title: '',
    points: '',
    textColor: '#4A2E1F',
    textSize: 56,
    textAlign: 'left',
    // Initial position only (top-left, like the reference); draggable on the canvas.
    textBox: { x: 0.05, y: 0.05, width: 0.46, height: 0.5 },
  }
}

/** Manual text is used verbatim; blank lines are dropped, nothing is rewritten. */
export function pointLines(draft: GenerationDraft) {
  return draft.points.split('\n').filter((line) => line.trim())
}

export function textSpec(draft: GenerationDraft): TextSpec | null {
  const points = pointLines(draft)
  const title = draft.title.trim() ? draft.title : undefined
  if (!title && !points.length) return null
  return {
    ...(title ? { title } : {}),
    ...(points.length ? { points } : {}),
    color: draft.textColor,
    size: draft.textSize,
    align: draft.textAlign,
    box: { ...draft.textBox },
  }
}

export function buildGeneration(
  feature: Feature,
  project: string,
  draft: GenerationDraft,
): Record<string, unknown> {
  if (!draft.product) throw new Error('请先上传或选择商品白底图。')
  if (feature === 'GIFT' && !draft.gift)
    throw new Error('请先上传或选择赠品图。')
  if (feature === 'SCENE' && !draft.scenePreset && !draft.scenePrompt.trim())
    throw new Error('请选择场景预设或填写场景描述。')
  if (feature === 'SELLING_POINT') {
    if (!draft.styles.length) throw new Error('请至少选择一种风格。')
    if (!pointLines(draft).length)
      throw new Error('请输入至少一条卖点（每行一条）。')
  }
  const box = draft.textBox
  if (box.x + box.width > 1.000001 || box.y + box.height > 1.000001)
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
      format: draft.format,
      count: feature === 'SELLING_POINT' ? draft.styles.length : draft.count,
    },
  }
  if (draft.stylePrompt.trim()) value.style_prompt = draft.stylePrompt
  const text = textSpec(draft)
  if (feature === 'GIFT') {
    value.gift_asset_id = draft.gift
    value.gift_position = draft.giftPosition
    value.background =
      draft.backgroundMode === 'CUSTOM'
        ? { mode: 'CUSTOM', prompt: draft.backgroundPrompt }
        : { mode: draft.backgroundMode, color: draft.backgroundColor }
    if (text) value.text = text
  } else if (feature === 'SCENE') {
    if (draft.scenePreset) value.scene_preset = draft.scenePreset
    if (draft.scenePrompt.trim()) value.scene_prompt = draft.scenePrompt
  } else {
    value.styles = [...draft.styles]
    value.text = text
  }
  if (validateContract('generation-v4-create', value).length)
    throw new Error(
      '请检查输入：标题不超过 60 字、卖点每条不超过 20 字且最多 6 条、自定义描述不超过 300 字。',
    )
  return value
}
