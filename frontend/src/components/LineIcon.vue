<script setup lang="ts">
// Monochrome line icons (24 × 24, stroke = currentColor); decorative unless labelled nearby.
const paths: Record<string, string> = {
  home: 'M4 11l8-7 8 7v8a1 1 0 0 1-1 1h-4v-6H9v6H5a1 1 0 0 1-1-1z',
  gift: 'M4 11h16v9H4zM3 7h18v4H3zM12 7v13M12 7c-1.5-3-5-3.5-5-1.2C7 7 10 7 12 7zm0 0c1.5-3 5-3.5 5-1.2C17 7 14 7 12 7z',
  scene: 'M3 5h18v14H3zM3 16l5-5 4 4 3-3 6 6M15.5 9.5a1.5 1.5 0 1 0 0-.01',
  selling:
    'M4 5h16M4 5v14h16V5M7.5 9.5l1.5 1.5 3-3M14 10h3M7.5 14.5l1.5 1.5 3-3M14 15h3',
  box: 'M3 8l9-4 9 4-9 4-9-4zM3 8v8l9 4 9-4V8M12 12v8',
  grid: 'M4 4h7v7H4zM13 4h7v7h-7zM4 13h7v7H4zM13 13h7v7h-7z',
  clock: 'M12 3.5a8.5 8.5 0 1 0 0 17 8.5 8.5 0 0 0 0-17zM12 7.5V12l3 2',
  user: 'M12 5a3.5 3.5 0 1 0 0 7 3.5 3.5 0 0 0 0-7zM5 20c1.2-3.6 4-5 7-5s5.8 1.4 7 5',
  cpu: 'M7 7h10v10H7zM10 10h4v4h-4zM9 3v4M15 3v4M9 17v4M15 17v4M3 9h4M3 15h4M17 9h4M17 15h4',
  out: 'M10 4H6a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h4M15 16l4-4-4-4M19 12H9',
  down: 'M6 9l6 6 6-6',
  up: 'M12 16V5M7.5 9.5L12 5l4.5 4.5M5 19h14',
  lib: 'M3.5 5h17v14h-17zM3.5 9h17M8 5v4',
  check: 'M5 12.5l4.2 4L19 7',
  text: 'M5 6V4h14v2M12 4v16M9 20h6',
  cmp: 'M3 5h18v14H3zM12 3v18',
  zoom: 'M11 5a6 6 0 1 0 0 12 6 6 0 0 0 0-12zM20 20l-4.5-4.5',
  dl: 'M12 4v11M7.5 10.5L12 15l4.5-4.5M5 20h14',
  del: 'M5 7h14M10 7V5h4v2M7 7l1 12h8l1-12',
  redo: 'M20 12a8 8 0 1 1-2.3-5.7M20 4v5h-5',
  plus: 'M12 5v14M5 12h14',
  close: 'M6 6l12 12M18 6L6 18',
  key: 'M8 11a4 4 0 1 0 0 .01zM11.5 12.5L20 4M16 8l2.5 2.5M18 6l2 2',
  globe:
    'M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18zM3 12h18M12 3c2.6 2.6 3.8 5.6 3.8 9s-1.2 6.4-3.8 9c-2.6-2.6-3.8-5.6-3.8-9S9.4 5.6 12 3z',
  shield: 'M12 3l7 3v6c0 4.4-3 7.6-7 9-4-1.4-7-4.6-7-9V6z',
  edit: 'M4 20h4L19 9l-4-4L4 16zM13.5 6.5l4 4',
  star: 'M12 4l2.4 4.9 5.4.8-3.9 3.8.9 5.4L12 16.4l-4.8 2.5.9-5.4-3.9-3.8 5.4-.8z',
  spark:
    'M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8zM19 16l.8 2.2L22 19l-2.2.8L19 22l-.8-2.2L16 19l2.2-.8z',
  alert: 'M12 4l9 16H3zM12 10v4M12 17v.01',
  info: 'M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18zM12 11v5M12 8v.01',
  search: 'M11 5a6 6 0 1 0 0 12 6 6 0 0 0 0-12zM20 20l-4.5-4.5',
  refresh:
    'M20 11a8 8 0 0 0-14.3-4.9M4 5v4h4M4 13a8 8 0 0 0 14.3 4.9M20 19v-4h-4',
  arrow: 'M5 12h14M13 6l6 6-6 6',
  panel: 'M4 5h16v14H4zM9 5v14',
  users:
    'M9 5.8a3.2 3.2 0 1 0 0 6.4 3.2 3.2 0 0 0 0-6.4zM3 19c1-3.2 3.4-4.5 6-4.5s5 1.3 6 4.5M16 6.5a3 3 0 0 1 0 5.8M18 14.8c1.6.6 2.6 1.9 3 4.2',
  prev: 'M15 6l-6 6 6 6',
  next: 'M9 6l6 6-6 6',
  minus: 'M11 5a6 6 0 1 0 0 12 6 6 0 0 0 0-12zM20 20l-4.5-4.5M8.5 11h5',
  zoomin:
    'M11 5a6 6 0 1 0 0 12 6 6 0 0 0 0-12zM20 20l-4.5-4.5M11 8.5v5M8.5 11h5',
  copy: 'M8 8h11v11H8zM5 16V5h11',
}
withDefaults(defineProps<{ name: string; size?: number }>(), { size: 16 })
</script>

<template>
  <svg
    class="icon"
    :width="size"
    :height="size"
    viewBox="0 0 24 24"
    aria-hidden="true"
    focusable="false"
  >
    <path :d="paths[name] ?? ''" />
  </svg>
</template>
