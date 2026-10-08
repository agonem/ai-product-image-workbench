<script setup lang="ts">
import { computed, inject } from 'vue'
import PrivateImage from '../workbench/PrivateImage.vue'
import { workbenchKey } from '../workbench/useWorkbench'

// An agent's picture, or the first character of its name on a colour taken from its id.
const props = withDefaults(
  defineProps<{
    agent: { id?: string; name?: string; avatar?: boolean } | null
    size?: number
    version?: string
  }>(),
  { size: 32, version: '' },
)
const w = inject(workbenchKey)!
const tones = ['#E8823A', '#3E9B5F', '#1683D8', '#B55FC5', '#D6466F', '#3AA6A0']
const tone = computed(() => {
  const id = props.agent?.id ?? ''
  let sum = 0
  for (const char of id) sum = (sum * 31 + char.charCodeAt(0)) % 9973
  return tones[sum % tones.length]
})
const initial = computed(() => [...(props.agent?.name ?? '?')][0] ?? '?')
</script>

<template>
  <span
    class="agent-avatar"
    :style="{
      width: `${size}px`,
      height: `${size}px`,
      fontSize: `${Math.round(size * 0.45)}px`,
      background: agent?.avatar ? '#fff' : tone,
    }"
    aria-hidden="true"
  >
    <PrivateImage
      v-if="agent?.avatar && agent.id"
      :key="`${agent.id}-${version}`"
      :path="`/agents/${agent.id}/avatar`"
      alt=""
      :api="w.api"
    />
    <template v-else-if="agent">{{ initial }}</template>
    <svg v-else viewBox="0 0 24 24" width="60%" height="60%">
      <path
        d="M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8zm-7 8a7 7 0 0 1 14 0"
        fill="none"
        stroke="currentColor"
        stroke-width="1.8"
        stroke-linecap="round"
      />
    </svg>
  </span>
</template>
