<template>
  <div class="h-full flex bg-slate-50">
    <!-- 左侧：层级树面板 -->
    <HierarchyTree
      :baseName="dashboard?.base_name || '基地'"
      :workshops="dashboard?.workshops || []"
      :customKbs="dashboard?.custom_kbs || []"
      :activeNode="activeNode"
      :expanded="expandedWorkshops"
      :expandedDevices="expandedDevices"
      :deviceDocuments="deviceDocuments"
      :deviceDocsLoading="deviceDocsLoading"
      @nav="handleNavigate"
      @toggle-workshop="toggleWorkshop"
      @toggle-device="toggleDevice"
    />

    <!-- 右侧：主内容区 -->
    <div class="flex-1 overflow-y-auto p-6">
      <!-- 顶部：基地名称 + 按钮 -->
      <div class="flex items-start justify-between mb-5">
        <div>
          <h1 class="text-xl font-bold text-slate-800">{{ dashboard?.base_name || '基地总览' }}</h1>
          <p class="text-sm text-slate-500 mt-1">管理知识库、收集计划和已发布文档</p>
        </div>
        <div class="flex items-center gap-2">
          <button class="btn-ghost text-sm" @click="handleSyncDeviceTypes" :disabled="syncing">
            <span v-if="syncing" class="inline-block w-3.5 h-3.5 border-2 border-amber-400 border-t-transparent rounded-full animate-spin mr-1"></span>
            <svg v-else class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"/></svg>
            {{ syncing ? '同步中...' : '同步设备类型' }}
          </button>
          <button class="btn-primary !bg-white !text-slate-800 border-2 border-slate-300 hover:!bg-slate-50 font-bold" @click="showCreateDialog = true">
            <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 4v16m8-8H4"/></svg>
            创建知识库
          </button>
        </div>
      </div>

      <!-- 加载 -->
      <div v-if="loading" class="flex items-center justify-center py-20">
        <div class="animate-spin rounded-full h-7 w-7 border-b-2 border-amber-500"></div>
        <span class="ml-3 text-slate-500 text-sm">加载中...</span>
      </div>

      <template v-else-if="dashboard">
        <!-- 统计卡片 -->
        <div class="grid grid-cols-5 gap-3.5 mb-5">
          <div class="bg-white border border-slate-200 rounded-2xl p-4">
            <div class="flex items-center justify-between mb-2">
              <span class="text-xs font-semibold text-slate-500 uppercase tracking-wide">总完成率</span>
              <div class="w-8 h-8 rounded-lg bg-amber-50 flex items-center justify-center text-amber-500">
                <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z"/></svg>
              </div>
            </div>
            <p class="text-2xl font-bold text-amber-500">{{ dashboard.total_progress ?? '—' }}%</p>
            <p class="text-xs text-slate-500 mt-1">{{ dashboard.completed_items || 0 }}/{{ dashboard.total_items || 0 }} 项完成</p>
            <div class="h-1 bg-slate-100 rounded mt-2.5 overflow-hidden"><div class="h-full bg-amber-500 rounded transition-all duration-500" :style="{ width: (dashboard.total_progress || 0) + '%' }"></div></div>
          </div>
          <div class="bg-white border border-slate-200 rounded-2xl p-4">
            <div class="flex items-center justify-between mb-2">
              <span class="text-xs font-semibold text-slate-500 uppercase tracking-wide">质量分</span>
              <div class="w-8 h-8 rounded-lg bg-emerald-50 flex items-center justify-center text-emerald-500">
                <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z"/></svg>
              </div>
            </div>
            <p class="text-2xl font-bold text-emerald-500">{{ dashboard.quality_score ?? '—' }}</p>
            <p class="text-xs text-slate-500 mt-1">AI 综合评估</p>
            <div class="h-1 bg-slate-100 rounded mt-2.5 overflow-hidden"><div class="h-full bg-emerald-500 rounded transition-all duration-500" :style="{ width: (dashboard.quality_score || 0) + '%' }"></div></div>
          </div>
          <div class="bg-white border border-slate-200 rounded-2xl p-4">
            <div class="flex items-center justify-between mb-2">
              <span class="text-xs font-semibold text-slate-500 uppercase tracking-wide">车间数</span>
              <div class="w-8 h-8 rounded-lg bg-blue-50 flex items-center justify-center text-blue-500">
                <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 21V5a2 2 0 00-2-2H7a2 2 0 00-2 2v16m14 0h2m-2 0h-5m-9 0H3m2 0h5M9 7h1m-1 4h1m4-4h1m-1 4h1m-5 10v-5a1 1 0 011-1h2a1 1 0 011 1v5m-4 0h4"/></svg>
              </div>
            </div>
            <p class="text-2xl font-bold text-blue-500">{{ dashboard.workshop_count || 0 }}</p>
            <p class="text-xs text-slate-500 mt-1">覆盖车间</p>
          </div>
          <div class="bg-white border border-slate-200 rounded-2xl p-4">
            <div class="flex items-center justify-between mb-2">
              <span class="text-xs font-semibold text-slate-500 uppercase tracking-wide">设备类型数</span>
              <div class="w-8 h-8 rounded-lg bg-purple-50 flex items-center justify-center text-purple-500">
                <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 3v2m6-2v2M9 19v2m6-2v2M5 9H3m2 6H3m18-6h-2m2 6h-2M7 19h10a2 2 0 002-2V7a2 2 0 00-2-2H7a2 2 0 00-2 2v10a2 2 0 002 2zM9 9h6v6H9V9z"/></svg>
              </div>
            </div>
            <p class="text-2xl font-bold text-purple-500">{{ dashboard.device_type_count || 0 }}</p>
            <p class="text-xs text-slate-500 mt-1">设备类型</p>
          </div>
          <div class="bg-white border border-slate-200 rounded-2xl p-4">
            <div class="flex items-center justify-between mb-2">
              <span class="text-xs font-semibold text-slate-500 uppercase tracking-wide">已上传文档数</span>
              <div class="w-8 h-8 rounded-lg bg-orange-50 flex items-center justify-center text-orange-500">
                <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"/></svg>
              </div>
            </div>
            <p class="text-2xl font-bold text-orange-500">{{ dashboard.total_documents || 0 }}</p>
            <p class="text-xs text-slate-500 mt-1">已上传文档</p>
          </div>
        </div>

        <!-- KB卡片网格 -->
        <div class="mb-4">
          <h3 class="text-sm font-semibold text-slate-800 mb-3">知识库列表</h3>
        </div>
        <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-3">
          <!-- KB 卡片按完成率升序排列，匹配 HTML 设计：左侧图标+名称+元数据，右侧大号评分，底部进度条 -->
          <div v-for="kb in sortedKbTypes" :key="kb.kb_id || kb.id"
            class="bg-white rounded-xl border p-4 cursor-pointer transition-all hover:border-amber-500 hover:shadow-md flex flex-col"
            :class="{ 'border-red-200': (kb.progress || 0) < 30 && kb.kb_type !== 'history' }"
            :style="{ borderLeft: '3px solid ' + kbBorderColor(kb.kb_type) }"
            @click="openKB(kb)">
            <div class="flex items-start justify-between">
              <div class="flex-1">
                <div class="w-10 h-10 rounded-lg flex items-center justify-center text-lg mb-2.5" :style="{ background: kbIconBgColor(kb.kb_type), color: kbBorderColor(kb.kb_type) }">{{ kbIcon(kb.kb_type) }}</div>
                <div class="font-semibold text-[15px] text-slate-900 mb-0.5">{{ kb.name }}</div>
                <div class="text-[11px] text-slate-400 mb-2.5">{{ kbSubtitle(kb) }}</div>
                <div class="flex gap-4 text-xs text-slate-500 mb-2.5 flex-wrap">
                  <span v-if="kb.device_type_count">设备类型 <strong class="text-slate-900">{{ kb.device_type_count }}</strong></span>
                  <span v-if="kb.doc_count !== undefined">文档 <strong class="text-slate-900">{{ kb.doc_count }}</strong></span>
                  <span v-if="kb.kb_type==='compliance'">有效 <strong class="text-green-600">{{ kb.valid_count || 0 }}</strong></span>
                  <span v-if="kb.kb_type==='compliance'" class="text-red-500">过期 <strong class="text-red-500">{{ kb.expired_count || 0 }}</strong></span>
                </div>
              </div>
              <div class="text-center flex-shrink-0">
                <div class="text-[26px] font-bold" :style="{ color: kbBorderColor(kb.kb_type) }">{{ kb.score ?? '—' }}</div>
                <div class="text-[10px] text-slate-400">评分</div>
              </div>
            </div>
            <div class="mt-auto pt-2.5">
              <div class="flex justify-between items-center text-[11px] text-slate-500 mb-0.5"><span>完成率</span><span>{{ kb.progress ?? '—' }}%</span></div>
              <div class="h-[5px] bg-slate-100 rounded-sm overflow-hidden"><div class="h-full rounded-sm transition-all duration-500" :style="{ width: (kb.progress || 0) + '%', background: kbProgressColor(kb.kb_type) }"></div></div>
            </div>
          </div>
          <!-- 新建自定义知识库 -->
          <div class="bg-slate-50 rounded-xl border-2 border-dashed border-slate-200 flex flex-col items-center justify-center p-6 cursor-pointer min-h-[180px]" @click="showCreateDialog = true">
            <div class="text-2xl text-slate-400 mb-1">+</div>
            <div class="text-[13px] font-semibold text-slate-500">新建自定义知识库</div>
            <div class="text-[10px] text-slate-400 mt-1 text-center">自由创建类别、收集计划<br>独立评分</div>
          </div>

          <!-- 空状态（sortedKbTypes 为空时） -->
          <div v-if="sortedKbTypes.length === 0" class="col-span-full flex flex-col items-center justify-center py-20">
            <svg class="w-14 h-14 text-slate-300 mb-3" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M19 11H5m14 0a2 2 0 012 2v6a2 2 0 01-2 2H5a2 2 0 01-2-2v-6a2 2 0 012-2m14 0V9a2 2 0 00-2-2M5 11V9a2 2 0 012-2m0 0V5a2 2 0 012-2h6a2 2 0 012 2v2M7 7h10"/></svg>
            <p class="text-slate-500">暂无知识库</p>
            <p class="text-slate-400 text-xs mt-1">点击"创建知识库"开始使用</p>
          </div>
        </div>
      </template>

      <!-- 加载失败 -->
      <div v-else class="flex flex-col items-center justify-center py-20">
        <p class="text-slate-500">加载失败，请刷新重试</p>
      </div>
    </div>

    <!-- 创建弹窗 -->
    <teleport to="body">
      <div v-if="showCreateDialog" class="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm" @click.self="showCreateDialog = false">
        <div class="bg-white rounded-2xl shadow-xl w-full max-w-md mx-4 p-6 animate-[modalIn_.2s_ease]">
          <h3 class="text-base font-bold text-slate-800 mb-4">创建知识库</h3>

          <div class="space-y-3.5">
            <div>
              <label class="block text-[13px] font-medium text-slate-700 mb-1">名称 <span class="text-red-500">*</span></label>
              <input v-model="createForm.name" type="text"
                class="w-full px-3.5 py-2.5 border border-slate-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-amber-400/30 focus:border-amber-400 transition-shadow"
                placeholder="输入知识库名称" />
            </div>
            <div>
              <label class="block text-[13px] font-medium text-slate-700 mb-1">描述</label>
              <textarea v-model="createForm.description" rows="3"
                class="w-full px-3.5 py-2.5 border border-slate-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-amber-400/30 focus:border-amber-400 transition-shadow resize-none"
                placeholder="描述该知识库的用途"></textarea>
            </div>
            <div>
              <label class="block text-[13px] font-medium text-slate-700 mb-1">分块方法</label>
              <CustomSelect v-model="createForm.chunk_method" :options="chunkOptions" class="w-full" />
            </div>
          </div>

          <div class="flex justify-end gap-3 mt-5">
            <button class="btn-ghost" @click="showCreateDialog = false">取消</button>
            <button class="btn-primary" :disabled="!createForm.name.trim() || creating" @click="handleCreate">
              {{ creating ? '创建中...' : '创建' }}
            </button>
          </div>
        </div>
      </div>
    </teleport>

    <!-- 删除确认弹窗 -->
    <teleport to="body">
      <div v-if="deleteTarget" class="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm" @click.self="deleteTarget = null">
        <div class="bg-white rounded-2xl shadow-xl w-full max-w-sm mx-4 p-6 animate-[modalIn_.2s_ease] text-center">
          <div class="w-12 h-12 rounded-full bg-red-100 flex items-center justify-center mx-auto mb-3 text-red-500">
            <svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V9z"/><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 2v7h7"/></svg>
          </div>
          <h3 class="text-base font-bold text-slate-800 mb-1">确认删除</h3>
          <p class="text-slate-500 text-[13px] mb-5">确定要删除知识库"{{ deleteTarget.name }}"吗？此操作同时删除 RAGFlow 数据集，不可恢复。</p>
          <div class="flex justify-center gap-3">
            <button class="btn-ghost" @click="deleteTarget = null">取消</button>
            <button class="btn-primary !bg-red-500 hover:!bg-red-600" @click="handleDelete">确认删除</button>
          </div>
        </div>
      </div>
    </teleport>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useKnowledgeManagement } from '../../composables/knowledge_management/useKnowledgeManagement.js'
