<template>
  <div class="h-full overflow-y-auto bg-slate-50">
    <!-- 顶部面包屑 -->
    <div class="bg-white border-b border-slate-200 px-6 py-3 flex items-center gap-2 text-[13px]">
      <button class="inline-flex items-center gap-1.5 px-2 py-1.5 rounded-lg text-slate-500 hover:text-amber-500 hover:bg-amber-50 transition-colors" @click="goBack">
        <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 19l-7-7 7-7"/></svg>
        {{ backText }}
      </button>
    </div>

    <div class="p-6">
      <!-- 标题行 -->
      <div class="flex items-start justify-between mb-5">
        <div>
          <h1 class="text-xl font-bold text-slate-800">{{ currentKB?.name || (loadError ? '加载失败' : '加载中...') }}</h1>
          <p v-if="currentKB?.description" class="text-sm text-slate-500 mt-1">{{ currentKB.description }}</p>
          <p v-if="!currentKB && !loadError" class="text-sm text-slate-400 mt-1">正在加载知识库信息...</p>
          <p v-if="loadError" class="text-sm text-red-500 mt-1">加载失败，请刷新重试</p>
        </div>
        <div class="flex items-center gap-2">
          <button class="btn-ghost text-sm" @click="openKBEditDialog" title="编辑知识库">
            <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z"/></svg>
            编辑
          </button>
          <button v-if="currentKB?.kb_type === 'custom_base'" class="btn-ghost text-sm !text-red-400 hover:!bg-red-50" @click="handleDeleteKB" title="删除知识库">
            <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"/></svg>
            删除
          </button>
          <button class="btn-ghost text-sm" :disabled="refreshingKB" @click="refreshAll" title="刷新评估">
            <span v-if="refreshingKB" class="inline-block w-3.5 h-3.5 border-2 border-amber-400 border-t-transparent rounded-full animate-spin mr-1"></span>
            <svg v-else class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"/></svg>
            {{ refreshingKB ? '刷新中...' : '刷新评估' }}
          </button>
          <span v-if="kbLastRefresh" class="text-[10px] text-slate-400">{{ kbLastRefresh }}</span>
        </div>
      </div>

    <!-- KB 编辑弹窗 -->
    <teleport to="body">
      <div v-if="showKBEditDialog" class="modal-overlay" @click.self="showKBEditDialog = false">
        <div class="modal max-w-md">
          <h3>编辑知识库</h3>
          <div class="form-group"><label class="form-label">名称 <span class="text-red-500">*</span></label><input v-model="kbEditForm.name" class="form-input" placeholder="知识库名称"></div>
          <div class="form-group"><label class="form-label">描述</label><textarea v-model="kbEditForm.description" class="form-textarea" rows="3" placeholder="知识库描述"></textarea></div>
          <div class="modal-footer"><button class="btn-ghost" @click="showKBEditDialog = false">取消</button><button class="btn-primary" :disabled="!kbEditForm.name.trim()" @click="handleSaveKBEdit">保存</button></div>
        </div>
      </div>
    </teleport>

      <!-- 概览卡片 -->
      <div class="grid grid-cols-3 gap-3.5 mb-5">
        <div class="bg-white border border-slate-200 rounded-2xl p-4">
          <div class="flex items-center justify-between mb-2">
            <span class="text-xs font-semibold text-slate-500 uppercase tracking-wide">收集进度</span>
            <div class="w-8 h-8 rounded-lg bg-amber-50 flex items-center justify-center text-amber-500">
              <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z"/></svg>
            </div>
          </div>
          <p class="text-2xl font-bold text-amber-500">{{ plans.length ? kbOverview.progress + '%' : '—' }}</p>
          <p class="text-xs text-slate-500 mt-1">{{ plans.length ? kbOverview.completed + '/' + kbOverview.totalItems + ' 项已完成' : '暂无收集计划' }}</p>
          <div class="h-1 bg-slate-100 rounded mt-2.5 overflow-hidden"><div class="h-full bg-amber-500 rounded transition-all duration-500" :style="{ width: (plans.length ? kbOverview.progress : 0) + '%' }"></div></div>
        </div>
        <div class="bg-white border border-slate-200 rounded-2xl p-4">
          <div class="flex items-center justify-between mb-2">
            <span class="text-[11px] font-semibold text-slate-500 uppercase tracking-wide">文档质量</span>
            <div class="w-8 h-8 rounded-lg bg-emerald-50 flex items-center justify-center text-emerald-500">
              <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z"/></svg>
            </div>
          </div>
          <p class="text-2xl font-bold text-emerald-500">{{ plans.length && kbOverview.score != null ? kbOverview.score : '—' }}</p>
          <p class="text-xs text-slate-500 mt-1">AI 综合评分</p>
          <div class="h-1 bg-slate-100 rounded mt-2.5 overflow-hidden"><div class="h-full bg-emerald-500 rounded transition-all duration-500" :style="{ width: (plans.length && kbOverview.score || 0) + '%' }"></div></div>
          <div class="mt-2 flex items-start gap-1">
            <p class="text-[10px] text-slate-400 leading-relaxed flex-1">评分基于已审批文档的AI质量评估，综合关联性、完整性等维度自动计算</p>
            <button class="text-[10px] text-amber-500 hover:text-amber-600 flex-shrink-0" @click.stop="showEvalDetail = !showEvalDetail">{{ showEvalDetail ? '收起' : '详情' }}</button>
          </div>
          <div v-if="showEvalDetail" class="mt-2 p-2 bg-slate-50 rounded-lg text-[10px] text-slate-500 leading-relaxed space-y-1">
            <p><b class="text-slate-600">评估流程：</b></p>
            <p>1. 文档上传后触发AI审核，评估关联性和质量</p>
            <p>2. 人工审批通过后，评分计入收集项统计</p>
            <p>3. 收集项下所有文档评分汇总，生成综合评估</p>
            <p>4. 各收集项评估结果汇总为知识库整体质量评分</p>
            <p class="text-slate-400 mt-1.5"><b>评分说明：</b>85分以上为优秀，60-85分为良好，60分以下待改进</p>
          </div>
        </div>
        <div class="bg-white border border-slate-200 rounded-2xl p-4">
          <div class="flex items-center justify-between mb-2">
            <span class="text-[11px] font-semibold text-slate-500 uppercase tracking-wide">已发布文档</span>
            <div class="w-8 h-8 rounded-lg bg-blue-50 flex items-center justify-center text-blue-500">
              <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M7 21h10a2 2 0 002-2V9.414a1 1 0 00-.293-.707l-5.414-5.414A1 1 0 0012.586 3H7a2 2 0 00-2 2v14a2 2 0 002 2z"/></svg>
            </div>
          </div>
          <p class="text-2xl font-bold text-blue-500">{{ validRAGDocs.length }}</p>
          <p class="text-xs text-slate-500 mt-1">已发布到知识库</p>
        </div>
      </div>

      <!-- Tabs -->
      <div class="flex gap-0 border-b-2 border-slate-100 mb-0">
        <button class="tab" :class="{ active: activeTab === 'plans' }" @click="activeTab = 'plans'">收集计划<span class="tab-badge">{{ plans.length }}</span></button>
        <button class="tab" :class="{ active: activeTab === 'documents' }" @click="activeTab = 'documents'">文档列表<span class="tab-badge">{{ validRAGDocs.length }}</span></button>
        <button v-if="currentKB?.kb_type !== 'compliance'" class="tab" :class="{ active: activeTab === 'custom-docs' }" @click="activeTab = 'custom-docs'">自定义文档<span class="tab-badge">{{ customPlans.length }}</span></button>
      </div>

      <!-- ===== Tab: 文档列表 ===== -->
      <div v-if="activeTab === 'documents'" class="pt-5">
        <div class="bg-white border border-slate-200 rounded-2xl overflow-hidden">
          <div class="flex items-center justify-between px-4 py-3 border-b border-slate-100">
            <h4 class="text-sm font-semibold text-slate-800">已发布文档 <span class="font-normal text-slate-400 text-xs">({{ validRAGDocs.length }})</span></h4>
            <button class="btn-ghost text-xs py-1.5 px-3" @click="refreshRAGDocs">
              <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"/></svg>刷新
            </button>
          </div>
          <!-- 加载 -->
          <div v-if="loading.ragDocs" class="flex items-center justify-center py-12">
            <div class="animate-spin rounded-full h-5 w-5 border-b-2 border-amber-500"></div>
            <span class="ml-2 text-slate-500 text-xs">加载中...</span>
          </div>
          <!-- 空 -->
          <div v-else-if="validRAGDocs.length === 0" class="text-center py-12">
            <svg class="w-10 h-10 text-slate-300 mx-auto mb-2" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"/></svg>
            <p class="text-slate-500 text-sm">暂无已发布文档</p>
          </div>
          <!-- 表格 -->
          <table v-else class="w-full">
            <thead class="bg-slate-50 border-b border-slate-100">
              <tr><th class="px-4 py-2.5 text-left text-[11px] font-semibold text-slate-500 uppercase">文档名称</th><th class="px-4 py-2.5 text-left text-[11px] font-semibold text-slate-500 uppercase">类型</th><th class="px-4 py-2.5 text-left text-[11px] font-semibold text-slate-500 uppercase">大小</th><th class="px-4 py-2.5 text-left text-[11px] font-semibold text-slate-500 uppercase">同步时间</th><th class="px-4 py-2.5 text-right text-[11px] font-semibold text-slate-500 uppercase">操作</th></tr>
            </thead>
            <tbody class="divide-y divide-slate-50">
              <tr v-for="doc in validRAGDocs" :key="doc.id" class="hover:bg-amber-50/30">
                <td class="px-4 py-3 text-[13px] font-medium text-slate-800">{{ doc.name }}</td>
                <td class="px-4 py-3 text-[13px]"><span class="doc-type-tag" :class="docTypeClass(doc.type)">{{ doc.type || '-' }}</span></td>
                <td class="px-4 py-3 text-[13px] text-slate-500">{{ formatSize(doc.size) }}</td>
                <td class="px-4 py-3 text-[13px] text-slate-500">{{ formatDate(doc.update_time || doc.create_time) }}</td>
                <td class="px-4 py-3 text-right">
                  <div class="flex items-center justify-end gap-1">
                    <button class="btn-ghost text-xs py-1 px-2" @click="openChunkViewer(doc)">预览</button>
                    <button class="btn-ghost text-xs py-1 px-2" @click="downloadRAGDoc(doc)">下载</button>
                  </div>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <!-- ===== Tab: 自定义文档 ===== -->
      <div v-if="activeTab === 'custom-docs'" class="pt-5">
        <div class="flex items-center justify-between mb-3.5">
          <h4 class="text-sm font-semibold text-slate-800">自定义文档收集计划</h4>
          <button class="btn-primary text-xs !bg-white !text-slate-800 border-2 border-slate-300 hover:!bg-slate-50 font-bold" @click="openCreateCustomPlan">
            <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 4v16m8-8H4"/></svg>新建收集计划
          </button>
        </div>

        <div v-if="loading.plans" class="flex items-center justify-center py-12">
          <div class="animate-spin rounded-full h-5 w-5 border-b-2 border-amber-500"></div>
        </div>
        <div v-else-if="customPlans.length === 0" class="text-center py-12">
          <p class="text-slate-400 text-sm">暂无自定义文档收集计划</p>
        </div>
        <div v-else class="flex flex-col gap-2.5">
          <div v-for="plan in customPlans" :key="plan.id" class="bg-white border border-slate-200 rounded-2xl hover:border-slate-300 hover:shadow-sm transition-all cursor-pointer">
            <div class="p-4" @click="router.push(`/knowledge-management/plans/${plan.id}`)">
              <div class="flex items-start justify-between gap-3">
                <div class="flex-1 min-w-0">
                  <div class="flex items-center justify-between mb-1.5">
                    <span class="text-[15px] font-semibold text-slate-800">{{ plan.name }}</span>
                    <div class="flex items-center gap-2 flex-shrink-0">
                      <span class="score-circle" :class="scoreClass(plan.overall_score)">{{ plan.overall_score || '—' }}</span>
                    </div>
                  </div>
                  <p v-if="plan.description" class="text-[13px] text-slate-500 mb-2">{{ plan.description }}</p>
                  <div class="flex items-center gap-2.5 text-[11px] text-slate-400">
                    <span>{{ plan.plan_items?.length || 0 }} 个收集项</span>
                    <span v-if="plan.due_date">截止 {{ plan.due_date }}</span>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- ===== Tab: 收集计划 ===== -->
      <div v-if="activeTab === 'plans'" class="pt-5">
        <div class="flex gap-4">
          <!-- 左侧：类别 + 对象 -->
          <div class="w-72 flex-shrink-0 flex flex-col gap-3.5">
            <!-- 自定义KB提示 -->
            <div v-if="currentKB?.kb_type === 'custom_base'" class="bg-amber-50 border border-amber-200 rounded-xl p-3 text-[12px] text-amber-700">
              <div class="font-semibold mb-1">💡 自定义知识库</div>
              请手动添加文档类别、收集对象和收集计划
            </div>
            <!-- 文档类别 -->
            <div class="bg-white border border-slate-200 rounded-2xl p-4">
              <div class="flex items-center justify-between mb-3">
                <h4 class="text-[13px] font-semibold text-slate-800">文档类别</h4>
                <div class="flex gap-1">
                  <button class="btn-ghost text-[10px] px-2 py-1" @click="showAllCategories = true" :disabled="categories.length === 0">查看全部</button>
                  <button class="btn-icon-xs" @click="openCategoryDialog()"><svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 4v16m8-8H4"/></svg></button>
                </div>
              </div>
              <div v-if="loading.categories" class="text-center py-3 text-slate-400 text-xs">加载中...</div>
              <div v-else-if="categories.length === 0" class="text-center py-3 text-slate-400 text-xs">暂无类别</div>
              <div v-else class="space-y-1 max-h-[300px] overflow-y-auto">
                <div v-for="cat in categories" :key="cat.id" class="group p-2.5 rounded-lg hover:bg-slate-50 text-[13px]">
                  <div class="flex items-center justify-between mb-1">
                    <div class="flex items-center gap-1.5 flex-1 min-w-0">
                      <span class="font-medium text-slate-800 truncate">{{ cat.name }}</span>
                      <span v-if="cat.preset_category_id" class="text-[9px] bg-blue-50 text-blue-600 px-1.5 py-0.5 rounded shrink-0">预置</span>
                      <span v-else class="text-[9px] bg-amber-50 text-amber-600 px-1.5 py-0.5 rounded shrink-0">手动</span>
                    </div>
                    <div class="flex gap-0.5 shrink-0">
                      <!-- 只有手动创建的类别才能编辑/删除 -->
                      <template v-if="!cat.preset_category_id">
                        <div class="flex gap-0.5 opacity-0 group-hover:opacity-100 transition-opacity">
                          <button class="btn-icon-xs" @click="editCategoryItem(cat)" title="编辑"><svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z"/></svg></button>
                          <button class="btn-icon-xs !text-red-400" @click="handleDeleteCategory(cat)" title="删除"><svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"/></svg></button>
                        </div>
                      </template>
                      <span v-else class="text-[10px] text-slate-400">只读</span>
                    </div>
                  </div>
                  <div class="text-[11px] text-slate-500 leading-relaxed whitespace-pre-wrap">{{ cat.requirement_desc || '（无要求描述）' }}</div>
                </div>
              </div>
            </div>
            <!-- 收集对象 -->
            <div class="bg-white border border-slate-200 rounded-2xl p-4">
              <div class="flex items-center justify-between mb-3">
                <h4 class="text-[13px] font-semibold text-slate-800">收集对象</h4>
                <button class="btn-icon-xs" @click="openTargetDialog()"><svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 4v16m8-8H4"/></svg></button>
              </div>
              <div v-if="loading.targets" class="text-center py-3 text-slate-400 text-xs">加载中...</div>
              <div v-else-if="targets.length === 0" class="text-center py-3 text-slate-400 text-xs">暂无对象</div>
              <div v-else class="space-y-1">
                <div v-for="tgt in targets" :key="tgt.id" class="group flex items-center justify-between p-2 rounded-lg hover:bg-slate-50 text-[13px]">
                  <div class="min-w-0 flex-1">
                    <div class="font-medium text-slate-800 truncate">{{ tgt.name }}</div>
                    <div class="text-[11px] text-slate-400">{{ tgt.target_type }}<span v-if="tgt.attributes?.length"> · {{ tgt.attributes.map(a => a.value).join(' · ') }}</span></div>
                  </div>
                  <div class="flex gap-0.5 opacity-0 group-hover:opacity-100 transition-opacity">
                    <button class="btn-icon-xs" @click="editTargetItemFn(tgt)"><svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z"/></svg></button>
                    <button class="btn-icon-xs !text-red-400" @click="handleDeleteTarget(tgt)"><svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"/></svg></button>
                  </div>
                </div>
              </div>
            </div>
          </div>

          <!-- 右侧：收集计划 -->
          <div class="flex-1 min-w-0">
            <div class="flex items-center justify-between mb-3.5">
              <h4 class="text-sm font-semibold text-slate-800">收集计划</h4>
              <button class="btn-primary text-xs !bg-white !text-slate-800 border-2 border-slate-300 hover:!bg-slate-50 font-bold" @click="openCreatePlan">
                <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 4v16m8-8H4"/></svg>新建计划
              </button>
            </div>

            <!-- 批量操作栏 -->
            <div v-if="selectedPlanIds.length > 0" class="flex items-center gap-2.5 px-3 py-2 bg-amber-50 border border-amber-200 rounded-lg mb-3 text-[13px] animate-[slideDown_.2s_ease]">
              <span class="font-semibold text-amber-600">已选 {{ selectedPlanIds.length }} 项</span>
              <button class="btn-ghost text-xs" @click="selectAllPlans(true)">全选</button>
              <button class="btn-ghost text-xs" @click="selectAllPlans(false)">取消选择</button>
              <button class="btn-ghost text-xs !text-red-500 hover:!bg-red-50" @click="batchDeletePlans">批量删除</button>
            </div>

            <!-- 计划列表 -->
            <div v-if="loading.plans" class="flex items-center justify-center py-12">
              <div class="animate-spin rounded-full h-5 w-5 border-b-2 border-amber-500"></div>
            </div>
            <div v-else-if="plans.length === 0" class="text-center py-12">
              <p class="text-slate-400 text-sm">暂无收集计划</p>
            </div>
            <div v-else class="flex flex-col gap-2.5">
              <div v-for="plan in plans" :key="plan.id" class="bg-white border border-slate-200 rounded-2xl hover:border-slate-300 hover:shadow-sm transition-all cursor-pointer">
                <!-- 卡片主体 -->
                <div class="p-4" @click="togglePlanExpand(plan.id)">
                  <div class="flex items-start gap-3">
                    <div class="mt-0.5 flex-shrink-0" @click.stop>
                      <input v-if="plan.sync_type !== 'auto'" type="checkbox" class="w-4 h-4 accent-amber-500 cursor-pointer" :checked="selectedPlanIds.includes(plan.id)" @change="togglePlanSelect(plan.id)">
                      <input v-else type="checkbox" class="w-4 h-4 accent-slate-300 cursor-not-allowed" :disabled="true" :title="'该收集计划不可删除（自动生成）'">
                    </div>
                    <div class="flex-1 min-w-0">
                      <!-- Row 1: 名称 + 操作 -->
                      <div class="flex items-start justify-between gap-3 mb-1.5">
                        <span class="text-[15px] font-semibold text-slate-800">{{ plan.name }}</span>
                        <div class="flex items-center gap-2 flex-shrink-0" @click.stop>
                          <button class="btn-primary text-xs !bg-amber-500 hover:!bg-amber-600 font-bold py-1.5 px-3" @click="router.push(`/knowledge-management/plans/${plan.id}`)"><svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 17v-2m3 2v-4m3 4v-6m2 10H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"/></svg>收集项</button>
                          <button class="btn-icon-xs" @click="openEditPlan(plan)" title="编辑"><svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z"/></svg></button>
                          <button class="btn-icon-xs !text-slate-300 cursor-not-allowed hover:!bg-slate-50 hover:!text-slate-300" :disabled="true" :title="plan.sync_type === 'auto' ? '该收集计划不可删除（自动生成）' : '删除'"><svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"/></svg></button>
                          <button class="btn-ghost text-xs" :disabled="refreshingPlanEval.has(plan.id)" @click.stop="refreshPlanEval(plan.id)" :title="refreshingPlanEval.has(plan.id) ? '评估中...' : '刷新评估'">
                            <svg v-if="!refreshingPlanEval.has(plan.id)" class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"/></svg>
                            <span v-else class="inline-block w-3 h-3 border-2 border-amber-400 border-t-transparent rounded-full animate-spin"></span>
                            {{ refreshingPlanEval.has(plan.id) ? '评估中' : '刷新' }}
                          </button>
                        </div>
                      </div>
                      <!-- 描述 -->
                      <p v-if="plan.description" class="text-[13px] text-slate-500 mb-2.5">{{ plan.description }}</p>
                      <!-- Row 3: 标签 + 评分 -->
                      <div class="flex items-center justify-between mb-2.5">
                        <div class="flex items-center gap-2.5 flex-wrap text-[11px]">
                          <span v-if="plan.due_date" class="font-medium text-slate-700">截止 {{ plan.due_date }}</span>
                          <span class="priority-tag" :class="priorityClass(plan.priority)">{{ priorityLabel(plan.priority) }}</span>
                          <span class="status-badge" :class="plan.status === 'completed' ? 'bg-emerald-50 text-emerald-600' : plan.status === 'archived' ? 'bg-slate-100 text-slate-400' : 'bg-emerald-50 text-emerald-600'">{{ plan.status === 'active' ? '进行中' : plan.status === 'completed' ? '已完成' : '已归档' }}</span>
                        </div>
                        <span class="score-circle" :class="scoreClass(plan.overall_score)">{{ plan.overall_score || '—' }}</span>
                      </div>
                      <!-- 进度条 -->
                      <div class="h-1.5 bg-slate-100 rounded mb-1.5 overflow-hidden"><div class="h-full bg-amber-500 rounded transition-all duration-500" :style="{ width: (plan.overall_progress || 0) + '%' }"></div></div>
                      <!-- 进度统计 -->
                      <div class="flex items-center gap-3.5 text-xs">
                        <span class="flex items-center gap-1"><span class="w-1.5 h-1.5 rounded-full bg-emerald-500 flex-shrink-0"></span>已完成 {{ plan.overall_stats?.completed || 0 }}</span>
                        <span class="flex items-center gap-1"><span class="w-1.5 h-1.5 rounded-full bg-amber-500 flex-shrink-0"></span>待完善 {{ plan.overall_stats?.improving || 0 }}</span>
                        <span class="flex items-center gap-1"><span class="w-1.5 h-1.5 rounded-full bg-red-500 flex-shrink-0"></span>缺失 {{ plan.overall_stats?.missing || 0 }}</span>
                        <span class="flex items-center gap-1 text-slate-500"><svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"/></svg>已上传 {{ plan.uploaded_doc_count || 0 }}</span>
                        <div class="ml-auto flex items-baseline gap-1.5">
                          <span class="text-[13px] font-bold text-slate-800">{{ plan.overall_progress || 0 }}%</span>
                          <span class="text-[10px] text-slate-400">{{ ((plan.overall_stats?.completed || 0) + (plan.overall_stats?.improving || 0) + (plan.overall_stats?.missing || 0)) }}项</span>
                        </div>
                      </div>
                    </div>
                  </div>
                </div>
                <!-- 展开：AI 评估 -->
                <div v-if="expandedPlans.has(plan.id)" class="border-t border-slate-100 px-4 py-3 bg-slate-50 rounded-b-2xl animate-[slideDown_.2s_ease]">
                  <div class="text-[11px] font-semibold text-slate-500 uppercase tracking-wide mb-2">🤖 AI 整体评估</div>
                  <p class="text-[13px] text-slate-700 leading-relaxed">{{ plan.overall_analysis || '暂无评估数据。' }}</p>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- ===== MODALS: 类别 / 对象 / 计划 ===== -->
    <!-- 类别弹窗 (复用原有逻辑) -->
    <teleport to="body">
      <div v-if="showCategoryDialog" class="modal-overlay" @click.self="showCategoryDialog = false">
        <div class="modal">
          <button class="modal-close-x" @click="showCategoryDialog = false">×</button>
          <h3>{{ editCategory ? '编辑类别' : '新建类别' }}</h3>
          <div class="form-group"><label class="form-label">名称 <span class="text-red-500">*</span></label><input v-model="categoryForm.name" class="form-input" placeholder="如：维修保养手册"></div>
          <div class="form-group"><label class="form-label">要求描述 <span class="text-red-500">*</span></label><textarea v-model="categoryForm.requirement_desc" class="form-textarea" rows="6" placeholder="描述此类文档的收集要求"></textarea></div>
          <div class="modal-footer"><button class="btn-ghost" @click="showCategoryDialog = false">取消</button><button class="btn-primary" :disabled="!categoryForm.name.trim() || !categoryForm.requirement_desc.trim()" @click="handleSaveCategory">保存</button></div>
        </div>
      </div>
    </teleport>

    <!-- 对象弹窗 -->
    <teleport to="body">
      <div v-if="showTargetDialog" class="modal-overlay" @click.self="showTargetDialog = false">
        <div class="modal">
          <h3>{{ editTargetItem ? '编辑对象' : '新建对象' }}</h3>
          <div class="form-group flex gap-3">
            <div class="flex-1"><label class="form-label">名称 <span class="text-red-500">*</span></label><input v-model="targetForm.name" class="form-input" placeholder="如：冲网线"></div>
            <div class="flex-1"><label class="form-label">类型 <span class="text-red-500">*</span></label><input v-model="targetForm.target_type" class="form-input" placeholder="如：设备、工序"></div>
          </div>
          <div class="form-group">
            <label class="form-label">属性列表</label>
            <div v-for="(attr, idx) in targetForm.attributes" :key="idx" class="flex gap-2 mb-2">
              <input v-model="attr.label" class="form-input flex-1 text-xs" placeholder="属性名"><input v-model="attr.value" class="form-input flex-1 text-xs" placeholder="属性值">
              <button class="btn-icon-xs !text-red-400" @click="targetForm.attributes.splice(idx, 1)"><svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/></svg></button>
            </div>
            <button class="text-[13px] text-amber-500 hover:text-amber-600 flex items-center gap-1" @click="targetForm.attributes.push({ label: '', value: '' })"><svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 4v16m8-8H4"/></svg>添加属性</button>
          </div>
          <div class="modal-footer"><button class="btn-ghost" @click="showTargetDialog = false">取消</button><button class="btn-primary" :disabled="!targetForm.name.trim() || !targetForm.target_type.trim()" @click="handleSaveTarget">保存</button></div>
        </div>
      </div>
    </teleport>

    <!-- 新建计划弹窗 -->
    <teleport to="body">
      <div v-if="showPlanDialog" class="modal-overlay" @click.self="showPlanDialog = false">
        <div class="modal !max-w-4xl">
          <h3>新建收集计划</h3>
          <!-- 第一排：计划名称 + 要求完成时间 + 优先级 -->
          <div class="flex gap-3 mb-4">
            <div class="flex-1"><label class="form-label">计划名称 <span class="text-red-500">*</span></label><input v-model="planForm.name" class="form-input" placeholder="输入收集计划名称"></div>
            <div class="w-44"><label class="form-label">要求完成时间 <span class="text-red-500">*</span></label><input v-model="planForm.due_date" type="date" class="form-input"></div>
            <div class="w-32"><label class="form-label">优先级</label><CustomSelect v-model="planForm.priority" :options="priorityOptions" class="w-full" /></div>
          </div>
          <!-- 文档类别 + 收集对象（仅普通收集计划需要，自定义计划跳过） -->
          <!-- 文档类别 + 收集对象（自定义计划可选择手动创建的类别，不选择则创建空计划） -->
          <div class="flex gap-4">
            <div class="flex-1">
              <MultiSelect
                v-model="planForm.category_ids"
                :options="creatingCustom ? customCategoryOptions : categoryOptions"
                label="文档类别"
                :required="!creatingCustom"
              />
              <p v-if="creatingCustom && customCategoryOptions.length === 0" class="text-[11px] text-amber-500 mt-1">暂无手动创建的文档类别，请先在左侧"文档类别"中创建</p>
            </div>
            <div class="flex-1">
              <MultiSelect
                v-model="planForm.target_ids"
                :options="targetOptions"
                label="收集对象"
                :required="!creatingCustom"
              />
            </div>
          </div>
          <p class="text-[11px] text-slate-400 mt-3">
            <template v-if="planForm.category_ids.length && planForm.target_ids.length">
              选择后将自动生成 类别×对象 的全部收集项，预计生成 <b class="text-amber-600">{{ planForm.category_ids.length * planForm.target_ids.length }}</b> 个收集项。
            </template>
            <template v-else-if="creatingCustom">
              可选择手动创建的文档类别和收集对象（均可为空），创建后可在收集计划中手动添加收集项。
            </template>
            <template v-else>
              请选择文档类别和收集对象。
            </template>
          </p>
          <div class="modal-footer"><button class="btn-ghost" @click="showPlanDialog = false">取消</button><button class="btn-primary" :disabled="!planForm.name.trim() || !planForm.due_date || (!creatingCustom && (!planForm.category_ids.length || !planForm.target_ids.length))" @click="handleCreatePlan">{{ creatingCustom ? '创建计划' : '生成收集项' }}</button></div>
        </div>
      </div>
    </teleport>

    <!-- 编辑计划弹窗 -->
    <teleport to="body">
      <div v-if="showEditPlanDialog" class="modal-overlay" @click.self="showEditPlanDialog = false">
        <div class="modal">
          <h3>编辑收集计划</h3>
          <div class="form-group"><label class="form-label">计划名称 <span class="text-red-500">*</span></label><input v-model="editPlanForm.name" class="form-input"></div>
          <div class="form-group flex gap-3">
            <div class="flex-1"><label class="form-label">要求完成时间</label><input v-model="editPlanForm.due_date" type="date" class="form-input"></div>
            <div class="flex-1"><label class="form-label">优先级</label><CustomSelect v-model="editPlanForm.priority" :options="priorityOptions" class="w-full" /></div>
          </div>
          <p class="text-xs text-slate-400">类别和对象绑定在创建时确定，如需修改请删除重建。</p>
          <div class="modal-footer"><button class="btn-ghost" @click="showEditPlanDialog = false">取消</button><button class="btn-primary" @click="handleSaveEditPlan">保存</button></div>
        </div>
      </div>
    </teleport>

    <!-- 切片查看弹窗 -->
    <ChunkViewer
      v-if="chunkViewDoc"
      :doc="{ id: chunkViewDoc.ragDocId, name: chunkViewDoc.docName }"
      :dataset-id="chunkViewDoc.ragDatasetId"
      :pdf-preview-url="chunkViewDoc.previewUrl"
      @close="chunkViewDoc = null"
    />

    <!-- 自定义确认弹窗 -->
    <teleport to="body">
      <div v-if="confirmDialog.show" class="modal-overlay" @click.self="confirmDialog.show = false">
        <div class="modal max-w-sm text-center">
          <div class="w-12 h-12 rounded-full bg-red-100 flex items-center justify-center mx-auto mb-3 text-red-500">
            <svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-2.5L13.732 4c-.77-.833-1.964-.833-2.732 0L4.082 16.5c-.77.833.192 2.5 1.732 2.5z"/></svg>
          </div>
          <h3 class="text-base font-bold text-slate-800 mb-1">{{ confirmDialog.title }}</h3>
          <p class="text-slate-500 text-[13px] mb-5">{{ confirmDialog.message }}</p>
          <div class="flex justify-center gap-3">
            <button class="btn-ghost" @click="confirmDialog.show = false">取消</button>
            <button class="btn-primary !bg-red-500 hover:!bg-red-600" @click="confirmDialog.onOk">确认删除</button>
          </div>
        </div>
      </div>

      <!-- 查看全部文档类别弹窗 -->
      <div v-if="showAllCategories" class="modal-overlay" @click.self="showAllCategories = false">
        <div class="bg-white rounded-2xl w-[720px] max-w-[92vw] max-h-[80vh] flex flex-col shadow-2xl">
          <div class="flex items-center justify-between p-5 border-b border-slate-200">
            <h3 class="text-base font-bold text-slate-800">全部文档类别（{{ categories.length }}项）</h3>
            <button class="modal-close-x" @click="showAllCategories = false">×</button>
          </div>
          <div class="p-5 overflow-y-auto flex-1 space-y-2">
            <div v-for="cat in categories" :key="cat.id" class="p-3 rounded-lg border border-slate-100 hover:bg-slate-50">
              <div class="font-medium text-[13px] text-slate-800 mb-1">{{ cat.name }}</div>
              <div class="text-[12px] text-slate-500 leading-relaxed whitespace-pre-wrap">{{ cat.requirement_desc || '（无要求描述）' }}</div>
              <span v-if="!cat.is_custom" class="text-[10px] bg-slate-100 text-slate-500 px-1.5 py-0.5 rounded mt-1.5 inline-block">预置</span>
            </div>
          </div>
        </div>
      </div>
    </teleport>
  </div>
