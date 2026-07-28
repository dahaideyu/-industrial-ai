<template>
  <section class="min-h-screen">
    <div class="border-b border-slate-200 bg-white/80 px-6 py-5 backdrop-blur lg:px-8">
      <div class="mx-auto max-w-[1500px]">
        <p class="text-xs font-bold uppercase tracking-[0.18em] text-amber-700">AI Report Studio</p>
        <h1 class="mt-2 font-headline text-2xl font-semibold text-slate-950">智能报告生成</h1>
        <p class="mt-1 text-sm text-slate-500">从模板、数据和 AI 推理过程生成可交付报告。</p>
      </div>
    </div>

    <div class="mx-auto grid max-w-[1500px] gap-6 p-6 lg:grid-cols-[360px_1fr] lg:p-8">
      <aside class="space-y-6">
        <div class="rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
          <h2 class="font-headline text-lg font-semibold text-slate-950">报告配置</h2>
          <div class="mt-5 space-y-4">
            <div>
              <label class="mb-2 block text-xs font-bold uppercase tracking-[0.14em] text-slate-500">报告模板</label>
              <select
                v-model="selectedTemplate"
                class="w-full rounded-md border border-slate-200 bg-slate-50 px-3 py-2.5 text-sm outline-none transition-colors focus:border-amber-500 focus:bg-white"
              >
                <option value="">请选择模板</option>
                <option v-for="(name, key) in templates" :key="key" :value="key">
                  {{ name }}
                </option>
              </select>
            </div>

            <div>
              <label class="mb-2 block text-xs font-bold uppercase tracking-[0.14em] text-slate-500">报告目标</label>
              <textarea
                v-model="reportGoal"
                rows="4"
                class="w-full resize-none rounded-md border border-slate-200 bg-slate-50 px-3 py-2.5 text-sm leading-6 outline-none transition-colors focus:border-amber-500 focus:bg-white"
                placeholder="例如：总结本周质量异常、输出原因判断和整改建议"
              ></textarea>
            </div>

            <div class="grid grid-cols-2 gap-3">
              <div>
                <label class="mb-2 block text-xs font-bold uppercase tracking-[0.14em] text-slate-500">时间范围</label>
                <select v-model="period" class="w-full rounded-md border border-slate-200 bg-slate-50 px-3 py-2.5 text-sm outline-none focus:border-amber-500">
                  <option value="daily">日报</option>
                  <option value="weekly">周报</option>
                  <option value="monthly">月报</option>
                </select>
              </div>
              <div>
                <label class="mb-2 block text-xs font-bold uppercase tracking-[0.14em] text-slate-500">输出格式</label>
                <select v-model="preferredFormat" class="w-full rounded-md border border-slate-200 bg-slate-50 px-3 py-2.5 text-sm outline-none focus:border-amber-500">
                  <option value="text">文本</option>
                  <option value="html">HTML</option>
                </select>
              </div>
            </div>

            <button
              @click="generateReport"
              :disabled="generating || !selectedTemplate"
              class="w-full rounded-md bg-slate-950 px-4 py-3 text-sm font-bold text-white transition-colors hover:bg-amber-700 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {{ generating ? 'AI 正在生成...' : '开始生成报告' }}
            </button>
          </div>
        </div>

        <div class="rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
          <div class="flex items-center justify-between">
            <h2 class="font-headline text-lg font-semibold text-slate-950">高级数据</h2>
            <button @click="advancedOpen = !advancedOpen" class="text-xs font-bold text-amber-700">
              {{ advancedOpen ? '收起' : '展开' }}
            </button>
          </div>
          <div v-if="advancedOpen" class="mt-4">
            <label class="mb-2 block text-xs font-bold uppercase tracking-[0.14em] text-slate-500">JSON 输入</label>
            <textarea
              v-model="jsonInput"
              rows="10"
              class="w-full resize-none rounded-md border border-slate-200 bg-slate-950 px-3 py-2.5 font-mono text-xs leading-5 text-amber-50 outline-none focus:border-amber-500"
            ></textarea>
          </div>
          <p v-else class="mt-3 text-sm leading-6 text-slate-500">
            默认会根据当前配置生成请求体。需要精确控制接口参数时可展开 JSON。
          </p>
        </div>
      </aside>

      <main class="space-y-6">
        <div class="grid gap-4 lg:grid-cols-4">
          <div
            v-for="step in generationSteps"
            :key="step.key"
            :class="[
              'rounded-lg border p-4 shadow-sm',
              activeStep === step.key
                ? 'border-amber-300 bg-amber-50'
                : completedSteps.includes(step.key)
                  ? 'border-emerald-200 bg-emerald-50'
                  : 'border-slate-200 bg-white'
            ]"
          >
            <div class="text-xs font-bold uppercase tracking-[0.14em] text-slate-500">{{ step.label }}</div>
            <div class="mt-3 font-headline text-base font-semibold text-slate-950">{{ step.title }}</div>
            <p class="mt-2 text-xs leading-5 text-slate-500">{{ step.desc }}</p>
          </div>
        </div>

        <div class="grid gap-6 xl:grid-cols-[1fr_340px]">
          <div class="rounded-lg border border-slate-200 bg-white shadow-sm">
            <div class="flex items-center justify-between border-b border-slate-200 px-5 py-4">
              <div>
                <h2 class="font-headline text-lg font-semibold text-slate-950">报告预览</h2>
                <p class="mt-1 text-xs text-slate-500">
                  {{ elapsedTime ? `生成耗时 ${elapsedTime.toFixed(2)}s` : '等待 AI 生成内容' }}
                </p>
              </div>
              <div class="flex gap-2">
                <button
                  @click="output = ''"
                  class="rounded-md border border-slate-200 px-3 py-2 text-xs font-bold text-slate-600 hover:border-amber-400 hover:text-amber-700"
                >
                  清空
                </button>
                <button
                  @click="copyReport"
                  :disabled="!output"
                  class="rounded-md bg-amber-600 px-3 py-2 text-xs font-bold text-white hover:bg-amber-700 disabled:opacity-50"
                >
                  复制
                </button>
              </div>
            </div>

            <div ref="outputRef" class="min-h-[620px] overflow-auto p-5">
              <div v-if="!output && !generating" class="grid min-h-[520px] place-items-center rounded-md border border-dashed border-slate-300 bg-slate-50 text-center">
                <div>
                  <div class="mx-auto mb-4 h-12 w-12 rounded-md bg-slate-950"></div>
                  <p class="font-headline text-lg font-semibold text-slate-800">配置报告目标后开始生成</p>
                  <p class="mt-2 text-sm text-slate-500">AI 会先组织证据，再输出结论和建议。</p>
                </div>
              </div>
              <div v-else-if="outputFormat === 'html'" class="prose max-w-none" v-html="output"></div>
              <pre v-else class="whitespace-pre-wrap rounded-md bg-slate-50 p-4 text-sm leading-7 text-slate-800">{{ output }}</pre>
            </div>
          </div>

          <aside class="space-y-6">
            <div class="rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
              <h2 class="font-headline text-lg font-semibold text-slate-950">AI 编辑建议</h2>
              <div class="mt-4 space-y-3">
                <button
                  v-for="suggestion in editSuggestions"
                  :key="suggestion"
                  class="w-full rounded-md border border-slate-200 px-3 py-2.5 text-left text-sm font-semibold text-slate-700 hover:border-amber-400 hover:bg-amber-50/50"
                >
                  {{ suggestion }}
                </button>
              </div>
            </div>

            <div class="rounded-lg border border-slate-200 bg-slate-950 p-5 text-white shadow-sm">
              <h2 class="font-headline text-lg font-semibold">输出结构</h2>
              <ol class="mt-4 space-y-3 text-sm text-slate-300">
                <li v-for="section in reportSections" :key="section" class="flex gap-3">
                  <span class="mt-1 h-2 w-2 shrink-0 rounded-full bg-amber-300"></span>
                  <span>{{ section }}</span>
                </li>
              </ol>
            </div>
          </aside>
        </div>
      </main>
    </div>
  </section>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { getTemplates } from '../api/client.js'

