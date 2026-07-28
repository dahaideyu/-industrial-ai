<template>
  <section class="min-h-screen p-6 lg:p-8">
    <div class="mx-auto grid max-w-[1500px] gap-6 lg:grid-cols-[420px_1fr]">
      <aside class="rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
        <p class="text-xs font-bold uppercase tracking-[0.18em] text-amber-700">AI Document Analysis</p>
        <h1 class="mt-2 font-headline text-2xl font-semibold text-slate-950">文档分析</h1>
        <p class="mt-2 text-sm leading-6 text-slate-500">把维修记录、操作说明或异常描述交给 AI 做结构化提取。</p>

        <textarea
          v-model="content"
          rows="12"
          class="mt-5 w-full resize-none rounded-md border border-slate-200 bg-slate-50 px-3 py-3 text-sm leading-6 outline-none focus:border-amber-500 focus:bg-white"
          placeholder="粘贴需要分析的文档内容..."
        ></textarea>

        <button
          @click="run"
          :disabled="loading || !content.trim()"
          class="mt-4 w-full rounded-md bg-slate-950 px-4 py-3 text-sm font-bold text-white hover:bg-amber-700 disabled:opacity-50"
        >
          {{ loading ? 'AI 正在分析...' : '开始分析文档' }}
        </button>
      </aside>

      <main class="rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
        <h2 class="font-headline text-lg font-semibold text-slate-950">分析结果</h2>
        <div class="mt-4 min-h-[520px] rounded-md bg-slate-50 p-4">
          <div v-if="!result && !error" class="grid h-[480px] place-items-center text-center text-slate-500">
            <div>
              <div class="mx-auto mb-4 h-12 w-12 rounded-md bg-slate-950"></div>
              <p class="font-semibold text-slate-700">等待文档输入</p>
              <p class="mt-1 text-sm">AI 将提取关键词、风险点和可追踪证据。</p>
            </div>
          </div>
          <pre v-else-if="result" class="whitespace-pre-wrap text-sm leading-7 text-slate-800">{{ formattedResult }}</pre>
          <p v-else class="text-sm font-semibold text-red-600">{{ error }}</p>
        </div>
      </main>
    </div>
  </section>
</template>

<script setup>
import { computed, ref } from 'vue'
import { analyzeDocument } from '../api/client.js'

const content = ref('')
const loading = ref(false)
const result = ref(null)
const error = ref('')

const formattedResult = computed(() => JSON.stringify(result.value, null, 2))

async function run() {
  loading.value = true
  error.value = ''
  result.value = null
  try {
    const res = await analyzeDocument({ content: content.value })
    if (res.code === 200) result.value = res.data
    else error.value = res.msg || '分析失败'
  } catch (err) {
    error.value = err.message
  } finally {
    loading.value = false
  }
}
</script>
