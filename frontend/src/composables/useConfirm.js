import { ref } from 'vue'
import ConfirmModal from '@/components/ui/ConfirmModal.vue'

const _state = ref({ show: false })

export function useConfirm() {
  return {
    show(options) {
      return new Promise((resolve) => {
        _state.value.show = false
        setTimeout(() => {
          _state.value = { ..._state.value, show: true, ...options, _resolve: resolve }
        }, 0)
      })
    },
  }
}

// 简易全局调用
let _modalInstance = null
export function setConfirmModalInstance(instance) {
  _modalInstance = instance
}

export async function showConfirm(message, title = '请确认', options = {}) {
  if (!_modalInstance) {
    return window.confirm(message)
  }
  return _modalInstance.show({
    title,
    message,
    type: options.type || 'primary',
    confirmText: options.confirmText || '确定',
    cancelText: options.cancelText || '取消',
    requireInput: options.requireInput || false,
    inputPlaceholder: options.inputPlaceholder || '',
    defaultValue: options.defaultValue || '',
  })
}
