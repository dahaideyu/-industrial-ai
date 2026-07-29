<template>
  <div class="p-8 max-w-[1440px] mx-auto">
    <!-- Header -->
    <div class="mb-8 flex justify-between items-end">
      <div>
        <h1 class="font-headline text-2xl font-semibold text-on-surface">报警分析</h1>
        <p class="text-secondary text-sm mt-1">选择时间段和报告类型，执行 AI 报警分析，结果自动存库并可覆盖</p>
      </div>
    </div>

    <div class="grid grid-cols-3 gap-6">
      <!-- Left: Controls + History -->
      <div class="col-span-1 space-y-4">
        <!-- Query Panel -->
        <div class="bg-white rounded-xl border border-gray-100 shadow-sm p-6">
          <h2 class="font-headline text-lg font-semibold mb-4">分析参数</h2>
          <div class="space-y-4">
            <div>
              <label class="block text-xs font-bold text-gray-500 uppercase tracking-widest mb-2">报告类型</label>
              <div class="flex gap-2">
                <button v-for="rt in reportTypes" :key="rt.value" @click="query.report_type = rt.value"
                  :class="[
                    'flex-1 px-3 py-2 text-xs font-bold rounded-lg transition-all',
                    query.report_type === rt.value
                      ? 'bg-amber-400 text-on-primary-container'
                      : 'bg-gray-50 border border-gray-200 text-gray-600 hover:border-amber-400'
                  ]">
                  {{ rt.label }}
                </button>
              </div>
            </div>
            <div>
              <label class="block text-xs font-bold text-gray-500 uppercase tracking-widest mb-2">设备</label>
              <select v-model="query.device_id"
                class="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-amber-400">
                <option value="">全部设备</option>
                <option value="102000018415">正1#金帆球磨机</option>
                <option value="102000000996">正2#衡远合膏机</option>
              </select>
            </div>
            <div>
              <label class="block text-xs font-bold text-gray-500 uppercase tracking-widest mb-2">开始日期</label>
              <input v-model="query.start_date" type="date"
                class="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-amber-400" />
            </div>
            <div>
              <label class="block text-xs font-bold text-gray-500 uppercase tracking-widest mb-2">结束日期</label>
              <input v-model="query.end_date" type="date"
                class="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-amber-400" />
            </div>
            <button @click="runAnalysis" :disabled="loading"
              class="w-full px-4 py-3 bg-amber-400 text-on-primary-container font-bold rounded-lg hover:bg-amber-500 transition-colors disabled:opacity-50">
              {{ loading ? '分析中...' : '执行分析' }}
            </button>
          </div>
        </div>

        <!-- History List -->
        <div class="bg-white rounded-xl border border-gray-100 shadow-sm">
          <div class="px-6 py-4 bg-gray-50 border-b border-gray-100">
            <h2 class="text-sm font-bold uppercase tracking-widest text-gray-600 flex items-center justify-between">
              <span>{{ reportTypeLabel }}历史</span>
              <button @click="loadHistory" class="text-xs text-amber-600 hover:text-amber-700">刷新</button>
            </h2>
          </div>
          <div class="p-2 max-h-[400px] overflow-y-auto">
            <div v-for="item in history" :key="item.id"
              @click="loadDetail(item)"
              class="p-3 rounded-lg cursor-pointer hover:bg-amber-50 transition-colors"
              :class="selectedId === item.id ? 'bg-amber-50 border border-amber-200' : 'border border-transparent'">
              <div class="flex items-center justify-between mb-1">
                <span class="text-sm font-bold text-on-surface">{{ item.report_date }}</span>
                <span class="text-xs text-gray-400">{{ item.device_id === 'all' ? '全部' : item.device_id }}</span>
              </div>
              <div class="flex gap-3 text-xs text-gray-500">
                <span>异常: <b class="text-amber-600">{{ item.total_anomalies || 0 }}</b></span>
                <span>报警: <b class="text-red-500">{{ item.total_alarms || 0 }}</b></span>
                <span>活跃: <b class="text-orange-500">{{ item.active_alarms || 0 }}</b></span>
              </div>
            </div>
            <div v-if="historyError" class="text-center text-red-400 py-6 text-sm">{{ historyError }}</div>
            <div v-else-if="!history.length" class="text-center text-gray-400 py-6 text-sm">暂无历史报告</div>
          </div>
        </div>
      </div>

      <!-- Right: Results -->
      <div class="col-span-2">
        <!-- Loading -->
        <div v-if="loading" class="bg-white rounded-xl border border-gray-100 shadow-sm p-12 text-center text-gray-400">
          <div class="text-2xl mb-2">⏳</div>
          <p>正在执行报警分析，请稍候...</p>
        </div>

        <!-- Error -->
        <div v-else-if="error" class="bg-white rounded-xl border border-gray-100 shadow-sm p-12 text-center text-red-400">
          <div class="text-2xl mb-2">❌</div>
          <p>{{ error }}</p>
        </div>

        <!-- Results -->
        <template v-else-if="result">
          <!-- Saved badge -->
          <div v-if="result.saved" class="mb-4 px-4 py-2 bg-green-50 border border-green-200 rounded-lg text-sm text-green-700 flex items-center gap-2">
            <span>✓</span> 已保存为{{ reportTypeLabel }}（{{ result.report_date }}），重复执行同日期将覆盖
          </div>

          <!-- Statistics Cards -->
          <div class="grid grid-cols-4 gap-4 mb-6">
            <div class="bg-white rounded-xl p-4 border border-gray-100 shadow-sm">
              <div class="text-xs font-bold text-gray-500 uppercase tracking-widest mb-2">总报警数</div>
              <div class="text-3xl font-headline font-bold text-on-surface">{{ result.statistics?.total || 0 }}</div>
            </div>
            <div class="bg-white rounded-xl p-4 border border-gray-100 shadow-sm border-l-4 border-l-red-400">
              <div class="text-xs font-bold text-gray-500 uppercase tracking-widest mb-2">活跃报警</div>
              <div class="text-3xl font-headline font-bold text-red-500">{{ result.statistics?.active || 0 }}</div>
            </div>
            <div class="bg-white rounded-xl p-4 border border-gray-100 shadow-sm">
              <div class="text-xs font-bold text-gray-500 uppercase tracking-widest mb-2">异常检测</div>
              <div class="text-3xl font-headline font-bold text-amber-600">{{ result.analysis?.total_anomalies || 0 }}</div>
            </div>
            <div class="bg-white rounded-xl p-4 border border-gray-100 shadow-sm">
              <div class="text-xs font-bold text-gray-500 uppercase tracking-widest mb-2">报警预测</div>
              <div class="text-3xl font-headline font-bold text-purple-600">{{ result.analysis?.alarm_predictions || 0 }}</div>
            </div>
          </div>

          <div class="grid grid-cols-2 gap-6 mb-6">
            <!-- Alarm Type Top10 -->
            <div class="bg-white rounded-xl border border-gray-100 shadow-sm">
              <div class="px-5 py-3 bg-gray-50 border-b border-gray-100">
                <h2 class="text-xs font-bold uppercase tracking-widest text-gray-600">报警类型 Top10</h2>
              </div>
              <div class="p-3">
                <div v-for="(item, idx) in (result.statistics?.by_type || []).slice(0, 10)" :key="idx"
                  class="flex items-center justify-between py-1.5 border-b border-gray-50 last:border-0">
                  <div class="flex items-center gap-2">
                    <span class="text-xs font-bold w-4 text-gray-400">{{ idx + 1 }}</span>
                    <span class="text-sm text-on-surface">{{ item.alarm_name || item.point_id }}</span>
                  </div>
                  <span class="text-sm font-bold text-amber-600">{{ item.count }}</span>
                </div>
                <div v-if="!result.statistics?.by_type?.length" class="text-center text-gray-400 py-3 text-sm">暂无数据</div>
              </div>
            </div>

            <!-- Severity Distribution -->
            <div class="bg-white rounded-xl border border-gray-100 shadow-sm">
              <div class="px-5 py-3 bg-gray-50 border-b border-gray-100">
                <h2 class="text-xs font-bold uppercase tracking-widest text-gray-600">异常严重程度分布</h2>
              </div>
              <div class="p-4">
                <div class="space-y-3">
                  <div v-for="(label, key) in severityLabels" :key="key">
                    <div class="flex justify-between items-center mb-1">
                      <span class="text-sm text-gray-600">{{ label }}</span>
                      <span class="text-sm font-bold" :class="severityColors[key]">{{ result.analysis?.severity_distribution?.[key] || 0 }}</span>
                    </div>
                    <div class="w-full bg-gray-100 rounded-full h-2">
                      <div class="h-2 rounded-full transition-all duration-500" :class="severityBgColors[key]"
                        :style="{ width: severityWidth(key) + '%' }"></div>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </div>

          <!-- Hourly Trend -->
          <div v-if="result.statistics?.hourly_trend?.length" class="bg-white rounded-xl border border-gray-100 shadow-sm mb-6">
            <div class="px-5 py-3 bg-gray-50 border-b border-gray-100">
              <h2 class="text-xs font-bold uppercase tracking-widest text-gray-600">报警小时趋势</h2>
            </div>
            <div class="p-4">
              <div class="flex items-end gap-1 h-28">
                <div v-for="(item, idx) in result.statistics.hourly_trend" :key="idx"
                  class="flex-1 bg-amber-400 rounded-t hover:bg-amber-500 transition-colors"
                  :style="{ height: trendHeight(item.count) + '%' }"
                  :title="item.hour + '时: ' + item.count + '次'">
                </div>
              </div>
              <div class="flex gap-1 mt-1">
                <div v-for="(item, idx) in result.statistics.hourly_trend" :key="idx"
                  class="flex-1 text-center text-[9px] text-gray-400">{{ item.hour }}h</div>
              </div>
            </div>
          </div>

          <!-- AI Analysis Details -->
          <div class="bg-white rounded-xl border border-gray-100 shadow-sm">
            <div class="px-5 py-3 bg-gray-50 border-b border-gray-100">
              <h2 class="text-xs font-bold uppercase tracking-widest text-gray-600">AI 分析详情</h2>
            </div>
            <div class="p-4">
              <pre class="text-xs font-mono bg-gray-50 p-4 rounded-lg whitespace-pre-wrap max-h-[400px] overflow-auto">{{ formattedAnalysis }}</pre>
            </div>
          </div>
        </template>

        <!-- Empty State -->
        <div v-else class="bg-white rounded-xl border border-gray-100 shadow-sm p-12 text-center text-gray-400">
          <div class="text-2xl mb-2">🔍</div>
          <p>选择参数并点击"执行分析"，或从左侧历史列表查看</p>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, watch } from 'vue'
