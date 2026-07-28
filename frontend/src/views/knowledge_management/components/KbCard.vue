<template>
  <div class="kb-card" :class="{ warning: warning, disabled: disabled }" :style="{ borderLeftColor: color, borderLeftWidth: '3px', '--card-color': color }" @click="$emit('click')">
    <div v-if="disabled" class="kb-card-mask"></div>
    <div class="flex items-start gap-3">
      <div class="flex-1 min-w-0">
        <div class="card-icon" :style="{ background: iconBg, color: color }">{{ icon }}</div>
        <div class="card-name">{{ name }}</div>
        <div class="card-sub">{{ sub }}</div>
        <div class="card-meta">
          <span v-for="(m, i) in meta" :key="i" v-html="m"></span>
        </div>
      </div>
      <!-- 评分：右侧顶部紧贴滑块下方（垂直起始位置对齐滑块底部） -->
      <div v-if="score !== undefined" class="text-center flex-shrink-0 pr-1" style="align-self:flex-start;margin-top:50px">
        <div class="text-[24px] font-bold" :style="{ color: color }">{{ score }}</div>
        <div class="text-[10px] text-slate-400">评分</div>
      </div>
    </div>
    <div class="mt-auto pt-2.5">
      <div class="flex justify-between items-center text-[11px] text-slate-500 mb-0.5">
        <span>完成率</span><span>{{ progress }}{{ typeof progress === 'number' ? '%' : '' }}</span>
      </div>
      <div class="progress-bar">
        <div class="progress-fill" :class="fillClass" :style="{ width: (typeof progress === 'number' ? progress : 0) + '%' }"></div>
      </div>
    </div>
  </div>
</template>

<script setup>
defineProps({
  name: { type: String, required: true },
  sub: { type: String, default: '' },
  icon: { type: String, default: '📋' },
  iconBg: { type: String, default: '#f8fafc' },
  color: { type: String, default: '#b45309' },
  meta: { type: Array, default: () => [] },
  score: { type: [String, Number], default: undefined },
  progress: { type: [String, Number], default: 0 },
  warning: { type: Boolean, default: false },
  fillClass: { type: String, default: 'amber' },
  disabled: { type: Boolean, default: false },
})
defineEmits(['click'])
</script>

<style scoped>
.kb-card{background:#fff;border-radius:10px;padding:16px;border:1px solid #e2e8f0;cursor:pointer;transition:all .15s;display:flex;flex-direction:column;min-height:160px}
.kb-card:hover{border-color:var(--card-color, #b45309);box-shadow:0 2px 12px rgba(0,0,0,.06)}
.kb-card.warning{border-color:#fecaca}
.kb-card.disabled{cursor:default;border-color:#cbd5e1;background:#f8fafc;color:#94a3b8;border-left-color:#cbd5e1 !important}
.kb-card.disabled:hover{border-color:#cbd5e1;box-shadow:none}
.kb-card.disabled .card-name,
.kb-card.disabled .card-sub,
.kb-card.disabled .card-meta{color:#94a3b8}
.kb-card.disabled .card-icon{background:#f1f5f9;color:#94a3b8}
.kb-card.disabled .progress-fill{background:#cbd5e1!important}
.kb-card.disabled .score-circle{background:#f1f5f9!important;color:#94a3b8!important}
.kb-card-mask{position:absolute;inset:0;background:rgba(148,163,184,0.25);border-radius:10px;pointer-events:none}
.kb-card{position:relative}
.card-icon{width:40px;height:40px;border-radius:8px;display:flex;align-items:center;justify-content:center;font-size:18px;margin-bottom:10px}
.card-name{font-weight:600;font-size:15px;color:#0f172a;margin-bottom:2px}
.card-sub{font-size:11px;color:#94a3b8;margin-bottom:10px}
.card-meta{display:flex;gap:16px;font-size:12px;color:#64748b;margin-bottom:10px;flex-wrap:wrap}
.card-meta strong{color:#0f172a}
.progress-bar{height:5px;background:#e2e8f0;border-radius:3px}
.progress-fill{height:100%;border-radius:3px}
.score-mini{display:inline-flex;align-items:baseline;gap:1px}
.kb-card.disabled .score-mini{color:#94a3b8!important}
.progress-fill.amber{background:#b45309}.progress-fill.green{background:#22c55e}
.progress-fill.warn{background:#f59e0b}.progress-fill.red{background:#ef4444}
.progress-fill.blue{background:#3b82f6}.progress-fill.purple{background:#7c3aed}
</style>
