<script setup lang="ts">
import {
  computed,
  inject,
  nextTick,
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
import ContextMenu, { type MenuItem } from '../components/ContextMenu.vue'
import ImageViewer from '../components/ImageViewer.vue'
import ModalDialog from '../components/ModalDialog.vue'
import InfiniteCanvas, {
  type CanvasCommand,
} from '../components/InfiniteCanvas.vue'
import LineIcon from '../components/LineIcon.vue'
import type { Placed } from '../workbench/canvas'
import {
  EMPTY,
  complete,
  duplicate,
  idOf,
  moveItems,
  pendingCells,
  pieceSize,
  rectOf,
  refOf,
  removeItems,
  restoreRemoved,
  tidy,
  type Layout,
  type Pending,
  type Piece,
} from '../workbench/chatCanvas'
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
import { useFileDrop } from '../workbench/fileDrop'

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
const uploading = ref(false)
let mounted = true
const uploadLocked = computed(
  () =>
    uploading.value ||
    sending.value ||
    loading.value ||
    !!pending.value ||
    w.busy ||
    w.uncertain,
)
const { dragging, handlers: dropEvents } = useFileDrop(
  () => uploadLocked.value,
  async (files) => {
    const slots = (['product', 'ref1', 'ref2'] as const).filter(
      (key) => !composer[key],
    )
    if (files.length > slots.length) {
      error.value = `还有 ${slots.length} 个图片空位，请减少拖入的图片或先清除已有选择。`
      return
    }
    uploading.value = true
    error.value = ''
    const conversation = current.value?.id
    const project = w.project
    try {
      for (const [index, file] of files.entries()) {
        if (
          !mounted ||
          !w.signedIn ||
          current.value?.id !== conversation ||
          w.project !== project
        )
          break
        const key = slots[index]!
        const asset = await w.upload(
          file,
          key === 'product' ? 'PRODUCT' : 'REFERENCE',
        )
        if (
          !asset ||
          !mounted ||
          current.value?.id !== conversation ||
          w.project !== project
        )
          break
        composer[key] = asset.id
      }
    } finally {
      uploading.value = false
    }
  },
)
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
// The canvas (ADR-20261010-S; arranged and saved since ADR-20261010-V): finished pictures and
// failed messages' cards sit where the user put them (new ones in rows below); copies and what
// was taken off the canvas are kept per conversation. Messages still generating show
// placeholders. Every picture has a caption; the first of each message carries its details.
const unknownSize = { width: 1, height: 1 }
const pieces = computed<Piece[]>(() =>
  (current.value?.tasks ?? []).flatMap((task): Piece[] =>
    task.status === 'SUCCEEDED'
      ? task.artifacts.map((artifact, index) => ({
          ref: artifact.id,
          kind: 'artifact',
          taskId: task.id,
          index,
          size: pieceSize(artifact),
        }))
      : task.status === 'FAILED'
        ? [
            {
              ref: task.id,
              kind: 'task',
              taskId: task.id,
              index: 0,
              size: pieceSize(task.output ?? unknownSize, true),
            },
          ]
        : [],
  ),
)
const pendingTasks = computed<Pending[]>(() =>
  (current.value?.tasks ?? [])
    .filter((task) => task.status === 'QUEUED' || task.status === 'RUNNING')
    .map((task) => ({
      taskId: task.id,
      count: task.output?.count ?? 1,
      size: pieceSize(task.output ?? unknownSize),
    })),
)
// As saved on the server (null: never arranged, shown in the automatic rows).
const saved = ref<Layout | null>(null)
const savedVersion = ref(0)
const arranged = computed(
  () => complete(saved.value ?? EMPTY, pieces.value).layout,
)
const placeholders = computed(() =>
  pendingCells(arranged.value, pendingTasks.value, saved.value ?? EMPTY),
)
const placed = computed<Placed[]>(() => [
  ...arranged.value.items.map((item) => ({
    key: item.id,
    rect: rectOf(item),
    movable: true,
  })),
  ...placeholders.value,
])
type Entry = {
  key: string
  task: Generation
  turn: number
  index: number
  artifact: Generation['artifacts'][number] | null
  copy: boolean
  lead: boolean
}
const entries = computed(() => {
  const tasks = current.value?.tasks ?? []
  const turns = new Map(tasks.map((task, turn) => [task.id, turn]))
  const byRef = new Map(pieces.value.map((piece) => [piece.ref, piece]))
  const map = new Map<string, Entry>()
  const leads = new Set<string>()
  const add = (
    key: string,
    taskId: string,
    index: number,
    artifactId: string | null,
    copy: boolean,
  ) => {
    const turn = turns.get(taskId)
    if (turn === undefined) return
    const task = tasks[turn]!
    map.set(key, {
      key,
      task,
      turn,
      index,
      artifact: artifactId
        ? (task.artifacts.find((item) => item.id === artifactId) ?? null)
        : null,
      copy,
      lead: !leads.has(taskId),
    })
    leads.add(taskId)
  }
  for (const item of arranged.value.items) {
    const piece = byRef.get(refOf(item))
    if (piece)
      add(
        item.id,
        piece.taskId,
        piece.index,
        item.artifact_id ?? null,
        item.id !== idOf(piece),
      )
  }
  for (const cell of placeholders.value) {
    const [, taskId, index] = cell.key.split(':')
    add(cell.key, taskId!, Number(index), null, false)
  }
  return map
})
const entryAt = (key: string) => {
  const entry = entries.value.get(key)
  return entry ? [entry] : []
}
// Opening a conversation, sending and each finished message frame the newest message.
const newest = computed(() => {
  const last = current.value?.tasks.at(-1)
  return last
    ? [...entries.value.values()]
        .filter((entry) => entry.task.id === last.id)
        .map((entry) => entry.key)
    : []
})
const frameOn = computed(() => {
  const last = current.value?.tasks.at(-1)
  return [
    current.value?.id,
    last?.id,
    last?.status,
    last?.artifacts.length,
  ].join('|')
})

// Arranging (ADR-20261010-V): select or hand tool, a selection, undo and redo, auto-save.
const board = ref<InstanceType<typeof InfiniteCanvas>>()
const tool = ref<'select' | 'hand'>('select')
const selection = ref<string[]>([])
const clipboard = ref<string[]>([])
const history = reactive({ past: [] as string[], future: [] as string[] })
const onCanvas = (key: string) =>
  arranged.value.items.find((item) => item.id === key)
const selectedPictures = computed(() =>
  selection.value.filter((key) => onCanvas(key)?.artifact_id),
)
const removable = computed(() =>
  selection.value.filter((key) => !!onCanvas(key)),
)
const removedCount = computed(() => {
  const known = new Set(pieces.value.map((piece) => piece.ref))
  return arranged.value.removed.filter((ref) => known.has(ref)).length
})
function change(next: Layout) {
  history.past.push(JSON.stringify(arranged.value))
  if (history.past.length > 50) history.past.shift()
  history.future = []
  saved.value = next
  scheduleSave()
}
const newId = () => `c:${crypto.randomUUID().replace(/-/g, '').slice(0, 12)}`
function moveSelection(keys: string[], dx: number, dy: number) {
  const ids = keys.filter((key) => onCanvas(key))
  if (ids.length && (dx || dy)) change(moveItems(arranged.value, ids, dx, dy))
}
function removeSelection() {
  if (!removable.value.length) return
  change(removeItems(arranged.value, removable.value))
  selection.value = []
}
function duplicateSelection(ids: string[] = selectedPictures.value) {
  const pictures = ids.filter((key) => onCanvas(key)?.artifact_id)
  if (!pictures.length) return
  const copied = duplicate(arranged.value, pictures, newId)
  change(copied.layout)
  selection.value = copied.ids
}
async function reframe() {
  await nextTick()
  board.value?.frame([])
}
function tidyCanvas() {
  change(tidy(arranged.value, pieces.value))
  void reframe()
}
function restoreCanvas() {
  change(restoreRemoved(arranged.value, pieces.value))
  void reframe()
}
function step(from: string[], to: string[]) {
  const snapshot = from.pop()
  if (snapshot === undefined) return
  to.push(JSON.stringify(arranged.value))
  saved.value = JSON.parse(snapshot) as Layout
  selection.value = []
  scheduleSave()
}
const undoCanvas = () => step(history.past, history.future)
const redoCanvas = () => step(history.future, history.past)
function command(name: CanvasCommand) {
  if (name === 'remove') removeSelection()
  else if (name === 'duplicate') duplicateSelection()
  else if (name === 'copy') clipboard.value = [...selectedPictures.value]
  else if (name === 'paste') duplicateSelection(clipboard.value)
  else if (name === 'undo') undoCanvas()
  else redoCanvas()
}
// Right-click menu (ADR-20261012-Z): copy, take off the canvas and download live here. A
// picture outside the selection is selected first; the commands act on the whole selection.
const menu = ref<{ x: number; y: number; items: MenuItem[] } | null>(null)
async function downloadPictures(ids: string[]) {
  for (const id of ids) await w.download(id, `chat-${id}`)
}
function openMenu(event: MouseEvent, entry: Entry) {
  if (!onCanvas(entry.key)) return
  event.preventDefault()
  if (!selection.value.includes(entry.key)) selection.value = [entry.key]
  const pictures = selectedPictures.value
  const artifacts = [
    ...new Set(
      pictures.map((key) => onCanvas(key)!.artifact_id!).filter(Boolean),
    ),
  ]
  const many = (label: string, count: number) =>
    count > 1 ? `${label}所选 ${count} 张` : label
  const items: MenuItem[] = []
  if (entry.artifact) {
    const artifact = entry.artifact
    const name = `第 ${entry.turn + 1} 条 · 图 ${entry.index + 1}`
    items.push(
      {
        label: '继续修改',
        icon: 'edit',
        run: () => chooseEdit(artifact.id, name),
      },
      {
        label: '放大查看',
        icon: 'zoomin',
        run: () => previewImage(entry.key),
      },
      {
        label: many('下载', artifacts.length),
        icon: 'dl',
        run: () => downloadPictures(artifacts),
      },
      {
        label: many('复制', pictures.length),
        icon: 'copy',
        hint: 'Ctrl+D',
        run: () => duplicateSelection(),
      },
    )
  } else if (entry.task.status === 'FAILED')
    items.push({ label: '重试', icon: 'redo', run: () => retry(entry.task) })
  items.push({
    label: many('从画布移除', removable.value.length),
    icon: 'close',
    hint: 'Delete',
    run: removeSelection,
  })
  // From the keyboard (context-menu key) there is no pointer: open under the picture.
  let { clientX: x, clientY: y } = event
  if (!x && !y) {
    const box = (event.target as HTMLElement).getBoundingClientRect()
    x = box.left + 12
    y = box.top + 12
  }
  menu.value = { x, y, items }
}
// New results join a saved layout and are saved with it (no undo step).
watch([pieces, saved], () => {
  if (!saved.value) return
  const next = complete(saved.value, pieces.value)
  if (!next.added) return
  saved.value = next.layout
  scheduleSave()
})
let saveTimer: ReturnType<typeof setTimeout> | undefined
let saving = false,
  again = false
function scheduleSave() {
  clearTimeout(saveTimer)
  saveTimer = setTimeout(() => {
    saveTimer = undefined
    void persist()
  }, 600)
}
async function persist() {
  const conversation = current.value?.id
  if (!conversation || !saved.value) return
  if (saving) {
    again = true
    return
  }
  saving = true
  try {
    const result = await w.api<{ version: number }>(
      `/conversations/${conversation}/canvas`,
      {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          version: savedVersion.value,
          layout: saved.value,
        }),
      },
    )
    if (current.value?.id === conversation) savedVersion.value = result.version
  } catch (cause) {
    if (current.value?.id !== conversation) return
    if (cause instanceof ApiError && cause.status === 409) {
      await loadCanvas(conversation).catch(() => undefined)
      w.notice = '画布在别的窗口改过，已载入最新摆放。'
    } else if (cause instanceof Error && cause.message !== 'STALE')
      error.value = `画布摆放没有保存：${cause.message}`
  } finally {
    saving = false
    if (again) {
      again = false
      void persist()
    }
  }
}
/** Saves a change still waiting before another conversation is shown. */
async function flushCanvas() {
  if (!saveTimer) return
  clearTimeout(saveTimer)
  saveTimer = undefined
  await persist()
}
function resetCanvas() {
  clearTimeout(saveTimer)
  saveTimer = undefined
  saved.value = null
  savedVersion.value = 0
  history.past = []
  history.future = []
  selection.value = []
  clipboard.value = []
}
async function loadCanvas(id: string) {
  const result = await w.api<{ version: number; layout: Layout | null }>(
    `/conversations/${id}/canvas`,
  )
  if (current.value?.id !== id) return
  resetCanvas()
  saved.value = result.layout
  savedVersion.value = result.version
}
// A message's details (inputs, model, what the text model wrote) open from its row.
const detailId = ref('')
const detail = computed(() => {
  const tasks = current.value?.tasks ?? []
  const turn = tasks.findIndex((task) => task.id === detailId.value)
  return turn >= 0 ? { task: tasks[turn]!, turn } : null
})
function previewImage(key: string) {
  const id = entries.value.get(key)?.artifact?.id ?? key
  const index = images.value.findIndex((item) => item.artifact.id === id)
  if (index >= 0) viewing.value = index
}
/** Whether the text model looked at the images (not when it could not, ADR-20261012-AB). */
const looked = (task: Generation) => !!task.analysis && !task.analysis.skipped
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
  await flushCanvas()
  await run(async () => {
    loading.value = true
    try {
      manualEdit = false
      pending.value = null
      resetCanvas()
      current.value = await w.api<Detail>(`/conversations/${id}`)
      await loadCanvas(id)
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
  void flushCanvas().then(resetCanvas)
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
  if (
    sending.value ||
    uploading.value ||
    w.busy ||
    (blocked.value && !pending.value)
  )
    return
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
  mounted = false
  clearTimeout(timer)
  void flushCanvas()
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
          ref="board"
          v-model:selected="selection"
          v-model:tool="tool"
          :items="placed"
          :focus="newest"
          :frame-on="frameOn"
          editable
          label="画布：本对话的所有图片"
          @preview="previewImage"
          @move="moveSelection"
          @command="command"
        >
          <template #default="{ item, near }">
            <template v-for="entry in entryAt(item.key)" :key="entry.key">
              <div
                class="cell-caption"
                :class="{ lead: entry.lead }"
                v-bind="
                  entry.lead
                    ? {
                        'data-testid': 'chat-turn',
                        'data-status': entry.task.status,
                      }
                    : {}
                "
              >
                <b>第 {{ entry.turn + 1 }} 条</b>
                <template v-if="entry.lead">
                  <span
                    class="canvas-prompt"
                    :title="String(entry.task.request?.prompt ?? '')"
                    >{{ entry.task.request?.prompt }}</span
                  >
                  <span
                    v-if="entry.task.status !== 'SUCCEEDED'"
                    class="turn-status"
                    :data-status="entry.task.status"
                    >{{ statusLabels[entry.task.status] }}</span
                  >
                  <button
                    type="button"
                    class="link-btn"
                    :aria-label="`第 ${entry.turn + 1} 条详情`"
                    @click="detailId = entry.task.id"
                  >
                    详情
                  </button>
                </template>
                <span v-else-if="entry.artifact" class="muted"
                  >图 {{ entry.index + 1 }}</span
                >
                <span v-if="entry.copy" class="copy-tag">副本</span>
              </div>
              <figure
                class="tile canvas-tile chat-cell"
                :class="{
                  running: !entry.artifact && entry.task.status !== 'FAILED',
                  shimmer: ['QUEUED', 'RUNNING'].includes(entry.task.status),
                  chosen: !!entry.artifact && edit?.id === entry.artifact.id,
                }"
                data-testid="canvas-image"
                :data-status="entry.task.status"
                :data-artifact="entry.artifact?.id"
                :data-copy="entry.copy || undefined"
                :data-selected="selection.includes(entry.key)"
                @contextmenu="openMenu($event, entry)"
              >
                <button
                  type="button"
                  class="open"
                  :aria-label="`选中第 ${entry.turn + 1} 条图 ${entry.index + 1}${entry.copy ? '（副本）' : ''}`"
                  :title="
                    entry.artifact
                      ? '单击选中，拖动移动，双击全屏查看，右键更多操作'
                      : undefined
                  "
                  @click="$event.detail === 0 && (selection = [entry.key])"
                >
                  <PrivateImage
                    v-if="entry.artifact && near"
                    :path="`/artifacts/${entry.artifact.id}/content`"
                    :alt="`第 ${entry.turn + 1} 条结果 ${entry.index + 1}`"
                    :api="w.api"
                  />
                  <span
                    v-else-if="entry.task.status === 'FAILED'"
                    class="tile-note"
                    ><LineIcon name="alert" :size="20" /><span
                      >{{ entry.task.error?.message }}（{{
                        entry.task.error?.code
                      }}）</span
                    ></span
                  >
                  <span v-else-if="!entry.artifact" class="tile-note"
                    ><span class="spinner"></span
                    ><span>{{
                      entry.task.status === 'QUEUED' ? '排队中' : '生成中'
                    }}</span></span
                  >
                </button>
                <span
                  v-if="entry.artifact && edit?.id === entry.artifact.id"
                  class="flag edit-flag"
                  >修改这张</span
                >
                <div v-if="entry.artifact" class="hover-actions">
                  <button
                    type="button"
                    aria-label="继续修改"
                    title="继续修改：下一条消息修改这张图"
                    @click="
                      chooseEdit(
                        entry.artifact.id,
                        `第 ${entry.turn + 1} 条 · 图 ${entry.index + 1}`,
                      )
                    "
                  >
                    <LineIcon name="edit" :size="13" />
                  </button>
                  <button
                    type="button"
                    aria-label="放大查看"
                    title="放大查看"
                    @click="previewImage(entry.artifact.id)"
                  >
                    <LineIcon name="zoomin" :size="13" />
                  </button>
                </div>
                <div
                  v-else-if="entry.task.status === 'FAILED'"
                  class="hover-actions always"
                >
                  <button
                    type="button"
                    aria-label="重试"
                    title="重试"
                    @click="retry(entry.task)"
                  >
                    <LineIcon name="redo" :size="13" />
                  </button>
                </div>
              </figure>
            </template>
          </template>
          <template v-if="placed.length || removedCount" #footer>
            <div class="canvas-tools" role="toolbar" aria-label="画布工具">
              <div class="seg" role="group" aria-label="画布操作方式">
                <button
                  type="button"
                  :aria-pressed="tool === 'select'"
                  title="选择（V）：拖动图片移动，在空白处拖动框选"
                  @click="tool = 'select'"
                >
                  选择
                </button>
                <button
                  type="button"
                  :aria-pressed="tool === 'hand'"
                  title="抓手（H）：拖动平移画布；也可以按住空格"
                  @click="tool = 'hand'"
                >
                  抓手
                </button>
              </div>
              <button
                type="button"
                class="tool icon-only"
                aria-label="撤销"
                title="撤销（Ctrl+Z）"
                :disabled="!history.past.length"
                @click="undoCanvas"
              >
                <LineIcon name="undo" />
              </button>
              <button
                type="button"
                class="tool icon-only"
                aria-label="重做"
                title="重做（Ctrl+Shift+Z）"
                :disabled="!history.future.length"
                @click="redoCanvas"
              >
                <LineIcon name="redo2" />
              </button>
              <button
                type="button"
                class="tool"
                aria-label="整理"
                title="按消息先后重新排列"
                :disabled="!pieces.length"
                @click="tidyCanvas"
              >
                <LineIcon name="grid" /><span class="label">整理</span>
              </button>
              <button
                v-if="removedCount"
                type="button"
                class="tool"
                :aria-label="`放回已移除（${removedCount}）`"
                title="把从画布移除的图片放回画布"
                @click="restoreCanvas"
              >
                <LineIcon name="undo" /><span class="label"
                  >放回已移除（{{ removedCount }}）</span
                >
              </button>
            </div>
          </template>
          <template #empty>
            <EmptyState v-if="loading">读取对话…</EmptyState>
            <div v-else-if="removedCount" class="chat-empty">
              <p>
                这段对话的图片都已从画布移除（仍在“我的作品”里），点左下角“放回已移除”可以放回画布。
              </p>
            </div>
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
        <ContextMenu
          v-if="menu"
          :x="menu.x"
          :y="menu.y"
          :items="menu.items"
          label="图片操作"
          @close="menu = null"
        />
      </div>

      <form class="composer" @submit.prevent="send">
        <p v-if="error" class="banner error" role="alert">
          <LineIcon name="alert" :size="14" />{{ error }}
        </p>
        <p v-if="pending" class="banner warn">
          上次发送结果不确定，再点“发送”会用原请求重发，不会重复生成。
        </p>
        <div
          class="composer-box"
          :class="{ 'file-dragging': dragging }"
          v-on="dropEvents"
        >
          <span v-if="dragging" class="drop-hint">松开上传图片</span>
          <div class="composer-assets">
            <AssetSlot
              v-model="composer.product"
              label="商品图"
              kind="PRODUCT"
              :disabled="uploadLocked"
            />
            <AssetSlot
              v-model="composer.ref1"
              label="参考图1"
              kind="REFERENCE"
              :disabled="uploadLocked"
            />
            <AssetSlot
              v-if="composer.ref1"
              v-model="composer.ref2"
              label="参考图2"
              kind="REFERENCE"
              :disabled="uploadLocked"
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
        <p class="hint">
          可将图片拖入输入框，按商品图、参考图1、参考图2的空位顺序添加。
        </p>
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
            :disabled="
              sending || uploading || w.busy || (!!blocked && !pending)
            "
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
            {{ looked(detail.task) ? '看图改写' : '改写' }}
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
            (detail.task.agent?.rewrite || looked(detail.task)) &&
            ['QUEUED', 'RUNNING'].includes(detail.task.status)
          "
          class="hint"
        >
          正在看图分析，写清每张图的细节后再出图…
        </p>
        <!-- ADR-20261012-AB: the default text model cannot look at images. -->
        <p
          v-if="detail.task.analysis?.skipped === 'NO_VISION'"
          class="hint"
          data-testid="analysis-skipped"
        >
          未做看图分析：文本模型不能看图，已直接出图。
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
