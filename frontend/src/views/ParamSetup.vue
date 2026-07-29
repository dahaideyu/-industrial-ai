<template>
  <div class="p-8 max-w-[1440px] mx-auto">
    <!-- Header -->
    <div class="mb-6 flex justify-between items-end">
      <div>
        <h1 class="font-headline text-2xl font-semibold text-on-surface">参数设定</h1>
        <p class="text-secondary text-sm mt-1">筛选设备有效参数、设定生产节拍（脉搏）、确认参数画像 —— 作为「参数分析」页各项分析的基础配置</p>
      </div>
    </div>

    <!-- 设备选择 -->
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
        <button
          v-if="selectedDevice"
          @click="goToAnalysis"
          class="px-4 py-2 bg-gray-50 text-gray-600 text-sm font-medium rounded-lg border border-gray-200 hover:bg-gray-100 transition-colors"
        >前往参数分析 →</button>
      </div>
    </div>

    <template v-if="selectedDevice">
      <!-- Tabs（三个并列，互不依赖，可随时切换） -->
      <div class="bg-white rounded-xl border border-gray-100 shadow-sm px-5 py-2 mb-6">
        <div class="flex flex-wrap items-center gap-2">
          <button
            v-for="t in TABS" :key="t.key"
            @click="activeTab = t.key"
            class="px-3 py-1.5 text-xs rounded-md transition-colors"
            :class="activeTab === t.key ? 'bg-white text-gray-900 font-bold shadow-sm' : 'text-gray-500 hover:text-gray-700'"
          >{{ t.icon }} {{ t.label }}
            <span v-if="t.key === 'screen' && checkedParams.length" class="text-emerald-500">✅</span>
            <span v-else-if="t.key === 'pulse' && pulseParam" class="text-emerald-500">✅</span>
          </button>
        </div>
        <p v-if="stateLoadNote" class="text-xs mt-1.5 px-1" :class="stateLoadErr ? 'text-rose-500' : 'text-gray-400'">{{ stateLoadNote }}</p>
      </div>

      <!-- Tab①：参数筛选 —— 始终列出该设备定义的全部参数，AI 只是辅助建议，人可随时勾选 -->
      <div v-if="activeTab === 'screen'" class="space-y-4">
        <div class="bg-white rounded-xl border border-gray-100 shadow-sm p-4">
          <div class="flex items-center justify-between flex-wrap gap-3">
            <div class="flex items-center gap-3 flex-wrap">
              <span class="text-xs font-bold text-gray-400 uppercase tracking-wider">参数筛选</span>
              <span class="text-xs text-gray-500">已选 {{ checkedParams.length }} / {{ paramRows.length }} 个参数</span>
              <span v-if="screenSummary" class="text-xs text-gray-400">{{ screenSummary }}</span>
              <div class="flex items-center gap-1">
                <span class="text-xs text-gray-400">窗口</span>
                <button v-for="d in [1, 3, 7]" :key="d" @click="screenDays = d"
                  class="px-1.5 py-0.5 text-[11px] rounded"
                  :class="screenDays === d ? 'bg-amber-100 text-amber-700' : 'hover:bg-gray-100 text-gray-400'">{{ d }}天</button>
              </div>
            </div>
            <div class="flex items-center gap-2">
              <button @click="toggleAll(true)" class="px-2.5 py-1.5 text-xs rounded-lg bg-gray-50 text-gray-500 border border-gray-200 hover:bg-gray-100">全选</button>
              <button @click="toggleAll(false)" class="px-2.5 py-1.5 text-xs rounded-lg bg-gray-50 text-gray-500 border border-gray-200 hover:bg-gray-100">全不选</button>
              <button @click="startScreening" :disabled="screening"
                title="启发式统计 + AI 识别参数用途；近期无数据的参数会自动改用其历史数据判断，不会因此从列表消失"
                class="px-3 py-1.5 text-xs rounded-lg bg-violet-500 text-white font-bold hover:bg-violet-600 disabled:opacity-50">
                {{ screening ? '智能筛选中…' : '智能筛选' }}
              </button>
              <button @click="saveScreening" :disabled="screenSaving"
                class="px-3 py-1.5 text-xs rounded-lg bg-emerald-500 text-white font-bold hover:bg-emerald-600 disabled:opacity-50">
                {{ screenSaving ? '保存中…' : '保存筛选' }}
              </button>
            </div>
          </div>
          <p v-if="screenNote" class="text-xs mt-2 text-rose-500">{{ screenNote }}</p>
          <p v-if="screenSaveNote" class="text-xs mt-2 text-emerald-600">{{ screenSaveNote }}</p>
          <input v-model="screenFilter" placeholder="搜索参数名 / 中文名…"
            class="mt-3 w-full max-w-xs text-xs border border-gray-200 rounded-lg px-2.5 py-1.5 focus:outline-none focus:ring-2 focus:ring-amber-400" />
        </div>

        <div v-if="paramRows.length === 0" class="text-center py-16 text-gray-400 bg-white rounded-xl border border-gray-100 shadow-sm">
          <div class="text-4xl mb-3">📋</div>
          <p class="text-sm">正在加载参数列表…</p>
        </div>
        <div v-else class="bg-white rounded-xl border border-gray-100 shadow-sm overflow-hidden">
          <div class="overflow-x-auto max-h-[560px] overflow-y-auto">
            <table class="w-full text-sm">
              <thead class="bg-gray-50 sticky top-0">
                <tr class="text-left text-xs text-gray-500 border-b border-gray-200 whitespace-nowrap">
                  <th class="py-2.5 px-4 font-semibold w-10"></th>
                  <th class="py-2.5 px-3 font-semibold">参数</th>
                  <th class="py-2.5 px-3 font-semibold">分类</th>
                  <th class="py-2.5 px-3 font-semibold">说明</th>
                  <th class="py-2.5 px-3 font-semibold text-right">数据点</th>
                  <th class="py-2.5 px-3 font-semibold text-center w-16">曲线</th>
                </tr>
              </thead>
              <tbody class="divide-y divide-gray-50">
                <template v-for="row in filteredParamRows" :key="row.p_name">
                <tr class="hover:bg-gray-50/50">
                  <td class="py-2 px-4"><input type="checkbox" v-model="row.checked" class="w-3.5 h-3.5" /></td>
                  <td class="py-2 px-3 whitespace-nowrap cursor-pointer" @click="togglePreview(row.p_name)" title="点击查看最近一天曲线">
                    <div class="font-medium text-gray-800 hover:text-indigo-600">{{ displayNames[row.p_name] || row.p_name }}</div>
                    <div class="text-[10px] text-gray-300">{{ row.p_name }}<span v-if="row.unit"> · {{ row.unit }}</span></div>
                  </td>
                  <td class="py-2 px-3">
                    <span class="px-1.5 py-0.5 rounded text-[10px] font-medium whitespace-nowrap" :class="catClass(row.category)">{{ catLabel(row.category) }}</span>
                    <span v-if="row.stale" class="ml-1 px-1 py-0.5 rounded text-[10px] bg-amber-50 text-amber-500" title="最近窗口内无数据，已自动改用该参数最近一批历史数据判断">历史数据</span>
                  </td>
                  <td class="py-2 px-3 text-xs text-gray-400">{{ row.reason || '—' }}</td>
                  <td class="py-2 px-3 text-right text-xs text-gray-400 tabular-nums">{{ row.n ?? '—' }}</td>
                  <td class="py-2 px-3 text-center">
                    <button @click.stop="togglePreview(row.p_name)"
                      class="text-xs px-1.5 py-0.5 rounded hover:bg-indigo-50"
                      :class="expandedParam === row.p_name ? 'text-indigo-600 bg-indigo-50' : 'text-gray-400'"
                      :title="expandedParam === row.p_name ? '收起' : '查看最近有数据的一天曲线'">📈</button>
                  </td>
                </tr>
                <tr v-if="expandedParam === row.p_name">
                  <td colspan="6" class="px-4 py-3 bg-gray-50/60">
                    <div v-if="previewLoading === row.p_name" class="text-xs text-gray-400 py-6 text-center">⏳ 正在向前查找最近有数据的一天…</div>
                    <div v-else-if="previewErr" class="text-xs text-rose-500 py-6 text-center">{{ previewErr }}</div>
                    <div v-else-if="!(previewSeries[row.p_name] || []).length" class="text-xs text-gray-400 py-6 text-center">最近 30 天内该参数无数据</div>
                    <div v-else>
                      <div class="text-[11px] text-gray-400 mb-1">{{ displayNames[row.p_name] || row.p_name }} · {{ previewDateRanges[row.p_name]?.label || '最近 24 小时' }} · {{ (previewSeries[row.p_name] || []).length }} 个点</div>
                      <div :ref="el => setPreviewEl(el)" class="w-full" style="height: 200px"></div>
                    </div>
                  </td>
                </tr>
                </template>
              </tbody>
            </table>
          </div>
        </div>
      </div>

      <!-- Tab②：设定脉搏 —— 同样列出全部参数（单选），当前脉搏参数排在最前并打勾 -->
      <div v-else-if="activeTab === 'pulse'" class="space-y-4">
        <div class="bg-white rounded-xl border border-gray-100 shadow-sm p-4">
          <div class="flex items-center justify-between flex-wrap gap-3">
            <div class="flex items-center gap-3 flex-wrap">
              <span class="text-xs font-bold text-gray-400 uppercase tracking-wider">设定脉搏</span>
              <span v-if="pulseParam" class="text-xs text-emerald-600">当前：{{ displayNames[pulseParam] || pulseParam }}</span>
              <span v-else class="text-xs text-amber-600">尚未设置生产节拍参数</span>
            </div>
            <div class="flex items-center gap-2">
              <button @click="startPulseDiscover" :disabled="pulseDiscovering"
                title="按周期性给全部参数打分，供挑选生产节拍参数参考"
                class="px-3 py-1.5 text-xs rounded-lg bg-violet-500 text-white font-bold hover:bg-violet-600 disabled:opacity-50">
                {{ pulseDiscovering ? '识别中…' : '智能识别脉搏' }}
              </button>
              <button @click="savePulse" :disabled="!pulseParam || pulseSaving"
                class="px-3 py-1.5 text-xs bg-emerald-500 text-white rounded-lg hover:bg-emerald-600 disabled:opacity-50">
                {{ pulseSaving ? '保存中…' : '保存' }}
              </button>
            </div>
          </div>
          <div class="flex items-center gap-2 mt-3">
            <span class="text-xs text-gray-500 shrink-0">手动指定（列表里没有时）：</span>
            <input v-model="pulseParam" class="text-xs border border-gray-200 rounded-lg px-2.5 py-1.5 flex-1" placeholder="输入参数名，如 Tec_Stage" />
          </div>
          <p v-if="pulseSaveNote" class="text-xs mt-2 text-emerald-600">{{ pulseSaveNote }}</p>
          <p v-if="pulseResult && pulseResult.kb_hint" class="text-xs mt-2 bg-indigo-50 text-indigo-700 rounded-lg px-2.5 py-1.5">💡 知识库提示：{{ pulseResult.kb_hint }}</p>
          <input v-model="pulseFilter" placeholder="搜索参数名 / 中文名…"
            class="mt-3 w-full max-w-xs text-xs border border-gray-200 rounded-lg px-2.5 py-1.5 focus:outline-none focus:ring-2 focus:ring-amber-400" />
        </div>

        <div v-if="pulseDiscovering" class="text-center py-12 text-gray-400 text-sm bg-white rounded-xl border border-gray-100 shadow-sm">⏳ 分析参数周期性...</div>
        <div v-else-if="paramRows.length === 0" class="text-center py-16 text-gray-400 bg-white rounded-xl border border-gray-100 shadow-sm">
          <div class="text-4xl mb-3">💓</div>
          <p class="text-sm">正在加载参数列表…</p>
        </div>
        <div v-else class="bg-white rounded-xl border border-gray-100 shadow-sm overflow-hidden">
          <div class="px-3 py-2 text-xs text-gray-500 border-b border-gray-50">点选一个参数作为生产节拍（脉搏），周期性得分越高越适合；选中后点上方"保存"生效。</div>
          <div class="overflow-x-auto max-h-[560px] overflow-y-auto">
            <table class="w-full text-sm">
              <thead class="bg-gray-50 sticky top-0">
                <tr class="text-left text-xs text-gray-500 border-b border-gray-200 whitespace-nowrap">
                  <th class="py-2.5 px-4 font-semibold w-10"></th>
                  <th class="py-2.5 px-3 font-semibold">参数</th>
                  <th class="py-2.5 px-3 font-semibold text-right">周期性得分</th>
                  <th class="py-2.5 px-3 font-semibold">说明</th>
                  <th class="py-2.5 px-3 font-semibold text-center w-16">曲线</th>
                </tr>
              </thead>
              <tbody class="divide-y divide-gray-50">
                <template v-for="row in filteredPulseRows" :key="row.p_name">
                <tr class="hover:bg-gray-50/50 cursor-pointer"
                  :class="row.p_name === pulseParam ? 'bg-amber-50' : ''"
                  @click="pulseParam = row.p_name">
                  <td class="py-2 px-4" @click.stop="pulseParam = row.p_name">
                    <input type="radio" :checked="row.p_name === pulseParam" @change="pulseParam = row.p_name" class="w-3.5 h-3.5" />
                  </td>
                  <td class="py-2 px-3 whitespace-nowrap" @click.stop="togglePreview(row.p_name)" title="点击查看最近一天曲线">
                    <div class="font-medium text-gray-800 hover:text-indigo-600">{{ displayNames[row.p_name] || row.p_name }}</div>
                    <div class="text-[10px] text-gray-300">{{ row.p_name }}<span v-if="row.unit"> · {{ row.unit }}</span></div>
                  </td>
                  <td class="py-2 px-3 text-right text-xs tabular-nums">
                    <span v-if="row.candidate" :class="row.candidate.score >= 70 ? 'text-emerald-600 font-bold' : row.candidate.score >= 40 ? 'text-amber-500' : 'text-gray-400'">
                      {{ row.candidate.score >= 70 ? '⭐' : row.candidate.score >= 40 ? '🔶' : '○' }} {{ row.candidate.score?.toFixed(0) }}
                    </span>
                    <span v-else class="text-gray-300">—</span>
                  </td>
                  <td class="py-2 px-3 text-xs text-gray-400 truncate max-w-xs" :title="row.candidate && row.candidate.reason">
                    {{ (row.candidate && row.candidate.reason) || '—' }}<span v-if="row.candidate && row.candidate.cycle_minutes"> · ~{{ row.candidate.cycle_minutes }}min</span>
                  </td>
                  <td class="py-2 px-3 text-center">
                    <button @click.stop="togglePreview(row.p_name)"
                      class="text-xs px-1.5 py-0.5 rounded hover:bg-indigo-50"
                      :class="expandedParam === row.p_name ? 'text-indigo-600 bg-indigo-50' : 'text-gray-400'"
                      :title="expandedParam === row.p_name ? '收起' : '查看最近有数据的一天曲线'">📈</button>
                  </td>
                </tr>
                <tr v-if="expandedParam === row.p_name">
                  <td colspan="5" class="px-4 py-3 bg-gray-50/60">
                    <div v-if="previewLoading === row.p_name" class="text-xs text-gray-400 py-6 text-center">⏳ 正在向前查找最近有数据的一天…</div>
                    <div v-else-if="previewErr" class="text-xs text-rose-500 py-6 text-center">{{ previewErr }}</div>
                    <div v-else-if="!(previewSeries[row.p_name] || []).length" class="text-xs text-gray-400 py-6 text-center">最近 30 天内该参数无数据</div>
                    <div v-else>
                      <div class="text-[11px] text-gray-400 mb-1">{{ displayNames[row.p_name] || row.p_name }} · {{ previewDateRanges[row.p_name]?.label || '最近 24 小时' }} · {{ (previewSeries[row.p_name] || []).length }} 个点</div>
                      <div :ref="el => setPreviewEl(el)" class="w-full" style="height: 200px"></div>
                    </div>
                  </td>
                </tr>
                </template>
              </tbody>
            </table>
          </div>
        </div>
      </div>

      <!-- Tab③：参数画像（AI 识别参数类型/角色/正常区间/spec，工艺确认后生效）-->
      <div v-else-if="activeTab === 'profile'" class="space-y-4">
        <div class="bg-white rounded-xl border border-gray-100 shadow-sm p-4">
          <div class="flex items-center justify-between flex-wrap gap-3">
            <div class="flex items-center gap-3 flex-wrap">
              <span class="text-xs font-bold text-gray-400 uppercase tracking-wider">参数画像 · 自适应</span>
              <span class="inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded bg-emerald-50 text-emerald-600 font-bold">已确认 {{ profileConfirmedCount }}</span>
              <span class="inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded bg-amber-50 text-amber-600">待确认 {{ visibleProfileRows.length - profileConfirmedCount }}</span>
              <span v-if="hiddenProfileCount > 0" class="text-xs text-gray-400" title="只展示「参数筛选」里勾选的参数">已按筛选隐藏 {{ hiddenProfileCount }} 个</span>
              <label class="flex items-center gap-1 text-xs text-gray-500">
                <input type="checkbox" v-model="profileUseLlm" class="w-3.5 h-3.5" /> 用 AI 提语义
              </label>
            </div>
            <div class="flex items-center gap-2">
              <button @click="loadProfile" :disabled="profileLoading"
                class="px-3 py-1.5 text-xs rounded-lg bg-gray-50 text-gray-600 border border-gray-200 hover:bg-gray-100 disabled:opacity-50">刷新</button>
              <button @click="runSuggest" :disabled="profileSuggesting"
                title="对设备全部参数自动识别类型/角色/正常区间(写为待确认建议)；下方表格只展示「参数筛选」勾选的参数"
                class="px-3 py-1.5 text-xs rounded-lg bg-violet-500 text-white font-bold hover:bg-violet-600 disabled:opacity-50">
                {{ profileSuggesting ? 'AI 识别中…' : 'AI 识别' }}
              </button>
            </div>
          </div>
          <p v-if="profileNote" class="text-xs mt-2" :class="profileNoteErr ? 'text-rose-500' : 'text-amber-600'">{{ profileNote }}</p>
          <p class="text-[11px] text-gray-300 mt-2">类型由统计签名(无名也能判)+DB type+AI 综合给出"建议"；正常区间从历史精确学习；Cpk 用确认的 spec。高风险阈值须确认后生效。</p>
        </div>

        <div v-if="visibleProfileRows.length > 0" class="bg-white rounded-xl border border-gray-100 shadow-sm overflow-hidden">
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
                <tr v-for="row in visibleProfileRows" :key="row.p_name" class="hover:bg-gray-50/50 align-top">
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
          <p v-if="profileRows.length > 0" class="text-sm">
            已有 {{ profileRows.length }} 条画像，但都不在「参数筛选」勾选范围内。请到①参数筛选勾选需要的参数后再回来查看。
          </p>
          <p v-else class="text-sm">尚无参数画像。点「AI 识别」让系统自动识别该设备所有参数的类型与正常区间。</p>
        </div>
      </div>
    </template>

    <div v-else class="text-center py-16 text-gray-400 bg-white rounded-xl border border-gray-100 shadow-sm">
      <div class="text-4xl mb-3">🔧</div>
      <p class="text-sm">请从上方选择设备</p>
    </div>

    <!-- 自动设置上下限 参数配置弹窗 -->
    <Teleport to="body">
      <div v-if="specDialogVisible" class="fixed inset-0 z-50 flex items-center justify-center p-4" @click.self="specDialogVisible = false">
        <div class="absolute inset-0 bg-black/40"></div>
        <div class="relative bg-white rounded-2xl shadow-2xl w-full max-w-sm">
          <div class="flex items-center justify-between px-5 py-3 border-b border-gray-100">
            <h3 class="text-base font-bold text-gray-900">自动设置上下限</h3>
            <button @click="specDialogVisible = false" class="text-gray-400 hover:text-gray-600 text-lg leading-none">✕</button>
          </div>
          <div class="px-5 py-4 space-y-3">
            <div>
              <label class="block text-xs text-gray-500 mb-1">中位数过滤范围（剔除离群数据）</label>
              <div class="flex items-center gap-2">
                <span class="text-xs text-gray-400">下限 -</span>
                <input v-model.number="specDialogRow._median_low_pct" type="number" step="1" min="1" max="50" class="w-16 text-sm border border-gray-200 rounded-lg px-2 py-1.5" />
                <span class="text-xs text-gray-400">%</span>
                <span class="text-xs text-gray-400 mx-1">上限 +</span>
                <input v-model.number="specDialogRow._median_high_pct" type="number" step="1" min="1" max="50" class="w-16 text-sm border border-gray-200 rounded-lg px-2 py-1.5" />
                <span class="text-xs text-gray-400">%</span>
              </div>
            </div>
            <div>
              <label class="block text-xs text-gray-500 mb-1">CPK 目标</label>
              <input v-model.number="specDialogRow._cpk_target" type="number" step="0.1" min="0.5" max="3" class="w-20 text-sm border border-gray-200 rounded-lg px-2 py-1.5" />
            </div>
          </div>
          <div class="flex items-center justify-end gap-2 px-5 py-3 border-t border-gray-100">
            <button @click="specDialogVisible = false" class="px-4 py-2 text-sm bg-gray-100 rounded-lg hover:bg-gray-200">取消</button>
            <button @click="doRecalcSpec" class="px-4 py-2 text-sm bg-indigo-500 text-white rounded-lg hover:bg-indigo-600">开始计算</button>
          </div>
        </div>
      </div>
    </Teleport>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted, nextTick } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import * as echarts from 'echarts'
