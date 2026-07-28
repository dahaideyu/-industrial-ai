<template>
  <div class="h-full overflow-y-auto bg-slate-50">
    <div class="p-6 max-w-[96vw] mx-auto">

      <!-- Header -->
      <div class="flex items-center justify-between mb-3">
        <div class="flex items-center gap-2">
          <span class="bg-amber-50 text-amber-700 px-3.5 py-1.5 rounded-2xl font-semibold text-[13px]">🏭 {{ baseName }}</span>
          <span v-if="lastSync" class="text-[11px] text-slate-400">最后同步: {{ lastSync }}</span>
        </div>
        <div class="flex gap-1.5">
          <button class="btn-ghost text-[11px]" @click="onSyncDevices" :disabled="syncing">
            {{ syncing ? '⏳ 同步中...' : '🔄 同步设备类型' }}
          </button>
          <button class="btn-ghost text-[11px]" @click="router.push('/knowledge-management/admin/categories')">📋 管理文档类别</button>
        </div>
      </div>

      <!-- 搜索栏 -->
      <DocumentSearchBar
        v-model="searchQuery"
        v-model:mode="searchMode"
        :loading="searchLoading"
        @search="doSearch"
        @clear="clearSearch"
      />

      <!-- Stats Bar -->
      <div v-if="!searchActive" class="stats-bar">
        <div class="stat-card"><div class="s-label">总完成率</div><div class="s-value amber">{{ baseProgress }}%</div><div class="s-bar"><div class="s-bar-fill amber" :style="{width:baseProgress+'%'}"></div></div></div>
        <div class="stat-card"><div class="s-label">质量分</div><div class="s-value">{{ baseScore }}</div></div>
        <div class="stat-card"><div class="s-label">车间数</div><div class="s-value">{{ workshopCount }}</div></div>
        <div class="stat-card"><div class="s-label">设备类型数</div><div class="s-value">{{ deviceTypeCount }}</div></div>
        <div class="stat-card"><div class="s-label">已上传文档</div><div class="s-value">{{ totalDocs }}</div></div>
      </div>

      <!-- 搜索状态下显示结果 -->
      <div v-if="searchActive" class="split-layout" style="min-height:480px">
        <HierarchyTree
          :base-name="baseName" :base-progress="baseProgress"
          :workshops="workshops" :custom-kbs="customKbs"
          :expanded="expandedWorkshops"
          @toggle-workshop="toggleWorkshopLocal"
          active-node="base" @nav="onTreeNav"
        />
        <DocumentSearchResults
          :results="searchResults"
          :total="searchTotal"
          :page="searchPage"
          :loading="searchLoading"
          :mode="searchMode"
          :degraded="searchDegraded"
          @load-more="loadMoreResults"
          @preview="handleSearchPreview"
          @clear="clearSearch"
        />
      </div>

      <!-- 非搜索状态：Split: Tree + Cards -->
      <div v-else class="split-layout" style="min-height:480px">
        <HierarchyTree
          :base-name="baseName" :base-progress="baseProgress"
          :workshops="workshops" :custom-kbs="customKbs"
          :expanded="expandedWorkshops"
          @toggle-workshop="toggleWorkshopLocal"
          active-node="base" @nav="onTreeNav"
        />
        <div class="flex-1">
          <div class="section-title">知识库类型 <span class="badge">按完成率排序 ↑</span></div>

          <!-- Loading -->
          <div v-if="loading" class="text-center py-16 text-slate-400">加载中...</div>

          <!-- Cards -->
          <div v-else class="card-grid" style="grid-template-columns:repeat(auto-fill,minmax(260px,1fr))">
            <div v-for="kb in sortedKbCards" :key="kb.key" class="relative">
              <KbCard :name="kb.name" :sub="kb.sub" :icon="kb.icon" :icon-bg="kb.iconBg"
                :color="kb.color" :meta="kb.meta" :score="kb.score" :progress="kb.progress"
                :fill-class="kb.fillClass" :disabled="!kbTypeStates[kb.key]" @click="onKbCardClick(kb)"
              />
              <div class="absolute top-3 right-3 z-20">
                <KbTypeSwitch :model-value="kbTypeStates[kb.key]"
                  :loading="switchLoading[kb.key]"
                  @change="(v) => toggleKbType(kb.key)" />
              </div>
            </div>
          </div>

          <!-- Custom KBs -->
          <div class="section-title mt-4">自定义知识库 <span class="badge">基地级别 · 独立评分，不参与总评</span></div>
          <div class="card-grid" style="grid-template-columns:repeat(auto-fill,minmax(260px,1fr))">
            <KbCard v-for="kb in sortedCustomCards" :key="kb.id"
              :name="kb.name" sub="基地级别 · 自定义类别和收集项" icon="📋" icon-bg="#f0f9ff"
              color="#0ea5e9" :score="kb.overall_score || 0"
              :progress="kb.overall_progress || 0" fill-class="blue"
              :meta="[`文档 ${kb.doc_count || 0}`, `计划 ${kb.plan_count || 0}`]"
              @click="router.push('/knowledge-management/' + kb.id)"
            />
            <!-- 新建自定义KB -->
            <div class="bg-slate-50 rounded-xl border-2 border-dashed border-slate-200 flex flex-col items-center justify-center p-6 cursor-pointer min-h-[160px] hover:border-amber-400 transition-colors" @click="showCreateCustomKb = true">
              <div class="text-2xl text-slate-400 mb-1">+</div>
              <div class="text-[13px] font-semibold text-slate-500">新建自定义知识库</div>
              <div class="text-[10px] text-slate-400 mt-1 text-center">自由创建类别、收集计划<br>独立评分</div>
            </div>
          </div>
        </div>
      </div>

      <div class="tip mt-3">
        <strong>💡 排序与导航：</strong> KB 卡片按<strong>完成率从低到高</strong>排列。点击卡片进入对应详情，左侧树可快速跳转。
      </div>
    </div>

    <!-- 切片/文档预览弹窗 -->
    <ChunkViewer
      v-if="chunkViewDoc"
      :doc="{ id: chunkViewDoc.ragDocId, name: chunkViewDoc.docName }"
      :dataset-id="chunkViewDoc.ragDatasetId"
      :pdf-preview-url="chunkViewDoc.previewUrl"
      @close="chunkViewDoc = null"
    />

    <!-- 新建自定义KB弹窗 -->
    <div v-if="showCreateCustomKb" class="modal-bg" @click.self="showCreateCustomKb = false">
      <div class="modal-box">
        <h3 class="text-base font-semibold mb-4">新建自定义知识库</h3>
        <div class="mb-3">
          <label class="block text-xs text-slate-500 mb-1">知识库名称</label>
          <input v-model="newCustomKbName" class="w-full border border-slate-200 rounded-lg px-3 py-2 text-sm" placeholder="如：基地管理办法" @keyup.enter="createCustomKb" />
        </div>
        <div class="flex justify-end gap-2">
          <button class="px-4 py-2 text-sm text-slate-500 border border-slate-200 rounded-lg" @click="showCreateCustomKb = false">取消</button>
          <button class="px-4 py-2 text-sm bg-amber-600 text-white rounded-lg disabled:opacity-50" @click="createCustomKb" :disabled="!newCustomKbName.trim()">创建</button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import HierarchyTree from './components/HierarchyTree.vue'
