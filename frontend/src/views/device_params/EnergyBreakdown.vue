<template>
  <div class="space-y-6">
    <div class="bg-white rounded-xl border border-gray-100 shadow-sm p-5">
      <div class="flex items-center justify-between mb-3 flex-wrap gap-2">
        <span class="text-xs font-bold text-gray-400 uppercase tracking-wider">
          ② 能耗 — 按房子(生产周期) 拆解<span v-if="energyMeter?.energy_points"> · {{ energyHasPrimary && energyHasSecondary ? '主：' + energyMeter.energy_points.primary.display_name + ' / 辅：' + energyMeter.energy_points.secondary.display_name : energyHasPrimary ? energyMeter.energy_points.primary.display_name : energyHasSecondary ? energyMeter.energy_points.secondary.display_name : '' }}</span>
        </span>
        <div v-if="energyResult?.meters?.length > 1" class="flex items-center gap-2">
          <span class="text-xs text-gray-400">电表</span>
          <select v-model="selectedMeterId" @change="onEnergyMeterChange"
                  class="text-xs px-2 py-1 border border-gray-200 rounded bg-white">
            <option v-for="m in energyResult.meters" :key="m.meter_id" :value="m.meter_id">{{ m.meter_id }}</option>
          </select>
          <span class="text-[10px] text-gray-400">共 {{ energyResult.meters.length }} 个，各表分别统计</span>
        </div>
        <span v-else-if="energyMeter" class="text-xs text-gray-400">电表 {{ energyMeter.meter_id }}</span>
      </div>
      <div v-if="!energyResult" class="text-center py-8 text-gray-400 text-sm">按上方时间范围自动分析能耗</div>
      <div v-else-if="energyResult.source === 'loading'" class="text-center py-12 text-gray-400">⏳ 分析中...</div>
      <div v-else-if="energyResult.source === 'error'" class="text-center py-12 text-gray-400 text-sm px-6">{{ energyResult.msg }}</div>
      <template v-else>
        <div class="grid gap-3 text-center mb-4" :class="energyActiveCount === 1 ? 'grid-cols-3' : 'grid-cols-4'">
          <div class="bg-sky-50 rounded-lg p-3">
            <div class="text-sky-700 font-bold text-lg">
              {{ energyMeter.summary.house_count }}<span v-if="energyValidHouseCount !== null" class="text-sm font-normal text-sky-500">（有效 {{ energyValidHouseCount }}）</span>
            </div>
            <div class="text-sky-600 text-xs">房子数(周期)</div>
          </div>
          <div v-if="energyHasPrimary" class="bg-blue-50 rounded-lg p-3">
            <div class="text-blue-700 font-bold text-lg">{{ energyMeter.summary.total_primary_kwh ?? '—' }}</div>
            <div class="text-blue-600 text-xs">总能耗 {{ energyMeter.energy_points.primary.display_name }}(kWh)</div>
          </div>
          <div v-if="energyHasPrimary" class="bg-cyan-50 rounded-lg p-3">
            <div class="text-cyan-700 font-bold text-lg">{{ energyMeter.summary.avg_primary_kwh ?? '—' }}</div>
            <div class="text-cyan-600 text-xs">单房子均值(kWh)</div>
          </div>
          <div v-if="energyHasSecondary" class="bg-violet-50 rounded-lg p-3">
            <div class="text-violet-700 font-bold text-lg">{{ energyMeter.summary.total_secondary_kwh ?? '—' }}</div>
            <div class="text-violet-600 text-xs">总能耗 {{ energyMeter.energy_points.secondary.display_name }}(kWh)</div>
          </div>
        </div>

        <div v-if="energyHasPrimary" class="grid grid-cols-2 gap-3 text-center mb-4">
          <div class="bg-emerald-50 rounded-lg p-3">
            <div class="text-emerald-700 font-bold text-lg">{{ energyMeter.summary.valid_primary_kwh ?? '—' }}</div>
            <div class="text-emerald-600 text-xs">有效能耗·运行(kWh)</div>
          </div>
          <div class="bg-rose-50 rounded-lg p-3">
            <div class="text-rose-700 font-bold text-lg">{{ energyMeter.summary.invalid_primary_kwh ?? '—' }}</div>
            <div class="text-rose-600 text-xs">无效能耗·待机(kWh)</div>
          </div>
        </div>

        <div v-if="energyDropNotes.length" class="mb-4 px-3 py-2 rounded-lg bg-amber-50 border border-amber-100 text-xs text-amber-700 space-y-0.5">
          <div v-for="(n, i) in energyDropNotes" :key="i">⚠ {{ n }}</div>
        </div>

        <div class="border border-gray-100 rounded-lg p-3 mb-4">
          <div class="flex items-center justify-between mb-2 flex-wrap gap-2">
            <div class="text-xs font-bold text-gray-500">每房子能耗（点击查看该房子阶段拆解，缺口＝该房子电表回绕已剔除）</div>
            <div class="flex items-center gap-0.5 bg-gray-50 rounded-lg p-0.5">
              <button @click="setEnergyChartType('bar')" class="px-2 py-0.5 text-[11px] rounded transition-colors" :class="energyChartType === 'bar' ? 'bg-white text-gray-700 font-bold shadow-sm' : 'text-gray-400'">柱状</button>
              <button @click="setEnergyChartType('line')" class="px-2 py-0.5 text-[11px] rounded transition-colors" :class="energyChartType === 'line' ? 'bg-white text-gray-700 font-bold shadow-sm' : 'text-gray-400'">趋势</button>
            </div>
          </div>
          <div ref="energyBarEl" class="w-full" style="height: 320px"></div>
        </div>

        <div class="border border-gray-100 rounded-lg p-3 mb-4">
          <div class="text-xs font-bold text-gray-500 mb-2">各阶段能耗对比（跨所有房子均值，按阶段聚合 · 点击柱子查看该阶段逐次趋势）</div>
          <div ref="energyStageCmpEl" class="w-full" style="height: 320px"></div>
        </div>

        <div v-if="stageTrendOptions.length" class="border border-gray-100 rounded-lg p-3 mb-4">
          <div class="flex items-center justify-between mb-2 flex-wrap gap-2">
            <div class="text-xs font-bold text-gray-500">周期·阶段排列（每行一个房子，色块=阶段，长度=实际耗时(min)，行首标注该房子总时长 · 点击色块/图例可多选，切换下方趋势线显示）</div>
            <div class="flex items-center gap-2">
              <button @click="selectAllStages" class="text-[10px] text-indigo-600 hover:underline">全选</button>
              <button @click="clearStages" class="text-[10px] text-gray-400 hover:underline">清空</button>
            </div>
          </div>
          <div class="flex items-center gap-1 flex-wrap mb-2">
            <button v-for="s in stageLegend" :key="s.key" @click="toggleStage(s.key)"
                    class="flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] border transition-colors"
                    :class="selectedStages.has(s.key) ? 'border-gray-300 bg-gray-100 font-bold text-gray-700' : 'border-gray-100 text-gray-300 hover:text-gray-500 hover:border-gray-200'">
              <span class="inline-block w-2.5 h-2.5 rounded-sm" :style="{ background: s.color, opacity: selectedStages.has(s.key) ? 1 : 0.3 }"></span>
              {{ s.label }}
            </button>
          </div>
          <div ref="energyGanttEl" class="w-full" :style="{ height: ganttHeight + 'px' }"></div>

          <div class="mt-3 pt-3 border-t border-gray-50">
            <div class="text-xs font-bold text-gray-500 mb-2">
              多阶段逐次能耗趋势 — 已选 {{ selectedStagesSorted.length }} 个阶段（同一阶段每次出现的能耗对比，按时间顺序）
            </div>
            <div v-if="!selectedStagesSorted.length" class="text-center py-8 text-gray-400 text-xs">请点击上方色块或图例，选择要显示的阶段（可多选）</div>
            <div v-else ref="energyStageTrendEl" class="w-full" style="height: 320px"></div>
          </div>
        </div>

        <div class="border border-gray-100 rounded-lg p-3 mb-4">
          <div class="flex items-center justify-between mb-2 flex-wrap gap-2">
            <div class="text-xs font-bold text-gray-500">
              房子 #{{ selectedEnergyHouse?.house_id }} 阶段能耗拆解
              <span class="text-gray-400 font-normal" v-if="selectedEnergyHouse">· {{ selectedEnergyHouse.t_start }} ~ {{ selectedEnergyHouse.t_end }} ({{ selectedEnergyHouse.dur_min }}分钟)</span>
            </div>
            <select v-model.number="selectedEnergyHouseId" @change="renderEnergyStage" class="text-xs px-2 py-1 border border-gray-200 rounded bg-white">
              <option v-for="h in energyMeter.houses" :key="h.house_id" :value="h.house_id">#{{ h.house_id }} {{ h.t_start.slice(5, 16) }}</option>
            </select>
          </div>
          <div ref="energyStageEl" class="w-full" style="height: 300px"></div>
        </div>

        <div class="border border-gray-100 rounded-lg overflow-hidden">
          <div class="px-3 py-2 bg-gray-50 text-xs font-bold text-gray-500 border-b">各阶段能耗汇总（跨房子均值）</div>
          <table class="w-full text-xs">
            <thead class="text-gray-400">
              <tr class="border-b border-gray-100">
                <th class="text-left px-3 py-1.5 font-medium">阶段</th>
                <th class="text-left px-3 py-1.5 font-medium">名称</th>
                <th class="text-right px-3 py-1.5 font-medium" title="该阶段在窗口内出现的总次数；括号内为出现过该阶段的房子数">出现次数</th>
                <th class="text-right px-3 py-1.5 font-medium" title="平均时长与平均能耗同为「每次出现」口径，可直接相除得功率">平均时长(分)</th>
                <th v-if="energyHasPrimary" class="text-right px-3 py-1.5 font-medium">平均{{ energyMeter.energy_points.primary.display_name }}(kWh)</th>
                <th v-if="energyHasSecondary" class="text-right px-3 py-1.5 font-medium">平均{{ energyMeter.energy_points.secondary.display_name }}(kWh)</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="s in energyMeter.summary.stage_summary" :key="s.stage" class="border-b border-gray-50">
                <td class="px-3 py-1.5">{{ s.stage }}</td>
                <td class="px-3 py-1.5 text-gray-600">{{ s.name }}</td>
                <td class="px-3 py-1.5 text-right">
                  {{ s.segment_count ?? s.appear_count }}<span v-if="s.segment_count && s.segment_count !== s.appear_count" class="text-gray-400">（{{ s.appear_count }}房）</span>
                  <span v-if="s.primary_drop_count > 0" class="ml-1 text-amber-600" :title="`其中 ${s.primary_drop_count} 次因电表读数回绕/重置被剔除，平均值按剩余 ${s.segment_count - s.primary_drop_count} 次计算`">−{{ s.primary_drop_count }}</span>
                </td>
                <td class="px-3 py-1.5 text-right">{{ s.avg_dur_min ?? '—' }}</td>
                <td v-if="energyHasPrimary" class="px-3 py-1.5 text-right text-blue-700">{{ s.avg_primary_kwh ?? '—' }}</td>
                <td v-if="energyHasSecondary" class="px-3 py-1.5 text-right text-violet-700">{{ s.avg_secondary_kwh ?? '—' }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </template>
    </div>
  </div>
</template>

<script setup>
import { ref, reactive, computed, watch, onUnmounted, nextTick } from 'vue'
import * as echarts from 'echarts'

const props = defineProps({
  energyResult: { type: Object, default: null },
})

const ENERGY_POINTS = ['ene_eptotal', 'ene_imp']
// 与 StageAnalysis.vue「周期·阶段排列」图用同一套调色板，保持视觉语言一致
// （该文件没有导出可复用的颜色工具，这里按同样的“按出现顺序取色”规则复制一份）。
const COLORS = ['#f59e0b', '#3b82f6', '#10b981', '#ef4444', '#8b5cf6', '#ec4899',
  '#06b6d4', '#f97316', '#84cc16', '#6366f1', '#14b8a6', '#e11d48', '#a855f7', '#0ea5e9', '#d946ef']
const energyBarEl = ref(null)
const energyStageEl = ref(null)
const energyStageCmpEl = ref(null)
const energyStageTrendEl = ref(null)
const energyGanttEl = ref(null)
let energyBarChart = null
let energyStageChart = null
let energyStageCmpChart = null
let energyStageTrendChart = null
let energyGanttChart = null
const selectedEnergyHouseId = ref(null)
const selectedMeterId = ref(null)
const energyChartType = ref('bar')
// 多选：勾选哪些阶段就在下方趋势图里显示哪些线，而不是只能显示一条
const selectedStages = reactive(new Set())
function withAlpha(hex, alpha) {
  const h = (hex || '#94a3b8').replace('#', '')
  const r = parseInt(h.substring(0, 2), 16), g = parseInt(h.substring(2, 4), 16), b = parseInt(h.substring(4, 6), 16)
  return `rgba(${r},${g},${b},${alpha})`
}
// 图表容器可能藏在 v-if 后面(如清空阶段选择后趋势图整个 div 会被移出 DOM)——
// 重新勾选时 Vue 会挂一个全新的 DOM 节点，旧的 echarts 实例还绑着已被摘除的老节点，
// 不是 null 也没 dispose，光靠 `!chart || chart.isDisposed()` 判断不出来，
// setOption 写了图但没人看得见。这里额外比较 getDom() 是否还是当前这个节点。
function ensureChart(chart, el) {
  if (chart && !chart.isDisposed() && chart.getDom() === el) return chart
  if (chart && !chart.isDisposed()) chart.dispose()
  return echarts.init(el)
}

const energyMeter = computed(() => {
  const ms = props.energyResult?.meters
  if (!ms || !ms.length) return null
  return ms.find(m => m.meter_id === selectedMeterId.value) || ms[0]
})
const selectedEnergyHouse = computed(() => {
  const m = energyMeter.value
  if (!m || !m.houses) return null
  return m.houses.find(h => h.house_id === selectedEnergyHouseId.value) || m.houses[0] || null
})
const energyHasPrimary = computed(() => !!energyMeter.value?.energy_points?.primary?.has_data)
const energyHasSecondary = computed(() => !!energyMeter.value?.energy_points?.secondary?.has_data)
const energyActiveCount = computed(() => (energyHasPrimary.value ? 1 : 0) + (energyHasSecondary.value ? 1 : 0))

const energyDropNotes = computed(() => {
  const m = energyMeter.value
  if (!m?.summary) return []
  const s = m.summary
  const notes = []
  if (energyHasPrimary.value && s.primary_dropped_house_count > 0) {
    notes.push(`${m.energy_points.primary.display_name}：${s.primary_dropped_house_count} 栋房子因电表读数回绕/重置被剔除，合计与均值按剩余 ${s.primary_valid_house_count} 栋计算`)
  }
  if (energyHasSecondary.value && s.secondary_dropped_house_count > 0) {
    notes.push(`${m.energy_points.secondary.display_name}：${s.secondary_dropped_house_count} 栋房子被剔除，按剩余 ${s.secondary_valid_house_count} 栋计算`)
  }
  if (s.boundary_dropped_house_ids?.length) {
    notes.push(`已排除窗口首尾各1栋房子（#${s.boundary_dropped_house_ids.join('、#')}），避免边界截断样本拉偏均值，不计入统计`)
  }
  return notes
})
const energyValidHouseCount = computed(() => {
  const s = energyMeter.value?.summary
  if (!s || !energyHasPrimary.value) return null
  return s.primary_dropped_house_count > 0 ? s.primary_valid_house_count : null
})

// ── 周期·阶段排列：每行一个房子，色块=阶段，长度=实际耗时(min)——把各阶段都摆到
// 图表上方（图例即多选开关），点击色块/图例即可勾选/取消，控制下方趋势图显示哪些阶段 ──
const stageLegend = computed(() => {
  const houses = energyMeter.value?.houses
  if (!houses?.length) return []
  const seen = new Map()
  for (const h of houses) {
    for (const s of (h.stages || [])) {
      if (!seen.has(s.stage)) seen.set(s.stage, s.name)
    }
  }
  const keys = [...seen.keys()].sort((a, b) => a - b)
  return keys.map((k, i) => ({ key: k, label: `阶段${k} ${seen.get(k)}`, color: COLORS[i % COLORS.length] }))
})
const ganttHeight = computed(() => {
  const n = energyMeter.value?.houses?.length || 0
  return Math.max(120, Math.min(560, n * 28 + 40))
})
function durText(min) {
  if (min == null) return '—'
  if (min < 60) return `${min}min`
  const h = Math.floor(min / 60), m = Math.round(min % 60)
  return m ? `${h}h${m}min` : `${h}h`
}
function _rerenderStageViews() {
  nextTick(() => { renderEnergyGantt(); renderEnergyStageTrend() })
}
function toggleStage(stage) {
  if (selectedStages.has(stage)) selectedStages.delete(stage)
  else selectedStages.add(stage)
  _rerenderStageViews()
}
function selectAllStages() {
  for (const s of stageLegend.value) selectedStages.add(s.key)
  _rerenderStageViews()
}
function clearStages() {
  selectedStages.clear()
  _rerenderStageViews()
}
function _initSelectedStages(summary) {
  selectedStages.clear()
  for (const s of (summary?.stage_summary || [])) selectedStages.add(s.stage)
}

// ── 单阶段逐次能耗趋势：同一阶段在各房子中每次出现的能耗，按时间顺序对比 ──
const stageTrendOptions = computed(() => {
  const list = energyMeter.value?.summary?.stage_summary
  if (!list?.length) return []
  const seen = new Set()
  const opts = []
  for (const s of list) {
    if (seen.has(s.stage)) continue
    seen.add(s.stage)
    opts.push({ stage: s.stage, name: s.name })
  }
  return opts
})
const selectedStagesSorted = computed(() => [...selectedStages].sort((a, b) => a - b))
// 多选后每个阶段一条线，共用同一条 x 轴(全部房子，按时间顺序)——某房子没出现该阶段就留空(断线)，
// 而不是像单选时那样只取"出现过的房子"当 x 轴(那样多条线的 x 轴对不齐，没法叠在一张图上比较)。
const stageTrendBundle = computed(() => {
  const r = energyMeter.value
  const stages = selectedStagesSorted.value
  if (!r?.houses?.length || !stages.length) return null
  const houses = r.houses
  const cats = houses.map(h => `#${h.house_id}\n${h.t_start.slice(5, 16)}`)
  const perStage = stages.map(stage => {
    const legendItem = stageLegend.value.find(s => s.key === stage)
    return {
      stage,
      name: legendItem?.label || `阶段${stage}`,
      color: legendItem?.color || '#94a3b8',
      primary: houses.map(h => (h.stages || []).find(s => s.stage === stage)?.primary_kwh ?? null),
      secondary: houses.map(h => (h.stages || []).find(s => s.stage === stage)?.secondary_kwh ?? null),
    }
  })
  return { cats, perStage }
})

function setEnergyChartType(t) {
  if (energyChartType.value === t) return
  energyChartType.value = t
  renderEnergyBar()
}

function onEnergyMeterChange() {
  selectedEnergyHouseId.value = energyMeter.value?.houses?.[0]?.house_id ?? null
  _initSelectedStages(energyMeter.value?.summary)
  renderEnergyCharts()
}

function disposeEnergyCharts() {
  for (const c of [energyBarChart, energyStageChart, energyStageCmpChart, energyStageTrendChart, energyGanttChart]) {
    if (c && !c.isDisposed()) c.dispose()
  }
  energyBarChart = null
  energyStageChart = null
  energyStageCmpChart = null
  energyStageTrendChart = null
  energyGanttChart = null
}

function renderEnergyGantt() {
  const r = energyMeter.value
  const houses = r?.houses
  if (!r || !houses?.length || !energyGanttEl.value) return
  energyGanttChart = ensureChart(energyGanttChart, energyGanttEl.value)
  const colorMap = new Map(stageLegend.value.map((it) => [it.key, it.color]))
  const maxSegs = Math.max(0, ...houses.map((h) => (h.stages || []).length))
  const yLabels = houses.map((h) => `#${h.house_id} ${h.t_start.slice(5, 16)} · 共${durText(h.dur_min)}`)
  const series = []
  for (let k = 0; k < maxSegs; k++) {
    series.push({
      type: 'bar', stack: 'house', barWidth: 14,
      data: houses.map((h) => {
        const s = (h.stages || [])[k]
        return s ? { value: s.dur_min, seg: s, house: h } : { value: 0 }
      }),
      itemStyle: {
        color: (p) => {
          if (!p.data.seg) return 'transparent'
          const base = colorMap.get(p.data.seg.stage) || '#94a3b8'
          return selectedStages.has(p.data.seg.stage) ? base : withAlpha(base, 0.2)
        },
      },
      emphasis: { focus: 'none' },
    })
  }
  energyGanttChart.setOption({
    tooltip: {
      trigger: 'item',
      formatter: (p) => {
        const s = p.data?.seg
        if (!s) return ''
        let t = `房子 #${p.data.house.house_id}<br/>阶段${s.stage} ${s.name}<br/>时长 ${s.dur_min} 分钟`
        if (s.primary_kwh != null) t += `<br/>能耗 ${s.primary_kwh} kWh`
        t += `<br/><span class="text-gray-400">点击${selectedStages.has(s.stage) ? '隐藏' : '显示'}该阶段趋势线</span>`
        return t
      },
    },
    grid: { left: 150, right: 20, top: 10, bottom: 30 },
    xAxis: { type: 'value', name: 'min' },
    yAxis: { type: 'category', data: yLabels, inverse: true, axisLabel: { fontSize: 10 } },
    series,
  }, true)
  energyGanttChart.off('click')
  energyGanttChart.on('click', (params) => {
    const s = params.data?.seg
    if (s) toggleStage(s.stage)
  })
}

function renderEnergyBar() {
  const r = energyMeter.value
  if (!r || !r.houses || !r.houses.length || !energyBarEl.value) return
  energyBarChart = ensureChart(energyBarChart, energyBarEl.value)
  const hasP = !!r.energy_points.primary?.has_data
  const hasS = !!r.energy_points.secondary?.has_data
  const pName = r.energy_points.primary?.display_name
  const sName = r.energy_points.secondary?.display_name
  const isLine = energyChartType.value === 'line'
  const cats = isLine
    ? r.houses.map(h => h.t_start.slice(5, 16))
    : r.houses.map(h => `#${h.house_id}\n${h.t_start.slice(5, 16)}`)
  const mk = (name, key, color, dashed) => (isLine
    ? { name, type: 'line', smooth: true, symbol: 'circle', symbolSize: 6,
        data: r.houses.map(h => h[key]), itemStyle: { color },
        ...(dashed ? { lineStyle: { type: 'dashed' } } : { areaStyle: { opacity: 0.08 } }) }
    : { name, type: 'bar', barMaxWidth: 36, data: r.houses.map(h => h[key]), itemStyle: { color } })
  const series = []
  if (hasP) series.push(mk(pName, 'primary_kwh', '#3b82f6', false))
  if (hasS) series.push(mk(sName, 'secondary_kwh', '#a78bfa', true))
  energyBarChart.off('click')
  energyBarChart.setOption({
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' },
      formatter: (ps) => {
        const h = r.houses[ps[0].dataIndex]
        if (!h) return ''
        let s = `房子 #${h.house_id}<br/>${h.t_start} ~ ${h.t_end}<br/>时长 ${h.dur_min} 分钟`
        const fmt = (v) => (v != null ? `${v} kWh` : '电表回绕，已剔除')
        if (hasP) s += `<br/><span style="color:#3b82f6">●</span> ${pName}: ${fmt(h.primary_kwh)}`
        if (hasS) s += `<br/><span style="color:#a78bfa">●</span> ${sName}: ${fmt(h.secondary_kwh)}`
        return s
      } },
    legend: { data: series.map(s => s.name), top: 0 },
    grid: { left: 50, right: 20, top: 36, bottom: isLine ? 40 : 56 },
    xAxis: { type: 'category', data: cats, boundaryGap: !isLine, axisLabel: { fontSize: 10, interval: 0 }, axisTick: { alignWithLabel: true } },
    yAxis: { type: 'value', name: 'kWh' },
    series,
  }, true)
  energyBarChart.on('click', (params) => {
    if (params.dataIndex == null) return
    selectedEnergyHouseId.value = r.houses[params.dataIndex].house_id
    renderEnergyStage()
  })
}

