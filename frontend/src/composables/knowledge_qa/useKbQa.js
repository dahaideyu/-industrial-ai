import { ref, computed, reactive } from 'vue'
import { kbQaClient } from '@/api/kbQaClient'

const sessions = ref([])
const currentSessionId = ref(null)
const messages = ref([])
const availableKbs = ref([])
const manualKbIds = ref([])  // 手动选择的 KB（为下个问题）
const loading = ref(false)
const error = ref(null)

export function useKbQa() {
  const currentSession = computed(() =>
    sessions.value.find((s) => s.id === currentSessionId.value) || null
  )

  const usedKbIdsByLastMessage = computed(() => {
    const lastAssistant = [...messages.value]
      .reverse()
      .find((m) => m.role === 'assistant')
    return lastAssistant?.used_kb_ids || []
  })

  async function loadSessions() {
    const result = await kbQaClient.listSessions()
    sessions.value = Array.isArray(result) ? result : []
    if (sessions.value.length === 0) {
      try {
        const s = await kbQaClient.createSession('新会话')
        if (s && s.id) {
          sessions.value = [s]
        }
      } catch (e) {
        // 创建会话失败（例如未登录），保持空列表
        console.warn('创建会话失败:', e)
      }
    }
    if (!currentSessionId.value && sessions.value.length > 0 && sessions.value[0]?.id) {
      currentSessionId.value = sessions.value[0].id
      await loadMessages(currentSessionId.value)
    }
  }

  async function loadMessages(sessionId) {
    currentSessionId.value = sessionId
    const result = await kbQaClient.listMessages(sessionId)
    messages.value = Array.isArray(result) ? result : []
  }

  async function newSession() {
    try {
      const s = await kbQaClient.createSession('新会话')
      if (s && s.id) {
        sessions.value.unshift(s)
        await loadMessages(s.id)
      }
    } catch (e) {
      console.warn('创建会话失败:', e)
    }
  }

  async function loadKbs() {
    try {
      const result = await kbQaClient.listKbs()
      console.log('[KBQA] listKbs 原始返回 type:', typeof result, 'value:', result, 'isArray:', Array.isArray(result))
      if (result && typeof result === 'object') {
        console.log('[KBQA] result keys:', Object.keys(result))
      }
      availableKbs.value = Array.isArray(result) ? result : []
    } catch (e) {
      console.error('[KBQA] listKbs 失败:', e.message, e.response?.status)
      const hasToken = typeof localStorage !== 'undefined' && !!localStorage.getItem('auth_token')
      console.error('[KBQA] 是否有 token:', hasToken)
      availableKbs.value = []
    }
    // DEBUG 临时日志：诊断 KB 列表
    if (typeof window !== 'undefined') {
      const withDocs = availableKbs.value.filter(k => (k.document_count || 0) > 0)
      console.log('[KBQA] KB 列表加载:', {
        total: availableKbs.value.length,
        withDocs: withDocs.length,
        sample: availableKbs.value.slice(0, 2),
      })
    }
  }

  /** 发送问题（流式，默认）。边接收边更新视图。 */
  async function sendQuestionStream(question) {
    if (!question.trim() || !currentSessionId.value) return
    loading.value = true
    error.value = null
    try {
      // 乐观追加 user 消息
      const tempUserMsg = {
        id: Date.now(),
        role: 'user',
        content: question,
        created_at: new Date().toISOString(),
      }
      messages.value.push(tempUserMsg)

      // 追加空白 assistant 占位消息（流式逐字填充）
      const placeholderMsg = reactive({
        id: -Date.now(),  // 临时 ID，done 事件中更新为真实 ID
        role: 'assistant',
        content: '',
        used_kb_ids: [],
        rag_references: null,
        created_at: new Date().toISOString(),
        streaming: true,
      })
      messages.value.push(placeholderMsg)

      await kbQaClient.chatStream({
        sessionId: currentSessionId.value,
        question,
        manualKbIds: manualKbIds.value,
        onChunk(delta) {
          placeholderMsg.content += delta
        },
        onDone(result) {
          placeholderMsg.id = result.message_id
          placeholderMsg.content = result.answer || placeholderMsg.content
          placeholderMsg.thinking = result.thinking || ''
          placeholderMsg.used_kb_ids = result.used_kb_ids || []
          placeholderMsg.rag_references = result.references
          placeholderMsg.streaming = false
        },
        onError(err) {
          error.value = err.message || '流式请求失败'
          placeholderMsg.content = placeholderMsg.content || '（回答生成失败）'
          placeholderMsg.streaming = false
        },
      })

      // 清空手动选择（已用）
      manualKbIds.value = []
    } catch (e) {
      error.value = e.message || '提问失败'
      // 移除乐观 user 消息
      const lastUserIdx = [...messages.value].reverse().findIndex(m => m.role === 'user')
      if (lastUserIdx >= 0) {
        messages.value.splice(messages.value.length - 1 - lastUserIdx, 1)
      }
    } finally {
      loading.value = false
    }
  }

  /** 发送问题（非流式，兼容旧行为）。 */
  async function sendQuestion(question) {
    if (!question.trim() || !currentSessionId.value) return
    loading.value = true
    error.value = null
    try {
      // 先追加 user 消息（乐观更新）
      const tempUserMsg = {
        id: Date.now(),
        role: 'user',
        content: question,
        created_at: new Date().toISOString(),
      }
      messages.value.push(tempUserMsg)

      // 调用后端
      const result = await kbQaClient.chat({
        sessionId: currentSessionId.value,
        question,
        manualKbIds: manualKbIds.value,
      })

      // 追加 assistant 消息
      const assistantMsg = {
        id: result.message_id,
        role: 'assistant',
        content: result.answer,
        used_kb_ids: result.used_kb_ids,
        rag_references: result.references,
        created_at: new Date().toISOString(),
      }
      messages.value.push(assistantMsg)

      // 清空手动选择（已用）
      manualKbIds.value = []
    } catch (e) {
      error.value = e.message || '提问失败'
      // 移除乐观 user 消息
      messages.value.pop()
    } finally {
      loading.value = false
    }
  }

  function toggleManualKb(kbId) {
    const idx = manualKbIds.value.indexOf(kbId)
    if (idx >= 0) {
      manualKbIds.value.splice(idx, 1)
    } else {
      manualKbIds.value.push(kbId)
    }
  }

  function refreshMemory() {
    // 重新加载会话列表
    return loadSessions()
  }

  return {
    sessions,
    currentSession,
    currentSessionId,
    messages,
    availableKbs,
    manualKbIds,
    usedKbIdsByLastMessage,
    loading,
    error,
    loadSessions,
    loadMessages,
    newSession,
    loadKbs,
    sendQuestion,
    sendQuestionStream,
    toggleManualKb,
    refreshMemory,
  }
}
