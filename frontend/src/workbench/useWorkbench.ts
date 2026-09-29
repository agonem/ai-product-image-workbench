import { computed, onUnmounted, reactive, ref } from 'vue'
import type { InjectionKey, UnwrapNestedRefs } from 'vue'
import { ApiError, json, request } from '../api/workbench'
import { validateContract } from '../contracts/validate'
import { buildGeneration, newDraft } from './generation'
import type { GenerationDraft } from './generation'
import { Submission } from './model'
import type {
  Asset,
  Feature,
  Generation,
  HistoryItem,
  Options,
  Page,
  Project,
  Task,
  TextSpec,
} from './model'

export type WorkbenchStore = UnwrapNestedRefs<ReturnType<typeof useWorkbench>>
export const workbenchKey: InjectionKey<WorkbenchStore> = Symbol('workbench')

const taskFields = [
  'id',
  'feature_type',
  'status',
  'attempt',
  'created_at',
  'artifacts',
  'error',
]
/** Validate the shared task part of any response before trusting it. */
function checked<T extends Task>(value: T): T {
  const base = Object.fromEntries(
    taskFields.map((key) => [key, (value as Record<string, unknown>)[key]]),
  )
  if (validateContract('task-response', base).length)
    throw new ApiError(0, '任务响应格式异常，请刷新查询，避免重复创建任务。')
  return value
}

