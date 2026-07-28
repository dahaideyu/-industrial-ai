<template>
  <div class="grid min-h-screen place-items-center bg-slate-950 px-4 text-white font-body">
    <div class="w-full max-w-md">
      <div class="mb-8 flex items-center gap-3">
        <div class="grid h-12 w-12 place-items-center rounded-md bg-amber-400 text-base font-black text-slate-950">
          AI
        </div>
        <div>
          <h1 class="font-headline text-xl font-semibold leading-tight">数智资产管理系统</h1>
          <p class="mt-0.5 text-xs text-slate-400">Industrial Intelligence</p>
        </div>
      </div>

      <div class="rounded-xl border border-white/10 bg-slate-900/80 p-8 shadow-2xl">
        <h2 class="font-headline text-lg font-semibold">登录</h2>
        <p class="mt-1 text-sm text-slate-400">请输入账号信息以访问平台</p>

        <form class="mt-6 space-y-5" @submit.prevent="onSubmit">
          <div>
            <label class="mb-1.5 block text-xs font-semibold uppercase tracking-[0.14em] text-slate-400">
              用户名
            </label>
            <input
              v-model.trim="username"
              type="text"
              autocomplete="username"
              autofocus
              class="w-full rounded-md border border-white/10 bg-slate-950/60 px-3.5 py-2.5 text-sm text-white placeholder:text-slate-500 outline-none transition-colors focus:border-amber-400"
              placeholder="请输入用户名"
            />
          </div>

          <div>
            <label class="mb-1.5 block text-xs font-semibold uppercase tracking-[0.14em] text-slate-400">
              密码
            </label>
            <input
              v-model="password"
              type="password"
              autocomplete="current-password"
              class="w-full rounded-md border border-white/10 bg-slate-950/60 px-3.5 py-2.5 text-sm text-white placeholder:text-slate-500 outline-none transition-colors focus:border-amber-400"
              placeholder="请输入密码"
            />
          </div>

          <p v-if="error" class="rounded-md border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-sm text-rose-300">
            {{ error }}
          </p>

          <button
            type="submit"
            :disabled="loading || !username || !password"
            class="flex w-full items-center justify-center rounded-md bg-amber-400 px-4 py-2.5 text-sm font-bold text-slate-950 transition-colors hover:bg-amber-300 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {{ loading ? '登录中…' : '登录' }}
          </button>
        </form>
      </div>

      <p class="mt-6 text-center text-xs text-slate-500">Industrial Intelligence Platform</p>
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { login as loginApi } from '../api/client'

const router = useRouter()
const route = useRoute()

const username = ref('')
const password = ref('')
const loading = ref(false)
const error = ref('')

async function onSubmit() {
  if (loading.value) return
  error.value = ''
  loading.value = true
  try {
    const res = await loginApi({ username: username.value, password: password.value })
    const data = res?.data || {}
    if (!data.token) {
      throw new Error(res?.msg || '登录失败')
    }
    localStorage.setItem('auth_token', data.token)
    localStorage.setItem('auth_user', JSON.stringify(data.user || {}))
    const redirect = typeof route.query.redirect === 'string' ? route.query.redirect : '/dashboard'
    router.replace(redirect)
  } catch (e) {
    error.value = e.message || '用户名或密码错误'
  } finally {
    loading.value = false
  }
}
</script>
