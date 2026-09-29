<script setup lang="ts">
import { onMounted, ref, useId } from 'vue'
import LineIcon from './LineIcon.vue'

// Native modal dialog: focus stays inside, Esc and the close button both emit close.
defineProps<{ title: string; wide?: boolean }>()
const emit = defineEmits<{ close: [] }>()
const dialog = ref<HTMLDialogElement>()
const heading = useId()
onMounted(() => dialog.value?.showModal())
</script>

<template>
  <dialog
    ref="dialog"
    class="modal"
    :class="{ wide }"
    :aria-labelledby="heading"
    @cancel.prevent="emit('close')"
  >
    <div class="modal-head">
      <h2 :id="heading">{{ title }}</h2>
      <button
        type="button"
        class="icon-btn"
        aria-label="关闭"
        @click="emit('close')"
      >
        <LineIcon name="close" />
      </button>
    </div>
    <div class="modal-body"><slot /></div>
    <div v-if="$slots.footer" class="modal-foot"><slot name="footer" /></div>
  </dialog>
</template>
