<template>
  <div
    v-if="visible"
    class="citation-preview"
    role="presentation"
    @click.self="close"
  >
    <section
      class="citation-preview__dialog"
      role="dialog"
      aria-modal="true"
      :aria-label="docName || '原文预览'"
    >
      <header class="citation-preview__header">
        <div class="citation-preview__title-group">
          <div class="citation-preview__file-icon" aria-hidden="true">文</div>
          <div class="min-w-0">
            <h3 class="citation-preview__title">{{ docName || '原文预览' }}</h3>
            <p class="citation-preview__meta">
              <span>数据集：{{ datasetId }}</span>
              <span>文档：{{ documentId }}</span>
            </p>
          </div>
        </div>
        <button
          type="button"
          class="citation-preview__close"
          aria-label="关闭原文预览"
          @click="close"
        >
          ×
        </button>
      </header>

      <div class="citation-preview__body">
        <main class="citation-preview__document">
          <SqlQaPdfErrorBoundary>
            <SqlQaPdfViewer
              :url="resolvedPdfUrl"
              :highlight-page="highlightPage"
              :highlight-positions="highlightPositions"
            />
          </SqlQaPdfErrorBoundary>
        </main>

        <aside v-if="chunks && chunks.length > 0" class="citation-preview__references">
          <div class="citation-preview__references-header">
            <div>
              <h4>相关内容块</h4>
              <p>共 {{ chunks.length }} 条引用内容</p>
            </div>
          </div>

          <div class="citation-preview__chunk-list">
            <article
              v-for="(chunk, index) in chunks"
              :key="`${chunk.id || chunk.document_id || 'chunk'}-${index}`"
              class="citation-preview__chunk"
            >
              <div class="citation-preview__chunk-heading">
                <span class="citation-preview__chunk-index">{{ index + 1 }}</span>
                <strong>{{ cleanDisplayText(chunk.document_name) || `内容块 ${index + 1}` }}</strong>
              </div>
              <div
                class="citation-preview__chunk-content"
                v-html="highlightKeywords(chunk.content, keywords)"
              ></div>
              <div class="citation-preview__similarity">
                <span>匹配度</span>
                <strong>{{ formatSimilarity(chunk.similarity) }}</strong>
              </div>
            </article>
          </div>
        </aside>
      </div>

      <footer class="citation-preview__footer">
        <a
          :href="resolvedPdfUrl"
          target="_blank"
          rel="noopener noreferrer"
          class="citation-preview__open-link"
        >
          在新窗口中查看
        </a>
        <button type="button" class="citation-preview__footer-close" @click="close">
          关闭预览
        </button>
      </footer>
    </section>
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted } from 'vue'
import SqlQaPdfViewer from './SqlQaPdfViewer.vue'
import SqlQaPdfErrorBoundary from './SqlQaPdfErrorBoundary.vue'

const props = defineProps({
  visible: { type: Boolean, default: false },
  datasetId: { type: String, default: '' },
  documentId: { type: String, default: '' },
  docName: { type: String, default: '' },
  chunks: { type: Array, default: () => [] },
  highlightPage: { type: Number, default: null },
  highlightPositions: { type: Array, default: () => [] },
  keywords: { type: String, default: '' },
  pdfUrl: { type: String, default: '' },
})

const emit = defineEmits(['close'])

const resolvedPdfUrl = computed(() => {
  if (props.pdfUrl) return props.pdfUrl
  const params = new URLSearchParams({
    dataset_id: props.datasetId,
    document_id: props.documentId,
  })
  return `/api/ragflow/document-download?${params.toString()}`
})

/** 移除历史数据中已存在的不可显示替换字符。 */
function cleanDisplayText(value) {
  return typeof value === 'string'
    ? value.replace(/\u0000|\uFEFF/g, '').replace(/\uFFFD+/g, '')
    : ''
}

/** 高亮完整问题或关键词，并对输出进行 HTML 转义。 */
function highlightKeywords(text, keyword) {
  const cleanedText = cleanDisplayText(text)
  const escapedText = escapeHtml(cleanedText)
  const cleanedKeyword = cleanDisplayText(keyword).trim()
  if (!cleanedKeyword) return escapedText

  const escapedKeyword = escapeRegExp(escapeHtml(cleanedKeyword))
  return escapedText.replace(
    new RegExp(`(${escapedKeyword})`, 'gi'),
    '<mark class="citation-preview__keyword">$1</mark>'
  )
}

function escapeHtml(value) {
  return value
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;')
}

function escapeRegExp(value) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}

function formatSimilarity(value) {
  const similarity = Number(value)
  return Number.isFinite(similarity) ? `${(similarity * 100).toFixed(1)}%` : '—'
}

function close() {
  emit('close')
}

function handleKeydown(event) {
  if (event.key === 'Escape') close()
}

onMounted(() => window.addEventListener('keydown', handleKeydown))
onUnmounted(() => window.removeEventListener('keydown', handleKeydown))
</script>

<style scoped>
.citation-preview {
  position: fixed;
  inset: 0;
  z-index: 50;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 3vh 2vw;
  background: rgb(15 23 42 / 58%);
}

.citation-preview__dialog {
  display: flex;
  width: min(96vw, 1680px);
  height: 94vh;
  min-height: 680px;
  flex-direction: column;
  overflow: hidden;
  border: 1px solid rgb(255 255 255 / 65%);
  border-radius: 16px;
  background: #fff;
  box-shadow: 0 28px 80px rgb(15 23 42 / 32%);
}

