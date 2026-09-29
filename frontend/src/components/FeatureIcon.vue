<script setup lang="ts">
defineProps<{ tone: 'gift' | 'scene' | 'selling' }>()
</script>

<template>
  <svg width="96" height="96" viewBox="0 0 96 96" aria-hidden="true">
    <template v-if="tone === 'gift'">
      <rect x="18" y="40" width="60" height="42" rx="6" fill="#ffd1bd" />
      <rect x="12" y="30" width="72" height="16" rx="5" fill="#ff9e7a" />
      <rect x="44" y="30" width="8" height="52" fill="#ff7a45" />
      <path
        d="M48 30c-8-14-22-10-18-2 3 5 18 2 18 2zm0 0c8-14 22-10 18-2-3 5-18 2-18 2z"
        fill="#ff7a45"
      />
    </template>
    <template v-else-if="tone === 'scene'">
      <rect x="10" y="18" width="76" height="60" rx="8" fill="#cfe0ff" />
      <circle cx="30" cy="36" r="8" fill="#ffffff" />
      <path d="M10 70l24-22 16 14 12-10 24 18v8H10z" fill="#7fa6ff" />
    </template>
    <template v-else>
      <rect x="14" y="16" width="68" height="64" rx="8" fill="#e4dbff" />
      <rect x="24" y="28" width="40" height="7" rx="3.5" fill="#7c5cff" />
      <circle cx="28" cy="48" r="5" fill="#7c5cff" />
      <rect x="38" y="45" width="30" height="6" rx="3" fill="#b8a6ff" />
      <circle cx="28" cy="63" r="5" fill="#7c5cff" />
      <rect x="38" y="60" width="24" height="6" rx="3" fill="#b8a6ff" />
    </template>
  </svg>
</template>
