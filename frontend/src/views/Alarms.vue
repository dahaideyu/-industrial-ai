<template>
  <div class="p-6 lg:p-8 max-w-[1500px] mx-auto">
    <div class="mb-6 rounded-lg border border-slate-200 bg-slate-950 p-6 text-white shadow-sm">
      <div class="flex flex-col gap-5 lg:flex-row lg:items-start lg:justify-between">
        <div>
          <p class="text-xs font-bold uppercase tracking-[0.18em] text-amber-200">Alarm Evidence</p>
          <h1 class="mt-2 font-headline text-2xl font-semibold">报警证据</h1>
          <p class="mt-3 max-w-3xl text-sm leading-7 text-slate-300">{{ alarmInsight }}</p>
        </div>
        <button @click="loadData" class="rounded-md bg-amber-400 px-4 py-2 text-sm font-bold text-slate-950 transition-colors hover:bg-amber-300">
          刷新证据
        </button>
      </div>
    </div>

    <div class="grid grid-cols-2 gap-4 mb-6 lg:grid-cols-4">
      <div v-for="item in evidenceCards" :key="item.label" class="rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
        <div class="text-xs font-bold uppercase tracking-[0.14em] text-slate-400">{{ item.label }}</div>
        <div :class="['mt-3 font-headline text-3xl font-bold', item.color]">{{ item.value }}</div>
        <div class="mt-1 text-xs text-slate-500">{{ item.hint }}</div>
      </div>
    </div>

    <!-- Filters -->
    <div class="bg-white rounded-xl border border-gray-100 shadow-sm p-6 mb-6">
      <div class="grid grid-cols-5 gap-4">
        <!-- Device Filter -->
        <div>
          <label class="block text-xs font-bold text-gray-500 uppercase tracking-widest mb-2">设备</label>
          <select
            v-model="filters.device_id"
            class="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-amber-400"
          >
            <option value="">全部设备</option>
            <option v-for="d in devices" :key="d.device_id" :value="d.device_id">
              {{ d.device_name || d.device_id }}
            </option>
          </select>
        </div>

        <!-- Keyword Search -->
        <div>
          <label class="block text-xs font-bold text-gray-500 uppercase tracking-widest mb-2">搜索</label>
          <input
            v-model="filters.keyword"
            type="text"
            placeholder="报警名称..."
            class="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-amber-400"
          />
        </div>

        <!-- Start Date -->
        <div>
          <label class="block text-xs font-bold text-gray-500 uppercase tracking-widest mb-2">开始日期</label>
          <input
            v-model="filters.start_date"
            type="date"
            class="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-amber-400"
          />
        </div>

        <!-- End Date -->
        <div>
          <label class="block text-xs font-bold text-gray-500 uppercase tracking-widest mb-2">结束日期</label>
          <input
            v-model="filters.end_date"
            type="date"
            class="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-amber-400"
          />
        </div>

        <!-- Active Only -->
        <div class="flex items-end">
          <label class="flex items-center gap-2 text-sm text-gray-600 cursor-pointer">
            <input
              v-model="filters.only_active"
              type="checkbox"
              class="rounded border-gray-300 text-amber-500 focus:ring-amber-500"
            />
            <span>只显示触发状态</span>
          </label>
        </div>
      </div>

      <div class="mt-4 flex justify-end gap-2">
        <button
          @click="resetFilters"
          class="px-4 py-2 border border-gray-200 text-gray-600 text-sm rounded-lg hover:bg-gray-50 transition-colors"
        >
          重置
        </button>
        <button
          @click="searchAlarms"
          class="px-4 py-2 bg-amber-400 text-on-primary-container text-sm font-bold rounded-lg hover:bg-amber-500 transition-colors"
        >
          搜索
        </button>
      </div>
    </div>

    <!-- Alarm Table -->
    <div class="bg-white rounded-xl border border-gray-100 shadow-sm overflow-hidden">
      <div class="px-6 py-4 bg-gray-50 border-b border-gray-100 flex justify-between items-center">
        <h2 class="text-sm font-bold uppercase tracking-widest text-gray-600">
          报警记录
          <span class="ml-2 text-amber-600">({{ pagination.total }} 条)</span>
        </h2>
        <div class="text-xs text-gray-500">
          第 {{ pagination.page }} / {{ pagination.total_pages }} 页
        </div>
      </div>

      <div class="overflow-x-auto">
        <table class="w-full text-left" v-if="alarms.length > 0">
          <thead class="bg-gray-50/50">
            <tr>
              <th class="px-6 py-3 text-[10px] font-bold text-gray-500 uppercase tracking-widest">时间</th>
              <th class="px-6 py-3 text-[10px] font-bold text-gray-500 uppercase tracking-widest">设备</th>
              <th class="px-6 py-3 text-[10px] font-bold text-gray-500 uppercase tracking-widest">报警名称</th>
              <th class="px-6 py-3 text-[10px] font-bold text-gray-500 uppercase tracking-widest">状态</th>
              <th class="px-6 py-3 text-[10px] font-bold text-gray-500 uppercase tracking-widest">点位ID</th>
            </tr>
          </thead>
          <tbody class="divide-y divide-gray-50">
            <tr v-for="alarm in alarms" :key="alarm.id" class="hover:bg-gray-50/30 transition-colors">
              <td class="px-6 py-4 text-xs font-mono text-gray-500">{{ formatTime(alarm.point_time) }}</td>
              <td class="px-6 py-4 text-sm text-on-surface">{{ alarm.device_name || alarm.device_id }}</td>
              <td class="px-6 py-4 text-sm font-bold text-on-surface">{{ alarm.alarm_name }}</td>
              <td class="px-6 py-4">
                <span
                  :class="[
                    'inline-flex items-center gap-1.5 px-2 py-0.5 text-[10px] font-bold rounded',
                    alarm.point_value === 1 ? 'bg-red-50 text-red-600' : 'bg-green-50 text-green-600'
                  ]"
                >
                  <span v-if="alarm.point_value === 1" class="w-1.5 h-1.5 rounded-full bg-red-500 animate-pulse"></span>
                  {{ alarm.status }}
                </span>
              </td>
              <td class="px-6 py-4 text-xs font-mono text-gray-400">{{ alarm.point_id }}</td>
            </tr>
          </tbody>
        </table>

        <div v-else class="p-12 text-center text-gray-400">
          <div class="mx-auto mb-4 h-10 w-10 rounded-md bg-slate-950"></div>
          <p v-if="alarmsError" class="text-red-500 font-medium">{{ alarmsError }}</p>
          <template v-else>
            <p>暂无报警记录</p>
            <p class="mt-1 text-xs">当前筛选条件下没有匹配的记录，可以尝试清空筛选条件或调整日期范围。</p>
          </template>
        </div>
      </div>

      <!-- Pagination -->
      <div v-if="pagination.total_pages > 1" class="px-6 py-4 bg-gray-50 border-t border-gray-100 flex justify-between items-center">
        <div class="text-xs text-gray-500">
          显示 {{ (pagination.page - 1) * pagination.page_size + 1 }} - {{ Math.min(pagination.page * pagination.page_size, pagination.total) }} 条
        </div>
        <div class="flex gap-2">
          <button
            @click="goToPage(1)"
            :disabled="pagination.page === 1"
            class="px-3 py-1 text-xs border border-gray-200 rounded hover:bg-gray-100 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            首页
          </button>
          <button
            @click="goToPage(pagination.page - 1)"
            :disabled="pagination.page === 1"
            class="px-3 py-1 text-xs border border-gray-200 rounded hover:bg-gray-100 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            上一页
          </button>

          <template v-for="p in visiblePages" :key="p">
            <button
              v-if="p !== '...'"
              @click="goToPage(p)"
              :class="[
                'px-3 py-1 text-xs rounded',
                p === pagination.page ? 'bg-amber-400 text-white font-bold' : 'border border-gray-200 hover:bg-gray-100'
              ]"
            >
              {{ p }}
            </button>
            <span v-else class="px-2 py-1 text-xs text-gray-400">...</span>
          </template>

          <button
            @click="goToPage(pagination.page + 1)"
            :disabled="pagination.page === pagination.total_pages"
            class="px-3 py-1 text-xs border border-gray-200 rounded hover:bg-gray-100 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            下一页
          </button>
          <button
            @click="goToPage(pagination.total_pages)"
            :disabled="pagination.page === pagination.total_pages"
            class="px-3 py-1 text-xs border border-gray-200 rounded hover:bg-gray-100 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            末页
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, watch } from 'vue'
import { getAlarms, getAlarmStatistics, getAlarmDevices } from '../api/client.js'

