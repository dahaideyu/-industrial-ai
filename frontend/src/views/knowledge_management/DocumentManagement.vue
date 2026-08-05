<template>
  <div class="h-full overflow-y-auto bg-slate-50">
    <!-- 面包屑 -->
    <div class="bg-white border-b border-slate-200 px-6 py-3 flex items-center gap-2 text-[13px]">
      <button class="inline-flex items-center gap-1.5 px-2 py-1.5 rounded-lg text-slate-500 hover:text-amber-500 hover:bg-amber-50 transition-colors" @click="router.back()">
        <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 19l-7-7 7-7"/></svg>
        返回收集项
      </button>
      <span class="text-slate-300">/</span>
      <span class="text-slate-700 font-medium">📄 管理文档 — {{ itemName }}</span>
    </div>

    <div class="p-6">
      <!-- 加载 -->
      <div v-if="loading.plan" class="flex items-center justify-center py-20">
        <div class="animate-spin rounded-full h-6 w-6 border-b-2 border-amber-500"></div>
        <span class="ml-2 text-slate-500 text-sm">加载中...</span>
      </div>

      <template v-else>
        <!-- 头部操作 -->
        <div class="flex items-center justify-between mb-5">
          <div>
            <h1 class="text-lg font-bold text-slate-800">{{ itemName }}</h1>
            <p class="text-sm text-slate-500 mt-1">文档管理 · {{ currentPlan?.name || '' }}</p>
          </div>
          <button class="btn-primary text-sm" @click="targetDocId = null; showUploadDialog = true">
            <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 4v16m8-8H4"/></svg>
            上传文档
          </button>
        </div>

        <!-- 合规性文档特有：AI检测结果 + 有效期填写 -->
        <div v-if="isCompliance" class="bg-blue-50 border border-blue-200 rounded-xl p-4 mb-4">
          <h4 class="text-sm font-semibold text-blue-800 mb-3">🤖 AI 视觉检测</h4>
          <div class="grid grid-cols-3 gap-3 text-xs">
            <div class="bg-white rounded-lg p-3 text-center">
              <div class="text-lg mb-1">{{ latestVersion?.has_stamp ? '🔴' : '⚪' }}</div>
              <div class="font-semibold">公章</div>
              <div :class="latestVersion?.has_stamp ? 'text-green-600' : 'text-slate-400'">{{ latestVersion?.has_stamp ? '已检测到' : '未检测到' }}</div>
            </div>
            <div class="bg-white rounded-lg p-3 text-center">
              <div class="text-lg mb-1">{{ latestVersion?.has_signature ? '🖊️' : '⚪' }}</div>
              <div class="font-semibold">签名</div>
              <div :class="latestVersion?.has_signature ? 'text-green-600' : 'text-slate-400'">{{ latestVersion?.has_signature ? '已检测到' : '未检测到' }}</div>
            </div>
            <div class="bg-white rounded-lg p-3 text-center">
              <div class="text-lg mb-1">{{ latestVersion?.valid_until ? '📅' : '⚠' }}</div>
              <div class="font-semibold">有效期</div>
              <div v-if="latestVersion?.valid_until" class="text-blue-600">{{ latestVersion.valid_from || '—' }} → {{ latestVersion.valid_until }}</div>
              <div v-else class="text-red-500">未识别</div>
            </div>
          </div>
          <!-- 手动填写有效期 -->
          <div class="mt-3 flex items-center gap-2 flex-wrap">
            <span class="text-xs text-blue-700 font-medium">手动设置有效期：</span>
            <input type="date" v-model="complianceValidFrom" class="border border-blue-200 rounded px-2 py-1 text-xs" />
            <span class="text-slate-400">→</span>
            <input type="date" v-model="complianceValidUntil" class="border border-blue-200 rounded px-2 py-1 text-xs" />
            <button class="bg-blue-600 text-white rounded px-3 py-1 text-xs hover:bg-blue-700" @click="saveComplianceDates" :disabled="!complianceValidFrom || !complianceValidUntil || savingCompliance">💾 保存</button>
          </div>
        </div>

        <!-- 文档列表 -->
        <div v-if="!documents.length" class="text-center py-16 text-slate-400 text-sm">暂无文档，请上传</div>
        <div v-else class="space-y-3">
          <template v-for="doc in documents" :key="doc.id">
          <!-- 图纸解析进度卡片 -->
          <div v-if="doc.file_type === 'plc' && doc.drawing_parse_status === 'processing'" class="bg-gradient-to-r from-blue-50 to-indigo-50 border border-blue-200 rounded-xl p-4">
            <div class="flex items-center gap-3 mb-3">
              <div class="animate-spin w-5 h-5 border-2 border-blue-500 border-t-transparent rounded-full"></div>
              <div>
                <h4 class="text-sm font-semibold text-blue-800">🔄 图纸解析进度</h4>
                <p class="text-xs text-blue-600">{{ doc.original_filename || doc.display_name }}</p>
              </div>
            </div>
            <!-- 进度条 -->
            <div class="mb-2">
              <div class="flex justify-between text-xs text-blue-700 mb-1">
                <span>{{ doc.drawing_parse_step || '准备中...' }}</span>
                <span>{{ doc.drawing_parse_progress || 0 }}%</span>
              </div>
              <div class="w-full h-2 bg-blue-100 rounded-full overflow-hidden">
                <div class="h-full bg-blue-500 rounded-full transition-all duration-500" :style="{ width: (doc.drawing_parse_progress || 0) + '%' }"></div>
              </div>
            </div>
            <p v-if="doc.drawing_parse_detail" class="text-[11px] text-blue-500 mt-1">{{ doc.drawing_parse_detail }}</p>
            <p class="text-[11px] text-blue-400 mt-2">⚠️ 解析完成后将自动生成说明文档，请勿进行其他操作</p>
          </div>

          <!-- 图纸解析失败提示 -->
          <div v-if="doc.file_type === 'plc' && doc.drawing_parse_status === 'failed'" class="bg-red-50 border border-red-200 rounded-xl p-4">
            <div class="flex items-center gap-3">
              <span class="text-red-500">❌</span>
              <div>
                <h4 class="text-sm font-semibold text-red-800">图纸解析失败</h4>
                <p class="text-xs text-red-600">{{ doc.drawing_parse_step || '未知错误' }}</p>
              </div>
            </div>
          </div>

          <!-- 文档卡片 -->
          <div class="bg-white border border-slate-200 rounded-xl overflow-hidden">
            <!-- 第一排：文档名 -->
            <div class="px-4 pt-3 pb-1 flex items-center gap-2">
              <template v-if="editingDocName === doc.id">
                <input v-model="editDocNameValue" class="text-[15px] font-semibold border-b-2 border-amber-400 outline-none px-1 py-0.5" @keyup.enter="saveDocName(doc)" @keyup.escape="editingDocName = null" @blur="saveDocName(doc)" />
              </template>
              <template v-else>
                <span class="text-[15px] font-semibold text-slate-800">{{ doc.display_name || doc.original_filename || '未命名' }}</span>
                <button v-if="!(doc.publish_status === 'published')" class="text-slate-300 hover:text-amber-500 transition-colors" @click="startEditDocName(doc)" title="编辑名称">
                  <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z"/></svg>
                </button>
              </template>
            </div>
            <!-- 第二排：属性 + 操作 -->
            <div class="flex items-center gap-5 px-4 py-2 text-[13px] border-t border-slate-50">
              <span class="text-slate-400 text-xs">类型</span>
              <span class="doc-type-tag text-[12px]" :class="docTypeClass(getDisplayVersion(doc).fileType)">{{ docTypeLabel(getDisplayVersion(doc).fileType) }}</span>
              <span class="text-slate-300">|</span>
              <span class="text-slate-400 text-xs">版本</span>
              <span class="font-medium text-slate-700">
                {{ getDisplayVersion(doc).versionLabel }}
                <span v-if="getDisplayVersion(doc).isDraft" class="text-amber-500">(审核中)</span>
              </span>
              <span class="text-slate-300">|</span>
              <span class="text-slate-400 text-xs">上传</span>
              <span class="text-slate-600">{{ formatDate(doc.created_at) }}</span>
              <span class="text-slate-300">|</span>
              <span class="text-slate-400 text-xs">状态</span>
              <span class="status-badge text-[12px]" :class="docStatusClass(doc)">{{ docStatusLabel(doc) }}</span>

              <span v-if="getDisplayVersion(doc).hasPublishedVersion" class="text-[10px] px-1.5 py-0.5 rounded bg-emerald-50 text-emerald-600 font-medium">{{ getDisplayVersion(doc).currentVersionLabel }} 已发布在线</span>

              <span class="flex-1"></span>

              <!-- 工作流按钮 -->
              <div class="flex items-center gap-1.5">
                <template v-if="getDisplayVersion(doc).isDraft">
                  <template v-if="getDisplayVersion(doc).status === 'pending'">
                    <button v-if="!isCompliance || getDisplayVersion(doc).valid_until" class="btn-workflow text-[12px] py-1.5 px-3 bg-purple-50 text-purple-600 hover:bg-purple-100 rounded font-medium" :disabled="processingDocs.has(doc.id) || doc.convert_status === 'processing' || doc.extract_status === 'processing'" @click="onTriggerAIReview(doc, getDisplayVersion(doc).versionId)">{{ doc.convert_status === 'processing' || doc.extract_status === 'processing' ? '⏳ 内容提取中...' : '🤖 AI审核' }}</button>
                    <button v-else class="btn-workflow text-[12px] py-1.5 px-3 bg-slate-100 text-slate-400 rounded font-medium cursor-not-allowed" disabled title="合规性文档须先填写有效期">⚠ 请先设置有效期</button>
                  </template>
                  <span v-else-if="getDisplayVersion(doc).status === 'ai_processing'" class="text-xs text-purple-500">⏳ AI审核中...</span>
                  <template v-else-if="getDisplayVersion(doc).status === 'ai_completed_manual_pending'">
                    <button class="btn-workflow text-[12px] py-1.5 px-3 bg-emerald-50 text-emerald-600 hover:bg-emerald-100 rounded font-medium" @click="onApprove(doc, getDisplayVersion(doc).versionId)">✓ 通过</button>
                    <button class="btn-workflow text-[12px] py-1.5 px-3 bg-red-50 text-red-500 hover:bg-red-100 rounded font-medium" @click="openRejectDialog(doc, getDisplayVersion(doc).versionId)">✗ 驳回</button>
                  </template>
                  <button v-else-if="getDisplayVersion(doc).status === 'approved'" class="btn-workflow text-[12px] py-1.5 px-3 bg-blue-50 text-blue-600 hover:bg-blue-100 rounded font-medium" @click="onPublish(doc, getDisplayVersion(doc).versionId)">🚀 确认发布</button>
                  <template v-else-if="getDisplayVersion(doc).status === 'rejected'">
                    <button class="btn-workflow text-[12px] py-1.5 px-3 bg-amber-50 text-amber-600 hover:bg-amber-100 rounded font-medium" @click="targetDocId = doc.id; showUploadDialog = true">🔄 重新上传</button>
                    <button class="text-[12px] py-1.5 px-3 text-red-500 border border-red-200 rounded hover:bg-red-50 font-medium" @click="handleDeleteDraft(doc, getDisplayVersion(doc).versionId)">删除草稿</button>
                  </template>
                </template>

                <template v-else-if="doc.publish_status === 'publishing'">
                  <span class="text-xs text-blue-500 flex items-center gap-1">
                    <span class="inline-block w-3 h-3 border-2 border-blue-400 border-t-transparent rounded-full animate-spin"></span>
                    发布中...
                  </span>
                </template>

                <template v-else-if="doc.publish_status === 'published'">
                  <template v-if="doc.parse_status === 'running'">
                    <span class="text-xs text-amber-500 flex items-center gap-1">
                      <span class="inline-block w-3 h-3 border-2 border-amber-400 border-t-transparent rounded-full animate-spin"></span>
                      解析中
                    </span>
                    <button class="btn-workflow text-[12px] py-1.5 px-3 bg-red-50 text-red-500 rounded font-medium" @click="onStopParse(doc)">⏹ 停止解析</button>
                  </template>
                  <template v-else-if="doc.parse_status === 'fail' || doc.parse_status === 'cancel' || doc.parse_status === 'unstart'">
                    <span class="text-xs text-red-500">{{ doc.parse_status === 'fail' ? '❌ 解析失败' : doc.parse_status === 'cancel' ? '⚠ 已取消' : '⏳ 待解析' }}</span>
                    <button class="btn-workflow text-[12px] py-1.5 px-3 bg-amber-50 text-amber-600 rounded font-medium" @click="onRetryParse(doc)">🔄 重试</button>
                    <button v-if="doc.version_count > 1" class="btn-workflow text-[12px] py-1.5 px-3 text-amber-600 border border-amber-200 rounded font-medium" @click="handleRollback(doc)">↩ 回滚</button>
                    <button class="text-[12px] py-1.5 px-3 text-red-500 border border-red-200 rounded font-medium" @click="handleDeleteDocument(doc.id)">删除</button>
                  </template>
                  <template v-else-if="doc.parse_status === 'done'">
                    <span class="text-xs text-emerald-500">✅ 解析完成</span>
                    <button class="btn-workflow text-[12px] py-1.5 px-3 bg-blue-50 text-blue-600 rounded font-medium" @click="targetDocId = doc.id; showUploadDialog = true">🔄 更新</button>
                    <button v-if="doc.version_count > 1" class="btn-workflow text-[12px] py-1.5 px-3 text-amber-600 border border-amber-200 rounded font-medium" @click="handleRollback(doc)">↩ 回滚</button>
                    <button class="text-[12px] py-1.5 px-3 text-red-500 border border-red-200 rounded font-medium" @click="handleDeleteDocument(doc.id)">删除</button>
                  </template>
                  <span v-else class="text-xs text-emerald-500">✓ 已发布</span>
                </template>

                <template v-else-if="!doc.status || doc.status === 'pending'">
                  <button v-if="!isCompliance || getDisplayVersion(doc).valid_until" class="btn-workflow text-[12px] py-1.5 px-3 bg-purple-50 text-purple-600 rounded font-medium" :disabled="doc.convert_status === 'processing' || doc.extract_status === 'processing'" @click="onTriggerAIReview(doc)">{{ doc.convert_status === 'processing' || doc.extract_status === 'processing' ? '⏳ 内容提取中...' : '🤖 AI审核' }}</button>
                  <button v-else class="btn-workflow text-[12px] py-1.5 px-3 bg-slate-100 text-slate-400 rounded font-medium cursor-not-allowed" disabled title="合规性文档须先填写有效期">⚠ 请先设置有效期</button>
                  <button class="text-[12px] py-1.5 px-3 text-red-500 border border-red-200 rounded hover:bg-red-50 font-medium" @click="handleDeleteDocument(doc.id)">删除</button>
                </template>
                <template v-else-if="doc.status === 'ai_processing'">
                  <span class="text-xs text-purple-500">⏳ AI审核中...</span>
                  <button class="text-[12px] py-1.5 px-3 text-red-500 border border-red-200 rounded hover:bg-red-50 font-medium" @click="handleDeleteDocument(doc.id)">删除</button>
                </template>
                <template v-else-if="doc.status === 'ai_retrying'">
                  <span class="text-xs text-amber-500 flex items-center gap-1">
                    <span class="inline-block w-3 h-3 border-2 border-amber-400 border-t-transparent rounded-full animate-spin"></span>
                    AI审核重试中...
                  </span>
                  <button class="text-[12px] py-1.5 px-3 text-red-500 border border-red-200 rounded hover:bg-red-50 font-medium" @click="handleDeleteDocument(doc.id)">删除</button>
                </template>
                <template v-else-if="doc.status === 'ai_review_failed'">
                  <span class="text-xs text-red-500">❌ AI审核失败</span>
                  <button class="btn-workflow text-[12px] py-1.5 px-3 bg-amber-50 text-amber-600 rounded font-medium" @click="onTriggerAIReview(doc)">🔄 重试审核</button>
                  <button class="text-[12px] py-1.5 px-3 text-red-500 border border-red-200 rounded hover:bg-red-50 font-medium" @click="handleDeleteDocument(doc.id)">删除</button>
                </template>
                <template v-else-if="doc.status === 'ai_completed_manual_pending'">
                  <button class="btn-workflow text-[12px] py-1.5 px-3 bg-emerald-50 text-emerald-600 rounded font-medium" @click="onApprove(doc)">✓ 通过</button>
                  <button class="btn-workflow text-[12px] py-1.5 px-3 bg-red-50 text-red-500 rounded font-medium" @click="openRejectDialog(doc)">✗ 驳回</button>
                  <button class="text-[12px] py-1.5 px-3 text-red-500 border border-red-200 rounded hover:bg-red-50 font-medium" @click="handleDeleteDocument(doc.id)">删除</button>
                </template>
                <template v-else-if="doc.status === 'approved'">
                  <button class="btn-workflow text-[12px] py-1.5 px-3 bg-blue-50 text-blue-600 rounded font-medium" @click="onPublish(doc)">🚀 确认发布</button>
                  <button class="text-[12px] py-1.5 px-3 text-red-500 border border-red-200 rounded hover:bg-red-50 font-medium" @click="handleDeleteDocument(doc.id)">删除</button>
                </template>
                <template v-else-if="doc.status === 'rejected'">
                  <button class="btn-workflow text-[12px] py-1.5 px-3 bg-amber-50 text-amber-600 rounded font-medium" @click="targetDocId = doc.id; showUploadDialog = true">🔄 重新上传</button>
                  <button class="text-[12px] py-1.5 px-3 text-red-500 border border-red-200 rounded hover:bg-red-50 font-medium" @click="handleDeleteDocument(doc.id)">删除</button>
                </template>
              </div>
            </div>

            <!-- 第三排：评分 + 预览 + 下载 -->
            <div class="flex items-center gap-4 px-4 pb-3 text-[13px]">
              <button v-if="getDisplayVersion(doc).versionId" class="text-amber-500 hover:text-amber-600 font-medium" @click="onPreviewDoc(doc)">📋 预览</button>
              <button v-if="getDisplayVersion(doc).versionId" class="text-amber-500 hover:text-amber-600 font-medium" @click="onDownloadDoc(doc)">⬇ 下载</button>
              <button v-if="getDisplayVersion(doc).versionId && getDisplayVersion(doc).extracted_text" class="text-amber-500 hover:text-amber-600 font-medium" @click="viewExtractedText(doc)">📝 文本</button>
              <span class="text-slate-300">|</span>
              <span class="text-slate-400 text-xs">关联性</span><b :class="scoreTextClass(getDisplayVersion(doc).ai_relevance_score)">{{ getDisplayVersion(doc).ai_relevance_score != null ? getDisplayVersion(doc).ai_relevance_score : '—' }}</b>
              <span class="text-slate-400 text-xs ml-3">质量</span><b :class="scoreTextClass(getDisplayVersion(doc).ai_quality_score)">{{ getDisplayVersion(doc).ai_quality_score != null ? getDisplayVersion(doc).ai_quality_score : '—' }}</b>
              <!-- AI审核建议状态 -->
              <span v-if="getDisplayVersion(doc).aiReviewDecision" class="ai-review-badge" :class="'ai-review-' + getDisplayVersion(doc).aiReviewDecision">🤖 {{ getDisplayVersion(doc).aiReviewDecision }}</span>
              <span v-if="getDisplayVersion(doc).ai_quality_remark" class="text-slate-400 text-xs truncate max-w-xs ml-3" :title="getDisplayVersion(doc).ai_quality_remark">{{ getDisplayVersion(doc).ai_quality_remark.split('[版本改进]')[0].split('[AI审核建议]')[0] }}</span>
              <span class="flex-1"></span>
              <button class="text-xs text-slate-400 hover:text-slate-600" @click="toggleDocVersions(doc.id)">
                {{ expandedDocVersions.includes(doc.id) ? '收起' : '展开' }}版本 ({{ doc.version_count || 0 }})
              </button>
            </div>

            <!-- 版本历史 -->
            <div v-if="expandedDocVersions.includes(doc.id)" class="border-t border-slate-100 bg-slate-50 px-4 py-3 text-xs overflow-x-auto">
              <table class="w-full min-w-[800px]">
                <thead>
                  <tr class="text-[10px] font-semibold text-slate-500 uppercase">
                    <th class="text-left pb-2 px-2 w-16">版本</th>
                    <th class="text-left pb-2 px-2 min-w-[200px]">文件名</th>
                    <th class="text-left pb-2 px-2 w-20">状态</th>
                    <th class="text-left pb-2 px-2 w-16">关联性</th>
                    <th class="text-left pb-2 px-2 w-16">质量</th>
                    <th class="text-left pb-2 px-2 w-36">上传时间</th>
                    <th class="text-left pb-2 px-2 w-40">操作</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="v in doc.versions" :key="v.id" class="hover:bg-white rounded text-[12px]">
                    <td class="py-1.5 px-2 font-medium text-slate-700">{{ v.version_label || '—' }}</td>
                    <td class="py-1.5 px-2 text-slate-600">{{ v.original_filename || '—' }}</td>
                    <td class="py-1.5 px-2"><span class="status-badge text-[10px]" :class="versionStatusClass(v)">{{ versionStatusLabel(v) }}</span></td>
                    <td class="py-1.5 px-2" :class="scoreTextClass(v.ai_relevance_score)">{{ v.ai_relevance_score || '—' }}</td>
                    <td class="py-1.5 px-2" :class="scoreTextClass(v.ai_quality_score)">{{ v.ai_quality_score || '—' }}</td>
                    <td class="py-1.5 px-2 text-slate-400">{{ formatDate(v.created_at) }}</td>
                    <td class="py-1.5 px-2">
                      <div class="flex gap-1.5">
                        <button class="text-amber-500 hover:text-amber-600 text-[11px]" @click="onPreviewVersion(v)">预览</button>
                        <button class="text-amber-500 hover:text-amber-600 text-[11px]" @click="onDownloadVersion(v)">下载</button>
                        <button class="text-amber-500 hover:text-amber-600 text-[11px]" @click="viewVersionText(v)">文本</button>
                        <button v-if="!v.is_current && !(v.publish_status === 'published')" class="text-red-400 hover:text-red-600 text-[11px]" @click="handleDeleteVersion(v)">删除</button>
                      </div>
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>
          </template>
        </div>
      </template>
    </div>

    <!-- 上传弹窗 -->
    <teleport to="body">
      <div v-if="showUploadDialog" class="modal-overlay" @click.self="cancelUpload">
        <div class="modal">
          <h3>上传文档到「{{ itemName }}」</h3>
          <div class="form-group">
            <label class="form-label">文件类型 <span class="text-red-500">* 选择后不可更改</span></label>
            <CustomSelect v-model="uploadFileType" :options="fileTypeOptions" class="w-full" />
            <p class="text-[11px] text-slate-400 mt-1">选择正确的文件类型有助于系统选择最佳处理方式</p>
            <div v-if="uploadFileType === 'plc'" class="mt-2 p-2.5 bg-blue-50 border border-blue-200 rounded-lg">
              <p class="text-[11px] text-blue-700 flex items-start gap-1.5">
                <svg class="w-3.5 h-3.5 mt-0.5 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"/></svg>
                <span>选择「图纸」类型后，系统将使用<strong>视觉AI模型</strong>辅助解析 PDF 图纸（如 PLC 梯形图、电气原理图等），并自动生成描述性说明文档。解析过程可能需要几分钟，请耐心等待。</span>
              </p>
            </div>
          </div>
          <div class="form-group">
            <label class="flex items-center gap-2 cursor-pointer">
              <input type="checkbox" v-model="uploadForceOCR" class="w-4 h-4 accent-amber-500">
              <span class="text-[13px] text-slate-700">扫描件（强制 OCR 识别）</span>
            </label>
            <p class="text-[11px] text-slate-400 mt-1">勾选后将使用OCR逐页识别文档中的文字</p>
          </div>
          <div class="form-group">
            <label class="form-label">选择文件 <span class="text-red-500">*</span></label>
            <div class="border-2 border-dashed border-slate-200 rounded-xl p-6 text-center hover:border-amber-400 transition-colors cursor-pointer" @click="triggerFileInput" @dragover.prevent @drop.prevent="onDrop">
              <svg class="w-8 h-8 text-slate-300 mx-auto mb-2" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12"/></svg>
              <p class="text-sm text-slate-500">拖拽文件或<span class="text-amber-500 font-medium">点击选择</span></p>
              <input ref="fileInputRef" type="file" multiple class="hidden" @change="onFileSelect" accept=".pdf,.doc,.docx,.xls,.xlsx,.ppt,.pptx,.png,.jpg,.jpeg,.txt,.csv" />
            </div>
          </div>
          <div v-if="selectedFiles.length > 0" class="form-group">
            <label class="form-label">已选文件 ({{ selectedFiles.length }})</label>
            <div class="max-h-40 overflow-y-auto space-y-1.5">
              <div v-for="(file, idx) in selectedFiles" :key="idx" class="flex items-center justify-between px-3 py-2 bg-slate-50 rounded-lg text-[13px]">
                <span class="text-slate-700 truncate flex-1">{{ file.name }}</span>
                <span class="text-slate-400 text-xs mx-2">{{ formatFileSize(file.size) }}</span>
                <button class="text-red-400 hover:text-red-600" @click="selectedFiles.splice(idx, 1)"><svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/></svg></button>
              </div>
            </div>
          </div>
          <div v-if="uploading" class="flex items-center gap-2 text-sm text-slate-600 py-2">
            <div class="animate-spin rounded-full h-4 w-4 border-b-2 border-amber-500"></div> 上传中...
          </div>
          <p v-if="uploadError" class="text-red-500 text-xs mt-1">{{ uploadError }}</p>
          <div class="modal-footer">
            <button class="btn-ghost" @click="cancelUpload" :disabled="uploading">取消</button>
            <button class="btn-primary" :disabled="selectedFiles.length === 0 || uploading" @click="handleUpload">{{ uploading ? '上传中...' : '开始上传' }}</button>
          </div>
        </div>
      </div>
    </teleport>

    <!-- 驳回弹窗 -->
    <teleport to="body">
      <div v-if="rejectDialog.show" class="modal-overlay" @click.self="rejectDialog.show = false">
        <div class="modal max-w-sm">
          <h3>驳回文档</h3>
          <p class="text-xs text-slate-500 mb-3">驳回「{{ rejectDialog.docName }}」：</p>
          <div class="form-group"><textarea v-model="rejectDialog.reason" class="form-textarea" rows="3" placeholder="驳回原因（必填）"></textarea></div>
          <div class="modal-footer">
            <button class="btn-ghost" @click="rejectDialog.show = false">取消</button>
            <button class="btn-primary !bg-red-500 hover:!bg-red-600" :disabled="!rejectDialog.reason.trim()" @click="onReject">确认驳回</button>
          </div>
        </div>
      </div>
    </teleport>

    <!-- 确认弹窗 -->
    <teleport to="body">
      <div v-if="confirmDialog.show" class="modal-overlay" @click.self="resolveConfirm(false)">
        <div class="modal max-w-sm text-center">
          <div class="w-12 h-12 rounded-full bg-amber-100 flex items-center justify-center mx-auto mb-3 text-amber-500">
            <svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-2.5L13.732 4c-.77-.833-1.964-.833-2.732 0L4.082 16.5c-.77.833.192 2.5 1.732 2.5z"/></svg>
          </div>
          <h3 class="text-base font-bold text-slate-800 mb-1">{{ confirmDialog.title }}</h3>
          <p class="text-slate-500 text-[13px] mb-5">{{ confirmDialog.message }}</p>
          <div class="flex justify-center gap-3">
            <button class="btn-ghost" @click="resolveConfirm(false)">取消</button>
            <button class="btn-primary !bg-red-500 hover:!bg-red-600" @click="resolveConfirm(true)">{{ confirmDialog.okText || '确认' }}</button>
          </div>
        </div>
      </div>
    </teleport>

    <!-- PDF 预览 -->
    <FilePreview v-if="previewDoc" :preview-url="previewDoc.previewUrl" :doc-name="previewDoc.docName" :relevance-score="previewDoc.relevanceScore" :quality-score="previewDoc.qualityScore" :relevance-remark="previewDoc.relevanceRemark" :quality-remark="previewDoc.qualityRemark" @close="previewDoc = null" />

    <!-- 提取文本查看弹窗 -->
    <teleport to="body">
      <div v-if="showTextDialog" class="modal-overlay" @click.self="showTextDialog = null">
        <div class="modal !max-w-[90vw] !w-[90vw]">
          <div class="flex items-center justify-between mb-4">
            <h3 class="mb-0">📝 {{ showTextDialog.title }}</h3>
            <div class="flex items-center gap-2">
              <button
                v-if="showTextDialog.isMarkdown"
                class="text-xs px-2 py-1 rounded"
                :class="showTextDialog.renderMode === 'markdown' ? 'bg-amber-500 text-white' : 'bg-slate-200 text-slate-600'"
                @click="showTextDialog.renderMode = 'markdown'"
              >Markdown</button>
              <button
                v-if="showTextDialog.isMarkdown"
                class="text-xs px-2 py-1 rounded"
                :class="showTextDialog.renderMode === 'source' ? 'bg-amber-500 text-white' : 'bg-slate-200 text-slate-600'"
                @click="showTextDialog.renderMode = 'source'"
              >源码</button>
            </div>
          </div>
          <div class="max-h-[75vh] overflow-y-auto bg-slate-50 rounded-lg p-5 mt-3">
            <!-- Markdown 渲染模式 -->
            <div v-if="showTextDialog.isMarkdown && showTextDialog.renderMode === 'markdown'" class="prose prose-sm max-w-none" v-html="renderedMarkdown"></div>
            <!-- 源码模式 -->
            <pre v-else class="text-sm text-slate-700 whitespace-pre-wrap font-sans leading-relaxed">{{ showTextDialog.text }}</pre>
          </div>
          <div class="modal-footer"><button class="btn-primary" @click="showTextDialog = null">关闭</button></div>
        </div>
      </div>
    </teleport>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onBeforeUnmount } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { marked } from 'marked'
