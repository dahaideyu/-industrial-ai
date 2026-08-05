<template>
  <div class="space-y-6">
    <div class="bg-white rounded-xl border border-gray-100 shadow-sm p-5">
      <div class="flex items-center justify-between mb-3 flex-wrap gap-2">
        <span class="text-xs font-bold text-gray-400 uppercase tracking-wider">③ KPI — 产量 / OEE / 节拍 / 能耗</span>
      </div>
      <div v-if="!kpiResult" class="text-center py-8 text-gray-400 text-sm">按上方时间范围自动计算 KPI</div>
      <div v-else class="space-y-3">
          <div v-if="kpiResult.source === 'loading'" class="text-center py-12 text-gray-400">⏳ 计算中...</div>
          <div v-else-if="kpiResult.source === 'error'" class="text-center py-12 text-gray-400">{{ kpiResult.msg }}</div>
          <template v-else>
            <div v-if="kpiCards.length > 1" class="text-xs text-gray-500 text-center">
              按"房子形状"识别出 {{ kpiCards.length - 1 }} 种产品型号，最后一张是设备整体汇总
            </div>
            <div v-if="kpiResult.type_insight" class="bg-amber-50 rounded-lg p-3 text-xs text-amber-800 leading-relaxed">
              🔍 型号划分判断：{{ kpiResult.type_insight }}
            </div>

            <!-- 标准节拍：性能效率的固定基准（设备级）。冻结不随窗口漂移，设备变慢才看得出来 -->
            <div v-if="kpiResult.std_cycle" class="flex items-center flex-wrap gap-2 text-xs bg-gray-50 border border-gray-100 rounded-lg p-2.5">
              <span class="text-gray-500">标准节拍基准</span>
              <template v-if="!editingStdCycle">
                <span class="font-bold text-gray-800">{{ kpiResult.std_cycle.min ?? '未标定' }}</span>
                <span v-if="kpiResult.std_cycle.min != null" class="text-gray-400">分钟</span>
                <span class="px-1.5 py-0.5 rounded text-[10px]"
                      :class="kpiResult.std_cycle.source === 'manual' ? 'bg-emerald-50 text-emerald-600' : 'bg-amber-50 text-amber-600'">
                  {{ kpiResult.std_cycle.source === 'manual' ? '工艺已确认' : '自动标定 · 待工艺确认' }}
                </span>
                <span v-if="kpiResult.std_cycle.calibrated_at" class="text-[10px] text-gray-400">{{ kpiResult.std_cycle.calibrated_at }}</span>
                <button @click="startEditStdCycle" class="px-2 py-0.5 rounded border border-gray-200 text-gray-600 hover:bg-white">修改</button>
                <button @click="recalibrateStdCycle" :disabled="stdCycleSaving"
                        class="px-2 py-0.5 rounded border border-gray-200 text-gray-500 hover:bg-white"
                        title="清除当前基准，按最近一次分析的数据重新自动标定">重新标定</button>
              </template>
              <template v-else>
                <input v-model.number="stdCycleDraft" type="number" step="0.1" min="0"
                       class="w-24 px-2 py-0.5 border border-gray-200 rounded" />
                <span class="text-gray-400">分钟</span>
                <button @click="saveStdCycle" :disabled="stdCycleSaving"
                        class="px-2 py-0.5 rounded bg-indigo-600 text-white hover:bg-indigo-700">保存并重算</button>
                <button @click="editingStdCycle = false" class="px-2 py-0.5 rounded border border-gray-200 text-gray-600">取消</button>
              </template>
              <span v-if="stdCycleErr" class="text-rose-500">{{ stdCycleErr }}</span>
              <span v-if="kpiResult.std_cycle.multi_type_warning" class="text-amber-600">
                ⚠ 识别到多个产品型号，不同型号节拍本就不同，设备级单一基准会失真
              </span>
            </div>

            <div v-for="kpi in kpiCards" :key="kpi.type_label" class="border border-gray-100 rounded-lg p-3 space-y-3">
              <div class="text-sm font-bold text-gray-700">
                {{ kpi.type_label }}
                <span v-if="kpi.batch_count != null" class="text-xs font-normal text-gray-400">（{{ kpi.batch_count }}个循环）</span>
              </div>
              <div v-if="kpi.signature" class="text-[10px] text-gray-400">特征：{{ kpi.signature }}</div>

              <div class="grid grid-cols-3 gap-3 text-center">
                <div class="bg-sky-50 rounded-lg p-3">
                  <div class="text-sky-700 font-bold text-lg">{{ kpi.total_cycles }}</div>
                  <div class="text-sky-600 text-xs">总循环数（房子）</div>
                </div>
                <div class="bg-green-50 rounded-lg p-3">
                  <div class="text-green-700 font-bold text-lg">{{ kpi.output_count }}</div>
                  <div class="text-green-600 text-xs">产量（已剔除空跑{{ kpi.empty_run_count }}次）</div>
                </div>
                <div class="bg-violet-50 rounded-lg p-3">
                  <div class="text-violet-700 font-bold text-lg">{{ kpi.pass_rate != null ? kpi.pass_rate + '%' : '—' }}</div>
                  <div class="text-violet-600 text-xs">合格率<span v-if="kpi.quality_status !== 'ok'">（{{ kpi.quality_status === 'no_confirmed_spec' ? '暂无已确认规格限' : kpi.quality_status }}）</span></div>
                </div>
              </div>

              <div class="bg-gray-50 rounded-lg p-3">
                <div class="text-xs text-gray-500 mb-2">OEE = 可用率 × 性能效率 × 合格率</div>
                <div class="flex items-center justify-center gap-2 text-sm">
                  <span class="text-emerald-700 font-medium">{{ kpi.availability != null ? kpi.availability + '%' : '—' }}</span>
                  <span class="text-gray-300">×</span>
                  <span class="text-amber-700 font-medium">{{ kpi.performance != null ? kpi.performance : '—' }}</span>
                  <span class="text-gray-300">×</span>
                  <span class="text-violet-700 font-medium">{{ kpi.pass_rate != null ? (kpi.pass_rate / 100).toFixed(2) : '—' }}</span>
                  <span class="text-gray-300">=</span>
                  <span class="text-gray-900 font-bold text-lg">{{ kpi.oee != null ? kpi.oee + '%' : '—' }}</span>
                </div>
                <div v-if="kpi.oee_note" class="text-center text-[10px] text-gray-400 mt-1">{{ kpi.oee_note }}</div>
                <div class="text-center text-[10px] text-gray-400 mt-1">
                  性能效率 = 标准节拍 / 实际平均节拍 · 可用率 = {{ kpi.availability_basis || '运行 ÷ 在线时长' }}
                </div>
                <div v-if="kpi.utilization != null" class="text-center text-[10px] text-gray-400">
                  资产利用率（含停机的日历口径）{{ kpi.utilization }}%
                </div>
              </div>

              <div class="grid grid-cols-2 gap-3">
                <div class="bg-white border border-gray-100 rounded-lg p-3">
                  <div class="text-xs text-gray-500 mb-1">节拍（有效批次）</div>
                  <div class="text-xs text-gray-700">均值 {{ kpi.cycle_time.mean_min ?? '—' }} 分钟</div>
                  <div class="text-xs text-gray-700">中位 {{ kpi.cycle_time.median_min ?? '—' }} 分钟</div>
                  <div class="text-xs text-gray-700">P10 {{ kpi.cycle_time.p10_min ?? '—' }} 分钟</div>
                </div>
                <div class="bg-white border border-gray-100 rounded-lg p-3">
                  <div class="text-xs text-gray-500 mb-1">能耗</div>
                  <div class="text-xs text-gray-700">有效 {{ kpi.energy.valid_kwh }}<span v-if="kpi.energy.valid_ratio != null" class="text-gray-400"> ({{ kpi.energy.valid_ratio }}%)</span></div>
                  <div class="text-xs text-gray-700">空跑 {{ kpi.energy.empty_run_kwh }}<span v-if="kpi.energy.empty_run_ratio != null" class="text-gray-400"> ({{ kpi.energy.empty_run_ratio }}%)</span></div>
                  <div class="text-xs text-gray-700">单件 {{ kpi.energy.per_unit_kwh ?? '—' }}</div>
                </div>
              </div>

              <div v-if="kpi.empty_run_status !== 'ok'" class="text-[10px] text-gray-400 text-center">
                空跑判定：{{ kpi.empty_run_status === 'no_weight_param' ? '该设备没有已识别的重量类参数，本次未剔除空跑（产量=总循环数）' : kpi.empty_run_status }}
              </div>

              <div v-if="kpi.ai_insight" class="bg-indigo-50 rounded-lg p-3 text-xs text-indigo-800 leading-relaxed">
                💡 {{ kpi.ai_insight }}
              </div>
            </div>
          </template>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'
