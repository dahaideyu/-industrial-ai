<template>
  <div class="h-full overflow-y-auto bg-slate-50">
    <div class="p-6 max-w-[96vw] mx-auto">
      <div class="flex items-center justify-between mb-4">
        <div class="flex items-center gap-3">
          <button class="btn-ghost text-[13px]" @click="router.back()">← 返回</button>
          <h1 class="text-xl font-bold text-slate-800">知识库 AI 评估报告</h1>
        </div>
        <button
          class="btn-primary"
          @click="router.push('/knowledge-management')"
        >进入知识库管理 →</button>
      </div>

      <div v-if="loading" class="text-center py-16 text-slate-400">加载中...</div>

      <div v-else-if="error" class="rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
        AI 评估失败，请稍后重试
      </div>

      <template v-else-if="overview">
        <!-- 总览 Banner -->
        <div class="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3 mb-5">
          <div class="bg-white border border-slate-200 rounded-2xl p-4">
            <div class="text-xs text-slate-500 mb-1">总完成率</div>
            <div class="text-2xl font-bold text-amber-500">{{ overview.summary.total_progress }}%</div>
          </div>
          <div class="bg-white border border-slate-200 rounded-2xl p-4">
            <div class="text-xs text-slate-500 mb-1">质量分</div>
            <div class="text-2xl font-bold text-emerald-500">{{ overview.summary.total_score }}</div>
          </div>
          <div class="bg-white border border-slate-200 rounded-2xl p-4">
            <div class="text-xs text-slate-500 mb-1">合规过期</div>
            <div class="text-2xl font-bold text-red-500">{{ overview.summary.expired_count }}</div>
          </div>
          <div class="bg-white border border-slate-200 rounded-2xl p-4">
            <div class="text-xs text-slate-500 mb-1">内容缺失</div>
            <div class="text-2xl font-bold text-purple-500">{{ (overview.summary.missing_device_type_count ?? 0) + (overview.summary.missing_plan_item_count ?? 0) }}</div>
          </div>
          <div class="bg-white border border-slate-200 rounded-2xl p-4">
            <div class="text-xs text-slate-500 mb-1">评估时间</div>
            <div class="text-[13px] text-slate-700 mt-2">{{ formatTime(overview.evaluated_at) }}</div>
          </div>
        </div>

        <!-- AI 智能总结 -->
        <div class="bg-slate-50 border border-slate-200 rounded-xl p-5 mb-5">
          <div class="text-sm font-semibold text-slate-700 mb-2">🤖 AI 智能总结</div>
          <div v-if="summaryLoading" class="text-sm text-slate-400">生成中...</div>
          <div v-else class="text-sm text-slate-700 leading-relaxed markdown-body" v-html="renderedSummary"></div>
        </div>

        <!-- 进度维度 -->
        <section class="bg-white border border-slate-200 rounded-xl p-5 mb-4">
          <h2 class="text-base font-semibold text-slate-800 mb-3">📈 进度</h2>
          <div v-if="!overview.progress.kb_progress.length" class="text-sm text-slate-400">暂无 KB 数据</div>
          <div v-else class="space-y-3">
            <div v-for="kb in overview.progress.kb_progress" :key="kb.kb_type" class="flex items-center gap-3">
              <div class="w-32 text-sm text-slate-700">{{ kb.name }}</div>
              <div class="flex-1 h-2 bg-slate-100 rounded overflow-hidden">
                <div class="h-full bg-amber-500 rounded" :style="{ width: kb.progress + '%' }"></div>
              </div>
              <div class="w-16 text-right text-sm font-semibold text-slate-700">{{ kb.progress }}%</div>
            </div>
          </div>
        </section>

        <!-- 质量维度 -->
        <section class="bg-white border border-slate-200 rounded-xl p-5 mb-4">
          <h2 class="text-base font-semibold text-slate-800 mb-3">🎯 质量</h2>
          <div v-if="!overview.quality.low_quality_docs.length" class="text-sm text-slate-400">暂无低分文档</div>
          <table v-else class="w-full text-xs table-fixed">
            <colgroup>
              <col style="width: 140px">
              <col style="width: 72px">
              <col style="width: 56px">
              <col style="width: 56px">
              <col>
            </colgroup>
            <thead class="text-[11px] text-slate-500 border-b border-slate-200">
              <tr>
                <th class="text-left py-1 px-1 font-medium">文件名</th>
                <th class="text-center py-1 px-1 font-medium">设备类型</th>
                <th class="text-center py-1 px-1 font-medium">相关度</th>
                <th class="text-center py-1 px-1 font-medium">质量分</th>
                <th class="text-left py-1 pl-4 pr-1 font-medium">原因</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="doc in overview.quality.low_quality_docs" :key="doc.version_id" class="border-b border-slate-100 align-top">
                <td class="py-1 px-1 text-slate-700 leading-tight break-all">{{ doc.filename }}</td>
                <td class="py-1 px-1 text-center text-slate-600 leading-tight">{{ doc.device_type }}</td>
                <td class="py-1 px-1 text-center text-slate-600 leading-tight">{{ doc.relevance_score }}</td>
                <td class="py-1 px-1 text-center font-semibold text-red-500 leading-tight">{{ doc.quality_score }}</td>
                <td class="py-1 pl-4 pr-1 text-slate-500 leading-tight break-words">{{ doc.remark }}</td>
              </tr>
            </tbody>
          </table>
        </section>

        <!-- 合规维度 -->
        <section class="bg-white border border-slate-200 rounded-xl p-5 mb-4">
          <h2 class="text-base font-semibold text-slate-800 mb-3">🛡️ 合规</h2>
          <div v-if="!overview.compliance.expired_count && !overview.compliance.expiring_soon_count"
               class="text-sm text-slate-400">尚未配置合规性知识库</div>
          <template v-else>
            <div class="grid grid-cols-3 gap-3 mb-3 text-center">
              <div class="rounded-md bg-emerald-50 p-3">
                <div class="text-xs text-emerald-700">有效证书</div>
                <div class="text-xl font-bold text-emerald-600">{{ overview.compliance.valid_count }}</div>
              </div>
              <div class="rounded-md bg-red-50 p-3">
                <div class="text-xs text-red-700">已过期</div>
                <div class="text-xl font-bold text-red-600">{{ overview.compliance.expired_count }}</div>
              </div>
              <div class="rounded-md bg-amber-50 p-3">
                <div class="text-xs text-amber-700">30 天内过期</div>
                <div class="text-xl font-bold text-amber-600">{{ overview.compliance.expiring_soon_count }}</div>
              </div>
            </div>
            <div v-if="overview.compliance.expired_docs.length" class="text-xs text-slate-500 mt-2">
              <div v-for="d in overview.compliance.expired_docs" :key="d.version_id" class="py-1">
                ❗ {{ d.filename }}（已过期 {{ d.expired_days }} 天）
              </div>
            </div>
          </template>
        </section>

        <!-- 内容缺失 -->
        <section class="bg-white border border-slate-200 rounded-xl p-5 mb-4">
          <h2 class="text-base font-semibold text-slate-800 mb-3">📭 内容缺失</h2>
          <div v-if="!hasMissingItems" class="text-sm text-slate-400">暂无缺失项</div>
          <div v-else class="grid grid-cols-1 lg:grid-cols-3 gap-3">
            <!-- 合规性知识库 -->
            <div class="border border-blue-200 rounded-lg overflow-hidden">
              <div class="bg-blue-50 px-2 py-1.5 text-xs font-semibold text-blue-700 flex items-center justify-between gap-2">
                <span class="whitespace-nowrap">🛡️ 合规性知识库</span>
                <span class="text-[10px] bg-blue-200 px-1.5 py-0.5 rounded-full whitespace-nowrap">{{ missingFiltered.compliance.length }} 项</span>
              </div>
              <div class="max-h-[400px] overflow-y-auto divide-y divide-slate-100">
                <div v-for="item in missingFiltered.compliance" :key="item.plan_item_id"
                     class="px-3 py-2 text-xs text-slate-600 hover:bg-blue-50/50">
                  {{ item.category }}
                </div>
                <div v-if="!missingFiltered.compliance.length" class="px-3 py-4 text-xs text-slate-400 text-center">无缺失</div>
              </div>
            </div>
            <!-- 设备说明知识库 -->
            <div class="border border-amber-200 rounded-lg overflow-hidden">
              <div class="bg-amber-50 px-2 py-1.5 text-xs font-semibold text-amber-700 flex items-center justify-between gap-2">
                <span class="whitespace-nowrap">📐 设备说明</span>
                <div class="flex items-center gap-1.5 min-w-0">
                  <span class="text-[10px] bg-amber-200 px-1.5 py-0.5 rounded-full whitespace-nowrap">{{ missingFiltered.device_doc.length }} 项</span>
                  <div class="km-mini-select">
                    <SqlQaSelect
                      v-if="deviceTypeOptions.device_doc.length > 0"
                      v-model="deviceTypeFilter.device_doc"
                      :options="deviceTypeOptions.device_doc"
                      width-class="w-[100px]"
                    />
                  </div>
                </div>
              </div>
              <div class="max-h-[400px] overflow-y-auto divide-y divide-slate-100">
                <div v-for="item in missingFiltered.device_doc" :key="item.plan_item_id"
                     class="px-3 py-2 text-xs text-slate-600 hover:bg-amber-50/50">
                  <span class="text-slate-400">{{ item.device_type }}</span>
                  <span class="mx-1 text-slate-300">·</span>
                  {{ item.category }}
                </div>
                <div v-if="!missingFiltered.device_doc.length" class="px-3 py-6 text-xs text-emerald-600 text-center">
                  ✓ 该设备类型设备说明已全部完成
                </div>
              </div>
            </div>
            <!-- 设备 SOP 知识库 -->
            <div class="border border-emerald-200 rounded-lg overflow-hidden">
              <div class="bg-emerald-50 px-2 py-1.5 text-xs font-semibold text-emerald-700 flex items-center justify-between gap-2">
                <span class="whitespace-nowrap">📋 设备 SOP</span>
                <div class="flex items-center gap-1.5 min-w-0">
                  <span class="text-[10px] bg-emerald-200 px-1.5 py-0.5 rounded-full whitespace-nowrap">{{ missingFiltered.sop_doc.length }} 项</span>
                  <div class="km-mini-select">
                    <SqlQaSelect
                      v-if="deviceTypeOptions.sop_doc.length > 0"
                      v-model="deviceTypeFilter.sop_doc"
                      :options="deviceTypeOptions.sop_doc"
                      width-class="w-[100px]"
                    />
                  </div>
                </div>
              </div>
              <div class="max-h-[400px] overflow-y-auto divide-y divide-slate-100">
                <div v-for="item in missingFiltered.sop_doc" :key="item.plan_item_id"
                     class="px-3 py-2 text-xs text-slate-600 hover:bg-emerald-50/50">
                  <span class="text-slate-400">{{ item.device_type }}</span>
                  <span class="mx-1 text-slate-300">·</span>
                  {{ item.category }}
                </div>
                <div v-if="!missingFiltered.sop_doc.length" class="px-3 py-6 text-xs text-emerald-600 text-center">
                  ✓ 该设备类型设备 SOP 已全部完成
                </div>
              </div>
            </div>
          </div>
        </section>
      </template>
    </div>
  </div>