import KbCard from './components/KbCard.vue'
import KbTypeSwitch from './components/KbTypeSwitch.vue'
import DocumentSearchBar from './components/DocumentSearchBar.vue'
import DocumentSearchResults from './components/DocumentSearchResults.vue'
import ChunkViewer from './components/ChunkViewer.vue'
import { syncDeviceTypes, listKnowledgeBases, createCustomKnowledgeBase, getKbTypeStates, setKbTypeState, searchDocuments, getRAGDocPreviewUrl } from '../../api/knowledgeManagementClient.js'
import { useKnowledgeManagement } from '../../composables/knowledge_management/useKnowledgeManagement.js'
import { useToast } from '../../composables/useToast'

const router = useRouter()
const toast = useToast()
const { fetchDashboardBase, invalidateDashboardCache } = useKnowledgeManagement()

// State
const loading = ref(true)
const baseName = ref('—')
const baseProgress = ref(0)
const baseScore = ref(0)
const workshopCount = ref(0)
const deviceTypeCount = ref(0)
const totalDocs = ref(0)
const lastSync = ref('')

// KB 类型启用/禁用状态
const kbTypeStates = ref({ compliance: true, device_doc: true, sop_doc: true, history: true })
const switchLoading = ref({})
const syncing = ref(false)
const kbTypes = ref({})
const workshops = ref([])
const customKbs = ref([])

