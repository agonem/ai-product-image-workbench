<script setup lang="ts">
import { onUnmounted, ref } from 'vue'
import { json } from '../api/workbench'

const props = defineProps<{
  api: <T>(path: string, init?: RequestInit) => Promise<T>
}>()
type Version = {
  id: string
  model: string
  provider_tag: string
  api_key_mask: string
  created_at: string
  active?: boolean
}
type Listing = {
  provider: string
  enabled: boolean
  active_version_id: string | null
  items: Version[]
}
type Capabilities = {
  model: string
  provider_tag: string
  input_modalities: string[]
  output_modalities: string[]
  endpoints: {
    provider_tag: string
    supported_parameters: Record<string, { type: string; values: string[] }>
  }[]
}
type PaidTest = {
  sha256: string
  width: number
  height: number
  media_type: string
  model: string
  duration_ms: number
  content_base64: string
  review_status: string
}
const view = ref<'closed' | 'config'>('closed')
const busy = ref(false),
  error = ref(''),
  notice = ref('')
const listing = ref<Listing | null>(null)
const model = ref(''),
  tag = ref(''),
  key = ref(''),
  enabled = ref(false)
const capabilities = ref<Capabilities | null>(null)
const paid = ref<PaidTest | null>(null),
  acceptCost = ref(false)
let alive = true
function stateLabel(state: Listing | null): string {
  if (!state || !state.items.length)
    return '未配置：Worker 使用其私有环境凭据（如已设置）。'
  return state.enabled
    ? '已启用：新任务绑定当前版本；重试沿用各自冻结版本。'
    : '已禁用：真实场景任务无法提交，也不会回退到环境凭据。'
}
function ratioSupport(cap: Capabilities): string {
  const total = cap.endpoints.length
  const ok = cap.endpoints.filter((item) =>
    (item.supported_parameters?.aspect_ratio?.values ?? []).includes('1:1'),
  ).length
  return `支持 1:1 的路由端点 ${ok}/${total}`
}
function modalities(
  cap: Capabilities,
  key: 'input_modalities' | 'output_modalities',
): string {
  const values = cap[key]
  return Array.isArray(values) && values.length ? values.join('/') : '未知'
}
onUnmounted(() => {
  alive = false
})
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
function openPanel() {
  view.value = 'config'
  void action(async () => {
    listing.value = await props.api<Listing>('/admin/provider-configs')
  })
}
async function save() {
  await action(async () => {
    await props.api(
      '/admin/provider-configs',
      json({
        provider: 'openrouter',
        model: model.value.trim(),
        provider_tag: tag.value.trim(),
        api_key: key.value,
        enabled: enabled.value,
      }),
    )
    key.value = ''
    model.value = tag.value = ''
    enabled.value = false
    listing.value = await props.api<Listing>('/admin/provider-configs')
    notice.value = '已创建新版本并设为当前版本；仅影响之后提交的任务。'
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
    listing.value = await props.api<Listing>('/admin/provider-configs')
    notice.value = listing.value?.enabled
      ? '已启用：之后的场景任务开始绑定该版本。'
      : '已禁用：之后的场景任务将被拒绝，已排队任务按原绑定继续。'
  })
}
async function check() {
  const active = listing.value?.active_version_id
  if (!active) return
  await action(async () => {
    capabilities.value = await props.api<Capabilities>(
      `/admin/provider-configs/${active}/check`,
      json({}),
    )
    notice.value = '非付费能力检查完成（仅 GET 查询，未产生费用）。'
  })
}
async function runPaidTest() {
  const active = listing.value?.active_version_id
  if (!active || !acceptCost.value) return
  await action(async () => {
    paid.value = await props.api<PaidTest>(
      `/admin/provider-configs/${active}/test-generate`,
      json({ confirm: 'PAID_TEST', aspect_ratio: '1:1' }),
    )
    acceptCost.value = false
    notice.value = '付费测试完成；输出仅展示，不入库、不发布、不计为成品。'
  })
}
</script>

