<script setup lang="ts">
// Small vector illustrations for empty lists; decorative only.
withDefaults(
  defineProps<{
    art?: 'images' | 'box' | 'clock' | 'model'
    compact?: boolean
  }>(),
  { art: 'images', compact: false },
)
</script>

<template>
  <div class="empty-state" :class="{ compact }">
    <svg viewBox="0 0 96 72" aria-hidden="true">
      <ellipse cx="48" cy="64" rx="34" ry="4" fill="#E9ECF1" />
      <template v-if="art === 'images'">
        <rect
          x="22"
          y="14"
          width="44"
          height="36"
          rx="5"
          fill="#E8F0FF"
          transform="rotate(-8 44 32)"
        />
        <rect
          x="30"
          y="18"
          width="44"
          height="38"
          rx="5"
          fill="#FFFFFF"
          stroke="#C9D6F2"
          stroke-width="1.5"
        />
        <circle cx="42" cy="30" r="4" fill="#BFD2FA" />
        <path
          d="M32 52l12-11 8 7 7-6 13 10"
          fill="none"
          stroke="#8FB0F0"
          stroke-width="2"
          stroke-linejoin="round"
        />
      </template>
      <template v-else-if="art === 'box'">
        <path
          d="M24 26l24-10 24 10-24 10z"
          fill="#E8F0FF"
          stroke="#8FB0F0"
          stroke-width="1.5"
          stroke-linejoin="round"
        />
        <path
          d="M24 26v22l24 10V36z"
          fill="#FFFFFF"
          stroke="#C9D6F2"
          stroke-width="1.5"
          stroke-linejoin="round"
        />
        <path
          d="M72 26v22L48 58V36z"
          fill="#F4F7FD"
          stroke="#C9D6F2"
          stroke-width="1.5"
          stroke-linejoin="round"
        />
        <path
          d="M48 8v6M40 10l2 5M56 10l-2 5"
          stroke="#8FB0F0"
          stroke-width="1.5"
          stroke-linecap="round"
        />
      </template>
      <template v-else-if="art === 'clock'">
        <circle
          cx="48"
          cy="34"
          r="22"
          fill="#FFFFFF"
          stroke="#C9D6F2"
          stroke-width="1.5"
        />
        <circle cx="48" cy="34" r="16" fill="#E8F0FF" />
        <path
          d="M48 24v10l7 5"
          fill="none"
          stroke="#5D8BE6"
          stroke-width="2"
          stroke-linecap="round"
        />
      </template>
      <template v-else>
        <rect
          x="30"
          y="16"
          width="36"
          height="36"
          rx="6"
          fill="#FFFFFF"
          stroke="#C9D6F2"
          stroke-width="1.5"
        />
        <rect
          x="40"
          y="26"
          width="16"
          height="16"
          rx="3"
          fill="#E8F0FF"
          stroke="#8FB0F0"
          stroke-width="1.5"
        />
        <path
          d="M38 10v6M48 10v6M58 10v6M38 52v6M48 52v6M58 52v6M24 26h6M24 42h6M66 26h6M66 42h6"
          stroke="#C9D6F2"
          stroke-width="1.5"
          stroke-linecap="round"
        />
      </template>
    </svg>
    <slot />
  </div>
</template>
