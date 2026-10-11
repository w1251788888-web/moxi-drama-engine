<script setup lang="ts">
import { computed, ref } from 'vue'
import { Database, FileText, Filter, RotateCcw, Search, SearchCheck } from 'lucide-vue-next'
import { RAG_EVIDENCE_LOG_MAX } from '@/features/workspace/utils/workflowState'

type RagEvidenceSource = {
  source_type?: string
  source_path?: string
  chunk_index?: number
  title?: string
  excerpt?: string
}

type RagEvidenceItem = {
  kind?: string
  backend?: string
  source?: string
  inject_as?: string
  query?: string
  count?: number
  doc_types?: string[]
  items?: RagEvidenceSource[]
}

type RagEvidenceLog = {
  created_at?: string
  episode_no?: number
  scene_no?: number
  summary?: string
  items?: RagEvidenceItem[]
}

const props = defineProps<{
  logs: RagEvidenceLog[]
  selectedEpisode?: number | { episode_number?: number } | null
}>()

const query = ref('')
const sourceType = ref('all')
const docTypeFilter = ref('all')
const injectTargetFilter = ref('all')
const episodeScope = ref<'current' | 'all'>('current')
const expandedKeys = ref<Set<string>>(new Set())

const normalizedLogs = computed(() => {
  return Array.isArray(props.logs)
    ? props.logs
        .filter(item => item && typeof item === 'object')
        .map((item, index) => ({
          ...item,
          _key: `${item.created_at || 'time'}-${item.episode_no || 0}-${item.scene_no || 0}-${index}`,
          items: Array.isArray(item.items) ? item.items : [],
        }))
    : []
})

const currentEpisodeNo = computed(() => {
  if (typeof props.selectedEpisode === 'number') return props.selectedEpisode
  return Number(props.selectedEpisode?.episode_number || 0)
})

const sourceTypeOptions = computed(() => {
  const values = new Set<string>()
  for (const log of normalizedLogs.value) {
    for (const item of log.items) {
      const kind = normalizeKind(item)
      if (kind) values.add(kind)
    }
  }
  return Array.from(values).sort((a, b) => a.localeCompare(b))
})

const docTypeOptions = computed(() => {
  const values = new Set<string>()
  for (const log of normalizedLogs.value) {
    for (const item of log.items) {
      for (const docType of itemDocTypes(item)) {
        values.add(docType)
      }
    }
  }
  return Array.from(values).sort((a, b) => a.localeCompare(b))
})

const injectTargetOptions = computed(() => {
  const values = new Set<string>()
  for (const log of normalizedLogs.value) {
    for (const item of log.items) {
      const target = normalizeText(item.inject_as)
      if (target) values.add(target)
    }
  }
  return Array.from(values).sort((a, b) => a.localeCompare(b))
})

const filteredLogs = computed(() => {
  const term = query.value.trim().toLowerCase()
  return normalizedLogs.value.filter(log => {
    if (
      episodeScope.value === 'current'
      && currentEpisodeNo.value > 0
      && Number(log.episode_no || 0) !== currentEpisodeNo.value
    ) {
      return false
    }

    const flattenedItems = log.items.flatMap(item => [
      item.kind,
      item.backend,
      item.source,
      item.inject_as,
      item.query,
      ...(Array.isArray(item.doc_types) ? item.doc_types : []),
      ...(Array.isArray(item.items)
        ? item.items.flatMap(source => [
            source.source_type,
            source.source_path,
            source.title,
            source.excerpt,
            source.chunk_index,
          ])
        : []),
    ])

    const haystack = [
      log.created_at,
      log.episode_no,
      log.scene_no,
      log.summary,
      ...flattenedItems,
    ].map(value => String(value ?? '').toLowerCase()).join('\n')

    const matchesQuery = !term || haystack.includes(term)
    const matchesType = sourceType.value === 'all'
      || log.items.some(item => normalizeKind(item) === sourceType.value)
    const matchesDocType = docTypeFilter.value === 'all'
      || log.items.some(item => itemDocTypes(item).includes(docTypeFilter.value))
    const matchesInjectTarget = injectTargetFilter.value === 'all'
      || log.items.some(item => normalizeText(item.inject_as) === injectTargetFilter.value)
    return matchesQuery && matchesType && matchesDocType && matchesInjectTarget
  })
})

