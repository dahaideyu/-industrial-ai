<template>
  <div :class="['flex gap-3 mb-6', msg.role === 'user' ? 'justify-end' : '']">
    <!-- Assistant avatar -->
    <div v-if="msg.role === 'assistant'" class="flex-shrink-0 w-8 h-8 rounded-full bg-amber-100 flex items-center justify-center text-amber-600 text-xs font-bold mt-1">AI</div>

    <div :class="[msg.role === 'user' ? 'max-w-[80%]' : 'w-full max-w-[85%] space-y-3']">
      <!-- User message -->
      <div v-if="msg.role === 'user'" class="bg-amber-400 text-gray-900 rounded-2xl rounded-br-md px-4 py-2.5">
        <p class="text-sm whitespace-pre-wrap">{{ msg.content }}</p>
      </div>

      <!-- Assistant message: independent blocks -->
      <template v-else>
        <!-- Agentic Thinking (streaming 思考过程) -->
        <AgenticThinking
          v-if="msg.source === 'agentic_qa' && (msg.thinking || msg.isThinking)"
          :thinking="msg.thinking || ''"
          :is-thinking="msg.isThinking || false"
          :collapsed="hasAnswer"
        />

        <!-- Agentic Steps (增强版步骤时间线) -->
        <AgenticSteps
          v-if="msg.source === 'agentic_qa' && msg.steps && msg.steps.length > 0 && msg.steps.some(s => s.tool || s.id)"
          :steps="msg.steps"
          :collapsed="hasAnswer"
        />

        <!-- Execution Steps (旧版 agentic 步骤，非 agentic_qa 源时显示) -->
        <SqlQaExecutionSteps
          v-if="msg.steps && msg.steps.length > 0 && msg.steps[0].id && msg.source !== 'agentic_qa'"
          :steps="msg.steps"
        />

        <!-- 1. Step progress (collapsible bar, 非 agentic 模式) -->
        <SqlQaStepProgress
          v-if="msg.steps && msg.steps.length > 0 && !msg.steps[0].id && msg.source !== 'agentic_qa'"
          :steps="msg.steps"
          :msg-id="msg.id"
          :source="msg.source"
          :has-answer="hasAnswer"
        />

        <!-- 2. Answer content (independent block) -->
        <div
          v-if="msg.content && msg.content !== '正在处理...' && !isCountResult(msg.results?.[0]) && !(msg.clarification_options && msg.clarification_options.length > 0) && !(msg.clarification_groups && msg.clarification_groups.length > 0)"
          class="bg-white rounded-lg border border-gray-100 px-3 py-2.5"
        >
          <div class="text-sm text-gray-700 leading-relaxed" v-html="renderedContent"></div>
        </div>

        <!-- 3. Intent clarification groups (new multi-select UI) -->
        <div v-if="msg.clarification_groups && msg.clarification_groups.length > 0" class="bg-white rounded-xl shadow-sm border border-blue-200 p-4">
          <p class="text-sm font-medium mb-3" :class="clarifyResolved ? 'text-green-700' : 'text-gray-700'">{{ msg.content || '请明确以下信息：' }}</p>
          <div v-for="(group, gi) in msg.clarification_groups" :key="gi" class="mb-3">
            <p class="text-xs text-gray-500 mb-1.5">{{ group.label }}<span v-if="group.multi && !group.resolved" class="text-blue-400 ml-1">(可多选)</span></p>
            <div class="flex flex-wrap gap-1.5 mb-1.5">
              <button
                v-for="opt in group.options"
                :key="opt"
                type="button"
                :disabled="group.resolved"
                @click="toggleClarifyOption(gi, opt, group.multi)"
                class="flex items-center gap-1 text-xs px-2.5 py-1.5 rounded border transition-colors"
                :class="group.resolved
                  ? (isClarifySelectedResolved(gi, opt, group) ? 'border-green-300 bg-green-50 text-green-700 cursor-default' : 'border-gray-100 bg-gray-50 text-gray-300 cursor-default')
                  : (isClarifySelected(gi, opt) ? 'border-blue-400 bg-blue-50 text-blue-700' : 'border-gray-200 bg-white text-gray-600 hover:border-blue-200')"
              >
                <svg v-if="isClarifySelectedResolved(gi, opt, group) || isClarifySelected(gi, opt)" class="w-3 h-3 flex-shrink-0" :class="group.resolved ? 'text-green-500' : 'text-blue-500'" fill="currentColor" viewBox="0 0 20 20">
                  <path fill-rule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clip-rule="evenodd" />
                </svg>
                {{ opt }}
              </button>
            </div>
            <template v-if="!group.resolved">
              <button
                v-if="group.allow_select_all && group.options && group.options.length > 1"
                @click="toggleSelectAll(gi, group)"
                type="button"
                class="text-xs px-2 py-1 rounded border transition-colors border-gray-200 bg-white text-gray-500 hover:bg-gray-50"
              >
                {{ isAllSelected(gi, group) ? '取消全选' : '全选' }}
              </button>
              <div class="flex gap-1.5">
                <input v-model="clarifyCustoms[gi]" @keydown.enter="addClarifyCustom(gi, group.field)" type="text" :placeholder="group.placeholder || '或输入其他...'" class="flex-1 text-xs px-2.5 py-1.5 border border-gray-200 rounded focus:outline-none focus:border-amber-400" />
                <button @click="addClarifyCustom(gi, group.field)" class="text-xs px-2 py-1.5 rounded bg-gray-100 text-gray-500 hover:bg-gray-200">添加</button>
              </div>
            </template>
          </div>
          <button
            v-if="!clarifyResolved"
            @click="onClarifyConfirm"
            :disabled="clarifyLoading"
            class="mt-2 px-4 py-1.5 text-xs rounded font-medium transition-colors flex items-center gap-1.5"
            :class="clarifyLoading ? 'bg-gray-200 text-gray-400 cursor-not-allowed' : 'bg-amber-400 text-gray-900 hover:bg-amber-300'"
          >
            <svg v-if="clarifyLoading" class="w-3 h-3 animate-spin" fill="none" viewBox="0 0 24 24">
              <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"/>
              <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"/>
            </svg>
            {{ clarifyLoading ? '生成中...' : '确认查询' }}
          </button>
          <p v-else class="mt-2 text-xs text-green-600">已确认</p>
        </div>

        <!-- 4. Entity candidates (clarification or resolved) -->
        <div v-if="msg.entity_candidates && msg.entity_candidates.length > 0" class="bg-white rounded-xl shadow-sm border border-amber-200 p-4">
          <p class="text-sm font-medium mb-3" :class="isEntityResolved ? 'text-green-700' : 'text-amber-800'">
            {{ isEntityResolved ? '已确认的实体信息：' : '请确认以下实体信息：' }}
          </p>
          <div v-for="(ec, i) in msg.entity_candidates" :key="i" class="mb-3">
            <p class="text-xs text-gray-500 mb-1">{{ ec.entity_label || ec.entity_type }}</p>
            <div class="flex flex-wrap gap-1">
              <button
                v-for="cand in ec.candidates"
                :key="cand.value"
                type="button"
                :disabled="isEntityResolved"
                @click="toggleEntity(i, cand.value)"
                class="flex items-center gap-1 text-xs px-2 py-1 rounded border transition-colors"
                :class="isEntityResolved
                  ? (isEntityChecked(i, cand.value) ? 'border-green-300 bg-green-50 text-green-700 cursor-default' : 'border-gray-100 bg-gray-50 text-gray-300 cursor-default')
                  : (isEntityChecked(i, cand.value) ? 'border-amber-400 bg-amber-100 text-amber-800 cursor-pointer' : 'border-gray-200 bg-white text-gray-600 hover:border-amber-200 cursor-pointer')"
              >
                <svg v-if="isEntityChecked(i, cand.value)" class="w-3 h-3 flex-shrink-0" :class="isEntityResolved ? 'text-green-500' : 'text-amber-500'" fill="currentColor" viewBox="0 0 20 20">
                  <path fill-rule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clip-rule="evenodd" />
                </svg>
                {{ cand.label || cand.value }}
              </button>
            </div>
          </div>
          <button
            v-if="!isEntityResolved"
            @click="onConfirmEntities"
            :disabled="!hasConfirmedSelections"
            class="mt-2 px-4 py-1.5 text-xs rounded font-medium transition-colors"
            :class="hasConfirmedSelections ? 'bg-amber-400 text-gray-900 hover:bg-amber-300' : 'bg-gray-200 text-gray-400 cursor-not-allowed'"
          >
            确认选择
          </button>
          <p v-else class="mt-2 text-xs text-green-600">✓ 已确认，后续不可修改</p>
        </div>

        <!-- 4. StatCard for COUNT results -->
        <SqlQaStatCard
          v-if="msg.results && msg.results.length === 1 && isCountResult(msg.results[0])"
          :value="getCountValue(msg.results[0])"
          :tags="getCountTags(msg.results[0])"
        />

        <!-- 6. Result table (single query, merged with SQL) -->
        <SqlQaResultTable v-else-if="msg.results && !msg.result_groups" :data="msg.results" :sql="msg.sql || ''" />

        <!-- 7. Result groups (multi-query) -->
        <SqlQaResultGroups v-if="msg.result_groups" :groups="msg.result_groups" />

        <!-- 8. Chart -->
        <SqlQaChart v-if="msg.analysis_chart" :chart-data="msg.analysis_chart" />

        <!-- Followup suggestions (追问建议) -->
        <div v-if="msg.followups && msg.followups.length > 0" class="flex flex-wrap gap-1.5">
          <button
            v-for="(f, i) in msg.followups"
            :key="i"
            @click="$emit('suggestion-select', { text: typeof f === 'string' ? f : (f.text || f.question || ''), source_question: msg.question || '', source_sql: msg.sql || '' })"
            class="text-xs px-2.5 py-1 rounded-full bg-amber-50 text-amber-700 border border-amber-200 hover:bg-amber-100 transition-colors"
          >
            {{ typeof f === 'string' ? f : (f.text || f.question || '') }}
          </button>
        </div>

        <!-- Citation references -->
        <div v-if="citationRefs.length > 0" class="flex flex-wrap gap-1">
          <button
            v-for="(ref, i) in citationRefs"
            :key="i"
            @click="openCitation(ref)"
            class="text-xs px-2 py-0.5 rounded bg-blue-50 text-blue-600 hover:bg-blue-100 transition-colors"
          >
            参考 {{ ref.index }}: {{ ref.name || '文档' }}
          </button>
        </div>

        <!-- Feedback buttons -->
        <SqlQaFeedbackButtons
          v-if="msg.content && msg.content !== '正在处理...' && !msg.needs_clarification && (msg.sql || msg.results || msg.result_groups) && !isMsgFailure"
          :status="msg.feedback_status"
          :feedback-text="msg.feedback_text"
          @correct="$emit('feedback-correct', msg)"
          @wrong="(text) => $emit('feedback-wrong', msg, text)"
          @reset="$emit('feedback-reset', msg)"
        />
      </template>
    </div>

    <!-- User avatar -->
    <div v-if="msg.role === 'user'" class="flex-shrink-0 w-8 h-8 rounded-full bg-gray-200 flex items-center justify-center text-gray-500 text-xs font-bold mt-1">U</div>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'
