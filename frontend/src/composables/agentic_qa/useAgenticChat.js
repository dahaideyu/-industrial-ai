// frontend/src/composables/agentic_qa/useAgenticChat.js
import { ref, reactive } from 'vue'

export function useAgenticChat(sessionId) {
  const messages = ref([])
  const thinking = ref('')
  const steps = reactive([])
  const isStreaming = ref(false)
  const clarificationRequest = ref(null)
  let ws = null

  function connect() {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const wsUrl = `${protocol}//${window.location.host}/api/agentic-qa/ws/${sessionId}`

    ws = new WebSocket(wsUrl)

    ws.onmessage = (event) => {
      const event_data = JSON.parse(event.data)
      handleEvent(event_data)
    }

    ws.onclose = () => {
      isStreaming.value = false
    }

    ws.onerror = (err) => {
      console.error('[agentic_qa] WebSocket error:', err)
      isStreaming.value = false
    }
  }

  function handleEvent(event_data) {
    const { type, data } = event_data

    switch (type) {
      case 'planning':
        steps.length = 0
        if (data.goal) {
          messages.value.push({ role: 'system', content: `目标: ${data.goal}`, type: 'plan' })
        }
        break

      case 'thinking':
        thinking.value = data.text || ''
        break

      case 'step_start':
        steps.push({ id: data.task_id, description: data.description, status: 'running' })
        messages.value.push({
          role: 'system',
          content: `执行中: ${data.description}`,
          type: 'step',
          taskId: data.task_id,
        })
        break

      case 'step_end': {
        const step = steps.find((s) => s.id === data.task_id)
        if (step) {
          step.status = data.status === 'completed' ? 'done' : 'error'
        }
        break
      }

      case 'tool_call':
        messages.value.push({
          role: 'system',
          content: `调用: ${data.tool}`,
          type: 'tool',
          tool: data.tool,
          input: data.input,
        })
        break

      case 'review':
        messages.value.push({
          role: 'system',
          content: `审核: ${data.verdict} — ${data.reason || ''}`,
          type: 'review',
          verdict: data.verdict,
        })
        break

      case 'clarify_request':
        clarificationRequest.value = {
          message: data.message,
          suggestions: data.suggestions || [],
        }
        messages.value.push({
          role: 'assistant',
          content: data.message,
          type: 'clarify',
        })
        isStreaming.value = false
        break

      case 'answer':
        messages.value.push({
          role: 'assistant',
          content: data.text,
          type: 'answer',
          sql: data.sql,
          chart: data.chart,
        })
        isStreaming.value = false
        thinking.value = ''
        break

      case 'error':
        messages.value.push({
          role: 'assistant',
          content: data.message,
          type: 'error',
        })
        isStreaming.value = false
        break
    }
  }

  function sendQuery(question) {
    if (!ws || ws.readyState !== WebSocket.OPEN) {
      connect()
      ws.onopen = () => {
        isStreaming.value = true
        messages.value.push({ role: 'user', content: question, type: 'query' })
        ws.send(JSON.stringify({ type: 'query', question }))
      }
      return
    }
    isStreaming.value = true
    messages.value.push({ role: 'user', content: question, type: 'query' })
    ws.send(JSON.stringify({ type: 'query', question }))
    clarificationRequest.value = null
  }

  function sendContinue(response) {
    sendQuery(response)
  }

  function disconnect() {
    if (ws) {
      ws.close()
      ws = null
    }
  }

  return {
    messages,
    thinking,
    steps,
    isStreaming,
    clarificationRequest,
    connect,
    sendQuery,
    sendContinue,
    disconnect,
  }
}
