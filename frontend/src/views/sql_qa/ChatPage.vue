<template>
  <div class="h-full flex overflow-hidden">
    <!-- Main chat area -->
    <div class="flex-1 flex flex-col min-h-0">
      <!-- Messages (only this area scrolls) -->
      <div ref="msgContainer" class="flex-1 overflow-y-auto p-4" :class="messages.length === 0 && !sending ? 'flex flex-col justify-center' : ''">
        <div v-if="messages.length === 0 && !sending" class="flex items-center justify-center">
          <SqlQaWelcomeScreen @select="onSend" />
        </div>

        <SqlQaMessageBubble
          v-for="msg in messages"
          :key="msg.id"
          :msg="msg"
          :question="lastUserQuestion"
          @entity-confirm="onEntityConfirm"
          @suggestion-select="onSuggestionSelect"
          @feedback-correct="onFeedbackCorrect"
          @feedback-wrong="onFeedbackWrong"
          @feedback-reset="onFeedbackReset"
          @citation-open="onCitationOpen"
          @clarify-confirm="onClarifyConfirm"
        />

        <!-- Sending indicator -->
        <div v-if="sending && messages.length > 0 && messages[messages.length - 1]?.content === '正在处理...'" class="flex gap-2 items-center text-gray-400 text-sm px-2">
          <span class="w-1.5 h-1.5 rounded-full bg-amber-400 animate-bounce" style="animation-delay: 0ms"></span>
          <span class="w-1.5 h-1.5 rounded-full bg-amber-400 animate-bounce" style="animation-delay: 150ms"></span>
          <span class="w-1.5 h-1.5 rounded-full bg-amber-400 animate-bounce" style="animation-delay: 300ms"></span>
        </div>
      </div>

      <!-- Floating Input area -->
      <div class="flex-shrink-0 px-4 pb-4 pt-2 bg-gradient-to-t from-[#eef2f6] via-[#eef2f6] to-transparent">
        <div class="max-w-2xl mx-auto">
          <SqlQaInputArea
            :sending="sending"
            :question="fillQuestion"
            @send="onSend"
            @update:question="fillQuestion = $event"
          />
        </div>
      </div>
    </div>

    <!-- Right panel -->
    <SqlQaRightPanel @select="onSend" @fill="onFill" />
  </div>

  <!-- Citation popup -->
  <SqlQaCitationPopup
    :visible="citationVisible"
    :dataset-id="citationData.dataset_id"
    :document-id="citationData.document_id"
    :doc-name="citationData.name"
    :highlight-page="citationData.page"
    :highlight-positions="citationData.positions || []"
    :keywords="lastUserQuestion"
    @close="citationVisible = false"
  />

</template>

<script setup>
import { ref, computed, watch, nextTick } from 'vue'
import { useSqlQaSessions } from '../../composables/sql_qa/useSqlQaSessions.js'
import { useSqlQaChat } from '../../composables/sql_qa/useSqlQaChat.js'
import SqlQaWelcomeScreen from './components/SqlQaWelcomeScreen.vue'
import SqlQaMessageBubble from './components/SqlQaMessageBubble.vue'
import SqlQaInputArea from './components/SqlQaInputArea.vue'
import SqlQaRightPanel from './components/SqlQaRightPanel.vue'
import SqlQaCitationPopup from './components/SqlQaCitationPopup.vue'

import { submitFeedback, recordFeedback, appendMessage as apiAppendMessage } from '../../api/sqlQaClient.js'

const { activeId, sessions, getSession } = useSqlQaSessions()
const chat = useSqlQaChat(activeId)
const { getSessionData, sendMessage, clearMessages, confirmEntities } = chat

const msgContainer = ref(null)
const fillQuestion = ref('')

const citationVisible = ref(false)
const citationData = ref({})

const messages = computed(() => getSessionData().messages)
const sending = computed(() => getSessionData().sending)

const lastUserQuestion = computed(() => {
  const msgs = messages.value
  for (let i = msgs.length - 1; i >= 0; i--) {
    if (msgs[i].role === 'user') return msgs[i].content
  }
  return ''
})

// Auto-scroll to bottom
watch(() => messages.value.length, () => {
  nextTick(() => {
    if (msgContainer.value) {
      msgContainer.value.scrollTop = msgContainer.value.scrollHeight
    }
  })
})

function onSuggestionSelect(data) {
  if (data && data.clarifications) {
    // 澄清确认 → 调用 clarify API
    chat.sendClarify(data.clarifications)
    return
  }
  const text = typeof data === 'string' ? data : data.text
  const ctx = (typeof data === 'object' && data.source_sql) ? {
    source_question: data.source_question,
    source_sql: data.source_sql,
    source_entity_context: data.source_entity_context,
  } : null
  sendMessage(text, ctx)
}

