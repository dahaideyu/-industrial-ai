<template>
  <div class="mt-2">
    <div class="flex items-center gap-2 flex-wrap">
      <!-- Question prompt -->
      <span class="text-xs text-gray-500">回答准确吗？</span>

      <button
        @click="onCorrect"
        :class="[
          'text-xs px-2.5 py-1 rounded border transition-colors',
          status === 'correct'
            ? 'border-green-400 bg-green-50 text-green-600'
            : 'border-gray-200 text-gray-400 hover:text-green-600 hover:border-green-300'
        ]"
      >
        ✓ 正确
      </button>
      <button
        @click="onToggleWrong"
        :class="[
          'text-xs px-2.5 py-1 rounded border transition-colors',
          status === 'wrong'
            ? 'border-red-400 bg-red-50 text-red-600'
            : showInput
              ? 'border-red-300 bg-red-50 text-red-500'
              : 'border-gray-200 text-gray-400 hover:text-red-500 hover:border-red-300'
        ]"
      >
        ✗ 错误
      </button>

      <span v-if="status === 'wrong'" class="text-xs text-red-400">反馈已记录，感谢！</span>

      <!-- Inline error input -->
      <template v-if="showInput && status !== 'wrong'">
        <input
          ref="inputRef"
          v-model="inputText"
          type="text"
          placeholder="哪里不对？请详细描述一下"
          class="text-xs px-2.5 py-1.5 border border-gray-200 rounded w-48 focus:outline-none focus:border-amber-400"
          @keydown.enter="onWrong"
        />
        <button @click="onWrong" class="text-xs px-2.5 py-1 rounded bg-amber-400 text-gray-900 hover:bg-amber-300 transition-colors">提交</button>
        <button @click="onCancel" class="text-xs px-2.5 py-1 rounded border border-gray-200 text-gray-500 hover:bg-gray-50 transition-colors">取消</button>
      </template>
    </div>
  </div>
</template>

<script setup>
import { ref, nextTick } from 'vue'

const props = defineProps({
  status: { type: String, default: null },
  feedbackText: { type: String, default: '' },
})

const emit = defineEmits(['correct', 'wrong', 'reset'])

const showInput = ref(false)
const inputText = ref('')
const inputRef = ref(null)

function onCorrect() {
  if (props.status === 'correct') {
    // clicking again deselects
    showInput.value = false
    inputText.value = ''
    emit('reset')
    return
  }
  showInput.value = false
  inputText.value = ''
  emit('correct')
}

function onToggleWrong() {
  if (props.status === 'wrong') return // 已反馈错误，不允许重复
  if (props.status === 'correct') {
    emit('reset')
  }
  showInput.value = !showInput.value
  inputText.value = ''
  if (showInput.value) {
    nextTick(() => {
      inputRef.value?.focus()
    })
  }
}

function onCancel() {
  showInput.value = false
  inputText.value = ''
}

function onWrong() {
  if (!inputText.value.trim()) return
  emit('wrong', inputText.value.trim())
  showInput.value = false
}
</script>
