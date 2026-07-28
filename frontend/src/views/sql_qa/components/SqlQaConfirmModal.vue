<template>
  <div v-if="showConfirm" class="fixed inset-0 z-50 flex items-center justify-center bg-black/40" @click.self="onCancel">
    <div class="bg-white rounded-xl shadow-xl p-6 w-full max-w-md m-4">
      <h3 class="text-lg font-semibold text-gray-800 mb-2">{{ confirmOptions.title }}</h3>
      <p class="text-sm text-gray-500 mb-6">{{ confirmOptions.message }}</p>
      <div class="flex justify-end gap-3">
        <button @click="onCancel" class="px-4 py-2 text-sm rounded-lg border border-gray-200 text-gray-600 hover:bg-gray-50 transition-colors">
          取消
        </button>
        <button
          @click="onConfirm"
          :class="confirmOptions.danger ? 'bg-red-500 hover:bg-red-600 text-white' : 'bg-amber-400 hover:bg-amber-300 text-gray-900'"
          class="px-4 py-2 text-sm rounded-lg font-medium transition-colors"
        >
          确认
        </button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { useSqlQaConfirm } from '../../../composables/sql_qa/useSqlQaConfirm.js'

const { showConfirm, confirmOptions, onConfirm, onCancel } = useSqlQaConfirm()
</script>
