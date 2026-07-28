<template>
  <div>
    <div class="mb-4">
      <h3 class="text-base font-semibold text-gray-700">记忆库管理</h3>
    </div>

    <div class="flex items-center gap-2 mb-3 flex-wrap">
      <input v-model="searchText" placeholder="搜索记忆..." class="text-sm px-4 py-2.5 border border-gray-200 rounded w-64 focus:outline-none focus:border-amber-400" />
      <SqlQaSelect v-model="typeFilter" :options="[{value:'all',label:'全部类型'},{value:'sql_pair',label:'SQL 对'},{value:'documentation',label:'文档'}]" />
      <SqlQaSelect v-model="themeFilter" :options="themeOptions" />
      <button @click="handleExportAll" class="text-xs px-3 py-1.5 rounded border border-gray-200 text-gray-600 hover:bg-gray-50">导出全部</button>
      <button @click="showImport = true" class="text-xs px-3 py-1.5 rounded border border-gray-200 text-gray-600 hover:bg-gray-50">导入 JSON</button>
    </div>

    <!-- Batch actions -->
    <div v-if="anySelected" class="flex items-center gap-2 mb-3 px-3 py-2 bg-amber-50 rounded text-xs">
      <span class="text-amber-700">已选 {{ selectedIds.size }} 项</span>
      <button @click="handleBatchDelete" class="px-2 py-1 rounded border border-red-200 text-red-600 hover:bg-red-50">删除所选</button>
      <button @click="handleExportSelected" class="px-2 py-1 rounded border border-gray-200 text-gray-600 hover:bg-gray-50">导出所选</button>
    </div>

    <!-- Table -->
    <div v-if="loading" class="text-center text-sm text-gray-400 py-8">加载中...</div>
    <div v-else-if="memories.length === 0" class="text-center text-sm text-gray-400 py-8">暂无记忆数据</div>
    <template v-else>
      <table class="w-full text-xs border-collapse">
        <thead><tr class="bg-gray-50">
          <th class="w-10 px-3 py-2"><input type="checkbox" :checked="allPageSelected" @change="toggleSelectAll" /></th>
          <th class="w-20 px-3 py-2 text-left font-medium text-gray-600">类型</th>
          <th class="w-32 px-3 py-2 text-left font-medium text-gray-600">主题</th>
          <th class="px-3 py-2 text-left font-medium text-gray-600">内容</th>
          <th class="w-40 px-3 py-2 text-left font-medium text-gray-600">时间</th>
          <th class="w-28 px-3 py-2 text-left font-medium text-gray-600">操作</th>
        </tr></thead>
        <tbody>
          <tr v-for="m in paginatedMemories" :key="m.id" :class="['border-b border-gray-100 hover:bg-gray-50', selectedIds.has(m.id) ? 'bg-amber-50' : '']">
            <td class="px-3 py-1.5"><input type="checkbox" :checked="selectedIds.has(m.id)" @change="toggleSelect(m.id)" /></td>
            <td class="px-3 py-1.5">
              <span :class="['text-xs px-2 py-0.5 rounded', m.type === 'sql_pair' ? 'bg-blue-50 text-blue-600' : 'bg-green-50 text-green-600']">
                {{ m.type === 'sql_pair' ? 'SQL对' : '文档' }}
              </span>
            </td>
            <td class="px-3 py-1.5">
              <span v-if="m.theme" class="text-xs text-gray-600">{{ m.theme }}</span>
              <span v-else class="text-xs text-gray-300">—</span>
            </td>
            <td class="px-3 py-1.5">
              <div class="text-xs max-w-md">
                <template v-if="m.type === 'sql_pair'">
                  <div class="truncate text-gray-700">{{ m.question || '—' }}</div>
                  <div v-if="m.args?.sql" class="truncate font-mono text-green-600 text-[11px] mt-0.5">{{ m.args.sql }}</div>
                </template>
                <template v-else>
                  <div class="truncate text-gray-600">{{ m.content || '—' }}</div>
                </template>
              </div>
            </td>
            <td class="px-3 py-1.5 text-gray-400 text-[11px]">{{ m.timestamp || '—' }}</td>
            <td class="px-3 py-1.5">
              <div class="flex gap-1">
                <button @click="startEdit(m)" class="text-xs px-2 py-0.5 rounded border border-gray-200 text-gray-500 hover:text-gray-700">编辑</button>
                <button @click="deleteMemory(m.id)" class="text-xs px-2 py-0.5 rounded border border-red-200 text-red-500 hover:bg-red-50">删除</button>
              </div>
            </td>
          </tr>
        </tbody>
      </table>
      <SqlQaPagination :page="page" :pageSize="pageSize" :total="total" @pageChange="page = $event" @pageSizeChange="pageSize = $event; page = 1" />
    </template>

    <!-- Edit Modal -->
    <div v-if="editing" class="fixed inset-0 z-50 flex items-center justify-center bg-black/40" @click.self="editing = null">
      <div class="bg-white rounded-xl shadow-xl p-6 w-full max-w-4xl m-4">
        <h3 class="text-lg font-semibold text-gray-800 mb-4">编辑记忆</h3>
        <div class="space-y-3">
          <template v-if="editing.type === 'sql_pair'">
            <label class="block text-xs text-gray-500">问题</label>
            <input v-model="editForm.question" class="w-full px-4 py-3 border border-gray-200 rounded text-sm focus:outline-none focus:border-amber-400" />
            <label class="block text-xs text-gray-500">SQL</label>
            <textarea v-model="editForm.sql" class="w-full px-4 py-3 border border-gray-200 rounded text-sm font-mono text-green-600 focus:outline-none focus:border-amber-400 resize-none" rows="20" />
            <label class="block text-xs text-gray-500">训练主题（可选）</label>
            <input v-model="editForm.theme" placeholder="例如：设备故障工单、设备状态信息统计" maxlength="50" class="w-full px-4 py-3 border border-gray-200 rounded text-sm focus:outline-none focus:border-amber-400" />
          </template>
          <template v-else>
            <label class="block text-xs text-gray-500">文档内容</label>
            <textarea v-model="editForm.content" class="w-full px-4 py-3 border border-gray-200 rounded text-sm focus:outline-none focus:border-amber-400 resize-none" rows="30" />
          </template>
        </div>
        <div class="flex gap-3 mt-4">
          <button @click="submitEdit" class="px-4 py-2 text-sm rounded bg-amber-400 text-gray-900 font-medium hover:bg-amber-300">保存并重新向量化</button>
          <button @click="editing = null" class="px-4 py-2 text-sm rounded border border-gray-200 text-gray-600 hover:bg-gray-50">取消</button>
        </div>
      </div>
    </div>

    <SqlQaImportModal :open="showImport" title="导入记忆库数据" entityLabel="记忆库" :onImport="handleImport" @close="showImport = false" @done="fetchMemories" />
  </div>