import { useKnowledgeManagement } from '../../composables/knowledge_management/useKnowledgeManagement.js'
import { formatDateTime as formatDate, formatFileSize } from '../../utils/format.js'
import CustomSelect from './components/CustomSelect.vue'
import FilePreview from './components/FilePreview.vue'
import { getDocumentPreviewUrl, deleteVersion, getParseStatus, reparseDocument, stopParse, updateDocument } from '../../api/knowledgeManagementClient.js'

// 配置 marked
marked.setOptions({
  breaks: true,
  gfm: true,
})

function buildOnlyOfficeUrl(rawFileUrl, fileName) {
  // 已弃用 OnlyOffice，保留函数防止报错
  return rawFileUrl
}

const route = useRoute()
const router = useRouter()
const itemId = computed(() => route.params.itemId)
const isCompliance = computed(() => route.query.compliance === '1')

const { currentPlan, loading, fetchPlan, fetchPlanItemEvaluation, uploadDocuments, deleteDocument: removeDocument, triggerAIReview: triggerAI, submitApproval: submitAppr, publishToRAGFlow: publishRAG } = useKnowledgeManagement()

// 合规性特有
const complianceValidFrom = ref('')
const complianceValidUntil = ref('')
const savingCompliance = ref(false)
import { updateComplianceDates } from '../../api/knowledgeManagementClient.js'
import { useToast } from '../../composables/useToast'
const toast = useToast()

