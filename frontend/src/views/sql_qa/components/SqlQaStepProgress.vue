<template>
  <div v-if="steps && steps.length > 0" class="mb-4 overflow-hidden rounded-lg border border-gray-200">
    <!-- Toggle bar -->
    <button
      @click="toggleCollapsed"
      class="w-full flex items-center justify-between px-4 py-2 bg-slate-100 hover:bg-slate-200 transition-colors"
    >
      <div class="flex items-center gap-2">
        <svg v-if="(allDone || hasAnswer) && !hasError" class="w-5 h-5 text-emerald-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
        </svg>
        <svg v-else-if="hasError" class="w-5 h-5 text-rose-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10 14l2-2m0 0l2-2m-2 2l-2-2m2 2l2 2m7-2a9 9 0 11-18 0 9 9 0 0118 0z" />
        </svg>
        <svg v-else class="w-5 h-5 text-amber-500 animate-spin" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
        </svg>
        <span class="text-xs font-medium text-gray-700">{{ statusText }}</span>
      </div>
      <svg class="w-4 h-4 text-gray-400 transition-transform duration-200" :class="{ 'rotate-180': !isCollapsed }" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7" />
      </svg>
    </button>

    <!-- Steps detail -->
    <div v-if="!isCollapsed" class="bg-slate-50 border-t border-gray-200 py-3">
      <div v-for="(step, i) in orderedSteps" :key="i" class="relative flex gap-3 px-4">
        <!-- Left: timeline icon + connector -->
        <div class="flex flex-col items-center flex-shrink-0 pt-0.5" style="width: 20px">
          <svg v-if="step.status === 'done'" class="w-5 h-5 text-emerald-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
          </svg>
          <svg v-else-if="step.status === 'error'" class="w-5 h-5 text-rose-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10 14l2-2m0 0l2-2m-2 2l-2-2m2 2l2 2m7-2a9 9 0 11-18 0 9 9 0 0118 0z" />
          </svg>
          <svg v-else class="w-5 h-5 text-amber-400 animate-spin" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
          </svg>
          <div v-if="i < orderedSteps.length - 1" class="flex-1 w-px min-h-[16px] mt-2"
            :class="step.status === 'done' ? 'bg-emerald-200' : 'bg-gray-200'"></div>
        </div>

        <!-- Right: content -->
        <div class="flex-1 min-w-0 pb-3">
          <div class="flex items-center gap-2 flex-wrap">
            <span class="text-xs font-medium text-gray-600">{{ step.title }}</span>
            <span v-if="step.elapsed != null" class="text-[10px] text-gray-400">({{ formatTime(step.elapsed) }})</span>
          </div>
          <p v-if="step.detail || step.message" class="text-[11px] text-gray-400 mt-0.5 leading-relaxed">{{ step.detail || step.message }}</p>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, watch, onMounted } from 'vue'

const props = defineProps({
  steps: { type: Array, default: () => [] },
  msgId: { type: String, default: '' },
  source: { type: String, default: '' },
  hasAnswer: { type: Boolean, default: false },
})

const NL2SQL_TITLES = [
  '意图分析',
  '路由决策',
  '实体检索',
  '记忆检索',
  'SQL生成',
  'SQL安全检查',
  '数据库查询',
  '结果汇总',
  '数据分析',
]

const RAG_TITLES = [
  '意图分析',
  '路由决策',
  '文档检索',
  '结果生成',
]

const storageKey = computed(() => `step-collapsed-${props.msgId}`)
const isCollapsed = ref(false)

onMounted(() => {
  if (props.msgId) {
    const stored = sessionStorage.getItem(storageKey.value)
    if (stored !== null) {
      isCollapsed.value = stored === 'true'
    } else if (props.hasAnswer) {
      isCollapsed.value = true
    }
  } else if (props.hasAnswer) {
    isCollapsed.value = true
  }
})

const allDone = computed(() => {
  if (!props.steps || props.steps.length === 0) return false
  return props.steps.every(s => s.status === 'done' || s.status === 'error')
})

const hasError = computed(() => {
  return props.steps.some(s => s.status === 'error')
})

const doneCount = computed(() => {
  return props.steps.filter(s => s.status === 'done').length
})

const totalTime = computed(() => {
  const ms = props.steps.reduce((sum, s) => sum + (s.elapsed_ms || s.elapsed || 0), 0)
  return ms
})

const statusText = computed(() => {
  if (props.hasAnswer || (allDone.value && !hasError.value)) {
    return `执行完毕，${doneCount.value}/${props.steps.length}步，${formatTime(totalTime.value)}`
  }
  if (hasError.value) {
    return `执行失败，${doneCount.value}/${props.steps.length}步`
  }
  return `执行中... ${doneCount.value}/${props.steps.length}步`
})

const orderedSteps = computed(() => {
  const titles = props.source === 'ragflow' ? RAG_TITLES : NL2SQL_TITLES
  return props.steps.map((step, i) => ({
    ...step,
    title: titles[i] || step.message || `步骤 ${i + 1}`,
    elapsed: step.elapsed_ms ?? step.elapsed,
  }))
})

function formatTime(ms) {
  if (ms == null) return ''
  if (ms >= 1000) return `${(ms / 1000).toFixed(1)}s`
  return `${ms}ms`
}

function toggleCollapsed() {
  isCollapsed.value = !isCollapsed.value
  if (props.msgId) {
    sessionStorage.setItem(storageKey.value, isCollapsed.value.toString())
  }
}

watch(() => props.hasAnswer, (has) => {
  if (has) {
    setTimeout(() => {
      isCollapsed.value = true
      if (props.msgId) {
        sessionStorage.setItem(storageKey.value, 'true')
      }
    }, 300)
  }
})
</script>
