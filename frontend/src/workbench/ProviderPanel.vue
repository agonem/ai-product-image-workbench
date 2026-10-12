<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { json } from '../api/workbench'
import EmptyState from '../components/EmptyState.vue'
import LineIcon from '../components/LineIcon.vue'
import ModalDialog from '../components/ModalDialog.vue'
import { confirmAction } from './confirm'
import {
  kindLabel,
  kindPurposes,
  modelExamples,
  offeredKinds,
  paramSet,
  paramSummary,
  parseParam,
  type ParamValue,
  type Purpose,
} from './modelParameters'

// Admin model catalogue in two levels since ADR-20261012-AB, as in Dify: a model interface holds
// the key, address and proxy setting once; the models under it hold the model id, purpose and
// the official parameters the admin filled in (blank ones are not sent). Models and interfaces
// are edited in place (ADR-20261009-Q); one default model per purpose.
const props = defineProps<{
  api: <T>(path: string, init?: RequestInit) => Promise<T>
}>()
type Interface = {
  id: string
  name: string
  kind: string
  base_url?: string
  api_key_mask: string
  use_proxy: boolean
  created_at: string
}
type Item = {
  id: string
  interface_id: string
  name: string
  provider: string
  model: string
  provider_tag?: string
  enabled: boolean
  default: boolean
  created_at: string
  purpose: Purpose
  /** Text models only: whether it can look at images (ADR-20261012-AB). */
  vision: boolean
  parameters?: Record<string, ParamValue>
}
type Proxy = { configured: boolean; mask?: string; updated_at?: string }
type Listing = {
  default_id: string | null
  interfaces: Interface[]
  items: Item[]
  proxy: Proxy
}
const tab = ref<'models' | 'proxy'>('models')

const busy = ref(false),
  error = ref(''),
  notice = ref('')
const listing = ref<Listing | null>(null)
const dialog = ref<'' | 'interface' | 'model'>('')
const editingInterface = ref<Interface | null>(null)
const editingModel = ref<Item | null>(null)
const owner = ref<Interface | null>(null)
const face = ref({
  name: '',
  kind: 'openrouter',
  base: '',
  key: '',
  proxy: false,
})
const form = ref({
  name: '',
  model: '',
  tag: '',
  enabled: true,
  purpose: 'IMAGE' as Purpose,
  vision: true,
  params: {} as Record<string, string | number>,
})
const proxyUrl = ref('')

const modelsOf = (id: string) =>
  listing.value?.items.filter((item) => item.interface_id === id) ?? []
const thirdParty = computed(() => face.value.kind.endsWith('-compatible'))
const plainHttp = computed(
  () => thirdParty.value && face.value.base.trim().startsWith('http://'),
)
const kindChoices = computed(() => {
  const current = face.value.kind
  return offeredKinds.some((item) => item.id === current)
    ? offeredKinds
    : [...offeredKinds, { id: current, label: kindLabel(current) }]
})
const ownerKind = computed(() => owner.value?.kind ?? 'openrouter')
const purposes = computed(() => kindPurposes(ownerKind.value))
// The official parameters of this model under this interface; unknown models get the
// interface's general list (ADR-20261012-AB).
const set = computed(() =>
  paramSet(ownerKind.value, form.value.model, form.value.purpose),
)
const specs = computed(() => set.value?.parameters ?? [])
const examples = computed(() =>
  modelExamples(ownerKind.value, form.value.purpose),
)
/** Same rule as the server: https anywhere, http only to a private IPv4 address. */
function baseProblem(value: string): string {
  let url: URL
  try {
    url = new URL(value)
  } catch {
    return '接口地址格式不正确，例如 http://10.2.2.110:3000/v1。'
  }
  if (url.username || url.password || url.search || url.hash)
    return '接口地址不能包含账号、查询参数或 #。'
  if (url.protocol === 'https:') return ''
  if (url.protocol !== 'http:') return '接口地址只支持 http 或 https。'
  const parts = url.hostname.split('.').map(Number)
  const ipv4 =
    parts.length === 4 && parts.every((n) => Number.isInteger(n) && n <= 255)
  const intranet =
    ipv4 &&
    (parts[0] === 10 ||
      (parts[0] === 172 && parts[1]! >= 16 && parts[1]! <= 31) ||
      (parts[0] === 192 && parts[1] === 168))
  return intranet
    ? ''
    : 'http 地址只允许内网 IP（10.x、172.16–31.x、192.168.x）；公网地址请用 https。'
}
let alive = true