// 最新文档版本（用于展示AI检测结果）
const latestVersion = computed(() => {
  for (const doc of documents.value) {
    const v = getDisplayVersion(doc)
    if (v && (v.has_stamp != null || v.valid_until != null)) return v
    // check drafts too
    if (doc.draft_version_id && doc.draft_has_stamp != null) {
      return { has_stamp: doc.draft_has_stamp, has_signature: doc.draft_has_signature, valid_from: doc.draft_valid_from, valid_until: doc.draft_valid_until }
    }
  }
  return null
})

async function saveComplianceDates() {
  if (!complianceValidFrom.value || !complianceValidUntil.value) return
  savingCompliance.value = true
  try {
    // 找到第一个文档的当前版本
    for (const doc of documents.value) {
      const v = getDisplayVersion(doc)
      if (v && v.versionId) {
        await updateComplianceDates(v.versionId, {
          valid_from: complianceValidFrom.value,
          valid_until: complianceValidUntil.value,
        })
        toast.success('有效期已保存')
        await fetchPlan(route.query.planId)
        return
      }
    }
    toast.warn('未找到可更新的文档版本')
  } catch (e) { toast.error('保存失败: ' + e.message) }
  finally { savingCompliance.value = false }
}

const itemName = ref('加载中...')
const documents = computed(() => {
  const items = currentPlan.value?.plan_items || []
  const item = items.find(i => i.id === itemId.value)
  if (item) {
    itemName.value = (item.category?.name || item.category_name || '') + ' · ' + (item.target?.name || item.target_name || '')
  }
  return item?.documents || []
})

