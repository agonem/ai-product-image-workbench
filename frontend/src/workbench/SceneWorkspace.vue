<script setup lang="ts">
import { inject, ref } from 'vue'
import { workbenchKey } from './useWorkbench'
import SceneCanvas from './SceneCanvas.vue'
import PrivateImage from './PrivateImage.vue'
import BoxFields from './BoxFields.vue'
import CutoutPanel from './CutoutPanel.vue'
import { statusLabels } from './model'
const w = inject(workbenchKey)!
defineProps<{
  blocked: string
}>()
const enlarged = ref(false)
function ratioChanged() {
  const output = w.draft.sceneOutput
  const [x, y] = output.aspect_ratio.split(':').map(Number)
  const unit = Math.max(1, Math.floor(1024 / Math.max(x!, y!)))
  output.width = x! * unit
  output.height = y! * unit
}
async function show(id: string) {
  await w.showImage(id, true)
  enlarged.value = !!w.preview
}
</script>
<template>
  <section class="scene-workspace" aria-label="场景编辑工作台">
    <h1>场景主图 <small>上传素材 → 编辑位置与场景 → 查看真实结果</small></h1>
    <form class="scene-grid" @submit.prevent="w.submit">
      <section class="panel scene-assets">
        <h2>1. 上传素材</h2>
        <label
          >商品原图<select
            v-model="w.draft.product"
            required
            :disabled="w.busy || w.uncertain"
          >
            <option value="">选择商品原图</option>
            <option
              v-for="asset in w.assets.filter((a) => a.kind === 'PRODUCT')"
              :key="asset.id"
              :value="asset.id"
            >
              {{ asset.id }} ·
              {{ asset.cutout_ready ? '抠图已确认' : '抠图待确认' }}
            </option>
          </select></label
        >
        <div class="asset-thumbnail" v-if="w.draft.product">
          <PrivateImage
            :key="w.draft.product"
            :path="`/assets/${w.draft.product}/content`"
            alt="商品原图"
            :api="w.api"
          />
        </div>
        <label class="upload"
          >上传商品图<input
            type="file"
            accept="image/png,image/jpeg"
            :disabled="w.busy || w.uncertain"
            @change="w.upload($event, 'PRODUCT')"
        /></label>
        <CutoutPanel
          v-if="w.draft.product"
          :key="w.draft.product"
          :asset="w.draft.product"
          label="商品"
        />
        <p class="asset-note">
          原图保留，模型仅生成背景。新上传的商品须先确认抠图边缘。
        </p>
        <button
          v-if="w.assetNext !== null"
          type="button"
          class="secondary"
          :disabled="w.busy"
          @click="w.moreAssets"
        >
          加载更多素材
        </button>
        <div class="capability-note">
          <strong>商品保真</strong>
          <p>狮子图案、印花、孔洞和细带均来自原图。允许等比缩放和位置调整。</p>
        </div>
      </section>
      <SceneCanvas
        :key="w.project + ':' + w.draft.product"
        :product="w.draft.product"
        :width="w.draft.sceneOutput.width"
        :height="w.draft.sceneOutput.height"
        :disabled="w.busy || w.uncertain"
        :api="w.api"
        v-model:box="w.draft.productBox"
      />
      <section class="panel scene-parameters">
        <h2>3. 参数设置</h2>
        <fieldset class="fields" :disabled="w.busy || w.uncertain">
          <label
            >场景来源<select v-model="w.draft.sceneTemplate">
              <option value="">自定义描述</option>
              <option
                v-for="item in w.options?.templates.filter(
                  (t) => t.type === 'scene',
                )"
                :key="item.id"
                :value="item.id"
              >
                {{ item.name }} · v{{ item.version }}
              </option>
            </select></label
          >
          <small v-if="!w.options?.templates.some((t) => t.type === 'scene')"
            >暂无已发布场景预设；预设管理尚未实现。</small
          >
          <label v-if="!w.draft.sceneTemplate"
            >场景描述<textarea
              v-model="w.draft.scene"
              rows="4"
              required
              placeholder="浅色木桌，柔和左侧采光，为商品预留承托面"
            />
          </label>
          <label
            >自定义风格（可选）<input
              v-model="w.draft.style"
              placeholder="例如：温暖、自然光"
          /></label>
          <label
            >画布比例<select
              v-model="w.draft.sceneOutput.aspect_ratio"
              @change="ratioChanged"
            >
              <option
                v-for="ratio in w.options?.scene?.aspect_ratios"
                :key="ratio"
              >
                {{ ratio }}
              </option>
            </select></label
          >
          <div class="dimension-row">
            <label
              >输出宽度（像素）<input
                v-model.number="w.draft.sceneOutput.width"
                type="number"
                min="64"
                max="2048"
                required /></label
            ><label
              >输出高度（像素）<input
                v-model.number="w.draft.sceneOutput.height"
                type="number"
                min="64"
                max="2048"
                required
            /></label>
          </div>
          <div class="dimension-row">
            <label
              >导出格式<select v-model="w.draft.sceneOutput.format">
                <option
                  v-for="format in w.options?.scene?.formats"
                  :key="format"
                >
                  {{ format }}
                </option>
              </select></label
            ><label
              >生成数量<input
                v-model.number="w.draft.sceneOutput.count"
                type="number"
                min="1"
                :max="w.options?.scene?.max_count"
                step="1"
                required
            /></label>
          </div>
          <details>
            <summary>位置与尺寸参数</summary>
            <BoxFields title="商品" v-model:box="w.draft.productBox" />
          </details>
          <small
            >背景等比缩放、居中裁切，本地导出指定规格。平台专用预设待核实。</small
          >
        </fieldset>
        <p v-if="blocked" class="blocked">{{ blocked }}</p>
        <p v-if="w.uncertain" class="blocked">
          提交结果不确定。仅重发原请求，不重复创建任务。
        </p>
        <button
          type="submit"
          class="generate-button"
          :disabled="w.busy || w.loading || (!!blocked && !w.uncertain)"
        >
          {{ w.busy ? '处理中…' : w.uncertain ? '用原请求重发' : '生成场景图' }}
        </button>
        <small>真实调用可能产生费用；全部成功才展示。新结果待人工审核。</small>
      </section>
    </form>
    <section
      class="panel task-panel scene-results"
      aria-labelledby="task-title"
    >
      <div class="section-heading">
        <h2 id="task-title">生成结果 <small>PENDING · 等待人工审核</small></h2>
        <button
          class="text-button"
          :disabled="!w.selected || w.busy"
          @click="w.refreshTask"
        >
          刷新状态
        </button>
      </div>
      <template v-if="w.selected">
        <strong class="task-status" :data-status="w.selected.status">{{
          w.selectedRealScene && w.selected.status === 'SUCCEEDED'
            ? w.mockProvider
              ? '模拟链路完成 · 非真实生成'
              : '场景合成完成 · 待人工审核'
            : statusLabels[w.selected.status]
        }}</strong>
        <small>任务 {{ w.selected.id }} · 第 {{ w.selected.attempt }} 次</small>
        <div v-if="w.selected.error" class="message error">
          <p>{{ w.selected.error.message }}</p>
          <small
            >{{ w.selected.error.code }} ·
            {{ w.selected.error.correlation_id }}</small
          >
        </div>
        <template v-if="w.selected.status === 'FAILED'"
          ><button class="secondary" :disabled="w.busy" @click="w.retry">
            重试任务</button
          ><small
            >整批重新生成，可能再次收费；是否允许重试由服务端决定。</small
          ></template
        >
        <div class="result-strip">
          <article
            v-for="artifact in w.selected.artifacts"
            :key="artifact.id"
            class="artifact"
          >
            <button
              class="result-image"
              @click="show(artifact.id)"
              :aria-label="w.selectedRealScene ? '查看场景图' : '查看测试产物'"
            >
              <PrivateImage
                :path="`/artifacts/${artifact.id}/content`"
                :alt="`结果缩略图 ${artifact.width}×${artifact.height} · 待审核`"
                :api="w.api"
              />
            </button>
            <small
              >{{
                w.selectedRealScene ? w.sceneLabel : '测试产物 · 非真实成品'
              }}
              · {{ artifact.width }}×{{ artifact.height }}</small
            >
            <button
              class="text-button"
              :disabled="w.busy"
              @click="w.showImage(artifact.id, true, true)"
            >
              {{ w.selectedRealScene ? '下载场景图' : '下载测试产物' }}
            </button>
          </article>
        </div>
        <p
          v-if="
            w.selected.status === 'QUEUED' || w.selected.status === 'RUNNING'
          "
        >
          {{
            w.selected.status === 'QUEUED'
              ? '等待 Worker 领取任务…'
              : '正在生成背景并合成商品…'
          }}
          本批次全部完成后显示结果。
        </p>
      </template>
      <p v-else class="empty">提交场景任务后，真实处理的图片将显示在这里。</p>
    </section>
    <dialog
      :open="enlarged && !!w.preview"
      class="image-dialog preview-panel"
      @keydown.esc="enlarged = false"
    >
      <button class="secondary" @click="enlarged = false">关闭放大预览</button>
      <figure v-if="w.preview">
        <img :src="w.preview" :alt="w.previewTitle" />
        <figcaption>{{ w.previewTitle }}</figcaption>
      </figure>
    </dialog>
  </section>
</template>
