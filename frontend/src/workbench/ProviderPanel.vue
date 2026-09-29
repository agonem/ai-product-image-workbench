<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { json } from '../api/workbench'

const props = defineProps<{
  api: <T>(path: string, init?: RequestInit) => Promise<T>
}>()
type Provider =
  | 'openrouter'
  | 'openai'
  | 'gemini'
  | 'openai-compatible'
  | 'gemini-compatible'
type Version = {
  id: string
  provider: Provider
  model: string
  provider_tag?: string
  base_url?: string
  api_key_mask: string
  created_at: string
  active?: boolean
}
type Listing = {
  enabled: boolean
  active_version_id: string | null
  items: Version[]
}
// Model names are examples only; the vendor's current model list is authoritative.
const types: {
  id: Provider
  name: string
  model: string
  base?: string
}[] = [
  { id: 'openrouter', name: 'OpenRouter', model: 'openai/gpt-image-2' },
  { id: 'openai', name: 'OpenAI 官方', model: 'gpt-image-2' },
  { id: 'gemini', name: 'Gemini 官方', model: 'gemini-2.5-flash-image' },
  {
    id: 'openai-compatible',
    name: 'OpenAI 格式（第三方）',
    model: 'gpt-image-2',
    base: 'http://10.2.2.110:3000/v1',
  },
  {
    id: 'gemini-compatible',
    name: 'Gemini 格式（第三方）',
    model: 'gemini-2.5-flash-image',
    base: 'https://relay.example.com',
  },
]
const typeName = (id: Provider) => types.find((t) => t.id === id)?.name ?? id

const busy = ref(false),
  error = ref(''),
  notice = ref('')
const listing = ref<Listing | null>(null)
const provider = ref<Provider>('openrouter')
const model = ref(''),
  tag = ref(''),
  base = ref(''),
  key = ref(''),
  enabled = ref(true)
const selected = computed(() => types.find((t) => t.id === provider.value)!)
const thirdParty = computed(() => provider.value.endsWith('-compatible'))
const current = computed(() => listing.value?.items.find((item) => item.active))
const plainHttp = computed(
  () => thirdParty.value && base.value.trim().startsWith('http://'),
)
let alive = true

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
onMounted(() => {
  void action(load)
})
onUnmounted(() => {
  alive = false
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
  }
}
async function save() {
  if (thirdParty.value) {
    const problem = baseProblem(base.value.trim())
    if (problem) {
      error.value = problem
      return
    }
  }
  await action(async () => {
    const body: Record<string, unknown> = {
      provider: provider.value,
      model: model.value.trim(),
      api_key: key.value,
      enabled: enabled.value,
    }
    if (provider.value === 'openrouter') body.provider_tag = tag.value.trim()
    if (thirdParty.value) body.base_url = base.value.trim()
    await props.api('/admin/provider-configs', json(body))
    key.value = ''
    model.value = tag.value = base.value = ''
    await load()
    notice.value = '已保存并设为当前配置；只影响之后提交的任务。'
  })
}
async function toggle() {
  const active = listing.value?.active_version_id
  if (!active) return
  await action(async () => {
    await props.api(
      `/admin/provider-configs/${active}/status`,
      json({ enabled: !listing.value?.enabled }),
    )
    await load()
    notice.value = listing.value?.enabled
      ? '已启用：之后提交的任务使用当前配置。'
      : '已停用：之后提交的生成任务会被拒绝，已排队的任务按原配置继续。'
  })
}
</script>

<template>
  <section class="account-section" aria-label="模型配置">
    <p>
      生成图片时，商品图（赠品入口另加赠品图）会作为参考图发送到这里配置的接口。
      密钥加密保存，页面只显示掩码。同一时间只有一个配置生效；新建即替换，已排队的任务仍按提交时的配置执行。
    </p>
    <p class="provider-state" data-testid="provider-state">
      <strong>{{
        listing?.enabled
          ? '当前状态：已启用'
          : listing?.items.length
            ? '当前状态：已停用'
            : '当前状态：未配置'
      }}</strong>
      <small v-if="current"
        >{{ typeName(current.provider) }} · {{ current.model }}</small
      >
    </p>
    <p v-if="error" class="message error" role="alert">{{ error }}</p>
    <p v-if="notice" class="message" role="status">{{ notice }}</p>
    <template v-if="listing?.items.length">
      <ul class="account-list">
        <li
          v-for="item in [...listing.items].reverse()"
          :key="item.id"
          data-testid="provider-version-row"
        >
          <span
            ><strong>{{ typeName(item.provider) }}</strong> · {{ item.model
            }}<template v-if="item.provider_tag">
              · {{ item.provider_tag }}</template
            ><template v-if="item.base_url"> · {{ item.base_url }}</template> ·
            密钥 {{ item.api_key_mask }}
            <small>{{ item.active ? ' · 当前配置' : '' }}</small></span
          >
        </li>
      </ul>
      <div class="asset-actions">
        <button class="secondary" :disabled="busy" @click="toggle">
          {{ listing.enabled ? '停用当前配置' : '启用当前配置' }}
        </button>
      </div>
    </template>
    <form class="account-create" @submit.prevent="save">
      <h3>新建配置</h3>
      <label
        >接口类型<select v-model="provider" :disabled="busy">
          <option v-for="item in types" :key="item.id" :value="item.id">
            {{ item.name }}
          </option>
        </select></label
      >
      <label
        >模型名称<input
          v-model="model"
          :placeholder="selected.model"
          required
          maxlength="200"
          :disabled="busy"
      /></label>
      <label v-if="provider === 'openrouter'"
        >provider_tag（OpenRouter 路由）<input
          v-model="tag"
          placeholder="openai"
          required
          maxlength="100"
          :disabled="busy"
      /></label>
      <label v-if="thirdParty"
        >接口地址<input
          v-model="base"
          :placeholder="selected.base"
          required
          maxlength="300"
          :disabled="busy"
      /></label>
      <p v-if="plainHttp" class="message warn" role="note">
        http 地址不加密：API Key 与商品图会在内网明文传输。
      </p>
      <label
        >API Key（保存后不可查看）<input
          v-model="key"
          type="password"
          autocomplete="new-password"
          required
          :disabled="busy"
      /></label>
      <label class="check"
        ><input v-model="enabled" type="checkbox" />保存后立即启用</label
      >
      <button :disabled="busy">保存配置</button>
    </form>
  </section>
</template>
