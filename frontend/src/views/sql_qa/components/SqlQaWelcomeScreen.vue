<template>
  <div class="text-center max-w-2xl p-6">
    <div class="w-16 h-16 mx-auto mb-4 rounded-2xl bg-amber-100 flex items-center justify-center">
      <svg class="w-8 h-8 text-amber-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 10h.01M12 10h.01M16 10h.01M9 16H5a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v8a2 2 0 01-2 2h-5l-5 5v-5z" />
      </svg>
    </div>
    <h2 class="text-lg font-semibold text-gray-800 mb-2">工业数据智能问答</h2>
    <p class="text-sm text-gray-500 mb-6">输入您的问题，AI 将自动查询数据库或知识库并给出答案</p>
    <div v-if="questions.length > 0" class="grid grid-cols-3 gap-2">
      <button
        v-for="q in questions"
        :key="q"
        @click="$emit('select', q)"
        class="px-3 py-2 text-sm rounded-full border border-amber-200 text-amber-700 bg-amber-50 hover:bg-amber-100 transition-colors truncate"
        :title="q"
      >
        {{ q }}
      </button>
    </div>
    <div v-else class="flex justify-center gap-2">
      <button
        v-for="q in fallbackQuestions"
        :key="q"
        @click="$emit('select', q)"
        class="px-4 py-2 text-sm rounded-full border border-amber-200 text-amber-700 bg-amber-50 hover:bg-amber-100 transition-colors"
      >
        {{ q }}
      </button>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { listMemories } from '../../../api/sqlQaClient.js'

defineEmits(['select'])

const questions = ref([])

const fallbackQuestions = [
  '查询所有产线列表',
  '设备数量统计',
  '最近7天故障记录',
]

onMounted(async () => {
  try {
    const data = await listMemories({ type: 'sql_pair', random: true, limit: 50 })
    const pairs = data.memories || data || []
    questions.value = pairs
      .map(p => p.question)
      .filter(q => q && q.length < 60)
      .slice(0, 9)
  } catch {
    questions.value = []
  }
})
</script>
