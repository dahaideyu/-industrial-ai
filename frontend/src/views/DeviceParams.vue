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

        <div class="flex items-center gap-1 ml-2 bg-gray-100 rounded-lg p-0.5">
          <button
            @click="switchDataMode('params')"
            class="px-3 py-1.5 text-xs rounded-md transition-colors"
            :class="dataMode === 'params' ? 'bg-white text-gray-900 font-bold shadow-sm' : 'text-gray-500 hover:text-gray-700'"
          >原始参数</button>
          <button
            @click="switchDataMode('features')"
            class="px-3 py-1.5 text-xs rounded-md transition-colors"
            :class="dataMode === 'features' ? 'bg-white text-gray-900 font-bold shadow-sm' : 'text-gray-500 hover:text-gray-700'"
          >特征视图</button>
          <button
            @click="switchDataMode('stage')"
            class="px-3 py-1.5 text-xs rounded-md transition-colors"
            :class="dataMode === 'stage' ? 'bg-white text-gray-900 font-bold shadow-sm' : 'text-gray-500 hover:text-gray-700'"
          >阶段分析</button>
          <button
            @click="switchDataMode('trend-alerts')"
            class="px-3 py-1.5 text-xs rounded-md transition-colors"
            :class="dataMode === 'trend-alerts' ? 'bg-white text-gray-900 font-bold shadow-sm' : 'text-gray-500 hover:text-gray-700'"
          >趋势预警</button>
          <button
            @click="switchDataMode('profile')"
            class="px-3 py-1.5 text-xs rounded-md transition-colors"
            :class="dataMode === 'profile' ? 'bg-white text-gray-900 font-bold shadow-sm' : 'text-gray-500 hover:text-gray-700'"
          >参数画像</button>
          <button
            @click="switchDataMode('predictive')"
            class="px-3 py-1.5 text-xs rounded-md transition-colors"
            :class="dataMode === 'predictive' ? 'bg-white text-gray-900 font-bold shadow-sm' : 'text-gray-500 hover:text-gray-700'"
          >预测维护</button>
        </div>

        <div v-if="dataMode === 'params'" class="flex items-center gap-1 ml-2 bg-gray-100 rounded-lg p-0.5">
          <button @click="chartMode='stack'; updateChart()" class="px-2 py-1 text-xs rounded transition-colors"
            :class="chartMode === 'stack' ? 'bg-white text-gray-900 font-bold shadow-sm' : 'text-gray-500'">分列</button>
          <button @click="chartMode='overlay'; updateChart()" class="px-2 py-1 text-xs rounded transition-colors"
            :class="chartMode === 'overlay' ? 'bg-white text-gray-900 font-bold shadow-sm' : 'text-gray-500'">叠加</button>
        </div>
      </div>

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
    </div>

    <!-- 阶段分析视图（独立组件，自行加载数据）-->
    <div v-if="dataMode === 'stage'">
      <div v-if="!selectedDevice" class="text-center py-16 text-gray-400 bg-white rounded-xl border border-gray-100 shadow-sm">
        <div class="text-4xl mb-3">🔧</div>
        <p class="text-sm">请从上方选择设备</p>
      </div>
      <StageAnalysis v-else :key="selectedDevice" :device-code="selectedDevice" />
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

    <!-- 参数画像（AI 识别参数类型/角色/正常区间/spec，工艺确认后生效）-->
    <div v-else-if="dataMode === 'profile'">
      <div v-if="!selectedDevice" class="text-center py-16 text-gray-400 bg-white rounded-xl border border-gray-100 shadow-sm">
        <div class="text-4xl mb-3">🧬</div>
        <p class="text-sm">请从上方选择设备</p>
      </div>
      <div v-else class="space-y-4">
        <div class="bg-white rounded-xl border border-gray-100 shadow-sm p-4">
          <div class="flex items-center justify-between flex-wrap gap-3">
            <div class="flex items-center gap-3 flex-wrap">
              <span class="text-xs font-bold text-gray-400 uppercase tracking-wider">参数画像 · 自适应</span>
              <span class="inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded bg-emerald-50 text-emerald-600 font-bold">已确认 {{ profileConfirmedCount }}</span>
              <span class="inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded bg-amber-50 text-amber-600">待确认 {{ profileRows.length - profileConfirmedCount }}</span>
              <label class="flex items-center gap-1 text-xs text-gray-500">
                <input type="checkbox" v-model="profileUseLlm" class="w-3.5 h-3.5" /> 用 AI 提语义
              </label>
            </div>
            <div class="flex items-center gap-2">
              <button @click="loadProfile" :disabled="profileLoading"
                class="px-3 py-1.5 text-xs rounded-lg bg-gray-50 text-gray-600 border border-gray-200 hover:bg-gray-100 disabled:opacity-50">刷新</button>
              <button @click="runSuggest" :disabled="profileSuggesting"
                title="对全部参数自动识别类型/角色/正常区间(写为待确认建议)"
                class="px-3 py-1.5 text-xs rounded-lg bg-violet-500 text-white font-bold hover:bg-violet-600 disabled:opacity-50">
                {{ profileSuggesting ? 'AI 识别中…' : 'AI 识别' }}
              </button>
            </div>
          </div>
          <p v-if="profileNote" class="text-xs mt-2" :class="profileNoteErr ? 'text-rose-500' : 'text-amber-600'">{{ profileNote }}</p>
          <p class="text-[11px] text-gray-300 mt-2">类型由统计签名(无名也能判)+DB type+AI 综合给出"建议"；正常区间从历史精确学习；Cpk 用确认的 spec。高风险阈值须确认后生效。</p>
        </div>

        <div v-if="profileRows.length > 0" class="bg-white rounded-xl border border-gray-100 shadow-sm overflow-hidden">
          <div class="overflow-x-auto">
            <table class="w-full text-sm">
              <thead class="bg-gray-50">
                <tr class="text-left text-xs text-gray-500 border-b border-gray-200 whitespace-nowrap">
                  <th class="py-3 px-4 font-semibold">参数</th>
                  <th class="py-3 px-3 font-semibold">类型</th>
                  <th class="py-3 px-3 font-semibold">角色 / 类别</th>
                  <th class="py-3 px-3 font-semibold text-center">盯</th>
                  <th class="py-3 px-3 font-semibold text-right">正常区间</th>
                  <th class="py-3 px-3 font-semibold">规格(spec_low / spec_high)</th>
                  <th class="py-3 px-3 font-semibold text-right">Cpk</th>
                  <th class="py-3 px-3 font-semibold text-center">来源/置信</th>
                  <th class="py-3 px-3 font-semibold text-center">状态</th>
                  <th class="py-3 px-3 font-semibold"></th>
                </tr>
              </thead>
              <tbody class="divide-y divide-gray-50">
                <tr v-for="row in profileRows" :key="row.p_name" class="hover:bg-gray-50/50 align-top">
                  <td class="py-2 px-4 whitespace-nowrap">
                    <div class="font-bold text-gray-800">{{ row.display_name || row.p_name }}</div>
                    <div class="text-[10px] text-gray-300">{{ row.p_name }}<span v-if="row.unit"> · {{ row.unit }}</span></div>
                  </td>
                  <td class="py-2 px-3">
                    <select v-model="row.ptype" class="text-xs border border-gray-200 rounded px-1 py-0.5 bg-white">
                      <option v-for="t in PTYPES" :key="t" :value="t">{{ t }}</option>
                    </select>
                  </td>
                  <td class="py-2 px-3">
                    <input v-model="row.role" class="text-xs border border-gray-200 rounded px-1 py-0.5 w-28" />
                    <input v-model="row.category" class="text-xs border border-gray-200 rounded px-1 py-0.5 w-24 mt-0.5" />
                  </td>
                  <td class="py-2 px-3 text-center">
                    <input type="checkbox" v-model="row.monitor" class="w-4 h-4" />
                  </td>
                  <td class="py-2 px-3 text-right text-xs text-gray-500 tabular-nums whitespace-nowrap">
                    {{ fmtNum(row.bands && row.bands.normal_low) }} ~ {{ fmtNum(row.bands && row.bands.normal_high) }}
                  </td>
                  <td class="py-2 px-3 whitespace-nowrap">
                    <input v-model.number="row._spec_low" type="number" step="any" placeholder="LSL"
                      class="text-xs border border-gray-200 rounded px-1 py-0.5 w-20" />
                    <span class="text-gray-300 mx-0.5">/</span>
                    <input v-model.number="row._spec_high" type="number" step="any" placeholder="USL"
                      class="text-xs border border-gray-200 rounded px-1 py-0.5 w-20" />
                  </td>
                  <td class="py-2 px-3 text-right tabular-nums font-semibold"
                    :class="cpkCls(row._cpk)">{{ row._cpk == null ? '—' : fmtNum(row._cpk, 2) }}</td>
                  <td class="py-2 px-3 text-center text-[10px] text-gray-400 whitespace-nowrap">
                    {{ row.source && row.source.ptype }} · {{ Math.round((row.confidence||0)*100) }}%
                  </td>
                  <td class="py-2 px-3 text-center">
                    <span :class="['text-[10px] px-1.5 py-0.5 rounded', row.confirmed ? 'bg-emerald-50 text-emerald-600' : 'bg-amber-50 text-amber-600']">
                      {{ row.confirmed ? '已确认' : '建议' }}
                    </span>
                  </td>
                  <td class="py-2 px-3">
                    <div class="flex items-center gap-1">
                      <button @click="recalcSpec(row)" :disabled="row._recalc"
                        class="text-xs px-2 py-1 rounded bg-indigo-500 text-white hover:bg-indigo-600 disabled:opacity-50"
                        :title="row._recalc_result ? `中位数=${row._recalc_result.median} μ=${row._recalc_result.mean} σ=${row._recalc_result.std} 过滤${row._recalc_result.filtered_count}/${row._recalc_result.total_count}条` : '基于原始数据+CPK=1.33 重算上下限'">
                        {{ row._recalc ? '计算中...' : '自动设置上下限' }}
                      </button>
                      <button @click="recalcCpkRow(row)" :disabled="row._recalcCpk"
                        class="text-xs px-2 py-1 rounded bg-amber-500 text-white hover:bg-amber-600 disabled:opacity-50"
                        :title="row._recalcCpkResult ? `全量数据 CPK=${row._recalcCpkResult.cpk} CPU=${row._recalcCpkResult.cpu} CPL=${row._recalcCpkResult.cpl} μ=${row._recalcCpkResult.mean} σ=${row._recalcCpkResult.std}` : '用当前上下限 + 全量原始数据直接算 CPK'">
                        {{ row._recalcCpk ? '计算中...' : '重算' }}
                      </button>
                      <button @click="confirmRow(row)" :disabled="row._saving"
                        class="text-xs px-2 py-1 rounded bg-emerald-500 text-white hover:bg-emerald-600 disabled:opacity-50">确认</button>
                    </div>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>

        <div v-else-if="!profileLoading" class="text-center py-16 text-gray-400 bg-white rounded-xl border border-gray-100 shadow-sm">
          <div class="text-4xl mb-3">🧬</div>
          <p class="text-sm">尚无参数画像。点「AI 识别」让系统自动识别该设备所有参数的类型与正常区间。</p>
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

    <template v-else>
    <!-- Loading -->
    <div v-if="loading" class="text-center py-16 text-gray-400">
      <div class="text-3xl mb-3 animate-spin">⏳</div>
      <p>正在加载参数数据...</p>
    </div>

    <!-- Empty State -->
    <div v-else-if="!selectedDevice" class="text-center py-16 text-gray-400 bg-white rounded-xl border border-gray-100 shadow-sm">
      <div class="text-4xl mb-3">🔧</div>
      <p class="text-sm">请从上方选择设备并点击查询</p>
    </div>

    <div v-else-if="seriesKeys.length === 0" class="text-center py-16 text-gray-400 bg-white rounded-xl border border-gray-100 shadow-sm">
      <div class="text-4xl mb-3">📉</div>
      <p class="text-sm">该时间段内暂无参数数据</p>
    </div>

    <!-- Chart -->
    <div v-else class="space-y-6">
      <div class="bg-white rounded-xl border border-gray-100 shadow-sm p-5">
        <div class="flex items-center justify-between mb-3 flex-wrap gap-2">
          <div class="flex items-center gap-3">
            <span v-if="dataMode === 'features'" class="text-xs font-bold text-indigo-500 uppercase tracking-wider bg-indigo-50 px-2 py-0.5 rounded">📊 特征视图</span>
            <span v-else class="text-xs font-bold text-gray-400 uppercase tracking-wider">参数趋势</span>
            <!-- 仅运行状态开关（参数视图 + 特征视图通用）-->
            <label v-if="runningPeriods.length > 0" class="flex items-center gap-1.5 cursor-pointer select-none" title="只显示设备运行(code 1)时段内的数据点">
              <input type="checkbox" v-model="showRunningOnly" @change="onRunningOnlyToggle" class="sr-only peer" />
              <span class="w-8 h-4 rounded-full bg-gray-200 peer-checked:bg-green-500 transition-colors relative after:content-[''] after:absolute after:top-0.5 after:left-0.5 after:w-3 after:h-3 after:rounded-full after:bg-white after:transition-transform peer-checked:after:translate-x-4"></span>
              <span class="text-xs text-gray-500">仅运行状态</span>
            </label>
            <template v-if="dataMode === 'params'">
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
            </template>
          </div>
          <span class="text-xs text-gray-400">
            <template v-if="dataMode === 'features'">
              {{ seriesKeys.length }} 个参数 · 每参数 4 张特征图
            </template>
            <template v-else>
              {{ visibleKeys.length }} / {{ seriesKeys.length }} 个参数
              <span v-if="aggInterval" class="ml-1 text-amber-600 bg-amber-50 px-1.5 py-0.5 rounded">
                已按 {{ aggInterval }} 聚合
              </span>
            </template>
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

        <!-- 特征视图：参数选择器 -->
        <div v-if="dataMode === 'features'" class="flex flex-wrap items-center gap-1.5 mb-3 max-h-[96px] overflow-y-auto py-1">
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

        <!-- Parameter toggles - above chart, not overlapping (仅原始参数模式) -->
        <div v-if="dataMode === 'params'" class="flex flex-wrap gap-1.5 mb-4 max-h-[120px] overflow-y-auto py-1">
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

        <!-- 原始参数模式：单一大图 -->
        <div v-if="dataMode === 'params'" ref="chartContainer" class="w-full" :style="{ height: chartHeight }"></div>

        <!-- 特征视图模式：选中参数的 4 张特征图 -->
        <div v-else>
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

      <!-- AI Analysis History -->
      <div v-if="showAnalysisLog" class="bg-white rounded-xl border border-gray-100 shadow-sm p-5">
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

      <!-- AI Analysis Result -->
      <div v-if="analysisResult" class="bg-white rounded-xl border border-gray-100 shadow-sm p-5">
        <div class="flex items-center justify-between mb-4">
          <h2 class="font-headline text-base font-semibold text-gray-900">
            AI 分析结果<span v-if="analysisResultMeta" class="ml-2 text-xs font-normal text-gray-400">{{ analysisResultMeta }}</span>
          </h2>
          <button
            @click="analysisResult = ''; analysisResultMeta = ''"
            class="text-xs text-gray-400 hover:text-gray-600 transition-colors"
          >关闭</button>
        </div>
        <div class="prose prose-sm max-w-none text-gray-700 leading-relaxed whitespace-pre-wrap">
          {{ analysisResult }}
        </div>
      </div>

      <!-- Analysis Error -->
      <div v-if="analysisError" class="bg-red-50 border border-red-200 rounded-xl p-4 text-sm text-red-700">
        {{ analysisError }}
      </div>
    </div>
    </template>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted, nextTick, watch } from 'vue'
