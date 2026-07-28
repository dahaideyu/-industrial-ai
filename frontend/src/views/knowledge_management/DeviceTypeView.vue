<template>
  <div class="h-full overflow-y-auto bg-slate-50">
    <div class="p-6 max-w-[96vw] mx-auto">

      <!-- Breadcrumb -->
      <div class="breadcrumb">
        <span class="node" @click="router.push('/knowledge-management')">🏭 {{ baseName }}</span>
        <span class="sep">›</span>
        <span class="node" @click="router.push('/knowledge-management/kb-type/' + kbType)">{{ kbTypeLabel }}</span>
        <span class="sep">›</span>
        <span class="node current">📁 {{ workshopName }}</span>
      </div>

      <!-- Stats -->
      <div class="stats-bar">
        <div class="stat-card"><div class="s-label">完成率</div><div class="s-value amber">{{ avgProgress }}%</div><div class="s-bar"><div class="s-bar-fill amber" :style="{width:avgProgress+'%'}"></div></div></div>
        <div class="stat-card"><div class="s-label">质量分</div><div class="s-value">{{ avgScore }}</div></div>
        <div class="stat-card"><div class="s-label">设备类型数</div><div class="s-value">{{ deviceList.length }}</div></div>
        <div class="stat-card"><div class="s-label">已上传文档</div><div class="s-value">{{ totalDocs }}</div></div>
      </div>

      <!-- Split -->
      <div class="split-layout">
        <HierarchyTree
          :base-name="baseName" :workshops="sidebarWorkshops" :custom-kbs="customKbs"
          :active-node="'workshop-' + workshopName" :show-workshops="true"
          :expanded="expandedWorkshops"
          :expandedDevices="expandedDevices"
          :deviceDocuments="deviceDocuments"
          :deviceDocsLoading="deviceDocsLoading"
          @nav="onTreeNav"
          @toggle-workshop="toggleWorkshop"
          @toggle-device="toggleDevice"
        />
        <div class="flex-1">
          <div class="section-title">{{ workshopName }} · 设备类型 <span class="badge">按完成率排序 ↑</span></div>

          <div v-if="loading" class="text-center py-12 text-slate-400">加载中...</div>

          <div v-else-if="deviceList.length === 0" class="text-center py-12 text-slate-400">
            该车间暂无设备类型数据。<br>
            <a class="mt-2 text-amber-600 underline cursor-pointer inline-block" @click="router.push('/knowledge-management')">返回首页同步设备类型</a>
          </div>

          <div v-else class="card-grid">
            <div v-for="dt in sortedDevices" :key="dt.id" class="relative">
              <div class="kb-card" :class="{ warning: dt.overall_progress < 30, disabled: !dt.enabled }"
                   @click="toDetail(dt)">
                <div v-if="!dt.enabled" class="kb-card-mask"></div>
                <div :class="['card-icon', dt.overall_progress >= 80 ? 'green' : dt.overall_progress >= 50 ? 'amber' : 'red']">🏗</div>
                <div class="card-name">{{ dt.device_type || dt.name }}</div>
                <div class="card-sub">
                  <template v-if="!dt.enabled">🚫 已禁用</template>
                  <template v-else-if="dt.status === 'disabled'">⚠ 已停用</template>
                  <template v-else-if="dt.overall_progress < 30">⚠ 进度严重落后</template>
                  <template v-else-if="dt.overall_progress >= 80">✅ 接近完成</template>
                  <template v-else>📋 正常推进</template>
                </div>
                <div class="card-meta">
                  <span>进度 <strong :style="{color: (dt.overall_progress||0) >= 60 ? '#16a34a' : (dt.overall_progress||0) >= 30 ? '#f59e0b' : '#ef4444'}">{{ dt.overall_progress || 0 }}%</strong></span>
                  <span>质量分 <strong>{{ dt.overall_score || 0 }}</strong></span>
                  <span>文档 <strong>{{ dt.doc_count || 0 }}</strong></span>
                </div>
                <!-- 设备说明进度 -->
                <div class="flex justify-between text-[11px] text-slate-500"><span>设备说明</span><span>{{ dt.doc_progress ?? '—' }}{{ dt.doc_progress != null ? '%' : '' }}</span></div>
                <div class="progress-bar"><div class="progress-fill" :class="(dt.doc_progress||0)>=60?'amber':(dt.doc_progress||0)>=30?'warn':'red'" :style="{width:(dt.doc_progress||0)+'%'}"></div></div>
                <!-- SOP进度 -->
                <div class="flex justify-between text-[11px] text-slate-500 mt-1"><span>SOP文档</span><span>{{ dt.sop_progress ?? '—' }}{{ dt.sop_progress != null ? '%' : '' }}</span></div>
                <div class="progress-bar"><div class="progress-fill" :class="(dt.sop_progress||0)>=60?'green':(dt.sop_progress||0)>=30?'warn':'red'" :style="{width:(dt.sop_progress||0)+'%'}"></div></div>
              </div>
              <!-- 启用/禁用滑块 -->
              <div class="absolute top-3 right-3 z-20">
                <KbTypeSwitch :model-value="dt.enabled !== false"
                  :loading="switchLoading[dt.id]"
                  @change="(v) => toggleDeviceKb(dt, v)" />
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, watch } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import HierarchyTree from './components/HierarchyTree.vue'
import KbTypeSwitch from './components/KbTypeSwitch.vue'
import { listKnowledgeBases, updateKnowledgeBase, getKbDocumentsTree } from '../../api/knowledgeManagementClient.js'
import { useKnowledgeManagement } from '../../composables/knowledge_management/useKnowledgeManagement.js'
import { useToast } from '../../composables/useToast'

