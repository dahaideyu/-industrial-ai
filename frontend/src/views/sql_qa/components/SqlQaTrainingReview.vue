<template>
  <div>
    <div class="mb-4">
      <h3 class="text-base font-semibold text-gray-700">训练审核</h3>
      <p class="text-xs text-gray-400 mt-1">用户标记的问答对在此审核。审核通过后进入记忆库，供后续 SQL 生成参考。</p>
    </div>

    <div class="flex gap-2 mb-3 flex-wrap items-center">
      <button v-for="f in filters" :key="f.val" @click="filter = f.val" :class="['text-xs px-4 py-1.5 rounded border transition-colors', filter === f.val ? 'bg-amber-400 text-gray-900 border-amber-400' : 'border-gray-200 text-gray-600 hover:bg-gray-50']">
        {{ f.label }}
      </button>
    </div>

    <!-- Batch actions -->
    <div v-if="selectedIds.size > 0" class="flex items-center gap-3 mb-3 px-3 py-2 bg-amber-50 rounded-lg text-xs">
      <span class="text-amber-700 font-medium">已选 {{ selectedIds.size }} 项</span>
      <button @click="batchApprove" :disabled="batchLoading" class="px-3 py-1 rounded border border-green-300 text-green-600 hover:bg-green-50 disabled:opacity-50">{{ batchLoading ? '处理中...' : '批量通过' }}</button>
      <button @click="batchDelete" :disabled="batchLoading" class="px-3 py-1 rounded border border-red-300 text-red-500 hover:bg-red-50 disabled:opacity-50">{{ batchLoading ? '处理中...' : '批量删除' }}</button>
      <button @click="selectedIds.clear()" class="px-2 py-1 text-gray-400 hover:text-gray-600">取消选择</button>
    </div>

    <div v-if="loading" class="text-center text-sm text-gray-400 py-8">加载中...</div>
    <div v-else-if="paginatedReviews.length === 0" class="text-center text-sm text-gray-400 py-8">暂无待审核的问答对</div>
    <table v-else class="w-full text-xs border-collapse">
      <thead><tr class="bg-gray-50">
        <th class="w-10 px-3 py-2"><input type="checkbox" :checked="allPageSelected" @change="toggleSelectAll" /></th>
        <th class="w-16 px-3 py-2 text-left font-medium text-gray-600">类型</th>
        <th class="px-3 py-2 text-left font-medium text-gray-600">问题</th>
        <th class="px-3 py-2 text-left font-medium text-gray-600">SQL</th>
        <th v-if="filter !== 'pending'" class="px-3 py-2 text-left font-medium text-gray-600">反馈详情</th>
        <th class="w-44 px-3 py-2 text-left font-medium text-gray-600">操作</th>
      </tr></thead>
      <tbody>
        <tr v-for="r in paginatedReviews" :key="r.id" :class="['border-b border-gray-100 hover:bg-gray-50', r.type === 'feedback' ? 'border-l-2 border-l-red-400' : '', selectedIds.has(r.id) ? 'bg-amber-50' : '']">
          <td class="px-3 py-1.5"><input type="checkbox" :checked="selectedIds.has(r.id)" @change="toggleSelect(r.id)" /></td>
          <td class="px-3 py-1.5 whitespace-nowrap">
            <span :class="['text-xs px-2 py-0.5 rounded', r.type === 'feedback' ? 'bg-red-50 text-red-600' : 'bg-green-50 text-green-600']">
              {{ r.type === 'feedback' ? '错误' : '正确' }}
            </span>
          </td>
          <td class="px-3 py-1.5 max-w-[260px] text-gray-700">{{ r.question }}</td>
          <td class="px-3 py-1.5 font-mono text-[11px] text-green-600 break-all">{{ truncate(r.sql, 120) }}</td>
          <td v-if="filter !== 'pending'" class="px-3 py-1.5 max-w-[200px] text-[11px] text-gray-500">
            <template v-if="r.type === 'feedback'">
              <div v-if="r.user_feedback" class="mb-1"><strong>反馈：</strong>{{ r.user_feedback }}</div>
              <div v-if="r.answer"><strong>原回答：</strong>{{ truncate(r.answer, 80) }}</div>
            </template>
            <span v-else class="text-gray-300">—</span>
          </td>
          <td class="px-3 py-1.5">
            <div class="flex gap-1">
              <button @click="doAction(r.id, 'approve', r.question, r.sql, r.theme)" class="text-xs px-2 py-0.5 rounded border border-green-200 text-green-600 hover:bg-green-50">通过</button>
              <button @click="startEdit(r)" class="text-xs px-2 py-0.5 rounded border border-gray-200 text-gray-500 hover:text-gray-700">编辑</button>
              <button @click="onDelete(r)" class="text-xs px-2 py-0.5 rounded border border-red-200 text-red-500 hover:bg-red-50">删除</button>
            </div>
          </td>
        </tr>
      </tbody>
    </table>

    <SqlQaPagination v-if="reviews.length > 0" :page="page" :pageSize="pageSize" :total="reviews.length" @pageChange="page = $event" @pageSizeChange="pageSize = $event; page = 1" />

    <!-- Edit Modal -->
    <div v-if="editing" class="fixed inset-0 z-50 flex items-center justify-center bg-black/40" @click.self="editing = null">
      <div class="bg-white rounded-xl shadow-xl p-6 w-full max-w-3xl m-4">
        <h3 class="text-lg font-semibold text-gray-800 mb-4">编辑问答{{ editing.type === 'feedback' ? '（错误反馈）' : '' }}</h3>
        <div v-if="editing.type === 'feedback'" class="mb-3 space-y-2">
          <div>
            <label class="block text-xs text-gray-500 mb-1">用户反馈</label>
            <div v-if="editing.user_feedback" class="text-xs px-3 py-2 rounded bg-red-50 text-red-600">{{ editing.user_feedback }}</div>
            <div v-else class="text-xs text-gray-300">—</div>
          </div>
          <div>
            <label class="block text-xs text-gray-500 mb-1">原回答</label>
            <div v-if="editing.answer" class="text-xs px-3 py-2 rounded bg-gray-50 text-gray-500 max-h-20 overflow-auto">{{ editing.answer }}</div>
            <div v-else class="text-xs text-gray-300">—</div>
          </div>
        </div>
        <div class="space-y-3">
          <div>
            <label class="block text-xs text-gray-500 mb-1">问题</label>
            <input v-model="editForm.question" class="w-full px-4 py-3 border border-gray-200 rounded text-sm focus:outline-none focus:border-amber-400" />
          </div>
          <div>
            <label class="block text-xs text-gray-500 mb-1">SQL</label>
            <textarea v-model="editForm.sql" class="w-full px-4 py-3 border border-gray-200 rounded text-sm font-mono text-green-600 focus:outline-none focus:border-amber-400 resize-none" rows="16" />
          </div>
          <div>
            <label class="block text-xs text-gray-500 mb-1">训练主题（可选）</label>
            <input v-model="editForm.theme" placeholder="例如：设备故障工单、设备状态信息统计" maxlength="50" class="w-full px-4 py-3 border border-gray-200 rounded text-sm focus:outline-none focus:border-amber-400" />
          </div>
        </div>
        <div class="flex gap-3 mt-4">
          <button @click="doAction(editing.id, 'edit', editForm.question, editForm.sql, editForm.theme)" class="px-4 py-2 text-sm rounded bg-amber-400 text-gray-900 font-medium hover:bg-amber-300">保存为 SQL 训练对</button>
          <button @click="editing = null" class="px-4 py-2 text-sm rounded border border-gray-200 text-gray-600 hover:bg-gray-50">取消</button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, watch, onMounted } from 'vue'
