import { computed, onUnmounted, reactive, ref, watch } from 'vue'
import { ApiError, checkedTask, json, request } from '../api/workbench'
import { buildRequest, newDraft, Submission } from './model'
import type {
  Asset,
  Feature,
  HistoryItem,
  Options,
  Page,
  Project,
  Task,
} from './model'

export function useWorkbench() {
  const mode =
    import.meta.env.VITE_AUTH_MODE ??
    (import.meta.env.PROD ? 'production-local' : 'development-only')
  if (!['production-local', 'development-only'].includes(mode))
    throw new Error('Invalid authentication mode')
  const production = mode === 'production-local'
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
    loading = ref(false),
    feature = ref<Feature>('GIFT')
  const projects = ref<Project[]>([]),
    project = ref(''),
    projectName = ref('')
  const options = ref<Options | null>(null),
    assets = ref<Asset[]>([]),
    assetNext = ref<number | null>(null)
  const history = ref<HistoryItem[]>([]),
    historyNext = ref<number | null>(null),
    selected = ref<Task | null>(null)
  const preview = ref(''),
    previewTitle = ref(''),
    uncertain = ref(false)
  const drafts = reactive({
    GIFT: newDraft(),
    SCENE: newDraft(),
    SELLING_POINT: newDraft(),
  })
  const draft = computed(() => drafts[feature.value])
  const selectedProduct = computed(() =>
    assets.value.find((a) => a.id === draft.value.product),
  )
  const submission = new Submission()
  let epoch = 0,
    projectEpoch = 0,
    refreshSequence = 0,
    timer: ReturnType<typeof setTimeout> | undefined
  let abort = new AbortController()
  function clearPreview() {
    if (preview.value) URL.revokeObjectURL(preview.value)
    preview.value = ''
    previewTitle.value = ''
  }
  function stopPolling() {
    clearTimeout(timer)
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
    clearPreview()
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
    for (const key of ['GIFT', 'SCENE', 'SELLING_POINT'] as const)
      Object.assign(drafts[key], newDraft())
  }
  async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
    const current = epoch
    try {
      const value = await request<T>(path, token.value, {
        ...init,
        signal: AbortSignal.any([abort.signal, AbortSignal.timeout(15000)]),
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
      }
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
    if (config.mode !== mode || config.generation_available !== false)
      throw new Error('能力配置不符合当前开发工作台版本。')
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
    clearPreview()
    selected.value = null
    history.value = []
    assets.value = []
    historyNext.value = null
    assetNext.value = null
    for (const key of ['GIFT', 'SCENE', 'SELLING_POINT'] as const)
      Object.assign(drafts[key], newDraft())
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
      for (const key of ['GIFT', 'SCENE', 'SELLING_POINT'] as const) {
        drafts[key].product =
          a.items.find((v) => v.kind === 'PRODUCT')?.id ?? ''
        drafts[key].gift = a.items.find((v) => v.kind === 'GIFT')?.id ?? ''
      }
      if (h.items[0]) selectTask(h.items[0].task)
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
    await action(async () => {
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
      if (selected.value) await refreshTask()
    })
  }
  async function upload(event: Event, kind: 'PRODUCT' | 'GIFT') {
    const input = event.target as HTMLInputElement,
      file = input.files?.[0]
    input.value = ''
    if (!file) return
    await action(async () => {
      const item = await api<Asset>(
        `/projects/${project.value}/assets?kind=${kind}`,
        {
          method: 'POST',
          headers: { 'Content-Type': file.type || 'application/octet-stream' },
          body: file,
        },
      )
      assets.value.unshift({ ...item, cutout_ready: false })
      if (kind === 'PRODUCT') draft.value.product = item.id
      else draft.value.gift = item.id
      notice.value = '原图已保存。商品需等待边缘审核；当前不会自动生成图片。'
    })
  }
  async function showImage(id: string, artifact = false, download = false) {
    await action(async () => {
      const blob = await api<Blob>(
        `/${artifact ? 'artifacts' : 'assets'}/${id}/content`,
      )
      const url = URL.createObjectURL(blob)
      if (download) {
        const link = document.createElement('a')
        link.href = url
        link.download = `development-test-${id}.image`
        link.click()
        setTimeout(() => URL.revokeObjectURL(url), 1000)
      } else {
        clearPreview()
        preview.value = url
        previewTitle.value = artifact
          ? '开发/测试产物 · 非真实商品成品'
          : '上传原图 · 非生成预览'
      }
    })
  }
  function installTask(task: Task) {
    selected.value = checkedTask(task)
    const item = history.value.find((item) => item.task.id === task.id)
    if (item) item.task = task
  }
  async function submit() {
    await action(async () => {
      const pending =
        submission.pending ??
        submission.prepare(
          buildRequest(feature.value, project.value, draft.value),
        )
      try {
        const task = checkedTask(
          await api<Task>('/tasks', {
            ...json(pending.body),
            headers: {
              'Content-Type': 'application/json',
              'Idempotency-Key': pending.key,
            },
          }),
        )
        submission.resolve()
        uncertain.value = false
        installTask(task)
        schedule()
        notice.value = '任务已提交。真实制图未接入，当前仅验证开发任务流程。'
      } catch (cause) {
        if (
          cause instanceof ApiError &&
          cause.status > 0 &&
          cause.status < 500
        ) {
          submission.resolve()
          uncertain.value = false
        } else if (token.value) uncertain.value = true
        throw cause
      }
      // Read fixture labels from the frozen server snapshot, not the current draft.
      const page = await api<Page<HistoryItem>>(
        `/projects/${project.value}/tasks`,
      )
      history.value = page.items
      historyNext.value = page.next_offset
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
  function selectTask(task: Task) {
    refreshSequence++
    stopPolling()
    clearPreview()
    selected.value = task
    schedule()
  }
  async function refreshTask() {
    const id = selected.value?.id,
      current = projectEpoch,
      sequence = ++refreshSequence
    if (!id) return
    stopPolling()
    try {
      const task = checkedTask(await api<Task>(`/tasks/${id}`))
      if (
        current !== projectEpoch ||
        selected.value?.id !== id ||
        sequence !== refreshSequence
      )
        return
      installTask(task)
      schedule()
    } catch (cause) {
      if (
        current === projectEpoch &&
        selected.value?.id === id &&
        sequence === refreshSequence
      ) {
        report(cause)
        if (
          cause instanceof ApiError &&
          (cause.status === 0 || cause.status >= 500)
        )
          schedule()
      }
    }
  }
  async function retry() {
    await action(async () => {
      const task = selected.value
      if (!task) return
      refreshSequence++
      installTask(
        await api<Task>(
          `/tasks/${task.id}/retry`,
          json({ attempt: task.attempt }),
        ),
      )
      schedule()
    })
  }
  watch(
    () => [feature.value, draft.value.product, draft.value.gift],
    clearPreview,
  )
  onUnmounted(reset)
  return {
    production,
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
    feature,
    projects,
    project,
    projectName,
    options,
    assets,
    assetNext,
    history,
    historyNext,
    selected,
    preview,
    previewTitle,
    uncertain,
    draft,
    selectedProduct,
    login,
    logout,
    createProject,
    loadProject,
    moreAssets,
    refreshHistory,
    upload,
    showImage,
    submit,
    selectTask,
    refreshTask,
    retry,
    reload: () => action(loadProjects),
  }
}
