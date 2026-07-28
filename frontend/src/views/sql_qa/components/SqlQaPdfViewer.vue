<template>
  <section class="pdf-viewer" aria-label="原文预览">
    <header class="pdf-viewer__toolbar">
      <div class="pdf-viewer__page-controls">
        <button
          type="button"
          class="pdf-viewer__button"
          :disabled="page <= 1 || loading"
          @click="page--"
        >
          上一页
        </button>
        <span class="pdf-viewer__page-status">
          <strong>{{ totalPages ? page : '—' }}</strong>
          <span>/</span>
          <span>{{ totalPages || '—' }}</span>
        </span>
        <button
          type="button"
          class="pdf-viewer__button"
          :disabled="page >= totalPages || loading"
          @click="page++"
        >
          下一页
        </button>
      </div>

      <div class="pdf-viewer__view-controls">
        <button
          type="button"
          :class="['pdf-viewer__button', { 'pdf-viewer__button--active': viewMode === 'page' }]"
          @click="setViewMode('page')"
        >
          适合整页
        </button>
        <button
          type="button"
          :class="['pdf-viewer__button', { 'pdf-viewer__button--active': viewMode === 'width' }]"
          @click="setViewMode('width')"
        >
          适合页宽
        </button>
        <div class="pdf-viewer__zoom-controls" aria-label="缩放">
          <button
            type="button"
            class="pdf-viewer__icon-button"
            aria-label="缩小"
            :disabled="zoom <= MIN_ZOOM"
            @click="changeZoom(-ZOOM_STEP)"
          >
            −
          </button>
          <span class="pdf-viewer__zoom-value">{{ Math.round(zoom * 100) }}%</span>
          <button
            type="button"
            class="pdf-viewer__icon-button"
            aria-label="放大"
            :disabled="zoom >= MAX_ZOOM"
            @click="changeZoom(ZOOM_STEP)"
          >
            +
          </button>
        </div>
        <button
          v-if="highlightPage"
          type="button"
          class="pdf-viewer__highlight-button"
          @click="jumpToHighlight"
        >
          定位引用页
        </button>
      </div>
    </header>

    <div ref="containerRef" class="pdf-viewer__stage">
      <div v-if="loading" class="pdf-viewer__state" aria-live="polite">
        <span class="pdf-viewer__spinner"></span>
        <span>正在准备原文预览…</span>
      </div>

      <div v-else-if="loadError" class="pdf-viewer__state pdf-viewer__state--error">
        <strong>无法加载原文预览</strong>
        <span>{{ loadError }}</span>
      </div>

      <div
        v-else
        class="pdf-viewer__page"
        :class="{ 'pdf-viewer__page--highlighted': page === highlightPage }"
        :style="{ width: canvasCssWidth + 'px', height: canvasCssHeight + 'px' }"
      >
        <canvas ref="canvasRef" class="pdf-viewer__canvas"></canvas>
        <div class="pdf-viewer__highlights" aria-hidden="true">
          <span
            v-for="(rect, index) in currentHighlightRects"
            :key="`${page}-${index}`"
            class="pdf-viewer__highlight"
            :style="rect"
          ></span>
        </div>
        <span v-if="page === highlightPage" class="pdf-viewer__reference-badge">引用页</span>
      </div>
    </div>
  </section>
</template>

<script setup>
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import pdfjsWorker from 'pdfjs-dist/build/pdf.worker.min.mjs?url'

const MIN_ZOOM = 0.5
const MAX_ZOOM = 2.5
const ZOOM_STEP = 0.15
const STAGE_PADDING = 64
const FIT_PAGE_SCALE_BOOST = 1.08

const props = defineProps({
  url: { type: String, required: true },
  highlightPage: { type: Number, default: null },
  highlightPositions: { type: Array, default: () => [] },
})

const loading = ref(true)
const loadError = ref('')
const page = ref(1)
const totalPages = ref(0)
const viewMode = ref('page')
const zoom = ref(1)
const canvasCssWidth = ref(0)
const canvasCssHeight = ref(0)
const containerRef = ref(null)
const canvasRef = ref(null)

let pdfDoc = null
let renderTask = null
let renderRevision = 0
let resizeTimer = null
let pendingHighlightScroll = false

/**
 * RAGFlow 坐标格式为 [页码, 左, 右, 上, 下]，坐标基于 0-1000 的页面空间。
 * 在当前 Canvas 尺寸上换算百分比，缩放模式变化时无需重新计算原始坐标。
 */
