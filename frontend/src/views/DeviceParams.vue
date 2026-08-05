<template>
  <div class="p-8 max-w-[1440px] mx-auto">
    <!-- Header -->
    <div class="mb-6 flex justify-between items-end">
      <div>
        <h1 class="font-headline text-2xl font-semibold text-on-surface">设备参数监控</h1>
        <p class="text-secondary text-sm mt-1">选择设备查看各参数实时趋势曲线</p>
      </div>
    </div>

    <!-- Filters -->
    <div class="bg-white rounded-xl border border-gray-100 shadow-sm p-5 mb-6">
      <div class="flex flex-wrap items-end gap-4">
        <div class="min-w-[220px] flex-1 max-w-sm">
          <label class="block text-xs font-bold text-gray-500 uppercase tracking-widest mb-2">设备</label>
          <select
            v-model="selectedDevice"
            @change="onDeviceChange"
            class="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-amber-400 bg-white"
          >
            <option value="">请选择设备</option>
            <option v-for="d in devices" :key="d.device_code" :value="d.device_code">
              {{ d.device_name || d.device_code }}
            </option>
          </select>
        </div>

        <div>
          <label class="block text-xs font-bold text-gray-500 uppercase tracking-widest mb-2">
            时间范围 <span class="text-gray-300 normal-case font-normal">（≤ 30 天）</span>
          </label>
          <div class="flex items-center gap-2">
            <input
              v-model="startTime"
              @change="onRangeInputChange"
              type="datetime-local"
              class="px-3 py-2 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-amber-400 bg-white"
            />
            <span class="text-gray-400">~</span>
            <input
              v-model="endTime"
              @change="onRangeInputChange"
              type="datetime-local"
              class="px-3 py-2 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-amber-400 bg-white"
            />
          </div>
        </div>

        <button
          @click="loadData"
          :disabled="loading || !selectedDevice"
          class="px-5 py-2 bg-amber-400 text-on-primary-container text-sm font-bold rounded-lg hover:bg-amber-500 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {{ loading ? '加载中...' : '查询' }}
        </button>

        <label class="flex items-center gap-2 px-3 py-2 bg-white border border-gray-200 rounded-lg cursor-pointer hover:border-gray-300">
          <input
            v-model="analyzeRunningOnly"
            type="checkbox"
            class="w-4 h-4 text-amber-500 focus:ring-amber-500 border-gray-300 rounded"
          />
          <span class="text-sm text-gray-700">仅分析运行状态的数据</span>
        </label>
        <button
          v-if="seriesKeys.length > 0"
          @click="startAnalysis"
          :disabled="analyzing"
          class="px-5 py-2 bg-violet-500 text-white text-sm font-bold rounded-lg hover:bg-violet-600 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {{ analyzing ? '分析中...' : 'AI 分析' }}
        </button>
        <button
          v-if="seriesKeys.length > 0"
          @click="toggleAnalysisLog"
          class="px-3 py-2 bg-white text-violet-600 text-sm font-medium rounded-lg border border-violet-200 hover:bg-violet-50 transition-colors"
        >
          历史{{ showAnalysisLog ? ' ▴' : ' ▾' }}
        </button>

      </div>
    </div>

    <!-- 工作流 Tab（原弹窗内容已全部内联到各 tab 下）-->
    <div class="bg-white rounded-xl border border-gray-100 shadow-sm px-5 py-2 mb-6">
      <div class="flex flex-wrap items-center gap-2">
        <button
          v-for="(s, i) in WORKFLOW_STEPS" :key="s.key"
          @click="onStepClick(i + 1)"
          :title="s.desc"
          class="px-3 py-1.5 text-xs rounded-md transition-colors"
          :class="activeStep === i + 1 ? 'bg-white text-gray-900 font-bold shadow-sm' : 'text-gray-500 hover:text-gray-700'"
        >{{ s.label }}</button>

        <template v-if="activeStep === 1">
          <span class="text-gray-200 mx-1">|</span>
          <button @click="chartMode='stack'; updateChart()"
            class="px-1.5 py-0.5 text-[11px] rounded transition-colors"
            :class="chartMode === 'stack' ? 'text-gray-700 font-bold' : 'text-gray-400 hover:text-gray-600'">分列</button>
          <button @click="chartMode='overlay'; updateChart()"
            class="px-1.5 py-0.5 text-[11px] rounded transition-colors"
            :class="chartMode === 'overlay' ? 'text-gray-700 font-bold' : 'text-gray-400 hover:text-gray-600'">叠加</button>
        </template>
      </div>
      <template v-if="activeStep === 1 && rangeWarning">
        <span class="text-xs text-amber-600 ml-2">⚠ {{ rangeWarning }}</span>
      </template>
    </div>

    <!-- 分析单位选择：班次(白班06-18 / 晚班18-06)与天(06:00~次日06:00)都是一等分析单位，
         结果都按整体(①状态&效率②能耗③KPI④阶段 四个Tab一起)落库缓存，选哪个块就整体展示哪个的结果。
         已分析过的直接读库；进行中的标"进行中"，后端拒绝分析(数据未定型)。 -->
    <div v-if="selectedDevice && (shiftList.length || dayList.length)" class="bg-white rounded-xl border border-gray-100 shadow-sm px-4 py-3 mb-4">
      <div class="flex items-center justify-between mb-2 flex-wrap gap-2">
        <span class="text-xs font-bold text-gray-400 uppercase tracking-wider">
          分析单位 — 班次/天二选一，点选后四个 Tab 整体切换到该单位的结果
        </span>
        <div class="flex items-center gap-2">
          <span v-if="currentShiftMeta?.cacheInfo" class="text-[11px] text-gray-400">{{ currentShiftMeta.cacheInfo }}</span>
          <button @click="reanalyzeShift" :disabled="shiftAnalyzing"
                  class="px-2.5 py-1 text-xs rounded-lg border border-indigo-200 text-indigo-600 hover:bg-indigo-50 disabled:opacity-50">
            {{ shiftAnalyzing ? '分析中…' : '🤖 重新分析' }}
          </button>
        </div>
      </div>

      <div v-if="shiftList.length" class="mb-2">
        <div class="text-[10px] text-gray-400 mb-1">班次 — 共 {{ shiftList.length }} 个</div>
        <div class="flex gap-1.5 overflow-x-auto pb-1">
          <button v-for="s in shiftList" :key="s.key" @click="selectShift(s.key)"
                  class="shrink-0 px-2.5 py-1.5 rounded-lg text-xs border transition-colors"
                  :class="s.key === selectedShiftKey
                    ? 'bg-indigo-600 text-white border-indigo-600'
                    : 'bg-white text-gray-600 border-gray-200 hover:border-indigo-300'">
            {{ s.label }}
            <span v-if="!s.closed" class="ml-1 text-[10px]" :class="s.key === selectedShiftKey ? 'text-indigo-100' : 'text-amber-500'">进行中</span>
            <span v-else-if="s.partial" class="ml-1 text-[10px]" :class="s.key === selectedShiftKey ? 'text-indigo-100' : 'text-gray-400'">不完整</span>
          </button>
        </div>
      </div>

      <div v-if="dayList.length">
        <div class="text-[10px] text-gray-400 mb-1">天(06:00~次日06:00) — 共 {{ dayList.length }} 个</div>
        <div class="flex gap-1.5 overflow-x-auto pb-1">
          <button v-for="d in dayList" :key="d.key" @click="selectShift(d.key)"
                  class="shrink-0 px-2.5 py-1.5 rounded-lg text-xs border transition-colors"
                  :class="d.key === selectedShiftKey
                    ? 'bg-teal-600 text-white border-teal-600'
                    : 'bg-white text-gray-600 border-gray-200 hover:border-teal-300'">
            {{ d.label }}
            <span v-if="!d.closed" class="ml-1 text-[10px]" :class="d.key === selectedShiftKey ? 'text-teal-100' : 'text-amber-500'">进行中</span>
            <span v-else-if="d.partial" class="ml-1 text-[10px]" :class="d.key === selectedShiftKey ? 'text-teal-100' : 'text-gray-400'">不完整</span>
          </button>
        </div>
      </div>

      <div v-if="currentShiftMeta?.note" class="mt-2 text-[11px] text-amber-600">⚠ {{ currentShiftMeta.note }}</div>
    </div>

    <div v-if="!selectedDevice" class="text-center py-16 text-gray-400 bg-white rounded-xl border border-gray-100 shadow-sm">
      <div class="text-4xl mb-3">🔧</div>
      <p class="text-sm">请从上方选择设备</p>
    </div>

    <!-- ① 状态：设备状态划分 + 原始参数曲线 -->
    <div v-else-if="activeStep === 1" class="space-y-6">
      <StateCard ref="stateCardRef" :state-result="stateResult" :pulse-param-display="pulseParam ? (displayNames[pulseParam] || pulseParam) : ''" />

      <!-- 原始参数曲线 -->
      <div v-if="loading" class="text-center py-16 text-gray-400">
        <div class="text-3xl mb-3 animate-spin">⏳</div>
        <p>正在加载参数数据...</p>
      </div>
      <div v-else-if="seriesKeys.length === 0" class="text-center py-16 text-gray-400 bg-white rounded-xl border border-gray-100 shadow-sm">
        <div class="text-4xl mb-3">📉</div>
        <p class="text-sm">该时间段内暂无参数数据</p>
      </div>
      <div v-else class="bg-white rounded-xl border border-gray-100 shadow-sm p-5">
        <div class="flex items-center justify-between mb-3 flex-wrap gap-2">
          <div class="flex items-center gap-3 flex-wrap">
            <span class="text-xs font-bold text-gray-400 uppercase tracking-wider">参数趋势</span>
            <label v-if="runningPeriods.length > 0" class="flex items-center gap-1.5 cursor-pointer select-none" title="只显示设备运行(code 1)时段内的数据点">
              <input type="checkbox" v-model="showRunningOnly" @change="onRunningOnlyToggle" class="sr-only peer" />
              <span class="w-8 h-4 rounded-full bg-gray-200 peer-checked:bg-green-500 transition-colors relative after:content-[''] after:absolute after:top-0.5 after:left-0.5 after:w-3 after:h-3 after:rounded-full after:bg-white after:transition-transform peer-checked:after:translate-x-4"></span>
              <span class="text-xs text-gray-500">仅运行状态</span>
            </label>
            <span v-if="runningPeriods.length > 0" class="flex items-center gap-1 text-xs text-green-600">
              <span class="inline-block w-4 h-1.5 rounded-sm bg-green-400/40"></span>
              绿色区域 = 运行时段
            </span>
            <!-- 告警叠加开关 -->
            <label class="flex items-center gap-1.5 cursor-pointer select-none">
              <input type="checkbox" v-model="showAlarmOverlay" @change="onAlarmOverlayToggle" class="sr-only peer" />
              <span class="w-8 h-4 rounded-full bg-gray-200 peer-checked:bg-red-400 transition-colors relative after:content-[''] after:absolute after:top-0.5 after:left-0.5 after:w-3 after:h-3 after:rounded-full after:bg-white after:transition-transform peer-checked:after:translate-x-4"></span>
              <span class="text-xs text-gray-500">告警叠加</span>
            </label>
            <!-- 告警计数窗口 -->
            <select v-if="showAlarmOverlay" v-model="alarmWindowMin" @change="reloadAlignedData" class="text-xs px-2 py-1 border border-gray-200 rounded bg-white">
              <option :value="5">5分钟窗口</option>
              <option :value="15">15分钟窗口</option>
              <option :value="30">30分钟窗口</option>
              <option :value="60">60分钟窗口</option>
            </select>
            <!-- 异常检测开关 -->
            <label class="flex items-center gap-1.5 cursor-pointer select-none">
              <input type="checkbox" v-model="showAnomalyDetection" @change="onAnomalyToggle" class="sr-only peer" />
              <span class="w-8 h-4 rounded-full bg-gray-200 peer-checked:bg-purple-400 transition-colors relative after:content-[''] after:absolute after:top-0.5 after:left-0.5 after:w-3 after:h-3 after:rounded-full after:bg-white after:transition-transform peer-checked:after:translate-x-4"></span>
              <span class="text-xs text-gray-500">异常检测</span>
            </label>
            <select v-if="showAnomalyDetection" v-model="anomalyContamination" class="text-xs px-2 py-1 border border-gray-200 rounded bg-white">
              <option :value="0.01">敏感度: 高</option>
              <option :value="0.05">敏感度: 中</option>
              <option :value="0.10">敏感度: 低</option>
            </select>
          </div>
          <span class="text-xs text-gray-400">
            {{ visibleKeys.length }} / {{ seriesKeys.length }} 个参数
            <span v-if="aggInterval" class="ml-1 text-amber-600 bg-amber-50 px-1.5 py-0.5 rounded">
              已按 {{ aggInterval }} 聚合
            </span>
          </span>
        </div>

        <!-- 告警类型筛选 -->
        <div v-if="showAlarmOverlay && alarmEvents.length > 0" class="flex flex-wrap gap-1.5 mb-3">
          <span class="text-xs text-gray-400 mr-1 self-center">告警类型:</span>
          <button
            v-for="(meta, code) in ALARM_STATUS_META"
            :key="code"
            @click="toggleAlarmType(Number(code))"
            class="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs border transition-all"
            :class="alarmTypeFilter.includes(Number(code))
              ? 'text-white border-transparent'
              : 'bg-gray-50 text-gray-400 border-gray-200 hover:border-gray-300'"
            :style="alarmTypeFilter.includes(Number(code)) ? { backgroundColor: meta.color, borderColor: meta.color } : {}"
          >
            <span class="w-2 h-2 rounded-full flex-shrink-0"
              :style="{ backgroundColor: alarmTypeFilter.includes(Number(code)) ? '#fff' : meta.color }"
            ></span>
            {{ meta.name }}
          </button>
          <button @click="alarmTypeFilter = []" class="text-xs text-gray-400 hover:text-gray-600 ml-1">清除</button>

          <!-- 告警数据状态提示 -->
          <span v-if="alarmEvents.length === 0" class="text-xs text-gray-400 ml-2">
            ✓ 告警叠加已开启 · 此时间段内<strong class="text-green-600">无告警记录</strong>（设备运行平稳）
          </span>
          <span v-else class="text-xs text-gray-400 ml-2">
            共 <strong>{{ alarmEvents.length }}</strong> 条状态事件
            <span v-if="alarmEventsByType(2).length > 0" class="text-red-500 ml-1">{{ alarmEventsByType(2).length }} 条报警</span>
            <span v-if="alarmEventsByType(3).length > 0" class="text-amber-500 ml-1">{{ alarmEventsByType(3).length }} 条待机</span>
          </span>
        </div>

        <!-- 异常检测摘要 -->
        <div v-if="showAnomalyDetection && anomalySummary" class="flex items-center gap-4 my-2 p-3 rounded-lg text-xs"
          :class="anomalySummary.avg_health >= 85 ? 'bg-green-50 border border-green-200' : anomalySummary.avg_health >= 60 ? 'bg-amber-50 border border-amber-200' : 'bg-red-50 border border-red-200'">
          <div class="flex items-center gap-2">
            <span class="text-lg">{{ anomalySummary.avg_health >= 85 ? '🟢' : anomalySummary.avg_health >= 60 ? '🟡' : '🔴' }}</span>
            <div>
              <div class="font-bold text-sm" :class="anomalySummary.avg_health >= 85 ? 'text-green-700' : anomalySummary.avg_health >= 60 ? 'text-amber-700' : 'text-red-700'">
                健康指数 {{ anomalySummary.avg_health }} / 100
              </div>
              <div class="text-gray-500 mt-0.5">
                最低 {{ anomalySummary.min_health }} · 异常占比 {{ (anomalySummary.anomaly_ratio * 100).toFixed(1) }}%
                · {{ anomalySummary.anomaly_periods?.length || 0 }} 个异常时段
              </div>
            </div>
          </div>
          <div class="flex gap-2 ml-auto">
            <span class="px-2 py-0.5 rounded-full bg-white text-gray-500 border border-gray-200">
              IQR {{ Object.keys(iqrThresholds).length }} 参数
            </span>
            <span v-if="anomalyDetecting" class="px-2 py-0.5 rounded-full bg-purple-50 text-purple-600 border border-purple-200 animate-pulse">
              检测中...
            </span>
          </div>
        </div>

        <div class="flex flex-wrap gap-1.5 mb-4 max-h-[120px] overflow-y-auto py-1">
          <button
            v-for="(key, idx) in seriesKeys"
            :key="key"
            @click="toggleSeries(key)"
            class="inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-xs font-medium transition-all border"
            :class="[
              visibleKeys.includes(key)
                ? 'text-white border-transparent'
                : LOADED_POINT_NAMES.has(key)
                  ? 'bg-gray-50 text-gray-400 border-gray-200 hover:border-gray-300'
                  : 'bg-gray-100 text-gray-300 border-gray-200 hover:border-gray-300',
              !LOADED_POINT_NAMES.has(key) ? 'opacity-60' : ''
            ]"
            :style="visibleKeys.includes(key) ? { backgroundColor: SERIES_COLORS[idx % SERIES_COLORS.length], borderColor: SERIES_COLORS[idx % SERIES_COLORS.length] } : {}"
          >
            <span class="w-2 h-2 rounded-full flex-shrink-0"
              :style="{ backgroundColor: visibleKeys.includes(key) ? '#fff' : SERIES_COLORS[idx % SERIES_COLORS.length] }"
            ></span>
            {{ displayNames[key] || key }}<span v-if="paramUnits[key]" class="opacity-60 ml-0.5">{{ paramUnits[key] }}</span>
            <span v-if="!LOADED_POINT_NAMES.has(key)" class="opacity-50 ml-0.5">未加载</span>
          </button>
          <button
            v-if="seriesKeys.length > 1"
            @click="toggleAll"
            class="inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-xs font-medium border transition-all"
            :class="visibleKeys.length === seriesKeys.length
              ? 'bg-gray-800 text-white border-gray-800'
              : 'bg-gray-50 text-gray-500 border-gray-200 hover:border-gray-300'"
          >
            {{ visibleKeys.length === seriesKeys.length ? '全部取消' : '全部显示' }}
          </button>
        </div>

        <div ref="chartContainer" class="w-full" :style="{ height: chartHeight }"></div>
      </div>

      <!-- 效率（与状态同一数据源：资产利用率 vs 设备运转率）-->
      <EfficiencyCard :state-result="stateResult" />
    </div>

    <!-- ② 能耗：按房子(合膏生产周期)列每房子能耗，拆解房内各阶段能耗 -->
    <div v-else-if="activeStep === 2" class="space-y-6">
      <!-- 日期范围跨度 > 1 天时，先看按天(06:00~次日06:00)独立掐头去尾的多日汇总 -->
      <EnergyDayTrend v-if="isMultiDayRange" :result="dayTrendResult" :loading="dayTrendLoading" />
      <EnergyBreakdown ref="energyBreakdownRef" :energy-result="energyResult" />
    </div>

    <!-- ③ KPI：产量/OEE/节拍/能耗 -->
    <KpiPanel v-else-if="activeStep === 3" :kpi-result="kpiResult" :device-code="selectedDevice"
              @reload="loadShiftAnalysis(true, ['kpi'])" />

    <!-- ④ 阶段：阶段分析 + CPK/公差/能耗逐段 -->
    <div v-else-if="activeStep === 4" class="space-y-6">
      <StageCpkPanel :stage-cpk-result="stageCpkResult" />

      <!-- 阶段配方/周期排列/跨周期对比：跟其它3个Tab一样吃选中班次/天的缓存结果 -->
      <StageAnalysis :stage-result="stageAnalysisResult"
                     @reload="loadShiftAnalysis(true, ['stage_recipe'])" />
    </div>
    <!-- AI Analysis History（所有 tab 可见）-->
    <AiAnalysisLog :visible="showAnalysisLog" :loading="analysisLogLoading" :items="analysisLogItems" @select="viewAnalysisLogItem" />
    <!-- AI Analysis Modal -->
    <AiAnalysisModal :result="analysisResult" :meta="analysisResultMeta" :error="analysisError"
      :html="analysisResultHtml" :analyzing="analyzing" :start-time="startTime" :end-time="endTime"
      :analyze-running-only="analyzeRunningOnly" @close="analysisResult = ''; analysisResultMeta = ''; analysisError = ''"
      @reanalyze="startAnalysis()" />
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted, nextTick, watch } from 'vue'
import { useRoute } from 'vue-router'
import * as echarts from 'echarts'
import client from '../api/client.js'
import {
  getDeviceParamData,
  getRunningPeriods,
  getAlignedData,
  detectAnomalies,
  analyzeDeviceParams,
  getAnalysisLog,
  getDeviceParamPoints,
} from '../api/client.js'
import StageAnalysis from './StageAnalysis.vue'
import AiAnalysisModal from './device_params/AiAnalysisModal.vue'
import AiAnalysisLog from './device_params/AiAnalysisLog.vue'
import EnergyBreakdown from './device_params/EnergyBreakdown.vue'
import EnergyDayTrend from './device_params/EnergyDayTrend.vue'
import KpiPanel from './device_params/KpiPanel.vue'
import StageCpkPanel from './device_params/StageCpkPanel.vue'
import StateCard from './device_params/StateCard.vue'
import EfficiencyCard from './device_params/EfficiencyCard.vue'
import { marked } from 'marked'