.citation-preview__header {
  display: flex;
  min-height: 76px;
  align-items: center;
  justify-content: space-between;
  gap: 20px;
  padding: 14px 20px;
  border-bottom: 1px solid #e5eaf0;
  background: #fff;
}

.citation-preview__title-group {
  display: flex;
  min-width: 0;
  align-items: center;
  gap: 12px;
}

.citation-preview__file-icon {
  display: grid;
  width: 40px;
  height: 40px;
  flex: 0 0 auto;
  place-items: center;
  border-radius: 10px;
  background: #fff7ed;
  color: #b45309;
  font-size: 16px;
  font-weight: 800;
}

.citation-preview__title {
  overflow: hidden;
  color: #172033;
  font-size: 17px;
  font-weight: 700;
  line-height: 1.35;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.citation-preview__meta {
  display: flex;
  flex-wrap: wrap;
  gap: 4px 16px;
  margin-top: 4px;
  color: #64748b;
  font-size: 12px;
}

.citation-preview__close {
  display: grid;
  width: 38px;
  height: 38px;
  flex: 0 0 auto;
  place-items: center;
  border: 0;
  border-radius: 9px;
  background: transparent;
  color: #64748b;
  font-size: 25px;
  line-height: 1;
  transition: background-color 160ms ease, color 160ms ease;
}

.citation-preview__close:hover {
  background: #f1f5f9;
  color: #0f172a;
}

.citation-preview__body {
  display: grid;
  min-height: 0;
  flex: 1;
  grid-template-columns: minmax(0, 1fr) clamp(340px, 24vw, 420px);
  overflow: hidden;
  background: #f5f7fa;
}

.citation-preview__document {
  min-width: 0;
  min-height: 0;
  padding: 14px;
}

.citation-preview__references {
  display: flex;
  min-width: 0;
  min-height: 0;
  flex-direction: column;
  border-left: 1px solid #e2e8f0;
  background: #fff;
}

.citation-preview__references-header {
  padding: 16px 18px 13px;
  border-bottom: 1px solid #e9edf2;
}

.citation-preview__references-header h4 {
  color: #1e293b;
  font-size: 14px;
  font-weight: 700;
}

.citation-preview__references-header p {
  margin-top: 2px;
  color: #64748b;
  font-size: 12px;
}

.citation-preview__chunk-list {
  min-height: 0;
  flex: 1;
  overflow-y: auto;
  padding: 12px;
}

.citation-preview__chunk {
  padding: 14px;
  border: 1px solid #e5eaf0;
  border-radius: 10px;
  background: #f8fafc;
}

.citation-preview__chunk + .citation-preview__chunk {
  margin-top: 10px;
}

.citation-preview__chunk-heading {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  color: #334155;
  font-size: 13px;
  line-height: 1.45;
}

.citation-preview__chunk-heading strong {
  overflow-wrap: anywhere;
}

.citation-preview__chunk-index {
  display: grid;
  width: 22px;
  height: 22px;
  flex: 0 0 auto;
  place-items: center;
  border-radius: 6px;
  background: #ffedd5;
  color: #b45309;
  font-size: 11px;
  font-weight: 800;
}

.citation-preview__chunk-content {
  margin-top: 10px;
  color: #475569;
  font-size: 13px;
  line-height: 1.75;
  overflow-wrap: anywhere;
}

.citation-preview__similarity {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-top: 12px;
  padding-top: 10px;
  border-top: 1px solid #e5eaf0;
  color: #64748b;
  font-size: 12px;
}

.citation-preview__similarity strong {
  color: #b45309;
  font-variant-numeric: tabular-nums;
}

:deep(.citation-preview__keyword) {
  padding: 1px 2px;
  border-radius: 3px;
  background: #fde68a;
  color: #78350f;
}

.citation-preview__footer {
  display: flex;
  min-height: 58px;
  align-items: center;
  justify-content: space-between;
  padding: 10px 20px;
  border-top: 1px solid #e5eaf0;
  background: #fff;
}

.citation-preview__open-link {
  color: #b45309;
  font-size: 13px;
  font-weight: 650;
}

.citation-preview__open-link:hover {
  text-decoration: underline;
}

.citation-preview__footer-close {
  min-height: 36px;
  padding: 0 16px;
  border: 1px solid #cbd5e1;
  border-radius: 8px;
  background: #fff;
  color: #334155;
  font-size: 13px;
  font-weight: 650;
}

.citation-preview__close:focus-visible,
.citation-preview__footer-close:focus-visible,
.citation-preview__open-link:focus-visible {
  outline: 3px solid rgb(245 158 11 / 28%);
  outline-offset: 2px;
}

@media (max-width: 1100px) {
  .citation-preview {
    padding: 2vh 1.5vw;
  }

  .citation-preview__dialog {
    width: 97vw;
    height: 96vh;
  }

  .citation-preview__body {
    grid-template-columns: minmax(0, 1fr) 330px;
  }
}

@media (max-width: 780px) {
  .citation-preview__dialog {
    min-height: 0;
  }

  .citation-preview__body {
    overflow-y: auto;
    grid-template-columns: 1fr;
    grid-template-rows: minmax(520px, 70vh) auto;
  }

  .citation-preview__references {
    max-height: 45vh;
    border-top: 1px solid #e2e8f0;
    border-left: 0;
  }

  .citation-preview__meta {
    display: none;
  }
}

@media (prefers-reduced-motion: reduce) {
  .citation-preview__close {
    transition: none;
  }
}
</style>
