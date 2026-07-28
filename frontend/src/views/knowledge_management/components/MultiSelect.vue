<template>
  <div>
    <div class="flex items-center justify-between mb-2">
      <label class="text-[13px] font-medium text-slate-700">
        {{ label }} <span v-if="required" class="text-red-500">*</span>
        <span class="text-xs text-slate-400 ml-2">(已选 {{ selected.length }}/{{ options.length }})</span>
      </label>
      <div class="flex items-center gap-2">
        <button @click="toggleAll" class="text-xs text-amber-600 hover:text-amber-700 font-medium">
          {{ allFilteredSelected ? '取消全选' : '全选' }}
        </button>
        <button @click="invertSelection" class="text-xs text-slate-500 hover:text-slate-700 font-medium">反选</button>
        <button @click="clearSelection" class="text-xs text-slate-400 hover:text-slate-600 font-medium">清空</button>
      </div>
    </div>
    <div class="border border-slate-200 rounded-lg overflow-hidden">
      <!-- 搜索框 -->
      <div class="p-2 border-b border-slate-100 bg-slate-50">
        <div class="relative">
          <svg class="absolute left-2.5 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"/>
          </svg>
          <input
            v-model="searchQuery"
            type="text"
            :placeholder="`搜索${label}...`"
            class="w-full pl-8 pr-8 py-1.5 text-sm border border-slate-200 rounded-md focus:outline-none focus:border-amber-400 focus:ring-1 focus:ring-amber-400/30"
          />
          <button
            v-if="searchQuery"
            @click="searchQuery = ''"
            class="absolute right-2 top-1/2 -translate-y-1/2 w-5 h-5 flex items-center justify-center text-slate-400 hover:text-slate-600 rounded-full hover:bg-slate-200"
          >
            <svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/>
            </svg>
          </button>
        </div>
      </div>
      <!-- 选项列表 -->
      <div class="max-h-48 overflow-y-auto scrollbar-thin">
        <div v-if="filteredOptions.length === 0" class="px-3 py-4 text-center text-sm text-slate-400">
          {{ searchQuery ? '无匹配项' : '暂无选项' }}
        </div>
        <label
          v-for="option in filteredOptions"
          :key="option.value"
          class="flex items-center gap-2.5 px-3 py-2 hover:bg-amber-50/50 cursor-pointer transition-colors"
        >
          <input
            type="checkbox"
            :checked="isSelected(option.value)"
            @change="toggleOption(option.value)"
            class="w-4 h-4 rounded border-slate-300 text-amber-500 focus:ring-amber-400"
          />
          <span class="text-sm text-slate-700 flex-1">{{ option.label }}</span>
          <span v-if="option.sub" class="text-xs text-slate-400">{{ option.sub }}</span>
        </label>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'

const props = defineProps({
  modelValue: {
    type: Array,
    default: () => []
  },
  options: {
    type: Array,
    default: () => []
    // 格式: [{ value: 'id', label: '名称', sub: '可选描述' }]
  },
  label: {
    type: String,
    default: '选项'
  },
  required: {
    type: Boolean,
    default: false
  }
})

const emit = defineEmits(['update:modelValue'])

const searchQuery = ref('')

// 过滤后的选项
const filteredOptions = computed(() => {
  const query = searchQuery.value.toLowerCase()
  if (!query) return props.options
  return props.options.filter(opt =>
    opt.label.toLowerCase().includes(query) ||
    (opt.sub && opt.sub.toLowerCase().includes(query))
  )
})

// 已选中的值
const selected = computed(() => props.modelValue || [])

// 当前过滤后的选项是否全部选中
const allFilteredSelected = computed(() => {
  return filteredOptions.value.length > 0 && filteredOptions.value.every(opt => selected.value.includes(opt.value))
})

// 判断是否选中
function isSelected(value) {
  return selected.value.includes(value)
}

// 切换选项
function toggleOption(value) {
  const newSelected = [...selected.value]
  const index = newSelected.indexOf(value)
  if (index >= 0) {
    newSelected.splice(index, 1)
  } else {
    newSelected.push(value)
  }
  emit('update:modelValue', newSelected)
}

// 全选/取消全选（基于当前过滤结果）
function toggleAll() {
  if (allFilteredSelected.value) {
    // 取消选中当前过滤结果中的所有选项
    const filteredValues = new Set(filteredOptions.value.map(opt => opt.value))
    const newSelected = selected.value.filter(v => !filteredValues.has(v))
    emit('update:modelValue', newSelected)
  } else {
    // 选中当前过滤结果中的所有选项（保留其他已选中的）
    const newSelected = [...new Set([...selected.value, ...filteredOptions.value.map(opt => opt.value)])]
    emit('update:modelValue', newSelected)
  }
}

// 反选
function invertSelection() {
  const newSelected = props.options
    .filter(opt => !selected.value.includes(opt.value))
    .map(opt => opt.value)
  emit('update:modelValue', newSelected)
}

// 清空
function clearSelection() {
  emit('update:modelValue', [])
}
</script>

<style scoped>
.scrollbar-thin::-webkit-scrollbar {
  width: 6px;
}
.scrollbar-thin::-webkit-scrollbar-track {
  background: #f1f5f9;
  border-radius: 3px;
}
.scrollbar-thin::-webkit-scrollbar-thumb {
  background: #cbd5e1;
  border-radius: 3px;
}
.scrollbar-thin::-webkit-scrollbar-thumb:hover {
  background: #94a3b8;
}
</style>