// 检查是否允许触发 AI 审核（合规性文档必须先填写有效期）
function canTriggerAIReview(doc) {
  const dv = getDisplayVersion(doc)
  if (!isCompliance.value) return { allowed: true, reason: '' }
  if (!dv.valid_until) return { allowed: false, reason: '⚠ 请先设置有效期' }
  return { allowed: true, reason: '' }
}

// 从质量备注中提取 AI 审核建议
function extractAiDecision(remark) {
  if (!remark) return null
  const m = remark.match(/\[AI审核建议\]\s*(通过|驳回|待完善)/)
  return m ? m[1] : null
}

// 获取主行应展示的版本信息
function getDisplayVersion(doc) {
  if (doc.draft_version_id) {
    const draftRemark = doc.draft_ai_quality_remark || ''
    return {
      versionId: doc.draft_version_id,
      versionLabel: doc.draft_version_label,
      status: doc.draft_status,
      filename: doc.draft_original_filename || doc.original_filename,
      fileType: doc.draft_file_type || doc.file_type,
      rejectedReason: doc.draft_rejected_reason,
      isDraft: true,
      hasPublishedVersion: doc.publish_status === 'published',
      currentVersionLabel: doc.current_version_label,
      currentVersionId: doc.current_version_id,
      // 草稿版本的评分信息
      ai_relevance_score: doc.draft_ai_relevance_score,
      ai_quality_score: doc.draft_ai_quality_score,
      ai_relevance_remark: doc.draft_ai_relevance_remark,
      ai_quality_remark: draftRemark,
      aiReviewDecision: extractAiDecision(draftRemark),
      extracted_text: doc.draft_extracted_text,
      created_at: doc.draft_created_at,
      // 合规性字段
      has_stamp: doc.draft_has_stamp,
      has_signature: doc.draft_has_signature,
      valid_from: doc.draft_valid_from,
      valid_until: doc.draft_valid_until,
      compliance_score: doc.draft_compliance_score,
    }
  }
  const currentRemark = doc.ai_quality_remark || ''
  return {
    versionId: doc.current_version_id,
    versionLabel: doc.current_version_label,
    status: doc.status,
    filename: doc.original_filename,
    fileType: doc.file_type,
    isDraft: false,
    hasPublishedVersion: false,
    currentVersionId: doc.current_version_id,
    // 当前版本的评分信息
    ai_relevance_score: doc.ai_relevance_score,
    ai_quality_score: doc.ai_quality_score,
    ai_relevance_remark: doc.ai_relevance_remark,
    ai_quality_remark: currentRemark,
    aiReviewDecision: extractAiDecision(currentRemark),
    extracted_text: doc.extracted_text,
    created_at: doc.created_at,
    // 合规性字段
    has_stamp: doc.has_stamp,
    has_signature: doc.has_signature,
    valid_from: doc.valid_from,
    valid_until: doc.valid_until,
    compliance_score: doc.compliance_score,
  }
}