<template>
  <section class="account-section" aria-label="供应商配置">
    <nav class="account-nav">
      <button class="secondary" :disabled="busy" @click="openPanel">
        供应商配置
      </button>
      <button
        v-if="view !== 'closed'"
        class="text-button"
        :disabled="busy"
        @click="((view = 'closed'), (capabilities = null), (paid = null))"
      >
        收起供应商设置
      </button>
    </nav>
    <div v-if="view === 'config'" class="panel account-panel">
      <h2>背景供应商配置</h2>
      <p>
        仅 OpenRouter 官方接口；密钥加密保存，任何页面都不回显。
        新任务绑定启用版本，重试沿用各自冻结版本，禁用不回退环境凭据。
      </p>
      <p class="provider-state" data-testid="provider-state">
        <strong>{{
          listing?.enabled
            ? '当前状态：已启用'
            : listing?.items.length
              ? '当前状态：已禁用'
              : '当前状态：未配置'
        }}</strong>
        <small>{{ stateLabel(listing) }}</small>
      </p>
      <p v-if="error" class="message error" role="alert">{{ error }}</p>
      <p v-if="notice" class="message" role="status">{{ notice }}</p>
      <template v-if="listing?.items.length">
        <ul class="account-list">
          <li
            v-for="item in listing.items"
            :key="item.id"
            data-testid="provider-version-row"
          >
            <span
              ><strong>{{ item.model }}</strong> · {{ item.provider_tag }} ·
              密钥 {{ item.api_key_mask }}
              <small>{{ item.active ? ' · 当前版本' : '' }}</small></span
            >
          </li>
        </ul>
        <div class="asset-actions">
          <button class="secondary" :disabled="busy" @click="toggle">
            {{ listing.enabled ? '禁用当前版本' : '启用当前版本' }}
          </button>
          <button
            class="secondary"
            :disabled="busy"
            data-testid="provider-check"
            @click="check"
          >
            非付费能力检查
          </button>
          <button
            class="secondary"
            :disabled="busy"
            data-testid="provider-paid-open"
            @click="((paid = null), (acceptCost = false))"
          >
            付费试生成
          </button>
        </div>
        <div v-if="capabilities" data-testid="provider-check-result">
          <h3>能力摘要（非付费 GET）</h3>
          <p>
            模型 {{ capabilities.model }} · 路由
            {{ capabilities.provider_tag }} · 输入
            {{ modalities(capabilities, 'input_modalities') }} · 输出
            {{ modalities(capabilities, 'output_modalities') }} ·
            {{ ratioSupport(capabilities) }}
          </p>
        </div>
        <div
          v-if="!paid"
          class="paid-dialog"
          data-testid="paid-dialog"
          role="group"
          aria-label="付费试生成确认"
        >
          <p>
            付费试生成会向 OpenRouter
            发起一次真实付费调用（固定测试提示词，1:1），
            费用按供应商计费；输出为背景测试图，不是商品成品，也不会保存或发布。
            保存配置、打开本页与能力检查均不会触发付费请求。
          </p>
          <label
            ><input
              v-model="acceptCost"
              type="checkbox"
            />我已了解可能产生费用</label
          >
          <button
            class="secondary"
            :disabled="busy || !acceptCost"
            data-testid="provider-paid-run"
            @click="runPaidTest"
          >
            确认发起付费测试
          </button>
        </div>
        <div v-else data-testid="paid-result">
          <h3>付费测试输出 · 待人工审核 · 非成品</h3>
          <img
            :src="`data:${paid.media_type};base64,${paid.content_base64}`"
            :alt="`付费测试背景 ${paid.width}×${paid.height}`"
          />
          <p>
            {{ paid.model }} · {{ paid.width }}×{{ paid.height }} ·
            {{ paid.duration_ms }}ms · sha256 {{ paid.sha256.slice(0, 16) }}…
          </p>
          <button
            class="text-button"
            :disabled="busy"
            @click="((paid = null), (acceptCost = false))"
          >
            再次测试（将再次计费）
          </button>
        </div>
      </template>
      <form class="account-create" @submit.prevent="save">
        <h3>创建 / 轮换凭据（生成新版本）</h3>
        <label
          >模型（官方端点发现的完整名称）<input
            v-model="model"
            placeholder="openai/gpt-image-2"
            required
            :disabled="busy"
        /></label>
        <label
          >provider_tag（来自端点发现）<input
            v-model="tag"
            placeholder="openai"
            required
            :disabled="busy"
        /></label>
        <label
          >API Key（保存后不可查看）<input
            v-model="key"
            type="password"
            autocomplete="new-password"
            required
            :disabled="busy"
        /></label>
        <label><input v-model="enabled" type="checkbox" />保存后立即启用</label>
        <button :disabled="busy">保存新版本</button>
      </form>
    </div>
  </section>
</template>
