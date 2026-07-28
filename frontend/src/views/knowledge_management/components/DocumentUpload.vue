<template>
  <div>
    <!-- 拖拽上传区域 -->
    <div
      class="border-2 border-dashed rounded-xl p-6 text-center transition-colors"
      :class="isDragging ? 'border-blue-400 bg-blue-50' : 'border-gray-300 hover:border-gray-400'"
      @dragover.prevent="isDragging = true"
      @dragleave.prevent="isDragging = false"
      @drop.prevent="handleDrop"
      @click="triggerFileInput"
    >
      <input
        ref="fileInput"
        type="file"
        multiple
        class="hidden"
        @change="handleFileSelect"
      />

      <svg class="w-10 h-10 mx-auto text-gray-400 mb-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5"
          d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12" />
      </svg>

      <p class="text-sm text-gray-600 mb-1">点击或拖拽文件到此处上传</p>
      <p class="text-xs text-gray-400">支持多文件上传</p>
    </div>

    <!-- 上传引导提示 -->
    <div class="mt-3 p-3 bg-gray-50 rounded-lg text-xs text-gray-500 space-y-1">
      <p class="font-medium text-gray-600 mb-1">上传建议：</p>
      <p>📄 <strong>文档类</strong>：建议直接上传 PDF，RAGFlow 解析效果最佳</p>
      <p>📊 <strong>表格类</strong>：建议上传 Excel（.xlsx），保留表格结构</p>
      <p>⚙️ <strong>PLC 程序</strong>：上传 PLC 源文件（.awl/.stl 等），系统自动解析生成说明文档</p>
    </div>

    <!-- 上传进度 -->
    <div v-if="uploading" class="mt-4 space-y-2">
      <div v-for="(file, idx) in uploadFiles" :key="idx" class="flex items-center gap-3 p-2 bg-blue-50 rounded-lg">
        <div class="animate-spin rounded-full h-4 w-4 border-b-2 border-blue-600"></div>
        <span class="text-sm text-gray-700 truncate flex-1">{{ file.name }}</span>
        <span class="text-xs text-blue-600">上传中...</span>
      </div>
    </div>

    <!-- 后台处理进度（轮询） -->
    <div v-if="processingVersions.length > 0" class="mt-4 space-y-2">
      <div
        v-for="v in processingVersions"
        :key="v.id"
        class="flex items-center gap-3 p-2 rounded-lg"
        :class="v.allDone ? 'bg-green-50' : 'bg-yellow-50'"
      >
        <div v-if="!v.allDone" class="animate-spin rounded-full h-4 w-4 border-b-2 border-yellow-600"></div>
        <svg v-else class="w-4 h-4 text-green-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7" />
        </svg>
        <span class="text-sm text-gray-700 truncate flex-1">{{ v.name }}</span>
        <span class="text-xs" :class="v.allDone ? 'text-green-600' : 'text-yellow-600'">
          {{ v.allDone ? '处理完成' : v.statusText }}
        </span>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onUnmounted } from 'vue'
import { uploadDocuments, getVersionProgress } from '../../../api/knowledgeManagementClient.js'

const props = defineProps({
  planItemId: { type: String, required: true },
  fileTypeHint: { type: String, default: '' },
})

const emit = defineEmits(['uploaded'])

const fileInput = ref(null)
const isDragging = ref(false)
const uploading = ref(false)
const uploadFiles = ref([])
const processingVersions = ref([])
let pollTimers = []

function triggerFileInput() {
  fileInput.value?.click()
}

function handleFileSelect(e) {
  const files = Array.from(e.target.files || [])
  if (files.length > 0) doUpload(files)
  e.target.value = ''
}

function handleDrop(e) {
  isDragging.value = false
  const files = Array.from(e.dataTransfer?.files || [])
  if (files.length > 0) doUpload(files)
}

async function doUpload(files) {
  if (!props.planItemId) return

  uploading.value = true
  uploadFiles.value = files

  try {
    const formData = new FormData()
    files.forEach(f => formData.append('files', f))

    const result = await uploadDocuments(props.planItemId, formData)

    uploading.value = false
    uploadFiles.value = []

    // 开始轮询后台任务进度
    const versions = result.versions || result.documents || []
    if (versions.length > 0) {
      startPolling(versions)
    }

    emit('uploaded')
  } catch (err) {
    uploading.value = false
    uploadFiles.value = []
    alert('上传失败: ' + err.message)
  }
}

function startPolling(versions) {
  processingVersions.value = versions.map(v => ({
    id: v.id,
    name: v.original_filename || v.display_name || '文档',
    convertStatus: v.convert_status || null,
    extractStatus: v.extract_status || null,
    allDone: isDone(v.convert_status) && isDone(v.extract_status),
    statusText: buildStatusText(v.convert_status, v.extract_status),
  }))

  // 启动轮询
  processingVersions.value.forEach(v => {
    if (!v.allDone) {
      const timer = setInterval(() => pollVersion(v), 3000)
      pollTimers.push(timer)
    }
  })
}

async function pollVersion(v) {
  try {
    const progress = await getVersionProgress(v.id)
    v.convertStatus = progress.convert_status || v.convertStatus
    v.extractStatus = progress.extract_status || v.extractStatus
    v.allDone = isDone(v.convertStatus) && isDone(v.extractStatus)
    v.statusText = buildStatusText(v.convertStatus, v.extractStatus)

    if (v.allDone) {
      // 停止该版本的轮询
      clearPollTimers()
      emit('uploaded')
    }
  } catch {
    // 忽略轮询错误
  }
}

function isDone(status) {
  return status === 'done' || status === 'failed' || status === null
}

function buildStatusText(convert, extract) {
  const parts = []
  if (convert === 'processing' || convert === 'pending') parts.push('转换中')
  if (extract === 'processing' || extract === 'pending') parts.push('提取中')
  if (convert === 'failed') parts.push('转换失败')
  if (extract === 'failed') parts.push('提取失败')
  return parts.join('、') || '处理中'
}

function clearPollTimers() {
  pollTimers.forEach(t => clearInterval(t))
  pollTimers = []
}

onUnmounted(() => {
  clearPollTimers()
})
</script>