// 侧边栏展开状态——从 localStorage 加载，跨页面保留
const STORAGE_KEY = 'km_sidebar_expanded'
const expandedWorkshops = ref({})
try {
  const saved = localStorage.getItem(STORAGE_KEY)
  if (saved) expandedWorkshops.value = JSON.parse(saved)
} catch (e) {}
function toggleWorkshopLocal(name) {
  expandedWorkshops.value[name] = !expandedWorkshops.value[name]
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(expandedWorkshops.value))
  } catch (e) {}
}

// 文档搜索
const searchQuery = ref('')
const searchMode = ref('keyword')
const searchResults = ref([])
const searchTotal = ref(0)
const searchPage = ref(1)
const searchLoading = ref(false)
const searchDegraded = ref(false)
const searchActive = computed(() => searchQuery.value.trim().length >= 2)
const chunkViewDoc = ref(null) // ChunkViewer 预览文档

// Modal
const showCreateCustomKb = ref(false)
const newCustomKbName = ref('')

// KB card definitions for the 4 standard types
const kbCardDefs = {
  compliance: { name: '合规性知识库', sub: '基地级别 · 安环合规文档与证书', icon: '🛡️', iconBg: '#eff6ff', color: '#3b82f6', fillClass: 'blue', route: 'compliance', meta: ['文档 0', '计划 0'] },
  device_doc: { name: '设备说明知识库', sub: '车间级别 · 图纸/手册/参数/备件清单', icon: '📐', iconBg: '#fef3c7', color: '#b45309', fillClass: 'amber', route: 'device-doc', meta: ['设备类型 0', '文档 0', '计划 0'] },
  sop_doc: { name: '设备SOP知识库', sub: '车间级别 · 操作/点检/保养/异常/防错', icon: '📋', iconBg: '#f0fdf4', color: '#16a34a', fillClass: 'green', route: 'sop-doc', meta: ['设备类型 0', '文档 0', '计划 0'] },
}

const sortedKbCards = computed(() => {
  const cards = []
  // Always include history
  cards.push({
    key: 'history', name: '历史沉淀知识库', sub: '车间级别 · 维修工单+精益改善任务',
    icon: '📚', iconBg: '#f5f3ff', color: '#7c3aed', progress: '—', score: '—',
    meta: ['延后实现'], fillClass: 'purple', route: null,
  })
  // 所有预置 KB 类型都要展示（即使禁用时无统计数据，也显示灰色禁用卡片）
  for (const [type, def] of Object.entries(kbCardDefs)) {
    const data = kbTypes.value[type] || {}
    const docCount = data.doc_count || 0
    const planCount = data.plan_count || 0
    cards.push({
      key: type, ...def,
      progress: data.progress ?? 0,
      score: data.score ?? 0,
      meta: data.device_type_count !== undefined
        ? [`设备类型 ${data.device_type_count || 0}`, `文档 ${docCount}`, `计划 ${planCount}`]
        : def.meta || [],
    })
  }
  // Sort: 启用的按进度升序在前，禁用的统一排到末尾
  return cards.sort((a, b) => {
    const aDisabled = !kbTypeStates.value[a.key]
    const bDisabled = !kbTypeStates.value[b.key]
    if (aDisabled !== bDisabled) return aDisabled ? 1 : -1
    if (typeof a.progress !== 'number') return -1
    if (typeof b.progress !== 'number') return 1
    return a.progress - b.progress
  })
})

const sortedCustomCards = computed(() =>
  [...customKbs.value].sort((a, b) => (a.overall_progress || 0) - (b.overall_progress || 0))
)

// Navigation
const onKbCardClick = (kb) => {
  if (!kb.route) return
  if (kb.route === 'compliance') router.push('/knowledge-management/compliance')
  else if (kb.route === 'device-doc') router.push('/knowledge-management/kb-type/device_doc')
  else if (kb.route === 'sop-doc') router.push('/knowledge-management/kb-type/sop_doc')
}

