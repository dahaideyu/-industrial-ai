<template>
  <div class="h-full flex bg-slate-50 text-[15px]" data-test="kbqa-page">
    <!-- 左侧：会话列表 -->
    <div class="w-[280px] flex-shrink-0">
      <SessionList
        :sessions="sessions"
        :current-session-id="currentSessionId"
        @new-session="newSession"
        @select-session="loadMessages"
        @refresh-memory="refreshMemory"
        @delete-session="handleDeleteSession"
      />
    </div>

    <!-- 中间：对话区 -->
    <div class="flex-1 flex flex-col min-w-0">
      <div ref="messagesContainer" class="flex-1 overflow-y-auto p-5">
        <div v-if="messages.length === 0" class="text-center text-slate-400 text-base py-12">
          暂无对话，点击下方输入框开始提问
        </div>
        <CitationMessage
          v-for="m in (messages || []).filter(x => x && x.id)"
          :key="m.id"
          :message="m"
          :all-kbs="availableKbs"
          @preview="openCitationPopup"
        />
        <div v-if="loading" class="text-center py-4 text-slate-400 text-base">
          🤔 AI 思考中...
        </div>
        <div v-if="error" class="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded-md text-base mt-2">
          {{ error }}
        </div>
      </div>

      <!-- 输入区 -->
      <div class="border-t border-slate-200 p-4 bg-white">
        <div class="flex gap-3 items-center">
          <input
            v-model="inputQuestion"
            @keyup.enter="handleSend"
            type="text"
            placeholder="💬 输入你的问题..."
            class="flex-1 px-4 py-3 text-[15px] border border-slate-200 rounded-lg focus:outline-none focus:border-amber-400"
            :disabled="loading"
          />
          <button
            @click="handleSend"
            :disabled="loading || !inputQuestion.trim()"
            class="px-6 py-3 text-[15px] font-semibold text-white bg-slate-900 rounded-lg hover:bg-slate-700 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            发送
          </button>
        </div>
      </div>
    </div>

    <!-- 右侧：KB 选择面板 -->
    <div class="w-[340px] flex-shrink-0">
      <KbRightPanel
        :all-kbs="availableKbs"
        :matched-kb-ids="usedKbIdsByLastMessage"
        :manual-kb-ids="manualKbIds"
        @open-selector="showSelector = true"
        @remove-manual="toggleManualKb"
      />
    </div>

    <!-- 选择 KB 弹窗 -->
    <KbSelectorModal
      :visible="showSelector"
      :kbs="availableKbs"
      :selected="manualKbIds"
      @close="showSelector = false"
      @update="onManualKbUpdate"
    />

    <!-- 引用预览弹窗（复用 SQL QA 的组件） -->
    <SqlQaCitationPopup
      v-if="citationData"
      :visible="true"
      :dataset-id="citationData.dataset_id"
      :document-id="citationData.document_id"
      :doc-name="citationData.name"
      :highlight-page="citationData.page"
      :highlight-positions="citationData.positions || []"
      :chunks="citationData.chunks || []"
      :keywords="lastUserQuestion"
      :pdf-url="citationPdfUrl"
      @close="citationData = null"
    />
  </div>
</template>

<script setup>
import { ref, computed, onMounted, nextTick, watch } from 'vue'
import { useToast } from '@/composables/useToast'
import SessionList from './components/SessionList.vue'
import KbRightPanel from './components/KbRightPanel.vue'
import KbSelectorModal from './components/KbSelectorModal.vue'
import CitationMessage from './components/CitationMessage.vue'
import SqlQaCitationPopup from '../sql_qa/components/SqlQaCitationPopup.vue'
import { useKbQa } from '../../composables/knowledge_qa/useKbQa'

const toast = useToast()
const {
  sessions,
  currentSessionId,
  messages,
  availableKbs,
  manualKbIds,
  usedKbIdsByLastMessage,
  loading,
  error,
  loadSessions,
  loadMessages,
  newSession,
  loadKbs,
  sendQuestionStream,
  toggleManualKb,
  refreshMemory,
} = useKbQa()

const inputQuestion = ref('')
const showSelector = ref(false)
const citationData = ref(null)
const messagesContainer = ref(null)

// KB QA 的预览接口会将 Office 文档临时转换为 PDF，供复用的 PDF 查看器加载。
const citationPdfUrl = computed(() => {
  if (!citationData.value) return ''
  const params = new URLSearchParams({
    dataset_id: citationData.value.dataset_id,
    document_id: citationData.value.document_id,
    filename: citationData.value.name || '',
  })
  return `/api/kb-qa/ragflow/document-preview-pdf?${params.toString()}`
})

// 最近一次用户提问，用作引用预览弹窗的关键词高亮
const lastUserQuestion = computed(() => {
  const lastUser = [...(messages.value || [])].reverse().find(m => m.role === 'user')
  return lastUser?.content || ''
})

async function handleSend() {
  const q = inputQuestion.value.trim()
  if (!q) return
  await sendQuestionStream(q)
  inputQuestion.value = ''
  if (error.value) {
    toast.error(error.value)
  }
}

// 流式输出时自动滚动到底部
watch(
  () => messages.value,
  () => {
    nextTick(() => {
      if (messagesContainer.value) {
        messagesContainer.value.scrollTop = messagesContainer.value.scrollHeight
      }
    })
  },
  { deep: true }
)

function onManualKbUpdate(ids) {
  manualKbIds.value = ids
}

function openCitationPopup(card) {
  citationData.value = card
}

async function handleDeleteSession(sessionId) {
  // 如果删除的是当前会话，清空消息列表
  if (sessionId === currentSessionId.value) {
    currentSessionId.value = null
    messages.value = []
  }
  // 刷新会话列表
  await loadSessions()
  toast.success('会话已删除')
}

onMounted(async () => {
  try {
    await loadKbs()
    await loadSessions()
  } catch (e) {
    toast.error('加载失败: ' + (e.message || '未知错误'))
  }
})
</script>