</template>

<script setup>
import { ref, reactive, computed, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useKnowledgeManagement } from '../../composables/knowledge_management/useKnowledgeManagement.js'
import { getRAGDocPreviewUrl } from '../../api/knowledgeManagementClient.js'
import { useToast } from '../../composables/useToast'
import { showConfirm } from '../../composables/useConfirm'
import CustomSelect from './components/CustomSelect.vue'
import ChunkViewer from './components/ChunkViewer.vue'
import MultiSelect from './components/MultiSelect.vue'


const route = useRoute()
const router = useRouter()
const kbId = computed(() => route.params.id)
const toast = useToast()

const { currentKB, categories, targets, plans, ragDocuments, loading, fetchKnowledgeBase, fetchRAGDocuments, fetchCategories, createCategory, updateCategory, deleteCategory, fetchTargets, createTarget, updateTarget, deleteTarget, fetchPlans, createPlan, updatePlan, deletePlan, fetchPlanProgress, updateKnowledgeBase, deleteKnowledgeBase } = useKnowledgeManagement()

const activeTab = ref('plans')
const expandedPlans = ref(new Set())
const selectedPlanIds = ref([])
const showEvalDetail = ref(false)

// 过滤空文档记录
const validRAGDocs = computed(() => (Array.isArray(ragDocuments.value) ? ragDocuments.value : []).filter(d => d && d.id))

