<script setup lang="ts">
import { computed, inject, onMounted, ref } from 'vue'
import { json } from '../api/workbench'
import EmptyState from '../components/EmptyState.vue'
import LineIcon from '../components/LineIcon.vue'
import SceneArt from '../components/SceneArt.vue'
import { confirmAction } from '../workbench/confirm'
import { workbenchKey } from '../workbench/useWorkbench'

type Scene = { id: string; name: string; prompt: string }
type Style = Scene & {
  title_color: string
  badge_color: string
  badge_text_color: string
  accent_color: string
}
type Version = {
  version: number
  note: string
  restored_from?: number
  published_by: string
  published_at: string
  scene_count: number
  style_count: number
}
type Catalog = {
  current: { version: number; label: string; scenes: Scene[]; styles: Style[] }
  history: Version[]
}
// Template management for admins (ADR-20260930-F): saving publishes a new version at once.
const w = inject(workbenchKey)!
const admin = computed(() => w.production && w.identity?.role === 'ADMIN')
const tab = ref<'scenes' | 'styles' | 'history'>('scenes')
const catalog = ref<Catalog | null>(null)
const scenes = ref<Scene[]>([]),
  styles = ref<Style[]>([]),
  note = ref('')
const busy = ref(false),
  error = ref(''),
  notice = ref('')
const snapshot = () => JSON.stringify([scenes.value, styles.value])
let loaded = ''
const dirty = computed(() => snapshot() !== loaded)
const problem = computed(() => {
  for (const [list, limit, what] of [
    [scenes.value, 600, '场景'],
    [styles.value, 500, '风格'],
  ] as const) {
    if (!list.length) return `至少保留一个${what}。`
    for (const item of list) {
      if (!item.name.trim() || item.name.length > 20)
        return `${what}名称需要 1–20 个字。`
      if (!item.prompt.trim() || item.prompt.length > limit)
        return `${what}“${item.name || '未命名'}”的描述需要 1–${limit} 个字。`
    }
  }
  return ''
})
const time = (value: string) => new Date(value).toLocaleString('zh-CN')
// Math.random rather than crypto.randomUUID: the latter is missing on plain-HTTP pages.
const newId = (prefix: string) =>
  `${prefix}_${Date.now().toString(36).slice(-5)}${Math.random().toString(36).slice(2, 7)}`

async function run(fn: () => Promise<void>) {
  if (busy.value) return
  busy.value = true
  error.value = ''
  notice.value = ''
  try {
    await fn()
  } catch (cause) {
    if (cause instanceof Error && cause.message !== 'STALE')
      error.value = cause.message
  } finally {
    busy.value = false
  }
}
async function load() {
  const data = await w.api<Catalog>('/admin/presets')
  catalog.value = data
  // Editable copies of the plain response (reactive proxies cannot be structured-cloned).
  scenes.value = JSON.parse(JSON.stringify(data.current.scenes))
  styles.value = JSON.parse(JSON.stringify(data.current.styles))
  note.value = ''
  loaded = snapshot()
}
onMounted(() => {
  if (admin.value) void run(load)
})
function move<T>(list: T[], index: number, delta: number) {
  const target = index + delta
  if (target < 0 || target >= list.length) return
  const [item] = list.splice(index, 1)
  list.splice(target, 0, item!)
}
function addScene() {
  scenes.value.push({ id: newId('scene'), name: '新场景', prompt: '' })
}
function addStyle() {
  styles.value.push({
    id: newId('style'),
    name: '新风格',
    prompt: '',
    title_color: '#1F2328',
    badge_color: '#F2F4F7',
    badge_text_color: '#1F2328',
    accent_color: '#1683D8',
  })
}
async function publish() {
  if (problem.value) {
    error.value = problem.value
    return
  }
  await run(async () => {
    const result = await w.api<{ version: number }>('/admin/presets', {
      ...json({ scenes: scenes.value, styles: styles.value, note: note.value }),
      method: 'PUT',
    })
    await load()
    await w.refreshOptions()
    notice.value = `已发布版本 ${result.version}，之后提交的任务使用新预设。`
  })
}
async function restore(version: number) {
  const ok = await confirmAction(
    version ? `回退到版本 ${version}` : '恢复内置默认',
    '会发布一个与所选版本内容相同的新版本；已提交的任务不受影响。',
    version ? '回退' : '恢复',
  )
  if (!ok) return
  await run(async () => {
    const result = await w.api<{ version: number }>(
      `/admin/presets/${version}/restore`,
      { method: 'POST' },
    )
    await load()
    await w.refreshOptions()
    notice.value = `已发布版本 ${result.version}。`
  })
}
</script>

