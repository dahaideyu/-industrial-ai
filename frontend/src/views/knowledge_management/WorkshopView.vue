<template>
  <div class="h-full overflow-y-auto bg-slate-50">
    <div class="p-6 max-w-[96vw] mx-auto">

      <!-- Breadcrumb -->
      <div class="breadcrumb">
        <span class="node" @click="router.push('/knowledge-management')">🏭 {{ baseName }}</span>
        <span class="sep">›</span>
        <span class="node current">{{ currentLabel }}</span>
      </div>

      <!-- Stats -->
      <div class="stats-bar">
        <div class="stat-card"><div class="s-label">完成率</div><div class="s-value amber">{{ avgProgress }}%</div><div class="s-bar"><div class="s-bar-fill amber" :style="{width:avgProgress+'%'}"></div></div></div>
        <div class="stat-card"><div class="s-label">质量分</div><div class="s-value">{{ avgScore }}</div></div>
        <div class="stat-card"><div class="s-label">涉及车间</div><div class="s-value">{{ workshopCount }}</div></div>
        <div class="stat-card"><div class="s-label">设备类型数</div><div class="s-value">{{ totalDeviceTypes }}</div></div>
        <div class="stat-card"><div class="s-label">已上传文档</div><div class="s-value">{{ totalDocs }}</div></div>
      </div>

      <!-- Split -->
      <div class="split-layout">
        <HierarchyTree
          :base-name="baseName" :workshops="sidebarWorkshops" :custom-kbs="customKbs"
          :active-node="'kb-' + (kbType === 'sop_doc' ? 'sop-doc' : 'device-doc')"
          @nav="onTreeNav"
        />
        <div class="flex-1">
          <div class="section-title">各车间 · {{ currentLabel }}完成情况 <span class="badge">按完成率排序 ↑</span></div>

          <div v-if="loading" class="text-center py-12 text-slate-400">加载中...</div>

          <div v-else-if="sortedWorkshops.length === 0" class="text-center py-12 text-slate-400">
            暂无车间数据。请先<a class="text-amber-600 underline cursor-pointer" @click="router.push('/knowledge-management')">返回首页</a>同步设备类型。
          </div>

          <div v-for="ws in sortedWorkshops" :key="ws.name" class="workshop-row" @click="toDeviceView(ws.name)">
            <div class="ws-icon" :style="{background:ws.progress>=60?'#dcfce7':ws.progress>=40?'#fef3c7':'#fef2f2'}">📁</div>
            <div class="ws-info">
              <div class="ws-name">{{ ws.name }}</div>
              <div class="ws-sub">{{ ws.kb_count }}台设备类型</div>
            </div>
            <div class="ws-stats">
              <div><div class="ws-stat-val" :style="{color:ws.progress>=60?'#16a34a':ws.progress>=40?'#f59e0b':'#ef4444'}">{{ ws.progress }}%</div><div class="ws-stat-lbl">完成率</div></div>
              <div><div class="ws-stat-val">{{ ws.score }}</div><div class="ws-stat-lbl">质量分</div></div>
              <div><div class="ws-stat-val">{{ ws.kb_count }}</div><div class="ws-stat-lbl">设备类型</div></div>
              <div><div class="ws-stat-val">{{ ws.docs || '—' }}</div><div class="ws-stat-lbl">文档</div></div>
            </div>
            <div class="s-bar" style="width:120px"><div class="s-bar-fill" :class="ws.progress>=60?'amber':ws.progress>=40?'warn':'red'" :style="{width:ws.progress+'%'}"></div></div>
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
import { getDashboardWorkshop, listKnowledgeBases } from '../../api/knowledgeManagementClient.js'
import { useKnowledgeManagement } from '../../composables/knowledge_management/useKnowledgeManagement.js'

const router = useRouter()
const route = useRoute()
const { fetchDashboardBase } = useKnowledgeManagement()

const baseName = ref('—')
const kbType = ref(route.params.type || 'device_doc')
const workshopList = ref([])
const loading = ref(true)
const customKbs = ref([])

// 侧边栏workshop数据（含设备类型）
const deviceKbs = ref([])
const sidebarWorkshops = computed(() =>
  [...workshopList.value]
    .sort((a, b) => a.name.localeCompare(b.name, 'zh'))
    .map(ws => {
    const wsDevices = deviceKbs.value
      .filter(kb => kb.tags?.workshop === ws.name)
      .map(kb => ({ name: kb.device_type || kb.name, kb_id: kb.id, progress: kb.overall_progress || 0 }))
    return { name: ws.name, deviceCount: ws.kb_count, deviceTypes: wsDevices }
  })
)

const currentLabel = computed(() => kbType.value === 'sop_doc' ? '📋 设备SOP知识库' : '📐 设备说明知识库')

const sortedWorkshops = computed(() => [...workshopList.value].sort((a, b) => (a.progress || 0) - (b.progress || 0)))

const workshopCount = computed(() => workshopList.value.length)
const totalDeviceTypes = computed(() => workshopList.value.reduce((s, w) => s + (w.kb_count || 0), 0))
const totalDocs = computed(() => workshopList.value.reduce((s, w) => s + (w.docs || 0), 0))

