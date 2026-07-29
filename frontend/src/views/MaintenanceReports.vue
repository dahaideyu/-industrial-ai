<template>
<section class="min-h-screen p-6 lg:p-8">
  <div class="mx-auto max-w-[1500px]">
    <div class="rounded-lg border border-slate-200 bg-white p-6 shadow-sm">
      <p class="text-xs font-bold uppercase tracking-[0.18em] text-amber-700">AI Maintenance Reports</p>
      <h1 class="mt-2 font-headline text-2xl font-semibold text-slate-950">维护报告</h1>
      <p class="mt-2 max-w-3xl text-sm leading-6 text-slate-500">
        按设备生成/查看预测性维护报告（日报/周报/月报），含健康分、风险等级、故障预测与保养建议。
      </p>
    </div>

    <!-- 生成 + 筛选 -->
    <div class="mt-6 rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
      <div class="flex flex-wrap items-end gap-3">
        <div>
          <label class="block text-xs text-slate-400 mb-1">报告类型</label>
          <select v-model="reportType" class="text-sm border border-slate-200 rounded-lg px-3 py-2">
            <option value="daily">日报</option>
            <option value="weekly">周报</option>
            <option value="monthly">月报</option>
          </select>
        </div>
        <div>
          <label class="block text-xs text-slate-400 mb-1">设备（生成时必选，筛选时留空=全部）</label>
          <select v-model="deviceId" class="text-sm border border-slate-200 rounded-lg px-3 py-2 min-w-[220px]">
            <option value="">全部设备</option>
            <option v-for="d in devices" :key="d.id" :value="d.id">{{ d.workshop_name }} / {{ d.name }}</option>
          </select>
        </div>
        <div>
          <label class="block text-xs text-slate-400 mb-1">日期</label>
          <input v-model="reportDate" type="date" class="text-sm border border-slate-200 rounded-lg px-3 py-2" />
        </div>
        <button @click="loadReports" :disabled="listLoading"
          class="px-4 py-2 text-sm bg-white border border-slate-200 rounded-lg hover:bg-slate-50 disabled:opacity-50">
          {{ listLoading ? '查询中...' : '筛选查询' }}
        </button>
        <button @click="generate" :disabled="generating"
          class="px-4 py-2 text-sm bg-amber-500 text-white rounded-lg hover:bg-amber-600 disabled:opacity-50">
          {{ generating ? '生成中...' : (deviceId ? '生成该设备报告' : '批量生成(该类型全部设备)') }}
        </button>
      </div>
      <div v-if="generateMsg" class="mt-3 text-xs" :class="generateErr ? 'text-red-600' : 'text-emerald-600'">
        {{ generateMsg }}
      </div>
    </div>

    <!-- 报告列表 -->
    <div class="mt-6 rounded-lg border border-slate-200 bg-white shadow-sm">
      <div v-if="listLoading" class="text-center py-16 text-slate-400 text-sm">⏳ 加载中...</div>
      <div v-else-if="listError" class="text-center py-16 text-slate-400 text-sm">{{ listError }}</div>
      <div v-else-if="reports.length === 0" class="text-center py-16 text-slate-400 text-sm">
        暂无{{ reportTypeLabel }}报告 — 选择设备后点击"生成该设备报告"，或不选设备点击"批量生成"生成该类型下所有设备的报告。
      </div>
      <table v-else class="w-full text-sm">
        <thead>
          <tr class="border-b border-slate-100 text-left text-xs text-slate-400">
            <th class="px-4 py-3">日期</th>
            <th class="px-4 py-3">车间/设备</th>
            <th class="px-4 py-3">类型</th>
            <th class="px-4 py-3">健康分</th>
            <th class="px-4 py-3">风险等级</th>
            <th class="px-4 py-3">报警数</th>
            <th class="px-4 py-3">生成时间</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="r in reports" :key="r.id" @click="openDetail(r.id)"
            class="border-b border-slate-50 hover:bg-amber-50/40 cursor-pointer">
            <td class="px-4 py-3">{{ r.report_date }}</td>
            <td class="px-4 py-3">{{ r.workshop || '—' }} / {{ r.device_name || r.device_id }}</td>
            <td class="px-4 py-3">{{ reportTypeText(r.report_type) }}</td>
            <td class="px-4 py-3">
              <span v-if="r.health_score != null" :class="healthScoreClass(r.health_score)" class="px-2 py-0.5 rounded text-xs font-medium">
                {{ r.health_score }}
              </span>
              <span v-else class="text-slate-300">—</span>
            </td>
            <td class="px-4 py-3">
              <span v-if="r.risk_level" :class="riskLevelClass(r.risk_level)" class="px-2 py-0.5 rounded text-xs font-medium">
                {{ r.risk_level }}
              </span>
              <span v-else class="text-slate-300">—</span>
            </td>
            <td class="px-4 py-3">{{ r.alarm_count ?? '—' }}</td>
            <td class="px-4 py-3 text-slate-400 text-xs">{{ (r.created_at || '').slice(0, 19) }}</td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>

  <!-- 报告详情弹窗 -->
  <Teleport to="body">
    <div v-if="detail" class="fixed inset-0 z-50 flex items-center justify-center p-4" @click.self="detail = null">
      <div class="absolute inset-0 bg-black/40"></div>
      <div class="relative bg-white rounded-2xl shadow-2xl w-full max-w-3xl max-h-[85vh] flex flex-col">
        <div class="flex items-center justify-between px-5 py-3 border-b border-slate-100 shrink-0">
          <span class="text-sm font-bold" v-if="detail.source !== 'loading'">
            {{ detail.workshop }} / {{ detail.device_name || detail.device_id }} — {{ reportTypeText(detail.report_type) }} {{ detail.report_date }}
          </span>
          <span class="text-sm font-bold" v-else>加载中...</span>
          <button @click="detail = null" class="text-slate-400 hover:text-slate-600 text-lg leading-none">✕</button>
        </div>
        <div class="overflow-y-auto flex-1 px-5 py-4">
          <div v-if="detail.source === 'loading'" class="text-center py-12 text-slate-400">⏳ 加载中...</div>
          <div v-else-if="detail.source === 'error'" class="text-center py-12 text-slate-400">{{ detail.msg }}</div>
          <template v-else>
            <div class="grid grid-cols-4 gap-3 text-center mb-4">
              <div class="bg-slate-50 rounded-lg p-3">
                <div class="font-bold text-lg" :class="detail.health_score != null ? healthScoreTextClass(detail.health_score) : 'text-slate-300'">
                  {{ detail.health_score ?? '—' }}
                </div>
                <div class="text-xs text-slate-400">健康分</div>
              </div>
              <div class="bg-slate-50 rounded-lg p-3">
                <div class="font-bold text-lg">{{ detail.risk_level || '—' }}</div>
                <div class="text-xs text-slate-400">风险等级</div>
              </div>
              <div class="bg-slate-50 rounded-lg p-3">
                <div class="font-bold text-lg">{{ detail.alarm_count ?? '—' }}</div>
                <div class="text-xs text-slate-400">报警数</div>
              </div>
              <div class="bg-slate-50 rounded-lg p-3">
                <div class="font-bold text-lg">{{ detail.health_trend || '—' }}</div>
                <div class="text-xs text-slate-400">健康趋势</div>
              </div>
            </div>

            <div v-if="detail.report_content" class="prose prose-sm max-w-none text-slate-700 leading-relaxed"
              v-html="renderMarkdown(detail.report_content)"></div>
            <div v-else-if="detail.report_summary" class="text-sm text-slate-700 whitespace-pre-wrap">{{ detail.report_summary }}</div>
            <div v-else class="text-sm text-slate-400 text-center py-8">该报告没有生成正文内容。</div>

            <div v-if="detail.maintenance_suggestions" class="mt-4 bg-amber-50 rounded-lg p-3 text-xs text-amber-800">
              🔧 保养建议：{{ formatMaybeJson(detail.maintenance_suggestions) }}
            </div>
            <div v-if="detail.urgent_actions" class="mt-2 bg-red-50 rounded-lg p-3 text-xs text-red-700">
              ⚠️ 紧急处理：{{ formatMaybeJson(detail.urgent_actions) }}
            </div>
          </template>
        </div>
      </div>
    </div>
  </Teleport>
