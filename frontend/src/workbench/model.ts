import { validateContract } from '../contracts/validate.ts'

export type Feature = 'GIFT' | 'SCENE' | 'SELLING_POINT'
export const features: { id: Feature; name: string; description: string }[] = [
  { id: 'GIFT', name: '赠品图', description: '独立赠品素材，手动调整位置' },
  { id: 'SCENE', name: '场景图', description: '选择场景预设或描述你的场景' },
  {
    id: 'SELLING_POINT',
    name: '卖点图',
    description: '人工输入卖点，每条一个候选任务内容',
  },
]
export interface Box {
  x: number
  y: number
  width: number
  height: number
}
export function newDraft() {
  return {
    product: '',
    gift: '',
    preset: '',
    template: '',
    sceneTemplate: '',
    scene: '',
    style: '',
    selling: '',
    manual: '',
    sceneOutput: {
      aspect_ratio: '1:1',
      resolution: '1K',
      format: 'png',
      count: 3,
    },
    productBox: { x: 0.1, y: 0.1, width: 0.8, height: 0.8 },
    giftBox: { x: 0.7, y: 0.7, width: 0.2, height: 0.2 },
  }
}
export type Draft = ReturnType<typeof newDraft>
export function buildRequest(
  feature: Feature,
  project: string,
  draft: Draft,
  realScene = false,
): Record<string, unknown> {
  for (const box of feature === 'GIFT'
    ? [draft.productBox, draft.giftBox]
    : [draft.productBox]) {
    if (
      Object.values(box).some((value) => !Number.isFinite(value)) ||
      box.x + box.width > 1.000001 ||
      box.y + box.height > 1.000001
    )
      throw new Error('位置与尺寸必须在画布范围内。')
  }
  const value: Record<string, unknown> = {
    project_id: project,
    product_asset_id: draft.product,
    output_preset_id: draft.preset,
    feature_type: feature,
    layout: { product: { ...draft.productBox } },
  }
  if (feature === 'GIFT')
    Object.assign(value, {
      gift_asset_id: draft.gift,
      template_version_id: draft.template,
      manual_text: draft.manual,
      layout: { product: { ...draft.productBox }, gift: { ...draft.giftBox } },
    })
  else if (feature === 'SCENE') {
    if (realScene) {
      delete value.output_preset_id
      value.output = { ...draft.sceneOutput }
    }
    if (draft.sceneTemplate)
      value.scene_template_version_id = draft.sceneTemplate
    else value.scene_custom_prompt = draft.scene
    if (draft.style.trim()) value.style_custom_prompt = draft.style
  } else
    Object.assign(value, {
      layout_template_version_id: draft.template,
      selling_points: draft.selling.split('\n').filter((line) => line.trim()),
    })
  if (
    validateContract(
      realScene && feature === 'SCENE' ? 'scene-create' : 'task-create',
      value,
    ).length
  )
    throw new Error('请补全本入口的素材、配置和文字。')
  return value
}

// An ambiguous network result must retain exactly the same request and key.
export class Submission {
  pending: { key: string; body: Record<string, unknown> } | null = null
  prepare(body: Record<string, unknown>) {
    this.pending ??= { key: crypto.randomUUID(), body: structuredClone(body) }
    return this.pending
  }
  resolve() {
    this.pending = null
  }
}

export interface Project {
  id: string
  name: string
}
export interface Asset {
  id: string
  project_id: string
  kind: 'PRODUCT' | 'GIFT'
  width: number
  height: number
  review_status: string
  cutout_ready: boolean
}
export interface Task {
  id: string
  feature_type: Feature
  status: 'QUEUED' | 'RUNNING' | 'SUCCEEDED' | 'FAILED'
  attempt: number
  created_at: string
  artifacts: { id: string; kind: string; width: number; height: number }[]
  error: { code: string; message: string; correlation_id: string } | null
}
export interface HistoryItem {
  task: Task
  test_fixture: boolean
  real_scene?: boolean
}
export interface Page<T> {
  items: T[]
  next_offset: number | null
}
export interface Options {
  mode: 'development-only' | 'production-local'
  generation_available: false
  scene?: {
    enabled: boolean
    max_count: number
    aspect_ratios: string[]
    resolutions: string[]
    formats: string[]
  }
  templates: { id: string; name: string; type: string; version: number }[]
  output_presets: { id: string; test_fixture: boolean }[]
}
export const statusLabels = {
  QUEUED: '排队中',
  RUNNING: '执行中',
  FAILED: '执行失败',
  SUCCEEDED: '开发/测试任务完成 · 非真实成品',
}
