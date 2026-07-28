<template>
  <div class="max-w-[1280px] mx-auto px-6 py-8">
    <!-- 头部 -->
    <div class="flex items-center justify-between flex-wrap gap-3 mb-6">
      <div>
        <h1 class="font-headline text-xl font-semibold text-gray-900">任务管理</h1>
        <p class="text-sm text-gray-400 mt-1">统一查看、编辑 cron 计划、手动触发所有定时任务；每次运行结果/异常自动入库。</p>
      </div>
      <button @click="load" :disabled="loading"
        class="px-4 py-2 text-sm rounded-lg bg-gray-50 text-gray-600 border border-gray-200 hover:bg-gray-100 disabled:opacity-50">
        {{ loading ? '加载中…' : '刷新' }}
      </button>
    </div>

    <!-- 调度器状态横幅 -->
    <div class="mb-5 rounded-xl border p-4 text-sm flex items-center gap-2"
      :class="schedulerEnabled ? 'bg-emerald-50 border-emerald-100 text-emerald-700' : 'bg-amber-50 border-amber-100 text-amber-700'">
      <span class="h-2 w-2 rounded-full" :class="schedulerEnabled ? 'bg-emerald-500' : 'bg-amber-500'"></span>
      <span v-if="schedulerEnabled">调度器已开启（ENABLE_REPORT_SCHEDULER=true）——改 cron/启停即时生效，已启用的任务按计划运行。</span>
      <span v-else>调度器未开启（ENABLE_REPORT_SCHEDULER=false）——定时不会自动运行；改 cron 只落库（下次启动生效），仍可手动触发。</span>
    </div>

    <!-- 汇总条 -->
    <div class="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-5">
      <div class="bg-white rounded-xl border border-gray-100 shadow-sm p-4">
        <div class="text-[11px] text-gray-400">任务总数</div>
        <div class="text-2xl font-semibold text-gray-800 tabular-nums mt-1">{{ summary.total }}</div>
      </div>
      <div class="bg-white rounded-xl border border-gray-100 shadow-sm p-4">
        <div class="text-[11px] text-gray-400">已启用</div>
        <div class="text-2xl font-semibold text-emerald-600 tabular-nums mt-1">{{ summary.enabled }}</div>
      </div>
      <div class="bg-white rounded-xl border border-gray-100 shadow-sm p-4">
        <div class="text-[11px] text-gray-400">运行中</div>
        <div class="text-2xl font-semibold text-amber-500 tabular-nums mt-1">{{ summary.running }}</div>
      </div>
      <div class="bg-white rounded-xl border border-gray-100 shadow-sm p-4">
        <div class="text-[11px] text-gray-400">最近运行失败</div>
        <div class="text-2xl font-semibold text-rose-500 tabular-nums mt-1">{{ summary.failed }}</div>
      </div>
    </div>

    <div v-if="notice" class="mb-4 text-sm rounded-lg px-4 py-2"
      :class="noticeErr ? 'bg-rose-50 text-rose-600' : 'bg-indigo-50 text-indigo-600'">{{ notice }}</div>

    <!-- 任务表（按分组） -->
    <div v-for="g in grouped" :key="g.name" class="mb-6">
      <div class="text-xs font-semibold uppercase tracking-wider text-gray-400 mb-2">{{ g.name }}</div>
      <div class="bg-white rounded-xl border border-gray-100 shadow-sm overflow-hidden">
        <div class="overflow-x-auto">
          <table class="w-full text-sm">
            <thead class="bg-gray-50">
              <tr class="text-left text-xs text-gray-500 border-b border-gray-200 whitespace-nowrap">
                <th class="py-3 px-4 font-semibold">任务</th>
                <th class="py-3 px-3 font-semibold">计划 (cron)</th>
                <th class="py-3 px-3 font-semibold">启用</th>
                <th class="py-3 px-3 font-semibold">状态</th>
                <th class="py-3 px-3 font-semibold">下次运行</th>
                <th class="py-3 px-3 font-semibold">最近运行</th>
                <th class="py-3 px-3 font-semibold text-right">操作</th>
              </tr>
            </thead>
            <tbody class="divide-y divide-gray-50">
              <template v-for="j in g.items" :key="j.id">
                <tr class="hover:bg-gray-50/50">
                  <td class="py-3 px-4">
                    <div class="font-bold text-gray-800">{{ j.name }}</div>
                    <div class="text-[10px] text-gray-300">{{ j.id }}<span v-if="j.cron_env"> · {{ j.cron_env }}</span></div>
                  </td>
                  <td class="py-3 px-3">
                    <button @click="openCronModal(j)" class="text-left group">
                      <div class="text-xs font-medium text-gray-700 group-hover:text-violet-600">{{ describeCron(j.cron) }}</div>
                      <div class="text-[10px] text-gray-300 tabular-nums">{{ j.cron || '未设置' }}</div>
                    </button>
                  </td>
                  <td class="py-3 px-3">
                    <button @click="j.enabled = !j.enabled"
                      :class="['relative inline-flex h-5 w-9 items-center rounded-full transition-colors', j.enabled ? 'bg-emerald-500' : 'bg-gray-200']">
                      <span :class="['inline-block h-4 w-4 transform rounded-full bg-white transition-transform', j.enabled ? 'translate-x-4' : 'translate-x-0.5']"></span>
                    </button>
                  </td>
                  <td class="py-3 px-3">
                    <span :class="['text-[11px] px-2 py-0.5 rounded', statusCls(j.status)]">{{ j.status }}</span>
                  </td>
                  <td class="py-3 px-3 tabular-nums text-gray-500 text-xs">{{ j.next_run_time || '—' }}</td>
                  <td class="py-3 px-3">
                    <button v-if="j.last_run" @click="toggleRuns(j)"
                      class="flex items-center gap-1.5 text-left hover:opacity-80">
                      <span :class="['text-[11px] px-1.5 py-0.5 rounded', runCls(j.last_run.status)]">{{ runText(j.last_run.status) }}</span>
                      <span class="text-[11px] text-gray-400 tabular-nums">{{ j.last_run.start_time || '' }}</span>
                      <span class="text-[10px] text-gray-300">{{ expanded[j.id] ? '▴' : '▾' }}</span>
                    </button>
                    <span v-else class="text-[11px] text-gray-300">从未运行</span>
                  </td>
                  <td class="py-3 px-3 text-right whitespace-nowrap">
                    <button @click="saveJob(j)" :disabled="saving[j.id]"
                      class="text-xs px-2.5 py-1.5 rounded bg-gray-50 text-gray-600 border border-gray-200 hover:bg-gray-100 disabled:opacity-50">
                      {{ saving[j.id] ? '保存中…' : '保存' }}
                    </button>
                    <button v-if="j.manual" @click="runJob(j)" :disabled="running[j.id]"
                      class="ml-1.5 text-xs px-2.5 py-1.5 rounded bg-violet-500 text-white hover:bg-violet-600 disabled:opacity-50">
                      {{ running[j.id] ? '触发中…' : '立即运行' }}
                    </button>
                  </td>
                </tr>
                <!-- 运行历史展开 -->
                <tr v-if="expanded[j.id]" class="bg-gray-50/40">
                  <td colspan="7" class="py-3 px-4">
                    <div v-if="runsLoading[j.id]" class="text-xs text-gray-400">加载运行历史…</div>
                    <div v-else-if="(runsMap[j.id] || []).length === 0" class="text-xs text-gray-400">暂无运行记录。</div>
                    <table v-else class="w-full text-xs">
                      <thead>
                        <tr class="text-left text-gray-400">
                          <th class="py-1 pr-4 font-medium">开始</th>
                          <th class="py-1 pr-4 font-medium">结束</th>
                          <th class="py-1 pr-4 font-medium">耗时</th>
                          <th class="py-1 pr-4 font-medium">状态</th>
                          <th class="py-1 font-medium">异常</th>
                        </tr>
                      </thead>
                      <tbody>
                        <tr v-for="r in runsMap[j.id]" :key="r.id" class="border-t border-gray-100">
                          <td class="py-1 pr-4 tabular-nums text-gray-500">{{ r.start_time || '—' }}</td>
                          <td class="py-1 pr-4 tabular-nums text-gray-500">{{ r.end_time || '—' }}</td>
                          <td class="py-1 pr-4 tabular-nums text-gray-500">{{ r.duration_seconds != null ? r.duration_seconds + 's' : '—' }}</td>
                          <td class="py-1 pr-4"><span :class="['px-1.5 py-0.5 rounded', runCls(r.status)]">{{ runText(r.status) }}</span></td>
                          <td class="py-1 text-rose-500 max-w-[520px] truncate" :title="r.error_message || ''">{{ r.error_message || '—' }}</td>
                        </tr>
                      </tbody>
                    </table>
                  </td>
                </tr>
              </template>
            </tbody>
          </table>
        </div>
      </div>
    </div>

    <div v-if="!loading && jobs.length === 0" class="text-center py-16 text-gray-400">
      <p class="text-sm">暂无可管理的任务。</p>
    </div>

    <!-- 预测性维护报告调度（maintenance_report 模块自带调度器，只读展示） -->
    <div class="mb-6">
      <div class="flex items-center justify-between mb-2">
        <div class="text-xs font-semibold uppercase tracking-wider text-gray-400">预测性维护报告（只读）</div>
        <button @click="showReportModal = true"
          class="text-xs px-2.5 py-1.5 rounded bg-violet-500 text-white hover:bg-violet-600">手动生成报告</button>
      </div>
      <div class="bg-white rounded-xl border border-gray-100 shadow-sm overflow-hidden">
        <div v-if="maintenanceJobs.length" class="overflow-x-auto">
          <table class="w-full text-sm">
            <thead class="bg-gray-50">
              <tr class="text-left text-xs text-gray-500 border-b border-gray-200 whitespace-nowrap">
                <th class="py-3 px-4 font-semibold">任务</th>
                <th class="py-3 px-3 font-semibold">触发规则</th>
                <th class="py-3 px-3 font-semibold">下次运行</th>
              </tr>
            </thead>
            <tbody class="divide-y divide-gray-50">
              <tr v-for="m in maintenanceJobs" :key="m.id" class="hover:bg-gray-50/50">
                <td class="py-3 px-4 font-bold text-gray-800">{{ m.name }}</td>
                <td class="py-3 px-3 text-xs text-gray-500">{{ m.trigger || '—' }}</td>
                <td class="py-3 px-3 tabular-nums text-gray-500 text-xs">{{ formatNextRun(m.next_run) }}</td>
              </tr>
            </tbody>
          </table>
        </div>
        <div v-else class="p-4 text-xs text-gray-400">
          调度器未开启或暂无已注册的维护报告任务；仍可点右上角"手动生成报告"。
        </div>
      </div>
    </div>

    <!-- 手动生成维护报告弹窗 -->
    <div v-if="showReportModal" class="fixed inset-0 bg-black/40 z-50 flex items-center justify-center"
      @click.self="showReportModal = false">
      <div class="bg-white rounded-2xl p-8 w-full max-w-md shadow-2xl">
        <h2 class="text-lg font-bold mb-6">生成维护报告</h2>
        <div class="space-y-4">
          <div>
            <label class="block text-xs font-bold text-gray-500 uppercase tracking-widest mb-2">报告类型</label>
            <select v-model="reportForm.report_type"
              class="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-violet-400">
              <option value="daily">日报</option>
              <option value="weekly">周报</option>
              <option value="monthly">月报</option>
            </select>
          </div>
          <div>
            <label class="block text-xs font-bold text-gray-500 uppercase tracking-widest mb-2">报告日期</label>
            <input v-model="reportForm.report_date" type="date"
              class="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-violet-400" />
          </div>
        </div>
        <div v-if="reportMsg" class="mt-4 text-sm px-3 py-2 rounded-lg"
          :class="reportSuccess ? 'bg-emerald-50 text-emerald-700' : 'bg-rose-50 text-rose-700'">
          {{ reportMsg }}
        </div>
        <div class="mt-6 flex justify-end gap-3">
          <button @click="showReportModal = false"
            class="px-4 py-2 border border-gray-200 text-gray-600 text-sm rounded-lg hover:bg-gray-50">取消</button>
          <button @click="submitReport" :disabled="reportSubmitting"
            class="px-4 py-2 bg-violet-500 text-white text-sm font-bold rounded-lg hover:bg-violet-600 disabled:opacity-50">
            {{ reportSubmitting ? '提交中…' : '确认生成' }}
          </button>
        </div>
      </div>
    </div>

    <CronPickerModal :visible="!!cronModalJob" :cron="cronModalJob?.cron" :job-name="cronModalJob?.name"
      @close="cronModalJob = null" @update="onCronUpdate" />
  </div>
