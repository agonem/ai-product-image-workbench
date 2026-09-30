<script setup lang="ts">
import { computed } from 'vue'

// Tasks per day as bars (failed share darker at the base), drawn to one scale.
const props = defineProps<{
  days: { day: string; tasks: number; failed: number; images: number }[]
}>()
const width = 720,
  height = 220,
  left = 36,
  right = 8,
  top = 12,
  bottom = 28
const ceiling = computed(() => {
  const max = Math.max(1, ...props.days.map((d) => d.tasks))
  const step = max <= 5 ? 1 : max <= 10 ? 2 : Math.ceil(max / 5 / 5) * 5
  return Math.ceil(max / step) * step
})
const ticks = computed(() => {
  const count = Math.min(5, ceiling.value)
  return Array.from(
    { length: count + 1 },
    (_, i) => (ceiling.value / count) * i,
  )
})
const band = computed(
  () => (width - left - right) / Math.max(1, props.days.length),
)
const y = (value: number) =>
  top + (height - top - bottom) * (1 - value / ceiling.value)
const label = (day: string) => day.slice(5).replace('-', '/')
</script>

<template>
  <svg
    class="daily-chart"
    :viewBox="`0 0 ${width} ${height}`"
    role="img"
    :aria-label="`每日任务数，共 ${days.length} 天`"
  >
    <g class="grid">
      <line
        v-for="tick in ticks"
        :key="tick"
        :x1="left"
        :x2="width - right"
        :y1="y(tick)"
        :y2="y(tick)"
      />
      <text
        v-for="tick in ticks"
        :key="`t${tick}`"
        :x="left - 6"
        :y="y(tick) + 4"
        text-anchor="end"
      >
        {{ Math.round(tick) }}
      </text>
    </g>
    <g v-for="(day, index) in days" :key="day.day">
      <rect
        class="bar"
        :x="left + index * band + band * 0.18"
        :width="band * 0.64"
        :y="y(day.tasks)"
        :height="y(0) - y(day.tasks)"
        rx="3"
      >
        <title>
          {{ day.day }}：任务 {{ day.tasks }}，失败 {{ day.failed }}，图片
          {{ day.images }}
        </title>
      </rect>
      <rect
        v-if="day.failed"
        class="bar failed"
        :x="left + index * band + band * 0.18"
        :width="band * 0.64"
        :y="y(day.failed)"
        :height="y(0) - y(day.failed)"
        rx="3"
      />
      <text
        v-if="days.length <= 14 || index % Math.ceil(days.length / 14) === 0"
        class="axis"
        :x="left + index * band + band / 2"
        :y="height - 8"
        text-anchor="middle"
      >
        {{ label(day.day) }}
      </text>
    </g>
  </svg>
</template>
