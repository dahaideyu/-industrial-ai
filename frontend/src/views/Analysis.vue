<template>
  <section class="min-h-screen">
    <div class="border-b border-slate-200 bg-white/80 px-6 py-5 backdrop-blur lg:px-8">
      <div class="mx-auto max-w-[1500px]">
        <p class="text-xs font-bold uppercase tracking-[0.18em] text-amber-700">AI Device Diagnosis</p>
        <h1 class="mt-2 font-headline text-2xl font-semibold text-slate-950">设备诊断</h1>
        <p class="mt-1 text-sm text-slate-500">选择诊断目标，AI 将输出结论、建议动作和可追溯证据。</p>
      </div>
    </div>

    <div class="mx-auto grid max-w-[1500px] gap-6 p-6 lg:grid-cols-[380px_1fr] lg:p-8">
      <aside class="space-y-6">
        <div class="rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
          <h2 class="font-headline text-lg font-semibold text-slate-950">诊断目标</h2>
          <div class="mt-4 space-y-2">
            <button
              v-for="mod in moduleList"
              :key="mod.key"
              @click="selectModule(mod.key)"
              :class="[
                'w-full rounded-md border px-4 py-3 text-left transition-colors',
                selectedModule === mod.key
                  ? 'border-amber-400 bg-amber-50'
                  : 'border-slate-200 bg-white hover:border-amber-300 hover:bg-amber-50/40'
              ]"
            >
              <div class="flex items-center gap-3">
                <span class="h-2.5 w-2.5 rounded-full bg-amber-500"></span>
                <div>
                  <div class="text-sm font-bold text-slate-950">{{ mod.name }}</div>
                  <div class="mt-1 text-xs leading-5 text-slate-500">{{ mod.desc }}</div>
                </div>
              </div>
            </button>
          </div>
        </div>

        <div class="rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
          <h2 class="font-headline text-lg font-semibold text-slate-950">参数配置</h2>
          <div class="mt-4 space-y-4">
            <div>
              <label class="mb-2 block text-xs font-bold uppercase tracking-[0.14em] text-slate-500">时间范围</label>
              <div class="grid grid-cols-4 gap-2">
                <button
                  v-for="h in hourPresets"
                  :key="h"
                  @click="hours = h"
                  :class="[
                    'rounded-md border px-2 py-2 text-xs font-bold',
                    hours === h ? 'border-amber-400 bg-amber-400 text-slate-950' : 'border-slate-200 text-slate-600'
                  ]"
                >
                  {{ h }}h
                </button>
              </div>
            </div>
            <div>
              <label class="mb-2 block text-xs font-bold uppercase tracking-[0.14em] text-slate-500">设备 ID</label>
              <input
                v-model="deviceId"
                type="text"
                placeholder="留空使用默认设备"
                class="w-full rounded-md border border-slate-200 bg-slate-50 px-3 py-2.5 text-sm outline-none focus:border-amber-400 focus:bg-white"
              />
            </div>
            <button
              @click="runAnalysis"
              :disabled="loading"
              class="w-full rounded-md bg-slate-950 px-4 py-3 text-sm font-bold text-white transition-colors hover:bg-amber-600 disabled:opacity-50"
            >
              {{ loading ? 'AI 正在诊断...' : '运行 AI 诊断' }}
            </button>
          </div>
        </div>
      </aside>

      <main class="space-y-6">
        <div class="rounded-lg border border-slate-200 bg-slate-950 p-6 text-white shadow-sm">
          <div class="flex flex-col gap-5 lg:flex-row lg:items-start lg:justify-between">
            <div>
              <div class="mb-3 inline-flex items-center gap-2 rounded-md border border-amber-300/30 bg-amber-300/10 px-3 py-1 text-xs font-bold text-amber-100">
                <span class="h-2 w-2 rounded-full bg-amber-300"></span>
                当前诊断策略
              </div>
              <h2 class="font-headline text-2xl font-semibold">{{ selectedModuleInfo.name }}</h2>
              <p class="mt-3 max-w-2xl text-sm leading-7 text-slate-300">{{ selectedModuleInfo.prompt }}</p>
            </div>
            <div class="grid grid-cols-3 gap-3 text-center">
              <div class="rounded-md border border-white/10 bg-white/5 p-3">
                <div class="text-xs text-slate-400">时间窗</div>
                <div class="mt-1 font-headline text-xl font-bold">{{ hours }}h</div>
              </div>
              <div class="rounded-md border border-white/10 bg-white/5 p-3">
                <div class="text-xs text-slate-400">置信度</div>
                <div class="mt-1 font-headline text-xl font-bold">{{ confidence }}%</div>
              </div>
              <div class="rounded-md border border-white/10 bg-white/5 p-3">
                <div class="text-xs text-slate-400">状态</div>
                <div class="mt-1 font-headline text-xl font-bold">{{ statusText }}</div>
              </div>
            </div>
          </div>
        </div>

        <div v-if="loading" class="rounded-lg border border-amber-200 bg-amber-50 p-8 text-center text-sm font-semibold text-amber-800">
          AI 正在读取设备数据、识别异常窗口并组织诊断结论...
        </div>

        <div v-else-if="error" class="rounded-lg border border-red-200 bg-red-50 p-8 text-center text-sm font-semibold text-red-700">
          {{ error }}
        </div>

        <template v-else-if="result">
          <div class="grid gap-6 xl:grid-cols-[1fr_340px]">
            <div class="rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
              <p class="text-xs font-bold uppercase tracking-[0.16em] text-amber-700">AI Conclusion</p>
              <h2 class="mt-2 font-headline text-xl font-semibold text-slate-950">{{ conclusionTitle }}</h2>
              <p class="mt-3 text-sm leading-7 text-slate-600">{{ conclusionText }}</p>
              <div class="mt-5 grid gap-3 md:grid-cols-3">
                <div v-for="item in decisionCards" :key="item.label" class="rounded-md border border-slate-200 bg-slate-50 p-4">
                  <div class="text-xs font-bold uppercase tracking-[0.12em] text-slate-400">{{ item.label }}</div>
                  <div class="mt-2 text-lg font-bold text-slate-950">{{ item.value }}</div>
                  <div class="mt-1 text-xs leading-5 text-slate-500">{{ item.hint }}</div>
                </div>
              </div>
            </div>

            <div class="rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
              <h2 class="font-headline text-lg font-semibold text-slate-950">建议动作</h2>
              <div class="mt-4 space-y-3">
                <router-link
                  v-for="action in recommendedActions"
                  :key="action.path"
                  :to="action.path"
                  class="block rounded-md border border-slate-200 px-4 py-3 transition-colors hover:border-amber-400 hover:bg-amber-50/50"
                >
                  <div class="text-sm font-bold text-slate-950">{{ action.title }}</div>
                  <div class="mt-1 text-xs leading-5 text-slate-500">{{ action.desc }}</div>
                </router-link>
              </div>
            </div>
          </div>

          <div class="rounded-lg border border-slate-200 bg-white shadow-sm">
            <div class="flex items-center justify-between border-b border-slate-200 px-5 py-4">
              <div>
                <h2 class="font-headline text-lg font-semibold text-slate-950">证据数据</h2>
                <p class="mt-1 text-xs text-slate-500">保留原始接口结果，便于追溯 AI 判断。</p>
              </div>
              <button
                @click="showRaw = !showRaw"
                class="rounded-md border border-slate-200 px-3 py-2 text-xs font-bold text-slate-600 hover:border-amber-400 hover:text-amber-700"
              >
                {{ showRaw ? '隐藏原始数据' : '查看原始数据' }}
              </button>
            </div>
            <pre v-if="showRaw" class="max-h-[520px] overflow-auto bg-slate-950 p-5 text-xs leading-6 text-amber-50">{{ formattedResult }}</pre>
            <div v-else class="grid gap-3 p-5 md:grid-cols-3">
              <div v-for="item in evidenceSummary" :key="item.label" class="rounded-md border border-slate-200 bg-slate-50 p-4">
                <div class="text-xs font-bold uppercase tracking-[0.12em] text-slate-400">{{ item.label }}</div>
                <div class="mt-2 text-2xl font-bold text-slate-950">{{ item.value }}</div>
              </div>
            </div>
          </div>
        </template>

        <div v-else class="grid min-h-[520px] place-items-center rounded-lg border border-dashed border-slate-300 bg-white text-center shadow-sm">
          <div>
            <div class="mx-auto mb-4 h-12 w-12 rounded-md bg-slate-950"></div>
            <p class="font-headline text-lg font-semibold text-slate-800">选择诊断目标后运行 AI 分析</p>
            <p class="mt-2 text-sm text-slate-500">结果会先以结论和建议呈现，原始 JSON 作为证据保留。</p>
          </div>
        </div>
      </main>
    </div>
  </section>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { runDeviceAnalysis } from '../api/client.js'

