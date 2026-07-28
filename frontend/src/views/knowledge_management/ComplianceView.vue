<template>
  <div class="h-full overflow-y-auto bg-slate-50">
    <div class="p-6 max-w-[96vw] mx-auto">

      <!-- Breadcrumb -->
      <div class="breadcrumb">
        <span class="node" @click="router.push('/knowledge-management')">🏭 {{ baseName }}</span>
        <span class="sep">›</span>
        <span class="node current">🛡️ 合规性知识库</span>
      </div>

      <!-- Loading -->
      <div v-if="loading" class="text-center py-12 text-slate-400">加载合规性数据中...</div>

      <!-- No compliance KB -->
      <div v-else-if="!complianceKb" class="text-center py-12 text-slate-400">
        尚未创建合规性知识库。<br>
        <span class="text-amber-600">应用启动时会自动创建，或联系管理员手动创建。</span>
      </div>

      <template v-else>
        <!-- Stats -->
        <div class="stats-bar">
          <div class="stat-card">
            <div class="s-label">收集进度</div>
            <div class="s-value amber">{{ progress }}%</div>
            <div class="s-bar"><div class="s-bar-fill blue" :style="{width:progress+'%'}"></div></div>
            <div class="text-[10px] text-slate-400 mt-1">{{ doneCount }}/{{ totalCount }} 项已完成</div>
          </div>
          <div class="stat-card">
            <div class="s-label">质量分</div>
            <div class="s-value">{{ avgScore }}</div>
            <div class="text-[10px] text-slate-400 mt-1">AI综合评分均值</div>
          </div>
          <div class="stat-card">
            <div class="s-label">有效文档</div>
            <div class="s-value green">{{ validCount }}</div>
            <div class="text-[10px] text-slate-400 mt-1">未过期</div>
          </div>
          <div class="stat-card">
            <div class="s-label">即将过期</div>
            <div class="s-value" style="color:#f59e0b">{{ expiringCount }}</div>
            <div class="text-[10px] text-amber-500 mt-1">90天内</div>
          </div>
          <div class="stat-card">
            <div class="s-label">已过期/缺失</div>
            <div class="s-value red">{{ expiredCount + missingDateCount }}</div>
            <div class="text-[10px] text-slate-400 mt-1">0分/待填写</div>
          </div>
        </div>

        <!-- Split: Sidebar + Content -->
        <div class="split-layout">
          <HierarchyTree
            :base-name="baseName" :workshops="sidebarWorkshops" :custom-kbs="sidebarCustomKbs"
            active-node="kb-compliance"
            @nav="onTreeNav"
          />

          <div class="flex-1">
            <div class="section-title">收集项与合规状态 <span class="badge">计划: {{ planName }} · {{ totalCount }}个收集项</span></div>

            <!-- Compliance items -->
            <div v-for="item in complianceItems" :key="item.id"
                 class="compliance-item"
                 :class="{ expired: item.isExpired }"
                 :style="item.isMissingDate ? { borderColor: '#fecaca', background: '#fffbfb' } : {}">

              <div :class="['ci-status', item.isExpired ? 'expired-icon' : item.isExpiring ? 'expiring' : item.isMissingDate ? '' : 'valid']"
                   :style="item.isMissingDate ? { background: '#fef2f2', color: '#ef4444' } : {}">
                {{ item.isExpired ? '✗' : item.isExpiring ? '⏰' : item.isMissingDate ? '⚠' : '✓' }}
              </div>

              <div class="ci-info">
                <div class="ci-name">{{ item.category_name || item.name }}</div>

                <!-- 有效期展示（从文档版本聚合） -->
                <div v-if="!item.isMissingDate && item.validUntil" class="ci-dates">
                  🤖 有效期: {{ item.validFrom || '—' }} → <strong>{{ item.validUntil }}</strong> ·
                  <span v-if="item.isExpired" class="text-red-500 font-semibold">已过期 {{ item.daysOver }} 天</span>
                  <span v-else-if="item.isExpiring" class="text-amber-500 font-semibold">剩余 {{ item.daysLeft }} 天</span>
                  <span v-else>剩余 {{ item.daysLeft }} 天</span>
                </div>

                <!-- 缺失有效期 -->
                <div v-else class="ci-dates">
                  <span class="text-red-500 font-semibold">⚠ 尚未识别有效期 — 请上传文档后在文档管理中填写</span>
                </div>

                <!-- 标签 -->
                <div class="mt-1">
                  <span v-for="t in getItemTags(item)" :key="t.text" class="tag" :class="t.cls">{{ t.text }}</span>
                </div>
              </div>

              <div class="ci-score">
                <div class="ci-score-val" :style="{ color: scoreColor(item.complianceScore ?? item.latestScore) }">
                  {{ item.isMissingDate ? '—' : (item.complianceScore ?? item.latestScore ?? '—') }}
                </div>
                <div class="text-[10px]" :style="{ color: scoreColor(item.complianceScore ?? item.latestScore) }">{{ item.isMissingDate ? '待填写' : item.isExpired ? '已过期' : scoreLabel(item.complianceScore ?? item.latestScore) }}</div>
              </div>

              <!-- 操作按钮 -->
              <div class="ci-actions">
                <button class="btn-xs-doc" @click.stop="goToDoc(item)">📄 管理文档</button>
                <button v-if="!item.not_applicable" class="btn-ghost text-xs py-1 px-2 !text-amber-500 hover:!bg-amber-50" @click.stop="onMarkNA(item)">🚫 不适用</button>
                <button v-else class="btn-ghost text-xs py-1 px-2 !text-green-500 hover:!bg-green-50" @click.stop="onUnmarkNA(item)">✅ 启用</button>
              </div>
            </div>

            <!-- No items -->
            <div v-if="!loading && complianceItems.length === 0 && complianceKb" class="text-center py-8 text-slate-400">
              暂无收集项。请先同步预设类别到该知识库。
            </div>
          </div>
        </div>
      </template>

    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import HierarchyTree from './components/HierarchyTree.vue'
