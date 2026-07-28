<template>
  <div class="space-y-5">
    <!-- Controls -->
    <div class="bg-white rounded-xl border border-gray-100 shadow-sm p-4 flex flex-wrap items-end gap-4">
      <div>
        <label class="block text-xs font-bold text-gray-500 uppercase tracking-widest mb-2">回溯范围</label>
        <div class="flex items-center gap-1 bg-gray-100 rounded-lg p-0.5">
          <button v-for="d in DAY_OPTIONS" :key="d.v" @click="days = d.v; load()"
            class="px-3 py-1.5 text-xs rounded-md transition-colors"
            :class="days === d.v ? 'bg-white text-gray-900 font-bold shadow-sm' : 'text-gray-500 hover:text-gray-700'">
            {{ d.label }}
          </button>
        </div>
      </div>
      <button @click="load" :disabled="loading || !deviceCode"
        class="px-5 py-2 bg-amber-400 text-on-primary-container text-sm font-bold rounded-lg hover:bg-amber-500 transition-colors disabled:opacity-50">
        {{ loading ? '分析中...' : '刷新' }}
      </button>

      <!-- 按阶段 / 按状态：决定"固定哪个单元跨周期对比" -->
      <div>
        <span class="block text-[10px] text-gray-400 mb-1">对比粒度</span>
        <div class="flex items-center gap-1 bg-gray-100 rounded-lg p-0.5">
          <button @click="setLevel('stage')" class="px-3 py-1.5 text-xs rounded-md transition-colors"
            :class="level === 'stage' ? 'bg-white text-gray-900 font-bold shadow-sm' : 'text-gray-500'">按阶段</button>
          <button @click="setLevel('state')" class="px-3 py-1.5 text-xs rounded-md transition-colors"
            :class="level === 'state' ? 'bg-white text-gray-900 font-bold shadow-sm' : 'text-gray-500'">按状态</button>
        </div>
      </div>

      <button v-if="data" @click="openEditor"
        class="px-3 py-1.5 text-xs rounded-lg border border-gray-200 text-gray-600 hover:border-gray-300 hover:bg-gray-50 transition-colors">
        ⚙ 编辑状态分组
      </button>

      <div class="flex items-center gap-1 ml-auto bg-gray-100 rounded-lg p-0.5">
        <button @click="metric = 'mean'" class="px-3 py-1.5 text-xs rounded-md transition-colors"
          :class="metric === 'mean' ? 'bg-white text-gray-900 font-bold shadow-sm' : 'text-gray-500'">段内均值</button>
        <button @click="metric = 'delta'" class="px-3 py-1.5 text-xs rounded-md transition-colors"
          :class="metric === 'delta' ? 'bg-white text-gray-900 font-bold shadow-sm' : 'text-gray-500'">段内变化Δ</button>
      </div>
    </div>

    <!-- States -->
    <div v-if="loading" class="text-center py-16 text-gray-400 bg-white rounded-xl border border-gray-100 shadow-sm">
      <div class="text-3xl mb-3 animate-spin">⏳</div><p>正在按阶段拆分参数...</p>
    </div>
    <div v-else-if="errMsg" class="bg-amber-50 border border-amber-200 rounded-xl p-4 text-sm text-amber-700">⚠ {{ errMsg }}</div>

    <template v-else-if="data">
      <!-- Summary -->
      <div class="bg-white rounded-xl border border-gray-100 shadow-sm p-4 flex flex-wrap items-center gap-x-6 gap-y-2 text-sm">
        <div><span class="text-gray-400">阶段参数</span>
          <span class="font-bold text-gray-800 ml-1">{{ data.stage_param.display_name }}</span>
          <span class="text-gray-400 ml-1">({{ data.stage_param.p_name }})</span></div>
        <div><span class="text-gray-400">周期数</span>
          <span class="font-bold ml-1" :class="enoughCycles ? 'text-gray-800' : 'text-rose-500'">{{ data.window.batch_count }}</span></div>
        <div><span class="text-gray-400">单周期(中位)≈</span><span class="font-bold text-gray-800 ml-1">{{ cycleText }}</span></div>
        <div class="text-xs text-gray-400">窗口 {{ data.window.days }} 天<span v-if="data.window.auto_extended" class="text-amber-600 ml-1">(已自动扩到 ≥{{ data.window.min_cycles }} 周期)</span></div>
        <div class="text-xs text-gray-400 ml-auto">{{ data.window.start.slice(5,16) }} ~ {{ data.window.end.slice(5,16) }}</div>
      </div>
      <div v-if="!enoughCycles" class="bg-amber-50 border border-amber-200 rounded-xl p-3 text-xs text-amber-700 -mt-2">
        ⚠ 窗口内只有 {{ data.window.batch_count }} 个周期，不足以稳定对比，请加大"回溯范围"。
      </div>

      <!-- 状态分组说明 -->
      <div v-if="level === 'state' && data.state_map.length" class="text-xs text-gray-400 px-1 -mt-2">
        状态分组
        <span class="ml-1 px-1.5 py-0.5 rounded text-[10px]"
          :class="data.state_map_is_default ? 'bg-gray-100 text-gray-500' : 'bg-emerald-50 text-emerald-600'">
          {{ data.state_map_is_default ? '默认·未保存' : '工艺已自定义' }}
        </span>：
        <span v-for="(g, i) in data.state_map" :key="g.state">
          <span class="text-gray-600 font-medium">{{ g.state }}</span>=阶段{{ rangeText(g.codes) }}<span v-if="i < data.state_map.length - 1"> · </span>
        </span>
        <span class="text-amber-600 ml-1">（状态是对阶段码的归并，可点"编辑状态分组"调整）</span>
      </div>

      <!-- 状态分组编辑器 -->
      <div v-if="editing" class="bg-white rounded-xl border-2 border-amber-200 shadow-sm p-4 space-y-4">
        <div class="flex items-center justify-between">
          <div class="text-sm font-bold text-gray-700">编辑状态分组 <span class="text-xs font-normal text-gray-400 ml-1">把每个阶段码归到一个状态；未分配的码归为"其他"</span></div>
          <div class="flex items-center gap-2">
            <button @click="saveConfig" :disabled="saving"
              class="px-4 py-1.5 bg-emerald-500 text-white text-xs font-bold rounded-lg hover:bg-emerald-600 disabled:opacity-50">
              {{ saving ? '保存中...' : '保存' }}
            </button>
            <button @click="editing = false" class="px-3 py-1.5 text-xs text-gray-500 rounded-lg border border-gray-200 hover:bg-gray-50">取消</button>
          </div>
        </div>
        <div>
          <div class="text-xs text-gray-400 mb-1.5">状态（可改名、删除、新增）</div>
          <div class="flex flex-wrap items-center gap-2">
            <div v-for="s in editStates" :key="s.id" class="flex items-center gap-1 bg-gray-50 border border-gray-200 rounded-lg pl-2 pr-1 py-1">
              <input v-model="s.name" class="w-20 text-xs bg-transparent focus:outline-none text-gray-700" />
              <button @click="deleteState(s.id)" class="text-gray-300 hover:text-rose-500 text-sm leading-none px-1">×</button>
            </div>
            <div class="flex items-center gap-1">
              <input v-model="newStateName" @keyup.enter="addState" placeholder="新状态名"
                class="w-24 text-xs px-2 py-1.5 border border-gray-200 rounded-lg focus:outline-none focus:ring-1 focus:ring-amber-400" />
              <button @click="addState" class="px-2 py-1.5 text-xs bg-gray-100 rounded-lg hover:bg-gray-200">+ 添加</button>
            </div>
          </div>
        </div>
        <div>
          <div class="text-xs text-gray-400 mb-1.5">阶段码归属</div>
          <div class="flex flex-wrap gap-2">
            <div v-for="code in availableCodes" :key="code" class="flex items-center gap-1 border border-gray-200 rounded-lg px-2 py-1">
              <span class="text-xs font-bold text-gray-700 w-5 text-center">{{ code }}</span>
              <select v-model="editAssign[code]" class="text-xs bg-transparent border-0 focus:outline-none text-gray-600 max-w-[88px]">
                <option :value="null">（未分配）</option>
                <option v-for="s in editStates" :key="s.id" :value="s.id">{{ s.name }}</option>
              </select>
            </div>
          </div>
        </div>
        <div v-if="editErr" class="text-xs text-rose-500">{{ editErr }}</div>
      </div>

      <!-- 周期·阶段排列图：每行一个周期，段长=该阶段实际耗时 -->
      <div v-if="data.batches?.length" class="bg-white rounded-xl border border-gray-100 shadow-sm p-4 space-y-2">
        <div class="flex flex-wrap items-baseline gap-x-3 gap-y-1">
          <span class="text-xs font-bold text-gray-400 uppercase tracking-wider">周期·阶段排列</span>
          <span class="text-xs text-gray-400">每行一个周期(按时间从上到下)，色块={{ unitLabel }}，长度=实际耗时(min)；行尾标注为该周期总时长</span>
        </div>
        <div class="flex flex-wrap items-center gap-x-3 gap-y-1">
          <span v-for="it in ganttLegend" :key="it.key"
            @click="toggleGanttLegend(it.key)"
            class="inline-flex items-center gap-1 text-[11px] cursor-pointer select-none transition-opacity"
            :class="hiddenKeys.includes(it.key) ? 'text-gray-300' : 'text-gray-500 hover:text-gray-800'">
            <span class="w-2.5 h-2.5 rounded-sm transition-opacity" :style="{ backgroundColor: it.color, opacity: hiddenKeys.includes(it.key) ? 0.25 : 1 }"></span>{{ it.label }}
          </span>
        </div>
        <div ref="ganttEl" :style="{ height: ganttHeight + 'px' }"></div>
      </div>

      <!-- Param selector -->
      <div class="bg-white rounded-xl border border-gray-100 shadow-sm p-4">
        <div class="flex flex-wrap items-center gap-1.5">
          <span class="text-xs text-gray-400 mr-1">显示参数:</span>
          <button v-for="(p, idx) in data.params" :key="p.p_name" @click="toggleParam(p.p_name)"
            class="inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-xs font-medium border transition-all"
            :class="selectedParams.includes(p.p_name) ? 'text-white border-transparent' : 'bg-gray-50 text-gray-400 border-gray-200 hover:border-gray-300'"
            :style="selectedParams.includes(p.p_name) ? { backgroundColor: COLORS[idx % COLORS.length], borderColor: COLORS[idx % COLORS.length] } : {}">
            <span class="w-2 h-2 rounded-full" :style="{ backgroundColor: selectedParams.includes(p.p_name) ? '#fff' : COLORS[idx % COLORS.length] }"></span>
            {{ pdisp(p.p_name) }}<span v-if="p.unit" class="opacity-60 ml-0.5">{{ p.unit }}</span>
          </button>
        </div>
      </div>

      <!-- 配方总览表（跨周期平均，点行=选它做跨周期对比）-->
      <div class="bg-white rounded-xl border border-gray-100 shadow-sm p-4 overflow-x-auto">
        <div class="text-xs font-bold text-gray-400 uppercase tracking-wider mb-3">
          配方总览 · 跨 {{ data.window.batch_count }} 周期 · 时长=各周期的<span class="text-amber-600">中位数</span> ·
          参数=各周期{{ metric === 'mean' ? '段内均值' : '段内变化Δ' }}的<span class="text-amber-600">平均值</span> ·
          点某行 → 看该{{ unitLabel }}逐周期对比
        </div>
        <table class="w-full text-sm border-collapse">
          <thead>
            <tr class="text-left text-xs text-gray-500 border-b border-gray-200">
              <th class="py-2 px-2 font-semibold">{{ level === 'state' ? '状态' : '阶段码' }}</th>
              <th class="py-2 px-2 font-semibold">{{ level === 'state' ? '阶段码' : '工序推测' }}</th>
              <th class="py-2 px-2 font-semibold text-right">时长中位(min)</th>
              <th class="py-2 px-2 font-semibold text-right">累计中位(min)</th>
              <th class="py-2 px-2 font-semibold text-right">段数</th>
              <th v-for="pn in selectedParams" :key="pn" class="py-2 px-2 font-semibold text-right whitespace-nowrap">
                {{ pdisp(pn) }}<span v-if="punit(pn)" class="text-gray-300 ml-0.5">{{ punit(pn) }}</span>
                <span class="text-gray-300 ml-0.5">({{ metric === 'mean' ? '均值' : 'Δ' }})</span>
              </th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in rows" :key="rowId(row)"
              @click="selectUnit(rowId(row))"
              class="border-b border-gray-50 cursor-pointer transition-colors"
              :class="selectedUnit === rowId(row) ? 'bg-amber-50' : 'hover:bg-gray-50'">
              <td class="py-1.5 px-2 font-bold text-gray-800">{{ rowId(row) }}</td>
              <td class="py-1.5 px-2 text-xs text-gray-500">
                {{ level === 'state' ? rangeText(row.stage_codes) : (row.phase_guess || '—') }}
              </td>
              <td class="py-1.5 px-2 text-right text-gray-600 tabular-nums">{{ row.dur_min }}</td>
              <td class="py-1.5 px-2 text-right text-gray-400 tabular-nums">{{ row.cum_min }}</td>
              <td class="py-1.5 px-2 text-right text-gray-400 tabular-nums">{{ row.seg_count }}</td>
              <td v-for="pn in selectedParams" :key="pn" class="py-1.5 px-2 text-right tabular-nums"
                :class="metric === 'delta' && cell(row, pn) != null ? (cell(row, pn) > 0 ? 'text-emerald-600' : cell(row, pn) < 0 ? 'text-rose-500' : 'text-gray-400') : 'text-gray-700'">
                {{ fmt(cell(row, pn)) }}
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <!-- 同阶段/状态 跨周期对比（主对比区）-->
      <div class="bg-white rounded-xl border border-gray-100 shadow-sm p-4 space-y-3">
        <div class="flex flex-wrap items-center gap-2">
          <span class="text-xs font-bold text-gray-700">同{{ unitLabel }}跨周期对比</span>
          <span class="text-xs text-gray-400">选一个{{ unitLabel }}，对比它在各周期的{{ metric === 'mean' ? '段内均值' : '段内变化Δ' }}：</span>
        </div>
        <!-- 单元选择 -->
        <div class="flex flex-wrap items-center gap-1.5">
          <button v-for="row in rows" :key="rowId(row)" @click="selectUnit(rowId(row))"
            class="px-2.5 py-1 rounded-full text-xs font-medium border transition-all"
            :class="selectedUnit === rowId(row) ? 'bg-amber-400 text-white border-amber-400' : 'bg-gray-50 text-gray-500 border-gray-200 hover:border-gray-300'">
            {{ level === 'state' ? row.state : (row.phase_guess ? `${row.stage}·${row.phase_guess}` : `阶段${row.stage}`) }}
          </button>
        </div>

        <div v-if="focusLoading" class="text-center py-10 text-gray-400 text-sm">加载中...</div>
        <template v-else-if="focus && focus.batches.length">
          <!-- 图表1：周期时长对比 -->
          <div class="grid grid-cols-1 lg:grid-cols-2 gap-4 mb-4">
            <div>
              <div class="text-xs font-bold text-gray-600 mb-1 flex items-center gap-2">
                <span class="w-3 h-3 rounded bg-amber-400"></span>
                各周期时长对比
                <span class="text-gray-400 font-normal ml-1">(横坐标：周期序号，纵坐标：持续时间 min)</span>
              </div>
              <div ref="cycleDurEl" style="height: 240px"></div>
            </div>
            <!-- 图表2：周期参数值对比 -->
            <div>
              <div class="text-xs font-bold text-gray-600 mb-1 flex items-center gap-2">
                <span v-for="(pn, idx) in selectedParams" :key="pn" class="inline-flex items-center gap-1">
                  <span class="w-3 h-3 rounded" :style="{ backgroundColor: pcolor(pn) }"></span>
                  {{ pdisp(pn) }}
                </span>
                <span class="text-gray-400 font-normal ml-1">(横坐标：周期序号，纵坐标：{{ metric === 'mean' ? '段内均值' : '段内变化Δ' }})</span>
              </div>
              <div ref="cycleValueEl" style="height: 240px"></div>
            </div>
          </div>
          <!-- 原有的多参数跨周期对比图 -->
          <div ref="cmpEl" style="height: 300px"></div>
          <!-- 逐周期明细表 -->
          <div class="overflow-x-auto">
            <table class="w-full text-xs border-collapse">
              <thead>
                <tr class="text-left text-gray-500 border-b border-gray-200">
                  <th class="py-1.5 px-2 font-semibold">周期(起始)</th>
                  <th class="py-1.5 px-2 font-semibold text-right">实际时长(min)</th>
                  <th v-for="pn in selectedParams" :key="pn" class="py-1.5 px-2 font-semibold text-right whitespace-nowrap">
                    {{ pdisp(pn) }}<span class="text-gray-300 ml-0.5">({{ metric === 'mean' ? '段内均值' : '段内Δ' }})</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="(b, i) in focus.batches" :key="i" class="border-b border-gray-50">
                  <td class="py-1 px-2 text-gray-600 tabular-nums">{{ b.start.slice(5, 16) }}</td>
                  <td class="py-1 px-2 text-right text-gray-400 tabular-nums">{{ b.dur_min }}</td>
                  <td v-for="pn in selectedParams" :key="pn" class="py-1 px-2 text-right tabular-nums text-gray-700">
                    {{ fmt((metric === 'mean' ? b.means : b.deltas)?.[pn] ?? null) }}
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </template>
        <div v-else class="text-center py-10 text-gray-400 text-sm">该{{ unitLabel }}在窗口内无数据</div>
      </div>
    </template>
  </div>