import client from '../api/client.js'
import {
  getDeviceParamDevices,
  getDeviceParamData,
  getDeviceParamPoints,
  getParamProfile,
  suggestParamProfile,
  saveParamProfile,
  getCpk,
  recalcSpecLimits,
  recalcCpk,
} from '../api/client.js'

const route = useRoute()
const router = useRouter()

const devices = ref([])
const selectedDevice = ref('')
const displayNames = ref({})   // p_name code -> Chinese display name

const TABS = [
  { key: 'screen', label: '参数筛选', icon: '🔍' },
  { key: 'pulse', label: '设定脉搏', icon: '💓' },
  { key: 'profile', label: '参数画像', icon: '🧬' },
]
const activeTab = ref('screen')

// ── Tab①参数筛选：始终列出该设备定义的全部参数，checked 由人工/AI 共同决定 ──
const paramRows = ref([])      // [{p_name, unit, checked, category, reason, n, stale, last_seen}]
const screenDays = ref(1)
const screening = ref(false)
const screenSaving = ref(false)
const screenNote = ref('')
const screenSaveNote = ref('')
const screenSummary = ref('')
const screenFilter = ref('')
// 已保存设定的加载结果提示：区分"没存过"和"读取失败"，避免静默失败让人误以为数据丢了
const stateLoadNote = ref('')
const stateLoadErr = ref(false)
const checkedParams = computed(() => paramRows.value.filter(r => r.checked).map(r => r.p_name))
const filteredParamRows = computed(() => {
  const q = screenFilter.value.trim().toLowerCase()
  if (!q) return paramRows.value
  return paramRows.value.filter(r =>
    r.p_name.toLowerCase().includes(q) || (displayNames.value[r.p_name] || '').toLowerCase().includes(q))
})

