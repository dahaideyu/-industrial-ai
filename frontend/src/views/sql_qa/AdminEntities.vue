<template>
  <div class="p-6 h-full overflow-y-auto">
    <div class="mb-6">
      <h2 class="text-lg font-semibold text-gray-800">实体消歧</h2>
      <p class="text-sm text-gray-400 mt-1">管理实体别名映射、自定义指标和向量索引</p>
    </div>

    <div class="bg-white rounded-xl border border-gray-200 overflow-hidden">
      <div class="flex gap-1 border-b border-gray-200 px-4 pt-3">
        <button v-for="t in entityTabs" :key="t.key" @click="tab = t.key"
          :class="['px-4 py-2.5 text-sm font-medium rounded-t-lg transition-colors', tab === t.key ? 'bg-amber-400 text-gray-900' : 'text-gray-500 hover:text-gray-700 hover:bg-gray-100']">
          {{ t.label }}
        </button>
      </div>
      <div class="p-4">

    <!-- ==================== Alias Manager ==================== -->
    <div v-if="tab === 'aliases'">
      <div class="mb-4">
        <h3 class="text-base font-semibold text-gray-700">添加别名映射</h3>
        <div class="flex gap-2 mt-2">
          <button @click="handleExportAliases" class="text-xs px-3 py-1.5 rounded border border-gray-200 text-gray-600 hover:bg-gray-50">导出 JSON</button>
          <button @click="showAliasImport = true" class="text-xs px-3 py-1.5 rounded border border-gray-200 text-gray-600 hover:bg-gray-50">导入 JSON</button>
        </div>
      </div>

      <div class="flex gap-2 mb-4">
        <SqlQaSelect v-model="aliasForm.entity_type" :options="entityOptions" widthClass="w-56" />
        <input v-model="aliasForm.alias" placeholder="别名 (如: 冲网)" class="text-sm px-4 py-2.5 border border-gray-200 rounded w-36 focus:outline-none focus:border-amber-400" />
        <input v-model="aliasForm.canonical_name" placeholder="标准名称 (如: 正冲网线)" class="text-sm px-4 py-2.5 border border-gray-200 rounded w-44 focus:outline-none focus:border-amber-400" />
        <button @click="addAlias" :disabled="aliasLoading" class="text-xs px-3 py-1.5 rounded bg-amber-400 text-gray-900 font-medium hover:bg-amber-300 disabled:opacity-40">
          {{ aliasLoading ? '添加中...' : '添加' }}
        </button>
      </div>

      <h4 class="text-sm text-gray-600 mb-2">现有别名 ({{ aliases.length }})</h4>
      <div v-if="aliases.length === 0" class="text-center text-sm text-gray-400 py-8">暂无别名映射</div>
      <table v-else class="w-full text-xs border-collapse">
        <thead><tr class="bg-gray-50">
          <th class="px-3 py-2 text-left font-medium text-gray-600">类型</th>
          <th class="px-3 py-2 text-left font-medium text-gray-600">别名</th>
          <th class="px-3 py-2 text-left font-medium text-gray-600">标准名称</th>
          <th class="w-28 px-3 py-2 text-left font-medium text-gray-600">操作</th>
        </tr></thead>
        <tbody>
          <tr v-for="a in aliases" :key="a.id" class="border-b border-gray-100 hover:bg-gray-50">
            <td class="px-3 py-1.5"><span class="text-xs px-2 py-0.5 rounded bg-gray-100 text-gray-600">{{ typeLabel(a.entity_type) }}</span></td>
            <td class="px-3 py-1.5 text-gray-700">{{ a.alias }}</td>
            <td class="px-3 py-1.5 text-gray-700">{{ a.canonical_name }}</td>
            <td class="px-3 py-1.5">
              <div class="flex gap-1">
                <button @click="startEditAlias(a)" class="text-xs px-2 py-0.5 rounded border border-gray-200 text-gray-500 hover:text-gray-700">编辑</button>
                <button @click="delAlias(a.id)" class="text-xs px-2 py-0.5 rounded border border-red-200 text-red-500 hover:bg-red-50">删除</button>
              </div>
            </td>
          </tr>
        </tbody>
      </table>

      <!-- Edit Alias Modal -->
      <div v-if="editingAlias" class="fixed inset-0 z-50 flex items-center justify-center bg-black/40" @click.self="editingAlias = null">
        <div class="bg-white rounded-xl shadow-xl p-6 w-full max-w-md m-4">
          <h3 class="text-lg font-semibold text-gray-800 mb-4">编辑别名</h3>
          <div class="space-y-3">
            <SqlQaSelect v-model="editAliasForm.entity_type" :options="entityOptions" class="w-full" />
            <input v-model="editAliasForm.alias" placeholder="别名" class="w-full px-4 py-3 border border-gray-200 rounded text-sm focus:outline-none focus:border-amber-400" />
            <input v-model="editAliasForm.canonical_name" placeholder="标准名称" class="w-full px-4 py-3 border border-gray-200 rounded text-sm focus:outline-none focus:border-amber-400" />
          </div>
          <div class="flex gap-3 mt-4">
            <button @click="submitEditAlias" class="px-4 py-2 text-sm rounded bg-amber-400 text-gray-900 font-medium hover:bg-amber-300">保存</button>
            <button @click="editingAlias = null" class="px-4 py-2 text-sm rounded border border-gray-200 text-gray-600 hover:bg-gray-50">取消</button>
          </div>
        </div>
      </div>

      <SqlQaImportModal :open="showAliasImport" title="导入实体别名数据" entityLabel="实体别名" :onImport="handleImportAliases" @close="showAliasImport = false" @done="loadAliases" />
    </div>

    <!-- ==================== Metrics Manager ==================== -->
    <div v-if="tab === 'metrics'">
      <div class="mb-4">
        <h3 class="text-base font-semibold text-gray-700">添加自定义指标</h3>
        <div class="flex gap-2 mt-2">
          <button @click="handleExportMetrics" class="text-xs px-3 py-1.5 rounded border border-gray-200 text-gray-600 hover:bg-gray-50">导出 JSON</button>
          <button @click="showMetricImport = true" class="text-xs px-3 py-1.5 rounded border border-gray-200 text-gray-600 hover:bg-gray-50">导入 JSON</button>
        </div>
      </div>

      <div class="flex gap-2 mb-4">
        <input v-model="metricForm.name" placeholder="指标名称 (如: 月均故障率)" class="text-sm px-4 py-2.5 border border-gray-200 rounded w-44 focus:outline-none focus:border-amber-400" />
        <input v-model="metricForm.description" placeholder="描述" class="text-sm px-4 py-2.5 border border-gray-200 rounded w-36 focus:outline-none focus:border-amber-400" />
        <input v-model="metricForm.keywords" placeholder="触发关键词, 逗号分隔" class="text-sm px-4 py-2.5 border border-gray-200 rounded w-48 focus:outline-none focus:border-amber-400" />
        <button @click="addMetric" :disabled="metricLoading" class="text-xs px-3 py-1.5 rounded bg-amber-400 text-gray-900 font-medium hover:bg-amber-300 disabled:opacity-40">
          {{ metricLoading ? '添加中...' : '添加' }}
        </button>
      </div>

      <h4 class="text-sm text-gray-600 mb-2">现有指标 ({{ metrics.length }})</h4>
      <div v-if="metrics.length === 0" class="text-center text-sm text-gray-400 py-8">暂无自定义指标</div>
      <table v-else class="w-full text-xs border-collapse">
        <thead><tr class="bg-gray-50">
          <th class="px-3 py-2 text-left font-medium text-gray-600">名称</th>
          <th class="px-3 py-2 text-left font-medium text-gray-600">描述</th>
          <th class="px-3 py-2 text-left font-medium text-gray-600">关键词</th>
          <th class="w-28 px-3 py-2 text-left font-medium text-gray-600">操作</th>
        </tr></thead>
        <tbody>
          <tr v-for="m in metrics" :key="m.id" class="border-b border-gray-100 hover:bg-gray-50">
            <td class="px-3 py-1.5 text-gray-700">{{ m.name }}</td>
            <td class="px-3 py-1.5 text-gray-500">{{ m.description }}</td>
            <td class="px-3 py-1.5 text-gray-500">{{ m.keywords }}</td>
            <td class="px-3 py-1.5">
              <div class="flex gap-1">
                <button @click="startEditMetric(m)" class="text-xs px-2 py-0.5 rounded border border-gray-200 text-gray-500 hover:text-gray-700">编辑</button>
                <button @click="delMetric(m.id)" class="text-xs px-2 py-0.5 rounded border border-red-200 text-red-500 hover:bg-red-50">删除</button>
              </div>
            </td>
          </tr>
        </tbody>
      </table>

      <!-- Edit Metric Modal -->
      <div v-if="editingMetric" class="fixed inset-0 z-50 flex items-center justify-center bg-black/40" @click.self="editingMetric = null">
        <div class="bg-white rounded-xl shadow-xl p-6 w-full max-w-md m-4">
          <h3 class="text-lg font-semibold text-gray-800 mb-4">编辑指标</h3>
          <div class="space-y-3">
            <input v-model="editMetricForm.name" placeholder="名称" class="w-full px-4 py-3 border border-gray-200 rounded text-sm focus:outline-none focus:border-amber-400" />
            <input v-model="editMetricForm.description" placeholder="描述" class="w-full px-4 py-3 border border-gray-200 rounded text-sm focus:outline-none focus:border-amber-400" />
            <input v-model="editMetricForm.keywords" placeholder="关键词 (逗号分隔)" class="w-full px-4 py-3 border border-gray-200 rounded text-sm focus:outline-none focus:border-amber-400" />
          </div>
          <div class="flex gap-3 mt-4">
            <button @click="submitEditMetric" class="px-4 py-2 text-sm rounded bg-amber-400 text-gray-900 font-medium hover:bg-amber-300">保存</button>
            <button @click="editingMetric = null" class="px-4 py-2 text-sm rounded border border-gray-200 text-gray-600 hover:bg-gray-50">取消</button>
          </div>
        </div>
      </div>

      <SqlQaImportModal :open="showMetricImport" title="导入自定义指标数据" entityLabel="自定义指标" :onImport="handleImportMetrics" @close="showMetricImport = false" @done="loadMetrics" />
    </div>

    <!-- ==================== Entity Tools ==================== -->
    <div v-if="tab === 'tools'">
      <!-- Entity Search -->
      <div class="mb-6 p-4 border border-gray-200 rounded-xl">
        <h3 class="text-base font-semibold text-gray-700 mb-3">实体搜索</h3>
        <div class="flex gap-2 mb-3">
          <SqlQaSelect v-model="searchType" :options="entityOptions" />
          <input v-model="searchKw" placeholder="输入关键词搜索..." @keydown.enter="doSearch" class="text-sm px-4 py-2.5 border border-gray-200 rounded w-56 focus:outline-none focus:border-amber-400" />
          <button @click="doSearch" class="text-xs px-3 py-1.5 rounded bg-amber-400 text-gray-900 font-medium hover:bg-amber-300">搜索</button>
        </div>
        <table v-if="searchResults.length > 0" class="w-full text-xs border-collapse">
          <thead><tr class="bg-gray-50">
            <th class="px-3 py-2 text-left font-medium text-gray-600">名称</th>
            <th class="px-3 py-2 text-left font-medium text-gray-600">类型</th>
            <th class="px-3 py-2 text-left font-medium text-gray-600">详情</th>
            <th class="px-3 py-2 text-left font-medium text-gray-600">相似度</th>
          </tr></thead>
          <tbody>
            <tr v-for="(r, i) in searchResults" :key="i" class="border-b border-gray-100">
              <td class="px-3 py-1.5 text-gray-700">{{ r.label }}</td>
              <td class="px-3 py-1.5"><span class="text-xs px-2 py-0.5 rounded bg-gray-100 text-gray-600">{{ typeLabel(r.entity_type) }}</span></td>
              <td class="px-3 py-1.5 text-gray-400">{{ r.sublabel }}</td>
              <td class="px-3 py-1.5 text-gray-600">{{ r.score != null ? (r.score * 100).toFixed(1) + '%' : '—' }}</td>
            </tr>
          </tbody>
        </table>
        <p v-if="searchKw && searchResults.length === 0 && !searchLoading" class="text-xs text-gray-400 mt-2">未找到匹配的实体</p>
      </div>

      <!-- Entity Config Management -->
      <div class="p-4 border border-gray-200 rounded-xl">
        <div class="flex items-center justify-between mb-3">
          <div>
            <h3 class="text-base font-semibold text-gray-700">实体向量索引</h3>
            <p class="text-xs text-gray-400 mt-1">配置需要向量化的数据库表和实体信息，配置完成后点击"重建索引"生效</p>
          </div>
          <div class="flex gap-2">
            <button @click="showAddEntity = true" class="text-xs px-3 py-1.5 rounded bg-amber-400 text-gray-900 font-medium hover:bg-amber-300">增加实体</button>
            <button @click="doRebuild" :disabled="indexLoading" class="text-xs px-3 py-1.5 rounded border border-amber-400 text-amber-600 hover:bg-amber-50 disabled:opacity-50">{{ indexLoading ? '索引中...' : '重建索引' }}</button>
          </div>
        </div>
        <span v-if="indexMsg" class="text-xs" :class="indexMsg.includes('失败') ? 'text-red-500' : 'text-gray-500'">{{ indexMsg }}</span>

        <!-- Config List -->
        <div v-if="entityConfigs.length === 0" class="text-center text-sm text-gray-400 py-4">暂无实体配置，点击"增加实体"开始</div>
        <table v-else class="w-full text-xs border-collapse mt-3">
          <thead><tr class="bg-gray-50">
            <th class="px-3 py-2 text-left font-medium text-gray-600">标签</th>
            <th class="px-3 py-2 text-left font-medium text-gray-600">表名</th>
            <th class="px-3 py-2 text-left font-medium text-gray-600">搜索列</th>
            <th class="px-3 py-2 text-left font-medium text-gray-600">关键词</th>
            <th class="w-20 px-3 py-2 text-left font-medium text-gray-600">状态</th>
            <th class="w-28 px-3 py-2 text-left font-medium text-gray-600">操作</th>
          </tr></thead>
          <tbody>
            <tr v-for="c in entityConfigs" :key="c.id" class="border-b border-gray-100">
              <td class="px-3 py-1.5 text-gray-700 font-medium">{{ c.label }}</td>
              <td class="px-3 py-1.5 text-gray-500 font-mono text-[11px]">{{ c.table_name }}</td>
              <td class="px-3 py-1.5 text-gray-500">{{ (c.search_columns || []).join(', ') || c.label_column }}</td>
              <td class="px-3 py-1.5 text-gray-400">{{ (c.keyword_hints || []).slice(0,4).join(', ') }}{{ (c.keyword_hints || []).length > 4 ? '...' : '' }}</td>
              <td class="px-3 py-1.5">
                <span :class="['text-xs px-2 py-0.5 rounded', c.is_indexed ? 'bg-green-50 text-green-600' : 'bg-gray-100 text-gray-400']">
                  {{ c.is_indexed ? '已索引' : '未索引' }}
                </span>
              </td>
              <td class="px-3 py-1.5">
                <div class="flex gap-1">
                  <button @click="startEditEntity(c)" class="text-xs px-2 py-0.5 rounded border border-gray-200 text-gray-500 hover:text-gray-700">编辑</button>
                  <button @click="delEntityConfig(c.id)" class="text-xs px-2 py-0.5 rounded border border-red-200 text-red-500 hover:bg-red-50">删除</button>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <!-- Add/Edit Entity Modal -->
      <div v-if="showAddEntity || editingEntity" class="fixed inset-0 z-50 flex items-center justify-center bg-black/40" @click.self="closeEntityModal">
        <div class="bg-white rounded-xl shadow-xl p-6 w-full max-w-lg m-4 max-h-[90vh] overflow-y-auto">
          <h3 class="text-lg font-semibold text-gray-800 mb-4">{{ editingEntity ? '编辑实体配置' : '增加实体' }}</h3>
          <div class="space-y-3">
            <div>
              <label class="block text-xs text-gray-500 mb-1">数据库表 <span class="text-red-400">*</span></label>
              <SqlQaSelect v-model="entityForm.table_name" :options="[{value:'',label:'请选择表...'}, ...tableOptions]" class="w-full" />
            </div>
            <div class="grid grid-cols-2 gap-3">
              <div>
                <label class="block text-xs text-gray-500 mb-1">实体标签 <span class="text-red-400">*</span></label>
                <input v-model="entityForm.label" placeholder="如：设备、产线" class="w-full px-3 py-2 border border-gray-200 rounded text-sm focus:outline-none focus:border-amber-400" />
              </div>
              <div>
                <label class="block text-xs text-gray-500 mb-1">实体类型键 <span class="text-red-400">*</span></label>
                <input v-model="entityForm.entity_type" placeholder="如：device" class="w-full px-3 py-2 border border-gray-200 rounded text-sm focus:outline-none focus:border-amber-400" />
              </div>
            </div>
            <div class="grid grid-cols-2 gap-3">
              <div>
                <label class="block text-xs text-gray-500 mb-1">名称列</label>
                <SqlQaSelect v-model="entityForm.label_column" :options="[{value:'',label:'选择列...'}, ...columnOptions]" class="w-full" />
              </div>
              <div>
                <label class="block text-xs text-gray-500 mb-1">ID列</label>
                <SqlQaSelect v-model="entityForm.value_column" :options="[{value:'',label:'选择列...'}, ...columnOptions]" class="w-full" />
              </div>
            </div>
            <div>
              <label class="block text-xs text-gray-500 mb-1">搜索列（可多选）</label>
              <div class="flex flex-wrap gap-1">
                <button v-for="c in tableColumns" :key="c.name" @click="toggleSearchCol(c.name)"
                  :class="['text-xs px-2 py-1 rounded border transition-colors', entityForm.search_columns.includes(c.name) ? 'border-amber-400 bg-amber-50 text-amber-700' : 'border-gray-200 text-gray-500 hover:border-gray-300']">
                  {{ c.name }}
                </button>
              </div>
            </div>
            <div>
              <label class="block text-xs text-gray-500 mb-1">上下文列</label>
              <div class="flex flex-wrap gap-1">
                <button v-for="c in tableColumns" :key="'ctx-'+c.name" @click="toggleContextCol(c.name)"
                  :class="['text-xs px-2 py-1 rounded border transition-colors', entityForm.context_columns.includes(c.name) ? 'border-blue-400 bg-blue-50 text-blue-700' : 'border-gray-200 text-gray-500 hover:border-gray-300']">
                  {{ c.name }}
                </button>
              </div>
            </div>
            <div>
              <label class="block text-xs text-gray-500 mb-1">搜索关键词</label>
              <div class="flex flex-wrap gap-1 mb-2">
                <span v-for="(kw, i) in entityForm.keyword_hints" :key="i" class="text-xs px-2 py-0.5 rounded bg-gray-100 text-gray-600 flex items-center gap-1">
                  {{ kw }}
                  <button @click="entityForm.keyword_hints.splice(i, 1)" class="text-gray-400 hover:text-red-500">&times;</button>
                </span>
              </div>
              <div class="flex gap-2">
                <button @click="onGenerateKeywords" :disabled="kwLoading" class="text-xs px-3 py-1.5 rounded border border-blue-200 text-blue-600 hover:bg-blue-50 disabled:opacity-50">{{ kwLoading ? '生成中...' : 'AI 生成关键词' }}</button>
                <input v-model="newKeyword" @keydown.enter="addKeyword" placeholder="手动输入关键词..." class="flex-1 text-xs px-2.5 py-1.5 border border-gray-200 rounded focus:outline-none focus:border-amber-400" />
                <button @click="addKeyword" class="text-xs px-2 py-1.5 rounded bg-gray-100 text-gray-500 hover:bg-gray-200">添加</button>
              </div>
            </div>
            <div>
              <label class="block text-xs text-gray-500 mb-1">过滤条件（WHERE）</label>
              <input v-model="entityForm.filter_condition" placeholder="如：del_flag = 0" class="w-full px-3 py-2 border border-gray-200 rounded text-sm font-mono focus:outline-none focus:border-amber-400" />
              <p class="text-[10px] text-gray-400 mt-0.5">索引时拼接 WHERE 条件，过滤不需要的实体</p>
            </div>
          </div>
          <div class="flex gap-3 mt-4">
            <button @click="saveEntity" :disabled="saving" class="px-4 py-2 text-sm rounded bg-amber-400 text-gray-900 font-medium hover:bg-amber-300 disabled:opacity-50">{{ saving ? '保存中...' : '保存' }}</button>
            <button @click="closeEntityModal" class="px-4 py-2 text-sm rounded border border-gray-200 text-gray-600 hover:bg-gray-50">取消</button>
          </div>
        </div>
      </div>

      <!-- Entity Relationship Enhancement -->
      <div class="mt-6 p-4 border border-gray-200 rounded-xl">
        <div class="flex items-center justify-between mb-3">
          <div>
            <h3 class="text-base font-semibold text-gray-700">实体关系增强</h3>
            <p class="text-xs text-gray-400 mt-1">配置实体间的层级与关联关系，导入 Neo4j 知识图谱后可增强实体消歧的语义理解能力</p>
          </div>
          <button @click="openGraphMappingEditor" class="text-xs px-3 py-1.5 rounded bg-amber-400 text-gray-900 font-medium hover:bg-amber-300 whitespace-nowrap">配置关系映射</button>
        </div>

        <div class="flex items-center gap-3 text-xs">
          <span class="flex items-center gap-1">
            <span :class="['w-2 h-2 rounded-full', graphStatus.available ? 'bg-green-400' : 'bg-red-400']"></span>
            Neo4j: {{ graphStatus.available ? '已连接' : '未连接' }}
          </span>
          <span v-if="graphStatus.available && graphStatus.node_counts" class="text-gray-400">
            {{ Object.entries(graphStatus.node_counts).map(([k,v]) => `${graphStatus.label_zh?.[k] || k}: ${v}`).join(' | ') }}
          </span>
        </div>
        <p v-if="graphMappingMsg && !showGraphMappingEditor" class="text-xs mt-2" :class="graphMappingMsg.includes('失败') || graphMappingMsg.includes('错误') ? 'text-red-500' : 'text-green-600'">{{ graphMappingMsg }}</p>
      </div>

      <!-- Graph Mapping Editor Modal -->
      <div v-if="showGraphMappingEditor" class="fixed inset-0 z-50 flex items-center justify-center bg-black/40" @click.self="closeGraphMappingEditor">
        <div class="bg-white rounded-xl shadow-xl p-6 w-full max-w-3xl m-4 max-h-[90vh] flex flex-col">
          <h3 class="text-lg font-semibold text-gray-800 mb-2">实体关系映射配置</h3>
          <p class="text-xs text-gray-400 mb-3">编辑 YAML 配置，保存后将自动导入 Neo4j 知识图谱。修改前建议先参考示例。</p>

          <details v-if="graphMappingExample" class="mb-3 border border-blue-200 rounded-lg overflow-hidden">
            <summary class="px-3 py-2 bg-blue-50 text-xs text-blue-700 cursor-pointer font-medium">查看示例和配置说明</summary>
            <pre class="text-[11px] text-gray-600 bg-gray-50 p-3 max-h-64 overflow-auto whitespace-pre-wrap">{{ graphMappingExample }}</pre>
          </details>

          <textarea
            v-model="graphMappingYaml"
            class="flex-1 min-h-[300px] text-xs font-mono p-3 border border-gray-200 rounded-lg focus:outline-none focus:border-amber-400 resize-y"
            placeholder="在此编辑 YAML 映射配置..."
            spellcheck="false"
          ></textarea>

          <div v-if="graphMappingResult" class="mt-3 p-3 rounded-lg text-xs" :class="graphMappingResult.success ? 'bg-green-50 text-green-700 border border-green-200' : 'bg-red-50 text-red-600 border border-red-200'">
            <template v-if="graphMappingResult.success">
              导入完成: {{ graphMappingResult.nodes_created || 0 }} 个节点, {{ graphMappingResult.relationships_created || 0 }} 条关系, {{ graphMappingResult.manual_nodes || 0 }} 个手工节点, {{ graphMappingResult.manual_relationships || 0 }} 条手工关系
            </template>
            <template v-else>
              {{ graphMappingResult.error || '导入失败' }}
              <ul v-if="graphMappingResult.errors && graphMappingResult.errors.length > 0" class="mt-1 list-disc list-inside">
                <li v-for="(e, i) in graphMappingResult.errors" :key="i">{{ e }}</li>
              </ul>
            </template>
          </div>

          <div class="flex items-center gap-3 mt-3">
            <button @click="saveGraphMapping" :disabled="graphMappingLoading"
              class="px-4 py-2 text-sm rounded bg-amber-400 text-gray-900 font-medium hover:bg-amber-300 disabled:opacity-50">
              {{ graphMappingLoading ? '保存并导入中...' : '保存并导入图谱' }}
            </button>
            <button @click="closeGraphMappingEditor" class="px-4 py-2 text-sm rounded border border-gray-200 text-gray-600 hover:bg-gray-50">取消</button>
            <span v-if="graphMappingMsg && !graphMappingResult" class="text-xs" :class="graphMappingMsg.includes('失败') || graphMappingMsg.includes('错误') ? 'text-red-500' : 'text-green-600'">{{ graphMappingMsg }}</span>
          </div>
        </div>
      </div>
    </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, watch, onMounted } from 'vue'