const alarms = ref([])
const devices = ref([])
const statistics = ref({})
const pagination = ref({
  total: 0,
  page: 1,
  page_size: 50,
  total_pages: 0
})

const filters = ref({
  device_id: '',
  keyword: '',
  start_date: '',
  end_date: '',
  only_active: false
})
const alarmsError = ref('')

const alarmInsight = computed(() => {
  const total = statistics.value.total || 0
  const active = statistics.value.active || 0
  const typeCount = statistics.value.by_type?.length || 0
  if (active > 0) {
    return `AI 当前建议优先处理 ${active} 条活跃报警，再按设备和点位追溯重复触发原因。当前共有 ${total} 条报警证据，覆盖 ${typeCount} 类报警类型。`
  }
  return `AI 未发现活跃报警，但仍建议按时间窗口检查 ${total} 条历史报警，识别重复触发和潜在工艺波动。`
})

const evidenceCards = computed(() => [
  { label: '总报警数', value: statistics.value.total || 0, hint: '当前筛选范围内证据量', color: 'text-slate-950' },
  { label: '活跃报警', value: statistics.value.active || 0, hint: '需要优先处理', color: 'text-red-600' },
  { label: '涉及设备', value: devices.value.length, hint: '报警覆盖设备数', color: 'text-amber-700' },
  { label: '报警类型', value: statistics.value.by_type?.length || 0, hint: '用于模式归因', color: 'text-slate-700' },
])

