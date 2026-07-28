import axios from 'axios'

const client = axios.create({
  baseURL: '/api',
  timeout: 60000,
  headers: { 'Content-Type': 'application/json' },
})

// 请求拦截器：自动附加登录令牌
client.interceptors.request.use((config) => {
  const token = localStorage.getItem('auth_token')
  if (token) {
    config.headers = config.headers || {}
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

client.interceptors.response.use(
  (res) => res.data,
  (err) => {
    const status = err.response?.status
    // 登录失效：清理本地状态并跳转登录页（登录接口自身的 401 不跳转）
    const url = err.config?.url || ''
    if (status === 401 && !url.includes('/auth/login')) {
      localStorage.removeItem('auth_token')
      localStorage.removeItem('auth_user')
      if (window.location.pathname !== '/login') {
        window.location.assign('/login')
      }
    }
    const msg = err.response?.data?.msg || err.message || '请求失败'
    console.error('API Error:', msg)
    return Promise.reject(new Error(msg))
  }
)

export default client

// ==================== 用户认证 ====================

export async function login(payload) {
  return client.post('/auth/login', payload)
}

export async function getCurrentUser() {
  return client.get('/auth/me')
}

export async function logout() {
  return client.post('/auth/logout')
}

// ==================== 健康检查 ====================

export async function getHealth() {
  return client.get('/health')
}

// ==================== 质量报告 (daily_report) ====================

export async function getTemplates() {
  return client.get('/templates')
}

// ==================== 设备分析 ====================

export async function getDeviceModules() {
  return client.get('/device_analysis/modules')
}

export async function runDeviceAnalysis(params) {
  return client.post('/device_analysis', params)
}

// ==================== 任务调度 (jobs) ====================
// 预测性维护报告的 APScheduler 调度状态（供任务管理页只读展示）
export async function getScheduledJobs() {
  return client.get('/jobs/scheduled')
}

// ==================== 报警记录 ====================

export async function getAlarms(params = {}) {
  return client.get('/alarms', { params })
}

export async function getAlarmStatistics(params = {}) {
  return client.get('/alarms/statistics', { params })
}

export async function getAlarmDevices() {
  return client.get('/alarms/devices')
}

export async function getAlarmTypes(params = {}) {
  return client.get('/alarms/types', { params })
}

// ==================== 报警分析 ====================

export async function runAlarmAnalysis(params) {
  return client.post('/alarms/analysis', params)
}

export async function getAlarmAnalysisHistory(params = {}) {
  return client.get('/alarms/analysis/history', { params })
}

export async function getAlarmAnalysisDetail(params = {}) {
  return client.get('/alarms/analysis/detail', { params })
}

// ==================== 文档分析 ====================

export async function analyzeDocument(params) {
  return client.post('/document_analysis', params)
}

// ==================== 预测性维护报告 (maintenance-reports) ====================

export async function generateMaintenanceReport(params) {
  return client.post('/maintenance-reports/generate', params)
}

export async function generateBatchReports(params) {
  return client.post('/maintenance-reports/generate/batch', params)
}

export async function listMaintenanceReports(params = {}) {
  return client.get('/maintenance-reports/list', { params })
}

export async function getMaintenanceReportDetail(reportId) {
  return client.get(`/maintenance-reports/detail/${reportId}`)
}

export async function deleteMaintenanceReport(reportId) {
  return client.delete(`/maintenance-reports/delete/${reportId}`)
}

export async function getMaintenanceReportSummary(reportType, reportDate) {
  return client.get(`/maintenance-reports/summary/${reportType}/${reportDate}`)
}

export async function getWorkshopSummaries(params = {}) {
  return client.get('/maintenance-reports/workshop-summary', { params })
}

export async function listMaintenanceDevices(params = {}) {
  return client.get('/maintenance-reports/devices', { params })
}

export async function triggerReportGeneration(params) {
  return client.post('/maintenance-reports/schedule/trigger', params)
}

export async function listMaintenanceReportJobs(params = {}) {
  return client.get('/maintenance-reports/jobs', { params })
}

export async function getMaintenanceReportJobDetail(jobId) {
  return client.get(`/maintenance-reports/jobs/${jobId}`)
}

export async function getMaintenanceScheduleStatus() {
  return client.get('/maintenance-reports/schedule/status')
}

export async function getMaintenanceTemplates() {
  return client.get('/maintenance-reports/templates')
}

// ==================== 维修建议 (repair-suggestion 服务) ====================

export async function getRepairSuggestion(params) {
  return client.post('/repair-suggestion', params)
}

export async function scoreRepairOrder(params) {
  return client.post('/repair-order-scoring', params)
}

// ==================== 设备参数监控 ====================

export async function getDeviceParamDevices() {
  return client.get('/device-params/devices')
}

export async function getDeviceParamPoints(deviceCode) {
  return client.get('/device-params/points', { params: { device_code: deviceCode } })
}

export async function getDeviceParamData(params) {
  return client.get('/device-params/data', { params, timeout: 300000 })
}

export async function getRunningPeriods(params) {
  return client.get('/device-params/running-periods', { params })
}

export async function getAlignedData(params) {
  return client.get('/device-params/aligned-data', { params })
}

export async function getDeviceFeatures(params) {
  return client.get('/device-params/features', { params })
}

export async function detectAnomalies(params) {
  return client.post('/device-params/anomaly/detect', params)
}

export async function getAnomalyThresholds(params) {
  return client.get('/device-params/anomaly/thresholds', { params })
}

export async function analyzeDeviceParams(params) {
  return client.post('/device-params/analyze', params)
}

export async function getAnalysisLog(params) {
  return client.get('/device-params/analysis-log', { params })
}

export async function getStageAnalysis(params) {
  return client.get('/device-params/stage-analysis', { params, timeout: 300000 })
}

export async function saveStageStateConfig(payload) {
  return client.post('/device-params/stage-state-config', payload)
}

// ── 趋势漂移预警（预计算汇总只读）──
export async function getTrendAlerts(params) {
  return client.get('/device-params/trend-alerts', { params })
}

export async function getStatsSeries(params) {
  return client.get('/device-params/stats-series', { params })
}

export async function getStatsSummary(params) {
  return client.get('/device-params/stats-summary', { params })
}

export async function getStatsOverview(params) {
  return client.get('/device-params/stats-overview', { params })
}

// ── 分阶段漂移报警 · 知识库诊断 ──
export async function getAlertDiagnosis(params) {
  return client.get('/device-params/trend-alerts/diagnosis', { params })
}
export async function runAlertDiagnose(params) {
  // 单条按需诊断：走知识库 LLM，较慢
  return client.post('/device-params/trend-alerts/diagnose', null, { params, timeout: 300000 })
}
export async function runAllAlertDiagnosis(params) {
  return client.post('/device-params/trend-alerts/diagnose/run-all', null, { params, timeout: 600000 })
}

// ── 参数画像自适应层 + Cpk ──
export async function getParamProfile(deviceCode) {
  return client.get('/device-params/profile', { params: { device_code: deviceCode } })
}

export async function suggestParamProfile(params) {
  return client.post('/device-params/profile/suggest', null, { params })
}

export async function saveParamProfile(payload) {
  return client.post('/device-params/profile', payload)
}

export async function getCpk(params) {
  return client.get('/device-params/cpk', { params })
}

export async function recalcSpecLimits(payload) {
  return client.post('/device-params/profile/recalc-spec', payload)
}

export async function recalcCpk(payload) {
  return client.post('/device-params/profile/recalc-cpk', payload)
}

// ── Pillar 3 高级分析 ──
export async function getRul(params) {
  return client.get('/device-params/rul', { params })
}
export async function getBenchmark(params) {
  return client.get('/device-params/benchmark', { params })
}
export async function getPrecursors(params) {
  return client.get('/device-params/precursors', { params })
}

// ── AI 自主诊断 agent ──
export async function diagnoseDevice(params) {
  return client.post('/device-params/diagnose', null, { params, timeout: 300000 })
}

// ── 系统管理 · Job 管理 ──
export async function getSystemJobs() {
  return client.get('/system/jobs')
}
export async function runSystemJob(jobId) {
  return client.post('/system/jobs/run', { job_id: jobId })
}
export async function saveSystemJobConfig(payload) {
  return client.post('/system/jobs/config', payload)
}
export async function getSystemJobRuns(jobId, params) {
  return client.get(`/system/jobs/${encodeURIComponent(jobId)}/runs`, { params })
}

export async function getDriftConfig(deviceCode) {
  return client.get('/device-params/drift-config', { params: { device_code: deviceCode } })
}

export async function saveDriftConfig(payload) {
  return client.post('/device-params/drift-config', payload)
}

export async function runRollup(params) {
  return client.post('/device-params/rollup/run', null, { params })
}