import { useSqlQaConfirm } from '../../composables/sql_qa/useSqlQaConfirm.js'
import { listAliases, createAlias, updateAlias, deleteAlias as apiDelAlias, exportAliases, importAliases } from '../../api/sqlQaClient.js'
import { listMetrics, createMetric, updateMetric, deleteMetric as apiDelMetric, exportMetrics, importMetrics } from '../../api/sqlQaClient.js'
import { searchEntities, rebuildEntityIndex, listEntityConfigs, createEntityConfig, updateEntityConfig, deleteEntityConfig, generateKeywords, listTables, listColumns } from '../../api/sqlQaClient.js'
import { getGraphMapping, updateGraphMapping, getGraphMappingExample, getGraphStatus } from '../../api/sqlQaClient.js'
import SqlQaImportModal from './components/SqlQaImportModal.vue'
import SqlQaSelect from './components/SqlQaSelect.vue'

const { confirm } = useSqlQaConfirm()

const entityOptions = computed(() => entityConfigs.value.map(c => ({ value: c.entity_type, label: c.label })))
const tableOptions = computed(() => allTables.value.map(t => ({ value: t, label: t })))
const columnOptions = computed(() => tableColumns.value.map(c => ({ value: c.name, label: `${c.name} (${c.type})` })))

const tab = ref('aliases')
const entityTabs = [
  { key: 'aliases', label: '实体别名' },
  { key: 'metrics', label: '自定义指标' },
  { key: 'tools', label: '索引工具' },
]

