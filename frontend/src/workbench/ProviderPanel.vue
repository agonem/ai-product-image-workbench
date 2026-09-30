<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { json } from '../api/workbench'
import EmptyState from '../components/EmptyState.vue'
import LineIcon from '../components/LineIcon.vue'
import ModalDialog from '../components/ModalDialog.vue'
import { confirmAction } from './confirm'
import { providerNames } from './model'

// Admin model catalogue (ADR-20260929-C): several models, one default, per-model proxy;
// third-party endpoints in the OpenAI or Gemini format again since ADR-20260930-E.
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
const dialog = ref<'' | 'create' | 'key' | 'rename'>('')
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
})
const proxyUrl = ref('')
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
function open(kind: 'create' | 'key' | 'rename', item: Item | null = null) {
  target.value = item
  form.value = {
    name: item?.name ?? '',
    provider: 'openrouter',
    model: '',
    tag: '',
    base: '',
    key: '',
    proxy: false,
    enabled: true,
  }
  error.value = ''
  dialog.value = kind
}
function close() {
  dialog.value = ''
  target.value = null
  form.value.key = ''
}
async function create() {
  if (thirdParty.value) {
    const problem = baseProblem(form.value.base.trim())
    if (problem) {
      error.value = problem
      return
    }
  }
  await action(async () => {
    const f = form.value
    const body: Record<string, unknown> = {
      name: f.name.trim(),
      provider: f.provider,
      model: f.model.trim(),
      api_key: f.key,
      enabled: f.enabled,
      use_proxy: f.proxy,
    }
    if (f.provider === 'openrouter') body.provider_tag = f.tag.trim()
    if (thirdParty.value) body.base_url = f.base.trim()
    await props.api('/admin/provider-configs', json(body))
    close()
    await load()
    notice.value = '模型已添加；运营可在生成页选择已启用的模型。'
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
    notice.value = '密钥已更换；之前提交的任务仍按原密钥执行。'
  })
}
async function rename() {
  const item = target.value
  if (!item) return
  await action(async () => {
    await props.api(
      `/admin/provider-configs/${item.id}/settings`,
      json({ name: form.value.name.trim() }),
    )
    close()
    await load()
    notice.value = '名称已更新。'
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
                }}<span v-if="item.default" class="tag accent"
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
                  @click="open('rename', item)"
                >
                  改名
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

  <ModalDialog v-if="dialog === 'create'" title="添加模型" @close="close">
    <form id="model-form" class="form-grid" @submit.prevent="create">
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
        ><span>路由标签（provider_tag）</span
        ><input
          v-model="form.tag"
          placeholder="openai"
          maxlength="100"
          required
          :disabled="busy"
      /></label>
      <label class="form-row"
        ><span>API Key</span
        ><input
          aria-label="API Key"
          aria-describedby="api-key-hint"
          v-model="form.key"
          type="password"
          autocomplete="new-password"
          required
          :disabled="busy"
        /><small id="api-key-hint">保存后不可查看，只显示掩码。</small></label
      >
      <label class="check"
        ><input
          v-model="form.proxy"
          type="checkbox"
          :disabled="busy"
        />通过网络代理访问</label
      >
      <label class="check"
        ><input
          v-model="form.enabled"
          type="checkbox"
          :disabled="busy"
        />保存后启用</label
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

  <ModalDialog
    v-if="dialog === 'rename' && target"
    title="修改显示名称"
    @close="close"
  >
    <form id="rename-form" class="form-grid" @submit.prevent="rename">
      <p v-if="error" class="banner error" role="alert">
        <LineIcon name="alert" :size="14" />{{ error }}
      </p>
      <label class="form-row"
        ><span>显示名称</span
        ><input v-model="form.name" maxlength="40" required :disabled="busy"
      /></label>
    </form>
    <template #footer>
      <button type="button" class="btn" @click="close">取消</button>
      <button
        type="submit"
        form="rename-form"
        class="btn primary"
        :disabled="busy"
      >
        保存
      </button>
    </template>
  </ModalDialog>
</template>
