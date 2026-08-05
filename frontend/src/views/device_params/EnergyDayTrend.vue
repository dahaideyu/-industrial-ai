<template>
  <div class="bg-white rounded-xl border border-gray-100 shadow-sm p-5">
    <div class="flex items-center justify-between mb-3 flex-wrap gap-2">
      <span class="text-xs font-bold text-gray-400 uppercase tracking-wider">
        多日汇总 — 按天(06:00~次日06:00) 独立掐头去尾<span v-if="days.length"> · 共 {{ days.length }} 天</span>
      </span>
      <span v-if="result?.truncate_note" class="text-[11px] text-amber-600">⚠ {{ result.truncate_note }}</span>
    </div>

    <div v-if="loading" class="text-center py-8 text-gray-400 text-sm">⏳ 分析中...</div>
    <div v-else-if="!days.length" class="text-center py-8 text-gray-400 text-sm">该范围内暂无可汇总的天</div>
    <template v-else>
      <div class="border border-gray-100 rounded-lg p-3 mb-4">
        <div class="text-xs font-bold text-gray-500 mb-2">每日单房子均值能耗（{{ primaryName }}，kWh · 已按天独立掐头去尾）</div>
        <div ref="trendEl" class="w-full" style="height: 260px"></div>
      </div>

      <div class="border border-gray-100 rounded-lg overflow-hidden">
        <table class="w-full text-xs">
          <thead class="text-gray-400">
            <tr class="border-b border-gray-100">
              <th class="text-left px-3 py-1.5 font-medium">天</th>
              <th class="text-right px-3 py-1.5 font-medium">房子数(掐头去尾后)</th>
              <th class="text-right px-3 py-1.5 font-medium">单房子均值(kWh)</th>
              <th class="text-right px-3 py-1.5 font-medium">有效能耗·运行(kWh)</th>
              <th class="text-right px-3 py-1.5 font-medium">无效能耗·待机(kWh)</th>
              <th class="px-3 py-1.5"></th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="d in days" :key="d.key" class="border-b border-gray-50"
                :class="d.key === selectedDayKey ? 'bg-indigo-50/40' : ''">
              <td class="px-3 py-1.5">
                {{ d.label }}
                <span v-if="!d.closed" class="ml-1 text-[10px] text-amber-500">进行中</span>
                <span v-else-if="d.partial" class="ml-1 text-[10px] text-gray-400">不完整</span>
              </td>
              <td class="px-3 py-1.5 text-right">{{ d.summary?.house_count ?? '—' }}</td>
              <td class="px-3 py-1.5 text-right text-cyan-700">{{ d.summary?.avg_primary_kwh ?? '—' }}</td>
              <td class="px-3 py-1.5 text-right text-emerald-700">{{ d.summary?.valid_primary_kwh ?? '—' }}</td>
              <td class="px-3 py-1.5 text-right text-rose-700">{{ d.summary?.invalid_primary_kwh ?? '—' }}</td>
              <td class="px-3 py-1.5 text-right">
                <button v-if="d.energyResult" @click="selectDay(d)" class="text-[11px] text-indigo-600 hover:underline">
                  {{ d.key === selectedDayKey ? '收起' : '查看详情' }}
                </button>
                <span v-else class="text-[11px] text-gray-300">{{ d.error || '无数据' }}</span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <div v-if="selectedDay" class="mt-4">
        <div class="text-xs font-bold text-gray-500 mb-2">{{ selectedDay.label }} 详情</div>
        <EnergyBreakdown :energy-result="selectedDay.energyResult" />
      </div>
    </template>
  </div>
</template>

<script setup>
import { ref, computed, watch, nextTick, onUnmounted } from 'vue'
import * as echarts from 'echarts'
import EnergyBreakdown from './EnergyBreakdown.vue'

const props = defineProps({
  result: { type: Object, default: null },
  loading: { type: Boolean, default: false },
})

const selectedDayKey = ref(null)
const trendEl = ref(null)
let trendChart = null

// 后端 analyze_one_shift() 对班次/天统一用 "shift" 这个字段名返回窗口元信息，
// 这里只是取用，不代表这是班次。
const days = computed(() => {
  const list = props.result?.days || []
  return list.map((d) => {
    const meta = d.shift || {}
    const energyRaw = d.results?.energy
    const energyResult = (energyRaw && !energyRaw.error) ? energyRaw : null
    const meter = energyResult?.meters?.[0] || null
    return {
      key: meta.key,
      label: meta.label,
      closed: meta.closed,
      partial: meta.partial,
      summary: meter?.summary || null,
      energyResult,
      error: energyRaw?.msg || (d.skipped ? '该天尚未结束' : null),
    }
  })
})

const primaryName = computed(() => {
  for (const d of days.value) {
    const nm = d.energyResult?.meters?.[0]?.energy_points?.primary?.display_name
    if (nm) return nm
  }
  return '组合有功总电能'
})

const selectedDay = computed(() => days.value.find((d) => d.key === selectedDayKey.value) || null)

function selectDay(d) {
  selectedDayKey.value = selectedDayKey.value === d.key ? null : d.key
}

function renderTrend() {
  if (!trendEl.value) return
  const list = days.value.filter((d) => d.summary)
  if (!list.length) return
  if (!trendChart || trendChart.isDisposed()) trendChart = echarts.init(trendEl.value)
  trendChart.setOption({
    tooltip: { trigger: 'axis' },
    grid: { left: 50, right: 20, top: 20, bottom: 40 },
    xAxis: { type: 'category', data: list.map((d) => d.label), axisLabel: { fontSize: 10, interval: 0 } },
    yAxis: { type: 'value', name: 'kWh' },
    series: [{
      type: 'line', smooth: true, symbol: 'circle', symbolSize: 6,
      data: list.map((d) => d.summary.avg_primary_kwh),
      itemStyle: { color: '#06b6d4' }, areaStyle: { opacity: 0.08 },
    }],
  }, true)
}

watch(() => props.result, () => {
  selectedDayKey.value = null
  nextTick(renderTrend)
}, { immediate: true })

onUnmounted(() => {
  if (trendChart && !trendChart.isDisposed()) trendChart.dispose()
})
</script>
