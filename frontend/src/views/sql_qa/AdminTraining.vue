<template>
  <div class="p-6 h-full overflow-y-auto">
    <div class="mb-6">
      <h2 class="text-lg font-semibold text-gray-800">NL2SQL 训练</h2>
      <p class="text-sm text-gray-400 mt-1">索引表结构 → 补充注释 → 训练问答对 → 记忆库管理</p>
    </div>

    <div class="bg-white rounded-xl border border-gray-200 overflow-hidden">
      <div class="flex gap-1 border-b border-gray-200 px-4 pt-3">
        <button
          v-for="t in tabs"
          :key="t.key"
          @click="tab = t.key"
          :class="[
            'px-4 py-2.5 text-sm font-medium rounded-t-lg transition-colors',
            tab === t.key ? 'bg-amber-400 text-gray-900' : 'text-gray-500 hover:text-gray-700 hover:bg-gray-100'
          ]"
        >
          {{ t.label }}
        </button>
      </div>
      <div class="p-4">
        <SqlQaSchemaIndex v-if="tab === 'schema'" />
        <SqlQaBatchGenerate v-if="tab === 'quick'" />
        <SqlQaTrainForm v-if="tab === 'train'" />
        <SqlQaTrainingReview v-if="tab === 'review'" />
        <SqlQaMemoryManager v-if="tab === 'memory'" />
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import SqlQaSchemaIndex from './components/SqlQaSchemaIndex.vue'
import SqlQaBatchGenerate from './components/SqlQaBatchGenerate.vue'
import SqlQaTrainForm from './components/SqlQaTrainForm.vue'
import SqlQaTrainingReview from './components/SqlQaTrainingReview.vue'
import SqlQaMemoryManager from './components/SqlQaMemoryManager.vue'

const tab = ref('schema')

const tabs = [
  { key: 'schema', label: '数据库索引' },
  { key: 'quick', label: '快速训练' },
  { key: 'train', label: '手动训练' },
  { key: 'review', label: '训练审核' },
  { key: 'memory', label: '记忆库管理' },
]
</script>
