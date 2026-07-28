<template>
  <div class="kb-type-switch" :class="{ enabled: modelValue, disabled: !modelValue }" @click.stop="toggle">
    <div class="switch-track">
      <div class="switch-thumb">
        <svg v-if="modelValue" class="w-3 h-3 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="3" d="M5 13l4 4L19 7"/>
        </svg>
        <svg v-else class="w-3 h-3 text-slate-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="3" d="M6 18L18 6M6 6l12 12"/>
        </svg>
      </div>
      <span class="switch-label">{{ modelValue ? '启用' : '禁用' }}</span>
    </div>
  </div>
</template>

<script setup>
const props = defineProps({
  modelValue: { type: Boolean, required: true },
  loading: { type: Boolean, default: false },
})
const emit = defineEmits(['update:modelValue', 'change'])

function toggle() {
  if (props.loading) return
  emit('update:modelValue', !props.modelValue)
  emit('change', !props.modelValue)
}
</script>

<style scoped>
.kb-type-switch {
  display: inline-flex;
  align-items: center;
  cursor: pointer;
  user-select: none;
}

.switch-track {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 2px;
  border-radius: 999px;
  transition: all 0.2s;
  position: relative;
}

.kb-type-switch.enabled .switch-track {
  background: #dcfce7;
  border: 1px solid #86efac;
}

.kb-type-switch.disabled .switch-track {
  background: #f1f5f9;
  border: 1px solid #cbd5e1;
}

.switch-thumb {
  width: 18px;
  height: 18px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.2s;
  flex-shrink: 0;
}

.kb-type-switch.enabled .switch-thumb {
  background: #16a34a;
  transform: translateX(0);
}

.kb-type-switch.disabled .switch-thumb {
  background: #cbd5e1;
  transform: translateX(0);
}

.switch-label {
  font-size: 10px;
  font-weight: 600;
  padding: 0 6px 0 0;
}

.kb-type-switch.enabled .switch-label {
  color: #16a34a;
}

.kb-type-switch.disabled .switch-label {
  color: #94a3b8;
}
</style>