// ── Tab②设定脉搏：复用同一份 paramRows 全参数列表，单选（radio），当前脉搏参数排最前 ──
const pulseDiscovering = ref(false)
const pulseResult = ref(null)
const pulseParam = ref('')
const pulseSaving = ref(false)
const pulseSaveNote = ref('')
const pulseFilter = ref('')
const pulseRows = computed(() => {
  const scoreMap = {}
  if (pulseResult.value && pulseResult.value.candidates) {
    for (const c of pulseResult.value.candidates) scoreMap[c.p_name] = c
  }
  const rows = paramRows.value.map(r => ({ p_name: r.p_name, unit: r.unit, candidate: scoreMap[r.p_name] || null }))
  rows.sort((a, b) => {
    const aSel = a.p_name === pulseParam.value
    const bSel = b.p_name === pulseParam.value
    if (aSel !== bSel) return aSel ? -1 : 1
    const as = a.candidate ? a.candidate.score : -1
    const bs = b.candidate ? b.candidate.score : -1
    return bs - as
  })
  return rows
})
const filteredPulseRows = computed(() => {
  const q = pulseFilter.value.trim().toLowerCase()
  if (!q) return pulseRows.value
  return pulseRows.value.filter(r =>
    r.p_name.toLowerCase().includes(q) || (displayNames.value[r.p_name] || '').toLowerCase().includes(q))
})