import { listKnowledgeBases, listPlans, markNotApplicable, unmarkNotApplicable, getDashboardBase } from '../../api/knowledgeManagementClient.js'
import { useToast } from '../../composables/useToast'
import { showConfirm } from '../../composables/useConfirm'

const router = useRouter()
const toast = useToast()
const baseName = ref('江西基地')
const complianceKb = ref(null)
const complianceItems = ref([])
const loading = ref(true)
const planName = ref('安环合规文档采集')
const sidebarWorkshops = ref([])
const sidebarCustomKbs = ref([])

function onTreeNav(target, payload) {
  if (target === 'base') router.push('/knowledge-management')
  else if (target === 'compliance') {} // 已在当前页
  else if (target === 'kb-type') router.push(`/knowledge-management/kb-type/${payload}`)
  else if (target === 'workshop') router.push(`/knowledge-management/kb-type/device_doc/workshop/${encodeURIComponent(payload)}`)
  else if (target === 'device') router.push(`/knowledge-management/${payload.kbId}`)
  else if (target === 'custom-kb') router.push(`/knowledge-management/${payload}`)
}

const doneCount = computed(() => complianceItems.value.filter(i => i.overall_status === 'completed').length)
const totalCount = computed(() => complianceItems.value.length)
const progress = computed(() => totalCount.value > 0 ? Math.round(doneCount.value / totalCount.value * 100) : 0)

const validCount = computed(() => complianceItems.value.filter(i => !i.isExpired && !i.isExpiring && !i.isMissingDate && i.overall_status === 'completed').length)
const expiringCount = computed(() => complianceItems.value.filter(i => i.isExpiring).length)
const expiredCount = computed(() => complianceItems.value.filter(i => i.isExpired).length)
const missingDateCount = computed(() => complianceItems.value.filter(i => i.isMissingDate).length)

const avgScore = computed(() => {
  const scored = complianceItems.value.filter(i => !i.isMissingDate && i.complianceScore != null)
  if (scored.length === 0) return '—'
  return Math.round(scored.reduce((s, i) => s + (i.complianceScore || 0), 0) / scored.length)
})

// 评分颜色梯度：≥85 绿 → ≥60 黄 → ≥1 橙红 → 0 深红 → 无评分 灰
function scoreColor(s) {
  if (s == null) return '#94a3b8'
  if (s === 0) return '#dc2626'
  if (s >= 85) return '#16a34a'
  if (s >= 60) return '#f59e0b'
  if (s >= 1) return '#ea580c'
  return '#94a3b8'
}
function scoreLabel(s) {
  if (s == null) return '未评估'
  if (s === 0) return '不相关'
  if (s >= 85) return '优秀'
  if (s >= 60) return '良好'
  if (s >= 1) return '较差'
  return '—'
}

