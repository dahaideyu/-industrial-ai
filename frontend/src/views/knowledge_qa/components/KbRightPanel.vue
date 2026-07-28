<template>
  <div class="flex flex-col h-full bg-slate-50/50 border-l border-slate-200 overflow-y-auto text-[14px]" data-test="kbqa-right-panel">
    <!-- 🔮 AI 自动匹配的知识库（针对上一个问题，只读） -->
    <div class="p-4 border-b border-slate-200">
      <div class="text-[15px] font-semibold text-slate-900 mb-2.5">
        🔮 AI 匹配的知识库
        <span class="text-[12px] text-slate-400 font-normal ml-1">（上个问题）</span>
      </div>
      <div class="flex flex-col gap-2">
        <div
          v-for="kb in matchedKbs"
          :key="kb.id"
          class="flex items-center gap-2 px-3 py-2 bg-emerald-50 border border-emerald-200 rounded-md text-[13px]"
        >
          <span>{{ kb.icon }}</span>
          <span class="font-medium text-slate-900 truncate flex-1">{{ kb.name }}</span>
          <span class="text-[11px] text-emerald-600 bg-emerald-100 px-2 py-0.5 rounded font-medium">AI</span>
        </div>
        <div
          v-if="matchedKbs.length === 0"
          class="text-[12px] text-slate-400 px-2 py-1"
        >
          暂无匹配
        </div>
      </div>
    </div>

    <!-- 👆 手动选择知识库（为下一个问题预设） -->
    <div class="p-4 border-b border-slate-200">
      <div class="text-[15px] font-semibold text-slate-900 mb-2.5">
        👆 手动选择的知识库
        <span class="text-[12px] text-slate-400 font-normal ml-1">（下个问题）</span>
      </div>
      <div class="flex flex-col gap-2 mb-3">
        <div
          v-for="kbId in manualKbIds"
          :key="kbId"
          class="flex items-center gap-2 px-3 py-2 bg-white border border-slate-200 rounded-md text-[13px]"
        >
          <span>{{ getKbIcon(kbId) }}</span>
          <span class="font-medium text-slate-900 truncate flex-1">{{ getKbName(kbId) }}</span>
          <span class="text-[11px] text-slate-600 bg-slate-100 px-2 py-0.5 rounded font-medium">手动</span>
          <button
            @click="$emit('remove-manual', kbId)"
            class="text-slate-400 hover:text-red-500 text-base leading-none"
          >×</button>
        </div>
        <div
          v-if="manualKbIds.length === 0"
          class="text-[12px] text-slate-400 px-2 py-1"
        >
          未选择（将使用 AI 自动判断）
        </div>
      </div>
      <button
        @click="$emit('open-selector')"
        class="w-full px-3 py-2 text-[14px] text-slate-600 border border-dashed border-slate-300 rounded-md hover:border-amber-400 hover:text-amber-600 bg-white font-medium"
      >
        + 添加/修改知识库
      </button>
    </div>

    <!-- 提示 -->
    <div class="p-4 text-[12px] text-slate-600 leading-relaxed">
      💡 手动选择的 KB 会与 AI 自动判断合并，作为<strong>下个问题</strong>的检索范围。
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  allKbs: Array,
  matchedKbIds: Array,
  manualKbIds: Array,
})
defineEmits(['open-selector', 'remove-manual'])

function getKbName(id) {
  return props.allKbs?.find((k) => k.id === id)?.name || id
}

function getKbIcon(id) {
  const kb = props.allKbs?.find((k) => k.id === id)
  const t = kb?.kb_type || 'custom'
  if (t === 'compliance') return '🛡️'
  if (t === 'device_doc') return '🔧'
  if (t === 'sop_doc') return '📋'
  return '📌'
}

const matchedKbs = computed(() =>
  (props.matchedKbIds || [])
    .map((id) => props.allKbs?.find((k) => k.id === id))
    .filter(Boolean)
    .map((kb) => ({ ...kb, icon: getKbIcon(kb.id) }))
)
</script>
