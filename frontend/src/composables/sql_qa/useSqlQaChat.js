import { ref, watch, onUnmounted } from 'vue'
import { useSqlQaSessions, nextMsgId } from './useSqlQaSessions.js'
import { submitQuery, confirmQuery, appendMessage as apiAppendMessage, generateTitle as apiGenerateTitle } from '../../api/sqlQaClient.js'
import { getWebSocketUrl } from '../../api/sqlQaClient.js'

function compactMemory(mem) {
  const out = {}
  for (const [k, v] of Object.entries(mem)) {
    if (k === 'last_query' && v && typeof v === 'object') {
      const lq = { ...v }
      if (Array.isArray(lq.results) && lq.results.length > 50) {
        lq.results = lq.results.slice(0, 50)
        lq._results_truncated = true
      }
      out[k] = lq
    } else if (k === 'history') {
      continue
    } else {
      out[k] = v
    }
  }
  return out
}

const wsMap = new Map()
const pendingMsgMap = new Map()
const controllersMap = new Map()
let typewriterTimer = null
let typewriterFullText = ''

export function useSqlQaChat(sessionId) {
  const {
    getSession,
    updateSessionMessages,
    updateSessionTitle,
    appendMessage,
    sessionExists,
    setSessionRunning,
    updateSessionMemory,
    sessions,
  } = useSqlQaSessions()

  // 辅助：安全获取当前会话消息
  function getCurrentMessages(sid) {
    return sessions.value.find(s => s.id === sid)?.messages || []
  }

  // WebSocket 连接管理
  function ensureWebSocket(sid) {
    const existing = wsMap.get(sid)
    if (existing && existing.readyState === WebSocket.OPEN) return
    if (existing) wsMap.delete(sid)

    const url = getWebSocketUrl(sid)
    const ws = new WebSocket(url)

    ws.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data)
        if (msg.type === 'step_update' && pendingMsgMap.get(sid)) {
          const pid = pendingMsgMap.get(sid)
          setSessionRunning(sid, true)
          updateSessionMessages(sid,
            getCurrentMessages(sid).map(m => {
              if (m.id !== pid) return m
              const stepData = msg.data

              // ── streaming 事件：thinking_chunk ──
              if (stepData.type === 'thinking_chunk') {
                const current = m.thinking || ''
                return { ...m, thinking: current + (stepData.content || ''), isThinking: true }
              }

              // ── streaming 事件：thinking_end ──
              if (stepData.type === 'thinking_end') {
                return { ...m, isThinking: false }
              }

              // ── streaming 事件：step_start ──
              if (stepData.type === 'step_start') {
                const prevSteps = m.steps || []
                const newStep = { ...stepData, status: 'running', _start_ts: Date.now() }
                // 用 id 或 tool 去重
                const existIdx = prevSteps.findIndex(s => (s.id && s.id === stepData.id) || (s.tool && s.tool === stepData.tool && s.status === 'running'))
                if (existIdx >= 0) {
                  const updated = [...prevSteps]
                  updated[existIdx] = { ...updated[existIdx], ...newStep }
                  return { ...m, steps: updated }
                }
                return { ...m, steps: [...prevSteps, newStep] }
              }

              // ── streaming 事件：step_end ──
              if (stepData.type === 'step_end') {
                const prevSteps = m.steps || []
                const matchIdx = prevSteps.findIndex(s =>
                  (s.id && s.id === stepData.id) || (s.tool && s.tool === stepData.tool)
                )
                if (matchIdx >= 0) {
                  const existing = prevSteps[matchIdx]
                  const updated = [...prevSteps]
                  const elapsed = stepData.elapsed_ms || (existing._start_ts ? Date.now() - existing._start_ts : 0)
                  updated[matchIdx] = {
                    ...existing,
                    ...stepData,
                    status: stepData.status || (stepData.error ? 'error' : 'done'),
                    elapsed_ms: elapsed,
                  }
                  return { ...m, steps: updated }
                }
                return m
              }

              // ── streaming 事件：answer_chunk ──
              if (stepData.type === 'answer_chunk') {
                const current = m.content === '正在处理...' ? '' : (m.content || '')
                return { ...m, content: current + (stepData.content || '') }
              }

              // ── streaming 事件：answer_end ──
              if (stepData.type === 'answer_end') {
                return { ...m, isStreamingAnswer: false }
              }

              // rag_stream special case (for RAGFlow source)
              if (stepData.type === 'rag_stream') {
                if (stepData.chunk) {
                  const current = m.content === '正在处理...' ? '' : m.content || ''
                  return { ...m, content: current + stepData.chunk }
                }
                return m
              }

              const prevSteps = m.steps || []

              // Use id for dedup — same id = same step, update in place
              const existIdx = prevSteps.findIndex(s => s.id === stepData.id)
              if (existIdx >= 0) {
                const existing = prevSteps[existIdx]
                // Never downgrade: done/error won't be overwritten by running
                if ((existing.status === 'done' || existing.status === 'error') && stepData.status === 'running') {
                  return m
                }
                const updated = [...prevSteps]
                updated[existIdx] = { ...existing, ...stepData }
                return { ...m, steps: updated }
              }

              // New step — record start timestamp for total elapsed
              return { ...m, steps: [...prevSteps, { ...stepData, _start_ts: Date.now() }] }
            })
          )
        }
        if (msg.type === 'complete' && pendingMsgMap.get(sid)) {
          const pid = pendingMsgMap.get(sid)
          const finalData = msg.data
          updateSessionMessages(sid,
            getCurrentMessages(sid).map(m =>
              m.id === pid ? {
                ...m,
                content: finalData.answer || m.content,
                sql: finalData.sql,
                results: finalData.results,
                steps: (finalData.steps && finalData.steps.length > 0) ? finalData.steps : (m.steps || []),
                intent: finalData.intent,
                source: finalData.source,
                needs_clarification: finalData.needs_clarification,
                clarification_questions: finalData.clarification_questions,
                clarification_options: finalData.clarification_options,
                clarification_groups: finalData.clarification_groups,
                entity_candidates: finalData.entity_candidates,
                auto_completions: finalData.auto_completions,
                analysis_chart: finalData.analysis_chart,
                followups: finalData.followups,
                analysis_suggestions: finalData.analysis_suggestions,
                result_groups: finalData.result_groups,
                rag_thinking: finalData.rag_thinking,
                rag_references: finalData.rag_references,
                isThinking: false,
                isStreamingAnswer: false,
              } : m
            )
          )
          if (finalData.session_memory) {
            updateSessionMemory(sid, compactMemory(finalData.session_memory))
          }
          if (!finalData.answer && !finalData.results) {
            pendingMsgMap.delete(sid)
            setSessionRunning(sid, false)
          }
        }
      } catch {}
    }

    ws.onerror = () => { wsMap.delete(sid) }
    ws.onclose = () => { wsMap.delete(sid) }

    wsMap.set(sid, ws)
  }

  // sessionId 变化时建立 WebSocket
  watch(() => sessionId?.value, (sid) => {
    if (sid) ensureWebSocket(sid)
  }, { immediate: true })

  // 清理
  onUnmounted(() => {
    controllersMap.forEach(c => c.abort())
    controllersMap.clear()
    wsMap.forEach(ws => { try { ws.close() } catch {} })
    wsMap.clear()
    if (typewriterTimer) {
      clearInterval(typewriterTimer)
      typewriterTimer = null
    }
  })

  function buildHistory(sid) {
    const msgs = getCurrentMessages(sid)
    const history = []
    for (let i = 0; i < msgs.length; i++) {
      if (msgs[i].role === 'user') {
        const assistant = msgs.slice(i + 1).find(m => m.role === 'assistant')
        if (assistant && assistant.content && assistant.content !== '正在处理...') {
          history.push({
            question: msgs[i].content,
            answer: assistant.content,
            sql: assistant.sql,
          })
        }
      }
    }
    return history.slice(-5)
  }

  function stopTypewriter() {
    if (typewriterTimer) {
      clearInterval(typewriterTimer)
      typewriterTimer = null
    }
  }

  function startTypewriter(sid, msgId, fullAnswer) {
    stopTypewriter()
    typewriterFullText = fullAnswer
    let revealed = 0
    const totalLen = fullAnswer.length
    typewriterTimer = setInterval(() => {
      revealed += Math.max(1, Math.floor(totalLen / 80))
      if (revealed >= totalLen) {
        clearInterval(typewriterTimer)
        typewriterTimer = null
        revealed = totalLen
      }
      updateSessionMessages(sid,
        getCurrentMessages(sid).map(m =>
          m.id === msgId ? { ...m, content: fullAnswer.slice(0, revealed) } : m
        )
      )
    }, 20)
  }

  async function sendMessage(question, sourceContext = null) {
    const sid = typeof sessionId === 'function' ? sessionId() : (sessionId?.value || sessionId)
    if (!sid) return
    const initialSession = getSession(sid)
    if (!initialSession) return

    const wasEmpty = initialSession.messages.length === 0

    stopTypewriter()

    const userMsg = { id: nextMsgId(), role: 'user', content: question, timestamp: Date.now() }
    appendMessage(sid, userMsg)

    const t = localStorage.getItem('auth_token')
    if (t) {
      apiAppendMessage(sid, { id: userMsg.id, role: 'user', content: question, timestamp: userMsg.timestamp }).catch(() => {})
    }

    if (wasEmpty && question.length > 0) {
      const fallbackTitle = question.length > 30 ? question.slice(0, 30) + '...' : question
      updateSessionTitle(sid, fallbackTitle)
      apiGenerateTitle(sid, { question }).then(res => {
        if (res?.title) updateSessionTitle(sid, res.title)
      }).catch(() => {})
    }

    const placeholderId = nextMsgId()
    pendingMsgMap.set(sid, placeholderId)
    const placeholder = { id: placeholderId, role: 'assistant', content: '正在处理...', steps: [], thinking: '', isThinking: false, source: 'agentic_qa', timestamp: Date.now() }
    appendMessage(sid, placeholder)
    setSessionRunning(sid, true)

    const controller = new AbortController()
    controllersMap.set(sid, controller)

    // 分析建议回链：使用原始查询上下文，避免后续对话污染
    let history = buildHistory(sid)
    const memory = { ...(initialSession.memory || {}) }
    if (sourceContext && sourceContext.source_sql) {
      memory["last_query"] = {
        question: sourceContext.source_question || question,
        sql: sourceContext.source_sql,
      }
      if (sourceContext.source_entity_context) {
        memory["entity_context"] = sourceContext.source_entity_context
      }
      history = [] // 清空无关对话历史
    }

    try {
      const data = await submitQuery({
        question,
        session_id: sid,
        history,
        session_memory: memory,
      })

      if (pendingMsgMap.get(sid) === placeholderId) {
        updateSessionMessages(sid,
          getCurrentMessages(sid).map(m =>
            m.id === placeholderId ? {
              ...m,
              content: data.answer || m.content,
              sql: data.sql, results: data.results,
              steps: (data.steps && data.steps.length > 0) ? data.steps : (m.steps || []),
              intent: data.intent, needs_clarification: data.needs_clarification,
              clarification_questions: data.clarification_questions,
              clarification_options: data.clarification_options,
              clarification_groups: data.clarification_groups,
              entity_candidates: data.entity_candidates,
              auto_completions: data.auto_completions,
              source: data.source,
              followups: data.followups || data.analysis_suggestions || m.followups,
              analysis_chart: data.analysis_chart,
              analysis_suggestions: data.analysis_suggestions,
              result_groups: data.result_groups,
              rag_thinking: data.rag_thinking,
              rag_references: data.rag_references,
              isThinking: false,
            } : m
          )
        )

        // 同步助手消息到服务端
        if (t) {
          const currentMsg = getCurrentMessages(sid).find(m => m.id === placeholderId)
          apiAppendMessage(sid, {
            id: placeholderId, role: 'assistant',
            content: data.answer, sql: data.sql || null,
            results: data.results ? JSON.stringify(data.results) : null,
            steps: JSON.stringify((currentMsg?.steps && currentMsg.steps.length > 0) ? currentMsg.steps : (data.steps || [])),
            intent: data.intent || null, source: data.source || null,
            followups: JSON.stringify(data.followups || []),
            analysis_chart: data.analysis_chart ? JSON.stringify(data.analysis_chart) : null,
            analysis_suggestions: data.analysis_suggestions ? JSON.stringify(data.analysis_suggestions) : null,
            result_groups: data.result_groups ? JSON.stringify(data.result_groups) : null,
            thinking: currentMsg?.thinking || null,
            rag_thinking: data.rag_thinking || null,
            rag_references: data.rag_references ? JSON.stringify(data.rag_references) : null,
            entity_candidates: JSON.stringify(data.entity_candidates || []),
            needs_clarification: data.needs_clarification || false,
            clarification_options: JSON.stringify(data.clarification_options || []),
            clarification_groups: JSON.stringify(data.clarification_groups || []),
            feedback_status: null, feedback_text: null, timestamp: Date.now(),
          }).catch(() => {})
        }

        setSessionRunning(sid, false)
        pendingMsgMap.delete(sid)

        if (data.session_memory) {
          updateSessionMemory(sid, compactMemory(data.session_memory))
        }

        const pid = placeholderId
        const fullAnswer = data.answer || '未能获取回答。'

        // 判断是否已通过 WebSocket 流式接收了回答内容
        const currentMsg = getCurrentMessages(sid).find(m => m.id === pid)
        const wsStreamedContent = currentMsg?.content && currentMsg.content !== '正在处理...'
          ? currentMsg.content : ''
        const hasStreamedAnswer = wsStreamedContent.length > 0 && data.source === 'agentic_qa'

        const isStreamAnswer = data.source === 'ragflow' && fullAnswer.length > 50

        if (hasStreamedAnswer) {
          // agentic_qa 模式下回答已通过 answer_chunk 流式到达，直接使用当前内容
          updateSessionMessages(sid,
            getCurrentMessages(sid).map(m =>
              m.id === pid ? { ...m, content: fullAnswer } : m
            )
          )
        } else if (isStreamAnswer) {
          startTypewriter(sid, pid, fullAnswer)
        } else {
          setTimeout(() => {
            updateSessionMessages(sid,
              getCurrentMessages(sid).map(m =>
                m.id === pid ? { ...m, content: fullAnswer } : m
              )
            )
          }, 400)
        }
      }
    } catch (err) {
      stopTypewriter()
      if (err.name === 'AbortError') return
      if (sessionExists(sid)) {
        const errorContent = `请求失败: ${err.message}`
        updateSessionMessages(sid,
          getCurrentMessages(sid).map(m =>
            m.id === placeholderId ? { ...m, content: errorContent, isThinking: false, isStreamingAnswer: false } : m
          )
        )
        const t = localStorage.getItem('auth_token')
        if (t) {
          apiAppendMessage(sid, {
            id: placeholderId, role: 'assistant', content: errorContent,
            source: 'agentic_qa', timestamp: Date.now(),
          }).catch(() => {})
        }
      }
      pendingMsgMap.delete(sid)
      setSessionRunning(sid, false)
    } finally {
      controllersMap.delete(sid)
      if (pendingMsgMap.get(sid) === placeholderId) {
        pendingMsgMap.delete(sid)
        setSessionRunning(sid, false)
      }
    }
  }

  async function confirmEntities(question, entities, initialSteps = []) {
    const sid = typeof sessionId === 'function' ? sessionId() : (sessionId?.value || sessionId)
    if (!sid) return
    const session = getSession(sid)
    if (!session) return

    stopTypewriter()

    // 标记实体确认消息为已解决，保留选中状态
    const msgs = getCurrentMessages(sid)
    const clarifyIdx = msgs.findLastIndex(m => m.role === 'assistant' && (m.needs_clarification || (m.entity_candidates && m.entity_candidates.length > 0)))
    if (clarifyIdx >= 0) {
      const clarifyMsg = msgs[clarifyIdx]
      const selectionsByType = {}
      entities.forEach(e => {
        if (!selectionsByType[e.entity_type]) selectionsByType[e.entity_type] = new Set()
        selectionsByType[e.entity_type].add(e.value)
      })
      const updatedCandidates = (clarifyMsg.entity_candidates || []).map(ec => ({
        ...ec,
        resolved: true,
        selected_values: selectionsByType[ec.entity_type] ? [...selectionsByType[ec.entity_type]] : [],
      }))
      updateSessionMessages(sid,
        getCurrentMessages(sid).map(m =>
          m.id === clarifyMsg.id ? { ...m, needs_clarification: false, entity_candidates: updatedCandidates } : m
        )
      )
      const t = localStorage.getItem('auth_token')
      if (t) {
        apiAppendMessage(sid, {
          id: clarifyMsg.id, role: 'assistant',
          content: clarifyMsg.content || '', sql: clarifyMsg.sql || null,
          entity_candidates: JSON.stringify(updatedCandidates),
          needs_clarification: false,
          timestamp: clarifyMsg.timestamp || Date.now(),
        }).catch(() => {})
      }
    }

    // Seed new placeholder with existing steps so timeline continues
    const seededSteps = initialSteps.map(s => {
      if (s.status === 'running') return { ...s, status: 'done' }
      return s
    })
    const placeholderId = nextMsgId()
    pendingMsgMap.set(sid, placeholderId)
    appendMessage(sid, { id: placeholderId, role: 'assistant', content: '正在处理...', steps: seededSteps, thinking: '', isThinking: false, source: 'agentic_qa', timestamp: Date.now() })
    setSessionRunning(sid, true)

    try {
      const history = buildHistory(sid)
      const memory = session.memory || {}
      const data = await confirmQuery({ question, session_id: sid, confirmed_entities: entities, history, session_memory: memory })

      updateSessionMessages(sid,
        getCurrentMessages(sid).map(m =>
          m.id === placeholderId ? {
            ...m,
            content: data.answer || m.content,
            sql: data.sql, results: data.results,
            steps: (data.steps && data.steps.length > 0) ? data.steps : (m.steps || []),
            intent: data.intent, source: data.source,
            followups: data.followups,
            analysis_chart: data.analysis_chart,
            result_groups: data.result_groups,
            analysis_suggestions: data.analysis_suggestions,
            isThinking: false,
          } : m
        )
      )
      setSessionRunning(sid, false)
      pendingMsgMap.delete(sid)

      if (data.session_memory) {
        updateSessionMemory(sid, compactMemory(data.session_memory))
      }

      const pid = placeholderId
      const fullAnswer = data.answer || '未能获取回答。'
      const isRagAnswer = data.source === 'ragflow' && fullAnswer.length > 50

      // 同步确认后的回答到服务端（刷新页面后可恢复）
      const t = localStorage.getItem('auth_token')
      if (t) {
        const currentMsg = getCurrentMessages(sid).find(m => m.id === placeholderId)
        apiAppendMessage(sid, {
          id: placeholderId, role: 'assistant',
          content: fullAnswer, sql: data.sql || null,
          results: data.results ? JSON.stringify(data.results) : null,
          steps: JSON.stringify(data.steps || []),
          intent: data.intent || null, source: data.source || null,
          followups: JSON.stringify(data.followups || []),
          analysis_chart: data.analysis_chart ? JSON.stringify(data.analysis_chart) : null,
          analysis_suggestions: data.analysis_suggestions ? JSON.stringify(data.analysis_suggestions) : null,
          result_groups: data.result_groups ? JSON.stringify(data.result_groups) : null,
          thinking: currentMsg?.thinking || null,
          rag_thinking: data.rag_thinking || null,
          rag_references: data.rag_references ? JSON.stringify(data.rag_references) : null,
          entity_candidates: JSON.stringify(data.entity_candidates || []),
          needs_clarification: data.needs_clarification || false,
          clarification_options: JSON.stringify(data.clarification_options || []),
          clarification_groups: JSON.stringify(data.clarification_groups || []),
          feedback_status: null, feedback_text: null, timestamp: Date.now(),
        }).catch(() => {})
      }

      if (isRagAnswer) {
        startTypewriter(sid, pid, fullAnswer)
      } else {
        setTimeout(() => {
          updateSessionMessages(sid,
            getCurrentMessages(sid).map(m =>
              m.id === pid ? { ...m, content: fullAnswer } : m
            )
          )
        }, 400)
      }
    } catch (err) {
      stopTypewriter()
      if (err.name === 'AbortError') return
      if (sessionExists(sid)) {
        const errorContent = `确认请求失败: ${err.message}`
        updateSessionMessages(sid,
          getCurrentMessages(sid).map(m =>
            m.id === placeholderId ? { ...m, content: errorContent, isThinking: false, isStreamingAnswer: false } : m
          )
        )
        const t = localStorage.getItem('auth_token')
        if (t) {
          apiAppendMessage(sid, {
            id: placeholderId, role: 'assistant', content: errorContent,
            source: 'agentic_qa', timestamp: Date.now(),
          }).catch(() => {})
        }
      }
    } finally {
      setSessionRunning(sid, false)
      pendingMsgMap.delete(sid)
    }
  }

  function resolveMessage(msgId, selections) {
    const sid = typeof sessionId === 'function' ? sessionId() : (sessionId?.value || sessionId)
    if (!sid) return
    updateSessionMessages(sid,
      getCurrentMessages(sid).map(m =>
        m.id === msgId ? {
          ...m,
          needs_clarification: false,
          entity_candidates: (m.entity_candidates || []).map((ec, i) => ({
            ...ec,
            resolved: true,
            selected_values: selections[i] || [],
          })),
        } : m
      )
    )
  }

  function clearMessages() {
    const sid = typeof sessionId === 'function' ? sessionId() : (sessionId?.value || sessionId)
    if (!sid) return
    updateSessionMessages(sid, [])
    updateSessionTitle(sid, '新对话')
  }

  // 计算属性
  function getSessionData() {
    const sid = typeof sessionId === 'function' ? sessionId() : (sessionId?.value || sessionId)
    if (!sid) return { messages: [], sending: false, session: null }
    const session = getSession(sid)
    return {
      messages: session?.messages ?? [],
      sending: session?.running ?? false,
      session,
    }
  }

  return {
    getSessionData,
    sendMessage,
    clearMessages,
    confirmEntities,
    resolveMessage,
    stopTypewriter,
  }
}