const route = useRoute()
const energyBreakdownRef = ref(null)
const stateCardRef = ref(null)
const devices = ref([])
const selectedDevice = ref('')
const loading = ref(false)
const seriesData = ref({})
const seriesKeys = ref([])
const visibleKeys = ref([])
const displayNames = ref({})  // p_name code -> Chinese display name
const paramUnits = ref({})    // p_name code -> unit string
const chartContainer = ref(null)
const runningPeriods = ref([])
const analyzing = ref(false)
const analysisResult = ref('')
const analysisResultMeta = ref('')
const analysisError = ref('')
const analyzeRunningOnly = ref(true)
const showAnalysisLog = ref(false)
const analysisLogLoading = ref(false)
const analysisLogItems = ref([])
const workflowStep = ref(0)
const pulseParam = ref('')
const stateResult = ref(null)
const kpiResult = ref(null)
// ── 状态切片图（运行/非运行/离线 时间轴）：渲染逻辑已提取到 StateCard.vue，
// 父组件只在 tab 切换/数据重置的关键时机调用 ref 暴露的 render/dispose ──

const stageCpkResult = ref(null)
// ④阶段Tab里独立的"配方总览/周期排列/跨周期对比"组件用的结果，跟 stageCpkResult
// (阶段CPK/公差/能耗逐段) 是两个不同的分析类型(stage_recipe vs stage)，分开存
const stageAnalysisResult = ref(null)

// ── ② 能耗 Tab ──
// 能耗渲染逻辑已提取到 EnergyBreakdown.vue 组件；父组件只保留数据管线：
// energyResult 由 API/班次分析写入，selectedEnergyPoints 用于检测勾选变化重拉。
const ENERGY_POINTS = ['ene_eptotal', 'ene_imp']
const energyResult = ref(null)
let _lastEnergySel = ''
const selectedEnergyPoints = computed(() => ENERGY_POINTS.filter(p => visibleKeys.value.includes(p)))

// 多日汇总：日期范围跨度 > 1 天时，按天(06:00~次日06:00)读已存的天粒度能耗结果，
// 而不是只看单个班次——天粒度独立掐头去尾，见 shift.py full_days_in_range()。
const dayTrendResult = ref(null)
const dayTrendLoading = ref(false)
const isMultiDayRange = computed(() => rangeDays.value > 1)

async function loadDayTrend() {
  if (!selectedDevice.value || !pulseParam.value || !isMultiDayRange.value) {
    dayTrendResult.value = null
    return
  }
  dayTrendLoading.value = true
  try {
    const res = await client.post('/device-params/day-analysis', {
      device_code: selectedDevice.value,
      device_name: currentDeviceName(),
      pulse_param: pulseParam.value,
      start_time: formatForApi(startTime.value),
      end_time: formatForApi(endTime.value),
      analysis_types: ['energy'],
      selected_points: selectedEnergyPoints.value,
    }, { timeout: 0 })
    dayTrendResult.value = (res.code === 200) ? res.data : null
  } catch (e) {
    dayTrendResult.value = null
  } finally {
    dayTrendLoading.value = false
  }
}

const rangeDays = computed(() => {
  const diffMs = new Date(endTime.value) - new Date(startTime.value)
  return Math.max(1, Math.round(diffMs / 86400000))
})

