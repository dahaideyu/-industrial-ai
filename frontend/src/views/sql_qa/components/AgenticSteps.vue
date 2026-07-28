<template>
  <div v-if="steps && steps.length > 0" class="agentic-steps">
    <!-- 头部汇总 -->
    <button
      @click="toggleCollapse"
      class="w-full flex items-center justify-between px-3 py-2 hover:bg-slate-50 transition-colors"
    >
      <div class="flex items-center gap-2">
        <!-- 状态图标 -->
        <svg v-if="isAllDone && !hasError" class="w-4 h-4 text-emerald-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
        </svg>
        <svg v-else-if="hasError" class="w-4 h-4 text-rose-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10 14l2-2m0 0l2-2m-2 2l-2-2m2 2l2 2m7-2a9 9 0 11-18 0 9 9 0 0118 0z" />
        </svg>
        <svg v-else class="w-4 h-4 text-amber-500 animate-spin" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
        </svg>
        <span class="text-xs font-medium text-slate-600">{{ headerLabel }}</span>
      </div>
      <div class="flex items-center gap-2">
        <span class="text-[10px] text-slate-400">{{ doneCount }}/{{ steps.length }} 步</span>
        <span v-if="totalElapsed > 0" class="text-[10px] text-slate-400">{{ formatTime(totalElapsed) }}</span>
        <svg
          class="w-3.5 h-3.5 text-slate-400 transition-transform duration-200"
          :class="{ 'rotate-180': !isCollapsed }"
          fill="none" stroke="currentColor" viewBox="0 0 24 24"
        >
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7" />
        </svg>
      </div>
    </button>

    <!-- 步骤时间线 -->
    <Transition name="steps-expand">
    <div v-if="!isCollapsed" class="px-3 pb-3 pt-1">
      <div
        v-for="(step, i) in enrichedSteps"
        :key="step.id || i"
        class="relative flex gap-3"
      >
        <!-- 左侧：图标 + 连接线 -->
        <div class="flex flex-col items-center flex-shrink-0 pt-0.5" style="width: 22px">
          <!-- 完成图标 -->
          <div v-if="step.status === 'done'" class="step-icon step-icon-done">
            <svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2.5" d="M5 13l4 4L19 7" />
            </svg>
          </div>
          <!-- 错误图标 -->
          <div v-else-if="step.status === 'error'" class="step-icon step-icon-error">
            <svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2.5" d="M6 18L18 6M6 6l12 12" />
            </svg>
          </div>
          <!-- 运行中旋转动画 -->
          <div v-else class="step-icon step-icon-running">
            <div class="step-spinner"></div>
          </div>
          <!-- 连接线 -->
          <div
            v-if="i < enrichedSteps.length - 1"
            class="flex-1 w-px min-h-[12px] mt-1.5 mb-1"
            :class="stepLineColor(step, i)"
          ></div>
        </div>

        <!-- 右侧：内容 -->
        <div class="flex-1 min-w-0 pb-3">
          <!-- 标题行 -->
          <div class="flex items-center gap-2 flex-wrap">
            <span class="text-xs font-medium" :class="stepTitleColor(step.status)">{{ step.title || step.tool || `步骤 ${i + 1}` }}</span>
            <span v-if="step.attempt > 1" class="text-[10px] px-1.5 py-0.5 rounded bg-amber-50 text-amber-600 font-medium">重试 {{ step.attempt }}</span>
            <!-- 计时 -->
            <span v-if="step.status === 'running'" class="text-[10px] font-mono text-amber-500">{{ formatTime(runningElapsed(step)) }}</span>
            <span v-else-if="step.elapsed_ms || step.elapsed" class="text-[10px] font-mono text-slate-400">{{ formatTime(step.elapsed_ms || step.elapsed) }}</span>
          </div>

          <!-- 详情文本 -->
          <p v-if="step.detail" class="text-[11px] text-slate-400 mt-0.5 leading-relaxed whitespace-pre-wrap break-all line-clamp-4">{{ step.detail }}</p>

          <!-- 可展开详情 -->
          <div v-if="hasExpandableDetail(step)" class="mt-1">
            <button
              @click="toggleStepDetail(i)"
              class="text-[10px] text-blue-400 hover:text-blue-500 transition-colors"
            >
              {{ expandedSteps[i] ? '收起详情' : '查看详情' }}
            </button>
            <div v-if="expandedSteps[i]" class="mt-1.5 space-y-1.5">
              <!-- Tool 输入参数 -->
              <div v-if="step.tool_args" class="bg-slate-50 rounded px-2.5 py-1.5">
                <p class="text-[10px] text-slate-400 font-medium mb-1">输入参数</p>
                <pre class="text-[11px] text-slate-600 whitespace-pre-wrap break-all font-mono leading-relaxed">{{ formatJson(step.tool_args) }}</pre>
              </div>
              <!-- Tool 输出摘要 -->
              <div v-if="step.result_summary" class="bg-slate-50 rounded px-2.5 py-1.5">
                <p class="text-[10px] text-slate-400 font-medium mb-1">输出摘要</p>
                <pre class="text-[11px] text-slate-600 whitespace-pre-wrap break-all font-mono leading-relaxed max-h-32 overflow-y-auto">{{ formatJson(step.result_summary) }}</pre>
              </div>
              <!-- 错误信息 -->
              <div v-if="step.error" class="bg-rose-50 rounded px-2.5 py-1.5">
                <p class="text-[10px] text-rose-400 font-medium mb-0.5">错误信息</p>
                <p class="text-[11px] text-rose-600 whitespace-pre-wrap break-all">{{ typeof step.error === 'string' ? step.error : step.error.message || JSON.stringify(step.error) }}</p>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
    </Transition>
  </div>
