<template>
  <div class="max-w-[1280px] mx-auto px-6 py-8">
    <!-- 头部 -->
    <div class="flex items-center justify-between flex-wrap gap-3 mb-6">
      <div>
        <h1 class="font-headline text-xl font-semibold text-gray-900">设备列表</h1>
        <p class="text-sm text-gray-400 mt-1">从 MySQL 同步设备清单；勾选哪些设备出现在"参数分析"页的设备下拉框里。</p>
      </div>
      <div class="flex items-center gap-2">
        <button @click="onSync" :disabled="syncing"
          class="px-4 py-2 text-sm rounded-lg bg-amber-400 text-on-primary-container font-bold hover:bg-amber-500 disabled:opacity-50">
          {{ syncing ? '同步中…' : '🔄 同步设备列表' }}
        </button>
        <button @click="load" :disabled="loading"
          class="px-4 py-2 text-sm rounded-lg bg-gray-50 text-gray-600 border border-gray-200 hover:bg-gray-100 disabled:opacity-50">
          {{ loading ? '加载中…' : '刷新' }}
        </button>
      </div>
    </div>

    <!-- 汇总条 -->
    <div class="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-5">
      <div class="bg-white rounded-xl border border-gray-100 shadow-sm p-4">
        <div class="text-[11px] text-gray-400">设备总数</div>
        <div class="text-2xl font-semibold text-gray-800 tabular-nums mt-1">{{ devices.length }}</div>
      </div>
      <div class="bg-white rounded-xl border border-gray-100 shadow-sm p-4">
        <div class="text-[11px] text-gray-400">参数分析页可见</div>
        <div class="text-2xl font-semibold text-emerald-600 tabular-nums mt-1">{{ visibleCount }}</div>
      </div>
      <div class="bg-white rounded-xl border border-gray-100 shadow-sm p-4">
        <div class="text-[11px] text-gray-400">未保存的改动</div>
        <div class="text-2xl font-semibold tabular-nums mt-1" :class="dirtyCount ? 'text-amber-500' : 'text-gray-300'">{{ dirtyCount }}</div>
      </div>
      <div class="bg-white rounded-xl border border-gray-100 shadow-sm p-4 flex items-center">
        <button @click="saveChanges" :disabled="!dirtyCount || saving"
          class="w-full px-3 py-2 text-sm rounded-lg bg-indigo-600 text-white font-bold hover:bg-indigo-700 disabled:opacity-40 disabled:cursor-not-allowed">
          {{ saving ? '保存中…' : `保存修改${dirtyCount ? ` (${dirtyCount})` : ''}` }}
        </button>
      </div>
    </div>

    <div v-if="notice" class="mb-4 text-sm rounded-lg px-4 py-2"
      :class="noticeErr ? 'bg-rose-50 text-rose-600' : 'bg-indigo-50 text-indigo-600'">{{ notice }}</div>

    <!-- 设备表（按类型分组） -->
    <div v-for="g in grouped" :key="g.type" class="mb-6">
      <div class="text-xs font-semibold uppercase tracking-wider text-gray-400 mb-2">
        {{ g.type }} <span class="text-gray-300 normal-case font-normal">共 {{ g.items.length }} 台，{{ g.visibleCount }} 台可见</span>
      </div>
      <div class="bg-white rounded-xl border border-gray-100 shadow-sm overflow-hidden">
        <div class="overflow-x-auto">
          <table class="w-full text-sm">
            <thead class="bg-gray-50">
              <tr class="text-left text-xs text-gray-500 border-b border-gray-200 whitespace-nowrap">
                <th class="py-3 px-4 font-semibold">设备编码</th>
                <th class="py-3 px-3 font-semibold">设备名称</th>
                <th class="py-3 px-3 font-semibold">参数分析页可见</th>
              </tr>
            </thead>
            <tbody class="divide-y divide-gray-50">
              <tr v-for="d in g.items" :key="d.device_code" class="hover:bg-gray-50/50">
                <td class="py-2.5 px-4 font-mono text-xs text-gray-700">{{ d.device_code }}</td>
                <td class="py-2.5 px-3 text-gray-700">{{ d.device_name }}</td>
                <td class="py-2.5 px-3">
                  <button @click="toggleVisible(d)"
                    :class="['relative inline-flex h-5 w-9 items-center rounded-full transition-colors', d.visible_in_params ? 'bg-emerald-500' : 'bg-gray-200']">
                    <span :class="['inline-block h-4 w-4 transform rounded-full bg-white transition-transform', d.visible_in_params ? 'translate-x-4' : 'translate-x-0.5']"></span>
                  </button>
                  <span v-if="dirty.has(d.device_code)" class="ml-2 text-[10px] text-amber-500">未保存</span>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>

    <div v-if="!loading && devices.length === 0" class="text-center py-16 text-gray-400 bg-white rounded-xl border border-gray-100 shadow-sm">
      <p class="text-sm">暂无设备，先点右上角"同步设备列表"从 MySQL 拉取。</p>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, reactive, onMounted } from 'vue'