</template>

<script setup>
import { ref, computed, onMounted, reactive } from 'vue'
import { getSystemJobs, runSystemJob, saveSystemJobConfig, getSystemJobRuns, getScheduledJobs, triggerReportGeneration } from '../api/client.js'
import { describeCron } from '../utils/cron.js'
import CronPickerModal from '../components/CronPickerModal.vue'

const jobs = ref([])
const schedulerEnabled = ref(false)
const loading = ref(false)
const running = reactive({})
const saving = reactive({})
const expanded = reactive({})
const runsMap = reactive({})
const runsLoading = reactive({})
const notice = ref('')
const noticeErr = ref(false)
const cronModalJob = ref(null)
const maintenanceJobs = ref([])

// 手动生成维护报告
const showReportModal = ref(false)
const reportSubmitting = ref(false)
const reportMsg = ref('')
const reportSuccess = ref(false)
const reportForm = ref({
  report_type: 'daily',
  report_date: new Date().toISOString().slice(0, 10),
})

const summary = computed(() => ({
  total: jobs.value.length,
  enabled: jobs.value.filter(j => j.enabled).length,
  running: jobs.value.filter(j => j.last_run?.status === 'running').length,
  failed: jobs.value.filter(j => j.last_run?.status === 'failed').length,
}))