function catLabel(cat) {
  const m = { predictive: '预测维护', quality: '质量管理', management: '经营管理', useless: '无用', nodata: '无数据' }
  return m[cat] || (cat ? cat : '未筛选')
}
function catClass(cat) {
  const m = { predictive: 'bg-blue-50 text-blue-600', quality: 'bg-emerald-50 text-emerald-600',
              management: 'bg-amber-50 text-amber-600', useless: 'bg-gray-100 text-gray-400',
              nodata: 'bg-rose-50 text-rose-400' }
  return m[cat] || 'bg-gray-50 text-gray-300'
}

function fmtNum(v, digits = 2) {
  if (v == null || isNaN(v)) return '—'
  return Number(v).toFixed(digits).replace(/\.?0+$/, '') || '0'
}
function cpkCls(v) {
  if (v == null) return 'text-gray-300'
  if (v < 1) return 'text-rose-500'
  if (v < 1.33) return 'text-amber-500'
  return 'text-emerald-600'
}

async function loadDevices() {
  try {
    const res = await getDeviceParamDevices()
    if (res.code === 200 && res.data) devices.value = res.data
  } catch (err) {
    console.error('加载设备列表失败:', err)
  }
}

function currentDeviceName() {
  const d = devices.value.find(d => d.device_code === selectedDevice.value)
  return d ? d.device_name || d.device_code : selectedDevice.value
}

