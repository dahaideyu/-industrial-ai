<template>
  <teleport to="body">
    <div class="fixed inset-0 z-50 flex items-center justify-center bg-black/60" @click.self="$emit('close')">
      <div class="bg-white rounded-xl shadow-2xl w-full max-w-7xl mx-4 h-[90vh] flex flex-col">
        <!-- 头部 -->
        <div class="flex items-center justify-between px-6 py-3 border-b border-gray-200">
          <div class="flex items-center gap-4">
            <h2 class="text-base font-bold text-gray-800 truncate">
              文档：{{ doc?.name || '未知文档' }}
            </h2>
            <span class="text-xs text-gray-500">切片数量：{{ chunkTotal }}</span>
            <span v-if="docInfo.chunk_method" class="text-xs text-gray-500">
              分块方式：{{ docInfo.chunk_method }}
            </span>
          </div>
          <button class="p-1 text-gray-400 hover:text-gray-600 transition-colors" @click="$emit('close')">
            <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        <!-- 内容区：左侧 PDF + 右侧切片列表 -->
        <div class="flex-1 flex overflow-hidden">
          <!-- 左侧 PDF 渲染区 -->
          <div class="flex-1 bg-gray-100 overflow-auto p-4">
            <div v-if="pdfLoading" class="flex items-center justify-center h-full">
              <div class="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600"></div>
            </div>
            <div v-else-if="pdfError" class="flex flex-col items-center justify-center h-full text-gray-500">
              <p class="text-sm">{{ pdfError }}</p>
            </div>
            <div v-else ref="pdfContainer" class="flex flex-col items-center gap-4">
              <canvas
                v-for="page in totalPages"
                :key="page"
                :ref="el => { if (el) canvasRefs[page] = el }"
                class="shadow-lg max-w-full"
              ></canvas>
            </div>
          </div>

          <!-- 右侧切片列表 -->
          <div class="w-[480px] border-l border-gray-200 flex flex-col bg-white">
            <!-- 搜索栏 -->
            <div class="p-3 border-b border-gray-200">
              <div class="relative">
                <svg class="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
                </svg>
                <input
                  v-model="searchKeyword"
                  type="text"
                  class="w-full pl-9 pr-3 py-2 text-sm border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500 outline-none"
                  placeholder="搜索切片内容..."
                  @keyup.enter="doSearch"
                />
              </div>
            </div>

            <!-- 切片列表 -->
            <div class="flex-1 overflow-y-auto p-3 space-y-3">
              <div v-if="chunksLoading" class="flex items-center justify-center py-8">
                <div class="animate-spin rounded-full h-5 w-5 border-b-2 border-blue-600"></div>
              </div>

              <div v-else-if="chunks.length === 0" class="text-center py-8 text-gray-400 text-sm">
                暂无切片数据
              </div>

              <div
                v-for="(chunk, idx) in chunks"
                :key="chunk.id || idx"
                class="border border-gray-200 rounded-lg p-3"
                :class="chunk.available === false ? 'opacity-50' : ''"
              >
                <div class="flex items-center justify-between mb-2">
                  <div class="flex items-center gap-2">
                    <span class="text-xs font-medium text-gray-600">
                      切片 #{{ (currentPage - 1) * pageSize + idx + 1 }}
                    </span>
                    <span v-if="chunk.token_count" class="text-xs text-gray-400">
                      token: {{ chunk.token_count }}
                    </span>
                  </div>
                  <button
                    class="px-2 py-0.5 text-xs rounded transition-colors"
                    :class="chunk.available !== false
                      ? 'bg-green-100 text-green-700 hover:bg-green-200'
                      : 'bg-gray-100 text-gray-500 hover:bg-gray-200'"
                    @click="toggleChunk(chunk)"
                  >
                    {{ chunk.available !== false ? '启用' : '禁用' }}
                  </button>
                </div>
                <div class="text-sm text-gray-700 max-h-48 overflow-y-auto chunk-content" v-html="chunk.content"></div>
                <div v-if="chunk.important_keywords?.length" class="mt-2 flex flex-wrap gap-1">
                  <span
                    v-for="kw in chunk.important_keywords"
                    :key="kw"
                    class="px-1.5 py-0.5 text-xs bg-blue-50 text-blue-600 rounded"
                  >
                    {{ kw }}
                  </span>
                </div>
              </div>
            </div>

            <!-- 分页 -->
            <div class="p-3 border-t border-gray-200 flex items-center justify-between">
              <span class="text-xs text-gray-500">共 {{ chunkTotal }} 条</span>
              <div class="flex items-center gap-2">
                <button
                  class="px-2 py-1 text-xs text-gray-600 border border-gray-300 rounded hover:bg-gray-50 disabled:opacity-40"
                  :disabled="currentPage <= 1"
                  @click="goPage(currentPage - 1)"
                >
                  上一页
                </button>
                <span class="text-xs text-gray-600">{{ currentPage }} / {{ totalChunkPages }}</span>
                <button
                  class="px-2 py-1 text-xs text-gray-600 border border-gray-300 rounded hover:bg-gray-50 disabled:opacity-40"
                  :disabled="currentPage >= totalChunkPages"
                  @click="goPage(currentPage + 1)"
                >
                  下一页
                </button>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </teleport>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted, nextTick } from 'vue'