const visibleLogs = computed(() => filteredLogs.value.slice(0, RAG_EVIDENCE_LOG_MAX))

const totalEvidenceCount = computed(() => {
  return filteredLogs.value.reduce((sum, log) => sum + logEvidenceCount(log), 0)
})

const hasActiveFilters = computed(() => {
  return Boolean(query.value.trim())
    || sourceType.value !== 'all'
    || docTypeFilter.value !== 'all'
    || injectTargetFilter.value !== 'all'
    || episodeScope.value !== 'current'
})

const filterSummary = computed(() => {
  const scope = episodeScope.value === 'current' && currentEpisodeNo.value > 0
    ? `第${currentEpisodeNo.value}集`
    : '全部集'
  return `${scope} / ${filteredLogs.value.length} of ${normalizedLogs.value.length} 次 / ${totalEvidenceCount.value} 条证据`
})

const DOC_TYPE_LABELS: Record<string, string> = {
  project: '项目文本',
  rule: '创作规则',
  material: '素材样本',
  skill: '工具规则',
}

const INJECT_TARGET_LABELS: Record<string, string> = {
  rag_script_references: '剧本参考',
  rag_beat_references: '节拍参考',
  rag_character_references: '角色参考',
  rag_review_references: '评审参考',
  rag_outline_references: '大纲参考',
}

function normalizeText(value: unknown) {
  return String(value ?? '').trim()
}

function normalizeKind(item: RagEvidenceItem) {
  return normalizeText(item.kind || item.backend || item.source)
}

function formatEvidenceKind(item: RagEvidenceItem) {
  const kind = normalizeKind(item)
  if (kind === 'dify') return '外部素材库'
  if (kind.includes('local') || kind.includes('knowledge')) return '项目资料'
  return kind || '参考素材'
}

function itemDocTypes(item: RagEvidenceItem) {
  const values = new Set<string>()
  if (Array.isArray(item.doc_types)) {
    for (const docType of item.doc_types) {
      const normalized = normalizeText(docType)
      if (normalized) values.add(normalized)
    }
  }
  if (Array.isArray(item.items)) {
    for (const source of item.items) {
      const normalized = normalizeText(source.source_type)
      if (normalized) values.add(normalized)
    }
  }
  return Array.from(values)
}

function itemEvidenceCount(item: RagEvidenceItem) {
  const declaredCount = Number(item.count || 0)
  if (declaredCount > 0) return declaredCount
  return Array.isArray(item.items) ? item.items.length : 0
}

function logEvidenceCount(log: { items?: RagEvidenceItem[] }) {
  return Array.isArray(log.items)
    ? log.items.reduce((sum, item) => sum + itemEvidenceCount(item), 0)
    : 0
}

function formatDocType(value?: string) {
  const key = normalizeText(value)
  return DOC_TYPE_LABELS[key] || key || '未知类型'
}

function formatInjectTarget(value?: string) {
  const key = normalizeText(value)
  return INJECT_TARGET_LABELS[key] || key || '未记录用途'
}