// Registry (shared)
function typeLabel(t) { return entityConfigs.value.find(c => c.entity_type === t)?.label || t }

// ===== Alias Manager =====
const aliases = ref([])
const aliasForm = ref({ entity_type: '', alias: '', canonical_name: '', canonical_value: '' })
const aliasLoading = ref(false)
const editingAlias = ref(null)
const editAliasForm = ref({ entity_type: '', alias: '', canonical_name: '', canonical_value: '' })
const showAliasImport = ref(false)

async function loadAliases() {
  try { const d = await listAliases(); aliases.value = d.aliases || [] } catch (e) { console.error('[AdminEntities] 加载别名失败:', e) }
}
onMounted(loadAliases)

async function addAlias() {
  if (!aliasForm.value.alias || !aliasForm.value.canonical_name) return
  aliasLoading.value = true
  try {
    await createAlias(aliasForm.value)
    aliasForm.value = { ...aliasForm.value, alias: '', canonical_name: '', canonical_value: '' }
    loadAliases()
  } finally { aliasLoading.value = false }
}

async function delAlias(id) {
  const ok = await confirm({ message: '确认删除此别名？', danger: true })
  if (!ok) return
  await apiDelAlias(id)
  loadAliases()
}

function startEditAlias(a) {
  editingAlias.value = a
  editAliasForm.value = { entity_type: a.entity_type, alias: a.alias, canonical_name: a.canonical_name, canonical_value: a.canonical_value || '' }
}

