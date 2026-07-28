<template>
  <div class="w-72 flex-shrink-0 border-l border-gray-200 bg-white flex flex-col hidden lg:flex">
    <!-- New conversation button -->
    <div class="p-3 border-b border-gray-100">
      <button
        @click="onNewSession"
        class="w-full px-4 py-2 rounded-full bg-amber-400 text-gray-900 text-sm font-medium hover:bg-amber-300 transition-colors flex items-center justify-center gap-1.5"
      >
        <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 4v16m8-8H4" />
        </svg>
        开启新对话
      </button>
    </div>

    <!-- Tab switcher -->
    <div class="flex border-b border-gray-100 relative">
      <button
        @click="activeTab = 'sessions'"
        :class="[
          'flex-1 py-2.5 text-xs font-medium text-center transition-colors',
          activeTab === 'sessions' ? 'text-amber-700' : 'text-gray-400 hover:text-gray-600'
        ]"
      >
        会话记录
      </button>
      <button
        @click="activeTab = 'questions'"
        :class="[
          'flex-1 py-2.5 text-xs font-medium text-center transition-colors',
          activeTab === 'questions' ? 'text-amber-700' : 'text-gray-400 hover:text-gray-600'
        ]"
      >
        预置问题
      </button>
      <!-- Sliding indicator -->
      <div
        class="absolute bottom-0 h-0.5 bg-amber-400 transition-all duration-300 ease-in-out"
        :style="{ left: activeTab === 'sessions' ? '0%' : '50%', width: '50%' }"
      ></div>
    </div>

    <!-- Tab content with slide animation -->
    <div class="flex-1 overflow-hidden relative">
      <Transition :name="slideDirection" mode="out-in">
        <!-- Sessions tab -->
        <div v-if="activeTab === 'sessions'" key="sessions" class="absolute inset-0 overflow-y-auto p-2 space-y-0.5">
          <div
            v-for="s in sessions"
            :key="s.id"
            @click="onSelectSession(s.id)"
            :class="[
              'group flex items-center gap-2 px-3 py-2 rounded-lg cursor-pointer transition-colors',
              s.id === activeId
                ? 'bg-amber-50 text-amber-700'
                : 'text-gray-600 hover:bg-gray-50'
            ]"
          >
            <div class="flex-1 min-w-0">
              <p class="text-xs truncate">{{ s.title || '新对话' }}</p>
              <p class="text-[10px] text-gray-400 mt-0.5">{{ formatTime(s.updatedAt || s.createdAt) }}</p>
            </div>
            <button
              @click.stop="onDeleteSession(s.id)"
              class="flex-shrink-0 p-1 rounded opacity-0 group-hover:opacity-100 text-gray-300 hover:text-red-500 hover:bg-red-50 transition-all"
              title="删除会话"
            >
              <svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
          </div>
          <div v-if="sessions.length === 0" class="text-center text-xs text-gray-400 py-8">
            暂无会话记录
          </div>
        </div>

        <!-- Preset questions tab -->
        <div v-else key="questions" class="absolute inset-0 overflow-y-auto p-3">
          <div class="flex items-center justify-between px-1 mb-3">
            <span class="text-xs text-gray-400">随机推荐问题</span>
            <button
              @click="fetchQuestions"
              :disabled="questionsLoading"
              class="p-1 rounded text-gray-400 hover:text-amber-600 hover:bg-amber-50 transition-colors"
              title="刷新"
            >
              <svg class="w-3.5 h-3.5" :class="{ 'animate-spin': questionsLoading }" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
              </svg>
            </button>
          </div>
          <div class="space-y-1.5">
            <button
              v-for="(q, i) in questions"
              :key="i"
              @click="$emit('fill', q)"
              class="block w-full text-left text-xs text-gray-600 px-3 py-2 rounded-lg border border-gray-200 hover:border-amber-300 hover:bg-amber-50 hover:text-amber-700 transition-colors"
              style="display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden;"
            >
              {{ q }}
            </button>
          </div>
          <div v-if="questions.length === 0 && !questionsLoading" class="text-center text-xs text-gray-400 py-8">
            暂无预置问题
          </div>
          <div v-if="questionsLoading" class="text-center text-xs text-gray-400 py-8">
            加载中...
          </div>
        </div>
      </Transition>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, watch } from 'vue'
import { useSqlQaSessions } from '../../../composables/sql_qa/useSqlQaSessions.js'
import { useSqlQaConfirm } from '../../../composables/sql_qa/useSqlQaConfirm.js'
import { listMemories } from '../../../api/sqlQaClient.js'

defineEmits(['select', 'fill'])
const { confirm } = useSqlQaConfirm()

const { sessions, activeId, setActiveId, createSession, deleteSession } = useSqlQaSessions()

const activeTab = ref('sessions')
const questions = ref([])
const questionsLoading = ref(false)
const prevTab = ref('sessions')

const slideDirection = computed(() => {
  return activeTab.value === 'questions' ? 'slide-left' : 'slide-right'
})

watch(activeTab, (newVal, oldVal) => {
  prevTab.value = oldVal
})

function onNewSession() {
  createSession()
}

function onSelectSession(id) {
  setActiveId(id)
}

async function onDeleteSession(id) {
  if (sessions.value.length <= 1) return
  const ok = await confirm({ message: '确认删除此会话？删除后不可恢复。', danger: true })
  if (!ok) return
  deleteSession(id)
}

function formatTime(ts) {
  if (!ts) return ''
  const d = new Date(ts)
  const now = new Date()
  const diff = now - d
  if (diff < 60000) return '刚刚'
  if (diff < 3600000) return `${Math.floor(diff / 60000)}分钟前`
  if (diff < 86400000) return `${Math.floor(diff / 3600000)}小时前`
  return `${d.getMonth() + 1}/${d.getDate()} ${d.getHours().toString().padStart(2, '0')}:${d.getMinutes().toString().padStart(2, '0')}`
}

async function fetchQuestions() {
  questionsLoading.value = true
  try {
    const data = await listMemories({ type: 'sql_pair', random: true, limit: 50 })
    const pairs = data.memories || data || []
    questions.value = pairs.map(p => p.question).filter(q => q && q.length < 80).slice(0, 15)
  } catch {
    questions.value = []
  } finally {
    questionsLoading.value = false
  }
}

onMounted(fetchQuestions)
</script>

<style scoped>
.slide-left-enter-active,
.slide-left-leave-active,
.slide-right-enter-active,
.slide-right-leave-active {
  transition: transform 0.25s ease-in-out, opacity 0.25s ease-in-out;
}

.slide-left-enter-from {
  transform: translateX(30px);
  opacity: 0;
}

.slide-left-leave-to {
  transform: translateX(-30px);
  opacity: 0;
}

.slide-right-enter-from {
  transform: translateX(-30px);
  opacity: 0;
}

.slide-right-leave-to {
  transform: translateX(30px);
  opacity: 0;
}
</style>
