<template>
  <div class="h-full overflow-y-auto bg-slate-50">
    <!-- 面包屑 -->
    <div class="bg-white border-b border-slate-200 px-6 py-3 flex items-center gap-2 text-[13px]">
      <button class="inline-flex items-center gap-1.5 px-2 py-1.5 rounded-lg text-slate-500 hover:text-amber-500 hover:bg-amber-50 transition-colors" @click="router.back()">
        <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 19l-7-7 7-7"/></svg>
        返回收集计划
      </button>
    </div>

    <div class="p-6">
      <!-- 标题 + 进度 -->
      <div class="mb-4">
        <h3 class="text-base font-bold text-slate-800">{{ currentPlan?.name || '加载中...' }} — 计划收集项</h3>
        <div class="flex items-center gap-4 mt-2">
          <!-- 进度条 -->
          <div class="flex items-center gap-2">
            <div class="w-40 h-2 bg-slate-200 rounded-full overflow-hidden">
              <div class="h-full bg-amber-500 rounded-full transition-all" :style="{ width: (currentPlan?.overall_progress || 0) + '%' }"></div>
            </div>
            <span class="text-xs text-slate-500 font-medium">{{ currentPlan?.overall_progress || 0 }}%</span>
          </div>
          <!-- 状态统计 -->
          <span class="text-xs text-slate-400">
            完成{{ currentPlan?.overall_stats?.completed || 0 }} / 待完善{{ currentPlan?.overall_stats?.improving || 0 }} / 缺失{{ planMissingCount }}
            <span v-if="currentPlan?.overall_stats?.overdue" class="text-purple-500 font-medium ml-1">超期{{ currentPlan.overall_stats.overdue }}</span>
          </span>
          <!-- 评估时间 -->
          <span v-if="currentPlan?.evaluated_at" class="text-[10px] text-slate-400">{{ formatEvalTime(currentPlan.evaluated_at) }}</span>
        </div>
        <p class="text-xs text-slate-500 mt-1">收集项由类别×对象自动生成。创建后可新增或删除收集项，不可修改已有项绑定的类别/对象。</p>
      </div>

      <!-- 筛选 + 操作 -->
      <div class="flex items-center gap-3 mb-4 flex-wrap">
        <div class="flex items-center gap-2">
          <CustomSelect v-model="filterCategory" :options="categoryFilterOptions" class="w-[140px]" />
          <CustomSelect v-model="filterTarget" :options="targetFilterOptions" class="w-[140px]" />
        </div>
        <div class="flex-1"></div>
        <button class="btn-ghost text-xs" @click="showAddItemDialog = true"><svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 4v16m8-8H4"/></svg>新增收集项</button>
        <button class="btn-ghost text-xs !text-amber-500 hover:!bg-amber-50" :disabled="selectedItems.length === 0" @click="batchMarkNA">批量标记不适用</button>
      </div>

      <!-- 收集项表格 -->
      <div class="bg-white border border-slate-200 rounded-2xl overflow-hidden">
        <div v-if="loading.plan" class="flex items-center justify-center py-16">
          <div class="animate-spin rounded-full h-6 w-6 border-b-2 border-amber-500"></div>
          <span class="ml-2 text-slate-500 text-sm">加载中...</span>
        </div>
        <table v-else class="w-full">
          <thead class="bg-slate-50 border-b border-slate-100">
            <tr>
              <th class="w-10 px-3 py-2.5 text-center"><input type="checkbox" class="w-4 h-4 accent-amber-500 cursor-pointer" @change="toggleAll"></th>
              <th class="px-4 py-2.5 text-left text-xs font-bold text-slate-600 uppercase">收集项</th>
              <th class="px-4 py-2.5 text-left text-xs font-bold text-slate-600 uppercase">类别</th>
              <th class="px-4 py-2.5 text-left text-xs font-bold text-slate-600 uppercase">对象</th>
              <th class="px-4 py-2.5 text-left text-xs font-bold text-slate-600 uppercase">优先级</th>
              <th class="px-4 py-2.5 text-left text-xs font-bold text-slate-600 uppercase">状态</th>
              <th class="px-4 py-2.5 text-left text-xs font-bold text-slate-600 uppercase">评分</th>
              <th class="px-4 py-2.5 text-left text-xs font-bold text-slate-600 uppercase">文档</th>
              <th class="px-4 py-2.5 text-right text-xs font-bold text-slate-600 uppercase">操作</th>
            </tr>
          </thead>
          <tbody class="divide-y divide-slate-50">
            <template v-for="item in filteredItems" :key="item.id">
              <tr class="hover:bg-amber-50/30 cursor-pointer" :class="{ 'bg-amber-50/20': expandedItems.includes(item.id) }" @click="toggleItemExpand(item.id)">
                <td class="px-3 py-3 text-center" @click.stop><input type="checkbox" class="w-4 h-4 accent-amber-500 cursor-pointer" :checked="selectedItems.includes(item.id)" @change="toggleItemSelect(item.id)"></td>
                <td class="px-4 py-3 text-[13px] font-medium text-slate-800">{{ item.category?.name || item.category_name }} · {{ item.target?.name || item.target_name }}</td>
                <td class="px-4 py-3 text-[13px] text-slate-700">{{ item.category?.name || item.category_name }}</td>
                <td class="px-4 py-3 text-[13px] text-slate-700">{{ item.target?.name || item.target_name }}</td>
                <td class="px-4 py-3">
                  <div class="flex flex-col gap-0.5">
                    <span class="priority-tag" :class="priorityClass(item.priority)">{{ priorityLabel(item.priority) }}</span>
                    <span v-if="item.due_date" class="text-[10px]" :class="_isOverdue(item) ? 'text-purple-500 font-semibold' : 'text-slate-400'">{{ item.due_date }}</span>
                  </div>
                </td>
                <td class="px-4 py-3">
                  <div class="flex items-center gap-1.5">
                    <span class="status-badge" :class="itemStatusClass(item)">{{ itemStatusLabel(item) }}</span>
                    <span v-if="_isOverdue(item)" class="inline-block px-1.5 py-0.5 rounded text-[10px] font-semibold bg-purple-50 text-purple-600">超期</span>
                  </div>
                </td>
                <td class="px-4 py-3">
                  <span v-if="item.overall_score" class="score-sm" :class="scoreSmClass(item.overall_score)">{{ item.overall_score }}</span>
                  <span v-else class="text-slate-300 text-sm">—</span>
                </td>
                <td class="px-4 py-3 text-[13px] text-slate-500">{{ item.documents?.length || item.doc_count || 0 }} 个</td>
                <td class="px-4 py-3 text-right" @click.stop>
                  <div class="flex items-center justify-end gap-1.5">
                    <button class="btn-primary text-xs !bg-blue-500 hover:!bg-blue-600 font-bold py-1 px-3" @click="openDocManager(item)">📄 管理文档</button>
                    <button v-if="item.is_custom" class="btn-ghost text-xs py-1 px-2 text-slate-600 border border-slate-300 rounded hover:bg-slate-100 font-medium" @click.stop="openEditItemDialog(item)">编辑</button>
                    <!-- 自动生成项：不适用/启用 切换 -->
                    <button v-if="!item.is_custom && !item.not_applicable" class="btn-ghost text-xs py-1 px-2 !text-amber-500 hover:!bg-amber-50" @click="handleMarkNA(item)">🚫 不适用</button>
                    <button v-else-if="!item.is_custom && item.not_applicable" class="btn-ghost text-xs py-1 px-2 !text-green-500 hover:!bg-green-50" @click="handleUnmarkNA(item)">✅ 启用</button>
                    <!-- 手动创建项：删除 -->
                    <button v-if="item.is_custom" class="btn-ghost text-xs py-1 px-2 !text-red-400 hover:!bg-red-50" @click="handleDeletePlanItem(item.id)">删除</button>
                  </div>
                </td>
              </tr>
              <!-- 展开行 -->
              <tr v-if="expandedItems.includes(item.id)" class="bg-slate-50">
                <td colspan="9" class="px-4 py-0">
                  <div class="py-3 pl-10 pr-4 space-y-3 animate-[slideDown_.2s_ease]">
                    <!-- 文档类别收集要求 -->
                    <div v-if="item.category_name" class="bg-amber-50 border border-amber-200 rounded-lg p-3.5">
                      <div class="text-[10px] text-amber-600 uppercase tracking-wide font-semibold mb-1.5">📌 文档类别收集要求</div>
                      <div class="text-[13px] font-semibold text-slate-800 mb-1">{{ item.category_name }}</div>
                      <div class="text-[12px] text-slate-600 leading-relaxed whitespace-pre-wrap">{{ item.category_requirement || '（无要求描述）' }}</div>
                    </div>

                    <!-- 收集项评估 -->
                    <div class="bg-white border border-slate-200 rounded-lg p-3.5">
                      <!-- 评估 -->
                      <div class="flex items-center justify-between mb-2">
                        <h5 class="text-[14px] font-semibold text-slate-800">📊 收集项评估</h5>
                        <div class="flex items-center gap-2">
                          <span v-if="item.evaluated_at" class="text-[10px] text-slate-400">{{ formatEvalTime(item.evaluated_at) }}</span>
                          <button class="btn-ghost text-xs py-1 px-2" :disabled="evaluatingItems.has(item.id)" @click="triggerEvaluation(item.id)">
                            <svg v-if="!evaluatingItems.has(item.id)" class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"/></svg>
                            <span v-else class="inline-block w-3 h-3 border-2 border-amber-400 border-t-transparent rounded-full animate-spin"></span>
                            {{ evaluatingItems.has(item.id) ? '评估中' : '刷新' }}
                          </button>
                        </div>
                      </div>
                      <div class="flex items-center gap-5 text-[14px]">
                        <div><span class="text-[10px] text-slate-400 uppercase tracking-wide">综合评分</span><p class="font-bold" :class="scoreTextClass(item.overall_score)">{{ item.overall_score ? item.overall_score + ' / 100' : '—' }}</p></div>
                        <div><span class="text-[10px] text-slate-400 uppercase tracking-wide">完成度</span><p class="font-bold" :class="completionClass(item.overall_status)">{{ completionLabel(item.overall_status) }}</p></div>
                        <div><span class="text-[10px] text-slate-400 uppercase tracking-wide">状态建议</span><span class="status-badge ml-1" :class="itemStatusClass(item)">{{ itemStatusLabel(item) }}</span></div>
                      </div>
                      <div v-if="item.evaluation_detail" class="text-sm mt-2 space-y-1 leading-relaxed">
                        <template v-if="typeof item.evaluation_detail === 'object'">
                          <p v-if="item.evaluation_detail.strengths?.length"><b class="text-emerald-600">优点：</b>{{ item.evaluation_detail.strengths.join('；') }}</p>
                          <p v-if="item.evaluation_detail.weaknesses?.length"><b class="text-red-500">不足：</b>{{ item.evaluation_detail.weaknesses.join('；') }}</p>
                          <p v-if="item.evaluation_detail.suggestions?.length"><b class="text-amber-600">建议：</b>{{ item.evaluation_detail.suggestions.join('；') }}</p>
                        </template>
                        <p v-else class="text-slate-500">{{ item.evaluation_detail }}</p>
                      </div>
                      <p v-else class="text-sm text-slate-400 mt-2">暂无评估数据。</p>
                    </div>

                  </div>
                </td>
              </tr>
            </template>
            <tr v-if="filteredItems.length === 0 && !loading.plan">
              <td colspan="9" class="text-center py-12 text-slate-400 text-sm">暂无收集项</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- 新增收集项弹窗 -->
    <teleport to="body">
      <div v-if="showAddItemDialog" class="modal-overlay" @click.self="showAddItemDialog = false">
        <div class="modal !max-w-3xl">
          <button class="modal-close-x" @click="showAddItemDialog = false">×</button>
          <h3>新增收集项</h3>
          <!-- 上下布局：先文档类别、收集对象，再参数 -->
          <div class="space-y-4">
            <div>
              <label class="form-label">文档类别 <span class="text-red-500">*</span></label>
              <MultiSelect
                v-model="newItem.category_ids"
                :options="categoryOptions"
                label=""
                :required="true"
              />
            </div>
            <div>
              <label class="form-label">收集对象 <span class="text-red-500">*</span></label>
              <MultiSelect
                v-model="newItem.target_ids"
                :options="targetOptions"
                label=""
                :required="true"
              />
            </div>
            <div class="flex gap-3">
              <div class="w-32"><label class="form-label">优先级</label><CustomSelect v-model="newItem.priority" :options="priorityOptions" class="w-full" /></div>
              <div class="flex-1"><label class="form-label">截止时间</label><input v-model="newItem.due_date" type="date" class="form-input"></div>
            </div>
            <p class="text-[11px] text-slate-400">将生成 <b class="text-amber-600">{{ newItem.category_ids.length * newItem.target_ids.length }}</b> 个收集项</p>
          </div>
          <div class="modal-footer"><button class="btn-ghost" @click="showAddItemDialog = false">取消</button><button class="btn-primary" :disabled="!newItem.category_ids.length || !newItem.target_ids.length || addingItem" @click="handleAddItem">{{ addingItem ? '添加中...' : '添加' }}</button></div>
        </div>
      </div>
    </teleport>
    <!-- 编辑收集项弹窗 -->
    <teleport to="body">
      <div v-if="showEditItemDialog" class="modal-overlay" @click.self="showEditItemDialog = false">
        <div class="modal max-w-sm">
          <h3>编辑收集项</h3>
          <div class="form-group"><label class="form-label">收集要求</label><textarea v-model="editItemDialogForm.requirement_override" class="form-textarea" rows="3" :placeholder="editItemDialogForm.category_desc || ''"></textarea></div>
          <div class="form-group flex gap-3">
            <div class="flex-1"><label class="form-label">优先级</label><CustomSelect v-model="editItemDialogForm.priority" :options="priorityOptions" class="w-full" /></div>
            <div class="flex-1"><label class="form-label">截止时间</label><input v-model="editItemDialogForm.due_date" type="date" class="form-input text-sm"></div>
          </div>
          <div class="modal-footer"><button class="btn-ghost" @click="showEditItemDialog = false">取消</button><button class="btn-primary" @click="handleSaveEditItemDialog">保存</button></div>
        </div>
      </div>
    </teleport>

    <!-- 驳回原因弹窗 -->
    <teleport to="body">
      <div v-if="rejectDialog.show" class="modal-overlay" @click.self="rejectDialog.show = false">
        <div class="modal max-w-sm">
          <h3>驳回文档</h3>
          <p class="text-xs text-slate-500 mb-3">驳回「{{ rejectDialog.docName }}」，请填写原因：</p>
          <div class="form-group">
            <textarea v-model="rejectDialog.reason" class="form-textarea" rows="3" placeholder="填写驳回原因（必填）"></textarea>
          </div>
          <div class="modal-footer">
            <button class="btn-ghost" @click="rejectDialog.show = false">取消</button>
            <button class="btn-primary !bg-red-500 hover:!bg-red-600" :disabled="!rejectDialog.reason.trim() || processingDocs.has(rejectDialog.docId)" @click="onReject">{{ processingDocs.has(rejectDialog.docId) ? '处理中...' : '确认驳回' }}</button>
          </div>
        </div>
      </div>
    </teleport>

    <!-- Markdown 文本查看弹窗 -->
    <teleport to="body">
      <div v-if="showTextDialog" class="fixed inset-0 z-50 flex items-center justify-center bg-black/60" @click.self="showTextDialog = null">
        <div class="bg-white rounded-xl shadow-2xl w-full max-w-4xl mx-4 max-h-[85vh] flex flex-col">
          <div class="flex items-center justify-between px-6 py-3 border-b border-gray-200">
            <h3 class="text-base font-bold text-gray-800">{{ showTextDialog.title }}</h3>
            <div class="flex items-center gap-2">
              <button v-if="showTextDialog.isMarkdown" class="text-xs px-2 py-1 rounded" :class="showTextDialog.renderMode === 'markdown' ? 'bg-amber-500 text-white' : 'bg-slate-200 text-slate-600'" @click="showTextDialog.renderMode = 'markdown'">Markdown</button>
              <button v-if="showTextDialog.isMarkdown" class="text-xs px-2 py-1 rounded" :class="showTextDialog.renderMode === 'source' ? 'bg-amber-500 text-white' : 'bg-slate-200 text-slate-600'" @click="showTextDialog.renderMode = 'source'">源码</button>
              <button class="p-1 text-gray-400 hover:text-gray-600" @click="showTextDialog = null">
                <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/></svg>
              </button>
            </div>
          </div>
          <div class="flex-1 overflow-y-auto bg-slate-50 rounded-b-xl p-5">
            <div v-if="showTextDialog.isMarkdown && showTextDialog.renderMode === 'markdown'" class="prose prose-sm max-w-none bg-white rounded-lg p-6 shadow-sm" v-html="renderedMarkdown"></div>
            <pre v-else class="text-sm text-slate-700 whitespace-pre-wrap font-sans leading-relaxed">{{ showTextDialog.text }}</pre>
          </div>
        </div>
      </div>
    </teleport>

    <!-- 文件预览弹窗（PDF/HTML/图片 渲染 + AI 评分报告） -->
    <FilePreview
      v-if="previewDoc"
      :preview-url="previewDoc.previewUrl"
      :doc-name="previewDoc.docName"
      :relevance-score="previewDoc.relevanceScore"
      :quality-score="previewDoc.qualityScore"
      :relevance-remark="previewDoc.relevanceRemark"
      :quality-remark="previewDoc.qualityRemark"
      @close="previewDoc = null"
    />

    <!-- 上传文档弹窗 -->
    <teleport to="body">
      <div v-if="showUploadDialog" class="modal-overlay" @click.self="cancelUpload">
        <div class="modal">
          <h3>上传文档</h3>
          <p class="text-xs text-slate-500 mb-4">上传文件到收集项「{{ uploadTargetItem?.category?.name || uploadTargetItem?.category_name }} · {{ uploadTargetItem?.target?.name || uploadTargetItem?.target_name }}」</p>
          <!-- 文件选择区 -->
          <div class="form-group">
            <label class="form-label">选择文件 <span class="text-red-500">*</span></label>
            <div class="border-2 border-dashed border-slate-200 rounded-xl p-6 text-center hover:border-amber-400 transition-colors cursor-pointer" @click="triggerFileInput" @dragover.prevent @drop.prevent="onDrop">
              <svg class="w-8 h-8 text-slate-300 mx-auto mb-2" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12"/></svg>
              <p class="text-sm text-slate-500">拖拽文件到此处，或<span class="text-amber-500 font-medium">点击选择</span></p>
              <p class="text-xs text-slate-400 mt-1">支持 PDF、Word、Excel、图片等格式，单文件不超过 50MB</p>
              <input ref="fileInputRef" type="file" multiple class="hidden" @change="onFileSelect" accept=".pdf,.doc,.docx,.xls,.xlsx,.ppt,.pptx,.png,.jpg,.jpeg,.bmp,.txt,.csv" />
            </div>
          </div>
          <!-- 已选文件列表 -->
          <div v-if="selectedFiles.length > 0" class="form-group">
            <label class="form-label">已选文件 ({{ selectedFiles.length }})</label>
            <div class="max-h-40 overflow-y-auto space-y-1.5">
              <div v-for="(file, idx) in selectedFiles" :key="idx" class="flex items-center justify-between px-3 py-2 bg-slate-50 rounded-lg text-[13px]">
                <span class="text-slate-700 truncate flex-1">{{ file.name }}</span>
                <span class="text-slate-400 text-xs flex-shrink-0 mx-2">{{ formatFileSize(file.size) }}</span>
                <button class="text-red-400 hover:text-red-600 flex-shrink-0" @click="selectedFiles.splice(idx, 1)"><svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/></svg></button>
              </div>
            </div>
          </div>
          <!-- 上传进度 -->
          <div v-if="uploading" class="flex items-center gap-2 text-sm text-slate-600 py-2">
            <div class="animate-spin rounded-full h-4 w-4 border-b-2 border-amber-500"></div>
            正在上传 {{ uploadProgress }}%...
          </div>
          <p v-if="uploadError" class="text-red-500 text-xs mt-1">{{ uploadError }}</p>
          <div class="modal-footer"><button class="btn-ghost" @click="cancelUpload" :disabled="uploading">取消</button><button class="btn-primary" :disabled="selectedFiles.length === 0 || uploading" @click="handleUpload">{{ uploading ? '上传中...' : '开始上传' }}</button></div>
        </div>
      </div>
    </teleport>

    <!-- 自定义确认弹窗 -->
    <teleport to="body">
      <div v-if="confirmDialog.show" class="modal-overlay" @click.self="confirmDialog.resolve(false)">
        <div class="modal max-w-sm text-center">
          <div class="w-12 h-12 rounded-full bg-amber-100 flex items-center justify-center mx-auto mb-3 text-amber-500">
            <svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-2.5L13.732 4c-.77-.833-1.964-.833-2.732 0L4.082 16.5c-.77.833.192 2.5 1.732 2.5z"/></svg>
          </div>
          <h3 class="text-base font-bold text-slate-800 mb-1">{{ confirmDialog.title }}</h3>
          <p class="text-slate-500 text-[13px] mb-5 whitespace-pre-line">{{ confirmDialog.message }}</p>
          <div class="flex justify-center gap-3">
            <button class="btn-ghost" @click="confirmDialog.resolve(false)">取消</button>
            <button class="btn-primary !bg-red-500 hover:!bg-red-600" @click="confirmDialog.resolve(true)">{{ confirmDialog.okText || '确认' }}</button>
          </div>
        </div>
      </div>
    </teleport>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted, onBeforeUnmount } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useKnowledgeManagement } from '../../composables/knowledge_management/useKnowledgeManagement.js'
