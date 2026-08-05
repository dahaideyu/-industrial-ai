/**
 * 共享 Axios 客户端工厂。
 *
 * 此前 client.js / sqlQaClient.js / knowledgeManagementClient.js 各自
 * 重复了同一套"取 token → 加 Bearer 头 → 捕获 401 → reject Error"逻辑
 * （4 份副本）。本工厂统一为一份，各模块只需传配置。
 *
 * @param {Object} opts
 * @param {string} opts.baseURL       - API 基地址，默认 '/api'
 * @param {number} opts.timeout       - 超时（ms），默认 60000
 * @param {boolean} opts.unwrap       - 是否自动解包 {code, data} → data，默认 false
 * @param {boolean} opts.handle401    - 是否处理 401 跳转登录，默认 true
 * @param {Object} opts.extra         - 传给 axios.create 的额外配置（如 paramsSerializer）
 * @returns {import('axios').AxiosInstance}
 */
import axios from 'axios'

export function createApiClient({
  baseURL = '/api',
  timeout = 60000,
  unwrap = false,
  handle401 = true,
  extra = {},
} = {}) {
  const instance = axios.create({
    baseURL,
    timeout,
    headers: { 'Content-Type': 'application/json' },
    ...extra,
  })

  // 请求拦截器：自动附加登录令牌（全项目唯一一份）
  instance.interceptors.request.use((config) => {
    const token = localStorage.getItem('auth_token')
    if (token) {
      config.headers = config.headers || {}
      config.headers.Authorization = `Bearer ${token}`
    }
    return config
  })

  // 响应拦截器
  instance.interceptors.response.use(
    (res) => {
      const body = res.data
      if (unwrap && body && typeof body === 'object' && 'code' in body && 'data' in body) {
        if (body.code === 200) return body.data
        return Promise.reject(new Error(body.msg || '请求失败'))
      }
      return body
    },
    (err) => {
      const status = err.response?.status
      const url = err.config?.url || ''

      // 401：清理本地状态并跳转登录页（登录接口自身的 401 不跳转）
      if (handle401 && status === 401 && !url.includes('/auth/login')) {
        localStorage.removeItem('auth_token')
        localStorage.removeItem('auth_user')
        if (window.location.pathname !== '/login') {
          window.location.assign('/login')
        }
      }

      const msg = err.response?.data?.detail || err.response?.data?.msg || err.message || '请求失败'
      return Promise.reject(new Error(msg))
    }
  )

  return instance
}