import { getDashboardBase, syncDeviceTypes, getKbDocumentsTree } from '../../api/knowledgeManagementClient.js'
import { formatDate } from '../../utils/format.js'
import CustomSelect from './components/CustomSelect.vue'
import HierarchyTree from './components/HierarchyTree.vue'

const router = useRouter()
const { createKnowledgeBase, deleteKnowledgeBase } = useKnowledgeManagement()

const dashboard = ref(null)
const loading = ref(true)
const syncing = ref(false)
const activeNode = ref('base')
const expandedWorkshops = ref({})
const expandedDevices = ref({})
const deviceDocuments = ref({})
const deviceDocsLoading = ref({})
const showCreateDialog = ref(false)
const creating = ref(false)
const deleteTarget = ref(null)

const chunkOptions = [
  { value: 'naive', label: '通用（naive）' },
  { value: 'manual', label: '手册（manual）' },
  { value: 'table', label: '表格（table）' },
  { value: 'qa', label: '问答（qa）' },
  { value: 'book', label: '书籍（book）' },
]

const createForm = ref({ name: '', description: '', chunk_method: 'naive' })

onMounted(async () => {
  try {
    dashboard.value = await getDashboardBase()
    // 展开嵌套的 data
    if (dashboard.value?.data) dashboard.value = dashboard.value.data
    // 确保 kb_types 为数组供 sortedKbTypes 使用
    if (dashboard.value?.kb_types && !Array.isArray(dashboard.value.kb_types)) {
      dashboard.value.kb_types = Object.values(dashboard.value.kb_types)
    }
  } catch (err) {
    console.error('获取看板数据失败:', err.message)
  } finally {
    loading.value = false
  }
})