const templates = ref({})
const selectedTemplate = ref('')
const reportGoal = ref('总结关键异常、风险原因和下一步处理建议')
const period = ref('weekly')
const preferredFormat = ref('text')
const jsonInput = ref('')
const output = ref('')
const outputFormat = ref('text')
const generating = ref(false)
const elapsedTime = ref(0)
const outputRef = ref(null)
const advancedOpen = ref(false)
const activeStep = ref('')
const completedSteps = ref([])

const generationSteps = [
  { key: 'collect', label: 'Step 01', title: '读取证据', desc: '整理模板、时间范围和输入数据。' },
  { key: 'reason', label: 'Step 02', title: 'AI 推理', desc: '识别异常、原因和风险优先级。' },
  { key: 'compose', label: 'Step 03', title: '组织报告', desc: '形成结论、依据和行动建议。' },
  { key: 'deliver', label: 'Step 04', title: '输出交付', desc: '生成可复制、可编辑的报告内容。' },
]

const editSuggestions = [
  '强化风险排序',
  '增加维修建议',
  '压缩成管理摘要',
  '补充数据证据',
]

const reportSections = [
  '管理摘要',
  '关键异常与影响',
  'AI 原因判断',
  '数据证据',
  '建议动作和责任跟进',
]

async function loadTemplates() {
  try {
    const res = await getTemplates()
    if (res.code === 200) {
      templates.value = res.data
      const first = Object.keys(res.data || {})[0]
      if (!selectedTemplate.value && first) selectedTemplate.value = first
    }
  } catch (err) {
    console.error('加载模板失败:', err)
  }
}