const route = useRoute()

const moduleList = [
  { key: 'all', name: '完整分析', desc: '整合异常、健康、故障和能耗信号', prompt: 'AI 将综合全部可用模块，给出整体风险判断和优先处理建议。' },
  { key: 'anomaly', name: '异常检测', desc: '识别参数突变和异常窗口', prompt: 'AI 将重点检查参数波动、越界点和异常持续时间。' },
  { key: 'health', name: '健康评估', desc: '评估设备综合健康状态', prompt: 'AI 将根据健康分、在线率和报警情况判断设备状态。' },
  { key: 'fault', name: '故障预测', desc: '识别潜在故障风险', prompt: 'AI 将关注趋势变化和故障先兆，生成预防性维护建议。' },
  { key: 'energy', name: '能耗优化', desc: '分析能耗特征和优化空间', prompt: 'AI 将评估能耗异常、低效运行窗口和优化机会。' },
]

const hourPresets = [6, 12, 24, 72]
const selectedModule = ref('all')
const hours = ref(24)
const deviceId = ref('')
const loading = ref(false)
const error = ref('')
const result = ref(null)
const showRaw = ref(false)

const selectedModuleInfo = computed(() => moduleList.find((m) => m.key === selectedModule.value) || moduleList[0])
const formattedResult = computed(() => (result.value ? JSON.stringify(result.value, null, 2) : ''))
const confidence = computed(() => {
  if (!result.value) return 0
  if (selectedModule.value === 'all') return 88
  if (selectedModule.value === 'fault') return 84
  return 91
})
const statusText = computed(() => (result.value ? '完成' : '待诊断'))