const expandedDocVersions = ref([])
const processingDocs = ref(new Set())
const rejectDialog = ref({ show: false, docId: '', versionId: '', docName: '', reason: '' })
const confirmDialog = ref({ show: false, title: '', message: '', okText: '' })
let confirmResolve = null
function showConfirm(title, message, okText) { return new Promise(resolve => { confirmResolve = resolve; confirmDialog.value = { show: true, title, message, okText } }) }
function resolveConfirm(result) { confirmDialog.value.show = false; if (confirmResolve) { confirmResolve(result); confirmResolve = null } }
const previewDoc = ref(null)

// 上传
const showUploadDialog = ref(false)
const targetDocId = ref(null)  // null=新建文档，有值=更新已有文档
const uploadFileType = ref('general')
const uploadForceOCR = ref(false)
const selectedFiles = ref([])
const uploading = ref(false)
const uploadError = ref('')
const fileInputRef = ref(null)
const fileTypeOptions = [{ value: 'general', label: '通用' }, { value: 'table', label: '表格' }, { value: 'image', label: '图片' }, { value: 'manual', label: '手册' }, { value: 'plc', label: '图纸' }]

let autoRefreshTimer = null
let parsePollTimer = null
const editingDocName = ref(null)
const editDocNameValue = ref('')
function startEditDocName(doc) {
  editingDocName.value = doc.id
  editDocNameValue.value = doc.display_name || doc.original_filename || ''
}
const showTextDialog = ref(null) // { title, text, isMarkdown, renderMode }

// 计算属性：渲染Markdown
const renderedMarkdown = computed(() => {
  if (!showTextDialog.value?.text) return ''
  return marked(showTextDialog.value.text)
})

function viewExtractedText(doc) {
  const dv = getDisplayVersion(doc)
  const text = dv.extracted_text || doc.extracted_text || '(暂无提取内容)'
  const isMarkdown = (doc.original_filename || '').endsWith('.md') || (doc.display_name || '').endsWith('.md')
  showTextDialog.value = {
    title: doc.display_name || doc.original_filename || '文档',
    text,
    isMarkdown,
    renderMode: isMarkdown ? 'markdown' : 'source',
  }
}