function renderEnergyStage() {
  const r = energyMeter.value
  const h = selectedEnergyHouse.value
  if (!r || !h || !energyStageEl.value) return
  energyStageChart = ensureChart(energyStageChart, energyStageEl.value)
  const stages = h.stages || []
  const hasP = !!r.energy_points.primary?.has_data
  const hasS = !!r.energy_points.secondary?.has_data
  const pName = r.energy_points.primary?.display_name
  const sName = r.energy_points.secondary?.display_name
  const series = []
  if (hasP) series.push({ name: pName, type: 'bar', barMaxWidth: 30, data: stages.map(s => s.primary_kwh), itemStyle: { color: '#3b82f6' } })
  if (hasS) series.push({ name: sName, type: 'bar', barMaxWidth: 30, data: stages.map(s => s.secondary_kwh), itemStyle: { color: '#a78bfa' } })
  energyStageChart.setOption({
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
    legend: { data: series.map(s => s.name), top: 0 },
    grid: { left: 50, right: 20, top: 36, bottom: 70 },
    xAxis: { type: 'category', data: stages.map(s => `${s.stage}\n${s.name}`), axisLabel: { fontSize: 10, interval: 0 } },
    yAxis: { type: 'value', name: 'kWh' },
    series,
  }, true)
}

function renderEnergyStageCmp() {
  const r = energyMeter.value
  if (!r || !r.summary?.stage_summary?.length || !energyStageCmpEl.value) return
  energyStageCmpChart = ensureChart(energyStageCmpChart, energyStageCmpEl.value)
  const hasP = !!r.energy_points.primary?.has_data
  const hasS = !!r.energy_points.secondary?.has_data
  const pName = r.energy_points.primary?.display_name
  const sName = r.energy_points.secondary?.display_name
  const order = []
  const agg = {}
  for (const s of r.summary.stage_summary) {
    const nm = s.name
    if (!(nm in agg)) { agg[nm] = { p: 0, s: 0, dur: 0, pCnt: 0, sCnt: 0 }; order.push(nm) }
    const a = agg[nm]
    if (hasP && s.avg_primary_kwh != null) { a.p += s.avg_primary_kwh; a.pCnt++ }
    if (hasS && s.avg_secondary_kwh != null) { a.s += s.avg_secondary_kwh; a.sCnt++ }
    if (s.avg_dur_min != null) a.dur += s.avg_dur_min
  }
  const series = []
  if (hasP) series.push({ name: pName, type: 'bar', barMaxWidth: 48, data: order.map(n => +agg[n].p.toFixed(4)), itemStyle: { color: '#3b82f6', cursor: 'pointer' }, label: { show: true, position: 'top', fontSize: 10, formatter: '{c}' } })
  if (hasS) series.push({ name: sName, type: 'bar', barMaxWidth: 48, data: order.map(n => +agg[n].s.toFixed(4)), itemStyle: { color: '#a78bfa', cursor: 'pointer' } })
  energyStageCmpChart.setOption({
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' },
      formatter: (ps) => {
        const nm = order[ps[0].dataIndex]
        const a = agg[nm]
        return `${nm}<br/>` + ps.map(p => `${p.marker} ${p.seriesName}: ${p.value} kWh`).join('<br/>') + `<br/>平均时长 ${a.dur.toFixed(1)} 分钟<br/><span class="text-gray-400">点击查看该阶段逐次趋势</span>`
      } },
    legend: { data: series.map(s => s.name), top: 0 },
    grid: { left: 50, right: 20, top: 36, bottom: 40 },
    xAxis: { type: 'category', data: order, axisLabel: { fontSize: 11, interval: 0 } },
    yAxis: { type: 'value', name: 'kWh' },
    series,
  }, true)
  energyStageCmpChart.off('click')
  energyStageCmpChart.on('click', (params) => {
    if (params.dataIndex == null) return
    const nm = order[params.dataIndex]
    const hit = r.summary.stage_summary.find(s => s.name === nm)
    if (!hit) return
    toggleStage(hit.stage)
  })
}

