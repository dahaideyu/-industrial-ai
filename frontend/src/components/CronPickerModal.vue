<template>
  <div v-if="visible" class="fixed inset-0 bg-black/40 flex items-center justify-center z-50" @click.self="close">
    <div class="bg-white rounded-xl p-6 w-[480px] max-w-[92vw] shadow-2xl">
      <h3 class="text-base font-semibold text-gray-900 mb-1">编辑运行计划</h3>
      <p class="text-xs text-gray-400 mb-4 truncate">{{ jobName }}</p>

      <div class="flex gap-1.5 mb-4 flex-wrap">
        <button v-for="opt in freqOptions" :key="opt.value" type="button" @click="mode = opt.value"
          :class="['px-3 py-1.5 text-xs rounded-lg border transition-colors',
            mode === opt.value ? 'bg-violet-500 text-white border-violet-500' : 'bg-gray-50 text-gray-600 border-gray-200 hover:bg-gray-100']">
          {{ opt.label }}
        </button>
      </div>

      <div v-if="mode === 'weekly'" class="mb-4">
        <label class="block text-xs text-gray-500 mb-1.5">星期几</label>
        <div class="flex gap-1.5">
          <button v-for="d in weekdayLabels" :key="d.value" type="button" @click="toggleWeekday(d.value)"
            :class="['h-8 w-8 text-xs rounded-full border transition-colors',
              weekdays.includes(d.value) ? 'bg-violet-500 text-white border-violet-500' : 'bg-gray-50 text-gray-600 border-gray-200 hover:bg-gray-100']">
            {{ d.label }}
          </button>
        </div>
      </div>

      <div v-if="mode === 'monthly'" class="mb-4">
        <label class="block text-xs text-gray-500 mb-1.5">每月第几天</label>
        <div class="grid grid-cols-7 gap-1.5">
          <button v-for="d in 31" :key="d" type="button" @click="toggleDay(d)"
            :class="['h-7 text-xs rounded border transition-colors tabular-nums',
              days.includes(d) ? 'bg-violet-500 text-white border-violet-500' : 'bg-gray-50 text-gray-600 border-gray-200 hover:bg-gray-100']">
            {{ d }}
          </button>
        </div>
      </div>

      <div v-if="mode === 'hourly'" class="mb-4">
        <label class="block text-xs text-gray-500 mb-1.5">在第几分钟执行</label>
        <select v-model.number="minute"
          class="w-24 px-2 py-1.5 text-sm rounded-lg border border-gray-200 focus:border-violet-400 focus:outline-none">
          <option v-for="m in 60" :key="m - 1" :value="m - 1">{{ pad2(m - 1) }} 分</option>
        </select>
      </div>

      <div v-if="['daily', 'weekly', 'monthly'].includes(mode)" class="mb-4">
        <label class="block text-xs text-gray-500 mb-1.5">执行时间</label>
        <div class="flex items-center gap-1.5">
          <select v-model.number="hour"
            class="w-20 px-2 py-1.5 text-sm rounded-lg border border-gray-200 focus:border-violet-400 focus:outline-none">
            <option v-for="h in 24" :key="h - 1" :value="h - 1">{{ pad2(h - 1) }} 时</option>
          </select>
          <span class="text-gray-400">:</span>
          <select v-model.number="minute"
            class="w-20 px-2 py-1.5 text-sm rounded-lg border border-gray-200 focus:border-violet-400 focus:outline-none">
            <option v-for="m in 60" :key="m - 1" :value="m - 1">{{ pad2(m - 1) }} 分</option>
          </select>
        </div>
      </div>

      <div v-if="mode === 'custom'" class="mb-4">
        <label class="block text-xs text-gray-500 mb-1.5">cron 表达式</label>
        <input v-model="customCron" placeholder="0 2 * * *" spellcheck="false"
          class="w-full px-3 py-1.5 text-sm tabular-nums rounded-lg border border-gray-200 focus:border-violet-400 focus:outline-none" />
        <p class="text-[11px] text-gray-400 mt-1.5 leading-relaxed">
          字段顺序：分(0-59) 时(0-23) 日(1-31) 月(1-12) 周(0-6，0=周日)；用 * 表示不限，逗号分隔多个值
        </p>
      </div>

      <div class="rounded-lg bg-gray-50 border border-gray-100 px-3 py-2 text-xs text-gray-600 mb-5">
        <div>{{ previewText }}</div>
        <div class="text-gray-400 mt-0.5 tabular-nums">cron: {{ previewCron || '—' }}</div>
      </div>

      <div class="flex justify-end gap-2">
        <button type="button" @click="close"
          class="px-4 py-2 text-xs rounded-lg border border-gray-200 text-gray-600 hover:bg-gray-50">取消</button>
        <button type="button" @click="confirm" :disabled="!previewCron"
          class="px-4 py-2 text-xs rounded-lg bg-violet-500 text-white hover:bg-violet-600 disabled:opacity-50">确定</button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, watch } from 'vue'
import { parseCron, buildCron, describeCron, pad2 } from '../utils/cron.js'

const props = defineProps({
  visible: Boolean,
  cron: { type: String, default: '' },
  jobName: { type: String, default: '' },
})
const emit = defineEmits(['close', 'update'])

const freqOptions = [
  { value: 'hourly', label: '每小时' },
  { value: 'daily', label: '每天' },
  { value: 'weekly', label: '每周' },
  { value: 'monthly', label: '每月' },
  { value: 'custom', label: '自定义' },
]
const weekdayLabels = [
  { value: 1, label: '一' },
  { value: 2, label: '二' },
  { value: 3, label: '三' },
  { value: 4, label: '四' },
  { value: 5, label: '五' },
  { value: 6, label: '六' },
  { value: 0, label: '日' },
]

const mode = ref('daily')
const hour = ref(2)
const minute = ref(0)
const weekdays = ref([1])
const days = ref([1])
const customCron = ref('')

// 弹窗打开时，按当前 job 的 cron 重新解析初始状态
watch(() => props.visible, (v) => {
  if (!v) return
  const s = parseCron(props.cron)
  mode.value = s.mode
  hour.value = s.hour
  minute.value = s.minute
  weekdays.value = [...s.weekdays]
  days.value = [...s.days]
  customCron.value = s.mode === 'custom' ? (props.cron || '') : ''
}, { immediate: true })

function toggleWeekday(v) {
  const i = weekdays.value.indexOf(v)
  if (i >= 0) { if (weekdays.value.length > 1) weekdays.value.splice(i, 1) }
  else weekdays.value.push(v)
}
function toggleDay(v) {
  const i = days.value.indexOf(v)
  if (i >= 0) { if (days.value.length > 1) days.value.splice(i, 1) }
  else days.value.push(v)
}

const previewCron = computed(() => buildCron({
  mode: mode.value, hour: hour.value, minute: minute.value, weekdays: weekdays.value, days: days.value, raw: customCron.value,
}))
const previewText = computed(() => {
  if (mode.value === 'custom' && !customCron.value.trim()) return '请输入 cron 表达式'
  return describeCron(previewCron.value)
})

function close() { emit('close') }
function confirm() {
  if (!previewCron.value) return
  emit('update', previewCron.value)
  close()
}
</script>
