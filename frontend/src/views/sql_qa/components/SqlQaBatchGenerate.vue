<template>
  <div class="flex gap-4 h-full min-h-0">
    <!-- ========== 左侧：生成配置 ========== -->
    <div class="w-96 flex-shrink-0 flex flex-col gap-4 overflow-y-auto pr-1">
      <!-- 主题 -->
      <div>
        <label class="block text-sm font-medium text-gray-700 mb-1.5">训练主题</label>
        <input
          v-model="theme"
          type="text"
          placeholder="例如：设备维修、设备状态、设备效率"
          maxlength="50"
          class="w-full text-sm border border-gray-200 rounded-lg px-3.5 py-2.5 bg-white text-gray-700 placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-amber-400/30 focus:border-amber-400 transition-shadow"
        />
      </div>

      <!-- 数据来源表 -->
      <div>
        <label class="block text-sm font-medium text-gray-700 mb-1.5">数据来源表</label>
        <!-- 已选标签 + 添加按钮 -->
        <div class="flex flex-wrap gap-1.5 mb-2">
          <span
            v-for="t in selectedTables"
            :key="t"
            class="inline-flex items-center gap-1 px-2 py-1 text-xs rounded-md bg-amber-50 border border-amber-200 text-amber-700"
          >
            {{ t }}
            <button @click="removeTable(t)" class="text-amber-400 hover:text-amber-600 ml-0.5">
              <svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2.5" d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
          </span>
          <button
            @click="openTableModal"
            class="inline-flex items-center gap-1 px-2 py-1 text-xs rounded-md border border-dashed border-gray-300 text-gray-500 hover:border-amber-400 hover:text-amber-600 transition-colors"
          >
            <svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 4v16m8-8H4" />
            </svg>
            添加表
          </button>
          <span v-if="selectedTables.length === 0" class="text-xs text-gray-400 self-center">暂未选择</span>
        </div>
        <p class="text-xs text-gray-400">已选 {{ selectedTables.length }} 张表</p>
      </div>

      <!-- 表选择弹窗 -->
      <Teleport to="body">
        <div v-if="showTableModal" class="fixed inset-0 z-50 flex items-center justify-center bg-black/40" @click.self="showTableModal = false">
          <div class="bg-white rounded-xl shadow-xl border border-gray-200 w-full max-w-2xl mx-4" style="height: 70vh; max-height: 700px;">
            <!-- 弹窗标题栏 -->
            <div class="flex items-center justify-between px-5 py-4 border-b border-gray-100">
              <h3 class="text-base font-semibold text-gray-800">选择数据来源表</h3>
              <button @click="showTableModal = false" class="text-gray-400 hover:text-gray-600">
                <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
                </svg>
              </button>
            </div>

            <div class="flex flex-col h-full" style="height: calc(100% - 57px);">
              <!-- 已选区域 -->
              <div v-if="modalSelected.length > 0" class="px-5 pt-4 pb-2 border-b border-gray-50">
                <p class="text-xs text-gray-400 mb-2">已选择（{{ modalSelected.length }} 张）</p>
                <div class="flex flex-wrap gap-1.5">
                  <span
                    v-for="t in modalSelected"
                    :key="t"
                    class="inline-flex items-center gap-1 px-2.5 py-1 text-sm rounded-md bg-amber-50 border border-amber-200 text-amber-700"
                  >
                    {{ t }}
                    <button @click="toggleTableInModal(t)" class="text-amber-400 hover:text-amber-600 ml-0.5">
                      <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2.5" d="M6 18L18 6M6 6l12 12" />
                      </svg>
                    </button>
                  </span>
                </div>
              </div>

              <!-- 搜索框 -->
              <div class="px-5 py-3">
                <div class="relative">
                  <svg class="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
                  </svg>
                  <input
                    v-model="tableSearch"
                    type="text"
                    placeholder="搜索表名..."
                    class="w-full text-sm border border-gray-200 rounded-lg pl-9 pr-3.5 py-2.5 bg-white text-gray-700 placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-amber-400/30 focus:border-amber-400 transition-shadow"
                  />
                </div>
              </div>

              <!-- 表列表 -->
              <div class="flex-1 overflow-y-auto px-5 pb-4">
                <div class="border border-gray-200 rounded-lg divide-y divide-gray-100">
                  <label
                    v-for="t in filteredTables"
                    :key="t.name"
                    class="flex items-center gap-3 px-4 py-3 hover:bg-gray-50 cursor-pointer text-sm"
                  >
                    <input
                      type="checkbox"
                      :value="t.name"
                      :checked="modalSelected.includes(t.name)"
                      @change="toggleTableInModal(t.name)"
                      class="w-4 h-4 text-amber-500 border-gray-300 rounded focus:ring-amber-400/30"
                    />
                    <div class="flex-1 min-w-0">
                      <span class="text-gray-700 font-medium">{{ t.name }}</span>
                      <span v-if="t.comment" class="text-gray-400 ml-2 text-xs">({{ t.comment }})</span>
                    </div>
                  </label>
                  <div v-if="filteredTables.length === 0" class="px-4 py-8 text-sm text-gray-400 text-center">
                    {{ tableSearch ? '无匹配的表' : '加载中...' }}
                  </div>
                </div>
              </div>

              <!-- 底部操作栏 -->
              <div class="flex items-center justify-between px-5 py-3 border-t border-gray-100">
                <div class="flex gap-2 text-xs">
                  <button @click="selectAllInModal" class="text-amber-600 hover:text-amber-700">全选</button>
                  <button @click="invertInModal" class="text-gray-400 hover:text-gray-600">反选</button>
                </div>
                <button
                  @click="confirmTableSelection"
                  class="px-5 py-2 text-sm font-medium text-white bg-amber-500 rounded-lg hover:bg-amber-600 transition-colors"
                >确认选择</button>
              </div>
            </div>
          </div>
        </div>
      </Teleport>

      <!-- 表结构补充说明 -->
      <div>
        <label class="block text-sm font-medium text-gray-700 mb-1.5">表结构补充说明</label>
        <textarea
          v-model="schemaSupplement"
          rows="5"
          maxlength="5000"
          placeholder="补充表/列注释中未体现的业务含义，例如：&#10;repair_status 字段含义：0=待维修, 1=维修中, 2=已完成, 3=已关闭&#10;line_id 关联 sys_line 表的产线"
          class="w-full text-sm border border-gray-200 rounded-lg px-3.5 py-2.5 bg-white text-gray-700 placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-amber-400/30 focus:border-amber-400 transition-shadow resize-none"
        ></textarea>
      </div>

      <!-- 示例SQL -->
      <div>
        <label class="block text-sm font-medium text-gray-700 mb-1.5">示例SQL</label>
        <textarea
          v-model="exampleSql"
          rows="6"
          maxlength="10000"
          placeholder="帮助大模型理解表关联关系，例如：&#10;SELECT r.*, l.name as line_name&#10;FROM dev_repair_order r&#10;LEFT JOIN sys_line l ON r.line_id = l.id&#10;WHERE r.del_flag = 0"
          class="w-full text-sm border border-gray-200 rounded-lg px-3.5 py-2.5 bg-white text-gray-700 placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-amber-400/30 focus:border-amber-400 transition-shadow resize-none font-mono"
        ></textarea>
      </div>

      <!-- 训练数量 -->
      <div>
        <label class="block text-sm font-medium text-gray-700 mb-1.5">训练数量（上限，AI判断无价值场景会少生成）</label>
        <div class="flex flex-wrap gap-2">
          <button
            v-for="c in [50, 100, 200]"
            :key="c"
            @click="count = c"
            :class="[
              'px-4 py-2 text-sm rounded-lg border transition-colors',
              count === c
                ? 'bg-amber-400 border-amber-400 text-gray-900 font-medium'
                : 'bg-white border-gray-200 text-gray-600 hover:border-gray-300'
            ]"
          >{{ c }} 条</button>
          <div class="flex items-center gap-1">
            <input
              v-model.number="customCount"
              type="number"
              min="10"
              max="500"
              placeholder="自定义"
              class="w-20 text-sm border border-gray-200 rounded-lg px-3 py-2 bg-white text-gray-700 focus:outline-none focus:ring-2 focus:ring-amber-400/30 focus:border-amber-400 transition-shadow"
              @input="onCustomCountInput"
            />
          </div>
        </div>
      </div>

      <!-- 生成按钮 -->
      <button
        @click="startGenerate"
        :disabled="!canGenerate || isGenerating"
        class="w-full py-2.5 text-sm font-medium rounded-lg transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
        :class="isGenerating ? 'bg-gray-300 text-gray-500' : 'bg-amber-400 text-gray-900 hover:bg-amber-500'"
      >
        <span v-if="isGenerating" class="flex items-center justify-center gap-2">
          <svg class="animate-spin w-4 h-4" fill="none" viewBox="0 0 24 24">
            <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4" />
            <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
          </svg>
          生成中...
        </span>
        <span v-else>开始生成</span>
      </button>

      <!-- 进度显示 -->
      <div v-if="isGenerating && jobProgress" class="bg-amber-50 border border-amber-200 rounded-lg p-3 text-sm">
        <div class="flex items-center justify-between mb-1.5">
          <span class="text-gray-600">生成进度</span>
          <span class="text-amber-700 font-medium">{{ jobProgress.generated }}/{{ jobProgress.target_count }} 条</span>
        </div>
        <div class="w-full bg-amber-200 rounded-full h-2">
          <div
            class="bg-amber-500 h-2 rounded-full transition-all duration-500"
            :style="{ width: progressPercent + '%' }"
          ></div>
        </div>
        <div v-if="jobProgress.errors && jobProgress.errors.length > 0" class="mt-2 text-xs text-red-500">
          <p v-for="(e, i) in jobProgress.errors.slice(-3)" :key="i" class="truncate">{{ e }}</p>
        </div>
      </div>
    </div>

    <!-- ========== 右侧：审核队列 ========== -->
    <div class="flex-1 min-w-0 flex flex-col bg-white rounded-xl border border-gray-200 overflow-hidden">
      <!-- 顶部工具栏 -->
      <div class="flex items-center gap-3 px-4 py-3 border-b border-gray-100 bg-gray-50/50 flex-shrink-0">
        <span class="text-sm text-gray-500 flex-shrink-0">审核主题:</span>
        <SqlQaSelect
          v-model="activeTheme"
          :options="themeOptions"
          widthClass="w-56"
          @update:modelValue="onThemeChange"
        />

        <div class="flex-1"></div>

        <label class="flex items-center gap-1.5 text-sm text-gray-500 cursor-pointer select-none">
          <input type="checkbox" v-model="selectAll" @change="onSelectAll" class="w-4 h-4 text-amber-500 border-gray-300 rounded" />
          全选
        </label>
        <span v-if="selectedIds.length > 0" class="text-xs text-gray-400">已选 {{ selectedIds.length }} 项</span>

        <button
          @click="batchApprove"
          :disabled="selectedIds.length === 0"
          class="px-3 py-1.5 text-xs font-medium rounded-md bg-green-500 text-white hover:bg-green-600 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
        >批量通过</button>
        <button
          @click="batchDelete"
          :disabled="selectedIds.length === 0"
          class="px-3 py-1.5 text-xs font-medium rounded-md bg-red-500 text-white hover:bg-red-600 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
        >批量删除</button>
      </div>

      <!-- 草稿卡列表 -->
      <div class="flex-1 overflow-y-auto px-4 py-3 space-y-3">
        <div v-if="!activeTheme" class="flex items-center justify-center h-full text-sm text-gray-400">
          <div class="text-center">
            <svg class="w-12 h-12 mx-auto mb-3 text-gray-300" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
            </svg>
            <p>选择或生成训练主题以查看草稿</p>
          </div>
        </div>

        <div v-else-if="drafts.length === 0 && !loadingDrafts" class="flex items-center justify-center h-full text-sm text-gray-400">
          <div class="text-center">
            <svg class="w-12 h-12 mx-auto mb-3 text-gray-300" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M20 13V6a2 2 0 00-2-2H6a2 2 0 00-2 2v7m16 0v5a2 2 0 01-2 2H6a2 2 0 01-2-2v-5m16 0h-2.586a1 1 0 00-.707.293l-2.414 2.414a1 1 0 01-.707.293h-3.172a1 1 0 01-.707-.293l-2.414-2.414A1 1 0 006.586 13H4" />
            </svg>
            <p>该主题下没有待审核的草稿</p>
          </div>
        </div>

        <template v-else>
          <div v-if="loadingDrafts" class="flex items-center justify-center py-8 text-sm text-gray-400">
            <svg class="animate-spin w-5 h-5 mr-2" fill="none" viewBox="0 0 24 24">
              <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4" />
              <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
            </svg>
            加载中...
          </div>
          <template v-else>
            <div v-for="d in drafts" :key="d.draft_id" class="border border-gray-200 rounded-lg overflow-hidden transition-shadow hover:shadow-sm">
              <div class="flex items-start gap-3 p-3">
                <input
                  type="checkbox"
                  :value="d.draft_id"
                  v-model="selectedIds"
                  class="w-4 h-4 mt-0.5 text-amber-500 border-gray-300 rounded flex-shrink-0"
                />
                <div class="flex-1 min-w-0">
                  <p class="text-sm font-medium text-gray-800 mb-1">{{ d.question }}</p>
                  <div v-if="d.alt_questions && d.alt_questions.length > 0" class="flex flex-wrap gap-1 mb-2">
                    <span
                      v-for="(aq, i) in d.alt_questions"
                      :key="i"
                      class="inline-flex items-center px-1.5 py-0.5 text-xs rounded bg-blue-50 text-blue-600 border border-blue-100"
                    >{{ aq }}</span>
                  </div>
                  <pre class="text-xs text-gray-600 bg-gray-50 rounded-md p-2.5 overflow-x-auto font-mono leading-relaxed">{{ d.sql }}</pre>
                </div>
                <div class="flex items-center gap-1.5 flex-shrink-0 ml-2">
                  <button
                    @click="approveOne(d)"
                    class="px-2.5 py-1 text-xs font-medium rounded-md bg-green-50 text-green-600 hover:bg-green-100 transition-colors"
                  >通过</button>
                  <button
                    @click="startEdit(d)"
                    class="px-2.5 py-1 text-xs font-medium rounded-md bg-blue-50 text-blue-600 hover:bg-blue-100 transition-colors"
                  >编辑</button>
                  <button
                    @click="deleteOne(d)"
                    class="px-2.5 py-1 text-xs font-medium rounded-md bg-red-50 text-red-500 hover:bg-red-100 transition-colors"
                  >删除</button>
                </div>
              </div>
            </div>
          </template>
        </template>
      </div>

      <!-- 底部分页 -->
      <div v-if="activeTheme && draftTotal > 0" class="border-t border-gray-100 px-4 flex-shrink-0">
        <SqlQaPagination
          :page="draftPage"
          :pageSize="draftPageSize"
          :total="draftTotal"
          @pageChange="onDraftPageChange"
          @pageSizeChange="onDraftPageSizeChange"
        />
      </div>
    </div>

    <!-- 编辑弹窗 -->
    <Teleport to="body">
      <div v-if="editingDraft" class="fixed inset-0 z-50 flex items-center justify-center bg-black/40" @click.self="cancelEdit">
        <div class="bg-white rounded-xl shadow-xl border border-gray-200 w-full max-w-2xl mx-4 max-h-[85vh] flex flex-col">
          <div class="flex items-center justify-between px-5 py-4 border-b border-gray-100">
            <h3 class="text-base font-semibold text-gray-800">编辑问答对</h3>
            <button @click="cancelEdit" class="text-gray-400 hover:text-gray-600">
              <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
          </div>
          <div class="flex-1 overflow-y-auto px-5 py-4 space-y-4">
            <div>
              <label class="block text-sm font-medium text-gray-700 mb-1.5">主问题</label>
              <textarea
                v-model="editForm.question"
                rows="2"
                class="w-full text-sm border border-gray-200 rounded-lg px-3.5 py-2.5 bg-white text-gray-700 focus:outline-none focus:ring-2 focus:ring-amber-400/30 focus:border-amber-400 transition-shadow resize-none"
              ></textarea>
            </div>
            <div>
              <label class="block text-sm font-medium text-gray-700 mb-1.5">SQL</label>
              <textarea
                v-model="editForm.sql"
                rows="6"
                class="w-full text-sm border border-gray-200 rounded-lg px-3.5 py-2.5 bg-white text-gray-700 font-mono focus:outline-none focus:ring-2 focus:ring-amber-400/30 focus:border-amber-400 transition-shadow resize-none"
              ></textarea>
            </div>
            <div>
              <label class="block text-sm font-medium text-gray-700 mb-1.5">训练主题（可选）</label>
              <input
                v-model="editForm.theme"
                type="text"
                placeholder="例如：设备故障工单、设备状态信息统计"
                maxlength="50"
                class="w-full text-sm border border-gray-200 rounded-lg px-3.5 py-2.5 bg-white text-gray-700 placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-amber-400/30 focus:border-amber-400 transition-shadow"
              />
            </div>
            <div>
              <div class="flex items-center justify-between mb-1.5">
                <label class="text-sm font-medium text-gray-700">备选问法</label>
                <button
                  @click="addAltQuestion"
                  class="inline-flex items-center gap-1 text-xs text-amber-600 hover:text-amber-700"
                >
                  <svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 4v16m8-8H4" />
                  </svg>
                  添加
                </button>
              </div>
              <div class="space-y-1.5">
                <div
                  v-for="(_, i) in editForm.altQuestions"
                  :key="i"
                  class="flex items-center gap-1.5"
                >
                  <input
                    v-model="editForm.altQuestions[i]"
                    type="text"
                    :placeholder="`备选问法 ${i + 1}`"
                    class="flex-1 text-sm border border-gray-200 rounded-lg px-3 py-2 bg-white text-gray-700 placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-amber-400/30 focus:border-amber-400 transition-shadow"
                  />
                  <button
                    @click="removeAltQuestion(i)"
                    class="flex-shrink-0 w-7 h-7 flex items-center justify-center rounded-md text-gray-400 hover:text-red-500 hover:bg-red-50 transition-colors"
                  >
                    <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
                    </svg>
                  </button>
                </div>
                <p v-if="editForm.altQuestions.length === 0" class="text-xs text-gray-400 py-1">暂无备选问法，点击"添加"按钮新增</p>
              </div>
            </div>
          </div>
          <div class="flex justify-end gap-2 px-5 py-4 border-t border-gray-100">
            <button @click="cancelEdit" class="px-4 py-2 text-sm font-medium text-gray-600 bg-gray-100 rounded-lg hover:bg-gray-200 transition-colors">取消</button>
            <button @click="saveEdit" class="px-4 py-2 text-sm font-medium text-white bg-amber-500 rounded-lg hover:bg-amber-600 transition-colors">保存</button>
          </div>
        </div>
      </div>
    </Teleport>

    <!-- Toast -->
    <Teleport to="body">
      <div
        v-if="toast"
        :class="[
          'fixed top-6 right-6 z-[100] px-4 py-3 rounded-lg shadow-lg text-sm font-medium transition-all duration-300',
          toast.type === 'success' ? 'bg-green-500 text-white' : 'bg-red-500 text-white'
        ]"
      >{{ toast.message }}</div>
    </Teleport>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onBeforeUnmount, watch } from 'vue'