</template>

<script setup>
import { ref, computed, watch, onMounted } from 'vue'
import { listMemories, listMemoryThemes, deleteMemory as apiDeleteMemory, batchDeleteMemories, editMemory, importMemories, exportMemories } from '../../../api/sqlQaClient.js'
import { useSqlQaConfirm } from '../../../composables/sql_qa/useSqlQaConfirm.js'
import SqlQaPagination from './SqlQaPagination.vue'
import SqlQaImportModal from './SqlQaImportModal.vue'
import SqlQaSelect from './SqlQaSelect.vue'

const { confirm } = useSqlQaConfirm()

const memories = ref([])
const total = ref(0)
const loading = ref(false)
const searchText = ref('')
const typeFilter = ref('all')
const themeFilter = ref('all')
const page = ref(1)
const pageSize = ref(10)
const editing = ref(null)
const editForm = ref({ question: '', sql: '', content: '', theme: '' })
const showImport = ref(false)
const selectedIds = ref(new Set())

// 主题选项（从已加载的记忆中提取去重）
const allThemes = ref([])
const themeOptions = computed(() => {
  const opts = [{ value: 'all', label: '全部主题' }]
  for (const t of allThemes.value) {
    opts.push({ value: t, label: t })
  }
  return opts
})

async function fetchMemories() {
  loading.value = true
  try {
    const params = { page: page.value, page_size: pageSize.value }
    if (typeFilter.value !== 'all') params.type = typeFilter.value
    if (searchText.value) params.search = searchText.value
    if (themeFilter.value !== 'all') params.theme = themeFilter.value
    const d = await listMemories(params)
    memories.value = d.memories || []
    total.value = d.total || 0
    // 每次加载时刷新主题列表
    fetchAllThemes()
  } catch {} finally { loading.value = false }
}

