import axios from 'axios'

const client = axios.create({
  baseURL: '/api',
  timeout: 300000,
  headers: { 'Content-Type': 'application/json' },
})

// 请求拦截器：自动附加 JWT token
client.interceptors.request.use((config) => {
  const token = localStorage.getItem('auth_token')
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

// 响应拦截器：解包 res.data
client.interceptors.response.use(
  (res) => res.data,
  (err) => {
    const msg = err.response?.data?.detail || err.response?.data?.msg || err.message || '请求失败'
    console.error('SQL-QA API Error:', msg)
    return Promise.reject(new Error(msg))
  }
)

export default client

// ==================== Auth ====================

export function authLogin(username, password) {
  return client.post('/auth/login', { username, password })
}

export function authMe() {
  return client.get('/auth/me')
}

// ==================== Query ====================

export function submitQuery(params) {
  return client.post('/query', params)
}

export function composeQuestion(params) {
  return client.post('/query/compose', params)
}

export function confirmQuery(params) {
  return client.post('/query/confirm', params)
}


// ==================== Feedback ====================

export function submitFeedback(params) {
  return client.post('/feedback', params)
}

export function recordFeedback(params) {
  return client.post('/feedback/record', params)
}

// ==================== Sessions ====================

export function listSessions(params = {}) {
  return client.get('/sessions', { params })
}

export function createSession(data) {
  return client.post('/sessions', data)
}

export function getSession(sessionId) {
  return client.get(`/sessions/${sessionId}`)
}

export function updateSession(sessionId, data) {
  return client.put(`/sessions/${sessionId}`, data)
}

export function deleteSession(sessionId) {
  return client.delete(`/sessions/${sessionId}`)
}

export function appendMessage(sessionId, data) {
  return client.post(`/sessions/${sessionId}/messages`, data)
}

export function generateTitle(sessionId, data) {
  return client.post(`/sessions/${sessionId}/generate-title`, data)
}

// ==================== Admin - Memories ====================

export function listMemories(params = {}) {
  return client.get('/admin/memories', { params })
}

export function listMemoryThemes() {
  return client.get('/admin/memories/themes')
}

export function deleteMemory(memoryId) {
  return client.delete(`/admin/memories/${memoryId}`)
}

export function batchDeleteMemories(ids) {
  return client.post('/admin/memories/batch-delete', { ids })
}

export function clearMemories(type) {
  return client.delete('/admin/memories', { params: { type } })
}

export function trainMemory(data) {
  return client.post('/admin/memories/train', data)
}

export function exportMemories(type) {
  return client.get('/admin/memories/export', { params: type ? { type } : {}, responseType: 'blob' })
}

export function importMemories(data) {
  return client.post('/admin/memories/import', data)
}

export function editMemory(data) {
  return client.put('/admin/memories/edit', data)
}

// ==================== Admin - Stats ====================

export function getAdminStats() {
  return client.get('/admin/stats')
}

// ==================== Admin - Presets ====================

export function getPresets() {
  return client.get('/admin/presets')
}

export function addPreset(data) {
  return client.post('/admin/presets', data)
}

// ==================== Admin - Entities ====================

export function getEntityRegistry() {
  return client.get('/admin/entities/registry')
}

export function searchEntities(data) {
  return client.post('/admin/entities/search', data)
}

export function rebuildEntityIndex() {
  return client.post('/admin/entities/index')
}

// Entity Configs
export function listEntityConfigs() {
  return client.get('/admin/entities/configs')
}
export function createEntityConfig(data) {
  return client.post('/admin/entities/configs', data)
}
export function updateEntityConfig(id, data) {
  return client.put(`/admin/entities/configs/${id}`, data)
}
export function deleteEntityConfig(id) {
  return client.delete(`/admin/entities/configs/${id}`)
}
export function generateKeywords(data) {
  return client.post('/admin/entities/configs/generate-keywords', data)
}

// Database schema
export function listTables() {
  return client.get('/admin/tables')
}
export function listColumns(tableName) {
  return client.get(`/admin/tables/${tableName}/columns`)
}

// Entity Aliases
export function listAliases(entityType) {
  return client.get('/admin/entities/aliases', { params: { entity_type: entityType } })
}

export function createAlias(data) {
  return client.post('/admin/entities/aliases', data)
}

export function updateAlias(aliasId, data) {
  return client.put(`/admin/entities/aliases/${aliasId}`, data)
}

export function deleteAlias(aliasId) {
  return client.delete(`/admin/entities/aliases/${aliasId}`)
}

export function exportAliases() {
  return client.get('/admin/entities/aliases/export', { responseType: 'blob' })
}

export function importAliases(data) {
  return client.post('/admin/entities/aliases/import', data)
}

// Custom Metrics
export function listMetrics() {
  return client.get('/admin/entities/metrics')
}

export function createMetric(data) {
  return client.post('/admin/entities/metrics', data)
}

export function updateMetric(metricId, data) {
  return client.put(`/admin/entities/metrics/${metricId}`, data)
}

export function deleteMetric(metricId) {
  return client.delete(`/admin/entities/metrics/${metricId}`)
}

export function exportMetrics() {
  return client.get('/admin/entities/metrics/export', { responseType: 'blob' })
}

export function importMetrics(data) {
  return client.post('/admin/entities/metrics/import', data)
}

// ==================== Admin - Schemas ====================

export function getSchemaStatus() {
  return client.get('/admin/schemas/status')
}

export function indexSchemas(tableNames) {
  return client.post('/admin/schemas/index', { table_names: tableNames })
}

export function unindexSchemas(tableNames) {
  return client.post('/admin/schemas/unindex', { table_names: tableNames })
}

// ==================== Admin - Training Review ====================

export function listTrainingReview(params = {}) {
  return client.get('/admin/training-review', { params })
}

export function trainingReviewAction(data) {
  return client.post('/admin/training-review/action', data)
}

// ==================== Admin - Batch Generate ====================

export function startBatchGenerate(data) {
  return client.post('/admin/batch-generate', data)
}

export function getBatchGenerateStatus(jobId) {
  return client.get(`/admin/batch-generate/status/${jobId}`)
}

export function listBatchDraftThemes() {
  return client.get('/admin/batch-drafts/themes')
}

export function listBatchDrafts(params = {}) {
  return client.get('/admin/batch-drafts', { params })
}

export function approveBatchDrafts(data) {
  return client.post('/admin/batch-drafts/approve', data)
}

export function updateBatchDraft(draftId, data) {
  return client.put(`/admin/batch-drafts/${draftId}`, data)
}

export function deleteBatchDrafts(data) {
  return client.post('/admin/batch-drafts/delete', data)
}

// ==================== Admin - Graph ====================

export function reloadGraph() {
  return client.post('/admin/reload-graph')
}

export function getGraphStatus() {
  return client.get('/admin/graph-status')
}

export function getGraphMapping() {
  return client.get('/admin/graph-mapping')
}

export function updateGraphMapping(yaml) {
  return client.put('/admin/graph-mapping', { yaml })
}

export function getGraphMappingExample() {
  return client.get('/admin/graph-mapping/example')
}

// ==================== RAGFlow ====================

export function getDocumentPreview(datasetId, documentId) {
  return client.get('/ragflow/document-preview', { params: { dataset_id: datasetId, document_id: documentId } })
}

export function getDocumentDownloadUrl(datasetId, documentId) {
  return `/api/ragflow/document-download?dataset_id=${datasetId}&document_id=${documentId}`
}

// ==================== Health ====================

export function getHealth() {
  return client.get('/health')
}

// ==================== Init ====================

export function initVanna() {
  return client.post('/init')
}

// ==================== WebSocket ====================

export function getWebSocketUrl(sessionId) {
  const token = localStorage.getItem('auth_token')
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  const host = window.location.host
  return `${protocol}//${host}/api/ws/${sessionId}?token=${encodeURIComponent(token || '')}`
}