const grouped = computed(() => {
  const map = new Map()
  for (const j of jobs.value) {
    if (!map.has(j.group)) map.set(j.group, [])
    map.get(j.group).push(j)
  }
  return [...map.entries()].map(([name, items]) => ({ name, items }))
})

function statusCls(s) {
  if (s === '运行中') return 'bg-emerald-50 text-emerald-600'
  if (s === '未配置') return 'bg-gray-100 text-gray-400'
  if (s === '已停用') return 'bg-gray-100 text-gray-400'
  if (s === '调度器未开启') return 'bg-amber-50 text-amber-600'
  return 'bg-sky-50 text-sky-600'
}
function runCls(s) {
  if (s === 'success') return 'bg-emerald-50 text-emerald-600'
  if (s === 'failed') return 'bg-rose-50 text-rose-600'
  if (s === 'running') return 'bg-amber-50 text-amber-600'
  return 'bg-gray-100 text-gray-500'
}
function runText(s) {
  return { success: '成功', failed: '失败', running: '运行中' }[s] || s || '—'
}

async function load() {
  loading.value = true
  try {
    const res = await getSystemJobs()
    if (res.code === 200 && res.data) {
      jobs.value = res.data.jobs || []
      schedulerEnabled.value = !!res.data.scheduler_enabled
    }
  } catch (err) {
    console.error('加载任务列表失败:', err)
    notice.value = '加载任务列表失败。'
    noticeErr.value = true
  } finally {
    loading.value = false
  }
  try {
    const res = await getScheduledJobs()
    maintenanceJobs.value = res.code === 200 ? (res.data || []) : []
  } catch (err) {
    console.error('加载维护报告调度失败:', err)
    maintenanceJobs.value = []
  }
}

