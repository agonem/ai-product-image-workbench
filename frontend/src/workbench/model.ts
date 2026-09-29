export type Feature = 'GIFT' | 'SCENE' | 'SELLING_POINT'

export interface Box {
  x: number
  y: number
  width: number
  height: number
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
export interface TextSpec {
  title?: string
  points?: string[]
  color: string
  size: number
  align: 'left' | 'center' | 'right'
  box: Box
}
/** v4 task detail: the base task plus frozen output, submitted inputs and model outputs. */
export interface Generation extends Task {
  output?: {
    aspect_ratio: string
    width: number
    height: number
    format: string
    count: number
  }
  request?: Record<string, unknown> & { text?: TextSpec }
  source?: { task_id: string; ordinal: number }
  bases?: { id: string; width: number; height: number }[]
  review_status?: string
}
export interface HistoryItem {
  task: Task
  test_fixture: boolean
  real_scene?: boolean
  generation_v4?: boolean
}
export interface Page<T> {
  items: T[]
  next_offset: number | null
}
export interface Style {
  id: string
  name: string
  title_color: string
  badge_color: string
  badge_text_color: string
  accent_color: string
}
export interface GenerationOptions {
  enabled: boolean
  max_count: number
  max_side: number
  max_pixels: number
  presets_version: string
  aspect_ratios: string[]
  formats: string[]
  scene_presets: { id: string; name: string }[]
  styles: Style[]
}
export interface Options {
  mode: 'development-only' | 'production-local'
  generation_available: false
  generation?: GenerationOptions
}

// An ambiguous network result must retain exactly the same request and key.
export class Submission {
  pending: { key: string; path: string; body: Record<string, unknown> } | null =
    null
  prepare(path: string, body: Record<string, unknown>) {
    this.pending ??= {
      key: crypto.randomUUID(),
      path,
      body: structuredClone(body),
    }
    return this.pending
  }
  resolve() {
    this.pending = null
  }
}

export const statusLabels: Record<Task['status'], string> = {
  QUEUED: '排队中',
  RUNNING: '生成中',
  FAILED: '生成失败',
  SUCCEEDED: '已完成 · 待人工审核',
}