import CustomSelect from './components/CustomSelect.vue'
import FilePreview from './components/FilePreview.vue'
import MultiSelect from './components/MultiSelect.vue'
import { getDocumentPreviewUrl } from '../../api/knowledgeManagementClient.js'
import { marked } from 'marked'

const route = useRoute()
const router = useRouter()
const { currentPlan, loading, fetchPlan, fetchPlanItemEvaluation, triggerPlanItemEvaluation, createPlanItem, updatePlanItem, deletePlanItem: removePlanItem, uploadDocuments, deleteDocument: removeDocument, triggerAIReview: triggerAI, submitApproval: submitAppr, publishToRAGFlow: publishRAG, listDocumentVersions: listVersions, categories, targets, fetchCategories, fetchTargets } = useKnowledgeManagement()

const expandedItems = ref([])
const selectedItems = ref([])
const filterCategory = ref('')
const filterTarget = ref('')
const showAddItemDialog = ref(false)
const addingItem = ref(false)
const newItem = ref({ category_ids: [], target_ids: [], priority: 'normal', due_date: '' })

// 上传相关状态
const showUploadDialog = ref(false)
const uploadTargetItem = ref(null)
const selectedFiles = ref([])
const uploading = ref(false)
const uploadProgress = ref(0)
const uploadError = ref('')
let autoRefreshTimer = null
const fileInputRef = ref(null)