// 自定义文档收集计划（is_custom=true 的计划）
const customPlans = computed(() => plans.value.filter(p => p.is_custom === true))

// 加载错误状态
const loadError = ref(false)

// 自定义确认弹窗
const confirmDialog = ref({ show: false, title: '', message: '', onOk: null })

// 切片查看
const chunkViewDoc = ref(null)  // { ragDocId, ragDatasetId, docName, previewUrl }

async function openChunkViewer(doc) {
  if (!currentKB.value?.rag_dataset_id) return
  // 先通过后端代理获取 MinIO 预签名预览 URL
  let previewUrl = ''
  try {
    const resp = await fetch(getRAGDocPreviewUrl(doc.id), {
      headers: { Authorization: 'Bearer ' + (localStorage.getItem('auth_token') || '') }
    })
    const data = await resp.json()
    previewUrl = data?.data?.preview_url || data?.preview_url || ''
  } catch {}
  chunkViewDoc.value = {
    ragDocId: doc.id,
    ragDatasetId: currentKB.value.rag_dataset_id,
    docName: doc.name || '文档',
    previewUrl,
  }
}

// 返回导航
function goBack() {
  if (currentKB.value?.kb_type === 'custom_base' || currentKB.value?.kb_type === 'compliance') {
    router.push('/knowledge-management')
  } else if (currentKB.value?.kb_type === 'device' && currentKB.value?.tags?.workshop) {
    router.push(`/knowledge-management/kb-type/device_doc/workshop/${encodeURIComponent(currentKB.value.tags.workshop)}`)
  } else {
    router.push('/knowledge-management')
  }
}