// 按完成率升序排序的KB列表
const sortedKbTypes = computed(() => {
  if (!dashboard.value?.kb_types) return []
  const list = Array.isArray(dashboard.value.kb_types)
    ? dashboard.value.kb_types
    : Object.values(dashboard.value.kb_types)
  return list.filter(kb => kb).sort((a, b) => (a.progress || 0) - (b.progress || 0))
})

// 层级树导航
function handleNavigate(target, payload) {
  if (target === 'base') {
    activeNode.value = 'base'
  } else if (target === 'workshop') {
    activeNode.value = 'workshop-' + payload
  } else if (target === 'compliance') {
    const kb = sortedKbTypes.value.find(k => k.kb_type === 'compliance')
    if (kb) router.push(`/knowledge-management/${kb.kb_id}`)
  } else if (target === 'workshop-kb') {
    const kb = sortedKbTypes.value.find(k => k.kb_type === payload)
    if (kb) router.push(`/knowledge-management/${kb.kb_id}`)
  } else if (target === 'device') {
    // 点击设备节点：跳转到知识库详情页
    if (payload?.kbId) router.push(`/knowledge-management/${payload.kbId}`)
  } else if (target === 'document') {
    // 点击文档节点：跳转到知识库详情页（目前文档详情在 KB 详情页内查看）
    // 后续可以扩展为直接预览文档
  } else if (target === 'custom-kb') {
    router.push(`/knowledge-management/${payload}`)
  }
}

