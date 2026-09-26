<script setup lang="ts">
import type { Box } from './model'
defineProps<{ title: string }>()
const box = defineModel<Box>('box', { required: true })
</script>
<template>
  <fieldset class="box-fields">
    <legend>{{ title }}（相对画布，0–1）</legend>
    <label
      v-for="(label, key) in {
        x: '横向位置',
        y: '纵向位置',
        width: '宽度',
        height: '高度',
      }"
      :key="key"
    >
      {{ label
      }}<input
        v-model.number="box[key]"
        type="number"
        :min="key === 'x' || key === 'y' ? 0 : 0.01"
        max="1"
        step="0.01"
        required
      />
    </label>
  </fieldset>
</template>