const backText = computed(() => {
  const t = currentKB.value?.kb_type
  if (t === 'custom_base' || t === 'compliance') return '返回首页'
  if (t === 'device' && currentKB.value?.tags?.workshop) return '返回设备列表'
  return '返回首页'
})

// KB 编辑
const showKBEditDialog = ref(false)
const kbEditForm = ref({ name: '', description: '' })
function openKBEditDialog() {
  kbEditForm.value = { name: currentKB.value?.name || '', description: currentKB.value?.description || '' }
  showKBEditDialog.value = true
}
async function handleSaveKBEdit() {
  if (!kbEditForm.value.name.trim()) return
  try {
    await updateKnowledgeBase(currentKB.value.id, kbEditForm.value)
    showKBEditDialog.value = false
    toast.success('知识库已更新')
  } catch (e) { toast.error('保存失败: ' + e.message) }
}

async function handleDeleteKB() {
  if (!currentKB.value) return
  const name = currentKB.value.name || '未命名知识库'
  if (!await showConfirm(`确定删除自定义知识库「${name}」？`, '删除知识库', { type: 'danger' })) return
  try {
    await deleteKnowledgeBase(currentKB.value.id)
    toast.success('知识库已删除')
    router.push('/knowledge-management')
  } catch (e) { toast.error('删除失败: ' + e.message) }
}