/** 车间展开/折叠 */
function toggleWorkshop(wsName) {
  const next = { ...expandedWorkshops.value }
  if (next[wsName]) {
    delete next[wsName]
  } else {
    next[wsName] = true
  }
  expandedWorkshops.value = next
}

/** 设备展开/折叠：展开时加载文档列表 */
async function toggleDevice(kbId) {
  if (!kbId) return
  const next = { ...expandedDevices.value }
  if (next[kbId]) {
    // 折叠
    delete next[kbId]
    expandedDevices.value = next
    return
  }
  // 展开：先设置状态，再异步加载文档
  next[kbId] = true
  expandedDevices.value = next

  if (!deviceDocuments.value[kbId]) {
    deviceDocsLoading.value = { ...deviceDocsLoading.value, [kbId]: true }
    try {
      const docs = await getKbDocumentsTree(kbId)
      deviceDocuments.value = { ...deviceDocuments.value, [kbId]: Array.isArray(docs) ? docs : [] }
    } catch (e) {
      console.error('加载设备文档失败:', e)
      deviceDocuments.value = { ...deviceDocuments.value, [kbId]: [] }
    } finally {
      deviceDocsLoading.value = { ...deviceDocsLoading.value, [kbId]: false }
    }
  }
}

function openKB(kb) {
  router.push(`/knowledge-management/${kb.kb_id || kb.id}`)
}