// 工作流相关状态
const expandedDocs = ref([])
const processingDocs = ref(new Set()) // 正在执行操作的文档 ID 集合
const evaluatingItems = reactive(new Set()) // 正在评估的收集项 ID 集合
const rejectDialog = ref({ show: false, docId: '', versionId: '', docName: '', reason: '' })
const confirmDialog = ref({ show: false, title: '', message: '', okText: '', resolve: null })
function showConfirm(title, message, okText = '确认') {
  return new Promise(resolve => {
    confirmDialog.value = { show: true, title, message, okText, resolve }
  })
}


// 收集项编辑表单（按 item id 索引）
const editItemForm = ref({})
function initEditForm(items) {
  for (const item of items) {
    if (!editItemForm.value[item.id]) {
      // 归一化 priority 值（后端可能返回中文）
      const p = item.priority || ''
      const priorityMap = { '紧急': 'urgent', '一般': 'normal', '非必需': 'optional' }
      editItemForm.value[item.id] = {
        requirement_override: item.requirement_override || '',
        priority: priorityMap[p] || p || 'normal',
        due_date: item.due_date || '',
      }
    }
  }
}

// 编辑弹窗
const showEditItemDialog = ref(false)
const editItemDialogForm = ref({ id: '', requirement_override: '', priority: 'normal', due_date: '', category_desc: '' })
function openEditItemDialog(item) {
  const p = item.priority || ''
  const priorityMap = { '紧急': 'urgent', '一般': 'normal', '非必需': 'optional' }
  editItemDialogForm.value = {
    id: item.id,
    requirement_override: item.requirement_override || '',
    priority: priorityMap[p] || p || 'normal',
    due_date: item.due_date || '',
    category_desc: item.category?.requirement_desc || '',
  }
  showEditItemDialog.value = true
}
async function handleSaveEditItemDialog() {
  const f = editItemDialogForm.value
  try {
    await updatePlanItem(f.id, { requirement_override: f.requirement_override, priority: f.priority, due_date: f.due_date || null })
    showEditItemDialog.value = false
  } catch (e) { alert('保存失败: ' + e.message) }
}

