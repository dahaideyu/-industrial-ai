<template>
  <div class="p-8 max-w-[1440px] mx-auto text-center">
    <div class="bg-white rounded-xl p-12 border border-gray-100 shadow-sm">
      <div class="text-6xl mb-4">🚧</div>
      <h1 class="font-headline text-4xl font-bold text-on-surface mb-2">404</h1>
      <p class="text-secondary mb-8">页面不存在或已被移除</p>
      <router-link
        to="/dashboard"
        class="inline-block px-6 py-3 bg-amber-400 text-on-primary-container font-bold rounded-lg hover:bg-amber-500 transition-colors"
      >
        返回 Dashboard
      </router-link>
    </div>
  </div>
</template>