</template>

<script setup>
import { computed, ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { marked } from 'marked'
import { getKnowledgeOverview, getKnowledgeOverviewSummary } from '../../api/knowledgeManagementClient.js'
import SqlQaSelect from '../sql_qa/components/SqlQaSelect.vue'

// 配置 marked：禁用 HTML 标签、支持 GFM
marked.setOptions({ gfm: true, breaks: true })

const renderedSummary = computed(() => {
  if (!summary.value) return ''
  // 降级文案无 Markdown，直接展示
  if (!summary.value.includes('## ')) {
    return `<p class="text-slate-700">${summary.value}</p>`
  }
  return marked.parse(summary.value)
})

const router = useRouter()
const deviceTypeFilter = ref({ device_doc: '', sop_doc: '' })
const loading = ref(true)
const error = ref(false)
const summaryLoading = ref(true)
const overview = ref(null)
const summary = ref('')

function formatTime(s) {
  if (!s) return ''
  try { return new Date(s).toLocaleString('zh-CN', { hour12: false }) } catch { return s }
}

const hasMissingItems = computed(() => {
  const m = overview.value?.missing?.missing_by_plan_type
  if (!m) return false
  return m.compliance?.length > 0 || m.device_doc?.length > 0 || m.sop_doc?.length > 0
})

const deviceTypeOptions = computed(() => {
  // 列全部 KB 设备类型（不论是否有缺失项），切任何设备都有内容
  const list = overview.value?.missing?.device_type_list
  if (!list) return { device_doc: [], sop_doc: [] }
  return {
    device_doc: list.device_doc || [],
    sop_doc: list.sop_doc || [],
  }
})

const missingFiltered = computed(() => {
  const m = overview.value?.missing?.missing_by_plan_type
  const empty = { compliance: [], device_doc: [], sop_doc: [] }
  if (!m) return empty
  const f = deviceTypeFilter.value
  // 默认按当前选中的设备类型筛选（无"全部"选项，必选）
  return {
    compliance: m.compliance || [],
    device_doc: f.device_doc
      ? (m.device_doc || []).filter(i => i.device_type === f.device_doc)
      : (m.device_doc || []),
    sop_doc: f.sop_doc
      ? (m.sop_doc || []).filter(i => i.device_type === f.sop_doc)
      : (m.sop_doc || []),
  }
})

async function loadOverview() {
  loading.value = true
  error.value = false
  try {
    const data = await getKnowledgeOverview()
    overview.value = data?.data ?? data
    // 默认每个 KB 选中第一个设备类型（必选，无"全部"选项）
    const m = overview.value?.missing?.missing_by_plan_type
    if (m) {
      if (!deviceTypeFilter.value.device_doc) {
        const dts = [...new Set((m.device_doc || []).map(i => i.device_type).filter(Boolean))].sort()
        if (dts.length) deviceTypeFilter.value.device_doc = dts[0]
      }
      if (!deviceTypeFilter.value.sop_doc) {
        const dts = [...new Set((m.sop_doc || []).map(i => i.device_type).filter(Boolean))].sort()
        if (dts.length) deviceTypeFilter.value.sop_doc = dts[0]
      }
    }
  } catch (e) {
    console.error('overview load error', e)
    error.value = true
  } finally {
    loading.value = false
  }
}

async function loadSummary() {
  summaryLoading.value = true
  try {
    const data = await getKnowledgeOverviewSummary()
    summary.value = data?.data?.summary ?? data?.summary ?? '总结暂不可用，请稍后重试。'
  } catch (e) {
    console.error('summary load error', e)
    summary.value = '智能总结暂不可用，已切换到本地摘要（请刷新页面重试）。'
  } finally {
    summaryLoading.value = false
  }
}

onMounted(() => {
  loadOverview()
  loadSummary()
})
</script>

<style scoped>
.btn-primary {
  @apply inline-flex items-center gap-1.5 px-4 py-2 bg-amber-500 text-white text-[13px] font-medium rounded-lg hover:bg-amber-600 transition-colors;
}
.btn-ghost {
  @apply inline-flex items-center gap-1.5 px-3 py-1.5 text-slate-500 text-[13px] font-medium rounded-lg hover:bg-slate-100 transition-colors;
}
.markdown-body :deep(h2) {
  @apply text-sm font-bold text-slate-800 mt-3 mb-1.5 flex items-center gap-1.5;
}
.markdown-body :deep(h2:first-child) {
  @apply mt-0;
}
.markdown-body :deep(ul) {
  @apply list-disc pl-5 space-y-1 my-1.5;
}
.markdown-body :deep(ol) {
  @apply list-decimal pl-5 space-y-1 my-1.5;
}
.markdown-body :deep(li) {
  @apply leading-relaxed;
}
.markdown-body :deep(p) {
  @apply leading-relaxed my-1;
}
.markdown-body :deep(strong) {
  @apply font-semibold text-slate-900;
}
/* 紧凑化设备类型下拉：覆盖 SqlQaSelect 内部 button 高度与最小宽度 */
.km-mini-select :deep(.custom-select-wrapper),
.km-mini-select :deep(div) {
  min-width: 0;
}
.km-mini-select :deep(button) {
  font-size: 11px !important;
  padding: 2px 6px !important;
  min-width: 0 !important;
  border-radius: 4px !important;
  line-height: 1.4 !important;
  height: 22px !important;
}
.km-mini-select :deep(button svg) {
  width: 11px !important;
  height: 11px !important;
}
.km-mini-select :deep(.w-\[110px\]) {
  width: 100px !important;
}
</style>