// PDF 预览状态
const previewDoc = ref(null)  // { previewUrl, docName, relevanceScore, ... }

// Markdown 文本查看弹窗状态
const showTextDialog = ref(null)  // { title, text, isMarkdown, renderMode }
const renderedMarkdown = computed(() => {
  if (!showTextDialog.value?.text) return ''
  return marked(showTextDialog.value.text)
})

const priorityOptions = [{ value: 'urgent', label: '紧急' }, { value: 'normal', label: '一般' }, { value: 'optional', label: '非必需' }]

// 类别/对象选项（从知识库中获取所有类别和对象）
const categoryOptions = computed(() => {
  // 优先使用从知识库获取的类别列表
  if (categories.value && categories.value.length > 0) {
    return categories.value.map(cat => ({ value: cat.id, label: cat.name, sub: cat.requirement_desc?.substring(0, 30) }))
  }
  // 降级：从计划数据中提取
  const items = currentPlan.value?.plan_items || []
  return [...new Map(items.map(i => [i.category?.id || i.category_id, { value: i.category?.id || i.category_id, label: i.category?.name || i.category_name }])).values()]
})
const targetOptions = computed(() => {
  // 优先使用从知识库获取的对象列表
  if (targets.value && targets.value.length > 0) {
    return targets.value.map(tgt => ({ value: tgt.id, label: tgt.name, sub: tgt.target_type }))
  }
  // 降级：从计划数据中提取
  const items = currentPlan.value?.plan_items || []
  return [...new Map(items.map(i => [i.target?.id || i.target_id, { value: i.target?.id || i.target_id, label: i.target?.name || i.target_name }])).values()]
})

