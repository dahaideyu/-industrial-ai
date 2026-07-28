<template>
  <div ref="chartContainer" class="w-full" :style="{ height }"></div>
</template>

<script setup>
import { nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import * as echarts from 'echarts/core'
import { LineChart } from 'echarts/charts'
import {
  DataZoomComponent,
  GridComponent,
  MarkAreaComponent,
  TooltipComponent,
} from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'

echarts.use([
  LineChart,
  DataZoomComponent,
  GridComponent,
  MarkAreaComponent,
  TooltipComponent,
  CanvasRenderer,
])

const props = defineProps({
  height: { type: String, required: true },
  seriesData: { type: Object, required: true },
  seriesKeys: { type: Array, required: true },
  visibleKeys: { type: Array, required: true },
  displayNames: { type: Object, required: true },
  paramUnits: { type: Object, required: true },
  runningPeriods: { type: Array, required: true },
  colors: { type: Array, required: true },
})

const chartContainer = ref(null)
let chartInstance = null

function parseTime(str) {
  if (!str) return null
  const d = new Date(str.replace(' ', 'T'))
  return isNaN(d.getTime()) ? null : d.getTime()
}

function initChart() {
  if (!chartContainer.value || props.seriesKeys.length === 0) return
  chartInstance = echarts.init(chartContainer.value)
  updateChart()
}

function updateChart() {
  if (!chartInstance || chartInstance.isDisposed()) return

  const visibleCount = props.visibleKeys.length
  if (visibleCount === 0) {
    chartInstance.clear()
    return
  }

  const hasRunningStatus = props.runningPeriods.length > 0
  const statusHeight = 32
  const topOffset = hasRunningStatus ? statusHeight + 12 : 8
  const bottomOffset = 60
  const gap = 4
  const stripHeight = 80

  const grids = []
  const xAxes = []
  const yAxes = []
  const seriesList = []
  let gridIdx = 0

  if (hasRunningStatus) {
    grids.push({ left: 70, right: 16, top: 4, height: statusHeight })
    xAxes.push({
      type: 'time',
      gridIndex: gridIdx,
      axisLine: { show: false },
      axisTick: { show: false },
      axisLabel: {
        show: true,
        color: '#9ca3af',
        fontSize: 9,
        formatter: { month: 'MM-dd', day: 'MM-dd', hour: 'HH:mm', minute: 'HH:mm' },
        inside: true,
        hideOverlap: true,
      },
      splitLine: { show: false },
    })
    yAxes.push({
      type: 'value',
      gridIndex: gridIdx,
      min: 0,
      max: 1,
      show: false,
      name: '运行状态',
      nameLocation: 'middle',
      nameGap: 30,
      nameTextStyle: { color: '#22c55e', fontSize: 10, fontWeight: 600 },
    })

    const sortedPeriods = [...props.runningPeriods].sort((a, b) => parseTime(a.start_time) - parseTime(b.start_time))
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
      seriesList.push({
        name: '运行状态',
        type: 'line',
        step: 'start',
        symbol: 'none',
        lineStyle: { width: 0 },
        itemStyle: { color: '#22c55e' },
        areaStyle: { color: 'rgba(34, 197, 94, 0.45)' },
        data: statusData,
        xAxisIndex: gridIdx,
        yAxisIndex: gridIdx,
        connectNulls: false,
        silent: true,
      })

      const markAreas = []
      for (const p of sortedPeriods) {
        const s = parseTime(p.start_time)
        const e = p.end_time ? parseTime(p.end_time) : Date.now()
        if (s && e) {
          markAreas.push([{ xAxis: s, name: '运行中' }, { xAxis: e }])
        }
      }
      seriesList.push({
        name: '运行标注',
        type: 'line',
        symbol: 'none',
        lineStyle: { width: 0 },
        data: [],
        xAxisIndex: gridIdx,
        yAxisIndex: gridIdx,
        markArea: {
          silent: true,
          itemStyle: { color: 'transparent' },
          label: {
            show: true,
            position: 'insideTop',
            color: '#16a34a',
            fontSize: 9,
            fontWeight: 500,
            formatter: (p) => p.name || '',
          },
          data: markAreas,
        },
      })
    }
    gridIdx++
  }

  for (let i = 0; i < visibleCount; i++) {
    const top = topOffset + i * (stripHeight + gap)
    const isLast = i === visibleCount - 1
    const key = props.visibleKeys[i]
    const idx = props.seriesKeys.indexOf(key)
    const color = props.colors[idx % props.colors.length]
    const displayName = props.displayNames[key] || key
    const unit = props.paramUnits[key] || ''

    grids.push({ left: 70, right: 16, top, height: stripHeight })
    xAxes.push({
      type: 'time',
      gridIndex: gridIdx,
      axisLine: { show: isLast, lineStyle: { color: '#e5e7eb' } },
      axisTick: { show: isLast, lineStyle: { color: '#d1d5db' } },
      axisLabel: {
        show: isLast,
        color: '#6b7280',
        fontSize: 11,
        formatter: { year: '{yyyy}', month: '{MM}-{dd}', day: '{MM}-{dd}', hour: '{HH}:{mm}', minute: '{HH}:{mm}' },
        hideOverlap: true,
      },
      splitLine: {
        show: true,
        lineStyle: { color: '#f3f4f6', type: 'dashed' },
      },
      min: hasRunningStatus ? 'dataMin' : undefined,
      max: hasRunningStatus ? 'dataMax' : undefined,
    })
    yAxes.push({
      type: 'value',
      gridIndex: gridIdx,
      scale: true,
      axisLine: { show: false },
      axisTick: { show: false },
      splitLine: { lineStyle: { color: '#f3f4f6', type: 'dashed' } },
      axisLabel: { show: false },
      name: unit ? `${displayName} (${unit})` : displayName,
      nameLocation: 'middle',
      nameGap: 30,
      nameTextStyle: { color, fontSize: 10, fontWeight: 500 },
    })

    const data = props.seriesData[key] || []
    const timeMap = new Map()
    for (const d of data) {
      if (d.time) {
        timeMap.set(d.time, typeof d.value === 'number' ? d.value : null)
      }
    }
    const allTimes = [...timeMap.keys()].sort()
    const values = allTimes.map((t) => timeMap.get(t) ?? null)

    const paramSeries = {
      name: displayName,
      type: 'line',
      smooth: true,
      symbol: 'none',
      lineStyle: { width: 1.5, color },
      itemStyle: { color },
      data: values.map((v, index) => [parseTime(allTimes[index]), v]),
      connectNulls: true,
      xAxisIndex: gridIdx,
      yAxisIndex: gridIdx,
    }

    if (hasRunningStatus) {
      const sortedPeriods = [...props.runningPeriods].sort((a, b) => parseTime(a.start_time) - parseTime(b.start_time))
      const markAreaData = []
      for (const p of sortedPeriods) {
        const s = parseTime(p.start_time)
        const e = p.end_time ? parseTime(p.end_time) : Date.now()
        if (s && e) {
          markAreaData.push([{ xAxis: s, itemStyle: { color: 'rgba(34,197,94,0.06)' } }, { xAxis: e }])
        }
      }
      paramSeries.markArea = { silent: true, data: markAreaData }
    }

    seriesList.push(paramSeries)
    gridIdx++
  }

  const allXIndices = Array.from({ length: gridIdx }, (_, i) => i)
  const option = {
    tooltip: {
      trigger: 'axis',
      backgroundColor: 'rgba(255,255,255,0.96)',
      borderColor: '#e5e7eb',
      textStyle: { color: '#374151', fontSize: 12 },
      order: 'valueDesc',
      formatter(params) {
        if (!params || params.length === 0) return ''
        const pad = (n) => String(n).padStart(2, '0')
        let timeVal = params[0].axisValue
        for (const p of params) {
          if (p.value && typeof p.value[0] === 'number' && p.value[0] > 1e12) {
            const d = new Date(p.value[0])
            timeVal = `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
            break
          }
        }
        let html = `<div style="font-weight:600;margin-bottom:4px">${timeVal}</div>`
        for (const p of params) {
          if (p.seriesName === '运行状态') {
            html += `<div style="display:flex;justify-content:space-between;gap:16px">
              <span>${p.marker} ${p.seriesName}</span>
              <span style="font-weight:600;color:#22c55e">运行中</span>
            </div>`
          }
        }
        for (const p of params) {
          if (p.seriesName !== '运行状态' && p.seriesName !== '运行标注') {
            const val = p.value && p.value[1] != null ? p.value[1] : '-'
            const pKey = Object.keys(props.displayNames).find((k) => props.displayNames[k] === p.seriesName) || p.seriesName
            const unit = props.paramUnits[pKey] || ''
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
        type: 'slider',
        xAxisIndex: allXIndices,
        start: 0,
        end: 100,
        height: 24,
        bottom: bottomOffset / 2,
        borderColor: '#e5e7eb',
        backgroundColor: '#f9fafb',
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
}

watch(
  () => [
    props.height,
    props.visibleKeys,
    props.seriesData,
    props.displayNames,
    props.paramUnits,
    props.runningPeriods,
  ],
  async () => {
    await nextTick()
    if (!chartInstance) initChart()
    else {
      chartInstance.resize()
      updateChart()
    }
  },
  { deep: true },
)

onMounted(() => {
  initChart()
  window.addEventListener('resize', handleResize)
})

onUnmounted(() => {
  disposeChart()
  window.removeEventListener('resize', handleResize)
})
</script>