import {
  listTables,
  startBatchGenerate,
  getBatchGenerateStatus,
  listBatchDraftThemes,
  listBatchDrafts,
  approveBatchDrafts,
  updateBatchDraft,
  deleteBatchDrafts,
} from '../../../api/sqlQaClient.js'
import SqlQaPagination from './SqlQaPagination.vue'
import SqlQaSelect from './SqlQaSelect.vue'
import { useSqlQaConfirm } from '../../../composables/sql_qa/useSqlQaConfirm.js'

// ======== 左侧：生成配置 ========
const theme = ref('')
const tables = ref([])
const selectedTables = ref([])
const schemaSupplement = ref('')
const exampleSql = ref('')
const count = ref(100)
const customCount = ref(null)
const isGenerating = ref(false)
const jobId = ref(null)
const jobProgress = ref(null)

// 表选择弹窗
const showTableModal = ref(false)
const modalSelected = ref([])    // 弹窗内临时选中
const tableSearch = ref('')

const filteredTables = computed(() => {
  if (!tableSearch.value.trim()) return tables.value
  const q = tableSearch.value.trim().toLowerCase()
  return tables.value.filter(t => t.name.toLowerCase().includes(q))
})

const canGenerate = computed(() =>
  theme.value.trim() && selectedTables.value.length > 0 && !isGenerating.value
)