const currentHighlightRects = computed(() => normalizeHighlightPositions(props.highlightPositions)
  .filter(position => position.page === page.value)
  .map(position => ({
    left: `${position.left / 10}%`,
    top: `${position.top / 10}%`,
    width: `${(position.right - position.left) / 10}%`,
    height: `${(position.bottom - position.top) / 10}%`,
  })))

/** 加载 PDF，并在 Canvas 挂载后绘制第一页。 */
async function loadPdf() {
  loading.value = true
  loadError.value = ''
  try {
    const pdfjsLib = await import('pdfjs-dist')
    pdfjsLib.GlobalWorkerOptions.workerSrc = pdfjsWorker

    const loadingTask = pdfjsLib.getDocument(props.url)
    pdfDoc = await loadingTask.promise
    totalPages.value = pdfDoc.numPages
    page.value = normalizePage(props.highlightPage || 1)
    pendingHighlightScroll = Boolean(props.highlightPage)
    loading.value = false

    // 必须先让 v-else 中的 Canvas 完成挂载，再执行首次绘制。
    await nextTick()
    await renderCurrentPage()
  } catch (error) {
    console.error('PDF load error:', error)
    loadError.value = '请尝试重新打开预览，或下载原文件后查看。'
    loading.value = false
  }
}

/** 根据容器空间和查看模式计算比例并绘制当前页。 */
async function renderCurrentPage() {
  if (!pdfDoc || !canvasRef.value || !containerRef.value) return

  const currentRevision = ++renderRevision
  try {
    const pdfPage = await pdfDoc.getPage(page.value)
    if (currentRevision !== renderRevision) return

    if (renderTask) {
      renderTask.cancel()
      try {
        await renderTask.promise
      } catch (error) {
        if (error?.name !== 'RenderingCancelledException') throw error
      }
      renderTask = null
      if (currentRevision !== renderRevision) return
    }

    const baseViewport = pdfPage.getViewport({ scale: 1 })
    const availableWidth = Math.max(containerRef.value.clientWidth - STAGE_PADDING, 240)
    const availableHeight = Math.max(containerRef.value.clientHeight - STAGE_PADDING, 320)

    let scale
    if (viewMode.value === 'width') {
      scale = availableWidth / baseViewport.width
    } else if (viewMode.value === 'custom') {
      scale = zoom.value
    } else {
      scale = Math.min(
        availableWidth / baseViewport.width,
        availableHeight / baseViewport.height
      ) * FIT_PAGE_SCALE_BOOST
    }

    scale = Math.min(Math.max(scale, MIN_ZOOM), MAX_ZOOM)
    zoom.value = scale
    const viewport = pdfPage.getViewport({ scale })
    const pixelRatio = Math.min(window.devicePixelRatio || 1, 2)
    const canvas = canvasRef.value

    canvasCssWidth.value = Math.round(viewport.width)
    canvasCssHeight.value = Math.round(viewport.height)
    canvas.width = Math.round(viewport.width * pixelRatio)
    canvas.height = Math.round(viewport.height * pixelRatio)
    canvas.style.width = `${canvasCssWidth.value}px`
    canvas.style.height = `${canvasCssHeight.value}px`

    const context = canvas.getContext('2d')
    renderTask = pdfPage.render({
      canvasContext: context,
      viewport,
      ...(pixelRatio === 1
        ? {}
        : { transform: [pixelRatio, 0, 0, pixelRatio, 0, 0] }),
    })
    await renderTask.promise
    if (currentRevision === renderRevision) {
      renderTask = null
      await nextTick()
      if (pendingHighlightScroll) {
        scrollToHighlight()
        pendingHighlightScroll = false
      }
    }
  } catch (error) {
    if (
      currentRevision === renderRevision
      && error?.name !== 'RenderingCancelledException'
    ) {
      console.error('PDF render error:', error)
      loadError.value = '页面绘制失败，请重新打开预览。'
    }
  }
}

/** 窗口变化结束后重新适配页面，避免 ResizeObserver 与首次绘制并发。 */
function handleWindowResize() {
  if (viewMode.value === 'custom') return
  window.clearTimeout(resizeTimer)
  resizeTimer = window.setTimeout(() => renderCurrentPage(), 120)
}

/** 切换整页或页宽查看模式。 */
async function setViewMode(mode) {
  viewMode.value = mode
  await nextTick()
  await renderCurrentPage()
  scrollStageToOrigin()
}

