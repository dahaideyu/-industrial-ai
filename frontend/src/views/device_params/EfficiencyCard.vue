<template>
  <div class="bg-white rounded-xl border border-gray-100 shadow-sm p-5">
    <div class="flex items-center justify-between mb-3 flex-wrap gap-2">
      <span class="text-xs font-bold text-gray-400 uppercase tracking-wider">效率 — 资产利用率（老板视角） vs 设备运转率（班长视角）</span>
    </div>
    <div v-if="!stateResult" class="text-center py-8 text-gray-400 text-sm">按上方时间范围自动计算效率</div>
    <div v-else-if="stateResult.source === 'loading'" class="text-center py-12 text-gray-400">⏳ 分析中...</div>
    <div v-else-if="stateResult.source === 'error'" class="text-center py-12 text-gray-400">{{ stateResult.msg }}</div>
    <template v-else>
      <div class="space-y-3">
        <div v-if="stateResult.truncate_note" class="bg-amber-50 border border-amber-200 rounded-lg p-2.5 text-xs text-amber-700">
          ⚠ {{ stateResult.truncate_note }}
        </div>
          <div class="grid grid-cols-2 gap-3 text-center">
            <div class="bg-indigo-50 rounded-lg p-3">
              <div class="text-indigo-700 font-bold text-xl">{{ stateResult.utilization }}%</div>
              <div class="text-indigo-600 text-xs">🏢 资产利用率（老板视角）</div>
              <div class="text-gray-400 text-[10px]">运行 / {{ stateResult.total_hours }}h × 100%</div>
            </div>
            <div class="bg-emerald-50 rounded-lg p-3">
              <div class="text-emerald-700 font-bold text-xl">{{ stateResult.operation_rate ?? stateResult.availability }}%</div>
              <div class="text-emerald-600 text-xs">🔧 设备运转率（班长视角）</div>
              <div class="text-gray-400 text-[10px]">运行 / (总时长 - 离线时间) × 100%</div>
            </div>
          </div>
          <div v-if="stateResult.daily_breakdown?.length" class="border rounded-lg">
            <div class="px-3 py-2 bg-gray-50 text-xs font-bold text-gray-500 border-b">每日明细（点击展开）</div>
            <div v-for="d in stateResult.daily_breakdown" :key="d.date"
              class="px-3 py-1.5 border-b border-gray-50 text-xs flex items-center gap-3 cursor-pointer hover:bg-gray-50"
              @click="d._open = !d._open">
              <span class="w-20">{{ d.date.slice(5) }}</span>
              <span class="text-green-600 w-12 text-right">{{ d.running_h }}h</span>
              <span class="text-amber-600 w-12 text-right">{{ d.idle_h }}h</span>
              <span class="text-gray-400 w-12 text-right">{{ d.offline_h }}h</span>
              <span class="font-bold w-12 text-right">{{ d.operation_rate ?? d.utilization }}%</span>
              <span class="text-gray-400">{{ d.segments }}次切换</span>
            </div>
          </div>
      </div>
    </template>
  </div>
</template>

<script setup>
defineProps({
  stateResult: { type: Object, default: null },
})
</script>
