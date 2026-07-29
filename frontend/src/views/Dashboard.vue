<template>
  <section class="min-h-screen">
    <div class="border-b border-slate-200 bg-white/80 px-6 py-5 backdrop-blur lg:px-8">
      <div class="mx-auto flex max-w-[1500px] flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
        <div>
          <p class="text-xs font-bold uppercase tracking-[0.18em] text-amber-700">AI Operations Brain</p>
          <h1 class="mt-2 font-headline text-2xl font-semibold text-slate-950">AI 工作台</h1>
        </div>
        <div class="flex flex-wrap items-center gap-2">
          <span class="rounded-md border border-emerald-200 bg-emerald-50 px-3 py-1.5 text-xs font-bold text-emerald-700">
            系统健康 {{ healthScore }}/100
          </span>
          <button
            @click="loadData"
            class="rounded-md border border-slate-300 bg-white px-4 py-2 text-sm font-bold text-slate-700 transition-colors hover:border-amber-500 hover:text-amber-700"
          >
            刷新洞察
          </button>
        </div>
      </div>
    </div>

    <div class="mx-auto max-w-[1500px] p-6 lg:p-8">
      <div class="grid gap-6 xl:grid-cols-[1.35fr_0.65fr]">
        <div class="relative overflow-hidden rounded-lg border border-slate-200 bg-slate-950 p-6 text-white shadow-sm">
          <div class="pointer-events-none absolute inset-y-0 right-0 hidden w-[44%] lg:block">
            <div class="brain-grid"></div>
            <div class="brain-core">
              <span class="brain-node node-a"></span>
              <span class="brain-node node-b"></span>
              <span class="brain-node node-c"></span>
              <span class="brain-node node-d"></span>
              <span class="brain-line line-a"></span>
              <span class="brain-line line-b"></span>
              <span class="brain-line line-c"></span>
              <span class="brain-line line-d"></span>
            </div>
          </div>
          <div class="relative flex flex-col gap-6 lg:flex-row lg:items-start lg:justify-between">
            <div class="max-w-3xl">
              <div class="mb-4 inline-flex items-center gap-2 rounded-md border border-amber-300/30 bg-amber-300/10 px-3 py-1 text-xs font-bold text-amber-100">
                <span class="h-2 w-2 rounded-full bg-amber-300"></span>
                过去 24 小时 AI 摘要
              </div>
              <h2 class="font-headline text-3xl font-semibold leading-tight">
                {{ executiveSummary }}
              </h2>
              <p class="mt-4 max-w-2xl text-sm leading-7 text-slate-300">
                当前优先级来自健康分、报警活跃度和设备在线率的综合判断。建议先处理高置信度风险，再追溯参数分析。
              </p>
            </div>
            <div class="grid min-w-[260px] grid-cols-3 gap-3 lg:grid-cols-1">
              <div v-for="metric in heroMetrics" :key="metric.label" class="rounded-md border border-white/10 bg-white/5 p-4">
                <div class="text-xs font-semibold text-slate-400">{{ metric.label }}</div>
                <div class="mt-2 font-headline text-2xl font-bold">{{ metric.value }}</div>
                <div class="mt-1 text-xs text-slate-400">{{ metric.hint }}</div>
              </div>
            </div>
          </div>
        </div>

        <div class="rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
          <div class="flex items-center justify-between">
            <h2 class="font-headline text-lg font-semibold text-slate-950">AI 指令入口</h2>
            <span class="rounded-md bg-amber-50 px-2.5 py-1 text-xs font-bold text-amber-700">Beta</span>
          </div>
          <div class="mt-4 rounded-md border border-slate-200 bg-slate-50 p-3">
            <textarea
              v-model="command"
              rows="4"
              class="w-full resize-none bg-transparent text-sm leading-6 text-slate-800 outline-none placeholder:text-slate-400"
              placeholder="例如：分析今天报警最多的设备，并生成维护建议"
            ></textarea>
          </div>
          <div class="mt-3 grid grid-cols-2 gap-2">
            <button
              v-for="preset in commandPresets"
              :key="preset"
              @click="command = preset"
              class="rounded-md border border-slate-200 bg-white px-3 py-2 text-left text-xs font-semibold text-slate-600 transition-colors hover:border-amber-400 hover:text-amber-700"
            >
              {{ preset }}
            </button>
          </div>
          <button
            @click="dispatchCommand"
            class="mt-4 w-full rounded-md bg-slate-950 px-4 py-3 text-sm font-bold text-white transition-colors hover:bg-amber-700"
          >
            进入对应 AI 工作流
          </button>
        </div>
      </div>

      <div class="mt-6 grid gap-6 xl:grid-cols-[1fr_360px]">
        <div class="rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
          <div class="mb-5 flex items-center justify-between">
            <div>
              <h2 class="font-headline text-lg font-semibold text-slate-950">AI 洞察队列</h2>
              <p class="mt-1 text-sm text-slate-500">按风险优先级排列，可直接进入分析或报告生成。</p>
            </div>
            <span class="text-xs font-bold text-slate-400">{{ insights.length }} 条建议</span>
          </div>

          <div class="space-y-3">
            <article
              v-for="item in insights"
              :key="item.title"
              class="rounded-md border border-slate-200 bg-white p-4 transition-colors hover:border-amber-300 hover:bg-amber-50/30"
            >
              <div class="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
                <div>
                  <div class="mb-2 flex flex-wrap items-center gap-2">
                    <span :class="['rounded-md px-2 py-1 text-xs font-bold', riskClass(item.level)]">{{ item.level }}</span>
                    <span class="text-xs font-semibold text-slate-500">置信度 {{ item.confidence }}%</span>
                  </div>
                  <h3 class="font-headline text-base font-semibold text-slate-950">{{ item.title }}</h3>
                  <p class="mt-2 text-sm leading-6 text-slate-600">{{ item.reason }}</p>
                  <p class="mt-3 text-sm font-semibold text-slate-800">建议：{{ item.action }}</p>
                </div>
                <div class="flex shrink-0 gap-2">
                  <router-link :to="item.primaryPath" class="rounded-md bg-slate-950 px-3 py-2 text-xs font-bold text-white hover:bg-amber-700">
                    {{ item.primaryLabel || '查看分析' }}
                  </router-link>
                  <router-link
                    v-if="item.secondaryPath"
                    :to="item.secondaryPath"
                    class="rounded-md border border-slate-300 px-3 py-2 text-xs font-bold text-slate-700 hover:border-amber-500 hover:text-amber-700"
                  >
                    {{ item.secondaryLabel || '次操作' }}
                  </router-link>
                  <router-link
                    v-else
                    to="/report"
                    class="rounded-md border border-slate-300 px-3 py-2 text-xs font-bold text-slate-700 hover:border-amber-500 hover:text-amber-700"
                  >
                    生成报告
                  </router-link>
                </div>
              </div>
            </article>
          </div>
        </div>

        <aside class="space-y-6">
          <div class="rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
            <h2 class="font-headline text-lg font-semibold text-slate-950">证据概览</h2>
            <div class="mt-4 space-y-4">
              <div v-for="evidence in evidenceItems" :key="evidence.label">
                <div class="mb-1 flex justify-between text-sm">
                  <span class="font-semibold text-slate-700">{{ evidence.label }}</span>
                  <span class="text-slate-500">{{ evidence.value }}</span>
                </div>
                <div class="h-2 overflow-hidden rounded-full bg-slate-100">
                  <div class="h-full rounded-full bg-amber-500" :style="{ width: evidence.percent + '%' }"></div>
                </div>
              </div>
            </div>
          </div>

          <div class="rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
            <h2 class="font-headline text-lg font-semibold text-slate-950">常用 AI 动作</h2>
            <div class="mt-4 space-y-2">
              <router-link
                v-for="action in quickActions"
                :key="action.path"
                :to="action.path"
                class="block rounded-md border border-slate-200 px-4 py-3 transition-colors hover:border-amber-400 hover:bg-amber-50/50"
              >
                <div class="text-sm font-bold text-slate-900">{{ action.title }}</div>
                <div class="mt-1 text-xs leading-5 text-slate-500">{{ action.desc }}</div>
              </router-link>
            </div>
          </div>
        </aside>
      </div>

      <div v-if="loading" class="mt-6 rounded-md border border-amber-200 bg-amber-50 px-4 py-3 text-sm font-semibold text-amber-800">
        正在刷新 AI 洞察...
      </div>
    </div>
  </section>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { runDeviceAnalysis } from '../api/client.js'