const onTreeNav = (target, payload) => {
  if (target === 'base') return
  if (target === 'compliance') router.push('/knowledge-management/compliance')
  else if (target === 'kb-type') router.push(`/knowledge-management/kb-type/${payload}`)
  else if (target === 'workshop') router.push(`/knowledge-management/kb-type/device_doc/workshop/${encodeURIComponent(payload)}`)
  else if (target === 'device') router.push(`/knowledge-management/${payload.kbId}`)
  else if (target === 'custom-kb') router.push(`/knowledge-management/${payload}`)
}

// Actions
const onSyncDevices = async () => {
  syncing.value = true
  try {
    await syncDeviceTypes()
    invalidateDashboardCache()
    await loadData()
  } catch (e) { alert('同步失败: ' + e.message) }
  finally { syncing.value = false }
}

const createCustomKb = async () => {
  const name = newCustomKbName.value.trim()
  if (!name) return
  try {
    const newKb = await createCustomKnowledgeBase({ name, tags: { base: baseName.value } })
    showCreateCustomKb.value = false
    newCustomKbName.value = ''
    // 跳转到新创建的KB详情页（与设备KB体验一致）
    const kbId = newKb?.id || newKb?.kb_id
    if (kbId) {
      router.push(`/knowledge-management/${kbId}`)
    } else {
      await loadCustomKbs()
    }
  } catch (e) { alert('创建失败: ' + e.message) }
}

const loadData = async () => {
  loading.value = true
  try {
    const dash = await fetchDashboardBase()
    if (dash) {
      baseName.value = dash.base_name || '—'
      baseScore.value = dash.base_score ?? 0
      workshopCount.value = dash.workshop_count ?? 0
      deviceTypeCount.value = dash.device_type_count ?? 0
      totalDocs.value = dash.total_docs ?? 0
      kbTypes.value = dash.kb_types || {}
      workshops.value = (dash.workshops || []).map(w => ({
        name: w.name,
        deviceCount: w.device_count || 0,
        deviceTypes: w.device_types || [],
      }))
      baseProgress.value = dash.base_progress ?? 0
      lastSync.value = dash.last_sync || ''
      if (dash.kb_type_states) kbTypeStates.value = { ...kbTypeStates.value, ...dash.kb_type_states }
    }
  } catch (e) {
    console.error('Dashboard load error:', e)
    // Fallback defaults
    baseName.value = '—'
  } finally {
    loading.value = false
  }
}

const loadCustomKbs = async () => {
  try {
    const result = await listKnowledgeBases({ kb_type: 'custom_base' })
    customKbs.value = Array.isArray(result) ? result : (result?.items || [])
  } catch (e) {
    console.error('Custom KBs load error:', e)
  }
}

async function loadKbTypeStates() {
  try {
    const resp = await getKbTypeStates()
    if (resp?.data) kbTypeStates.value = { ...kbTypeStates.value, ...resp.data }
  } catch (e) { console.error('加载 KB 类型状态失败:', e) }
}

async function toggleKbType(kbType) {
  const newEnabled = !kbTypeStates.value[kbType]
  switchLoading.value[kbType] = true
  try {
    await setKbTypeState(kbType, newEnabled)
    kbTypeStates.value[kbType] = newEnabled
    invalidateDashboardCache()
    await loadData()
    toast.success(`已${newEnabled ? '启用' : '禁用'}「${kbTypeLabel(kbType)}」`)
  } catch (e) { toast.error('操作失败: ' + e.message) }
  finally { switchLoading.value[kbType] = false }
}

function kbTypeLabel(kbType) {
  return { compliance: '合规性', device_doc: '设备说明', sop_doc: '设备SOP', history: '历史沉淀' }[kbType] || kbType
}

// 文档搜索
async function doSearch(query, mode, page = 1) {
  if (!query || query.length < 2) return
  searchLoading.value = true
  searchDegraded.value = false
  try {
    const result = await searchDocuments({ q: query, mode, page, page_size: 20 })
    // 解包可能的 {data: ...} 包装
    const data = result?.data || result
    if (page === 1) {
      searchResults.value = data?.items || []
    } else {
      searchResults.value = [...searchResults.value, ...(data?.items || [])]
    }
    searchTotal.value = data?.total || 0
    searchPage.value = page
    searchQuery.value = query
    searchMode.value = data?.mode || mode
    searchDegraded.value = !!data?.degraded
  } catch (e) {
    console.error('文档搜索失败:', e)
    if (page === 1) {
      searchResults.value = []
      searchTotal.value = 0
    }
  } finally {
    searchLoading.value = false
  }
}