const categoryFilterOptions = computed(() => [{ value: '', label: '全部类别' }, ...categoryOptions.value.map(opt => ({ value: opt.label, label: opt.label }))])
const targetFilterOptions = computed(() => [{ value: '', label: '全部对象' }, ...targetOptions.value.map(opt => ({ value: opt.label, label: opt.label }))])

const planItems = computed(() => currentPlan.value?.plan_items || [])

// 计算缺失的收集项数量
const planMissingCount = computed(() => {
  const stats = currentPlan.value?.overall_stats
  // 如果有评估数据，使用评估数据
  if (stats && (stats.completed || stats.improving || stats.missing)) {
    return stats.missing || 0
  }
  // 否则使用收集项总数（所有未评估的都算缺失）
  return planItems.value.length
})

const filteredItems = computed(() => {
  return planItems.value.filter(i => {
    const cid = i.category?.id || i.category_id
    const tid = i.target?.id || i.target_id
    if (filterCategory.value && (i.category?.name || i.category_name) !== filterCategory.value) return false
    if (filterTarget.value && (i.target?.name || i.target_name) !== filterTarget.value) return false
    return true
  })
})

onBeforeUnmount(() => { if (autoRefreshTimer) clearInterval(autoRefreshTimer) })

onMounted(async () => {
  try {
    await fetchPlan(route.params.id)
    const p = currentPlan.value
    if (p?.plan_items) initEditForm(p.plan_items)
    // 加载知识库的类别和对象列表
    if (p?.knowledge_base_id) {
      await Promise.all([fetchCategories(p.knowledge_base_id), fetchTargets(p.knowledge_base_id)])
    }
  } catch (e) { console.error(e) }
})

// 选择与展开
function toggleItemExpand(id) { const idx = expandedItems.value.indexOf(id); if (idx >= 0) expandedItems.value.splice(idx, 1); else expandedItems.value.push(id) }
function toggleItemSelect(id) { const idx = selectedItems.value.indexOf(id); if (idx >= 0) selectedItems.value.splice(idx, 1); else selectedItems.value.push(id) }
function toggleAll(e) { selectedItems.value = e.target.checked ? filteredItems.value.map(i => i.id) : [] }

// 操作
async function handleAddItem() {
  if (!newItem.value.category_ids.length || !newItem.value.target_ids.length) return
  addingItem.value = true
  try {
    const totalCount = newItem.value.category_ids.length * newItem.value.target_ids.length
    let created = 0
    let failed = 0
    // 批量创建收集项（笛卡尔积）
    for (const catId of newItem.value.category_ids) {
      for (const tgtId of newItem.value.target_ids) {
        try {
          await createPlanItem({
            plan_id: currentPlan.value.id,
            category_id: catId,
            target_id: tgtId,
            priority: newItem.value.priority,
            due_date: newItem.value.due_date || null
          })
          created++
        } catch (e) {
          failed++
          console.error('创建收集项失败:', e)
        }
      }
    }
    showAddItemDialog.value = false
    newItem.value = { category_ids: [], target_ids: [], priority: 'normal', due_date: '' }
    await fetchPlan(route.params.id)
    if (failed > 0) {
      alert(`成功创建 ${created} 个收集项，${failed} 个失败`)
    }
  } catch (e) { alert('添加失败: ' + (e.response?.data?.detail || e.message)) }
  finally { addingItem.value = false }
}
async function handleDeletePlanItem(id) { if (!(await showConfirm('删除收集项', '确定删除该收集项及其下的所有文档？此操作不可恢复。', '删除'))) return; try { await removePlanItem(id); await fetchPlan(route.params.id) } catch (e) { alert('删除失败: ' + e.message) } }
async function handleMarkNA(item) {
  if (!(await showConfirm('标记不适用', `确定将"${item.name || item.category_name}"标记为不适用？标记后该收集项将不计入进度和评分。`, '标记不适用'))) return
  try {
    const { markNotApplicable } = await import('../../api/knowledgeManagementClient.js')
    await markNotApplicable(item.id, '')
    await fetchPlan(route.params.id)
  } catch (e) { alert('操作失败: ' + e.message) }
}
async function handleUnmarkNA(item) {
  if (!(await showConfirm('恢复收集项', `确定将"${item.name || item.category_name}"恢复为启用状态？`, '启用'))) return
  try {
    const { unmarkNotApplicable } = await import('../../api/knowledgeManagementClient.js')
    await unmarkNotApplicable(item.id)
    await fetchPlan(route.params.id)
  } catch (e) { alert('操作失败: ' + e.message) }
}
async function batchDeleteItems() {
  if (!(await showConfirm('批量删除', `确定删除选中的 ${selectedItems.value.length} 个收集项？此操作不可恢复。`, '删除'))) return
  let failed = 0
  for (const id of selectedItems.value) { try { await removePlanItem(id) } catch (e) { failed++ } }
  selectedItems.value = []
  await fetchPlan(route.params.id)
  if (failed) alert(failed + ' 个收集项删除失败')
}
async function batchMarkNA() {
  if (!(await showConfirm('批量标记不适用', `确定将选中的 ${selectedItems.value.length} 个收集项标记为不适用？`, '标记不适用'))) return
  let failed = 0
  const { markNotApplicable } = await import('../../api/knowledgeManagementClient.js')
  for (const id of selectedItems.value) { try { await markNotApplicable(id, '') } catch (e) { failed++ } }
  selectedItems.value = []
  await fetchPlan(route.params.id)
  if (failed) alert(failed + ' 个标记失败')
}
async function triggerEvaluation(id) {
  evaluatingItems.add(id)
  try {
    // 使用 POST 触发评估（同步执行），而非 GET 只读
    const resp = await triggerPlanItemEvaluation(id)
    const data = resp?.data || resp
    // 更新本地收集项数据
    const items = currentPlan.value?.plan_items || []
    const idx = items.findIndex(i => i.id === id)
    if (idx >= 0) {
      if (data.overall_score !== undefined) items[idx].overall_score = data.overall_score
      if (data.overall_status !== undefined) items[idx].overall_status = data.overall_status
      if (data.overall_completion !== undefined) items[idx].overall_completion = data.overall_completion
      if (data.evaluation_detail !== undefined) items[idx].evaluation_detail = data.evaluation_detail
      if (data.evaluated_at !== undefined) items[idx].evaluated_at = data.evaluated_at
    }
    // 同时刷新计划进度
    await fetchPlanProgress()
  } catch (e) { alert('评估失败: ' + e.message) }
  finally { evaluatingItems.delete(id) }
}
async function fetchPlanProgress() {
  try {
    const resp = await useKnowledgeManagement().fetchPlanProgress(currentPlan.value.id)
    const data = resp?.data || resp
    if (currentPlan.value) {
      if (data.overall_progress !== undefined) currentPlan.value.overall_progress = data.overall_progress
      if (data.overall_stats !== undefined) currentPlan.value.overall_stats = data.overall_stats
      if (data.overall_analysis !== undefined) currentPlan.value.overall_analysis = data.overall_analysis
      if (data.evaluated_at !== undefined) currentPlan.value.evaluated_at = data.evaluated_at
    }
  } catch {}
}
async function refreshPlanProgress() {
  await fetchPlanProgress()
  // 同时刷新全部 plan 数据以获取最新收集项评估结果
  await fetchPlan(route.params.id)
}
async function handleDeleteDocument(docId) { if (!(await showConfirm('删除文档', '确定删除该文档？此操作不可恢复。', '删除'))) return; try { await removeDocument(docId); await fetchPlan(route.params.id) } catch (e) { alert('删除失败: ' + e.message) } }
// 上传文档
function uploadDocs(item) { uploadTargetItem.value = item; selectedFiles.value = []; uploadError.value = ''; uploadProgress.value = 0; showUploadDialog.value = true }
// 不支持的 PLC 源码文件格式
const UNSUPPORTED_EXTENSIONS = ['.awl', '.stl', '.scl', '.db', '.gxw', '.gpp', '.cxp', '.cx5']

