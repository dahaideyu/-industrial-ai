<template>
  <div>
    <h3 class="text-sm font-semibold text-gray-800 mb-3">文档列表</h3>

    <div class="space-y-3">
      <div
        v-for="doc in documents"
        :key="doc.id"
        class="border border-gray-200 rounded-lg p-4"
      >
        <div class="flex items-start justify-between">
          <!-- 左侧：文档信息 -->
          <div class="min-w-0 flex-1">
            <div class="flex items-center gap-2 mb-1">
              <p class="text-sm font-medium text-gray-800 truncate">
                {{ doc.display_name || doc.versions?.[0]?.original_filename || '未命名文档' }}
              </p>
              <!-- 状态标签 -->
              <span
                class="px-2 py-0.5 text-xs rounded-full font-medium whitespace-nowrap"
                :class="statusClass(currentStatus(doc))"
              >
                {{ statusLabel(currentStatus(doc)) }}
              </span>
              <!-- 文件类型选择 -->
              <select
                v-if="currentVersion(doc)?.status === 'pending'"
                :value="currentVersion(doc)?.file_type || 'general'"
                @change="handleFileTypeChange(doc, $event.target.value)"
                class="text-xs border border-gray-300 rounded px-1.5 py-0.5 focus:ring-1 focus:ring-blue-500 outline-none"
              >
                <option value="general">文档类</option>
                <option value="table">表格类</option>
                <option value="image">图片类</option>
                <option value="manual">手册类</option>
                <option value="plc">PLC程序</option>
              </select>
            </div>

            <!-- 版本信息 -->
            <div class="flex items-center gap-3 text-xs text-gray-500">
              <span v-if="currentVersion(doc)?.version_label">
                版本: {{ currentVersion(doc).version_label }}
              </span>
              <span v-if="currentVersion(doc)?.file_size">
                {{ formatSize(currentVersion(doc).file_size) }}
              </span>
              <span v-if="currentVersion(doc)?.original_filename" class="truncate">
                {{ currentVersion(doc).original_filename }}
              </span>
            </div>

            <!-- AI 评分徽章 -->
            <div v-if="hasAIScores(doc)" class="flex items-center gap-2 mt-2">
              <span class="px-2 py-0.5 text-xs rounded bg-blue-100 text-blue-700">
                关联性: {{ currentVersion(doc).ai_relevance_score }}分
              </span>
              <span class="px-2 py-0.5 text-xs rounded bg-green-100 text-green-700">
                质量: {{ currentVersion(doc).ai_quality_score }}分
              </span>
            </div>

            <!-- 后台处理进度 -->
            <div
              v-if="isProcessing(doc)"
              class="flex items-center gap-2 mt-2"
            >
              <div class="animate-spin rounded-full h-3 w-3 border-b-2 border-yellow-500"></div>
              <span class="text-xs text-yellow-600">{{ processingText(doc) }}</span>
            </div>

            <!-- 驳回原因 -->
            <div v-if="currentStatus(doc) === 'rejected' && currentVersion(doc)?.rejected_reason" class="mt-2">
              <p class="text-xs text-red-600 bg-red-50 rounded px-2 py-1">
                驳回原因: {{ currentVersion(doc).rejected_reason }}
              </p>
            </div>
          </div>

          <!-- 右侧：操作按钮 -->
          <div class="flex items-center gap-2 ml-4 flex-shrink-0">
            <!-- pending（处理完成）：AI审核 -->
            <button
              v-if="currentStatus(doc) === 'pending' && !isProcessing(doc)"
              class="px-3 py-1.5 text-xs font-medium bg-yellow-500 text-white rounded hover:bg-yellow-600 transition-colors"
              @click="handleAIReview(doc)"
              :disabled="actionLoading"
            >
              AI 审核
            </button>

            <!-- ai_processing：显示中 -->
            <span
              v-if="currentStatus(doc) === 'ai_processing'"
              class="px-3 py-1.5 text-xs text-yellow-600"
            >
              审核中...
            </span>

            <!-- ai_completed_manual_pending：通过/驳回 -->
            <template v-if="currentStatus(doc) === 'ai_completed_manual_pending'">
              <button
                class="px-3 py-1.5 text-xs font-medium bg-green-600 text-white rounded hover:bg-green-700 transition-colors"
                @click="handleApprove(doc)"
                :disabled="actionLoading"
              >
                通过并发布
              </button>
              <button
                class="px-3 py-1.5 text-xs font-medium bg-red-600 text-white rounded hover:bg-red-700 transition-colors"
                @click="handleReject(doc)"
                :disabled="actionLoading"
              >
                驳回
              </button>
            </template>

            <!-- approved（未发布）：发布到知识库 -->
            <button
              v-if="currentStatus(doc) === 'approved' && currentVersion(doc)?.publish_status !== 'published'"
              class="px-3 py-1.5 text-xs font-medium bg-amber-600 text-white rounded hover:bg-amber-700 transition-colors"
              @click="handlePublish(doc)"
              :disabled="actionLoading"
            >
              发布到知识库
            </button>

            <!-- approved（已发布）：已发布标签 -->
            <span
              v-if="currentStatus(doc) === 'approved' && currentVersion(doc)?.publish_status === 'published'"
              class="px-3 py-1.5 text-xs font-medium text-green-700 bg-green-100 rounded"
            >
              已发布
            </span>

            <!-- rejected：重新上传 -->
            <button
              v-if="currentStatus(doc) === 'rejected'"
              class="px-3 py-1.5 text-xs font-medium bg-blue-600 text-white rounded hover:bg-blue-700 transition-colors"
              @click="triggerReupload(doc)"
            >
              重新上传
            </button>

            <!-- 通用操作 -->
            <button
              class="p-1.5 text-gray-400 hover:text-blue-600 transition-colors"
              title="预览"
              @click="$emit('preview', doc)"
            >
              <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z" />
              </svg>
            </button>

            <a
              v-if="currentVersion(doc)?.id"
              :href="downloadUrl(doc)"
              class="p-1.5 text-gray-400 hover:text-green-600 transition-colors"
              title="下载"
            >
              <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
              </svg>
            </a>

            <button
              class="p-1.5 text-gray-400 hover:text-red-600 transition-colors"
              title="删除"
              @click="handleDelete(doc)"
            >
              <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
              </svg>
            </button>
          </div>
        </div>
      </div>
    </div>

    <!-- 驳回原因弹窗 -->
    <teleport to="body">
      <div
        v-if="rejectDialogVisible"
        class="fixed inset-0 z-50 flex items-center justify-center bg-black/50"
        @click.self="rejectDialogVisible = false"
      >
        <div class="bg-white rounded-xl shadow-xl w-full max-w-md mx-4 p-6">
          <h2 class="text-lg font-bold text-gray-800 mb-4">驳回文档</h2>
          <div>
            <label class="block text-sm font-medium text-gray-700 mb-1">驳回原因 <span class="text-red-500">*</span></label>
            <textarea
              v-model="rejectReason"
              rows="4"
              class="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500 outline-none resize-none"
              placeholder="请输入驳回原因"
            ></textarea>
          </div>
          <div class="flex justify-end gap-3 mt-6">
            <button class="px-4 py-2 text-gray-600 hover:text-gray-800" @click="rejectDialogVisible = false">取消</button>
            <button
              class="px-4 py-2 bg-red-600 text-white rounded-lg hover:bg-red-700 disabled:opacity-50"
              :disabled="!rejectReason.trim()"
              @click="confirmReject"
            >
              确认驳回
            </button>
          </div>
        </div>
      </div>
    </teleport>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import {
  triggerAIReview,
  submitApproval,
  publishToRAGFlow,
  deleteDocument,
  setDocumentFileType,
  getDocumentDownloadUrl,
} from '../../../api/knowledgeManagementClient.js'

