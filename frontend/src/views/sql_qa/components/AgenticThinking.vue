<template>
  <div v-if="thinking || isThinking" class="agentic-thinking">
    <button
      @click="toggleCollapse"
      class="w-full flex items-center gap-2 px-3 py-2 rounded-lg hover:bg-slate-50 transition-colors text-left"
    >
      <!-- 思考中脉冲动画 -->
      <span v-if="isThinking" class="relative flex h-2.5 w-2.5 flex-shrink-0">
        <span class="animate-ping absolute inline-flex h-full w-full rounded-full bg-amber-400 opacity-75"></span>
        <span class="relative inline-flex rounded-full h-2.5 w-2.5 bg-amber-500"></span>
      </span>
      <!-- 思考结束图标 -->
      <svg v-else class="w-4 h-4 text-slate-400 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z" />
      </svg>
      <span class="text-xs font-medium" :class="isThinking ? 'text-amber-600' : 'text-slate-500'">
        {{ isThinking ? '思考中...' : '思考过程' }}
      </span>
      <svg
        class="w-3.5 h-3.5 text-slate-400 transition-transform duration-200 ml-auto"
        :class="{ 'rotate-180': !isCollapsed }"
        fill="none" stroke="currentColor" viewBox="0 0 24 24"
      >
        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7" />
      </svg>
    </button>

    <!-- 思考内容 -->
    <div
      v-if="!isCollapsed"
      class="px-3 pb-2 overflow-hidden transition-all duration-300"
      :class="{ 'fade-out': !isThinking && thinking }"
    >
      <div class="text-xs text-slate-500 leading-relaxed whitespace-pre-wrap break-words bg-slate-50 rounded-md px-3 py-2 max-h-60 overflow-y-auto">
        <span>{{ displayedThinking }}</span>
        <span v-if="isThinking" class="inline-block w-0.5 h-3.5 bg-amber-400 ml-0.5 align-text-bottom animate-blink"></span>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, watch } from 'vue'

const props = defineProps({
  thinking: { type: String, default: '' },
  isThinking: { type: Boolean, default: false },
  // 最终结果就绪信号：置真时自动折叠思考过程（与步骤时间线一致）
  collapsed: { type: Boolean, default: false },
})

const isCollapsed = ref(false)

// 思考开始时自动展开
watch(() => props.isThinking, (newVal) => {
  if (newVal) {
    isCollapsed.value = false
  }
})

// 最终结果出来后自动折叠思考过程（用户仍可手动点开）
watch(() => props.collapsed, (newVal) => {
  if (newVal) {
    isCollapsed.value = true
  }
}, { immediate: true })

// 显示的思考文本（直接使用完整文本，避免打字机闪烁）
const displayedThinking = computed(() => props.thinking || '')

function toggleCollapse() {
  isCollapsed.value = !isCollapsed.value
}
</script>

<style scoped>
.agentic-thinking {
  border-radius: 8px;
  border: 1px solid #e2e8f0;
  overflow: hidden;
  margin-bottom: 8px;
}

.fade-out {
  opacity: 0.75;
}

@keyframes blink {
  0%, 50% { opacity: 1; }
  51%, 100% { opacity: 0; }
}

.animate-blink {
  animation: blink 1s step-end infinite;
}
</style>