async function submitEditAlias() {
  if (!editingAlias.value) return
  await updateAlias(editingAlias.value.id, editAliasForm.value)
  editingAlias.value = null
  loadAliases()
}

async function handleImportAliases(entries) {
  const r = await fetch('/api/admin/entities/aliases/import', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ version: 1, entity: 'entity_aliases', entries }),
  })
  if (!r.ok) {
    const text = await r.text()
    throw new Error(`服务器错误 (${r.status}): ${text.slice(0, 300)}`)
  }
  return r.json()
}

async function handleExportAliases() {
  try {
    const r = await fetch('/api/admin/entities/aliases/export')
    const blob = await r.blob()
    const a = document.createElement('a'); a.href = URL.createObjectURL(blob); a.download = 'entity-aliases-export.json'; a.click(); URL.revokeObjectURL(a.href)
  } catch (e) { console.error('[AdminEntities] 导出别名失败:', e) }
}

const metrics = ref([])
const metricForm = ref({ name: '', description: '', keywords: '' })
const metricLoading = ref(false)
const editingMetric = ref(null)
const editMetricForm = ref({ name: '', description: '', keywords: '' })
const showMetricImport = ref(false)

async function loadMetrics() {
  try { const d = await listMetrics(); metrics.value = d.metrics || [] } catch (e) { console.error('[AdminEntities] 加载指标失败:', e) }
}
onMounted(loadMetrics)

