import axios from './client'

// axios 实例的 baseURL 已是 '/api'，此处只追加路径段
// 拦截器 (res) => res.data 已将响应解包，所以 await 直接返回数据本体
const BASE = '/kb-qa'

export const kbQaClient = {
  // KB 列表
  async listKbs() {
    return await axios.get(`${BASE}/kbs`)
  },

  // 会话
  async listSessions() {
    return await axios.get(`${BASE}/sessions`)
  },

  async createSession(title = '新会话') {
    return await axios.post(`${BASE}/sessions`, { title })
  },

  async deleteSession(sessionId) {
    return await axios.delete(`${BASE}/sessions/${sessionId}`)
  },

  // 消息
  async listMessages(sessionId) {
    return await axios.get(`${BASE}/sessions/${sessionId}/messages`)
  },

  // 提问（非流式）
  async chat({ sessionId, question, manualKbIds = [] }) {
    return await axios.post(`${BASE}/chat`, {
      session_id: sessionId,
      question,
      manual_kb_ids: manualKbIds,
    })
  },

  // 提问（流式 SSE）
  async chatStream({ sessionId, question, manualKbIds = [], onChunk, onDone, onError }) {
    const token = localStorage.getItem('auth_token')
    const response = await fetch('/api/kb-qa/chat/stream', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${token}`,
      },
      body: JSON.stringify({
        session_id: sessionId,
        question,
        manual_kb_ids: manualKbIds,
      }),
    })

    if (!response.ok) {
      const errText = await response.text().catch(() => '')
      throw new Error(errText || `HTTP ${response.status}`)
    }

    const reader = response.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''

    while (true) {
      const { done, value } = await reader.read()
      if (done) break

      buffer += decoder.decode(value, { stream: true })
      const lines = buffer.split('\n')
      // 最后一行可能不完整，保留到下次
      buffer = lines.pop() || ''

      for (const line of lines) {
        if (!line.startsWith('data: ')) continue
        try {
          const event = JSON.parse(line.slice(6))
          switch (event.type) {
            case 'chunk':
              onChunk?.(event.content)
              // 一个网络数据包可能包含多个 SSE 事件；让出事件循环，避免 Vue 将所有增量合并成一次绘制。
              await new Promise(resolve => setTimeout(resolve, 0))
              break
            case 'done':
              onDone?.(event)
              break
            case 'error':
              onError?.(new Error(event.message || '未知错误'))
              break
          }
        } catch (_e) {
          // 跳过解析失败的行
        }
      }
    }

    // 流结束后 flush decoder 并处理 buffer 中残留的最后一行数据
    // 防止连接关闭时最后一个 SSE 事件（done/error）因缺少尾部换行而被丢弃
    buffer += decoder.decode()
    if (buffer.trim()) {
      const line = buffer.trim()
      if (line.startsWith('data: ')) {
        try {
          const event = JSON.parse(line.slice(6))
          switch (event.type) {
            case 'chunk':
              onChunk?.(event.content)
              await new Promise(resolve => setTimeout(resolve, 0))
              break
            case 'done':
              onDone?.(event)
              break
            case 'error':
              onError?.(new Error(event.message || '未知错误'))
              break
          }
        } catch (_e) {
          // 跳过解析失败的行
        }
      }
    }
  },

  // 文档预览（base64）
  async previewDocument({ datasetId, documentId }) {
    return await axios.get(`${BASE}/ragflow/document-preview`, {
      params: { dataset_id: datasetId, document_id: documentId },
    })
  },

  // 文档下载 URL（直接返回给浏览器，用于 <a href>）
  getDocumentDownloadUrl({ datasetId, documentId }) {
    return `/api${BASE}/ragflow/document-download?dataset_id=${datasetId}&document_id=${documentId}`
  },
}