/** 按固定步长缩放，并切换到自定义缩放模式。 */
async function changeZoom(delta) {
  viewMode.value = 'custom'
  zoom.value = Math.min(Math.max(zoom.value + delta, MIN_ZOOM), MAX_ZOOM)
  await renderCurrentPage()
}

/** 跳转到引用所在页。 */
function jumpToHighlight() {
  if (props.highlightPage) {
    const targetPage = normalizePage(props.highlightPage)
    pendingHighlightScroll = true
    if (page.value === targetPage) {
      nextTick(() => {
        scrollToHighlight()
        pendingHighlightScroll = false
      })
    } else {
      page.value = targetPage
    }
  }
}

/** 将页码约束在有效范围内。 */
function normalizePage(value) {
  return Math.min(Math.max(Number(value) || 1, 1), totalPages.value || 1)
}

/** 兼容嵌套坐标数组，并丢弃无效或越界的高亮区域。 */
function normalizeHighlightPositions(positions) {
  if (!Array.isArray(positions)) return []
  const rows = Array.isArray(positions[0]) ? positions : [positions]

  return rows.flatMap((position) => {
    if (!Array.isArray(position) || position.length < 5) return []
    const [rawPage, rawLeft, rawRight, rawTop, rawBottom] = position.map(Number)
    if (![rawPage, rawLeft, rawRight, rawTop, rawBottom].every(Number.isFinite)) return []

    const left = Math.min(Math.max(rawLeft, 0), 1000)
    const right = Math.min(Math.max(rawRight, left), 1000)
    const top = Math.min(Math.max(rawTop, 0), 1000)
    const bottom = Math.min(Math.max(rawBottom, top), 1000)
    if (right <= left || bottom <= top) return []

    return [{ page: rawPage, left, right, top, bottom }]
  })
}

watch(page, async () => {
  const shouldLocateHighlight = pendingHighlightScroll
  await nextTick()
  await renderCurrentPage()
  if (!shouldLocateHighlight) {
    scrollStageToOrigin()
  }
})

/** 将文档恢复到可访问的左上起点，避免大页面因居中布局截断顶部。 */
function scrollStageToOrigin() {
  containerRef.value?.scrollTo({ top: 0, left: 0, behavior: 'smooth' })
}

/** 将第一处引用高亮滚动到预览区中部；无坐标时退化为引用页顶部。 */
function scrollToHighlight() {
  const stage = containerRef.value
  const highlight = stage?.querySelector('.pdf-viewer__highlight')
  if (!stage || !highlight) {
    scrollStageToOrigin()
    return
  }

  const stageRect = stage.getBoundingClientRect()
  const highlightRect = highlight.getBoundingClientRect()
  const top = Math.max(
    stage.scrollTop + highlightRect.top - stageRect.top - stage.clientHeight / 3,
    0
  )
  const left = Math.max(
    stage.scrollLeft + highlightRect.left - stageRect.left - stage.clientWidth / 3,
    0
  )
  stage.scrollTo({ top, left, behavior: 'smooth' })
}

watch(
  () => props.url,
  async () => {
    await pdfDoc?.destroy()
    pdfDoc = null
    await loadPdf()
  }
)

watch(
  () => [props.highlightPage, props.highlightPositions],
  async ([highlightPage]) => {
    if (!pdfDoc || !highlightPage) return
    const targetPage = normalizePage(highlightPage)
    pendingHighlightScroll = true
    if (page.value !== targetPage) {
      page.value = targetPage
      return
    }
    await nextTick()
    scrollToHighlight()
    pendingHighlightScroll = false
  },
  { deep: true }
)

onMounted(() => {
  window.addEventListener('resize', handleWindowResize)
  loadPdf()
})
onUnmounted(() => {
  window.removeEventListener('resize', handleWindowResize)
  window.clearTimeout(resizeTimer)
  renderRevision++
  renderTask?.cancel()
  pdfDoc?.destroy()
  pdfDoc = null
})
</script>

<style scoped>
.pdf-viewer {
  display: flex;
  min-height: 0;
  height: 100%;
  flex-direction: column;
  overflow: hidden;
  border: 1px solid #dfe5ec;
  border-radius: 12px;
  background: #fff;
}

.pdf-viewer__toolbar {
  display: flex;
  min-height: 56px;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 10px 14px;
  border-bottom: 1px solid #e5eaf0;
  background: #f8fafc;
}

.pdf-viewer__page-controls,
.pdf-viewer__view-controls,
.pdf-viewer__zoom-controls {
  display: flex;
  align-items: center;
  gap: 8px;
}

