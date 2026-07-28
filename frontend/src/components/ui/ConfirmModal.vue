<template>
  <Teleport to="body">
    <div v-if="state.show" class="confirm-overlay" @click.self="cancel">
      <div class="confirm-box">
        <button class="confirm-close" @click="cancel">×</button>
        <div class="confirm-icon" :class="`confirm-icon-${state.type}`">
          {{ state.type === 'danger' ? '⚠' : 'ℹ' }}
        </div>
        <h3 class="confirm-title">{{ state.title || '请确认' }}</h3>
        <p class="confirm-message">{{ state.message }}</p>
        <div v-if="state.requireInput" class="confirm-input-wrap">
          <input v-model="inputValue" class="confirm-input" :placeholder="state.inputPlaceholder" @keyup.enter="confirm" />
        </div>
        <div class="confirm-actions">
          <button class="confirm-btn confirm-btn-cancel" @click="cancel">{{ state.cancelText || '取消' }}</button>
          <button class="confirm-btn" :class="`confirm-btn-${state.type}`" @click="confirm">
            {{ state.confirmText || '确定' }}
          </button>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<script setup>
import { reactive, ref } from 'vue'

const state = reactive({ show: false, type: 'primary', title: '', message: '', requireInput: false, inputValue: '' })
let resolver = null
const inputValue = ref('')

function show(options) {
  return new Promise((resolve) => {
    state.show = true
    state.type = options.type || 'primary'
    state.title = options.title || '请确认'
    state.message = options.message || ''
    state.confirmText = options.confirmText || '确定'
    state.cancelText = options.cancelText || '取消'
    state.requireInput = options.requireInput || false
    state.inputPlaceholder = options.inputPlaceholder || ''
    inputValue.value = options.defaultValue || ''
    resolver = resolve
  })
}

function confirm() {
  if (state.requireInput && !inputValue.value.trim()) {
    return
  }
  state.show = false
  const v = state.requireInput ? inputValue.value : true
  if (resolver) { resolver(v); resolver = null }
}

function cancel() {
  state.show = false
  if (resolver) { resolver(false); resolver = null }
}

defineExpose({ show })
</script>

<style scoped>
.confirm-overlay {
  position: fixed;
  inset: 0;
  z-index: 9998;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(15, 23, 42, 0.5);
  backdrop-filter: blur(4px);
}
.confirm-box {
  position: relative;
  background: #fff;
  border-radius: 16px;
  padding: 32px 28px 24px;
  width: 420px;
  max-width: 92vw;
  box-shadow: 0 20px 60px rgba(0, 0, 0, 0.2);
  text-align: center;
  animation: confirmIn 0.2s ease;
}
@keyframes confirmIn {
  from { opacity: 0; transform: scale(0.95); }
  to { opacity: 1; transform: scale(1); }
}
.confirm-close {
  position: absolute;
  top: 12px;
  right: 12px;
  width: 28px;
  height: 28px;
  border-radius: 6px;
  border: none;
  background: transparent;
  color: #94a3b8;
  font-size: 20px;
  cursor: pointer;
}
.confirm-close:hover { background: #f1f5f9; color: #475569; }
.confirm-icon {
  width: 56px;
  height: 56px;
  border-radius: 50%;
  margin: 0 auto 16px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 28px;
}
.confirm-icon-primary { background: #dbeafe; color: #2563eb; }
.confirm-icon-danger { background: #fee2e2; color: #dc2626; }
.confirm-icon-warning { background: #fef3c7; color: #d97706; }
.confirm-title {
  font-size: 17px;
  font-weight: 600;
  color: #0f172a;
  margin: 0 0 8px;
}
.confirm-message {
  font-size: 13px;
  color: #475569;
  line-height: 1.6;
  margin: 0 0 20px;
}
.confirm-input-wrap { margin: -10px 0 20px; }
.confirm-input {
  width: 100%;
  padding: 9px 12px;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  font-size: 13px;
  outline: none;
  transition: border-color 0.15s, box-shadow 0.15s;
}
.confirm-input:focus {
  border-color: #3b82f6;
  box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.1);
}
.confirm-actions {
  display: flex;
  gap: 10px;
  justify-content: center;
}
.confirm-btn {
  flex: 1;
  padding: 10px 16px;
  border-radius: 8px;
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  border: 1px solid transparent;
  transition: all 0.15s;
}
.confirm-btn-cancel {
  background: #fff;
  color: #475569;
  border-color: #e2e8f0;
}
.confirm-btn-cancel:hover { background: #f8fafc; }
.confirm-btn-primary {
  background: #3b82f6;
  color: #fff;
}
.confirm-btn-primary:hover { background: #2563eb; }
.confirm-btn-danger {
  background: #ef4444;
  color: #fff;
}
.confirm-btn-danger:hover { background: #dc2626; }
.confirm-btn-warning {
  background: #f59e0b;
  color: #fff;
}
.confirm-btn-warning:hover { background: #d97706; }
</style>