const props = defineProps({
  documents: { type: Array, default: () => [] },
  planItemId: { type: String, default: '' },
})

const emit = defineEmits(['refresh', 'preview'])

const actionLoading = ref(false)
const rejectDialogVisible = ref(false)
const rejectReason = ref('')
const rejectingDoc = ref(null)

function currentVersion(doc) {
  return doc.versions?.find(v => v.is_current) || doc.versions?.[0] || doc.current_version || null
}

function currentStatus(doc) {
  return currentVersion(doc)?.status || 'pending'
}

function hasAIScores(doc) {
  const v = currentVersion(doc)
  return v && (v.ai_relevance_score != null || v.ai_quality_score != null)
}

function isProcessing(doc) {
  const v = currentVersion(doc)
  if (!v) return false
  return v.convert_status === 'processing' || v.convert_status === 'pending' ||
         v.extract_status === 'processing' || v.extract_status === 'pending'
}

function processingText(doc) {
  const v = currentVersion(doc)
  if (!v) return ''
  const parts = []
  if (v.convert_status === 'processing' || v.convert_status === 'pending') parts.push('文件转换中')
  if (v.extract_status === 'processing' || v.extract_status === 'pending') parts.push('文本提取中')
  return parts.join('、') || '处理中'
}

function statusClass(status) {
  switch (status) {
    case 'pending': return 'bg-yellow-100 text-yellow-700'
    case 'ai_processing': return 'bg-blue-100 text-blue-700'
    case 'ai_completed_manual_pending': return 'bg-purple-100 text-purple-700'
    case 'approved': return 'bg-green-100 text-green-700'
    case 'rejected': return 'bg-red-100 text-red-700'
    default: return 'bg-gray-100 text-gray-600'
  }
}

