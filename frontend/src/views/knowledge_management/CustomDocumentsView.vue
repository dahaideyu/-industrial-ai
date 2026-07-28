<template>
  <div class="h-full overflow-y-auto bg-slate-50">
    <div class="p-6 max-w-[96vw] mx-auto">

      <!-- Breadcrumb -->
      <div class="breadcrumb">
        <span class="node" @click="router.push('/knowledge-management')">🏭 知识库管理</span>
        <span class="sep">›</span>
        <span class="node current">📝 自定义文档</span>
      </div>

      <!-- KB selector -->
      <div v-if="customKbs.length === 0 && !loading" class="text-center py-12 text-slate-400">
        暂无自定义知识库。<br>
        <a class="text-amber-600 underline cursor-pointer" @click="router.push('/knowledge-management')">返回首页新建</a>
      </div>

      <template v-else>
        <!-- KB selector tabs -->
        <div class="flex gap-2 mb-4 flex-wrap">
          <span v-for="kb in customKbs" :key="kb.id"
                :class="selectedKbId === kb.id ? 'bg-sky-50 text-sky-700 font-semibold' : 'text-slate-500 cursor-pointer bg-white border border-slate-200'"
                class="px-3 py-1.5 rounded-lg text-xs transition-colors hover:border-sky-300"
                @click="selectKb(kb.id)">
            📋 {{ kb.name }}
          </span>
        </div>

        <!-- Stats for selected KB -->
        <div v-if="selectedKb" class="stats-bar" style="grid-template-columns:repeat(4,1fr)">
          <div class="stat-card"><div class="s-label">收集进度</div><div class="s-value" style="color:#0ea5e9">{{ selectedKb.overall_progress || 0 }}%</div></div>
          <div class="stat-card"><div class="s-label">质量分</div><div class="s-value">{{ selectedKb.overall_score || 0 }}</div></div>
          <div class="stat-card"><div class="s-label">收集计划</div><div class="s-value">{{ plans.length }}</div></div>
          <div class="stat-card"><div class="s-label">收集项</div><div class="s-value">{{ totalItems }}</div></div>
        </div>

        <!-- Tip -->
        <div class="tip mb-3">
          <strong>📝 自定义文档说明：</strong> 自动创建项不可删除只能标 N/A。手动创建项可自由增删。收集项<strong>必须</strong>关联到收集计划。
        </div>

        <!-- Header actions -->
        <div class="flex items-center justify-between mb-3">
          <div class="section-title mb-0">自定义收集计划与收集项</div>
          <button class="tag blue cursor-pointer px-3.5 py-1.5 text-xs" @click="showCreatePlan = true">+ 新建收集计划</button>
        </div>

        <!-- Plans list -->
        <div v-if="loading" class="text-center py-8 text-slate-400">加载中...</div>

        <div v-for="plan in plans" :key="plan.id" class="bg-white rounded-xl border border-slate-200 mb-2.5 overflow-hidden">
          <!-- Plan header -->
          <div class="flex items-center justify-between px-4 py-3 bg-slate-50 border-b border-slate-200 cursor-pointer" @click="togglePlan(plan.id)">
            <div class="flex items-center gap-2">
              <span class="text-sm">{{ expandedPlanId === plan.id ? '▾' : '▸' }}</span>
              <span class="font-semibold text-[13px]">{{ plan.name }}</span>
              <span class="tag amber" v-if="plan.is_custom || plan.plan_type === 'custom'">自定义计划</span>
              <span class="tag gray" v-else>自动计划</span>
              <span class="text-[11px] text-slate-400">进度 {{ plan.progress || 0 }}% · 得分 {{ plan.score || '—' }}</span>
            </div>
            <div class="flex gap-1.5" @click.stop>
              <button v-if="plan.is_custom || plan.plan_type === 'custom'" class="text-[11px] text-red-500 cursor-pointer hover:underline" @click="onDeletePlan(plan.id)">🗑️ 删除</button>
              <button class="text-[11px] text-amber-600 cursor-pointer hover:underline" @click="openCreateItem(plan)">+ 收集项</button>
            </div>
          </div>

          <!-- Plan items (when expanded) -->
          <div v-if="expandedPlanId === plan.id" class="px-4 py-2">
            <div v-for="item in getPlanItems(plan)" :key="item.id" class="flex items-center gap-3.5 py-2 border-b border-slate-50 last:border-0">
              <div class="w-10 h-10 rounded-lg bg-slate-50 flex items-center justify-center text-base">📄</div>
              <div class="flex-1">
                <div class="font-semibold text-[13px]">{{ item.name }}</div>
                <div class="text-[11px] text-slate-400 mt-0.5">{{ item.description || '无描述' }}</div>
                <div class="mt-0.5">
                  <span :class="['tag', item.overall_status === 'completed' ? 'green' : 'amber']">
                    {{ item.overall_status === 'completed' ? '已完成' : '待完善' }}
                  </span>
                  <span :class="['tag', item.is_custom ? 'blue' : 'gray']">
                    {{ item.is_custom ? '自定义' : '自动生成' }}
                  </span>
                  <span class="text-[11px] text-slate-400" v-if="item.overall_score"> 得分: {{ item.overall_score }}</span>
                </div>
              </div>
              <div class="flex gap-1.5">
                <button v-if="item.is_custom" class="text-[11px] text-red-500 cursor-pointer hover:underline" @click="onDeleteItem(item.id)">🗑️</button>
                <button v-else class="text-[11px] text-amber-500 cursor-pointer hover:underline" @click="onMarkNA(item)">🚫 不适用</button>
              </div>
            </div>
            <div v-if="getPlanItems(plan).length === 0" class="text-center py-4 text-xs text-slate-400">
              暂无收集项。点击「+ 收集项」创建。
            </div>
          </div>
        </div>
      </template>

      <!-- Create Plan Modal -->
      <div v-if="showCreatePlan" class="modal-bg" @click.self="showCreatePlan = false">
        <div class="modal-box">
          <h3 class="text-base font-semibold mb-4">新建收集计划</h3>
          <div class="mb-3">
            <label class="block text-xs text-slate-500 mb-1">计划名称</label>
            <input v-model="newPlanName" class="w-full border border-slate-200 rounded-lg px-3 py-2 text-sm" placeholder="如：临时审核文档收集" />
          </div>
          <div class="flex justify-end gap-2">
            <button class="px-4 py-2 text-sm text-slate-500 border border-slate-200 rounded-lg" @click="showCreatePlan = false">取消</button>
            <button class="px-4 py-2 text-sm bg-amber-600 text-white rounded-lg disabled:opacity-50" @click="onCreatePlan" :disabled="!newPlanName.trim()">创建</button>
          </div>
        </div>
      </div>

      <!-- Create Item Modal -->
      <div v-if="showCreateItem" class="modal-bg" @click.self="showCreateItem = false">
        <div class="modal-box">
          <h3 class="text-base font-semibold mb-4">新建收集项</h3>
          <div class="mb-3">
            <label class="block text-xs text-slate-500 mb-1">所属计划</label>
            <input disabled :value="selectedPlanForItem?.name" class="w-full border border-slate-100 bg-slate-50 rounded-lg px-3 py-2 text-sm" />
          </div>
          <div class="mb-3">
            <label class="block text-xs text-slate-500 mb-1">收集项名称</label>
            <input v-model="newItemName" class="w-full border border-slate-200 rounded-lg px-3 py-2 text-sm" placeholder="如：供应商资质审核报告" />
          </div>
          <div class="flex justify-end gap-2">
            <button class="px-4 py-2 text-sm text-slate-500 border border-slate-200 rounded-lg" @click="showCreateItem = false">取消</button>
            <button class="px-4 py-2 text-sm bg-amber-600 text-white rounded-lg disabled:opacity-50" @click="onCreateItem" :disabled="!newItemName.trim()">创建</button>
          </div>
        </div>
      </div>

    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { listKnowledgeBases, listPlans, createPlan, deletePlan, createPlanItem, deletePlanItem, markNotApplicable } from '../../api/knowledgeManagementClient.js'

