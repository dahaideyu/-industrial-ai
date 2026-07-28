<template>
  <div class="h-screen flex flex-col bg-[#eef2f6] overflow-hidden sql-qa-app">
      <!-- 顶部导航栏 (fixed) -->
      <div class="flex-shrink-0 border-b border-gray-200 bg-white shadow-sm px-6 z-10">
        <div class="flex items-center justify-between h-14">
          <nav class="flex gap-1 bg-gray-100 rounded-lg p-1">
            <router-link
              v-for="tab in tabs"
              :key="tab.path"
              :to="tab.path"
              :class="[
                'px-4 py-1.5 text-sm font-medium rounded-md transition-all duration-200',
                isActiveTab(tab.path)
                  ? 'bg-amber-400 text-gray-900 shadow-sm'
                  : 'text-gray-500 hover:text-gray-700 hover:bg-gray-200'
              ]"
            >
              {{ tab.name }}
            </router-link>
          </nav>
        </div>
      </div>

      <!-- 内容区 -->
      <div class="flex-1 min-h-0 overflow-hidden">
        <router-view />
      </div>

      <!-- 全局确认弹窗 -->
      <SqlQaConfirmModal />
  </div>
</template>

<script setup>
import { useRouter } from 'vue-router'
import SqlQaConfirmModal from './components/SqlQaConfirmModal.vue'

const router = useRouter()

const tabs = [
  { name: '智能问答', path: '/sql-qa' },
  { name: '训练管理', path: '/sql-qa/admin/training' },
  { name: '实体管理', path: '/sql-qa/admin/entities' },
  { name: '查询监控', path: '/sql-qa/admin/monitor' },
]

function isActiveTab(path) {
  const route = router.currentRoute.value
  // For '/sql-qa' (chat page), only match exactly or with query params
  if (path === '/sql-qa') {
    return route.path === '/sql-qa'
  }
  // For other paths, match exactly or with sub-paths
  return route.path === path || route.path.startsWith(path + '/')
}
</script>

<style>
/* Custom scrollbar styles for the entire SQL-QA app */
.sql-qa-app ::-webkit-scrollbar {
  width: 6px;
  height: 6px;
}
.sql-qa-app ::-webkit-scrollbar-track {
  background: transparent;
}
.sql-qa-app ::-webkit-scrollbar-thumb {
  background: #d1d5db;
  border-radius: 3px;
}
.sql-qa-app ::-webkit-scrollbar-thumb:hover {
  background: #9ca3af;
}

/* Firefox scrollbar */
.sql-qa-app * {
  scrollbar-width: thin;
  scrollbar-color: #d1d5db transparent;
}

.sql-qa-app select {
  appearance: none;
  background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='12' fill='none' stroke='%2394a3b8' stroke-width='2'%3E%3Cpath d='M2 4l4 4 4-4'/%3E%3C/svg%3E");
  background-repeat: no-repeat;
  background-position: right 0.5rem center;
  padding-right: 2rem;
}
</style>