</template>

<script setup>
import { ref, computed, watch, onMounted, onUnmounted, nextTick } from 'vue'
import * as echarts from 'echarts'
import { getStageAnalysis, saveStageStateConfig } from '../api/client.js'

const props = defineProps({ deviceCode: { type: String, default: '' } })

const DAY_OPTIONS = [
  { v: 0.25, label: '最近6小时' }, { v: 0.5, label: '最近12小时' },
  { v: 1, label: '最近1天' }, { v: 3, label: '最近3天' },
]
const COLORS = [
  '#f59e0b', '#3b82f6', '#10b981', '#ef4444', '#8b5cf6',
  '#ec4899', '#06b6d4', '#f97316', '#84cc16', '#6366f1',
  '#14b8a6', '#e11d48', '#a855f7', '#0ea5e9', '#d946ef',
]

const days = ref(0.25)            // 默认 6 小时：小窗口在隧道下也能秒回，且够多周期对比
const level = ref('stage')        // 'stage' | 'state'  —— 默认按阶段
const metric = ref('mean')        // 'mean' | 'delta'
const loading = ref(false)
const errMsg = ref('')
const data = ref(null)
const selectedParams = ref([])

// 跨周期对比：固定的单元(阶段码或状态名) + 它的逐周期数据
const selectedUnit = ref(null)
const focus = ref(null)
const focusLoading = ref(false)