function viewVersionText(v) {
  const text = v.extracted_text || '(暂无提取内容)'
  const isMarkdown = (v.original_filename || '').endsWith('.md')
  showTextDialog.value = {
    title: `${v.original_filename || '文档'} (${v.version_label})`,
    text,
    isMarkdown,
    renderMode: isMarkdown ? 'markdown' : 'source',
  }
}

async function saveDocName(doc) {
  if (!editingDocName.value) return
  const newName = editDocNameValue.value.trim()
  editingDocName.value = null
  if (!newName || newName === (doc.display_name || doc.original_filename)) return
  try {
    await updateDocument(doc.id, { display_name: newName })
    doc.display_name = newName
  } catch (e) { alert('保存失败: ' + e.message) }
}

// 轮询解析状态：对 parse_status === 'running' 的文档实时查询 RAGFlow
async function pollParseStatus() {
  if (!documents.value || !Array.isArray(documents.value)) return
  for (const doc of documents.value) {
    if (doc.publish_status === 'published' && doc.parse_status === 'running' && doc.current_version_id) {
      try {
        const data = await getParseStatus(doc.current_version_id)
        const status = data?.data?.parse_status || data?.parse_status
        if (status && status !== doc.parse_status) {
          doc.parse_status = status
          if (data?.data?.progress !== undefined) doc.parse_progress = data.data.progress
        }
      } catch (e) { /* 网络波动，下次轮询重试 */ }
    }
  }
}

onMounted(async () => {
  try { await fetchPlan(route.query.planId) } catch (e) { console.error(e) }
  autoRefreshTimer = setInterval(async () => { try { await fetchPlan(route.query.planId) } catch {} }, 15000)
  parsePollTimer = setInterval(pollParseStatus, 3000)  // 每 3 秒轮询解析状态
})

onBeforeUnmount(() => {
  if (autoRefreshTimer) clearInterval(autoRefreshTimer)
  if (parsePollTimer) clearInterval(parsePollTimer)
})

// 工作流
function toggleDocVersions(docId) {
  const idx = expandedDocVersions.value.indexOf(docId)
  if (idx >= 0) expandedDocVersions.value.splice(idx, 1); else expandedDocVersions.value.push(docId)
}

async function onTriggerAIReview(doc, specificVersionId) {
  const versionId = specificVersionId || doc.current_version_id
  if (!versionId) { alert('文档无当前版本'); return }
  processingDocs.value.add(doc.id)
  try { await triggerAI(versionId); await fetchPlan(route.query.planId) }
  catch (e) { alert('AI审核触发失败: ' + (e.response?.data?.detail || e.message)) }
  finally { processingDocs.value.delete(doc.id) }
}

async function onApprove(doc, specificVersionId) {
  const versionId = specificVersionId || doc.current_version_id
  if (!versionId) { alert('文档无当前版本'); return }
  if (!(await showConfirm('审批通过', `确认通过「${doc.display_name || doc.original_filename}」的审核？`, '通过'))) return
  processingDocs.value.add(doc.id)
  try { await submitAppr(versionId, 'approve'); await fetchPlan(route.query.planId) }
  catch (e) { alert('审批失败: ' + (e.response?.data?.detail || e.message)) }
  finally { processingDocs.value.delete(doc.id) }
}

function openRejectDialog(doc, specificVersionId) {
  rejectDialog.value = {
    show: true,
    docId: doc.id,
    versionId: specificVersionId || doc.current_version_id,
    docName: doc.display_name || doc.original_filename || '文档',
    reason: '',
  }
}

async function onReject() {
  const dlg = rejectDialog.value
  if (!dlg.reason.trim()) return
  processingDocs.value.add(dlg.docId)
  try { await submitAppr(dlg.versionId, 'reject', dlg.reason); rejectDialog.value.show = false; await fetchPlan(route.query.planId) }
  catch (e) { alert('驳回失败: ' + (e.response?.data?.detail || e.message)) }
  finally { processingDocs.value.delete(dlg.docId) }
}

async function onPublish(doc, specificVersionId) {
  const versionId = specificVersionId || doc.current_version_id
  if (!versionId) { alert('文档无当前版本'); return }
  if (!(await showConfirm('确认发布', '确认发布该文档到知识库？', '发布'))) return
  processingDocs.value.add(doc.id)
  try { await publishRAG(versionId); await fetchPlan(route.query.planId) }
  catch (e) { alert('发布失败: ' + (e.response?.data?.detail || e.message)) }
  finally { processingDocs.value.delete(doc.id) }
}

async function onStopParse(doc) {
  if (!doc.current_version_id) return
  processingDocs.value.add(doc.id)
  try {
    await stopParse(doc.current_version_id)
    doc.parse_status = 'cancel'
  } catch (e) { alert('停止解析失败: ' + e.message) }
  finally { processingDocs.value.delete(doc.id) }
}

async function onRetryParse(doc) {
  if (!doc.current_version_id) return
  processingDocs.value.add(doc.id)
  try {
    await reparseDocument(doc.current_version_id)
    doc.parse_status = 'running'
  } catch (e) { alert('重试解析失败: ' + e.message) }
  finally { processingDocs.value.delete(doc.id) }
}

async function handleRollback(doc) {
  if (!doc.current_version_id) return
  const label = doc.current_version_label || '当前版本'
  if (!(await showConfirm(
    '回滚版本',
    `将删除「${doc.display_name || doc.original_filename}」的 ${label}，自动恢复到上一个版本。\n\n⚠️ 当前版本将从知识库中移除，上一版本将重新生效。`,
    '确认回滚'
  ))) return
  processingDocs.value.add(doc.id)
  try {
    await deleteVersion(doc.current_version_id)
    await fetchPlan(route.query.planId)
  } catch (e) { alert('回滚失败: ' + e.message) }
  finally { processingDocs.value.delete(doc.id) }
}

async function handleDeleteDraft(doc, draftVersionId) {
  if (!(await showConfirm('删除草稿', `确定删除「${doc.display_name || doc.original_filename}」的草稿版本？已发布的版本不受影响。`, '删除'))) return
  try {
    await deleteVersion(draftVersionId)
    await fetchPlan(route.query.planId)
  } catch (e) { alert('删除草稿失败: ' + e.message) }
}

async function handleDeleteDocument(docId) {
  const doc = documents.value.find(d => d.id === docId)
  const name = doc ? (doc.display_name || doc.original_filename) : '该文档'
  const versionCount = doc?.version_count || 0
  const warn = versionCount > 1
    ? `确定永久删除「${name}」及其全部 ${versionCount} 个版本？\n\n⚠️ 此操作不可恢复！所有版本及关联数据将被彻底清除。`
    : `确定永久删除「${name}」？\n\n⚠️ 此操作不可恢复！文档及关联数据将被彻底清除。`
  if (!(await showConfirm('删除文档', warn, '确认删除'))) return
  try {
    await removeDocument(docId)
    targetDocId.value = null
    await fetchPlan(route.query.planId)
  } catch (e) { alert('删除失败: ' + e.message) }
}

// 上传
// 不支持的 PLC 源码文件格式
const UNSUPPORTED_EXTENSIONS = ['.awl', '.stl', '.scl', '.db', '.gxw', '.gpp', '.cxp', '.cx5']

function triggerFileInput() { fileInputRef.value?.click() }

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
function cancelUpload() { if (uploading.value) return; showUploadDialog.value = false; selectedFiles.value = []; uploadError.value = ''; uploadForceOCR.value = false; targetDocId.value = null }