function filterFiles(files) {
  const accepted = []
  const rejected = []
  for (const file of files) {
    const ext = '.' + file.name.split('.').pop()?.toLowerCase()
    if (UNSUPPORTED_EXTENSIONS.includes(ext)) {
      rejected.push(file.name)
    } else {
      accepted.push(file)
    }
  }
  if (rejected.length > 0) {
    alert(`以下文件格式不支持：\n${rejected.join('\n')}\n\nPLC 源码文件无法直接解析，请上传 PLC 图纸 PDF 文件。`)
  }
  return accepted
}

function triggerFileInput() { fileInputRef.value?.click() }

function onFileSelect(e) {
  const files = Array.from(e.target.files || [])
  const filtered = filterFiles(files)
  if (filtered.length) selectedFiles.value = [...selectedFiles.value, ...filtered]
  if (fileInputRef.value) fileInputRef.value.value = ''
}

function onDrop(e) {
  const files = Array.from(e.dataTransfer?.files || [])
  const filtered = filterFiles(files)
  if (filtered.length) selectedFiles.value = [...selectedFiles.value, ...filtered]
}
function cancelUpload() { if (uploading.value) return; showUploadDialog.value = false; selectedFiles.value = []; uploadError.value = '' }
async function handleUpload() {
  if (!selectedFiles.value.length || !uploadTargetItem.value) return
  uploading.value = true; uploadError.value = ''; uploadProgress.value = 0
  let progressTimer = null
  try {
    const formData = new FormData(); selectedFiles.value.forEach(f => formData.append('files', f))
    progressTimer = setInterval(() => { if (uploadProgress.value < 90) uploadProgress.value += 10 }, 300)
    await uploadDocuments(uploadTargetItem.value.id, formData)
    uploadProgress.value = 100
    showUploadDialog.value = false; selectedFiles.value = []
    await fetchPlan(route.params.id)
  } catch (e) { uploadError.value = '上传失败: ' + (e.response?.data?.detail || e.message) }
  finally { if (progressTimer) clearInterval(progressTimer); uploading.value = false }
}
function formatFileSize(bytes) { if (!bytes) return '0 B'; if (bytes < 1024) return bytes + ' B'; if (bytes < 1048576) return (bytes / 1024).toFixed(1) + ' KB'; return (bytes / 1048576).toFixed(1) + ' MB' }

// ========== 工作流操作 ==========
const workflowSteps = [
  { key: 'upload', label: '上传' },
  { key: 'ai_review', label: 'AI审核' },
  { key: 'approval', label: '人工审批' },
  { key: 'published', label: '已发布' },
]

function getDisplayVersion(doc) {
  if (doc.draft_version_id) {
    return {
      versionId: doc.draft_version_id,
      status: doc.draft_status,
      isDraft: true,
    }
  }
  return {
    versionId: doc.current_version_id,
    status: doc.status,
    isDraft: false,
  }
}

function workflowStepClass(doc, stepIndex) {
  const dv = getDisplayVersion(doc)
  const s = dv.status
  const ps = dv.isDraft ? null : doc.publish_status

  let currentStep = 0
  if (s === 'pending' || s === 'ai_processing' || !s) currentStep = 1
  else if (s === 'ai_completed_manual_pending') currentStep = 2
  else if (s === 'approved') currentStep = 2
  else if (s === 'rejected') currentStep = 1
  if (ps === 'published' && !dv.isDraft) currentStep = 3

  if (stepIndex < currentStep) return 'bg-amber-400'
  if (stepIndex === currentStep) return 'bg-amber-500'
  return 'bg-slate-200'
}

// ========== 收集项编辑 ==========
function saveEditItem(itemId) {
  const form = editItemForm.value[itemId]
  if (!form) return
  try {
    updatePlanItem(itemId, {
      requirement_override: form.requirement_override,
      priority: form.priority,
      due_date: form.due_date || null,
    })
  } catch (e) { alert('保存失败: ' + e.message) }
}
function openDocManager(item) {
  router.push('/knowledge-management/items/' + item.id + '/documents?planId=' + currentPlan.value.id)
}

// ========== 工作流 ==========
function toggleDocExpand(docId) {
  const idx = expandedDocs.value.indexOf(docId)
  if (idx >= 0) expandedDocs.value.splice(idx, 1); else expandedDocs.value.push(docId)
}

async function onTriggerAIReview(doc) {
  const versionId = doc.current_version_id
  if (!versionId) { alert('文档无当前版本，无法触发审核'); return }
  processingDocs.value.add(doc.id)
  try { await triggerAI(versionId); await fetchPlan(route.params.id) }
  catch (e) { alert('AI审核触发失败: ' + (e.response?.data?.detail || e.message)) }
  finally { processingDocs.value.delete(doc.id) }
}