const progressPercent = computed(() => {
  if (!jobProgress.value || jobProgress.value.target_count === 0) return 0
  return Math.min(100, Math.round((jobProgress.value.generated / jobProgress.value.target_count) * 100))
})

function onCustomCountInput() {
  if (customCount.value && customCount.value >= 10 && customCount.value <= 500) {
    count.value = customCount.value
  }
}

async function loadTableList() {
  try {
    const res = await listTables()
    tables.value = (res.tables || []).map(t => {
      if (typeof t === 'string') return { name: t, comment: '' }
      return { name: t.name || t.table_name || '', comment: t.comment || t.table_comment || '' }
    })
  } catch (e) {
    console.error('Failed to load tables:', e)
  }
}

function removeTable(name) {
  selectedTables.value = selectedTables.value.filter(t => t !== name)
}

// ======== 表选择弹窗 ========

function openTableModal() {
  modalSelected.value = [...selectedTables.value]
  tableSearch.value = ''
  showTableModal.value = true
}

function toggleTableInModal(name) {
  const idx = modalSelected.value.indexOf(name)
  if (idx >= 0) {
    modalSelected.value.splice(idx, 1)
  } else {
    modalSelected.value.push(name)
  }
}

function selectAllInModal() {
  modalSelected.value = filteredTables.value.map(t => t.name)
}

