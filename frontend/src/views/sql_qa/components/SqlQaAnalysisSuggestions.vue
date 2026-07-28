<template>
  <div v-if="suggestions && suggestions.length > 0" class="bg-gray-50 rounded-xl border border-gray-200 p-4">
    <p class="text-xs text-gray-500 mb-3 font-medium">基于以上数据，我能帮你进一步分析：</p>
    <div class="space-y-2">
      <button
        v-for="(s, i) in suggestions"
        :key="i"
        @click="$emit('select', s)"
        class="flex items-center gap-2 w-full text-left text-sm px-3 py-2.5 rounded-lg border border-gray-200 text-gray-700 bg-white hover:bg-gray-50 hover:border-amber-300 transition-colors"
      >
        <svg class="w-4 h-4 text-amber-400 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 10h.01M12 10h.01M16 10h.01M9 16H5a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v8a2 2 0 01-2 2h-5l-5 5v-5z" />
        </svg>
        <span>{{ s }}</span>
      </button>
    </div>
    <!-- Custom input -->
    <div class="mt-3">
      <div class="flex gap-2">
        <div class="relative flex-1">
          <svg class="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
          </svg>
          <input
            v-model="customQuestion"
            @keydown.enter="onCustomSubmit"
            type="text"
            placeholder="输入自定义分析问题..."
            class="w-full text-sm pl-8 pr-3 py-2 border border-gray-200 rounded-lg focus:outline-none focus:border-amber-400"
          />
        </div>
        <button
          @click="onCustomSubmit"
          :disabled="!customQuestion.trim()"
          class="px-5 py-2 text-sm rounded-lg transition-colors flex-shrink-0"
          :class="customQuestion.trim() ? 'bg-amber-400 text-gray-900 hover:bg-amber-300' : 'bg-gray-100 text-gray-400 cursor-not-allowed'"
        >
          开始分析
        </button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'

defineProps({
  suggestions: { type: Array, default: () => [] },
})

const emit = defineEmits(['select'])

const customQuestion = ref('')

function onCustomSubmit() {
  if (!customQuestion.value.trim()) return
  emit('select', customQuestion.value.trim())
  customQuestion.value = ''
}
</script>
