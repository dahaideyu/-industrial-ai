<template>
  <Teleport to="body">
    <div class="toast-container">
      <TransitionGroup name="toast">
        <div v-for="t in toasts" :key="t.id" :class="['toast', `toast-${t.type}`]">
          <span class="toast-icon">{{ iconFor(t.type) }}</span>
          <div class="toast-content">
            <div v-if="t.title" class="toast-title">{{ t.title }}</div>
            <div class="toast-message">{{ t.message }}</div>
          </div>
          <button class="toast-close" @click="remove(t.id)">×</button>
        </div>
      </TransitionGroup>
    </div>
  </Teleport>
</template>

<script setup>
import { useToast } from '@/composables/useToast'
const { toasts, remove, iconFor } = useToast()
</script>

<style scoped>
.toast-container {
  position: fixed;
  top: 20px;
  right: 20px;
  z-index: 9999;
  display: flex;
  flex-direction: column;
  gap: 10px;
  pointer-events: none;
}
.toast {
  pointer-events: auto;
  min-width: 280px;
  max-width: 400px;
  padding: 12px 16px;
  background: #fff;
  border-radius: 10px;
  box-shadow: 0 4px 20px rgba(0, 0, 0, 0.08), 0 0 0 1px rgba(0, 0, 0, 0.04);
  display: flex;
  align-items: flex-start;
  gap: 10px;
  font-size: 13px;
  line-height: 1.5;
}
.toast-icon {
  font-size: 18px;
  line-height: 1;
  flex-shrink: 0;
  margin-top: 1px;
}
.toast-content { flex: 1; min-width: 0; }
.toast-title { font-weight: 600; color: #0f172a; margin-bottom: 2px; }
.toast-message { color: #475569; word-break: break-word; }
.toast-close {
  background: transparent;
  border: none;
  font-size: 20px;
  line-height: 1;
  color: #94a3b8;
  cursor: pointer;
  padding: 0;
  width: 20px;
  height: 20px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 4px;
  flex-shrink: 0;
}
.toast-close:hover { background: #f1f5f9; color: #475569; }

.toast-success { border-left: 3px solid #10b981; }
.toast-info { border-left: 3px solid #3b82f6; }
.toast-warn { border-left: 3px solid #f59e0b; }
.toast-error { border-left: 3px solid #ef4444; }

.toast-enter-active, .toast-leave-active {
  transition: all 0.2s ease;
}
.toast-enter-from {
  opacity: 0;
  transform: translateX(20px);
}
.toast-leave-to {
  opacity: 0;
  transform: translateX(20px);
}
</style>
