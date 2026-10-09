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
import ImageViewer from '../components/ImageViewer.vue'
import LineIcon from '../components/LineIcon.vue'
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
const stream = ref<HTMLElement>()
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
async function scrollDown() {
  await nextTick()
  stream.value?.scrollTo({ top: stream.value.scrollHeight })
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
      await scrollDown()
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
      await scrollDown()
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
      <div ref="stream" class="chat-stream" data-testid="chat-stream">
        <template v-if="current?.tasks.length">
          <article
            v-for="(task, turn) in current.tasks"
            :key="task.id"
            class="turn"
            data-testid="chat-turn"
            :data-status="task.status"
          >
            <div class="bubble user">
              <span v-if="task.agent" class="agent-tag"
                ><AgentAvatar
                  :agent="
                    agents.find((item) => item.id === task.agent?.id) ?? {
                      id: task.agent.id,
                      name: task.agent.name ?? '默认设计师',
                    }
                  "
                  :size="18" />{{ task.agent.name ?? '默认设计师'
                }}<LineIcon
                  v-if="task.agent.rewrite"
                  name="wand"
                  :size="12"
                  aria-label="已开魔法棒"
              /></span>
              <p>{{ task.request?.prompt }}</p>
              <div class="refs">
                <span v-if="task.request?.edit_artifact_id" class="ref edit">
                  <PrivateImage
                    :path="`/artifacts/${task.request.edit_artifact_id}/content`"
                    alt="修改对象"
                    :api="w.api"
                    missing="已删除"
                  /><small>修改</small>
                </span>
                <span class="ref">
                  <PrivateImage
                    :path="`/assets/${task.request?.product_asset_id}/content`"
                    alt="商品图"
                    :api="w.api"
                    missing="已删除"
                  /><small>商品图</small>
                </span>
                <span
                  v-for="(id, index) in references(task)"
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
            </div>
            <div class="bubble ai">
              <div class="ai-head">
                <LineIcon name="spark" :size="14" />
                <span>{{ modelName(task) }}</span>
                <span v-if="task.output" class="num"
                  >{{ task.output.width }} × {{ task.output.height }}</span
                >
                <span class="status" :data-status="task.status">{{
                  statusLabels[task.status]
                }}</span>
              </div>
              <details
                v-if="task.agent?.rewritten"
                class="rewritten"
                open
                data-testid="rewritten"
              >
                <summary>
                  <LineIcon name="wand" :size="13" />{{
                    task.agent.name ?? '默认设计师'
                  }}
                  {{ task.analysis ? '看图改写' : '改写' }}
                </summary>
                <p>{{ task.agent.rewritten }}</p>
              </details>
              <!-- Look first, then draw (ADR-20261009-P): what the text model saw. -->
              <details
                v-else-if="task.analysis?.text"
                class="rewritten"
                open
                data-testid="analysis"
              >
                <summary><LineIcon name="spark" :size="13" />看图分析</summary>
                <p>{{ task.analysis.text }}</p>
              </details>
              <p
                v-else-if="
                  (task.agent?.rewrite || task.analysis) &&
                  (task.status === 'QUEUED' || task.status === 'RUNNING')
                "
                class="hint"
              >
                {{
                  task.agent?.rewrite
                    ? `正在按${task.agent.name ?? '默认设计师'}的设定${task.analysis ? '看图并' : ''}改写需求…`
                    : '正在看图分析，写清每张图的细节后再出图…'
                }}
              </p>
              <div
                v-if="task.status === 'QUEUED' || task.status === 'RUNNING'"
                class="ai-wait"
                role="status"
              >
                <span class="spinner"></span>正在生成，通常需要 20–40 秒…
              </div>
              <div v-else-if="task.status === 'FAILED'" class="ai-fail">
                <LineIcon name="alert" :size="14" />
                <span>{{ task.error?.message }}（{{ task.error?.code }}）</span>
                <button type="button" class="btn sm" @click="retry(task)">
                  <LineIcon name="redo" :size="14" />重试
                </button>
              </div>
              <div v-else class="ai-images">
                <figure
                  v-for="(artifact, index) in task.artifacts"
                  :key="artifact.id"
                  :class="{ chosen: edit?.id === artifact.id }"
                  data-testid="chat-image"
                >
                  <button
                    type="button"
                    class="zoom"
                    :aria-label="`放大第 ${turn + 1} 条图 ${index + 1}`"
                    @click="
                      viewing = images.findIndex(
                        (item) => item.artifact.id === artifact.id,
                      )
                    "
                  >
                    <PrivateImage
                      :path="`/artifacts/${artifact.id}/content`"
                      :alt="`第 ${turn + 1} 条结果 ${index + 1}`"
                      :api="w.api"
                    />
                  </button>
                  <figcaption>
                    <button
                      type="button"
                      class="link-btn"
                      @click="
                        chooseEdit(
                          artifact.id,
                          `第 ${turn + 1} 条 · 图 ${index + 1}`,
                        )
                      "
                    >
                      <LineIcon name="edit" :size="13" />继续修改
                    </button>
                    <button
                      type="button"
                      class="link-btn"
                      @click="w.download(artifact.id, `chat-${artifact.id}`)"
                    >
                      <LineIcon name="dl" :size="13" />下载
                    </button>
                  </figcaption>
                </figure>
              </div>
            </div>
          </article>
        </template>
        <div v-else class="chat-empty">
          <EmptyState v-if="loading">读取对话…</EmptyState>
          <template v-else>
            <h2>想生成什么样的图？</h2>
            <p>
              选择商品图，用自己的话描述画面；生成后可以接着说要怎么改，比如“背景换成浅蓝色”“加一束花”。
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
          </template>
        </div>
      </div>

      <form class="composer" @submit.prevent="send">
        <p v-if="error" class="banner error" role="alert">
          <LineIcon name="alert" :size="14" />{{ error }}
        </p>
        <p v-if="pending" class="banner warn">
          上次发送结果不确定，再点“发送”会用原请求重发，不会重复生成。
        </p>
        <div class="composer-assets">
          <AssetSlot v-model="composer.product" label="商品图" kind="PRODUCT" />
          <AssetSlot v-model="composer.ref1" label="参考图1" kind="REFERENCE" />
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
        <p
          v-if="composer.ref1 || edit"
          class="hint names"
          data-testid="image-names"
        >
          描述里用图片下方的名称指代图片（{{
            imageNames
          }}），例如“在参考图1的基础上，把商品图作为赠品加进去”。
        </p>
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
          <small class="hint guard" data-testid="guard"
            >自动要求：商品外形、颜色、Logo、包装文字和数量不变；不在图里生成文字；{{
              textModel ? '先看图分析再出图' : '未配置文本模型，不做看图分析'
            }}</small
          >
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