function kbIcon(kbType) {
  if (kbType === 'compliance') return '🛡️'
  if (kbType === 'device_doc') return '📐'
  if (kbType === 'sop_doc') return '📋'
  if (kbType === 'device') return '🏗️'
  return '📚'
}

function kbIconBgClass(kbType) {
  if (kbType === 'compliance') return 'bg-blue-50'
  if (kbType === 'device_doc') return 'bg-amber-50'
  if (kbType === 'sop_doc') return 'bg-emerald-50'
  if (kbType === 'device') return 'bg-amber-50'
  return 'bg-slate-100'
}

function scoreClass(s) {
  if (!s) return 'bg-slate-100 text-slate-400'
  if (s >= 85) return 'bg-emerald-50 text-emerald-600'
  if (s >= 60) return 'bg-amber-50 text-amber-600'
  return 'bg-red-50 text-red-600'
}

function progressBarClass(p) {
  if (!p) return 'bg-slate-300'
  if (p >= 85) return 'bg-emerald-500'
  if (p >= 60) return 'bg-amber-500'
  return 'bg-red-500'
}

function kbStatusLabel(status) {
  if (status === 'active') return '进行中'
  if (status === 'completed') return '已完成'
  return '待开始'
}
function kbBorderColor(kbType) {
  if (kbType === 'compliance') return '#3b82f6'
  if (kbType === 'device_doc') return '#b45309'
  if (kbType === 'sop_doc') return '#16a34a'
  if (kbType === 'history') return '#7c3aed'
  return '#0ea5e9'
}
function kbIconBgColor(kbType) {
  if (kbType === 'compliance') return '#eff6ff'
  if (kbType === 'device_doc') return '#fef3c7'
  if (kbType === 'sop_doc') return '#f0fdf4'
  if (kbType === 'history') return '#f5f3ff'
  return '#f0f9ff'
}
function kbSubtitle(kb) {
  if (kb.kb_type === 'compliance') return '基地级别 · 安环合规文档与证书'
  if (kb.kb_type === 'device_doc') return '车间级别 · 图纸/手册/参数/备件清单'
  if (kb.kb_type === 'sop_doc') return '车间级别 · 操作/点检/保养/异常/防错'
  if (kb.kb_type === 'history') return '车间级别 · 维修工单 + 精益改善任务'
  return '基地级别 · 自定义类别和收集项'
}
function kbProgressColor(kbType) {
  if (kbType === 'compliance') return '#3b82f6'
  if (kbType === 'device_doc') return '#b45309'
  if (kbType === 'sop_doc') return '#22c55e'
  if (kbType === 'history') return '#7c3aed'
  return '#0ea5e9'
}

async function handleCreate() {
  if (!createForm.value.name.trim()) return
  creating.value = true
  try {
    await createKnowledgeBase({ ...createForm.value })
    showCreateDialog.value = false
    createForm.value = { name: '', description: '', chunk_method: 'naive' }
    // 重新加载看板
    dashboard.value = await getDashboardBase()
    if (dashboard.value?.data) dashboard.value = dashboard.value.data
  } catch (err) {
    alert('创建失败: ' + err.message)
  } finally {
    creating.value = false
  }
}

function confirmDelete(kb) { deleteTarget.value = kb }

async function handleDelete() {
  if (!deleteTarget.value) return
  try {
    await deleteKnowledgeBase(deleteTarget.value.id)
    deleteTarget.value = null
    // 重新加载看板
    dashboard.value = await getDashboardBase()
    if (dashboard.value?.data) dashboard.value = dashboard.value.data
  } catch (err) {
    alert('删除失败: ' + err.message)
  }
}

async function handleSyncDeviceTypes() {
  syncing.value = true
  try {
    await syncDeviceTypes()
    alert('同步完成')
  } catch (err) {
    alert('同步失败: ' + err.message)
  } finally {
    syncing.value = false
  }
}

</script>

<style scoped>
.score-circle {
  @apply inline-flex items-center justify-center w-8 h-8 rounded-full text-sm font-bold;
}
</style>