// 拉取该设备全部参数定义（不依赖是否有数据），作为筛选列表的基础
async function loadPointNames() {
  if (!selectedDevice.value) return
  try {
    const res = await getDeviceParamPoints(selectedDevice.value)
    if (res.code === 200 && res.data) {
      const dn = {}
      const rows = []
      for (const p of res.data) {
        dn[p.p_name] = p.display_name || p.p_name
        rows.push({
          p_name: p.p_name, unit: p.unit || '', checked: false,
          category: null, reason: '', n: null, stale: false, last_seen: null,
        })
      }
      displayNames.value = dn
      paramRows.value = rows
    }
  } catch (err) {
    console.error('加载参数点位失败:', err)
  }
}

// 把 classified（AI/启发式识别结果）合并进 paramRows；useSuggestedChecked=true 时采用 AI 建议的勾选状态，
// 否则（从数据库恢复时）保留原勾选状态，勾选状态改由 checked_params 列表决定
function applyClassifiedToRows(classified, useSuggestedChecked) {
  const classMap = {}
  for (const c of (classified || [])) classMap[c.p_name] = c
  for (const row of paramRows.value) {
    const c = classMap[row.p_name]
    if (!c) continue
    row.category = c.category
    row.reason = c.reason
    row.n = c.n
    row.stale = !!c.stale
    row.last_seen = c.last_seen ?? null
    if (useSuggestedChecked) row.checked = !!c.checked
  }
  // classified 里可能有点位表还没同步到的参数，照样展示出来，不因为定义表滞后而漏掉
  const known = new Set(paramRows.value.map(r => r.p_name))
  for (const c of (classified || [])) {
    if (!known.has(c.p_name)) {
      paramRows.value.push({
        p_name: c.p_name, unit: '', checked: !!c.checked,
        category: c.category, reason: c.reason, n: c.n, stale: !!c.stale, last_seen: c.last_seen ?? null,
      })
      known.add(c.p_name)
    }
  }
}

