<template>
  <div class="flex flex-col h-full bg-slate-50 border-r border-slate-200" data-test="kbqa-session-list">
    <div class="p-4 border-b border-slate-200">
      <button
        @click="$emit('new-session')"
        class="w-full px-4 py-2.5 text-[15px] font-semibold text-slate-700 bg-white border border-slate-200 rounded-lg hover:bg-slate-100 transition-colors"
      >
        + 新建会话
      </button>
    </div>

    <div class="flex-1 overflow-y-auto p-3">
      <div class="text-[13px] font-semibold text-slate-500 px-2 py-1.5 mb-2 uppercase tracking-wide">最近会话</div>
      <div
        v-for="s in (sessions || []).filter(x => x && x.id)"
        :key="s.id"
        @click="$emit('select-session', s.id)"
        :class="[
          'group p-3 mb-2 rounded-lg cursor-pointer text-[14px] relative',
          s.id === currentSessionId
            ? 'bg-amber-50 border-2 border-amber-400'
            : 'bg-white border border-slate-200 hover:border-amber-300'
        ]"
      >
        <div class="font-semibold text-slate-900 truncate pr-6">{{ s.title }}</div>
        <div class="text-[12px] text-slate-400 mt-1">
          {{ formatTime(s.updated_at) }}
        </div>
        <!-- 删除按钮 -->
        <button
          @click.stop="handleDelete(s)"
          class="absolute top-2 right-2 w-6 h-6 flex items-center justify-center rounded-full text-slate-400 opacity-0 group-hover:opacity-100 hover:bg-red-100 hover:text-red-500 transition-all duration-150"
          title="删除会话"
        >
          ✕
        </button>
      </div>
    </div>

    <div
      class="p-3 border-t border-slate-200 text-center text-[13px] text-slate-600 cursor-pointer hover:bg-slate-100 font-medium"
      @click="$emit('refresh-memory')"
    >
      🔄 刷新问答记忆
    </div>

    <!-- 删除确认弹窗 -->
    <Teleport to="body">
      <div
        v-if="showDeleteConfirm"
        class="fixed inset-0 z-50 flex items-center justify-center bg-black/40"
        @click.self="showDeleteConfirm = false"
      >
        <div class="bg-white rounded-xl shadow-xl p-6 w-[360mx] animate-in fade-in zoom-in duration-150">
          <div class="text-[16px] font-semibold text-slate-900 mb-2">确认删除</div>
          <div class="text-[14px] text-slate-600 mb-6">
            确定要删除会话「{{ deletingSession?.title }}」吗？<br>
            <span class="text-red-500">该操作会同时删除所有聊天记录，且无法恢复。</span>
          </div>
          <div class="flex justify-end gap-3">
            <button
              @click="showDeleteConfirm = false"
              class="px-4 py-2 text-[14px] text-slate-700 bg-slate-100 rounded-lg hover:bg-slate-200 transition-colors"
            >
              取消
            </button>
            <button
              @click="confirmDelete"
              class="px-4 py-2 text-[14px] text-white bg-red-500 rounded-lg hover:bg-red-600 transition-colors"
            >
              删除
            </button>
          </div>
        </div>
      </div>
    </Teleport>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { kbQaClient } from '@/api/kbQaClient'

const props = defineProps({
  sessions: Array,
  currentSessionId: String,
})
const emit = defineEmits(['new-session', 'select-session', 'refresh-memory', 'delete-session'])

const showDeleteConfirm = ref(false)
const deletingSession = ref(null)

function formatTime(iso) {
  if (!iso) return ''
  const d = new Date(iso)
  const today = new Date()
  if (d.toDateString() === today.toDateString()) {
    return `今天 ${d.getHours().toString().padStart(2, '0')}:${d.getMinutes().toString().padStart(2, '0')}`
  }
  return `${d.getMonth() + 1}/${d.getDate()} ${d.getHours().toString().padStart(2, '0')}:${d.getMinutes().toString().padStart(2, '0')}`
}

function handleDelete(session) {
  deletingSession.value = session
  showDeleteConfirm.value = true
}

async function confirmDelete() {
  if (!deletingSession.value) return
  try {
    await kbQaClient.deleteSession(deletingSession.value.id)
    emit('delete-session', deletingSession.value.id)
  } catch (err) {
    console.error('删除会话失败:', err)
  } finally {
    showDeleteConfirm.value = false
    deletingSession.value = null
  }
}
</script>