const cmpEl = ref(null)
let cmpChart = null

const cycleDurEl = ref(null)
let cycleDurChart = null

const cycleValueEl = ref(null)
let cycleValueChart = null

const ganttEl = ref(null)
let ganttChart = null
const hiddenKeys = ref([])

// ── 状态分组编辑器 ──
const editing = ref(false)
const saving = ref(false)
const editErr = ref('')
const editStates = ref([])
const editAssign = ref({})
const editExtras = ref({})
const newStateName = ref('')
let nextStateId = 1

const rows = computed(() => {
  if (!data.value) return []
  if (level.value === 'state' && data.value.states?.length) return data.value.states
  return data.value.stages
})
const unitLabel = computed(() => (level.value === 'state' ? '状态' : '阶段'))
const enoughCycles = computed(() =>
  !data.value ? true : data.value.window.batch_count >= (data.value.window.min_cycles || 3))
const cycleText = computed(() => {
  const m = data.value?.window?.cycle_min || 0
  if (!m) return '—'
  return m >= 90 ? `${(m / 60).toFixed(1)} 小时` : `${m} 分钟`
})
const availableCodes = computed(() =>
  [...new Set((data.value?.stages || []).map(s => s.stage))].sort((a, b) => a - b))

// ── 周期·阶段排列图 ──
const ganttHeight = computed(() => {
  const n = data.value?.batches?.length || 0
  return Math.min(640, Math.max(180, n * 26 + 70))
})
// 图例：按状态(level=state)或阶段码上色；key→颜色的唯一来源
const ganttLegend = computed(() => {
  const seen = new Map()
  for (const b of (data.value?.batches || [])) {
    for (const s of b.segments) {
      const key = level.value === 'state' ? (s.state ?? '其他') : s.stage
      if (!seen.has(key)) seen.set(key, s)
    }
  }
  let keys = [...seen.keys()]
  if (level.value !== 'state') keys.sort((a, b) => a - b)
  return keys.map((k, i) => ({
    key: k,
    label: level.value === 'state' ? String(k) : `阶段${k}`,
    color: COLORS[i % COLORS.length],
  }))
})

