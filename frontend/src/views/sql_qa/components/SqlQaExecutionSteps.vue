<template>
  <div v-if="steps.length > 0" class="execution-steps">
    <!-- Status header -->
    <div class="steps-header">
      <span class="status-label">{{ statusLabel }}</span>
      <span class="header-sep">·</span>
      <span class="count-text">{{ doneCount }}/{{ steps.length }} 已完成</span>
      <span v-if="!isRunning" class="header-sep">·</span>
      <span v-if="!isRunning" class="elapsed-text">耗时{{ formatTime(totalElapsed) }}</span>
    </div>

    <!-- Timeline -->
    <div class="timeline">
      <div
        v-for="(s, i) in steps"
        :key="s.id"
        class="timeline-row"
        :class="'row-' + s.status"
      >
        <!-- Left: dot + line -->
        <div class="timeline-left">
          <div :class="['dot', 'dot-' + s.status]">
            <!-- done checkmark -->
            <svg v-if="s.status === 'done'" width="10" height="10" viewBox="0 0 20 20" fill="#22c55e">
              <path fill-rule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clip-rule="evenodd"/>
            </svg>
            <!-- error cross -->
            <svg v-else-if="s.status === 'error'" width="10" height="10" viewBox="0 0 20 20" fill="#ef4444">
              <path fill-rule="evenodd" d="M4.293 4.293a1 1 0 011.414 0L10 8.586l4.293-4.293a1 1 0 111.414 1.414L11.414 10l4.293 4.293a1 1 0 01-1.414 1.414L10 11.414l-4.293 4.293a1 1 0 01-1.414-1.414L8.586 10 4.293 5.707a1 1 0 010-1.414z" clip-rule="evenodd"/>
            </svg>
            <!-- running spinner -->
            <div v-else class="spinner"></div>
          </div>
          <div v-if="i < steps.length - 1" :class="['line', 'line-' + lineColor(i)]"></div>
        </div>

        <!-- Right: content -->
        <div class="timeline-content">
          <div :class="['step-title', 'title-' + s.status]">
            {{ s.title }}
            <span v-if="s.attempt > 1" class="retry-badge">重试 {{ s.attempt }}/{{ s.retry_max || '?' }}</span>
            <span :class="['step-time', 'time-' + s.status]">{{ formatTime(s.elapsed_ms) }}</span>
          </div>
          <div v-if="s.detail" :class="['step-detail', 'detail-' + s.status]">{{ s.detail }}</div>
          <!-- Error box -->
          <div v-if="s.status === 'error' && s.error" class="error-box">
            {{ s.error.message }}
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, ref, onUnmounted, watch } from 'vue'

const props = defineProps({
  steps: { type: Array, default: () => [] },
})

const now = ref(Date.now())
let timer = null

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

const totalElapsed = computed(() => {
  now.value
  if (isRunning.value) {
    const startTime = props.steps[0]?._start_ts
    if (startTime) return Date.now() - startTime
  }
  return props.steps.reduce((sum, s) => sum + (s.elapsed_ms || 0), 0)
})

const doneCount = computed(() => props.steps.filter(s => s.status === 'done').length)
const runningCount = computed(() => props.steps.filter(s => s.status === 'running').length)
const errorCount = computed(() => props.steps.filter(s => s.status === 'error').length)

const statusLabel = computed(() => {
  if (runningCount.value > 0) return '执行中'
  if (doneCount.value === props.steps.length && props.steps.length > 0) return '执行完毕'
  return '执行开始'
})

function formatTime(ms) {
  if (!ms || ms <= 0) return '—'
  if (ms < 1000) return ms + 'ms'
  return (ms / 1000).toFixed(1) + 's'
}

function lineColor(i) {
  const s = props.steps[i]
  if (s.status === 'error') return 'error'
  const next = props.steps[i + 1]
  if (!next) return 'gray'
  if (next.status === 'done') return 'done'
  if (next.status === 'error') return 'error'
  return 'gray'
}
</script>

<style scoped>
.execution-steps {
  background: #fafbfc;
  border-radius: 12px;
  padding: 16px 20px;
  margin-bottom: 8px;
  font-family: system-ui, -apple-system, sans-serif;
}

.steps-header {
  display: flex;
  align-items: baseline;
  gap: 4px;
  margin-bottom: 12px;
  padding-bottom: 10px;
  border-bottom: 1px solid #e2e8f0;
}

.status-label {
  font-size: 12px;
  color: #64748b;
  font-weight: 500;
}

.header-sep {
  font-size: 12px;
  color: #cbd5e1;
}

.count-text {
  font-size: 12px;
  color: #94a3b8;
}

.elapsed-text {
  font-size: 12px;
  color: #94a3b8;
}

/* Timeline */
.timeline-row {
  display: flex;
  gap: 10px;
}

.timeline-left {
  display: flex;
  flex-direction: column;
  align-items: center;
  flex-shrink: 0;
  width: 20px;
}

.dot {
  width: 20px;
  height: 20px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.dot-done {
  background: #ecfdf5;
  border: 2px solid #22c55e;
}

.dot-error {
  background: #fef2f2;
  border: 2px solid #ef4444;
}

.dot-running {
  background: #fffbeb;
  border: 2px solid #f59e0b;
  box-shadow: 0 0 0 4px rgba(245, 158, 11, 0.12);
}

.line {
  width: 2px;
  flex: 1;
  min-height: 10px;
  margin: 2px 0;
  border-radius: 1px;
}

.line-done { background: #22c55e; }
.line-error { background: #fca5a5; }
.line-gray { background: #e2e8f0; }

.spinner {
  width: 16px;
  height: 16px;
  border-radius: 50%;
  border: 2px solid #f59e0b;
  border-top-color: transparent;
  animation: spin 0.8s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

/* Content */
.timeline-content {
  flex: 1;
  padding-bottom: 14px;
  min-width: 0;
}

.step-title {
  font-weight: 600;
  font-size: 13px;
  display: flex;
  align-items: baseline;
  gap: 8px;
  flex-wrap: wrap;
}

.title-done { color: #1e293b; }
.title-error { color: #dc2626; }
.title-running { color: #1e293b; }

.retry-badge {
  background: #fef3c7;
  color: #b45309;
  font-size: 10px;
  font-weight: 600;
  padding: 1px 6px;
  border-radius: 3px;
}

.step-time {
  font-size: 11px;
  font-family: 'SF Mono', 'Fira Code', monospace;
  font-weight: 400;
}

.time-done { color: #94a3b8; }
.time-error { color: #94a3b8; }
.time-running { color: #f59e0b; }

.step-detail {
  font-size: 12px;
  margin-top: 1px;
}

.detail-done { color: #64748b; }
.detail-error { color: #dc2626; }
.detail-running { color: #64748b; }

.error-box {
  font-size: 12px;
  color: #dc2626;
  background: #fef2f2;
  border-radius: 4px;
  padding: 4px 8px;
  margin-top: 4px;
  white-space: pre-wrap;
  word-break: break-all;
}
</style>
