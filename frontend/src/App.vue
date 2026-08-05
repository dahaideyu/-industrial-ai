<template>
  <router-view v-if="isPublicPage" />

  <div v-else class="h-screen bg-[#eef2f6] text-slate-950 font-body overflow-hidden flex flex-col">
    <header class="bg-amber-400 text-slate-950 sticky top-0 z-50 shadow-md">
      <div class="flex items-center justify-between px-4 py-2">
        <div class="flex items-center gap-4">
          <router-link to="/dashboard" class="flex items-center gap-2 shrink-0">
            <div class="flex h-8 w-8 items-center justify-center rounded-md bg-white text-xs font-black">
              AI
            </div>
            <span class="hidden sm:inline text-sm font-bold">数智资产管理系统</span>
          </router-link>

          <nav class="flex items-center gap-1 ml-4">
            <div
              v-for="group in navGroups"
              :key="group.name"
              class="relative group"
            >
              <button
                type="button"
                class="flex items-center gap-1 px-3 py-2 text-sm font-medium rounded-md hover:bg-white/20 transition-colors"
              >
                {{ group.name }}
                <span class="text-xs opacity-70">▼</span>
              </button>

              <div
                class="absolute top-full left-0 mt-1 w-48 bg-white rounded-md shadow-lg invisible group-hover:visible opacity-0 group-hover:opacity-100 transition-all duration-200 border border-slate-200 z-50"
              >
                <div class="py-1">
                  <template v-for="item in group.items" :key="item.path">
                    <router-link
                      v-if="!isFeatureDisabled(item)"
                      :to="item.path"
                      :class="[
                        'block px-4 py-2 text-sm font-medium transition-colors',
                        ($route.path === item.path || $route.path.startsWith(item.path + '/'))
                          ? 'bg-amber-100 text-amber-900'
                          : 'text-slate-700 hover:bg-slate-100'
                      ]"
                    >
                      {{ item.name }}
                    </router-link>
                    <div v-else
                      class="block px-4 py-2 text-sm font-medium text-slate-300 cursor-not-allowed"
                      title="该功能当前环境未启用（需管理员在部署配置里开启）">
                      {{ item.name }} <span class="text-[10px]">未启用</span>
                    </div>
                  </template>
                </div>
              </div>
            </div>
          </nav>
        </div>

        <div class="flex items-center gap-3">
          <router-link
            to="/report"
            class="hidden sm:flex items-center gap-2 rounded-md bg-white px-4 py-1.5 text-sm font-bold text-slate-950 transition-colors hover:bg-slate-100"
          >
            <span>生成 AI 报告</span>
            <span class="text-xs">+</span>
          </router-link>

          <div class="flex items-center gap-2 px-3 py-1.5 rounded-md bg-white/20">
            <span class="h-2 w-2 rounded-full bg-emerald-500 shadow-[0_0_8px_rgba(16,185,129,0.8)]"></span>
            <span class="text-xs font-semibold">AI 在线</span>
          </div>

          <div class="flex items-center gap-2 pl-3 border-l border-slate-950/20">
            <div class="grid h-7 w-7 place-items-center rounded-full bg-slate-950 text-xs font-bold text-white">
              {{ userInitial }}
            </div>
            <div class="hidden sm:block">
              <p class="text-xs font-medium">{{ displayName }}</p>
              <p class="text-[10px] text-slate-700">{{ currentUser.role || '已登录' }}</p>
            </div>
            <button
              type="button"
              title="退出登录"
              class="ml-1 px-2 py-1 rounded-md text-xs font-medium text-slate-700 hover:bg-white/20 transition-colors"
              @click="onLogout"
            >
              退出
            </button>
          </div>
        </div>
      </div>
    </header>

    <main class="flex-1 overflow-y-auto">
      <router-view />
    </main>

    <Toast />
    <ConfirmModal ref="confirmRef" />
  </div>
</template>

<script setup>
import { computed, ref, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import client, { logout as logoutApi } from './api/client'
import Toast from './components/ui/Toast.vue'
import ConfirmModal from './components/ui/ConfirmModal.vue'
import { setConfirmModalInstance } from './composables/useConfirm'

const route = useRoute()
const router = useRouter()
const confirmRef = ref(null)

// 后端可选模块的开关状态：null=还没查到(此时不灰化，避免请求慢时闪一下"未启用")，
// 查到之后 true/false 才决定要不要灰化对应导航项，避免用户点进一个后端根本没注册路由的死链接
const featureFlags = ref({ sql_qa: null, knowledge_base: null, knowledge_qa: null })
function isFeatureDisabled(item) {
  if (!item.flag) return false
  return featureFlags.value[item.flag] === false
}
async function loadFeatureFlags() {
  try {
    const res = await client.get('/features')
    if (res.code === 200 && res.data) featureFlags.value = res.data
  } catch {
    // 查询本身失败时保持 null(不灰化)，避免因为这一个小接口抖动就把整块导航锁死
  }
}

onMounted(() => {
  setConfirmModalInstance(confirmRef.value)
  loadFeatureFlags()
})

const isPublicPage = computed(() => route.meta.public === true)

const currentUser = computed(() => {
  try {
    return JSON.parse(localStorage.getItem('auth_user') || '{}')
  } catch {
    return {}
  }
})
const displayName = computed(() => currentUser.value.display_name || currentUser.value.username || '用户')
const userInitial = computed(() => (displayName.value || 'U').charAt(0).toUpperCase())

async function onLogout() {
  try {
    await logoutApi()
  } catch {
  }
  localStorage.removeItem('auth_token')
  localStorage.removeItem('auth_user')
  router.replace('/login')
}

const navGroups = [
  {
    name: 'AI 工作流',
    items: [
      { path: '/dashboard', name: 'AI 工作台' },
      { path: '/alarm-analysis', name: '风险洞察' },
      { path: '/report', name: '智能报告' },
    ],
  },
  {
    name: '诊断与建议',
    items: [
      { path: '/analysis', name: '设备诊断' },
      { path: '/param-setup', name: '参数设定' },
      { path: '/device-params', name: '参数分析' },
      { path: '/param-intelligence', name: '参数智能' },
      { path: '/repair-suggestion', name: '维修建议' },
    ],
  },
  {
    name: '数据与任务',
    items: [
      { path: '/alarms', name: '报警证据' },
      { path: '/maintenance-reports', name: '维护报告' },
      { path: '/document-analysis', name: '文档分析' },
    ],
  },
  {
    name: 'AI 智能问答',
    items: [
      { path: '/sql-qa', name: '问答平台', flag: 'sql_qa' },
      { path: '/knowledge-management', name: '知识库管理', flag: 'knowledge_base' },
      { path: '/knowledge-qa', name: '知识库问答', flag: 'knowledge_qa' },
    ],
  },
  {
    name: '系统管理',
    items: [
      { path: '/system/jobs', name: '任务管理' },
      { path: '/system/device-visibility', name: '设备列表' },
    ],
  },
]
</script>

<style>
main::-webkit-scrollbar {
  width: 5px;
}
main::-webkit-scrollbar-track {
  background: transparent;
}
main::-webkit-scrollbar-thumb {
  background: rgb(0 0 0 / 0.10);
  border-radius: 3px;
}
main::-webkit-scrollbar-thumb:hover {
  background: rgb(0 0 0 / 0.18);
}
</style>