import { runAlarmAnalysis, getAlarmAnalysisHistory, getAlarmAnalysisDetail } from '../api/client.js'

const reportTypes = [
  { value: 'daily', label: '日报' },
  { value: 'weekly', label: '周报' },
  { value: 'monthly', label: '月报' },
]

const query = ref({
  device_id: '',
  start_date: '',
  end_date: '',
  report_type: 'daily'
})

const loading = ref(false)
const error = ref('')
const result = ref(null)
const history = ref([])
const historyError = ref('')
const selectedId = ref(null)

const severityLabels = { '严重': '严重', '高': '高', '中': '中', '低': '低' }
const severityColors = { '严重': 'text-red-600', '高': 'text-orange-600', '中': 'text-amber-600', '低': 'text-blue-600' }
const severityBgColors = { '严重': 'bg-red-500', '高': 'bg-orange-500', '中': 'bg-amber-500', '低': 'bg-blue-500' }

const reportTypeLabel = computed(() => {
  const rt = reportTypes.find(r => r.value === query.value.report_type)
  return rt ? rt.label : '日报'
})

const formattedAnalysis = computed(() => {
  if (!result.value?.analysis) return ''
  return JSON.stringify(result.value.analysis, null, 2)
})

function severityWidth(key) {
  const dist = result.value?.analysis?.severity_distribution
  if (!dist) return 0
  const total = Object.values(dist).reduce((a, b) => a + b, 0)
  return total > 0 ? ((dist[key] || 0) / total) * 100 : 0
}

