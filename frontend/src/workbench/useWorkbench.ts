import { computed, onUnmounted, reactive, ref, watch } from 'vue'
import type { InjectionKey, UnwrapNestedRefs } from 'vue'
import { ApiError, json, request } from '../api/workbench'
import { validateContract } from '../contracts/validate'
import { buildGeneration, newDraft } from './generation'
import type { GenerationDraft } from './generation'
import { Submission, kindName } from './model'
import { prepareUpload } from './upload'
import type {
  Asset,
  AssetKind,
  Feature,
  Generation,
  HistoryItem,
  Options,
  Page,
  Project,
  Task,
  TextSpec,
} from './model'

/** Signed-in account as returned by login or `/me`. */
interface Account {
  id: string
  username?: string
  role?: 'ADMIN' | 'USER'
  mode: string
  expires_at?: string
}

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
  // The session itself is an HttpOnly cookie; the page only knows whether it is signed in.
  const signedIn = ref(false),
    restoring = ref(true),
    sessionExpires = ref(''),
    username = ref(''),
    password = ref(''),
    error = ref(''),
    notice = ref('')
  const busy = ref(false),
    loading = ref(false)
  // Every account works in one implicit project (created on first sign-in).
  const project = ref('')
  const options = ref<Options | null>(null),
    assets = ref<Asset[]>([]),
    assetNext = ref<number | null>(null)
  const history = ref<HistoryItem[]>([]),
    historyNext = ref<number | null>(null)
  const selected = ref<Generation | null>(null),
    uncertain = ref(false)
  const drafts = reactive<Record<Feature, GenerationDraft>>({
    GIFT: newDraft('GIFT'),
    SCENE: newDraft('SCENE'),
    SELLING_POINT: newDraft('SELLING_POINT'),
  })
  const generation = computed(() => options.value?.generation ?? null)
  const models = computed(() => options.value?.models ?? [])
  const defaultModel = computed(
    () => models.value.find((item) => item.default)?.id ?? '',
  )
  const products = computed(() =>
    assets.value.filter((item) => item.kind === 'PRODUCT'),
  )
  const gifts = computed(() =>
    assets.value.filter((item) => item.kind === 'GIFT'),
  )
  const references = computed(() =>
    assets.value.filter((item) => item.kind === 'REFERENCE'),
  )
  /** The originals of one material category (ADR-20261009-R). */
  const assetsOf = (kind: AssetKind) =>
    kind === 'PRODUCT'
      ? products.value
      : kind === 'GIFT'
        ? gifts.value
        : references.value
  const submission = new Submission()
  let epoch = 0,
    projectEpoch = 0,
    refreshSequence = 0,
    timer: ReturnType<typeof setTimeout> | undefined
  let abort = new AbortController()

  // Confirmations fade on their own; errors stay until dismissed or the next action.
  let noticeTimer: ReturnType<typeof setTimeout> | undefined
  watch(notice, (value) => {
    clearTimeout(noticeTimer)
    if (value) noticeTimer = setTimeout(() => (notice.value = ''), 6000)
  })

  // Tasks submitted in this session keep being checked while another result is on screen,
  // so a new image never stays "generating" just because the user looked elsewhere.
  const watched = new Set<string>()
  let watchTimer: ReturnType<typeof setTimeout> | undefined

  function stopPolling() {
    clearTimeout(timer)
  }
  function scheduleWatch() {
    clearTimeout(watchTimer)
    if (signedIn.value && [...watched].some((id) => id !== selected.value?.id))
      watchTimer = setTimeout(() => void checkWatched(), 4000)
  }
  async function checkWatched() {
    const current = projectEpoch
    let finished = false
    for (const id of [...watched]) {
      if (id === selected.value?.id) continue // polled by refreshTask
      try {
        const detail = checked(
          await api<Generation>(`/v4/generation-tasks/${id}`),
        )
        if (current !== projectEpoch) return
        const item = history.value.find((entry) => entry.task.id === id)
        if (item)
          item.task = {
            ...item.task,
            status: detail.status,
            attempt: detail.attempt,
            artifacts: detail.artifacts,
            error: detail.error,
          }
        if (!['QUEUED', 'RUNNING'].includes(detail.status)) {
          watched.delete(id)
          finished = true
        }
      } catch {
        // Background check only: the next round retries; the on-screen task reports errors.
        if (current !== projectEpoch) return
      }
    }
    if (finished) await refreshHistory().catch(() => undefined)
    scheduleWatch()
  }
  function resetDrafts() {
    for (const key of ['GIFT', 'SCENE', 'SELLING_POINT'] as const)
      Object.assign(drafts[key], newDraft(key), { model: defaultModel.value })
  }
  /** Keep each draft on models, scenes and styles that still exist (the admin may change them). */
  function syncModels() {
    const ids = new Set(models.value.map((item) => item.id))
    const scenes = new Set(
      (generation.value?.scene_presets ?? []).map((item) => item.id),
    )
    const styles = (generation.value?.styles ?? []).map((item) => item.id)
    for (const key of ['GIFT', 'SCENE', 'SELLING_POINT'] as const) {
      const draft = drafts[key]
      if (!ids.has(draft.model)) draft.model = defaultModel.value
      if (scenes.size && draft.scenePreset && !scenes.has(draft.scenePreset))
        draft.scenePreset = [...scenes][0]!
      if (styles.length) {
        const kept = draft.styles.filter((id) => styles.includes(id))
        if (kept.length !== draft.styles.length)
          draft.styles = kept.length ? kept : [styles[0]!]
      }
    }
  }
  /** Models can change while signed in (the admin adds or disables one). */
  async function refreshOptions() {
    if (!signedIn.value) return
    try {
      const config = await api<Options>('/workbench/options')
      if (config.mode !== mode) return
      options.value = config
      syncModels()
    } catch (cause) {
      report(cause)
    }
  }
  function reset() {
    clearTimeout(sessionTimer)
    identity.value = null
    expiresAt = 0
    sessionExpires.value = ''
    epoch++
    projectEpoch++
    refreshSequence++
    loading.value = false
    abort.abort()
    abort = new AbortController()
    stopPolling()
    watched.clear()
    clearTimeout(watchTimer)
    signedIn.value = false
    password.value = ''
    project.value = ''
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
      const value = await request<T>(path, {
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

  /** Accept a login or `/me` answer and open the workbench. */
  async function start(account: Account) {
    if (account.mode !== mode)
      throw new Error('页面与服务认证模式不符，请联系管理员。')
    expiresAt = Date.parse(account.expires_at ?? '')
    if (production) {
      if (
        !account.username ||
        !['ADMIN', 'USER'].includes(account.role ?? '') ||
        !Number.isFinite(expiresAt) ||
        expiresAt <= Date.now()
      )
        throw new Error('生产认证响应无效。')
      identity.value = {
        id: account.id,
        username: account.username,
        role: account.role!,
      }
    } else
      identity.value = {
        id: account.id,
        username: account.username ?? username.value,
        role: 'USER',
      }
    sessionExpires.value = Number.isFinite(expiresAt)
      ? new Date(expiresAt).toISOString()
      : ''
    signedIn.value = true
    if (production) scheduleSession()
    await loadProjects()
  }
  async function login() {
    await action(async () => {
      const result = await api<{
        mode: string
        expires_at?: string
        user?: { id: string; username?: string; role?: 'ADMIN' | 'USER' }
      }>(
        authPath + '/login',
        json({ username: username.value, password: password.value }),
      )
      password.value = ''
      if (!result.user) throw new Error('认证响应无效。')
      await start({
        ...result.user,
        mode: result.mode,
        expires_at: result.expires_at,
      })
    })
    password.value = ''
  }
  /** On page load: reuse a still-valid session cookie instead of asking to log in again. */
  async function restore() {
    try {
      const account = await request<Account>(authPath + '/me')
      await start(account)
    } catch (cause) {
      // No valid session is the normal case; only report problems after sign-in.
      if (signedIn.value) report(cause)
      else reset()
    } finally {
      restoring.value = false
    }
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
    if (!production || !signedIn.value) return
    if (Date.now() >= expiresAt) {
      expire()
      return
    }
    try {
      await api(authPath + '/me')
    } catch (cause) {
      report(cause)
    } finally {
      if (signedIn.value) scheduleSession()
    }
  }
  async function loadProjects() {
    const [list, config] = await Promise.all([
      api<Project[]>('/projects'),
      api<Options>('/workbench/options'),
    ])
    if (config.mode !== mode)
      throw new Error('能力配置与当前页面模式不符，请联系管理员。')
    options.value = config
    syncModels()
    // The list is newest first; the oldest project is the account's working project.
    const chosen =
      list.at(-1) ??
      (await api<Project>('/projects', json({ name: '默认项目' })))
    project.value = chosen.id
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
      // No material is chosen in advance: each page starts empty until the user picks one
      // (ADR-20261010-T).
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
  async function upload(file: File, kind: AssetKind): Promise<Asset | null> {
    let created: Asset | null = null
    await action(async () => {
      const prepared = await prepareUpload(file)
      const item = await api<Asset>(
        `/projects/${project.value}/assets?kind=${kind}`,
        {
          method: 'POST',
          headers: { 'Content-Type': prepared.type },
          body: prepared.body,
        },
      )
      assets.value.unshift(item)
      created = item
      notice.value =
        `${kindName(kind).replace('图', '')}原图已保存` +
        (prepared.converted ? '（已转为 PNG 保存）。' : '。')
    })
    return created
  }
  /** Copies a generated result into a new original (ADR-20260930-E). */
  async function reuseWork(
    artifact: string,
    kind: AssetKind,
  ): Promise<Asset | null> {
    let copied: Asset | null = null
    await action(async () => {
      const item = await api<Asset>(
        `/artifacts/${artifact}/asset`,
        json({ kind }),
      )
      if (!assets.value.some((entry) => entry.id === item.id))
        assets.value.unshift(item)
      copied = item
      notice.value = `已把作品复制为${kindName(kind)}。`
    })
    return copied
  }
  /** The owner deletes an original; results made from it stay in history. */
  async function deleteAsset(id: string) {
    await action(async () => {
      await api(`/assets/${id}`, { method: 'DELETE' })
      assets.value = assets.value.filter((item) => item.id !== id)
      for (const key of ['GIFT', 'SCENE', 'SELLING_POINT'] as const) {
        if (drafts[key].product === id) drafts[key].product = ''
        if (drafts[key].gift === id) drafts[key].gift = ''
      }
      notice.value = '原图已删除；用它生成过的结果仍保留。'
    })
  }
  /** The owner deletes one result (and the model output behind it). */
  async function deleteArtifact(id: string) {
    await action(async () => {
      await api(`/artifacts/${id}`, { method: 'DELETE' })
      await refreshHistory()
      const current = selected.value
      if (current?.artifacts.some((item) => item.id === id))
        await select(current.id)
      notice.value = '生成结果已删除。'
    })
  }
  async function download(artifact: string, name: string) {
    await downloadFile(`/artifacts/${artifact}/content`, name)
  }
  /** Saves any private image (a result or an original) under a readable name. */
  async function downloadFile(path: string, name: string) {
    await action(async () => {
      const blob = await api<Blob>(path)
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
      signedIn.value &&
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
    scheduleWatch()
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
      if (!['QUEUED', 'RUNNING'].includes(detail.status)) {
        watched.delete(id)
        await refreshHistory()
      }
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
      watched.add(task.id)
      await refreshHistory()
      await select(task.id)
    } catch (cause) {
      // A definite rejection frees the draft; an unknown outcome keeps the same key.
      if (cause instanceof ApiError && cause.status > 0 && cause.status < 500) {
        submission.resolve()
        uncertain.value = false
      } else if (signedIn.value) uncertain.value = true
      throw cause
    }
  }
  async function submit(feature: Feature) {
    await action(async () => {
      const body = submission.pending
        ? submission.pending.body
        : buildGeneration(feature, project.value, drafts[feature])
      await send('/v4/generation-tasks', body)
      notice.value = '已提交生成任务，完成后显示在画布中。'
    })
  }
  async function retypeset(task: string, ordinal: number, text: TextSpec) {
    await action(async () => {
      await send(`/v4/generation-tasks/${task}/retypeset`, { ordinal, text })
      notice.value = '已提交文字修改：只重排文字，不重新生成。'
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
      watched.add(task.id)
      await select(task.id)
    })
  }

  onUnmounted(() => {
    clearTimeout(noticeTimer)
    clearTimeout(watchTimer)
    reset()
  })
  void restore()
  return {
    production,
    mockProvider,
    identity,
    api,
    expire,
    signedIn,
    restoring,
    sessionExpires,
    username,
    password,
    error,
    notice,
    busy,
    loading,
    project,
    options,
    generation,
    models,
    defaultModel,
    refreshOptions,
    dismissError: () => (error.value = ''),
    assets,
    products,
    gifts,
    references,
    assetsOf,
    assetNext,
    history,
    historyNext,
    selected,
    uncertain,
    drafts,
    login,
    logout,
    moreAssets,
    refreshHistory: (more = false) => action(() => refreshHistory(more)),
    upload,
    deleteAsset,
    deleteArtifact,
    download,
    downloadFile,
    reuseWork,
    select: (id: string) => action(() => select(id)),
    refreshTask,
    submit,
    retypeset,
    retry,
  }
}
