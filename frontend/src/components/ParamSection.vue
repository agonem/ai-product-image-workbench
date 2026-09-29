<script setup lang="ts">
import { useId } from 'vue'
import LineIcon from './LineIcon.vue'

// One collapsible parameter group; the summary keeps the choice visible when closed.
defineProps<{ title: string; summary: string; icon: string; open: boolean }>()
const emit = defineEmits<{ toggle: [] }>()
const body = useId()
</script>

<template>
  <section class="acc" :class="{ open }">
    <button
      type="button"
      class="acc-head"
      :aria-expanded="open"
      :aria-controls="body"
      @click="emit('toggle')"
    >
      <span class="badge"><LineIcon :name="icon" :size="14" /></span>
      <span class="title"
        ><b>{{ title }}</b
        ><small>{{ summary }}</small></span
      >
      <LineIcon class="chev" name="down" />
    </button>
    <div
      v-if="open"
      :id="body"
      class="acc-body"
      role="group"
      :aria-label="title"
    >
      <slot />
    </div>
  </section>
</template>
