<template>
  <div v-if="steps.length > 0" class="step-progress">
    <div
      v-for="(step, i) in steps"
      :key="step.id"
      class="step-item"
      :class="`step-${step.status}`"
    >
      <span class="step-icon">
        <span v-if="step.status === 'running'">&#9679;</span>
        <span v-else-if="step.status === 'done'">&#10003;</span>
        <span v-else>&#10007;</span>
      </span>
      <span class="step-label">{{ step.description }}</span>
      <span v-if="i < steps.length - 1" class="step-connector"></span>
    </div>
  </div>
</template>

<script setup>
defineProps({
  steps: { type: Array, default: () => [] },
})
</script>

<style scoped>
.step-progress {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  margin: 8px 0;
  padding: 8px;
  background: #fff;
  border-radius: 6px;
}
.step-item {
  display: flex;
  align-items: center;
  font-size: 12px;
  color: #909399;
}
.step-running { color: #409eff; font-weight: 600; }
.step-done { color: #67c23a; }
.step-error { color: #f56c6c; }
.step-icon { margin-right: 4px; }
.step-connector {
  display: inline-block;
  width: 20px;
  height: 1px;
  background: #dcdfe6;
  margin: 0 6px;
}
</style>
