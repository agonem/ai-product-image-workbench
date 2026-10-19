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
/** Material categories (ADR-20261009-R); any original may fill any slot. */
export type AssetKind = 'PRODUCT' | 'GIFT' | 'REFERENCE'
export const assetKinds: { id: AssetKind; name: string }[] = [
  { id: 'PRODUCT', name: '商品图' },
  { id: 'GIFT', name: '赠品图' },
  { id: 'REFERENCE', name: '参考图' },
]
export const kindName = (kind: string) =>
  assetKinds.find((item) => item.id === kind)?.name ?? '原图'
export interface Asset {
  id: string
  project_id: string
  kind: AssetKind
  width: number
  height: number
  /** Set when the original is a copy of a generated result (ADR-20260930-E). */
  source_artifact_id?: string
}
/** Tasks also come from the conversation page (CUSTOM, ADR-20261008-I). */
export type TaskFeature = Feature | 'CUSTOM'
export interface Task {
  id: string
  feature_type: TaskFeature
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
  /** Agent used and, after a magic-wand rewrite, the brief the image model got. */
  agent?: { id?: string; name?: string; rewrite: boolean; rewritten?: string }
  /** Chat: what the text model saw in the images before drawing (ADR-20261009-P), or why
   *  it did not look (ADR-20261012-AB: NO_VISION). */
  analysis?: { text?: string; skipped?: 'NO_VISION' }
}
/** Agents of the conversation page (ADR-20261008-L). */
export interface Agent {
  id: string
  name: string
  description: string
  instructions: string
  public: boolean
  editable: boolean
  avatar: boolean
  updated_at: string
}
/** One row of the task history; every task is a v4 task (ADR-20261019-AD). */
export interface HistoryItem {
  task: Task
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
/** An enabled model the admin added; operators pick one per task (ADR-20260929-C). */
export interface ModelChoice {
  id: string
  name: string
  provider: 'openrouter' | 'openai' | 'gemini' | string
  model: string
  default: boolean
  /** Clarities the pages may offer (e.g. ["1K", "2K"]) and the starting one (ADR-20261009-R). */
  resolutions?: string[]
  resolution?: string
}
export interface Options {
  mode: 'development-only' | 'production-local'
  generation?: GenerationOptions
  models?: ModelChoice[]
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
  SUCCEEDED: '已完成',
}

export const providerNames: Record<string, string> = {
  openrouter: 'OpenRouter',
  openai: 'OpenAI 官方',
  deepseek: 'DeepSeek 官方',
  gemini: 'Gemini 官方',
  'openai-compatible': 'OpenAI 协议第三方',
  'gemini-compatible': 'Gemini 格式第三方',
}
