<script setup lang="ts">
import { onUnmounted } from 'vue'
import { confirmState, settleConfirm } from '../workbench/confirm'
import LineIcon from './LineIcon.vue'
import ModalDialog from './ModalDialog.vue'

// Signing out while a question is open answers it with "no".
onUnmounted(() => settleConfirm(false))
</script>

<template>
  <ModalDialog
    v-if="confirmState.open"
    :title="confirmState.title"
    @close="settleConfirm(false)"
  >
    <p class="confirm-message">
      <LineIcon name="alert" :size="18" />{{ confirmState.message }}
    </p>
    <template #footer>
      <button type="button" class="btn" @click="settleConfirm(false)">
        取消
      </button>
      <button
        type="button"
        class="btn primary danger-fill"
        data-testid="confirm-action"
        @click="settleConfirm(true)"
      >
        {{ confirmState.action }}
      </button>
    </template>
  </ModalDialog>
</template>