import { getKnowledgeOverview } from '../api/knowledgeManagementClient.js'

const router = useRouter()

const loading = ref(false)
const healthScore = ref(98)
const alarmCount = ref(3)
const criticalAlarms = ref(1)
const warningAlarms = ref(2)
const onlineRate = ref(96)
const onlineDevices = ref(24)
const totalDevices = ref(25)

const knowledgeInsight = ref({
  level: '稳定',
  confidence: null,
  reason: '正在加载知识库健康度数据...',
  title: '知识库健康度待提升',
})
const command = ref('')

const executiveSummary = computed(() => {
  if (criticalAlarms.value > 0) {
    return `AI 识别到 ${criticalAlarms.value} 个高优先级风险，建议先处理活跃报警设备并生成维护建议。`
  }
  if (healthScore.value < 90) {
    return 'AI 发现设备健康指数下降，建议追溯最近 24 小时的参数波动和报警模式。'
  }
  return 'AI 未发现严重异常，建议继续关注报警重复触发和关键设备健康趋势。'
})

const heroMetrics = computed(() => [
  { label: '健康指数', value: healthScore.value, hint: '综合设备状态' },
  { label: '活跃报警', value: criticalAlarms.value + warningAlarms.value, hint: `${alarmCount.value} 条总报警` },
  { label: '在线率', value: `${onlineRate.value}%`, hint: `${onlineDevices.value}/${totalDevices.value} 台在线` },
])