const router = useRouter()
const customKbs = ref([])
const selectedKbId = ref(null)
const plans = ref([])
const loading = ref(false)
const expandedPlanId = ref(null)

// Modals
const showCreatePlan = ref(false)
const showCreateItem = ref(false)
const newPlanName = ref('')
const newItemName = ref('')
const selectedPlanForItem = ref(null)

const selectedKb = computed(() => customKbs.value.find(k => k.id === selectedKbId.value))
const totalItems = computed(() => plans.value.reduce((s, p) => s + (getPlanItems(p).length), 0))

function getPlanItems(plan) {
  return plan.plan_items || plan.items || []
}

function togglePlan(id) { expandedPlanId.value = expandedPlanId.value === id ? null : id }

function selectKb(id) {
  selectedKbId.value = id
  loadPlans()
}

function openCreateItem(plan) {
  selectedPlanForItem.value = plan
  newItemName.value = ''
  showCreateItem.value = true
}

async function onCreatePlan() {
  if (!newPlanName.value.trim() || !selectedKbId.value) return
  try {
    await createPlan({
      knowledge_base_id: selectedKbId.value,
      name: newPlanName.value.trim(),
      plan_type: 'custom',
      is_custom: true,
    })
    showCreatePlan.value = false
    newPlanName.value = ''
    await loadPlans()
  } catch (e) { alert('创建失败: ' + e.message) }
}

