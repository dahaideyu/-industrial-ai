<template>
  <div class="flex items-center justify-between py-2 text-sm">
    <div class="text-gray-500">
      <span>{{ start }}-{{ end }}</span>
      <span class="mx-1">/</span>
      <span>{{ total }}</span>
    </div>
    <div class="flex items-center gap-3">
      <select
        :value="pageSize"
        @change="$emit('pageSizeChange', Number($event.target.value))"
        class="text-xs border border-gray-200 rounded-md px-2 py-1 bg-white text-gray-600 focus:outline-none focus:ring-1 focus:ring-amber-400/30 focus:border-amber-400 cursor-pointer transition-shadow"
      >
        <option v-for="s in pageSizeOptions" :key="s" :value="s">{{ s }} 条/页</option>
      </select>
      <div class="flex items-center gap-1">
        <button
          :disabled="page <= 1"
          @click="$emit('pageChange', page - 1)"
          class="px-2 py-1 rounded border border-gray-200 text-gray-400 disabled:opacity-30 hover:bg-gray-50"
        >
          <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2"><polyline points="15 18 9 12 15 6"/></svg>
        </button>
        <span class="text-xs text-gray-400 px-2">{{ page }}<span class="mx-0.5">/</span>{{ totalPages }}</span>
        <button
          :disabled="page >= totalPages"
          @click="$emit('pageChange', page + 1)"
          class="px-2 py-1 rounded border border-gray-200 text-gray-400 disabled:opacity-30 hover:bg-gray-50"
        >
          <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2"><polyline points="9 18 15 12 9 6"/></svg>
        </button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  page: { type: Number, default: 1 },
  pageSize: { type: Number, default: 10 },
  total: { type: Number, default: 0 },
})

defineEmits(['pageChange', 'pageSizeChange'])

const pageSizeOptions = [10, 50, 100]

const totalPages = computed(() => Math.max(1, Math.ceil(props.total / props.pageSize)))
const start = computed(() => props.total === 0 ? 0 : (props.page - 1) * props.pageSize + 1)
const end = computed(() => Math.min(props.page * props.pageSize, props.total))
</script>