function invertInModal() {
  const all = filteredTables.value.map(t => t.name)
  modalSelected.value = all.filter(n => !modalSelected.value.includes(n))
}

function confirmTableSelection() {
  selectedTables.value = [...modalSelected.value]
  showTableModal.value = false
}

// ======== 右侧：审核队列 ========
const themes = ref([])
const activeTheme = ref('')
const drafts = ref([])
const draftTotal = ref(0)
const draftPage = ref(1)
const draftPageSize = ref(20)
const selectedIds = ref([])
const selectAll = ref(false)
const loadingDrafts = ref(false)

// 确认弹窗
const { confirm } = useSqlQaConfirm()

// 主题下拉选项
const themeOptions = computed(() => {
  return themes.value.map(t => ({
    value: t.theme,
    label: `${t.theme} (${t.pending_count} 条待审核)`,
  }))
})

// 编辑弹窗
const editingDraft = ref(null)
const editForm = ref({ question: '', sql: '', altQuestions: [], theme: '' })

// Toast
const toast = ref(null)
let toastTimer = null

function showToast(message, type = 'success') {
  toast.value = { message, type }
  if (toastTimer) clearTimeout(toastTimer)
  toastTimer = setTimeout(() => { toast.value = null }, 3000)
}

// ======== 生成流程 ========

