/**
 * 共享格式化工具函数。
 *
 * 此前 formatDate / formatTime 在 9+ 个 .vue 文件中各自重复实现，
 * 现在统一到这里，各组件 import 即可。
 */
import { marked } from 'marked'

/**
 * 格式化日期（仅日期，不含时间）。
 * @param {string|Date|null} d
 * @returns {string} 如 "2025/01/03"，无效时返回 fallback
 */
export function formatDate(d, fallback = '—') {
  if (!d) return fallback
  try {
    return new Date(d).toLocaleDateString('zh-CN', {
      year: 'numeric', month: '2-digit', day: '2-digit'
    })
  } catch {
    return typeof d === 'string' ? d : fallback
  }
}

/**
 * 格式化日期时间（含时分秒）。
 * @param {string|Date|null} d
 * @param {string} fallback
 * @returns {string} 如 "2025/01/03 14:30:00"
 */
export function formatDateTime(d, fallback = '—') {
  if (!d) return fallback
  try {
    return new Date(d).toLocaleString('zh-CN', {
      year: 'numeric', month: '2-digit', day: '2-digit',
      hour: '2-digit', minute: '2-digit', second: '2-digit'
    })
  } catch {
    return typeof d === 'string' ? d : fallback
  }
}

/**
 * 格式化文件大小。
 * @param {number|null} bytes
 * @returns {string} 如 "1.5 MB"
 */
export function formatFileSize(bytes) {
  if (!bytes) return '0 B'
  if (bytes < 1024) return bytes + ' B'
  if (bytes < 1048576) return (bytes / 1024).toFixed(1) + ' KB'
  return (bytes / 1048576).toFixed(1) + ' MB'
}

/**
 * 将 Markdown 渲染为 HTML（使用 marked）。
 * 统一错误处理，避免每个组件各自 try/catch。
 * @param {string} text
 * @returns {string} HTML 字符串
 */
export function renderMarkdown(text) {
  if (!text) return ''
  try {
    return marked.parse(text)
  } catch {
    return text
  }
}
