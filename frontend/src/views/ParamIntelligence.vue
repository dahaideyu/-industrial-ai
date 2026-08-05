<template>
  <div class="p-8 max-w-[1440px] mx-auto">
    <!-- Header -->
    <div class="mb-6 flex justify-between items-end">
      <div>
        <h1 class="font-headline text-2xl font-semibold text-on-surface">参数智能</h1>
        <p class="text-secondary text-sm mt-1">特征视图 · 趋势预警 · 预测维护 —— 基于参数数据的进阶分析</p>
      </div>
      <button
        v-if="selectedDevice"
        @click="goToAnalysis"
        class="px-4 py-2 bg-gray-50 text-gray-600 text-sm font-medium rounded-lg border border-gray-200 hover:bg-gray-100 transition-colors"
      >前往参数分析 →</button>
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

        <div v-if="dataMode === 'features'">
          <label class="block text-xs font-bold text-gray-500 uppercase tracking-widest mb-2">
            时间范围 <span class="text-gray-300 normal-case font-normal">（≤ 7 天）</span>
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
            <button
              @click="loadData"
              :disabled="!selectedDevice || loading"
              class="px-5 py-2 bg-amber-500 text-white text-sm font-bold rounded-lg hover:bg-amber-600 transition-colors disabled:opacity-50"
            >查询</button>
          </div>
          <p v-if="rangeWarning" class="text-xs text-amber-600 mt-1">{{ rangeWarning }}</p>
        </div>
      </div>
    </div>

    <!-- Tabs -->
    <div class="bg-white rounded-xl border border-gray-100 shadow-sm px-5 py-2 mb-6">
      <div class="flex flex-wrap items-center gap-2">
        <button
          @click="switchDataMode('features')"
          class="px-3 py-1.5 text-xs rounded-md transition-colors"
          :class="dataMode === 'features' ? 'bg-white text-gray-900 font-bold shadow-sm' : 'text-gray-500 hover:text-gray-700'"
        >📊 特征视图</button>
        <button
          @click="switchDataMode('trend-alerts')"
          class="px-3 py-1.5 text-xs rounded-md transition-colors"
          :class="dataMode === 'trend-alerts' ? 'bg-white text-gray-900 font-bold shadow-sm' : 'text-gray-500 hover:text-gray-700'"
        >📈 趋势预警</button>
        <button
          @click="switchDataMode('predictive')"
          class="px-3 py-1.5 text-xs rounded-md transition-colors"
          :class="dataMode === 'predictive' ? 'bg-white text-gray-900 font-bold shadow-sm' : 'text-gray-500 hover:text-gray-700'"
        >🔮 预测维护</button>
      </div>
    </div>

    <!-- 特征视图：基于已加载的实时参数在前端现算（5min 重采样 + 滑动统计 + 变化率）-->
    <div v-if="dataMode === 'features'">
      <div v-if="loading" class="text-center py-16 text-gray-400">
        <div class="text-3xl mb-3 animate-spin">⏳</div>
        <p>正在加载参数数据...</p>
      </div>
      <div v-else-if="!selectedDevice" class="text-center py-16 text-gray-400 bg-white rounded-xl border border-gray-100 shadow-sm">
        <div class="text-4xl mb-3">📊</div>
        <p class="text-sm">请从上方选择设备</p>
      </div>
      <div v-else-if="seriesKeys.length === 0" class="text-center py-16 text-gray-400 bg-white rounded-xl border border-gray-100 shadow-sm">
        <div class="text-4xl mb-3">📉</div>
        <p class="text-sm">该时间段内暂无参数数据</p>
      </div>
      <div v-else class="bg-white rounded-xl border border-gray-100 shadow-sm p-5">
        <div class="flex items-center justify-between mb-3 flex-wrap gap-2">
          <div class="flex items-center gap-3">
            <span class="text-xs font-bold text-indigo-500 uppercase tracking-wider bg-indigo-50 px-2 py-0.5 rounded">📊 特征视图</span>
            <label v-if="runningPeriods.length > 0" class="flex items-center gap-1.5 cursor-pointer select-none" title="只显示设备运行(code 1)时段内的数据点">
              <input type="checkbox" v-model="showRunningOnly" @change="onRunningOnlyToggle" class="sr-only peer" />
              <span class="w-8 h-4 rounded-full bg-gray-200 peer-checked:bg-green-500 transition-colors relative after:content-[''] after:absolute after:top-0.5 after:left-0.5 after:w-3 after:h-3 after:rounded-full after:bg-white after:transition-transform peer-checked:after:translate-x-4"></span>
              <span class="text-xs text-gray-500">仅运行状态</span>
            </label>
          </div>
          <span class="text-xs text-gray-400">{{ seriesKeys.length }} 个参数 · 每参数 4 张特征图</span>
        </div>

        <!-- 参数选择器 -->
        <div class="flex flex-wrap items-center gap-1.5 mb-3 max-h-[96px] overflow-y-auto py-1">
          <span class="text-xs text-gray-400 mr-1 self-center">选择参数:</span>
          <button
            v-for="p in featureParamList" :key="p.key"
            @click="selectFeatureParam(p.key)"
            class="px-2.5 py-1 rounded-full text-xs font-medium border transition-all"
            :class="selectedFeatureParam === p.key
              ? 'bg-indigo-500 text-white border-indigo-500'
              : 'bg-gray-50 text-gray-500 border-gray-200 hover:border-gray-300'"
          >
            {{ p.label }}<span v-if="p.unit" class="opacity-60 ml-0.5">{{ p.unit }}</span>
          </button>
        </div>

        <div v-if="selectedFeatureParam" class="grid grid-cols-1 lg:grid-cols-2 gap-4">
          <div v-for="fc in FEATURE_CHARTS" :key="fc.key" class="border border-gray-100 rounded-lg p-3">
            <div class="text-xs font-bold text-gray-600 mb-1">
              {{ fc.title }}
              <span class="text-gray-400 font-normal ml-1">{{ fc.subtitle }}</span>
            </div>
            <div :ref="el => setFeatureChartRef(fc.key, el)" class="w-full" style="height: 240px"></div>
          </div>
        </div>
        <div v-else class="text-center py-12 text-gray-400 text-sm">
          请在上方选择一个参数查看其特征图
        </div>
      </div>
    </div>

    <!-- 参数趋势总览 / 漂移预警视图（读预计算统计，与原始图表无关）-->
    <div v-else-if="dataMode === 'trend-alerts'">
      <div v-if="!selectedDevice" class="text-center py-16 text-gray-400 bg-white rounded-xl border border-gray-100 shadow-sm">
        <div class="text-4xl mb-3">📈</div>
        <p class="text-sm">请从上方选择设备</p>
      </div>
      <div v-else class="space-y-4">
        <!-- 头部：天数选择 + 漂移摘要 + 操作 -->
        <div class="bg-white rounded-xl border border-gray-100 shadow-sm p-4">
          <div class="flex items-center justify-between flex-wrap gap-3">
            <div class="flex items-center gap-3 flex-wrap">
              <span class="text-xs font-bold text-gray-400 uppercase tracking-wider">参数趋势总览</span>
              <div class="flex items-center gap-0.5 bg-gray-100 rounded-lg p-0.5">
                <button v-for="d in [7, 30, 90]" :key="d" @click="setTrendDays(d)"
                  class="px-2.5 py-1 text-xs rounded-md transition-colors"
                  :class="trendDays === d ? 'bg-white text-gray-900 font-bold shadow-sm' : 'text-gray-500 hover:text-gray-700'"
                >{{ d }}天</button>
              </div>
              <span v-if="trendWindow" class="text-xs text-gray-400">{{ trendWindow }}</span>
              <span class="inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded bg-red-50 text-red-600 font-bold">显著漂移 {{ trendCounts.critical }}</span>
              <span class="inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded bg-amber-50 text-amber-600 font-bold">需关注 {{ trendCounts.warning }}</span>
              <span class="inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded bg-gray-100 text-gray-500">平稳 {{ trendCounts.info }}</span>
            </div>
            <div class="flex items-center gap-2">
              <button @click="loadTrendAlerts" :disabled="trendLoading"
                class="px-3 py-1.5 text-xs rounded-lg bg-gray-50 text-gray-600 border border-gray-200 hover:bg-gray-100 disabled:opacity-50">
                {{ trendLoading ? '加载中…' : '刷新' }}
              </button>
              <button @click="triggerRollup" :disabled="trendRollupRunning"
                title="按最近90天回填/重算该设备的统计与漂移（首次或数据更新后用）"
                class="px-3 py-1.5 text-xs rounded-lg bg-violet-500 text-white font-bold hover:bg-violet-600 disabled:opacity-50">
                {{ trendRollupRunning ? '计算中…(可能较慢)' : '立即计算(90天)' }}
              </button>
              <button @click="runDiagnose" :disabled="diagRunning"
                title="AI 自主调用画像/趋势/Cpk/RUL/对标/前兆/告警工具，给出诊断"
                class="px-3 py-1.5 text-xs rounded-lg bg-indigo-600 text-white font-bold hover:bg-indigo-700 disabled:opacity-50">
                {{ diagRunning ? 'AI 诊断中…' : '🩺 AI 诊断' }}
              </button>
            </div>
          </div>
          <p v-if="trendNote" class="text-xs text-amber-600 mt-2">⚠ {{ trendNote }}</p>
          <p class="text-[11px] text-gray-300 mt-2">
            均值/方差/标准差/极值按窗口内可叠加量精确重算；中位为日中位的近似；均差=各日中位的日间平均绝对偏差。趋势 = Mann-Kendall + Sen 斜率/天。
          </p>
        </div>

        <!-- 分阶段漂移报警(7天滑动窗口·6σ) + 知识库诊断 -->
        <div class="bg-white rounded-xl border border-gray-100 shadow-sm p-4">
          <div class="flex items-center justify-between flex-wrap gap-3 mb-1">
            <div class="flex items-center gap-3 flex-wrap">
              <span class="text-xs font-bold text-gray-400 uppercase tracking-wider">分阶段漂移报警 · 7天滑动窗口(6σ)</span>
              <span class="inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded bg-red-50 text-red-600 font-bold">显著 {{ stageAlertCounts.critical }}</span>
              <span class="inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded bg-amber-50 text-amber-600 font-bold">需关注 {{ stageAlertCounts.warning }}</span>
              <span class="inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded bg-gray-100 text-gray-500">平稳 {{ stageAlertCounts.info }}</span>
            </div>
            <div class="flex items-center gap-2">
              <button @click="loadStageAlerts" :disabled="stageAlertsLoading"
                class="px-3 py-1.5 text-xs rounded-lg bg-gray-50 text-gray-600 border border-gray-200 hover:bg-gray-100 disabled:opacity-50">
                {{ stageAlertsLoading ? '加载中…' : '刷新' }}
              </button>
              <button @click="runAllStageDiag" :disabled="stageDiagRunning"
                title="对全部需关注/显著漂移报警，结合知识库生成「是什么问题」并保存"
                class="px-3 py-1.5 text-xs rounded-lg bg-emerald-600 text-white font-bold hover:bg-emerald-700 disabled:opacity-50">
                {{ stageDiagRunning ? '知识库诊断中…' : '📚 全部诊断(知识库)' }}
              </button>
            </div>
          </div>
          <p v-if="stageAlertNote" class="text-xs text-amber-600 mt-1">⚠ {{ stageAlertNote }}</p>
          <p class="text-[11px] text-gray-300 mt-1">
            对每个连续参数在每个阶段内，按近 7 天稳健 z（MAD·1.4826≈σ）+ Mann-Kendall + Sen 斜率检测「逐渐变大/变小」；夜间任务对报警结合知识库预生成诊断。
          </p>

          <div v-if="stageAlerts.length > 0" class="mt-3 overflow-x-auto">
            <table class="w-full text-sm">
              <thead class="bg-gray-50">
                <tr class="text-left text-xs text-gray-500 border-b border-gray-200 whitespace-nowrap">
                  <th class="py-2.5 px-3 font-semibold">参数 · 阶段</th>
                  <th class="py-2.5 px-3 font-semibold">趋势判定</th>
                  <th class="py-2.5 px-3 font-semibold text-right">变化率</th>
                  <th class="py-2.5 px-3 font-semibold text-right">σ(稳健z)</th>
                  <th class="py-2.5 px-3 font-semibold text-right">斜率/天</th>
                  <th class="py-2.5 px-3 font-semibold text-right">基线→近期</th>
                  <th class="py-2.5 px-3 font-semibold text-right">样本</th>
                  <th class="py-2.5 px-3 font-semibold">知识库诊断</th>
                </tr>
              </thead>
              <tbody class="divide-y divide-gray-50">
                <template v-for="a in stageAlerts" :key="alertSnapKey(a)">
                  <tr class="hover:bg-gray-50/50">
                    <td class="py-2.5 px-3 whitespace-nowrap">
                      <div class="font-bold text-gray-800">{{ a.display_name || a.metric }}</div>
                      <div class="flex items-center gap-1.5 mt-0.5">
                        <span v-if="a.unit" class="text-xs text-gray-300">{{ a.unit }}</span>
                        <span class="text-[10px] px-1.5 py-0.5 rounded bg-indigo-50 text-indigo-500">阶段 {{ a.stage }}</span>
                        <span v-if="a.note" class="text-[10px] px-1.5 py-0.5 rounded bg-orange-50 text-orange-500">{{ a.note }}</span>
                      </div>
                    </td>
                    <td class="py-2.5 px-3 whitespace-nowrap"
                      :title="mkLabel(a.mk_trend) + (a.mk_p != null ? ' (p=' + fmtNum(a.mk_p, 3) + ')' : '')">
                      <span :class="['inline-flex items-center gap-1 px-2 py-0.5 text-xs font-bold rounded', sevMeta(a.severity).cls]">
                        <span>{{ dirArrow(a.direction) }}</span>{{ sevMeta(a.severity).label }}
                      </span>
                    </td>
                    <td class="py-2.5 px-3 text-right tabular-nums font-semibold"
                      :class="a.change_pct > 0 ? 'text-rose-500' : a.change_pct < 0 ? 'text-sky-600' : 'text-gray-400'">
                      {{ a.change_pct == null ? '—' : (a.change_pct > 0 ? '+' : '') + fmtNum(a.change_pct) + '%' }}
                    </td>
                    <td class="py-2.5 px-3 text-right text-gray-600 tabular-nums">{{ a.robust_z == null ? '—' : fmtNum(a.robust_z) + 'σ' }}</td>
                    <td class="py-2.5 px-3 text-right text-gray-500 tabular-nums">{{ a.sen_slope == null ? '—' : fmtNum(a.sen_slope, 4) }}</td>
                    <td class="py-2.5 px-3 text-right text-gray-400 tabular-nums whitespace-nowrap">{{ fmtNum(a.baseline_median) }} → {{ fmtNum(a.recent_median) }}</td>
                    <td class="py-2.5 px-3 text-right text-gray-500 tabular-nums">{{ a.sample_days }}天</td>
                    <td class="py-2.5 px-3 whitespace-nowrap">
                      <button @click="toggleDiag(a)"
                        class="px-2 py-1 text-xs rounded-lg border hover:bg-gray-50"
                        :class="alertDiagMap[alertSnapKey(a)] ? 'text-emerald-600 border-emerald-200 bg-emerald-50/50' : 'text-gray-500 border-gray-200'">
                        {{ expandedDiagKey === alertSnapKey(a) ? '收起' : (alertDiagMap[alertSnapKey(a)] ? '已诊断 ▾' : '诊断详情 ▾') }}
                      </button>
                    </td>
                  </tr>
                  <tr v-if="expandedDiagKey === alertSnapKey(a)" class="bg-gray-50/40">
                    <td colspan="8" class="py-3 px-4">
                      <div v-if="diagLoadingKey === alertSnapKey(a)" class="text-xs text-gray-400">正在处理…（知识库 LLM 调用，较慢）</div>
                      <div v-else-if="alertDiagMap[alertSnapKey(a)]">
                        <div class="prose prose-sm max-w-none text-gray-700 leading-relaxed whitespace-pre-wrap">{{ alertDiagMap[alertSnapKey(a)].problem }}</div>
                        <p v-if="alertDiagMap[alertSnapKey(a)].kb_evidence" class="text-[11px] text-gray-400 mt-2">📚 来源：{{ alertDiagMap[alertSnapKey(a)].kb_evidence }}</p>
                        <div class="flex items-center gap-3 mt-2">
                          <span v-if="alertDiagMap[alertSnapKey(a)].created_at" class="text-[11px] text-gray-300">{{ alertDiagMap[alertSnapKey(a)].created_at }}</span>
                          <button @click="generateDiag(a)" class="text-[11px] text-indigo-500 hover:text-indigo-600">重新诊断</button>
                        </div>
                      </div>
                      <div v-else class="flex items-center gap-3">
                        <span class="text-xs text-gray-400">尚未生成知识库诊断。</span>
                        <button @click="generateDiag(a)"
                          class="px-2.5 py-1 text-xs rounded-lg bg-emerald-600 text-white font-bold hover:bg-emerald-700">立即诊断</button>
                      </div>
                    </td>
                  </tr>
                </template>
              </tbody>
            </table>
          </div>
          <div v-else-if="!stageAlertsLoading" class="mt-3 text-center py-8 text-gray-400 text-sm">
            暂无 7 天分阶段漂移报警（连续参数在阶段内未见逐渐漂移，或尚未回填统计）。
          </div>
        </div>

        <!-- AI 诊断结果 -->
        <div v-if="diagResult || diagErr" class="bg-white rounded-xl border border-indigo-100 shadow-sm p-5">
          <div class="flex items-center justify-between mb-3">
            <h3 class="text-sm font-bold text-indigo-700">🩺 AI 自主诊断</h3>
            <div class="flex items-center gap-2">
              <span v-if="diagTrace.length" class="text-[10px] text-gray-400">调用了 {{ diagTrace.length }} 个分析工具</span>
              <button @click="diagResult=''; diagErr=''; diagTrace=[]" class="text-xs text-gray-400 hover:text-gray-600">关闭</button>
            </div>
          </div>
          <div v-if="diagTrace.length" class="flex flex-wrap gap-1 mb-3">
            <span v-for="(t,i) in diagTrace" :key="i"
              :class="['text-[10px] px-1.5 py-0.5 rounded', t.ok ? 'bg-indigo-50 text-indigo-500' : 'bg-rose-50 text-rose-500']">{{ t.tool }}</span>
          </div>
          <p v-if="diagErr" class="text-sm text-rose-500">{{ diagErr }}</p>
          <div v-else class="prose prose-sm max-w-none text-gray-700 leading-relaxed whitespace-pre-wrap">{{ diagResult }}</div>
        </div>

        <!-- 总览表（即使无漂移也列出全部参数）-->
        <div v-if="trendAlerts.length > 0" class="bg-white rounded-xl border border-gray-100 shadow-sm overflow-hidden">
          <div class="overflow-x-auto">
            <table class="w-full text-sm">
              <thead class="bg-gray-50">
                <tr class="text-left text-xs text-gray-500 border-b border-gray-200 whitespace-nowrap">
                  <th class="py-3 px-4 font-semibold">参数 / 阶段</th>
                  <th class="py-3 px-3 font-semibold">近{{ trendDays }}天趋势</th>
                  <th class="py-3 px-3 font-semibold">趋势判定</th>
                  <th class="py-3 px-3 font-semibold text-right">变化率</th>
                  <th class="py-3 px-3 font-semibold text-right">斜率/天</th>
                  <th class="py-3 px-3 font-semibold text-right">均值</th>
                  <th class="py-3 px-3 font-semibold text-right">中位</th>
                  <th class="py-3 px-3 font-semibold text-right">方差</th>
                  <th class="py-3 px-3 font-semibold text-right">标准差</th>
                  <th class="py-3 px-3 font-semibold text-right">均差</th>
                  <th class="py-3 px-3 font-semibold text-right">范围(min~max)</th>
                  <th class="py-3 px-3 font-semibold text-right">样本</th>
                </tr>
              </thead>
              <tbody class="divide-y divide-gray-50">
                <tr v-for="a in trendAlerts" :key="alertKey(a)" class="hover:bg-gray-50/50">
                  <td class="py-2.5 px-4 whitespace-nowrap">
                    <div class="font-bold text-gray-800">{{ a.display_name || a.metric }}</div>
                    <div class="flex items-center gap-1.5 mt-0.5">
                      <span v-if="a.unit" class="text-xs text-gray-300">{{ a.unit }}</span>
                      <span v-if="a.stage !== null && a.stage !== undefined"
                        class="text-[10px] px-1.5 py-0.5 rounded bg-indigo-50 text-indigo-500">阶段 {{ a.stage }}</span>
                    </div>
                  </td>
                  <td class="py-2.5 px-3">
                    <div :ref="el => setSparklineRef(alertKey(a), el)" style="width: 120px; height: 34px"></div>
                  </td>
                  <td class="py-2.5 px-3 whitespace-nowrap"
                    :title="mkLabel(a.mk_trend) + (a.mk_p != null ? ' (p=' + fmtNum(a.mk_p, 3) + ')' : '')">
                    <span :class="['inline-flex items-center gap-1 px-2 py-0.5 text-xs font-bold rounded', sevMeta(a.severity).cls]">
                      <span>{{ dirArrow(a.direction) }}</span>{{ sevMeta(a.severity).label }}
                    </span>
                  </td>
                  <td class="py-2.5 px-3 text-right tabular-nums font-semibold"
                    :class="a.change_pct > 0 ? 'text-rose-500' : a.change_pct < 0 ? 'text-sky-600' : 'text-gray-400'">
                    {{ a.change_pct == null ? '—' : (a.change_pct > 0 ? '+' : '') + fmtNum(a.change_pct) + '%' }}
                  </td>
                  <td class="py-2.5 px-3 text-right text-gray-500 tabular-nums">{{ a.sen_slope == null ? '—' : fmtNum(a.sen_slope, 4) }}</td>
                  <td class="py-2.5 px-3 text-right text-gray-800 font-semibold tabular-nums">{{ fmtNum(a.mean) }}</td>
                  <td class="py-2.5 px-3 text-right text-gray-600 tabular-nums">{{ fmtNum(a.median) }}</td>
                  <td class="py-2.5 px-3 text-right text-gray-600 tabular-nums">{{ fmtNum(a.variance) }}</td>
                  <td class="py-2.5 px-3 text-right text-gray-600 tabular-nums">{{ fmtNum(a.std) }}</td>
                  <td class="py-2.5 px-3 text-right text-gray-600 tabular-nums">{{ fmtNum(a.daily_mad) }}</td>
                  <td class="py-2.5 px-3 text-right text-gray-400 tabular-nums whitespace-nowrap">{{ fmtNum(a.min) }} ~ {{ fmtNum(a.max) }}</td>
                  <td class="py-2.5 px-3 text-right text-gray-500 tabular-nums">{{ a.n_days }}天</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>

        <div v-else-if="!trendLoading" class="text-center py-16 text-gray-400 bg-white rounded-xl border border-gray-100 shadow-sm">
          <div class="text-4xl mb-3">🗂️</div>
          <p class="text-sm">暂无统计数据。若首次使用，请点「立即计算(90天)」回填该设备统计后再看。</p>
        </div>
      </div>
    </div>

    <!-- 预测维护：RUL/触限ETA · 跨设备对标 · 故障前兆 -->
    <div v-else-if="dataMode === 'predictive'">
      <div v-if="!selectedDevice" class="text-center py-16 text-gray-400 bg-white rounded-xl border border-gray-100 shadow-sm">
        <div class="text-4xl mb-3">🔮</div>
        <p class="text-sm">请从上方选择设备</p>
      </div>
      <div v-else class="space-y-4">
        <div class="bg-white rounded-xl border border-gray-100 shadow-sm p-4 flex items-center justify-between flex-wrap gap-3">
          <div class="flex items-center gap-3 flex-wrap">
            <span class="text-xs font-bold text-gray-400 uppercase tracking-wider">预测维护 · RUL / 对标 / 前兆</span>
            <span v-if="predComputedAt" class="text-[11px] text-gray-300">数据计算于 {{ predComputedAt }}（读缓存）</span>
          </div>
          <button @click="loadPredictive(true)" :disabled="predLoading"
            title="重新现算并刷新缓存"
            class="px-3 py-1.5 text-xs rounded-lg bg-gray-50 text-gray-600 border border-gray-200 hover:bg-gray-100 disabled:opacity-50">
            {{ predLoading ? '计算中…' : '重新计算' }}
          </button>
        </div>

        <!-- RUL / 触限 ETA -->
        <div class="bg-white rounded-xl border border-gray-100 shadow-sm overflow-hidden">
          <div class="px-4 py-2.5 bg-gray-50 text-xs font-bold text-gray-600 border-b border-gray-100">⏳ 剩余寿命 / 触限 ETA <span class="text-gray-300 font-normal">按趋势斜率外推到画像上下限</span></div>
          <div v-if="predRul.length" class="overflow-x-auto">
            <table class="w-full text-sm">
              <thead class="bg-white"><tr class="text-left text-xs text-gray-400 border-b border-gray-100">
                <th class="py-2 px-4 font-semibold">参数</th><th class="py-2 px-3 font-semibold">方向</th>
                <th class="py-2 px-3 font-semibold text-right">当前</th><th class="py-2 px-3 font-semibold text-right">目标限</th>
                <th class="py-2 px-3 font-semibold text-right">斜率/天</th><th class="py-2 px-3 font-semibold text-right">预计触限</th>
                <th class="py-2 px-3 font-semibold text-right">ETA</th></tr></thead>
              <tbody class="divide-y divide-gray-50">
                <tr v-for="x in predRul" :key="x.p_name" class="hover:bg-gray-50/50">
                  <td class="py-2 px-4 font-semibold text-gray-800">{{ x.display_name }}<span class="text-gray-300 text-xs ml-1">{{ x.unit }}</span></td>
                  <td class="py-2 px-3">{{ x.direction === 'up' ? '↑ 升' : '↓ 降' }}</td>
                  <td class="py-2 px-3 text-right tabular-nums">{{ fmtNum(x.current) }}</td>
                  <td class="py-2 px-3 text-right tabular-nums">{{ fmtNum(x.target_limit) }}</td>
                  <td class="py-2 px-3 text-right tabular-nums text-gray-500">{{ fmtNum(x.slope_per_day, 4) }}</td>
                  <td class="py-2 px-3 text-right tabular-nums">{{ x.eta_date }}</td>
                  <td class="py-2 px-3 text-right tabular-nums font-bold" :class="x.eta_days < 14 ? 'text-rose-500' : x.eta_days < 60 ? 'text-amber-500' : 'text-gray-600'">{{ x.eta_days }}天</td>
                </tr>
              </tbody>
            </table>
          </div>
          <p v-else class="px-4 py-6 text-xs text-gray-400 text-center">暂无显著趋势触限项（需画像有 spec + 足够历史）。</p>
        </div>

        <!-- 跨设备对标 -->
        <div class="bg-white rounded-xl border border-gray-100 shadow-sm overflow-hidden">
          <div class="px-4 py-2.5 bg-gray-50 text-xs font-bold text-gray-600 border-b border-gray-100">📊 跨设备对标 <span class="text-gray-300 font-normal">同名参数 z 分，找与同伴不一样的</span></div>
          <div v-if="predBench.length" class="overflow-x-auto">
            <table class="w-full text-sm">
              <thead class="bg-white"><tr class="text-left text-xs text-gray-400 border-b border-gray-100">
                <th class="py-2 px-4 font-semibold">参数</th><th class="py-2 px-3 font-semibold text-right">本机均值</th>
                <th class="py-2 px-3 font-semibold text-right">同群均值</th><th class="py-2 px-3 font-semibold text-right">设备数</th>
                <th class="py-2 px-3 font-semibold text-right">z 分</th><th class="py-2 px-3 font-semibold">判定</th></tr></thead>
              <tbody class="divide-y divide-gray-50">
                <tr v-for="x in predBench" :key="x.p_name" class="hover:bg-gray-50/50">
                  <td class="py-2 px-4 font-semibold text-gray-800">{{ x.display_name }}</td>
                  <td class="py-2 px-3 text-right tabular-nums">{{ fmtNum(x.this_mean) }}</td>
                  <td class="py-2 px-3 text-right tabular-nums text-gray-500">{{ fmtNum(x.fleet_mean) }}</td>
                  <td class="py-2 px-3 text-right tabular-nums text-gray-400">{{ x.fleet_n }}</td>
                  <td class="py-2 px-3 text-right tabular-nums font-semibold" :class="x.outlier ? 'text-rose-500' : 'text-gray-600'">{{ x.z == null ? '—' : fmtNum(x.z) }}</td>
                  <td class="py-2 px-3"><span v-if="x.outlier" class="text-[10px] px-1.5 py-0.5 rounded bg-rose-50 text-rose-500">离群</span><span v-else class="text-gray-300 text-xs">—</span></td>
                </tr>
              </tbody>
            </table>
          </div>
          <p v-else class="px-4 py-6 text-xs text-gray-400 text-center">暂无对标数据（需 ≥3 台设备共享同名参数）。</p>
        </div>

        <!-- 故障前兆 -->
        <div class="bg-white rounded-xl border border-gray-100 shadow-sm overflow-hidden">
          <div class="px-4 py-2.5 bg-gray-50 text-xs font-bold text-gray-600 border-b border-gray-100">⚡ 故障前兆自学习 <span class="text-gray-300 font-normal">历史告警前偏移最大的参数</span></div>
          <div v-if="predPrec.precursors && predPrec.precursors.length" class="overflow-x-auto">
            <p class="px-4 pt-2 text-[11px] text-gray-400">基于近窗 {{ predPrec.n_events }} 次报警、告警前 {{ predPrec.pre_min }} 分钟。{{ predPrec.note }}</p>
            <table class="w-full text-sm">
              <thead class="bg-white"><tr class="text-left text-xs text-gray-400 border-b border-gray-100">
                <th class="py-2 px-4 font-semibold">参数</th><th class="py-2 px-3 font-semibold text-right">平均偏移(|z|)</th>
                <th class="py-2 px-3 font-semibold text-right">命中率</th><th class="py-2 px-3 font-semibold text-right">出现事件</th></tr></thead>
              <tbody class="divide-y divide-gray-50">
                <tr v-for="x in predPrec.precursors" :key="x.p_name" class="hover:bg-gray-50/50">
                  <td class="py-2 px-4 font-semibold text-gray-800">{{ x.display_name }}<span class="text-gray-300 text-xs ml-1">{{ x.unit }}</span></td>
                  <td class="py-2 px-3 text-right tabular-nums font-semibold" :class="x.avg_abs_z >= 2 ? 'text-rose-500' : 'text-gray-600'">{{ fmtNum(x.avg_abs_z) }}</td>
                  <td class="py-2 px-3 text-right tabular-nums">{{ Math.round(x.hit_rate * 100) }}%</td>
                  <td class="py-2 px-3 text-right tabular-nums text-gray-400">{{ x.events_seen }}</td>
                </tr>
              </tbody>
            </table>
          </div>
          <p v-else class="px-4 py-6 text-xs text-gray-400 text-center">{{ predPrec.note || '暂无前兆数据（需窗口内有报警事件 + 连续参数基线）。' }}</p>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted, nextTick } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import * as echarts from 'echarts'