import SqlQaStepProgress from './SqlQaStepProgress.vue'
import SqlQaExecutionSteps from './SqlQaExecutionSteps.vue'
import AgenticThinking from './AgenticThinking.vue'
import AgenticSteps from './AgenticSteps.vue'
import SqlQaStatCard from './SqlQaStatCard.vue'
import SqlQaResultTable from './SqlQaResultTable.vue'
import SqlQaResultGroups from './SqlQaResultGroups.vue'
import SqlQaChart from './SqlQaChart.vue'
import SqlQaFeedbackButtons from './SqlQaFeedbackButtons.vue'
import { marked } from 'marked'

const props = defineProps({
  msg: { type: Object, required: true },
  question: { type: String, default: '' },
})

const emit = defineEmits(['entity-confirm', 'suggestion-select', 'feedback-correct', 'feedback-wrong', 'feedback-reset', 'citation-open', 'clarify-confirm'])

const clarifySelections = ref({})
const clarifyCustoms = ref({})
const clarifyLoading = ref(false)

const clarifyResolved = computed(() => {
  return props.msg.clarification_groups?.some(g => g.resolved) || false
})

function isClarifySelected(gi, opt) {
  return (clarifySelections.value[gi] || []).includes(opt)
}

function isClarifySelectedResolved(gi, opt, group) {
  if (!group.resolved) return false
  return (group.selected || []).includes(opt)
}

