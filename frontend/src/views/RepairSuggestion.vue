<template>
  <section class="min-h-screen p-6 lg:p-8">
    <div class="mx-auto grid max-w-[1500px] gap-6 lg:grid-cols-[420px_1fr]">
      <aside class="rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
        <p class="text-xs font-bold uppercase tracking-[0.18em] text-amber-700">AI Repair Advisor</p>
        <h1 class="mt-2 font-headline text-2xl font-semibold text-slate-950">维修建议</h1>
        <p class="mt-2 text-sm leading-6 text-slate-500">输入设备和故障现象，AI 将结合知识库生成处理建议。</p>

        <div class="mt-5 space-y-4">
          <div>
            <label class="mb-2 block text-xs font-bold uppercase tracking-[0.14em] text-slate-500">设备名称</label>
            <input v-model="form.device_name" class="w-full rounded-md border border-slate-200 bg-slate-50 px-3 py-2.5 text-sm outline-none focus:border-amber-500" />
          </div>
          <div>
            <label class="mb-2 block text-xs font-bold uppercase tracking-[0.14em] text-slate-500">设备类型</label>
            <input v-model="form.device_type" class="w-full rounded-md border border-slate-200 bg-slate-50 px-3 py-2.5 text-sm outline-none focus:border-amber-500" />
          </div>
          <div>
            <label class="mb-2 block text-xs font-bold uppercase tracking-[0.14em] text-slate-500">故障现象</label>
            <textarea v-model="form.fault_description" rows="7" class="w-full resize-none rounded-md border border-slate-200 bg-slate-50 px-3 py-2.5 text-sm leading-6 outline-none focus:border-amber-500"></textarea>
          </div>
          <button
            @click="run"
            :disabled="loading || !form.fault_description"
            class="w-full rounded-md bg-slate-950 px-4 py-3 text-sm font-bold text-white hover:bg-amber-700 disabled:opacity-50"
          >
            {{ loading ? 'AI 正在检索...' : '生成维修建议' }}
          </button>
        </div>
      </aside>

      <main class="space-y-6">
        <div class="rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
          <h2 class="font-headline text-lg font-semibold text-slate-950">AI 结论</h2>
          <div class="mt-4 min-h-[220px] rounded-md bg-slate-50 p-4">
            <p v-if="!result && !error" class="text-sm leading-7 text-slate-500">等待生成维修建议。</p>
            <p v-else-if="error" class="text-sm font-semibold text-red-600">{{ error }}</p>
            <p v-else class="whitespace-pre-wrap text-sm leading-7 text-slate-800">{{ result.conclusion }}</p>
          </div>
        </div>

        <div class="rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
          <h2 class="font-headline text-lg font-semibold text-slate-950">处理建议与依据</h2>
          <pre class="mt-4 min-h-[280px] whitespace-pre-wrap rounded-md bg-slate-950 p-4 text-sm leading-7 text-amber-50">{{ result?.context || 'AI 将在这里输出建议步骤、检查项和依据。' }}</pre>
        </div>
      </main>
    </div>
  </section>
</template>

<script setup>
import { reactive, ref } from 'vue'
import { getRepairSuggestion } from '../api/client.js'

const form = reactive({
  device_name: '',
  device_type: '',
  fault_description: '',
})

const loading = ref(false)
const result = ref(null)
const error = ref('')

async function run() {
  loading.value = true
  error.value = ''
  result.value = null
  try {
    const res = await getRepairSuggestion(form)
    result.value = res
    if (res.status === 'error') error.value = res.error_message || '生成失败'
  } catch (err) {
    error.value = err.message
  } finally {
    loading.value = false
  }
}
</script>