<template>
  <main class="page">
    <div class="page-head">
      <div class="intro">
        <h1>模板管理</h1>
        <p>
          场景预设与卖点风格；保存即发布为新版本，已提交的任务仍用当时的描述。
        </p>
      </div>
      <span class="spacer"></span>
      <span v-if="catalog" class="tag accent num"
        >当前：{{
          catalog.current.version
            ? `版本 ${catalog.current.version}`
            : '内置默认'
        }}</span
      >
    </div>
    <section v-if="!admin" class="card">
      <EmptyState art="model">只有生产环境的管理员可以管理模板。</EmptyState>
    </section>
    <template v-else>
      <div
        class="tabs"
        role="group"
        aria-label="模板分类"
        style="justify-self: start"
      >
        <button
          type="button"
          :aria-pressed="tab === 'scenes'"
          @click="tab = 'scenes'"
        >
          场景预设
        </button>
        <button
          type="button"
          :aria-pressed="tab === 'styles'"
          @click="tab = 'styles'"
        >
          卖点风格
        </button>
        <button
          type="button"
          :aria-pressed="tab === 'history'"
          @click="tab = 'history'"
        >
          版本记录
        </button>
      </div>
      <p v-if="error" class="banner error" role="alert">
        <LineIcon name="alert" :size="14" />{{ error }}
      </p>
      <p v-if="notice" class="banner ok" role="status">
        <LineIcon name="check" :size="14" />{{ notice }}
      </p>

      <section v-if="tab === 'scenes'" class="card">
        <div class="card-head">
          <h2><LineIcon name="scene" />场景预设</h2>
          <span class="muted num">{{ scenes.length }} 个</span>
          <span class="spacer"></span>
          <button type="button" class="btn sm" @click="addScene">
            <LineIcon name="plus" :size="14" />添加场景
          </button>
        </div>
        <div class="card-body preset-list">
          <div
            v-for="(item, index) in scenes"
            :key="item.id"
            class="preset-row"
            data-testid="preset-scene"
          >
            <SceneArt :scene="item.id" class="preset-art" />
            <div class="form-grid">
              <label class="form-row"
                ><span>场景名称</span
                ><input
                  v-model="item.name"
                  maxlength="20"
                  :aria-label="`场景名称 ${index + 1}`"
              /></label>
              <label class="form-row"
                ><span>给模型的场景描述</span
                ><textarea
                  v-model="item.prompt"
                  rows="2"
                  maxlength="600"
                  :aria-label="`场景描述 ${index + 1}`"
                ></textarea>
              </label>
              <small class="mono muted">{{ item.id }}</small>
            </div>
            <div class="preset-actions">
              <button
                type="button"
                class="icon-btn"
                aria-label="上移"
                title="上移"
                :disabled="index === 0"
                @click="move(scenes, index, -1)"
              >
                <LineIcon name="up" />
              </button>
              <button
                type="button"
                class="icon-btn"
                aria-label="下移"
                title="下移"
                :disabled="index === scenes.length - 1"
                @click="move(scenes, index, 1)"
              >
                <LineIcon name="down" />
              </button>
              <button
                type="button"
                class="icon-btn danger"
                :aria-label="`删除场景 ${item.name}`"
                title="删除"
                :disabled="scenes.length === 1"
                @click="scenes.splice(index, 1)"
              >
                <LineIcon name="del" />
              </button>
            </div>
          </div>
        </div>
      </section>

      <section v-if="tab === 'styles'" class="card">
        <div class="card-head">
          <h2><LineIcon name="grid" />卖点风格</h2>
          <span class="muted num">{{ styles.length }} 个</span>
          <span class="spacer"></span>
          <button type="button" class="btn sm" @click="addStyle">
            <LineIcon name="plus" :size="14" />添加风格
          </button>
        </div>
        <div class="card-body preset-list">
          <div
            v-for="(item, index) in styles"
            :key="item.id"
            class="preset-row"
            data-testid="preset-style"
          >
            <div
              class="style-preview"
              :style="{ background: item.badge_color }"
              aria-hidden="true"
            >
              <b :style="{ color: item.title_color }">标题</b>
              <span :style="{ color: item.badge_text_color }"
                ><i :style="{ background: item.accent_color }"></i>卖点</span
              >
            </div>
            <div class="form-grid">
              <label class="form-row"
                ><span>风格名称</span
                ><input
                  v-model="item.name"
                  maxlength="20"
                  :aria-label="`风格名称 ${index + 1}`"
              /></label>
              <label class="form-row"
                ><span>给模型的风格描述</span
                ><textarea
                  v-model="item.prompt"
                  rows="2"
                  maxlength="500"
                  :aria-label="`风格描述 ${index + 1}`"
                ></textarea>
              </label>
              <div class="inline-fields">
                <label class="check"
                  ><input
                    v-model="item.title_color"
                    type="color"
                  />标题色</label
                >
                <label class="check"
                  ><input
                    v-model="item.badge_color"
                    type="color"
                  />标签底色</label
                >
                <label class="check"
                  ><input
                    v-model="item.badge_text_color"
                    type="color"
                  />标签文字</label
                >
                <label class="check"
                  ><input
                    v-model="item.accent_color"
                    type="color"
                  />点缀色</label
                >
              </div>
            </div>
            <div class="preset-actions">
              <button
                type="button"
                class="icon-btn"
                aria-label="上移"
                title="上移"
                :disabled="index === 0"
                @click="move(styles, index, -1)"
              >
                <LineIcon name="up" />
              </button>
              <button
                type="button"
                class="icon-btn"
                aria-label="下移"
                title="下移"
                :disabled="index === styles.length - 1"
                @click="move(styles, index, 1)"
              >
                <LineIcon name="down" />
              </button>
              <button
                type="button"
                class="icon-btn danger"
                :aria-label="`删除风格 ${item.name}`"
                title="删除"
                :disabled="styles.length === 1"
                @click="styles.splice(index, 1)"
              >
                <LineIcon name="del" />
              </button>
            </div>
          </div>
        </div>
      </section>

      <section v-if="tab === 'history'" class="card">
        <div class="card-head">
          <h2><LineIcon name="clock" />版本记录</h2>
          <span class="spacer"></span>
          <button
            type="button"
            class="btn sm"
            :disabled="busy || catalog?.current.version === 0"
            @click="restore(0)"
          >
            恢复内置默认
          </button>
        </div>
        <div v-if="catalog?.history.length" class="table-wrap">
          <table class="table">
            <thead>
              <tr>
                <th>版本</th>
                <th>说明</th>
                <th>场景 / 风格</th>
                <th>发布人</th>
                <th>时间</th>
                <th style="text-align: right">操作</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="item in catalog.history"
                :key="item.version"
                data-testid="preset-version"
              >
                <td class="num">
                  版本 {{ item.version
                  }}<span
                    v-if="item.version === catalog.current.version"
                    class="tag accent"
                    >当前</span
                  >
                </td>
                <td>{{ item.note || '—' }}</td>
                <td class="num">
                  {{ item.scene_count }} / {{ item.style_count }}
                </td>
                <td>{{ item.published_by }}</td>
                <td class="num">{{ time(item.published_at) }}</td>
                <td>
                  <div class="actions">
                    <button
                      v-if="item.version !== catalog.current.version"
                      type="button"
                      class="link-btn"
                      :disabled="busy"
                      @click="restore(item.version)"
                    >
                      回退到此版本
                    </button>
                  </div>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <EmptyState v-else art="clock"
          >还没有发布过，当前使用内置默认预设。</EmptyState
        >
      </section>

      <div v-if="tab !== 'history'" class="publish-bar">
        <input
          v-model="note"
          maxlength="200"
          placeholder="修改说明（可选），例如：新增花园场景"
          aria-label="修改说明"
        />
        <button
          type="button"
          class="btn"
          :disabled="busy || !dirty"
          @click="run(load)"
        >
          放弃修改
        </button>
        <button
          type="button"
          class="btn primary"
          :disabled="busy || !dirty"
          @click="publish"
        >
          <LineIcon name="check" :size="14" />保存并发布
        </button>
      </div>
    </template>
  </main>
</template>