// 从计划数据计算概览统计
const kbOverview = computed(() => {
  if (!plans.value.length) return { progress: 0, score: null, totalItems: 0, total: 0, completed: 0, improving: 0, missing: 0 }
  let totalItems = 0, completed = 0, improving = 0, missing = 0, totalScore = 0, scoreCount = 0
  for (const p of plans.value) {
    const s = p.overall_stats || {}
    // 优先用 overall_stats 的合计，如果未评估则用 item_count 或 plan_items 数量
    const statsTotal = (s.completed || 0) + (s.improving || 0) + (s.missing || 0)
    const planItemCount = p.item_count || p.plan_items?.length || 0
    totalItems += statsTotal > 0 ? statsTotal : planItemCount
    completed += s.completed || 0
    improving += s.improving || 0
    missing += s.missing || 0
    if (p.overall_score != null) { totalScore += p.overall_score; scoreCount++ }
  }
  const progress = totalItems > 0 ? Math.round((completed / totalItems) * 100) : 0
  const score = scoreCount > 0 ? Math.round(totalScore / scoreCount) : null
  return { progress, score, totalItems, total: totalItems, completed, improving, missing }
})

// 类别弹窗
const showCategoryDialog = ref(false); const editCategory = ref(null)
const categoryForm = ref({ name: '', requirement_desc: '' })

