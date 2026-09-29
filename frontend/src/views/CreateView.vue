<script setup lang="ts">
import { computed, inject, onMounted, reactive, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import AssetSlot from '../components/AssetSlot.vue'
import DropSelect from '../components/DropSelect.vue'
import EmptyState from '../components/EmptyState.vue'
import LineIcon from '../components/LineIcon.vue'
import ParamSection from '../components/ParamSection.vue'
import SceneArt from '../components/SceneArt.vue'
import StudioCanvas from '../components/StudioCanvas.vue'
import PrivateImage from '../workbench/PrivateImage.vue'
import {
  adoptText,
  backgrounds,
  buildGeneration,
  canvasSizes,
  featureByRoute,
  giftPositions,
  placeText,
  pointLines,
  textColors,
  textLevels,
  textPositions,
  textSpec,
} from '../workbench/generation'
import type { Feature, Generation, Task } from '../workbench/model'
import { providerNames } from '../workbench/model'
import { workbenchKey } from '../workbench/useWorkbench'

const w = inject(workbenchKey)!
const route = useRoute()
const meta = computed(() => featureByRoute(String(route.params.feature))!)
const feature = computed(() => meta.value.id)
const draft = computed(() => w.drafts[feature.value])
const hasText = computed(() => feature.value !== 'SCENE')
const styles = computed(() => w.generation?.styles ?? [])
const locked = computed(() => w.busy || w.uncertain)

// One parameter group open at a time, remembered per entry.
const openSection = reactive<Record<Feature, string>>({
  GIFT: 'text',
  SCENE: 'scene',
  SELLING_POINT: 'text',
})
function toggle(id: string) {
  openSection[feature.value] = openSection[feature.value] === id ? '' : id
}

// What the canvas shows: the composition guide or one result (task + image index).
const view = ref<{ task: string; ordinal: number } | null>(null)
const mode = ref<'plan' | 'result'>('plan')
const compare = ref(false)
watch(feature, () => {
  view.value = null
  mode.value = 'plan'
  compare.value = false
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
const failure = computed(() =>
  shown.value?.status === 'FAILED' ? shown.value.error : null,
)
const generating = computed(
  () =>
    !!w.selected &&
    w.selected.feature_type === feature.value &&
    ['QUEUED', 'RUNNING'].includes(w.selected.status),
)
const originals = computed(() => {
  const request = shown.value?.request
  return {
    product: String(request?.product_asset_id ?? draft.value.product),
    gift: request?.gift_asset_id ? String(request.gift_asset_id) : '',
  }
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
  const light = draft.value.textColor.toUpperCase() === '#FFFFFF'
  return {
    badge: '#FFFFFF',
    badgeText: light ? '#4A2E1F' : draft.value.textColor,
    accent: light ? '#C8814E' : draft.value.textColor,
  }
})
const preview = computed(() =>
  hasText.value ? textSpec(draft.value, outputSize.value.width) : null,
)
// Selling images take the title colour of their style (no separate colour choice).
watch(
  () => [feature.value, draft.value.styles[0], styles.value] as const,
  () => {
    if (feature.value !== 'SELLING_POINT') return
    const style = styles.value.find((s) => s.id === draft.value.styles[0])
    if (style) draft.value.textColor = style.title_color
  },
  { immediate: true },
)

const blocked = computed(() => {
  try {
    buildGeneration(feature.value, w.project, draft.value)
    return ''
  } catch (cause) {
    return cause instanceof Error ? cause.message : '输入不完整。'
  }
})
const imageCount = computed(() =>
  feature.value === 'SELLING_POINT'
    ? draft.value.styles.length
    : draft.value.count,
)
const modelOptions = computed(() =>
  w.models.map((item) => ({
    value: item.id,
    label: item.name,
    hint: providerNames[item.provider] ?? item.provider,
  })),
)
const sizeOptions = canvasSizes.map((size, index) => ({
  value: index,
  label: size.label,
  hint: size.ratio,
}))
const countOptions = computed(() =>
  Array.from({ length: w.generation?.max_count ?? 4 }, (_, i) => ({
    value: i + 1,
    label: `${i + 1} 张`,
  })),
)
const sellingCount = computed({
  get: () => draft.value.styles.length,
  set: () => undefined,
})

const summary = computed(() => {
  const d = draft.value
  const firstLine = d.title.split('\n')[0]?.trim()
  const model = w.models.find((m) => m.id === d.model)?.name ?? '未配置模型'
  return {
    gift: giftPositions.find((p) => p.id === d.giftPosition)?.name ?? '',
    background:
      d.backgroundMode === 'CUSTOM'
        ? d.backgroundPrompt.trim() || '自定义描述'
        : (backgrounds.find((b) => b.color === d.backgroundColor)?.name ??
          d.backgroundColor),
    text: `${firstLine || '未填写标题'} · ${pointLines(d).length} 条`,
    scene: d.scenePreset
      ? (w.generation?.scene_presets.find((s) => s.id === d.scenePreset)
          ?.name ?? d.scenePreset)
      : '自定义',
    styles:
      d.styles
        .map((id) => styles.value.find((s) => s.id === id)?.name ?? id)
        .join('、') || '未选择',
    output: `${model} · ${canvasSizes[d.size]!.label} · ${imageCount.value} 张`,
  }
})

function toggleStyle(id: string) {
  const list = draft.value.styles
  draft.value.styles = list.includes(id)
    ? list.filter((item) => item !== id)
    : [...list, id]
}

// Results of this entry, newest first; the selected task may be fresher than the list.
type Tile = {
  key: string
  task: Task
  ordinal: number
  artifact: Task['artifacts'][number] | null
}
const tiles = computed<Tile[]>(() => {
  const list: Task[] = w.history
    .filter(
      (item) => item.generation_v4 && item.task.feature_type === feature.value,
    )
    .map((item) => item.task)
  const current = w.selected
  const tasks =
    current && current.feature_type === feature.value
      ? [current as Task, ...list.filter((task) => task.id !== current.id)]
      : list
  return tasks.flatMap((task): Tile[] =>
    task.status === 'SUCCEEDED'
      ? task.artifacts.map((artifact, ordinal) => ({
          key: artifact.id,
          task,
          ordinal,
          artifact,
        }))
      : [{ key: task.id, task, ordinal: 0, artifact: null }],
  )
})

async function open(task: string, ordinal: number) {
  await w.select(task)
  if (w.selected?.id !== task) return
  view.value = { task, ordinal }
  mode.value = 'result'
  const text = w.selected.request?.text
  if (hasText.value && text && w.selected.output)
    adoptText(feature.value, draft.value, text, w.selected.output.width)
}
async function compareWith(task: string, ordinal: number) {
  await open(task, ordinal)
  compare.value = true
}
async function retry(task: string) {
  await w.select(task)
  await w.retry()
}
function remove(artifact: string) {
  if (confirm('确定删除这张生成结果？删除后不可恢复，也不能再免费改字。'))
    void w.deleteArtifact(artifact)
}
watch(
  () => [w.selected?.id, w.selected?.status] as const,
  ([id, status]) => {
    if (!id || w.selected?.feature_type !== feature.value) return
    if (status !== 'SUCCEEDED' && status !== 'FAILED') return
    // Show a finished task but keep any text the user edited while waiting.
    if (!view.value || view.value.task !== id)
      view.value = { task: id, ordinal: 0 }
    mode.value = 'result'
  },
)
async function generate() {
  view.value = null
  mode.value = 'plan'
  compare.value = false
  await w.submit(feature.value)
}
async function applyText() {
  const text = preview.value
  if (!view.value || !text) return
  await w.retypeset(view.value.task, view.value.ordinal, text)
}
function openFromQuery() {
  const task = route.query.task
  if (typeof task === 'string') void open(task, 0)
}
watch(() => route.query.task, openFromQuery)
onMounted(() => {
  void w.refreshOptions()
  openFromQuery()
})
</script>

<template>
  <main class="board">
    <section class="card studio-left" aria-label="素材与参数">
      <div class="sec">
        <h2 class="sec-head">素材</h2>
        <div class="slots" :class="{ one: feature !== 'GIFT' }">
          <AssetSlot v-model="draft.product" label="商品图" kind="PRODUCT" />
          <AssetSlot
            v-if="feature === 'GIFT'"
            v-model="draft.gift"
            label="赠品图"
            kind="GIFT"
          />
        </div>
      </div>

      <fieldset class="params" :disabled="locked">
        <template v-if="feature === 'GIFT'">
          <ParamSection
            title="赠品位置"
            icon="gift"
            :summary="summary.gift"
            :open="openSection.GIFT === 'gift'"
            @toggle="toggle('gift')"
          >
            <div class="posmap" role="group" aria-label="赠品位置">
              <span></span><span></span><span></span>
              <button
                v-for="[id, name, area] in [
                  ['LEFT', '左侧', '2 / 1'],
                  ['RIGHT', '右侧', '2 / 3'],
                  ['BOTTOM_LEFT', '左下', '3 / 1'],
                  ['BOTTOM_RIGHT', '右下', '3 / 3'],
                ] as const"
                :key="id"
                type="button"
                :style="{ gridArea: area }"
                :aria-pressed="draft.giftPosition === id"
                @click="draft.giftPosition = id"
              >
                {{ name }}
              </button>
              <span class="prod">商品</span>
            </div>
          </ParamSection>
          <ParamSection
            title="背景"
            icon="scene"
            :summary="summary.background"
            :open="openSection.GIFT === 'bg'"
            @toggle="toggle('bg')"
          >
            <div class="seg" role="group" aria-label="背景方式">
              <button
                type="button"
                :aria-pressed="draft.backgroundMode === 'SOLID'"
                @click="draft.backgroundMode = 'SOLID'"
              >
                纯色
              </button>
              <button
                type="button"
                :aria-pressed="draft.backgroundMode === 'CUSTOM'"
                @click="draft.backgroundMode = 'CUSTOM'"
              >
                描述
              </button>
            </div>
            <div
              v-if="draft.backgroundMode === 'SOLID'"
              class="swatches"
              role="group"
              aria-label="背景颜色"
            >
              <button
                v-for="item in backgrounds"
                :key="item.color"
                type="button"
                class="swatch"
                :title="item.name"
                :aria-label="`背景 ${item.name}`"
                :aria-pressed="draft.backgroundColor === item.color"
                :style="{ background: item.color }"
                @click="draft.backgroundColor = item.color"
              ></button>
            </div>
            <label v-else class="form-row"
              ><span>背景描述</span
              ><input
                v-model="draft.backgroundPrompt"
                maxlength="300"
                placeholder="例如：浅木色桌面，柔和自然光"
            /></label>
          </ParamSection>
        </template>

        <ParamSection
          v-if="feature === 'SCENE'"
          title="场景"
          icon="scene"
          :summary="summary.scene"
          :open="openSection.SCENE === 'scene'"
          @toggle="toggle('scene')"
        >
          <div class="scenes" role="group" aria-label="场景预设">
            <button
              v-for="item in w.generation?.scene_presets ?? []"
              :key="item.id"
              type="button"
              class="scene-card"
              :aria-pressed="draft.scenePreset === item.id"
              @click="draft.scenePreset = item.id"
            >
              <SceneArt :scene="item.id" />{{ item.name }}
            </button>
            <button
              type="button"
              class="scene-card"
              :aria-pressed="draft.scenePreset === ''"
              @click="draft.scenePreset = ''"
            >
              <SceneArt scene="custom" />自定义
            </button>
          </div>
          <label class="form-row"
            ><span>{{
              draft.scenePreset ? '补充描述（可选）' : '场景描述'
            }}</span
            ><input
              v-model="draft.scenePrompt"
              maxlength="500"
              placeholder="例如：窗边暖光，旁边放一只小熊玩偶"
          /></label>
        </ParamSection>

        <ParamSection
          v-if="hasText"
          :title="feature === 'SELLING_POINT' ? '卖点文字' : '营销文字'"
          icon="text"
          :summary="summary.text"
          :open="openSection[feature] === 'text'"
          @toggle="toggle('text')"
        >
          <label class="form-row"
            ><span>标题</span
            ><textarea
              v-model="draft.title"
              rows="2"
              maxlength="60"
              :placeholder="
                feature === 'SELLING_POINT'
                  ? '例如：轻松喂养\n宝宝更舒适'
                  : '例如：下单即送\n宝宝软勺'
              "
            ></textarea>
          </label>
          <label class="form-row"
            ><span>{{
              feature === 'SELLING_POINT'
                ? '卖点（每行一条）'
                : '标签（每行一条）'
            }}</span
            ><textarea
              v-model="draft.points"
              rows="3"
              :placeholder="
                feature === 'SELLING_POINT'
                  ? '安全材质\n防胀气设计\n易清洗'
                  : '食品级硅胶'
              "
            ></textarea>
          </label>
          <div class="form-row">
            <span>位置</span>
            <div class="seg" role="group" aria-label="文字位置">
              <button
                v-for="item in textPositions"
                :key="item.id"
                type="button"
                :aria-pressed="draft.textPosition === item.id"
                @click="placeText(feature, draft, item.id)"
              >
                {{ item.name }}
              </button>
            </div>
          </div>
          <div class="inline-fields">
            <div class="form-row">
              <span>大小</span>
              <div class="seg" role="group" aria-label="文字大小">
                <button
                  v-for="(item, index) in textLevels"
                  :key="item.name"
                  type="button"
                  :aria-pressed="draft.textLevel === index"
                  @click="draft.textLevel = index"
                >
                  {{ item.name }}
                </button>
              </div>
            </div>
            <div v-if="feature === 'GIFT'" class="form-row">
              <span>颜色</span>
              <div class="swatches" role="group" aria-label="文字颜色">
                <button
                  v-for="item in textColors"
                  :key="item.color"
                  type="button"
                  class="swatch"
                  :title="item.name"
                  :aria-label="`文字 ${item.name}`"
                  :aria-pressed="draft.textColor === item.color"
                  :style="{ background: item.color }"
                  @click="draft.textColor = item.color"
                ></button>
              </div>
            </div>
          </div>
        </ParamSection>

        <ParamSection
          v-if="feature === 'SELLING_POINT'"
          title="风格"
          icon="grid"
          :summary="summary.styles"
          :open="openSection.SELLING_POINT === 'style'"
          @toggle="toggle('style')"
        >
          <div
            class="styles"
            role="group"
            aria-label="风格（每种风格生成一张）"
          >
            <button
              v-for="item in styles"
              :key="item.id"
              type="button"
              class="style-card"
              :aria-pressed="draft.styles.includes(item.id)"
              @click="toggleStyle(item.id)"
            >
              <span class="pal" aria-hidden="true"
                ><i :style="{ background: item.badge_color }"></i
                ><i :style="{ background: item.accent_color }"></i
                ><i :style="{ background: item.title_color }"></i></span
              >{{ item.name }}
            </button>
          </div>
          <small class="hint"
            >每种风格生成一张，已选 {{ draft.styles.length }} 种。</small
          >
        </ParamSection>

        <ParamSection
          title="输出设置"
          icon="cpu"
          :summary="summary.output"
          :open="openSection[feature] === 'out'"
          @toggle="toggle('out')"
        >
          <div class="form-row">
            <span>模型</span>
            <DropSelect
              v-model="draft.model"
              label="模型"
              tall
              :options="modelOptions"
              placeholder="未配置模型"
              :disabled="locked || !modelOptions.length"
            />
          </div>
          <div class="pair">
            <div class="form-row">
              <span>尺寸</span>
              <DropSelect
                v-model="draft.size"
                label="尺寸"
                :options="sizeOptions"
                :disabled="locked"
              />
            </div>
            <div class="form-row">
              <span>数量</span>
              <DropSelect
                v-if="feature === 'SELLING_POINT'"
                v-model="sellingCount"
                label="数量"
                :options="[
                  {
                    value: draft.styles.length,
                    label: `${draft.styles.length} 张`,
                  },
                ]"
                disabled
              />
              <DropSelect
                v-else
                v-model="draft.count"
                label="数量"
                :options="countOptions"
                :disabled="locked"
              />
            </div>
          </div>
        </ParamSection>
      </fieldset>

      <div class="generate">
        <p v-if="w.uncertain" class="reason warn">
          上次提交结果不确定，将重发同一份请求，不会重复创建任务。
        </p>
        <p
          v-else-if="blocked"
          id="generate-reason"
          class="reason"
          :title="blocked"
        >
          {{ blocked }}
        </p>
        <button
          type="button"
          class="btn primary generate-button"
          data-testid="generate"
          :disabled="w.busy || (!!blocked && !w.uncertain)"
          :aria-describedby="blocked ? 'generate-reason' : undefined"
          @click="generate"
        >
          <span v-if="w.busy" class="spinner"></span>
          <LineIcon v-else name="spark" />
          {{
            w.busy
              ? '处理中…'
              : w.uncertain
                ? '用原请求重发'
                : imageCount > 1
                  ? `生成 ${imageCount} 张`
                  : '生成图片'
          }}
        </button>
      </div>
    </section>

    <section class="card studio-right" aria-label="编辑设计与生成结果">
      <StudioCanvas
        v-model:mode="mode"
        v-model:compare="compare"
        v-model:box="draft.textBox"
        :feature="feature"
        :width="outputSize.width"
        :height="outputSize.height"
        :image="stageImage"
        :image-alt="`${meta.name}生成结果`"
        :text="preview"
        :text-align="draft.textAlign"
        :palette="palette"
        :product="originals.product"
        :gift="originals.gift"
        :gift-position="
          String(shown?.request?.gift_position ?? draft.giftPosition)
        "
        :has-result="!!shown"
        :generating="generating"
        :failure="failure"
        :can-apply="shown?.status === 'SUCCEEDED' && !!preview"
        :disabled="locked"
        :api="w.api"
        @moved="draft.textPosition = ''"
        @apply="applyText"
        @retry="shown && retry(shown.id)"
      />
      <div class="results">
        <div class="results-head">
          <b>最近结果</b><span class="count num">{{ tiles.length }}</span>
          <span class="spacer"></span>
          <button
            type="button"
            class="icon-btn"
            aria-label="刷新结果"
            title="刷新"
            :disabled="w.busy"
            @click="w.refreshHistory()"
          >
            <LineIcon name="refresh" />
          </button>
          <router-link class="link-btn" to="/works">全部作品</router-link>
        </div>
        <div class="strip">
          <article
            v-for="tile in tiles"
            :key="tile.key"
            class="tile"
            :class="{
              running: !tile.artifact && tile.task.status !== 'FAILED',
              shimmer: ['QUEUED', 'RUNNING'].includes(tile.task.status),
            }"
            data-testid="result-card"
            :data-task="tile.task.id"
            :data-status="tile.task.status"
            :data-selected="
              view?.task === tile.task.id && view.ordinal === tile.ordinal
            "
            :title="
              tile.task.error
                ? `${tile.task.error.message}（${tile.task.error.code}）`
                : undefined
            "
          >
            <button
              type="button"
              class="open"
              :aria-label="`查看结果 ${tile.ordinal + 1}`"
              :disabled="w.busy"
              @click="open(tile.task.id, tile.ordinal)"
            >
              <PrivateImage
                v-if="tile.artifact"
                :path="`/artifacts/${tile.artifact.id}/content`"
                :alt="`${meta.name}结果 ${tile.artifact.width}×${tile.artifact.height}`"
                :api="w.api"
              />
              <template v-else-if="tile.task.status === 'FAILED'">
                <LineIcon name="alert" :size="20" />
                <span class="sr-only"
                  >生成失败：{{ tile.task.error?.message }}（{{
                    tile.task.error?.code
                  }}）</span
                >
              </template>
              <template v-else
                ><span class="spinner"></span
                ><span>{{
                  tile.task.status === 'QUEUED' ? '排队中' : '生成中'
                }}</span></template
              >
            </button>
            <span v-if="tile.task.status === 'FAILED'" class="flag">失败</span>
            <div v-if="tile.artifact" class="hover-actions">
              <button
                type="button"
                aria-label="对照原图"
                title="对照原图"
                :disabled="w.busy"
                @click="compareWith(tile.task.id, tile.ordinal)"
              >
                <LineIcon name="cmp" :size="13" />
              </button>
              <button
                type="button"
                aria-label="下载"
                title="下载"
                :disabled="w.busy"
                @click="
                  w.download(
                    tile.artifact.id,
                    `${meta.route}-${tile.artifact.id}`,
                  )
                "
              >
                <LineIcon name="dl" :size="13" />
              </button>
              <button
                type="button"
                class="danger"
                aria-label="删除"
                title="删除"
                :disabled="w.busy"
                @click="remove(tile.artifact.id)"
              >
                <LineIcon name="del" :size="13" />
              </button>
            </div>
            <div
              v-else-if="tile.task.status === 'FAILED'"
              class="hover-actions always"
            >
              <button
                type="button"
                aria-label="重试"
                title="重试"
                :disabled="w.busy"
                @click="retry(tile.task.id)"
              >
                <LineIcon name="redo" :size="13" />
              </button>
            </div>
          </article>
          <EmptyState v-if="!tiles.length" compact>暂无结果</EmptyState>
        </div>
      </div>
    </section>
  </main>
</template>
