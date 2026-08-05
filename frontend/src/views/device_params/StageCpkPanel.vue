<template>
  <div class="bg-white rounded-xl border border-gray-100 shadow-sm p-5">
    <div class="flex items-center justify-between mb-3 flex-wrap gap-2">
      <span class="text-xs font-bold text-gray-400 uppercase tracking-wider">④ 阶段 — CPK / 公差 / 能耗逐段分析</span>
    </div>
    <div v-if="!stageCpkResult" class="text-center py-8 text-gray-400 text-sm">按上方时间范围自动分析逐段 CPK</div>
    <div v-else class="space-y-3">
        <div v-if="stageCpkResult.source === 'loading'" class="text-center py-12 text-gray-400">⏳ 计算中...</div>
        <div v-else-if="stageCpkResult.source === 'error'" class="text-center py-12 text-gray-400">{{ stageCpkResult.msg }}</div>
        <template v-else>
          <div v-if="stageCpkResult.boundary_dropped_batch_ids?.length"
               class="px-3 py-2 rounded-lg bg-amber-50 border border-amber-100 text-xs text-amber-700">
            ⚠ 已排除窗口首尾各1个批次（#{{ stageCpkResult.boundary_dropped_batch_ids.join('、#') }}），避免边界截断样本拉偏统计；待机阶段(阶段{{ stageCpkResult.lawn_code }})不计入任何阶段统计
          </div>
          <div v-for="s in stageCpkResult.stages" :key="s.stage" class="border border-gray-100 rounded-lg p-3">
            <div class="text-xs font-bold text-gray-700 mb-2">阶段 {{ s.stage }}</div>

            <div class="text-xs text-gray-600 mb-1" v-if="s.duration_cpk">
              <template v-if="s.duration_cpk.cpk != null">
                时长：{{ s.duration_cpk.mean_min }}±{{ s.duration_cpk.std_min }}分钟，
                规格[{{ s.duration_cpk.spec_low_min }}, {{ s.duration_cpk.spec_high_min }}]，
                CPK={{ s.duration_cpk.cpk }}，超差 {{ s.duration_cpk.out_of_spec_count }}/{{ s.duration_cpk.n }}
                ({{ s.duration_cpk.out_of_spec_ratio }}%)
              </template>
              <template v-else>时长：{{ s.duration_cpk.note }}</template>
            </div>

            <div v-if="Object.keys(s.param_stats || {}).length" class="text-xs text-gray-500 space-y-0.5 mb-1">
              <div v-for="(stat, pname) in s.param_stats" :key="pname">
                {{ stat.display_name }}：均值 {{ stat.mean }}{{ stat.unit }} (±{{ stat.std }})
                <span v-if="stat.cpk != null">，规格[{{ stat.spec_low }}, {{ stat.spec_high }}]，CPK={{ stat.cpk }}</span>
              </div>
            </div>

            <!-- 与②能耗Tab同一套插值算法、同一电表口径，两处数字必须一致 -->
            <div v-if="s.energy_avg != null" class="text-xs text-gray-500 mb-1">
              阶段平均能耗：{{ s.energy_avg }}
              <span v-if="s.energy_meter" class="text-gray-400">（电表 {{ s.energy_meter }}）</span>
              <span v-if="s.energy_dropped" class="ml-1 text-amber-600"
                    :title="`该阶段有 ${s.energy_dropped} 次因电表读数回绕/重置被剔除，均值按剩余次数计算`">−{{ s.energy_dropped }}</span>
            </div>

            <!-- 单阶段能耗波动：跟时长同一套 CPK+超差算法，只对主电表算 -->
            <div class="text-xs text-gray-600 mb-1" v-if="s.energy_cpk">
              <template v-if="s.energy_cpk.cpk != null">
                能耗波动：{{ s.energy_cpk.mean_kwh }}±{{ s.energy_cpk.std_kwh }}kWh，
                规格[{{ s.energy_cpk.spec_low_kwh }}, {{ s.energy_cpk.spec_high_kwh }}]，
                CPK={{ s.energy_cpk.cpk }}，超差 {{ s.energy_cpk.out_of_spec_count }}/{{ s.energy_cpk.n }}
                ({{ s.energy_cpk.out_of_spec_ratio }}%)
              </template>
              <template v-else>能耗波动：{{ s.energy_cpk.note }}</template>
            </div>

            <div v-if="s.ai_insight" class="text-xs text-indigo-700 bg-indigo-50 rounded p-2 mt-1">💡 {{ s.ai_insight }}</div>
          </div>
        </template>
    </div>
  </div>
</template>

<script setup>
defineProps({
  stageCpkResult: { type: Object, default: null },
})
</script>