function durText(m) {
  if (m == null) return '—'
  return m >= 90 ? `${(m / 60).toFixed(1)}h` : `${Math.round(m)}min`
}

function rowId(row) { return level.value === 'state' ? row.state : row.stage }
function pmeta(pn) { return (data.value?.params || []).find(p => p.p_name === pn) }
// ene_ 前缀 = 关联电表的能耗点位（见 backend stage_analysis._fetch_long），加 ⚡ 前缀
// 跟工艺点位区分，跟 DeviceParams.vue 参数分析页的能耗分组视觉语言保持一致
function pdisp(pn) { return (pn?.startsWith('ene_') ? '⚡ ' : '') + (pmeta(pn)?.display_name || pn) }
function punit(pn) { return pmeta(pn)?.unit || '' }
function pcolor(pn) { const i = (data.value?.params || []).findIndex(p => p.p_name === pn); return COLORS[(i < 0 ? 0 : i) % COLORS.length] }
function cell(row, pn) {
  const src = metric.value === 'mean' ? row.means : row.deltas
  const v = src ? src[pn] : null
  return v === undefined ? null : v
}
function fmt(v) { return v == null ? '—' : v }
function rangeText(codes) {
  if (!codes || !codes.length) return '—'
  const c = [...codes].sort((a, b) => a - b)
  const contiguous = c.every((v, i) => i === 0 || v === c[i - 1] + 1)
  return contiguous && c.length > 1 ? `${c[0]}–${c[c.length - 1]}` : c.join(',')
}

