<template>
  <div v-if="!evaluation" class="text-center py-8 text-gray-400">
    <p class="text-sm">暂无评估数据</p>
  </div>

  <div v-else class="space-y-4">
    <!-- 整体状态 -->
    <div class="flex items-center gap-3">
      <span
        class="w-4 h-4 rounded-full"
        :class="statusColor(evaluation.overall_status)"
      ></span>
      <span class="text-base font-semibold text-gray-800">
        {{ evaluation.overall_status || '未评估' }}
      </span>
      <span
        v-if="evaluation.overall_score != null"
        class="text-lg font-bold"
        :class="scoreColor(evaluation.overall_score)"
      >
        {{ evaluation.overall_score }}分
      </span>
    </div>

    <!-- 完成度 -->
    <div v-if="evaluation.overall_completion">
      <h4 class="text-sm font-medium text-gray-600 mb-1">完成度评估</h4>
      <p class="text-sm text-gray-700 bg-gray-50 rounded-lg p-3">{{ evaluation.overall_completion }}</p>
    </div>

    <!-- 详细说明 -->
    <div v-if="evaluationDetail">
      <h4 class="text-sm font-medium text-gray-600 mb-1">详细分析</h4>
      <div class="text-sm text-gray-700 bg-gray-50 rounded-lg p-3 whitespace-pre-wrap">{{ evaluationDetail }}</div>
    </div>

    <!-- 评分分布 -->
    <div v-if="evaluation.evaluation_detail" class="space-y-2">
      <h4 class="text-sm font-medium text-gray-600">评分维度</h4>
      <div
        v-for="(value, key) in evaluation.evaluation_detail"
        :key="key"
        class="flex items-center justify-between p-2 bg-gray-50 rounded-lg"
      >
        <span class="text-sm text-gray-600">{{ key }}</span>
        <span
          v-if="typeof value === 'number'"
          class="text-sm font-medium"
          :class="scoreColor(value)"
        >
          {{ value }}
        </span>
        <span v-else class="text-sm text-gray-500">{{ value }}</span>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  evaluation: { type: Object, default: null },
})

const evaluationDetail = computed(() => {
  if (!props.evaluation) return ''
  // 尝试从 evaluation_detail 中提取文本
  const detail = props.evaluation.evaluation_detail
  if (typeof detail === 'string') return detail
  if (detail?.analysis) return detail.analysis
  if (detail?.summary) return detail.summary
  return ''
})

function statusColor(status) {
  switch (status) {
    case '已完成': return 'bg-green-500'
    case '待完善': return 'bg-yellow-500'
    case '缺失': return 'bg-red-500'
    default: return 'bg-gray-300'
  }
}

function scoreColor(score) {
  if (score == null) return 'text-gray-400'
  if (score >= 80) return 'text-green-600'
  if (score >= 60) return 'text-yellow-600'
  return 'text-red-600'
}
</script>