.pdf-viewer__button,
.pdf-viewer__icon-button,
.pdf-viewer__highlight-button {
  min-height: 34px;
  border: 1px solid #cbd5e1;
  border-radius: 7px;
  background: #fff;
  color: #334155;
  font-size: 13px;
  font-weight: 600;
  transition: border-color 160ms ease, background-color 160ms ease, color 160ms ease;
}

.pdf-viewer__button {
  padding: 0 12px;
}

.pdf-viewer__icon-button {
  width: 34px;
  font-size: 18px;
}

.pdf-viewer__button:hover:not(:disabled),
.pdf-viewer__icon-button:hover:not(:disabled) {
  border-color: #94a3b8;
  background: #f1f5f9;
}

.pdf-viewer__button--active {
  border-color: #d97706;
  background: #fff7ed;
  color: #b45309;
}

.pdf-viewer__highlight-button {
  padding: 0 12px;
  border-color: #f59e0b;
  color: #b45309;
}

.pdf-viewer__button:focus-visible,
.pdf-viewer__icon-button:focus-visible,
.pdf-viewer__highlight-button:focus-visible {
  outline: 3px solid rgb(245 158 11 / 25%);
  outline-offset: 1px;
}

.pdf-viewer__button:disabled,
.pdf-viewer__icon-button:disabled {
  cursor: not-allowed;
  opacity: 0.4;
}

.pdf-viewer__page-status {
  display: flex;
  min-width: 58px;
  justify-content: center;
  gap: 5px;
  color: #64748b;
  font-size: 13px;
  font-variant-numeric: tabular-nums;
}

.pdf-viewer__page-status strong {
  color: #0f172a;
}

.pdf-viewer__zoom-controls {
  gap: 4px;
  padding: 2px;
  border-radius: 8px;
  background: #eef2f6;
}

.pdf-viewer__zoom-value {
  min-width: 48px;
  text-align: center;
  color: #475569;
  font-size: 12px;
  font-variant-numeric: tabular-nums;
}

.pdf-viewer__stage {
  position: relative;
  display: block;
  min-height: 420px;
  flex: 1;
  overflow: auto;
  padding: 24px;
  background: #e9eef4;
}

.pdf-viewer__page {
  position: relative;
  margin: 0 auto;
  overflow: hidden;
  background: #fff;
  box-shadow: 0 10px 28px rgb(15 23 42 / 16%);
}

.pdf-viewer__page--highlighted {
  box-shadow: 0 0 0 2px #f59e0b, 0 10px 28px rgb(15 23 42 / 16%);
}

.pdf-viewer__canvas {
  display: block;
}

.pdf-viewer__highlights {
  position: absolute;
  inset: 0;
  pointer-events: none;
}

.pdf-viewer__highlight {
  position: absolute;
  min-width: 3px;
  min-height: 3px;
  border: 1px solid rgb(245 158 11 / 85%);
  border-radius: 2px;
  background: rgb(250 204 21 / 35%);
  box-shadow: 0 0 0 1px rgb(255 255 255 / 45%), 0 2px 6px rgb(180 83 9 / 18%);
  mix-blend-mode: multiply;
}

.pdf-viewer__reference-badge {
  position: absolute;
  top: 12px;
  right: 12px;
  padding: 4px 8px;
  border-radius: 999px;
  background: #f59e0b;
  color: #fff;
  font-size: 11px;
  font-weight: 700;
  box-shadow: 0 3px 10px rgb(146 64 14 / 25%);
}

.pdf-viewer__state {
  display: flex;
  min-height: 360px;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 12px;
  color: #64748b;
  font-size: 14px;
}

.pdf-viewer__state--error {
  max-width: 420px;
  text-align: center;
  color: #b91c1c;
}

.pdf-viewer__spinner {
  width: 28px;
  height: 28px;
  border: 3px solid #dbe3ec;
  border-top-color: #d97706;
  border-radius: 50%;
  animation: pdf-viewer-spin 800ms linear infinite;
}

@keyframes pdf-viewer-spin {
  to { transform: rotate(360deg); }
}

@media (max-width: 900px) {
  .pdf-viewer__toolbar {
    align-items: stretch;
  }

  .pdf-viewer__view-controls {
    flex-wrap: wrap;
  }
}

@media (prefers-reduced-motion: reduce) {
  .pdf-viewer__button,
  .pdf-viewer__icon-button,
  .pdf-viewer__highlight-button {
    transition: none;
  }

  .pdf-viewer__spinner {
    animation-duration: 1.6s;
  }
}
</style>
