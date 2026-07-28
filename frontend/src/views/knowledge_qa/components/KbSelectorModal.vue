<template>
  <div
    v-if="visible"
    class="fixed inset-0 bg-black/40 flex items-center justify-center z-50"
    @click.self="$emit('close')"
    data-test="kbqa-selector-modal"
  >
    <div class="bg-white rounded-xl p-6 w-[560px] max-w-[90vw] max-h-[80vh] overflow-y-auto shadow-2xl">
      <h3 class="text-lg font-semibold text-slate-900 mb-2">选择知识库</h3>
      <p class="text-[12px] text-slate-500 mb-4">
        💡 仅显示<strong>已上传文档</strong>的知识库。空知识库不出现。
      </p>

      <input
        v-model="search"
        type="text"
        placeholder="🔍 搜索知识库..."
        class="w-full px-4 py-2.5 text-[14px] border border-slate-200 rounded-lg mb-5 focus:outline-none focus:border-amber-400"
      />

      <!-- 分组：合规性 -->
      <div class="text-[12px] font-bold text-slate-600 pb-1.5 mb-2 border-b border-slate-200 uppercase tracking-wide">🛡️ 合规性知识库</div>
      <label
        v-for="kb in filteredKbs('compliance').filter(x => x && x.id)"
        :key="kb.id"
        class="flex items-center gap-2 p-2.5 mb-1.5 bg-white border border-slate-200 rounded-md text-[13px] cursor-pointer hover:bg-slate-50"
      >
        <input type="checkbox" :checked="isSelected(kb.id)" @change="toggle(kb.id)" class="w-4 h-4">
        <span>🛡️</span>
        <div class="flex-1">
          <div class="font-semibold text-slate-900">{{ kb.name }}</div>
          <div class="text-[11px] text-slate-500">安环合规文档与证书</div>
        </div>
      </label>

      <!-- 分组：设备说明 -->
      <div class="text-[12px] font-bold text-slate-600 pb-1.5 mb-2 mt-4 border-b border-slate-200 uppercase tracking-wide">📐 设备说明知识库（按设备类型）</div>
      <label
        v-for="kb in filteredKbs('device_doc').filter(x => x && x.id)"
        :key="kb.id"
        class="flex items-center gap-2 p-2.5 mb-1.5 bg-white border border-slate-200 rounded-md text-[13px] cursor-pointer hover:bg-slate-50"
      >
        <input type="checkbox" :checked="isSelected(kb.id)" @change="toggle(kb.id)" class="w-4 h-4">
        <span>🔧</span>
        <div class="flex-1">
          <div class="font-semibold text-slate-900">{{ kb.name }}</div>
          <div class="text-[11px] text-slate-500">图纸/手册/参数/备件清单</div>
        </div>
      </label>

      <!-- 分组：设备SOP -->
      <div class="text-[12px] font-bold text-slate-600 pb-1.5 mb-2 mt-4 border-b border-slate-200 uppercase tracking-wide">📋 设备SOP知识库（按设备类型）</div>
      <label
        v-for="kb in filteredKbs('sop_doc').filter(x => x && x.id)"
        :key="kb.id"
        class="flex items-center gap-2 p-2.5 mb-1.5 bg-white border border-slate-200 rounded-md text-[13px] cursor-pointer hover:bg-slate-50"
      >
        <input type="checkbox" :checked="isSelected(kb.id)" @change="toggle(kb.id)" class="w-4 h-4">
        <span>📋</span>
        <div class="flex-1">
          <div class="font-semibold text-slate-900">{{ kb.name }}</div>
          <div class="text-[11px] text-slate-500">操作/点检/保养/异常/防错</div>
        </div>
      </label>

      <!-- 分组：自定义 -->
      <div class="text-[12px] font-bold text-slate-600 pb-1.5 mb-2 mt-4 border-b border-slate-200 uppercase tracking-wide">📌 自定义知识库</div>
      <label
        v-for="kb in filteredKbs('custom').filter(x => x && x.id)"
        :key="kb.id"
        class="flex items-center gap-2 p-2.5 mb-1.5 bg-white border border-slate-200 rounded-md text-[13px] cursor-pointer hover:bg-slate-50"
      >
        <input type="checkbox" :checked="isSelected(kb.id)" @change="toggle(kb.id)" class="w-4 h-4">
        <span>📌</span>
        <div class="flex-1">
          <div class="font-semibold text-slate-900">{{ kb.name }}</div>
          <div class="text-[11px] text-slate-500">自定义类别</div>
        </div>
      </label>

      <!-- 空状态提示 -->
      <div
        v-if="(props.kbs || []).filter(k => k && k.id && (k.document_count || 0) > 0).length === 0"
        class="mt-8 text-center py-8 px-4 bg-amber-50 rounded-lg border border-amber-200"
      >
        <div class="text-[32px] mb-3">📚</div>
        <div class="text-[15px] font-semibold text-slate-700 mb-2">
          暂无可用知识库
        </div>
        <div class="text-[13px] text-slate-600 leading-relaxed">
          所有知识库都还没有上传文档。<br>
          请到「<strong>知识库管理</strong>」页面给至少一个知识库上传文档后，<br>
          再回到这里手动选择。
        </div>
      </div>

      <div class="flex justify-between items-center mt-5 pt-4 border-t border-slate-200">
        <span class="text-[12px] text-slate-600">已选 <strong class="text-amber-600">{{ selectedIds.length }}</strong> 个知识库</span>
        <div class="flex gap-2">
          <button
            @click="$emit('close')"
            class="px-5 py-2 text-[13px] border border-slate-200 rounded-md hover:bg-slate-50"
          >
            取消
          </button>
          <button
            @click="confirm"
            class="px-5 py-2 text-[13px] font-semibold bg-amber-500 text-white rounded-md hover:bg-amber-600"
          >
            确认选择
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, watch } from 'vue'

const props = defineProps({
  visible: Boolean,
  kbs: Array,
  selected: Array,
})
const emit = defineEmits(['close', 'update'])

const search = ref('')
const selectedIds = ref([...(props.selected || [])])

watch(() => props.selected, (newVal) => {
  selectedIds.value = [...(newVal || [])]
})

watch(() => props.visible, (newVal) => {
  if (newVal) {
    // 弹窗打开时，从 props 同步最新选择
    selectedIds.value = [...(props.selected || [])]
  }
})

function isSelected(id) {
  return selectedIds.value.includes(id)
}

function toggle(id) {
  const idx = selectedIds.value.indexOf(id)
  if (idx >= 0) selectedIds.value.splice(idx, 1)
  else selectedIds.value.push(id)
}

function filteredKbs(type) {
  // 兼容历史遗留的命名不一致：device_doc vs device、sop_doc vs sop
  const aliases = {
    'compliance': ['compliance'],
    'device_doc': ['device_doc', 'device'],
    'sop_doc': ['sop_doc', 'sop', 'device'],  // 历史数据：sop 类也可能用 device
    'custom': ['custom'],
  }
  const allowedTypes = aliases[type] || [type]
  return (props.kbs || []).filter(
    (k) => k && k.id
      && allowedTypes.includes(k.kb_type || 'custom')
      && (k.document_count === undefined
          ? false  // 字段缺失（可能是缓存了旧API响应）→ 隐藏
          : k.document_count > 0)
      && (!search.value || (k.name || '').includes(search.value))
  )
}

function confirm() {
  emit('update', [...selectedIds.value])
  emit('close')
}
</script>
