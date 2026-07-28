<template>
  <div v-if="open" class="fixed inset-0 z-50 flex items-center justify-center bg-black/40" @click.self="close">
    <div class="bg-white rounded-xl shadow-xl p-6 w-full max-w-lg m-4 max-h-[80vh] overflow-auto">
      <h3 class="text-lg font-semibold text-gray-800 mb-4">{{ title }}</h3>

      <!-- Phase: select -->
      <div v-if="phase === 'select'">
        <div class="flex items-center gap-3 mb-4">
          <input ref="fileRef" type="file" accept=".json" class="hidden" @change="handleFile" />
          <button @click="$refs.fileRef.click()" class="px-4 py-2 text-sm rounded-lg bg-amber-400 text-gray-900 font-medium hover:bg-amber-300">选择文件</button>
          <span v-if="fileName" class="text-sm text-gray-600">{{ fileName }}</span>
          <span v-else class="text-sm text-gray-400">请选择 {{ entityLabel }} 导出的 JSON 文件</span>
        </div>

        <div v-if="parseError" class="text-sm text-red-500 bg-red-50 rounded-lg p-3 mb-3">{{ parseError }}</div>

        <div v-if="entries.length > 0 && !parseError" class="text-sm text-gray-600 bg-gray-50 rounded-lg p-3 mb-3">
          共检测到 <strong>{{ entries.length }}</strong> 条{{ entityLabel }}数据
        </div>

        <div class="flex gap-3">
          <button @click="startImport" :disabled="entries.length === 0" class="px-4 py-2 text-sm rounded-lg font-medium transition-colors" :class="entries.length > 0 ? 'bg-amber-400 text-gray-900 hover:bg-amber-300' : 'bg-gray-200 text-gray-400 cursor-not-allowed'">开始导入</button>
          <button @click="close" class="px-4 py-2 text-sm rounded-lg border border-gray-200 text-gray-600 hover:bg-gray-50">取消</button>
        </div>
      </div>

      <!-- Phase: uploading -->
      <div v-else-if="phase === 'uploading'" class="text-center py-8 text-sm text-gray-500">正在导入中，请稍候...</div>

      <!-- Phase: done -->
      <div v-else-if="phase === 'done' && result">
        <div :class="['text-sm rounded-lg p-3 mb-3', result.failed === 0 ? 'bg-green-50 text-green-700' : 'bg-amber-50 text-amber-700']">
          成功导入 <strong>{{ result.imported }}</strong> 条
          <template v-if="result.skipped">, 跳过重复 <strong>{{ result.skipped }}</strong> 条</template>
          <template v-if="result.failed > 0">, 失败 <strong>{{ result.failed }}</strong> 条</template>
        </div>

        <div v-if="result.failed > 0" class="space-y-1 mb-3 max-h-32 overflow-auto">
          <div v-for="(r, i) in result.results.filter(r => r.status === 'error')" :key="i" class="text-xs text-red-500 py-1">
            #{{ r.index + 1 }} {{ r.message }}
          </div>
        </div>

        <button @click="done" class="px-4 py-2 text-sm rounded-lg bg-amber-400 text-gray-900 font-medium hover:bg-amber-300">完成</button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'

const props = defineProps({
  open: { type: Boolean, default: false },
  title: { type: String, default: '导入数据' },
  entityLabel: { type: String, default: '' },
  onImport: { type: Function, default: null },
})

const emit = defineEmits(['close', 'done'])

const phase = ref('select')
const fileName = ref('')
const entries = ref([])
const result = ref(null)
const parseError = ref('')
const fileRef = ref(null)

function handleFile(e) {
  const file = e.target.files?.[0]
  if (!file) return
  fileName.value = file.name
  parseError.value = ''
  const reader = new FileReader()
  reader.onload = (ev) => {
    try {
      const parsed = JSON.parse(ev.target.result)
      const list = parsed?.entries
      if (!Array.isArray(list) || list.length === 0) {
        parseError.value = 'JSON 文件中未找到有效的 entries 数组'
        entries.value = []
        return
      }
      entries.value = list
      parseError.value = ''
    } catch {
      parseError.value = 'JSON 格式解析失败，请检查文件内容'
      entries.value = []
    }
  }
  reader.readAsText(file)
}

async function startImport() {
  if (entries.value.length === 0) return
  if (!props.onImport) {
    // No import callback provided — parent handles it via file parse only
    done()
    return
  }
  phase.value = 'uploading'
  try {
    result.value = await props.onImport(entries.value)
  } catch (e) {
    result.value = { success: false, imported: 0, failed: entries.value.length, results: [{ index: 0, status: 'error', message: e?.message || '导入请求失败' }] }
  }
  phase.value = 'done'
}

function close() {
  phase.value = 'select'
  fileName.value = ''
  entries.value = []
  result.value = null
  parseError.value = ''
  emit('close')
}

function done() {
  close()
  emit('done')
}
</script>