</section>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { marked } from 'marked'
import {
  listMaintenanceReports, getMaintenanceReportDetail,
  generateMaintenanceReport, generateBatchReports, listMaintenanceDevices,
} from '../api/client.js'

const reportType = ref('daily')
const deviceId = ref('')
const reportDate = ref(new Date().toISOString().slice(0, 10))

const devices = ref([])
const reports = ref([])
const listLoading = ref(false)
const listError = ref('')

const generating = ref(false)
const generateMsg = ref('')
const generateErr = ref(false)

const detail = ref(null)

const reportTypeLabel = computed(() => reportTypeText(reportType.value))
function reportTypeText(t) {
  return { daily: '日', weekly: '周', monthly: '月' }[t] || t || ''
}

function healthScoreClass(v) {
  if (v >= 80) return 'bg-emerald-50 text-emerald-700'
  if (v >= 60) return 'bg-amber-50 text-amber-700'
  return 'bg-red-50 text-red-700'
}
function healthScoreTextClass(v) {
  if (v >= 80) return 'text-emerald-600'
  if (v >= 60) return 'text-amber-600'
  return 'text-red-600'
}
function riskLevelClass(level) {
  const l = String(level).toLowerCase()
  if (l.includes('high') || l.includes('高')) return 'bg-red-50 text-red-700'
  if (l.includes('medium') || l.includes('中')) return 'bg-amber-50 text-amber-700'
  return 'bg-emerald-50 text-emerald-700'
}
function formatMaybeJson(v) {
  if (typeof v === 'string') return v
  try { return JSON.stringify(v) } catch { return String(v) }
}
function renderMarkdown(text) {
  try { return marked(text) } catch { return text }
}

