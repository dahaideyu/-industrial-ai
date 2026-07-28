<template>
  <teleport to="body">
    <div class="fixed inset-0 z-50 flex items-center justify-center bg-black/60" @click.self="$emit('close')">
      <div class="bg-white rounded-xl shadow-2xl w-full max-w-6xl mx-4 h-[85vh] flex flex-col">
        <!-- 头部 -->
        <div class="flex items-center justify-between px-6 py-3 border-b border-gray-200">
          <h2 class="text-base font-bold text-gray-800 truncate">{{ docName || '文档预览' }}</h2>
          <button class="p-1 text-gray-400 hover:text-gray-600 transition-colors" @click="$emit('close')">
            <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/></svg>
          </button>
        </div>

        <div class="flex-1 flex overflow-hidden">
          <div class="flex-1 bg-gray-100 overflow-auto">
            <!-- 图片：直接显示 -->
            <div v-if="isImage" class="flex items-center justify-center h-full p-4">
              <img :src="previewUrl" :alt="docName" class="max-w-full max-h-full object-contain rounded-lg shadow-lg" />
            </div>

            <!-- HTML（Excel 转换/Markdown 后端已转 HTML）：iframe 加载 -->
            <iframe v-else-if="isHtml || useHtmlFallback" :src="previewUrl" class="w-full h-full border-0" sandbox="allow-scripts allow-same-origin"></iframe>

            <!-- Markdown（后端未转换时回退）：前端 marked 渲染 -->
            <div v-else-if="isMarkdown && mdContent" class="max-w-[900px] mx-auto my-8 px-6">
              <div class="prose prose-sm max-w-none bg-white rounded-lg shadow p-8" v-html="renderedMd"></div>
            </div>

            <!-- PDF：pdfjs-dist -->
            <template v-else>
              <div v-if="mdLoading" class="flex items-center justify-center h-full"><div class="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600"></div></div>
              <div v-else-if="pdfLoading" class="flex items-center justify-center h-full"><div class="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600"></div></div>
              <div v-else-if="pdfError" class="flex flex-col items-center justify-center h-full text-gray-500 p-4"><p class="text-sm">{{ pdfError }}</p></div>
              <div v-else ref="pdfContainer" class="flex flex-col items-center gap-4 p-4">
                <canvas v-for="p in totalPages" :key="p" :ref="el => { if(el) canvasRefs[p]=el }" class="shadow-lg max-w-full"></canvas>
              </div>
            </template>
          </div>

          <div class="w-80 border-l border-gray-200 overflow-y-auto p-4 bg-white">
            <h3 class="text-sm font-semibold text-gray-800 mb-4">AI 评价报告</h3>
            <div v-if="!hasScores" class="text-center py-8 text-gray-400"><p class="text-sm">暂无 AI 评价</p></div>
            <div v-else class="space-y-4">
              <div>
                <div class="flex items-center justify-between mb-1"><span class="text-xs font-medium text-gray-600">关联性评分</span><span class="text-sm font-bold" :class="scoreColor(relevanceScore)">{{ relevanceScore }}分</span></div>
                <div class="h-2 bg-gray-100 rounded-full overflow-hidden"><div class="h-full rounded-full transition-all" :class="scoreBarColor(relevanceScore)" :style="{width:(relevanceScore||0)+'%'}"></div></div>
                <p v-if="relevanceRemark" class="text-xs text-gray-500 mt-1">{{ relevanceRemark }}</p>
              </div>
              <div>
                <div class="flex items-center justify-between mb-1"><span class="text-xs font-medium text-gray-600">质量评分</span><span class="text-sm font-bold" :class="scoreColor(qualityScore)">{{ qualityScore }}分</span></div>
                <div class="h-2 bg-gray-100 rounded-full overflow-hidden"><div class="h-full rounded-full transition-all" :class="scoreBarColor(qualityScore)" :style="{width:(qualityScore||0)+'%'}"></div></div>
                <p v-if="qualityRemark" class="text-xs text-gray-500 mt-1">{{ qualityRemark }}</p>
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
import pdfjsWorker from 'pdfjs-dist/build/pdf.worker.min.mjs?url'
import { marked } from 'marked'