function statusLabel(status) {
  switch (status) {
    case 'pending': return '处理中'
    case 'ai_processing': return 'AI审核中'
    case 'ai_completed_manual_pending': return '待审批'
    case 'approved': return '已通过'
    case 'rejected': return '已驳回'
    default: return status
  }
}

function downloadUrl(doc) {
  const v = currentVersion(doc)
  return v ? getDocumentDownloadUrl(v.id) : '#'
}

function formatSize(bytes) {
  if (!bytes) return ''
  if (bytes < 1024) return bytes + ' B'
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB'
  return (bytes / 1024 / 1024).toFixed(1) + ' MB'
}

async function handleAIReview(doc) {
  const v = currentVersion(doc)
  if (!v) return
  actionLoading.value = true
  try {
    await triggerAIReview(v.id)
    emit('refresh')
  } catch (err) {
    alert('AI 审核失败: ' + err.message)
  } finally {
    actionLoading.value = false
  }
}

async function handleApprove(doc) {
  const v = currentVersion(doc)
  if (!v) return
  actionLoading.value = true
  try {
    await submitApproval(v.id, 'approve')
    // 通过后自动发布
    await publishToRAGFlow(v.id)
    emit('refresh')
  } catch (err) {
    alert('操作失败: ' + err.message)
  } finally {
    actionLoading.value = false
  }
}

function handleReject(doc) {
  rejectingDoc.value = doc
  rejectReason.value = ''
  rejectDialogVisible.value = true
}

async function confirmReject() {
  const doc = rejectingDoc.value
  const v = currentVersion(doc)
  if (!v || !rejectReason.value.trim()) return
  actionLoading.value = true
  try {
    await submitApproval(v.id, 'reject', rejectReason.value)
    rejectDialogVisible.value = false
    emit('refresh')
  } catch (err) {
    alert('驳回失败: ' + err.message)
  } finally {
    actionLoading.value = false
  }
}

async function handlePublish(doc) {
  const v = currentVersion(doc)
  if (!v) return
  actionLoading.value = true
  try {
    await publishToRAGFlow(v.id)
    emit('refresh')
  } catch (err) {
    alert('发布失败: ' + err.message)
  } finally {
    actionLoading.value = false
  }
}

async function handleDelete(doc) {
  if (!confirm('确定删除此文档吗？相关 RAGFlow 数据也将被清理。')) return
  try {
    await deleteDocument(doc.id)
    emit('refresh')
  } catch (err) {
    alert('删除失败: ' + err.message)
  }
}

async function handleFileTypeChange(doc, fileType) {
  try {
    await setDocumentFileType(doc.id, fileType)
    emit('refresh')
  } catch (err) {
    alert('设置文件类型失败: ' + err.message)
  }
}

function triggerReupload(doc) {
  // 触发文件选择，重新上传到同一文档
  const input = document.createElement('input')
  input.type = 'file'
  input.multiple = true
  input.onchange = async (e) => {
    const files = Array.from(e.target.files || [])
    if (files.length === 0) return
    // 复用上传逻辑：通过 emit 让父组件处理
    emit('refresh')
  }
  input.click()
}
</script>
