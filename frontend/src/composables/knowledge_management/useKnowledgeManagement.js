import { ref, reactive, computed } from 'vue'
import {
  getDashboardBase as apiGetDashboardBase,
  getDashboardWorkshop as apiGetDashboardWorkshop,
  listKnowledgeBases as apiListKBs,
  getKnowledgeBase as apiGetKB,
  createKnowledgeBase as apiCreateKB,
  updateKnowledgeBase as apiUpdateKB,
  deleteKnowledgeBase as apiDeleteKB,
  getRAGDocuments as apiGetRAGDocs,
  listCategories as apiListCategories,
  createCategory as apiCreateCategory,
  updateCategory as apiUpdateCategory,
  deleteCategory as apiDeleteCategory,
  listTargets as apiListTargets,
  createTarget as apiCreateTarget,
  updateTarget as apiUpdateTarget,
  deleteTarget as apiDeleteTarget,
  listPlans as apiListPlans,
  getPlan as apiGetPlan,
  createPlan as apiCreatePlan,
  updatePlan as apiUpdatePlan,
  deletePlan as apiDeletePlan,
  createPlanItem as apiCreatePlanItem,
  updatePlanItem as apiUpdatePlanItem,
  deletePlanItem as apiDeletePlanItem,
  uploadDocuments as apiUploadDocs,
  getVersionProgress as apiGetVersionProgress,
  setDocumentFileType as apiSetFileType,
  triggerAIReview as apiTriggerAIReview,
  submitApproval as apiSubmitApproval,
  publishToRAGFlow as apiPublish,
  listDocumentVersions as apiListVersions,
  deleteDocument as apiDeleteDocument,
  getPlanProgress as apiGetPlanProgress,
  getPlanItemEvaluation as apiGetPlanItemEvaluation,
  evaluatePlanItem as apiEvaluatePlanItem,
  getRAGDocChunks as apiGetRAGDocChunks,
} from '../../api/knowledgeManagementClient.js'

// 模块级状态（单例）
const knowledgeBases = ref([])
const currentKB = ref(null)
const categories = ref([])
const targets = ref([])
const plans = ref([])
const currentPlan = ref(null)
const ragDocuments = ref([])
const loading = reactive({
  kbs: true,
  categories: true,
  targets: true,
  plans: true,
  plan: true,
  ragDocs: true,
})

// Dashboard 数据缓存（跨页面共享，60秒内不重复请求）
const dashboardCache = ref(null)
let dashboardCacheTime = 0
const DASHBOARD_CACHE_TTL = 60000  // 60秒