function buildPayload() {
  if (advancedOpen.value && jsonInput.value.trim()) {
    return JSON.parse(jsonInput.value)
  }

  return {
    reportCode: selectedTemplate.value,
    data: {
      report_type: period.value,
      goal: reportGoal.value,
      output_format: preferredFormat.value,
    },
  }
}

async function generateReport() {
  if (!selectedTemplate.value) return

  generating.value = true
  output.value = ''
  outputFormat.value = 'text'
  elapsedTime.value = 0
  completedSteps.value = []
  activeStep.value = 'collect'

  let payload
  try {
    payload = buildPayload()
  } catch (err) {
    output.value = 'JSON 解析错误: ' + err.message
    generating.value = false
    activeStep.value = ''
    return
  }

  const startTime = Date.now()

  try {
    completedSteps.value.push('collect')
    activeStep.value = 'reason'

    const response = await fetch('/api/ai_report', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    })

    completedSteps.value.push('reason')
    activeStep.value = 'compose'

    const reader = response.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''
    let fullContent = ''

    while (true) {
      const { done, value } = await reader.read()
      if (done) break

      buffer += decoder.decode(value, { stream: true })
      const lines = buffer.split('\n')
      buffer = lines.pop() || ''

      let eventType = 'message'
      let eventData = ''

      for (const line of lines) {
        if (line.startsWith('event: ')) {
          eventType = line.substring(7)
        } else if (line.startsWith('data: ')) {
          eventData += line.substring(6) + '\n'
        } else if (line === '') {
          eventData = eventData.trim()
          if (eventData) {
            if (eventType === 'message') {
              output.value += eventData + '\n'
              fullContent += eventData + '\n'
            } else if (eventType === 'end') {
              try {
                const result = JSON.parse(eventData)
                if (result.data) {
                  output.value = result.data
                  fullContent = result.data
                }
                if (result.totalTime) elapsedTime.value = result.totalTime
              } catch (e) {
                // SSE end payload is optional.
              }
            }
          }
          eventType = 'message'
          eventData = ''
        }
      }
    }

    completedSteps.value.push('compose')
    activeStep.value = 'deliver'

    if (preferredFormat.value === 'html' || fullContent.trim().startsWith('<!DOCTYPE') || fullContent.trim().startsWith('<html')) {
      outputFormat.value = 'html'
    }
    completedSteps.value.push('deliver')
  } catch (err) {
    output.value = '请求错误: ' + err.message
  } finally {
    generating.value = false
    activeStep.value = ''
    elapsedTime.value = elapsedTime.value || (Date.now() - startTime) / 1000
  }
}

async function copyReport() {
  if (!output.value) return
  try {
    await navigator.clipboard.writeText(output.value)
  } catch (err) {
    console.error('复制失败:', err)
  }
}

onMounted(loadTemplates)
</script>
