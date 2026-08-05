<template>
  <div class="bg-white rounded-xl border border-gray-100 shadow-sm p-5">
    <div class="flex items-center justify-between mb-3 flex-wrap gap-2">
      <span class="text-xs font-bold text-gray-400 uppercase tracking-wider">
        ① 状态划分          <span v-if="pulseParamDisplay"> — 基于脉搏 {{ pulseParamDisplay }}</span>
      </span>
    </div>
    <div v-if="!stateResult" class="text-center py-8 text-gray-400 text-sm">按上方时间范围自动分析状态划分</div>
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
            共 {{ stateResult.timeline_totals?.segments }} 段。离线＝脉搏参数连续 {{ stateResult.timeline_gap_minutes }} 分钟以上没有上报（数据断档）；上方卡片同口径。
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
</template>

<script setup>
import { ref, onUnmounted } from 'vue'
import * as echarts from 'echarts'

const props = defineProps({
  stateResult: { type: Object, default: null },
  pulseParamDisplay: { type: String, default: '' },
})

function parseTime(str) {
  if (!str) return null
  const d = new Date(str.replace(' ', 'T'))
  return isNaN(d.getTime()) ? null : d.getTime()
}

// ── 状态切片图（运行/非运行/离线 时间轴）──
const stateTimelineEl = ref(null)
let stateTimelineChart = null
const STATE_META = {
  running: { name: '运行', color: '#22c55e' },
  idle: { name: '非运行', color: '#f59e0b' },
  offline: { name: '离线', color: '#d1d5db' },
}

function disposeStateTimeline() {
  if (stateTimelineChart && !stateTimelineChart.isDisposed()) stateTimelineChart.dispose()
  stateTimelineChart = null
}

function renderStateTimeline() {
  const tl = props.stateResult?.timeline
  if (!stateTimelineEl.value) return
  if (!tl || tl.length === 0) return
  if (!stateTimelineChart || stateTimelineChart.isDisposed()) {
    stateTimelineChart = echarts.init(stateTimelineEl.value)
  }

  // 三行：运行(0)、非运行(1)、离线(2)
  const categories = ['运行', '非运行', '离线']
  const stateToRow = { running: 0, idle: 1, offline: 2 }

  const data = tl.map((seg) => {
    const s = parseTime(seg.start)
    const e = parseTime(seg.end)
    const row = stateToRow[seg.state] ?? 2
    const color = STATE_META[seg.state]?.color || '#d1d5db'
    return {
      value: [row, s, e, e - s],
      itemStyle: { color, borderRadius: 2 },
      state: seg.state,
      hours: seg.hours,
    }
  })

  stateTimelineChart.setOption({
    animation: false,
    grid: { left: 70, right: 20, top: 8, bottom: 52 },
    tooltip: {
      confine: true,
      trigger: 'item',
      formatter: (p) => {
        if (!p.data || !p.data.value) return ''
        const meta = STATE_META[p.data.state] || {}
        const fmt = (t) => new Date(t).toLocaleString('zh-CN', { hour12: false, month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
        return `<b>${meta.name || p.data.state}</b><br/>${fmt(p.value[1])} ~ ${fmt(p.value[2])}<br/>时长 ${p.data.hours} 小时`
      },
    },
    xAxis: {
      type: 'time',
      axisLabel: {
        fontSize: 11, color: '#6b7280', hideOverlap: true,
        formatter: function (value) {
          const d = new Date(value)
          const pad = (n) => String(n).padStart(2, '0')
          return `${pad(d.getMonth()+1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
        },
      },
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
  }, true)
  stateTimelineChart.resize()
}

function resizeStateTimeline() {
  if (stateTimelineChart && !stateTimelineChart.isDisposed()) stateTimelineChart.resize()
}

onUnmounted(disposeStateTimeline)

defineExpose({ renderStateTimeline, disposeStateTimeline, resizeStateTimeline })
</script>