async function loadDevices() {
  try {
    const res = await listMaintenanceDevices()
    if (res.code === 200 && res.data) devices.value = res.data.items || []
  } catch (err) {
    console.error('加载设备列表失败:', err)
  }
}

async function loadReports() {
  listLoading.value = true
  listError.value = ''
  try {
    const params = { report_type: reportType.value }
    if (deviceId.value) params.device_id = deviceId.value
    const res = await listMaintenanceReports(params)
    if (res.code === 200 && res.data) {
      reports.value = res.data.items || []
    } else {
      listError.value = res.msg || '查询失败'
      reports.value = []
    }
  } catch (err) {
    listError.value = err.response?.data?.msg || err.message || '查询失败'
    reports.value = []
  } finally {
    listLoading.value = false
  }
}

async function generate() {
  generating.value = true
  generateMsg.value = ''
  generateErr.value = false
  try {
    if (deviceId.value) {
      const res = await generateMaintenanceReport({
        device_id: deviceId.value, report_type: reportType.value, report_date: reportDate.value,
      })
      if (res.code === 200) {
        generateMsg.value = '生成成功，已刷新列表'
        await loadReports()
      } else {
        generateErr.value = true
        generateMsg.value = res.msg || '生成失败'
      }
    } else {
      const res = await generateBatchReports({ report_type: reportType.value, report_date: reportDate.value })
      generateErr.value = res.code !== 200
      generateMsg.value = res.code === 200
        ? '批量生成任务已提交（后台执行，稍后刷新查看）'
        : (res.msg || '提交失败')
    }
  } catch (err) {
    generateErr.value = true
    generateMsg.value = err.response?.data?.msg || err.message || '生成失败'
  } finally {
    generating.value = false
  }
}

async function openDetail(id) {
  detail.value = { source: 'loading' }
  try {
    const res = await getMaintenanceReportDetail(id)
    if (res.code === 200 && res.data) detail.value = res.data
    else detail.value = { source: 'error', msg: res.msg || '加载失败' }
  } catch (err) {
    detail.value = { source: 'error', msg: err.response?.data?.msg || err.message }
  }
}

onMounted(() => {
  loadDevices()
  loadReports()
})
</script>