function renderEnergyStageTrend() {
  const r = energyMeter.value
  const bundle = stageTrendBundle.value
  if (!r || !bundle || !energyStageTrendEl.value) return
  energyStageTrendChart = ensureChart(energyStageTrendChart, energyStageTrendEl.value)
  const hasP = !!r.energy_points.primary?.has_data
  const hasS = !!r.energy_points.secondary?.has_data
  const pName = r.energy_points.primary?.display_name
  const sName = r.energy_points.secondary?.display_name
  // 多阶段共用同一条 x 轴(全部房子)，某房子没出现该阶段就是 null(断线，不连接)
  const series = []
  for (const st of bundle.perStage) {
    if (hasP) series.push({ name: `${st.name}·${pName}`, type: 'line', smooth: true, symbol: 'circle',
      symbolSize: 5, connectNulls: false, data: st.primary, itemStyle: { color: st.color } })
    if (hasS) series.push({ name: `${st.name}·${sName}`, type: 'line', smooth: true, symbol: 'circle',
      symbolSize: 5, connectNulls: false, data: st.secondary, itemStyle: { color: st.color }, lineStyle: { type: 'dashed' } })
  }
  energyStageTrendChart.setOption({
    tooltip: { trigger: 'axis',
      formatter: (ps) => {
        if (!ps.length) return ''
        let s = `${bundle.cats[ps[0].dataIndex]}`.replace('\n', ' ')
        for (const item of ps) {
          if (item.value == null) continue
          s += `<br/>${item.marker} ${item.seriesName}: ${item.value} kWh`
        }
        return s
      } },
    legend: { data: series.map(s => s.name), top: 0, type: 'scroll', textStyle: { fontSize: 10 } },
    grid: { left: 50, right: 20, top: series.length > 6 ? 56 : 36, bottom: 56 },
    xAxis: { type: 'category', data: bundle.cats, axisLabel: { fontSize: 10, interval: 0 } },
    yAxis: { type: 'value', name: 'kWh' },
    series,
  }, true)
}

function renderEnergyCharts() {
  renderEnergyBar()
  renderEnergyStageCmp()
  renderEnergyStage()
  renderEnergyGantt()
  if (selectedStagesSorted.value.length) nextTick(() => renderEnergyStageTrend())
}

// energyResult 变化时自动初始化电表选择并重画
watch(() => props.energyResult, (val) => {
  if (val && val.meters?.length) {
    const m = val.meters[0]
    selectedMeterId.value = m.meter_id
    selectedEnergyHouseId.value = m.houses?.[0]?.house_id ?? null
    _initSelectedStages(m.summary)
    nextTick(() => renderEnergyCharts())
  }
}, { immediate: true })

onUnmounted(disposeEnergyCharts)

defineExpose({ renderEnergyCharts, disposeEnergyCharts })
</script>
