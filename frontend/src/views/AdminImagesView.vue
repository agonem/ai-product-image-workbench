<script setup lang="ts">
import { computed, inject, onMounted, ref } from 'vue'
import EmptyState from '../components/EmptyState.vue'
import ImageViewer from '../components/ImageViewer.vue'
import LineIcon from '../components/LineIcon.vue'
import PrivateImage from '../workbench/PrivateImage.vue'
import { confirmAction } from '../workbench/confirm'
import { featureName } from '../workbench/generation'
import type { Feature } from '../workbench/model'
import { workbenchKey } from '../workbench/useWorkbench'

type Image = {
  id: string
  kind: 'PRODUCT' | 'GIFT' | 'COMPOSITE'
  width: number
  height: number
  owner: string
  owner_id: string
  created_at: string
  feature_type?: Feature
}
type Account = { id: string; username: string }
// Image management for admins (ADR-20260930-F): every account's originals and works.
const w = inject(workbenchKey)!
const admin = computed(() => w.production && w.identity?.role === 'ADMIN')
const category = ref<'ORIGINAL' | 'WORK'>('ORIGINAL')
const owner = ref('')
const accounts = ref<Account[]>([])
const images = ref<Image[]>([]),
  next = ref<number | null>(null)
const busy = ref(false),
  error = ref(''),
  notice = ref('')
const viewing = ref<number | null>(null)
const kindName = (image: Image) =>
  image.kind === 'PRODUCT'
    ? '商品图'
    : image.kind === 'GIFT'
      ? '赠品图'
      : featureName(image.feature_type ?? 'SCENE')
const day = (value: string) =>
  new Date(value).toLocaleString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
const path = (image: Image) => `/admin/images/${image.id}/content`
const viewerItems = computed(() =>
  images.value.map((image) => ({
    path: path(image),
    title: `${image.owner} · ${kindName(image)}`,
    detail: `${image.width} × ${image.height} · ${day(image.created_at)}`,
    download: () => w.downloadFile(path(image), `image-${image.id}`),
  })),
)
async function run(fn: () => Promise<void>) {
  if (busy.value) return
  busy.value = true
  error.value = ''
  try {
    await fn()
  } catch (cause) {
    if (cause instanceof Error && cause.message !== 'STALE')
      error.value = cause.message
  } finally {
    busy.value = false
  }
}
async function load(more = false) {
  await run(async () => {
    const query = new URLSearchParams({ category: category.value })
    if (owner.value) query.set('owner', owner.value)
    if (more && next.value !== null) query.set('offset', String(next.value))
    const page = await w.api<{ items: Image[]; next_offset: number | null }>(
      `/admin/images?${query}`,
    )
    images.value = more ? [...images.value, ...page.items] : page.items
    next.value = page.next_offset
  })
}
async function remove(image: Image) {
  const ok = await confirmAction(
    `删除 ${image.owner} 的${kindName(image)}`,
    image.kind === 'COMPOSITE'
      ? '删除后该账号也无法再查看、下载或免费改字，不可恢复。'
      : '删除后该账号不能再用它生成；用它生成过的作品仍保留，不可恢复。',
    '删除',
  )
  if (!ok) return
  await run(async () => {
    await w.api(`/admin/images/${image.id}`, { method: 'DELETE' })
    images.value = images.value.filter((item) => item.id !== image.id)
    notice.value = '图片已删除。'
  })
}
function choose(value: 'ORIGINAL' | 'WORK') {
  category.value = value
  void load()
}
onMounted(async () => {
  if (!admin.value) return
  void load()
  try {
    accounts.value = (
      await w.api<{ items: Account[] }>('/admin/accounts')
    ).items
  } catch {
    // Without the list the filter only offers "all accounts".
  }
})
</script>

<template>
  <main class="page">
    <div class="page-head">
      <div class="intro">
        <h1>图片管理</h1>
        <p>查看和删除所有账号的原图与作品；删除会记录在操作日志中。</p>
      </div>
      <span class="spacer"></span>
      <div v-if="admin" class="tabs" role="group" aria-label="图片类别">
        <button
          type="button"
          :aria-pressed="category === 'ORIGINAL'"
          @click="choose('ORIGINAL')"
        >
          原图
        </button>
        <button
          type="button"
          :aria-pressed="category === 'WORK'"
          @click="choose('WORK')"
        >
          作品
        </button>
      </div>
    </div>
    <section v-if="!admin" class="card">
      <EmptyState>只有生产环境的管理员可以管理全部图片。</EmptyState>
    </section>
    <template v-else>
      <div class="filter-bar">
        <label class="form-row inline"
          ><span>账号</span
          ><select
            v-model="owner"
            aria-label="账号"
            :disabled="busy"
            @change="load()"
          >
            <option value="">全部账号</option>
            <option v-for="item in accounts" :key="item.id" :value="item.id">
              {{ item.username }}
            </option>
          </select></label
        >
      </div>
      <p v-if="error" class="banner error" role="alert">
        <LineIcon name="alert" :size="14" />{{ error }}
      </p>
      <p v-if="notice" class="banner ok" role="status">
        <LineIcon name="check" :size="14" />{{ notice }}
      </p>
      <section class="card">
        <div class="card-body">
          <div v-if="images.length" class="image-grid">
            <article
              v-for="(image, index) in images"
              :key="image.id"
              class="image-card lift"
              data-testid="admin-image"
            >
              <figure @click="viewing = index">
                <PrivateImage
                  :path="path(image)"
                  :alt="`${image.owner} ${kindName(image)}`"
                  :api="w.api"
                />
              </figure>
              <div class="caption">
                <span class="tag">{{ image.owner }}</span>
                <span>{{ kindName(image) }}</span>
                <span class="spacer"></span>
                <span class="muted num">{{ day(image.created_at) }}</span>
              </div>
              <div class="hover-actions">
                <button
                  type="button"
                  title="放大查看"
                  aria-label="放大查看"
                  @click="viewing = index"
                >
                  <LineIcon name="zoomin" :size="14" />
                </button>
                <button
                  type="button"
                  class="danger"
                  title="删除"
                  aria-label="删除"
                  :disabled="busy"
                  @click="remove(image)"
                >
                  <LineIcon name="del" :size="14" />
                </button>
              </div>
            </article>
          </div>
          <EmptyState v-else-if="!busy" art="box"
            >没有符合条件的图片。</EmptyState
          >
        </div>
        <div v-if="next !== null" class="card-foot">
          <button
            type="button"
            class="btn sm"
            :disabled="busy"
            @click="load(true)"
          >
            加载更多
          </button>
        </div>
      </section>
      <ImageViewer
        v-if="viewing !== null && viewerItems.length"
        :items="viewerItems"
        :start="viewing"
        @close="viewing = null"
      />
    </template>
  </main>
</template>