import { listTrainingReview, trainingReviewAction } from '../../../api/sqlQaClient.js'
import { useSqlQaConfirm } from '../../../composables/sql_qa/useSqlQaConfirm.js'
import SqlQaPagination from './SqlQaPagination.vue'

const { confirm } = useSqlQaConfirm()

const reviews = ref([])
const loading = ref(true)
const filter = ref('all')
const editing = ref(null)
const editForm = ref({ question: '', sql: '', theme: '' })
const selectedIds = ref(new Set())
const page = ref(1)
const pageSize = ref(10)
const batchLoading = ref(false)

const filters = [
  { val: 'all', label: '全部' },
  { val: 'pending', label: '正确反馈' },
  { val: 'feedback', label: '错误反馈' },
]

const paginatedReviews = computed(() => {
  const start = (page.value - 1) * pageSize.value
  return reviews.value.slice(start, start + pageSize.value)
})

const allPageSelected = computed(() =>
  paginatedReviews.value.length > 0 && paginatedReviews.value.every(r => selectedIds.value.has(r.id))
)

watch([filter], () => { page.value = 1; selectedIds.value = new Set() })

async function load() {
  loading.value = true
  try {
    const d = await listTrainingReview({ review_type: filter.value })
    reviews.value = d.reviews || []
  } catch {} finally { loading.value = false }
}

onMounted(load)
watch(filter, load)

function toggleSelect(id) {
  const next = new Set(selectedIds.value)
  if (next.has(id)) next.delete(id); else next.add(id)
  selectedIds.value = next
}

function toggleSelectAll() {
  if (allPageSelected.value) {
    const next = new Set(selectedIds.value)
    paginatedReviews.value.forEach(r => next.delete(r.id))
    selectedIds.value = next
  } else {
    selectedIds.value = new Set([...selectedIds.value, ...paginatedReviews.value.map(r => r.id)])
  }
}

async function batchApprove() {
  if (selectedIds.value.size === 0) return
  const ok = await confirm({ message: `确认通过选中的 ${selectedIds.value.size} 条记录？` })
  if (!ok) return
  batchLoading.value = true
  try {
    const ids = [...selectedIds.value]
    for (const id of ids) {
      const r = reviews.value.find(rv => rv.id === id)
      await trainingReviewAction({ review_id: id, action: 'approve', question: r?.question || '', sql: r?.sql || '', theme: r?.theme || undefined })
    }
    selectedIds.value = new Set()
    await load()
  } catch {} finally { batchLoading.value = false }
}

async function batchDelete() {
  if (selectedIds.value.size === 0) return
  const ok = await confirm({ message: `确认删除选中的 ${selectedIds.value.size} 条记录？此操作不可逆！`, danger: true })
  if (!ok) return
  batchLoading.value = true
  try {
    for (const id of selectedIds.value) {
      await trainingReviewAction({ review_id: id, action: 'delete' })
    }
    selectedIds.value = new Set()
    await load()
  } catch {} finally { batchLoading.value = false }
}

async function doAction(id, action, question, sql, theme) {
  await trainingReviewAction({ review_id: id, action, question, sql, theme: theme || undefined })
  editing.value = null
  load()
}

function startEdit(r) {
  editing.value = r
  editForm.value = { question: r.question, sql: r.sql, theme: r.theme || '' }
}

async function onDelete(r) {
  const ok = await confirm({ message: '确认删除此训练记录？', danger: true })
  if (ok) doAction(r.id, 'delete')
}

function truncate(s, n) { return s && s.length > n ? s.slice(0, n) + '...' : s }
</script>