async function onDeletePlan(planId) {
  if (!confirm('确定删除此收集计划？关联的收集项也会被删除。')) return
  try { await deletePlan(planId); await loadPlans() }
  catch (e) { alert('删除失败: ' + e.message) }
}

async function onCreateItem() {
  if (!newItemName.value.trim()) return
  try {
    await createPlanItem({
      plan_id: selectedPlanForItem.value.id,
      name: newItemName.value.trim(),
      is_custom: true,
    })
    showCreateItem.value = false
    newItemName.value = ''
    await loadPlans()
  } catch (e) { alert('创建失败: ' + e.message) }
}

async function onDeleteItem(itemId) {
  if (!confirm('确定删除此收集项？')) return
  try { await deletePlanItem(itemId); await loadPlans() }
  catch (e) { alert('删除失败: ' + e.message) }
}

async function onMarkNA(item) {
  const reason = prompt('标记为不适用的原因（可选）：')
  try { await markNotApplicable(item.id, reason || ''); await loadPlans() }
  catch (e) { alert('操作失败: ' + e.message) }
}

async function loadPlans() {
  if (!selectedKbId.value) return
  loading.value = true
  try {
    const result = await listPlans(selectedKbId.value)
    plans.value = Array.isArray(result) ? result : (result?.items || [result]).filter(Boolean)
  } catch (e) { console.error('Plans load error:', e) }
  finally { loading.value = false }
}

onMounted(async () => {
  try {
    const result = await listKnowledgeBases({ kb_type: 'custom_base' })
    customKbs.value = Array.isArray(result) ? result : (result?.items || [])
    if (customKbs.value.length > 0) {
      selectedKbId.value = customKbs.value[0].id
      await loadPlans()
    }
  } catch (e) { console.error('Custom KBs load error:', e) }
})
</script>

<style scoped>
.breadcrumb{display:flex;align-items:center;gap:6px;padding:10px 14px;background:#fff;border-radius:10px;border:1px solid #e2e8f0;margin-bottom:14px;font-size:13px;flex-wrap:wrap}
.breadcrumb .sep{color:#cbd5e1}
.breadcrumb .node{color:#64748b;padding:3px 10px;cursor:pointer;border-radius:4px;font-size:12px}
.breadcrumb .node:hover{background:#f1f5f9}
.breadcrumb .node.current{background:#fef3c7;color:#b45309;font-weight:600;border-radius:16px;padding:4px 12px}
.stats-bar{display:grid;gap:10px;margin-bottom:16px}
.stat-card{background:#fff;border-radius:10px;padding:14px;border:1px solid #e2e8f0;text-align:center}
.stat-card .s-label{font-size:10px;color:#94a3b8;text-transform:uppercase;letter-spacing:.3px;margin-bottom:4px}
.stat-card .s-value{font-size:24px;font-weight:700;color:#0f172a}
.section-title{font-size:14px;font-weight:600;color:#0f172a;display:flex;align-items:center;gap:8px}
.tip{background:#eff6ff;border:1px solid #bfdbfe;border-radius:8px;padding:10px 14px;font-size:12px;color:#1e40af;line-height:1.6}
.tag{font-size:10px;padding:2px 7px;border-radius:4px;font-weight:500;margin-right:4px}
.tag.blue{background:#dbeafe;color:#2563eb}.tag.amber{background:#fef3c7;color:#b45309}
.tag.green{background:#dcfce7;color:#16a34a}.tag.gray{background:#f1f5f9;color:#94a3b8}
.modal-bg{position:fixed;inset:0;background:rgba(0,0,0,.4);display:flex;align-items:center;justify-content:center;z-index:99;backdrop-filter:blur(2px)}
.modal-box{background:#fff;border-radius:12px;padding:24px;width:480px;max-width:90vw;box-shadow:0 20px 40px rgba(0,0,0,.15)}
</style>
