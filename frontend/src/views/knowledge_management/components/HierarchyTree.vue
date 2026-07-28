<template>
  <div class="tree-panel">
    <div class="tree-title">层级结构</div>
    <!-- 基地 -->
    <div class="tree-item" :class="{ active: activeNode === 'base' }" @click="$emit('nav', 'base')">
      🏭 {{ baseName }} <span v-if="baseProgress!==null" class="ml-auto text-[10px] text-slate-400">{{ baseProgress }}%</span>
    </div>

    <!-- 车间 + 设备类型（可展开折叠） -->
    <template v-if="showWorkshops">
      <div v-for="ws in workshops" :key="ws.name">
        <div class="tree-item l2"
             :class="{ active: activeNode === 'workshop-'+ws.name }">
          <span class="expand-icon cursor-pointer" @click.stop="$emit('toggle-workshop', ws.name)">{{ isWorkshopExpanded(ws.name) ? '▾' : '▸' }}</span>
          <span class="flex-1 cursor-pointer" @click="$emit('nav','workshop',ws.name)">📁 {{ ws.name }}</span>
          <span class="text-[10px] text-slate-400">{{ ws.deviceCount }}台</span>
        </div>
        <!-- 设备类型子节点 -->
        <template v-if="isWorkshopExpanded(ws.name)">
          <div v-for="dt in (ws.deviceTypes || [])" :key="dt.kb_id || dt.name">
            <div class="tree-item l3"
                 :class="{ active: activeNode === 'device-'+dt.name }">
              <span class="expand-icon cursor-pointer" @click.stop="$emit('toggle-device', dt.kb_id)">{{ isDeviceExpanded(dt.kb_id) ? '▾' : '▸' }}</span>
              <span class="flex-1 cursor-pointer" @click="$emit('nav','device',{name:dt.name,workshop:ws.name,kbId:dt.kb_id})">
                <span class="dot" :class="dt.progress>=80?'green':dt.progress>=50?'amber':'red'" />
                {{ dt.name }}
              </span>
              <span class="ml-auto text-[10px]" :style="{color:dt.progress>=80?'#16a34a':dt.progress>=50?'#f59e0b':'#ef4444'}">{{ dt.progress }}%</span>
            </div>
            <!-- 设备下的文档列表 -->
            <template v-if="isDeviceExpanded(dt.kb_id)">
              <div v-if="deviceDocsLoading[dt.kb_id]" class="tree-item l4 loading">加载中...</div>
              <div v-else-if="getDeviceDocs(dt.kb_id).length === 0" class="tree-item l4 empty">暂无文档</div>
              <div v-else>
                <div v-for="doc in getDeviceDocs(dt.kb_id)" :key="doc.id"
                     class="tree-item l4 doc-item"
                     @click="$emit('nav','document', doc)">
                  <span class="doc-icon">{{ docIcon(doc.file_type) }}</span>
                  <span class="doc-name" :title="doc.name">{{ doc.name }}</span>
                  <span v-if="doc.status === 'approved'" class="doc-status approved">✓</span>
                  <span v-else-if="doc.status === 'rejected'" class="doc-status rejected">✗</span>
                </div>
              </div>
            </template>
          </div>
        </template>
      </div>
      <div class="tree-divider" />
    </template>

    <!-- 知识库类型 -->
    <div style="font-size:10px;color:#94a3b8;margin-bottom:4px">知识库类型</div>
    <div class="tree-item" :class="{ active: activeNode==='kb-compliance' }" @click="$emit('nav','compliance')" style="color:#3b82f6">🛡️ 合规性知识库</div>
    <div class="tree-item" :class="{ active: activeNode==='kb-device-doc' }" @click="$emit('nav','kb-type','device_doc')">📐 设备说明知识库</div>
    <div class="tree-item" :class="{ active: activeNode==='kb-sop-doc' }" @click="$emit('nav','kb-type','sop_doc')">📋 设备SOP知识库</div>
    <div class="tree-item" style="cursor:default;color:#94a3b8">📚 历史沉淀知识库</div>

    <!-- 自定义知识库 -->
    <div class="tree-divider" />
    <div style="font-size:10px;color:#94a3b8;margin-bottom:4px">自定义知识库</div>
    <div v-for="kb in customKbs" :key="kb.id" class="tree-item text-xs" style="color:#0ea5e9" @click="$emit('nav','custom-kb',kb.id)">📋 {{ kb.name }}</div>
  </div>
</template>

<script setup>
const props = defineProps({
  baseName: { type: String, default: '江西基地' },
  baseProgress: { type: Number, default: null },
  workshops: { type: Array, default: () => [] },
  showWorkshops: { type: Boolean, default: true },
  customKbs: { type: Array, default: () => [] },
  activeNode: { type: String, default: 'base' },
  expanded: { type: Object, default: () => ({}) },
  expandedDevices: { type: Object, default: () => ({}) },
  deviceDocuments: { type: Object, default: () => ({}) },
  deviceDocsLoading: { type: Object, default: () => ({}) },
})

defineEmits(['nav', 'toggle-workshop', 'toggle-device'])

/** 车间是否展开 */
function isWorkshopExpanded(wsName) {
  return !!(props.expanded && props.expanded[wsName])
}

/** 设备是否展开 */
function isDeviceExpanded(kbId) {
  return !!(props.expandedDevices && props.expandedDevices[kbId])
}

/** 获取设备下的文档列表 */
function getDeviceDocs(kbId) {
  return props.deviceDocuments[kbId] || []
}

/** 根据文件类型返回图标 */
function docIcon(fileType) {
  if (fileType === 'table') return '📊'
  if (fileType === 'image') return '🖼️'
  return '📄'
}
</script>

<style scoped>
.tree-panel{width:240px;flex-shrink:0;background:#fff;border-radius:10px;padding:14px;border:1px solid #e2e8f0;font-size:12px;overflow-y:auto;max-height:calc(100vh - 180px)}
.tree-title{font-size:10px;color:#94a3b8;margin-bottom:10px;text-transform:uppercase;letter-spacing:.5px;font-weight:600}
.tree-item{padding:5px 10px;border-radius:5px;cursor:pointer;margin-bottom:1px;color:#64748b;font-size:12px;display:flex;align-items:center;gap:5px;transition:all .1s}
.tree-item:hover{background:#f8fafc}
.tree-item.active{background:#fef3c7;color:#b45309;font-weight:600;border-left:3px solid #b45309;margin-left:-3px;padding-left:13px}
.tree-item.l2{padding-left:22px;font-size:11px}
.tree-item.l3{padding-left:38px;font-size:11px;color:#94a3b8}
.tree-item.l4{padding-left:52px;font-size:10px;color:#94a3b8}
.tree-item.l4.loading{color:#cbd5e1;cursor:default}
.tree-item.l4.empty{color:#cbd5e1;cursor:default;font-style:italic}
.tree-item.l4.doc-item:hover{background:#f0f9ff}
.tree-divider{border-top:1px solid #e2e8f0;margin:8px 0;padding-top:8px}
.expand-icon{font-size:10px;width:12px;text-align:center;flex-shrink:0;user-select:none}
.dot{width:6px;height:6px;border-radius:50%;flex-shrink:0}
.dot.green{background:#22c55e}.dot.amber{background:#f59e0b}.dot.red{background:#ef4444}.dot.gray{background:#cbd5e1}
.doc-icon{flex-shrink:0;font-size:10px}
.doc-name{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.doc-status{flex-shrink:0;font-size:9px;font-weight:bold}
.doc-status.approved{color:#16a34a}
.doc-status.rejected{color:#ef4444}
</style>