const visiblePages = computed(() => {
  const total = pagination.value.total_pages
  const current = pagination.value.page
  const pages = []

  if (total <= 7) {
    for (let i = 1; i <= total; i++) pages.push(i)
  } else {
    pages.push(1)
    if (current > 3) pages.push('...')

    const start = Math.max(2, current - 1)
    const end = Math.min(total - 1, current + 1)

    for (let i = start; i <= end; i++) pages.push(i)

    if (current < total - 2) pages.push('...')
    pages.push(total)
  }

  return pages
})

function formatTime(isoString) {
  if (!isoString) return '-'
  const date = new Date(isoString)
  return date.toLocaleString('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit'
  })
}

async function loadDevices() {
  try {
    const res = await getAlarmDevices()
    if (res.code === 200) {
      devices.value = res.data || []
    }
  } catch (err) {
    console.error('加载设备列表失败:', err)
  }
}

async function loadStatistics() {
  try {
    const params = {}
    if (filters.value.device_id) params.device_id = filters.value.device_id
    if (filters.value.start_date) params.start_date = filters.value.start_date
    if (filters.value.end_date) params.end_date = filters.value.end_date

    const res = await getAlarmStatistics(params)
    if (res.code === 200) {
      statistics.value = res.data || {}
    }
  } catch (err) {
    console.error('加载统计数据失败:', err)
  }
}

async function loadAlarms() {
  alarmsError.value = ''
  try {
    const params = {
      page: pagination.value.page,
      page_size: pagination.value.page_size
    }

    if (filters.value.device_id) params.device_id = filters.value.device_id
    if (filters.value.keyword) params.keyword = filters.value.keyword
    if (filters.value.start_date) params.start_date = filters.value.start_date
    if (filters.value.end_date) params.end_date = filters.value.end_date
    if (filters.value.only_active) params.only_active = true

    const res = await getAlarms(params)
    if (res.code === 200) {
      alarms.value = res.data.items || []
      pagination.value = {
        total: res.data.total,
        page: res.data.page,
        page_size: res.data.page_size,
        total_pages: res.data.total_pages
      }
    } else {
      alarms.value = []
      alarmsError.value = res.msg || '加载报警记录失败'
    }
  } catch (err) {
    console.error('加载报警记录失败:', err)
    alarms.value = []
    alarmsError.value = err.response
      ? (err.response.data?.msg || err.message)
      : '连不上后端服务，请检查后端是否正常运行。'
  }
}

async function loadData() {
  await Promise.all([loadDevices(), loadStatistics(), loadAlarms()])
}

function searchAlarms() {
  pagination.value.page = 1
  loadAlarms()
  loadStatistics()
}

function resetFilters() {
  filters.value = {
    device_id: '',
    keyword: '',
    start_date: '',
    end_date: '',
    only_active: false
  }
  pagination.value.page = 1
  loadData()
}

function goToPage(page) {
  if (page < 1 || page > pagination.value.total_pages) return
  pagination.value.page = page
  loadAlarms()
}

onMounted(() => {
  loadData()
})
</script>
