<template>
  <div v-if="text" class="thinking-block">
    <details open>
      <summary class="thinking-header">思考过程</summary>
      <div class="thinking-content">{{ text }}</div>
    </details>
  </div>
</template>

<script setup>
defineProps({
  text: { type: String, default: '' },
})
</script>

<style scoped>
.thinking-block {
  margin: 8px 0;
  padding: 8px 12px;
  background: #f5f7fa;
  border-radius: 8px;
  border-left: 3px solid #409eff;
}
.thinking-header {
  font-size: 13px;
  color: #909399;
  cursor: pointer;
  user-select: none;
}
.thinking-content {
  margin-top: 6px;
  font-size: 13px;
  color: #606266;
  white-space: pre-wrap;
  word-break: break-word;
}
</style>
