import axios from 'axios'

const client = axios.create({
  baseURL: '/api/knowledge-management',
  timeout: 120000,
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

// 响应拦截器：仅当响应是 success_response 包装时解包 data
client.interceptors.response.use(
  (res) => {
    const body = res.data
    // 严格的 success_response 包装：必须同时有 code 和 data 字段
    if (body && typeof body === 'object' && 'code' in body && 'data' in body) {
      return body.data
    }
    // 否则直接返回（如 dashboard 端点返回的纯 dict）
    return body
  },
  (err) => {
    const msg = err.response?.data?.detail || err.response?.data?.msg || err.message || '请求失败'
    console.error('Knowledge Management API Error:', msg)
    return Promise.reject(new Error(msg))
  }
)

export default client

// ==================== 知识库管理 ====================

export function createKnowledgeBase(data) {
  return client.post('/bases', data)
}

export function listKnowledgeBases(params = {}) {
  return client.get('/bases', { params })
}

export function getKnowledgeBase(id) {
  return client.get(`/bases/${id}`)
}

export function updateKnowledgeBase(id, data) {
  return client.put(`/bases/${id}`, data)
}

export function deleteKnowledgeBase(id) {
  return client.delete(`/bases/${id}`)
}

export function getRAGDocuments(kbId, params = {}) {
  return client.get(`/bases/${kbId}/rag-documents`, { params })
}

// ==================== 文档类别 ====================

export function createCategory(kbId, data) {
  return client.post(`/bases/${kbId}/categories`, data)
}

export function listCategories(kbId) {
  return client.get(`/bases/${kbId}/categories`)
}

export function updateCategory(id, data) {
  return client.put(`/categories/${id}`, data)
}

export function deleteCategory(id) {
  return client.delete(`/categories/${id}`)
}

// ==================== 收集对象 ====================

export function createTarget(kbId, data) {
  return client.post(`/bases/${kbId}/targets`, data)
}

export function listTargets(kbId) {
  return client.get(`/bases/${kbId}/targets`)
}

export function updateTarget(id, data) {
  return client.put(`/targets/${id}`, data)
}

export function deleteTarget(id) {
  return client.delete(`/targets/${id}`)
}

// ==================== 收集计划 ====================

export function createPlan(data) {
  return client.post('/plans', data)
}

export function listPlans(kbId) {
  return client.get(`/bases/${kbId}/plans`)
}

export function getPlan(id) {
  return client.get(`/plans/${id}`)
}

export function updatePlan(id, data) {
  return client.put(`/plans/${id}`, data)
}

export function deletePlan(id) {
  return client.delete(`/plans/${id}`)
}

export function createPlanItem(data) {
  return client.post('/plan-items', data)
}

export function updatePlanItem(id, data) {
  return client.put(`/plan-items/${id}`, data)
}

export function deletePlanItem(id) {
  return client.delete(`/plan-items/${id}`)
}

// ==================== 文档操作 ====================

export function uploadDocuments(planItemId, formData) {
  return client.post(`/plan-items/${planItemId}/upload`, formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
    timeout: 300000,
  })
}

export function getVersionProgress(versionId) {
  return client.get(`/versions/${versionId}/progress`)
}

export function setDocumentFileType(documentId, data) {
  return client.put(`/documents/${documentId}/filetype`, data)
}

export function triggerAIReview(versionId) {
  return client.post(`/versions/${versionId}/ai-review`)
}

export function submitApproval(versionId, data) {
  return client.post(`/versions/${versionId}/approval`, data)
}

export function publishToRAGFlow(versionId) {
  return client.post(`/versions/${versionId}/publish`)
}

export function listDocumentVersions(documentId) {
  return client.get(`/documents/${documentId}/versions`)
}

export function getDocumentPreviewUrl(versionId) {
  // 不将 token 暴露在 URL 中，由拦截器自动附加 Authorization header
  return `/api/knowledge-management/versions/${versionId}/preview`
}

export function getDocumentDownloadUrl(versionId) {
  return `/api/knowledge-management/versions/${versionId}/download`
}

export function deleteDocument(documentId) {
  return client.delete(`/documents/${documentId}`)
}

export function updateDocument(documentId, data) {
  return client.put(`/documents/${documentId}`, data)
}

export function deleteVersion(versionId) {
  return client.delete(`/versions/${versionId}`)
}

// ==================== 评估 ====================

export function getPlanProgress(planId) {
  return client.get(`/plans/${planId}/progress`)
}

export function getPlanItemEvaluation(planItemId) {
  return client.get(`/plan-items/${planItemId}/evaluation`)
}

export function evaluatePlanItem(planItemId) {
  return client.post(`/plan-items/${planItemId}/evaluate`)
}

// ==================== 解析状态 ====================

export function getParseStatus(versionId) {
  return client.get(`/versions/${versionId}/parse-status`)
}

export function reparseDocument(versionId) {
  return client.post(`/versions/${versionId}/reparse`)
}

export function stopParse(versionId) {
  return client.post(`/versions/${versionId}/stop-parse`)
}

// ==================== RAGFlow 文档查看 ====================

export function getRAGDocChunks(docId, params = {}) {
  return client.get(`/rag-documents/${docId}/chunks`, { params })
}

export function getRAGDocPreviewUrl(docId) {
  return `/api/knowledge-management/rag-documents/${docId}/preview`
}

// ===== 知识库文档搜索 =====
export const searchDocuments = (params) => client.get('/documents/search', { params })

// ===== 知识库文档树（左侧树展开用） =====
export const getKbDocumentsTree = (kbId) => client.get(`/bases/${kbId}/documents-tree`)

// ===== 看板 =====
export const getDashboardBase = () => client.get('/dashboard/base')
export const getDashboardWorkshop = (kbType) => client.get('/dashboard/workshop', { params: { kb_type: kbType } })
export const getDashboardDevice = (kbId) => client.get(`/dashboard/device/${kbId}`)

// ===== 预设类别 =====
export const getPresetCategories = () => client.get('/preset-categories', { params: { flat: true } })
export const createPresetCategory = (data) => client.post('/admin/preset-categories', data)
export const updatePresetCategory = (id, data) => client.put(`/admin/preset-categories/${id}`, data)
export const deletePresetCategory = (id) => client.delete(`/admin/preset-categories/${id}`)
export const syncPresetCategories = (categoryType) => client.post('/admin/preset-categories/sync', { category_type: categoryType })

// ===== 同步 =====
export const syncDeviceTypes = () => client.post('/sync/device-types')
export const getSyncStatus = () => client.get('/sync/device-types/status')

// ===== 不适用标记 =====
export const markNotApplicable = (itemId, reason) => client.put(`/plan-items/${itemId}/not-applicable`, { reason })
export const unmarkNotApplicable = (itemId) => client.delete(`/plan-items/${itemId}/not-applicable`)

// ===== 合规性 =====
export const updateComplianceDates = (versionId, data) => client.put(`/versions/${versionId}/compliance-dates`, data)
export const retryReview = (versionId) => client.post(`/versions/${versionId}/retry-review`)

// ===== 操作日志 =====
export const getOperationLogs = (params) => client.get('/operation-logs', { params })

// ===== 自定义知识库 =====
export const createCustomKnowledgeBase = (data) => client.post('/bases', { kb_type: 'custom_base', sync_type: 'manual', ...data })

// ===== 知识库按设备类型查询 =====
export const getDeviceKnowledgeBases = (workshopName, kbType, page = 1, pageSize = 50) =>
  listKnowledgeBases({ workshop: workshopName, kb_type: kbType, page, page_size: pageSize })

// ===== 知识库类型启用/禁用状态 =====
export const getKbTypeStates = () => client.get('/kb-type-states')
export const setKbTypeState = (kbType, enabled) => client.put(`/kb-type-states/${kbType}`, { enabled })

// ===== 知识库健康度评估 =====
export const getKnowledgeOverview = () => client.get('/dashboard/knowledge-overview')
export const getKnowledgeOverviewSummary = () => client.get('/dashboard/knowledge-overview/summary')
