<template>
  <div
    :class="[
      'mb-4 px-2',
      message.role === 'user' ? 'flex justify-end' : ''
    ]"
    data-test="kbqa-message"
  >
    <!-- 用户消息 -->
    <div
      v-if="message.role === 'user'"
      class="bg-blue-50 px-4 py-2.5 rounded-xl text-[15px] max-w-[70%] text-slate-900"
    >
      {{ message.content }}
      <div class="text-[12px] text-slate-400 text-right mt-1.5">
        {{ formatTime(message.created_at) }}
      </div>
    </div>

    <!-- AI 消息 -->
    <div v-else class="flex gap-2.5 items-start w-full">
      <div class="w-9 h-9 bg-amber-100 rounded-lg flex items-center justify-center text-base flex-shrink-0">🤖</div>
      <div class="flex-1 max-w-[95%]">
        <div
          v-if="message.used_kb_ids && message.used_kb_ids.length"
          class="text-[13px] text-slate-500 mb-1.5"
        >
          已检索 {{ kbNames }}
        </div>

        <!-- 思考过程（可折叠，默认收起） -->
        <div v-if="message.thinking" class="mb-2">
          <div
            class="thinking-header"
            @click="thinkingExpanded = !thinkingExpanded"
          >
            <span>🤔 思考过程</span>
            <span class="thinking-toggle">{{ thinkingExpanded ? '收起 ▲' : '展开 ▼' }}</span>
          </div>
          <div v-show="thinkingExpanded" class="thinking-body">
            {{ message.thinking }}
          </div>
        </div>

        <div
          class="bg-slate-50 px-4 py-3 rounded-lg border border-slate-200 text-[15px] leading-relaxed text-slate-900 markdown-body"
          v-html="renderedAnswer"
          @click="handleCitationClick"
        ></div>

        <!-- 流式输出中光标 -->
        <div v-if="message.streaming" class="text-[15px] text-slate-400 mt-1">
          正在生成中<span class="streaming-cursor">▊</span>
        </div>

        <!-- 引用文档卡片 -->
        <div v-if="referenceCards.length > 0" class="mt-3">
          <div class="text-[12px] font-semibold text-slate-500 mb-1.5">📎 引用文档</div>
          <div class="flex flex-wrap gap-2">
            <div
              v-for="card in referenceCards"
              :key="card.document_id"
              class="bg-white border border-slate-200 rounded-md p-3 min-w-[200px] max-w-[320px]"
            >
              <div class="text-[13px] font-semibold text-slate-900 truncate">{{ card.name }}</div>
              <div class="text-[12px] text-slate-500 mt-1">
                匹配度 {{ card.similarity }}%
                <span v-if="card.page"> · 第 {{ card.page }} 页</span>
              </div>
              <div class="mt-2 flex gap-2">
                <button
                  @click="handleCardPreview(card)"
                  class="text-[12px] font-medium text-blue-600 cursor-pointer px-2 py-1 bg-blue-50 rounded hover:bg-blue-100 border-0"
                >👁 预览</button>
                <button
                  @click="handleDownload(card)"
                  class="text-[12px] font-medium text-emerald-600 cursor-pointer px-2 py-1 bg-emerald-50 rounded hover:bg-emerald-100 border-0"
                >⬇ 下载</button>
              </div>
            </div>
          </div>
        </div>

        <div class="text-[12px] text-slate-400 mt-1.5">{{ formatTime(message.created_at) }}</div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'
import { marked } from 'marked'
import { kbQaClient } from '@/api/kbQaClient'

// 思考过程展开/折叠状态
const thinkingExpanded = ref(false)

// ---------- marked 配置 ----------
marked.setOptions({
  breaks: true,   // 单换行转 <br>
  gfm: true,      // GitHub Flavored Markdown（表格、任务列表等）
})

// ---------- props / emits ----------
const props = defineProps({
  message: {
    type: Object,
    required: true,
  },
  allKbs: {
    type: Array,
    default: () => [],
  },
})
const emit = defineEmits(['preview'])

// ---------- 引用占位符 ----------
// 保护引用标记不被 markdown 误解析。
// 注意：不能用 __TEXT__ 格式（markdown 会解析为粗体 <strong>，破坏占位符）。
// 使用 CITREF__N 格式（__ 夹在单词中间，markdown 不会触发强调解析）。
const CITREF_PLACEHOLDER = /CITREF__(\d+)/g

/** 生成 <sup> 角标 HTML */
function buildSupHtml(idx, num) {
  return `<sup data-citation="${idx}" class="citation-badge" title="引用 ${num}">[${num}]</sup>`
}