// 对象弹窗
const showTargetDialog = ref(false); const editTargetItem = ref(null)
const targetForm = ref({ name: '', target_type: '', attributes: [] })

// 计划弹窗
const showAllCategories = ref(false)
const showPlanDialog = ref(false); const showEditPlanDialog = ref(false)
const planForm = ref({ name: '', description: '', due_date: '', priority: 'normal', category_ids: [], target_ids: [] })
const editPlanForm = ref({ id: '', name: '', due_date: '', priority: 'normal' })
const priorityOptions = [{ value: 'urgent', label: '紧急' }, { value: 'normal', label: '一般' }, { value: 'optional', label: '非必需' }]

// MultiSelect 组件所需的选项格式
const categoryOptions = computed(() =>
  categories.value.map(cat => ({ value: cat.id, label: cat.name, sub: cat.requirement_desc?.substring(0, 20) }))
)
const customCategoryOptions = computed(() =>
  categories.value
    .filter(cat => !cat.preset_category_id)  // 非预置类别即为手动创建
    .map(cat => ({ value: cat.id, label: cat.name, sub: cat.requirement_desc?.substring(0, 20) }))
)
const targetOptions = computed(() =>
  targets.value.map(tgt => ({ value: tgt.id, label: tgt.name, sub: tgt.target_type }))
)

// 唯一入口：immediate: true 覆盖初始加载 + 路由切换
watch(kbId, async (newId) => {
  if (newId) {
    currentKB.value = null
    await loadAll()
  }
}, { immediate: true })