async function onSend(question) {
  await sendMessage(question)
  nextTick(() => {
    if (msgContainer.value) {
      msgContainer.value.scrollTop = msgContainer.value.scrollHeight
    }
  })
}

function onEntityConfirm(question, entities) {
  confirmEntities(question, entities)
}

function onFill(question) {
  fillQuestion.value = question
}

function onClarifyConfirm(data) {
  const { entityContext, msgId } = data
  const s = getSession(activeId.value)
  if (!s) return

  // Find the USER's original question (not the assistant's clarification text)
  const userMsgs = s.messages.filter(m => m.role === 'user')
  const originalQuestion = userMsgs.length > 0 ? userMsgs[userMsgs.length - 1].content : ''

  // Convert clarification_groups selections → entity format for confirmQuery
  const entities = []
  entityContext.forEach(ec => {
    ec.values.forEach(v => {
      entities.push({
        entity_type: ec.field,
        value: v,
        label: v,
        mention: v,
      })
    })
  })

  // Save confirmed entities in session memory
  s.memory = { ...(s.memory || {}), confirmed_entities: entityContext }

  // Mark clarification message as resolved (keep UI visible, read-only)
  const updatedGroups = (s.messages.find(m => m.id === msgId)?.clarification_groups || []).map(g => ({
    ...g,
    resolved: true,
    selected: (entityContext.find(ec => ec.field === g.field)?.values || []),
  }))
  s.messages = s.messages.map(m => {
    if (m.id === msgId && m.clarification_groups) {
      return {
        ...m,
        needs_clarification: false,
        clarification_groups: updatedGroups,
      }
    }
    return m
  })

  // 持久化澄清确认状态到服务端
  const t = localStorage.getItem('auth_token')
  if (t) {
    const msg = s.messages.find(m => m.id === msgId)
    if (msg) {
      apiAppendMessage(activeId.value, {
        id: msg.id, role: 'assistant',
        content: msg.content || '', sql: msg.sql || null,
        clarification_groups: JSON.stringify(updatedGroups),
        needs_clarification: false,
        timestamp: msg.timestamp || Date.now(),
      }).catch(() => {})
    }
  }

  // Get existing steps to continue the timeline
  const clarifyMsg = s.messages.find(m => m.id === msgId)
  const existingSteps = clarifyMsg?.steps || []

  confirmEntities(originalQuestion, entities, existingSteps)
}

function onCitationOpen(ref) {
  citationData.value = ref
  citationVisible.value = true
}

function getCombinedSql(msg) {
  if (msg.result_groups && msg.result_groups.length > 0) {
    return msg.result_groups.map((g, i) => `-- 数据集${i + 1}\n${g.sql || ''}`).filter(s => s.length > 10).join('\n\n')
  }
  return msg.sql || ''
}

function _persistFeedback(msg, feedback_status, feedback_text = null) {
  const t = localStorage.getItem('auth_token')
  if (t) {
    apiAppendMessage(activeId.value, {
      id: msg.id, role: 'assistant',
      content: msg.content || '', sql: msg.sql || null,
      feedback_status, feedback_text,
      timestamp: msg.timestamp || Date.now(),
    }).catch(() => {})
  }
}

function onFeedbackReset(msg) {
  const s = getSession(activeId.value)
  if (s) {
    const updated = s.messages.map(m => m.id === msg.id ? { ...m, feedback_status: null, feedback_text: null } : m)
    s.messages = updated
    _persistFeedback(msg, null)
  }
}

async function onFeedbackCorrect(msg) {
  const lastUser = lastUserQuestion.value
  try {
    await submitFeedback({
      question: lastUser,
      sql: getCombinedSql(msg),
      feedback: 'correct',
      session_id: activeId.value,
    })
    const s = getSession(activeId.value)
    if (s) {
      const updated = s.messages.map(m => m.id === msg.id ? { ...m, feedback_status: 'correct' } : m)
      s.messages = updated
      _persistFeedback(msg, 'correct')
    }
  } catch {}
}

async function onFeedbackWrong(msg, text) {
  const lastUser = lastUserQuestion.value
  try {
    await recordFeedback({
      question: lastUser,
      answer: msg.content,
      sql: getCombinedSql(msg),
      user_feedback: text,
      session_id: activeId.value,
    })
    const s = getSession(activeId.value)
    if (s) {
      const updated = s.messages.map(m => m.id === msg.id ? { ...m, feedback_status: 'wrong', feedback_text: text } : m)
      s.messages = updated
      _persistFeedback(msg, 'wrong', text)
    }
  } catch {}
}
</script>