function getItemTags(item) {
  const tags = []
  // 盖章识别状态
  if (item.hasStamp === true) tags.push({ text: '🤖 已盖章', cls: 'green' })
  else if (item.hasStamp === false) tags.push({ text: '缺盖章', cls: 'red' })
  else tags.push({ text: '盖章未检测', cls: 'gray' })
  // 签名识别状态
  if (item.hasSignature === true) tags.push({ text: '🤖 已签名', cls: 'green' })
  else if (item.hasSignature === false) tags.push({ text: '未签名', cls: 'red' })
  else tags.push({ text: '签名未检测', cls: 'gray' })
  // 有效期状态
  if (item.isMissingDate) tags.push({ text: '⚠ 待填写有效期', cls: 'red' })
  else if (item.isExpired) tags.push({ text: '已过期', cls: 'red' })
  else if (item.isExpiring) tags.push({ text: `剩余${item.daysLeft}天`, cls: 'amber' })
  else if (item.validUntil) tags.push({ text: `有效期至 ${item.validUntil}`, cls: 'green' })
  // AI 审核建议
  if (item.aiReviewDecision) {
    const decisionMap = { '通过': 'green', '待完善': 'amber', '驳回': 'red' }
    tags.push({ text: `AI审核: ${item.aiReviewDecision}`, cls: decisionMap[item.aiReviewDecision] || 'gray' })
  }
  // 文档数：显示已上传/已审核状态
  const documents = item.documents || []
  const docCount = documents.length
  const approvedCount = documents.filter(d => {
    const cur = d.current_version_id ? d : documents.find(x => x.is_current) || d
    return cur && cur.status === 'approved'
  }).length
  if (docCount > 0) {
    if (approvedCount === docCount) {
      tags.push({ text: `已审核 ${docCount}个版本`, cls: 'green' })
    } else if (approvedCount > 0) {
      tags.push({ text: `已审核 ${approvedCount}/${docCount} 版本`, cls: 'amber' })
    } else {
      tags.push({ text: `待审核 ${docCount}个版本`, cls: 'amber' })
    }
  }
  return tags
}

// 从文档的 versions 提取最新版本的合规字段
function extractComplianceFields(item) {
  const today = new Date()
  let validUntil = null, validFrom = null, isExpired = false, isExpiring = false, isMissingDate = false
  let latestScore = null, hasStamp = null, hasSignature = null, aiReviewDecision = null
  const documents = item.documents || []
  if (documents.length > 0) {
    // 取第一个文档的 current version
    const doc = documents[0]
    const currentVer = doc.current_version_id
      ? doc
      : documents.find(d => d.is_current) || documents[0]
    if (currentVer) {
      validUntil = currentVer.valid_until
      validFrom = currentVer.valid_from
      latestScore = currentVer.compliance_score ?? currentVer.ai_relevance_score
      hasStamp = currentVer.has_stamp ?? null
      hasSignature = currentVer.has_signature ?? null
      // 从 AI 质量备注中提取 AI 审核建议
      const remark = currentVer.ai_quality_remark || ''
      const decisionMatch = remark.match(/\[AI审核建议\]\s*(通过|驳回|待完善)/)
      if (decisionMatch) {
        aiReviewDecision = decisionMatch[1]
      }
      if (validUntil) {
        const expiry = new Date(validUntil)
        const diffDays = Math.ceil((expiry - today) / (1000 * 60 * 60 * 24))
        if (diffDays < 0) isExpired = true
        else if (diffDays <= 90) isExpiring = true
      } else {
        isMissingDate = true
      }
    } else {
      isMissingDate = true
    }
  } else {
    isMissingDate = true
  }
  return {
    validUntil, validFrom,
    isExpired, isExpiring, isMissingDate,
    complianceScore: latestScore,
    latestScore,
    hasStamp, hasSignature,
    aiReviewDecision,
    docCount: documents.length,
    daysLeft: validUntil ? Math.max(0, Math.ceil((new Date(validUntil) - today) / (1000 * 60 * 60 * 24))) : 0,
    daysOver: validUntil ? Math.max(0, Math.ceil((today - new Date(validUntil)) / (1000 * 60 * 60 * 24))) : 0,
  }
}

// 导航到文档管理页
function goToDoc(item) {
  if (item.id) {
    // 关键：必须传 planId，DocumentManagement 组件的 onMounted 依赖它
    router.push(`/knowledge-management/items/${item.id}/documents?planId=${item.plan_id}&compliance=1`)
  }
}

// 标记不适用
async function onMarkNA(item) {
  if (!await showConfirm(`将「${item.category_name || item.name}」标记为不适用？`, '标记不适用', { type: 'warning' })) return
  try {
    await markNotApplicable(item.id, '')
    toast.success('已标记为不适用')
    await loadData()
  } catch (e) { toast.error('操作失败: ' + e.message) }
}

