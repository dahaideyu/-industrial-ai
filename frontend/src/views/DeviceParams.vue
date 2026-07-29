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
      <template v-if="activeStep === 1">
      <!-- 快捷时间范围 -->
      <div class="flex flex-wrap items-center gap-1.5 mt-3">
        <span class="text-xs text-gray-400 mr-1">快捷范围:</span>
        <button
          v-for="r in QUICK_RANGES" :key="r.key"
          @click="applyQuickRange(r)"
          class="px-2.5 py-1 rounded-full text-xs border transition-all"
          :class="activeQuickRange === r.key
            ? 'bg-amber-400 text-white border-amber-400'
            : 'bg-gray-50 text-gray-500 border-gray-200 hover:border-gray-300'"
        >{{ r.label }}</button>
        <span v-if="activeQuickRange === 'custom'" class="text-xs text-gray-400 ml-1">自定义范围</span>
        <span v-if="rangeWarning" class="text-xs text-amber-600 ml-2">⚠ {{ rangeWarning }}</span>
      </div>
      </template>
    </div>

    <div v-if="!selectedDevice" class="text-center py-16 text-gray-400 bg-white rounded-xl border border-gray-100 shadow-sm">
      <div class="text-4xl mb-3">🔧</div>
      <p class="text-sm">请从上方选择设备</p>
    </div>

    <!-- ① 状态：设备状态划分 + 原始参数曲线 -->
    <div v-else-if="activeStep === 1" class="space-y-6">
      <div class="bg-white rounded-xl border border-gray-100 shadow-sm p-5">
        <div class="flex items-center justify-between mb-3 flex-wrap gap-2">
          <span class="text-xs font-bold text-gray-400 uppercase tracking-wider">
            ① 状态划分<span v-if="pulseParam"> — 基于脉搏 {{ displayNames[pulseParam] || pulseParam }}</span>
          </span>
          <div class="flex items-center gap-2 text-xs text-gray-500">
            分析天数：
            <button v-for="d in [1,3,7,30]" :key="d" @click="stateDays = d; startStateAnalysis()"
              class="px-2 py-0.5 rounded" :class="stateDays === d ? 'bg-amber-100 text-amber-700' : 'hover:bg-gray-100'">{{ d }}天</button>
          </div>
        </div>
        <div v-if="!stateResult" class="text-center py-8 text-gray-400 text-sm">点上方「分析天数」开始状态划分</div>
        <div v-else-if="stateResult.source === 'loading'" class="text-center py-12 text-gray-400">⏳ 分析中...</div>
        <div v-else-if="stateResult.source === 'error'" class="text-center py-12 text-gray-400">{{ stateResult.msg }}</div>
        <template v-else>
          <div class="space-y-3">
            <div v-if="stateResult.truncate_note" class="bg-amber-50 border border-amber-200 rounded-lg p-2.5 text-xs text-amber-700">
              ⚠ {{ stateResult.truncate_note }}
            </div>
            <!-- 状态切片图：运行/非运行/离线 按时间轴铺开 -->
            <div v-if="stateResult.timeline?.length" class="border border-gray-100 rounded-lg p-3">
              <div class="flex items-center justify-between flex-wrap gap-2 mb-2">
                <span class="text-xs font-bold text-gray-500">状态切片（按时间轴）</span>
                <div class="flex items-center gap-3 text-[11px] text-gray-500">
                  <span class="flex items-center gap-1"><i class="inline-block w-3 h-2 rounded-sm" style="background:#22c55e"></i>运行 {{ stateResult.timeline_totals?.running_h }}h</span>
                  <span class="flex items-center gap-1"><i class="inline-block w-3 h-2 rounded-sm" style="background:#f59e0b"></i>非运行 {{ stateResult.timeline_totals?.idle_h }}h</span>
                  <span class="flex items-center gap-1"><i class="inline-block w-3 h-2 rounded-sm" style="background:#d1d5db"></i>离线 {{ stateResult.timeline_totals?.offline_h }}h</span>
                </div>
              </div>
              <div ref="stateTimelineEl" class="w-full" style="height: 200px"></div>
              <p class="text-[10px] text-gray-400 mt-1">
                共 {{ stateResult.timeline_totals?.segments }} 段。离线＝脉搏参数连续 {{ stateResult.timeline_gap_minutes }} 分钟以上没有上报（数据断档），
                与上方卡片按“总时长−运行−非运行”反推的离线时长口径不同，故两处数值可能有差异。
              </p>
            </div>
              <div class="grid grid-cols-3 gap-3 text-center">
                <div class="bg-green-50 rounded-lg p-3"><div class="text-green-700 font-bold text-lg">{{ stateResult.running_hours }}h</div><div class="text-green-600 text-xs">🏠 运行（房子里）</div></div>
                <div class="bg-amber-50 rounded-lg p-3"><div class="text-amber-700 font-bold text-lg">{{ stateResult.idle_hours }}h</div><div class="text-amber-600 text-xs">🌿 非运行（草坪上）</div></div>
                <div class="bg-gray-100 rounded-lg p-3"><div class="text-gray-700 font-bold text-lg">{{ stateResult.offline_hours }}h</div><div class="text-gray-500 text-xs">💤 离线</div></div>
              </div>
              <div v-if="stateResult.ai_insight" class="bg-indigo-50 rounded-lg p-3 text-xs text-indigo-700 leading-relaxed">
                💡 AI 洞察：{{ stateResult.ai_insight }}
              </div>
          </div>
        </template>
      </div>

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
    </div>

    <!-- ② 效率：资产利用率 vs 设备可用率 -->
    <div v-else-if="activeStep === 2" class="space-y-6">
      <div class="bg-white rounded-xl border border-gray-100 shadow-sm p-5">
        <div class="flex items-center justify-between mb-3 flex-wrap gap-2">
          <span class="text-xs font-bold text-gray-400 uppercase tracking-wider">② 效率 — 资产利用率（老板视角） vs 设备可用率（班长视角）</span>
          <div class="flex items-center gap-2 text-xs text-gray-500">
            分析天数：
            <button v-for="d in [1,3,7,30]" :key="d" @click="stateDays = d; startStateAnalysis()"
              class="px-2 py-0.5 rounded" :class="stateDays === d ? 'bg-amber-100 text-amber-700' : 'hover:bg-gray-100'">{{ d }}天</button>
          </div>
        </div>
        <div v-if="!stateResult" class="text-center py-8 text-gray-400 text-sm">点上方「分析天数」开始计算</div>
        <div v-else-if="stateResult.source === 'loading'" class="text-center py-12 text-gray-400">⏳ 分析中...</div>
        <div v-else-if="stateResult.source === 'error'" class="text-center py-12 text-gray-400">{{ stateResult.msg }}</div>
        <template v-else>
          <div class="space-y-3">
            <div v-if="stateResult.truncate_note" class="bg-amber-50 border border-amber-200 rounded-lg p-2.5 text-xs text-amber-700">
              ⚠ {{ stateResult.truncate_note }}
            </div>
              <div class="grid grid-cols-2 gap-3 text-center">
                <div class="bg-indigo-50 rounded-lg p-3">
                  <div class="text-indigo-700 font-bold text-xl">{{ stateResult.utilization }}%</div>
                  <div class="text-indigo-600 text-xs">🏢 资产利用率（老板视角）</div>
                  <div class="text-gray-400 text-[10px]">运行 / {{ stateResult.total_hours }}h × 100%</div>
                </div>
                <div class="bg-emerald-50 rounded-lg p-3">
                  <div class="text-emerald-700 font-bold text-xl">{{ stateResult.availability }}%</div>
                  <div class="text-emerald-600 text-xs">🔧 设备可用率（班长视角）</div>
                  <div class="text-gray-400 text-[10px]">(运行+非运行) / {{ stateResult.total_hours }}h × 100%</div>
                </div>
              </div>
              <div v-if="stateResult.daily_breakdown?.length" class="border rounded-lg">
                <div class="px-3 py-2 bg-gray-50 text-xs font-bold text-gray-500 border-b">每日明细（点击展开）</div>
                <div v-for="d in stateResult.daily_breakdown" :key="d.date"
                  class="px-3 py-1.5 border-b border-gray-50 text-xs flex items-center gap-3 cursor-pointer hover:bg-gray-50"
                  @click="d._open = !d._open">
                  <span class="w-20">{{ d.date.slice(5) }}</span>
                  <span class="text-green-600 w-12 text-right">{{ d.running_h }}h</span>
                  <span class="text-amber-600 w-12 text-right">{{ d.idle_h }}h</span>
                  <span class="text-gray-400 w-12 text-right">{{ d.offline_h }}h</span>
                  <span class="font-bold w-12 text-right">{{ d.utilization }}%</span>
                  <span class="text-gray-400">{{ d.segments }}次切换</span>
                </div>
              </div>
          </div>
        </template>
      </div>
    </div>

    <!-- ③ KPI：产量/OEE/节拍/能耗 -->
    <div v-else-if="activeStep === 3" class="space-y-6">
      <div class="bg-white rounded-xl border border-gray-100 shadow-sm p-5">
        <div class="flex items-center justify-between mb-3 flex-wrap gap-2">
          <span class="text-xs font-bold text-gray-400 uppercase tracking-wider">③ KPI — 产量 / OEE / 节拍 / 能耗</span>
          <div class="flex items-center gap-2 text-xs text-gray-500">
            分析天数：
            <button v-for="d in [1,3,7,30]" :key="d" @click="kpiDays = d; startKpiAnalysis()"
              class="px-2 py-0.5 rounded" :class="kpiDays === d ? 'bg-amber-100 text-amber-700' : 'hover:bg-gray-100'">{{ d }}天</button>
          </div>
        </div>
        <div v-if="!kpiResult" class="text-center py-8 text-gray-400 text-sm">点上方「分析天数」开始计算 KPI</div>
        <div v-else class="space-y-3">
            <div v-if="kpiResult.source === 'loading'" class="text-center py-12 text-gray-400">⏳ 计算中...</div>
            <div v-else-if="kpiResult.source === 'error'" class="text-center py-12 text-gray-400">{{ kpiResult.msg }}</div>
            <template v-else>
              <div v-if="kpiCards.length > 1" class="text-xs text-gray-500 text-center">
                按"房子形状"识别出 {{ kpiCards.length - 1 }} 种产品型号，最后一张是设备整体汇总
              </div>
              <div v-if="kpiResult.type_insight" class="bg-amber-50 rounded-lg p-3 text-xs text-amber-800 leading-relaxed">
                🔍 型号划分判断：{{ kpiResult.type_insight }}
              </div>

              <div v-for="kpi in kpiCards" :key="kpi.type_label" class="border border-gray-100 rounded-lg p-3 space-y-3">
                <div class="text-sm font-bold text-gray-700">
                  {{ kpi.type_label }}
                  <span v-if="kpi.batch_count != null" class="text-xs font-normal text-gray-400">（{{ kpi.batch_count }}个循环）</span>
                </div>
                <div v-if="kpi.signature" class="text-[10px] text-gray-400">特征：{{ kpi.signature }}</div>

                <div class="grid grid-cols-3 gap-3 text-center">
                  <div class="bg-sky-50 rounded-lg p-3">
                    <div class="text-sky-700 font-bold text-lg">{{ kpi.total_cycles }}</div>
                    <div class="text-sky-600 text-xs">总循环数（房子）</div>
                  </div>
                  <div class="bg-green-50 rounded-lg p-3">
                    <div class="text-green-700 font-bold text-lg">{{ kpi.output_count }}</div>
                    <div class="text-green-600 text-xs">产量（已剔除空跑{{ kpi.empty_run_count }}次）</div>
                  </div>
                  <div class="bg-violet-50 rounded-lg p-3">
                    <div class="text-violet-700 font-bold text-lg">{{ kpi.pass_rate != null ? kpi.pass_rate + '%' : '—' }}</div>
                    <div class="text-violet-600 text-xs">合格率<span v-if="kpi.quality_status !== 'ok'">（{{ kpi.quality_status === 'no_confirmed_spec' ? '暂无已确认规格限' : kpi.quality_status }}）</span></div>
                  </div>
                </div>

                <div class="bg-gray-50 rounded-lg p-3">
                  <div class="text-xs text-gray-500 mb-2">OEE = 可用率 × 性能效率 × 合格率</div>
                  <div class="flex items-center justify-center gap-2 text-sm">
                    <span class="text-emerald-700 font-medium">{{ kpi.availability != null ? kpi.availability + '%' : '—' }}</span>
                    <span class="text-gray-300">×</span>
                    <span class="text-amber-700 font-medium">{{ kpi.performance != null ? kpi.performance : '—' }}</span>
                    <span class="text-gray-300">×</span>
                    <span class="text-violet-700 font-medium">{{ kpi.pass_rate != null ? (kpi.pass_rate / 100).toFixed(2) : '—' }}</span>
                    <span class="text-gray-300">=</span>
                    <span class="text-gray-900 font-bold text-lg">{{ kpi.oee != null ? kpi.oee + '%' : '—' }}</span>
                  </div>
                  <div v-if="kpi.oee_note" class="text-center text-[10px] text-gray-400 mt-1">{{ kpi.oee_note }}</div>
                  <div class="text-center text-[10px] text-gray-400 mt-1">性能效率 = P10最快批次节拍 / 实际平均节拍（近似值，非工艺标准节拍）</div>
                </div>

                <div class="grid grid-cols-2 gap-3">
                  <div class="bg-white border border-gray-100 rounded-lg p-3">
                    <div class="text-xs text-gray-500 mb-1">节拍（有效批次）</div>
                    <div class="text-xs text-gray-700">均值 {{ kpi.cycle_time.mean_min ?? '—' }} 分钟</div>
                    <div class="text-xs text-gray-700">中位 {{ kpi.cycle_time.median_min ?? '—' }} 分钟</div>
                    <div class="text-xs text-gray-700">P10 {{ kpi.cycle_time.p10_min ?? '—' }} 分钟</div>
                  </div>
                  <div class="bg-white border border-gray-100 rounded-lg p-3">
                    <div class="text-xs text-gray-500 mb-1">能耗</div>
                    <div class="text-xs text-gray-700">有效 {{ kpi.energy.valid_kwh }}</div>
                    <div class="text-xs text-gray-700">空跑 {{ kpi.energy.empty_run_kwh }}</div>
                    <div class="text-xs text-gray-700">单件 {{ kpi.energy.per_unit_kwh ?? '—' }}</div>
                  </div>
                </div>

                <div v-if="kpi.empty_run_status !== 'ok'" class="text-[10px] text-gray-400 text-center">
                  空跑判定：{{ kpi.empty_run_status === 'no_weight_param' ? '该设备没有已识别的重量类参数，本次未剔除空跑（产量=总循环数）' : kpi.empty_run_status }}
                </div>

                <div v-if="kpi.ai_insight" class="bg-indigo-50 rounded-lg p-3 text-xs text-indigo-800 leading-relaxed">
                  💡 {{ kpi.ai_insight }}
                </div>
              </div>
            </template>
        </div>
      </div>
    </div>

    <!-- ④ 阶段：阶段分析 + CPK/公差/能耗逐段 -->
    <div v-else-if="activeStep === 4" class="space-y-6">
      <div class="bg-white rounded-xl border border-gray-100 shadow-sm p-5">
        <div class="flex items-center justify-between mb-3 flex-wrap gap-2">
          <span class="text-xs font-bold text-gray-400 uppercase tracking-wider">④ 阶段 — CPK / 公差 / 能耗逐段分析</span>
          <div class="flex items-center gap-2 text-xs text-gray-500">
            分析天数：
            <button v-for="d in [3,7,15,30]" :key="d" @click="stageCpkDays = d; startStageCpkAnalysis()"
              class="px-2 py-0.5 rounded" :class="stageCpkDays === d ? 'bg-amber-100 text-amber-700' : 'hover:bg-gray-100'">{{ d }}天</button>
          </div>
        </div>
        <div v-if="!stageCpkResult" class="text-center py-8 text-gray-400 text-sm">点上方「分析天数」开始逐段 CPK 分析</div>
        <div v-else class="space-y-3">
            <div v-if="stageCpkResult.source === 'loading'" class="text-center py-12 text-gray-400">⏳ 计算中...</div>
            <div v-else-if="stageCpkResult.source === 'error'" class="text-center py-12 text-gray-400">{{ stageCpkResult.msg }}</div>
            <template v-else>
              <div v-for="s in stageCpkResult.stages" :key="s.stage" class="border border-gray-100 rounded-lg p-3">
                <div class="text-xs font-bold text-gray-700 mb-2">阶段 {{ s.stage }}</div>

                <div class="text-xs text-gray-600 mb-1" v-if="s.duration_cpk">
                  <template v-if="s.duration_cpk.cpk != null">
                    时长：{{ s.duration_cpk.mean_min }}±{{ s.duration_cpk.std_min }}分钟，
                    规格[{{ s.duration_cpk.spec_low_min }}, {{ s.duration_cpk.spec_high_min }}]，
                    CPK={{ s.duration_cpk.cpk }}，超差 {{ s.duration_cpk.out_of_spec_count }}/{{ s.duration_cpk.n }}
                    ({{ s.duration_cpk.out_of_spec_ratio }}%)
                  </template>
                  <template v-else>时长：{{ s.duration_cpk.note }}</template>
                </div>

                <div v-if="Object.keys(s.param_stats || {}).length" class="text-xs text-gray-500 space-y-0.5 mb-1">
                  <div v-for="(stat, pname) in s.param_stats" :key="pname">
                    {{ stat.display_name }}：均值 {{ stat.mean }}{{ stat.unit }} (±{{ stat.std }})
                    <span v-if="stat.cpk != null">，规格[{{ stat.spec_low }}, {{ stat.spec_high }}]，CPK={{ stat.cpk }}</span>
                  </div>
                </div>

                <div v-if="s.energy_avg != null" class="text-xs text-gray-500 mb-1">阶段平均能耗：{{ s.energy_avg }}</div>

                <div v-if="s.ai_insight" class="text-xs text-indigo-700 bg-indigo-50 rounded p-2 mt-1">💡 {{ s.ai_insight }}</div>
              </div>
            </template>
        </div>
      </div>

      <!-- 阶段分析（独立组件，自行加载数据）-->
      <StageAnalysis :key="selectedDevice" :device-code="selectedDevice" />
    </div>
    <!-- AI Analysis History（所有 tab 可见）-->
    <div v-if="showAnalysisLog" id="analysis-history-section" class="bg-white rounded-xl border border-gray-100 shadow-sm p-5">
      <div class="flex items-center justify-between mb-3">
        <h2 class="font-headline text-base font-semibold text-gray-900">历史 AI 分析</h2>
        <span class="text-xs text-gray-400">{{ analysisLogLoading ? '加载中...' : `共 ${analysisLogItems.length} 条` }}</span>
      </div>
      <div v-if="!analysisLogLoading && analysisLogItems.length === 0" class="text-xs text-gray-400">
        暂无历史分析记录，点击"AI 分析"生成第一条。
      </div>
      <ul v-else class="divide-y divide-gray-100">
        <li v-for="item in analysisLogItems" :key="item.id"
          class="py-2.5 flex items-center justify-between gap-3 cursor-pointer hover:bg-gray-50 rounded-lg px-2"
          @click="viewAnalysisLogItem(item)"
        >
          <div class="min-w-0">
            <div class="text-sm text-gray-800 truncate">{{ item.start_time }} ~ {{ item.end_time }}</div>
            <div class="text-xs text-gray-400">{{ item.created_at }}{{ item.running_only ? ' · 仅运行时段' : '' }}</div>
          </div>
          <span class="text-xs text-violet-500 shrink-0">查看 →</span>
        </li>
      </ul>
    </div>
    <!-- AI Analysis Modal -->
    <Teleport to="body">
      <div v-if="analysisResult || analysisError" class="fixed inset-0 z-50 flex items-center justify-center p-4" @click.self="analysisResult = ''; analysisResultMeta = ''; analysisError = ''">
        <div class="absolute inset-0 bg-black/40"></div>
        <div class="relative bg-white rounded-2xl shadow-2xl w-full max-w-4xl max-h-[85vh] flex flex-col">
          <div class="flex items-center justify-between px-6 py-4 border-b border-gray-100 shrink-0">
            <h2 class="text-lg font-bold text-gray-900">
              {{ analysisError ? '分析失败' : 'AI 分析结果' }}
              <span v-if="analysisResultMeta" class="ml-2 text-xs font-normal text-gray-400">{{ analysisResultMeta }}</span>
            </h2>
            <button
              @click="analysisResult = ''; analysisResultMeta = ''; analysisError = ''"
              class="text-gray-400 hover:text-gray-600 text-xl leading-none px-2"
            >✕</button>
          </div>
          <div class="overflow-y-auto px-6 py-4 flex-1">
            <div v-if="analysisError" class="text-red-600 text-sm">{{ analysisError }}</div>
            <div v-else class="prose prose-sm max-w-none text-gray-700 leading-relaxed" v-html="analysisResultHtml"></div>
          </div>
          <div class="flex items-center justify-between px-6 py-3 border-t border-gray-100 shrink-0">
            <div class="flex items-center gap-2 text-xs text-gray-400">
              <template v-if="!analysisError">
                分析时间：{{ startTime }} ~ {{ endTime }}
                <span v-if="analyzeRunningOnly" class="text-green-500">· 仅运行时段</span>
              </template>
            </div>
            <div class="flex items-center gap-2">
              <button @click="startAnalysis()" :disabled="analyzing"
                class="px-4 py-2 text-sm bg-violet-500 text-white rounded-lg hover:bg-violet-600 disabled:opacity-50">
                {{ analyzing ? '分析中...' : '重新分析' }}
              </button>
              <button @click="analysisResult = ''; analysisResultMeta = ''; analysisError = ''"
                class="px-4 py-2 text-sm bg-gray-100 rounded-lg hover:bg-gray-200">关闭</button>
            </div>
          </div>
        </div>
      </div>
    </Teleport>
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
import { marked } from 'marked'

