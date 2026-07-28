import { ref, readonly } from 'vue'

const TOKEN_KEY = 'auth_token'
const USER_KEY = 'auth_user'

function loadUser() {
  try {
    const raw = localStorage.getItem(USER_KEY)
    return raw ? JSON.parse(raw) : null
  } catch {
    return null
  }
}

// 模块级状态（单例）
const token = ref(localStorage.getItem(TOKEN_KEY) || null)
const user = ref(loadUser())
const isAuthReady = ref(true) // 路由守卫已保证认证，无需异步校验

export function useSqlQaAuth() {
  function login(newToken, newUser) {
    localStorage.setItem(TOKEN_KEY, newToken)
    localStorage.setItem(USER_KEY, JSON.stringify(newUser))
    token.value = newToken
    user.value = newUser
  }

  function logout() {
    localStorage.removeItem(TOKEN_KEY)
    localStorage.removeItem(USER_KEY)
    token.value = null
    user.value = null
  }

  return {
    token: readonly(token),
    user: readonly(user),
    isAuthenticated: () => !!token.value,
    isAuthReady: readonly(isAuthReady),
    login,
    logout,
  }
}
