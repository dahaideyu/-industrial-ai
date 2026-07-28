<template>
  <div>
    <div class="mb-4">
      <h3 class="text-base font-semibold text-gray-700">数据库索引</h3>
      <p class="text-xs text-gray-400 mt-1">选择需要向量化的表，索引后 AI 可在生成 SQL 时自动检索这些表的结构</p>
    </div>

    <div class="flex items-center gap-2 mb-3 flex-wrap">
      <input v-model="search" placeholder="搜索表名..." class="text-sm px-4 py-2.5 border border-gray-200 rounded w-64 focus:outline-none focus:border-amber-400" />
      <SqlQaSelect v-model="filter" :options="filterOptions" />
      <div class="flex-1" />
      <button @click="doIndex" :disabled="loading || !canIndex" class="text-xs px-3 py-1.5 rounded bg-amber-400 text-gray-900 font-medium hover:bg-amber-300 disabled:opacity-40 disabled:cursor-not-allowed">
        确认索引 ({{ indexCount }})
      </button>
      <button @click="doUnindex" :disabled="loading || !canUnindex" class="text-xs px-3 py-1.5 rounded bg-red-500 text-white font-medium hover:bg-red-400 disabled:opacity-40 disabled:cursor-not-allowed">
        取消索引 ({{ unindexCount }})
      </button>
    </div>

    <div v-if="msg" class="text-xs px-3 py-2 rounded bg-amber-50 text-amber-700 mb-3 flex items-center justify-between">
      {{ msg }}
      <button @click="msg = ''" class="text-gray-400 hover:text-gray-600">&times;</button>
    </div>

    <table class="w-full text-xs border-collapse">
      <thead><tr class="bg-gray-50">
        <th class="w-10 px-3 py-2 text-left"><input type="checkbox" :checked="allPageSelected" @change="toggleAll" /></th>
        <th class="px-3 py-2 text-left font-medium text-gray-600">表名</th>
        <th class="w-24 px-3 py-2 text-left font-medium text-gray-600">状态</th>
      </tr></thead>
      <tbody>
        <tr v-for="t in paginatedTables" :key="t" @click="toggleSelect(t)" class="border-b border-gray-100 hover:bg-amber-50/50 cursor-pointer">
          <td class="px-3 py-1.5"><input type="checkbox" :checked="selected.has(t)" @change="toggleSelect(t)" /></td>
          <td class="px-3 py-1.5 text-gray-700 font-mono text-xs">{{ t }}</td>
          <td class="px-3 py-1.5">
            <span v-if="indexedSet.has(t)" class="text-xs px-2 py-0.5 rounded bg-green-50 text-green-600">已索引</span>
            <span v-else class="text-xs px-2 py-0.5 rounded bg-gray-100 text-gray-400">未索引</span>
          </td>
        </tr>
      </tbody>
    </table>
    <div v-if="filteredTables.length === 0" class="text-center text-sm text-gray-400 py-8">没有匹配的表</div>

    <SqlQaPagination :page="page" :pageSize="pageSize" :total="filteredTables.length" @pageChange="page = $event" @pageSizeChange="pageSize = $event; page = 1" />
  </div>
</template>

<script setup>
import { ref, computed, onMounted, watch } from 'vue'
import { getSchemaStatus, indexSchemas, unindexSchemas } from '../../../api/sqlQaClient.js'
import { useSqlQaConfirm } from '../../../composables/sql_qa/useSqlQaConfirm.js'
import SqlQaPagination from './SqlQaPagination.vue'
import SqlQaSelect from './SqlQaSelect.vue'

const filterOptions = computed(() => [
  { value: 'all', label: `全部 (${allTables.value.length})` },
  { value: 'indexed', label: `已索引 (${indexedTables.value.length})` },
  { value: 'unindexed', label: `未索引 (${allTables.value.length - indexedTables.value.length})` },
])

const { confirm } = useSqlQaConfirm()

const allTables = ref([])
const indexedTables = ref([])
const selected = ref(new Set())
const search = ref('')
const filter = ref('all')
const loading = ref(false)
const msg = ref('')
const page = ref(1)
const pageSize = ref(10)

const indexedSet = computed(() => new Set(indexedTables.value))

const filteredTables = computed(() => {
  let list = allTables.value
  if (search.value) {
    const s = search.value.toLowerCase()
    list = list.filter(t => t.toLowerCase().includes(s))
  }
  if (filter.value === 'indexed') list = list.filter(t => indexedSet.value.has(t))
  if (filter.value === 'unindexed') list = list.filter(t => !indexedSet.value.has(t))
  return list
})

const paginatedTables = computed(() => {
  const start = (page.value - 1) * pageSize.value
  return filteredTables.value.slice(start, start + pageSize.value)
})

const allPageSelected = computed(() => paginatedTables.value.length > 0 && paginatedTables.value.every(t => selected.value.has(t)))

const indexCount = computed(() => [...selected.value].filter(t => !indexedSet.value.has(t)).length)
const unindexCount = computed(() => [...selected.value].filter(t => indexedSet.value.has(t)).length)
const canIndex = computed(() => selected.value.size > 0 && indexCount.value > 0)
const canUnindex = computed(() => selected.value.size > 0 && unindexCount.value > 0)

watch([search, filter], () => { page.value = 1 })

async function loadStatus() {
  try {
    const d = await getSchemaStatus()
    if (d.success) {
      allTables.value = d.all_tables || []
      indexedTables.value = d.indexed_tables || []
    }
  } catch {}
}

onMounted(loadStatus)

function toggleSelect(t) {
  const next = new Set(selected.value)
  if (next.has(t)) next.delete(t); else next.add(t)
  selected.value = next
}

function toggleAll() {
  if (allPageSelected.value) {
    selected.value = new Set()
  } else {
    selected.value = new Set(filteredTables.value)
  }
}

async function doIndex() {
  const toIndex = [...selected.value].filter(t => !indexedSet.value.has(t))
  if (toIndex.length === 0) { msg.value = '所选表均已索引'; return }
  msg.value = `正在索引 ${toIndex.length} 张表...`
  loading.value = true
  try {
    const d = await indexSchemas(toIndex)
    if (d.success) {
      const errCount = d.errors?.length || 0
      msg.value = `已索引 ${d.indexed?.length || 0} 张表` + (errCount > 0 ? `，${errCount} 张失败` : '')
    } else {
      msg.value = '索引失败: ' + (d.detail || '未知错误')
    }
    selected.value = new Set()
    await loadStatus()
  } finally { loading.value = false }
}

async function doUnindex() {
  const toRemove = [...selected.value].filter(t => indexedSet.value.has(t))
  if (toRemove.length === 0) { msg.value = '所选表均未索引'; return }
  const ok = await confirm({ message: `确认取消索引 ${toRemove.length} 张表？`, danger: true })
  if (!ok) return
  loading.value = true
  try {
    const d = await unindexSchemas(toRemove)
    msg.value = `已取消索引 ${d.removed?.length || 0} 张表`
    selected.value = new Set()
    await loadStatus()
  } finally { loading.value = false }
}
</script>
