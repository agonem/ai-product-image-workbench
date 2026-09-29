<script setup lang="ts">
// Decorative corner art for the home cards, in the accent palette.
defineProps<{ tone: 'gift' | 'scene' | 'selling' }>()
</script>

<template>
  <svg class="art" viewBox="0 0 112 84" aria-hidden="true">
    <template v-if="tone === 'gift'">
      <rect x="40" y="30" width="56" height="44" rx="6" fill="#E8F0FF" />
      <rect x="34" y="22" width="68" height="14" rx="4" fill="#D3E1FC" />
      <rect x="64" y="22" width="8" height="52" fill="#9DBAF3" />
      <path
        d="M68 22c-7-12-20-9-16-2 3 4 16 2 16 2zm0 0c7-12 20-9 16-2-3 4-16 2-16 2z"
        fill="#9DBAF3"
      />
    </template>
    <template v-else-if="tone === 'scene'">
      <rect x="28" y="14" width="76" height="60" rx="7" fill="#E8F0FF" />
      <circle cx="48" cy="32" r="7" fill="#FFFFFF" />
      <path d="M28 66l22-20 14 12 12-10 28 20v6H28z" fill="#B7CDF7" />
    </template>
    <template v-else>
      <rect x="30" y="12" width="70" height="64" rx="7" fill="#E8F0FF" />
      <rect x="40" y="24" width="36" height="6" rx="3" fill="#9DBAF3" />
      <circle cx="44" cy="44" r="4.5" fill="#9DBAF3" />
      <rect x="53" y="41" width="30" height="6" rx="3" fill="#D3E1FC" />
      <circle cx="44" cy="59" r="4.5" fill="#9DBAF3" />
      <rect x="53" y="56" width="24" height="6" rx="3" fill="#D3E1FC" />
    </template>
  </svg>
</template>