async function fetchAllThemes() {
  try {
    const d = await listMemoryThemes()
    allThemes.value = d.themes || []
  } catch {}
}

onMounted(fetchMemories)
watch([searchText, typeFilter, themeFilter], () => { page.value = 1; fetchMemories() })
watch([page, pageSize], fetchMemories)

// 服务端分页，直接使用后端返回的当前页数据
const paginatedMemories = computed(() => memories.value)

const allPageSelected = computed(() => paginatedMemories.value.length > 0 && paginatedMemories.value.every(m => selectedIds.value.has(m.id)))
const anySelected = computed(() => selectedIds.value.size > 0)
const selectedCount = computed(() => paginatedMemories.value.filter(m => selectedIds.value.has(m.id)).length)

function toggleSelect(id) {
  const next = new Set(selectedIds.value)
  if (next.has(id)) next.delete(id); else next.add(id)
  selectedIds.value = next
}

function toggleSelectAll() {
  const pageIds = paginatedMemories.value.map(m => m.id)
  if (allPageSelected.value) {
    const next = new Set(selectedIds.value)
    pageIds.forEach(id => next.delete(id))
    selectedIds.value = next
  } else {
    selectedIds.value = new Set([...selectedIds.value, ...pageIds])
  }
}

async function deleteMemory(id) {
  const ok = await confirm({ message: '确认删除此记忆？', danger: true })
  if (!ok) return
  await apiDeleteMemory(id)
  const next = new Set(selectedIds.value); next.delete(id); selectedIds.value = next
  fetchMemories()
}

async function handleBatchDelete() {
  if (selectedIds.value.size === 0) return
  const ok = await confirm({ message: `确认删除选中的 ${selectedIds.value.size} 条记忆？此操作不可逆！`, danger: true })
  if (!ok) return
  await batchDeleteMemories(Array.from(selectedIds.value))
  selectedIds.value = new Set()
  fetchMemories()
}

function handleExportSelected() {
  if (selectedIds.value.size === 0) return
  const selected = memories.value.filter(m => selectedIds.value.has(m.id))
  const entries = selected.map(m => {
    if (m.type === 'sql_pair') return { type: 'sql_pair', question: m.question || '', sql: m.args?.sql || '', theme: m.theme || m.metadata?.theme || '' }
    return { type: 'documentation', content: m.content || '', theme: '' }
  })
  downloadJson({ version: 2, exported_at: new Date().toISOString(), entity: 'memories', entries }, 'memories-export.json')
}

async function handleImport(entries) {
  return await importMemories({ version: 1, entity: 'memories', entries })
}

async function handleExportAll() {
  const ok = await confirm({ message: '确认导出全部记忆数据？将导出所有类型的全部条目。', confirmLabel: '导出全部' })
  if (!ok) return
  try {
    const blob = await exportMemories(typeFilter.value !== 'all' ? typeFilter.value : undefined)
    downloadBlob(blob, 'memories-export.json')
  } catch {}
}

function startEdit(m) {
  editing.value = m
  editForm.value = { question: m.question || '', sql: m.args?.sql || '', content: m.content || '', theme: m.theme || m.metadata?.theme || '' }
}

async function submitEdit() {
  if (!editing.value) return
  const body = { memory_id: editing.value.id, type: editing.value.type }
  if (editing.value.type === 'sql_pair') { body.question = editForm.value.question; body.sql = editForm.value.sql; body.theme = editForm.value.theme || undefined }
  else { body.content = editForm.value.content }
  const d = await editMemory(body)
  if (d.success) { editing.value = null; fetchMemories() }
  else { alert('编辑失败: ' + JSON.stringify(d)) }
}

function truncate(s, n) { return s && s.length > n ? s.slice(0, n) + '...' : s }

function downloadJson(data, filename) {
  const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' })
  downloadBlob(blob, filename)
}

function downloadBlob(blob, filename) {
  const a = document.createElement('a')
  a.href = URL.createObjectURL(blob)
  a.download = filename
  a.click()
  URL.revokeObjectURL(a.href)
}
</script>
