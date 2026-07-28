<template>
  <div class="p-6 h-full overflow-y-auto">
    <div class="mb-6">
      <h2 class="text-lg font-semibold text-gray-800">问答监控</h2>
      <p class="text-sm text-gray-500 mt-1">查询统计、性能指标和意图分布</p>
    </div>

    <!-- Stat cards -->
    <div class="grid grid-cols-3 gap-4 mb-6">
      <div v-for="c in cards" :key="c.label" class="rounded-xl border-t-2 bg-white shadow-sm p-4" :style="{ borderTopColor: c.color }">
        <div class="text-2xl font-bold text-gray-800">{{ c.value }}</div>
        <div class="text-xs text-gray-400 mt-1">{{ c.label }}</div>
      </div>
    </div>

    <!-- Charts row -->
    <div class="grid grid-cols-2 gap-4">
      <!-- Intent distribution -->
      <div class="bg-white rounded-xl border border-gray-100 p-4">
        <h3 class="text-sm font-semibold text-gray-700 mb-4">意图分布</h3>
        <div class="space-y-2">
          <div v-for="item in intentData" :key="item.label" class="flex items-center gap-2">
            <span class="text-xs text-gray-500 w-24 flex-shrink-0">{{ item.label }}</span>
            <div class="flex-1 h-5 bg-gray-100 rounded-full overflow-hidden">
              <div class="h-full rounded-full transition-all" :style="{ width: item.pct, background: item.color }" />
            </div>
            <span class="text-xs text-gray-400 w-10 text-right">{{ item.pct }}</span>
          </div>
        </div>
        <p class="text-xs text-gray-300 mt-3">* 演示数据，后续接入真实统计</p>
      </div>

      <!-- Performance overview -->
      <div class="bg-white rounded-xl border border-gray-100 p-4">
        <h3 class="text-sm font-semibold text-gray-700 mb-4">性能概览</h3>
        <div class="space-y-2">
          <div v-for="p in perfData" :key="p.label" class="flex items-center justify-between py-1.5 border-b border-gray-50">
            <span class="text-xs text-gray-500">{{ p.label }}</span>
            <span :class="['text-xs font-medium', p.warn ? 'text-red-500' : 'text-gray-700']">{{ p.value }}</span>
          </div>
        </div>
        <p class="text-xs text-gray-300 mt-3">* 演示数据，后续接入真实统计</p>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { getAdminStats } from '../../api/sqlQaClient.js'

const stats = ref(null)

onMounted(async () => {
  try { const d = await getAdminStats(); stats.value = d.stats } catch {}
})

const cards = [
  { label: '总查询次数', value: stats.value?.total_queries ?? '—', color: '#f59e0b' },
  { label: '成功查询', value: stats.value?.successful_queries ?? '—', color: '#10b981' },
  { label: '成功率', value: stats.value ? `${stats.value.success_rate}%` : '—', color: '#fbbf24' },
]

const intentData = [
  { label: '简单事实查询', pct: '65%', color: '#f59e0b' },
  { label: '聚合统计', pct: '20%', color: '#8b5cf6' },
  { label: '文档查询', pct: '10%', color: '#10b981' },
  { label: '多跳关联', pct: '3%', color: '#fbbf24' },
  { label: '元问题', pct: '2%', color: '#ef4444' },
]

const perfData = [
  { label: '平均响应时间', value: '3.2s' },
  { label: '实体检索 P50', value: '320ms' },
  { label: 'SQL 生成 P50', value: '2.1s' },
  { label: '数据库查询 P50', value: '45ms' },
  { label: '慢查询 (>5s)', value: '3 条', warn: true },
]
</script>