const props = defineProps({
  previewUrl: { type: String, default: '' },
  docName: { type: String, default: '' },
  relevanceScore: { type: Number, default: null },
  qualityScore: { type: Number, default: null },
  relevanceRemark: { type: String, default: '' },
  qualityRemark: { type: String, default: '' },
})

defineEmits(['close'])

const pdfContainer = ref(null), canvasRefs = ref({}), pdfLoading = ref(true), pdfError = ref(''), totalPages = ref(0)
const mdContent = ref(''), mdLoading = ref(false), useHtmlFallback = ref(false)
let pdfDoc = null

const hasScores = computed(() => props.relevanceScore != null || props.qualityScore != null)
const isExcel = computed(() => /\.(xlsx|xls|xlsm)$/i.test(props.docName || ''))
const isImage = computed(() => /\.(png|jpe?g|bmp|gif|webp|tiff?)$/i.test(props.docName || ''))
// HTML 预览：仅 Excel 转换后的 HTML 通过 iframe 展示
const isHtml = computed(() => isExcel.value)
// Markdown 文件：前端 marked 渲染（同时兼容后端已转 HTML / 未转换两种情况）
const isMarkdown = computed(() => /\.(md|markdown)$/i.test(props.docName || ''))
const renderedMd = computed(() => {
  if (!mdContent.value) return ''
  return marked(mdContent.value)
})

onMounted(async () => {
  // Markdown 文件：fetch 内容，自动适配 HTML（后端已转换）或纯文本（marked 渲染）
  if (isMarkdown.value) {
    mdLoading.value = true
    try {
      const resp = await fetch(props.previewUrl)
      if (resp.ok) {
        const contentType = resp.headers.get('content-type') || ''
        if (contentType.includes('text/html')) {
          // 后端已转换为 HTML —— 直接注入 iframe 供用户预览
          mdContent.value = ''  // 不触发 marked 渲染
          useHtmlFallback.value = true  // 模板走 iframe 分支
        } else {
          // 原始 markdown 文本，用 marked 渲染
          mdContent.value = await resp.text()
        }
      } else {
        mdContent.value = '无法加载 Markdown 内容'
      }
    } catch (e) {
      mdContent.value = '加载失败: ' + (e.message || '')
    } finally {
      mdLoading.value = false
    }
    pdfLoading.value = false
    return
  }

  // Excel / 图片：无需额外处理
  if (isExcel.value || isImage.value) { pdfLoading.value = false; return }
  // PDF：pdfjs-dist 渲染
  if (props.previewUrl) await loadPdf()
  else { pdfLoading.value = false; pdfError.value = '未提供预览地址' }
})

onUnmounted(() => { if (pdfDoc) { pdfDoc.destroy(); pdfDoc = null } })

async function loadPdf(url) {
  pdfLoading.value = true; pdfError.value = ''
  try {
    const pdfjsLib = await import('pdfjs-dist')
    pdfjsLib.GlobalWorkerOptions.workerSrc = pdfjsWorker
    const task = pdfjsLib.getDocument(props.previewUrl); pdfDoc = await task.promise; totalPages.value = pdfDoc.numPages
    await nextTick()
    for (let i = 1; i <= pdfDoc.numPages; i++) renderPage(i)
  } catch (e) { pdfError.value = '加载失败: ' + (e.message || '') }
  finally { pdfLoading.value = false }
}

async function renderPage(n) {
  if (!pdfDoc) return
  try {
    const page = await pdfDoc.getPage(n); const vp = page.getViewport({ scale: 1.5 }); const c = canvasRefs.value[n]
    if (!c) return; c.height = vp.height; c.width = vp.width; await page.render({ canvasContext: c.getContext('2d'), viewport: vp }).promise
  } catch {}
}

function scoreColor(s) { return s == null ? 'text-gray-400' : s >= 80 ? 'text-green-600' : s >= 60 ? 'text-yellow-600' : 'text-red-600' }
function scoreBarColor(s) { return s == null ? 'bg-gray-300' : s >= 80 ? 'bg-green-500' : s >= 60 ? 'bg-yellow-500' : 'bg-red-500' }
</script>

<style scoped>
</style>