async function loadMoreResults() {
  const nextPage = searchPage.value + 1
  await doSearch(searchQuery.value, searchMode.value, nextPage)
}

function clearSearch() {
  searchQuery.value = ''
  searchResults.value = []
  searchTotal.value = 0
  searchPage.value = 1
  searchDegraded.value = false
}

async function handleSearchPreview(item) {
  if (!item.rag_dataset_id) return

  // 获取 PDF 预览 URL（通过 RAGFlow 文档 ID）
  const previewDocId = item.rag_document_id || item.version_id
  let previewUrl = ''
  if (previewDocId) {
    try {
      const resp = await fetch(getRAGDocPreviewUrl(previewDocId), {
        headers: { Authorization: 'Bearer ' + (localStorage.getItem('auth_token') || '') }
      })
      const data = await resp.json()
      previewUrl = data?.data?.preview_url || data?.preview_url || ''
    } catch {}
  }

  chunkViewDoc.value = {
    ragDocId: previewDocId,
    ragDatasetId: item.rag_dataset_id,
    docName: item.display_name || item.original_filename || '文档',
    previewUrl,
  }
}

onMounted(async () => {
  await loadKbTypeStates()
  await loadData()
  await loadCustomKbs()
})
</script>

<style scoped>
/* Tab (legacy — keep minimal styling but no tabs are rendered since this is single-page) */
.stats-bar{display:grid;grid-template-columns:repeat(5,1fr);gap:10px;margin-bottom:16px}
.stat-card{background:#fff;border-radius:10px;padding:14px;border:1px solid #e2e8f0;text-align:center}
.stat-card .s-label{font-size:10px;color:#94a3b8;text-transform:uppercase;letter-spacing:.3px;margin-bottom:4px}
.stat-card .s-value{font-size:24px;font-weight:700;color:#0f172a}
.stat-card .s-value.amber{color:#b45309}.stat-card .s-value.green{color:#16a34a}.stat-card .s-value.red{color:#ef4444}
.stat-card .s-bar{height:5px;background:#e2e8f0;border-radius:3px;margin-top:6px}
.stat-card .s-bar-fill{height:100%;border-radius:3px}
.stat-card .s-bar-fill.amber{background:#b45309}.stat-card .s-bar-fill.green{background:#22c55e}
.stat-card .s-bar-fill.warn{background:#f59e0b}.stat-card .s-bar-fill.red{background:#ef4444}.stat-card .s-bar-fill.blue{background:#3b82f6}
.section-title{font-size:14px;font-weight:600;color:#0f172a;margin-bottom:12px;display:flex;align-items:center;gap:8px}
.section-title .badge{font-size:10px;background:#e2e8f0;padding:2px 8px;border-radius:10px;color:#64748b;font-weight:400}
.split-layout{display:flex;gap:12px}
.card-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(250px,1fr));gap:10px;align-content:start}
.tip{background:#eff6ff;border:1px solid #bfdbfe;border-radius:8px;padding:10px 14px;font-size:12px;color:#1e40af;margin-top:12px;line-height:1.6}
.btn-ghost{font-size:11px;padding:5px 10px;border:1px solid #e2e8f0;border-radius:6px;color:#64748b;cursor:pointer;background:transparent}
.btn-ghost:hover{background:#f1f5f9}
.modal-bg{position:fixed;inset:0;background:rgba(0,0,0,.4);display:flex;align-items:center;justify-content:center;z-index:99;backdrop-filter:blur(2px)}
.modal-box{background:#fff;border-radius:12px;padding:24px;width:480px;max-width:90vw;box-shadow:0 20px 40px rgba(0,0,0,.15)}
@media(max-width:768px){.stats-bar{grid-template-columns:repeat(2,1fr)}.split-layout{flex-direction:column}.card-grid{grid-template-columns:1fr}}
</style>