import * as echarts from 'echarts'
import {
  getDeviceParamData,
  getRunningPeriods,
  getAlignedData,
  detectAnomalies,
  analyzeDeviceParams,
  getAnalysisLog,
  getStatsOverview,
  getTrendAlerts,
  getAlertDiagnosis,
  runAlertDiagnose,
  runAllAlertDiagnosis,
  runRollup,
  getParamProfile,
  suggestParamProfile,
  saveParamProfile,
  getDeviceParamPoints,
  getCpk,
  recalcSpecLimits,
  recalcCpk,
  diagnoseDevice,
  getRul,
  getBenchmark,
  getPrecursors,
} from '../api/client.js'
import StageAnalysis from './StageAnalysis.vue'

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
const dataMode = ref('params')  // 'params' | 'features' | 'stage' | 'trend-alerts'

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

// ── 参数画像状态 ──
const PTYPES = ['continuous', 'state', 'counter', 'switch', 'setpoint', 'enum', 'unknown']
const profileRows = ref([])
const profileLoading = ref(false)
const profileSuggesting = ref(false)
const profileUseLlm = ref(true)
const profileNote = ref('')
const profileNoteErr = ref(false)
const profileConfirmedCount = computed(() => profileRows.value.filter(r => r.confirmed).length)

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
function cpkCls(v) {
  if (v == null) return 'text-gray-300'
  if (v < 1) return 'text-rose-500'
  if (v < 1.33) return 'text-amber-500'
  return 'text-emerald-600'
}

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

