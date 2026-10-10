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
import CanvasText from '../components/CanvasText.vue'
import DropSelect from '../components/DropSelect.vue'
import EmptyState from '../components/EmptyState.vue'
import AgentAvatar from '../components/AgentAvatar.vue'
import AgentDialog from '../components/AgentDialog.vue'
import ImageViewer from '../components/ImageViewer.vue'
import ModalDialog from '../components/ModalDialog.vue'
import InfiniteCanvas, {
  type CanvasCommand,
} from '../components/InfiniteCanvas.vue'
import LineIcon from '../components/LineIcon.vue'
import { fitSide, type Placed } from '../workbench/canvas'
import {
  BOARD_SIDE,
  EMPTY,
  PICTURE_SIDE,
  complete,
  duplicate,
  exportLayers,
  idOf,
  isOwn,
  moveItems,
  pendingCells,
  pieceSize,
  ratioOf,
  rectOf,
  refOf,
  removeItems,
  reorder,
  resizeItem,
  restoreRemoved,
  tidy,
  updateItem,
  type Anchors,
  type Layout,
  type Pending,
  type Piece,
  type Placement,
  type TextSpec,
} from '../workbench/chatCanvas'
import { confirmAction } from '../workbench/confirm'
import {
  backgrounds,
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
// Messages and canvas exports are numbered separately (ADR-20261010-W).
const isExport = (task: Generation) => task.feature_type === 'COMPOSE'
const numbers = computed(() => {
  const map = new Map<string, number>()
  let messages = 0,
    exports = 0
  for (const task of current.value?.tasks ?? [])
    map.set(task.id, isExport(task) ? ++exports : ++messages)
  return map
})
const pictureName = (task: Generation, index: number) =>
  isExport(task)
    ? `导出 ${numbers.value.get(task.id)}`
    : `第 ${numbers.value.get(task.id)} 条 · 图 ${index + 1}`
const viewerItems = computed(() =>
  images.value.map((item) => ({
    path: `/artifacts/${item.artifact.id}/content`,
    title: pictureName(item.task, item.index),
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
// An export's result goes beside the board it came from (ADR-20261010-W).
const anchors = computed<Anchors>(() => {
  const boards = new Map(
    (saved.value ?? EMPTY).items
      .filter((item) => item.frame)
      .map((item) => [item.id, item]),
  )
  const map: Anchors = new Map()
  for (const task of current.value?.tasks ?? []) {
    const board = boards.get(String(task.request?.frame_id ?? ''))
    if (isExport(task) && board)
      map.set(task.id, { x: board.x + board.width + 48, y: board.y })
  }
  return map
})
const arranged = computed(
  () => complete(saved.value ?? EMPTY, pieces.value, anchors.value).layout,
)
const placeholders = computed(() =>
  pendingCells(
    arranged.value,
    pendingTasks.value,
    saved.value ?? EMPTY,
    anchors.value,
  ),
)
// Boards always lie under everything else; the rest in the user's order.
const placed = computed<Placed[]>(() => [
  ...[...arranged.value.items]
    .sort((a, b) => Number(!!b.frame) - Number(!!a.frame))
    .map(
      (item): Placed => ({
        key: item.id,
        rect: rectOf(item),
        movable: true,
        resize: item.task_id ? undefined : item.text ? 'free' : 'ratio',
      }),
    ),
  ...placeholders.value,
])
type Entry = {
  key: string
  kind: 'result' | 'text' | 'asset' | 'frame'
  item: Placement | null
  task: Generation | null
  no: number
  index: number
  artifact: Generation['artifacts'][number] | null
  copy: boolean
  lead: boolean
}
const entries = computed(() => {
  const tasks = new Map(
    (current.value?.tasks ?? []).map((task) => [task.id, task]),
  )
  const byRef = new Map(pieces.value.map((piece) => [piece.ref, piece]))
  const map = new Map<string, Entry>()
  const leads = new Set<string>()
  const add = (
    key: string,
    taskId: string,
    index: number,
    artifactId: string | null,
    copy: boolean,
    item: Placement | null,
  ) => {
    const task = tasks.get(taskId)
    if (!task) return
    map.set(key, {
      key,
      kind: 'result',
      item,
      task,
      no: numbers.value.get(taskId) ?? 0,
      index,
      artifact: artifactId
        ? (task.artifacts.find((entry) => entry.id === artifactId) ?? null)
        : null,
      copy,
      lead: !leads.has(taskId),
    })
    leads.add(taskId)
  }
  for (const item of arranged.value.items) {
    if (isOwn(item)) {
      map.set(item.id, {
        key: item.id,
        kind: item.text ? 'text' : item.frame ? 'frame' : 'asset',
        item,
        task: null,
        no: 0,
        index: 0,
        artifact: null,
        copy: false,
        lead: false,
      })
      continue
    }
    const piece = byRef.get(refOf(item)!)
    if (piece)
      add(
        item.id,
        piece.taskId,
        piece.index,
        item.artifact_id ?? null,
        item.id !== idOf(piece),
        item,
      )
  }
  for (const cell of placeholders.value) {
    const [, taskId, index] = cell.key.split(':')
    add(cell.key, taskId!, Number(index), null, false, null)
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
        .filter((entry) => entry.task?.id === last.id)
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
// Everything but a failed message's card can be copied.
const selectedPictures = computed(() =>
  selection.value.filter((key) => {
    const item = onCanvas(key)
    return !!item && !item.task_id
  }),
)
const removable = computed(() =>
  selection.value.filter((key) => !!onCanvas(key)),
)
const removedCount = computed(() => {
  const known = new Set(pieces.value.map((piece) => piece.ref))
  return arranged.value.removed.filter((ref) => known.has(ref)).length
})
// A burst of edits to one text box (typing) is one undo step.
let lastMerge = '',
  lastAt = 0
function change(next: Layout, merge = '') {
  const now = Date.now()
  if (!merge || merge !== lastMerge || now - lastAt > 1500) {
    history.past.push(JSON.stringify(arranged.value))
    if (history.past.length > 50) history.past.shift()
    history.future = []
  }
  lastMerge = merge
  lastAt = now
  saved.value = next
  scheduleSave()
}
// Adding text, library pictures and boards (ADR-20261010-W), in the middle of what is shown.
const shortId = () => crypto.randomUUID().replace(/-/g, '').slice(0, 12)
function addItem(item: Omit<Placement, 'x' | 'y'>) {
  const centre = board.value?.worldCentre() ?? { x: 0, y: 0 }
  const placed = {
    ...item,
    x: Math.round(centre.x - item.width / 2),
    y: Math.round(centre.y - item.height / 2),
  } as Placement
  change({
    items: [...arranged.value.items, placed],
    removed: arranged.value.removed,
  })
  tool.value = 'select'
  selection.value = [placed.id]
}
const textPalette = [
  { color: '#1D2129', name: '深灰' },
  { color: '#FFFFFF', name: '白色' },
  { color: '#4A2E1F', name: '深棕' },
  { color: '#1E3A5F', name: '深蓝' },
  { color: '#C8573A', name: '橙红' },
  { color: '#1683D8', name: '主题蓝' },
]
const textSizes = [24, 32, 40, 48, 64, 80, 96, 120, 160].map((size) => ({
  value: size,
  label: `${size}`,
}))
function addText() {
  addItem({
    id: `x:${shortId()}`,
    text: {
      content: '双击编辑文字',
      size: 48,
      color: '#1D2129',
      align: 'left',
    },
    width: 360,
    height: 120,
  })
  void nextTick(() => textEditor.value?.select())
}
function addBoard() {
  const size = canvasSizes[0]!
  const world = fitSide(size, BOARD_SIDE)
  addItem({
    id: `f:${shortId()}`,
    frame: { width: size.width, height: size.height, background: '#FFFFFF' },
    ...world,
  })
}
// The image button is a material slot: what is picked lands on the canvas.
const picking = ref('')
watch(picking, (id) => {
  if (!id) return
  const asset = w.assets.find((item) => item.id === id)
  const size = fitSide(
    asset
      ? { width: asset.width, height: asset.height }
      : { width: 1, height: 1 },
    PICTURE_SIDE,
  )
  addItem({ id: `s:${shortId()}`, asset_id: id, ...size })
  picking.value = ''
})
function resizeOne(key: string, width: number, height: number) {
  if (onCanvas(key)) change(resizeItem(arranged.value, key, width, height))
}
function order(where: 'front' | 'back') {
  if (removable.value.length)
    change(reorder(arranged.value, removable.value, where))
}
// The settings bar edits the one selected text box or board.
const editing = computed(() => {
  if (selection.value.length !== 1) return null
  const item = onCanvas(selection.value[0]!)
  return item && (item.text || item.frame) ? item : null
})
const textEditor = ref<HTMLTextAreaElement>()
function setText(field: keyof TextSpec, value: string | number) {
  const item = editing.value
  if (!item?.text) return
  change(
    updateItem(arranged.value, item.id, (entry) => ({
      ...entry,
      text: { ...entry.text!, [field]: value },
    })),
    field === 'content' ? `text:${item.id}` : '',
  )
}
const boardSize = computed({
  get: () => {
    const frame = editing.value?.frame
    return frame
      ? canvasSizes.findIndex(
          (size) => size.width === frame.width && size.height === frame.height,
        )
      : -1
  },
  set: (index: number) => {
    const item = editing.value
    const size = canvasSizes[index]
    if (!item?.frame || !size) return
    // Same width on the canvas; the height follows the new proportions.
    change(
      updateItem(arranged.value, item.id, (entry) => ({
        ...entry,
        frame: { ...entry.frame!, width: size.width, height: size.height },
        height: Math.round((entry.width * size.height) / size.width),
      })),
    )
  },
})
const boardSizes = canvasSizes.map((size, index) => ({
  value: index,
  label: size.label,
  hint: size.ratio,
}))
function setBackground(color: string) {
  const item = editing.value
  if (item?.frame)
    change(
      updateItem(arranged.value, item.id, (entry) => ({
        ...entry,
        frame: { ...entry.frame!, background: color },
      })),
    )
}
// How much each text box shrank to fit on the canvas (1 = the chosen size).
const fits = reactive(new Map<string, number>())
const exporting = ref('')
async function exportBoard(id: string) {
  const item = onCanvas(id)
  if (!item?.frame || !current.value || exporting.value) return
  const layers = exportLayers(arranged.value, id)
  if (!layers.length) {
    error.value = '画板里还没有图片或文字：先把内容拖到画板上。'
    return
  }
  // Text ending below 12 px on the export is refused by the server; say so now (approximate).
  const scale = item.frame.width / item.width
  if (
    layers.some(({ key }) => {
      const text = onCanvas(key)?.text
      return text && text.size * (fits.get(key) ?? 1) * scale < 12
    })
  ) {
    error.value =
      '有文字在文字框里放不下（导出后会小于 12px）：请放大文字框、调小字号或减少文字。'
    return
  }
  const body = {
    project_id: w.project,
    feature_type: 'COMPOSE',
    conversation_id: current.value.id,
    frame_id: id,
    output: {
      aspect_ratio: ratioOf(item.frame.width, item.frame.height),
      width: item.frame.width,
      height: item.frame.height,
      format: 'png',
      count: 1,
    },
    compose: {
      background: item.frame.background,
      layers: layers.map((entry) => entry.layer),
    },
  }
  if (validateContract('generation-v4-create', body).length) {
    error.value =
      '画板内容超出导出范围（最多 40 个图层，图片不能比画板大太多）。'
    return
  }
  exporting.value = id
  await run(async () => {
    try {
      await w.api('/v4/generation-tasks', {
        ...json(body),
        headers: {
          'Content-Type': 'application/json',
          'Idempotency-Key': crypto.randomUUID(),
        },
      })
      w.notice = '已提交导出，几秒后结果显示在画板右侧。'
      await refresh()
    } finally {
      exporting.value = ''
    }
  })
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
  const pictures = ids.filter((key) => {
    const item = onCanvas(key)
    return !!item && !item.task_id
  })
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
// New results join a saved layout and are saved with it (no undo step).
watch([pieces, saved], () => {
  if (!saved.value) return
  const next = complete(saved.value, pieces.value, anchors.value)
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
  // Double-clicking a text box edits it.
  if (onCanvas(key)?.text) {
    selection.value = [key]
    void nextTick(() => textEditor.value?.select())
    return
  }
  const id = entries.value.get(key)?.artifact?.id ?? key
  const index = images.value.findIndex((item) => item.artifact.id === id)
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
  // Only messages: an export is chosen by hand ("继续修改").
  const tasks = current.value.tasks.filter((task) => !isExport(task))
  for (let turn = tasks.length - 1; turn >= 0; turn--) {
    const artifact = tasks[turn]!.artifacts[0]
    if (tasks[turn]!.status === 'SUCCEEDED' && artifact) {
      edit.value = { id: artifact.id, label: pictureName(tasks[turn]!, 0) }
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
          @resize="resizeOne"
          @command="command"
        >
          <template #default="{ item, near }">
            <template v-for="entry in entryAt(item.key)" :key="entry.key">
              <!-- A board (ADR-20261010-W): what lies on it is exported as one picture. -->
              <div
                v-if="entry.kind === 'frame' && entry.item?.frame"
                class="board-frame"
                data-testid="canvas-frame"
                :style="{ background: entry.item.frame.background }"
              >
                <div class="cell-caption board-caption">
                  <b>画板</b>
                  <span class="muted num"
                    >{{ entry.item.frame.width }} ×
                    {{ entry.item.frame.height }}</span
                  >
                  <button
                    type="button"
                    class="link-btn"
                    data-testid="export-board"
                    :disabled="!!exporting"
                    @click="exportBoard(entry.key)"
                  >
                    <LineIcon name="dl" :size="12" />{{
                      exporting === entry.key ? '提交中…' : '导出图片'
                    }}
                  </button>
                </div>
              </div>
              <CanvasText
                v-else-if="entry.kind === 'text' && entry.item?.text"
                data-testid="canvas-text"
                :text="entry.item.text"
                :width="item.rect.width"
                :height="item.rect.height"
                @fit="fits.set(entry.key, $event)"
              />
              <figure
                v-else-if="entry.kind === 'asset' && entry.item?.asset_id"
                class="tile canvas-tile asset-cell"
                data-testid="canvas-asset"
                :data-selected="selection.includes(entry.key)"
              >
                <PrivateImage
                  v-if="near"
                  :path="`/assets/${entry.item.asset_id}/content`"
                  alt="画布上的素材图"
                  :api="w.api"
                  missing="原图已删除"
                />
              </figure>
              <template v-else-if="entry.task">
                <div
                  class="cell-caption"
                  :class="{ lead: entry.lead }"
                  v-bind="
                    entry.lead
                      ? {
                          'data-testid': isExport(entry.task)
                            ? 'chat-export'
                            : 'chat-turn',
                          'data-status': entry.task.status,
                        }
                      : {}
                  "
                >
                  <template v-if="isExport(entry.task)">
                    <b>导出</b>
                    <span v-if="entry.task.output" class="muted num"
                      >{{ entry.task.output.width }} ×
                      {{ entry.task.output.height }}</span
                    >
                    <span
                      v-if="entry.task.status !== 'SUCCEEDED'"
                      class="turn-status"
                      :data-status="entry.task.status"
                      >{{ statusLabels[entry.task.status] }}</span
                    >
                  </template>
                  <template v-else>
                    <b>第 {{ entry.no }} 条</b>
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
                        :aria-label="`第 ${entry.no} 条详情`"
                        @click="detailId = entry.task.id"
                      >
                        详情
                      </button>
                    </template>
                    <span v-else-if="entry.artifact" class="muted"
                      >图 {{ entry.index + 1 }}</span
                    >
                  </template>
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
                  :data-export="isExport(entry.task) || undefined"
                  :data-copy="entry.copy || undefined"
                  :data-selected="selection.includes(entry.key)"
                >
                  <button
                    type="button"
                    class="open"
                    :aria-label="`选中${pictureName(entry.task, entry.index).replace(' · ', '')}${entry.copy ? '（副本）' : ''}`"
                    :title="
                      entry.artifact
                        ? '单击选中，拖动移动，双击全屏查看'
                        : undefined
                    "
                    @click="$event.detail === 0 && (selection = [entry.key])"
                  >
                    <PrivateImage
                      v-if="entry.artifact && near"
                      :path="`/artifacts/${entry.artifact.id}/content`"
                      :alt="`${pictureName(entry.task, entry.index)} 结果`"
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
                          pictureName(entry.task, entry.index),
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
                    <button
                      type="button"
                      aria-label="下载"
                      title="下载"
                      @click="
                        w.download(
                          entry.artifact.id,
                          `chat-${entry.artifact.id}`,
                        )
                      "
                    >
                      <LineIcon name="dl" :size="13" />
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
          </template>
          <template v-if="editing" #overlay>
            <div
              class="canvas-settings"
              role="group"
              :aria-label="editing.text ? '文字设置' : '画板设置'"
            >
              <template v-if="editing.text">
                <textarea
                  ref="textEditor"
                  class="canvas-settings-text"
                  aria-label="文字内容"
                  rows="2"
                  maxlength="200"
                  :value="editing.text.content"
                  @input="
                    setText(
                      'content',
                      ($event.target as HTMLTextAreaElement).value,
                    )
                  "
                ></textarea>
                <DropSelect
                  :model-value="editing.text.size"
                  label="字号"
                  :options="textSizes"
                  @update:model-value="setText('size', Number($event))"
                />
                <div class="swatches" role="group" aria-label="文字颜色">
                  <button
                    v-for="option in textPalette"
                    :key="option.color"
                    type="button"
                    class="swatch"
                    :title="option.name"
                    :aria-label="`文字 ${option.name}`"
                    :aria-pressed="editing.text.color === option.color"
                    :style="{ background: option.color }"
                    @click="setText('color', option.color)"
                  ></button>
                </div>
                <div class="seg" role="group" aria-label="对齐">
                  <button
                    v-for="option in [
                      { id: 'left', name: '左' },
                      { id: 'center', name: '中' },
                      { id: 'right', name: '右' },
                    ] as const"
                    :key="option.id"
                    type="button"
                    :aria-pressed="editing.text.align === option.id"
                    @click="setText('align', option.id)"
                  >
                    {{ option.name }}
                  </button>
                </div>
                <small class="hint"
                  >画布上为近似显示，导出时用方正兰亭圆简体_中粗，放不下会自动缩小。</small
                >
              </template>
              <template v-else-if="editing.frame">
                <DropSelect
                  v-model="boardSize"
                  label="画板尺寸"
                  :options="boardSizes"
                />
                <div class="swatches" role="group" aria-label="画板背景">
                  <button
                    v-for="option in backgrounds"
                    :key="option.color"
                    type="button"
                    class="swatch"
                    :title="option.name"
                    :aria-label="`画板 ${option.name}`"
                    :aria-pressed="editing.frame.background === option.color"
                    :style="{ background: option.color }"
                    @click="setBackground(option.color)"
                  ></button>
                </div>
                <button
                  type="button"
                  class="btn primary sm"
                  :disabled="!!exporting"
                  @click="exportBoard(editing.id)"
                >
                  <LineIcon name="dl" :size="14" />导出图片
                </button>
                <small class="hint"
                  >导出与画板重叠的图片和文字（超出画板的部分裁掉），不调用
                  AI、不产生费用。</small
                >
              </template>
            </div>
          </template>
          <template v-if="current" #footer>
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
                aria-label="添加文字"
                title="在画布中间加一个文字框"
                @click="addText"
              >
                <LineIcon name="text" /><span class="label">文字</span>
              </button>
              <AssetSlot
                v-model="picking"
                class="canvas-add-image"
                label="图片"
                kind="REFERENCE"
              />
              <button
                type="button"
                class="tool"
                aria-label="添加画板"
                title="加一个画板：画板上的内容可以导出成一张图"
                @click="addBoard"
              >
                <LineIcon name="box" /><span class="label">画板</span>
              </button>
              <button
                type="button"
                class="tool"
                aria-label="复制"
                title="复制所选图片（Ctrl+D）"
                :disabled="!selectedPictures.length"
                @click="duplicateSelection()"
              >
                <LineIcon name="copy" /><span class="label">复制</span>
              </button>
              <button
                type="button"
                class="tool"
                aria-label="从画布移除"
                title="从画布移除（Delete）：图片仍在“我的作品”里"
                :disabled="!removable.length"
                @click="removeSelection"
              >
                <LineIcon name="close" /><span class="label">移除</span>
              </button>
              <button
                type="button"
                class="tool"
                aria-label="置顶"
                title="放到最上层（导出时盖在其他内容上面）"
                :disabled="!removable.length"
                @click="order('front')"
              >
                <LineIcon name="up" /><span class="label">置顶</span>
              </button>
              <button
                type="button"
                class="tool"
                aria-label="置底"
                title="放到最下层"
                :disabled="!removable.length"
                @click="order('back')"
              >
                <LineIcon name="down" /><span class="label">置底</span>
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