async function addMetric() {
  if (!metricForm.value.name) return
  metricLoading.value = true
  try {
    await createMetric(metricForm.value)
    metricForm.value = { name: '', description: '', keywords: '' }
    loadMetrics()
  } finally { metricLoading.value = false }
}

async function delMetric(id) {
  const ok = await confirm({ message: '确认删除此指标？', danger: true })
  if (!ok) return
  await apiDelMetric(id)
  loadMetrics()
}

function startEditMetric(m) {
  editingMetric.value = m
  editMetricForm.value = { name: m.name, description: m.description || '', keywords: m.keywords || '' }
}

async function submitEditMetric() {
  if (!editingMetric.value) return
  await updateMetric(editingMetric.value.id, editMetricForm.value)
  editingMetric.value = null
  loadMetrics()
}

async function handleImportMetrics(entries) {
  const r = await fetch('/api/admin/entities/metrics/import', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ version: 1, entity: 'custom_metrics', entries }),
  })
  if (!r.ok) {
    const text = await r.text()
    throw new Error(`服务器错误 (${r.status}): ${text.slice(0, 300)}`)
  }
  return r.json()
}

async function handleExportMetrics() {
  try {
    const r = await fetch('/api/admin/entities/metrics/export')
    const blob = await r.blob()
    const a = document.createElement('a'); a.href = URL.createObjectURL(blob); a.download = 'custom-metrics-export.json'; a.click(); URL.revokeObjectURL(a.href)
  } catch (e) { console.error('[AdminEntities] 导出指标失败:', e) }
}