import { getSystemDevices, saveDeviceVisibility, syncSystemDevices } from '../api/client.js'

const devices = ref([])
const loading = ref(false)
const syncing = ref(false)
const saving = ref(false)
const notice = ref('')
const noticeErr = ref(false)

// 改动过、还没保存的 device_code 集合——切换开关只改本地状态，点"保存修改"才发请求
const dirty = reactive(new Set())

const dirtyCount = computed(() => dirty.size)
const visibleCount = computed(() => devices.value.filter(d => d.visible_in_params).length)

const TYPE_ORDER = ['球磨机', '合膏机', '固化室', '其他']
const grouped = computed(() => {
  const map = new Map()
  for (const d of devices.value) {
    if (!map.has(d.device_type)) map.set(d.device_type, [])
    map.get(d.device_type).push(d)
  }
  return TYPE_ORDER.filter(t => map.has(t)).map(type => {
    const items = map.get(type)
    return { type, items, visibleCount: items.filter(d => d.visible_in_params).length }
  })
})

function toggleVisible(d) {
  d.visible_in_params = !d.visible_in_params
  dirty.add(d.device_code)
}

async function load() {
  loading.value = true
  try {
    const res = await getSystemDevices()
    if (res.code === 200 && res.data) {
      devices.value = res.data.devices || []
    } else {
      notice.value = res.msg || '加载设备列表失败'
      noticeErr.value = true
    }
  } catch (err) {
    console.error('加载设备列表失败:', err)
    notice.value = err?.response?.data?.msg || '加载设备列表失败'
    noticeErr.value = true
  } finally {
    loading.value = false
    dirty.clear()
  }
}

async function onSync() {
  syncing.value = true
  notice.value = ''
  noticeErr.value = false
  try {
    const res = await syncSystemDevices()
    if (res.code === 200) {
      notice.value = res.msg || `已同步 ${res.data?.synced ?? 0} 台设备`
      await load()
    } else {
      notice.value = res.msg || '同步失败'
      noticeErr.value = true
    }
  } catch (err) {
    console.error('同步设备列表失败:', err)
    notice.value = err?.response?.data?.msg || '同步失败'
    noticeErr.value = true
  } finally {
    syncing.value = false
  }
}

async function saveChanges() {
  if (!dirty.size) return
  saving.value = true
  notice.value = ''
  noticeErr.value = false
  try {
    const payload = devices.value
      .filter(d => dirty.has(d.device_code))
      .map(d => ({ device_id: d.device_code, visible: d.visible_in_params }))
    const res = await saveDeviceVisibility(payload)
    if (res.code === 200) {
      notice.value = `已保存 ${res.data?.updated ?? payload.length} 处改动`
      dirty.clear()
    } else {
      notice.value = res.msg || '保存失败'
      noticeErr.value = true
    }
  } catch (err) {
    console.error('保存设备可见性失败:', err)
    notice.value = err?.response?.data?.msg || '保存失败'
    noticeErr.value = true
  } finally {
    saving.value = false
  }
}

onMounted(load)
</script>
