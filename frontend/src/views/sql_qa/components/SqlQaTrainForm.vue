<template>
  <div>
    <div class="mb-4">
      <h3 class="text-base font-semibold text-gray-700">手动注入训练数据</h3>
      <p class="text-xs text-gray-400 mt-1">通过此页面向 Vanna 记忆库添加训练数据。注入的数据将立即生效，辅助后续的 SQL 生成。</p>
    </div>

    <div class="mb-3">
      <label class="text-xs text-gray-500 mr-2">训练类型:</label>
      <SqlQaSelect v-model="type" :options="[{value:'sql_pair',label:'问题-SQL 对'},{value:'documentation',label:'文档训练（字段注释/业务规则）'}]" />
    </div>

    <template v-if="type === 'sql_pair'">
      <div class="mb-3">
        <label class="block text-xs text-gray-500 mb-1">自然语言问题</label>
        <input v-model="question" placeholder="例如: 制带线有几台设备" class="w-full px-4 py-3 border border-gray-200 rounded text-sm focus:outline-none focus:border-amber-400" />
      </div>
      <div class="mb-3">
        <label class="block text-xs text-gray-500 mb-1">对应 SQL 语句</label>
        <textarea v-model="sql" placeholder="SELECT COUNT(*) FROM dev_device WHERE ..." class="w-full px-4 py-3 border border-gray-200 rounded text-sm font-mono text-green-600 focus:outline-none focus:border-amber-400 resize-none" rows="10" />
      </div>
      <div class="mb-3">
        <label class="block text-xs text-gray-500 mb-1">训练主题（可选）</label>
        <input v-model="theme" placeholder="例如：设备故障工单、设备状态信息统计" maxlength="50" class="w-full px-4 py-3 border border-gray-200 rounded text-sm focus:outline-none focus:border-amber-400" />
      </div>
    </template>

    <div v-else class="mb-3">
      <label class="block text-xs text-gray-500 mb-1">文档 / 业务规则内容</label>
      <textarea v-model="content" placeholder="输入表结构说明、字段注释补充、业务规则、指标定义等..." class="w-full px-4 py-3 border border-gray-200 rounded text-sm focus:outline-none focus:border-amber-400 resize-none" rows="8" />
    </div>

    <button @click="handleSubmit" class="px-4 py-2 text-sm rounded bg-amber-400 text-gray-900 font-medium hover:bg-amber-300">确认添加</button>

    <div v-if="message" :class="['mt-3 px-4 py-2.5 rounded text-sm', message.includes('成功') ? 'bg-green-50 text-green-700' : 'bg-red-50 text-red-600']">
      {{ message }}
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { trainMemory } from '../../../api/sqlQaClient.js'
import SqlQaSelect from './SqlQaSelect.vue'

const type = ref('sql_pair')
const content = ref('')
const question = ref('')
const sql = ref('')
const theme = ref('')
const message = ref('')

async function handleSubmit() {
  message.value = ''
  const body = { type: type.value, content: content.value }
  if (type.value === 'sql_pair') { body.question = question.value; body.sql = sql.value; body.theme = theme.value || undefined }

  try {
    const d = await trainMemory(body)
    if (d.success) {
      message.value = '训练数据已成功注入！'
      content.value = ''
      question.value = ''
      sql.value = ''
      theme.value = ''
    } else {
      message.value = '注入失败: ' + JSON.stringify(d)
    }
  } catch (e) {
    message.value = '请求失败: ' + e.message
  }
}
</script>