function setLevel(lv) {
  if (level.value === lv) return
  level.value = lv
  const first = rows.value[0]
  selectedUnit.value = first ? rowId(first) : null
  nextTick(renderGantt)   // 排列图按 level 上色，切换后重画
  loadFocus()
}

function toggleParam(pn) {
  const i = selectedParams.value.indexOf(pn)
  if (i >= 0) selectedParams.value.splice(i, 1)
  else selectedParams.value.push(pn)
  nextTick(renderCompare)
}

async function load() {
  if (!props.deviceCode) return
  loading.value = true
  errMsg.value = ''
  focus.value = null
  try {
    const res = await getStageAnalysis({ device_code: props.deviceCode, days: days.value, min_cycles: 3 })
    if (res.code === 200 && res.data) {
      data.value = res.data
      if (level.value === 'state' && !(res.data.states?.length)) level.value = 'stage'
      selectedParams.value = res.data.params.map(p => p.p_name).slice(0, Math.min(4, res.data.params.length))
      const first = rows.value[0]
      selectedUnit.value = first ? rowId(first) : null
      await loadFocus()
    } else {
      data.value = null
      errMsg.value = res.msg || '阶段分析失败'
    }
  } catch (e) {
    data.value = null
    errMsg.value = e.message || '阶段分析失败'
  } finally {
    loading.value = false
  }
  // loading 关闭后图表容器才挂回 DOM，此时才能真正画图
  await nextTick()
  renderGantt()
  renderCompare()
}

