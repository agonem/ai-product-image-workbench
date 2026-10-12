<script setup lang="ts">
// A right-click menu (ADR-20261012-Z): opens at the pointer (or under the focused element when
// opened from the keyboard), stays inside the window, and closes on Esc, a press elsewhere,
// scrolling, zooming or resizing. Arrow keys move between items.
import { nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import LineIcon from './LineIcon.vue'

export type MenuItem = {
  label: string
  run: () => unknown
  icon?: string
  hint?: string
  danger?: boolean
  disabled?: boolean
}
const props = defineProps<{
  x: number
  y: number
  items: MenuItem[]
  label: string
}>()
const emit = defineEmits<{ close: [] }>()

const menu = ref<HTMLElement>()
const place = ref({ left: props.x, top: props.y })
let returnTo: HTMLElement | null = null

const buttons = () =>
  [
    ...(menu.value?.querySelectorAll<HTMLButtonElement>('[role="menuitem"]') ??
      []),
  ].filter((button) => !button.disabled)
function close(restore = false) {
  emit('close')
  if (restore) returnTo?.focus()
}
const dismiss = () => close()
function outside(event: PointerEvent) {
  if (!menu.value?.contains(event.target as Node)) close()
}
function key(event: KeyboardEvent) {
  const list = buttons()
  const at = list.indexOf(document.activeElement as HTMLButtonElement)
  if (event.key === 'Escape' || event.key === 'Tab') {
    event.preventDefault()
    close(true)
  } else if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
    event.preventDefault()
    const step = event.key === 'ArrowDown' ? 1 : -1
    list[(at + step + list.length) % list.length]?.focus()
  } else if (event.key === 'Home' || event.key === 'End') {
    event.preventDefault()
    list[event.key === 'Home' ? 0 : list.length - 1]?.focus()
  }
}
function choose(item: MenuItem) {
  close(true)
  void item.run()
}
onMounted(async () => {
  returnTo = document.activeElement as HTMLElement | null
  await nextTick()
  const box = menu.value!.getBoundingClientRect()
  place.value = {
    left: Math.max(8, Math.min(props.x, innerWidth - box.width - 8)),
    top: Math.max(8, Math.min(props.y, innerHeight - box.height - 8)),
  }
  buttons()[0]?.focus()
  addEventListener('pointerdown', outside, true)
  addEventListener('wheel', dismiss, { capture: true, passive: true })
  addEventListener('scroll', dismiss, true)
  addEventListener('resize', dismiss)
  addEventListener('blur', dismiss)
})
onBeforeUnmount(() => {
  removeEventListener('pointerdown', outside, true)
  removeEventListener('wheel', dismiss, { capture: true })
  removeEventListener('scroll', dismiss, true)
  removeEventListener('resize', dismiss)
  removeEventListener('blur', dismiss)
})
</script>

<template>
  <Teleport to="body">
    <div
      ref="menu"
      class="menu context-menu"
      role="menu"
      :aria-label="label"
      :style="{ left: `${place.left}px`, top: `${place.top}px` }"
      @keydown="key"
      @contextmenu.prevent
    >
      <button
        v-for="item in items"
        :key="item.label"
        type="button"
        role="menuitem"
        class="menu-item"
        :class="{ danger: item.danger }"
        :disabled="item.disabled"
        @click="choose(item)"
      >
        <LineIcon v-if="item.icon" :name="item.icon" :size="14" />
        <span class="grow">{{ item.label }}</span>
        <kbd v-if="item.hint">{{ item.hint }}</kbd>
      </button>
    </div>
  </Teleport>
</template>

<style scoped>
.context-menu {
  position: fixed;
  right: auto;
  z-index: 80;
  min-width: 176px;
  max-width: calc(100vw - 16px);
  max-height: none;
}
.menu-item.danger {
  color: var(--danger, #d4380d);
}
.menu-item:disabled {
  color: var(--ink-3);
  cursor: default;
  background: none;
}
.menu-item:focus-visible {
  outline: none;
  background: var(--hover);
}
kbd {
  color: var(--ink-3);
  font: inherit;
  font-size: 12px;
}
</style>
