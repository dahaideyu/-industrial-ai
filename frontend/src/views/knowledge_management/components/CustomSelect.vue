<template>
  <div class="custom-select relative inline-block w-full" ref="rootEl">
    <button
      type="button"
      class="flex items-center justify-between gap-2 w-full text-sm border border-slate-200 rounded-lg px-3.5 py-2.5 bg-white text-slate-700 hover:border-slate-300 focus:outline-none focus:ring-2 focus:ring-amber-400/30 focus:border-amber-400 transition-shadow cursor-pointer"
      @click="toggle"
    >
      <span class="truncate">{{ selectedLabel }}</span>
      <svg class="w-3.5 h-3.5 text-slate-400 transition-transform flex-shrink-0" :class="{ 'rotate-180': open }" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7"/></svg>
    </button>

    <!-- 下拉菜单 teleport 到 body，突破弹窗 overflow 限制 -->
    <teleport to="body">
      <div
        v-if="open"
        class="fixed z-[9999] bg-white rounded-lg shadow-lg border border-slate-100 py-1 max-h-56 overflow-y-auto"
        :style="dropdownStyle"
      >
        <button
          v-for="opt in options" :key="opt.value"
          type="button"
          class="flex items-center w-full px-3.5 py-2.5 text-sm text-left transition-colors"
          :class="modelValue === opt.value ? 'bg-amber-50 text-amber-600 font-medium' : 'text-slate-600 hover:bg-slate-50'"
          @mousedown.prevent="select(opt.value)"
        >
          {{ opt.label }}
          <svg v-if="modelValue === opt.value" class="w-4 h-4 ml-auto text-amber-500 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"/></svg>
        </button>
      </div>
    </teleport>
  </div>
</template>

<script setup>
import { ref, computed, watch, onMounted, onBeforeUnmount } from 'vue'

const props = defineProps({
  modelValue: { type: String, default: '' },
  options: { type: Array, required: true }, // [{value, label}]
})

const emit = defineEmits(['update:modelValue'])

const open = ref(false)
const dropdownStyle = ref({})
const rootEl = ref(null)

const selectedLabel = computed(() => {
  const opts = props.options || []
  const found = opts.find(o => o.value === props.modelValue)
  return found ? found.label : props.modelValue || '请选择'
})

function toggle() {
  open.value = !open.value
  if (open.value) {
    updatePosition()
  }
}

function select(value) {
  emit('update:modelValue', value)
  open.value = false
}

function updatePosition() {
  if (!rootEl.value) return
  const rect = rootEl.value.getBoundingClientRect()
  dropdownStyle.value = {
    top: rect.bottom + 4 + 'px',
    left: rect.left + 'px',
    width: rect.width + 'px',
    minWidth: '120px',
  }
}

function handleClickOutside(e) {
  if (rootEl.value && !rootEl.value.contains(e.target)) {
    // 检查点击是否在 teleported 下拉菜单内
    const dropdown = document.querySelector('.custom-select-dropdown-teleported')
    if (!dropdown || !dropdown.contains(e.target)) {
      open.value = false
    }
  }
}

watch(open, (val) => {
  if (val) {
    updatePosition()
    document.addEventListener('click', handleClickOutside, true)
    window.addEventListener('scroll', updatePosition, true)
    window.addEventListener('resize', updatePosition)
  } else {
    document.removeEventListener('click', handleClickOutside, true)
    window.removeEventListener('scroll', updatePosition, true)
    window.removeEventListener('resize', updatePosition)
  }
})

onBeforeUnmount(() => {
  document.removeEventListener('click', handleClickOutside, true)
  window.removeEventListener('scroll', updatePosition, true)
  window.removeEventListener('resize', updatePosition)
})
</script>