// 时间范围：默认最近 24 小时；上限 7 天（jsonb 现算 + 大窗口性能考量）
const MAX_RANGE_DAYS = 7
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
  clampRangeWithin7Days()
}

// 保证范围 ≤ 7 天，超出则收窄起点并提示
function clampRangeWithin7Days() {
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
  showAlarmOverlay.value = false
  alarmEvents.value = []
  alignedRows.value = []
  paramsMeta.value = {}
  alarmTypeFilter.value = []
  selectedFeatureParam.value = ''
  disposeChart()
  disposeFeatureCharts()
  disposeSparklines()
  trendAlerts.value = []
  trendWindow.value = ''
  trendNote.value = ''
  profileRows.value = []
  profileNote.value = ''
  diagResult.value = ''
  diagErr.value = ''
  diagTrace.value = []
  predRul.value = []
  predBench.value = []
  predPrec.value = {}
  predComputedAt.value = ''
  if (selectedDevice.value) {
    if (dataMode.value === 'trend-alerts') { loadTrendAlerts(); loadStageAlerts() }
    else if (dataMode.value === 'profile') loadProfile()
    else if (dataMode.value === 'predictive') loadPredictive()
    else loadData()
  }
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

async function switchDataMode(mode) {
  dataMode.value = mode
  if (mode === 'stage') {
    // 阶段分析为独立组件，自行加载；释放主图表与特征图，避免占用
    disposeChart()
    disposeFeatureCharts()
    return
  }
  if (mode === 'trend-alerts') {
    // 趋势预警：读预计算快照，与原始图表无关
    disposeChart()
    disposeFeatureCharts()
    if (selectedDevice.value) { await loadTrendAlerts(); loadStageAlerts() }
    return
  }
  if (mode === 'profile') {
    // 参数画像：读/识别参数语义，与原始图表无关
    disposeChart()
    disposeFeatureCharts()
    if (selectedDevice.value) await loadProfile()
    return
  }
  if (mode === 'predictive') {
    // 预测维护：RUL/对标/前兆，只读端点
    disposeChart()
    disposeFeatureCharts()
    if (selectedDevice.value) await loadPredictive()
    return
  }
  if (mode === 'features') {
    // 特征视图：基于已加载的实时参数(device_alarm_info)在前端现算
    disposeChart()  // 释放原始参数大图
    if (seriesKeys.value.length === 0 && selectedDevice.value) {
      loading.value = true
      await loadData()   // loadData 末尾会按 dataMode 渲染特征图
      return
    }
    if (!selectedFeatureParam.value || !seriesKeys.value.includes(selectedFeatureParam.value)) {
      selectedFeatureParam.value = featureParamList.value[0]?.key || ''
    }
    await nextTick()
    renderFeatureCharts()
  } else {
    disposeFeatureCharts()
    loading.value = true
    await loadData()
  }
}

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

// ── 参数画像 ──

function _toProfileRow(p) {
  const bands = p.bands || {}
  return {
    ...p, bands, monitor: !!p.monitor,
    _spec_low: bands.spec_low ?? null,
    _spec_high: bands.spec_high ?? null,
    _cpk: null, _saving: false, _recalc: false, _recalc_result: null,
    _recalcCpk: false, _recalcCpkResult: null,
  }
}

async function loadProfile() {
  if (!selectedDevice.value) return
  profileLoading.value = true
  profileNote.value = ''
  profileNoteErr.value = false
  try {
    const res = await getParamProfile(selectedDevice.value)
    if (res.code === 200 && res.data) {
      profileRows.value = (res.data.profiles || []).map(_toProfileRow)
      if (profileRows.value.length === 0) {
        profileNote.value = '尚无画像，点「AI 识别」生成。'
      } else {
        await loadCpkInto()
      }
    }
  } catch (err) {
    console.error('加载参数画像失败:', err)
    profileNote.value = '加载参数画像失败。'
    profileNoteErr.value = true
  } finally {
    profileLoading.value = false
  }
}

async function loadCpkInto() {
  try {
    const res = await getCpk({ device_code: selectedDevice.value, days: 30 })
    if (res.code === 200 && res.data?.cpk) {
      const m = {}
      for (const c of res.data.cpk) m[c.p_name] = c.cpk
      for (const r of profileRows.value) r._cpk = m[r.p_name] ?? null
    }
  } catch (e) { /* Cpk 缺失不阻断 */ }
}

async function runSuggest() {
  if (!selectedDevice.value || profileSuggesting.value) return
  profileSuggesting.value = true
  profileNoteErr.value = false
  profileNote.value = profileUseLlm.value
    ? '正在识别全部参数(调用 AI 提语义，可能稍慢)…' : '正在按统计签名识别全部参数…'
  try {
    const res = await suggestParamProfile({
      device_code: selectedDevice.value, use_llm: profileUseLlm.value,
    })
    if (res.code === 200) {
      profileNote.value = `识别完成，共 ${res.data.count} 个参数(均为待确认建议，请逐行核对后确认)。`
      await loadProfile()
    } else {
      profileNote.value = res.msg || '识别失败'
      profileNoteErr.value = true
    }
  } catch (err) {
    console.error('参数识别失败:', err)
    profileNote.value = '参数识别失败。'
    profileNoteErr.value = true
  } finally {
    profileSuggesting.value = false
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

async function confirmRow(row) {
  if (row._saving) return
  row._saving = true
  // 组装回 profile：编辑的 spec 写回 bands（标记为工程规格）
  const profile = { ...row }
  for (const k of ['_spec_low', '_spec_high', '_cpk', '_saving', 'confirmed', 'updated_by']) {
    delete profile[k]
  }
  profile.bands = { ...(row.bands || {}) }
  if (row._spec_low != null) profile.bands.spec_low = row._spec_low
  if (row._spec_high != null) profile.bands.spec_high = row._spec_high
  if (row._spec_low != null || row._spec_high != null) profile.bands.spec_source = 'engineering'
  try {
    const res = await saveParamProfile({
      device_code: selectedDevice.value, p_name: row.p_name, profile,
    })
    if (res.code === 200) {
      row.confirmed = true
      await loadCpkInto()
    } else {
      profileNote.value = res.msg || '保存失败'
      profileNoteErr.value = true
    }
  } catch (err) {
    console.error('确认画像失败:', err)
    profileNote.value = '保存失败。'
    profileNoteErr.value = true
  } finally {
    row._saving = false
  }
}

async function recalcSpec(row) {
  row._recalc = true
  try {
    const res = await recalcSpecLimits({
      device_code: selectedDevice.value, p_name: row.p_name,
    })
    if (res.code === 200 && res.data) {
      row._spec_low = res.data.spec_low
      row._spec_high = res.data.spec_high
      row._recalc_result = res.data
    } else {
      profileNote.value = res.msg || '重算失败'
      profileNoteErr.value = true
    }
  } catch (err) {
    console.error('重算规格限失败:', err)
    profileNote.value = '重算失败。'
    profileNoteErr.value = true
  } finally {
    row._recalc = false
  }
}

async function recalcCpkRow(row) {
  const spec_low = row._spec_low
  const spec_high = row._spec_high
  if (spec_low == null || spec_high == null) {
    profileNote.value = '请先设置上下限或点"自动设置上下限"'
    profileNoteErr.value = true
    return
  }
  row._recalcCpk = true
  try {
    const res = await recalcCpk({
      device_code: selectedDevice.value, p_name: row.p_name,
      spec_low, spec_high,
    })
    if (res.code === 200 && res.data) {
      row._cpk = res.data.cpk
      row._recalcCpkResult = res.data
    } else {
      profileNote.value = res.msg || '重算CPK失败'
      profileNoteErr.value = true
    }
  } catch (err) {
    console.error('重算CPK失败:', err)
    profileNote.value = '重算CPK失败。'
    profileNoteErr.value = true
  } finally {
    row._recalcCpk = false
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
  if (dataMode.value === 'features') renderFeatureCharts()
  else updateChart()
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

  clampRangeWithin7Days()
  loading.value = true
  analysisResult.value = ''
  analysisError.value = ''
  disposeChart()

  try {
    const spanHours = (new Date(endTime.value) - new Date(startTime.value)) / 3600000
    const useInterval = (dataMode.value === 'params' && spanHours > 3) ? 'auto' : 'raw'

    if (dataMode.value === 'params') {
      const pointsRes = await getDeviceParamPoints(selectedDevice.value)
      if (pointsRes.code === 200 && pointsRes.data) {
        ALL_POINT_NAMES.value = pointsRes.data.map(p => p.p_name)
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
        // 如果默认点位没有数据，尝试加载所有点位
        if (Object.keys(series).length === 0 && ALL_POINT_NAMES.value.length > 0) {
          const allRes = await getDeviceParamData({
            device_code: selectedDevice.value,
            start_time: formatForApi(startTime.value),
            end_time: formatForApi(endTime.value),
            limit: 300000,
            interval: useInterval,
          })
          if (allRes.code === 200 && allRes.data?.series) {
            seriesData.value = allRes.data.series
            visibleKeys.value = Object.keys(allRes.data.series).slice(0, DEFAULT_VISIBLE_COUNT)
            Object.assign(displayNames.value, allRes.data.display_names || {})
            Object.assign(paramUnits.value, allRes.data.units || {})
            aggInterval.value = allRes.data.aggregated ? (allRes.data.interval || '') : ''
            for (const key of Object.keys(allRes.data.series)) {
              LOADED_POINT_NAMES.value.add(key)
            }
          } else {
            seriesData.value = {}
            visibleKeys.value = []
            displayNames.value = {}
            paramUnits.value = {}
            aggInterval.value = ''
          }
        } else {
          seriesData.value = series
          visibleKeys.value = defaultPoints.filter(k => series[k])
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
    } else {
      const res = await getDeviceParamData({
        device_code: selectedDevice.value,
        start_time: formatForApi(startTime.value),
        end_time: formatForApi(endTime.value),
        limit: 300000,
        interval: useInterval,
      })

      if (res.code === 200 && res.data?.series) {
        seriesData.value = res.data.series
        seriesKeys.value = Object.keys(res.data.series)
        visibleKeys.value = [...seriesKeys.value]
        Object.assign(displayNames.value, res.data.display_names || {})
        Object.assign(paramUnits.value, res.data.units || {})
        aggInterval.value = res.data.aggregated ? (res.data.interval || '') : ''

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
    if (dataMode.value === 'features') {
      if (!selectedFeatureParam.value || !seriesKeys.value.includes(selectedFeatureParam.value)) {
        selectedFeatureParam.value = featureParamList.value[0]?.key || ''
      }
      await nextTick()
      renderFeatureCharts()
    } else if (seriesKeys.value.length > 0) {
      initChart()
    }
  }
}

async function toggleSeries(key) {
  const idx = visibleKeys.value.indexOf(key)
  if (idx >= 0) {
    visibleKeys.value.splice(idx, 1)
    updateChart()
  } else {
    if (!LOADED_POINT_NAMES.value.has(key)) {
      try {
        const spanHours = (new Date(endTime.value) - new Date(startTime.value)) / 3600000
        const useInterval = spanHours > 3 ? 'auto' : 'raw'

        const res = await getDeviceParamData({
          device_code: selectedDevice.value,
          start_time: formatForApi(startTime.value),
          end_time: formatForApi(endTime.value),
          limit: 300000,
          interval: useInterval,
          p_names: [key],
        })

        LOADED_POINT_NAMES.value.add(key)
        if (res.code === 200 && res.data?.series) {
          Object.assign(seriesData.value, res.data.series)
          if (res.data.display_names) {
            Object.assign(displayNames.value, res.data.display_names)
          }
          if (res.data.units) {
            Object.assign(paramUnits.value, res.data.units)
          }
        }
      } catch (err) {
        console.error('加载参数数据失败:', err)
        return
      }
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

async function toggleAll() {
  if (visibleKeys.value.length === seriesKeys.value.length) {
    visibleKeys.value = []
    updateChart()
  } else {
    const unloadedKeys = seriesKeys.value.filter(k => !LOADED_POINT_NAMES.value.has(k))
    if (unloadedKeys.length > 0) {
      try {
        const spanHours = (new Date(endTime.value) - new Date(startTime.value)) / 3600000
        const useInterval = spanHours > 3 ? 'auto' : 'raw'

        const res = await getDeviceParamData({
          device_code: selectedDevice.value,
          start_time: formatForApi(startTime.value),
          end_time: formatForApi(endTime.value),
          limit: 300000,
          interval: useInterval,
          p_names: unloadedKeys,
        })

        if (res.code === 200 && res.data?.series) {
          Object.assign(seriesData.value, res.data.series)
          if (res.data.display_names) {
            Object.assign(displayNames.value, res.data.display_names)
          }
          if (res.data.units) {
            Object.assign(paramUnits.value, res.data.units)
          }
          for (const key of Object.keys(res.data.series)) {
            LOADED_POINT_NAMES.value.add(key)
          }
        }
      } catch (err) {
        console.error('加载参数数据失败:', err)
        return
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
    const paramSeries = {
      name: displayName,
      type: 'line', smooth: true, symbol: 'none',
      lineStyle: { width: 1.5, color },
      itemStyle: { color },
      data: values.map((v, i) => [parseTime(allTimes[i]), v]),
      connectNulls: true,
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

      seriesList.push({
        name: label, type: 'line', smooth: true, symbol: 'none',
        lineStyle: { width: 1.5, color },
        data: pts, xAxisIndex: gridIdx, yAxisIndex: gridIdx,
        connectNulls: true,
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
  if (showAnalysisLog.value) await loadAnalysisLog()
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

onMounted(() => {
  loadDevices()
  resizeHandler = () => handleResize()
  window.addEventListener('resize', resizeHandler)
})

onUnmounted(() => {
  disposeChart()
  disposeFeatureCharts()
  disposeSparklines()
  if (resizeHandler) {
    window.removeEventListener('resize', resizeHandler)
  }
})
</script>