</template>

<script setup>
import { ref, computed, watch, onUnmounted } from 'vue'

const props = defineProps({
  steps: { type: Array, default: () => [] },
  collapsed: { type: Boolean, default: false },
})

const isCollapsed = ref(props.collapsed)
const expandedSteps = ref({})
const now = ref(Date.now())
let timer = null

// 运行中步骤实时计时
const isRunning = computed(() => props.steps.some(s => s.status === 'running'))

function startTimer() {
  if (timer) return
  timer = setInterval(() => { now.value = Date.now() }, 1000)
}
function stopTimer() {
  if (timer) { clearInterval(timer); timer = null }
}

watch(isRunning, (running) => {
  if (running) startTimer()
  else stopTimer()
}, { immediate: true })

onUnmounted(() => stopTimer())

// 完成后自动折叠
watch(() => isRunning.value, (running, oldRunning) => {
  if (oldRunning && !running && isAllDone.value) {
    setTimeout(() => { isCollapsed.value = true }, 1500)
  }
})

const isAllDone = computed(() => {
  return props.steps.length > 0 && props.steps.every(s => s.status === 'done' || s.status === 'error')
})

const hasError = computed(() => props.steps.some(s => s.status === 'error'))

const doneCount = computed(() => props.steps.filter(s => s.status === 'done').length)

const totalElapsed = computed(() => {
  now.value // 响应式依赖
  let total = 0
  for (const s of props.steps) {
    if (s.status === 'running' && s._start_ts) {
      total += Date.now() - s._start_ts
    } else {
      total += (s.elapsed_ms || s.elapsed || 0)
    }
  }
  return total
})

const headerLabel = computed(() => {
  if (isRunning.value) return '执行中'
  if (isAllDone.value && !hasError.value) return '执行完毕'
  if (hasError.value) return '执行失败'
  return '准备执行'
})

// 丰富步骤数据：注入中文标题
const enrichedSteps = computed(() => {
  return props.steps.map((step, i) => ({
    ...step,
    title: step.title || TOOL_TITLES[step.tool] || step.tool || `步骤 ${i + 1}`,
  }))
})

function runningElapsed(step) {
  if (!step._start_ts) return 0
  now.value // 响应式依赖
  return Date.now() - step._start_ts
}

function stepLineColor(step, index) {
  if (step.status === 'error') return 'bg-rose-200'
  if (step.status === 'done') return 'bg-emerald-200'
  return 'bg-slate-200'
}

function stepTitleColor(status) {
  if (status === 'error') return 'text-rose-600'
  if (status === 'running') return 'text-amber-700'
  return 'text-slate-700'
}

function hasExpandableDetail(step) {
  return step.tool_args || step.result_summary || step.error
}

function toggleStepDetail(index) {
  expandedSteps.value[index] = !expandedSteps.value[index]
}

function toggleCollapse() {
  isCollapsed.value = !isCollapsed.value
}

function formatTime(ms) {
  if (!ms || ms <= 0) return ''
  if (ms < 1000) return `${Math.round(ms)}ms`
  return `${(ms / 1000).toFixed(1)}s`
}

function formatJson(obj) {
  if (typeof obj === 'string') return obj
  try {
    return JSON.stringify(obj, null, 2)
  } catch {
    return String(obj)
  }
}

// 工具标题映射（与后端 TOOL_TITLES 保持一致）
const TOOL_TITLES = {
  search_entities: '实体搜索',
  get_schema: '获取表结构',
  generate_sql: '生成SQL查询',
  execute_sql: '执行SQL查询',
  diagnose_sql_error: '诊断SQL错误',
  typo_check: '错别字检测',
  analyze_data: '数据分析',
  query_rag: '文档检索',
  answer_general: '直接回答',
  read_memory: '读取记忆',
  ask_clarification: '请求澄清',
}
</script>

<style scoped>
.agentic-steps {
  border-radius: 10px;
  border: 1px solid #e2e8f0;
  overflow: hidden;
  margin-bottom: 8px;
  background: #fff;
}

.step-icon {
  width: 22px;
  height: 22px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.step-icon-done {
  background: #ecfdf5;
  border: 2px solid #22c55e;
  color: #22c55e;
}

.step-icon-error {
  background: #fef2f2;
  border: 2px solid #ef4444;
  color: #ef4444;
}

.step-icon-running {
  background: #fffbeb;
  border: 2px solid #f59e0b;
  box-shadow: 0 0 0 3px rgba(245, 158, 11, 0.1);
}

.step-spinner {
  width: 14px;
  height: 14px;
  border-radius: 50%;
  border: 2px solid #f59e0b;
  border-top-color: transparent;
  animation: step-spin 0.8s linear infinite;
}

@keyframes step-spin {
  to { transform: rotate(360deg); }
}

.steps-expand-enter-active {
  animation: steps-slide-down 0.3s ease-out;
}
.steps-expand-leave-active {
  animation: steps-slide-down 0.2s ease-in reverse;
}

@keyframes steps-slide-down {
  from {
    opacity: 0;
    transform: translateY(-8px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}
</style>