export function useKnowledgeManagement() {
  // ==================== Dashboard 缓存 ====================

  async function fetchDashboardBase(force = false) {
    if (!force && dashboardCache.value && (Date.now() - dashboardCacheTime) < DASHBOARD_CACHE_TTL) {
      return dashboardCache.value
    }
    const data = await apiGetDashboardBase()
    dashboardCache.value = data
    dashboardCacheTime = Date.now()
    return data
  }

  async function fetchDashboardWorkshop(kbType, force = false) {
    // Workshop数据变化慢，复用dashboard缓存
    return await apiGetDashboardWorkshop(kbType)
  }

  function invalidateDashboardCache() {
    dashboardCache.value = null
    dashboardCacheTime = 0
  }

  // ==================== 知识库 ====================

  function _extractData(resp) {
    // 响应拦截器已自动解包 {code, data} → data，此处处理各种 data 格式
    if (Array.isArray(resp)) return resp
    if (!resp || typeof resp !== 'object') return resp
    // 优先判断：单对象（KB 详情等）有明确业务字段就返回
    // 注意: 使用 'id' in resp 而不是 resp.id，因为 id 可能为 0 或其他 falsy 值
    // 同时检查 name 和 kb_type 以增强识别能力
    const hasId = 'id' in resp && typeof resp.id === 'string'
    const hasName = 'name' in resp && typeof resp.name === 'string'
    const hasKbType = 'kb_type' in resp && typeof resp.kb_type === 'string'
    if (hasId && (hasName || hasKbType)) return resp
    if (hasKbType || hasName) return resp
    // 分页列表: {items: [...], total: N}
    if (Array.isArray(resp.items)) return resp.items
    // RAGFlow 格式: {docs: [...], total: N}
    if (Array.isArray(resp.docs)) return resp.docs
    // 旧格式: {documents: [...]}
    if (Array.isArray(resp.documents)) return resp.documents
    // 旧版嵌套格式（仅在 resp.data 是有效对象且有业务字段时解包）
    if (resp.data && typeof resp.data === 'object' && !Array.isArray(resp.data)) {
      if (('id' in resp.data) || ('name' in resp.data)) return resp.data
    }
    // 兜底：返回空数组（并警告）
    console.warn('[useKnowledgeManagement] _extractData 无法识别数据格式，返回 []:', typeof resp, Object.keys(resp || {}).slice(0, 10))
    return []
  }

  async function fetchKnowledgeBases(params = {}) {
    // 只在无缓存数据时显示 loading，避免已加载页面闪烁
    if (knowledgeBases.value.length === 0) loading.kbs = true
    try {
      const resp = await apiListKBs(params)
      knowledgeBases.value = _extractData(resp) || []
    } catch (err) {
      console.error('获取知识库列表失败:', err.message)
      knowledgeBases.value = []
    } finally {
      loading.kbs = false
    }
  }

  async function fetchKnowledgeBase(id) {
    try {
      const data = await apiGetKB(id)
      currentKB.value = _extractData(data)
      return currentKB.value
    } catch (err) {
      console.error('获取知识库详情失败:', err.message)
      currentKB.value = null
      throw err
    }
  }

  async function createKnowledgeBase(data) {
    const resp = await apiCreateKB(data)
    const kb = _extractData(resp)
    knowledgeBases.value.unshift(kb)
    return kb
  }

  async function updateKnowledgeBase(id, data) {
    const resp = await apiUpdateKB(id, data)
    const kb = _extractData(resp)
    const idx = knowledgeBases.value.findIndex(k => k.id === id)
    if (idx >= 0) knowledgeBases.value[idx] = kb
    if (currentKB.value?.id === id) currentKB.value = kb
    return kb
  }

  async function deleteKnowledgeBase(id) {
    await apiDeleteKB(id)
    knowledgeBases.value = knowledgeBases.value.filter(k => k.id !== id)
    if (currentKB.value?.id === id) currentKB.value = null
  }

  // ==================== RAGFlow 文档 ====================

  async function fetchRAGDocuments(kbId, params = {}) {
    if (ragDocuments.value.length === 0) loading.ragDocs = true
    try {
      const data = await apiGetRAGDocs(kbId, params)
      ragDocuments.value = _extractData(data) || []
      return data
    } catch (err) {
      console.error('获取 RAGFlow 文档失败:', err.message)
      ragDocuments.value = []
    } finally {
      loading.ragDocs = false
    }
  }

  // ==================== 文档类别 ====================

  async function fetchCategories(kbId) {
    if (categories.value.length === 0) loading.categories = true
    try {
      const data = await apiListCategories(kbId)
      categories.value = _extractData(data) || []
    } catch (err) {
      console.error('获取类别列表失败:', err.message)
      categories.value = []
    } finally {
      loading.categories = false
    }
  }

  async function createCategory(kbId, data) {
    const resp = await apiCreateCategory(kbId, data)
    const cat = _extractData(resp)
    categories.value.push(cat)
    return cat
  }

  async function updateCategory(id, data) {
    const resp = await apiUpdateCategory(id, data)
    const cat = _extractData(resp)
    const idx = categories.value.findIndex(c => c.id === id)
    if (idx >= 0) categories.value[idx] = cat
    return cat
  }

  async function deleteCategory(id) {
    await apiDeleteCategory(id)
    categories.value = categories.value.filter(c => c.id !== id)
  }

  // ==================== 收集对象 ====================

  async function fetchTargets(kbId) {
    if (targets.value.length === 0) loading.targets = true
    try {
      const data = await apiListTargets(kbId)
      targets.value = _extractData(data) || []
    } catch (err) {
      console.error('获取收集对象失败:', err.message)
      targets.value = []
    } finally {
      loading.targets = false
    }
  }

  async function createTarget(kbId, data) {
    const resp = await apiCreateTarget(kbId, data)
    const tgt = _extractData(resp)
    targets.value.push(tgt)
    return tgt
  }

  async function updateTarget(id, data) {
    const resp = await apiUpdateTarget(id, data)
    const tgt = _extractData(resp)
    const idx = targets.value.findIndex(t => t.id === id)
    if (idx >= 0) targets.value[idx] = tgt
    return tgt
  }

  async function deleteTarget(id) {
    await apiDeleteTarget(id)
    targets.value = targets.value.filter(t => t.id !== id)
  }

  // ==================== 收集计划 ====================

  async function fetchPlans(kbId) {
    if (plans.value.length === 0) loading.plans = true
    try {
      const data = await apiListPlans(kbId)
      plans.value = _extractData(data) || []
    } catch (err) {
      console.error('获取计划列表失败:', err.message)
      plans.value = []
    } finally {
      loading.plans = false
    }
  }

  async function fetchPlan(id) {
    if (!currentPlan.value || currentPlan.value.id !== id) loading.plan = true
    try {
      const data = await apiGetPlan(id)
      currentPlan.value = _extractData(data)
      return currentPlan.value
    } catch (err) {
      console.error('获取计划详情失败:', err.message)
      currentPlan.value = null
      throw err
    } finally {
      loading.plan = false
    }
  }

  async function createPlan(data) {
    const resp = await apiCreatePlan(data)
    const plan = _extractData(resp)
    plans.value.unshift(plan)
    return plan
  }

  async function updatePlan(id, data) {
    const resp = await apiUpdatePlan(id, data)
    const plan = _extractData(resp)
    const idx = plans.value.findIndex(p => p.id === id)
    if (idx >= 0) plans.value[idx] = plan
    if (currentPlan.value?.id === id) currentPlan.value = plan
    return plan
  }

  async function deletePlan(id) {
    await apiDeletePlan(id)
    plans.value = plans.value.filter(p => p.id !== id)
    if (currentPlan.value?.id === id) currentPlan.value = null
  }

  async function createPlanItem(data) {
    const item = await apiCreatePlanItem(data)
    if (currentPlan.value?.plan_items) {
      // 重新获取计划以获取完整数据（含关联 category/target）
      // 简化处理：追加到列表
      currentPlan.value.plan_items.push(item)
    }
    return item
  }

  async function updatePlanItem(id, data) {
    const item = await apiUpdatePlanItem(id, data)
    if (currentPlan.value?.plan_items) {
      const idx = currentPlan.value.plan_items.findIndex(i => i.id === id)
      if (idx >= 0) currentPlan.value.plan_items[idx] = { ...currentPlan.value.plan_items[idx], ...item }
    }
    return item
  }

  async function deletePlanItem(id) {
    await apiDeletePlanItem(id)
    if (currentPlan.value?.plan_items) {
      currentPlan.value.plan_items = currentPlan.value.plan_items.filter(i => i.id !== id)
    }
  }

  // ==================== 文档操作 ====================

  async function uploadDocuments(planItemId, formData) {
    return await apiUploadDocs(planItemId, formData)
  }

  async function getVersionProgress(versionId) {
    return await apiGetVersionProgress(versionId)
  }

  async function setDocumentFileType(documentId, fileType) {
    return await apiSetFileType(documentId, { file_type: fileType })
  }

  async function triggerAIReview(versionId) {
    return await apiTriggerAIReview(versionId)
  }

  async function submitApproval(versionId, action, reason = '') {
    return await apiSubmitApproval(versionId, { action, reason })
  }

  async function publishToRAGFlow(versionId) {
    return await apiPublish(versionId)
  }

  async function listDocumentVersions(documentId) {
    return await apiListVersions(documentId)
  }

  async function deleteDocument(documentId) {
    return await apiDeleteDocument(documentId)
  }

  // ==================== 评估 ====================

  async function fetchPlanProgress(planId) {
    return await apiGetPlanProgress(planId)
  }

  async function fetchPlanItemEvaluation(planItemId) {
    return await apiGetPlanItemEvaluation(planItemId)
  }

  async function triggerPlanItemEvaluation(planItemId) {
    return await apiEvaluatePlanItem(planItemId)
  }

  // ==================== RAGFlow 切片 ====================

  async function fetchRAGDocChunks(docId, params = {}) {
    return await apiGetRAGDocChunks(docId, params)
  }

  return {
    // 状态
    knowledgeBases,
    currentKB,
    categories,
    targets,
    plans,
    currentPlan,
    ragDocuments,
    loading,

    // Dashboard
    fetchDashboardBase,
    fetchDashboardWorkshop,
    invalidateDashboardCache,

    // 知识库
    fetchKnowledgeBases,
    fetchKnowledgeBase,
    createKnowledgeBase,
    updateKnowledgeBase,
    deleteKnowledgeBase,

    // RAGFlow 文档
    fetchRAGDocuments,

    // 类别
    fetchCategories,
    createCategory,
    updateCategory,
    deleteCategory,

    // 收集对象
    fetchTargets,
    createTarget,
    updateTarget,
    deleteTarget,

    // 计划
    fetchPlans,
    fetchPlan,
    createPlan,
    updatePlan,
    deletePlan,
    createPlanItem,
    updatePlanItem,
    deletePlanItem,

    // 文档操作
    uploadDocuments,
    getVersionProgress,
    setDocumentFileType,
    triggerAIReview,
    submitApproval,
    publishToRAGFlow,
    listDocumentVersions,
    deleteDocument,

    // 评估
    fetchPlanProgress,
    fetchPlanItemEvaluation,
    triggerPlanItemEvaluation,

    // 切片
    fetchRAGDocChunks,
  }
}