const insights = computed(() => {
  const list = [
    {
      level: knowledgeInsight.value.level,
      confidence: knowledgeInsight.value.confidence,
      title: knowledgeInsight.value.title,
      reason: knowledgeInsight.value.reason,
      action: '进入评估报告，查看四个维度的诊断明细。',
      primaryPath: '/knowledge-overview',
      primaryLabel: '查看分析',
      secondaryPath: '/knowledge-management',
      secondaryLabel: '进入知识库',
    },
    {
    level: criticalAlarms.value > 0 ? '高风险' : '关注',
    confidence: criticalAlarms.value > 0 ? 91 : 76,
    title: '报警触发需要优先诊断',
    reason: `当前检测到 ${alarmCount.value} 次报警，其中活跃报警 ${criticalAlarms.value + warningAlarms.value} 次。AI 建议先查看报警集中设备和触发时间段。`,
    action: '进入风险洞察，定位重复报警和关键点位。',
    primaryPath: '/alarm-analysis',
  },
  {
    level: healthScore.value < 90 ? '中风险' : '稳定',
    confidence: 84,
    title: '设备健康趋势可继续追踪',
    reason: `健康指数为 ${healthScore.value}，在线率 ${onlineRate.value}%。若连续下降，应对工艺参数做窗口对比。`,
    action: '运行设备诊断，查看异常检测和故障预测结果。',
    primaryPath: '/analysis?module=health',
  },
  {
    level: '建议',
    confidence: 79,
    title: '建议生成一份维护沟通报告',
    reason: 'AI 已具备健康、报警、在线率三类摘要信息，可形成面向维修和生产团队的简版报告。',
    action: '生成日报或维护报告，并保留数据证据。',
    primaryPath: '/report',
  },
  ]
  return list.sort((a, b) => (b.confidence ?? 0) - (a.confidence ?? 0))
})