async function onApprove(doc) {
  const versionId = doc.current_version_id
  if (!versionId) { alert('文档无当前版本'); return }
  if (!(await showConfirm('审批通过', `确认通过「${doc.display_name || doc.original_filename}」的审核？`, '通过'))) return
  processingDocs.value.add(doc.id)
  try { await submitAppr(versionId, 'approve'); await fetchPlan(route.params.id) }
  catch (e) { alert('审批失败: ' + (e.response?.data?.detail || e.message)) }
  finally { processingDocs.value.delete(doc.id) }
}

function openRejectDialog(doc) {
  rejectDialog.value = {
    show: true,
    docId: doc.id,
    versionId: doc.current_version_id,
    docName: doc.display_name || doc.original_filename || '文档',
    reason: '',
  }
}

async function onReject() {
  const dlg = rejectDialog.value
  if (!dlg.reason.trim() || !dlg.versionId) return
  processingDocs.value.add(dlg.docId)
  try { await submitAppr(dlg.versionId, 'reject', dlg.reason); rejectDialog.value.show = false; await fetchPlan(route.params.id) }
  catch (e) { alert('驳回失败: ' + (e.response?.data?.detail || e.message)) }
  finally { processingDocs.value.delete(dlg.docId) }
}

async function onPublish(doc) {
  const versionId = doc.current_version_id
  if (!versionId) { alert('文档无当前版本'); return }
  if (!(await showConfirm('确认发布', `确认发布「${doc.display_name || doc.original_filename}」到知识库？发布后将在知识库中可检索。`, '发布'))) return
  processingDocs.value.add(doc.id)
  try { await publishRAG(versionId); await fetchPlan(route.params.id) }
  catch (e) { alert('发布失败: ' + (e.response?.data?.detail || e.message)) }
  finally { processingDocs.value.delete(doc.id) }
}

async function onPreviewDoc(doc) {
  if (!doc.current_version_id) return
  const token = localStorage.getItem('auth_token')
  const filename = (doc.original_filename || doc.display_name || '').toLowerCase()

  // Markdown 文件：优先尝试 FilePreview（后端已转换），失败则回退到文本弹窗
  if (filename.endsWith('.md')) {
    try {
      const resp = await fetch(getDocumentPreviewUrl(doc.current_version_id), {
        headers: { Authorization: `Bearer ${token || ''}` }
      })
      const data = await resp.json()
      const convertStatus = data?.data?.convert_status || data?.convert_status
      const url = data?.data?.preview_url || data?.preview_url

      // 后端已转换完成 → 使用 FilePreview（iframe HTML 渲染）
      if (url) {
        previewDoc.value = {
          docName: doc.display_name || doc.original_filename || '文档预览',
          relevanceScore: doc.ai_relevance_score,
          qualityScore: doc.ai_quality_score,
          relevanceRemark: doc.ai_relevance_remark || '',
          qualityRemark: doc.ai_quality_remark || '',
          previewUrl: url,
        }
        return
      }

      // 转换中 / 失败 → 回退到文本弹窗展示 extracted_text
      if (convertStatus === 'processing') {
        const text = doc.extracted_text
        if (text) {
          showTextDialog.value = { title: doc.display_name || doc.original_filename || 'Markdown 文档', text, isMarkdown: true, renderMode: 'markdown' }
          return
        }
        alert('文件正在转换中，请稍后重试')
        return
      }

      // 最终回退：显示提取的文本
      const text = doc.extracted_text
      if (text) {
        showTextDialog.value = { title: doc.display_name || doc.original_filename || 'Markdown 文档', text, isMarkdown: true, renderMode: 'markdown' }
        return
      }
      alert('暂无预览内容')
      return
    } catch (e) { alert('预览失败: ' + e.message); return }
  }

  // 其他文件类型：统一走 FilePreview
  try {
    const resp = await fetch(getDocumentPreviewUrl(doc.current_version_id), {
      headers: { Authorization: `Bearer ${token || ''}` }
    })
    const data = await resp.json()
    const convertStatus = data?.data?.convert_status || data?.convert_status
    const url = data?.data?.preview_url || data?.preview_url
    if (!url) {
      if (convertStatus === 'processing') { alert('文件正在转换中，请稍后重试') }
      else if (convertStatus === 'failed') { alert('文件转换失败，请联系管理员') }
      else { alert('获取预览地址失败') }
      return
    }
    previewDoc.value = {
      docName: doc.display_name || doc.original_filename || '文档预览',
      relevanceScore: doc.ai_relevance_score,
      qualityScore: doc.ai_quality_score,
      relevanceRemark: doc.ai_relevance_remark || '',
      qualityRemark: doc.ai_quality_remark || '',
      previewUrl: url,
    }
  } catch (e) { alert('预览失败: ' + e.message) }
}

function onDownloadDoc(doc) {
  if (!doc.current_version_id) return
  const token = localStorage.getItem('auth_token')
  fetch(`/api/knowledge-management/versions/${doc.current_version_id}/download`, { headers: { Authorization: `Bearer ${token || ''}` } })
    .then(r => { if (!r.ok) throw new Error('下载失败'); return r.blob() })
    .then(b => { const a = document.createElement('a'); a.href = URL.createObjectURL(b); a.download = doc.original_filename || doc.display_name || 'document'; a.click(); URL.revokeObjectURL(a.href); a.remove() })
    .catch(e => alert('下载失败: ' + e.message))
}