import { getRAGDocChunks } from '../../../api/knowledgeManagementClient.js'
import pdfjsWorker from 'pdfjs-dist/build/pdf.worker.min.mjs?url'

const props = defineProps({
  doc: { type: Object, default: null },
  datasetId: { type: String, default: '' },
  pdfPreviewUrl: { type: String, default: '' },
})

defineEmits(['close'])

// PDF 相关
const pdfContainer = ref(null)
const canvasRefs = ref({})
const pdfLoading = ref(true)
const pdfError = ref('')
const totalPages = ref(0)
let pdfDoc = null

// 切片相关
const chunks = ref([])
const chunkTotal = ref(0)
const chunksLoading = ref(false)
const searchKeyword = ref('')
const currentPage = ref(1)
const pageSize = 20
const docInfo = ref({})

const totalChunkPages = computed(() => Math.max(1, Math.ceil(chunkTotal.value / pageSize)))

onMounted(async () => {
  await fetchChunks()
  if (props.pdfPreviewUrl) {
    await loadPdf(props.pdfPreviewUrl)
  } else {
    pdfLoading.value = false
    pdfError.value = '暂无 PDF 预览'
  }
})

onUnmounted(() => {
  if (pdfDoc) {
    pdfDoc.destroy()
    pdfDoc = null
  }
})

async function fetchChunks() {
  if (!props.doc?.id) return
  chunksLoading.value = true
  try {
    const params = {
      page: currentPage.value,
      page_size: pageSize,
    }
    if (searchKeyword.value.trim()) {
      params.keywords = searchKeyword.value.trim()
    }
    const resp = await getRAGDocChunks(props.doc.id, params)
    // 后端返回 {code: 200, msg: "ok", data: {chunks: [...], doc: {...}, total: N}}
    const d = resp?.data || resp
    chunks.value = d.chunks || d.items || []
    chunkTotal.value = d.total || d.doc?.chunk_count || chunks.value.length
    docInfo.value = d.doc || {}
  } catch (err) {
    console.error('获取切片失败:', err.message)
    chunks.value = []
  } finally {
    chunksLoading.value = false
  }
}

function doSearch() {
  currentPage.value = 1
  fetchChunks()
}

function goPage(page) {
  if (page < 1 || page > totalChunkPages.value) return
  currentPage.value = page
  fetchChunks()
}

function toggleChunk(chunk) {
  // 切换启用/禁用状态（乐观更新）
  chunk.available = chunk.available === false ? true : false
  // TODO: 调用 RAGFlow 更新切片状态的 API
}

async function loadPdf(url) {
  pdfLoading.value = true
  pdfError.value = ''
  try {
    const pdfjsLib = await import('pdfjs-dist')
    pdfjsLib.GlobalWorkerOptions.workerSrc = pdfjsWorker
    const loadingTask = pdfjsLib.getDocument(url)
    pdfDoc = await loadingTask.promise
    totalPages.value = pdfDoc.numPages
    await nextTick()
    for (let i = 1; i <= pdfDoc.numPages; i++) {
      renderPage(i)
    }
  } catch (err) {
    pdfError.value = 'PDF 加载失败'
  } finally {
    pdfLoading.value = false
  }
}

async function renderPage(pageNum) {
  if (!pdfDoc) return
  try {
    const page = await pdfDoc.getPage(pageNum)
    const viewport = page.getViewport({ scale: 1.5 })
    const canvas = canvasRefs.value[pageNum]
    if (!canvas) return
    canvas.height = viewport.height
    canvas.width = viewport.width
    const ctx = canvas.getContext('2d')
    await page.render({ canvasContext: ctx, viewport }).promise
  } catch {}
}
</script>

<style scoped>
.chunk-content :deep(table) {
  border-collapse: collapse;
  width: 100%;
  font-size: 12px;
}
.chunk-content :deep(td),
.chunk-content :deep(th) {
  border: 1px solid #e2e8f0;
  padding: 4px 6px;
  text-align: left;
  vertical-align: top;
}
.chunk-content :deep(th) {
  background: #f8fafc;
  font-weight: 600;
}
.chunk-content :deep(caption) {
  font-weight: 600;
  margin-bottom: 4px;
}
.chunk-content :deep(tr:nth-child(even)) {
  background: #fafafa;
}
</style>