export function useWorkbench() {
  const mode =
    import.meta.env.VITE_AUTH_MODE ??
    (import.meta.env.PROD ? 'production-local' : 'development-only')
  if (!['production-local', 'development-only'].includes(mode))
    throw new Error('Invalid authentication mode')
  const production = mode === 'production-local'
  const mockProvider = import.meta.env.VITE_ACCEPTANCE_MODE === 'mock-provider'
  const authPath = production ? '/local-auth' : '/auth'
  const identity = ref<{
    id: string
    username: string
    role: 'ADMIN' | 'USER'
  } | null>(null)
  let sessionTimer: ReturnType<typeof setTimeout> | undefined
  let expiresAt = 0
  const token = ref(''),
    username = ref(''),
    password = ref(''),
    error = ref(''),
    notice = ref('')
  const busy = ref(false),
    loading = ref(false)
  const projects = ref<Project[]>([]),
    project = ref(''),
    projectName = ref('')
  const options = ref<Options | null>(null),
    assets = ref<Asset[]>([]),
    assetNext = ref<number | null>(null)
  const history = ref<HistoryItem[]>([]),
    historyNext = ref<number | null>(null)
  const selected = ref<Generation | null>(null),
    uncertain = ref(false)
  const drafts = reactive<Record<Feature, GenerationDraft>>({
    GIFT: newDraft(),
    SCENE: newDraft(),
    SELLING_POINT: newDraft(),
  })
  const generation = computed(() => options.value?.generation ?? null)
  const products = computed(() =>
    assets.value.filter((item) => item.kind === 'PRODUCT'),
  )
  const gifts = computed(() =>
    assets.value.filter((item) => item.kind === 'GIFT'),
  )
  const submission = new Submission()
  let epoch = 0,
    projectEpoch = 0,
    refreshSequence = 0,
    timer: ReturnType<typeof setTimeout> | undefined
  let abort = new AbortController()

  function stopPolling() {
    clearTimeout(timer)
  }
  function resetDrafts() {
    for (const key of ['GIFT', 'SCENE', 'SELLING_POINT'] as const)
      Object.assign(drafts[key], newDraft())
  }
  function reset() {
    clearTimeout(sessionTimer)
    identity.value = null
    expiresAt = 0
    epoch++
    projectEpoch++
    refreshSequence++
    loading.value = false
    abort.abort()
    abort = new AbortController()
    stopPolling()
    token.value = ''
    password.value = ''
    projects.value = []
    project.value = ''
    projectName.value = ''
    options.value = null
    assets.value = []
    history.value = []
    selected.value = null
    assetNext.value = null
    historyNext.value = null
    submission.resolve()
    uncertain.value = false
    notice.value = ''
    resetDrafts()
  }
  async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
    const current = epoch
    try {
      const value = await request<T>(path, token.value, {
        ...init,
        signal: AbortSignal.any([abort.signal, AbortSignal.timeout(20000)]),
      })
      if (current !== epoch) throw new Error('STALE')
      return value
    } catch (cause) {
      if (current !== epoch) throw new Error('STALE')
      if (cause instanceof ApiError && cause.status === 401) {
        reset()
        error.value = cause.message
      }
      throw cause
    }
  }
  function report(cause: unknown) {
    if (cause instanceof Error && cause.message !== 'STALE')
      error.value = cause.message
  }
  async function action(fn: () => Promise<void>) {
    if (busy.value) return
    busy.value = true
    error.value = ''
    notice.value = ''
    try {
      await fn()
    } catch (cause) {
      report(cause)
    } finally {
      busy.value = false
    }
  }

  async function login() {
    await action(async () => {
      const result = await api<{
        access_token: string
        mode: string
        expires_at?: string
        user?: { id: string; username: string; role: 'ADMIN' | 'USER' }
      }>(
        authPath + '/login',
        json({ username: username.value, password: password.value }),
      )
      password.value = ''
      if (result.mode !== mode)
        throw new Error('页面与服务认证模式不匹配，请联系管理员。')
      if (production) {
        expiresAt = Date.parse(result.expires_at ?? '')
        if (
          !result.user ||
          !['ADMIN', 'USER'].includes(result.user.role) ||
          !Number.isFinite(expiresAt) ||
          expiresAt <= Date.now()
        )
          throw new Error('生产认证响应无效。')
        identity.value = result.user
      } else identity.value = { id: '', username: username.value, role: 'USER' }
      token.value = result.access_token
      if (production) scheduleSession()
      await loadProjects()
    })
    password.value = ''
  }
  function expire() {
    reset()
    error.value = '会话已失效，请重新登录。'
  }
  function scheduleSession() {
    clearTimeout(sessionTimer)
    sessionTimer = setTimeout(
      () => void checkSession(),
      Math.max(0, Math.min(5000, expiresAt - Date.now())),
    )
  }
  async function checkSession() {
    if (!production || !token.value) return
    if (Date.now() >= expiresAt) {
      expire()
      return
    }
    try {
      await api(authPath + '/me')
    } catch (cause) {
      report(cause)
    } finally {
      if (token.value) scheduleSession()
    }
  }
  async function loadProjects() {
    const [list, config] = await Promise.all([
      api<Project[]>('/projects'),
      api<Options>('/workbench/options'),
    ])
    if (config.mode !== mode)
      throw new Error('能力配置与当前页面模式不符，请联系管理员。')
    projects.value = list
    options.value = config
    if (!list.some((p) => p.id === project.value))
      project.value = list[0]?.id ?? ''
    await loadProject()
  }
  async function logout() {
    await action(async () => {
      try {
        await api(authPath + '/logout', { method: 'POST' })
      } finally {
        reset()
      }
    })
  }
  async function createProject() {
    await action(async () => {
      const value = await api<Project>(
        '/projects',
        json({ name: projectName.value }),
      )
      project.value = value.id
      projectName.value = ''
      await loadProjects()
    })
  }
  async function loadProject() {
    projectEpoch++
    refreshSequence++
    loading.value = false
    stopPolling()
    selected.value = null
    history.value = []
    assets.value = []
    historyNext.value = null
    assetNext.value = null
    resetDrafts()
    if (!project.value) return
    const current = projectEpoch,
      id = project.value
    loading.value = true
    try {
      const [a, h] = await Promise.all([
        api<Page<Asset>>(`/projects/${id}/assets`),
        api<Page<HistoryItem>>(`/projects/${id}/tasks`),
      ])
      if (current !== projectEpoch) return
      assets.value = a.items
      assetNext.value = a.next_offset
      history.value = h.items
      historyNext.value = h.next_offset
      const product = a.items.find((v) => v.kind === 'PRODUCT')?.id ?? ''
      const gift = a.items.find((v) => v.kind === 'GIFT')?.id ?? ''
      for (const key of ['GIFT', 'SCENE', 'SELLING_POINT'] as const) {
        drafts[key].product = product
        drafts[key].gift = gift
      }
    } catch (cause) {
      if (current === projectEpoch) report(cause)
    } finally {
      if (current === projectEpoch) loading.value = false
    }
  }
  async function moreAssets() {
    await action(async () => {
      if (assetNext.value === null) return
      const current = projectEpoch
      const page = await api<Page<Asset>>(
        `/projects/${project.value}/assets?offset=${assetNext.value}`,
      )
      if (current !== projectEpoch) return
      assets.value = [
        ...new Map(
          [...assets.value, ...page.items].map((item) => [item.id, item]),
        ).values(),
      ]
      assetNext.value = page.next_offset
    })
  }
  async function refreshHistory(more = false) {
    if (!project.value || (more && historyNext.value === null)) return
    const current = projectEpoch
    const page = await api<Page<HistoryItem>>(
      `/projects/${project.value}/tasks?offset=${more ? historyNext.value : 0}`,
    )
    if (current !== projectEpoch) return
    history.value = more
      ? [
          ...new Map(
            [...history.value, ...page.items].map((item) => [
              item.task.id,
              item,
            ]),
          ).values(),
        ]
      : page.items
    historyNext.value = page.next_offset
  }
  async function upload(
    file: File,
    kind: 'PRODUCT' | 'GIFT',
  ): Promise<Asset | null> {
    let created: Asset | null = null
    await action(async () => {
      const item = await api<Asset>(
        `/projects/${project.value}/assets?kind=${kind}`,
        {
          method: 'POST',
          headers: { 'Content-Type': file.type || 'application/octet-stream' },
          body: file,
        },
      )
      assets.value.unshift(item)
      created = item
      notice.value =
        kind === 'PRODUCT' ? '商品原图已保存。' : '赠品原图已保存。'
    })
    return created
  }
  async function download(artifact: string, name: string) {
    await action(async () => {
      const blob = await api<Blob>(`/artifacts/${artifact}/content`)
      const url = URL.createObjectURL(blob)
      const link = document.createElement('a')
      const signature = new Uint8Array(await blob.slice(0, 2).arrayBuffer())
      link.href = url
      link.download = `${name}.${signature[0] === 137 && signature[1] === 80 ? 'png' : 'jpg'}`
      link.click()
      setTimeout(() => URL.revokeObjectURL(url), 1000)
    })
  }

  function schedule() {
    stopPolling()
    if (
      token.value &&
      selected.value &&
      ['QUEUED', 'RUNNING'].includes(selected.value.status)
    )
      timer = setTimeout(() => {
        void refreshTask().catch(report)
      }, 2500)
  }
  async function select(id: string) {
    refreshSequence++
    stopPolling()
    const current = projectEpoch,
      sequence = refreshSequence
    const detail = checked(await api<Generation>(`/v4/generation-tasks/${id}`))
    if (current !== projectEpoch || sequence !== refreshSequence) return
    selected.value = detail
    schedule()
  }
  async function refreshTask() {
    const id = selected.value?.id,
      current = projectEpoch,
      sequence = ++refreshSequence
    if (!id) return
    stopPolling()
    try {
      const detail = checked(
        await api<Generation>(`/v4/generation-tasks/${id}`),
      )
      if (
        current !== projectEpoch ||
        selected.value?.id !== id ||
        sequence !== refreshSequence
      )
        return
      selected.value = detail
      if (!['QUEUED', 'RUNNING'].includes(detail.status)) await refreshHistory()
      schedule()
    } catch (cause) {
      if (current === projectEpoch && selected.value?.id === id) {
        report(cause)
        if (
          cause instanceof ApiError &&
          (cause.status === 0 || cause.status >= 500)
        )
          schedule()
      }
    }
  }
  async function send(path: string, body: Record<string, unknown>) {
    const pending = submission.pending ?? submission.prepare(path, body)
    try {
      const task = checked(
        await api<Task>(pending.path, {
          ...json(pending.body),
          headers: {
            'Content-Type': 'application/json',
            'Idempotency-Key': pending.key,
          },
        }),
      )
      submission.resolve()
      uncertain.value = false
      await refreshHistory()
      await select(task.id)
    } catch (cause) {
      // A definite rejection frees the draft; an unknown outcome keeps the same key.
      if (cause instanceof ApiError && cause.status > 0 && cause.status < 500) {
        submission.resolve()
        uncertain.value = false
      } else if (token.value) uncertain.value = true
      throw cause
    }
  }
  async function submit(feature: Feature) {
    await action(async () => {
      const body = submission.pending
        ? submission.pending.body
        : buildGeneration(feature, project.value, drafts[feature])
      await send('/v4/generation-tasks', body)
      notice.value =
        '已提交，生成完成后在下方查看结果；结果需人工审核后再使用。'
    })
  }
  async function retypeset(task: string, ordinal: number, text: TextSpec) {
    await action(async () => {
      await send(`/v4/generation-tasks/${task}/retypeset`, { ordinal, text })
      notice.value = '已提交文字修改：复用原生成图重新排字，不再调用模型。'
    })
  }
  async function retry() {
    await action(async () => {
      const task = selected.value
      if (!task) return
      await api<Task>(
        `/tasks/${task.id}/retry`,
        json({ attempt: task.attempt }),
      )
      await select(task.id)
    })
  }

  onUnmounted(reset)
  return {
    production,
    mockProvider,
    identity,
    api,
    expire,
    token,
    username,
    password,
    error,
    notice,
    busy,
    loading,
    projects,
    project,
    projectName,
    options,
    generation,
    assets,
    products,
    gifts,
    assetNext,
    history,
    historyNext,
    selected,
    uncertain,
    drafts,
    login,
    logout,
    createProject,
    loadProject,
    moreAssets,
    refreshHistory: (more = false) => action(() => refreshHistory(more)),
    upload,
    download,
    select: (id: string) => action(() => select(id)),
    refreshTask,
    submit,
    retypeset,
    retry,
    reload: () => action(loadProjects),
  }
}
