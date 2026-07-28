<template>
  <div v-if="request" class="clarify-inline">
    <div class="clarify-message">{{ request.message }}</div>
    <div v-if="request.suggestions.length > 0" class="clarify-suggestions">
      <span class="suggestions-label">已接入数据:</span>
      <span v-for="s in request.suggestions" :key="s" class="suggestion-chip">{{ s }}</span>
    </div>
    <div class="clarify-input-row">
      <input
        v-model="userInput"
        type="text"
        class="clarify-input"
        placeholder="输入补充信息..."
        @keyup.enter="onSubmit"
      />
      <button class="clarify-btn" @click="onSubmit">发送</button>
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'

const props = defineProps({
  request: { type: Object, default: null },
})
const emit = defineEmits(['respond'])
const userInput = ref('')

function onSubmit() {
  if (userInput.value.trim()) {
    emit('respond', userInput.value.trim())
    userInput.value = ''
  }
}
</script>

<style scoped>
.clarify-inline {
  margin: 12px 0;
  padding: 12px;
  background: #ecf5ff;
  border-radius: 8px;
  border: 1px solid #d9ecff;
}
.clarify-message {
  font-size: 14px;
  color: #303133;
  margin-bottom: 8px;
}
.clarify-suggestions { margin-bottom: 8px; }
.suggestions-label { font-size: 12px; color: #909399; margin-right: 6px; }
.suggestion-chip {
  display: inline-block;
  margin: 2px 4px;
  padding: 2px 8px;
  font-size: 12px;
  background: #fff;
  border: 1px solid #b3d8ff;
  border-radius: 12px;
  color: #409eff;
}
.clarify-input-row { display: flex; gap: 8px; }
.clarify-input { flex: 1; padding: 6px 10px; border: 1px solid #dcdfe6; border-radius: 4px; font-size: 13px; }
.clarify-btn { padding: 6px 16px; background: #409eff; color: #fff; border: none; border-radius: 4px; cursor: pointer; font-size: 13px; }
</style>