async function startGenerate() {
  if (!canGenerate.value) return

  isGenerating.value = true
  jobProgress.value = null

  try {
    const res = await startBatchGenerate({
      theme: theme.value.trim(),
      table_names: selectedTables.value,
      count: count.value,
      schema_supplement: schemaSupplement.value,
      example_sql: exampleSql.value,
    })

    if (res.success) {
      jobId.value = res.job_id
      showToast(res.message || '已启动批量生成任务')
      startPolling()

      // 如果右侧主题不在列表中，自动切换到当前主题
      await loadThemes()
      if (themes.value.some(t => t.theme === theme.value.trim())) {
        activeTheme.value = theme.value.trim()
        await loadDrafts()
      }
    } else {
      showToast(res.error || '启动失败', 'error')
      isGenerating.value = false
    }
  } catch (e) {
    showToast(e.message || '请求失败', 'error')
    isGenerating.value = false
  }
}

// ======== 轮询 ========

let pollingTimer = null
let draftRefreshTimer = null

function startPolling() {
  stopPolling()
  pollingTimer = setInterval(pollJobStatus, 2000)
  draftRefreshTimer = setInterval(refreshDraftsIfActive, 2000)
}

function stopPolling() {
  if (pollingTimer) { clearInterval(pollingTimer); pollingTimer = null }
  if (draftRefreshTimer) { clearInterval(draftRefreshTimer); draftRefreshTimer = null }
}