const avgProgress = computed(() => {
  if (workshopList.value.length === 0) return 0
  return Math.round(workshopList.value.reduce((s, w) => s + (w.progress || 0), 0) / workshopList.value.length)
})

const avgScore = computed(() => {
  if (workshopList.value.length === 0) return '0.0'
  return (workshopList.value.reduce((s, w) => s + (w.score || 0), 0) / workshopList.value.length).toFixed(1)
})

const switchKbType = (type) => {
  kbType.value = type
  router.replace(`/knowledge-management/kb-type/${type}`)
  loadWorkshops()
}

const toDeviceView = (wsName) => {
  router.push(`/knowledge-management/kb-type/${kbType.value}/workshop/${encodeURIComponent(wsName)}`)
}

const onTreeNav = (target, payload) => {
  if (target === 'base') router.push('/knowledge-management')
  else if (target === 'compliance') router.push('/knowledge-management/compliance')
  else if (target === 'kb-type') { kbType.value = payload; loadWorkshops() }
  else if (target === 'workshop') toDeviceView(payload)
  else if (target === 'device') router.push(`/knowledge-management/${payload.kbId}`)
  else if (target === 'custom-kb') router.push(`/knowledge-management/${payload}`)
}

const loadWorkshops = async () => {
  loading.value = true
  try {
    const data = await getDashboardWorkshop(kbType.value)
    workshopList.value = data?.workshops || []
  } catch (e) {
    console.error('Workshop load error:', e)
    workshopList.value = []
  } finally {
    loading.value = false
  }
}

onMounted(async () => {
  try {
    const dash = await fetchDashboardBase()
    baseName.value = dash?.base_name || '—'
    customKbs.value = dash?.custom_kbs || []
  } catch (e) { /* use defaults */ }
  // 加载所有device KBs供侧边栏使用
  try {
    const devKbs = await listKnowledgeBases({ kb_type: 'device' })
    deviceKbs.value = Array.isArray(devKbs) ? devKbs : []
  } catch (e) { /* ignore */ }
  await loadWorkshops()
})

watch(() => route.params.type, (newType) => {
  if (newType && newType !== kbType.value) {
    kbType.value = newType
    loadWorkshops()
  }
})
</script>

<style scoped>
.breadcrumb{display:flex;align-items:center;gap:6px;padding:10px 14px;background:#fff;border-radius:10px;border:1px solid #e2e8f0;margin-bottom:14px;font-size:13px;flex-wrap:wrap}
.breadcrumb .sep{color:#cbd5e1}
.breadcrumb .node{color:#64748b;padding:3px 10px;cursor:pointer;border-radius:4px;font-size:12px}
.breadcrumb .node:hover{background:#f1f5f9}
.breadcrumb .node.current{background:#fef3c7;color:#b45309;font-weight:600;border-radius:16px;padding:4px 12px}
.stats-bar{display:grid;grid-template-columns:repeat(5,1fr);gap:10px;margin-bottom:16px}
.stat-card{background:#fff;border-radius:10px;padding:14px;border:1px solid #e2e8f0;text-align:center}
.stat-card .s-label{font-size:10px;color:#94a3b8;text-transform:uppercase;letter-spacing:.3px;margin-bottom:4px}
.stat-card .s-value{font-size:24px;font-weight:700;color:#0f172a}
.stat-card .s-value.amber{color:#b45309}
.stat-card .s-bar{height:5px;background:#e2e8f0;border-radius:3px;margin-top:6px}
.stat-card .s-bar-fill{height:100%;border-radius:3px;background:#b45309}
.split-layout{display:flex;gap:12px;min-height:340px}
.section-title{font-size:14px;font-weight:600;color:#0f172a;margin-bottom:12px;display:flex;align-items:center;gap:8px}
.section-title .badge{font-size:10px;background:#e2e8f0;padding:2px 8px;border-radius:10px;color:#64748b;font-weight:400}
.workshop-row{background:#fff;border-radius:10px;padding:12px 16px;border:1px solid #e2e8f0;margin-bottom:6px;cursor:pointer;display:flex;align-items:center;gap:14px;transition:all .1s}
.workshop-row:hover{border-color:#b45309}
.workshop-row .ws-icon{width:36px;height:36px;border-radius:8px;display:flex;align-items:center;justify-content:center;font-size:16px;flex-shrink:0}
.workshop-row .ws-info{flex:1}
.workshop-row .ws-name{font-weight:600;font-size:13px}
.workshop-row .ws-sub{font-size:11px;color:#94a3b8}
.workshop-row .ws-stats{display:flex;gap:24px;text-align:center;font-size:12px}
.workshop-row .ws-stat-val{font-weight:700;font-size:15px;color:#0f172a}
.workshop-row .ws-stat-lbl{font-size:10px;color:#94a3b8}
.s-bar{height:5px;background:#e2e8f0;border-radius:3px;flex-shrink:0}
.s-bar-fill{height:100%;border-radius:3px}
.s-bar-fill.amber{background:#b45309}.s-bar-fill.warn{background:#f59e0b}.s-bar-fill.red{background:#ef4444}
</style>
