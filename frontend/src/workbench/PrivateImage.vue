<script setup lang="ts">
import { onUnmounted, ref, watch } from 'vue'
const props = defineProps<{
  path: string
  alt: string
  api: <T>(path: string, init?: RequestInit) => Promise<T>
}>()
const src = ref(''),
  error = ref('')
let sequence = 0
function clear() {
  if (src.value) URL.revokeObjectURL(src.value)
  src.value = ''
}
watch(
  () => props.path,
  async (path) => {
    const current = ++sequence
    clear()
    error.value = ''
    if (!path) return
    try {
      const blob = await props.api<Blob>(path)
      if (current === sequence) src.value = URL.createObjectURL(blob)
    } catch {
      if (current === sequence) error.value = '图片读取失败，请刷新任务。'
    }
  },
  { immediate: true },
)
onUnmounted(() => {
  sequence++
  clear()
})
</script>
<template>
  <img v-if="src" :src="src" :alt="alt" /><span v-else role="status">{{
    error || '读取图片…'
  }}</span>
</template>
