<script setup lang="ts">
import {
  computed,
  inject,
  onMounted,
  onUnmounted,
  reactive,
  ref,
  watch,
} from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ApiError, json } from '../api/workbench'
import { validateContract } from '../contracts/validate'
import AssetSlot from '../components/AssetSlot.vue'
import DropSelect from '../components/DropSelect.vue'
import EmptyState from '../components/EmptyState.vue'
import AgentAvatar from '../components/AgentAvatar.vue'
import AgentDialog from '../components/AgentDialog.vue'
import ImageViewer from '../components/ImageViewer.vue'
import ModalDialog from '../components/ModalDialog.vue'
import InfiniteCanvas from '../components/InfiniteCanvas.vue'
import LineIcon from '../components/LineIcon.vue'
import { fitSide, turns, type Turn } from '../workbench/canvas'
import { confirmAction } from '../workbench/confirm'
import {
  canvasSizes,
  resolutionsOf,
  type Resolution,
} from '../workbench/generation'
import type { Agent, Generation } from '../workbench/model'
import { providerNames, statusLabels } from '../workbench/model'
import PrivateImage from '../workbench/PrivateImage.vue'
import { workbenchKey } from '../workbench/useWorkbench'

// Conversational generation (ADR-20261008-I): every message is one CUSTOM v4 task.
type Conversation = {
  id: string
  title: string
  updated_at: string
  turns: number
  cover: string | null
}
type Detail = { id: string; title: string; tasks: Generation[] }

const w = inject(workbenchKey)!
const route = useRoute()
const router = useRouter()
const conversations = ref<Conversation[]>([])
const current = ref<Detail | null>(null)
const sending = ref(false),
  loading = ref(false),
  error = ref('')
const composer = reactive({
  product: '',
  ref1: '',
  ref2: '',
  prompt: '',
  model: '',
  size: 0,
  count: 1,
  resolution: '' as Resolution | '',
})
// The picture the next message changes; after each result the newest one is chosen unless the
// user picked or cleared it.
const edit = ref<{ id: string; label: string } | null>(null)
// The names the Worker gives the model for each image, so the user's words map onto them
// (ADR-20261009-M).
const imageNames = computed(() =>
  [
    edit.value ? '要修改的图' : '',
    '商品图',
    composer.ref1 ? '参考图1' : '',
    composer.ref1 && composer.ref2 ? '参考图2' : '',
  ]
    .filter(Boolean)
    .map((name) => `“${name}”`)
    .join('、'),
)
// Clearing 参考图1 moves 参考图2 up, so the names always match the order sent.
watch(
  () => composer.ref1,
  (value) => {
    if (!value && composer.ref2) {
      composer.ref1 = composer.ref2
      composer.ref2 = ''
    }
  },
)
let manualEdit = false
// An unknown outcome is resent with exactly the same body and key (no duplicate task).
const pending = ref<{ key: string; body: Record<string, unknown> } | null>(null)
// Agents and the magic wand (ADR-20261008-L): off = the agent's settings go with the request;
// on = a text model rewrites the request first, then the picture is generated.
const agents = ref<Agent[]>([])
const agentId = ref('')
const wand = ref(false)
const textModel = ref(false),
  admin = ref(false)
const picker = ref(false),
  managing = ref(false),
  pickerRoot = ref<HTMLElement>()
const agent = computed(
  () => agents.value.find((item) => item.id === agentId.value) ?? null,
)
async function loadAgents() {
  const result = await w.api<{
    items: Agent[]
    text_model: boolean
    admin: boolean
  }>('/agents')
  agents.value = result.items
  textModel.value = result.text_model
  admin.value = result.admin
  if (agentId.value && !agent.value) agentId.value = ''
  if (!textModel.value) wand.value = false
}
function pick(id: string) {
  agentId.value = id
  picker.value = false
}
function outsidePicker(event: PointerEvent) {
  if (!pickerRoot.value?.contains(event.target as Node)) picker.value = false
}
watch(picker, (open) =>
  open
    ? document.addEventListener('pointerdown', outsidePicker, true)
    : document.removeEventListener('pointerdown', outsidePicker, true),
)
async function agentsChanged(selected?: string) {
  await run(loadAgents)
  if (selected) agentId.value = selected
}
const suggestions = [
  '把商品放在浅木色桌面上，旁边有绿植，柔和的自然光',
  '温馨的婴儿房，商品放在白色床头柜上，暖色调',
  '纯白背景，商品居中，干净明亮的电商主图',
]