const router = useRouter()
const route = useRoute()
const toast = useToast()
const { fetchDashboardBase, invalidateDashboardCache } = useKnowledgeManagement()

const baseName = ref('—')
const kbType = ref(route.params.type || 'device_doc')
const workshopName = ref(route.params.name || '')
const deviceList = ref([])
const loading = ref(true)
const allWorkshops = ref([])
const customKbs = ref([])
const switchLoading = ref({})
const expandedWorkshops = ref({ [workshopName.value]: true })
const expandedDevices = ref({})
const deviceDocuments = ref({})
const deviceDocsLoading = ref({})

const kbTypeLabel = computed(() => kbType.value === 'sop_doc' ? '📋 设备SOP知识库' : '📐 设备说明知识库')

const sortedDevices = computed(() =>
  [...deviceList.value].sort((a, b) => (a.overall_progress || 0) - (b.overall_progress || 0))
)

const sidebarWorkshops = computed(() =>
  allWorkshops.value.map(w => {
    const wsDevices = deviceList.value
      .filter(kb => kb.tags?.workshop === w.name)
      .map(kb => ({ name: kb.device_type || kb.name, kb_id: kb.id, progress: kb.overall_progress || 0 }))
    return { name: w.name, deviceCount: w.device_count || wsDevices.length, deviceTypes: wsDevices }
  })
)

const avgProgress = computed(() => {
  if (deviceList.value.length === 0) return 0
  return Math.round(deviceList.value.reduce((s, d) => s + (d.overall_progress || 0), 0) / deviceList.value.length)
})

const avgScore = computed(() => {
  if (deviceList.value.length === 0) return '0.0'
  return (deviceList.value.reduce((s, d) => s + (d.overall_score || 0), 0) / deviceList.value.length).toFixed(1)
})

const totalDocs = computed(() => deviceList.value.reduce((s, d) => s + (d.doc_count || 0), 0))

const toDetail = (dt) => {
  router.push(`/knowledge-management/${dt.id}`)
}

const onTreeNav = (target, payload) => {
  if (target === 'base') router.push('/knowledge-management')
  else if (target === 'compliance') router.push('/knowledge-management/compliance')
  else if (target === 'kb-type') router.push(`/knowledge-management/kb-type/${payload}`)
  else if (target === 'workshop') {
    if (payload !== workshopName.value) {
      router.push(`/knowledge-management/kb-type/${kbType.value}/workshop/${encodeURIComponent(payload)}`)
    }
  }
  else if (target === 'device') router.push(`/knowledge-management/${payload.kbId}`)
  else if (target === 'custom-kb') router.push(`/knowledge-management/${payload}`)
}

/** 车间展开/折叠 */
function toggleWorkshop(wsName) {
  const next = { ...expandedWorkshops.value }
  if (next[wsName]) { delete next[wsName] } else { next[wsName] = true }
  expandedWorkshops.value = next
}

