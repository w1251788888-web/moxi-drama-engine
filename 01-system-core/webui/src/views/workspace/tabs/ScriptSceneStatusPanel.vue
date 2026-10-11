<script setup lang="ts">
import { computed } from 'vue'
import { Database, FileText, SearchCheck } from 'lucide-vue-next'

type Character = {
  id: string
  name: string
  role: string
}

type WorkflowChainStatus = {
  contractCount: number
  windowCount: number
  ragCardCount: number
  issueCount: number
}

type RagEvidenceItem = {
  kind?: string
  backend?: string
  source?: string
  inject_as?: string
  query?: string
  count?: number
  doc_types?: string[]
  items?: Array<{
    source_type?: string
    source_path?: string
    chunk_index?: number
    title?: string
    excerpt?: string
  }>
}

type RagEvidenceLog = {
  created_at?: string
  episode_no?: number
  scene_no?: number
  summary?: string
  items?: RagEvidenceItem[]
}

const props = defineProps<{
  characters: Character[]
  scriptSceneCharacters: string[]
  isValidatingScriptRules: boolean
  isAutoFixingScript: boolean
  scriptStreamStatus: string
  workflowChainStatus: WorkflowChainStatus
  showRagEvidence?: boolean
  latestRagEvidenceLog?: RagEvidenceLog | null
  roleColorFor: (role: string) => string
}>()

defineEmits<{
  toggleCharacter: [id: string]
}>()

const evidenceItems = computed(() => {
  const raw = props.latestRagEvidenceLog?.items
  return Array.isArray(raw) ? raw.slice(0, 4) : []
})

const evidenceTotal = computed(() => {
  return evidenceItems.value.reduce((sum, item) => sum + Number(item.count || 0), 0)
})

const isScriptStreamFailure = computed(() => {
  const status = String(props.scriptStreamStatus || '')
  return /失败|错误|质量门|EMPTY_SCRIPT_DRAFT|quality_gate/i.test(status)
})

function formatEvidenceKind(item: RagEvidenceItem) {
  const kind = String(item.kind || item.backend || '').trim()
  if (kind === 'dify') return '外部素材库'
  if (kind.includes('local') || kind.includes('knowledge')) return '项目资料'
  return kind || '参考素材'
}

</script>

<template>
  <div class="border-b px-3 py-2 bg-muted/10 shrink-0">
    <div class="flex items-center gap-2 flex-wrap">
      <span class="text-xs text-muted-foreground shrink-0">本集角色：</span>
      <button
        v-for="char in props.characters"
        :key="char.id"
        class="text-xs px-2 py-0.5 rounded-full border transition-all"
        :class="props.scriptSceneCharacters.includes(char.id)
          ? 'text-white border-transparent'
          : 'border-muted-foreground/30 text-muted-foreground hover:border-primary/50 hover:text-primary'"
        :style="props.scriptSceneCharacters.includes(char.id) ? { background: props.roleColorFor(char.role) } : {}"
        @click="$emit('toggleCharacter', char.id)"
      >
        {{ char.name }}
      </button>
      <span v-if="props.characters.length === 0" class="text-xs text-muted-foreground">角色库为空，请先在角色设计中添加</span>
      <span class="text-xs text-muted-foreground ml-auto">自动检测 · 点击切换出场</span>
    </div>
    <div v-if="props.isValidatingScriptRules || props.isAutoFixingScript" class="mt-2 rounded-lg bg-muted/60 px-2 py-1.5 text-[11px] text-muted-foreground">
      正在进行本集质量检查与内容整理…
    </div>
    <div
      v-else-if="props.scriptStreamStatus"
      class="mt-2 rounded-lg px-2 py-1.5 text-[11px] whitespace-pre-line"
      :class="isScriptStreamFailure
        ? 'border border-red-200 bg-red-50 text-red-700'
        : 'bg-muted/60 text-muted-foreground'"
    >
      {{ props.scriptStreamStatus }}
    </div>

    <details
      v-if="props.showRagEvidence && evidenceItems.length"
      class="mt-2 rounded-md border border-border/60 bg-background/80 text-xs"
    >
      <summary class="flex cursor-pointer list-none items-center gap-2 px-2.5 py-2 text-muted-foreground hover:text-foreground">
        <SearchCheck class="h-3.5 w-3.5 text-emerald-600" />
        <span class="font-medium text-foreground">参考素材记录</span>
        <span class="rounded bg-muted px-1.5 py-0.5 tabular-nums">{{ evidenceTotal }} 条</span>
        <span v-if="props.latestRagEvidenceLog?.episode_no" class="text-muted-foreground/70">
          第{{ props.latestRagEvidenceLog.episode_no }}集
        </span>
        <span class="truncate">{{ props.latestRagEvidenceLog?.summary }}</span>
      </summary>
      <div class="border-t border-border/50 px-2.5 py-2 space-y-2">
        <div
          v-for="item in evidenceItems"
          :key="`${item.backend}-${item.source}-${item.inject_as}-${item.query}`"
          class="space-y-1"
        >
          <div class="flex flex-wrap items-center gap-1.5 text-[11px]">
            <Database class="h-3 w-3 text-muted-foreground" />
            <span class="font-medium">{{ formatEvidenceKind(item) }}</span>
            <span v-if="item.query" class="truncate text-muted-foreground/80">关键词：{{ item.query }}</span>
          </div>
          <div
            v-for="(source, sourceIndex) in (item.items || []).slice(0, 3)"
            :key="`${source.title || item.source || '素材'}-${sourceIndex}`"
            class="ml-4 flex min-w-0 items-start gap-1.5 text-[11px] text-muted-foreground"
          >
            <FileText class="mt-0.5 h-3 w-3 shrink-0" />
            <span class="min-w-0 truncate">
              {{ source.title || '参考素材片段' }}
            </span>
          </div>
          <div
            v-if="!(item.items || []).length && item.source"
            class="ml-4 flex min-w-0 items-start gap-1.5 text-[11px] text-muted-foreground"
          >
            <FileText class="mt-0.5 h-3 w-3 shrink-0" />
            <span class="min-w-0 truncate">{{ item.source }}</span>
          </div>
        </div>
      </div>
    </details>
    <!--
      原 4 张工作流指标卡片已对用户隐藏（生成上下文元数据，
      不是创作面要关注的）。workflowChainStatus prop 保留，AI 生成时仍消费。
    -->
  </div>
</template>