onMounted(() => void action(load))
onUnmounted(() => {
  alive = false
  face.value.key = proxyUrl.value = ''
})
async function load() {
  listing.value = await props.api<Listing>('/admin/provider-configs')
}
async function action(fn: () => Promise<void>) {
  if (busy.value) return
  busy.value = true
  error.value = ''
  notice.value = ''
  try {
    await fn()
  } catch (cause) {
    if (alive && cause instanceof Error && cause.message !== 'STALE')
      error.value = cause.message
  } finally {
    busy.value = false
    face.value.key = ''
  }
}
function close() {
  dialog.value = ''
  editingInterface.value = editingModel.value = owner.value = null
  face.value.key = ''
}

function openInterface(item: Interface | null = null) {
  editingInterface.value = item
  face.value = {
    name: item?.name ?? '',
    kind: item?.kind ?? 'openrouter',
    base: item?.base_url ?? '',
    key: '',
    proxy: item?.use_proxy ?? false,
  }
  error.value = ''
  dialog.value = 'interface'
}
async function saveInterface() {
  if (thirdParty.value) {
    const problem = baseProblem(face.value.base.trim())
    if (problem) {
      error.value = problem
      return
    }
  }
  const editing = editingInterface.value
  await action(async () => {
    const f = face.value
    const body: Record<string, unknown> = {
      name: f.name.trim(),
      use_proxy: f.proxy,
    }
    if (thirdParty.value) body.base_url = f.base.trim()
    if (!editing || f.key) body.api_key = f.key
    if (editing)
      await props.api(
        `/admin/model-interfaces/${editing.id}/settings`,
        json(body),
      )
    else
      await props.api(
        '/admin/model-interfaces',
        json({ ...body, kind: f.kind }),
      )
    close()
    await load()
    notice.value = editing
      ? `已保存接口「${f.name.trim()}」；接口下的模型和已提交还未完成的任务都按新设置执行。`
      : `已添加接口「${f.name.trim()}」，接下来在它下面添加模型。`
  })
}
async function removeInterface(item: Interface) {
  if (
    !(await confirmAction(
      '删除接口',
      `删除接口「${item.name}」后，它的密钥一并删除，不可恢复。`,
      '删除',
    ))
  )
    return
  await action(async () => {
    await props.api(`/admin/model-interfaces/${item.id}`, { method: 'DELETE' })
    await load()
    notice.value = `已删除接口「${item.name}」。`
  })
}
async function interfaceProxy(item: Interface) {
  await action(async () => {
    await props.api(
      `/admin/model-interfaces/${item.id}/settings`,
      json({ use_proxy: !item.use_proxy }),
    )
    await load()
  })
}

