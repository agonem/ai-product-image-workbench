import { ref } from 'vue'

/** Handle local file drops only; text/URL drops keep their native behavior. */
export function useFileDrop(
  disabled: () => boolean,
  receive: (files: File[]) => Promise<void>,
) {
  const dragging = ref(false)
  let depth = 0
  const isFile = (event: DragEvent) =>
    event.dataTransfer?.types.includes('Files') ?? false
  function accept(event: DragEvent) {
    if (!isFile(event)) return false
    event.preventDefault()
    // A drop over an image slot must never also upload through its parent composer.
    event.stopPropagation()
    if (event.dataTransfer)
      event.dataTransfer.dropEffect = disabled() ? 'none' : 'copy'
    return true
  }
  return {
    dragging,
    handlers: {
      dragenter(event: DragEvent) {
        if (!accept(event)) return
        depth++
        dragging.value = !disabled()
      },
      dragover(event: DragEvent) {
        if (accept(event)) dragging.value = !disabled()
      },
      dragleave(event: DragEvent) {
        if (!accept(event)) return
        depth = Math.max(0, depth - 1)
        if (!depth) dragging.value = false
      },
      async drop(event: DragEvent) {
        if (!accept(event)) return
        depth = 0
        dragging.value = false
        if (disabled()) return
        const files = Array.from(event.dataTransfer?.files ?? [])
        if (files.length) await receive(files)
      },
    },
  }
}
