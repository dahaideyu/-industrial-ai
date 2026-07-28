<template>
  <div class="search-bar">
    <div class="search-input-wrap">
      <svg class="search-icon" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"/>
      </svg>
      <input
        ref="inputEl"
        :value="modelValue"
        type="text"
        class="search-input"
        :placeholder="placeholder"
        @input="onInput"
        @keyup.enter="$emit('search', modelValue, mode)"
        @keydown="onKeydown"
      />
      <button v-if="modelValue" class="clear-btn" @click="$emit('clear')" title="清除搜索">
        <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/>
        </svg>
      </button>
    </div>

    <div class="mode-dropdown-wrap">
      <button class="mode-btn" @click="toggleMenu">
        <span>{{ modeLabel }}</span>
        <svg class="w-3 h-3 ml-1" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7"/>
        </svg>
      </button>
      <div v-if="menuOpen" class="mode-menu" @click.self="menuOpen = false">
        <div class="mode-menu-item"
          :class="{ active: mode === 'keyword' }"
          @click="selectMode('keyword')">
          <div class="mode-menu-label">关键词搜索</div>
          <div class="mode-menu-desc">文件名 + 文本内容模糊匹配</div>
        </div>
        <div class="mode-menu-item"
          :class="{ active: mode === 'semantic', disabled: !semanticAvailable }"
          :title="!semanticAvailable ? '语义搜索需要 RAGFlow 服务支持，当前不可用' : ''"
          @click="semanticAvailable && selectMode('semantic')">
          <div class="mode-menu-label">语义搜索</div>
          <div class="mode-menu-desc">基于 AI 理解语义，仅已发布文档</div>
          <div v-if="!semanticAvailable" class="mode-menu-badge">不可用</div>
        </div>
      </div>
    </div>

    <button class="search-btn" @click="$emit('search', modelValue, mode)" :disabled="!modelValue || modelValue.length < 2">
      <span v-if="loading" class="spinner"></span>
      <span v-else>搜索</span>
    </button>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'

const props = defineProps({
  modelValue: { type: String, default: '' },
  mode: { type: String, default: 'keyword' },
  semanticAvailable: { type: Boolean, default: true },
  loading: { type: Boolean, default: false },
  placeholder: { type: String, default: '搜索文档名称、内容关键词...' },
})

const emit = defineEmits(['update:modelValue', 'update:mode', 'search', 'clear'])

const inputEl = ref(null)
const menuOpen = ref(false)
let debounceTimer = null

const modeLabel = computed(() => props.mode === 'semantic' ? '⚡ 语义搜索' : '🔤 关键词搜索')

function onInput(e) {
  const val = e.target.value
  emit('update:modelValue', val)

  // keyword 模式 500ms 防抖自动搜索
  if (props.mode === 'keyword' && val.length >= 2) {
    clearTimeout(debounceTimer)
    debounceTimer = setTimeout(() => emit('search', val, props.mode), 500)
  }
}

function onKeydown(e) {
  // Ctrl+K 聚焦已在全局监听处理
  if (e.key === 'Escape') {
    inputEl.value?.blur()
    menuOpen.value = false
  }
}

function toggleMenu() {
  menuOpen.value = !menuOpen.value
}

function selectMode(m) {
  emit('update:mode', m)
  menuOpen.value = false
  // 切换模式后，若关键词足够则触发搜索
  if (props.modelValue.length >= 2) {
    emit('search', props.modelValue, m)
  }
}

// 全局 Ctrl+K 聚焦搜索
function onGlobalKeydown(e) {
  if ((e.ctrlKey || e.metaKey) && e.key === 'k') {
    e.preventDefault()
    inputEl.value?.focus()
  }
}

onMounted(() => document.addEventListener('keydown', onGlobalKeydown))
onUnmounted(() => document.removeEventListener('keydown', onGlobalKeydown))

defineExpose({ focus: () => inputEl.value?.focus() })
</script>

<style scoped>
.search-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 12px 16px;
  background: #fff;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  margin-bottom: 16px;
}
.search-input-wrap {
  flex: 1;
  display: flex;
  align-items: center;
  gap: 8px;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  padding: 8px 12px;
  transition: border-color .15s, box-shadow .15s;
}
.search-input-wrap:focus-within {
  border-color: #b45309;
  box-shadow: 0 0 0 3px rgba(180,83,9,.12);
}
.search-icon {
  width: 16px;
  height: 16px;
  color: #94a3b8;
  flex-shrink: 0;
}
.search-input {
  flex: 1;
  border: none;
  outline: none;
  background: transparent;
  font-size: 13px;
  color: #1e293b;
}
.search-input::placeholder {
  color: #94a3b8;
}
.clear-btn {
  flex-shrink: 0;
  width: 22px;
  height: 22px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 50%;
  color: #94a3b8;
  cursor: pointer;
  border: none;
  background: transparent;
}
.clear-btn:hover {
  background: #e2e8f0;
  color: #64748b;
}

/* 模式切换 */
.mode-dropdown-wrap {
  position: relative;
}
.mode-btn {
  display: flex;
  align-items: center;
  padding: 8px 12px;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  font-size: 12px;
  color: #64748b;
  cursor: pointer;
  white-space: nowrap;
}
.mode-btn:hover { background: #f1f5f9; }
.mode-menu {
  position: absolute;
  top: calc(100% + 4px);
  right: 0;
  background: #fff;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  box-shadow: 0 10px 30px rgba(0,0,0,.12);
  padding: 4px;
  z-index: 50;
  min-width: 220px;
}
.mode-menu-item {
  padding: 10px 12px;
  border-radius: 6px;
  cursor: pointer;
  position: relative;
}
.mode-menu-item:hover:not(.disabled) { background: #f8fafc; }
.mode-menu-item.active { background: #fef3c7; }
.mode-menu-item.disabled { opacity: .5; cursor: not-allowed; }
.mode-menu-label { font-size: 13px; font-weight: 600; color: #1e293b; }
.mode-menu-desc { font-size: 11px; color: #94a3b8; margin-top: 2px; }
.mode-menu-badge {
  position: absolute;
  top: 10px;
  right: 10px;
  font-size: 10px;
  background: #e2e8f0;
  color: #94a3b8;
  padding: 1px 6px;
  border-radius: 4px;
}

/* 搜索按钮 */
.search-btn {
  padding: 8px 18px;
  background: #b45309;
  color: #fff;
  border: none;
  border-radius: 8px;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  white-space: nowrap;
  transition: background .15s;
}
.search-btn:hover:not(:disabled) { background: #92400e; }
.search-btn:disabled { opacity: .5; cursor: not-allowed; }

.spinner {
  display: inline-block;
  width: 14px;
  height: 14px;
  border: 2px solid rgba(255,255,255,.3);
  border-top-color: #fff;
  border-radius: 50%;
  animation: spin .6s linear infinite;
}
@keyframes spin { to { transform: rotate(360deg); } }
</style>