const route = useRoute()
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
const stateDays = ref(7)
const kpiResult = ref(null)
const kpiDays = ref(1)
// 识别出≥2种型号时，逐型号卡片 + 末尾追加"整体"汇总卡片；只有一种型号时只显示整体卡片
const kpiCards = computed(() => {
  const r = kpiResult.value
  if (!r || r.source) return []
  if (r.product_types && r.product_types.length >= 2) return [...r.product_types, r.overall]
  return r.overall ? [r.overall] : []
})
// ── 状态切片图（运行/非运行/离线 时间轴）──
const stateTimelineEl = ref(null)
let stateTimelineChart = null
const STATE_META = {
  running: { name: '运行', color: '#22c55e' },
  idle: { name: '非运行', color: '#f59e0b' },
  offline: { name: '离线', color: '#d1d5db' },
}
// 阶段颜色（用于合膏机等有Tec_Stage参数的设备），不同阶段用不同色调
const STAGE_COLORS = [
  '#22c55e', '#16a34a', '#15803d', '#14532d',  // green shades
  '#3b82f6', '#2563eb', '#1d4ed8',              // blue shades
  '#8b5cf6', '#7c3aed', '#6d28d9',              // purple shades
  '#ec4899', '#db2777', '#be185d',              // pink shades
  '#f59e0b', '#d97706', '#b45309',              // amber shades
]