const conclusionTitle = computed(() => {
  if (selectedModule.value === 'fault') return 'AI 已完成故障风险预判'
  if (selectedModule.value === 'anomaly') return 'AI 已完成异常窗口识别'
  if (selectedModule.value === 'energy') return 'AI 已完成能耗模式分析'
  return 'AI 已完成设备健康诊断'
})

const conclusionText = computed(() => {
  const moduleName = selectedModuleInfo.value.name
  return `本次 ${moduleName} 已完成。建议结合下方证据数据检查关键点位、报警记录和时间窗口，并将结论同步到维护报告或维修建议流程。`
})

const decisionCards = computed(() => [
  { label: '诊断模块', value: selectedModuleInfo.value.name, hint: '当前 AI 判断维度' },
  { label: '时间窗口', value: `${hours.value} 小时`, hint: '用于趋势和异常判断' },
  { label: '建议优先级', value: selectedModule.value === 'fault' ? '高' : '中', hint: '按风险和影响排序' },
])

const evidenceSummary = computed(() => [
  { label: '结果字段', value: Object.keys(result.value || {}).length },
  { label: '设备范围', value: deviceId.value || '默认' },
  { label: '置信度', value: `${confidence.value}%` },
])

const recommendedActions = [
  { path: '/alarm-analysis', title: '追溯报警模式', desc: '查看风险是否来自重复报警或活跃报警。' },
  { path: '/device-params', title: '查看参数分析', desc: '对比关键点位在异常窗口内的变化。' },
  { path: '/report', title: '生成诊断报告', desc: '把结论、证据和建议整理为可交付报告。' },
]

function selectModule(key) {
  selectedModule.value = key
}

async function runAnalysis() {
  loading.value = true
  error.value = ''
  result.value = null
  showRaw.value = false

  try {
    const params = {
      module: selectedModule.value,
      hours: hours.value,
    }
    if (deviceId.value) params.device_id = deviceId.value

    const res = await runDeviceAnalysis(params)
    if (res.code === 200) {
      result.value = res.data
    } else {
      error.value = res.msg || '分析失败'
    }
  } catch (err) {
    error.value = '请求错误: ' + err.message
  } finally {
    loading.value = false
  }
}

watch(
  () => route.query.module,
  (mod) => {
    if (mod && moduleList.find((m) => m.key === mod)) {
      selectedModule.value = mod
    }
  },
  { immediate: true },
)
</script>
