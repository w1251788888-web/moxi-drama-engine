<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { ArrowRight, Check, Circle, CircleDot, FilePenLine, RotateCcw } from 'lucide-vue-next'
import { Button } from '@/components/ui/button'

type StepStatus = 'pending' | 'running' | 'completed' | 'action_required' | 'blocked'

type ScriptWorkflowStep = {
  id: string
  label: string
  status: StepStatus
  description?: string
}

type ConfirmationStepId = 'prerequisite' | 'blueprint' | 'segment_cards' | 'candidate_save'

type ConfirmationItem = {
  key: string
  title: string
  body: string
  helper?: string
  editable?: boolean
  source?: string
}

type ConfirmationSection = {
  summary?: string
  note?: string
  items?: ConfirmationItem[]
}

type StepConfirmationPacket = Partial<Record<ConfirmationStepId, ConfirmationSection>> & {
  episode_no?: number
}

type ConfirmationStep = {
  id: ConfirmationStepId
  sourceIds: string[]
  title: string
  summary: string
  confirmText: string
  collapsedText: string
  pendingText: string
}

const props = defineProps<{
  selectedEpisode: number
  workflowSteps?: ScriptWorkflowStep[]
  scriptStreamStatus?: string
  isGeneratingScript?: boolean
  confirmationPacket?: StepConfirmationPacket
}>()

const emit = defineEmits<{
  regenerateStep: [payload: { stepId: ConfirmationStepId }]
  saveCandidate: []
  focusEditor: []
  updateConfirmationItem: [payload: { stepId: ConfirmationStepId; itemKey: string; body: string }]
  commitConfirmationItem: [payload: { stepId: ConfirmationStepId; itemKey: string; body: string }]
  commitConfirmationStep: [payload: { stepId: ConfirmationStepId; items: Array<{ itemKey: string; body: string }> }]
}>()

const confirmationSteps: ConfirmationStep[] = [
  {
    id: 'prerequisite',
    sourceIds: ['prerequisite_check', 'outline_check', 'context_check'],
    title: '前提资料',
    summary: '确认大纲、集纲、人物小传和上一集用户定稿已经进入本集依据。',
    confirmText: '确认前提资料',
    collapsedText: '已确认前提资料。',
    pendingText: '生成开始前先确认前提资料是否齐全。',
  },
  {
    id: 'blueprint',
    sourceIds: ['director_blueprint', 'blueprint', 'director_contract'],
    title: '本集导演蓝图',
    summary: '确认本集爽点、失控点、角色边界和结尾钩子，再进入四段任务卡。',
    confirmText: '确认并进入下一步',
    collapsedText: '已确认本集蓝图。',
    pendingText: '等待蓝图生成或用户确认。',
  },
  {
    id: 'segment_cards',
    sourceIds: ['segment_task_cards', 'segment_cards', 'four_part_cards'],
    title: '四段任务卡',
    summary: '检查四段是否都有钩子、推进、情绪兑现和新钩子。',
    confirmText: '确认并进入下一步',
    collapsedText: '已确认四段任务卡。',
    pendingText: '蓝图确认后再展开四段任务卡。',
  },
  {
    id: 'candidate_save',
    sourceIds: ['candidate_draft', 'review_and_save', 'draft_review', 'save_canon'],
    title: '正文候选与保存',
    summary: '正文候选生成后展开；保存后成为下一集承接的正史。',
    confirmText: '确认候选并保存',
    collapsedText: '候选保存后会成为下一集承接依据。',
    pendingText: '四段任务卡确认后再生成正文候选。',
  },
]

const localConfirmedStepIds = ref<ConfirmationStepId[]>([])
const expandedStepId = ref<ConfirmationStepId | null>('blueprint')

const backendStepById = computed(() => {
  const map = new Map<string, ScriptWorkflowStep>()
  for (const step of props.workflowSteps || []) {
    const id = String(step.id || '').trim()
    if (id) map.set(id, step)
  }
  return map
})

