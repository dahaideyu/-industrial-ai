<template>
  <div class="bg-white rounded-2xl shadow-lg border border-gray-200 overflow-hidden">
    <form @submit.prevent="onSend" class="flex items-end gap-2 p-2">
      <textarea
        v-model="text"
        data-sqlqa-input
        :placeholder="sending ? 'AI 正在思考...' : '输入您的问题...'"
        :disabled="sending"
        rows="1"
        @keydown.enter.exact="onSend"
        @input="autoResize"
        class="flex-1 resize-none border-0 px-4 py-3 text-base focus:outline-none focus:ring-0 disabled:bg-transparent disabled:text-gray-400 bg-transparent"
      ></textarea>
      <button
        type="submit"
        :disabled="!text.trim() || sending"
        class="flex-shrink-0 w-9 h-9 rounded-full flex items-center justify-center transition-colors"
        :class="text.trim() && !sending ? 'bg-amber-400 text-gray-900 hover:bg-amber-300' : 'bg-gray-100 text-gray-400 cursor-not-allowed'"
      >
        <svg v-if="sending" class="w-4 h-4 animate-spin" fill="none" viewBox="0 0 24 24">
          <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"/>
          <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"/>
        </svg>
        <svg v-else class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 19l9 2-9-18-9 18 9-2zm0 0v-8" />
        </svg>
      </button>
    </form>
  </div>
</template>

<script setup>
import { ref, watch, nextTick } from 'vue'

const props = defineProps({
  sending: { type: Boolean, default: false },
  question: { type: String, default: '' },
})

const emit = defineEmits(['send', 'update:question'])

const text = ref(props.question)
const textareaRef = ref(null)

watch(() => props.question, (v) => {
  if (v) {
    text.value = v
    nextTick(() => {
      const el = document.querySelector('[data-sqlqa-input]')
      if (el) {
        el.focus()
        el.style.height = 'auto'
        el.style.height = Math.min(el.scrollHeight, 120) + 'px'
      }
    })
  }
})
watch(text, (v) => { emit('update:question', v) })

function autoResize(e) {
  const el = e.target
  el.style.height = 'auto'
  el.style.height = Math.min(el.scrollHeight, 120) + 'px'
}

function onSend() {
  if (!text.value.trim()) return
  emit('send', text.value.trim())
  text.value = ''
  setTimeout(() => {
    const el = document.querySelector('[data-sqlqa-input]')
    if (el) { el.style.height = 'auto' }
  }, 0)
}
</script>