function selectUnit(id) {
  if (selectedUnit.value === id) return
  selectedUnit.value = id
  loadFocus()
}

async function loadFocus() {
  if (selectedUnit.value == null || !data.value) { focus.value = null; return }
  focusLoading.value = true
  try {
    const params = {
      device_code: props.deviceCode,
      start_time: data.value.window.start,
      end_time: data.value.window.end,
    }
    if (level.value === 'state') params.focus_state = selectedUnit.value
    else params.focus_stage = selectedUnit.value
    const res = await getStageAnalysis(params)
    focus.value = (res.code === 200 && res.data?.focus) ? res.data.focus : { batches: [] }
  } catch (e) {
    console.error('加载逐周期对比失败', e)
    focus.value = { batches: [] }
  } finally {
    focusLoading.value = false
  }
  // focusLoading 关闭后 v-else-if 分支才渲染出 cmpEl，再画图
  await nextTick()
  renderCycleDurChart()
  renderCycleValueChart()
  renderCompare()
}

function toggleGanttLegend(key) {
  const idx = hiddenKeys.value.indexOf(key)
  if (idx >= 0) hiddenKeys.value.splice(idx, 1)
  else hiddenKeys.value.push(key)
  nextTick(renderGantt)
}

function renderGantt() {
  const batches = data.value?.batches || []
  if (!ganttEl.value || !batches.length) return
  if (!ganttChart || ganttChart.isDisposed() || ganttChart.getDom() !== ganttEl.value) {
    if (ganttChart && !ganttChart.isDisposed()) ganttChart.dispose()
    ganttChart = echarts.init(ganttEl.value)
  }
  const colorMap = new Map(ganttLegend.value.map(it => [it.key, it.color]))
  const keyOf = s => (level.value === 'state' ? (s.state ?? '其他') : s.stage)
  const yLabels = batches.map((b, i) => `#${i + 1} ${b.start.slice(5, 16)} · 共${durText(b.dur_min)}`)
  const hidden = new Set(hiddenKeys.value)
  const visibleBatches = batches.map(b => ({
    ...b,
    segments: b.segments.filter(s => !hidden.has(keyOf(s)))
  }))
  const maxSegs = Math.max(1, ...visibleBatches.map(b => b.segments.length))
  const series = []
  for (let k = 0; k < maxSegs; k++) {
    series.push({
      type: 'bar', stack: 'cycle', barWidth: 14,
      data: visibleBatches.map(b => {
        const s = b.segments[k]
        return s ? { value: s.dur_min, seg: s, cycle: b } : { value: 0 }
      }),
      itemStyle: { color: p => (p.data.seg ? colorMap.get(keyOf(p.data.seg)) : 'transparent') },
      emphasis: { focus: 'none' },
    })
  }
  ganttChart.setOption({
    animation: false,
    tooltip: {
      confine: true,
      formatter: p => {
        const { seg, cycle } = p.data || {}
        if (!seg) return ''
        const lbl = level.value === 'state'
          ? `${seg.state ?? '其他'}（阶段${seg.stage}）`
          : `阶段${seg.stage}${seg.state ? ' · ' + seg.state : ''}`
        return `周期 #${p.dataIndex + 1}（${cycle.start.slice(5, 16)} 起，全程 ${durText(cycle.dur_min)}）<br/>` +
               `${lbl}：${seg.start} 开始，实际耗时 <b>${seg.dur_min} min</b>`
      },
    },
    grid: { left: 150, right: 24, top: 8, bottom: 28 },
    xAxis: { type: 'value', name: 'min', nameTextStyle: { fontSize: 10 }, axisLabel: { fontSize: 10 } },
    yAxis: {
      type: 'category', data: yLabels, inverse: true,
      axisLabel: { fontSize: 10, color: '#6b7280' }, axisTick: { show: false },
    },
    series,
  }, true)
  ganttChart.resize()
}

