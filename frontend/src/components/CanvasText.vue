<script setup lang="ts">
import { nextTick, onMounted, ref, watch } from 'vue'
import type { TextSpec } from '../workbench/chatCanvas'

// A text box on the conversation canvas (ADR-20261010-W). The browser's own font stands in for
// the deployment font, with the export's rules: lines break only where the user broke them, and
// the whole block shrinks until it fits its box. `fit` (1 = the chosen size) goes back to the
// page so it can warn before an export that would end below the readable minimum.
const props = defineProps<{ text: TextSpec; width: number; height: number }>()
const emit = defineEmits<{ fit: [value: number] }>()
const block = ref<HTMLElement>()
const fit = ref(1)
function measure() {
  const element = block.value
  if (!element) return
  // Transforms do not change the measured size: this is the block at its full size.
  const naturalWidth = element.offsetWidth,
    naturalHeight = element.offsetHeight
  if (!naturalWidth || !naturalHeight) return
  const next = Math.min(
    1,
    props.width / naturalWidth,
    props.height / naturalHeight,
  )
  if (Math.abs(next - fit.value) > 0.002) fit.value = next
  emit('fit', fit.value)
}
const remeasure = () => void nextTick(measure)
watch(() => [props.text, props.width, props.height], remeasure, { deep: true })
onMounted(() => {
  remeasure()
  void document.fonts?.ready.then(remeasure)
})
const origin = { left: 'top left', center: 'top center', right: 'top right' }
</script>

<template>
  <div
    class="canvas-text"
    :style="{
      justifyItems:
        text.align === 'center'
          ? 'center'
          : text.align === 'right'
            ? 'end'
            : 'start',
    }"
  >
    <div
      ref="block"
      class="canvas-text-block"
      :style="{
        fontSize: `${text.size}px`,
        color: text.color,
        textAlign: text.align,
        transform: `scale(${fit})`,
        transformOrigin: origin[text.align],
      }"
      v-text="text.content"
    ></div>
  </div>
</template>