function findBackendStep(step: ConfirmationStep) {
  for (const sourceId of step.sourceIds) {
    const exact = backendStepById.value.get(sourceId)
    if (exact) return exact
  }
  return (props.workflowSteps || []).find((item) => {
    const text = `${item.id} ${item.label}`.toLowerCase()
    if (step.id === 'prerequisite') return /前提|大纲|集纲|context|outline|prerequisite/.test(text)
    if (step.id === 'blueprint') return /蓝图|导演|director|blueprint/.test(text)
    if (step.id === 'segment_cards') return /四段|任务卡|segment|cards/.test(text)
    return /正文|候选|保存|candidate|draft|save|review/.test(text)
  })
}

function defaultStatus(step: ConfirmationStep): StepStatus {
  if (localConfirmedStepIds.value.includes(step.id)) return 'completed'
  if (props.isGeneratingScript && step.id === 'blueprint') return 'running'
  if (step.id === 'prerequisite') return 'completed'
  if (step.id === 'blueprint') return 'action_required'
  return 'pending'
}

function sectionFor(stepId: ConfirmationStepId): ConfirmationSection {
  const section = props.confirmationPacket?.[stepId]
  if (section && typeof section === 'object') return section
  return {
    summary: confirmationSteps.find(item => item.id === stepId)?.summary || '',
    items: [],
  }
}

function sectionItems(stepId: ConfirmationStepId): ConfirmationItem[] {
  const items = sectionFor(stepId).items
  return Array.isArray(items)
    ? items
        .filter(item => item && String(item.key || '').trim())
        .map(item => ({
          key: String(item.key || '').trim(),
          title: String(item.title || '').trim() || '待确认内容',
          body: String(item.body || ''),
          helper: String(item.helper || '').trim(),
          editable: item.editable !== false,
          source: String(item.source || '').trim(),
        }))
    : []
}

function editedBody(item: ConfirmationItem) {
  return String(item.body || '')
}

const displaySteps = computed(() => confirmationSteps.map((step, index) => {
  const backendStep = findBackendStep(step)
  let status = localConfirmedStepIds.value.includes(step.id)
    ? 'completed'
    : backendStep?.status || defaultStatus(step)
  const previousStep = confirmationSteps[index - 1]
  if (
    status === 'pending'
    && previousStep
    && localConfirmedStepIds.value.includes(previousStep.id)
  ) {
    status = 'action_required'
  }
  const section = sectionFor(step.id)
  return {
    ...step,
    number: index + 1,
    status,
    backendLabel: backendStep?.label || '',
    description: section.summary || backendStep?.description || step.summary,
    items: sectionItems(step.id),
    note: section.note || '',
  }
}))

const currentStep = computed(() => {
  return displaySteps.value.find(item => item.status === 'action_required')
    || displaySteps.value.find(item => item.status === 'running')
    || displaySteps.value.find(item => item.status === 'pending')
    || displaySteps.value[displaySteps.value.length - 1]
})

watch(() => props.selectedEpisode, () => {
  localConfirmedStepIds.value = []
  expandedStepId.value = 'blueprint'
})

watch(currentStep, (step) => {
  if (step && expandedStepId.value === null && !localConfirmedStepIds.value.includes(step.id)) {
    expandedStepId.value = step.id
  }
}, { immediate: false })

function toggleStep(stepId: ConfirmationStepId) {
  expandedStepId.value = expandedStepId.value === stepId ? null : stepId
}

function commitStepItems(step: ConfirmationStep) {
  const items: Array<{ itemKey: string; body: string }> = []
  for (const item of sectionItems(step.id)) {
    items.push({ itemKey: item.key, body: editedBody(item) })
  }
  emit('commitConfirmationStep', { stepId: step.id, items })
}

function confirmStep(step: ConfirmationStep) {
  commitStepItems(step)
  if (step.id === 'candidate_save') {
    emit('saveCandidate')
  }
  if (!localConfirmedStepIds.value.includes(step.id)) {
    localConfirmedStepIds.value = [...localConfirmedStepIds.value, step.id]
  }
  const currentIndex = confirmationSteps.findIndex(item => item.id === step.id)
  const next = confirmationSteps[currentIndex + 1]
  expandedStepId.value = next ? next.id : null
}