// ── 周期时长对比图 ──
function renderCycleDurChart() {
  if (!cycleDurEl.value || !focus.value || !focus.value.batches.length) return
  if (!cycleDurChart || cycleDurChart.isDisposed() || cycleDurChart.getDom() !== cycleDurEl.value) {
    if (cycleDurChart && !cycleDurChart.isDisposed()) cycleDurChart.dispose()
    cycleDurChart = echarts.init(cycleDurEl.value)
  }
  const batches = focus.value.batches
  const xLabels = batches.map((b, i) => `#${i + 1}`)
  const durationData = batches.map(b => b.dur_min)

  cycleDurChart.setOption({
    animation: false,
    tooltip: {
      trigger: 'axis',
      confine: true,
      formatter: (params) => {
        const p = params[0]
        return `周期 ${p.name}<br/>时长: <b>${p.value} min</b>`
      },
    },
    grid: { left: 56, right: 24, top: 12, bottom: 36 },
    xAxis: {
      type: 'category',
      data: xLabels,
      axisLabel: { fontSize: 10 },
      name: '周期',
      nameTextStyle: { fontSize: 10, color: '#9ca3af' },
    },
    yAxis: {
      type: 'value',
      scale: true,
      axisLabel: { fontSize: 10 },
      name: '时长 (min)',
      nameTextStyle: { fontSize: 10, color: '#9ca3af', align: 'center' },
    },
    series: [{
      name: '周期时长',
      type: 'bar',
      data: durationData,
      itemStyle: { color: '#f59e0b' },
      barWidth: '60%',
    }],
  }, true)
  cycleDurChart.resize()
}

// ── 周期参数值对比图 ──
function renderCycleValueChart() {
  if (!cycleValueEl.value || !focus.value || !focus.value.batches.length || !selectedParams.value.length) return
  if (!cycleValueChart || cycleValueChart.isDisposed() || cycleValueChart.getDom() !== cycleValueEl.value) {
    if (cycleValueChart && !cycleValueChart.isDisposed()) cycleValueChart.dispose()
    cycleValueChart = echarts.init(cycleValueEl.value)
  }
  const batches = focus.value.batches
  const xLabels = batches.map((b, i) => `#${i + 1}`)

  // 找出第一个有值的参数作为基准，用于双Y轴
  let baseParam = null
  for (const pn of selectedParams.value) {
    const hasData = batches.some(b => (metric.value === 'mean' ? b.means : b.deltas)?.[pn] != null)
    if (hasData) { baseParam = pn; break }
  }

  const series = selectedParams.value.map((pn, idx) => {
    const data = batches.map(b => (metric.value === 'mean' ? b.means : b.deltas)?.[pn] ?? null)
    return {
      name: pdisp(pn),
      type: 'line',
      showSymbol: true,
      symbolSize: 6,
      yAxisIndex: idx === 0 ? 0 : (selectedParams.value.indexOf(pn) % 2 === 0 ? 0 : 1),
      data,
      itemStyle: { color: pcolor(pn) },
      lineStyle: { width: 1.5 },
      connectNulls: true,
    }
  })

  const yAxes = []
  if (selectedParams.value.length > 0) {
    yAxes.push({
      type: 'value',
      scale: true,
      axisLabel: { fontSize: 10 },
      name: `${pdisp(selectedParams.value[0])}${punit(selectedParams.value[0]) ? ' (' + punit(selectedParams.value[0]) + ')' : ''}`,
      nameTextStyle: { fontSize: 9, color: pcolor(selectedParams.value[0]) },
    })
  }
  if (selectedParams.value.length > 1) {
    yAxes.push({
      type: 'value',
      scale: true,
      position: 'right',
      axisLabel: { fontSize: 10 },
      name: `${pdisp(selectedParams.value[1])}${punit(selectedParams.value[1]) ? ' (' + punit(selectedParams.value[1]) + ')' : ''}`,
      nameTextStyle: { fontSize: 9, color: pcolor(selectedParams.value[1]) },
    })
  }

  cycleValueChart.setOption({
    animation: false,
    tooltip: { trigger: 'axis', confine: true },
    legend: { top: 0, type: 'scroll', textStyle: { fontSize: 10 } },
    grid: { left: 56, right: selectedParams.value.length > 1 ? 56 : 24, top: 32, bottom: 36 },
    xAxis: {
      type: 'category',
      data: xLabels,
      axisLabel: { fontSize: 10 },
      name: '周期',
      nameTextStyle: { fontSize: 10, color: '#9ca3af' },
    },
    yAxis: yAxes,
    series,
  }, true)
  cycleValueChart.resize()
}