import {
  getDeviceParamData,
  getRunningPeriods,
  getDeviceParamPoints,
  getStatsOverview,
  getTrendAlerts,
  getAlertDiagnosis,
  runAlertDiagnose,
  runAllAlertDiagnosis,
  runRollup,
  diagnoseDevice,
  getRul,
  getBenchmark,
  getPrecursors,
} from '../api/client.js'
import client from '../api/client.js'

const route = useRoute()
const router = useRouter()

const devices = ref([])
const selectedDevice = ref('')
const loading = ref(false)
const seriesData = ref({})
const seriesKeys = ref([])
const displayNames = ref({})   // p_name code -> 中文名
const paramUnits = ref({})     // p_name code -> 单位
const runningPeriods = ref([])
const showRunningOnly = ref(false)
const dataMode = ref('features')   // 'features' | 'trend-alerts' | 'predictive'

const SERIES_COLORS = [
  '#6366f1', '#f59e0b', '#10b981', '#ef4444', '#8b5cf6',
  '#06b6d4', '#f97316', '#84cc16', '#ec4899', '#14b8a6',
]

// ── 时间范围（特征视图用）──
function toDatetimeLocal(date) {
  const pad = (n) => String(n).padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`
}
function formatForApi(dtLocal) {
  return dtLocal ? dtLocal.replace('T', ' ') + ':00' : ''
}
function parseTime(str) {
  if (!str) return null
  const t = new Date(str.includes('T') ? str : str.replace(' ', 'T')).getTime()
  return isNaN(t) ? null : t
}

const MAX_RANGE_DAYS = 7
const _initEnd = new Date()
const _initStart = new Date(_initEnd.getTime() - 24 * 3600 * 1000)
const startTime = ref(toDatetimeLocal(_initStart))
const endTime = ref(toDatetimeLocal(_initEnd))
const rangeWarning = ref('')

function onRangeInputChange() {
  clampRangeWithin7Days()
}

function clampRangeWithin7Days() {
  const s = new Date(startTime.value)
  const e = new Date(endTime.value)
  if (isNaN(s) || isNaN(e)) return
  const days = (e - s) / (24 * 3600 * 1000)
  if (days > MAX_RANGE_DAYS) {
    const clamped = new Date(e.getTime() - MAX_RANGE_DAYS * 24 * 3600 * 1000)
    startTime.value = toDatetimeLocal(clamped)
    rangeWarning.value = `时间范围最多 ${MAX_RANGE_DAYS} 天，已自动收窄起始时间`
  } else {
    rangeWarning.value = ''
  }
}

function goToAnalysis() {
  router.push({ path: '/device-params', query: { device: selectedDevice.value } })
}

// ── 趋势预警状态 ──
const trendAlerts = ref([])            // 预警快照列表
const trendLoading = ref(false)
const trendRollupRunning = ref(false)
const trendWindow = ref('')            // 统计窗口区间文字
const trendNote = ref('')              // 顶部提示
const trendDays = ref(30)              // 趋势窗口天数(7/30/90)
let sparklineInstances = {}            // alertKey -> echarts 实例
const sparklineEls = {}                // alertKey -> DOM
const sparklineSeries = {}             // alertKey -> [[ts,val],...]

const trendCounts = computed(() => {
  const c = { critical: 0, warning: 0, info: 0 }
  for (const a of trendAlerts.value) c[a.severity] = (c[a.severity] || 0) + 1
  return c
})

// ── 分阶段漂移报警(7天滑动窗口·6σ) + 知识库诊断 ──
const stageAlerts = ref([])            // 7天分阶段报警快照(读 device_param_trend_alert)
const stageAlertsLoading = ref(false)
const stageAlertNote = ref('')
const stageDiagRunning = ref(false)    // 批量「全部诊断」进行中
const expandedDiagKey = ref('')        // 当前展开诊断详情的报警 key
const alertDiagMap = ref({})           // key -> 诊断对象(null=已查询但无)
const diagLoadingKey = ref('')         // 正在读/生成诊断的 key

const stageAlertCounts = computed(() => {
  const c = { critical: 0, warning: 0, info: 0 }
  for (const a of stageAlerts.value) c[a.severity] = (c[a.severity] || 0) + 1
  return c
})

// ── AI 自主诊断 ──
const diagResult = ref('')
const diagErr = ref('')
const diagTrace = ref([])
const diagRunning = ref(false)

// ── 预测维护(Pillar3) ──
const predRul = ref([])
const predBench = ref([])
const predPrec = ref({})
const predLoading = ref(false)
const predComputedAt = ref('')

// 大跨度聚合：非空表示当前参数视图数据已按该粒度聚合（如 '15min'/'1hour'）
const aggInterval = ref('')

// ── 按参数组织的特征视图（前端基于实时参数现算）──
const selectedFeatureParam = ref('')   // 当前选中的基础参数 p_name
const featureChartEls = {}             // chartKey -> DOM 元素
let featureChartInstances = {}         // chartKey -> echarts 实例

// 每个参数展示的 4 张特征图
const FEATURE_CHARTS = [
  { key: 'raw',  title: '原始值',     subtitle: '采集原值' },
  { key: 'mean', title: '滑动均值',   subtitle: '5 / 15 / 30 / 60 min' },
  { key: 'std',  title: '滑动标准差', subtitle: '波动 15 / 30 / 60 min' },
  { key: 'diff', title: '变化率',     subtitle: '每分钟变化 (5min 重采样)' },
]

// 可选参数列表（复用原始参数：seriesKeys + 中文名 + 单位）
const featureParamList = computed(() =>
  (dataMode.value === 'features' ? seriesKeys.value : []).map(k => ({
    key: k,
    label: displayNames.value[k] || k,
    unit: paramUnits.value[k] || '',
  }))
)

function selectFeatureParam(key) {
  selectedFeatureParam.value = key
  nextTick(() => renderFeatureCharts())
}

function setFeatureChartRef(key, el) {
  if (el) featureChartEls[key] = el
  else delete featureChartEls[key]
}

function disposeFeatureCharts() {
  for (const k in featureChartInstances) {
    const inst = featureChartInstances[k]
    if (inst && !inst.isDisposed()) inst.dispose()
  }
  featureChartInstances = {}
}

// ── 趋势预警 ──

const SEV_META = {
  critical: { label: '显著漂移', cls: 'bg-red-50 text-red-600' },
  warning: { label: '需关注', cls: 'bg-amber-50 text-amber-600' },
  info: { label: '平稳', cls: 'bg-gray-100 text-gray-500' },
}
function sevMeta(sev) { return SEV_META[sev] || SEV_META.info }
function dirArrow(dir) { return dir === 'up' ? '↑' : dir === 'down' ? '↓' : '—' }
function mkLabel(t) { return t === 'up' ? '显著上升' : t === 'down' ? '显著下降' : '无显著趋势' }
function fmtNum(v, digits = 2) {
  if (v == null || isNaN(v)) return '—'
  return Number(v).toFixed(digits).replace(/\.?0+$/, '') || '0'
}
function alertKey(a) { return `${a.metric}|${a.stage == null ? '-' : a.stage}` }

function setTrendDays(d) {
  if (trendDays.value === d) return
  trendDays.value = d
  if (selectedDevice.value) loadTrendAlerts()
}

// 读「全参数趋势总览」：统计 + 内联趋势 + 内嵌序列（一次请求，省去逐参数拉取）
async function loadTrendAlerts() {
  if (!selectedDevice.value) return
  trendLoading.value = true
  trendNote.value = ''
  disposeSparklines()
  for (const k in sparklineSeries) delete sparklineSeries[k]
  try {
    const res = await getStatsOverview({ device_code: selectedDevice.value, days: trendDays.value })
    if (res.code === 200 && res.data) {
      trendAlerts.value = res.data.metrics || []
      trendWindow.value = (res.data.start && res.data.end) ? `${res.data.start} ~ ${res.data.end}` : ''
      if (trendAlerts.value.length === 0) {
        trendNote.value = '该设备暂无统计数据。请点「立即计算(90天)」回填后再看。'
      } else {
        for (const a of trendAlerts.value) {
          sparklineSeries[alertKey(a)] = (a.series || [])
            .filter(p => p.median != null)
            .map(p => [p.date, p.median])
        }
        await nextTick()
        renderSparklines()
      }
    }
  } catch (err) {
    console.error('加载趋势总览失败:', err)
    trendNote.value = '加载趋势总览失败。'
  } finally {
    trendLoading.value = false
  }
}

// ── 分阶段漂移报警(7天) + 知识库诊断 ──
function alertSnapKey(a) {
  return `${a.metric}|${a.stage == null ? '-' : a.stage}|${a.eval_date}|${a.baseline_days}`
}

async function loadStageAlerts() {
  if (!selectedDevice.value) return
  stageAlertsLoading.value = true
  stageAlertNote.value = ''
  expandedDiagKey.value = ''
  try {
    const res = await getTrendAlerts({ device_code: selectedDevice.value, baseline_days: 7 })
    if (res.code === 200 && res.data) {
      stageAlerts.value = (res.data.alerts || []).filter(a => a.stage !== null && a.stage !== undefined)
      if (stageAlerts.value.length === 0) {
        stageAlertNote.value = '暂无 7 天分阶段报警快照。请先用「立即计算(90天)」回填该设备统计。'
      }
    } else {
      stageAlerts.value = []
    }
  } catch (err) {
    console.error('加载分阶段报警失败:', err)
    stageAlertNote.value = '加载分阶段报警失败。'
  } finally {
    stageAlertsLoading.value = false
  }
}

async function toggleDiag(a) {
  const key = alertSnapKey(a)
  if (expandedDiagKey.value === key) { expandedDiagKey.value = ''; return }
  expandedDiagKey.value = key
  if (alertDiagMap.value[key] === undefined) await loadDiag(a)
}

async function loadDiag(a) {
  const key = alertSnapKey(a)
  diagLoadingKey.value = key
  try {
    const res = await getAlertDiagnosis({
      device_code: selectedDevice.value, metric: a.metric, stage: a.stage,
      eval_date: a.eval_date, baseline_days: a.baseline_days,
    })
    alertDiagMap.value[key] = (res.code === 200) ? (res.data || null) : null
  } catch (err) {
    console.error('读取诊断失败:', err)
    alertDiagMap.value[key] = null
  } finally {
    diagLoadingKey.value = ''
  }
}

async function generateDiag(a) {
  const key = alertSnapKey(a)
  diagLoadingKey.value = key
  try {
    const res = await runAlertDiagnose({
      device_code: selectedDevice.value, metric: a.metric, stage: a.stage,
      eval_date: a.eval_date, baseline_days: a.baseline_days,
    })
    alertDiagMap.value[key] = (res.code === 200)
      ? (res.data || null)
      : { problem: res.msg || '诊断失败', ok: false }
  } catch (err) {
    console.error('生成诊断失败:', err)
    alertDiagMap.value[key] = { problem: '诊断请求失败，请重试。', ok: false }
  } finally {
    diagLoadingKey.value = ''
  }
}

async function runAllStageDiag() {
  if (!selectedDevice.value || stageDiagRunning.value) return
  stageDiagRunning.value = true
  stageAlertNote.value = '正在对全部需关注/显著漂移报警结合知识库生成诊断，较慢，请稍候…'
  try {
    const res = await runAllAlertDiagnosis({ device_code: selectedDevice.value, baseline_days: 7 })
    if (res.code === 200) {
      stageAlertNote.value = `知识库诊断完成：${res.data?.diagnosed ?? 0} 条。展开报警可查看。`
      alertDiagMap.value = {}   // 清缓存，展开时重新拉最新
      const cur = stageAlerts.value.find(x => alertSnapKey(x) === expandedDiagKey.value)
      if (cur) await loadDiag(cur)
    } else {
      stageAlertNote.value = res.msg || '诊断任务失败。'
    }
  } catch (err) {
    console.error('批量诊断失败:', err)
    stageAlertNote.value = '诊断任务失败，请重试。'
  } finally {
    stageDiagRunning.value = false
  }
}

function setSparklineRef(key, el) {
  if (el) sparklineEls[key] = el
  else delete sparklineEls[key]
}

function renderSparklines() {
  for (const a of trendAlerts.value) {
    const key = alertKey(a)
    const el = sparklineEls[key]
    const data = sparklineSeries[key]
    if (!el || !data || data.length === 0) continue
    let chart = sparklineInstances[key]
    if (!chart || chart.isDisposed()) {
      chart = echarts.init(el)
      sparklineInstances[key] = chart
    }
    const color = a.severity === 'critical' ? '#ef4444'
      : a.severity === 'warning' ? '#f59e0b' : '#9ca3af'
    const mean = data.reduce((s, d) => s + d[1], 0) / data.length
    chart.setOption({
      animation: false,
      grid: { left: 1, right: 1, top: 3, bottom: 3 },
      xAxis: { type: 'category', show: false, boundaryGap: false },
      yAxis: { type: 'value', show: false, scale: true },
      tooltip: {
        trigger: 'axis', confine: true,
        formatter: (ps) => `${ps[0].axisValue}<br/>中位 ${fmtNum(ps[0].data[1], 3)}`,
      },
      // 窗口均值参考线，便于看"逐渐偏离"
      series: [{
        type: 'line', data, showSymbol: false, smooth: true,
        lineStyle: { width: 1.5, color },
        areaStyle: { color, opacity: 0.08 },
        markLine: {
          silent: true, symbol: 'none',
          lineStyle: { type: 'dashed', width: 1, color: '#d1d5db' },
          data: [{ yAxis: mean }],
        },
      }],
    }, true)
    chart.resize()
  }
}

function disposeSparklines() {
  for (const k in sparklineInstances) {
    const c = sparklineInstances[k]
    if (c && !c.isDisposed()) c.dispose()
  }
  sparklineInstances = {}
}

async function triggerRollup() {
  if (!selectedDevice.value || trendRollupRunning.value) return
  trendRollupRunning.value = true
  trendNote.value = '已在后台开始回填最近 90 天（最近的天最先生成），页面会自动刷新，约 1-2 分钟…'
  try {
    // 后台执行，立即返回免超时；最近的天先算好，随后自动刷新陆续显示
    const res = await runRollup({ device_code: selectedDevice.value, days: 90, background: true })
    if (res.code === 200) {
      _scheduleTrendAutoRefresh()
    } else {
      trendNote.value = res.msg || '触发失败。'
    }
  } catch (err) {
    console.error('回填触发失败:', err)
    trendNote.value = '触发失败，请重试或改用后端手动任务。'
  } finally {
    trendRollupRunning.value = false
  }
}

// 回填后多次延时自动刷新：最近的天先算好，逐步显示出来
function _scheduleTrendAutoRefresh() {
  for (const d of [8000, 20000, 45000, 90000]) {
    setTimeout(() => {
      if (dataMode.value === 'trend-alerts' && selectedDevice.value) { loadTrendAlerts(); loadStageAlerts() }
    }, d)
  }
}

async function loadPredictive(refresh = false) {
  if (!selectedDevice.value) return
  predLoading.value = true
  try {
    const dc = selectedDevice.value
    const q = { device_code: dc, refresh }
    const [rul, bench, prec] = await Promise.all([
      getRul(q).catch(() => null),
      getBenchmark(q).catch(() => null),
      getPrecursors(q).catch(() => null),
    ])
    predRul.value = (rul && rul.code === 200 && rul.data?.items) || []
    predBench.value = (bench && bench.code === 200 && bench.data?.items) || []
    predPrec.value = (prec && prec.code === 200 && prec.data) || {}
    // 取任一返回的 computed_at 作"上次计算时间"（命中缓存才有）
    predComputedAt.value = [rul, bench, prec]
      .map(r => r && r.code === 200 && r.data?.cached ? r.data.computed_at : null)
      .find(Boolean) || ''
  } catch (err) {
    console.error('加载预测维护失败:', err)
  } finally {
    predLoading.value = false
  }
}

async function runDiagnose() {
  if (!selectedDevice.value || diagRunning.value) return
  diagRunning.value = true
  diagErr.value = ''
  diagResult.value = ''
  diagTrace.value = []
  try {
    const res = await diagnoseDevice({ device_code: selectedDevice.value })
    if (res.code === 200 && res.data) {
      diagResult.value = res.data.diagnosis || ''
      diagTrace.value = res.data.trace || []
      if (res.data.error) diagErr.value = res.data.error
    } else {
      diagErr.value = res.msg || 'AI 诊断失败'
    }
  } catch (err) {
    console.error('AI 诊断失败:', err)
    diagErr.value = 'AI 诊断失败（多轮 LLM 较慢，可能超时）。'
  } finally {
    diagRunning.value = false
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
  renderFeatureCharts()
}

// 把某参数的原始序列现算成特征：5min 重采样 + 滑动统计 + 变化率
// 与后端 extract_device_features 语义一致（RESAMPLE_FREQ=5min, 窗口按时间, std ddof=1）
function computeFeatureSeries(rawPoints) {
  const pts = []
  for (const p of rawPoints) {
    const t = parseTime(p.time)
    const v = typeof p.value === 'number' ? p.value : parseFloat(p.value)
    if (t != null && !isNaN(v)) pts.push([t, v])
  }
  pts.sort((a, b) => a[0] - b[0])

  // 重采样到 5min 网格（均值）
  const BUCKET = 5 * 60 * 1000
  const buckets = new Map()
  for (const [t, v] of pts) {
    const b = Math.floor(t / BUCKET) * BUCKET
    const e = buckets.get(b) || [0, 0]
    e[0] += v; e[1] += 1
    buckets.set(b, e)
  }
  const gt = [...buckets.keys()].sort((a, b) => a - b)
  const gv = gt.map(b => buckets.get(b)[0] / buckets.get(b)[1])

  const winPts = { '5min': 1, '15min': 3, '30min': 6, '60min': 12 }

  const rollMean = (n) => gt.map((t, i) => {
    const s = Math.max(0, i - n + 1)
    let sum = 0, c = 0
    for (let j = s; j <= i; j++) { sum += gv[j]; c++ }
    return [t, c ? +(sum / c).toFixed(4) : null]
  })
  const rollStd = (n) => gt.map((t, i) => {
    const s = Math.max(0, i - n + 1)
    const arr = gv.slice(s, i + 1)
    if (arr.length < 2) return [t, null]
    const m = arr.reduce((a, b) => a + b, 0) / arr.length
    const varr = arr.reduce((a, b) => a + (b - m) * (b - m), 0) / (arr.length - 1)
    return [t, +Math.sqrt(varr).toFixed(4)]
  })
  // 5min 网格上的变化率：相邻差 / 5 分钟
  const diff = gt.map((t, i) => i === 0 ? [t, null] : [t, +((gv[i] - gv[i - 1]) / 5).toFixed(4)])

  return { rawPts: pts, winPts, rollMean, rollStd, diff }
}

function renderFeatureCharts() {
  if (dataMode.value !== 'features' || !selectedFeatureParam.value) return
  const key = selectedFeatureParam.value
  const raw = getSeries(key)
  const f = computeFeatureSeries(raw)
  const label = displayNames.value[key] || key
  const unit = paramUnits.value[key] || ''
  const unitSuffix = unit ? ` (${unit})` : ''

  const baseOpt = (series, legend = false) => ({
    animation: false,
    grid: { left: 52, right: 16, top: legend ? 30 : 12, bottom: 26 },
    tooltip: { trigger: 'axis', confine: true },
    legend: legend ? { top: 2, type: 'scroll', textStyle: { fontSize: 10 } } : undefined,
    xAxis: { type: 'time', axisLabel: { fontSize: 10, hideOverlap: true } },
    yAxis: { type: 'value', scale: true, axisLabel: { fontSize: 10 } },
    series,
  })
  const line = (name, data, color) => ({
    name, type: 'line', showSymbol: false, sampling: 'lttb',
    lineStyle: { width: 1 }, itemStyle: { color }, data,
  })

  const optByKey = {
    raw: baseOpt([line(label + unitSuffix, f.rawPts, '#6366f1')]),
    mean: baseOpt(['5min', '15min', '30min', '60min'].map(
      (w, i) => line(w, f.rollMean(f.winPts[w]), SERIES_COLORS[i % SERIES_COLORS.length])), true),
    std: baseOpt(['15min', '30min', '60min'].map(
      (w, i) => line(w, f.rollStd(f.winPts[w]), SERIES_COLORS[(i + 1) % SERIES_COLORS.length])), true),
    diff: baseOpt([line('变化率/min', f.diff, '#ef4444')]),
  }

  for (const fc of FEATURE_CHARTS) {
    const el = featureChartEls[fc.key]
    if (!el) continue
    let inst = featureChartInstances[fc.key]
    if (!inst || inst.isDisposed()) {
      inst = echarts.init(el)
      featureChartInstances[fc.key] = inst
    }
    inst.setOption(optByKey[fc.key], true)
    inst.resize()
  }
}

async function loadDevices() {
  try {
    const res = await client.get('/device-params/devices')
    if (res.code === 200 && res.data) devices.value = res.data
  } catch (err) {
    console.error('加载设备列表失败:', err)
  }
}

function currentDeviceName() {
  const d = devices.value.find(d => d.device_code === selectedDevice.value)
  return d ? d.device_name || d.device_code : selectedDevice.value
}

// 读「参数设定」页保存的筛选结果：特征视图只看勾选过的参数，与参数分析页口径一致。
// 没筛选过返回 null，回退到该设备全部参数。
async function loadCheckedParams() {
  try {
    const r = await client.get('/device-params/screen-state', { params: { device_code: selectedDevice.value } })
    if (r.code === 200 && r.data?.checked_params?.length) return r.data.checked_params
  } catch (e) {}
  return null
}

async function loadRunningPeriods() {
  try {
    const res = await getRunningPeriods({
      device_code: selectedDevice.value,
      start_time: formatForApi(startTime.value),
      end_time: formatForApi(endTime.value),
    })
    if (res.code === 200 && res.data?.periods) runningPeriods.value = res.data.periods
  } catch (err) {
    runningPeriods.value = []
  }
}

async function loadData() {
  if (!selectedDevice.value) return
  clampRangeWithin7Days()
  loading.value = true
  const checked = await loadCheckedParams()
  try {
    // 特征视图在前端现算，需要原始点（不聚合）
    const res = await getDeviceParamData({
      device_code: selectedDevice.value,
      start_time: formatForApi(startTime.value),
      end_time: formatForApi(endTime.value),
      limit: 300000,
      interval: 'raw',
      p_names: checked || undefined,
    })
    if (res.code === 200 && res.data?.series) {
      seriesData.value = res.data.series
      seriesKeys.value = checked || Object.keys(res.data.series)
      Object.assign(displayNames.value, res.data.display_names || {})
      Object.assign(paramUnits.value, res.data.units || {})
      await loadRunningPeriods()
    } else {
      seriesData.value = {}
      seriesKeys.value = []
      runningPeriods.value = []
    }
  } catch (err) {
    console.error('加载参数数据失败:', err)
    seriesData.value = {}
    seriesKeys.value = []
  } finally {
    loading.value = false
    await nextTick()
    if (dataMode.value === 'features') {
      if (!selectedFeatureParam.value || !seriesKeys.value.includes(selectedFeatureParam.value)) {
        selectedFeatureParam.value = featureParamList.value[0]?.key || ''
      }
      await nextTick()
      renderFeatureCharts()
    }
  }
}

// 参数点位的中文名/单位：即使某参数当前窗口没数据也能正确显示名字
async function loadPointMeta() {
  try {
    const res = await getDeviceParamPoints(selectedDevice.value)
    if (res.code === 200 && res.data) {
      for (const p of res.data) {
        if (!displayNames.value[p.p_name]) displayNames.value[p.p_name] = p.display_name || p.p_name
        if (p.unit && !paramUnits.value[p.p_name]) paramUnits.value[p.p_name] = p.unit
      }
    }
  } catch (e) {}
}

function onDeviceChange() {
  seriesData.value = {}

  seriesKeys.value = []
  displayNames.value = {}
  paramUnits.value = {}
  runningPeriods.value = []
  selectedFeatureParam.value = ''
  trendAlerts.value = []
  trendWindow.value = ''
  trendNote.value = ''
  stageAlerts.value = []
  stageAlertNote.value = ''
  alertDiagMap.value = {}
  expandedDiagKey.value = ''
  diagResult.value = ''
  diagErr.value = ''
  diagTrace.value = []
  predRul.value = []
  predBench.value = []
  predPrec.value = {}
  predComputedAt.value = ''
  disposeFeatureCharts()
  disposeSparklines()
  if (!selectedDevice.value) return
  loadPointMeta()
  if (dataMode.value === 'trend-alerts') { loadTrendAlerts(); loadStageAlerts() }
  else if (dataMode.value === 'predictive') loadPredictive()
  else loadData()
}

async function switchDataMode(mode) {
  dataMode.value = mode
  if (!selectedDevice.value) return
  if (mode === 'trend-alerts') {
    disposeFeatureCharts()
    await loadTrendAlerts()
    loadStageAlerts()
    return
  }
  if (mode === 'predictive') {
    disposeFeatureCharts()
    await loadPredictive()
    return
  }
  // features
  disposeSparklines()
  if (seriesKeys.value.length === 0) {
    await loadData()
    return
  }
  if (!selectedFeatureParam.value || !seriesKeys.value.includes(selectedFeatureParam.value)) {
    selectedFeatureParam.value = featureParamList.value[0]?.key || ''
  }
  await nextTick()
  renderFeatureCharts()
}

let resizeHandler = null

onMounted(async () => {
  await loadDevices()
  const deviceFromQuery = route.query.device
  if (deviceFromQuery && devices.value.some(d => d.device_code === deviceFromQuery)) {
    selectedDevice.value = deviceFromQuery
    onDeviceChange()
  }
  resizeHandler = () => {
    for (const k of Object.keys(featureChartInstances)) {
      const inst = featureChartInstances[k]
      if (inst && !inst.isDisposed()) inst.resize()
    }
  }
  window.addEventListener('resize', resizeHandler)
})

onUnmounted(() => {
  disposeFeatureCharts()
  disposeSparklines()
  if (resizeHandler) window.removeEventListener('resize', resizeHandler)
})
</script>