function updateItem(stepId: ConfirmationStepId, item: ConfirmationItem, event: Event, commit = false) {
  const target = event.target as HTMLTextAreaElement | null
  const body = target?.value || ''
  const payload = { stepId, itemKey: item.key, body }
  emit('updateConfirmationItem', payload)
  if (commit) emit('commitConfirmationItem', payload)
}

function statusText(status: StepStatus) {
  if (status === 'completed') return '已收起'
  if (status === 'running') return '生成中'
  if (status === 'action_required') return '需要确认'
  if (status === 'blocked') return '需处理'
  return '未开始'
}

function statusClass(status: StepStatus) {
  if (status === 'completed') return 'border-emerald-200 bg-emerald-50 text-emerald-700'
  if (status === 'running') return 'border-blue-200 bg-blue-50 text-blue-700'
  if (status === 'action_required') return 'border-amber-200 bg-amber-50 text-amber-700'
  if (status === 'blocked') return 'border-red-200 bg-red-50 text-red-700'
  return 'border-border bg-muted/30 text-muted-foreground'
}

function markClass(status: StepStatus) {
  if (status === 'completed') return 'bg-emerald-50 text-emerald-700'
  if (status === 'running') return 'bg-blue-50 text-blue-700'
  if (status === 'action_required') return 'bg-primary text-primary-foreground'
  if (status === 'blocked') return 'bg-red-50 text-red-700'
  return 'bg-muted text-muted-foreground'
}
</script>

