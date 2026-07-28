import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import obfuscator from 'rollup-plugin-javascript-obfuscator'
import { fileURLToPath, URL } from 'node:url'

export default defineConfig({
  plugins: [
    vue(),
    // 生产构建混淆业务代码。
    // 从 vite-plugin-javascript-obfuscator 切换到 rollup-plugin-javascript-obfuscator：
    // 前者 v3.1.0 已停止维护，与 Vite 6 不兼容，会破坏动态 import chunk 生成。
    // ignoreImports: true 跳过 import 语句混淆，确保懒加载路由正常工作。
    {
      ...obfuscator({
        options: {
          compact: true,
          identifierNamesGenerator: 'hexadecimal',
          stringArray: true,
          stringArrayEncoding: ['base64'],
          stringArrayThreshold: 0.75,
          splitStrings: true,
          splitStringsChunkLength: 10,
          numbersToExpressions: true,
          simplify: true,
          ignoreImports: true,  // 关键：避免破坏 Vue 懒加载路由
        },
        exclude: [/node_modules/, /vendor-.*\.js$/],
      }),
      apply: 'build',
      enforce: 'post',
    },
  ],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  server: {
    port: 5173,
    allowedHosts: true,
    proxy: {
      // Repair suggestion → port 8000
      '/api/repair-suggestion': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
      '/api/repair-order-scoring': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
      // 统一后端 → port 9300（含主应用 + SQL-QA 模块）
      '/api': {
        target: 'http://localhost:9300',
        changeOrigin: true,
      },
      '/api/ws': {
        target: 'ws://localhost:9300',
        ws: true,
        changeOrigin: true,
      },
    }
  },
  build: {
    sourcemap: false,
    chunkSizeWarningLimit: 600,
    rollupOptions: {
      output: {
        manualChunks: {
          vendor: ['vue', 'vue-router', 'axios', 'echarts', 'marked', 'pdfjs-dist', 'xlsx'],
        },
      },
    },
  }
})