const evidenceItems = computed(() => [
  { label: '报警证据完整度', value: `${Math.min(100, 60 + alarmCount.value * 8)}%`, percent: Math.min(100, 60 + alarmCount.value * 8) },
  { label: '健康数据覆盖', value: `${healthScore.value}%`, percent: healthScore.value },
  { label: '设备在线覆盖', value: `${onlineRate.value}%`, percent: onlineRate.value },
])

const quickActions = [
  { path: '/alarm-analysis', title: '分析报警模式', desc: '识别重复报警、异常时间段和高风险设备。' },
  { path: '/analysis?module=fault', title: '预测潜在故障', desc: '基于设备参数变化生成故障风险判断。' },
  { path: '/repair-suggestion', title: '生成维修建议', desc: '结合历史维修单和设备文档输出处理建议。' },
  { path: '/report', title: '生成 AI 报告', desc: '把分析结论整理成可交付报告。' },
]

const commandPresets = [
  '分析今天报警最多的设备',
  '生成本周维护报告',
  '解释健康分下降原因',
  '给出维修处理建议',
]

function riskClass(level) {
  if (level === '高风险') return 'bg-red-50 text-red-700'
  if (level === '中风险') return 'bg-amber-50 text-amber-700'
  if (level === '稳定') return 'bg-emerald-50 text-emerald-700'
  return 'bg-amber-50 text-amber-700'
}

async function loadKnowledgeInsight() {
  try {
    const data = await getKnowledgeOverview()
    const o = data?.data ?? data
    if (!o?.summary) {
      knowledgeInsight.value = {
        level: '稳定',
        confidence: 50,
        title: '知识库健康度待评估',
        reason: '知识库尚未初始化，请先到知识库管理创建基础数据。',
      }
      return
    }
    const s = o.summary
    const missingTotal = (s.missing_device_type_count ?? 0) + (s.missing_plan_item_count ?? 0)
    const parts = []

    // 基础信息
    parts.push(`总体完成率 ${s.total_progress ?? 0}%，质量分 ${s.total_score ?? 0}`)
    // 异常项
    if ((s.expired_count ?? 0) > 0) parts.push(`${s.expired_count} 项合规证书已过期需续期`)
    if (missingTotal > 0) parts.push(`${missingTotal} 个收集项缺失文档`)
    if ((s.low_quality_doc_count ?? 0) > 0) parts.push(`${s.low_quality_doc_count} 份文档 AI 评分低于 60`)

    let level = '稳定'
    if ((s.expired_count ?? 0) > 0 || (s.total_progress ?? 100) < 30 || (s.total_score ?? 100) < 60) {
      level = '高风险'
    } else if ((s.total_progress ?? 100) < 60 || (s.low_quality_doc_count ?? 0) > 5 || missingTotal > 5) {
      level = '中风险'
    }

    knowledgeInsight.value = {
      level,
      confidence: 95,
      title: '知识库健康度待提升',
      reason: parts.join('；') + '。',
    }
  } catch (e) {
    const status = e?.response?.status
    if (status === 404) {
      // 后端 ENABLE_KNOWLEDGE_BASE 关闭时这个路由根本不存在，重试也没用，如实告知而不是让人以为"稍后能好"
      knowledgeInsight.value = {
        level: '稳定',
        confidence: 0,
        title: '知识库管理功能未启用',
        reason: '当前环境未开启知识库管理模块（ENABLE_KNOWLEDGE_BASE），需要管理员在部署配置里打开并部署 RAGFlow 后才能看到这里的数据。',
      }
    } else {
      knowledgeInsight.value = {
        level: '稳定',
        confidence: 50,
        title: '知识库健康度待评估',
        reason: '暂未获取到知识库健康数据，请稍后点击"刷新洞察"重试。',
      }
    }
  }
}