function renderCompare() {
  if (!cmpEl.value || !focus.value || !focus.value.batches.length) return
  // v-if 切换会重建容器节点；旧实例绑在游离 DOM 上画不出来，必须重建
  if (!cmpChart || cmpChart.isDisposed() || cmpChart.getDom() !== cmpEl.value) {
    if (cmpChart && !cmpChart.isDisposed()) cmpChart.dispose()
    cmpChart = echarts.init(cmpEl.value)
  }
  const batches = focus.value.batches
  const x = batches.map((b, i) => `#${i + 1} ${b.start.slice(5, 16)}`)
  const series = selectedParams.value.map(pn => ({
    name: pdisp(pn), type: 'line', showSymbol: true, symbolSize: 5,
    data: batches.map(b => (metric.value === 'mean' ? b.means : b.deltas)?.[pn] ?? null),
    itemStyle: { color: pcolor(pn) }, lineStyle: { width: 1.5 }, connectNulls: true,
  }))
  cmpChart.setOption({
    animation: false,
    tooltip: { trigger: 'axis', confine: true },
    legend: { top: 0, type: 'scroll', textStyle: { fontSize: 11 } },
    grid: { left: 48, right: 16, top: 36, bottom: 60 },
    xAxis: { type: 'category', data: x, name: '周期(按时间)', axisLabel: { fontSize: 9, rotate: 40, hideOverlap: true } },
    yAxis: {
      type: 'value', scale: true, axisLabel: { fontSize: 10 },
      name: metric.value === 'mean' ? '段内均值(该周期内的平均)' : '段内变化Δ(段末-段首)',
      nameTextStyle: { fontSize: 10, color: '#9ca3af', align: 'left' },
    },
    dataZoom: [{ type: 'inside' }, { type: 'slider', height: 16, bottom: 4 }],
    series,
  }, true)
  cmpChart.resize()
}

// ── 编辑器 ──
function openEditor() {
  const groups = data.value?.state_map || []
  const present = new Set(availableCodes.value)
  editStates.value = groups.map(g => ({ id: nextStateId++, name: g.state }))
  const assign = {}
  for (const c of availableCodes.value) assign[c] = null
  const extras = {}
  for (const s of editStates.value) {
    const g = groups.find(x => x.state === s.name)
    extras[s.id] = (g?.codes || []).filter(c => !present.has(c))
    for (const c of (g?.codes || [])) if (present.has(c)) assign[c] = s.id
  }
  editAssign.value = assign
  editExtras.value = extras
  editErr.value = ''
  editing.value = true
}

function addState() {
  const name = newStateName.value.trim()
  if (!name) return
  if (editStates.value.some(s => s.name === name)) { editErr.value = `状态"${name}"已存在`; return }
  editStates.value.push({ id: nextStateId++, name })
  newStateName.value = ''
  editErr.value = ''
}

function deleteState(id) {
  editStates.value = editStates.value.filter(s => s.id !== id)
  for (const c of Object.keys(editAssign.value)) {
    if (editAssign.value[c] === id) editAssign.value[c] = null
  }
}

async function saveConfig() {
  const names = editStates.value.map(s => s.name.trim())
  if (names.some(n => !n)) { editErr.value = '状态名不能为空'; return }
  if (new Set(names).size !== names.length) { editErr.value = '状态名不能重复'; return }
  const config = editStates.value.map(s => {
    const codes = availableCodes.value.filter(c => editAssign.value[c] === s.id)
      .concat(editExtras.value[s.id] || [])
    return { state: s.name.trim(), codes: [...new Set(codes)].sort((a, b) => a - b) }
  }).filter(g => g.codes.length)
  if (!config.length) { editErr.value = '至少给一个状态分配阶段码'; return }
  saving.value = true
  editErr.value = ''
  try {
    const res = await saveStageStateConfig({ device_code: props.deviceCode, config })
    if (res.code === 200) {
      editing.value = false
      level.value = 'state'
      await load()
    } else {
      editErr.value = res.msg || '保存失败'
    }
  } catch (e) {
    editErr.value = e.message || '保存失败'
  } finally {
    saving.value = false
  }
}

watch(metric, () => {
  renderCycleValueChart()
  renderCompare()
})
watch(() => props.deviceCode, () => { data.value = null; load() })

function onResize() {
  if (cmpChart && !cmpChart.isDisposed()) cmpChart.resize()
  if (ganttChart && !ganttChart.isDisposed()) ganttChart.resize()
  if (cycleDurChart && !cycleDurChart.isDisposed()) cycleDurChart.resize()
  if (cycleValueChart && !cycleValueChart.isDisposed()) cycleValueChart.resize()
}

onMounted(() => {
  window.addEventListener('resize', onResize)
  if (props.deviceCode) load()
})
onUnmounted(() => {
  window.removeEventListener('resize', onResize)
  if (cmpChart && !cmpChart.isDisposed()) cmpChart.dispose()
  if (ganttChart && !ganttChart.isDisposed()) ganttChart.dispose()
  if (cycleDurChart && !cycleDurChart.isDisposed()) cycleDurChart.dispose()
  if (cycleValueChart && !cycleValueChart.isDisposed()) cycleValueChart.dispose()
})
</script>