function applyCheckedList(checkedList) {
  if (!checkedList || !checkedList.length) return
  const set = new Set(checkedList)
  for (const row of paramRows.value) row.checked = set.has(row.p_name)
}

// 保证 checked_params / pulse_param 里提到的参数一定在列表里有一行——哪怕参数定义表
// (dev_device_param) 还没同步、或 classified 因某些原因是空的，也不会出现"明明已经
// 筛选/设脉搏过了，但列表里什么都没有"的情况
function ensureRowsForPNames(pNames) {
  if (!pNames || !pNames.length) return
  const known = new Set(paramRows.value.map(r => r.p_name))
  for (const p of pNames) {
    if (!known.has(p)) {
      paramRows.value.push({ p_name: p, unit: '', checked: false, category: null, reason: '', n: null, stale: false, last_seen: null })
      known.add(p)
    }
  }
}

// 已勾选/已确认的参数排到列表最前面，方便一眼看到之前筛选的结果
function sortRowsCheckedFirst() {
  paramRows.value = [...paramRows.value].sort((a, b) => (b.checked ? 1 : 0) - (a.checked ? 1 : 0))
}

// ── 参数曲线预览（最近 1 天）：筛选/脉搏 两个 tab 共用，同时只展开一个 ──
const expandedParam = ref('')
const previewLoading = ref('')
const previewErr = ref('')
const previewSeries = ref({})   // p_name -> [[tsMs, value], ...]
const previewDateRanges = ref({}) // p_name -> { start, end, label, offsetDays }
let previewEl = null
let previewChart = null

function setPreviewEl(el) {
  previewEl = el
  if (!el) disposePreview()
}

function disposePreview() {
  if (previewChart && !previewChart.isDisposed()) previewChart.dispose()
  previewChart = null
}

