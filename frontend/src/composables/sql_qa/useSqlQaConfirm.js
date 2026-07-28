import { ref } from 'vue'

// 模块级状态
const showConfirm = ref(false)
const confirmOptions = ref({ title: '', message: '', danger: false })
let resolvePromise = null

export function useSqlQaConfirm() {
  function confirm(options = {}) {
    confirmOptions.value = {
      title: options.title || '确认',
      message: options.message || '确定要执行此操作吗？',
      danger: options.danger || false,
    }
    showConfirm.value = true
    return new Promise((resolve) => {
      resolvePromise = resolve
    })
  }

  function onConfirm() {
    showConfirm.value = false
    if (resolvePromise) {
      resolvePromise(true)
      resolvePromise = null
    }
  }

  function onCancel() {
    showConfirm.value = false
    if (resolvePromise) {
      resolvePromise(false)
      resolvePromise = null
    }
  }

  return {
    showConfirm,
    confirmOptions,
    confirm,
    onConfirm,
    onCancel,
  }
}
