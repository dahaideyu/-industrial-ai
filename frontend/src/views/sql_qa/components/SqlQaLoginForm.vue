<template>
  <div class="flex items-center justify-center min-h-[400px] p-8">
    <div class="w-full max-w-sm bg-white rounded-2xl shadow-lg border border-gray-100 p-8">
      <div class="text-center mb-8">
        <div class="w-14 h-14 mx-auto mb-4 rounded-xl bg-amber-400 flex items-center justify-center text-gray-900 text-xl font-bold">AI</div>
        <h2 class="text-xl font-semibold text-gray-800">数据智能问答平台</h2>
        <p class="text-sm text-gray-500 mt-1">请登录后使用问答功能</p>
      </div>
      <form @submit.prevent="handleSubmit" class="space-y-4">
        <div>
          <label class="block text-sm font-medium text-gray-700 mb-1">用户名</label>
          <input
            v-model="username"
            type="text"
            required
            autofocus
            class="w-full px-4 py-3 border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-amber-400 focus:border-transparent text-gray-800 text-sm"
          />
        </div>
        <div>
          <label class="block text-sm font-medium text-gray-700 mb-1">密码</label>
          <input
            v-model="password"
            type="password"
            required
            class="w-full px-4 py-3 border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-amber-400 focus:border-transparent text-gray-800 text-sm"
          />
        </div>
        <div v-if="error" class="text-sm text-red-500 text-center">{{ error }}</div>
        <button
          type="submit"
          :disabled="loading"
          class="w-full py-2.5 rounded-lg font-medium transition-colors"
          :class="loading ? 'bg-gray-300 text-gray-500 cursor-not-allowed' : 'bg-amber-400 text-gray-900 hover:bg-amber-300'"
        >
          {{ loading ? '登录中...' : '登 录' }}
        </button>
      </form>
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { authLogin } from '../../../api/sqlQaClient.js'

const emit = defineEmits(['loginSuccess'])

const username = ref('admin')
const password = ref('admin')
const error = ref('')
const loading = ref(false)

async function handleSubmit() {
  error.value = ''
  loading.value = true
  try {
    const data = await authLogin(username.value, password.value)
    emit('loginSuccess', data.token, data.user)
  } catch (e) {
    error.value = e.message || '登录失败'
  } finally {
    loading.value = false
  }
}
</script>
