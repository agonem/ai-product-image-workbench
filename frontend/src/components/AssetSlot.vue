<script setup lang="ts">
import { computed, inject, onUnmounted, ref } from 'vue'
import PrivateImage from '../workbench/PrivateImage.vue'
import { workbenchKey } from '../workbench/useWorkbench'
import LineIcon from './LineIcon.vue'
import ModalDialog from './ModalDialog.vue'
import EmptyState from './EmptyState.vue'

// A material slot: click to pick from the library or upload a new original.
const props = defineProps<{ label: string; kind: 'PRODUCT' | 'GIFT' }>()
const model = defineModel<string>({ required: true })
const w = inject(workbenchKey)!
const choices = computed(() =>
  props.kind === 'PRODUCT' ? w.products : w.gifts,
)
// Finished results can be reused as material too (ADR-20260930-E); picking one copies it.
const works = computed(() =>
  w.history
    .filter((item) => item.generation_v4 && item.task.status === 'SUCCEEDED')
    .flatMap((item) =>
      item.task.artifacts.map((artifact) => ({ task: item.task, artifact })),
    ),
)
const menu = ref(false),
  picking = ref(false),
  source = ref<'library' | 'works'>('library')
const root = ref<HTMLElement>(),
  file = ref<HTMLInputElement>()
const locked = computed(() => w.busy || w.uncertain)

function outside(event: PointerEvent) {
  if (!root.value?.contains(event.target as Node)) hide()
}
function toggle() {
  if (menu.value) return hide()
  menu.value = true
  document.addEventListener('pointerdown', outside, true)
}
function hide() {
  menu.value = false
  document.removeEventListener('pointerdown', outside, true)
}
function library() {
  hide()
  picking.value = true
}
function upload() {
  hide()
  file.value?.click()
}
async function pick(event: Event) {
  const input = event.target as HTMLInputElement
  const chosen = input.files?.[0]
  input.value = ''
  if (!chosen) return
  const created = await w.upload(chosen, props.kind)
  if (created) {
    model.value = created.id
    picking.value = false
  }
}
function select(id: string) {
  model.value = id
  picking.value = false
}
async function reuse(artifact: string) {
  const copied = await w.reuseWork(artifact, props.kind)
  if (copied) select(copied.id)
}
onUnmounted(() => document.removeEventListener('pointerdown', outside, true))
</script>

<template>
  <div ref="root" class="slot" @keydown.esc="hide">
    <button
      type="button"
      class="slot-button"
      :class="{ filled: !!model }"
      aria-haspopup="menu"
      :aria-expanded="menu"
      :aria-label="model ? `${label}（已选择，点击更换）` : label"
      :disabled="locked"
      @click="toggle"
    >
      <template v-if="model">
        <PrivateImage
          :key="model"
          :path="`/assets/${model}/content`"
          :alt="label"
          :api="w.api"
          missing="原图已删除"
        />
        <span class="slot-label">{{ label }}</span>
      </template>
      <template v-else>
        <LineIcon name="up" />
        <span>{{ label }}</span>
      </template>
    </button>
    <div v-if="menu" class="menu" role="menu" :aria-label="label">
      <button type="button" role="menuitem" class="menu-item" @click="library">
        <LineIcon name="lib" :size="15" />从素材库选择
      </button>
      <button type="button" role="menuitem" class="menu-item" @click="upload">
        <LineIcon name="up" :size="15" />上传图片
      </button>
    </div>
    <input
      ref="file"
      class="sr-only"
      type="file"
      accept="image/*"
      tabindex="-1"
      :aria-label="`上传${label}`"
      :disabled="locked"
      @change="pick"
    />
    <ModalDialog
      v-if="picking"
      :title="`选择${label}`"
      wide
      @close="picking = false"
    >
      <div class="tabs" role="group" aria-label="图片来源">
        <button
          type="button"
          :aria-pressed="source === 'library'"
          @click="source = 'library'"
        >
          素材库
        </button>
        <button
          type="button"
          :aria-pressed="source === 'works'"
          @click="source = 'works'"
        >
          我的作品
        </button>
      </div>
      <template v-if="source === 'works'">
        <div v-if="works.length" class="library-grid">
          <button
            v-for="work in works"
            :key="work.artifact.id"
            type="button"
            :aria-label="`使用作品 ${work.artifact.width}×${work.artifact.height}`"
            :disabled="locked"
            @click="reuse(work.artifact.id)"
          >
            <figure>
              <PrivateImage
                :path="`/artifacts/${work.artifact.id}/content`"
                :alt="`作品 ${work.artifact.width}×${work.artifact.height}`"
                :api="w.api"
              />
            </figure>
            <small class="num"
              >{{ work.artifact.width }} × {{ work.artifact.height }}</small
            >
          </button>
        </div>
        <EmptyState v-else>还没有已完成的作品</EmptyState>
        <p class="hint">
          选择作品会复制一份作为新的{{ label }}，原作品不受影响。
        </p>
      </template>
      <div v-else-if="choices.length" class="library-grid">
        <button
          v-for="asset in choices"
          :key="asset.id"
          type="button"
          :aria-pressed="asset.id === model"
          :aria-label="`选择${label} ${asset.width}×${asset.height}`"
          @click="select(asset.id)"
        >
          <figure>
            <PrivateImage
              :path="`/assets/${asset.id}/content`"
              :alt="`${label} ${asset.width}×${asset.height}`"
              :api="w.api"
            />
          </figure>
          <small class="num">{{ asset.width }} × {{ asset.height }}</small>
        </button>
      </div>
      <EmptyState v-else art="box">素材库里还没有{{ label }}</EmptyState>
      <button
        v-if="source === 'library' && w.assetNext !== null"
        type="button"
        class="btn sm"
        :disabled="w.busy"
        @click="w.moreAssets"
      >
        加载更多
      </button>
      <template #footer>
        <!-- The page behind a modal is inert, so the dialog has its own file input. -->
        <label class="btn" :aria-disabled="locked"
          ><LineIcon name="up" :size="14" />上传新图片<input
            class="sr-only"
            type="file"
            accept="image/*"
            :disabled="locked"
            @change="pick"
        /></label>
      </template>
    </ModalDialog>
  </div>
</template>