function isAllSelected(gi, group) {
  const selected = clarifySelections.value[gi] || []
  return group.options.every(opt => selected.includes(opt))
}

function toggleSelectAll(gi, group) {
  if (isAllSelected(gi, group)) {
    clarifySelections.value[gi] = []
  } else {
    clarifySelections.value[gi] = [...group.options]
  }
}

function toggleClarifyOption(gi, opt, multi) {
  const current = clarifySelections.value[gi] || []
  const updated = multi
    ? (current.includes(opt) ? current.filter(v => v !== opt) : [...current, opt])
    : (current.includes(opt) ? [] : [opt])
  clarifySelections.value = { ...clarifySelections.value, [gi]: updated }
}

function addClarifyCustom(gi, field) {
  const text = (clarifyCustoms.value[gi] || '').trim()
  if (!text) return
  const current = clarifySelections.value[gi] || []
  if (current.includes(text)) return // 去重
  clarifySelections.value = { ...clarifySelections.value, [gi]: [...current, text] }
  clarifyCustoms.value = { ...clarifyCustoms.value, [gi]: '' }
}

async function onClarifyConfirm() {
  if (clarifyLoading.value) return
  const groups = props.msg.clarification_groups || []
  const selections = groups.map((g, i) => ({
    field: g.field,
    values: clarifySelections.value[i] || [],
  })).filter(s => s.values.length > 0)

  if (selections.length === 0) return

  clarifyLoading.value = true
  clarifySelections.value = {}
  emit('clarify-confirm', {
    entityContext: selections,
    msgId: props.msg.id,
  })
  clarifyLoading.value = false
}