function getStageColor(stage) {
  if (stage == null) return undefined
  const s = Math.round(Number(stage))
  if (isNaN(s)) return undefined
  return STAGE_COLORS[s % STAGE_COLORS.length]
}

function getStageName(stage) {
  if (stage == null) return ''
  const s = Math.round(Number(stage))
  if (isNaN(s)) return ''
  if (s === 0) return '待机'
  return `阶段${s}`
}

function disposeStateTimeline() {
  if (stateTimelineChart && !stateTimelineChart.isDisposed()) stateTimelineChart.dispose()
  stateTimelineChart = null
}

function renderStateTimeline() {
  const tl = stateResult.value?.timeline
  if (!stateTimelineEl.value) return
  if (!tl || tl.length === 0) return
  if (!stateTimelineChart || stateTimelineChart.isDisposed()) {
    stateTimelineChart = echarts.init(stateTimelineEl.value)
  }

  const runningSegs = stateResult.value?.running_segments

  // 判断是否有阶段数据（运行段中有 stage 字段）
  let hasStages = false
  const stageSet = new Set()
  if (runningSegs && runningSegs.length > 0) {
    for (const rs of runningSegs) {
      if (rs.stage != null) {
        hasStages = true
        stageSet.add(Math.round(Number(rs.stage)))
      }
    }
  }

  // 为每个 timeline 段匹配 running_segments 中的 stage（用于运行段着色和 tooltip）
  const stageBySeg = new Map()
  if (hasStages) {
    for (const seg of tl) {
      if (seg.state !== 'running') continue
      const segStart = parseTime(seg.start)
      const segEnd = parseTime(seg.end)
      if (segStart == null || segEnd == null) continue
      let bestStage = null
      let bestOverlap = 0
      for (const rs of runningSegs) {
        const rsStart = parseTime(rs.start)
        const rsEnd = parseTime(rs.end)
        if (rsStart == null || rsEnd == null) continue
        const overlap = Math.min(segEnd, rsEnd) - Math.max(segStart, rsStart)
        if (overlap > bestOverlap) {
          bestOverlap = overlap
          bestStage = rs.stage
        }
      }
      const key = `${seg.start}_${seg.end}`
      stageBySeg.set(key, bestStage)
    }
  }

  // 三行：离线(0)、非运行(1)、运行(2)
  const categories = ['离线', '非运行', '运行']
  const stateToRow = { offline: 0, idle: 1, running: 2 }

  const data = tl.map((seg, idx) => {
    const s = parseTime(seg.start)
    const e = parseTime(seg.end)
    const row = stateToRow[seg.state] ?? 0
    const key = `${seg.start}_${seg.end}`
    const stage = stageBySeg.get(key)
    const baseColor = STATE_META[seg.state]?.color || '#d1d5db'
    const color = seg.state === 'running' && stage != null
      ? (getStageColor(stage) || baseColor)
      : baseColor
    return {
      value: [row, s, e, e - s],
      itemStyle: { color, borderRadius: seg.state === 'running' ? 2 : 0 },
      state: seg.state,
      hours: seg.hours,
      stage: stage,
    }
  })

  stateTimelineChart.setOption({
    animation: false,
    grid: { left: 70, right: 20, top: hasStages ? 22 : 8, bottom: 52 },
    tooltip: {
      confine: true,
      trigger: 'item',
      formatter: (p) => {
        if (!p.data || !p.data.value) return ''
        const meta = STATE_META[p.data.state] || {}
        const fmt = (t) => new Date(t).toLocaleString('zh-CN', { hour12: false, month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
        let stageInfo = ''
        if (p.data.stage != null) {
          stageInfo = `<br/>合膏阶段: ${getStageName(p.data.stage)}`
        }
        return `<b>${meta.name || p.data.state}</b>${stageInfo}<br/>${fmt(p.value[1])} ~ ${fmt(p.value[2])}<br/>时长 ${p.data.hours} 小时`
      },
    },
    xAxis: {
      type: 'time',
      axisLabel: { fontSize: 11, color: '#6b7280', hideOverlap: true },
      axisLine: { lineStyle: { color: '#d1d5db' } },
      splitLine: { show: true, lineStyle: { color: '#f3f4f6', type: 'dashed' } },
    },
    yAxis: {
      type: 'category',
      data: categories,
      axisTick: { show: false },
      axisLine: { show: false },
      axisLabel: { fontSize: 12, color: '#374151', fontWeight: 500 },
      inverse: true,
    },
    dataZoom: [
      { type: 'slider', height: 16, bottom: 8, xAxisIndex: 0 },
      { type: 'inside', xAxisIndex: 0 },
    ],
    series: [{
      type: 'custom',
      renderItem: (params, api) => {
        const rowIdx = api.value(0)
        const startPt = api.coord([api.value(1), rowIdx])
        const endPt = api.coord([api.value(2), rowIdx])
        const rowHeight = api.size([0, 1])[1] * 0.65
        const y = startPt[1] - rowHeight / 2
        const rect = echarts.graphic.clipRectByRect(
          { x: startPt[0], y: y, width: Math.max(endPt[0] - startPt[0], 1), height: rowHeight },
          { x: params.coordSys.x, y: params.coordSys.y, width: params.coordSys.width, height: params.coordSys.height },
        )
        if (!rect) return null
        // 短段时间标注
        const el = { type: 'rect', shape: rect, style: api.style() }
        const durHours = api.value(3)
        const shouldLabel = durHours != null && durHours < 1 && endPt[0] - startPt[0] > 40
        if (shouldLabel) {
          return {
            type: 'group',
            children: [
              el,
              { type: 'text', x: startPt[0] + 4, y: y + rowHeight / 2, style: { text: `${(durHours * 60).toFixed(0)}min`, fill: '#6b7280', fontSize: 9, fontFamily: 'sans-serif', textVerticalAlign: 'middle' } }
            ],
          }
        }
        return el
      },
      encode: { x: [1, 2], y: 0 },
      data,
    }],
    // 阶段图例（左上角小色块）
    graphic: hasStages ? [
      { type: 'text', left: 70, top: 2, style: { text: '阶段:', fill: '#9ca3af', fontSize: 10, fontFamily: 'sans-serif' } },
      ...[...stageSet].sort((a, b) => a - b).map((s, i) => ({
        type: 'group',
        left: 100 + i * 52,
        top: 4,
        children: [
          { type: 'rect', shape: { x: 0, y: 0, width: 10, height: 10 }, style: { fill: getStageColor(s) } },
          { type: 'text', left: 14, top: 8, style: { text: getStageName(s), fill: '#6b7280', fontSize: 10, fontFamily: 'sans-serif' } },
        ],
      })),
    ] : [],
  }, true)
  stateTimelineChart.resize()
}

const stageCpkResult = ref(null)
const stageCpkDays = ref(7)

// 四个 tab 对应四个分析步骤，内容直接内联展示（不再用弹窗）
const WORKFLOW_STEPS = [
  { key: 'state', label: '①状态', desc: '数据驱动划分运行/待机/离线' },
  { key: 'efficiency', label: '②效率', desc: '资产利用率(老板) vs 设备可用率(班长)' },
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

// 时间范围：默认最近 24 小时；默认最大30天，通过dataZoom可拖拽查看历史数据
const MAX_RANGE_DAYS = 30
const _initEnd = new Date()
const _initStart = new Date(_initEnd.getTime() - 24 * 3600 * 1000)
const startTime = ref(toDatetimeLocal(_initStart))
const endTime = ref(toDatetimeLocal(_initEnd))
const activeQuickRange = ref('24h')   // 当前选中的快捷范围（'custom' 表示手动）
const rangeWarning = ref('')

const QUICK_RANGES = [
  { key: '24h', label: '最近24小时', hours: 24 },
  { key: '3d',  label: '最近3天', hours: 72 },
  { key: '7d',  label: '最近7天', hours: 168 },
  { key: '30d', label: '最近30天', hours: 720 },
]

// 点快捷范围：以「当前时间」为终点回推，并立即查询
function applyQuickRange(r) {
  activeQuickRange.value = r.key
  rangeWarning.value = ''
  const end = new Date()
  const start = new Date(end.getTime() - r.hours * 3600 * 1000)
  startTime.value = toDatetimeLocal(start)
  endTime.value = toDatetimeLocal(end)
  if (selectedDevice.value) loadData()
}

// 手动改动输入框 → 标记为自定义
function onRangeInputChange() {
  activeQuickRange.value = 'custom'
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
  disposeStateTimeline()
  stateResult.value = null
  kpiResult.value = null
  stageCpkResult.value = null
  if (_stateAbort) { _stateAbort.abort(); _stateAbort = null }
  _stateRequestId++
  if (selectedDevice.value) loadData()
}

function currentDeviceName() {
  const d = devices.value.find(d => d.device_code === selectedDevice.value)
  return d ? d.device_name || d.device_code : selectedDevice.value
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

// tab 切换：① 状态(含原始参数曲线) ② 效率 ③ KPI ④ 阶段
async function onStepClick(step) {
  activeStep.value = step
  if (!selectedDevice.value) return
  if (step === 1 || step === 2) {
    if (!stateResult.value) await startStateAnalysis()
    if (step === 1) {
      disposeStateTimeline()
      await nextTick()
      if (seriesKeys.value.length > 0) initChart()
      await nextTick()
      renderStateTimeline()
    }
  } else if (step === 3) {
    if (!kpiResult.value) startKpiAnalysis()
  } else if (step === 4) {
    disposeChart()
    if (!stageCpkResult.value) startStageCpkAnalysis()
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
  disposeChart()

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
    // 状态切片图：已有数据则直接渲染，否则自动加载
    if (pulseParam.value && activeStep.value === 1) {
      if (stateResult.value && stateResult.value.timeline?.length) {
        await nextTick()
        renderStateTimeline()
      } else if (!stateResult.value || stateResult.value.source === 'error') {
        startStateAnalysis()
      }
    }
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
            activeQuickRange.value = 'custom'
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
        Object.assign(displayNames.value, allRes.data.display_names || {})
        Object.assign(paramUnits.value, allRes.data.units || {})
        aggInterval.value = allRes.data.aggregated ? (allRes.data.interval || '') : ''
        for (const key of Object.keys(allRes.data.series)) {
          LOADED_POINT_NAMES.value.add(key)
        }
        // fallback 找到数据：更新页面时间范围为数据实际起止时间
        startTime.value = toDatetimeLocal(win.start)
        endTime.value = toDatetimeLocal(win.end)
        activeQuickRange.value = 'custom'
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
      // 逐级回退尝试：当前范围 → 7天 → 30天 → 90天
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
                activeQuickRange.value = 'custom'
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
      // 标记剩余未加载的
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
  if (stateTimelineChart && !stateTimelineChart.isDisposed()) stateTimelineChart.resize()
  if (chartInstance && !chartInstance.isDisposed()) {
    chartInstance.resize()
  }
  for (const k in featureChartInstances) {
    const inst = featureChartInstances[k]
    if (inst && !inst.isDisposed()) inst.resize()
  }
  for (const k in sparklineInstances) {
    const inst = sparklineInstances[k]
    if (inst && !inst.isDisposed()) inst.resize()
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

async function startStateAnalysis() {
  if (!selectedDevice.value) return
  if (!pulseParam.value) {
    stateResult.value = { source: 'error', msg: '请先在「参数设定」页面中设置生产节拍(脉搏)参数' }
    return
  }
  // 取消上一次请求，递增计数器，只有最新请求的响应才生效
  if (_stateAbort) { _stateAbort.abort(); _stateAbort = null }
  const abortCtrl = new AbortController()
  _stateAbort = abortCtrl
  const reqId = ++_stateRequestId

  disposeStateTimeline()
  stateResult.value = { source: 'loading' }
  try {
    const res = await client.post('/device-params/state-analysis', {
      device_code: selectedDevice.value, device_name: currentDeviceName(),
      pulse_param: pulseParam.value, days: stateDays.value,
    }, { timeout: 0, signal: abortCtrl.signal })
    if (reqId !== _stateRequestId) return  // 不是最新请求，忽略
    if (res.code === 200 && res.data) {
      stateResult.value = res.data
      persistStateSnapshot()
      await nextTick()
      renderStateTimeline()
    } else {
      stateResult.value = { source: 'error', msg: res.msg || '状态分析失败' }
    }
  } catch (err) {
    if (err?.name === 'CanceledError' || err?.name === 'AbortError') return
    if (reqId !== _stateRequestId) return
    stateResult.value = { source: 'error', msg: err.response?.data?.msg || err.message || '状态分析请求失败' }
  } finally {
    if (_stateAbort === abortCtrl) _stateAbort = null
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

async function startKpiAnalysis() {
  if (!selectedDevice.value) return
  if (!pulseParam.value) {
    kpiResult.value = { source: 'error', msg: '请先在「参数设定」页面中设置生产节拍(脉搏)参数' }
    return
  }
  kpiResult.value = { source: 'loading' }
  try {
    const res = await client.post('/device-params/kpi', {
      device_code: selectedDevice.value, device_name: currentDeviceName(),
      pulse_param: pulseParam.value, days: kpiDays.value,
    }, { timeout: 0 })
    if (res.code === 200 && res.data) kpiResult.value = res.data
    else kpiResult.value = { source: 'error', msg: res.msg || 'KPI 计算失败' }
  } catch (err) {
    kpiResult.value = { source: 'error', msg: err.response?.data?.msg || err.message }
  }
}

async function startStageCpkAnalysis() {
  if (!selectedDevice.value) return
  if (!pulseParam.value) {
    stageCpkResult.value = { source: 'error', msg: '请先在「参数设定」页面中设置生产节拍(脉搏)参数' }
    return
  }
  stageCpkResult.value = { source: 'loading' }
  try {
    const res = await client.post('/device-params/stage-cpk', {
      device_code: selectedDevice.value, device_name: currentDeviceName(),
      pulse_param: pulseParam.value, days: stageCpkDays.value,
    }, { timeout: 0 })
    if (res.code === 200 && res.data) stageCpkResult.value = res.data
    else stageCpkResult.value = { source: 'error', msg: res.msg || '阶段CPK计算失败' }
  } catch (err) {
    stageCpkResult.value = { source: 'error', msg: err.response?.data?.msg || err.message }
  }
}

// 读取「参数设定」页筛选保存的 checked_params —— 本页参数范围唯一依据，返回非空数组；
// 没筛选过(无记录/从未保存)时返回 null，由调用方(loadData)回退到该设备全部参数。
// 顺带同步 pulse_param / workflow_step / state_data，供其它 tab(状态/KPI/阶段CPK)使用。
async function loadScreenStateFromDb() {
  try {
    const r = await client.get('/device-params/screen-state', { params: { device_code: selectedDevice.value } })
    if (r.code === 200 && r.data) {
      workflowStep.value = r.data.workflow_step || 2
      if (r.data.pulse_param) pulseParam.value = r.data.pulse_param
      if (r.data.state_data) stateResult.value = r.data.state_data
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
  disposeStateTimeline()

  if (resizeHandler) {
    window.removeEventListener('resize', resizeHandler)
  }
})
</script>
