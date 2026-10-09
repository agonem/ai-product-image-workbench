<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { json } from '../api/workbench'
import EmptyState from '../components/EmptyState.vue'
import LineIcon from '../components/LineIcon.vue'
import ModalDialog from '../components/ModalDialog.vue'
import { confirmAction } from './confirm'
import { providerNames } from './model'
import { paramSpecs, paramSummary } from './modelParameters'

// Admin model catalogue (ADR-20260929-C): several models, one default, per-model proxy;
// third-party endpoints in the OpenAI or Gemini format again since ADR-20260930-E. Since
// ADR-20261009-Q a model is edited in place (with its parameters) and can be deleted.
const props = defineProps<{
  api: <T>(path: string, init?: RequestInit) => Promise<T>
}>()
type Provider =
  | 'openrouter'
  | 'openai'
  | 'gemini'
  | 'openai-compatible'
  | 'gemini-compatible'
type Item = {
  id: string
  name: string
  provider: Provider
  model: string
  provider_tag?: string
  base_url?: string
  api_key_mask: string
  enabled: boolean
  use_proxy: boolean
  default: boolean
  created_at: string
  /** IMAGE draws pictures; TEXT rewrites briefs for agents (ADR-20261008-L). */
  purpose?: 'IMAGE' | 'TEXT'
  /** Stored parameters such as quality or resolution (ADR-20261009-Q). */
  parameters?: Record<string, string>
}
type Proxy = { configured: boolean; mask?: string; updated_at?: string }
type Listing = { default_id: string | null; items: Item[]; proxy: Proxy }
// Model names are examples only; the vendor's current model list is authoritative.
const types: { id: Provider; model: string; base?: string }[] = [
  { id: 'openrouter', model: 'openai/gpt-image-2' },
  { id: 'openai', model: 'gpt-image-2' },
  { id: 'gemini', model: 'gemini-2.5-flash-image' },
  {
    id: 'openai-compatible',
    model: 'gpt-image-2',
    base: 'http://10.2.2.110:3000/v1',
  },
  {
    id: 'gemini-compatible',
    model: 'gemini-2.5-flash-image',
    base: 'https://relay.example.com',
  },
]
const tab = ref<'models' | 'proxy'>('models')

const busy = ref(false),
  error = ref(''),
  notice = ref('')