async function loadAll() {
  loadError.value = false
  categories.value = []
  targets.value = []
  plans.value = []
  ragDocuments.value = []
  console.log('[KB Detail] loadAll 开始, kbId=', kbId.value)

  // 直接调用 API 获取原始数据，绕过 composable 的 _extractData 做个对照
  try {
    const rawResp = await fetch(`/api/knowledge-management/bases/${kbId.value}`, {
      headers: { Authorization: 'Bearer ' + (localStorage.getItem('auth_token') || '') }
    })
    const rawJson = await rawResp.json()
    console.log('[KB Detail] 原始 API 响应:', rawJson)
    // 手动画包: {code, data} → data
    const rawData = (rawJson && 'code' in rawJson && 'data' in rawJson) ? rawJson.data : rawJson
    console.log('[KB Detail] 解包后:', { id: rawData?.id, name: rawData?.name, kb_type: rawData?.kb_type, keys: Object.keys(rawData || {}) })
  } catch (e) {
    console.error('[KB Detail] 原始 API 请求失败:', e)
  }

  // 正常走 composable 流程
  try {
    const result = await fetchKnowledgeBase(kbId.value)
    console.log('[KB Detail] fetchKnowledgeBase 返回:', { type: typeof result, isArray: Array.isArray(result), id: result?.id, name: result?.name, kb_type: result?.kb_type })
    if (!result || Array.isArray(result)) {
      console.warn('[KB Detail] fetchKnowledgeBase 返回异常，currentKB 设为 null')
      currentKB.value = null
      loadError.value = true
    }
  } catch (e) {
    console.error('[KB Detail] 加载KB失败:', e)
    loadError.value = true
  }
  console.log('[KB Detail] loadAll 完成, currentKB.value=', { id: currentKB.value?.id, name: currentKB.value?.name, kb_type: currentKB.value?.kb_type, isArray: Array.isArray(currentKB.value) })

  if (!loadError.value && currentKB.value && !Array.isArray(currentKB.value)) {
    await Promise.allSettled([fetchCategories(kbId.value), fetchTargets(kbId.value), fetchPlans(kbId.value), fetchRAGDocuments(kbId.value)])
  } else {
    loading.categories = false
    loading.targets = false
    loading.plans = false
    loading.ragDocs = false
  }
}

watch(activeTab, t => { if (t === 'documents') refreshRAGDocs() })
function refreshRAGDocs() { fetchRAGDocuments(kbId.value) }
const refreshingKB = ref(false)
const kbLastRefresh = ref('')
async function refreshAll() {
  refreshingKB.value = true
  try {
    await Promise.allSettled([fetchPlans(kbId.value), fetchRAGDocuments(kbId.value), fetchCategories(kbId.value), fetchTargets(kbId.value)])
    kbLastRefresh.value = '刷新于 ' + new Date().toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit' })
    // 保留时间戳显示（不自动清除）
  } finally { refreshingKB.value = false }
}
const refreshingPlanEval = reactive(new Set())
async function refreshPlanEval(planId) {
  refreshingPlanEval.add(planId)
  try {
    const updatedPlan = await fetchPlanProgress(planId)
    if (updatedPlan) {
      const idx = plans.value.findIndex(p => p.id === planId)
      if (idx >= 0) {
        plans.value[idx] = { ...plans.value[idx], ...updatedPlan }
      }
    }
  } catch (e) { toast.error('刷新失败: ' + e.message) }
  finally { refreshingPlanEval.delete(planId) }
}

// 类别
function openCategoryDialog(cat) {
  editCategory.value = cat || null
  categoryForm.value = cat ? { name: cat.name, requirement_desc: cat.requirement_desc } : { name: '', requirement_desc: '' }
  showCategoryDialog.value = true
}
function editCategoryItem(cat) { openCategoryDialog(cat) }
async function handleSaveCategory() {
  try {
    if (editCategory.value) { await updateCategory(editCategory.value.id, { ...categoryForm.value }) } else { await createCategory(kbId.value, { ...categoryForm.value }) }
    showCategoryDialog.value = false
    toast.success(editCategory.value ? '类别已更新' : '类别已创建')
  } catch (e) { toast.error('保存失败: ' + e.message) }
}
function handleDeleteCategory(cat) {
  confirmDialog.value = { show: true, title: '删除类别', message: `确定删除类别"${cat.name}"？`, onOk: async () => { try { await deleteCategory(cat.id); toast.success('类别已删除') } catch (e) { toast.error('删除失败: ' + e.message) } finally { confirmDialog.value.show = false } } }
}

// 对象
function editTargetItemFn(tgt) {
  editTargetItem.value = tgt
  targetForm.value = { name: tgt.name, target_type: tgt.target_type, attributes: tgt.attributes ? JSON.parse(JSON.stringify(tgt.attributes)) : [] }
  showTargetDialog.value = true
}
function openTargetDialog() { editTargetItem.value = null; targetForm.value = { name: '', target_type: '', attributes: [] }; showTargetDialog.value = true }
async function handleSaveTarget() {
  try {
    const data = { name: targetForm.value.name, target_type: targetForm.value.target_type, attributes: targetForm.value.attributes.filter(a => a.label.trim()) }
    if (editTargetItem.value) { await updateTarget(editTargetItem.value.id, data) } else { await createTarget(kbId.value, data) }
    showTargetDialog.value = false
    toast.success(editTargetItem.value ? '对象已更新' : '对象已创建')
  } catch (e) { toast.error('保存失败: ' + e.message) }
}
function handleDeleteTarget(tgt) {
  confirmDialog.value = { show: true, title: '删除对象', message: `确定删除对象"${tgt.name}"？`, onOk: async () => { try { await deleteTarget(tgt.id); toast.success('对象已删除') } catch (e) { toast.error('删除失败: ' + e.message) } finally { confirmDialog.value.show = false } } }
}

// 计划
function openCreatePlan() {
  planForm.value = { name: '', description: '', due_date: '', priority: 'normal', category_ids: [], target_ids: [] }
  creatingCustom = false
  showPlanDialog.value = true
}
let creatingCustom = false
function openCreateCustomPlan() {
  planForm.value = { name: '', description: '', due_date: '', priority: 'normal', category_ids: [], target_ids: [] }
  creatingCustom = true
  showPlanDialog.value = true
}
function openEditPlan(plan) {
  editPlanForm.value = { id: plan.id, name: plan.name, due_date: plan.due_date || '', priority: plan.priority || 'normal' }
  showEditPlanDialog.value = true
}
async function handleCreatePlan() {
  try {
    const data = { knowledge_base_id: kbId.value, ...planForm.value }
    if (creatingCustom) data.is_custom = true
    await createPlan(data)
    showPlanDialog.value = false
    toast.success('收集计划已创建')
  } catch (e) { toast.error('创建失败: ' + e.message) }
}
async function handleSaveEditPlan() {
  try { await updatePlan(editPlanForm.value.id, { name: editPlanForm.value.name, due_date: editPlanForm.value.due_date, priority: editPlanForm.value.priority }); showEditPlanDialog.value = false; toast.success('计划已更新') } catch (e) { toast.error('保存失败: ' + e.message) }
}
function handleDeletePlan(plan) {
  confirmDialog.value = { show: true, title: '删除计划', message: `确定删除计划"${plan.name}"？收集项和文档将被级联删除。`, onOk: async () => { try { await deletePlan(plan.id); toast.success('计划已删除') } catch (e) { toast.error('删除失败: ' + e.message) } finally { confirmDialog.value.show = false } } }
}