async function pollJobStatus() {
  if (!jobId.value) return
  try {
    const res = await getBatchGenerateStatus(jobId.value)
    if (res.success) {
      jobProgress.value = res
      if (res.status === 'done' || res.status === 'failed') {
        stopPolling()
        isGenerating.value = false
        if (res.status === 'done') {
          showToast(`生成完成！共生成 ${res.generated} 条问答对`)
        } else {
          showToast(`生成失败：${(res.errors || []).slice(-1)[0] || '未知错误'}`, 'error')
        }
        // 最后刷新一次
        await loadThemes()
        if (activeTheme.value) await loadDrafts()
      }
    }
  } catch (e) {
    // 静默处理轮询错误
  }
}

async function refreshDraftsIfActive() {
  if (activeTheme.value) {
    await loadDrafts(true)
  }
}

// ======== 主题和草稿加载 ========

async function loadThemes() {
  try {
    const res = await listBatchDraftThemes()
    themes.value = res.themes || []
    // 清理已不存在的主题
    if (activeTheme.value && !themes.value.some(t => t.theme === activeTheme.value)) {
      // 如果当前主题仍有任务在运行，保留它
      if (!isGenerating.value || jobProgress.value?.theme !== activeTheme.value) {
        activeTheme.value = themes.value.length > 0 ? themes.value[0].theme : ''
        selectedIds.value = []
        await loadDrafts()
      }
    }
  } catch (e) {
    console.error('Failed to load themes:', e)
  }
}