async function loadData() {
  loading.value = true
  try {
    const res = await runDeviceAnalysis({ module: 'health', hours: 24 })
    if (res.code === 200 && res.data?.health) {
      const h = res.data.health
      healthScore.value = h.health_score || h.overall_health || healthScore.value
      alarmCount.value = h.alarm_count || h.total_alarms || alarmCount.value
      criticalAlarms.value = h.critical_alarms || criticalAlarms.value
      warningAlarms.value = h.warning_alarms || warningAlarms.value
      onlineRate.value = h.online_rate || onlineRate.value
    }
  } catch (err) {
    console.error('Dashboard load error:', err)
  } finally {
    loading.value = false
  }
}

function dispatchCommand() {
  const text = command.value
  if (text.includes('报告')) {
    router.push('/report')
  } else if (text.includes('维修')) {
    router.push('/repair-suggestion')
  } else if (text.includes('报警')) {
    router.push('/alarm-analysis')
  } else {
    router.push('/analysis')
  }
}

onMounted(() => {
  loadData()
  loadKnowledgeInsight()
})
</script>

<style scoped>
.brain-grid {
  position: absolute;
  inset: 0;
  opacity: 0.28;
  background:
    linear-gradient(rgba(251, 191, 36, 0.16) 1px, transparent 1px),
    linear-gradient(90deg, rgba(251, 191, 36, 0.16) 1px, transparent 1px);
  background-size: 28px 28px;
  mask-image: radial-gradient(circle at 55% 50%, black 0%, transparent 68%);
}

.brain-core {
  position: absolute;
  right: 11%;
  top: 50%;
  width: 260px;
  height: 180px;
  transform: translateY(-50%);
  border: 1px solid rgba(251, 191, 36, 0.36);
  border-radius: 44% 56% 48% 52% / 56% 44% 56% 44%;
  background:
    radial-gradient(circle at 35% 42%, rgba(251, 191, 36, 0.38), transparent 16%),
    radial-gradient(circle at 62% 38%, rgba(253, 224, 71, 0.3), transparent 18%),
    radial-gradient(circle at 52% 66%, rgba(245, 158, 11, 0.34), transparent 18%),
    rgba(255, 255, 255, 0.04);
  box-shadow:
    0 0 60px rgba(251, 191, 36, 0.28),
    inset 0 0 40px rgba(251, 191, 36, 0.12);
}

.brain-core::before,
.brain-core::after {
  content: "";
  position: absolute;
  border: 1px solid rgba(251, 191, 36, 0.24);
  border-radius: inherit;
}

.brain-core::before {
  inset: 18px 28px 22px 26px;
}

.brain-core::after {
  inset: 44px 54px 48px 52px;
}

.brain-node,
.brain-line {
  position: absolute;
  display: block;
}

.brain-node {
  width: 10px;
  height: 10px;
  border-radius: 999px;
  background: #fbbf24;
  box-shadow: 0 0 18px rgba(251, 191, 36, 0.95);
}

.node-a { left: 58px; top: 54px; }
.node-b { left: 142px; top: 42px; }
.node-c { left: 176px; top: 106px; }
.node-d { left: 92px; top: 118px; }

.brain-line {
  height: 1px;
  transform-origin: left center;
  background: linear-gradient(90deg, rgba(251, 191, 36, 0.9), rgba(251, 191, 36, 0.08));
}

.line-a { left: 66px; top: 59px; width: 82px; transform: rotate(-8deg); }
.line-b { left: 149px; top: 50px; width: 68px; transform: rotate(58deg); }
.line-c { left: 98px; top: 123px; width: 82px; transform: rotate(-12deg); }
.line-d { left: 64px; top: 62px; width: 74px; transform: rotate(58deg); }
</style>
