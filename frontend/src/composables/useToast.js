import { ref } from 'vue'

const toasts = ref([])
let _id = 0

function show(type, message, title = '', duration = 3000) {
  const id = ++_id
  toasts.value.push({ id, type, message, title })
  if (duration > 0) {
    setTimeout(() => remove(id), duration)
  }
  return id
}

function remove(id) {
  const idx = toasts.value.findIndex(t => t.id === id)
  if (idx >= 0) toasts.value.splice(idx, 1)
}

function iconFor(type) {
  return { success: '✓', info: 'ℹ', warn: '⚠', error: '✕' }[type] || 'ℹ'
}

export function useToast() {
  return {
    toasts,
    show,
    remove,
    success: (msg, title) => show('success', msg, title),
    info: (msg, title) => show('info', msg, title),
    warn: (msg, title) => show('warn', msg, title, 4000),
    error: (msg, title) => show('error', msg, title, 4000),
    iconFor,
  }
}