function formatNextRun(isoString) {
  if (!isoString) return '—'
  const date = new Date(isoString)
  if (Number.isNaN(date.getTime())) return isoString
  return date.toLocaleString('zh-CN', {
    month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit',
  })
}

async function submitReport() {
  reportSubmitting.value = true
  reportMsg.value = ''
  try {
    const res = await triggerReportGeneration({
      report_type: reportForm.value.report_type,
      report_date: reportForm.value.report_date || undefined,
    })
    if (res.code === 200) {
      reportSuccess.value = true
      reportMsg.value = '报告生成任务已提交'
      setTimeout(() => {
        showReportModal.value = false
        reportMsg.value = ''
      }, 1500)
    } else {
      reportSuccess.value = false
      reportMsg.value = res.msg || '提交失败'
    }
  } catch (err) {
    reportSuccess.value = false
    reportMsg.value = '请求错误: ' + err.message
  } finally {
    reportSubmitting.value = false
  }
}

function openCronModal(j) {
  cronModalJob.value = j
}

function onCronUpdate(newCron) {
  if (cronModalJob.value) cronModalJob.value.cron = newCron
}

async function saveJob(j) {
  saving[j.id] = true
  notice.value = ''
  noticeErr.value = false
  try {
    const res = await saveSystemJobConfig({ job_id: j.id, cron: j.cron || '', enabled: j.enabled })
    if (res.code === 200) {
      const applied = res.data?.applied
      const tip = applied === 'scheduled' ? '，已即时生效'
        : applied === 'removed' || applied === 'disabled' ? '，已停用'
        : applied === 'scheduler_not_running' ? '（调度器未开，下次启动生效）' : ''
      notice.value = `「${j.name}」已保存${tip}。`
      await load()
    } else {
      notice.value = res.msg || '保存失败'
      noticeErr.value = true
    }
  } catch (err) {
    console.error('保存任务配置失败:', err)
    notice.value = err?.response?.data?.msg || '保存失败。'
    noticeErr.value = true
  } finally {
    saving[j.id] = false
  }
}

async function runJob(j) {
  running[j.id] = true
  notice.value = ''
  noticeErr.value = false
  try {
    const res = await runSystemJob(j.id)
    if (res.code === 200) {
      notice.value = `「${j.name}」${res.data?.msg || '已触发。'}`
    } else {
      notice.value = res.msg || '触发失败'
      noticeErr.value = true
    }
  } catch (err) {
    console.error('触发任务失败:', err)
    notice.value = '触发任务失败。'
    noticeErr.value = true
  } finally {
    running[j.id] = false
  }
}

async function toggleRuns(j) {
  if (expanded[j.id]) { expanded[j.id] = false; return }
  expanded[j.id] = true
  await loadRuns(j)
}

async function loadRuns(j) {
  runsLoading[j.id] = true
  try {
    const res = await getSystemJobRuns(j.id, { limit: 20 })
    runsMap[j.id] = (res.code === 200 && res.data) ? (res.data.runs || []) : []
  } catch (err) {
    console.error('加载运行历史失败:', err)
    runsMap[j.id] = []
  } finally {
    runsLoading[j.id] = false
  }
}

onMounted(load)
</script>