const modelOptions = computed(() =>
  w.models.map((item) => ({
    value: item.id,
    label: item.name,
    hint: providerNames[item.provider] ?? item.provider,
  })),
)
const sizeOptions = canvasSizes.map((size, index) => ({
  value: index,
  label: size.label,
  hint: size.ratio,
}))
// Clarity (ADR-20261009-R): the model's 1K or 2K output, separate from the output size.
const clarity = computed(() => resolutionsOf(w.models, composer.model))
const clarityOptions = computed(() =>
  clarity.value.list.map((item) => ({ value: item, label: item })),
)
watch(
  () => clarity.value.list.join(),
  () => {
    if (
      !composer.resolution ||
      !clarity.value.list.includes(composer.resolution)
    )
      composer.resolution = clarity.value.start ?? ''
  },
  { immediate: true },
)
const countOptions = computed(() =>
  Array.from({ length: w.generation?.max_count ?? 4 }, (_, i) => ({
    value: i + 1,
    label: `${i + 1} 张`,
  })),
)
const busy = computed(
  () =>
    !!current.value?.tasks.some((task) =>
      ['QUEUED', 'RUNNING'].includes(task.status),
    ),
)
const viewing = ref<number | null>(null)
const images = computed(() =>
  (current.value?.tasks ?? []).flatMap((task, turn) =>
    task.artifacts.map((artifact, index) => ({ task, turn, index, artifact })),
  ),
)
const viewerItems = computed(() =>
  images.value.map((item) => ({
    path: `/artifacts/${item.artifact.id}/content`,
    title: `第 ${item.turn + 1} 条 · 图 ${item.index + 1}`,
    detail: `${item.artifact.width} × ${item.artifact.height}`,
    download: () => w.download(item.artifact.id, `chat-${item.artifact.id}`),
  })),
)
// The canvas (ADR-20261010-S): each message's pictures in a row, oldest at the top. A message
// still generating shows one placeholder per picture; a failed one its reason and "重试".
type Cell = {
  key: string
  task: Generation
  turn: number
  index: number
  artifact: Generation['artifacts'][number] | null
}
const PICTURE_SIDE = 360
const cells = computed(() => {
  const all: Cell[] = []
  ;(current.value?.tasks ?? []).forEach((task, turn) => {
    if (task.status === 'SUCCEEDED')
      task.artifacts.forEach((artifact, index) =>
        all.push({ key: artifact.id, task, turn, index, artifact }),
      )
    else if (task.status === 'FAILED')
      all.push({
        key: `${task.id}:failed`,
        task,
        turn,
        index: 0,
        artifact: null,
      })
    else
      for (let index = 0; index < (task.output?.count ?? 1); index++)
        all.push({
          key: `${task.id}:${index}`,
          task,
          turn,
          index,
          artifact: null,
        })
  })
  return all
})
const cellByKey = computed(
  () => new Map(cells.value.map((cell) => [cell.key, cell])),
)
const cellsAt = (key: string) => {
  const cell = cellByKey.value.get(key)
  return cell ? [cell] : []
}
const rows = computed<Turn[]>(() =>
  (current.value?.tasks ?? []).map((task) => ({
    key: task.id,
    label: { key: `label:${task.id}`, height: 32 },
    items: cells.value
      .filter((cell) => cell.task.id === task.id)
      .map((cell) => ({
        key: cell.key,
        size: fitSide(
          cell.artifact ?? task.output ?? { width: 1, height: 1 },
          cell.artifact || task.status !== 'FAILED' ? PICTURE_SIDE : 240,
        ),
      })),
  })),
)
const labelAt = (key: string) => {
  const tasks = current.value?.tasks ?? []
  const turn = tasks.findIndex((task) => `label:${task.id}` === key)
  return turn >= 0 ? [{ task: tasks[turn]!, turn }] : []
}
const placed = computed(() => turns(rows.value, 240, 20, 56))
// Opening a conversation, sending and each finished message frame the newest row.
const newest = computed(() => {
  const last = rows.value.at(-1)
  return last ? [last.label.key, ...last.items.map((item) => item.key)] : []
})
// The picture clicked on the canvas shows its actions.
const picked = ref('')
// A message's details (inputs, model, what the text model wrote) open from its row.
const detailId = ref('')
const detail = computed(() => {
  const tasks = current.value?.tasks ?? []
  const turn = tasks.findIndex((task) => task.id === detailId.value)
  return turn >= 0 ? { task: tasks[turn]!, turn } : null
})
function previewImage(key: string) {
  const index = images.value.findIndex((item) => item.artifact.id === key)
  if (index >= 0) viewing.value = index
}
const modelName = (task: Generation) => {
  const id = task.request?.model_id
  return w.models.find((item) => item.id === id)?.name ?? '默认模型'
}
const references = (task: Generation) =>
  (task.request?.reference_asset_ids as string[] | undefined) ?? []