const searchType = ref('production_line')
const searchKw = ref('')
const searchResults = ref([])
const searchLoading = ref(false)
const indexMsg = ref('')
const indexLoading = ref(false)

// Graph mapping
const graphMappingLoading = ref(false)
const graphMappingMsg = ref('')
const showGraphMappingEditor = ref(false)
const graphMappingYaml = ref('')
const graphMappingExample = ref('')
const graphMappingResult = ref(null)
const graphStatus = ref({ available: false, node_counts: {} })

// Entity config management
const entityConfigs = ref([])
const showAddEntity = ref(false)
const editingEntity = ref(null)
const allTables = ref([])
const tableColumns = ref([])
const kwLoading = ref(false)
const saving = ref(false)
const newKeyword = ref('')
const entityForm = ref({ entity_type: '', label: '', table_name: '', search_columns: [], label_column: 'name', value_column: 'id', context_columns: [], keyword_hints: [], filter_condition: 'del_flag = 0' })

async function loadEntityConfigs() {
  try {
    const d = await listEntityConfigs()
    entityConfigs.value = d.configs || []
    if (entityConfigs.value.length > 0) {
      const firstType = entityConfigs.value[0].entity_type
      searchType.value = firstType
      if (!entityConfigs.value.find(c => c.entity_type === aliasForm.value.entity_type)) {
        aliasForm.value.entity_type = firstType
      }
    }
  } catch (e) { console.error('[AdminEntities] 加载实体配置失败:', e) }
}
async function loadTables() {
  try { const d = await listTables(); allTables.value = d.tables || [] } catch (e) { console.error('[AdminEntities] 加载表列表失败:', e) }
}
watch(() => entityForm.value.table_name, () => onTableChange())

