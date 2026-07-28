<template>
  <div v-if="data && data.length > 0" class="bg-white rounded-lg border border-gray-100 overflow-hidden">
    <!-- SQL 折叠区（默认折叠） -->
    <div v-if="sql" class="border-b border-gray-100">
      <button @click="showSql = !showSql" class="w-full px-3 py-1.5 flex items-center justify-between text-[11px] text-gray-400 hover:bg-gray-50 transition-colors">
        <span class="font-medium">SQL 查询语句</span>
        <svg class="w-3 h-3 transition-transform" :class="{ 'rotate-180': showSql }" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7" />
        </svg>
      </button>
      <pre v-if="showSql" class="text-[10px] text-gray-500 bg-gray-50 px-3 py-2 overflow-x-auto whitespace-pre-wrap border-t border-gray-100 font-mono">{{ sql }}</pre>
    </div>

    <!-- 数据表格（纯滚动，默认显示 10 行高度） -->
    <div class="overflow-y-auto" :style="{ maxHeight: rowHeight + 'px' }">
      <table class="w-full text-xs result-table">
        <thead class="sticky top-0 bg-gray-50 z-10">
          <tr>
            <th v-for="col in columns" :key="col" @click="toggleSort(col)"
              class="px-3 py-1.5 text-left font-medium text-gray-600 border-b border-r border-gray-200 cursor-pointer hover:bg-gray-100 select-none whitespace-nowrap last:border-r-0">
              {{ col }}
              <span v-if="sortKey === col" class="text-amber-500 ml-0.5">{{ sortDir === 'asc' ? '▲' : '▼' }}</span>
            </th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="(row, ri) in sortedData" :key="ri"
            class="border-b border-gray-50 hover:bg-amber-50/50 transition-colors">
            <td v-for="col in columns" :key="col" @click="copyCell(row[col])"
              class="px-3 py-1.5 text-gray-700 cursor-pointer hover:text-amber-600 border-r border-gray-100 last:border-r-0 whitespace-nowrap"
              :title="formatCell(row[col])">
              {{ formatCell(row[col]) }}
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- 行数统计 -->
    <div class="flex items-center justify-between px-3 py-1 border-t border-gray-100 bg-gray-50/50 text-[11px] text-gray-400">
      <span>共 {{ totalRows }} 条数据</span>
      <span v-if="totalRows > displayRows">显示前 {{ displayRows }} 行，滚动查看更多</span>
    </div>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'

const props = defineProps({
  data: { type: Array, default: () => [] },
  sql: { type: String, default: '' },
  maxHeight: { type: String, default: null },
})

const showSql = ref(false)
const sortKey = ref(null)
const sortDir = ref('asc')
const displayRows = 10

// 行高约 32px，表头约 32px，底部统计约 28px
const rowHeight = computed(() => {
  if (props.maxHeight) return parseInt(props.maxHeight) || 360
  return displayRows * 32 + 32
})

const columns = computed(() => {
  if (!props.data || props.data.length === 0) return []
  return Object.keys(props.data[0])
})

const totalRows = computed(() => props.data?.length || 0)

const sortedData = computed(() => {
  let rows = [...(props.data || [])]
  if (sortKey.value) {
    rows.sort((a, b) => {
      const va = a[sortKey.value], vb = b[sortKey.value]
      if (va == null) return 1
      if (vb == null) return -1
      const r = String(va).localeCompare(String(vb), undefined, { numeric: true })
      return sortDir.value === 'desc' ? -r : r
    })
  }
  return rows
})

function toggleSort(col) {
  if (sortKey.value === col) {
    sortDir.value = sortDir.value === 'asc' ? 'desc' : 'asc'
  } else {
    sortKey.value = col
    sortDir.value = 'asc'
  }
}

function formatCell(val) {
  if (val === null || val === undefined) return ''
  if (typeof val === 'object') return JSON.stringify(val)
  return String(val)
}

function copyCell(val) {
  const text = formatCell(val)
  if (!text) return
  navigator.clipboard?.writeText(text).catch(() => {})
}
</script>

<style scoped>
.result-table {
  border-collapse: separate;
  border-spacing: 0;
}
</style>
