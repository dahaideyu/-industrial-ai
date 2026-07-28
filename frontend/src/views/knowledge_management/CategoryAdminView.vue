<template>
  <div class="h-full overflow-y-auto bg-slate-50">
    <div class="p-6 max-w-[96vw] mx-auto">

      <!-- Breadcrumb -->
      <div class="breadcrumb">
        <span class="node" @click="router.push('/knowledge-management')">🏭 知识库管理</span>
        <span class="sep">›</span>
        <span class="node current">📋 文档类别配置</span>
        <span class="ml-auto text-[10px] text-slate-400">管理员功能 · 修改后需手动同步到知识库</span>
      </div>

      <!-- Header -->
      <div class="flex items-center justify-between mb-3.5">
        <div class="flex items-center gap-2.5">
          <div class="text-sm font-semibold">全局文档类别体系 · {{ leafCount }}个叶子节点</div>
        </div>
        <div class="flex gap-1.5">
          <button class="tag cursor-pointer px-4 py-1.5 text-xs font-semibold" style="background:#fef2f2;color:#dc2626" @click="onReseed(true)" :disabled="syncing" title="清空预设表后重新创建，用于修复数据污染">
            🗑️ 清空重建
          </button>
          <button class="tag amber cursor-pointer px-4 py-1.5 text-xs font-semibold" @click="onReseed(false)" :disabled="syncing">
            🔄 重新加载预设
          </button>
          <button class="tag amber cursor-pointer px-4 py-1.5 text-xs font-semibold" @click="onSync" :disabled="syncing">
            {{ syncing ? '⏳ 同步中...' : '📤 同步到所有知识库' }}
          </button>
        </div>
      </div>

      <!-- Split -->
      <div class="split-layout min-h-[460px]">
        <!-- Left: Tree -->
        <div class="tree-panel" style="width:320px">
          <div class="tree-title">类别树（共{{ leafCount }}个叶子节点）</div>

          <div v-for="group in treeGroups" :key="group.type">
            <!-- 顶级：三大体系分组标题 -->
            <div class="tree-item font-semibold bg-slate-50 cursor-default"
                 style="border-radius:5px;margin-bottom:4px">
              {{ group.label }}
              <span class="ml-auto text-[10px] text-slate-400">{{ group.leafCount }}项</span>
            </div>
            <!--
              树结构：level 0 (group.items) → level 1 (children) → level 2 (叶子)
              group.items[0] = "设备说明文档" (level 0), 它的 children = 二级分类(图纸类/手册类...)
              遍历所有 level 0 的 children (即 level 1 二级分类)
            -->
            <template v-for="root in group.items" :key="'r-'+root.id">
              <template v-for="subcat in (root.children || [])" :key="subcat.id">
                <!-- 二级分类：展开/折叠 -->
                <div class="tree-item l2" style="display:flex;align-items:center"
                     @click="toggleSubcatExpand(subcat.id)">
                  <span class="expand-icon">{{ expandedSubcats[subcat.id] ? '▾' : '▸' }}</span>
                  <span class="flex-1">📂 {{ subcat.name }}</span>
                  <span class="text-[10px] text-slate-400">{{ (subcat.children || []).length }}项</span>
                  <button class="add-child-btn" @click.stop="onCreate(subcat.id, subcat.category_type)" title="添加子文档类别">+</button>
                </div>
                <!-- 三级叶子分类 -->
                <template v-if="expandedSubcats[subcat.id]">
                  <div v-for="leaf in (subcat.children || [])" :key="leaf.id"
                       class="tree-item l3 cursor-pointer"
                       :class="{ active: selectedId === leaf.id }"
                       @click="selectCat(leaf.id)">
                    <span class="dot green" />
                    <span class="flex-1">{{ leaf.name }}</span>
                  </div>
                </template>
              </template>
            </template>
          </div>
        </div>

        <!-- Right: Detail -->
        <div class="flex-1 bg-white rounded-xl border border-slate-200 p-6 ml-4">
          <template v-if="selectedCat">
            <div class="text-[10px] text-slate-400 uppercase mb-2 tracking-wider">选中类别详情</div>
            <div class="text-lg font-bold mb-3 text-slate-800">{{ selectedCat.name }}</div>
            <div class="flex gap-2 mb-4 flex-wrap">
              <span class="tag amber">{{ selectedCat.category_type === 'device_doc' ? '📐 设备说明文档' : selectedCat.category_type === 'sop_doc' ? '📋 设备SOP文档' : '🛡️ 合规性文档' }}</span>
              <span class="tag green" v-if="selectedCat.is_leaf">叶子节点（生成 PlanItem）</span>
              <span class="tag gray" v-else>分类节点</span>
              <span class="tag green" v-if="selectedCat.is_active !== false">启用</span>
              <span class="tag red" v-else>已停用</span>
            </div>

            <div class="mb-4">
              <div class="text-[11px] text-slate-500 font-semibold mb-1.5">收集要求（requirement_desc）</div>
              <div class="bg-slate-50 border border-slate-200 rounded-md p-3 text-xs text-slate-700 leading-relaxed">
                {{ selectedCat.requirement_desc || '暂无描述' }}
              </div>
            </div>

            <div class="mb-4">
              <div class="text-[11px] text-slate-500 font-semibold mb-1.5">类别属性</div>
              <div class="grid grid-cols-2 gap-3 text-xs">
                <div><span class="text-slate-400">所属体系：</span>{{ selectedCat.category_type }}</div>
                <div><span class="text-slate-400">层级：</span>{{ selectedCat.level !== undefined ? (selectedCat.level === 0 ? '一级' : selectedCat.level === 1 ? '二级' : '三级（叶子节点）') : '—' }}</div>
                <div><span class="text-slate-400">排序：</span>{{ selectedCat.sort_order || 0 }}</div>
                <div><span class="text-slate-400">版本：</span>V{{ selectedCat.version || 1 }}</div>
                <div><span class="text-slate-400">父类别：</span>{{ selectedCat.parent_name || '无（顶级）' }}</div>
                <div><span class="text-slate-400">状态：</span><span :style="{color: selectedCat.is_active !== false ? '#16a34a' : '#ef4444'}">{{ selectedCat.is_active !== false ? '启用中' : '已停用' }}</span></div>
              </div>
            </div>

            <div class="flex gap-2 pt-3 border-t border-slate-200">
              <button class="tag blue cursor-pointer px-4 py-1.5 text-xs" @click="onEdit(selectedCat)">✏️ 编辑</button>
              <button class="tag cursor-pointer px-4 py-1.5 text-xs" style="background:#fef2f2;color:#ef4444" @click="onDisable(selectedCat)">🗑️ 停用</button>
            </div>
          </template>
          <div v-else class="text-center py-16 text-slate-400">
            请从左侧选择一个类别查看详情
          </div>
        </div>
      </div>

      <!-- Tip -->
      <div class="tip mt-3">
        <strong>⚙️ 使用说明：</strong> 左侧树按体系分组。叶子节点生成 PlanItem。修改后点击「🔄 同步到所有知识库」增量更新。
      </div>
    </div>

    <!-- New/Edit Modal -->
    <div v-if="showForm" class="modal-bg" @click.self="showForm = false">
      <div class="modal-box">
        <h3 class="text-base font-semibold mb-4">
          {{ editingCat ? '编辑类别' : '新建子类别' }}
        </h3>
        <div class="mb-3">
          <label class="block text-xs text-slate-500 mb-1">类别名称</label>
          <input v-model="formName" class="w-full border border-slate-200 rounded-lg px-3 py-2 text-sm" placeholder="类别名称" />
        </div>
        <!-- 编辑时可修改父类别 -->
        <div v-if="editingCat" class="mb-3">
          <label class="block text-xs text-slate-500 mb-1">父类别</label>
          <select v-model="formParentId" class="w-full border border-slate-200 rounded-lg px-3 py-2 text-sm">
            <option v-for="c in parentOptions" :key="c.id" :value="c.id">{{ c.name }}</option>
          </select>
        </div>
        <!-- 仅叶子项或编辑时显示收集要求 -->
        <div v-if="isLeafForm || editingCat" class="mb-3">
          <label class="block text-xs text-slate-500 mb-1">收集要求</label>
          <textarea v-model="formDesc" class="w-full border border-slate-200 rounded-lg px-3 py-2 text-sm" rows="3" placeholder="描述该类别需要收集的文档要求..."></textarea>
        </div>
        <div class="flex justify-end gap-2">
          <button class="px-4 py-2 text-sm text-slate-500 border border-slate-200 rounded-lg" @click="showForm = false">取消</button>
          <button class="px-4 py-2 text-sm bg-amber-600 text-white rounded-lg disabled:opacity-50" @click="onSave" :disabled="!formName.trim()">
            {{ editingCat ? '保存修改' : '创建' }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { getPresetCategories, createPresetCategory, updatePresetCategory, deletePresetCategory, syncPresetCategories } from '../../api/knowledgeManagementClient.js'
import client from '../../api/knowledgeManagementClient.js'
import { useToast } from '../../composables/useToast'
import { showConfirm } from '../../composables/useConfirm'

const router = useRouter()
const categories = ref([])
const selectedId = ref(null)
const loading = ref(true)
const syncing = ref(false)
const expandedGroups = ref({ device_doc: true, sop_doc: true, compliance: true })
const expandedSubcats = ref({})  // 二级分类展开/折叠状态
const toast = useToast()

function toggleSubcatExpand(id) {
  expandedSubcats.value[id] = !expandedSubcats.value[id]
}

// Modal
const showForm = ref(false)
const editingCat = ref(null)
const formName = ref('')
const formDesc = ref('')
const formType = ref('device_doc')
const formParentId = ref('')

const groupConfig = {
  device_doc: { label: '📐 设备说明文档' },
  sop_doc: { label: '📋 设备SOP文档' },
  compliance: { label: '🛡️ 合规性文档' },
}

function countLeaves(cat) {
  if (!cat.children || cat.children.length === 0) return cat.is_leaf ? 1 : 0
  return cat.children.reduce((s, c) => s + countLeaves(c), 0)
}

const treeGroups = computed(() => {
  const groups = {}
  // Build tree from flat list
  const byParent = {}
  for (const cat of categories.value) {
    const key = cat.parent_id || 'root'
    if (!byParent[key]) byParent[key] = []
    byParent[key].push(cat)
  }
  function buildTree(parentId, depth = 0) {
    const children = byParent[parentId] || []
    return children.map(c => ({
      ...c,
      depth,
      children: buildTree(c.id, depth + 1),
    }))
  }
  const roots = byParent['root'] || []
  for (const cat of roots) {
    const type = cat.category_type
    if (!type) continue
    if (!groups[type]) groups[type] = { type, label: groupConfig[type]?.label || type, items: [], leafCount: 0 }
    const node = { ...cat, depth: 0, children: buildTree(cat.id, 1) }
    groups[type].items.push(node)
    groups[type].leafCount += countLeaves(node)
  }
  return Object.values(groups)
})

const selectedCat = computed(() => {
  if (!selectedId.value) return null
  for (const group of treeGroups.value) {
    for (const root of group.items) {
      if (root.id === selectedId.value) return root
      for (const subcat of (root.children || [])) {
        if (subcat.id === selectedId.value) return subcat
        for (const leaf of (subcat.children || [])) {
          if (leaf.id === selectedId.value) return leaf
        }
      }
    }
  }
  return null
})

const leafCount = computed(() => categories.value.filter(c => c.is_leaf && c.is_active !== false).length)

const parentOptions = computed(() => {
  const type = editingCat.value ? editingCat.value.category_type : formType.value
  return categories.value.filter(c => c.category_type === type && !c.is_leaf && c.is_active !== false)
})

// 父类别为 level 0（三大体系下的分类）→ 新建的是叶子项；父类别为 level 1 → 叶子项
const isLeafForm = computed(() => {
  if (!formParentId.value) return true  // 有父类别时默认显示收集要求
  const parent = categories.value.find(c => c.id === formParentId.value)
  return parent ? (parent.level || 0) >= 0 : true
})

function toggleGroup(type) { expandedGroups.value[type] = !expandedGroups.value[type] }
function selectCat(id) { selectedId.value = id }

function onCreate(parentId, categoryType) {
  editingCat.value = null
  formName.value = ''
  formDesc.value = ''
  formType.value = categoryType || 'device_doc'
  formParentId.value = parentId || ''
  showForm.value = true
}

function onEdit(cat) {
  editingCat.value = cat
  formName.value = cat.name
  formDesc.value = cat.requirement_desc || ''
  formType.value = cat.category_type
  formParentId.value = cat.parent_id || ''
  showForm.value = true
}

async function onSave() {
  if (!formName.value.trim()) return
  try {
    const data = {
      name: formName.value.trim(),
      requirement_desc: formDesc.value.trim(),
      category_type: formType.value,
      parent_id: formParentId.value || null,
    }
    if (editingCat.value) {
      // 编辑模式：保留原有的 level 和 is_leaf，不重算
      data.level = editingCat.value.level
      data.is_leaf = editingCat.value.is_leaf
      await updatePresetCategory(editingCat.value.id, data)
    } else {
      // 新建模式：根据父类别自动计算
      let level = 0
      let isLeaf = false
      if (formParentId.value) {
        const parent = categories.value.find(c => c.id === formParentId.value)
        if (parent) {
          level = (parent.level || 0) + 1
          isLeaf = level >= 2
        }
      }
      data.level = level
      data.is_leaf = isLeaf
      await createPresetCategory(data)
    }
    showForm.value = false
    await loadCategories()
  } catch (e) { toast.error('保存失败: ' + e.message) }
}

async function onDisable(cat) {
  if (!await showConfirm(`确定停用「${cat.name}」？此操作不可逆。`, '停用预设', { type: 'danger', confirmText: '停用' })) return
  try {
    await deletePresetCategory(cat.id)
    selectedId.value = null
    await loadCategories()
    toast.success(`已停用「${cat.name}」`)
  } catch (e) { toast.error('停用失败: ' + e.message) }
}

async function onReseed(force = false) {
  if (!await showConfirm(
    force ? '将清空预设类别表并重新创建（包括修复重复数据）。确认继续？' : '将重新写入全部70个预设文档类别。确认继续？',
    '重新加载预设',
    { type: force ? 'warning' : 'primary', confirmText: force ? '清空重建' : '重新加载' }
  )) return
  syncing.value = true
  try {
    const res = await client.post('/admin/preset-categories/reseed', null, { params: { force } })
    toast.success(`预设类别加载完成：新增${res.seed?.inserted || 0}，更新${res.seed?.updated || 0}`)
    await loadCategories()
  } catch (e) { toast.error('操作失败: ' + e.message) }
  finally { syncing.value = false }
}

async function onSync() {
  if (!await showConfirm('将把新增或修改的预设类别同步到所有活跃知识库。确认继续？', '同步到所有知识库', { type: 'primary' })) return
  syncing.value = true
  try {
    await syncPresetCategories()
    toast.success('同步完成')
  } catch (e) { toast.error('同步失败: ' + e.message) }
  finally { syncing.value = false }
}

async function loadCategories() {
  loading.value = true
  try {
    const data = await getPresetCategories()
    categories.value = Array.isArray(data) ? data : (data?.categories || data?.items || [])
  } catch (e) { console.error('Categories load error:', e) }
  finally { loading.value = false }
}

onMounted(loadCategories)
</script>

<style scoped>
.breadcrumb{display:flex;align-items:center;gap:6px;padding:10px 14px;background:#fff;border-radius:10px;border:1px solid #e2e8f0;margin-bottom:14px;font-size:13px;flex-wrap:wrap}
.breadcrumb .sep{color:#cbd5e1}
.breadcrumb .node{color:#64748b;padding:3px 10px;cursor:pointer;border-radius:4px;font-size:12px}
.breadcrumb .node:hover{background:#f1f5f9}
.breadcrumb .node.current{background:#fef3c7;color:#b45309;font-weight:600;border-radius:16px;padding:4px 12px}
.split-layout{display:flex;gap:12px}
.tree-panel{flex-shrink:0;background:#fff;border-radius:10px;padding:14px;border:1px solid #e2e8f0;font-size:12px;overflow-y:auto}
.tree-title{font-size:10px;color:#94a3b8;margin-bottom:10px;text-transform:uppercase;letter-spacing:.5px;font-weight:600}
.tree-item{padding:6px 10px;border-radius:5px;cursor:pointer;margin-bottom:1px;color:#64748b;font-size:12px;display:flex;align-items:center;gap:6px;transition:all .1s}
.tree-item:hover{background:#f8fafc}
.tree-item.active{background:#fef3c7;color:#b45309;font-weight:600}
.tree-item.l2{padding-left:28px;font-size:11px}
.tree-item.l3{padding-left:44px;font-size:11px;color:#94a3b8}
.tree-divider{border-top:1px solid #e2e8f0;margin:10px 0}
.tag{font-size:10px;padding:2px 7px;border-radius:4px;font-weight:500;margin-right:4px;display:inline-block}
.tag.blue{background:#dbeafe;color:#2563eb}.tag.amber{background:#fef3c7;color:#b45309}
.tag.green{background:#dcfce7;color:#16a34a}.tag.red{background:#fef2f2;color:#ef4444}.tag.gray{background:#f1f5f9;color:#94a3b8}
.tip{background:#eff6ff;border:1px solid #bfdbfe;border-radius:8px;padding:10px 14px;font-size:12px;color:#1e40af;margin-top:12px;line-height:1.6}
.modal-bg{position:fixed;inset:0;background:rgba(0,0,0,.4);display:flex;align-items:center;justify-content:center;z-index:99;backdrop-filter:blur(2px)}
.modal-box{background:#fff;border-radius:12px;padding:24px;width:480px;max-width:90vw;box-shadow:0 20px 40px rgba(0,0,0,.15)}
.dot{width:6px;height:6px;border-radius:50%;flex-shrink:0}
.dot.green{background:#22c55e}
.add-child-btn{opacity:0;width:18px;height:18px;border-radius:4px;border:1px solid #e2e8f0;background:#fff;color:#94a3b8;font-size:14px;line-height:1;cursor:pointer;display:flex;align-items:center;justify-content:center;flex-shrink:0;margin-left:4px;transition:all .1s}
.tree-item:hover .add-child-btn{opacity:1}
.add-child-btn:hover{background:#eff6ff;border-color:#3b82f6;color:#3b82f6}
</style>
