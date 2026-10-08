<script setup lang="ts">
import { inject, onUnmounted, ref } from 'vue'
import { json } from '../api/workbench'
import { confirmAction } from '../workbench/confirm'
import { canvasSizes } from '../workbench/generation'
import type { GenerationDraft } from '../workbench/generation'
import type { Feature } from '../workbench/model'
import { workbenchKey } from '../workbench/useWorkbench'
import LineIcon from './LineIcon.vue'
import ModalDialog from './ModalDialog.vue'

type Template = {
  id: string
  name: string
  settings: Partial<GenerationDraft>
  updated_at: string
}
// Personal templates (ADR-20260930-F): this entry's settings without images or text content.
const props = defineProps<{ feature: Feature; draft: GenerationDraft }>()
const emit = defineEmits<{ apply: [settings: Partial<GenerationDraft>] }>()
const w = inject(workbenchKey)!
const open = ref(false),
  saving = ref(false),
  name = ref('')
const templates = ref<Template[]>([])
const root = ref<HTMLElement>()
const busy = ref(false),
  error = ref('')
const FIELDS: Record<Feature, (keyof GenerationDraft)[]> = {
  GIFT: [
    'giftPosition',
    'backgroundMode',
    'backgroundColor',
    'backgroundPrompt',
    'giftCard',
    'giftCardSize',
    'giftCardBackground',
  ],
  SCENE: ['scenePreset', 'scenePrompt'],
  SELLING_POINT: [
    'styles',
    'keepOriginal',
    'productPosition',
    'textColor',
    'textLevel',
    'textPosition',
    'textAlign',
    'textBox',
  ],
}
// Deep copy that also works on reactive proxies (structuredClone rejects them).
const plain = <T,>(value: T): T =>
  value === undefined ? value : JSON.parse(JSON.stringify(value))
const fields = () =>
  [
    'model',
    'size',
    ...(props.feature === 'SELLING_POINT' ? [] : ['count']),
    ...FIELDS[props.feature],
  ] as (keyof GenerationDraft)[]

function outside(event: PointerEvent) {
  if (!root.value?.contains(event.target as Node)) hide()
}
function hide() {
  open.value = false
  document.removeEventListener('pointerdown', outside, true)
}
async function toggle() {
  if (open.value) return hide()
  open.value = true
  document.addEventListener('pointerdown', outside, true)
  await load()
}
onUnmounted(() => document.removeEventListener('pointerdown', outside, true))
async function run(fn: () => Promise<void>) {
  if (busy.value) return
  busy.value = true
  error.value = ''
  try {
    await fn()
  } catch (cause) {
    if (cause instanceof Error && cause.message !== 'STALE')
      error.value = cause.message
  } finally {
    busy.value = false
  }
}
async function load() {
  await run(async () => {
    templates.value = (
      await w.api<{ items: Template[] }>(`/templates?feature=${props.feature}`)
    ).items
  })
}
/** Applies what still makes sense now: unknown models, scenes or styles are skipped. */
function apply(template: Template) {
  const models = new Set(w.models.map((item) => item.id))
  const scenes = new Set(
    (w.generation?.scene_presets ?? []).map((item) => item.id),
  )
  const styles = new Set((w.generation?.styles ?? []).map((item) => item.id))
  const next: Partial<GenerationDraft> = {}
  for (const key of fields()) {
    const value = template.settings[key]
    if (value === undefined) continue
    if (key === 'model' && !models.has(value as string)) continue
    if (key === 'scenePreset' && value && !scenes.has(value as string)) continue
    if (key === 'size' && !canvasSizes[value as number]) continue
    if (key === 'count' && (value as number) > (w.generation?.max_count ?? 4))
      continue
    if (key === 'styles') {
      // One style per selling task now (ADR-20261008-G); older templates may hold several.
      const kept = (value as string[]).filter((id) => styles.has(id))
      if (kept.length) next.styles = kept.slice(0, 1)
      continue
    }
    Object.assign(next, { [key]: plain(value) })
  }
  emit('apply', next)
  hide()
  w.notice = `已套用模板“${template.name}”。`
}
function startSave() {
  hide()
  name.value = ''
  error.value = ''
  saving.value = true
}
async function save() {
  const settings = Object.fromEntries(
    fields().map((key) => [key, plain(props.draft[key])]),
  )
  await run(async () => {
    await w.api(
      '/templates',
      json({ name: name.value.trim(), feature_type: props.feature, settings }),
    )
    saving.value = false
    w.notice = `已保存模板“${name.value.trim()}”，同名模板会被覆盖。`
  })
}
async function remove(template: Template) {
  const ok = await confirmAction(
    `删除模板“${template.name}”`,
    '只删除这个参数模板，不影响任何图片。',
    '删除',
  )
  if (!ok) return
  await run(async () => {
    await w.api(`/templates/${template.id}`, { method: 'DELETE' })
    await load()
  })
}
</script>

<template>
  <div ref="root" class="dd template-menu" @keydown.esc="hide">
    <button
      type="button"
      class="tool"
      aria-haspopup="true"
      :aria-expanded="open"
      title="我的模板：保存或套用这一页的参数"
      :disabled="w.busy"
      @click="toggle"
    >
      <LineIcon name="save" /><span class="label">我的模板</span>
    </button>
    <div v-if="open" class="menu" role="group" aria-label="我的模板">
      <button type="button" class="menu-item" @click="startSave">
        <LineIcon name="plus" :size="14" />保存当前参数为模板
      </button>
      <p v-if="error" class="banner error" role="alert">{{ error }}</p>
      <div
        v-for="template in templates"
        :key="template.id"
        class="template-row"
        data-testid="template-row"
      >
        <button
          type="button"
          class="menu-item grow"
          :title="`套用“${template.name}”`"
          @click="apply(template)"
        >
          {{ template.name }}
        </button>
        <button
          type="button"
          class="icon-btn danger"
          :aria-label="`删除模板 ${template.name}`"
          @click="remove(template)"
        >
          <LineIcon name="del" :size="14" />
        </button>
      </div>
      <p v-if="!templates.length && !busy" class="hint template-empty">
        还没有模板。保存后可一键套用背景、文字位置、尺寸等参数。
      </p>
    </div>
    <ModalDialog v-if="saving" title="保存为模板" @close="saving = false">
      <form id="template-form" class="form-grid" @submit.prevent="save">
        <p v-if="error" class="banner error" role="alert">{{ error }}</p>
        <label class="form-row"
          ><span>模板名称</span
          ><input
            v-model="name"
            maxlength="40"
            required
            placeholder="例如：奶油底·右上文字"
        /></label>
        <p class="hint">
          保存本页的参数（不含图片和文字内容）；与已有模板同名时会覆盖。
        </p>
      </form>
      <template #footer>
        <button type="button" class="btn" @click="saving = false">取消</button>
        <button
          type="submit"
          form="template-form"
          class="btn primary"
          :disabled="busy"
        >
          保存模板
        </button>
      </template>
    </ModalDialog>
  </div>
</template>
