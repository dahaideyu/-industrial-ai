<template>
  <div class="search-results">
    <!-- 结果头 -->
    <div class="results-header">
      <div class="results-info">
        <span>{{ modeLabel }} — </span>
        <template v-if="loading">
          <span class="spinner-small"></span> 搜索中...
        </template>
        <template v-else>
          找到 <strong>{{ total }}</strong> 条结果
          <span v-if="degraded" class="degraded-tag" title="语义搜索不可用，已自动降级为关键词搜索">⚠ 已降级</span>
        </template>
      </div>
      <button class="clear-btn-text" @click="$emit('clear')">清除搜索</button>
    </div>

    <!-- 加载中 -->
    <div v-if="loading && results.length === 0" class="loading-state">
      <div class="spinner-large"></div>
      <span>搜索中...</span>
    </div>

    <!-- 空结果 -->
    <div v-else-if="!loading && results.length === 0" class="empty-state">
      <div class="empty-icon">🔍</div>
      <div class="empty-title">未找到匹配的文档</div>
      <div class="empty-desc">试试其他关键词，或切换到语义搜索模式</div>
    </div>

    <!-- 结果列表 -->
    <div v-else class="results-list">
      <div v-for="item in results" :key="item.version_id || item.document_id"
        class="result-item" @click="$emit('preview', item)">
        <div class="result-main">
          <div class="result-top">
            <span class="doc-icon">{{ fileIcon(item.file_type) }}</span>
            <span class="doc-name" :title="item.display_name || item.original_filename">
              {{ item.display_name || item.original_filename }}
            </span>
            <span v-if="item.file_type" class="type-tag">{{ item.file_type }}</span>
            <span class="status-tag" :class="statusClass(item.status)">{{ statusLabel(item.status) }}</span>
            <span v-if="item.similarity != null" class="similarity-tag">相关度 {{ (item.similarity * 100).toFixed(0) }}%</span>
          </div>
          <div class="result-context-text" v-if="item.match_context">
            {{ item.match_context }}
          </div>
          <div class="result-meta" v-if="item.knowledge_base">
            <span v-if="item.knowledge_base.workshop">{{ item.knowledge_base.workshop }} · </span>
            <span v-if="item.knowledge_base.device_type">{{ item.knowledge_base.device_type }} · </span>
            <span>{{ item.category_name || '未分类' }}</span>
          </div>
        </div>
        <div class="result-right">
          <span v-if="item.ai_quality_score != null" class="quality-score" :class="scoreClass(item.ai_quality_score)">
            {{ item.ai_quality_score }}
          </span>
          <span class="result-date">{{ formatDate(item.created_at) }}</span>
        </div>
      </div>
    </div>

    <!-- 加载更多 -->
    <div v-if="hasMore" class="load-more">
      <button class="load-more-btn" :disabled="loading" @click="$emit('load-more')">
        <span v-if="loading" class="spinner-small"></span>
        {{ loading ? '加载中...' : '加载更多' }}
      </button>
      <span class="load-more-info">已显示 {{ results.length }} / {{ total }} 条</span>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  results: { type: Array, default: () => [] },
  total: { type: Number, default: 0 },
  page: { type: Number, default: 1 },
  loading: { type: Boolean, default: false },
  mode: { type: String, default: 'keyword' },
  degraded: { type: Boolean, default: false },
  pageSize: { type: Number, default: 20 },
})

defineEmits(['load-more', 'preview', 'clear'])

const modeLabel = computed(() => props.mode === 'semantic' ? '⚡ 语义搜索' : '🔤 关键词搜索')
const hasMore = computed(() => props.results.length < props.total)

function fileIcon(ft) {
  if (ft === 'table') return '📊'
  if (ft === 'image') return '🖼️'
  return '📄'
}

function statusLabel(s) {
  const map = { approved: '已审批', rejected: '已驳回', pending: '待处理', ai_processing: 'AI审核中', published: '已发布' }
  return map[s] || s || '未知'
}

function statusClass(s) {
  if (s === 'approved' || s === 'published') return 'ok'
  if (s === 'rejected') return 'bad'
  return ''
}

function scoreClass(s) {
  if (s >= 85) return 'good'
  if (s >= 60) return 'mid'
  return 'low'
}

