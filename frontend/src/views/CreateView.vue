<script setup lang="ts">
import { computed, inject, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import AssetSlot from '../components/AssetSlot.vue'
import CompareDialog from '../components/CompareDialog.vue'
import DesignCanvas from '../components/DesignCanvas.vue'
import PrivateImage from '../workbench/PrivateImage.vue'
import {
  buildGeneration,
  canvasSizes,
  featureByRoute,
  giftPositions,
  swatches,
  textSpec,
} from '../workbench/generation'
import type { Generation, Task } from '../workbench/model'
import { statusLabels } from '../workbench/model'
import { workbenchKey } from '../workbench/useWorkbench'

const w = inject(workbenchKey)!
const route = useRoute()
const meta = computed(() => featureByRoute(String(route.params.feature))!)
const feature = computed(() => meta.value.id)
const draft = computed(() => w.drafts[feature.value])
const hasText = computed(() => feature.value !== 'SCENE')
const styles = computed(() => w.generation?.styles ?? [])
const view = ref<{ task: string; ordinal: number } | null>(null)
const comparing = ref<{ task: string; artifact: string } | null>(null)
const counts = computed(() =>
  Array.from({ length: w.generation?.max_count ?? 4 }, (_, i) => i + 1),
)

const blocked = computed(() => {
  try {
    buildGeneration(feature.value, w.project, draft.value)
    return ''
  } catch (cause) {
    return cause instanceof Error ? cause.message : '输入不完整。'
  }
})
const materialsReady = computed(
  () =>
    !!draft.value.product && (feature.value !== 'GIFT' || !!draft.value.gift),
)
const steps = computed(() => {
  const current = view.value ? 3 : materialsReady.value ? 2 : 1
  return ['上传素材', '编辑设计', '生成结果'].map((name, index) => ({
    name,
    state:
      index + 1 < current ? 'done' : index + 1 === current ? 'current' : '',
  }))
})

const results = computed(() => {
  const list = w.history
    .filter(
      (item) => item.generation_v4 && item.task.feature_type === feature.value,
    )
    .map((item) => item.task)
  const current = w.selected
  if (current && current.feature_type === feature.value)
    return [current as Task, ...list.filter((task) => task.id !== current.id)]
  return list
})
const shown = computed<Generation | null>(() =>
  view.value && w.selected?.id === view.value.task ? w.selected : null,
)
const outputSize = computed(() => {
  const size = shown.value?.output ?? canvasSizes[draft.value.size]!
  return { width: size.width, height: size.height }
})
const stageImage = computed(() => {
  const task = shown.value
  if (!task || task.status !== 'SUCCEEDED' || !view.value) return null
  const base = task.bases?.[view.value.ordinal]
  // Text entries show the model output under the editable text layer.
  if (hasText.value && base) return `/artifacts/${base.id}/content`
  const artifact = task.artifacts[view.value.ordinal]
  return artifact ? `/artifacts/${artifact.id}/content` : null
})
const background = computed(() => {
  if (feature.value !== 'GIFT' || stageImage.value) return '#f1f3f8'
  const d = draft.value
  if (d.backgroundMode === 'SOLID') return d.backgroundColor
  if (d.backgroundMode === 'GRADIENT')
    return `linear-gradient(160deg, #ffffff, ${d.backgroundColor})`
  return '#f1f3f8'
})
const palette = computed(() => {
  if (feature.value === 'SELLING_POINT') {
    const requested = shown.value?.request?.styles as string[] | undefined
    const id = requested?.[view.value?.ordinal ?? 0] ?? draft.value.styles[0]
    const style = styles.value.find((item) => item.id === id) ?? styles.value[0]
    if (style)
      return {
        badge: style.badge_color,
        badgeText: style.badge_text_color,
        accent: style.accent_color,
      }
  }
  return {
    badge: '#FFFFFF',
    badgeText: draft.value.textColor,
    accent: draft.value.textColor,
  }
})
const preview = computed(() => (hasText.value ? textSpec(draft.value) : null))

function toggleStyle(id: string) {
  const list = draft.value.styles
  draft.value.styles = list.includes(id)
    ? list.filter((item) => item !== id)
    : [...list, id]
}
function adopt(task: Generation) {
  const text = task.request?.text
  if (!hasText.value || !text) return
  // Start editing from exactly what was rendered for this result.
  Object.assign(draft.value, {
    title: text.title ?? '',
    points: (text.points ?? []).join('\n'),
    textColor: text.color,
    textSize: text.size,
    textAlign: text.align,
    textBox: { ...text.box },
  })
}
async function open(task: string, ordinal: number) {
  await w.select(task)
  if (w.selected?.id !== task) return
  view.value = { task, ordinal }
  adopt(w.selected)
}
async function retry(task: string) {
  await w.select(task)
  await w.retry()
}
watch(
  () => [w.selected?.id, w.selected?.status] as const,
  ([id, status]) => {
    if (
      id &&
      status === 'SUCCEEDED' &&
      w.selected?.feature_type === feature.value &&
      (!view.value || view.value.task !== id)
    ) {
      view.value = { task: id, ordinal: 0 }
      adopt(w.selected)
    }
  },
)
async function generate() {
  view.value = null
  await w.submit(feature.value)
}
async function applyText() {
  const text = textSpec(draft.value)
  if (!view.value || !text) return
  await w.retypeset(view.value.task, view.value.ordinal, text)
}
onMounted(() => {
  const task = route.query.task
  if (typeof task === 'string') void open(task, 0)
})
</script>

<template>
  <main class="page">
    <div class="workspace-head">
      <h1 class="page-title">{{ meta.name }}</h1>
      <ol class="stepper" aria-label="步骤">
        <li
          v-for="(step, index) in steps"
          :key="step.name"
          :data-state="step.state"
        >
          <b>{{ index + 1 }}</b
          >{{ step.name }}
        </li>
      </ol>
    </div>

    <div class="workspace-grid">
      <section class="panel" aria-labelledby="materials-title">
        <h2 id="materials-title">1. 上传素材</h2>
        <AssetSlot
          v-model="draft.product"
          label="产品主图（白底图）"
          kind="PRODUCT"
        />
        <AssetSlot
          v-if="feature === 'GIFT'"
          v-model="draft.gift"
          label="赠品图片（独立图）"
          kind="GIFT"
        />
        <small
          >原图永久保存。生成时原图作为参考发送给模型，模型可能细微改变商品，结果需人工对照原图检查。</small
        >
      </section>

      <section class="panel canvas-panel" aria-labelledby="design-title">
        <h2 id="design-title">2. 编辑设计</h2>
        <DesignCanvas
          v-model:box="draft.textBox"
          :width="outputSize.width"
          :height="outputSize.height"
          :background="background"
          :image="stageImage"
          :image-alt="`${meta.name}生成结果`"
          :hint="
            hasText
              ? '生成后在这里显示结果；现在可以先拖动虚线框安排文字位置。'
              : '生成后在这里显示结果。'
          "
          :text="preview"
          :palette="palette"
          :disabled="w.busy || w.uncertain"
          :api="w.api"
        />
        <div class="canvas-actions">
          <small v-if="hasText"
            >拖动虚线框移动文字，拖右下角调整文字区大小。预览为近似效果，以生成结果为准。</small
          >
          <button
            v-if="hasText && shown?.status === 'SUCCEEDED'"
            class="secondary"
            :disabled="w.busy || w.uncertain || !preview"
            @click="applyText"
          >
            应用文字修改（免费，不重新生成）
          </button>
        </div>
      </section>

      <section class="panel" aria-labelledby="params-title">
        <h2 id="params-title">3. 参数设置</h2>
        <fieldset class="fields" :disabled="w.busy || w.uncertain">
          <label
            >画布尺寸<select v-model.number="draft.size">
              <option
                v-for="(size, index) in canvasSizes"
                :key="size.label"
                :value="index"
              >
                {{ size.label }}
              </option>
            </select></label
          >
          <div class="row">
            <label
              >输出格式<select v-model="draft.format">
                <option value="png">PNG</option>
                <option value="jpeg">JPEG</option>
              </select></label
            >
            <label v-if="feature !== 'SELLING_POINT'"
              >生成数量<select v-model.number="draft.count">
                <option v-for="n in counts" :key="n" :value="n">
                  {{ n }} 张
                </option>
              </select></label
            >
          </div>

          <template v-if="feature === 'GIFT'">
            <div class="fields" role="group" aria-label="赠品位置">
              <span>赠品位置</span>
              <div class="chips">
                <button
                  v-for="item in giftPositions"
                  :key="item.id"
                  type="button"
                  class="chip"
                  :aria-pressed="draft.giftPosition === item.id"
                  @click="draft.giftPosition = item.id"
                >
                  {{ item.name }}
                </button>
              </div>
            </div>
            <div class="fields" role="group" aria-label="背景设置">
              <span>背景设置</span>
              <div class="chips">
                <button
                  v-for="[mode, name] in [
                    ['SOLID', '纯色背景'],
                    ['GRADIENT', '渐变背景'],
                    ['CUSTOM', '自定义背景'],
                  ] as const"
                  :key="mode"
                  type="button"
                  class="chip"
                  :aria-pressed="draft.backgroundMode === mode"
                  @click="draft.backgroundMode = mode"
                >
                  {{ name }}
                </button>
              </div>
              <div v-if="draft.backgroundMode !== 'CUSTOM'" class="swatches">
                <button
                  v-for="color in swatches"
                  :key="color"
                  type="button"
                  class="swatch"
                  :aria-label="`背景颜色 ${color}`"
                  :aria-pressed="draft.backgroundColor === color"
                  :style="{ background: color }"
                  @click="draft.backgroundColor = color"
                ></button>
                <input
                  v-model="draft.backgroundColor"
                  type="color"
                  aria-label="自选背景颜色"
                />
              </div>
              <label v-else
                >背景描述<input
                  v-model="draft.backgroundPrompt"
                  maxlength="300"
                  placeholder="例如：浅木色桌面，柔和自然光"
              /></label>
            </div>
          </template>

          <template v-if="feature === 'SCENE'">
            <div class="fields" role="group" aria-label="场景预设">
              <span>场景预设</span>
              <div class="chips">
                <button
                  v-for="item in w.generation?.scene_presets ?? []"
                  :key="item.id"
                  type="button"
                  class="chip"
                  :aria-pressed="draft.scenePreset === item.id"
                  @click="draft.scenePreset = item.id"
                >
                  {{ item.name }}
                </button>
                <button
                  type="button"
                  class="chip"
                  :aria-pressed="draft.scenePreset === ''"
                  @click="draft.scenePreset = ''"
                >
                  只用自定义描述
                </button>
              </div>
            </div>
            <label
              >场景描述{{ draft.scenePreset ? '（可选补充）' : ''
              }}<textarea
                v-model="draft.scenePrompt"
                rows="3"
                maxlength="500"
                placeholder="例如：明亮的婴儿房，浅色木质桌面"
              ></textarea>
            </label>
          </template>

          <div
            v-if="feature === 'SELLING_POINT'"
            class="fields"
            role="group"
            aria-label="风格（每种风格生成一张）"
          >
            <span>风格（每种风格生成一张）</span>
            <div class="chips">
              <button
                v-for="item in styles"
                :key="item.id"
                type="button"
                class="chip"
                :aria-pressed="draft.styles.includes(item.id)"
                @click="toggleStyle(item.id)"
              >
                {{ item.name }}
              </button>
            </div>
            <small
              >已选 {{ draft.styles.length }} 种，将生成
              {{ draft.styles.length }} 张。</small
            >
          </div>

          <label
            >风格补充（可选）<input
              v-model="draft.stylePrompt"
              maxlength="300"
              placeholder="例如：温暖、自然光"
          /></label>

          <template v-if="hasText">
            <label
              >标题文字（可选，原文使用）<textarea
                v-model="draft.title"
                rows="2"
                maxlength="60"
                placeholder="例如：轻松喂养&#10;宝宝更舒适"
              ></textarea>
            </label>
            <label
              >{{
                feature === 'SELLING_POINT'
                  ? '卖点（每行一条，原文使用）'
                  : '营销标签（每行一条，可选）'
              }}<textarea
                v-model="draft.points"
                rows="4"
                :placeholder="
                  feature === 'SELLING_POINT'
                    ? '安全材质\n防胀气设计\n易清洗'
                    : '下单即送'
                "
              ></textarea>
            </label>
            <div class="row-3">
              <label
                >字号<input
                  v-model.number="draft.textSize"
                  type="number"
                  min="12"
                  max="240"
              /></label>
              <label
                >文字颜色<input v-model="draft.textColor" type="color"
              /></label>
              <div class="align-group" role="group" aria-label="对齐方式">
                <button
                  v-for="[align, name] in [
                    ['left', '左'],
                    ['center', '中'],
                    ['right', '右'],
                  ] as const"
                  :key="align"
                  type="button"
                  class="chip"
                  :aria-label="`${name}对齐`"
                  :aria-pressed="draft.textAlign === align"
                  @click="draft.textAlign = align"
                >
                  {{ name }}
                </button>
              </div>
            </div>
          </template>
        </fieldset>
        <p v-if="blocked && !w.uncertain" class="blocked" id="generate-reason">
          {{ blocked }}
        </p>
        <p v-if="w.uncertain" class="blocked">
          上次提交结果不确定。将重发同一份请求，不会重复创建任务。
        </p>
        <button
          class="generate-button"
          :disabled="w.busy || (!!blocked && !w.uncertain)"
          aria-describedby="generate-reason"
          @click="generate"
        >
          {{ w.busy ? '处理中…' : w.uncertain ? '用原请求重发' : '✦ 生成图片' }}
        </button>
        <small
          >每次生成会调用模型并可能产生费用；文字修改不会再次调用模型。</small
        >
      </section>
    </div>

    <section class="panel results" aria-labelledby="results-title">
      <div class="results-head">
        <h2 id="results-title">生成结果 <small>待人工审核</small></h2>
        <button
          class="text-button"
          :disabled="w.busy"
          @click="w.refreshHistory()"
        >
          刷新
        </button>
      </div>
      <div v-if="results.length" class="result-strip">
        <template v-for="task in results" :key="task.id">
          <template v-if="task.status === 'SUCCEEDED'">
            <article
              v-for="(artifact, ordinal) in task.artifacts"
              :key="artifact.id"
              class="result-card"
              data-testid="result-card"
            >
              <figure>
                <PrivateImage
                  :path="`/artifacts/${artifact.id}/content`"
                  :alt="`${meta.name}结果 ${artifact.width}×${artifact.height}`"
                  :api="w.api"
                />
              </figure>
              <div class="meta">
                <span class="status-tag" data-status="SUCCEEDED"
                  >已完成 · 待人工审核</span
                >
                <span>{{ artifact.width }}×{{ artifact.height }}</span>
                <div class="actions">
                  <button
                    class="text-button"
                    :disabled="w.busy"
                    @click="open(task.id, ordinal)"
                  >
                    {{ hasText ? '编辑文字' : '查看' }}
                  </button>
                  <button
                    class="text-button"
                    @click="
                      comparing = { task: task.id, artifact: artifact.id }
                    "
                  >
                    对照原图
                  </button>
                  <button
                    class="text-button"
                    :disabled="w.busy"
                    @click="
                      w.download(artifact.id, `${meta.route}-${artifact.id}`)
                    "
                  >
                    下载
                  </button>
                </div>
              </div>
            </article>
          </template>
          <article v-else class="result-card" data-testid="result-card">
            <figure>
              <span>{{
                task.status === 'FAILED' ? '生成失败' : '生成中，请稍候…'
              }}</span>
            </figure>
            <div class="meta">
              <span class="status-tag" :data-status="task.status">{{
                statusLabels[task.status]
              }}</span>
              <span v-if="task.error"
                >{{ task.error.message }}（{{ task.error.code }}）</span
              >
              <div class="actions">
                <button
                  v-if="task.status === 'FAILED'"
                  class="text-button"
                  :disabled="w.busy"
                  @click="retry(task.id)"
                >
                  重试
                </button>
              </div>
            </div>
          </article>
        </template>
      </div>
      <p v-else class="empty">还没有结果。完成左侧设置后点击“生成图片”。</p>
    </section>
    <CompareDialog
      v-if="comparing"
      :task="comparing.task"
      :artifact="comparing.artifact"
      @close="comparing = null"
    />
  </main>
</template>