const hasAnswer = computed(() => {
  return props.msg.content && props.msg.content !== '正在处理...'
})

const isMsgFailure = computed(() => {
  const text = props.msg.content || ''
  return text.startsWith('抱歉，多次尝试后仍无法获取正确数据')
})

// Entity clarification state
const entitySelections = ref({})

const isEntityResolved = computed(() => {
  if (!props.msg.entity_candidates || props.msg.entity_candidates.length === 0) return false
  return props.msg.entity_candidates[0].resolved === true
})

function isEntityChecked(entityIdx, value) {
  if (isEntityResolved.value) {
    const ec = props.msg.entity_candidates[entityIdx]
    return (ec?.selected_values || []).includes(value)
  }
  return (entitySelections.value[entityIdx] || []).includes(value)
}

function toggleEntity(entityIdx, value) {
  const current = entitySelections.value[entityIdx] || []
  if (current.includes(value)) {
    entitySelections.value[entityIdx] = current.filter(v => v !== value)
  } else {
    entitySelections.value[entityIdx] = [...current, value]
  }
}

const hasConfirmedSelections = computed(() => {
  if (!props.msg.entity_candidates) return false
  return props.msg.entity_candidates.every((_, i) => (entitySelections.value[i] || []).length > 0)
})

function onConfirmEntities() {
  if (!hasConfirmedSelections.value) return
  const entities = []
  props.msg.entity_candidates.forEach((ec, i) => {
    const selectedValues = entitySelections.value[i] || []
    selectedValues.forEach(val => {
      const candidate = ec.candidates.find(c => c.value === val)
      if (candidate) {
        entities.push({
          entity_type: candidate.entity_type || ec.entity_type,
          mention: candidate.mention || ec.mention || '',
          label: candidate.label,
          value: candidate.value,
          sql_hint: candidate.sql_hint || '',
        })
      }
    })
  })
  emit('entity-confirm', props.question || props.msg.content, entities)
}

// COUNT result helpers
function isCountResult(row) {
  if (!row) return false
  const keys = Object.keys(row)
  return keys.length <= 2 && keys.some(k => /count|数量|total|总计/i.test(k)) && Object.values(row).some(v => typeof v === 'number')
}

function getCountValue(row) {
  return Object.values(row).find(v => typeof v === 'number') || null
}

function getCountTags(row) {
  return Object.entries(row)
    .filter(([_, v]) => typeof v !== 'number')
    .map(([k, v]) => `${k}: ${v}`)
}

// Markdown rendering (simple)
const renderedContent = computed(() => {
  const text = props.msg.content || ''
  if (!text || text === '正在处理...') return ''
  return renderSimpleMarkdown(text)
})

function renderSimpleMarkdown(text) {
  return marked.parse(text)
}

// Citation references
const citationRefs = computed(() => {
  const refs = []
  const text = props.msg.content || ''
  const regex = /##(\d+)\$\$/g
  let match
  while ((match = regex.exec(text)) !== null) {
    const idx = parseInt(match[1])
    if (props.msg.rag_references?.chunks?.[idx]) {
      const chunk = props.msg.rag_references.chunks[idx]
      refs.push({
        index: idx,
        name: chunk.document_name || '文档',
        document_id: chunk.document_id,
        dataset_id: chunk.dataset_id,
        page: chunk.positions ? parseInt(chunk.positions[0]) : null,
      })
    }
  }
  return refs
})

function openCitation(ref) {
  emit('citation-open', ref)
}
</script>

<style scoped>
</style>