const listing = ref<Listing | null>(null)
const dialog = ref<'' | 'create' | 'edit' | 'key'>('')
const target = ref<Item | null>(null)
const form = ref({
  name: '',
  provider: 'openrouter' as Provider,
  model: '',
  tag: '',
  base: '',
  key: '',
  proxy: false,
  enabled: true,
  purpose: 'IMAGE' as 'IMAGE' | 'TEXT',
  params: {} as Record<string, string>,
})
const proxyUrl = ref('')
// The parameters this model id supports; unknown models have none.
const specs = computed(() => paramSpecs(form.value.model, form.value.purpose))
const selectedType = computed(
  () => types.find((t) => t.id === form.value.provider)!,
)
const thirdParty = computed(() => form.value.provider.endsWith('-compatible'))
const plainHttp = computed(
  () => thirdParty.value && form.value.base.trim().startsWith('http://'),
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
  form.value.key = proxyUrl.value = ''
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
    form.value.key = ''
  }
}
function open(kind: 'create' | 'edit' | 'key', item: Item | null = null) {
  target.value = item
  const editing = kind === 'edit' && item
  form.value = {
    name: item?.name ?? '',
    provider: editing ? item.provider : 'openrouter',
    model: editing ? item.model : '',
    tag: editing ? (item.provider_tag ?? '') : '',
    base: editing ? (item.base_url ?? '') : '',
    key: '',
    proxy: editing ? item.use_proxy : false,
    enabled: editing ? item.enabled : true,
    purpose: editing ? (item.purpose ?? 'IMAGE') : 'IMAGE',
    params: editing ? { ...(item.parameters ?? {}) } : {},
  }
  error.value = ''
  dialog.value = kind
}
function close() {
  dialog.value = ''
  target.value = null
  form.value.key = ''
}
/** Only the parameters this model supports, and only those set to a value. */
function chosenParams(): Record<string, string> {
  return Object.fromEntries(
    Object.entries(form.value.params).filter(
      ([key, value]) => value && key in specs.value,
    ),
  )
}
async function save() {
  if (thirdParty.value) {
    const problem = baseProblem(form.value.base.trim())
    if (problem) {
      error.value = problem
      return
    }
  }
  const editing = dialog.value === 'edit' ? target.value : null
  await action(async () => {
    const f = form.value
    const body: Record<string, unknown> = {
      name: f.name.trim(),
      provider: f.provider,
      model: f.model.trim(),
      enabled: f.enabled,
      use_proxy: f.proxy,
      parameters: chosenParams(),
    }
    if (!editing || f.key) body.api_key = f.key
    if (!editing && f.purpose === 'TEXT') body.purpose = 'TEXT'
    if (f.provider === 'openrouter' && (f.tag.trim() || f.purpose !== 'TEXT'))
      body.provider_tag = f.tag.trim()
    if (thirdParty.value) body.base_url = f.base.trim()
    if (editing)
      await props.api(
        `/admin/provider-configs/${editing.id}/settings`,
        json(body),
      )
    else await props.api('/admin/provider-configs', json(body))
    close()
    await load()
    notice.value = editing
      ? `已保存「${f.name.trim()}」；已提交还未完成的任务也按新设置执行。`
      : '模型已添加；运营可在生成页选择已启用的模型。'
  })
}
async function remove(item: Item) {
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
async function rotate() {
  const item = target.value
  if (!item) return
  await action(async () => {
    await props.api(
      `/admin/provider-configs/${item.id}/key`,
      json({ api_key: form.value.key }),
    )
    close()
    await load()
    notice.value = '密钥已更换；已提交还未完成的任务也会使用新密钥。'
  })
}
async function settings(item: Item, change: Record<string, boolean>) {
  await action(async () => {
    await props.api(`/admin/provider-configs/${item.id}/settings`, json(change))
    await load()
  })
}
async function makeDefault(item: Item) {
  await action(async () => {
    await props.api(`/admin/provider-configs/${item.id}/default`, {
      method: 'POST',
    })
    await load()
    notice.value = `已将「${item.name}」设为默认模型。`
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
    notice.value = '代理已保存；只用于勾选了“走代理”的模型。'
  })
}
async function clearProxy() {
  if (
    !(await confirmAction(
      '清除代理',
      '清除后，勾选了“走代理”的模型将改为直连。',
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
</script>

<template>
  <div class="page-head">
    <div class="intro">
      <h1>模型配置</h1>
      <p>
        生成时商品图与赠品图会作为参考图发送到所选模型的接口；密钥与代理加密保存，只显示掩码。
      </p>
    </div>
    <span class="spacer"></span>
    <button
      type="button"
      class="btn primary"
      :disabled="busy"
      @click="open('create')"
    >
      <LineIcon name="plus" :size="14" />添加模型
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
      模型
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

  <section v-show="tab === 'models'" class="card" aria-label="模型列表">
    <div class="card-head">
      <h2><LineIcon name="cpu" />模型</h2>
      <span class="muted num">{{ listing?.items.length ?? 0 }} 个</span>
    </div>
    <div v-if="listing?.items.length" class="table-wrap">
      <table class="table">
        <thead>
          <tr>
            <th>名称</th>
            <th>接口</th>
            <th>模型标识</th>
            <th>密钥</th>
            <th>走代理</th>
            <th>启用</th>
            <th style="text-align: right">操作</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="item in listing.items"
            :key="item.id"
            data-testid="model-row"
          >
            <td>
              <span class="name"
                >{{ item.name
                }}<span v-if="item.purpose === 'TEXT'" class="tag"
                  >文本·智能体改写</span
                ><span v-if="item.default" class="tag accent"
                  ><LineIcon name="star" :size="11" />默认</span
                ></span
              >
            </td>
            <td>{{ providerNames[item.provider] ?? item.provider }}</td>
            <td>
              <span class="mono">{{ item.model }}</span>
              <small v-if="item.provider_tag"> · {{ item.provider_tag }}</small>
              <small v-if="item.base_url" class="mono">
                · {{ item.base_url }}</small
              >
              <small
                v-if="
                  paramSummary(
                    item.model,
                    item.purpose ?? 'IMAGE',
                    item.parameters,
                  )
                "
                class="params"
                data-testid="model-params"
                ><br />{{
                  paramSummary(
                    item.model,
                    item.purpose ?? 'IMAGE',
                    item.parameters,
                  )
                }}</small
              >
            </td>
            <td class="mono">{{ item.api_key_mask }}</td>
            <td>
              <button
                type="button"
                class="switch"
                role="switch"
                :aria-checked="item.use_proxy"
                :aria-label="`${item.name} 走代理`"
                :disabled="busy"
                @click="settings(item, { use_proxy: !item.use_proxy })"
              ></button>
            </td>
            <td>
              <button
                type="button"
                class="switch"
                role="switch"
                :aria-checked="item.enabled"
                :aria-label="`${item.name} 启用`"
                :disabled="busy"
                @click="settings(item, { enabled: !item.enabled })"
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
                  @click="open('key', item)"
                >
                  更换密钥
                </button>
                <button
                  type="button"
                  class="link-btn"
                  :disabled="busy"
                  @click="open('edit', item)"
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
                  @click="remove(item)"
                >
                  删除
                </button>
              </div>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
    <EmptyState v-else-if="listing" art="model"
      >还没有模型。点击右上角“添加模型”，填写接口类型、模型标识和密钥。</EmptyState
    >
  </section>

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
          >只用于勾选了“走代理”的模型；支持 http /
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
    v-if="dialog === 'create' || (dialog === 'edit' && target)"
    :title="dialog === 'edit' ? `编辑「${target?.name}」` : '添加模型'"
    @close="close"
  >
    <form id="model-form" class="form-grid" @submit.prevent="save">
      <p v-if="dialog === 'edit'" class="hint">
        修改后立即生效：已提交还未完成、以及失败后重试的任务也按新设置执行。
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
          :disabled="busy || dialog === 'edit'"
        >
          <option value="IMAGE">出图（生成页可选）</option>
          <option value="TEXT">文本（对话生图的魔法棒改写）</option>
        </select></label
      >
      <label class="form-row"
        ><span>接口类型</span
        ><select v-model="form.provider" :disabled="busy">
          <option v-for="item in types" :key="item.id" :value="item.id">
            {{ providerNames[item.id] }}
          </option>
        </select></label
      >
      <label class="form-row"
        ><span>模型标识</span
        ><input
          aria-label="模型标识"
          aria-describedby="model-id-hint"
          v-model="form.model"
          :placeholder="selectedType.model"
          maxlength="200"
          required
          :disabled="busy"
        /><small id="model-id-hint"
          >以接口方当前文档为准，示例仅供参考。</small
        ></label
      >
      <label v-if="thirdParty" class="form-row"
        ><span>接口地址</span
        ><input
          v-model="form.base"
          aria-label="接口地址"
          :placeholder="selectedType.base"
          maxlength="300"
          required
          :disabled="busy"
      /></label>
      <p v-if="plainHttp" class="banner warn" role="note">
        <LineIcon name="alert" :size="14" />http 地址不加密：API Key
        与商品图会在内网明文传输。
      </p>
      <label v-if="form.provider === 'openrouter'" class="form-row"
        ><span>{{
          form.purpose === 'TEXT'
            ? '路由标签（可留空）'
            : '路由标签（provider_tag）'
        }}</span
        ><input
          v-model="form.tag"
          :placeholder="
            form.purpose === 'TEXT' ? '留空由 OpenRouter 自动选择' : 'openai'
          "
          maxlength="100"
          :required="form.purpose !== 'TEXT'"
          :disabled="busy"
        /><small v-if="form.purpose === 'TEXT'"
          >文本模型只发送文字描述；填了会优先使用该服务商，不支持时自动换其他服务商。</small
        ></label
      >
      <label class="form-row"
        ><span>API Key</span
        ><input
          aria-label="API Key"
          aria-describedby="api-key-hint"
          v-model="form.key"
          type="password"
          autocomplete="new-password"
          :required="dialog !== 'edit'"
          :placeholder="
            dialog === 'edit'
              ? `留空则不修改（当前 ${target?.api_key_mask}）`
              : ''
          "
          :disabled="busy"
        /><small id="api-key-hint">保存后不可查看，只显示掩码。</small></label
      >
      <fieldset v-if="Object.keys(specs).length" class="params-group">
        <legend>模型参数</legend>
        <label v-for="(spec, key) in specs" :key="key" class="form-row"
          ><span>{{ spec.label }}</span
          ><select
            v-model="form.params[key]"
            :aria-label="spec.label"
            :disabled="busy"
          >
            <option value="">不指定（模型默认）</option>
            <option
              v-for="option in spec.values"
              :key="option.value"
              :value="option.value"
            >
              {{ option.label }}
            </option>
          </select></label
        >
        <small
          >选项按该模型在 OpenRouter
          公布的能力整理；生成页选“高清”时会在此基础上调高。</small
        >
      </fieldset>
      <p v-else-if="form.model.trim()" class="hint">该模型没有可调参数。</p>
      <label class="check"
        ><input
          v-model="form.proxy"
          type="checkbox"
          :disabled="busy"
        />通过网络代理访问</label
      >
      <label class="check"
        ><input v-model="form.enabled" type="checkbox" :disabled="busy" />{{
          dialog === 'edit' ? '启用' : '保存后启用'
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

  <ModalDialog
    v-if="dialog === 'key' && target"
    :title="`更换「${target.name}」的密钥`"
    @close="close"
  >
    <form id="key-form" class="form-grid" @submit.prevent="rotate">
      <p v-if="error" class="banner error" role="alert">
        <LineIcon name="alert" :size="14" />{{ error }}
      </p>
      <p class="hint">
        当前密钥 <span class="mono">{{ target.api_key_mask }}</span
        >。更换后新任务使用新密钥，名称、默认与代理设置不变。
      </p>
      <label class="form-row"
        ><span>新的 API Key</span
        ><input
          v-model="form.key"
          type="password"
          autocomplete="new-password"
          required
          :disabled="busy"
      /></label>
    </form>
    <template #footer>
      <button type="button" class="btn" @click="close">取消</button>
      <button
        type="submit"
        form="key-form"
        class="btn primary"
        :disabled="busy"
      >
        保存新密钥
      </button>
    </template>
  </ModalDialog>
</template>