async function onTableChange() {
  if (!entityForm.value.table_name) { tableColumns.value = []; return }
  try { const d = await listColumns(entityForm.value.table_name); tableColumns.value = d.columns || [] } catch { tableColumns.value = [] }
}
function toggleSearchCol(name) {
  const arr = entityForm.value.search_columns
  entityForm.value.search_columns = arr.includes(name) ? arr.filter(c => c !== name) : [...arr, name]
}
function toggleContextCol(name) {
  const arr = entityForm.value.context_columns
  entityForm.value.context_columns = arr.includes(name) ? arr.filter(c => c !== name) : [...arr, name]
}
function addKeyword() {
  const kw = newKeyword.value.trim()
  if (kw && !entityForm.value.keyword_hints.includes(kw)) { entityForm.value.keyword_hints.push(kw); newKeyword.value = '' }
}
async function onGenerateKeywords() {
  if (!entityForm.value.label) return
  kwLoading.value = true
  try {
    const d = await generateKeywords({ label: entityForm.value.label, table_name: entityForm.value.table_name, columns: tableColumns.value.map(c => c.name) })
    if (d.keywords?.length) {
      entityForm.value.keyword_hints = [...new Set([...entityForm.value.keyword_hints, ...d.keywords])]
    } else {
      alert('关键词生成失败：' + (d.error || '返回为空，请手动输入关键词'))
    }
  } catch (e) {
    alert('关键词生成请求失败：' + (e.message || '网络错误'))
  } finally { kwLoading.value = false }
}
function startEditEntity(c) {
  editingEntity.value = c
  entityForm.value = { ...c, search_columns: c.search_columns || [], context_columns: c.context_columns || [], keyword_hints: c.keyword_hints || [] }
  if (c.table_name) onTableChange()
}
function closeEntityModal() { showAddEntity.value = false; editingEntity.value = null; entityForm.value = { entity_type: '', label: '', table_name: '', search_columns: [], label_column: 'name', value_column: 'id', context_columns: [], keyword_hints: [], filter_condition: 'del_flag = 0' }; tableColumns.value = [] }
async function saveEntity() {
  if (!entityForm.value.label || !entityForm.value.table_name || !entityForm.value.entity_type) return
  saving.value = true
  try {
    if (editingEntity.value) {
      await updateEntityConfig(editingEntity.value.id, entityForm.value)
    } else {
      await createEntityConfig(entityForm.value)
    }
    closeEntityModal()
    await loadEntityConfigs()
  } catch (e) { alert('保存失败: ' + (e.message || '未知错误')) } finally { saving.value = false }
}
async function delEntityConfig(id) {
  const ok = await confirm({ message: '确认删除此实体配置？不影响已索引的数据。', danger: true })
  if (!ok) return
  try { await deleteEntityConfig(id); await loadEntityConfigs() } catch (e) { console.error('[AdminEntities] 删除实体配置失败:', e) }
}
async function doSearch() {
  if (!searchKw.value) return
  searchLoading.value = true
  try {
    const d = await searchEntities({ entity_type: searchType.value, keyword: searchKw.value, limit: 10 })
    searchResults.value = d.results || []
  } catch (e) { console.error('[AdminEntities] 搜索失败:', e) } finally { searchLoading.value = false }
}
async function doRebuild() {
  indexLoading.value = true; indexMsg.value = '正在重建索引...'
  try {
    const d = await rebuildEntityIndex()
    indexMsg.value = d.message || '完成'
    await loadEntityConfigs()
  } catch { indexMsg.value = '重建失败' } finally { indexLoading.value = false }
}