/** 设备展开/折叠：展开时加载文档列表 */
async function toggleDevice(kbId) {
  if (!kbId) return
  const next = { ...expandedDevices.value }
  if (next[kbId]) {
    delete next[kbId]
    expandedDevices.value = next
    return
  }
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

const loadDevices = async () => {
  loading.value = true
  try {
    // 查询所有device类型的KB，按车间过滤
    const result = await listKnowledgeBases({ workshop: workshopName.value, kb_type: 'device' })
    const items = Array.isArray(result) ? result : (result?.items || [])
    deviceList.value = items
  } catch (e) {
    console.error('Device load error:', e)
    deviceList.value = []
  } finally {
    loading.value = false
  }
}

onMounted(async () => {
  await loadSidebar()
  await loadDevices()
})

// 监听车间名称变化（侧边栏点击其他车间时路由参数变化）
watch(() => route.params.name, async (newName, oldName) => {
  if (newName && newName !== oldName) {
    workshopName.value = newName
    await loadDevices()
  }
})

async function toggleDeviceKb(dt, enabled) {
  switchLoading.value[dt.id] = true
  try {
    await updateKnowledgeBase(dt.id, { enabled })
    dt.enabled = enabled
    invalidateDashboardCache()
    toast.success(`已${enabled ? '启用' : '禁用'}「${dt.device_type || dt.name}」`)
  } catch (e) { toast.error('操作失败: ' + e.message) }
  finally { switchLoading.value[dt.id] = false }
}

async function loadSidebar() {
  try {
    const dash = await fetchDashboardBase()
    baseName.value = dash?.base_name || '—'
    allWorkshops.value = (dash?.workshops || []).map(w => ({ name: w.name, device_count: w.device_count || 0 }))
    customKbs.value = dash?.custom_kbs || []
  } catch (e) { /* use defaults */ }
}
</script>

<style scoped>
.breadcrumb{display:flex;align-items:center;gap:6px;padding:10px 14px;background:#fff;border-radius:10px;border:1px solid #e2e8f0;margin-bottom:14px;font-size:13px;flex-wrap:wrap}
.breadcrumb .sep{color:#cbd5e1}
.breadcrumb .node{color:#64748b;padding:3px 10px;cursor:pointer;border-radius:4px;font-size:12px}
.breadcrumb .node:hover{background:#f1f5f9}
.breadcrumb .node.current{background:#fef3c7;color:#b45309;font-weight:600;border-radius:16px;padding:4px 12px}
.stats-bar{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin-bottom:16px}
.stat-card{background:#fff;border-radius:10px;padding:14px;border:1px solid #e2e8f0;text-align:center}
.stat-card .s-label{font-size:10px;color:#94a3b8;text-transform:uppercase;letter-spacing:.3px;margin-bottom:4px}
.stat-card .s-value{font-size:24px;font-weight:700;color:#0f172a}
.stat-card .s-value.amber{color:#b45309}
.stat-card .s-bar{height:5px;background:#e2e8f0;border-radius:3px;margin-top:6px}
.stat-card .s-bar-fill{height:100%;border-radius:3px;background:#b45309}
.split-layout{display:flex;gap:12px;min-height:380px}
.section-title{font-size:14px;font-weight:600;color:#0f172a;margin-bottom:12px;display:flex;align-items:center;gap:8px}
.section-title .badge{font-size:10px;background:#e2e8f0;padding:2px 8px;border-radius:10px;color:#64748b;font-weight:400}
.card-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(250px,1fr));gap:10px;align-content:start}
.kb-card{background:#fff;border-radius:10px;padding:16px;border:1px solid #e2e8f0;cursor:pointer;transition:all .15s;display:flex;flex-direction:column}
.kb-card:hover{border-color:#b45309;box-shadow:0 2px 12px rgba(180,83,9,0.08)}
.kb-card.warning{border-color:#fecaca}
.card-icon{width:40px;height:40px;border-radius:8px;display:flex;align-items:center;justify-content:center;font-size:18px;margin-bottom:10px}
.card-icon.green{background:#f0fdf4;color:#16a34a}.card-icon.amber{background:#fef3c7;color:#b45309}.card-icon.red{background:#fef2f2;color:#ef4444}
.card-name{font-weight:600;font-size:15px;color:#0f172a;margin-bottom:2px}
.card-sub{font-size:11px;color:#94a3b8;margin-bottom:10px}
.card-meta{display:flex;gap:16px;font-size:12px;color:#64748b;margin-bottom:8px}
.card-meta strong{font-size:14px;color:#0f172a}
.progress-bar{height:5px;background:#e2e8f0;border-radius:3px;overflow:hidden}
.progress-fill{height:100%;border-radius:3px;transition:width .3s}
.progress-fill.amber{background:#b45309}.progress-fill.green{background:#22c55e}.progress-fill.warn{background:#f59e0b}.progress-fill.red{background:#ef4444}
</style>