async function handleUpload() {
  if (!selectedFiles.value.length) return
  uploading.value = true; uploadError.value = ''
  let progressTimer = null
  try {
    // 如果有 targetDocId，则为更新已有文档（创建新版本）
    const docId = targetDocId.value || undefined
    const formData = new FormData(); selectedFiles.value.forEach(f => formData.append('files', f))
    if (docId) formData.append('document_id', docId)
    if (uploadForceOCR.value) formData.append('force_ocr', 'true')
    // 传递文件类型
    formData.append('file_type', uploadFileType.value)
    progressTimer = setInterval(() => {}, 300)
    await uploadDocuments(itemId.value, formData)
    showUploadDialog.value = false; selectedFiles.value = []; targetDocId.value = null
    await fetchPlan(route.query.planId)
  } catch (e) { uploadError.value = '上传失败: ' + (e.response?.data?.detail || e.message) }
  finally { if (progressTimer) clearInterval(progressTimer); uploading.value = false }
}

// 预览/下载
async function onPreviewDoc(doc) {
  if (!doc.current_version_id) return

  const filename = doc.original_filename || doc.display_name || ''
  const token = localStorage.getItem('auth_token')

  // Markdown 直接显示内容
  if (filename.endsWith('.md')) { viewExtractedText(doc); return }

  // Excel/Word/PPT 转预览后获取URL
  const needConvert = ['.xls', '.xlsx', '.xlsm', '.doc', '.docx', '.ppt', '.pptx']
  if (needConvert.some(ext => filename.toLowerCase().endsWith(ext))) {
    try {
      const resp = await fetch(getDocumentPreviewUrl(doc.current_version_id), { headers: { Authorization: 'Bearer ' + (token || '') } })
      const data = await resp.json()
      const url = data?.data?.preview_url || data?.preview_url || ''
      const convertStatus = data?.data?.convert_status || data?.convert_status
      if (!url) {
        if (convertStatus === 'processing') { alert('文件正在转换中，请稍后刷新重试') }
        else if (convertStatus === 'failed') { alert('文件转换失败，请联系管理员') }
        else { alert('文件转换未完成，请稍后重试') }
        return
      }
      previewDoc.value = { docName: doc.display_name || doc.original_filename || '文档预览', relevanceScore: doc.ai_relevance_score, qualityScore: doc.ai_quality_score, relevanceRemark: doc.ai_relevance_remark || '', qualityRemark: doc.ai_quality_remark || '', previewUrl: url }
    } catch (e) { alert('获取预览失败: ' + e.message) }
    return
  }

  // CSV 直接下载
  if (/\.csv$/i.test(filename)) { onDownloadDoc(doc); return }

  // 图片预览（PNG/JPG/BMP等）
  if (/\.(png|jpe?g|bmp|gif|webp|tiff?)$/i.test(filename)) {
    try {
      const resp = await fetch(getDocumentPreviewUrl(doc.current_version_id), { headers: { Authorization: 'Bearer ' + (token || '') } })
      const data = await resp.json()
      const url = data?.data?.preview_url || data?.preview_url || ''
      if (!url) { toast.warn('获取预览地址失败'); return }
      previewDoc.value = { docName: doc.display_name || doc.original_filename || '图片预览', relevanceScore: doc.ai_relevance_score, qualityScore: doc.ai_quality_score, relevanceRemark: doc.ai_relevance_remark || '', qualityRemark: doc.ai_quality_remark || '', previewUrl: url }
    } catch (e) { toast.error('获取预览失败: ' + e.message) }
    return
  }

  // PDF 文件预览
  try {
    const resp = await fetch(getDocumentPreviewUrl(doc.current_version_id), { headers: { Authorization: 'Bearer ' + (token || '') } })
    const data = await resp.json()
    const url = data?.data?.preview_url || data?.preview_url || ''
    if (!url) { alert('获取预览地址失败'); return }
    previewDoc.value = { docName: doc.display_name || doc.original_filename || '文档预览', relevanceScore: doc.ai_relevance_score, qualityScore: doc.ai_quality_score, relevanceRemark: doc.ai_relevance_remark || '', qualityRemark: doc.ai_quality_remark || '', previewUrl: url }
  } catch (e) { alert('获取预览失败: ' + e.message) }
}

async function onPreviewVersion(v) {
  const filename = v.original_filename || ''
  const token = localStorage.getItem('auth_token')

  if (filename.endsWith('.md')) { viewVersionText(v); return }

  const needConvert = ['.xls', '.xlsx', '.xlsm', '.doc', '.docx', '.ppt', '.pptx']
  if (needConvert.some(ext => filename.toLowerCase().endsWith(ext))) {
    try {
      const resp = await fetch(getDocumentPreviewUrl(v.id), { headers: { Authorization: 'Bearer ' + (token || '') } })
      const data = await resp.json()
      const url = data?.data?.preview_url || data?.preview_url || ''
      const convertStatus = data?.data?.convert_status || data?.convert_status
      if (!url) {
        if (convertStatus === 'processing') { alert('文件正在转换中，请稍后刷新重试') }
        else if (convertStatus === 'failed') { alert('文件转换失败，请联系管理员') }
        else { alert('文件转换未完成，请稍后重试') }
        return
      }
      previewDoc.value = { docName: v.original_filename || '版本预览', relevanceScore: v.ai_relevance_score, qualityScore: v.ai_quality_score, relevanceRemark: v.ai_relevance_remark || '', qualityRemark: v.ai_quality_remark || '', previewUrl: url }
    } catch (e) { alert('获取预览失败: ' + e.message) }
    return
  }

  if (/\.csv$/i.test(filename)) { onDownloadVersion(v); return }

  // 图片预览
  if (/\.(png|jpe?g|bmp|gif|webp|tiff?)$/i.test(filename)) {
    try {
      const resp = await fetch(getDocumentPreviewUrl(v.id), { headers: { Authorization: 'Bearer ' + (token || '') } })
      const data = await resp.json()
      const url = data?.data?.preview_url || data?.preview_url || ''
      if (!url) { toast.warn('获取预览地址失败'); return }
      previewDoc.value = { docName: v.original_filename || '图片预览', relevanceScore: v.ai_relevance_score, qualityScore: v.ai_quality_score, relevanceRemark: v.ai_relevance_remark || '', qualityRemark: v.ai_quality_remark || '', previewUrl: url }
    } catch (e) { toast.error('获取预览失败: ' + e.message) }
    return
  }

  try {
    const resp = await fetch(getDocumentPreviewUrl(v.id), { headers: { Authorization: 'Bearer ' + (token || '') } })
    const data = await resp.json()
    const url = data?.data?.preview_url || data?.preview_url || ''
    if (!url) { toast.warn('获取预览地址失败'); return }
    previewDoc.value = { docName: v.original_filename || '版本预览', relevanceScore: v.ai_relevance_score, qualityScore: v.ai_quality_score, relevanceRemark: v.ai_relevance_remark || '', qualityRemark: v.ai_quality_remark || '', previewUrl: url }
  } catch (e) { toast.error('获取预览失败: ' + e.message) }
}

function onDownloadDoc(doc) {
  if (!doc.current_version_id) return
  const token = localStorage.getItem('auth_token')
  // 1. 获取 MinIO 预签名 URL
  fetch(`/api/knowledge-management/versions/${doc.current_version_id}/download`, { headers: { Authorization: `Bearer ${token || ''}` } })
    .then(r => r.json())
    .then(data => {
      const url = data?.data?.download_url || data?.download_url
      if (!url) throw new Error('获取下载地址失败')
      // 2. 从 MinIO 下载实际文件
      const a = document.createElement('a')
      a.href = url
      a.download = doc.original_filename || doc.display_name || 'document'
      a.click()
      a.remove()
    })
    .catch(e => alert('下载失败: ' + e.message))
}