function openModel(within: Interface, item: Item | null = null) {
  owner.value = within
  editingModel.value = item
  const stored = item?.parameters ?? {}
  form.value = {
    name: item?.name ?? '',
    model: item?.model ?? '',
    tag: item?.provider_tag ?? '',
    enabled: item?.enabled ?? true,
    purpose: item?.purpose ?? kindPurposes(within.kind)[0] ?? 'IMAGE',
    vision: item ? item.vision : true,
    params: Object.fromEntries(
      Object.entries(stored).map(([key, value]) => [key, String(value)]),
    ),
  }
  error.value = ''
  dialog.value = 'model'
}
/** The filled-in official parameters, typed; a field outside its range stops the save. */
function chosenParams(): Record<string, ParamValue> | null {
  const chosen: Record<string, ParamValue> = {}
  for (const spec of specs.value) {
    // Vue turns a number field's value into a number; an emptied one is ''.
    const raw = form.value.params[spec.name]
    const value = parseParam(spec, raw === undefined ? '' : String(raw))
    if (value === null) {
      error.value =
        spec.type === 'enum'
          ? `「${spec.label}」的值不在可选范围内。`
          : `「${spec.label}」需为${spec.type === 'integer' ? '整数' : '数字'}，范围 ${spec.min}–${spec.max}。`
      return null
    }
    if (value !== undefined) chosen[spec.name] = value
  }
  return chosen
}
async function saveModel() {
  const within = owner.value
  if (!within) return
  const parameters = chosenParams()
  if (!parameters) return
  const editing = editingModel.value
  await action(async () => {
    const f = form.value
    const body: Record<string, unknown> = {
      name: f.name.trim(),
      model: f.model.trim(),
      enabled: f.enabled,
      parameters,
    }
    if (within.kind === 'openrouter') {
      if (f.tag.trim()) body.provider_tag = f.tag.trim()
      else if (editing?.provider_tag) body.provider_tag = null
    }
    if (f.purpose === 'TEXT') body.vision = f.vision
    if (editing)
      await props.api(
        `/admin/provider-configs/${editing.id}/settings`,
        json(body),
      )
    else
      await props.api(
        '/admin/provider-configs',
        json({ ...body, interface_id: within.id, purpose: f.purpose }),
      )
    close()
    await load()
    notice.value = editing
      ? `已保存「${f.name.trim()}」；已提交还未完成的任务也按新设置执行。`
      : '模型已添加；运营可在生成页选择已启用的出图模型。'
  })
}
async function removeModel(item: Item) {
  if (
    !(await confirmAction(
      '删除模型',
      `删除「${item.name}」后不可恢复。还在排队、生成中或失败待重试的任务会改用默认模型；已完成的图片不受影响。`,
      '删除',
    ))
  )
    return
  await action(async () => {
    await props.api(`/admin/provider-configs/${item.id}`, { method: 'DELETE' })
    await load()
    notice.value = `已删除「${item.name}」。`
  })
}
async function toggle(item: Item) {
  await action(async () => {
    await props.api(
      `/admin/provider-configs/${item.id}/settings`,
      json({ enabled: !item.enabled }),
    )
    await load()
  })
}
async function makeDefault(item: Item) {
  await action(async () => {
    await props.api(`/admin/provider-configs/${item.id}/default`, {
      method: 'POST',
    })
    await load()
    notice.value = `已将「${item.name}」设为默认${item.purpose === 'TEXT' ? '文本' : '出图'}模型。`
  })
}
async function saveProxy() {
  await action(async () => {
    await props.api('/admin/network-proxy', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ proxy_url: proxyUrl.value.trim() }),
    })
    proxyUrl.value = ''
    await load()
    notice.value = '代理已保存；只用于勾选了“走代理”的接口。'
  })
}
async function clearProxy() {
  if (
    !(await confirmAction(
      '清除代理',
      '清除后，勾选了“走代理”的接口将改为直连。',
      '清除',
    ))
  )
    return
  await action(async () => {
    await props.api('/admin/network-proxy', { method: 'DELETE' })
    await load()
    notice.value = '代理已清除。'
  })
}
const purposeLabel = (purpose: Purpose) =>
  purpose === 'TEXT' ? '文本（看图分析、魔法棒）' : '出图（生成页可选）'
</script>