const when = (value: string) =>
  new Date(value).toLocaleString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })

async function run(fn: () => Promise<void>) {
  error.value = ''
  try {
    await fn()
  } catch (cause) {
    if (cause instanceof Error && cause.message !== 'STALE')
      error.value = cause.message
  }
}
async function loadList() {
  if (!w.project) return
  conversations.value = (
    await w.api<{ items: Conversation[] }>(
      `/projects/${w.project}/conversations`,
    )
  ).items
}
function pickLatest() {
  if (manualEdit || !current.value) return
  const tasks = current.value.tasks
  for (let turn = tasks.length - 1; turn >= 0; turn--) {
    const artifact = tasks[turn]!.artifacts[0]
    if (tasks[turn]!.status === 'SUCCEEDED' && artifact) {
      edit.value = { id: artifact.id, label: `第 ${turn + 1} 条 · 图 1` }
      return
    }
  }
  edit.value = null
}
let timer: ReturnType<typeof setTimeout> | undefined
function schedule() {
  clearTimeout(timer)
  if (busy.value) timer = setTimeout(() => void refresh(), 2500)
}
async function refresh() {
  const id = current.value?.id
  if (!id) return
  const wasBusy = busy.value
  const detail = await w.api<Detail>(`/conversations/${id}`)
  if (current.value?.id !== id) return
  current.value = detail
  pickLatest()
  if (wasBusy && !busy.value) void w.refreshHistory()
  schedule()
}
async function open(id: string) {
  await run(async () => {
    loading.value = true
    try {
      manualEdit = false
      pending.value = null
      current.value = await w.api<Detail>(`/conversations/${id}`)
      const last = current.value.tasks.at(-1)?.request
      if (last?.product_asset_id)
        composer.product = String(last.product_asset_id)
      pickLatest()
      schedule()
      if (route.query.c !== id)
        void router.replace({ path: '/chat', query: { c: id } })
    } finally {
      loading.value = false
    }
  })
}
function startNew() {
  clearTimeout(timer)
  current.value = null
  edit.value = null
  manualEdit = false
  pending.value = null
  composer.prompt = ''
  if (route.query.c) void router.replace({ path: '/chat' })
}
function chooseEdit(id: string, label: string) {
  manualEdit = true
  edit.value = { id, label }
}
function clearEdit() {
  manualEdit = true
  edit.value = null
}