async function loadDrafts(silent = false) {
  if (!activeTheme.value) return
  if (!silent) loadingDrafts.value = true
  try {
    const res = await listBatchDrafts({
      theme: activeTheme.value,
      status: 'pending',
      page: draftPage.value,
      page_size: draftPageSize.value,
    })
    drafts.value = res.drafts || []
    draftTotal.value = res.total || 0
  } catch (e) {
    console.error('Failed to load drafts:', e)
  } finally {
    loadingDrafts.value = false
  }
}

function onThemeChange() {
  selectedIds.value = []
  selectAll.value = false
  draftPage.value = 1
  loadDrafts()
}

function onSelectAll() {
  selectedIds.value = selectAll.value ? drafts.value.map(d => d.draft_id) : []
}

function onDraftPageChange(p) {
  draftPage.value = p
  loadDrafts()
}

function onDraftPageSizeChange(s) {
  draftPageSize.value = s
  draftPage.value = 1
  loadDrafts()
}

// ======== 审核操作 ========

async function approveOne(draft) {
  try {
    await approveBatchDrafts({ draft_ids: [draft.draft_id] })
    showToast('已通过并入库')
    // 从当前列表移除
    drafts.value = drafts.value.filter(d => d.draft_id !== draft.draft_id)
    draftTotal.value = Math.max(0, draftTotal.value - 1)
    selectedIds.value = selectedIds.value.filter(id => id !== draft.draft_id)
    // 刷新主题列表
    await loadThemes()
  } catch (e) {
    showToast(e.message || '操作失败', 'error')
  }
}