<template>
  <div class="page-head">
    <div class="intro">
      <h1>模型配置</h1>
      <p>
        先添加模型接口（填一次密钥），再在接口下添加模型。生成时商品图与赠品图会作为参考图发送到所选模型的接口；密钥与代理加密保存，只显示掩码。
      </p>
    </div>
    <span class="spacer"></span>
    <button
      type="button"
      class="btn primary"
      :disabled="busy"
      @click="openInterface()"
    >
      <LineIcon name="plus" :size="14" />添加接口
    </button>
  </div>
  <div
    class="tabs"
    role="group"
    aria-label="配置分类"
    style="justify-self: start"
  >
    <button
      type="button"
      :aria-pressed="tab === 'models'"
      @click="tab = 'models'"
    >
      模型接口
    </button>
    <button
      type="button"
      :aria-pressed="tab === 'proxy'"
      @click="tab = 'proxy'"
    >
      网络代理
    </button>
  </div>
  <p v-if="error && !dialog" class="banner error" role="alert">
    <LineIcon name="alert" :size="14" />{{ error }}
  </p>
  <p v-if="notice" class="banner ok" role="status">
    <LineIcon name="check" :size="14" />{{ notice }}
  </p>

  <template v-if="tab === 'models'">
    <section
      v-for="iface in listing?.interfaces ?? []"
      :key="iface.id"
      class="card interface-card"
      :aria-label="`接口：${iface.name}`"
      data-testid="interface-card"
    >
      <div class="card-head">
        <h2>
          <LineIcon name="cpu" />{{ iface.name
          }}<span class="tag">{{ kindLabel(iface.kind) }}</span>
        </h2>
        <small class="muted interface-meta">
          <span v-if="iface.base_url" class="mono">{{ iface.base_url }} · </span
          >密钥 <span class="mono">{{ iface.api_key_mask }}</span> ·
          {{ modelsOf(iface.id).length }} 个模型
        </small>
        <span class="spacer"></span>
        <label class="proxy-switch"
          ><button
            type="button"
            class="switch"
            role="switch"
            :aria-checked="iface.use_proxy"
            :aria-label="`${iface.name} 走代理`"
            :disabled="busy"
            @click="interfaceProxy(iface)"
          ></button
          >走代理</label
        >
        <button
          type="button"
          class="btn"
          :disabled="busy"
          :aria-label="`在「${iface.name}」下添加模型`"
          @click="openModel(iface)"
        >
          <LineIcon name="plus" :size="14" />添加模型
        </button>
        <button
          type="button"
          class="link-btn"
          :disabled="busy"
          :aria-label="`编辑接口「${iface.name}」`"
          @click="openInterface(iface)"
        >
          编辑接口
        </button>
        <button
          type="button"
          class="link-btn danger"
          :disabled="busy || modelsOf(iface.id).length > 0"
          :title="
            modelsOf(iface.id).length ? '接口下还有模型，请先删除这些模型' : ''
          "
          :aria-label="`删除接口「${iface.name}」`"
          @click="removeInterface(iface)"
        >
          删除接口
        </button>
      </div>
      <div v-if="modelsOf(iface.id).length" class="table-wrap">
        <table class="table">
          <thead>
            <tr>
              <th>名称</th>
              <th>模型标识</th>
              <th>参数</th>
              <th>启用</th>
              <th style="text-align: right">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="item in modelsOf(iface.id)"
              :key="item.id"
              data-testid="model-row"
            >
              <td>
                <span class="name"
                  >{{ item.name
                  }}<span v-if="item.purpose === 'TEXT'" class="tag">文本</span
                  ><span
                    v-if="item.purpose === 'TEXT'"
                    class="tag"
                    :class="item.vision ? 'ok' : ''"
                    >{{ item.vision ? '能看图' : '不能看图' }}</span
                  ><span v-if="item.default" class="tag accent"
                    ><LineIcon name="star" :size="11" />默认</span
                  ></span
                >
              </td>
              <td>
                <span class="mono">{{ item.model }}</span>
                <small v-if="item.provider_tag">
                  · {{ item.provider_tag }}</small
                >
              </td>
              <td>
                <small class="params" data-testid="model-params">{{
                  paramSummary(
                    iface.kind,
                    item.model,
                    item.purpose,
                    item.parameters,
                  ) || '全部按官方默认'
                }}</small>
              </td>
              <td>
                <button
                  type="button"
                  class="switch"
                  role="switch"
                  :aria-checked="item.enabled"
                  :aria-label="`${item.name} 启用`"
                  :disabled="busy"
                  @click="toggle(item)"
                ></button>
              </td>
              <td>
                <div class="actions">
                  <button
                    v-if="!item.default"
                    type="button"
                    class="link-btn"
                    :disabled="busy || !item.enabled"
                    :title="item.enabled ? '' : '先启用再设为默认'"
                    @click="makeDefault(item)"
                  >
                    设为默认
                  </button>
                  <button
                    type="button"
                    class="link-btn"
                    :disabled="busy"
                    @click="openModel(iface, item)"
                  >
                    编辑
                  </button>
                  <button
                    type="button"
                    class="link-btn danger"
                    :disabled="busy || item.default"
                    :title="
                      item.default
                        ? '默认模型不能删除，请先把其他模型设为默认'
                        : ''
                    "
                    :aria-label="`删除 ${item.name}`"
                    @click="removeModel(item)"
                  >
                    删除
                  </button>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <p v-else class="hint card-body">
        这个接口下还没有模型，点右上角“添加模型”。
      </p>
    </section>
    <section
      v-if="listing && !listing.interfaces.length"
      class="card"
      aria-label="模型接口"
    >
      <EmptyState art="model"
        >还没有模型接口。点击右上角“添加接口”，选择接口类型并填写密钥，再在接口下添加模型。</EmptyState
      >
    </section>
  </template>

  <section v-show="tab === 'proxy'" class="card" aria-label="网络代理">
    <div class="card-head">
      <h2><LineIcon name="globe" />网络代理</h2>
      <span
        class="tag"
        :class="listing?.proxy.configured ? 'ok' : ''"
        data-testid="proxy-state"
        ><span class="dot"></span
        >{{ listing?.proxy.configured ? '已设置' : '未设置' }}</span
      >
    </div>
    <form class="card-body narrow" @submit.prevent="saveProxy">
      <p v-if="listing?.proxy.configured" class="hint">
        当前代理：<span class="mono">{{ listing.proxy.mask }}</span>
      </p>
      <label class="form-row"
        ><span>代理地址</span
        ><input
          aria-label="代理地址"
          aria-describedby="proxy-hint"
          v-model="proxyUrl"
          autocomplete="off"
          maxlength="300"
          placeholder="http://用户名:密码@代理地址:端口"
          required
          :disabled="busy"
        /><small id="proxy-hint"
          >只用于勾选了“走代理”的接口；支持 http /
          https，可带账号密码，不能带路径。本服务器访问 OpenAI、Gemini
          官方接口需要代理。</small
        ></label
      >
      <div class="inline-fields">
        <button class="btn primary" :disabled="busy">保存代理</button>
        <button
          v-if="listing?.proxy.configured"
          type="button"
          class="btn danger"
          :disabled="busy"
          @click="clearProxy"
        >
          清除代理
        </button>
      </div>
    </form>
  </section>

  <ModalDialog
    v-if="dialog === 'interface'"
    :title="
      editingInterface ? `编辑接口「${editingInterface.name}」` : '添加接口'
    "
    @close="close"
  >
    <form id="interface-form" class="form-grid" @submit.prevent="saveInterface">
      <p v-if="error" class="banner error" role="alert">
        <LineIcon name="alert" :size="14" />{{ error }}
      </p>
      <label class="form-row"
        ><span>接口类型</span
        ><select
          v-model="face.kind"
          aria-label="接口类型"
          :disabled="busy || !!editingInterface"
        >
          <option v-for="item in kindChoices" :key="item.id" :value="item.id">
            {{ item.label }}
          </option>
        </select></label
      >
      <label class="form-row"
        ><span>接口名称</span
        ><input
          v-model="face.name"
          aria-label="接口名称"
          maxlength="40"
          :placeholder="kindLabel(face.kind)"
          required
          :disabled="busy"
      /></label>
      <label v-if="thirdParty" class="form-row"
        ><span>接口地址</span
        ><input
          v-model="face.base"
          aria-label="接口地址"
          placeholder="http://10.2.2.110:3000/v1"
          maxlength="300"
          required
          :disabled="busy"
      /></label>
      <p v-if="plainHttp" class="banner warn" role="note">
        <LineIcon name="alert" :size="14" />http 地址不加密：API Key
        与商品图会在内网明文传输。
      </p>
      <p v-if="face.kind === 'deepseek'" class="hint">
        DeepSeek 官方接口只能添加文本模型（看图分析、魔法棒）。
      </p>
      <label class="form-row"
        ><span>API Key</span
        ><input
          v-model="face.key"
          aria-label="API Key"
          aria-describedby="api-key-hint"
          type="password"
          autocomplete="new-password"
          :required="!editingInterface"
          :placeholder="
            editingInterface
              ? `留空则不修改（当前 ${editingInterface.api_key_mask}）`
              : ''
          "
          :disabled="busy"
        /><small id="api-key-hint"
          >接口下所有模型共用这个密钥；保存后不可查看，只显示掩码。</small
        ></label
      >
      <label class="check"
        ><input
          v-model="face.proxy"
          type="checkbox"
          :disabled="busy"
        />通过网络代理访问</label
      >
    </form>
    <template #footer>
      <button type="button" class="btn" @click="close">取消</button>
      <button
        type="submit"
        form="interface-form"
        class="btn primary"
        :disabled="busy"
      >
        保存接口
      </button>
    </template>
  </ModalDialog>

  <ModalDialog
    v-if="dialog === 'model' && owner"
    :title="editingModel ? `编辑「${editingModel.name}」` : '添加模型'"
    @close="close"
  >
    <form id="model-form" class="form-grid" @submit.prevent="saveModel">
      <p class="hint">
        接口：{{ owner.name }}（{{ kindLabel(owner.kind) }}）<template
          v-if="editingModel"
          >。修改后立即生效：已提交还未完成、以及失败后重试的任务也按新设置执行。</template
        >
      </p>
      <p v-if="error" class="banner error" role="alert">
        <LineIcon name="alert" :size="14" />{{ error }}
      </p>
      <label class="form-row"
        ><span>显示名称</span
        ><input
          aria-label="显示名称"
          aria-describedby="model-name-hint"
          v-model="form.name"
          maxlength="40"
          placeholder="例如：主力出图"
          required
          :disabled="busy"
        /><small id="model-name-hint"
          >运营在生成页看到的名称，最多 40 字。</small
        ></label
      >
      <label class="form-row"
        ><span>用途</span
        ><select
          v-model="form.purpose"
          aria-label="用途"
          :disabled="busy || !!editingModel || purposes.length < 2"
        >
          <option v-for="purpose in purposes" :key="purpose" :value="purpose">
            {{ purposeLabel(purpose) }}
          </option>
        </select></label
      >
      <label class="form-row"
        ><span>模型标识</span
        ><input
          aria-label="模型标识"
          aria-describedby="model-id-hint"
          v-model="form.model"
          :placeholder="examples[0] ?? ''"
          list="model-examples"
          maxlength="200"
          required
          :disabled="busy"
        /><datalist id="model-examples">
          <option v-for="example in examples" :key="example" :value="example" />
        </datalist>
        <small id="model-id-hint"
          >以接口方当前文档为准，示例仅供参考。</small
        ></label
      >
      <label v-if="owner.kind === 'openrouter'" class="form-row"
        ><span>{{
          form.purpose === 'TEXT'
            ? '路由标签（可留空）'
            : '路由标签（provider_tag）'
        }}</span
        ><input
          v-model="form.tag"
          aria-label="路由标签"
          :placeholder="
            form.purpose === 'TEXT' ? '留空由 OpenRouter 自动选择' : 'openai'
          "
          maxlength="100"
          :required="form.purpose !== 'TEXT'"
          :disabled="busy"
      /></label>
      <label v-if="form.purpose === 'TEXT'" class="check"
        ><input
          v-model="form.vision"
          type="checkbox"
          :disabled="busy"
        />能看图（对话消息用它先看图分析；不能看图时跳过分析直接出图）</label
      >
      <fieldset v-if="specs.length" class="params-group">
        <legend>模型参数（官方参数，不填就按官方默认）</legend>
        <label
          v-for="spec in specs"
          :key="spec.name"
          class="form-row"
          :data-param="spec.name"
          ><span
            >{{ spec.label
            }}<small class="mono param-name">{{ spec.name }}</small></span
          ><select
            v-if="spec.type === 'enum'"
            v-model="form.params[spec.name]"
            :aria-label="spec.label"
            :disabled="busy"
          >
            <option value="">
              不填（官方默认：{{ spec.official_default }}）
            </option>
            <option
              v-for="option in spec.values"
              :key="option.value"
              :value="option.value"
            >
              {{ option.label }}（{{ option.value }}）
            </option>
          </select>
          <input
            v-else
            v-model="form.params[spec.name]"
            :aria-label="spec.label"
            type="number"
            inputmode="decimal"
            :min="spec.min"
            :max="spec.max"
            :step="spec.type === 'integer' ? 1 : 'any'"
            :placeholder="`不填 = 官方默认：${spec.official_default}`"
            :disabled="busy"
          /><small v-if="spec.help">{{ spec.help }}</small></label
        >
        <small v-if="set?.help">{{ set.help }}</small>
        <small
          >由系统按每次任务决定的参数（提示词、图片、比例、张数、清晰度）不在这里设置；清晰度在生成页选择。</small
        >
      </fieldset>
      <p v-else-if="form.model.trim()" class="hint">
        该模型没有可填写的官方参数。
      </p>
      <label class="check"
        ><input v-model="form.enabled" type="checkbox" :disabled="busy" />{{
          editingModel ? '启用' : '保存后启用'
        }}</label
      >
    </form>
    <template #footer>
      <button type="button" class="btn" @click="close">取消</button>
      <button
        type="submit"
        form="model-form"
        class="btn primary"
        :disabled="busy"
      >
        保存模型
      </button>
    </template>
  </ModalDialog>
</template>

<style scoped>
.interface-card + .interface-card {
  margin-top: 0;
}
.interface-meta {
  min-width: 0;
  overflow-wrap: anywhere;
}
.proxy-switch {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  color: var(--ink-2);
}
.param-name {
  margin-left: 6px;
  color: var(--ink-3);
  font-weight: 400;
}
</style>
