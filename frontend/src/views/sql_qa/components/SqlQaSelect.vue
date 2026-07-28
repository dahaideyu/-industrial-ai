<template>
  <div class="relative inline-flex" :class="widthClass" ref="container">
    <button
      type="button"
      @click="open = !open"
      class="flex items-center justify-between gap-2 w-full text-sm border border-gray-200 rounded-lg px-3.5 py-2.5 bg-white text-gray-700 hover:border-gray-300 focus:outline-none focus:ring-2 focus:ring-amber-400/30 focus:border-amber-400 transition-shadow cursor-pointer min-w-[8rem]"
    >
      <span class="truncate text-left whitespace-nowrap">{{ selectedLabel }}</span>
      <svg class="w-3.5 h-3.5 text-gray-400 flex-shrink-0 transition-transform duration-150" :class="{ 'rotate-180': open }" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7" />
      </svg>
    </button>
    <div
      v-if="open"
      class="fixed z-50 bg-white rounded-lg shadow-lg border border-gray-100 py-1 max-h-60 overflow-y-auto"
      :style="dropdownStyle"
    >
      <button
        v-for="opt in options"
        :key="opt.value ?? opt"
        type="button"
        @click="select(opt)"
        class="flex items-center w-full px-3.5 py-2.5 text-sm text-left whitespace-nowrap transition-colors"
        :class="isSelected(opt) ? 'bg-amber-50 text-amber-700 font-medium' : 'text-gray-600 hover:bg-gray-50'"
      >
        <svg v-if="isSelected(opt)" class="w-3.5 h-3.5 text-amber-500 mr-2 flex-shrink-0" fill="currentColor" viewBox="0 0 20 20">
          <path fill-rule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clip-rule="evenodd" />
        </svg>
        <span :class="{ 'ml-5.5': !isSelected(opt) }">{{ opt.label ?? opt }}</span>
      </button>
    </div>
    <div v-if="open" class="fixed inset-0 z-40" @click="open = false"></div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted, nextTick, watch } from 'vue'

const props = defineProps({
  modelValue: { type: [String, Number], default: '' },
  options: { type: Array, default: () => [] },
  widthClass: { type: String, default: '' },
})
const emit = defineEmits(['update:modelValue'])

const open = ref(false)
const container = ref(null)
const containerWidth = ref(200)
const dropdownPos = ref({ top: 0, left: 0, width: 200 })

function updateDropdownPos() {
  if (!container.value) return
  const btn = container.value.querySelector('button')
  if (!btn) return
  const rect = btn.getBoundingClientRect()
  dropdownPos.value = {
    top: rect.bottom + 4,
    left: rect.left,
    width: rect.width,
  }
}

function select(opt) {
  emit('update:modelValue', opt.value ?? opt)
  open.value = false
}

function isSelected(opt) {
  return (opt.value ?? opt) === props.modelValue
}

const selectedLabel = computed(() => {
  const opt = props.options.find(o => (o.value ?? o) === props.modelValue)
  return opt ? (opt.label ?? opt) : props.modelValue || '请选择...'
})

const dropdownStyle = computed(() => ({
  top: dropdownPos.value.top + 'px',
  left: dropdownPos.value.left + 'px',
  minWidth: dropdownPos.value.width + 'px',
}))

watch(open, (val) => {
  if (val) {
    nextTick(updateDropdownPos)
    window.addEventListener('scroll', onScroll, true)
  } else {
    window.removeEventListener('scroll', onScroll, true)
  }
})

function onScroll() {
  if (open.value) updateDropdownPos()
}

onMounted(() => {
  if (container.value) containerWidth.value = container.value.offsetWidth || 200
})

onUnmounted(() => {
  window.removeEventListener('scroll', onScroll, true)
})
</script>
