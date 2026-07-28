import { ref, computed, watch, onMounted } from 'vue'
import { useSqlQaAuth } from './useSqlQaAuth.js'
import { listSessions, createSession as apiCreateSession, deleteSession as apiDeleteSession, updateSession as apiUpdateSession, getSession as apiGetSession } from '../../api/sqlQaClient.js'

const STORAGE_KEY = 'ai-qa-sessions'

// 模块级状态（单例）
const sessions = ref([])
const activeId = ref(null)
const sessionsLoaded = ref(false)

let _msgId = 0

export function nextMsgId() {
  return `msg-${Date.now()}-${++_msgId}`
}

function loadSessions() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    return raw ? JSON.parse(raw) : []
  } catch {
    return []
  }
}

function saveSessions(data) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(data))
  } catch {}
}

export function useSqlQaSessions() {
  const { isAuthenticated, token } = useSqlQaAuth()

  // 初始加载：认证后从 API 获取
  async function fetchSessions() {
    if (!isAuthenticated() || sessionsLoaded.value) return
    try {
      const data = await listSessions({ limit: 100 })
      if (data.sessions && data.sessions.length > 0) {
        sessions.value = data.sessions.map((s) => {
          let memory = s.memory
          if (typeof memory === 'string') {
            try { memory = JSON.parse(memory) } catch { memory = {} }
          }
          if (!memory || typeof memory !== 'object') memory = {}
          return {
            ...s,
            messages: [],
            memory,
            running: false,
            createdAt: typeof s.created_at === 'string' ? new Date(s.created_at).getTime() : (s.created_at || Date.now()),
            updatedAt: typeof s.updated_at === 'string' ? new Date(s.updated_at).getTime() : (s.updated_at || Date.now()),
          }
        })
        if (!activeId.value && data.sessions.length > 0) {
          activeId.value = data.sessions[0].id
        }
      } else {
        // 服务端无会话
        if (sessions.value.length === 0) {
          createSession()
        }
      }
    } catch {
      // API 不可达，本地也无会话则创建
      if (sessions.value.length === 0) {
        createSession()
      }
    } finally {
      sessionsLoaded.value = true
    }
  }

  // 认证状态变化时加载
  watch(() => isAuthenticated(), (authed) => {
    if (authed) {
      fetchSessions()
    } else {
      sessionsLoaded.value = false
    }
  }, { immediate: true })

  // 持久化到 localStorage
  watch(sessions, (val) => {
    saveSessions(val)
  }, { deep: true })

  function createSession() {
    const session = {
      id: `session-${Date.now()}`,
      title: '新对话',
      messages: [],
      createdAt: Date.now(),
      updatedAt: Date.now(),
      running: false,
      memory: {},
    }
    sessions.value = [session, ...sessions.value]
    activeId.value = session.id
    // 同步到 API
    apiCreateSession({ id: session.id, title: session.title }).catch(() => {})
    return session
  }

  function setActiveId(id) {
    activeId.value = id
  }

  function deleteSession(id) {
    sessions.value = sessions.value.filter(s => s.id !== id)
    if (activeId.value === id) {
      activeId.value = sessions.value.length > 0 ? sessions.value[0].id : null
    }
    apiDeleteSession(id).catch(() => {})
  }

  function updateSessionTitle(id, title) {
    const s = sessions.value.find(s => s.id === id)
    if (s) {
      s.title = title
      s.updatedAt = Date.now()
      apiUpdateSession(id, { title }).catch(() => {})
    }
  }

  function getSession(id) {
    return sessions.value.find(s => s.id === id)
  }

  function updateSessionMessages(id, messages) {
    const s = sessions.value.find(s => s.id === id)
    if (s) {
      s.messages = messages
      s.updatedAt = Date.now()
    }
  }

  function appendMessage(id, msg) {
    const s = sessions.value.find(s => s.id === id)
    if (s) {
      s.messages = [...s.messages, msg]
      s.updatedAt = Date.now()
    }
  }

  function sessionExists(id) {
    return sessions.value.some(s => s.id === id)
  }

  function setSessionRunning(id, running) {
    const s = sessions.value.find(s => s.id === id)
    if (s) {
      s.running = running
    }
  }

  function updateSessionMemory(id, memory) {
    const s = sessions.value.find(s => s.id === id)
    if (s) {
      s.memory = memory
      s.updatedAt = Date.now()
      apiUpdateSession(id, { memory: JSON.stringify(memory) }).catch(() => {})
    }
  }

  // 懒加载会话消息
  async function loadSessionMessages(sessionId) {
    try {
      const data = await apiGetSession(sessionId)
      return data.messages || []
    } catch {
      return []
    }
  }

  // 当 activeId 变化时，懒加载其消息
  watch(activeId, async (newId) => {
    if (!newId) return
    const session = getSession(newId)
    if (!session || session.messages.length > 0) return
    const msgs = await loadSessionMessages(newId)
    if (msgs.length > 0) {
      updateSessionMessages(newId, msgs)
    }
  })

  return {
    sessions,
    activeId,
    setActiveId,
    createSession,
    deleteSession,
    updateSessionTitle,
    getSession,
    updateSessionMessages,
    appendMessage,
    sessionExists,
    setSessionRunning,
    updateSessionMemory,
  }
}
