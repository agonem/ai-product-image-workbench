<script setup lang="ts">
import { computed, provide, reactive } from 'vue'
import BoxFields from './workbench/BoxFields.vue'
import AccountPanel from './workbench/AccountPanel.vue'
import SceneWorkspace from './workbench/SceneWorkspace.vue'
import { features, statusLabels } from './workbench/model'
import { useWorkbench, workbenchKey } from './workbench/useWorkbench'

const w = reactive(useWorkbench())
provide(workbenchKey, w)
const title = computed(
  () => features.find((item) => item.id === w.feature)!.name,
)
const blocked = computed(() =>
  !w.project
    ? '先创建或选择项目。'
    : !w.draft.product
      ? '先上传或选择商品白底原图。'
      : !w.selectedProduct?.cutout_ready
        ? '商品边缘待审核。T02 审核能力尚未接入，普通上传暂不能生成。'
        : !w.realSceneEnabled && !w.draft.preset
          ? '请选择已配置的输出预设。'
          : '',
)
const date = (value: string) => new Date(value).toLocaleString('zh-CN')
</script>

<template>
  <div class="shell" :class="{ 'authenticated-shell': w.token }">
    <aside v-if="w.token" class="side-nav" aria-label="工作台导航">
      <strong class="side-brand">商品图工作台</strong
      ><small>AI 背景 · 商品保真</small>
      <span class="nav-caption">图片生成</span>
      <button
        v-for="item in features"
        :key="item.id"
        :aria-label="`切换到${item.id === 'GIFT' ? '赠品' : item.id === 'SCENE' ? '场景' : '卖点'}`"
        :aria-current="w.feature === item.id ? 'page' : undefined"
        :disabled="w.busy || w.uncertain"
        @click="w.feature = item.id"
      >
        {{ item.name }}
      </button>
      <a href="#project-tools">素材与项目</a
      ><a href="#history-title">任务记录</a
      ><a v-if="w.production" href="#account-tools">账号与安全</a>
      <span class="unavailable-nav">模板管理 <small>尚未实现</small></span>
      <p class="side-footer">原图保留<br />生成结果人工审核</p>
    </aside>
    <header class="page-header">
      <div>
        <strong class="brand">商品图工作台</strong
        ><span class="badge">{{
          w.production ? '生产本地账号' : 'dev-local · 开发环境'
        }}</span>
      </div>
      <button
        v-if="w.token"
        class="secondary"
        :disabled="w.busy"
        @click="w.logout"
      >
        退出本地账号
      </button>
    </header>
    <aside class="development-note" aria-label="能力边界">
      <strong v-if="w.mockProvider">模拟供应商验收模式 · 非真实生成</strong>
      <strong>{{
        w.options?.scene?.enabled
          ? '场景背景生成已接入 · 商品像素来自原图'
          : '真实图片生成尚未开放'
      }}</strong>
      <span v-if="w.options?.scene?.enabled"
        >场景结果需人工审核；赠品与卖点入口的真实生成尚未开放。三分钟为待压测目标，不保证完成时间。</span
      >
      <span v-else
        >T07 / T08 / T09
        未完成；当前可验证提交、状态和历史。测试产物不代表商品成品。{{
          w.production
            ? '生产本地认证已接入；制图能力仍待验收。'
            : '开发本地账号不用于生产认证。'
        }}</span
      >
    </aside>
    <p v-if="w.error" class="message error" role="alert">{{ w.error }}</p>
    <p v-if="w.notice" class="message" role="status">{{ w.notice }}</p>

    <main v-if="!w.token" class="login-layout">
      <section>
        <h1>把素材和任务放在一起</h1>
        <p>
          赠品、场景、卖点，选择需要的入口即可。每个任务都能回看状态和失败原因。
        </p>
        <ul class="intro-list">
          <li>商品原图独立保存</li>
          <li>三个入口互不依赖</li>
          <li>任务历史按项目保存</li>
        </ul>
      </section>
      <form class="panel login" @submit.prevent="w.login">
        <h2>{{ w.production ? '生产账号登录' : '开发账号登录' }}</h2>
        <p v-if="w.production">
          使用管理员分配的本地账号。账号无默认密码；忘记密码请联系管理员。
        </p>
        <p v-else>
          仅连接以 dev-local 启动的 Java
          服务。账号由开发者在本机创建，无默认密码。
        </p>
        <label
          >本地账号<input
            v-model="w.username"
            name="username"
            autocomplete="username"
            required
            :disabled="w.busy"
        /></label>
        <label
          >密码<input
            v-model="w.password"
            name="password"
            type="password"
            autocomplete="current-password"
            required
            :disabled="w.busy"
        /></label>
        <button :disabled="w.busy">
          {{
            w.busy ? '连接中…' : w.production ? '登录生产账号' : '登录开发环境'
          }}
        </button>
        <small>会话只保存在当前页面内存中，刷新后需重新登录。</small>
      </form>
    </main>

    <main v-else>
      <div id="account-tools">
        <AccountPanel
          v-if="w.production && w.identity"
          :role="w.identity.role"
          :api="w.api"
          @changed="w.expire"
        />
      </div>
      <section id="project-tools" class="project-bar" aria-label="项目">
        <label
          >当前项目（最近100个）<select
            v-model="w.project"
            :disabled="w.busy || w.loading || w.uncertain"
            @change="w.loadProject"
          >
            <option value="" disabled>请选择项目</option>
            <option v-for="p in w.projects" :key="p.id" :value="p.id">
              {{ p.name }}
            </option>
          </select></label
        >
        <form class="inline-form" @submit.prevent="w.createProject">
          <label
            >新项目名称<input
              v-model="w.projectName"
              maxlength="120"
              required
              :disabled="w.busy || w.uncertain"
          /></label>
          <button class="secondary" :disabled="w.busy || w.uncertain">
            创建项目
          </button>
        </form>
        <button
          class="text-button"
          :disabled="w.busy || w.uncertain"
          @click="w.reload"
        >
          刷新项目与配置
        </button>
      </section>

      <h2 class="entry-heading">选择功能开始生成</h2>
      <nav class="entry-nav" aria-label="独立制图入口">
        <button
          v-for="item in features"
          :key="item.id"
          :data-feature="item.id"
          :aria-pressed="w.feature === item.id"
          :disabled="w.busy || w.uncertain"
          @click="w.feature = item.id"
        >
          <strong>{{ item.name }}</strong
          ><span>{{ item.description }}</span>
        </button>
      </nav>
      <p v-if="w.loading" role="status">正在读取项目素材与任务…</p>
      <p v-else-if="!w.project" class="empty">
        还没有项目。创建项目后上传素材，开始验证工作流程。
      </p>

      <SceneWorkspace
        v-if="w.project && w.realSceneEnabled"
        :key="w.project"
        :blocked="blocked"
      />
      <div v-if="w.project && !w.realSceneEnabled" class="workspace">
        <section class="panel inputs" aria-labelledby="input-title">
          <h1 id="input-title">{{ title }} · 输入</h1>
          <p>单张商品白底图；原图不会被生成模型重绘。</p>
          <form @submit.prevent="w.submit">
            <fieldset
              :disabled="w.busy || w.loading || w.uncertain"
              class="fields"
            >
              <label
                >商品原图<select v-model="w.draft.product" required>
                  <option value="">选择商品素材</option>
                  <option
                    v-for="asset in w.assets.filter(
                      (a) => a.kind === 'PRODUCT',
                    )"
                    :key="asset.id"
                    :value="asset.id"
                  >
                    {{ asset.id }} · {{ asset.width }}×{{ asset.height }} ·
                    {{ asset.cutout_ready ? '已有审核 alpha' : '边缘待审核' }}
                  </option>
                </select></label
              >
              <div class="asset-actions">
                <label class="upload"
                  >上传商品图<input
                    type="file"
                    accept="image/png,image/jpeg"
                    @change="w.upload($event, 'PRODUCT')"
                /></label>
                <button
                  type="button"
                  class="text-button"
                  :disabled="!w.draft.product"
                  @click="w.showImage(w.draft.product)"
                >
                  查看商品原图
                </button>
              </div>
              <small
                >支持 PNG/JPEG，实际内容、尺寸与资源预算由 Java
                校验；带复杂元数据的文件可能被拒绝。</small
              >

              <template v-if="w.feature === 'GIFT'">
                <label
                  >独立赠品图<select v-model="w.draft.gift" required>
                    <option value="">选择赠品素材</option>
                    <option
                      v-for="asset in w.assets.filter((a) => a.kind === 'GIFT')"
                      :key="asset.id"
                      :value="asset.id"
                    >
                      {{ asset.id }} · {{ asset.width }}×{{ asset.height }}
                    </option>
                  </select></label
                >
                <div class="asset-actions">
                  <label class="upload"
                    >上传赠品图<input
                      type="file"
                      accept="image/png,image/jpeg"
                      @change="w.upload($event, 'GIFT')"
                  /></label>
                  <button
                    type="button"
                    class="text-button"
                    :disabled="!w.draft.gift"
                    @click="w.showImage(w.draft.gift)"
                  >
                    查看赠品原图
                  </button>
                </div>
                <label
                  >人工补充文字（可选）<input v-model="w.draft.manual"
                /></label>
              </template>
              <template v-if="w.feature === 'SCENE'">
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
                <label v-if="!w.draft.sceneTemplate"
                  >场景描述<textarea
                    v-model="w.draft.scene"
                    rows="3"
                    required
                    placeholder="例如：明亮的婴儿房，浅色木质桌面"
                  ></textarea>
                </label>
                <label
                  >自定义风格（可选）<input
                    v-model="w.draft.style"
                    placeholder="人工描述风格，不自动改写"
                /></label>
              </template>
              <label v-if="w.feature === 'SELLING_POINT'"
                >人工卖点（每行一条，原文提交）<textarea
                  v-model="w.draft.selling"
                  rows="4"
                  required
                  placeholder="输入已确认的商品卖点"
                ></textarea>
              </label>
              <label v-if="w.feature !== 'SCENE'"
                >排版模板版本<select v-model="w.draft.template" required>
                  <option value="">选择已发布版本</option>
                  <option
                    v-for="item in w.options?.templates.filter(
                      (t) => t.type === 'layout',
                    )"
                    :key="item.id"
                    :value="item.id"
                  >
                    {{ item.name }} · v{{ item.version }}
                  </option>
                </select></label
              >
              <label v-if="!w.realSceneEnabled"
                >输出预设<select v-model="w.draft.preset" required>
                  <option value="">选择已配置预设</option>
                  <option
                    v-for="item in w.options?.output_presets"
                    :key="item.id"
                    :value="item.id"
                  >
                    {{
                      item.test_fixture
                        ? '开发/测试传输夹具 · 非图片规格'
                        : item.id
                    }}
                  </option>
                </select></label
              >
              <template v-if="w.realSceneEnabled">
                <label
                  >画布比例<select v-model="w.draft.sceneOutput.aspect_ratio">
                    <option
                      v-for="ratio in w.options?.scene?.aspect_ratios"
                      :key="ratio"
                    >
                      {{ ratio }}
                    </option>
                  </select></label
                >
                <label
                  >输出宽度（像素）<input
                    v-model.number="w.draft.sceneOutput.width"
                    type="number"
                    min="64"
                    max="2048"
                    required
                /></label>
                <label
                  >输出高度（像素）<input
                    v-model.number="w.draft.sceneOutput.height"
                    type="number"
                    min="64"
                    max="2048"
                    required
                /></label>
                <label
                  >导出格式<select v-model="w.draft.sceneOutput.format">
                    <option
                      v-for="format in w.options?.scene?.formats"
                      :key="format"
                    >
                      {{ format }}
                    </option>
                  </select></label
                >
                <label
                  >生成数量<input
                    v-model.number="w.draft.sceneOutput.count"
                    type="number"
                    min="1"
                    :max="w.options?.scene?.max_count"
                    step="1"
                    required
                /></label>
                <small
                  >每张独立生成，全部成功才展示；失败重试会重新生成整批，可能再次产生费用。本地保证输出尺寸与格式，背景等比缩放并居中裁切。拼多多专用规则待核实。</small
                >
              </template>
              <small
                >配置列表最多200项。未配置时保持空白，不假定拼多多尺寸或规则。</small
              >
              <details>
                <summary>位置与尺寸参数</summary>
                <p>当前是提交参数，不是生成预览；默认值仅用于内部开发。</p>
                <BoxFields
                  v-model:box="w.draft.productBox"
                  title="商品"
                /><BoxFields
                  v-if="w.feature === 'GIFT'"
                  v-model:box="w.draft.giftBox"
                  title="赠品（默认右下，可调整）"
                />
              </details>
            </fieldset>
            <button
              v-if="w.assetNext !== null"
              class="text-button"
              type="button"
              :disabled="w.busy || w.uncertain"
              @click="w.moreAssets"
            >
              加载更多素材
            </button>
            <p
              v-if="blocked && !w.uncertain"
              class="blocked"
              id="submit-reason"
            >
              {{ blocked }}
            </p>
            <p v-if="w.uncertain" class="blocked" id="pending-reason">
              上次提交结果不确定。将重发同一份请求，不会采用改动后的输入。
            </p>
            <button
              v-if="w.uncertain"
              type="button"
              :disabled="w.busy"
              @click="w.submit"
            >
              用原请求重发
            </button>
            <button
              v-else
              type="submit"
              :disabled="w.busy || w.loading || !!blocked"
              aria-describedby="submit-reason"
            >
              {{
                w.busy
                  ? '处理中…'
                  : w.realSceneEnabled
                    ? '生成场景图'
                    : '提交开发任务'
              }}
            </button>
          </form>
        </section>

        <section class="preview-column" aria-labelledby="preview-title">
          <div class="panel preview-panel">
            <h2 id="preview-title">素材与产物查看</h2>
            <figure v-if="w.preview">
              <img :src="w.preview" :alt="w.previewTitle" />
              <figcaption>{{ w.previewTitle }}</figcaption>
            </figure>
            <div v-else class="preview-empty">
              <span aria-hidden="true">＋</span>
              <h3>先查看你的原图</h3>
              <p>选择素材后点击“查看原图”。这里不会用模拟图片冒充生成预览。</p>
            </div>
          </div>
          <section class="panel task-panel" aria-labelledby="task-title">
            <div class="section-heading">
              <h2 id="task-title">当前任务</h2>
              <button
                class="text-button"
                :disabled="!w.selected || w.busy"
                @click="w.refreshTask"
              >
                刷新状态
              </button>
            </div>
            <template v-if="w.selected"
              ><strong class="task-status" :data-status="w.selected.status">{{
                w.selectedRealScene && w.selected.status === 'SUCCEEDED'
                  ? w.mockProvider
                    ? '模拟链路完成 · 非真实生成'
                    : '场景合成完成 · 待人工审核'
                  : statusLabels[w.selected.status]
              }}</strong>
              <dl>
                <dt>任务编号</dt>
                <dd>{{ w.selected.id }}</dd>
                <dt>入口 / 尝试</dt>
                <dd>
                  {{
                    features.find((f) => f.id === w.selected?.feature_type)
                      ?.name
                  }}
                  / 第 {{ w.selected.attempt }} 次
                </dd>
              </dl>
              <p v-if="w.selected.status === 'QUEUED'">
                等待 Worker 领取。未启动 Worker 时会保持排队。
              </p>
              <p v-if="w.selected.status === 'RUNNING'">
                Worker 正在处理，页面每 2.5 秒查询一次。
              </p>
              <div v-if="w.selected.error" class="message error">
                <p>{{ w.selected.error.message }}</p>
                <small
                  >{{ w.selected.error.code }} · 关联编号
                  {{ w.selected.error.correlation_id }}</small
                >
              </div>
              <button
                v-if="w.selected.status === 'FAILED'"
                class="secondary"
                :disabled="w.busy"
                @click="w.retry"
              >
                重试任务</button
              ><small v-if="w.selected.status === 'FAILED'"
                >能否重试由服务端当前状态和次数决定。生成能力未接入时，重试仍可能失败。</small
              >
              <div
                v-for="artifact in w.selected.artifacts"
                :key="artifact.id"
                class="artifact"
              >
                <p>
                  {{
                    w.selectedRealScene
                      ? w.sceneLabel
                      : '开发/测试产物 · 非真实商品成品'
                  }}
                  · {{ artifact.width }}×{{ artifact.height }}
                </p>
                <button
                  class="secondary"
                  :disabled="w.busy"
                  @click="w.showImage(artifact.id, true)"
                >
                  {{ w.selectedRealScene ? '查看场景图' : '查看测试产物' }}
                </button>
                <button
                  class="text-button"
                  :disabled="w.busy"
                  @click="w.showImage(artifact.id, true, true)"
                >
                  {{ w.selectedRealScene ? '下载场景图' : '下载测试产物' }}
                </button>
              </div>
            </template>
            <p v-else class="empty">
              还没有选中的任务。提交后可在这里查看状态，也可以从历史中选择。
            </p>
          </section>
        </section>
      </div>

      <section
        v-if="w.project"
        class="history panel"
        aria-labelledby="history-title"
      >
        <div class="section-heading">
          <div>
            <h2 id="history-title">项目任务历史</h2>
            <p>来自 Java 持久化记录，最新任务在前；重新登录后仍可查看。</p>
          </div>
          <button
            class="secondary"
            :disabled="w.busy || w.loading"
            @click="w.refreshHistory()"
          >
            刷新历史
          </button>
        </div>
        <p v-if="!w.history.length" class="empty">
          这个项目还没有任务。请先补齐当前入口的素材与配置。
        </p>
        <ol v-else class="history-list">
          <li v-for="item in w.history" :key="item.task.id">
            <button
              class="history-item"
              :aria-current="
                w.selected?.id === item.task.id ? 'true' : undefined
              "
              :disabled="w.busy"
              @click="w.selectTask(item.task)"
            >
              <span
                ><strong>{{
                  features.find((f) => f.id === item.task.feature_type)?.name
                }}</strong
                ><small>{{ item.task.id }}</small></span
              ><span class="history-state"
                >{{
                  item.real_scene && item.task.status === 'SUCCEEDED'
                    ? w.mockProvider
                      ? '模拟链路完成 · 非真实生成'
                      : '场景合成完成 · 待人工审核'
                    : statusLabels[item.task.status]
                }}<small>{{
                  item.real_scene
                    ? w.sceneLabel
                    : item.test_fixture
                      ? '合成夹具 / 开发测试'
                      : '开发任务 / 真实生成未开放'
                }}</small></span
              ><time :datetime="item.task.created_at">{{
                date(item.task.created_at)
              }}</time>
            </button>
          </li>
        </ol>
        <button
          v-if="w.historyNext !== null"
          class="secondary"
          :disabled="w.busy"
          @click="w.refreshHistory(true)"
        >
          加载更早任务
        </button>
      </section>
    </main>
    <footer>
      原图留存 · 人工审核 · 仅生成、预览与下载范围 · 不自动上架或发布
    </footer>
  </div>
</template>