function formatDate(d) {
  if (!d) return ''
  try { return new Date(d).toLocaleDateString('zh-CN', { month: '2-digit', day: '2-digit', year: 'numeric' }) } catch { return d }
}
</script>

<style scoped>
.search-results {
  flex: 1;
  min-width: 0;
}
.results-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12px;
}
.results-info {
  font-size: 13px;
  color: #64748b;
}
.results-info strong { color: #1e293b; }
.degraded-tag {
  display: inline-block;
  margin-left: 6px;
  font-size: 10px;
  background: #fef3c7;
  color: #b45309;
  padding: 1px 6px;
  border-radius: 4px;
  cursor: help;
}
.clear-btn-text {
  font-size: 12px;
  color: #ef4444;
  background: none;
  border: none;
  cursor: pointer;
}
.clear-btn-text:hover { text-decoration: underline; }

.loading-state, .empty-state {
  text-align: center;
  padding: 48px 0;
}
.empty-icon { font-size: 36px; margin-bottom: 8px; }
.empty-title { font-size: 15px; font-weight: 600; color: #64748b; margin-bottom: 4px; }
.empty-desc { font-size: 13px; color: #94a3b8; }

.results-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.result-item {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  padding: 12px 14px;
  background: #fff;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  cursor: pointer;
  transition: border-color .15s, box-shadow .15s;
}
.result-item:hover {
  border-color: #b45309;
  box-shadow: 0 2px 10px rgba(180,83,9,.08);
}
.result-main { flex: 1; min-width: 0; }
.result-top {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 4px;
  flex-wrap: wrap;
}
.doc-icon { font-size: 14px; flex-shrink: 0; }
.doc-name {
  font-size: 14px;
  font-weight: 600;
  color: #1e293b;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  flex: 1;
  min-width: 0;
}
.type-tag {
  font-size: 10px;
  background: #f1f5f9;
  color: #64748b;
  padding: 1px 6px;
  border-radius: 4px;
  flex-shrink: 0;
}
.status-tag {
  font-size: 10px;
  padding: 1px 6px;
  border-radius: 4px;
  flex-shrink: 0;
}
.status-tag.ok { background: #f0fdf4; color: #16a34a; }
.status-tag.bad { background: #fef2f2; color: #ef4444; }
.status-tag:not(.ok):not(.bad) { background: #f8fafc; color: #94a3b8; }
.similarity-tag {
  font-size: 10px;
  background: #eff6ff;
  color: #3b82f6;
  padding: 1px 6px;
  border-radius: 4px;
  flex-shrink: 0;
}

.result-context-text {
  font-size: 12px;
  color: #94a3b8;
  line-height: 1.5;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
  margin-bottom: 4px;
}
.result-meta {
  font-size: 11px;
  color: #94a3b8;
}
.result-right {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 4px;
  flex-shrink: 0;
}
.quality-score {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  border-radius: 50%;
  font-size: 13px;
  font-weight: 700;
}
.quality-score.good { background: #f0fdf4; color: #16a34a; }
.quality-score.mid { background: #fef3c7; color: #b45309; }
.quality-score.low { background: #fef2f2; color: #ef4444; }
.result-date {
  font-size: 10px;
  color: #94a3b8;
}

.load-more {
  text-align: center;
  padding: 16px 0;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 10px;
}
.load-more-btn {
  padding: 6px 16px;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  font-size: 12px;
  color: #64748b;
  cursor: pointer;
  display: flex;
  align-items: center;
  gap: 6px;
}
.load-more-btn:hover:not(:disabled) { background: #f1f5f9; }
.load-more-btn:disabled { opacity: .5; cursor: not-allowed; }
.load-more-info { font-size: 11px; color: #94a3b8; }

.spinner-small {
  display: inline-block;
  width: 12px;
  height: 12px;
  border: 2px solid #e2e8f0;
  border-top-color: #b45309;
  border-radius: 50%;
  animation: spin .6s linear infinite;
}
.spinner-large {
  width: 20px;
  height: 20px;
  border: 2px solid #e2e8f0;
  border-top-color: #b45309;
  border-radius: 50%;
  animation: spin .6s linear infinite;
  margin: 0 auto 8px;
}
@keyframes spin { to { transform: rotate(360deg); } }
</style>