function build(conversation: string): Record<string, unknown> {
  const size = canvasSizes[composer.size]!
  const refs = [composer.ref1, composer.ref2].filter(
    (id, index, all) =>
      id && id !== composer.product && all.indexOf(id) === index,
  )
  const body: Record<string, unknown> = {
    project_id: w.project,
    feature_type: 'CUSTOM',
    conversation_id: conversation,
    product_asset_id: composer.product,
    prompt: composer.prompt.trim(),
    output: {
      aspect_ratio: size.ratio,
      width: size.width,
      height: size.height,
      format: 'png',
      count: composer.count,
    },
  }
  if (refs.length) body.reference_asset_ids = refs
  if (edit.value) body.edit_artifact_id = edit.value.id
  if (composer.model) body.model_id = composer.model
  if (composer.resolution) body.resolution = composer.resolution
  if (agentId.value) body.agent_id = agentId.value
  if (wand.value) body.rewrite = true
  return body
}
const blocked = computed(() =>
  !composer.product
    ? '请先选择或上传商品图。'
    : !composer.prompt.trim()
      ? '请输入描述，说说想要的画面或要怎么改。'
      : [...composer.prompt.trim()].length > 1000
        ? '描述最多 1000 字。'
        : '',
)
async function send() {
  if (sending.value || (blocked.value && !pending.value)) return
  sending.value = true
  await run(async () => {
    try {
      let attempt = pending.value
      if (!attempt) {
        let conversation = current.value?.id
        if (!conversation) {
          const title = [...composer.prompt.trim()].slice(0, 20).join('')
          const created = await w.api<Conversation>(
            `/projects/${w.project}/conversations`,
            json({ title }),
          )
          conversation = created.id
          current.value = { id: created.id, title: created.title, tasks: [] }
          void router.replace({ path: '/chat', query: { c: created.id } })
        }
        const body = build(conversation)
        if (validateContract('generation-v4-create', body).length)
          throw new Error('请检查输入：描述 1–1000 字，其他参考图最多 2 张。')
        attempt = { key: crypto.randomUUID(), body }
        pending.value = attempt
      }
      await w.api('/v4/generation-tasks', {
        ...json(attempt.body),
        headers: {
          'Content-Type': 'application/json',
          'Idempotency-Key': attempt.key,
        },
      })
      pending.value = null
      composer.prompt = ''
      manualEdit = false
      await refresh()
      void loadList()
    } catch (cause) {
      // A definite rejection frees the message; an unknown outcome keeps the same key.
      if (cause instanceof ApiError && cause.status > 0 && cause.status < 500)
        pending.value = null
      throw cause
    }
  })
  sending.value = false
}
async function retry(task: Generation) {
  await run(async () => {
    await w.api(`/tasks/${task.id}/retry`, json({ attempt: task.attempt }))
    await refresh()
  })
}
async function remove(item: Conversation) {
  const ok = await confirmAction(
    `删除对话“${item.title}”`,
    '只删除这条对话记录，生成的图片仍在“我的作品”和“任务记录”里。',
    '删除',
  )
  if (!ok) return
  await run(async () => {
    await w.api(`/conversations/${item.id}`, { method: 'DELETE' })
    if (current.value?.id === item.id) startNew()
    await loadList()
    w.notice = '对话已删除，图片仍保留在“我的作品”。'
  })
}
function keydown(event: KeyboardEvent) {
  if (event.key === 'Enter' && (event.ctrlKey || event.metaKey)) {
    event.preventDefault()
    void send()
  }
}
watch(
  () => w.models.map((item) => item.id).join(),
  () => {
    if (!w.models.some((item) => item.id === composer.model))
      composer.model = w.defaultModel
  },
  { immediate: true },
)
async function openFromQuery() {
  const c = route.query.c
  const task = route.query.task
  if (typeof c === 'string' && c !== current.value?.id) await open(c)
  else if (typeof task === 'string')
    await run(async () => {
      const detail = await w.api<Generation>(`/v4/generation-tasks/${task}`)
      const conversation = detail.request?.conversation_id
      if (typeof conversation === 'string') await open(conversation)
      else error.value = '这条任务所属的对话已删除，图片仍在“我的作品”。'
    })
}
watch(() => [route.query.c, route.query.task], openFromQuery)
onMounted(() => {
  void w.refreshOptions()
  void run(loadList)
  void run(loadAgents)
  void openFromQuery()
})
onUnmounted(() => {
  clearTimeout(timer)
  document.removeEventListener('pointerdown', outsidePicker, true)
})
</script>

