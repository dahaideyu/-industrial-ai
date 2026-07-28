<template>
  <div v-if="error" class="p-4 text-center text-sm text-red-500">
    加载 PDF 失败: {{ error }}
    <button @click="reset" class="ml-2 text-amber-500 hover:underline">重试</button>
  </div>
  <slot v-else />
</template>

<script setup>
import { ref, onErrorCaptured } from 'vue'

const error = ref(null)

onErrorCaptured((err) => {
  error.value = err.message || '未知错误'
  return false
})

function reset() {
  error.value = null
}
</script>
