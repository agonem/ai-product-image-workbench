<script setup lang="ts">
import { computed, inject } from 'vue'
import PrivateImage from '../workbench/PrivateImage.vue'
import { workbenchKey } from '../workbench/useWorkbench'

const props = defineProps<{ label: string; kind: 'PRODUCT' | 'GIFT' }>()
const model = defineModel<string>({ required: true })
const w = inject(workbenchKey)!
const choices = computed(() =>
  props.kind === 'PRODUCT' ? w.products : w.gifts,
)
async function pick(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (!file) return
  const created = await w.upload(file, props.kind)
  if (created) model.value = created.id
}
</script>

<template>
  <section class="fields" :aria-label="label">
    <h3>{{ label }}</h3>
    <div class="asset-slot">
      <figure>
        <PrivateImage
          v-if="model"
          :key="model"
          :path="`/assets/${model}/content`"
          :alt="label"
          :api="w.api"
        />
        <span v-else>尚未选择</span>
      </figure>
      <label class="upload-tile"
        ><span aria-hidden="true">＋</span>{{ model ? '重新上传' : '上传图片'
        }}<input
          type="file"
          accept="image/png,image/jpeg"
          :aria-label="`上传${label}`"
          :disabled="w.busy || w.uncertain"
          @change="pick"
      /></label>
    </div>
    <label v-if="choices.length"
      >从素材库选择<select v-model="model" :disabled="w.busy || w.uncertain">
        <option value="">请选择</option>
        <option v-for="asset in choices" :key="asset.id" :value="asset.id">
          {{ asset.width }}×{{ asset.height }} · {{ asset.id.slice(0, 8) }}
        </option>
      </select></label
    >
  </section>
</template>