function formatDate(dateStr) {
  if (!dateStr) return '—'
  try { return new Date(dateStr).toLocaleDateString('zh-CN', { year: 'numeric', month: '2-digit', day: '2-digit' }) } catch { return dateStr }
}
function formatEvalTime(dateStr) {
  if (!dateStr) return ''
  try { return '评估于 ' + new Date(dateStr).toLocaleString('zh-CN', { year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit' }) } catch { return '' }
}

// 文档类型 / 状态工具（统一放在这里供 template 使用）
function docTypeLabel(t) { const m = { general: '通用', table: '表格', image: '图片', manual: '手册', plc: 'PLC' }; return m[t] || t || '通用' }
function docTypeClass(t) { const m = { general: 'bg-slate-100 text-slate-600', table: 'bg-emerald-50 text-emerald-600', image: 'bg-purple-50 text-purple-600', manual: 'bg-blue-50 text-blue-600', plc: 'bg-amber-50 text-amber-600' }; return m[t] || 'bg-slate-100 text-slate-500' }

function docStatusClass(doc) {
  const s = doc.status
  if (doc.publish_status === 'published' || s === 'published') return 'bg-emerald-50 text-emerald-600'
  if (s === 'approved') return 'bg-blue-50 text-blue-600'
  if (s === 'rejected') return 'bg-red-50 text-red-600'
  if (s === 'ai_completed_manual_pending') return 'bg-amber-50 text-amber-600'
  if (s === 'ai_processing') return 'bg-purple-50 text-purple-600'
  return 'bg-slate-100 text-slate-500'
}
function docStatusLabel(doc) {
  const s = doc.status
  if (doc.convert_status === 'processing' || doc.extract_status === 'processing') return '内容提取中'
  if (doc.publish_status === 'published' || s === 'published') return '已发布'
  if (s === 'approved') return '待发布'
  if (s === 'rejected') return '已驳回'
  if (s === 'ai_completed_manual_pending') return '待审核'
  if (s === 'ai_processing') return 'AI审核中'
  return '待处理'
}

// 工具函数
function priorityClass(p) { const v = (p || "").toLowerCase(); return v === "urgent" || v === "紧急" ? "bg-red-50 text-red-600" : v === "normal" || v === "一般" ? "bg-amber-50 text-amber-600" : "bg-slate-100 text-slate-500" }
function priorityLabel(p) { const v = (p || "").toLowerCase(); return v === "urgent" || v === "紧急" ? "紧急" : v === "normal" || v === "一般" ? "一般" : "非必需" }

function _isOverdue(item) {
  if (!item.due_date) return false
  if (item.overall_status === 'completed') return false
  // 兼容各种日期格式（ISO、yyyy-MM-dd 等）
  const due = new Date(item.due_date)
  if (isNaN(due.getTime())) return false
  // 只比较日期部分（忽略时间），避免时区问题
  const today = new Date()
  today.setHours(0, 0, 0, 0)
  due.setHours(0, 0, 0, 0)
  return due < today
}
function itemStatusClass(item) {
  if (_isOverdue(item)) return 'bg-red-100 text-red-700 font-bold'
  const s = item.overall_status || (item.overall_score ? (item.overall_score >= 85 ? 'completed' : item.overall_score >= 60 ? 'improving' : 'missing') : 'missing')
  return s === 'completed' ? 'bg-emerald-50 text-emerald-600' : s === 'improving' ? 'bg-amber-50 text-amber-600' : 'bg-red-50 text-red-600'
}
function itemStatusLabel(item) {
  if (_isOverdue(item)) return '已超期 ⚠'
  const s = item.overall_status; return s === 'completed' ? '已完成' : s === 'improving' ? '待完善' : s === 'missing' ? '缺失' : item.overall_status || '缺失'
}

function scoreSmClass(s) { if (!s) return ''; return s >= 85 ? 'bg-emerald-50 text-emerald-600' : s >= 60 ? 'bg-amber-50 text-amber-600' : 'bg-red-50 text-red-600' }
function scoreTextClass(s) { if (!s) return 'text-slate-300'; return s >= 85 ? 'text-emerald-600' : s >= 60 ? 'text-amber-600' : 'text-red-600' }
function completionClass(s) { if (!s) return 'text-slate-400'; return s === 'completed' ? 'text-emerald-600' : s === 'improving' ? 'text-amber-600' : 'text-red-600' }
function completionLabel(s) { if (!s) return '未知'; return s === 'completed' ? '满足要求' : s === 'improving' ? '内容不完整' : '未收集' }
</script>

<style scoped>
.btn-primary { @apply inline-flex items-center gap-1.5 px-4 py-2 bg-amber-500 text-white text-[13px] font-medium rounded-lg hover:bg-amber-600 transition-colors disabled:opacity-50 disabled:cursor-not-allowed; }
.btn-ghost { @apply inline-flex items-center gap-1 px-3 py-1.5 text-slate-500 text-[13px] font-medium rounded-lg hover:bg-slate-100 transition-colors disabled:opacity-50; }
.btn-workflow { @apply inline-flex items-center gap-1 font-medium transition-colors disabled:opacity-40 disabled:cursor-not-allowed; }
.score-sm { @apply inline-flex items-center justify-center w-6 h-6 rounded-full text-[11px] font-bold; }
.priority-tag { @apply inline-block px-1.5 py-0.5 rounded text-[11px] font-semibold; }
.status-badge { @apply inline-block px-1.5 py-0.5 rounded text-[11px] font-semibold; }
.doc-type-tag { @apply inline-block px-2 py-0.5 rounded text-[10px] font-semibold; }
.form-group { @apply mb-3.5; }
.form-label { @apply block text-[13px] font-medium text-slate-700 mb-1; }
.form-input, .form-textarea { @apply w-full px-3.5 py-2.5 border border-slate-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-amber-400/30 focus:border-amber-400 transition-shadow; }
.form-textarea { @apply resize-none; }
.modal-overlay { @apply fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm; }
.modal { @apply bg-white rounded-2xl shadow-xl w-full max-w-lg mx-4 p-6 animate-[modalIn_.2s_ease] max-h-[90vh] overflow-y-auto relative; }
.modal h3 { @apply text-base font-bold text-slate-800 mb-4 pr-8; }
.modal-close-x { @apply absolute top-3 right-3 w-8 h-8 flex items-center justify-center text-slate-400 hover:text-slate-700 hover:bg-slate-100 rounded-full text-2xl leading-none cursor-pointer; }
.modal { @apply bg-white rounded-2xl shadow-xl w-full max-w-md mx-4 p-6 animate-[modalIn_.2s_ease] max-h-[90vh] overflow-y-auto; }
.modal h3 { @apply text-base font-bold text-slate-800 mb-4; }
.modal-footer { @apply flex justify-end gap-3 mt-5; }
@keyframes modalIn { from { opacity: 0; transform: scale(.96) translateY(-8px); } to { opacity: 1; transform: scale(1) translateY(0); } }
@keyframes slideDown { from { opacity: 0; transform: translateY(-4px); } }

/* 日期选择器美化 */
input[type="date"].form-input {
  color-scheme: light;
  cursor: pointer;
  position: relative;
}
input[type="date"].form-input::-webkit-calendar-picker-indicator {
  cursor: pointer;
  opacity: 0.6;
  transition: opacity 0.15s;
}
input[type="date"].form-input:hover::-webkit-calendar-picker-indicator {
  opacity: 1;
}

/* 弹窗精简滚动条 */
.modal::-webkit-scrollbar {
  width: 4px;
}
.modal::-webkit-scrollbar-track {
  background: transparent;
}
.modal::-webkit-scrollbar-thumb {
  background: rgb(0 0 0 / 0.12);
  border-radius: 2px;
}
.modal::-webkit-scrollbar-thumb:hover {
  background: rgb(0 0 0 / 0.22);
}
.modal {
  scrollbar-width: thin;
  scrollbar-color: rgb(0 0 0 / 0.12) transparent;
}
</style>