// ---------- 渲染回答（Markdown + 引用角标） ----------
const renderedAnswer = computed(() => {
  const raw = cleanDisplayText(props.message.content)
  if (!raw) return ''

  // === 第 1 步：保护引用标记 ===
  // 三种 RAGFlow 引用格式：
  //   A: 【N】（全角方括号），N 从 1 开始 → chunks[N-1]
  //   B: ##N$$（遗留半角 hash-dollar），N 从 0 开始 → chunks[N]，显示 N+1
  //   C: [ID:N]（部分版本/模型），N 从 0 开始 → chunks[N]，显示 N+1
  const citations = []  // { idx: chunks数组下标, num: 显示数字 }
  let protectedText = raw

  // 格式 A: RAGFlow 原生 【N】
  protectedText = protectedText.replace(/【(\d+)】/g, (_match, numStr) => {
    const n = parseInt(numStr, 10)
    const id = citations.length
    citations.push({ idx: n - 1, num: n })  // 【1】→ chunks[0], 显示 [1]
    return `CITREF__${id}`
  })

  // 格式 B: 遗留 ##N$$
  protectedText = protectedText.replace(/##(\d+)\$\$/g, (_match, numStr) => {
    const n = parseInt(numStr, 10)
    const id = citations.length
    citations.push({ idx: n, num: n + 1 })  // ##0$$ → chunks[0], 显示 [1]
    return `CITREF__${id}`
  })

  // 格式 C: RAGFlow [ID:N]（部分版本/模型的引用格式，N 从 0 开始）
  protectedText = protectedText.replace(/\[ID:(\d+)\]/g, (_match, numStr) => {
    const n = parseInt(numStr, 10)
    const id = citations.length
    citations.push({ idx: n, num: n + 1 })  // [ID:0] → chunks[0], 显示 [1]
    return `CITREF__${id}`
  })

  // === 第 2 步：Markdown → HTML ===
  let html = marked.parse(protectedText) || ''

  // === 第 3 步：还原引用为可点击 <sup> ===
  html = html.replace(CITREF_PLACEHOLDER, (_match, idStr) => {
    const id = parseInt(idStr, 10)
    if (id < citations.length) {
      const { idx, num } = citations[id]
      return buildSupHtml(idx, num)
    }
    return _match
  })

  return html
})

/** 兼容清理历史消息中已保存的 Unicode 替换字符。 */
function cleanDisplayText(value) {
  return typeof value === 'string'
    ? value.replace(/\u0000|\uFEFF/g, '').replace(/\uFFFD+/g, '')
    : value
}

/** 从 RAGFlow 的 [页码, 左, 右, 上, 下] 坐标中安全读取首个引用页。 */
function getReferencePage(positions) {
  if (!Array.isArray(positions) || positions.length === 0) return null
  const firstPosition = Array.isArray(positions[0]) ? positions[0] : positions
  const page = Number(firstPosition[0])
  return Number.isFinite(page) && page > 0 ? page : null
}

// ---------- 引用角标点击（事件委托） ----------
function handleCitationClick(event) {
  // 找到最近的 sup[data-citation] 元素
  const sup = event.target.closest('sup[data-citation]')
  if (!sup) return

  const idx = parseInt(sup.dataset.citation, 10)
  if (isNaN(idx)) return

  // 从 rag_references.chunks 获取引用信息
  const chunks = props.message.rag_references?.chunks
  if (!chunks || idx < 0 || idx >= chunks.length) return

  const chunk = chunks[idx]
  // 找到当前文档相关的所有 chunks（用于预览弹窗侧边栏显示）
  const relatedChunks = chunks.filter(
    c => c.document_id === chunk.document_id
  )
  emit('preview', {
    document_id: chunk.document_id,
    dataset_id: chunk.dataset_id,
    name: chunk.document_name || chunk.document_id,
    page: getReferencePage(chunk.positions),
    chunks: relatedChunks,
    positions: chunk.positions || [],
  })
}

/** 参考卡片预览按钮：传递完整的文档 chunks 给预览弹窗 */
function handleCardPreview(card) {
  const chunks = props.message.rag_references?.chunks || []
  const docChunks = chunks.filter(c => c.document_id === card.document_id)
  emit('preview', {
    ...card,
    chunks: docChunks,
    positions: card.positions || [],
  })
}

// ---------- 其他 computed ----------
const kbNames = computed(() => {
  if (!props.message.used_kb_ids) return ''
  return props.message.used_kb_ids
    .map((id) => props.allKbs.find((k) => k.id === id)?.name || id)
    .join('、')
})

const referenceCards = computed(() => {
  const refs = props.message.rag_references
  if (!refs || !refs.chunks || !Array.isArray(refs.chunks)) return []
  // 按 document_id 去重
  const seen = new Set()
  const cards = []
  for (const chunk of refs.chunks) {
    if (!chunk.document_id || seen.has(chunk.document_id)) continue
    seen.add(chunk.document_id)
    cards.push({
      document_id: chunk.document_id,
      dataset_id: chunk.dataset_id,
      name: chunk.document_name || chunk.document_id,
      similarity: Math.round((chunk.similarity || 0) * 100),
      page: getReferencePage(chunk.positions),
      positions: chunk.positions || [],
      download_url: kbQaClient.getDocumentDownloadUrl({
        datasetId: chunk.dataset_id,
        documentId: chunk.document_id,
      }),
    })
  }
  return cards
})