// 四个 tab 对应四个分析步骤，内容直接内联展示（不再用弹窗）
// ①状态&效率（同源数据）②能耗 ③KPI ④阶段
const WORKFLOW_STEPS = [
  { key: 'state', label: '①状态&效率', desc: '运行/待机/离线划分 + 资产利用率 vs 设备运转率' },
  { key: 'energy', label: '②能耗', desc: '按房子(生产周期)列每房子能耗，拆解房内各阶段能耗' },
  { key: 'kpi', label: '③KPI', desc: '产量/OEE/单件能耗/合格率' },
  { key: 'stage', label: '④阶段', desc: '按脉搏切段，CPK/公差/能耗逐段分析' },
]
const analysisResultHtml = computed(() => {
  if (!analysisResult.value) return ''
  return marked(analysisResult.value)
})

// ── 仅运行状态过滤（图表/特征视图显示用，独立于 AI 分析的 analyzeRunningOnly）──
const showRunningOnly = ref(false)

// ── 告警叠加状态 ──
const showAlarmOverlay = ref(false)
const alarmEvents = ref([])
const alignedRows = ref([])
const paramsMeta = ref({})
const alarmWindowMin = ref(15)
const alarmTypeFilter = ref([])  // 选中的告警类型 status code 列表
const ALARM_STATUS_META = {
  2: { name: '报警', color: '#ef4444', bg: 'rgba(239,68,68,0.12)' },
  3: { name: '待机', color: '#f59e0b', bg: 'rgba(245,158,11,0.10)' },
  4: { name: '调试', color: '#3b82f6', bg: 'rgba(59,130,246,0.10)' },
  5: { name: '上下料', color: '#ec4899', bg: 'rgba(236,72,153,0.10)' },
  6: { name: '待料', color: '#f97316', bg: 'rgba(249,115,22,0.10)' },
  7: { name: '等待', color: '#ef4444', bg: 'rgba(239,68,68,0.08)' },
}

// ── 异常检测状态 ──
const showAnomalyDetection = ref(false)
const anomalyDetecting = ref(false)
const healthTimeline = ref([])
const anomalySummary = ref(null)
const iqrThresholds = ref({})
const anomalyContamination = ref(0.05)

// ── 特征视图状态 ──
const activeStep = ref(1)   // 1=状态 2=效率 3=KPI 4=阶段

// 大跨度聚合：非空表示当前参数视图数据已按该粒度聚合（如 '15min'/'1hour'）
const aggInterval = ref('')

let chartInstance = null
let resizeHandler = null

const chartHeight = computed(() => {
  // 只计算已加载数据的可见参数
  const loadedVisibleKeys = visibleKeys.value.filter(k => seriesData.value[k])
  if (chartMode.value === 'overlay') {
    // 叠加模式：频带 + N个分组 × 220px
    const groups = groupParams(loadedVisibleKeys)
    const groupCount = Object.keys(groups).length || 1
    const bands = (runningPeriods.value.length > 0 ? 40 : 0) +
                  (showAnomalyDetection.value && healthTimeline.value.length > 0 ? 48 : 0) +
                  (showAlarmOverlay.value && alarmEvents.value.length > 0 ? 42 : 0)
    return Math.max(bands + groupCount * 220 + 72, 400) + 'px'
  }
  // 分列模式
  const count = loadedVisibleKeys.length || 1
  const hasStatus = runningPeriods.value.length > 0
  const needed = (hasStatus ? 44 : 8) + count * 80 + 72 + count * 4
  return Math.max(needed, 500) + 'px'
})

const chartMode = ref('stack')  // 'stack' | 'overlay'

const SERIES_COLORS = [
  '#f59e0b', '#3b82f6', '#10b981', '#ef4444', '#8b5cf6',
  '#ec4899', '#06b6d4', '#f97316', '#84cc16', '#6366f1',
  '#14b8a6', '#e11d48', '#a855f7', '#0ea5e9', '#d946ef',
]

// 参数分组规则：按关键词归类
// 能耗点位(ene_ 前缀，来自关联电表)放最前面优先命中，组名带 ⚡ 前缀跟工艺参数
// 区分；按物理量拆成电压/电流/功率等子组，保证每组单位一致，Y轴标签不会错。
const PARAM_GROUP_RULES = [
  { name: '⚡ 能耗-电压', keys: ['ene_ua', 'ene_ub', 'ene_uc', 'ene_uab', 'ene_ubc', 'ene_uca'], unit: 'V' },
  { name: '⚡ 能耗-电流', keys: ['ene_ia', 'ene_ib', 'ene_ic'], unit: 'A' },
  { name: '⚡ 能耗-功率', keys: ['ene_pa', 'ene_pb', 'ene_pc', 'ene_ps', 'ene_qa', 'ene_qb', 'ene_qc', 'ene_qs', 'ene_sa', 'ene_sb', 'ene_sc', 'ene_ss'], unit: 'kW' },
  { name: '⚡ 能耗-功率因数', keys: ['ene_pf'], unit: '' },
  { name: '⚡ 能耗-累计电度', keys: ['ene_eptotal', 'ene_imp', 'ene_exp'], unit: 'kWh' },
  { name: '温度', keys: ['tep', 'Tep', 'End_Tep', 'Hg_tep'], unit: '°C' },
  { name: '真空度', keys: ['Vacuum'], unit: 'kPa' },
  { name: '重量', keys: ['Weight', 'weight', 'Actual_weight', 'Real_weight'], unit: 'kg' },
  { name: '时间', keys: ['_Time'], unit: 's' },
  { name: '转速/状态', keys: ['Sszkd', 'Gtjc', 'DQD_DH', 'EndHg', 'Sta_'], unit: '' },
]

function groupParams(paramNames) {
  const groups = {}
  const ungrouped = []

  for (const p of paramNames) {
    let matched = false
    for (const rule of PARAM_GROUP_RULES) {
      for (const kw of rule.keys) {
        if (p.includes(kw)) {
          if (!groups[rule.name]) groups[rule.name] = { params: [], unit: rule.unit }
          groups[rule.name].params.push(p)
          matched = true
          break
        }
      }
      if (matched) break
    }
    if (!matched) ungrouped.push(p)
  }
  if (ungrouped.length) groups['其他'] = { params: ungrouped, unit: '' }

  return groups
}

function groupColor(idx) {
  return ['#f59e0b','#3b82f6','#10b981','#8b5cf6','#ef4444','#ec4899'][idx % 6]
}