function _fmtApi(d) {
  const pad = (n) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:00`
}

function _fmtRangeLabel(start, end, offsetDays) {
  const pad = (n) => String(n).padStart(2, '0')
  const fmt = (d) => `${d.getMonth() + 1}/${pad(d.getDate())}`
  if (offsetDays === 0) return `最近 24 小时（${fmt(start)} - ${fmt(end)}）`
  return `${offsetDays}天前·24小时（${fmt(start)} - ${fmt(end)}）`
}

async function togglePreview(pName) {
  if (expandedParam.value === pName) {
    expandedParam.value = ''
    disposePreview()
    return
  }
  disposePreview()
  expandedParam.value = pName
  if (!previewSeries.value[pName]) await loadPreview(pName)
  await nextTick()
  renderPreview(pName)
}

async function loadPreview(pName) {
  previewLoading.value = pName
  previewErr.value = ''
  const MAX_LOOKBACK_DAYS = 30 // 最多往前找 30 天
  try {
    const now = new Date()
    let foundData = null
    let foundStart = null
    let foundEnd = null
    let foundOffset = 0

    for (let offsetDays = 0; offsetDays < MAX_LOOKBACK_DAYS; offsetDays++) {
      const end = new Date(now.getTime() - offsetDays * 24 * 3600 * 1000)
      const start = new Date(end.getTime() - 24 * 3600 * 1000)
      const res = await getDeviceParamData({
        device_code: selectedDevice.value,
        start_time: _fmtApi(start),
        end_time: _fmtApi(end),
        limit: 20000,
        interval: 'auto',
        p_names: [pName],
      })
      if (res.code === 200 && res.data?.series) {
        const pts = res.data.series[pName] || []
        if (pts.length > 0) {
          foundData = pts
          foundStart = start
          foundEnd = end
          foundOffset = offsetDays
          break
        }
      } else {
        previewErr.value = res.msg || '加载失败'
        break
      }
    }

    if (foundData !== null) {
      const mappedPts = foundData.map(pt => {
        const t = new Date(String(pt.time).includes('T') ? pt.time : String(pt.time).replace(' ', 'T')).getTime()
        const v = typeof pt.value === 'number' ? pt.value : parseFloat(pt.value)
        return [t, v]
      }).filter(([t, v]) => !isNaN(t) && !isNaN(v))
      previewSeries.value = {
        ...previewSeries.value,
        [pName]: mappedPts,
      }
      previewDateRanges.value = {
        ...previewDateRanges.value,
        [pName]: {
          start: foundStart,
          end: foundEnd,
          label: _fmtRangeLabel(foundStart, foundEnd, foundOffset),
          offsetDays: foundOffset,
        },
      }
    }
  } catch (e) {
    previewErr.value = '加载失败：' + (e?.message || '请求异常')
  } finally {
    previewLoading.value = ''
  }
}

function renderPreview(pName) {
  const data = previewSeries.value[pName]
  if (!previewEl || !data || data.length === 0) return
  if (!previewChart || previewChart.isDisposed()) previewChart = echarts.init(previewEl)
  previewChart.setOption({
    animation: false,
    grid: { left: 52, right: 16, top: 16, bottom: 24 },
    tooltip: { trigger: 'axis', confine: true },
    xAxis: { type: 'time', axisLabel: { fontSize: 10, hideOverlap: true } },
    yAxis: { type: 'value', scale: true, axisLabel: { fontSize: 10 } },
    series: [{
      name: displayNames.value[pName] || pName,
      type: 'line', showSymbol: false, sampling: 'lttb',
      lineStyle: { width: 1.2 }, itemStyle: { color: '#6366f1' }, data,
    }],
  }, true)
  previewChart.resize()
}

function toggleAll(check) {
  for (const row of paramRows.value) row.checked = check
}

async function loadScreenStateFromDb() {
  stateLoadNote.value = ''
  stateLoadErr.value = false
  try {
    const r = await client.get('/device-params/screen-state', { params: { device_code: selectedDevice.value } })
    if (r.code !== 200) {
      stateLoadErr.value = true
      stateLoadNote.value = `读取已保存设定失败：${r.msg || '接口返回异常'}`
      return
    }
    const saved = r.data || {}
    if (saved.pulse_param) pulseParam.value = saved.pulse_param
    applyClassifiedToRows(saved.classified, false)
    ensureRowsForPNames(saved.checked_params)
    if (saved.pulse_param) ensureRowsForPNames([saved.pulse_param])
    applyCheckedList(saved.checked_params)
    sortRowsCheckedFirst()

    const parts = []
    if (saved.checked_params?.length) parts.push(`已筛选 ${saved.checked_params.length} 个参数`)
    if (saved.pulse_param) parts.push(`脉搏 ${displayNames.value[saved.pulse_param] || saved.pulse_param}`)
    stateLoadNote.value = parts.length
      ? `已加载保存的设定：${parts.join(' · ')}`
      : '该设备尚未保存过筛选/脉搏，请勾选参数或点「智能筛选」后「保存」。（空白＝未筛选任何参数，监控页不会显示数据）'
  } catch (e) {
    stateLoadErr.value = true
    stateLoadNote.value = `读取已保存设定失败：${e?.message || '请求异常'}`
  }
}

function onDeviceChange() {
  // 同步设备选择到 URL，刷新/返回时不会丢失设备上下文
  router.replace({ query: { device: selectedDevice.value || undefined } })
  activeTab.value = 'screen'
  paramRows.value = []
  displayNames.value = {}
  pulseParam.value = ''
  pulseResult.value = null
  pulseFilter.value = ''
  screenSummary.value = ''
  screenNote.value = ''
  screenSaveNote.value = ''
  pulseSaveNote.value = ''
  stateLoadNote.value = ''
  stateLoadErr.value = false
  expandedParam.value = ''
  previewSeries.value = {}
  previewDateRanges.value = {}
  previewErr.value = ''
  disposePreview()
  profileRows.value = []
  profileNote.value = ''
  if (selectedDevice.value) {
    loadPointNames().then(() => loadScreenStateFromDb())
    loadProfile()
  }
}

function goToAnalysis() {
  router.push({ path: '/device-params', query: { device: selectedDevice.value } })
}

// 把当前 paramRows 状态整理成后端 screen-state 需要的 payload；两个 tab 的保存
// 都带上完整的 classified + checked_params + pulse_param，避免互相覆盖对方的数据
function persistScreenState(step) {
  const payload = {
    device_code: selectedDevice.value,
    workflow_step: step,
    pulse_param: pulseParam.value || null,
  }
  // 已保存设定读取失败时，界面上的勾选只是"默认全选"，不能拿它覆盖库里真实的筛选结果
  // （后端对未传字段保留原值）
  if (!stateLoadErr.value) {
    payload.classified = paramRows.value.map(r => ({
      p_name: r.p_name, category: r.category, reason: r.reason,
      checked: r.checked, n: r.n, stale: r.stale, last_seen: r.last_seen,
    }))
    payload.checked_params = checkedParams.value
  }
  return client.post('/device-params/screen-state', payload).then(res => {
    if (res.code !== 200) throw new Error(res.msg || res.detail || '保存失败')
    return res
  })
}

// ── Tab① 参数筛选 ──
async function startScreening() {
  if (!selectedDevice.value || screening.value) return
  screening.value = true
  screenNote.value = ''
  try {
    const res = await client.post('/device-params/screen-params', {
      device_code: selectedDevice.value, device_name: currentDeviceName(), days: screenDays.value,
    }, { timeout: 0 })
    if (res.code === 200 && res.data) {
      applyClassifiedToRows(res.data.classified, true)
      sortRowsCheckedFirst()
      screenSummary.value = res.data.summary || ''
    } else {
      screenNote.value = res.msg || res.detail || '智能筛选失败'
    }
  } catch (err) {
    screenNote.value = '智能筛选失败: ' + (err.response?.data?.msg || err.response?.data?.detail || err.message)
  } finally {
    screening.value = false
  }
}

async function saveScreening() {
  // 读取失败时 persistScreenState 会跳过 checked_params，保存下去等于什么都没存，
  // 必须先让用户重新加载，否则会得到"提示已保存但其实没存"的假象
  if (stateLoadErr.value) {
    screenNote.value = '已保存设定读取失败，请先切换设备或刷新页面重新加载，再保存筛选'
    return
  }
  screenSaving.value = true
  screenSaveNote.value = ''
  try {
    await persistScreenState(2)
    screenSaveNote.value = `已保存，共 ${checkedParams.value.length} 个参数`
    stateLoadNote.value = ''
  } catch (err) {
    screenSaveNote.value = '保存失败：' + (err?.message || '请求异常')
  } finally {
    screenSaving.value = false
  }
}

// ── Tab② 设定脉搏 ──
async function startPulseDiscover() {
  if (!selectedDevice.value) return
  pulseDiscovering.value = true
  pulseResult.value = { source: 'loading', candidates: [] }
  try {
    const res = await client.post('/device-params/pulse-discover', {
      device_code: selectedDevice.value, device_name: currentDeviceName(), days: 7,
    }, { timeout: 0 })
    if (res.code === 200 && res.data) {
      pulseResult.value = res.data
    } else {
      pulseResult.value = null
    }
  } catch (err) {
    pulseResult.value = null
  } finally {
    pulseDiscovering.value = false
  }
}

async function savePulse() {
  if (!pulseParam.value) return
  pulseSaving.value = true
  pulseSaveNote.value = ''
  try {
    await persistScreenState(3)
    pulseSaveNote.value = '已保存'
    stateLoadNote.value = ''
  } catch (err) {
    pulseSaveNote.value = '保存失败：' + (err?.message || '请求异常')
  } finally {
    pulseSaving.value = false
  }
}

// ── Tab③ 参数画像 ──
const PTYPES = ['continuous', 'state', 'counter', 'switch', 'setpoint', 'enum', 'unknown']
const profileRows = ref([])
const profileLoading = ref(false)
const profileSuggesting = ref(false)
const profileUseLlm = ref(true)
const profileNote = ref('')
const profileNoteErr = ref(false)
// 画像表只展示「参数筛选」勾选的参数。paramRows 尚未加载完(切设备瞬间)时不过滤，
// 否则会闪一下空表；加载完之后严格按勾选过滤，与参数分析页的口径保持一致。
const visibleProfileRows = computed(() => {
  if (!paramRows.value.length) return profileRows.value
  const set = new Set(checkedParams.value)
  return profileRows.value.filter(r => set.has(r.p_name))
})
const hiddenProfileCount = computed(() => profileRows.value.length - visibleProfileRows.value.length)
const profileConfirmedCount = computed(() => visibleProfileRows.value.filter(r => r.confirmed).length)
const specDialogVisible = ref(false)
const specDialogRow = ref(null)

// 中位数过滤上下限比例 + CPK目标值的默认值：来自后端 config/cpk_recalc_config.yaml
const cpkConfigDefaults = ref({ median_filter_low_pct: 15, median_filter_high_pct: 15, cpk_target: 1.33 })
let cpkConfigLoaded = false
async function loadCpkConfigDefaults() {
  if (cpkConfigLoaded) return
  cpkConfigLoaded = true
  try {
    const res = await client.get('/device-params/profile/cpk-config')
    if (res.code === 200 && res.data) {
      cpkConfigDefaults.value = {
        median_filter_low_pct: Math.round((res.data.median_filter_low_pct ?? 0.15) * 100),
        median_filter_high_pct: Math.round((res.data.median_filter_high_pct ?? 0.15) * 100),
        cpk_target: res.data.cpk_target ?? 1.33,
      }
    }
  } catch {}
}

function _toProfileRow(p) {
  const bands = p.bands || {}
  return {
    ...p, bands, monitor: !!p.monitor,
    _spec_low: bands.spec_low ?? null,
    _spec_high: bands.spec_high ?? null,
    _cpk: null, _saving: false, _recalc: false, _recalc_result: null,
    _recalcCpk: false, _recalcCpkResult: null,
    _median_low_pct: cpkConfigDefaults.value.median_filter_low_pct,
    _median_high_pct: cpkConfigDefaults.value.median_filter_high_pct,
    _cpk_target: cpkConfigDefaults.value.cpk_target,
  }
}

async function loadProfile() {
  if (!selectedDevice.value) return
  profileLoading.value = true
  profileNote.value = ''
  profileNoteErr.value = false
  try {
    await loadCpkConfigDefaults()
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

async function confirmRow(row) {
  if (row._saving) return
  row._saving = true
  // 组装回 profile：编辑的 spec 写回 bands（标记为工程规格）
  const profile = { ...row }
  for (const k of ['_spec_low', '_spec_high', '_cpk', '_saving', 'confirmed', 'updated_by',
                   '_recalc', '_recalc_result', '_recalcCpk', '_recalcCpkResult',
                   '_median_low_pct', '_median_high_pct', '_cpk_target']) {
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
  specDialogRow.value = row
  specDialogVisible.value = true
}

async function doRecalcSpec() {
  const row = specDialogRow.value
  if (!row) return
  row._recalc = true
  specDialogVisible.value = false
  try {
    const res = await recalcSpecLimits({
      device_code: selectedDevice.value, p_name: row.p_name,
      cpk_target: row._cpk_target || 1.33,
      median_filter_low_pct: (row._median_low_pct || 15) / 100,
      median_filter_high_pct: (row._median_high_pct || 15) / 100,
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

onUnmounted(() => {
  disposePreview()
})

onMounted(() => {
  loadDevices()
  const deviceFromQuery = route.query.device
  if (deviceFromQuery) {
    selectedDevice.value = deviceFromQuery
    onDeviceChange()
  }
})
</script>
