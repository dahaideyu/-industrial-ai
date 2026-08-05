/**
 * ESLint 配置 — Vue 3 + Vite 项目。
 *
 * 规则策略：先保证全项目跑通（warn 为主），逐步收紧到 error。
 * 重点拦截：未使用变量、console 遗留、空 catch、v-html 未加 sanitize。
 */
module.exports = {
  root: true,
  env: {
    browser: true,
    es2022: true,
    node: true,
  },
  extends: [
    'eslint:recommended',
    'plugin:vue/vue3-recommended',
  ],
  parserOptions: {
    ecmaVersion: 'latest',
    sourceType: 'module',
  },
  rules: {
    // ── 基础 ──
    'no-console': process.env.NODE_ENV === 'production' ? 'warn' : 'off',
    'no-debugger': 'warn',
    'no-unused-vars': ['warn', { argsIgnorePattern: '^_', varsIgnorePattern: '^_' }],
    'no-empty': ['warn', { allowEmptyCatch: false }],

    // ── Vue ──
    'vue/multi-word-component-names': 'off',
    'vue/no-v-html': 'warn',
    'vue/no-unused-components': 'warn',
    'vue/no-unused-vars': 'warn',
    'vue/require-default-prop': 'off',
    'vue/attributes-order': 'off',
    'vue/v-slot-style': 'off',
  },
  // 注意：eslintrc 格式的键名是 ignorePatterns；flat config 才叫 ignores，
  // 写成 ignores 会导致 ESLint 启动即报 "Unexpected top-level property"。
  ignorePatterns: [
    'dist/**',
    'node_modules/**',
    '.vite/**',
    'public/**',
    '*.cjs',
  ],
}
