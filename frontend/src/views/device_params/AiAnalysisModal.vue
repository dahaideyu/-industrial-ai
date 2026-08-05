<template>
  <Teleport to="body">
    <div v-if="result || error" class="fixed inset-0 z-50 flex items-center justify-center p-4" @click.self="$emit('close')">
      <div class="absolute inset-0 bg-black/40"></div>
      <div class="relative bg-white rounded-2xl shadow-2xl w-full max-w-4xl max-h-[85vh] flex flex-col">
        <div class="flex items-center justify-between px-6 py-4 border-b border-gray-100 shrink-0">
          <h2 class="text-lg font-bold text-gray-900">
            {{ error ? '分析失败' : 'AI 分析结果' }}
            <span v-if="meta" class="ml-2 text-xs font-normal text-gray-400">{{ meta }}</span>
          </h2>
          <button
            @click="$emit('close')"
            class="text-gray-400 hover:text-gray-600 text-xl leading-none px-2"
          >✕</button>
        </div>
        <div class="overflow-y-auto px-6 py-4 flex-1">
          <div v-if="error" class="text-red-600 text-sm">{{ error }}</div>
          <div v-else class="prose prose-sm max-w-none text-gray-700 leading-relaxed" v-html="html"></div>
        </div>
        <div class="flex items-center justify-between px-6 py-3 border-t border-gray-100 shrink-0">
          <div class="flex items-center gap-2 text-xs text-gray-400">
            <template v-if="!error">
              分析时间：{{ startTime }} ~ {{ endTime }}
              <span v-if="analyzeRunningOnly" class="text-green-500">· 仅运行时段</span>
            </template>
          </div>
          <div class="flex items-center gap-2">
            <button @click="$emit('reanalyze')" :disabled="analyzing"
              class="px-4 py-2 text-sm bg-violet-500 text-white rounded-lg hover:bg-violet-600 disabled:opacity-50">
              {{ analyzing ? '分析中...' : '重新分析' }}
            </button>
            <button @click="$emit('close')"
              class="px-4 py-2 text-sm bg-gray-100 rounded-lg hover:bg-gray-200">关闭</button>
          </div>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<script setup>
defineProps({
  result: { type: String, default: '' },
  meta: { type: String, default: '' },
  error: { type: String, default: '' },
  html: { type: String, default: '' },
  analyzing: { type: Boolean, default: false },
  startTime: { type: String, default: '' },
  endTime: { type: String, default: '' },
  analyzeRunningOnly: { type: Boolean, default: false },
})

defineEmits(['close', 'reanalyze'])
</script>