function formatTime(iso) {
  if (!iso) return ''
  try {
    const d = new Date(iso)
    return `${d.getHours().toString().padStart(2, '0')}:${d.getMinutes().toString().padStart(2, '0')}`
  } catch {
    return ''
  }
}

/** 下载文档：通过 fetch + Authorization 获取 blob，再触发浏览器下载。
 *  不使用 <a href> 直接导航，因为后端端点可能要求认证标头。 */
async function handleDownload(card) {
  const token = localStorage.getItem('auth_token')
  const params = new URLSearchParams({
    dataset_id: card.dataset_id,
    document_id: card.document_id,
    filename: card.name || '',
  })
  const url = `/api/kb-qa/ragflow/document-download?${params.toString()}`
  try {
    const resp = await fetch(url, {
      headers: { Authorization: `Bearer ${token || ''}` },
    })
    if (!resp.ok) {
      const errText = await resp.text().catch(() => '')
      throw new Error(errText || `HTTP ${resp.status}`)
    }
    const blob = await resp.blob()
    const blobUrl = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = blobUrl
    a.download = card.name || 'document'
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
    URL.revokeObjectURL(blobUrl)
  } catch (e) {
    console.error('下载文档失败:', e)
  }
}
</script>

<style scoped>
/* 思考过程样式 */
.thinking-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 6px 12px;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 6px;
  font-size: 13px;
  color: #64748b;
  cursor: pointer;
  user-select: none;
  transition: background 0.15s;
}
.thinking-header:hover {
  background: #f1f5f9;
}
.thinking-toggle {
  font-size: 12px;
  color: #94a3b8;
}
.thinking-body {
  margin-top: 6px;
  padding: 10px 12px;
  background: #fafbfc;
  border: 1px solid #e2e8f0;
  border-radius: 6px;
  font-size: 13px;
  line-height: 1.65;
  color: #475569;
  white-space: pre-wrap;
  word-break: break-word;
}

/* 引用角标样式 */
.citation-badge {
  background-color: #3b82f6;
  color: white;
  padding: 0 3px;
  border-radius: 3px;
  font-size: 10px;
  cursor: pointer;
  margin-left: 1px;
  vertical-align: super;
  transition: background-color 0.15s;
  line-height: 1;
}
.citation-badge:hover {
  background-color: #1d4ed8;
}

/* 流式输出闪烁光标 */
.streaming-cursor {
  animation: blink 1s step-end infinite;
}
@keyframes blink {
  0%, 100% { opacity: 1; }
  50% { opacity: 0; }
}

/* Markdown 内容样式增强 */
.markdown-body :deep(h1),
.markdown-body :deep(h2),
.markdown-body :deep(h3),
.markdown-body :deep(h4) {
  font-weight: 600;
  margin: 0.75em 0 0.5em;
  line-height: 1.4;
}
.markdown-body :deep(h1) { font-size: 1.4em; }
.markdown-body :deep(h2) { font-size: 1.25em; }
.markdown-body :deep(h3) { font-size: 1.1em; }

.markdown-body :deep(p) {
  margin: 0.5em 0;
}

.markdown-body :deep(ul),
.markdown-body :deep(ol) {
  padding-left: 1.5em;
  margin: 0.5em 0;
}

.markdown-body :deep(li) {
  margin: 0.25em 0;
}

.markdown-body :deep(code) {
  background-color: #f1f5f9;
  padding: 1px 5px;
  border-radius: 3px;
  font-size: 0.9em;
  font-family: 'Consolas', 'Monaco', 'Courier New', monospace;
}

.markdown-body :deep(pre) {
  background-color: #1e293b;
  color: #e2e8f0;
  padding: 12px 16px;
  border-radius: 6px;
  overflow-x: auto;
  margin: 0.75em 0;
  font-size: 0.9em;
}

.markdown-body :deep(pre code) {
  background: none;
  padding: 0;
  color: inherit;
  font-size: inherit;
}

.markdown-body :deep(table) {
  border-collapse: collapse;
  width: 100%;
  margin: 0.75em 0;
}

.markdown-body :deep(th),
.markdown-body :deep(td) {
  border: 1px solid #e2e8f0;
  padding: 6px 12px;
  text-align: left;
}

.markdown-body :deep(th) {
  background-color: #f8fafc;
  font-weight: 600;
}

.markdown-body :deep(strong) {
  font-weight: 600;
}

.markdown-body :deep(blockquote) {
  border-left: 3px solid #e2e8f0;
  padding-left: 12px;
  margin: 0.5em 0;
  color: #64748b;
}

.markdown-body :deep(hr) {
  border: none;
  border-top: 1px solid #e2e8f0;
  margin: 1em 0;
}
</style>
