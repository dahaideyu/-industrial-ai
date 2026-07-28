<template>
  <div v-if="chartData" class="mt-3 bg-white rounded-xl shadow-sm border border-gray-100 p-4">
    <h4 v-if="chartData.title" class="text-sm font-medium text-gray-700 mb-3">{{ chartData.title }}</h4>
    <div ref="chartRef" class="w-full" :style="{ height: '300px' }"></div>
  </div>
</template>

<script setup>
import { ref, onMounted, watch, onUnmounted } from 'vue'
import * as echarts from 'echarts'

const props = defineProps({
  chartData: { type: Object, default: null },
})

const chartRef = ref(null)
let chart = null

function renderChart() {
  if (!chartRef.value || !props.chartData) return
  if (!chart) {
    chart = echarts.init(chartRef.value)
  }

  const { type, title, x_key, y_key, data } = props.chartData
  if (!data || data.length === 0) return

  const colors = ['#f59e0b', '#3b82f6', '#10b981', '#ef4444', '#8b5cf6', '#ec4899', '#06b6d4', '#84cc16', '#f97316', '#6366f1']

  const categories = data.map(d => d[x_key])
  const values = data.map(d => d[y_key])

  const option = {
    tooltip: { trigger: 'axis' },
    grid: { left: '3%', right: '4%', bottom: '3%', containLabel: true },
    xAxis: type === 'bar' || type === 'line' ? { type: 'category', data: categories } : undefined,
    yAxis: type !== 'pie' ? { type: 'value' } : undefined,
    series: [{
      type: type || 'bar',
      data: type === 'pie' ? data.map((d, i) => ({ name: d[x_key], value: d[y_key] })) : values,
      itemStyle: { color: (params) => colors[params.dataIndex % colors.length] },
    }],
  }

  chart.setOption(option, true)
}

onMounted(() => renderChart())
watch(() => props.chartData, () => renderChart(), { deep: true })

const resizeHandler = () => chart?.resize()
window.addEventListener('resize', resizeHandler)
onUnmounted(() => {
  window.removeEventListener('resize', resizeHandler)
  chart?.dispose()
})
</script>
