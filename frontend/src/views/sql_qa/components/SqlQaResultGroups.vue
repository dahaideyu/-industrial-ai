<template>
  <div v-if="groups && groups.length > 0" class="bg-white rounded-lg border border-gray-100 overflow-hidden">
    <!-- Tab 标签栏 -->
    <div class="flex border-b border-gray-200 bg-gray-50">
      <button
        v-for="(group, i) in groups"
        :key="i"
        @click="activeTab = i"
        :class="[
          'px-4 py-2 text-xs font-medium border-b-2 transition-colors',
          activeTab === i
            ? 'border-amber-400 text-amber-700 bg-white'
            : 'border-transparent text-gray-500 hover:text-gray-700 hover:bg-gray-100'
        ]"
      >
        数据集 {{ i + 1 }}
        <span class="ml-1 text-[10px] px-1.5 py-0.5 rounded-full" :class="activeTab === i ? 'bg-amber-100 text-amber-600' : 'bg-gray-200 text-gray-500'">
          {{ group.results?.length || 0 }}
        </span>
      </button>
    </div>

    <!-- 当前 Tab 的结果表 -->
    <div class="p-1">
      <SqlQaResultTable
        v-if="currentGroup"
        :data="currentGroup.results || []"
        :sql="currentGroup.sql || ''"
      />
      <div v-else class="text-center text-xs text-gray-400 py-8">无查询结果</div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'
import SqlQaResultTable from './SqlQaResultTable.vue'

const props = defineProps({
  groups: { type: Array, default: () => [] },
})

const activeTab = ref(0)

const currentGroup = computed(() => props.groups[activeTab.value] || null)
</script>