<template>
  <section class="shrink-0 border-b bg-background" aria-label="分步确认">
    <div class="flex flex-col gap-3 px-3 py-3 lg:px-4">
      <div class="flex flex-col gap-3 xl:flex-row xl:items-center xl:justify-between">
        <div class="flex min-w-0 items-start gap-3">
          <div class="grid h-9 w-9 shrink-0 place-items-center rounded-lg bg-primary/10 text-sm font-bold text-primary">
            {{ selectedEpisode }}
          </div>
          <div class="min-w-0">
            <div class="text-base font-semibold leading-tight">分步确认</div>
            <div class="mt-1 text-xs leading-relaxed text-muted-foreground">
              确认完的步骤会收起；点开查看真实生成依据，点同一项可收起。
            </div>
          </div>
        </div>

        <div class="flex gap-2 overflow-x-auto pb-1 xl:justify-end xl:pb-0" aria-label="分步确认状态">
          <button
            v-for="step in displaySteps.slice(1)"
            :key="`pill-${step.id}`"
            type="button"
            class="inline-flex h-8 shrink-0 items-center gap-1.5 rounded-full border px-3 text-xs font-medium transition-colors"
            :class="expandedStepId === step.id
              ? 'border-primary/30 bg-primary/10 text-primary'
              : 'border-border bg-background text-muted-foreground hover:bg-muted/50'"
            @click="toggleStep(step.id)"
          >
            <span
              class="h-2 w-2 rounded-full"
              :class="step.status === 'completed' ? 'bg-emerald-500' : expandedStepId === step.id ? 'bg-primary' : 'bg-muted-foreground/30'"
            />
            {{ step.id === 'blueprint' ? '蓝图' : step.id === 'segment_cards' ? '四段卡' : '正文候选' }}
          </button>
        </div>
      </div>

      <div class="grid gap-2">
        <article
          v-for="step in displaySteps"
          :key="step.id"
          class="overflow-hidden rounded-lg border bg-background"
          :class="expandedStepId === step.id ? 'border-primary/30 ring-1 ring-primary/15' : 'border-border'"
        >
          <button
            type="button"
            class="flex w-full items-center gap-3 px-3 py-2.5 text-left transition-colors hover:bg-muted/30"
            @click="toggleStep(step.id)"
          >
            <span
              class="grid h-8 w-8 shrink-0 place-items-center rounded-md text-xs font-bold"
              :class="markClass(step.status)"
            >
              <Check v-if="step.status === 'completed'" class="h-4 w-4" />
              <CircleDot v-else-if="step.status === 'running' || step.status === 'action_required'" class="h-4 w-4" />
              <Circle v-else class="h-4 w-4" />
            </span>
            <span class="min-w-0 flex-1">
              <span class="block text-sm font-semibold">{{ step.title }}</span>
              <span class="mt-0.5 block truncate text-xs text-muted-foreground">
                {{ expandedStepId === step.id ? '点此收起' : step.status === 'completed' ? step.collapsedText : step.description || step.pendingText }}
              </span>
            </span>
            <span class="shrink-0 rounded-full border px-2.5 py-1 text-[11px] font-medium" :class="statusClass(step.status)">
              {{ statusText(step.status) }}
            </span>
          </button>

          <div
            v-if="expandedStepId === step.id"
            class="border-t bg-muted/10 p-3"
          >
            <div class="grid gap-3 xl:grid-cols-[minmax(0,1fr)_280px]">
              <div class="grid gap-2 sm:grid-cols-2 xl:grid-cols-3">
                <div
                  v-for="item in step.items"
                  :key="`${step.id}-${item.key}`"
                  class="min-h-28 rounded-lg border bg-background p-3"
                >
                  <div class="flex items-start justify-between gap-2">
                    <div class="min-w-0">
                      <div class="text-sm font-semibold text-foreground">{{ item.title }}</div>
                      <div v-if="item.source" class="mt-0.5 text-[11px] text-muted-foreground">{{ item.source }}</div>
                    </div>
                    <span
                      v-if="item.editable"
                      class="shrink-0 rounded-full bg-blue-50 px-2 py-0.5 text-[11px] font-medium text-blue-700"
                    >
                      可修改
                    </span>
                  </div>
                  <textarea
                    v-if="item.editable"
                    :value="editedBody(item)"
                    class="mt-2 min-h-24 w-full resize-y rounded-md border bg-background px-2.5 py-2 text-xs leading-relaxed outline-none focus:border-primary focus:ring-1 focus:ring-primary/20"
                    @input="updateItem(step.id, item, $event)"
                    @change="updateItem(step.id, item, $event, true)"
                    @blur="updateItem(step.id, item, $event, true)"
                  />
                  <p
                    v-else
                    class="mt-2 whitespace-pre-line text-xs leading-relaxed text-muted-foreground"
                  >
                    {{ item.body || '暂无可展示内容。' }}
                  </p>
                  <p v-if="item.helper" class="mt-2 text-[11px] leading-relaxed text-muted-foreground">
                    {{ item.helper }}
                  </p>
                </div>

                <div
                  v-if="!step.items.length"
                  class="rounded-lg border bg-background p-3 text-xs leading-relaxed text-muted-foreground sm:col-span-2 xl:col-span-3"
                >
                  {{ step.pendingText }}
                </div>
              </div>

              <aside class="rounded-lg border bg-background">
                <div class="border-b px-3 py-2 text-sm font-semibold">确认重点</div>
                <div class="max-h-44 overflow-auto p-3">
                  <div class="rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs leading-relaxed text-amber-900">
                    {{ step.note || step.description || step.pendingText }}
                  </div>
                  <div
                    v-if="scriptStreamStatus"
                    class="mt-2 rounded-md border bg-muted/50 px-3 py-2 text-xs leading-relaxed text-muted-foreground whitespace-pre-line"
                  >
                    {{ scriptStreamStatus }}
                  </div>
                </div>
                <div class="grid grid-cols-2 gap-2 border-t p-2">
                  <Button variant="outline" size="sm" class="gap-1 text-xs" @click.stop="emit('regenerateStep', { stepId: step.id })">
                    <RotateCcw class="h-3.5 w-3.5" />重新生成本步
                  </Button>
                  <Button
                    variant="outline"
                    size="sm"
                    class="gap-1 text-xs border-amber-200 text-amber-700 hover:bg-amber-50"
                    @click.stop="emit('focusEditor')"
                  >
                    <FilePenLine class="h-3.5 w-3.5" />
                    {{ step.id === 'candidate_save' ? '去下方正文编辑' : '查看正文' }}
                  </Button>
                  <Button size="sm" class="col-span-2 gap-1 text-xs" @click.stop="confirmStep(step)">
                    {{ step.confirmText }}<ArrowRight class="h-3.5 w-3.5" />
                  </Button>
                </div>
              </aside>
            </div>
          </div>
        </article>
      </div>
    </div>
  </section>
</template>