function toDatetimeLocal(date) {
  const pad = (n) => String(n).padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`
}
function formatForApi(dtLocal) {
  if (!dtLocal) return ''
  return dtLocal.replace('T', ' ') + ':00'
}

// 按班次对齐：找到离给定时间最近的 06:00 或 18:00
function nearestShiftBoundary(date) {
  const candidates = []
  for (const dayOffset of [-1, 0, 1]) {
    for (const hour of [6, 18]) {
      const d = new Date(date)
      d.setDate(d.getDate() + dayOffset)
      d.setHours(hour, 0, 0, 0)
      candidates.push(d)
    }
  }
  let closest = candidates[0]
  let minDiff = Math.abs(date.getTime() - closest.getTime())
  for (const c of candidates) {
    const diff = Math.abs(date.getTime() - c.getTime())
    if (diff < minDiff) {
      minDiff = diff
      closest = c
    }
  }
  return closest
}

// 时间范围：默认最近 24 小时，且按班次对齐到最近的 06:00/18:00；默认最大30天，通过dataZoom可拖拽查看历史数据
const MAX_RANGE_DAYS = 30
const _initEnd = nearestShiftBoundary(new Date())
const _initStart = new Date(_initEnd.getTime() - 24 * 3600 * 1000)
const startTime = ref(toDatetimeLocal(_initStart))
const endTime = ref(toDatetimeLocal(_initEnd))
const rangeWarning = ref('')



// 手动改动输入框 → 标记为自定义
function onRangeInputChange() {
  clampRangeWithin()
}

// 保证范围 ≤ MAX_RANGE_DAYS，超出则收窄起点并提示
function clampRangeWithin() {
  const s = new Date(startTime.value).getTime()
  const e = new Date(endTime.value).getTime()
  if (!isFinite(s) || !isFinite(e)) { rangeWarning.value = ''; return false }
  if (e < s) { rangeWarning.value = '结束时间早于开始时间'; return false }
  if (e - s > MAX_RANGE_DAYS * 86400000) {
    startTime.value = toDatetimeLocal(new Date(e - MAX_RANGE_DAYS * 86400000))
    rangeWarning.value = `时间范围超过 ${MAX_RANGE_DAYS} 天，已自动收窄到最近 ${MAX_RANGE_DAYS} 天`
    return true
  }
  rangeWarning.value = ''
  return false
}

async function loadDevices() {
  try {
    const res = await (await import('../api/client.js')).getDeviceParamDevices()
    if (res.code === 200 && res.data) {
      devices.value = res.data
    }
  } catch (err) {
    console.error('加载设备列表失败:', err)
  }
}

const ALL_POINT_NAMES = ref([])
const LOADED_POINT_NAMES = ref(new Set())
const DEFAULT_VISIBLE_COUNT = 5

let _stateAbort = null        // AbortController 用于取消重复状态分析请求
let _stateRequestId = 0       // 递增计数器，只有最新请求的响应才更新 stateResult

function onDeviceChange() {
  seriesKeys.value = []
  visibleKeys.value = []
  displayNames.value = {}
  paramUnits.value = {}
  seriesData.value = {}
  runningPeriods.value = []
  analysisResult.value = ''
  analysisResultMeta.value = ''
  analysisError.value = ''
  showAnalysisLog.value = false
  analysisLogItems.value = []
  ALL_POINT_NAMES.value = []
  LOADED_POINT_NAMES.value = new Set()
  workflowStep.value = 0
  showAlarmOverlay.value = false
  alarmEvents.value = []
  alignedRows.value = []
  paramsMeta.value = {}
  alarmTypeFilter.value = []
  disposeChart()
  stateCardRef.value?.disposeStateTimeline()
  stateResult.value = null
  kpiResult.value = null
  stageCpkResult.value = null
  stageAnalysisResult.value = null
  energyResult.value = null
  dayTrendResult.value = null
  shiftList.value = []
  dayList.value = []
  selectedShiftKey.value = null
  currentShiftMeta.value = null
  energyBreakdownRef.value?.disposeEnergyCharts()
  if (_stateAbort) { _stateAbort.abort(); _stateAbort = null }
  _stateRequestId++
  if (selectedDevice.value) loadData()
}

function currentDeviceName() {
  const d = devices.value.find(d => d.device_code === selectedDevice.value)
  return d ? d.device_name || d.device_code : selectedDevice.value
}

// ══════════════════════════════════════════════════════════
// 班次：分析与缓存的基本单位（白班06-18 / 晚班18-06）
// 一次请求拿回该班次的 4 类分析结果，各 Tab 只负责渲染。
// 已结束的班次结果永久有效直接读库；进行中的班次每次是当下快照。
// ══════════════════════════════════════════════════════════
const shiftList = ref([])
// 天(06:00~次日06:00)——与班次并列的另一个分析单位，同一套 parse_shift_key()/
// analyze_one_shift() 通用逻辑，key 后缀是 "-full"，selectShift()/selectedShiftKey
// 两种 key 通用，不用另外区分“当前选的是班次还是天”。
const dayList = ref([])
const selectedShiftKey = ref(null)
const shiftAnalyzing = ref(false)
const currentShiftMeta = ref(null)

async function loadShifts() {
  if (!selectedDevice.value) { shiftList.value = []; return }
  try {
    const r = await client.get('/device-params/shifts', {
      params: { start_time: formatForApi(startTime.value), end_time: formatForApi(endTime.value) },
    })
    shiftList.value = (r.code === 200 && r.data?.shifts) ? r.data.shifts : []
  } catch (e) {
    shiftList.value = []
    return
  }
  // 默认看最近的那个班次
  const last = shiftList.value[shiftList.value.length - 1]
  selectedShiftKey.value = last?.key ?? null
  if (selectedShiftKey.value) await loadShiftAnalysis()
}

async function loadDayWindows() {
  if (!selectedDevice.value) { dayList.value = []; return }
  try {
    const r = await client.get('/device-params/full-days', {
      params: { start_time: formatForApi(startTime.value), end_time: formatForApi(endTime.value) },
    })
    dayList.value = (r.code === 200 && r.data?.days) ? r.data.days : []
  } catch (e) {
    dayList.value = []
  }
}

function selectShift(key) {
  if (key === selectedShiftKey.value) return
  selectedShiftKey.value = key
  loadShiftAnalysis()
}

function reanalyzeShift() {
  return loadShiftAnalysis(true)
}

function _setAllResults(v) {
  stateResult.value = v
  energyResult.value = v
  kpiResult.value = v
  stageCpkResult.value = v
  stageAnalysisResult.value = v
}

async function loadShiftAnalysis(force = false, types = null) {
  if (!selectedDevice.value || !selectedShiftKey.value) return
  if (!pulseParam.value) {
    _setAllResults({ source: 'error', msg: '请先在「参数设定」页面中设置生产节拍(脉搏)参数' })
    return
  }
  shiftAnalyzing.value = true
  // 只重算部分类型时，其它 Tab 的已有结果保持不动
  const _apply = (v) => {
    if (!types) return _setAllResults(v)
    if (types.includes('state')) stateResult.value = v
    if (types.includes('energy')) energyResult.value = v
    if (types.includes('kpi')) kpiResult.value = v
    if (types.includes('stage')) stageCpkResult.value = v
    if (types.includes('stage_recipe')) stageAnalysisResult.value = v
  }
  _apply({ source: 'loading' })

  _lastEnergySel = selectedEnergyPoints.value.join(',')
  try {
    const res = await client.post('/device-params/shift-analysis', {
      device_code: selectedDevice.value,
      device_name: currentDeviceName(),
      pulse_param: pulseParam.value,
      shift_key: selectedShiftKey.value,
      analysis_types: types,
      selected_points: selectedEnergyPoints.value,
      force,
    }, { timeout: 0 })
    if (res.code === 200 && res.data?.shifts?.length) {
      applyShiftResult(res.data.shifts[0], types)
    } else {
      _apply({ source: 'error', msg: res.msg || '班次分析失败' })
    }
  } catch (e) {
    _apply({ source: 'error', msg: e.response?.data?.msg || e.message })
  } finally {
    shiftAnalyzing.value = false
  }
}

// 后端每类结果要么是正常数据、要么带 error 字段，这里统一成各 Tab 已有的
// { source: 'error', msg } 约定，渲染逻辑一行都不用改
function _asResult(x, name) {
  if (!x) return { source: 'error', msg: `${name}无结果` }
  if (x.error) return { source: 'error', msg: x.msg || `${name}失败` }
  return x
}

function applyShiftResult(s, types = null) {
  const r = s.results || {}
  const want = (t) => !types || types.includes(t)
  if (want('state')) stateResult.value = _asResult(r.state, '状态分析')
  if (want('kpi')) kpiResult.value = _asResult(r.kpi, 'KPI 计算')
  if (want('stage')) stageCpkResult.value = _asResult(r.stage, '阶段分析')
  if (want('stage_recipe')) stageAnalysisResult.value = _asResult(r.stage_recipe, '阶段配方分析')
  if (want('energy')) {
    energyResult.value = _asResult(r.energy, '能耗分析')
    // 电表/房子选择由 EnergyBreakdown 子组件在 watch(energyResult) 中自动初始化
  }

  // 状态结果仍按原样落一份 screen-state 快照（推进 workflow_step，供其它页面读）
  if (want('state') && !stateResult.value?.source) persistStateSnapshot()

  const cached = s.cached || []
  const at = r.kpi?._cache?.computed_at || r.state?._cache?.computed_at || r.energy?._cache?.computed_at
  const unitLabel = s.shift?.shift_type === 'full' ? '该天' : '该班次'
  currentShiftMeta.value = {
    cacheInfo: cached.length ? `已有结果${at ? ' · ' + at : ''}` : '本次新算',
    note: s.shift?.partial
      ? `${unitLabel}被时间范围截断，指标只覆盖选中的部分，不能与整个单位直接比较`
      : null,
  }
  renderCurrentTab()
}

async function renderCurrentTab() {
  await nextTick()
  if (activeStep.value === 1) {
    stateCardRef.value?.disposeStateTimeline()
    await nextTick()
    if (seriesKeys.value.length > 0) initChart()
    await nextTick()
    stateCardRef.value?.renderStateTimeline()
  } else if (activeStep.value === 2) {
    energyBreakdownRef.value?.renderEnergyCharts()
  }
}

async function loadRunningPeriods() {
  try {
    const res = await getRunningPeriods({
      device_code: selectedDevice.value,
      start_time: formatForApi(startTime.value),
      end_time: formatForApi(endTime.value),
    })
    if (res.code === 200 && res.data?.periods) {
      runningPeriods.value = res.data.periods
    }
  } catch (err) {
    console.error('加载运行时段失败:', err)
    runningPeriods.value = []
  }
}

// ── 特征视图 ──

// tab 切换：① 状态&效率(含原始参数曲线) ② 能耗 ③ KPI ④ 阶段
// 四个 Tab 的数据在选中班次时已一次性取回（共享一次取数），切 Tab 只做渲染，
// 不再各自发请求 —— 这是把"每切一次 Tab 重拉一遍数据"的搬运浪费去掉的关键。
async function onStepClick(step) {
  activeStep.value = step
  if (!selectedDevice.value) return

  // 尚未取过该班次的结果（如刚进页面直接点了别的 Tab）才补一次
  if (!stateResult.value && selectedShiftKey.value) await loadShiftAnalysis()

  if (step === 1) {
    energyBreakdownRef.value?.disposeEnergyCharts()
    stateCardRef.value?.disposeStateTimeline()
    await nextTick()
    if (seriesKeys.value.length > 0) initChart()
    await nextTick()
    stateCardRef.value?.renderStateTimeline()
  } else if (step === 2) {
    disposeChart()
    // 能耗点位勾选变了才需要重算，且只重算能耗这一类，不动其它三类的缓存
    if (_lastEnergySel !== selectedEnergyPoints.value.join(',')) {
      await loadShiftAnalysis(true, ['energy'])
    } else {
      await nextTick()
      energyBreakdownRef.value?.renderEnergyCharts()
    }
  } else if (step === 3) {
    disposeChart()
    energyBreakdownRef.value?.disposeEnergyCharts()
  } else if (step === 4) {
    disposeChart()
    energyBreakdownRef.value?.disposeEnergyCharts()
  }
}

// ── 仅运行状态过滤助手 ──
// 判断时间戳(ms)是否落在任一运行时段内
function pointInRunning(tMs) {
  for (const p of runningPeriods.value) {
    const s = parseTime(p.start_time)
    if (s == null) continue
    const e = p.end_time ? parseTime(p.end_time) : Infinity
    if (tMs >= s && tMs <= e) return true
  }
  return false
}

// 统一取序列：开启"仅运行状态"且有运行时段时，过滤到运行时段内的点。
// 图表与特征视图的所有 seriesData 消费点统一走此函数。
function getSeries(key) {
  const data = seriesData.value[key] || []
  if (!showRunningOnly.value || runningPeriods.value.length === 0) return data
  return data.filter(pt => {
    const t = parseTime(pt.time)
    return t != null && pointInRunning(t)
  })
}

function onRunningOnlyToggle() {
  updateChart()
}

// ── 异常检测 ──

async function onAnomalyToggle() {
  if (showAnomalyDetection.value) {
    await runAnomalyDetection()
  } else {
    healthTimeline.value = []
    anomalySummary.value = null
    updateChart()
  }
}

async function runAnomalyDetection() {
  if (!selectedDevice.value || !showAnomalyDetection.value) return

  anomalyDetecting.value = true
  healthTimeline.value = []
  anomalySummary.value = null

  try {
    const res = await detectAnomalies({
      device_code: selectedDevice.value,
      start_time: formatForApi(startTime.value),
      end_time: formatForApi(endTime.value),
      contamination: anomalyContamination.value,
    })

    if (res.code === 200 && res.data) {
      healthTimeline.value = res.data.health_timeline || []
      anomalySummary.value = res.data.summary || null
      iqrThresholds.value = res.data.iqr_thresholds || {}
      updateChart()
    }
  } catch (err) {
    console.error('异常检测失败:', err)
  } finally {
    anomalyDetecting.value = false
  }
}

// ── 告警叠加 ──

async function onAlarmOverlayToggle() {
  if (showAlarmOverlay.value) {
    await reloadAlignedData()
  } else {
    alarmEvents.value = []
    alignedRows.value = []
    alarmTypeFilter.value = []
    updateChart()
  }
}

async function reloadAlignedData() {
  if (!selectedDevice.value || !showAlarmOverlay.value) return

  try {
    const res = await getAlignedData({
      device_code: selectedDevice.value,
      start_time: formatForApi(startTime.value),
      end_time: formatForApi(endTime.value),
      alarm_window_min: alarmWindowMin.value,
    })
    if (res.code === 200 && res.data) {
      alarmEvents.value = res.data.alarm_events || []
      alignedRows.value = res.data.aligned_rows || []
      paramsMeta.value = res.data.params_meta || {}
      // 默认选中所有告警类型
      if (alarmTypeFilter.value.length === 0) {
        alarmTypeFilter.value = Object.keys(ALARM_STATUS_META).map(Number)
      }
      updateChart()
    }
  } catch (err) {
    console.error('加载对齐数据失败:', err)
  }
}

function alarmEventsByType(statusCode) {
  return alarmEvents.value.filter(e => e.status === statusCode)
}

function toggleAlarmType(code) {
  const idx = alarmTypeFilter.value.indexOf(code)
  if (idx >= 0) {
    alarmTypeFilter.value.splice(idx, 1)
  } else {
    alarmTypeFilter.value.push(code)
  }
  updateChart()
}

async function loadData() {
  if (!selectedDevice.value) return

  clampRangeWithin()
  loading.value = true
  analysisResult.value = ''
  analysisError.value = ''
  stateResult.value = null
  kpiResult.value = null
  stageCpkResult.value = null
  stageAnalysisResult.value = null
  energyResult.value = null
  disposeChart()
  stateCardRef.value?.disposeStateTimeline()
  energyBreakdownRef.value?.disposeEnergyCharts()
  showAlarmOverlay.value = false
  alarmEvents.value = []
  showAnomalyDetection.value = false
  healthTimeline.value = []
  anomalySummary.value = null

  // 「参数设定」页筛选保存的 checked_params 是本页参数范围的唯一依据；
  // 没筛选过(该设备从未在「参数设定」保存过)才回退到该设备全部参数
  const checkedParams = await loadScreenStateFromDb()

  try {
    const spanHours = (new Date(endTime.value) - new Date(startTime.value)) / 3600000
    const useInterval = spanHours > 3 ? 'auto' : 'raw'

    {
      const pointsRes = await getDeviceParamPoints(selectedDevice.value)
      let allPointNames = []
      if (pointsRes.code === 200 && pointsRes.data) {
        allPointNames = pointsRes.data.map(p => p.p_name)
        // 从点位列表预填显示名和单位，避免未加载参数显示英文代码
        for (const p of pointsRes.data) {
          if (!displayNames.value[p.p_name]) {
            displayNames.value[p.p_name] = p.display_name || p.p_name
          }
          if (p.unit && !paramUnits.value[p.p_name]) {
            paramUnits.value[p.p_name] = p.unit
          }
        }
      }
      ALL_POINT_NAMES.value = checkedParams || allPointNames

      // 自动检测脉搏参数：合膏机优先用 Tec_Stage，其他设备默认优先 pulse/count 类参数
      if (!pulseParam.value && allPointNames.length > 0) {
        const candidate = allPointNames.find(n =>
          n === 'Tec_Stage' || n.includes('Stage') || n.includes('_Stage')
        ) || allPointNames.find(n =>
          n.toLowerCase().includes('pulse') || n.toLowerCase().includes('cycle') ||
          n.toLowerCase().includes('count') || n.includes('_End')
        )
        if (candidate) pulseParam.value = candidate
      }

      const defaultPoints = ALL_POINT_NAMES.value.slice(0, DEFAULT_VISIBLE_COUNT)
      // 能耗点位（若已在「参数设定」页勾选）始终随默认点位一起拉取，不受 DEFAULT_VISIBLE_COUNT 截断影响，
      // 否则用户勾选了组合有功总电能，却因排序靠后未进入默认前5而拉不到数据、也不会自动可见
      for (const ep of ENERGY_POINTS) {
        if (ALL_POINT_NAMES.value.includes(ep) && !defaultPoints.includes(ep)) {
          defaultPoints.push(ep)
        }
      }

      const res = await getDeviceParamData({
        device_code: selectedDevice.value,
        start_time: formatForApi(startTime.value),
        end_time: formatForApi(endTime.value),
        limit: 300000,
        interval: useInterval,
        p_names: defaultPoints,
      })

      if (res.code === 200 && res.data?.series) {
        const series = res.data.series
        // 如果默认点位没有数据，尝试加载筛选范围内的其余点位(仍限定在筛选结果内，不回退到全设备参数)
        if (Object.keys(series).length === 0 && ALL_POINT_NAMES.value.length > 0) {
          const allRes = await getDeviceParamData({
            device_code: selectedDevice.value,
            start_time: formatForApi(startTime.value),
            end_time: formatForApi(endTime.value),
            limit: 300000,
            interval: useInterval,
            p_names: ALL_POINT_NAMES.value,
          })
          if (allRes.code === 200 && allRes.data?.series && Object.keys(allRes.data.series).length > 0) {
            seriesData.value = allRes.data.series
            visibleKeys.value = Object.keys(allRes.data.series).slice(0, DEFAULT_VISIBLE_COUNT)
            // 确保 Tec_Stage 等阶段参数始终可见
            for (const stageParam of allPointNames) {
              if ((stageParam.includes('_Stage') || stageParam.includes('Stage')) &&
                  allRes.data.series[stageParam] && !visibleKeys.value.includes(stageParam)) {
                visibleKeys.value.push(stageParam)
              }
            }
            // 已勾选的能耗点位始终可见，见上方 defaultPoints 处注释
            for (const ep of ENERGY_POINTS) {
              if (allRes.data.series[ep] && !visibleKeys.value.includes(ep)) {
                visibleKeys.value.push(ep)
              }
            }
            Object.assign(displayNames.value, allRes.data.display_names || {})
            Object.assign(paramUnits.value, allRes.data.units || {})
            aggInterval.value = allRes.data.aggregated ? (allRes.data.interval || '') : ''
            for (const key of Object.keys(allRes.data.series)) {
              LOADED_POINT_NAMES.value.add(key)
            }
          } else {
            // 当前时间范围无数据，尝试扩展范围回退查找
            const fallbackLoaded = await tryWiderRangeFallback(allPointNames)
            if (!fallbackLoaded) {
              seriesData.value = {}
              visibleKeys.value = []
              displayNames.value = {}
              paramUnits.value = {}
              aggInterval.value = ''
            }
          }
        } else {
          seriesData.value = series
          visibleKeys.value = defaultPoints.filter(k => series[k])
          // 确保 Tec_Stage 等阶段参数始终可见
          for (const stageParam of allPointNames) {
            if ((stageParam.includes('_Stage') || stageParam.includes('Stage')) &&
                series[stageParam] && !visibleKeys.value.includes(stageParam)) {
              visibleKeys.value.push(stageParam)
            }
          }
          // 已勾选的能耗点位始终可见，见上方 defaultPoints 处注释
          for (const ep of ENERGY_POINTS) {
            if (series[ep] && !visibleKeys.value.includes(ep)) {
              visibleKeys.value.push(ep)
            }
          }
          Object.assign(displayNames.value, res.data.display_names || {})
          Object.assign(paramUnits.value, res.data.units || {})
          aggInterval.value = res.data.aggregated ? (res.data.interval || '') : ''
          for (const key of Object.keys(series)) {
            LOADED_POINT_NAMES.value.add(key)
          }
        }
        seriesKeys.value = ALL_POINT_NAMES.value
        await loadRunningPeriods()
      } else {
        seriesKeys.value = []
        visibleKeys.value = []
        displayNames.value = {}
        paramUnits.value = {}
        seriesData.value = {}
        runningPeriods.value = []
        aggInterval.value = ''
      }
    }
  } catch (err) {
    console.error('加载参数数据失败:', err)
    seriesKeys.value = []
    visibleKeys.value = []
    displayNames.value = {}
    paramUnits.value = {}
    displayNames.value = {}
  } finally {
    loading.value = false
    await nextTick()
    if (activeStep.value === 1 && seriesKeys.value.length > 0) initChart()
    // 班次列表 → 默认选最近班次 → 一次取回该班次 4 类分析结果（内部会渲染当前 Tab）
    if (pulseParam.value) await loadShifts()
    // 天(06:00~次日06:00)列表——与班次并列展示，供整体切换到"看某一天"
    if (pulseParam.value) loadDayWindows()
    // 日期范围跨度 > 1 天：额外取按天(06:00~次日06:00)独立掐头去尾的多日汇总
    if (pulseParam.value && isMultiDayRange.value) loadDayTrend()
    else dayTrendResult.value = null
  }
}

async function toggleSeries(key) {
  const idx = visibleKeys.value.indexOf(key)
  if (idx >= 0) {
    visibleKeys.value.splice(idx, 1)
    updateChart()
  } else {
    if (!seriesData.value[key] || seriesData.value[key].length === 0) {
      await loadParamWithFallback(key)
    }
    if (seriesData.value[key] && seriesData.value[key].length > 0) {
      visibleKeys.value.push(key)
    }
    await nextTick()
    try {
      if (!chartInstance || chartInstance.isDisposed()) {
        initChart()
      } else {
        updateChart()
      }
    } catch (e) {
      console.warn('图表更新失败，重试初始化', e)
      nextTick(() => {
        if (chartInstance && !chartInstance.isDisposed()) chartInstance.dispose()
        initChart()
      })
    }
  }
}

async function loadParamWithFallback(key) {
  // 逐级回退时间窗口：当前范围 → 7天 → 30天 → 90天
  const now = new Date()
  const pad = (n) => String(n).padStart(2, '0')
  const fmtTs = (d) => `${d.getFullYear()}-${pad(d.getMonth()+1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`

  const tryWindows = [
    { label: '当前范围', start: new Date(startTime.value), end: new Date(endTime.value) },
    { label: '最近7天', start: new Date(now.getTime() - 7 * 86400000), end: now },
    { label: '最近30天', start: new Date(now.getTime() - 30 * 86400000), end: now },
    { label: '最近90天', start: new Date(now.getTime() - 90 * 86400000), end: now },
  ]

  for (const win of tryWindows) {
    const st = fmtTs(win.start)
    const et = fmtTs(win.end)
    const spanHours = (win.end - win.start) / 3600000
    const useInterval = spanHours > 3 ? 'auto' : 'raw'

    try {
      const res = await getDeviceParamData({
        device_code: selectedDevice.value,
        start_time: st,
        end_time: et,
        limit: 300000,
        interval: useInterval,
        p_names: [key],
      })

      if (res.code === 200 && res.data?.series && res.data.series[key]?.length > 0) {
        LOADED_POINT_NAMES.value.add(key)
        Object.assign(seriesData.value, res.data.series)
        if (res.data.display_names) Object.assign(displayNames.value, res.data.display_names)
        if (res.data.units) Object.assign(paramUnits.value, res.data.units)

        // fallback 找到数据了：更新页面时间范围显示为数据的实际起止时间
        if (win.label !== '当前范围') {
          const pts = res.data.series[key]
          const dataStart = pts[0]?.time
          const dataEnd = pts[pts.length - 1]?.time
          if (dataStart && dataEnd) {
            startTime.value = toDatetimeLocal(new Date(dataStart.replace(' ', 'T')))
            endTime.value = toDatetimeLocal(new Date(dataEnd.replace(' ', 'T')))
          }
        }
        aggInterval.value = res.data.aggregated ? (res.data.interval || '') : ''

        // 如果用了比当前更大的时间窗口，重新加载其他已显示的参数以对齐
        if (win.label !== '当前范围' && visibleKeys.value.length > 0) {
          await reloadVisibleParamsForRange(st, et)
        }
        return
      }
    } catch (err) {
      console.error(`加载参数 ${key} 失败 (${win.label}):`, err)
    }
  }
  // 所有窗口都无数据，标记已尝试过
  LOADED_POINT_NAMES.value.add(key)
}

async function reloadVisibleParamsForRange(st, et) {
  const spanHours = (new Date(et.replace(' ', 'T')) - new Date(st.replace(' ', 'T'))) / 3600000
  const useInterval = spanHours > 3 ? 'auto' : 'raw'
  const keys = visibleKeys.value.filter(k => seriesData.value[k])

  if (keys.length === 0) return

  try {
    const res = await getDeviceParamData({
      device_code: selectedDevice.value,
      start_time: st,
      end_time: et,
      limit: 300000,
      interval: useInterval,
      p_names: keys,
    })
    if (res.code === 200 && res.data?.series) {
      Object.assign(seriesData.value, res.data.series)
      if (res.data.display_names) Object.assign(displayNames.value, res.data.display_names)
      if (res.data.units) Object.assign(paramUnits.value, res.data.units)
      for (const k of Object.keys(res.data.series)) {
        LOADED_POINT_NAMES.value.add(k)
      }
      aggInterval.value = res.data.aggregated ? (res.data.interval || '') : ''
    }
  } catch (err) {
    console.error('重载其他参数失败:', err)
  }
}

async function tryWiderRangeFallback(allPointNames) {
  // 初始加载时当前范围无数据，逐级扩展回退
  const now = new Date()
  const pad = (n) => String(n).padStart(2, '0')
  const fmtTs = (d) => `${d.getFullYear()}-${pad(d.getMonth()+1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`

  const tryWindows = [
    { label: '最近7天', start: new Date(now.getTime() - 7 * 86400000), end: now },
    { label: '最近30天', start: new Date(now.getTime() - 30 * 86400000), end: now },
    { label: '最近90天', start: new Date(now.getTime() - 90 * 86400000), end: now },
  ]

  for (const win of tryWindows) {
    const st = fmtTs(win.start)
    const et = fmtTs(win.end)
    const spanHours = (win.end - win.start) / 3600000
    const useInterval = spanHours > 3 ? 'auto' : 'raw'

    try {
      const allRes = await getDeviceParamData({
        device_code: selectedDevice.value,
        start_time: st,
        end_time: et,
        limit: 300000,
        interval: useInterval,
        p_names: allPointNames,
      })

      if (allRes.code === 200 && allRes.data?.series && Object.keys(allRes.data.series).length > 0) {
        seriesData.value = allRes.data.series
        visibleKeys.value = Object.keys(allRes.data.series).slice(0, DEFAULT_VISIBLE_COUNT)
        // 确保 Tec_Stage 等阶段参数始终可见
        for (const stageParam of allPointNames) {
          if ((stageParam.includes('_Stage') || stageParam.includes('Stage')) &&
              allRes.data.series[stageParam] && !visibleKeys.value.includes(stageParam)) {
            visibleKeys.value.push(stageParam)
          }
        }
        // 已勾选的能耗点位始终可见，见 loadParamData 中 defaultPoints 处注释
        for (const ep of ENERGY_POINTS) {
          if (allRes.data.series[ep] && !visibleKeys.value.includes(ep)) {
            visibleKeys.value.push(ep)
          }
        }
        Object.assign(displayNames.value, allRes.data.display_names || {})
        Object.assign(paramUnits.value, allRes.data.units || {})
        aggInterval.value = allRes.data.aggregated ? (allRes.data.interval || '') : ''
        for (const key of Object.keys(allRes.data.series)) {
          LOADED_POINT_NAMES.value.add(key)
        }
        // fallback 找到数据：更新页面时间范围为数据实际起止时间
        startTime.value = toDatetimeLocal(win.start)
        endTime.value = toDatetimeLocal(win.end)
        return true
      }
    } catch (err) {
      console.error(`扩展范围加载失败 (${win.label}):`, err)
    }
  }
  return false
}

async function toggleAll() {
  if (visibleKeys.value.length === seriesKeys.value.length) {
    visibleKeys.value = []
    updateChart()
  } else {
    const unloadedKeys = seriesKeys.value.filter(k => !LOADED_POINT_NAMES.value.has(k) || (seriesData.value[k] && seriesData.value[k].length === 0))
    if (unloadedKeys.length > 0) {
      const now = new Date()
      const pad = (n) => String(n).padStart(2, '0')
      const fmtTs = (d) => `${d.getFullYear()}-${pad(d.getMonth()+1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`

      const tryWindows = [
        { label: '当前范围', start: new Date(startTime.value), end: new Date(endTime.value) },
        { label: '最近7天', start: new Date(now.getTime() - 7 * 86400000), end: now },
        { label: '最近30天', start: new Date(now.getTime() - 30 * 86400000), end: now },
        { label: '最近90天', start: new Date(now.getTime() - 90 * 86400000), end: now },
      ]

      let foundAny = false
      for (const win of tryWindows) {
        const st = fmtTs(win.start)
        const et = fmtTs(win.end)
        const spanHours = (win.end - win.start) / 3600000
        const useInterval = spanHours > 3 ? 'auto' : 'raw'

        try {
          const res = await getDeviceParamData({
            device_code: selectedDevice.value,
            start_time: st,
            end_time: et,
            limit: 300000,
            interval: useInterval,
            p_names: unloadedKeys,
          })

          if (res.code === 200 && res.data?.series) {
            const foundKeys = Object.keys(res.data.series)
            if (foundKeys.length > 0) {
              Object.assign(seriesData.value, res.data.series)
              if (res.data.display_names) Object.assign(displayNames.value, res.data.display_names)
              if (res.data.units) Object.assign(paramUnits.value, res.data.units)
              for (const k of foundKeys) LOADED_POINT_NAMES.value.add(k)

              if (win.label !== '当前范围') {
                startTime.value = toDatetimeLocal(win.start)
                endTime.value = toDatetimeLocal(win.end)
              }
              aggInterval.value = res.data.aggregated ? (res.data.interval || '') : ''
              foundAny = true
            }
          }
        } catch (err) {
          console.error('全部加载失败:', err)
        }
        if (foundAny) break
      }
      for (const k of unloadedKeys) {
        if (!LOADED_POINT_NAMES.value.has(k)) LOADED_POINT_NAMES.value.add(k)
      }
    }
    visibleKeys.value = [...seriesKeys.value]
    if (!chartInstance || chartInstance.isDisposed()) {
      initChart()
    } else {
      updateChart()
    }
  }
}

function parseTime(str) {
  if (!str) return null
  const d = new Date(str.replace(' ', 'T'))
  return isNaN(d.getTime()) ? null : d.getTime()
}

function initChart() {
  if (!chartContainer.value || !chartContainer.value.isConnected) {
    return
  }
  if (seriesKeys.value.length === 0) return

  chartInstance = echarts.init(chartContainer.value)
  updateChart()
}

function updateChart() {
  if (!chartInstance || chartInstance.isDisposed()) return
  if (!chartContainer.value || !chartContainer.value.isConnected) {
    nextTick(initChart)
    return
  }

  if (chartMode.value === 'overlay') {
    buildOverlayChart()
    return
  }

  // ── 分列模式（原有逻辑）──
  const loadedVisibleKeys = visibleKeys.value.filter(k => seriesData.value[k])
  const visibleCount = loadedVisibleKeys.length
  if (visibleCount === 0) return

  const queryStartTime = new Date(startTime.value).getTime()
  const queryEndTime = new Date(endTime.value).getTime()

  const hasRunningStatus = runningPeriods.value.length > 0
  const hasAlarmOverlay = showAlarmOverlay.value && alarmEvents.value.length > 0
  const hasAnomaly = showAnomalyDetection.value && healthTimeline.value.length > 0
  const statusHeight = 32
  const healthBandH = hasAnomaly ? 40 : 0
  const alarmBandHeight = hasAlarmOverlay ? 36 : 0
  const topOffset = (hasRunningStatus ? (statusHeight + 12) : 0) +
                    (hasAnomaly ? (healthBandH + 8) : 0) +
                    (hasAlarmOverlay ? (alarmBandHeight + 8) : 8)
  const gap = 4
  const stripHeight = 80

  const grids = []
  const xAxes = []
  const yAxes = []
  const seriesList = []

  let gridIdx = 0

  // --- Running status grid (top strip, more visible) ---
  if (hasRunningStatus) {
    grids.push({ left: 70, right: 16, top: 4, height: statusHeight })
    xAxes.push({
      type: 'time', gridIndex: gridIdx,
      min: queryStartTime,
      max: queryEndTime,
      axisLine: { show: false }, axisTick: { show: false },
      axisLabel: {
        show: true,
        color: '#9ca3af', fontSize: 11,
        formatter: function (value) {
          const d = new Date(value)
          const pad = (n) => String(n).padStart(2, '0')
          return `${pad(d.getMonth()+1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
        },
        inside: true, hideOverlap: true,
      },
      splitLine: { show: false },
    })
    yAxes.push({
      type: 'value', gridIndex: gridIdx,
      min: 0, max: 1, show: false,
      name: '运行状态',
      nameLocation: 'middle', nameGap: 30,
      nameTextStyle: { color: '#22c55e', fontSize: 10, fontWeight: 600 },
    })

    const sortedPeriods = [...runningPeriods.value].sort((a, b) =>
      parseTime(a.start_time) - parseTime(b.start_time)
    )
    const statusData = []
    for (const p of sortedPeriods) {
      const s = parseTime(p.start_time)
      const e = p.end_time ? parseTime(p.end_time) : null
      if (s) {
        statusData.push([s, 1])
        if (e) statusData.push([e, 0])
      }
    }
    if (statusData.length > 0) {
      // 用 custom series 绘制运行状态色块 + 文字标注
      seriesList.push({
        name: '运行状态', type: 'line', step: 'start', symbol: 'none',
        lineStyle: { width: 0 }, itemStyle: { color: '#22c55e' },
        areaStyle: { color: 'rgba(34, 197, 94, 0.45)' },
        data: statusData, xAxisIndex: gridIdx, yAxisIndex: gridIdx,
        connectNulls: false, silent: true,
      })
      // 在每个运行时段中间标注"运行中"
      const markAreas = []
      for (const p of sortedPeriods) {
        const s = parseTime(p.start_time)
        const e = p.end_time ? parseTime(p.end_time) : Date.now()
        if (s && e) {
          markAreas.push([
            { xAxis: s, name: '运行中' },
            { xAxis: e },
          ])
        }
      }
      seriesList.push({
        name: '运行标注', type: 'line', symbol: 'none',
        lineStyle: { width: 0 }, data: [],
        xAxisIndex: gridIdx, yAxisIndex: gridIdx,
        markArea: {
          silent: true,
          itemStyle: { color: 'transparent' },
          label: {
            show: true, position: 'insideTop',
            color: '#16a34a', fontSize: 9, fontWeight: 500,
            formatter: function (p) { return p.name || '' },
          },
          data: markAreas,
        },
      })
    }
    gridIdx++
  }

  // --- Health index band (anomaly detection) ---
  const healthBandHeight = hasAnomaly ? 40 : 0
  let healthXAxisIdx = -1

  if (hasAnomaly) {
    const healthIndex = gridIdx
    grids.push({ left: 70, right: 16, top: (hasRunningStatus ? (statusHeight + 10) : 4), height: healthBandHeight })
    xAxes.push({
      type: 'time', gridIndex: healthIndex,
      min: queryStartTime, max: queryEndTime,
      axisLine: { show: false }, axisTick: { show: false },
      axisLabel: { show: false },
      splitLine: { show: false },
    })
    yAxes.push({
      type: 'value', gridIndex: healthIndex,
      min: 0, max: 100,
      axisLabel: { show: true, color: '#8b5cf6', fontSize: 9 },
      axisLine: { show: false }, axisTick: { show: false },
      splitLine: { show: false },
      name: '健康指数',
      nameLocation: 'middle', nameGap: 30,
      nameTextStyle: { color: '#8b5cf6', fontSize: 9, fontWeight: 600 },
    })

    // Health index line
    const healthData = []
    const anomalyMarkers = []
    for (const pt of healthTimeline.value) {
      const t = parseTime(pt.timestamp)
      if (!t) continue
      healthData.push({ value: [t, pt.health_index], severity: pt.severity })
      if (pt.is_anomaly) {
        anomalyMarkers.push({
          xAxis: t,
          lineStyle: {
            color: pt.severity === 'critical' ? '#ef4444' : '#f59e0b',
            type: 'dashed', width: 1, opacity: 0.5,
          },
        })
      }
    }

    seriesList.push({
      name: '健康指数',
      type: 'line', smooth: true, symbol: 'none',
      lineStyle: { width: 2.5, color: '#8b5cf6' },
      areaStyle: {
        color: {
          type: 'linear', x: 0, y: 0, x2: 0, y2: 1,
          colorStops: [
            { offset: 0, color: 'rgba(139,92,246,0.25)' },
            { offset: 0.6, color: 'rgba(245,158,11,0.10)' },
            { offset: 0.85, color: 'rgba(239,68,68,0.15)' },
            { offset: 1, color: 'rgba(239,68,68,0.30)' },
          ],
        },
      },
      data: healthData.map(d => d.value),
      xAxisIndex: healthIndex, yAxisIndex: healthIndex,
      silent: true,
      markLine: anomalyMarkers.length > 0 ? {
        silent: true, symbol: 'none',
        data: anomalyMarkers,
        label: { show: false },
      } : undefined,
    })

    healthXAxisIdx = healthIndex
    gridIdx++
  }

  // --- Alarm count band (step chart showing alarm_count_Nmin over time) ---
  let alarmCountXAxisIdx = -1
  if (hasAlarmOverlay) {
    const topBand = (hasRunningStatus ? (statusHeight + 10) : 0) + (hasAnomaly ? (healthBandHeight + 8) : 0)
    const alarmIndex = gridIdx
    grids.push({ left: 70, right: 16, top: topBand || 4, height: alarmBandHeight })
    xAxes.push({
      type: 'time', gridIndex: alarmIndex,
      min: queryStartTime, max: queryEndTime,
      axisLine: { show: false }, axisTick: { show: false },
      axisLabel: { show: false },
      splitLine: { show: false },
    })
    yAxes.push({
      type: 'value', gridIndex: alarmIndex,
      min: 0,
      axisLabel: { show: true, color: '#ef4444', fontSize: 9 },
      axisLine: { show: false }, axisTick: { show: false },
      splitLine: { show: false },
      name: `告警计数(${alarmWindowMin.value}min)`,
      nameLocation: 'middle', nameGap: 30,
      nameTextStyle: { color: '#ef4444', fontSize: 9, fontWeight: 600 },
    })

    // Build alarm count time series from alignedRows
    const countData = []
    for (const row of alignedRows.value) {
      const t = parseTime(row.timestamp)
      if (t) {
        countData.push([t, row[`alarm_count_${alarmWindowMin.value}min`] || 0])
      }
    }

    seriesList.push({
      name: `告警计数(${alarmWindowMin.value}min)`,
      type: 'line', step: 'start', symbol: 'none',
      lineStyle: { width: 2, color: '#ef4444' },
      areaStyle: { color: 'rgba(239,68,68,0.08)' },
      data: countData,
      xAxisIndex: alarmIndex, yAxisIndex: alarmIndex,
      silent: true,
    })

    alarmCountXAxisIdx = alarmIndex
    gridIdx++
  }

  // --- One grid per visible parameter ---
  const allXAxisIndices = []
  for (let i = 0; i < visibleCount; i++) {
    const top = topOffset + i * (stripHeight + gap)
    const isLast = (i === visibleCount - 1)
    const key = loadedVisibleKeys[i]
    const idx = seriesKeys.value.indexOf(key)
    const color = SERIES_COLORS[idx % SERIES_COLORS.length]
    const displayName = displayNames.value[key] || key
    const unit = paramUnits.value[key] || ''

    grids.push({
      left: 70, right: 16, top: top, height: stripHeight,
    })

    // X-axis: last grid shows full labels; others show minimal tick marks for alignment
    xAxes.push({
      type: 'time', gridIndex: gridIdx,
      min: queryStartTime,
      max: queryEndTime,
      axisLine: { show: isLast, lineStyle: { color: '#e5e7eb' } },
      axisTick: { show: isLast, lineStyle: { color: '#d1d5db' } },
      axisLabel: {
        show: isLast,
        color: '#6b7280', fontSize: 12,
        formatter: function (value) {
          const d = new Date(value)
          const pad = (n) => String(n).padStart(2, '0')
          return `${pad(d.getMonth()+1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
        },
        hideOverlap: true,
      },
      splitLine: {
        show: true,
        lineStyle: { color: '#f3f4f6', type: 'dashed' },
      },
    })
    allXAxisIndices.push(gridIdx)

    // Y-axis: show parameter name + unit as axis label, colored to match the line
    yAxes.push({
      type: 'value', gridIndex: gridIdx, scale: true,
      axisLine: { show: false }, axisTick: { show: false },
      splitLine: { lineStyle: { color: '#f3f4f6', type: 'dashed' } },
      axisLabel: { show: false },
      // Use axis name to display parameter label on the left
      name: unit ? `${displayName} (${unit})` : displayName,
      nameLocation: 'middle', nameGap: 30,
      nameTextStyle: { color, fontSize: 10, fontWeight: 500 },
    })

    // Build data for this parameter
    const data = getSeries(key)
    const timeMap = new Map()
    for (const d of data) {
      if (d.time) {
        timeMap.set(d.time, typeof d.value === 'number' ? d.value : null)
      }
    }
    const allTimes = [...timeMap.keys()].sort()
    const values = allTimes.map((t) => timeMap.get(t) ?? null)

    // 用 markArea 在参数图上叠加运行时段背景
    const isStageParam = key.includes('_Stage') || key.includes('Stage')
    const paramSeries = {
      name: displayName,
      type: 'line',
      step: isStageParam ? 'start' : undefined,
      smooth: isStageParam ? false : true,
      symbol: 'none',
      lineStyle: { width: isStageParam ? 2.5 : 1.5, color },
      itemStyle: { color },
      data: values.map((v, i) => [parseTime(allTimes[i]), v]),
      connectNulls: isStageParam ? false : true,
      xAxisIndex: gridIdx, yAxisIndex: gridIdx,
    }

    // 每个参数图上也叠加运行时段背景色
    if (hasRunningStatus) {
      const sortedPeriods = [...runningPeriods.value].sort((a, b) =>
        parseTime(a.start_time) - parseTime(b.start_time)
      )
      const markAreaData = []
      for (const p of sortedPeriods) {
        const s = parseTime(p.start_time)
        const e = p.end_time ? parseTime(p.end_time) : Date.now()
        if (s && e) {
          markAreaData.push([
            { xAxis: s, itemStyle: { color: 'rgba(34,197,94,0.06)' } },
            { xAxis: e },
          ])
        }
      }
      paramSeries.markArea = {
        silent: true,
        data: markAreaData,
      }
    }

    // 告警叠加：在参数图上添加告警标记线
    if (hasAlarmOverlay) {
      const alarmLines = []
      for (const ev of alarmEvents.value) {
        const code = ev.status
        if (!alarmTypeFilter.value.includes(code)) continue
        const meta = ALARM_STATUS_META[code]
        if (!meta) continue
        const s = parseTime(ev.start_time)
        if (!s) continue
        alarmLines.push({
          xAxis: s,
          lineStyle: { color: meta.color, type: 'dashed', width: 1, opacity: 0.7 },
          label: {
            show: true,
            position: 'insideEndTop',
            formatter: meta.name,
            color: meta.color,
            fontSize: 9,
            fontWeight: 500,
          },
        })
      }

      // 异常检测标记线（叠加）
      if (hasAnomaly) {
        for (const pt of healthTimeline.value) {
          if (pt.is_anomaly) {
            const s = parseTime(pt.timestamp)
            if (!s) continue
            const color = pt.severity === 'critical' ? '#ef4444' : '#f59e0b'
            alarmLines.push({
              xAxis: s,
              lineStyle: { color, type: 'dotted', width: 2, opacity: 0.5 },
              label: { show: false },
            })
          }
        }
      }

      if (alarmLines.length > 0) {
        paramSeries.markLine = {
          silent: true,
          symbol: 'none',
          data: alarmLines,
        }
      }
    } else if (hasAnomaly) {
      // 只有异常检测时添加异常标记
      const anomalyLines = []
      for (const pt of healthTimeline.value) {
        if (pt.is_anomaly) {
          const s = parseTime(pt.timestamp)
          if (!s) continue
          const color = pt.severity === 'critical' ? '#ef4444' : '#f59e0b'
          anomalyLines.push({
            xAxis: s,
            lineStyle: { color, type: 'dotted', width: 2, opacity: 0.5 },
            label: {
              show: true,
              position: 'insideEndTop',
              formatter: pt.severity === 'critical' ? '严重' : '警告',
              color: color,
              fontSize: 9,
            },
          })
        }
      }
      if (anomalyLines.length > 0) {
        paramSeries.markLine = {
          silent: true,
          symbol: 'none',
          data: anomalyLines,
        }
      }
    }

    seriesList.push(paramSeries)

    gridIdx++
  }

  // --- DataZoom: link all X-axes ---
  const allXIndices = []
  for (let i = 0; i < gridIdx; i++) allXIndices.push(i)

  const option = {
    tooltip: {
      trigger: 'axis',
      backgroundColor: 'rgba(255,255,255,0.96)',
      borderColor: '#e5e7eb',
      textStyle: { color: '#374151', fontSize: 12 },
      order: 'valueDesc',
      formatter: function (params) {
        if (!params || params.length === 0) return ''
        const pad = (n) => String(n).padStart(2, '0')
        let timeVal = params[0].axisValue
        for (const p of params) {
          if (p.value && typeof p.value[0] === 'number' && p.value[0] > 1e12) {
            const d = new Date(p.value[0])
            timeVal = `${d.getFullYear()}-${pad(d.getMonth()+1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
            break
          }
        }
        let html = `<div style="font-weight:600;margin-bottom:4px">${timeVal}</div>`

        // Show health index
        for (const p of params) {
          if (p.seriesName === '健康指数') {
            const val = p.value && p.value[1] != null ? Math.round(p.value[1]) : '-'
            const color = val >= 85 ? '#16a34a' : val >= 60 ? '#d97706' : '#dc2626'
            html += `<div style="display:flex;justify-content:space-between;gap:16px;margin-bottom:2px">
              <span style="color:#8b5cf6">❤ ${p.seriesName}</span>
              <span style="font-weight:700;color:${color}">${val}/100</span>
            </div>`
          }
        }

        // Show alarm count band value
        for (const p of params) {
          if (p.seriesName && p.seriesName.startsWith('告警计数')) {
            const val = p.value && p.value[1] != null ? p.value[1] : 0
            html += `<div style="display:flex;justify-content:space-between;gap:16px;margin-bottom:2px">
              <span style="color:#ef4444">⚠ ${p.seriesName}</span>
              <span style="font-weight:700;color:#ef4444">${val}</span>
            </div>`
          }
        }

        // Show active alarms at this timestamp
        if (alignedRows.value.length > 0) {
          const tsStr = timeVal.replace(' ', 'T')
          const match = alignedRows.value.find(r => r.timestamp.startsWith(tsStr.substring(0, 16)))
          if (match && match.active_alarms && match.active_alarms.length > 0) {
            html += '<div style="margin-top:4px;padding-top:4px;border-top:1px solid #fee2e2">'
            html += '<div style="font-size:11px;color:#ef4444;font-weight:600;margin-bottom:2px">当前活跃告警:</div>'
            for (const al of match.active_alarms.slice(0, 5)) {
              const meta = ALARM_STATUS_META[al.status]
              const color = meta ? meta.color : '#999'
              html += `<div style="font-size:11px;color:${color};padding-left:4px">● ${al.status_name}</div>`
            }
            html += '</div>'
          }
        }

        for (const p of params) {
          if (p.seriesName === '运行状态') {
            html += `<div style="display:flex;justify-content:space-between;gap:16px">
              <span>${p.marker} ${p.seriesName}</span>
              <span style="font-weight:600;color:#22c55e">运行中</span>
            </div>`
          }
        }
        for (const p of params) {
          if (p.seriesName !== '运行状态' && p.seriesName !== '运行标注' && !p.seriesName.startsWith('告警计数')) {
            const val = p.value && p.value[1] != null ? p.value[1] : '-'
            const pKey = Object.keys(displayNames.value).find(k => displayNames.value[k] === p.seriesName) || p.seriesName
            const unit = paramUnits.value[pKey] || ''
            html += `<div style="display:flex;justify-content:space-between;gap:16px">
              <span>${p.marker} ${p.seriesName}</span>
              <span style="font-weight:500">${val}${unit ? ' ' + unit : ''}</span>
            </div>`
          }
        }
        return html
      },
    },
    grid: grids,
    xAxis: xAxes,
    yAxis: yAxes,
    series: seriesList,
    dataZoom: [
      {
        type: 'slider', xAxisIndex: allXIndices,
        start: 0, end: 100, height: 24, bottom: 30,
        borderColor: '#e5e7eb', backgroundColor: '#f9fafb',
        fillerColor: 'rgba(245, 158, 11, 0.1)',
        handleStyle: { color: '#f59e0b', borderColor: '#f59e0b' },
        textStyle: { color: '#9ca3af', fontSize: 10 },
        dataBackground: {
          lineStyle: { color: '#d1d5db' },
          areaStyle: { color: 'rgba(245, 158, 11, 0.05)' },
        },
        selectedDataBackground: {
          lineStyle: { color: '#f59e0b' },
          areaStyle: { color: 'rgba(245, 158, 11, 0.1)' },
        },
      },
      { type: 'inside', xAxisIndex: allXIndices },
    ],
    animation: true,
  }

  chartInstance.setOption(option, true)
  chartInstance.resize()
}

function buildOverlayChart() {
  if (!chartContainer.value || visibleKeys.value.length === 0) return

  chartInstance = echarts.init(chartContainer.value)

  const queryStart = new Date(startTime.value).getTime()
  const queryEnd = new Date(endTime.value).getTime()
  const hasRunning = runningPeriods.value.length > 0
  const hasAlarms = showAlarmOverlay.value && alarmEvents.value.length > 0
  const hasAnomaly = showAnomalyDetection.value && healthTimeline.value.length > 0

  // 参数分组 - 只处理已加载的数据
  const loadedVisibleKeys = visibleKeys.value.filter(k => seriesData.value[k])
  const groups = groupParams(loadedVisibleKeys)
  const groupNames = Object.keys(groups)
  if (groupNames.length === 0) return

  const groupHeight = 220
  const topBands = (hasRunning ? 36 : 0) + (hasAnomaly ? 44 : 0) + (hasAlarms ? 40 : 0)
  const totalHeight = topBands + groupNames.length * groupHeight + 72

  const grids = []
  const xAxes = []
  const yAxes = []
  const seriesList = []
  let gridIdx = 0

  // ── 顶部告警/运行频带 ──
  if (hasRunning) {
    grids.push({ left: 60, right: 60, top: 4, height: 32 })
    xAxes.push({ type: 'time', gridIndex: gridIdx, min: queryStart, max: queryEnd, axisLine: { show: false }, axisTick: { show: false }, axisLabel: { show: false }, splitLine: { show: false } })
    yAxes.push({ type: 'value', gridIndex: gridIdx, min: 0, max: 1, show: false })
    const statusData = []
    for (const p of [...runningPeriods.value].sort((a,b) => parseTime(a.start_time)-parseTime(b.start_time))) {
      const s = parseTime(p.start_time); const e = p.end_time ? parseTime(p.end_time) : null
      if (s) { statusData.push([s,1]); if (e) statusData.push([e,0]) }
    }
    seriesList.push({ name: '运行', type: 'line', step: 'start', symbol: 'none', lineStyle: { width: 0 }, areaStyle: { color: 'rgba(34,197,94,0.35)' }, data: statusData, xAxisIndex: gridIdx, yAxisIndex: gridIdx, silent: true })
    gridIdx++
  }

  // 健康指数带
  if (hasAnomaly) {
    const top = (hasRunning ? 38 : 4)
    grids.push({ left: 60, right: 60, top, height: 40 })
    xAxes.push({ type: 'time', gridIndex: gridIdx, min: queryStart, max: queryEnd, axisLine: { show: false }, axisTick: { show: false }, axisLabel: { show: false } })
    yAxes.push({ type: 'value', gridIndex: gridIdx, min: 0, max: 100, axisLabel: { show: true, color: '#8b5cf6', fontSize: 9 }, axisLine: { show: false }, axisTick: { show: false }, splitLine: { show: false }, name: '健康指数', nameLocation: 'middle', nameGap: 30, nameTextStyle: { color: '#8b5cf6', fontSize: 9 } })
    const hd = healthTimeline.value.map(p => [parseTime(p.timestamp), p.health_index]).filter(d => d[0])
    seriesList.push({ name: '健康指数', type: 'line', smooth: true, symbol: 'none', lineStyle: { width: 2, color: '#8b5cf6' }, areaStyle: { color: { type: 'linear', x:0,y:0,x2:0,y2:1, colorStops: [{offset:0,color:'rgba(139,92,246,0.2)'},{offset:0.6,color:'rgba(245,158,11,0.08)'},{offset:1,color:'rgba(239,68,68,0.2)'}] } }, data: hd, xAxisIndex: gridIdx, yAxisIndex: gridIdx, silent: true })
    gridIdx++
  }

  // 告警计数带
  if (hasAlarms) {
    const top = (hasRunning ? 38 : 4) + (hasAnomaly ? 46 : 0)
    grids.push({ left: 60, right: 60, top, height: 36 })
    xAxes.push({ type: 'time', gridIndex: gridIdx, min: queryStart, max: queryEnd, axisLine: { show: false }, axisTick: { show: false }, axisLabel: { show: false } })
    yAxes.push({ type: 'value', gridIndex: gridIdx, axisLabel: { show: true, color: '#ef4444', fontSize: 9 }, axisLine: { show: false }, axisTick: { show: false }, name: `告警(${alarmWindowMin.value}min)`, nameLocation: 'middle', nameGap: 30, nameTextStyle: { color: '#ef4444', fontSize: 9 } })
    const cd = alignedRows.value.map(r => [parseTime(r.timestamp), r['alarm_count_'+alarmWindowMin.value+'min']||0]).filter(d => d[0])
    seriesList.push({ name: '告警计数', type: 'line', step: 'start', symbol: 'none', lineStyle: { width: 1.5, color: '#ef4444' }, areaStyle: { color: 'rgba(239,68,68,0.06)' }, data: cd, xAxisIndex: gridIdx, yAxisIndex: gridIdx, silent: true })
    gridIdx++
  }

  // ── 参数分组叠加图 ──
  let groupColorIdx = 0
  for (const gname of groupNames) {
    const gparams = groups[gname].params
    const isLast = (gname === groupNames[groupNames.length - 1])
    const top = topBands + (groupNames.indexOf(gname)) * groupHeight + 8

    grids.push({ left: 70, right: groupColorIdx > 0 ? 70 : 16, top, height: groupHeight - 12 })

    xAxes.push({
      type: 'time', gridIndex: gridIdx, min: queryStart, max: queryEnd,
      axisLine: { show: isLast, lineStyle: { color: '#e5e7eb' } },
      axisTick: { show: isLast },
      axisLabel: { show: isLast, color: '#6b7280', fontSize: 11, hideOverlap: true },
      splitLine: { show: true, lineStyle: { color: '#f3f4f6', type: 'dashed' } },
    })

    // 左侧Y轴（第一个参数）
    const p0 = gparams[0]
    const unit0 = paramUnits.value[p0] || groups[gname].unit || ''
    yAxes.push({
      type: 'value', gridIndex: gridIdx, scale: true,
      axisLabel: { show: true, color: groupColor(groupColorIdx), fontSize: 9 },
      axisLine: { show: false }, axisTick: { show: false },
      splitLine: { lineStyle: { color: '#f3f4f6', type: 'dashed' } },
      name: unit0 ? `${gname} (${unit0})` : gname,
      nameLocation: 'middle', nameGap: 35,
      nameTextStyle: { color: groupColor(groupColorIdx), fontSize: 10, fontWeight: 600 },
    })

    // 每个参数一条曲线，共用左Y轴
    for (let pi = 0; pi < gparams.length; pi++) {
      const pname = gparams[pi]
      const color = SERIES_COLORS[(groupColorIdx + pi) % SERIES_COLORS.length]
      const data = getSeries(pname)
      const pts = data.map(d => [parseTime(d.time), d.value]).filter(d => d[0] != null)
      const label = (displayNames.value[pname] || pname) + (paramUnits.value[pname] ? ' ('+paramUnits.value[pname]+')' : '')
      const isStageParam = pname.includes('_Stage') || pname.includes('Stage')

      seriesList.push({
        name: label, type: 'line',
        step: isStageParam ? 'start' : undefined,
        smooth: isStageParam ? false : true,
        symbol: 'none',
        lineStyle: { width: isStageParam ? 2.5 : 1.5, color },
        data: pts, xAxisIndex: gridIdx, yAxisIndex: gridIdx,
        connectNulls: isStageParam ? false : true,
      })
    }

    // 运行时段背景 + 告警标记
    const markAreas = []
    if (hasRunning) {
      for (const p of [...runningPeriods.value].sort((a,b) => parseTime(a.start_time)-parseTime(b.start_time))) {
        const s = parseTime(p.start_time); const e = p.end_time ? parseTime(p.end_time) : Date.now()
        if (s && e) markAreas.push([{ xAxis: s, itemStyle: { color: 'rgba(34,197,94,0.04)' } }, { xAxis: e }])
      }
    }
    // 告警标记线
    const markLines = []
    if (hasAlarms) {
      for (const ev of alarmEvents.value) {
        const code = ev.status
        if (!alarmTypeFilter.value.includes(code)) continue
        const meta = ALARM_STATUS_META[code]; if (!meta) continue
        const s = parseTime(ev.start_time); if (!s) continue
        markLines.push({ xAxis: s, lineStyle: { color: meta.color, type: 'dashed', width: 1.5, opacity: 0.6 }, label: { show: true, position: 'insideEndTop', formatter: meta.name, color: meta.color, fontSize: 9 } })
      }
    }
    // 异常标记
    if (hasAnomaly) {
      for (const pt of healthTimeline.value) {
        if (pt.is_anomaly) {
          const s = parseTime(pt.timestamp); if (!s) continue
          markLines.push({ xAxis: s, lineStyle: { color: pt.severity==='critical'?'#ef4444':'#f59e0b', type: 'dotted', width: 2, opacity: 0.4 }, label: { show: false } })
        }
      }
    }

    // 给第一个参数系列附加 markArea/markLine
    if (seriesList.length > 0 && gparams.length > 0) {
      const firstSeries = seriesList[seriesList.length - gparams.length]
      if (markAreas.length > 0) firstSeries.markArea = { silent: true, data: markAreas }
      if (markLines.length > 0) firstSeries.markLine = { silent: true, symbol: 'none', data: markLines }
    }

    groupColorIdx++
    gridIdx++
  }

  const allXIndices = Array.from({length: gridIdx}, (_, i) => i)

  chartInstance.setOption({
    tooltip: {
      trigger: 'axis',
      backgroundColor: 'rgba(255,255,255,0.96)',
      borderColor: '#e5e7eb',
      textStyle: { color: '#374151', fontSize: 12 },
      formatter: function(ps) {
        if (!ps || !ps.length) return ''
        let t = ''
        for (const p of ps) {
          if (p.value && p.value[0] > 1e12) { const d = new Date(p.value[0]); const pad = n => String(n).padStart(2,'0'); t = `${d.getFullYear()}-${pad(d.getMonth()+1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`; break }
        }
        let h = `<div style="font-weight:600;margin-bottom:4px">${t}</div>`
        if (hasAnomaly) {
          const match = healthTimeline.value.find(pt => {
            const pdt = parseTime(pt.timestamp)
            const firstPt = ps[0].value && ps[0].value[0]
            return pdt && firstPt && Math.abs(pdt - firstPt) < 150000
          })
          if (match) h += `<div style="color:#8b5cf6;font-size:11px">健康指数: ${match.health_index}/100 ${match.severity==='critical'?'🔴':match.severity==='warning'?'🟡':'🟢'}</div>`
        }
        for (const p of ps) {
          if (['运行','健康指数','告警计数'].includes(p.seriesName)) continue
          const val = p.value && p.value[1] != null ? (typeof p.value[1] === 'number' ? p.value[1].toFixed(2) : p.value[1]) : '-'
          h += `<div style="display:flex;justify-content:space-between;gap:12px"><span>${p.marker}${p.seriesName}</span><span style="font-weight:500">${val}</span></div>`
        }
        return h
      },
    },
    grid: grids, xAxis: xAxes, yAxis: yAxes,
    series: seriesList,
    dataZoom: [
      { type: 'slider', xAxisIndex: allXIndices, start: 0, end: 100, height: 24, bottom: 30, borderColor: '#e5e7eb', backgroundColor: '#f9fafb', fillerColor: 'rgba(245,158,11,0.1)', handleStyle: { color: '#f59e0b' }, textStyle: { color: '#9ca3af', fontSize: 10 } },
      { type: 'inside', xAxisIndex: allXIndices },
    ],
    animation: true,
  }, true)
  chartInstance.resize()
}

function disposeChart() {
  if (chartInstance && !chartInstance.isDisposed()) {
    chartInstance.dispose()
  }
  chartInstance = null
}

function handleResize() {
  stateCardRef.value?.resizeStateTimeline()
  if (chartInstance && !chartInstance.isDisposed()) {
    chartInstance.resize()
  }
}

async function startAnalysis() {
  if (!selectedDevice.value || seriesKeys.value.length === 0) return

  analyzing.value = true
  analysisResult.value = ''
  analysisResultMeta.value = ''
  analysisError.value = ''

  try {
    const res = await analyzeDeviceParams({
      device_code: selectedDevice.value,
      device_name: currentDeviceName(),
      start_time: formatForApi(startTime.value),
      end_time: formatForApi(endTime.value),
      analyze_running_only: analyzeRunningOnly.value,
    })

    if (res.code === 200 && res.data?.analysis) {
      analysisResult.value = res.data.analysis
      if (showAnalysisLog.value) loadAnalysisLog()
    } else {
      analysisError.value = res.msg || '分析请求失败'
    }
  } catch (err) {
    analysisError.value = err.message || '分析请求失败'
  } finally {
    analyzing.value = false
  }
}

async function toggleAnalysisLog() {
  showAnalysisLog.value = !showAnalysisLog.value
  if (showAnalysisLog.value) {
    await loadAnalysisLog()
    await nextTick()
    const el = document.getElementById('analysis-history-section')
    if (el) el.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }
}

// 状态分析出结果后自动落库（原弹窗底部的“确认”按钮已取消）。
// 只推进度 + 存快照，不带 classified/checked_params，避免冲掉「参数设定」页的筛选结果
function persistStateSnapshot() {
  if (!stateResult.value || stateResult.value.source) return
  client.post('/device-params/screen-state', {
    device_code: selectedDevice.value,
    workflow_step: 4,
    pulse_param: pulseParam.value, state_data: stateResult.value,
  }).catch(() => {})
}

// ── 标准节拍基准（性能效率的分子）──
// 冻结在配置里、不随分析窗口漂移，否则设备整体变慢时 P10 跟着变慢，劣化被掩盖
// 读取「参数设定」页筛选保存的 checked_params —— 本页参数范围唯一依据，返回非空数组；
// 没筛选过(无记录/从未保存)时返回 null，由调用方(loadData)回退到该设备全部参数。
// 顺带同步 pulse_param / workflow_step / state_data，供其它 tab(状态/KPI/阶段CPK)使用。
async function loadScreenStateFromDb() {
  try {
    const r = await client.get('/device-params/screen-state', { params: { device_code: selectedDevice.value } })
    if (r.code === 200 && r.data) {
      workflowStep.value = r.data.workflow_step || 2
      if (r.data.pulse_param) pulseParam.value = r.data.pulse_param
      if (r.data.checked_params?.length) return r.data.checked_params
    }
  } catch (e) {}
  return null
}

async function loadAnalysisLog() {
  if (!selectedDevice.value) return
  analysisLogLoading.value = true
  try {
    const res = await getAnalysisLog({ device_code: selectedDevice.value, limit: 20 })
    analysisLogItems.value = (res.code === 200 && res.data?.items) ? res.data.items : []
  } catch (err) {
    analysisLogItems.value = []
  } finally {
    analysisLogLoading.value = false
  }
}

function viewAnalysisLogItem(item) {
  analysisResult.value = item.analysis
  analysisResultMeta.value = `历史记录 · ${item.created_at}`
  analysisError.value = ''
}

onMounted(async () => {
  await loadDevices()
  const deviceFromQuery = route.query.device
  if (deviceFromQuery && devices.value.some(d => d.device_code === deviceFromQuery)) {
    selectedDevice.value = deviceFromQuery
    onDeviceChange()
  }
  resizeHandler = () => handleResize()
  window.addEventListener('resize', resizeHandler)
})

onUnmounted(() => {
  disposeChart()
  stateCardRef.value?.disposeStateTimeline()
  energyBreakdownRef.value?.disposeEnergyCharts()

  if (resizeHandler) {
    window.removeEventListener('resize', resizeHandler)
  }
})
</script>