<template>
  <main class="board chat-board">
    <aside class="card chat-list" aria-label="对话列表">
      <div class="chat-list-head">
        <b>对话生图</b>
        <button
          type="button"
          class="btn sm"
          data-testid="new-chat"
          @click="startNew"
        >
          <LineIcon name="plus" :size="14" />新对话
        </button>
      </div>
      <div class="chat-items">
        <div
          v-for="item in conversations"
          :key="item.id"
          class="chat-item"
          :class="{ active: current?.id === item.id }"
          data-testid="chat-item"
        >
          <button
            type="button"
            class="chat-open"
            :title="item.title"
            @click="open(item.id)"
          >
            <span class="cover">
              <PrivateImage
                v-if="item.cover"
                :path="`/artifacts/${item.cover}/content`"
                alt=""
                :api="w.api"
              />
              <LineIcon v-else name="chat" :size="16" />
            </span>
            <span class="meta"
              ><b>{{ item.title }}</b
              ><small
                >{{ when(item.updated_at) }} · {{ item.turns }} 条</small
              ></span
            >
          </button>
          <button
            type="button"
            class="icon-btn danger"
            :aria-label="`删除对话 ${item.title}`"
            @click="remove(item)"
          >
            <LineIcon name="del" :size="14" />
          </button>
        </div>
        <p v-if="!conversations.length" class="hint chat-none">
          还没有对话。在右侧输入描述开始第一条。
        </p>
      </div>
    </aside>

    <section class="card chat-main" aria-label="对话">
      <div class="chat-canvas">
        <InfiniteCanvas
          :items="placed"
          :focus="newest"
          label="画布：本对话的所有图片"
          @preview="previewImage"
        >
          <template #default="{ item, near }">
            <template v-if="item.key.startsWith('label:')">
              <div
                v-for="row in labelAt(item.key)"
                :key="row.task.id"
                class="canvas-label"
                data-testid="chat-turn"
                :data-status="row.task.status"
              >
                <b>第 {{ row.turn + 1 }} 条</b>
                <span
                  class="canvas-prompt"
                  :title="String(row.task.request?.prompt ?? '')"
                  >{{ row.task.request?.prompt }}</span
                >
                <span
                  v-if="row.task.status !== 'SUCCEEDED'"
                  class="turn-status"
                  :data-status="row.task.status"
                  >{{ statusLabels[row.task.status] }}</span
                >
                <button
                  type="button"
                  class="link-btn"
                  :aria-label="`第 ${row.turn + 1} 条详情`"
                  @click="detailId = row.task.id"
                >
                  详情
                </button>
              </div>
            </template>
            <template v-else>
              <figure
                v-for="cell in cellsAt(item.key)"
                :key="cell.key"
                class="tile canvas-tile chat-cell"
                :class="{
                  running: !cell.artifact && cell.task.status !== 'FAILED',
                  shimmer: ['QUEUED', 'RUNNING'].includes(cell.task.status),
                  chosen: !!cell.artifact && edit?.id === cell.artifact.id,
                }"
                data-testid="canvas-image"
                :data-status="cell.task.status"
                :data-artifact="cell.artifact?.id"
                :data-selected="!!cell.artifact && picked === cell.artifact.id"
              >
                <button
                  type="button"
                  class="open"
                  :aria-label="`选中第 ${cell.turn + 1} 条图 ${cell.index + 1}`"
                  :title="cell.artifact ? '单击选中，双击全屏查看' : undefined"
                  @click="picked = cell.artifact?.id ?? ''"
                >
                  <PrivateImage
                    v-if="cell.artifact && near"
                    :path="`/artifacts/${cell.artifact.id}/content`"
                    :alt="`第 ${cell.turn + 1} 条结果 ${cell.index + 1}`"
                    :api="w.api"
                  />
                  <span
                    v-else-if="cell.task.status === 'FAILED'"
                    class="tile-note"
                    ><LineIcon name="alert" :size="20" /><span
                      >{{ cell.task.error?.message }}（{{
                        cell.task.error?.code
                      }}）</span
                    ></span
                  >
                  <span v-else-if="!cell.artifact" class="tile-note"
                    ><span class="spinner"></span
                    ><span>{{
                      cell.task.status === 'QUEUED' ? '排队中' : '生成中'
                    }}</span></span
                  >
                </button>
                <span
                  v-if="cell.artifact && edit?.id === cell.artifact.id"
                  class="flag edit-flag"
                  >修改这张</span
                >
                <div v-if="cell.artifact" class="hover-actions">
                  <button
                    type="button"
                    aria-label="继续修改"
                    title="继续修改：下一条消息修改这张图"
                    @click="
                      chooseEdit(
                        cell.artifact.id,
                        `第 ${cell.turn + 1} 条 · 图 ${cell.index + 1}`,
                      )
                    "
                  >
                    <LineIcon name="edit" :size="13" />
                  </button>
                  <button
                    type="button"
                    aria-label="放大查看"
                    title="放大查看"
                    @click="previewImage(cell.artifact.id)"
                  >
                    <LineIcon name="zoomin" :size="13" />
                  </button>
                  <button
                    type="button"
                    aria-label="下载"
                    title="下载"
                    @click="
                      w.download(cell.artifact.id, `chat-${cell.artifact.id}`)
                    "
                  >
                    <LineIcon name="dl" :size="13" />
                  </button>
                </div>
                <div
                  v-else-if="cell.task.status === 'FAILED'"
                  class="hover-actions always"
                >
                  <button
                    type="button"
                    aria-label="重试"
                    title="重试"
                    @click="retry(cell.task)"
                  >
                    <LineIcon name="redo" :size="13" />
                  </button>
                </div>
              </figure>
            </template>
          </template>
          <template #empty>
            <EmptyState v-if="loading">读取对话…</EmptyState>
            <div v-else class="chat-empty">
              <h2>想生成什么样的图？</h2>
              <p>
                选择商品图，用自己的话描述画面；生成后可以接着说要怎么改，比如“背景换成浅蓝色”“加一束花”。生成的图片按发送先后排在这块画布上：拖动平移，滚轮缩放，双击图片全屏查看。
              </p>
              <div class="suggest">
                <button
                  v-for="text in suggestions"
                  :key="text"
                  type="button"
                  class="chip"
                  @click="composer.prompt = text"
                >
                  {{ text }}
                </button>
              </div>
            </div>
          </template>
        </InfiniteCanvas>
      </div>

      <form class="composer" @submit.prevent="send">
        <p v-if="error" class="banner error" role="alert">
          <LineIcon name="alert" :size="14" />{{ error }}
        </p>
        <p v-if="pending" class="banner warn">
          上次发送结果不确定，再点“发送”会用原请求重发，不会重复生成。
        </p>
        <div class="composer-box">
          <div class="composer-assets">
            <AssetSlot
              v-model="composer.product"
              label="商品图"
              kind="PRODUCT"
            />
            <AssetSlot
              v-model="composer.ref1"
              label="参考图1"
              kind="REFERENCE"
            />
            <AssetSlot
              v-if="composer.ref1"
              v-model="composer.ref2"
              label="参考图2"
              kind="REFERENCE"
            />
            <div v-if="edit" class="edit-chip" data-testid="edit-target">
              <PrivateImage
                :path="`/artifacts/${edit.id}/content`"
                alt="修改对象"
                :api="w.api"
              />
              <span
                ><b>修改这张</b><small>{{ edit.label }}</small></span
              >
              <button
                type="button"
                class="icon-btn"
                aria-label="不修改，重新生成"
                title="不修改这张，按描述重新生成"
                @click="clearEdit"
              >
                <LineIcon name="close" :size="14" />
              </button>
            </div>
          </div>
          <textarea
            v-model="composer.prompt"
            aria-label="描述"
            rows="3"
            maxlength="1000"
            :placeholder="
              edit
                ? '说说要怎么改，例如：背景换成浅蓝色，加一束小雏菊'
                : '描述你想要的画面，例如：把商品放在浅木色桌面上，旁边有绿植，柔和的自然光'
            "
            @keydown="keydown"
          ></textarea>
        </div>
        <p
          v-if="composer.ref1 || edit"
          class="hint names"
          data-testid="image-names"
        >
          描述里用图片下方的名称指代图片（{{
            imageNames
          }}），例如“在参考图1的基础上，把商品图作为赠品加进去”。
        </p>
        <div class="composer-bar">
          <div ref="pickerRoot" class="dd agent-picker">
            <button
              type="button"
              class="chip-btn"
              aria-haspopup="true"
              :aria-expanded="picker"
              data-testid="agent-picker"
              :title="agent ? agent.description : '选择一位设计师（智能体）'"
              @click="picker = !picker"
            >
              <AgentAvatar :agent="agent" :size="22" />{{
                agent ? agent.name : '智能体'
              }}
            </button>
            <div
              v-if="picker"
              class="menu agent-menu"
              role="group"
              aria-label="智能体"
            >
              <button
                type="button"
                class="agent-option"
                :aria-pressed="!agentId"
                @click="pick('')"
              >
                <AgentAvatar :agent="null" :size="36" /><span class="meta"
                  ><b>不使用智能体</b><small>只用你的描述出图</small></span
                >
              </button>
              <template
                v-for="group in [
                  { name: '公共', items: agents.filter((a) => a.public) },
                  { name: '我的', items: agents.filter((a) => !a.public) },
                ]"
                :key="group.name"
              >
                <div v-if="group.items.length" class="agent-menu-group">
                  {{ group.name }}
                </div>
                <button
                  v-for="item in group.items"
                  :key="item.id"
                  type="button"
                  class="agent-option"
                  :aria-pressed="agentId === item.id"
                  data-testid="agent-option"
                  @click="pick(item.id)"
                >
                  <AgentAvatar :agent="item" :size="36" /><span class="meta"
                    ><b>{{ item.name }}</b
                    ><small>{{ item.description }}</small></span
                  >
                </button>
              </template>
              <button
                type="button"
                class="menu-item"
                @click="((picker = false), (managing = true))"
              >
                <LineIcon name="edit" :size="14" />管理智能体
              </button>
            </div>
          </div>
          <button
            type="button"
            class="chip-btn wand"
            :aria-pressed="wand"
            aria-label="魔法棒"
            data-testid="wand"
            :disabled="!textModel"
            :title="
              textModel
                ? wand
                  ? '魔法棒已开：先由 AI 按智能体改写需求再出图（再点关闭）'
                  : '魔法棒：点亮后先由 AI 按智能体改写需求再出图'
                : '管理员还没有配置文本模型，暂不能改写'
            "
            @click="wand = !wand"
          >
            <LineIcon name="wand" :size="15" /><span class="label">{{
              wand ? 'AI 改写' : ''
            }}</span>
          </button>
          <DropSelect
            v-model="composer.model"
            label="模型"
            :options="modelOptions"
            placeholder="未配置模型"
            :disabled="!modelOptions.length"
          />
          <DropSelect
            v-model="composer.size"
            label="尺寸"
            :options="sizeOptions"
          />
          <DropSelect
            v-model="composer.resolution"
            label="清晰度"
            :options="clarityOptions"
            :disabled="clarityOptions.length < 2"
          />
          <DropSelect
            v-model="composer.count"
            label="数量"
            :options="countOptions"
          />
          <span class="spacer"></span>
          <button
            type="submit"
            class="btn primary"
            data-testid="chat-send"
            :disabled="sending || (!!blocked && !pending)"
            :title="blocked || 'Ctrl+Enter 发送'"
          >
            <span v-if="sending" class="spinner"></span>
            <LineIcon v-else name="spark" :size="14" />{{
              pending ? '重发' : edit ? '修改' : '生成'
            }}
          </button>
        </div>
      </form>
    </section>

    <ModalDialog
      v-if="detail"
      :title="`第 ${detail.turn + 1} 条`"
      @close="detailId = ''"
    >
      <div class="turn-detail">
        <p class="turn-prompt">{{ detail.task.request?.prompt }}</p>
        <div class="refs">
          <span v-if="detail.task.request?.edit_artifact_id" class="ref edit">
            <PrivateImage
              :path="`/artifacts/${detail.task.request.edit_artifact_id}/content`"
              alt="要修改的图"
              :api="w.api"
              missing="已删除"
            /><small>要修改的图</small>
          </span>
          <span class="ref">
            <PrivateImage
              :path="`/assets/${detail.task.request?.product_asset_id}/content`"
              alt="商品图"
              :api="w.api"
              missing="已删除"
            /><small>商品图</small>
          </span>
          <span
            v-for="(id, index) in references(detail.task)"
            :key="id"
            class="ref"
          >
            <PrivateImage
              :path="`/assets/${id}/content`"
              :alt="`参考图${index + 1}`"
              :api="w.api"
              missing="已删除"
            /><small>参考图{{ index + 1 }}</small>
          </span>
        </div>
        <p class="hint">
          {{ modelName(detail.task) }}
          <template v-if="detail.task.output">
            · {{ detail.task.output.width }} × {{ detail.task.output.height }}
          </template>
          · {{ statusLabels[detail.task.status] }}
          <template v-if="detail.task.agent">
            · 智能体 {{ detail.task.agent.name ?? '默认设计师' }}
          </template>
        </p>
        <details
          v-if="detail.task.agent?.rewritten"
          class="rewritten"
          open
          data-testid="rewritten"
        >
          <summary>
            <LineIcon name="wand" :size="13" />{{
              detail.task.agent.name ?? '默认设计师'
            }}
            {{ detail.task.analysis ? '看图改写' : '改写' }}
          </summary>
          <p>{{ detail.task.agent.rewritten }}</p>
        </details>
        <!-- Look first, then draw (ADR-20261009-P): what the text model saw. -->
        <details
          v-else-if="detail.task.analysis?.text"
          class="rewritten"
          open
          data-testid="analysis"
        >
          <summary><LineIcon name="spark" :size="13" />看图分析</summary>
          <p>{{ detail.task.analysis.text }}</p>
        </details>
        <p
          v-else-if="
            (detail.task.agent?.rewrite || detail.task.analysis) &&
            ['QUEUED', 'RUNNING'].includes(detail.task.status)
          "
          class="hint"
        >
          正在看图分析，写清每张图的细节后再出图…
        </p>
        <p v-if="detail.task.status === 'FAILED'" class="ai-fail">
          <LineIcon name="alert" :size="14" />{{
            detail.task.error?.message
          }}（{{ detail.task.error?.code }}）
        </p>
      </div>
    </ModalDialog>
    <AgentDialog
      v-if="managing"
      :agents="agents"
      :admin="admin"
      @close="managing = false"
      @changed="agentsChanged"
    />
    <ImageViewer
      v-if="viewing !== null && viewerItems.length"
      :items="viewerItems"
      :start="viewing"
      @close="viewing = null"
    />
  </main>
</template>
