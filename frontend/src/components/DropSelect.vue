<script setup lang="ts" generic="T extends string | number">
import { computed, nextTick, onUnmounted, ref } from 'vue'
import LineIcon from './LineIcon.vue'

// A compact select that can show a second line (e.g. model name + provider).
const props = defineProps<{
  label: string
  options: { value: T; label: string; hint?: string }[]
  disabled?: boolean
  tall?: boolean
  placeholder?: string
  /** "tool": a compact toolbar button with an icon (e.g. canvas zoom). */
  variant?: 'field' | 'tool'
  icon?: string
}>()
const model = defineModel<T>({ required: true })
const open = ref(false),
  up = ref(false)
const root = ref<HTMLElement>(),
  trigger = ref<HTMLButtonElement>(),
  list = ref<HTMLElement>()
const current = computed(() =>
  props.options.find((item) => item.value === model.value),
)

function outside(event: PointerEvent) {
  if (!root.value?.contains(event.target as Node)) close(false)
}
async function show() {
  if (props.disabled || !props.options.length) return
  const rect = trigger.value!.getBoundingClientRect()
  const needed = Math.min(280, props.options.length * 40 + 10)
  up.value = innerHeight - rect.bottom < needed && rect.top > needed
  open.value = true
  document.addEventListener('pointerdown', outside, true)
  await nextTick()
  const items = [...(list.value?.querySelectorAll('button') ?? [])]
  ;(items.find((item) => item.ariaSelected === 'true') ?? items[0])?.focus()
}
function close(focus = true) {
  open.value = false
  document.removeEventListener('pointerdown', outside, true)
  if (focus) trigger.value?.focus()
}
function choose(value: T) {
  model.value = value
  close()
}
function move(event: KeyboardEvent) {
  const items = [...(list.value?.querySelectorAll('button') ?? [])]
  const index = items.indexOf(document.activeElement as HTMLButtonElement)
  if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
    event.preventDefault()
    const step = event.key === 'ArrowDown' ? 1 : -1
    items[(index + step + items.length) % items.length]?.focus()
  } else if (event.key === 'Escape') {
    event.preventDefault()
    close()
  } else if (event.key === 'Tab') close(false)
}
onUnmounted(() => document.removeEventListener('pointerdown', outside, true))
</script>

<template>
  <div ref="root" class="dd">
    <button
      ref="trigger"
      type="button"
      :class="variant === 'tool' ? 'tool' : ['dd-button', { tall }]"
      aria-haspopup="listbox"
      :aria-expanded="open"
      :aria-label="`${label}：${current?.label ?? placeholder ?? '未选择'}`"
      :disabled="disabled"
      @click="open ? close() : show()"
      @keydown.down.prevent="show()"
    >
      <template v-if="variant === 'tool'">
        <LineIcon :name="icon ?? 'zoom'" /><span class="label">{{
          current?.label
        }}</span>
      </template>
      <template v-else>
        <span class="value num"
          >{{ current?.label ?? placeholder ?? '未选择'
          }}<small v-if="current?.hint">{{ current.hint }}</small></span
        >
        <LineIcon name="down" :size="14" />
      </template>
    </button>
    <div
      v-if="open"
      ref="list"
      class="menu"
      :class="{ up }"
      role="listbox"
      :aria-label="label"
      @keydown="move"
    >
      <button
        v-for="item in options"
        :key="item.value"
        type="button"
        role="option"
        class="menu-item"
        :aria-selected="item.value === model"
        @click="choose(item.value)"
      >
        <span class="grow num"
          >{{ item.label }}<small v-if="item.hint">{{ item.hint }}</small></span
        >
        <LineIcon
          v-if="item.value === model"
          class="tick"
          name="check"
          :size="14"
        />
      </button>
    </div>
  </div>
</template>
