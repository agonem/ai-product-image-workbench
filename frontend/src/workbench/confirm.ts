import { reactive } from 'vue'

/** One in-page confirmation at a time (replaces the browser's native confirm box). */
export const confirmState = reactive<{
  open: boolean
  title: string
  message: string
  action: string
  resolve: ((ok: boolean) => void) | null
}>({ open: false, title: '', message: '', action: '', resolve: null })

export function confirmAction(
  title: string,
  message: string,
  action = '确定',
): Promise<boolean> {
  confirmState.resolve?.(false)
  return new Promise((resolve) =>
    Object.assign(confirmState, {
      open: true,
      title,
      message,
      action,
      resolve,
    }),
  )
}

export function settleConfirm(ok: boolean) {
  const resolve = confirmState.resolve
  Object.assign(confirmState, { open: false, resolve: null })
  resolve?.(ok)
}
