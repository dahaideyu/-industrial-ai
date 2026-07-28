<template>
  <div class="bg-white rounded-xl border border-gray-200 p-5">
    <!-- 进度条 -->
    <div class="flex items-center gap-4 mb-4">
      <div class="flex-1">
        <div class="h-3 bg-gray-100 rounded-full overflow-hidden">
          <div
            class="h-full rounded-full transition-all duration-500"
            :class="progressColor"
            :style="{ width: progress + '%' }"
          ></div>
        </div>
      </div>
      <span class="text-lg font-bold" :class="progressTextColor">
        {{ progress }}%
      </span>
    </div>

    <!-- 统计数字 -->
    <div v-if="stats" class="flex items-center gap-6 mb-4">
      <div class="flex items-center gap-1.5">
        <span class="w-2.5 h-2.5 rounded-full bg-green-500"></span>
        <span class="text-sm text-gray-600">已完成</span>
        <span class="text-sm font-semibold text-gray-800">{{ stats.completed || 0 }}</span>
      </div>
      <div class="flex items-center gap-1.5">
        <span class="w-2.5 h-2.5 rounded-full bg-yellow-500"></span>
        <span class="text-sm text-gray-600">待完善</span>
        <span class="text-sm font-semibold text-gray-800">{{ stats.improving || 0 }}</span>
      </div>
      <div class="flex items-center gap-1.5">
        <span class="w-2.5 h-2.5 rounded-full bg-red-500"></span>
        <span class="text-sm text-gray-600">缺失</span>
        <span class="text-sm font-semibold text-gray-800">{{ stats.missing || 0 }}</span>
      </div>
      <div v-if="stats.overdue != null" class="flex items-center gap-1.5">
        <span class="w-2.5 h-2.5 rounded-full bg-orange-500"></span>
        <span class="text-sm text-gray-600">超期</span>
        <span class="text-sm font-semibold text-gray-800">{{ stats.overdue }}</span>
      </div>
    </div>

    <!-- AI 评估分析（默认折叠） -->
    <div v-if="analysis">
      <button
        class="flex items-center gap-2 text-sm text-blue-600 hover:text-blue-800 transition-colors"
        @click="expanded = !expanded"
      >
        <svg
          class="w-4 h-4 transition-transform"
          :class="expanded ? 'rotate-90' : ''"
          fill="none"
          stroke="currentColor"
          viewBox="0 0 24 24"
        >
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5l7 7-7 7" />
        </svg>
        AI 评估分析
      </button>

      <div
        v-show="expanded"
        class="mt-3 p-4 bg-blue-50 rounded-lg text-sm text-gray-700 whitespace-pre-wrap border border-blue-100"
      >
        {{ analysis }}
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'

const props = defineProps({
  progress: { type: Number, default: 0 },
  stats: { type: Object, default: null },
  analysis: { type: String, default: '' },
})

const expanded = ref(false)

const progressColor = computed(() => {
  if (props.progress >= 80) return 'bg-green-500'
  if (props.progress >= 50) return 'bg-blue-500'
  if (props.progress >= 20) return 'bg-yellow-500'
  return 'bg-red-500'
})

const progressTextColor = computed(() => {
  if (props.progress >= 80) return 'text-green-600'
  if (props.progress >= 50) return 'text-blue-600'
  if (props.progress >= 20) return 'text-yellow-600'
  return 'text-red-600'
})
</script>
