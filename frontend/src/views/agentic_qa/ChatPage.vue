<template>
  <div class="agentic-chat-page">
    <div class="chat-header">
      <h3>智能数据问答 (Agentic)</h3>
      <span class="mode-badge">AGENTIC</span>
    </div>

    <div class="chat-messages" ref="messagesContainer">
      <template v-for="(msg, i) in messages" :key="i">
        <div v-if="msg.role === 'user'" class="message user-message">
          <div class="msg-content">{{ msg.content }}</div>
        </div>
        <div v-else-if="msg.role === 'assistant'" class="message assistant-message">
          <div class="msg-content">{{ msg.content }}</div>
          <div v-if="msg.sql" class="sql-block">
            <details>
              <summary>SQL</summary>
              <pre>{{ msg.sql }}</pre>
            </details>
          </div>
        </div>
      </template>

      <ThinkingBlock :text="thinking" />
    </div>

    <StepProgress :steps="steps" />

    <div class="chat-input-row">
      <input
        v-model="inputText"
        type="text"
        class="chat-input"
        placeholder="输入你的问题..."
        :disabled="isStreaming"
        @keyup.enter="onSend"
      />
      <button class="send-btn" :disabled="isStreaming || !inputText.trim()" @click="onSend">
        {{ isStreaming ? '...' : '发送' }}
      </button>
    </div>
  </div>
</template>

<script setup>
import { ref, watch, nextTick, onMounted, onUnmounted } from 'vue'
import { useAgenticChat } from '@/composables/agentic_qa/useAgenticChat'
import ThinkingBlock from './components/ThinkingBlock.vue'
import StepProgress from './components/StepProgress.vue'

const props = defineProps({
  sessionId: { type: String, required: true },
})

const inputText = ref('')
const messagesContainer = ref(null)

const {
  messages,
  thinking,
  steps,
  isStreaming,
  connect,
  sendQuery,
  disconnect,
} = useAgenticChat(props.sessionId)

onMounted(() => connect())
onUnmounted(() => disconnect())

function onSend() {
  const q = inputText.value.trim()
  if (!q || isStreaming.value) return
  sendQuery(q)
  inputText.value = ''
}

watch(messages, async () => {
  await nextTick()
  if (messagesContainer.value) {
    messagesContainer.value.scrollTop = messagesContainer.value.scrollHeight
  }
}, { deep: true })
</script>

<style scoped>
.agentic-chat-page {
  display: flex;
  flex-direction: column;
  height: 100%;
  max-width: 900px;
  margin: 0 auto;
}
.chat-header {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 12px 16px;
  border-bottom: 1px solid #e4e7ed;
}
.mode-badge {
  font-size: 11px;
  padding: 2px 8px;
  background: #e6f7ff;
  color: #1890ff;
  border-radius: 10px;
}
.chat-messages {
  flex: 1;
  overflow-y: auto;
  padding: 16px;
}
.message { margin-bottom: 12px; max-width: 80%; }
.user-message { margin-left: auto; }
.user-message .msg-content {
  background: #409eff;
  color: #fff;
  padding: 10px 14px;
  border-radius: 12px 12px 0 12px;
}
.assistant-message .msg-content {
  background: #f5f7fa;
  padding: 10px 14px;
  border-radius: 12px 12px 12px 0;
}
.sql-block { margin-top: 8px; font-size: 12px; }
.sql-block pre {
  background: #f0f0f0;
  padding: 8px;
  border-radius: 4px;
  overflow-x: auto;
  font-size: 11px;
}
.chat-input-row {
  display: flex;
  gap: 8px;
  padding: 12px 16px;
  border-top: 1px solid #e4e7ed;
}
.chat-input { flex: 1; padding: 10px 14px; border: 1px solid #dcdfe6; border-radius: 8px; font-size: 14px; }
.send-btn { padding: 10px 24px; background: #409eff; color: #fff; border: none; border-radius: 8px; cursor: pointer; font-size: 14px; }
.send-btn:disabled { background: #a0cfff; cursor: not-allowed; }
</style>