// 取消不适用
async function onUnmarkNA(item) {
  if (!await showConfirm(`恢复「${item.category_name || item.name}」为启用？`, '恢复收集项', { type: 'primary' })) return
  try {
    await unmarkNotApplicable(item.id)
    toast.success('已恢复')
    await loadData()
  } catch (e) { toast.error('操作失败: ' + e.message) }
}

async function loadData() {
  loading.value = true
  try {
    // 加载侧边栏数据（来自 dashboard 接口，复用缓存）
    try {
      const dash = await getDashboardBase()
      if (dash) {
        baseName.value = dash.base_name || '江西基地'
        sidebarWorkshops.value = (dash.workshops || []).map(w => ({
          name: w.name,
          deviceCount: w.device_count || 0,
          deviceTypes: w.device_types || [],
        }))
        sidebarCustomKbs.value = dash.custom_kbs || []
      }
    } catch (e) { /* 侧边栏数据加载失败不影响主内容 */ }

    const result = await listKnowledgeBases({ kb_type: 'compliance' })
    const kbs = Array.isArray(result) ? result : (result?.items || [])
    complianceKb.value = kbs[0] || null
    if (complianceKb.value) {
      const plans = await listPlans(complianceKb.value.id)
      const items = []
      for (const plan of (Array.isArray(plans) ? plans : plans?.items || [plans])) {
        planName.value = plan.name || planName.value
        for (const item of (plan.plan_items || plan.items || [])) {
          const fields = extractComplianceFields(item)
          items.push({
            ...item,
            ...fields,
            _saving: false,
          })
        }
      }
      complianceItems.value = items
    }
  } catch (e) {
    console.error('Compliance load error:', e)
  } finally {
    loading.value = false
  }
}

onMounted(loadData)
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
.stat-card .s-value.amber{color:#b45309}.stat-card .s-value.green{color:#16a34a}.stat-card .s-value.red{color:#ef4444}
.stat-card .s-bar{height:5px;background:#e2e8f0;border-radius:3px;margin-top:6px}
.stat-card .s-bar-fill{height:100%;border-radius:3px}
.stat-card .s-bar-fill.blue{background:#3b82f6}
.section-title{font-size:14px;font-weight:600;color:#0f172a;margin-bottom:12px;display:flex;align-items:center;gap:8px}
.section-title .badge{font-size:10px;background:#e2e8f0;padding:2px 8px;border-radius:10px;color:#64748b;font-weight:400}

.split-layout{display:flex;gap:12px;min-height:380px}
.compliance-item{background:#fff;border-radius:10px;padding:14px 16px;border:1px solid #e2e8f0;margin-bottom:6px;display:flex;align-items:center;gap:14px}
.compliance-item.expired{border-color:#fecaca;background:#fffbfb}
.ci-status{width:44px;height:44px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:18px;flex-shrink:0}
.ci-status.valid{background:#dcfce7;color:#16a34a}
.ci-status.expiring{background:#fef3c7;color:#f59e0b}
.ci-status.expired-icon{background:#fef2f2;color:#ef4444}
.ci-info{flex:1;min-width:0}
.ci-name{font-weight:600;font-size:14px}
.ci-dates{font-size:11px;color:#64748b;margin-top:2px}
.ci-score{text-align:center;min-width:50px;flex-shrink:0}
.ci-score-val{font-size:20px;font-weight:700}
.ci-actions{display:flex;flex-direction:column;gap:4px;flex-shrink:0}

.tag{font-size:10px;padding:2px 7px;border-radius:4px;font-weight:500;margin-right:4px;display:inline-block}
.tag.blue{background:#dbeafe;color:#2563eb}.tag.amber{background:#fef3c7;color:#b45309}
.tag.green{background:#dcfce7;color:#16a34a}.tag.red{background:#fef2f2;color:#ef4444}.tag.gray{background:#f1f5f9;color:#94a3b8}

.btn-xs-doc{padding:4px 10px;border-radius:5px;border:1px solid #dbeafe;background:#eff6ff;color:#2563eb;font-size:11px;cursor:pointer;transition:all .15s;white-space:nowrap;font-weight:500}
.btn-xs-doc:hover{background:#dbeafe;border-color:#3b82f6}

@media(max-width:768px){.stats-bar{grid-template-columns:repeat(2,1fr)}.compliance-item{flex-wrap:wrap}}
</style>