function trendHeight(count) {
  const trend = result.value?.statistics?.hourly_trend
  if (!trend || !trend.length) return 0
  const max = Math.max(...trend.map(t => t.count), 1)
  return (count / max) * 100
}

async function runAnalysis() {
  loading.value = true
  error.value = ''
  result.value = null

  try {
    const params = {
      report_type: query.value.report_type
    }
    if (query.value.device_id) params.device_id = query.value.device_id
    if (query.value.start_date) params.start_date = query.value.start_date
    if (query.value.end_date) params.end_date = query.value.end_date

    const res = await runAlarmAnalysis(params)
    if (res.code === 200) {
      result.value = res.data
      selectedId.value = null
      loadHistory()
    } else {
      error.value = res.msg || '分析失败'
    }
  } catch (err) {
    error.value = err.response
      ? ('请求错误: ' + (err.response.data?.msg || err.message))
      : '连不上后端服务，请检查后端是否正常运行。'
  } finally {
    loading.value = false
  }
}

async function loadHistory() {
  historyError.value = ''
  try {
    const res = await getAlarmAnalysisHistory({ report_type: query.value.report_type, limit: 50 })
    if (res.code === 200) {
      history.value = res.data || []
    } else {
      history.value = []
      historyError.value = res.msg || '加载历史失败'
    }
  } catch (err) {
    console.error('加载历史失败:', err)
    history.value = []
    historyError.value = err.response ? (err.response.data?.msg || err.message) : '连不上后端服务'
  }
}

async function loadDetail(item) {
  selectedId.value = item.id
  try {
    const params = {
      report_type: query.value.report_type,
      report_date: item.report_date
    }
    if (item.device_id && item.device_id !== 'all') params.device_id = item.device_id

    const res = await getAlarmAnalysisDetail(params)
    if (res.code === 200 && res.data) {
      result.value = {
        statistics: res.data.statistics,
        analysis: res.data.analysis,
        query: res.data.query_params,
        report_type: query.value.report_type,
        report_date: res.data.report_date,
        saved: true
      }
      error.value = ''
    } else {
      error.value = res.msg || '加载详情失败'
    }
  } catch (err) {
    console.error('加载详情失败:', err)
    error.value = err.response ? (err.response.data?.msg || err.message) : '连不上后端服务，请检查后端是否正常运行。'
  }
}

watch(() => query.value.report_type, () => {
  loadHistory()
  result.value = null
})

onMounted(() => {
  loadHistory()
})
</script>
