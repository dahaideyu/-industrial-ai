<template>
  <div class="my-3 p-4 bg-white rounded-xl shadow-sm border border-gray-100 text-center">
    <div class="text-2xl font-bold text-amber-700">{{ formattedValue }}</div>
    <div v-if="tags && tags.length > 0" class="mt-1 flex flex-wrap justify-center gap-1">
      <span v-for="tag in tags.slice(0, 20)" :key="tag" class="text-xs px-2 py-0.5 rounded bg-amber-100 text-amber-700">
        {{ tag }}
      </span>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  value: { type: [Number, String], default: null },
  tags: { type: Array, default: () => [] },
})

const formattedValue = computed(() => {
  const v = props.value
  if (v == null) return ''
  if (typeof v === 'number') return v.toLocaleString()
  return v
})
</script>