async function loadGraphStatus() {
  try {
    const d = await getGraphStatus()
    graphStatus.value = d.status || { available: false }
  } catch (e) { console.error('[AdminEntities] 加载图谱状态失败:', e) }
}

async function openGraphMappingEditor() {
  graphMappingResult.value = null
  graphMappingMsg.value = ''
  try {
    const [current, example] = await Promise.all([
      getGraphMapping(),
      getGraphMappingExample(),
    ])
    graphMappingYaml.value = current.yaml || ''
    graphMappingExample.value = example.yaml || ''
  } catch (e) {
    graphMappingMsg.value = '加载配置失败: ' + (e.message || '网络错误')
  }
  showGraphMappingEditor.value = true
}

async function saveGraphMapping() {
  if (!graphMappingYaml.value.trim()) {
    graphMappingMsg.value = 'YAML 内容不能为空'
    return
  }
  graphMappingLoading.value = true
  graphMappingMsg.value = ''
  graphMappingResult.value = null
  try {
    const d = await updateGraphMapping(graphMappingYaml.value)
    if (d.success) {
      graphMappingResult.value = d
      graphMappingMsg.value = `导入成功: ${d.nodes_created || 0} 节点, ${d.relationships_created || 0} 关系, ${d.manual_nodes || 0} 手工节点`
    } else {
      graphMappingResult.value = d
      graphMappingMsg.value = d.error || '导入失败'
      if (d.errors && d.errors.length > 0) {
        graphMappingMsg.value += '\n' + d.errors.join('\n')
      }
    }
    loadGraphStatus()
  } catch (e) {
    graphMappingMsg.value = '保存失败: ' + (e.message || '网络错误')
  } finally {
    graphMappingLoading.value = false
  }
}

function closeGraphMappingEditor() {
  showGraphMappingEditor.value = false
  graphMappingResult.value = null
}

onMounted(() => { loadEntityConfigs(); loadTables(); loadGraphStatus() })
</script>
