<template>
  <section class="min-h-screen p-6 lg:p-8">
    <div class="mx-auto max-w-[1500px]">
      <div class="rounded-lg border border-slate-200 bg-white p-6 shadow-sm">
        <p class="text-xs font-bold uppercase tracking-[0.18em] text-amber-700">AI Maintenance Reports</p>
        <h1 class="mt-2 font-headline text-2xl font-semibold text-slate-950">维护报告</h1>
        <p class="mt-2 max-w-3xl text-sm leading-6 text-slate-500">
          这里用于承接预测性维护报告列表、批量生成和调度结果。当前页面先提供 AI 化入口，后续可接入报告列表接口。
        </p>
      </div>

      <div class="mt-6 grid gap-6 lg:grid-cols-3">
        <router-link
          v-for="item in actions"
          :key="item.path"
          :to="item.path"
          class="rounded-lg border border-slate-200 bg-white p-5 shadow-sm transition-colors hover:border-amber-400 hover:bg-amber-50/40"
        >
          <div class="text-xs font-bold uppercase tracking-[0.14em] text-slate-400">{{ item.kicker }}</div>
          <h2 class="mt-3 font-headline text-lg font-semibold text-slate-950">{{ item.title }}</h2>
          <p class="mt-2 text-sm leading-6 text-slate-500">{{ item.desc }}</p>
        </router-link>
      </div>
    </div>
  </section>
</template>

<script setup>
const actions = [
  { kicker: 'Generate', title: '生成维护报告', desc: '进入 AI 报告工作室，生成设备维护日报、周报或月报。', path: '/report' },
  { kicker: 'Diagnose', title: '先做设备诊断', desc: '运行健康评估和故障预测，作为维护报告证据。', path: '/analysis?module=health' },
  { kicker: 'Risk', title: '查看风险洞察', desc: '从报警分析中提取优先处理设备和风险原因。', path: '/alarm-analysis' },
]
</script>
