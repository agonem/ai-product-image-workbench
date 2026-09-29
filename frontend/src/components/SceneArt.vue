<script setup lang="ts">
import { computed } from 'vue'

// Flat vector thumbnails for the scene presets; unknown presets get a neutral room.
const props = defineProps<{ scene: string }>()
const palette: Record<string, [string, string]> = {
  nursery: ['#F6EBDD', '#E7D2B8'],
  wood_table: ['#EEF1F4', '#C9A27C'],
  bathroom: ['#E4F1F6', '#F6FAFC'],
  outdoor: ['#DDEFFC', '#B9DDA1'],
  kitchen: ['#F4F1EC', '#DCD6CC'],
  bedroom: ['#EFE9F6', '#F7F2F8'],
  custom: ['#F2F3F5', '#E5E6EB'],
}
const colors = computed(() => palette[props.scene] ?? ['#EEF0F3', '#DCDFE5'])
</script>

<template>
  <svg viewBox="0 0 800 600" aria-hidden="true">
    <rect width="800" height="600" :fill="colors[0]" />
    <rect y="420" width="800" height="180" :fill="colors[1]" />
    <template v-if="scene === 'nursery'">
      <rect
        x="80"
        y="80"
        width="200"
        height="180"
        rx="10"
        fill="#FFFFFF"
        opacity=".7"
      />
      <path d="M80 170h200M180 80v180" stroke="#E4D3BD" stroke-width="6" />
      <rect
        v-for="i in 7"
        :key="i"
        :x="436 + i * 34"
        y="250"
        width="10"
        height="170"
        rx="5"
        fill="#EAD9C4"
      />
      <rect x="455" y="240" width="260" height="14" rx="7" fill="#DFC9AE" />
    </template>
    <path
      v-else-if="scene === 'wood_table'"
      d="M0 420h800M0 480h800M0 540h800"
      stroke="#B48A63"
      stroke-width="5"
    />
    <g
      v-else-if="scene === 'bathroom'"
      stroke="#CFE3EC"
      stroke-width="4"
      opacity=".8"
    >
      <path v-for="i in 4" :key="`v${i}`" :d="`M${i * 180} 0v420`" />
      <path v-for="i in 2" :key="`h${i}`" :d="`M0 ${i * 140}h800`" />
    </g>
    <template v-else-if="scene === 'outdoor'">
      <circle cx="650" cy="110" r="50" fill="#FFE39A" />
      <path
        d="M0 420c160-50 300-50 420-16s260 16 380-16v32H0z"
        fill="#A5D38B"
      />
    </template>
    <template v-else-if="scene === 'kitchen'">
      <rect
        x="60"
        y="70"
        width="300"
        height="150"
        rx="12"
        fill="#FFFFFF"
        opacity=".6"
      />
      <rect x="0" y="410" width="800" height="16" fill="#C9C1B4" />
    </template>
    <path
      v-else-if="scene === 'bedroom'"
      d="M0 450c200-40 600-40 800 0v150H0z"
      fill="#FFFFFF"
    />
    <path
      v-else-if="scene === 'custom'"
      d="M340 330l150-150 50 50-150 150h-50zM470 200l50 50"
      fill="none"
      stroke="#86909C"
      stroke-width="18"
      stroke-linejoin="round"
    />
  </svg>
</template>