async function handleDeleteVersion(v) {
  const doc = documents.value.find(d => d.versions?.some(ver => ver.id === v.id))
  const isLastVersion = doc && doc.version_count <= 1
  const warn = isLastVersion
    ? `确定删除版本「${v.version_label || v.original_filename}」？\n\n⚠️ 这是最后一个版本，删除后整个文档将被永久删除！`
    : `确定删除版本「${v.version_label || v.original_filename}」？此操作不可恢复。`
  if (!confirm(warn)) return
  try { await deleteVersion(v.id); await fetchPlan(route.query.planId) } catch (e) { alert('删除失败: ' + e.message) }
}

function onDownloadVersion(v) {
  const token = localStorage.getItem('auth_token')
  fetch(`/api/knowledge-management/versions/${v.id}/download`, { headers: { Authorization: `Bearer ${token || ''}` } })
    .then(r => r.json())
    .then(data => {
      const url = data?.data?.download_url || data?.download_url
      if (!url) throw new Error('获取下载地址失败')
      const a = document.createElement('a')
      a.href = url
      a.download = v.original_filename || 'document'
      a.click()
      a.remove()
    })
    .catch(e => alert('下载失败: ' + e.message))
}

// 工具
function docTypeLabel(t) { const m = { general: '通用', table: '表格', image: '图片', manual: '手册', plc: '图纸' }; return m[t] || t || '通用' }
function docTypeClass(t) { const m = { general: 'bg-slate-100 text-slate-600', table: 'bg-emerald-50 text-emerald-600', image: 'bg-purple-50 text-purple-600', manual: 'bg-blue-50 text-blue-600', plc: 'bg-amber-50 text-amber-600' }; return m[t] || 'bg-slate-100 text-slate-500' }
function docStatusLabel(doc) {
  const dv = getDisplayVersion(doc)
  if (dv.isDraft) {
    const s = dv.status
    if (s === 'pending') return '待审核'
    if (s === 'ai_processing') return 'AI审核中'
    if (s === 'ai_retrying') return 'AI审核重试中'
    if (s === 'ai_completed_manual_pending') return '待审批'
    if (s === 'approved') return '待发布'
    if (s === 'rejected') return '已驳回'
    if (s === 'ai_review_failed') return 'AI审核失败'
    return '草稿'
  }
  if (doc.convert_status === 'processing' || doc.extract_status === 'processing') return '内容提取中'
  if (doc.publish_status === 'publishing') return '发布中'
  if (doc.publish_status === 'published') return '已发布'
  if (doc.status === 'approved') return '待发布'
  if (doc.status === 'rejected') return '已驳回'
  if (doc.status === 'ai_completed_manual_pending') return '待审核'
  if (doc.status === 'ai_processing') return 'AI审核中'
  if (doc.status === 'ai_retrying') return 'AI审核重试中'
  if (doc.status === 'ai_review_failed') return 'AI审核失败'
  return '待处理'
}

function docStatusClass(doc) {
  const dv = getDisplayVersion(doc)
  if (dv.isDraft) {
    const s = dv.status
    if (s === 'pending' || s === 'ai_processing') return 'bg-purple-50 text-purple-600'
    if (s === 'ai_retrying') return 'bg-amber-50 text-amber-600'
    if (s === 'ai_completed_manual_pending') return 'bg-amber-50 text-amber-600'
    if (s === 'approved') return 'bg-blue-50 text-blue-600'
    if (s === 'rejected') return 'bg-red-50 text-red-600'
    if (s === 'ai_review_failed') return 'bg-red-50 text-red-600'
    return 'bg-slate-100 text-slate-500'
  }
  if (doc.publish_status === 'publishing') return 'bg-blue-50 text-blue-600'
  if (doc.publish_status === 'published') return 'bg-emerald-50 text-emerald-600'
  if (doc.status === 'approved') return 'bg-blue-50 text-blue-600'
  if (doc.status === 'rejected') return 'bg-red-50 text-red-600'
  if (doc.status === 'ai_completed_manual_pending') return 'bg-amber-50 text-amber-600'
  if (doc.status === 'ai_processing') return 'bg-purple-50 text-purple-600'
  if (doc.status === 'ai_retrying') return 'bg-amber-50 text-amber-600'
  if (doc.status === 'ai_review_failed') return 'bg-red-50 text-red-600'
  return 'bg-slate-100 text-slate-500'
}
function versionStatusLabel(v) {
  if (v.publish_status === 'published') return '已发布'
  if (v.publish_status === 'publishing') return '发布中'
  if (v.publish_status === 'replaced') return '已替换'
  if (v.publish_status === 'failed') return '发布失败'
  if (v.status === 'pending') return '待审核'
  if (v.status === 'ai_processing') return 'AI审核中'
  if (v.status === 'ai_retrying') return 'AI审核重试中'
  if (v.status === 'ai_completed_manual_pending') return '待审批'
  if (v.status === 'approved') return '待发布'
  if (v.status === 'rejected') return '已驳回'
  if (v.status === 'ai_review_failed') return 'AI审核失败'
  return '处理中'
}
function versionStatusClass(v) {
  if (v.publish_status === 'published') return 'bg-emerald-50 text-emerald-600'
  if (v.publish_status === 'publishing') return 'bg-blue-50 text-blue-600'
  if (v.publish_status === 'replaced') return 'bg-slate-100 text-slate-500'
  if (v.publish_status === 'failed') return 'bg-red-50 text-red-600'
  if (v.status === 'approved') return 'bg-blue-50 text-blue-600'
  if (v.status === 'rejected') return 'bg-red-50 text-red-600'
  if (v.status === 'ai_review_failed') return 'bg-red-50 text-red-600'
  if (v.status === 'ai_retrying') return 'bg-amber-50 text-amber-600'
  return 'bg-slate-100 text-slate-500'
}
function scoreTextClass(s) { if (s == null) return 'text-slate-300'; return s >= 85 ? 'text-emerald-600' : s >= 60 ? 'text-amber-600' : 'text-red-600' }
</script>

<style scoped>
.ai-review-badge { @apply inline-block px-2 py-0.5 rounded-full text-[11px] font-semibold ml-2; }
.ai-review-通过 { @apply bg-emerald-50 text-emerald-600; }
.ai-review-待完善 { @apply bg-amber-50 text-amber-600; }
.ai-review-驳回 { @apply bg-red-50 text-red-600; }

/* Markdown 渲染样式 */
.prose h1 { @apply text-2xl font-bold mt-6 mb-4 pb-2 border-b; }
.prose h2 { @apply text-xl font-bold mt-5 mb-3 pb-1 border-b; }
.prose h3 { @apply text-lg font-semibold mt-4 mb-2; }
.prose h4 { @apply text-base font-semibold mt-3 mb-2; }
.prose p { @apply my-2 leading-relaxed; }
.prose ul, .prose ol { @apply my-2 pl-6; }
.prose ul { @apply list-disc; }
.prose ol { @apply list-decimal; }
.prose li { @apply my-1; }
.prose blockquote { @apply pl-4 border-l-4 border-slate-300 italic text-slate-600 my-3; }
.prose code { @apply bg-slate-100 px-1.5 py-0.5 rounded text-sm font-mono; }
.prose pre { @apply bg-slate-800 text-slate-100 p-4 rounded-lg overflow-x-auto my-3; }
.prose pre code { @apply bg-transparent p-0; }
.prose table { @apply w-full border-collapse my-3; }
.prose th, .prose td { @apply border border-slate-300 px-3 py-2 text-left; }
.prose th { @apply bg-slate-100 font-semibold; }
.prose hr { @apply my-6 border-slate-300; }
.prose a { @apply text-amber-600 hover:underline; }
.prose strong { @apply font-bold; }
.prose em { @apply italic; }
</style>
