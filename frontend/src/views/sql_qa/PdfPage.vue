<template>
  <div class="p-6">
    <div class="flex items-center gap-4 mb-4">
      <router-link to="/sql-qa" class="text-sm text-amber-500 hover:underline">&larr; 返回问答</router-link>
      <h2 class="text-lg font-semibold text-gray-800">{{ docName || 'PDF 查看器' }}</h2>
    </div>
    <SqlQaPdfErrorBoundary>
      <SqlQaPdfViewer
        :url="pdfUrl"
        :highlight-page="highlightPage"
        :highlight-positions="highlightPositions"
      />
    </SqlQaPdfErrorBoundary>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import SqlQaPdfViewer from './components/SqlQaPdfViewer.vue'
import SqlQaPdfErrorBoundary from './components/SqlQaPdfErrorBoundary.vue'

const route = useRoute()

const datasetId = computed(() => route.query.dataset_id || '')
const documentId = computed(() => route.query.document_id || '')
const docName = computed(() => route.query.name || '')
const highlightPage = computed(() => parseInt(route.query.page) || null)
const highlightPositions = computed(() => {
  try { return JSON.parse(route.query.positions || '[]') } catch { return [] }
})
const pdfUrl = computed(() => {
  return `/api/ragflow/document-download?dataset_id=${datasetId.value}&document_id=${documentId.value}`
})
</script>
