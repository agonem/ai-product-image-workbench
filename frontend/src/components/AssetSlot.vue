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
const menu = ref(false),
  picking = ref(false)
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
      :title="`从素材库选择${label}`"
      wide
      @close="picking = false"
    >
      <div v-if="choices.length" class="library-grid">
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
        v-if="w.assetNext !== null"
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