async function deleteOne(draft) {
  try {
    await deleteBatchDrafts({ draft_ids: [draft.draft_id] })
    showToast('已删除')
    drafts.value = drafts.value.filter(d => d.draft_id !== draft.draft_id)
    draftTotal.value = Math.max(0, draftTotal.value - 1)
    selectedIds.value = selectedIds.value.filter(id => id !== draft.draft_id)
    await loadThemes()
  } catch (e) {
    showToast(e.message || '操作失败', 'error')
  }
}

async function batchApprove() {
  if (selectedIds.value.length === 0) return
  try {
    const res = await approveBatchDrafts({ draft_ids: [...selectedIds.value] })
    showToast(`成功通过 ${res.approved} 条，失败 ${res.failed} 条`)
    selectedIds.value = []
    selectAll.value = false
    await loadDrafts()
    await loadThemes()
  } catch (e) {
    showToast(e.message || '操作失败', 'error')
  }
}

async function batchDelete() {
  if (selectedIds.value.length === 0) return
  const ok = await confirm({ message: `确认删除选中的 ${selectedIds.value.length} 条草稿？`, danger: true })
  if (!ok) return
  try {
    const res = await deleteBatchDrafts({ draft_ids: [...selectedIds.value] })
    showToast(`成功删除 ${res.deleted} 条`)
    selectedIds.value = []
    selectAll.value = false
    await loadDrafts()
    await loadThemes()
  } catch (e) {
    showToast(e.message || '操作失败', 'error')
  }
}

// ======== 编辑 ========

function startEdit(draft) {
  editingDraft.value = draft
  editForm.value = {
    question: draft.question,
    sql: draft.sql,
    altQuestions: [...(draft.alt_questions || [])],
    theme: draft.theme || '',
  }
}

function addAltQuestion() {
  editForm.value.altQuestions.push('')
}

function removeAltQuestion(index) {
  editForm.value.altQuestions.splice(index, 1)
}

function cancelEdit() {
  editingDraft.value = null
  editForm.value = { question: '', sql: '', altQuestions: [] }
}

async function saveEdit() {
  if (!editingDraft.value) return
  const altQuestions = editForm.value.altQuestions
    .map(s => s.trim())
    .filter(s => s)
  try {
    await updateBatchDraft(editingDraft.value.draft_id, {
      question: editForm.value.question,
      sql: editForm.value.sql,
      alt_questions: altQuestions,
      theme: editForm.value.theme || undefined,
    })
    showToast('已保存')
    cancelEdit()
    await loadDrafts()
  } catch (e) {
    showToast(e.message || '保存失败', 'error')
  }
}

// ======== 生命周期 ========

onMounted(async () => {
  await loadTableList()
  await loadThemes()
  if (themes.value.length > 0) {
    activeTheme.value = themes.value[0].theme
    await loadDrafts()
  }
})

onBeforeUnmount(() => {
  stopPolling()
  if (toastTimer) clearTimeout(toastTimer)
})
</script>
