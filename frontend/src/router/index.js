import { createRouter, createWebHistory } from 'vue-router'
import Dashboard from '../views/Dashboard.vue'

const routes = [
  { path: '/login', component: () => import('../views/Login.vue'), meta: { public: true } },
  { path: '/', redirect: '/dashboard' },
  { path: '/dashboard', component: Dashboard },
  { path: '/report', component: () => import('../views/Report.vue') },
  { path: '/analysis', component: () => import('../views/Analysis.vue') },
  { path: '/alarms', component: () => import('../views/Alarms.vue') },
  { path: '/alarm-analysis', component: () => import('../views/AlarmAnalysis.vue') },
  { path: '/maintenance-reports', component: () => import('../views/MaintenanceReports.vue') },
  { path: '/document-analysis', component: () => import('../views/DocumentAnalysis.vue') },
  { path: '/repair-suggestion', component: () => import('../views/RepairSuggestion.vue') },
  { path: '/param-setup', component: () => import('../views/ParamSetup.vue') },
  { path: '/device-params', component: () => import('../views/DeviceParams.vue') },
  { path: '/param-intelligence', component: () => import('../views/ParamIntelligence.vue') },
  // 系统管理 · 统一 Job 管理
  { path: '/system/jobs', component: () => import('../views/SystemJobs.vue') },
  // SQL-QA 智能问答平台
  { path: '/sql-qa', component: () => import('../views/sql_qa/SqlQaLayout.vue'), children: [
    { path: '', name: 'sql-qa-chat', component: () => import('../views/sql_qa/ChatPage.vue') },
    { path: 'admin/training', name: 'sql-qa-admin-training', component: () => import('../views/sql_qa/AdminTraining.vue') },
    { path: 'admin/entities', name: 'sql-qa-admin-entities', component: () => import('../views/sql_qa/AdminEntities.vue') },
    { path: 'admin/monitor', name: 'sql-qa-admin-monitor', component: () => import('../views/sql_qa/AdminMonitor.vue') },
    { path: 'pdf-viewer', name: 'sql-qa-pdf-viewer', component: () => import('../views/sql_qa/PdfPage.vue') },
  ]},
  // 知识库管理 — 路由式跳转架构（注意：更具体的路径必须在 /:id 之前）
  { path: '/knowledge-management', name: 'knowledge-dashboard', component: () => import('../views/knowledge_management/KnowledgeDashboard.vue'), meta: { title: '知识库管理' } },
  { path: '/knowledge-management/kb-type/:type', name: 'workshop-view', component: () => import('../views/knowledge_management/WorkshopView.vue'), meta: { title: '车间视图' } },
  { path: '/knowledge-management/kb-type/:type/workshop/:name', name: 'device-type-view', component: () => import('../views/knowledge_management/DeviceTypeView.vue'), meta: { title: '设备类型' } },
  { path: '/knowledge-management/compliance', name: 'compliance-view', component: () => import('../views/knowledge_management/ComplianceView.vue'), meta: { title: '合规性知识库' } },
  { path: '/knowledge-management/admin/categories', name: 'category-admin', component: () => import('../views/knowledge_management/CategoryAdminView.vue'), meta: { title: '文档类别配置' } },
  // 知识库 AI 评估报告 — 首页洞察的目标落地页
  { path: '/knowledge-overview', name: 'knowledge-overview',
    component: () => import('../views/knowledge_management/KnowledgeOverview.vue'),
    meta: { title: '知识库 AI 评估报告' } },
  // 知识库问答 — 基于 RAGFlow 的文档检索对话
  { path: '/knowledge-qa', name: 'knowledge-qa',
    component: () => import('../views/knowledge_qa/KnowledgeQaPage.vue'),
    meta: { title: '知识库问答' } },
  // 保留现有详情页路由
  { path: '/knowledge-management/plans/:id', name: 'collection-plan-detail', component: () => import('../views/knowledge_management/CollectionPlanDetail.vue'), meta: { title: '收集计划' } },
  { path: '/knowledge-management/items/:itemId/documents', name: 'document-management', component: () => import('../views/knowledge_management/DocumentManagement.vue'), meta: { title: '文档管理' } },
  { path: '/knowledge-management/:id', name: 'knowledge-base-detail', component: () => import('../views/knowledge_management/KnowledgeBaseDetail.vue'), meta: { title: '知识库详情' } },
  { path: '/:pathMatch(.*)*', component: () => import('../views/NotFound.vue') },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

// 登录守卫
router.beforeEach((to) => {
  const token = localStorage.getItem('auth_token')
  if (!to.meta.public && !token) return '/login'
  if (to.path === '/login' && token) return '/dashboard'
  return true
})

router.afterEach((to) => {
  const titles = {
    '/login': '登录 - Industrial Intelligence',
    '/dashboard': 'Dashboard - Industrial Intelligence',
    '/report': '质量报告 - Industrial Intelligence',
    '/analysis': '设备分析 - Industrial Intelligence',
    '/alarms': '报警记录 - Industrial Intelligence',
    '/alarm-analysis': '报警分析 - Industrial Intelligence',
    '/maintenance-reports': '维护报告 - Industrial Intelligence',
    '/document-analysis': '文档分析 - Industrial Intelligence',
    '/repair-suggestion': '维修建议 - Industrial Intelligence',
    '/param-setup': '参数设定 - Industrial Intelligence',
    '/device-params': '设备参数 - Industrial Intelligence',
    '/param-intelligence': '参数智能 - Industrial Intelligence',
    '/system/jobs': '任务管理 - Industrial Intelligence',
    '/sql-qa': '智能问答 - Industrial Intelligence',
    '/knowledge-management': '知识库管理 - Industrial Intelligence',
    '/knowledge-qa': '知识库问答 - Industrial Intelligence',
  }
  // 知识库管理子路由使用动态标题
  if (to.path.startsWith('/knowledge-management/plans/')) {
    document.title = '收集计划 - Industrial Intelligence'
  } else if (to.path.startsWith('/knowledge-management/kb-type/')) {
    if (to.path.includes('/workshop/')) {
      document.title = '设备类型 - Industrial Intelligence'
    } else {
      document.title = '车间视图 - Industrial Intelligence'
    }
  } else if (to.path.startsWith('/knowledge-management/compliance')) {
    document.title = '合规性知识库 - Industrial Intelligence'
  } else if (to.path.startsWith('/knowledge-management/custom')) {
    document.title = '自定义文档 - Industrial Intelligence'
  } else if (to.path.startsWith('/knowledge-management/admin/categories')) {
    document.title = '文档类别配置 - Industrial Intelligence'
  } else if (to.path.startsWith('/knowledge-management/items/')) {
    document.title = '文档管理 - Industrial Intelligence'
  } else if (to.path.startsWith('/knowledge-management/')) {
    document.title = '知识库详情 - Industrial Intelligence'
  } else {
    document.title = titles[to.path] || 'Industrial Intelligence'
  }
})

export default router