// 计划选择/展开
function togglePlanExpand(id) { const s = new Set(expandedPlans.value); s.has(id) ? s.delete(id) : s.add(id); expandedPlans.value = s }
function togglePlanSelect(id) { const idx = selectedPlanIds.value.indexOf(id); if (idx >= 0) selectedPlanIds.value.splice(idx, 1); else selectedPlanIds.value.push(id) }
function selectAllPlans(all) { selectedPlanIds.value = all ? plans.value.map(p => p.id) : [] }
async function batchDeletePlans() {
  if (!await showConfirm(`确定删除选中的 ${selectedPlanIds.value.length} 个计划？`, '批量删除', { type: 'danger' })) return
  let failed = 0
  for (const id of selectedPlanIds.value) {
    try { await deletePlan(id) } catch (e) { failed++ }
  }
  selectedPlanIds.value = []
  if (failed) toast.error(failed + ' 个计划删除失败')
  else toast.success('已全部删除')
}

// 文档操作
function downloadRAGDoc(doc) {
  const token = localStorage.getItem('auth_token')
  fetch(`/api/knowledge-management/rag-documents/${doc.id}/download`, { headers: { Authorization: `Bearer ${token || ''}` } })
    .then(r => r.json())
    .then(data => {
      const url = data?.data?.download_url || data?.download_url
      if (!url) throw new Error('获取下载地址失败')
      const a = document.createElement('a')
      a.href = url
      a.download = doc.name || 'document'
      a.click()
      a.remove()
    })
    .catch(e => toast.error('下载失败: ' + e.message))
}

// 工具函数
function toggleArrayItem(arr, id) { const idx = arr.indexOf(id); if (idx >= 0) arr.splice(idx, 1); else arr.push(id) }
function priorityClass(p) { const v = (p || '').toLowerCase(); return v === 'urgent' || v === '紧急' ? 'bg-red-50 text-red-600' : v === 'normal' || v === '一般' ? 'bg-amber-50 text-amber-600' : 'bg-slate-100 text-slate-500' }
function priorityLabel(p) { const v = (p || "").toLowerCase(); return v === "urgent" || v === "紧急" ? "紧急" : v === "normal" || v === "一般" ? "一般" : "非必需" }
function scoreClass(s) { if (!s) return ''; if (s >= 85) return 'bg-emerald-50 text-emerald-600'; if (s >= 60) return 'bg-amber-50 text-amber-600'; return 'bg-red-50 text-red-600' }
function docTypeClass(t) {
  if (!t) return ''; const l = t.toLowerCase()
  if (l.includes('pdf')) return 'bg-red-50 text-red-600'; if (l.includes('excel') || l.includes('xlsx')) return 'bg-emerald-50 text-emerald-600'
  if (l.includes('word') || l.includes('doc')) return 'bg-blue-50 text-blue-600'; if (l.includes('img') || l.includes('图片')) return 'bg-purple-50 text-purple-600'
  return 'bg-slate-100 text-slate-500'
}
function formatSize(bytes) { if (!bytes) return '-'; if (bytes < 1024) return bytes + ' B'; if (bytes < 1048576) return (bytes / 1024).toFixed(1) + ' KB'; return (bytes / 1048576).toFixed(1) + ' MB' }
function formatDate(d) { if (!d) return '-'; try { return new Date(d).toLocaleDateString('zh-CN', { year: 'numeric', month: '2-digit', day: '2-digit' }) } catch { return d } }
</script>

<style scoped>
/* 按钮体系 */
.btn-primary { @apply inline-flex items-center gap-1.5 px-4 py-2 bg-amber-500 text-white text-[13px] font-medium rounded-lg hover:bg-amber-600 transition-colors disabled:opacity-50 disabled:cursor-not-allowed; }
.btn-ghost { @apply inline-flex items-center gap-1.5 px-3 py-1.5 text-slate-500 text-[13px] font-medium rounded-lg hover:bg-slate-100 transition-colors; }
.btn-outline-xs { @apply inline-flex items-center gap-1 px-2.5 py-1.5 text-slate-500 text-[13px] font-medium rounded-lg border border-slate-200 hover:bg-slate-50 hover:border-slate-300 transition-colors; }
.btn-icon-xs { @apply inline-flex items-center justify-center w-7 h-7 text-slate-400 hover:text-slate-600 hover:bg-slate-100 rounded-lg transition-colors; }

/* Tabs */
.tab { @apply px-5 py-2.5 text-[13px] font-medium text-slate-500 border-b-2 border-transparent hover:text-slate-700 transition-colors flex items-center gap-1.5; }
.tab.active { @apply text-amber-500 border-b-amber-500; }
.tab-badge { @apply px-1.5 py-0.5 rounded-md text-[11px] font-semibold bg-slate-100 text-slate-500; }
.tab.active .tab-badge { @apply bg-amber-50 text-amber-500; }

/* 文档类型标签 */
.doc-type-tag { @apply inline-block px-2 py-0.5 rounded text-[11px] font-semibold; }

/* 优先级 / 状态 */
.priority-tag { @apply inline-block px-1.5 py-0.5 rounded text-[11px] font-semibold; }
.status-badge { @apply inline-block px-1.5 py-0.5 rounded text-[11px] font-semibold; }

/* 评分圈 */
.score-circle { @apply inline-flex items-center justify-center w-9 h-9 rounded-full text-[13px] font-bold; }

/* 表单 */
.form-group { @apply mb-3.5; }
.form-label { @apply block text-[13px] font-medium text-slate-700 mb-1; }
.form-input, .form-textarea { @apply w-full px-3.5 py-2.5 border border-slate-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-amber-400/30 focus:border-amber-400 transition-shadow; }
.form-textarea { @apply resize-none; }

/* 弹窗 */
.modal-overlay { @apply fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm; }
.modal { @apply bg-white rounded-2xl shadow-xl w-full max-w-lg mx-4 p-6 animate-[modalIn_.2s_ease] max-h-[90vh] overflow-y-auto relative; }
.modal h3 { @apply text-base font-bold text-slate-800 mb-4 pr-8; }
.modal-footer { @apply flex justify-end gap-3 mt-5; }
.modal-close-x { @apply absolute top-3 right-3 w-8 h-8 flex items-center justify-center text-slate-400 hover:text-slate-700 hover:bg-slate-100 rounded-full text-2xl leading-none cursor-pointer; }

/* 多选 chip */
.check-chip { @apply inline-flex items-center gap-1 px-2.5 py-1 border border-slate-200 rounded text-xs cursor-pointer transition-colors select-none hover:border-slate-300; }
.check-chip.checked { @apply bg-amber-50 border-amber-400 text-amber-600; }
.check-chip input { @apply hidden; }

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