import client from '../../api/client.js'

const props = defineProps({
  kpiResult: { type: Object, default: null },
  deviceCode: { type: String, default: '' },
})
const emit = defineEmits(['reload'])

// 识别出≥2种型号时，逐型号卡片 + 末尾追加"整体"汇总卡片；只有一种型号时只显示整体卡片
const kpiCards = computed(() => {
  const r = props.kpiResult
  if (!r || r.source) return []
  if (r.product_types && r.product_types.length >= 2) return [...r.product_types, r.overall]
  return r.overall ? [r.overall] : []
})

const editingStdCycle = ref(false)
const stdCycleDraft = ref(null)
const stdCycleSaving = ref(false)
const stdCycleErr = ref('')

function startEditStdCycle() {
  stdCycleDraft.value = props.kpiResult?.std_cycle?.min ?? null
  stdCycleErr.value = ''
  editingStdCycle.value = true
}

async function _postKpiConfig(payload, okThen) {
  stdCycleSaving.value = true
  stdCycleErr.value = ''
  try {
    const res = await client.post('/device-params/kpi-config', {
      device_code: props.deviceCode, ...payload,
    })
    if (res.code === 200) {
      editingStdCycle.value = false
      await okThen?.()
    } else {
      stdCycleErr.value = res.msg || '保存失败'
    }
  } catch (err) {
    stdCycleErr.value = err.response?.data?.msg || err.message
  } finally {
    stdCycleSaving.value = false
  }
}

// 改了基准，后端会把该设备所有班次的 KPI 缓存作废（旧基准算的 performance 已失效），
// 让父组件 force 重算当前班次的 KPI
const _reloadKpi = () => emit('reload')

// 工艺确认的基准记为 manual，此后不再被自动标定覆盖
function saveStdCycle() {
  if (!(stdCycleDraft.value > 0)) {
    stdCycleErr.value = '标准节拍需大于 0'
    return
  }
  return _postKpiConfig({ std_cycle_min: stdCycleDraft.value }, _reloadKpi)
}

// 传 0 清除标定 → 下次分析用当前窗口 P10 重新自动标定
function recalibrateStdCycle() {
  return _postKpiConfig({ std_cycle_min: 0 }, _reloadKpi)
}
</script>
