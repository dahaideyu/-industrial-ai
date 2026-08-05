<template>
  <div v-if="visible" id="analysis-history-section" class="bg-white rounded-xl border border-gray-100 shadow-sm p-5">
    <div class="flex items-center justify-between mb-3">
      <h2 class="font-headline text-base font-semibold text-gray-900">历史 AI 分析</h2>
      <span class="text-xs text-gray-400">{{ loading ? '加载中...' : `共 ${items.length} 条` }}</span>
    </div>
    <div v-if="!loading && items.length === 0" class="text-xs text-gray-400">
      暂无历史分析记录，点击"AI 分析"生成第一条。
    </div>
    <ul v-else class="divide-y divide-gray-100">
      <li v-for="item in items" :key="item.id"
        class="py-2.5 flex items-center justify-between gap-3 cursor-pointer hover:bg-gray-50 rounded-lg px-2"
        @click="$emit('select', item)"
      >
        <div class="min-w-0">
          <div class="text-sm text-gray-800 truncate">{{ item.start_time }} ~ {{ item.end_time }}</div>
          <div class="text-xs text-gray-400">{{ item.created_at }}{{ item.running_only ? ' · 仅运行时段' : '' }}</div>
        </div>
        <span class="text-xs text-violet-500 shrink-0">查看 →</span>
      </li>
    </ul>
  </div>
</template>

<script setup>
defineProps({
  visible: { type: Boolean, default: false },
  loading: { type: Boolean, default: false },
  items: { type: Array, default: () => [] },
})

defineEmits(['select'])
</script>