function formatCreatedAt(value?: string) {
  const text = String(value || '').trim()
  if (!text) return '未记录时间'
  const parsed = new Date(text)
  if (Number.isNaN(parsed.getTime())) return text.slice(0, 19)
  return parsed.toLocaleString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

function formatSourcePath(value?: string) {
  const text = String(value || '').trim()
  if (!text) return '未记录来源'
  const parts = text.split('/')
  return parts.slice(-3).join('/')
}

function resetFilters() {
  query.value = ''
  sourceType.value = 'all'
  docTypeFilter.value = 'all'
  injectTargetFilter.value = 'all'
  episodeScope.value = 'current'
}

function toggleExpanded(key: string) {
  const next = new Set(expandedKeys.value)
  if (next.has(key)) {
    next.delete(key)
  } else {
    next.add(key)
  }
  expandedKeys.value = next
}
</script>

<template>
  <div
    v-if="normalizedLogs.length"
    class="border-b bg-background px-3 py-2 shrink-0"
  >
    <div class="flex flex-wrap items-center gap-2">
      <div class="flex items-center gap-1.5 text-xs font-medium">
        <SearchCheck class="h-3.5 w-3.5 text-emerald-600" />
        <span>参考素材历史</span>
        <span class="rounded bg-muted px-1.5 py-0.5 text-[11px] font-normal text-muted-foreground tabular-nums">
          {{ filteredLogs.length }} 次 / {{ totalEvidenceCount }} 条
        </span>
        <span class="hidden text-[11px] font-normal text-muted-foreground lg:inline">
          {{ filterSummary }}
        </span>
      </div>

      <div class="ml-auto flex min-w-0 flex-wrap items-center gap-1.5">
        <label class="relative">
          <Search class="pointer-events-none absolute left-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
          <input
            v-model="query"
            type="search"
            class="h-7 w-40 rounded-md border bg-background pl-7 pr-2 text-xs outline-none focus:border-primary sm:w-44"
            placeholder="检索来源、摘要、关键词"
          >
        </label>
        <label class="relative">
          <Filter class="pointer-events-none absolute left-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
          <select
            v-model="sourceType"
            class="h-7 rounded-md border bg-background pl-7 pr-7 text-xs outline-none focus:border-primary"
          >
            <option value="all">全部来源</option>
            <option
              v-for="option in sourceTypeOptions"
              :key="option"
              :value="option"
            >
              {{ option }}
            </option>
          </select>
        </label>
        <label class="relative">
          <Filter class="pointer-events-none absolute left-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
          <select
            v-model="docTypeFilter"
            class="h-7 rounded-md border bg-background pl-7 pr-7 text-xs outline-none focus:border-primary"
          >
            <option value="all">全部文档</option>
            <option
              v-for="option in docTypeOptions"
              :key="option"
              :value="option"
            >
              {{ formatDocType(option) }}
            </option>
          </select>
        </label>
        <label class="relative">
          <Filter class="pointer-events-none absolute left-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
          <select
            v-model="injectTargetFilter"
            class="h-7 rounded-md border bg-background pl-7 pr-7 text-xs outline-none focus:border-primary"
          >
            <option value="all">全部用途</option>
            <option
              v-for="option in injectTargetOptions"
              :key="option"
              :value="option"
            >
              {{ formatInjectTarget(option) }}
            </option>
          </select>
        </label>
        <div class="inline-flex h-7 rounded-md border bg-background p-0.5 text-[11px]">
          <button
            class="rounded px-2 transition-colors"
            :class="episodeScope === 'current' ? 'bg-muted text-foreground' : 'text-muted-foreground hover:text-foreground'"
            @click="episodeScope = 'current'"
          >
            当前集
          </button>
          <button
            class="rounded px-2 transition-colors"
            :class="episodeScope === 'all' ? 'bg-muted text-foreground' : 'text-muted-foreground hover:text-foreground'"
            @click="episodeScope = 'all'"
          >
            全部
          </button>
        </div>
        <button
          v-if="hasActiveFilters"
          class="inline-flex h-7 w-7 items-center justify-center rounded-md border bg-background text-muted-foreground transition-colors hover:text-foreground"
          title="清除筛选"
          @click="resetFilters"
        >
          <RotateCcw class="h-3.5 w-3.5" />
        </button>
      </div>
    </div>

    <div
      v-if="filteredLogs.length"
      class="mt-2 max-h-48 space-y-1.5 overflow-y-auto pr-1"
    >
      <div
        v-for="log in visibleLogs"
        :key="log._key"
        class="rounded-md border border-border/70 bg-muted/20"
      >
        <button
          class="flex w-full min-w-0 items-center gap-2 px-2.5 py-1.5 text-left text-xs"
          @click="toggleExpanded(log._key)"
        >
          <span class="shrink-0 rounded bg-background px-1.5 py-0.5 text-[11px] text-muted-foreground">
            第{{ log.episode_no || '-' }}集<span v-if="log.scene_no"> / 场{{ log.scene_no }}</span>
          </span>
          <span class="min-w-0 flex-1 truncate">{{ log.summary || '本次召回未写入摘要' }}</span>
          <span class="shrink-0 rounded bg-background px-1.5 py-0.5 text-[11px] text-muted-foreground tabular-nums">
            {{ logEvidenceCount(log) }} 条
          </span>
          <span class="shrink-0 text-[11px] text-muted-foreground">{{ formatCreatedAt(log.created_at) }}</span>
        </button>

        <div
          v-if="expandedKeys.has(log._key)"
          class="border-t border-border/60 px-2.5 py-2"
        >
          <div
            v-for="item in log.items"
            :key="`${log._key}-${item.backend}-${item.source}-${item.inject_as}-${item.query}`"
            class="mb-2 last:mb-0"
          >
            <div class="flex min-w-0 flex-wrap items-center gap-1.5 text-[11px]">
              <Database class="h-3 w-3 text-muted-foreground" />
              <span class="font-medium">{{ formatEvidenceKind(item) }}</span>
              <span v-if="item.inject_as" class="text-muted-foreground">{{ formatInjectTarget(item.inject_as) }}</span>
              <span
                v-if="itemDocTypes(item).length"
                class="rounded bg-background px-1 py-0.5 text-muted-foreground"
              >
                {{ itemDocTypes(item).map(formatDocType).join(' / ') }}
              </span>
              <span v-if="item.query" class="min-w-0 truncate text-muted-foreground">关键词：{{ item.query }}</span>
              <span
                v-if="itemEvidenceCount(item)"
                class="rounded bg-background px-1 py-0.5 text-muted-foreground tabular-nums"
              >
                {{ itemEvidenceCount(item) }} 条
              </span>
            </div>

            <div
              v-for="source in (item.items || []).slice(0, 4)"
              :key="`${source.source_path}-${source.chunk_index}`"
              class="ml-4 mt-1 flex min-w-0 items-start gap-1.5 text-[11px] text-muted-foreground"
            >
              <FileText class="mt-0.5 h-3 w-3 shrink-0" />
              <span class="min-w-0">
                <span class="block truncate">
                  <span
                    v-if="source.source_type"
                    class="mr-1 rounded bg-background px-1 py-0.5 text-[10px]"
                  >
                    {{ formatDocType(source.source_type) }}
                  </span>
                  {{ source.title || formatSourcePath(source.source_path) }}
                  <span class="text-muted-foreground/60">#{{ source.chunk_index }}</span>
                </span>
                <span v-if="source.excerpt" class="block truncate text-muted-foreground/70">
                  {{ source.excerpt }}
                </span>
              </span>
            </div>
          </div>
        </div>
      </div>
      <div
        v-if="filteredLogs.length > visibleLogs.length"
        class="text-center text-[11px] text-muted-foreground"
      >
        已显示最近 {{ visibleLogs.length }} 次，继续缩小筛选可定位更早记录
      </div>
    </div>

    <div
      v-else
      class="mt-2 flex items-center justify-between gap-2 rounded-md border border-dashed px-2.5 py-2 text-xs text-muted-foreground"
    >
      <span>当前筛选条件下没有召回记录</span>
      <button
        v-if="hasActiveFilters"
        class="inline-flex h-7 items-center gap-1 rounded-md border bg-background px-2 text-[11px] text-foreground"
        @click="resetFilters"
      >
        <RotateCcw class="h-3 w-3" />
        清除筛选
      </button>
    </div>
  </div>
</template>
