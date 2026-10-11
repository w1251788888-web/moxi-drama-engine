<script setup lang="ts">
import { onMounted } from 'vue'
import {
  AlertCircle,
  BookOpen,
  Database,
  FileSearch,
  Loader2,
  RefreshCw,
  Search,
  Sparkles,
} from 'lucide-vue-next'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import {
  useKnowledgeSearch,
  type KnowledgeDocType,
  type KnowledgeSearchMode,
} from '../composables/useKnowledgeSearch'

const {
  canSearch,
  emptyMessage,
  errorMessage,
  hasSearched,
  isLoading,
  isStatusLoading,
  knowledgeTypeOptions,
  loadStatus,
  mode,
  query,
  responseMeta,
  results,
  runSearch,
  selectedTypes,
  sourcePathFor,
  status,
  statusError,
  statusSummary,
  toggleType,
  typeCounts,
} = useKnowledgeSearch()

const modeOptions: Array<{ value: KnowledgeSearchMode; label: string; icon: typeof Sparkles }> = [
  { value: 'semantic', label: '语义检索', icon: Sparkles },
  { value: 'fulltext', label: '全文检索', icon: FileSearch },
]

const docTypeLabels: Record<KnowledgeDocType, string> = {
  rule: '规则',
  material: '素材',
  project: '项目',
  skill: '技能',
}

function docTypeLabel(type: KnowledgeDocType) {
  return docTypeLabels[type] || type
}

function scoreLabel(score: number) {
  if (!Number.isFinite(score)) return ''
  return score > 1 ? score.toFixed(1) : score.toFixed(3)
}

onMounted(() => {
  loadStatus()
})
</script>

<template>
  <section class="mb-8 rounded-xl border bg-card p-5 shadow-sm">
    <div class="mb-4 flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
      <div>
        <div class="flex items-center gap-2">
          <BookOpen class="h-5 w-5 text-primary" />
          <h2 class="text-lg font-semibold">知识库检索 / 规则素材检索</h2>
        </div>
        <p class="mt-1 text-sm text-muted-foreground">只读召回创作规则、热榜素材和项目文本，辅助灵感判断。</p>
      </div>

      <div class="rounded-lg border bg-muted/30 px-3 py-2 text-xs text-muted-foreground">
        <div class="flex items-center gap-2 font-medium text-foreground">
          <Database class="h-3.5 w-3.5" />
          <span>{{ statusSummary }}</span>
          <Loader2 v-if="isStatusLoading" class="h-3.5 w-3.5 animate-spin" />
        </div>
        <div v-if="statusError" class="mt-1 text-amber-600 dark:text-amber-300">{{ statusError }}</div>
        <div v-else class="mt-1 flex flex-wrap gap-2">
          <span v-for="item in typeCounts" :key="item.value">{{ item.shortLabel }} {{ item.count }}</span>
          <span v-if="status?.persist_path" class="max-w-72 truncate">路径 {{ status.persist_path }}</span>
        </div>
      </div>
    </div>

    <div class="grid gap-3 lg:grid-cols-[1fr_auto]">
      <div class="relative">
        <Input
          v-model="query"
          class="h-11 pl-10"
          placeholder="搜索规则、素材或项目片段，例如：追妻火葬场、身份反转、前三秒钩子"
          @keyup.enter="runSearch"
        />
        <Search class="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
      </div>
      <Button class="h-11 gap-2" :disabled="!canSearch" @click="runSearch">
        <Loader2 v-if="isLoading" class="h-4 w-4 animate-spin" />
        <Search v-else class="h-4 w-4" />
        查询
      </Button>
    </div>

    <div class="mt-3 flex flex-col gap-3 xl:flex-row xl:items-center xl:justify-between">
      <div class="flex flex-wrap gap-1.5">
        <button
          v-for="option in modeOptions"
          :key="option.value"
          type="button"
          class="inline-flex h-8 items-center gap-1.5 rounded-lg border px-3 text-sm transition-colors"
          :class="mode === option.value
            ? 'border-primary bg-primary text-primary-foreground'
            : 'border-border bg-background text-muted-foreground hover:border-primary/50 hover:text-foreground'"
          @click="mode = option.value"
        >
          <component :is="option.icon" class="h-3.5 w-3.5" />
          {{ option.label }}
        </button>
      </div>

      <div class="flex flex-wrap items-center gap-1.5">
        <span class="mr-1 text-xs text-muted-foreground">类型筛选</span>
        <button
          v-for="option in knowledgeTypeOptions"
          :key="option.value"
          type="button"
          class="h-8 rounded-lg border px-3 text-sm transition-colors"
          :class="selectedTypes.includes(option.value)
            ? 'border-primary/70 bg-primary/10 text-primary'
            : 'border-border bg-background text-muted-foreground hover:text-foreground'"
          @click="toggleType(option.value)"
        >
          {{ option.label }}
        </button>
        <Button variant="outline" size="sm" class="ml-1 h-8 gap-1.5" :disabled="isStatusLoading" @click="loadStatus">
          <RefreshCw class="h-3.5 w-3.5" :class="{ 'animate-spin': isStatusLoading }" />
          状态
        </Button>
      </div>
    </div>

    <div v-if="responseMeta" class="mt-4 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
      <Badge variant="secondary">后端 {{ responseMeta.backend }}</Badge>
      <Badge variant="outline">命中 {{ responseMeta.count }}</Badge>
      <Badge variant="outline">索引 {{ responseMeta.indexed_count }}</Badge>
      <Badge v-if="responseMeta.rebuilt" variant="outline">已自动刷新索引</Badge>
      <Badge v-if="responseMeta.semantic_degraded" variant="outline" class="border-amber-400 text-amber-600 dark:text-amber-300">
        语义降级
      </Badge>
      <span v-if="responseMeta.semantic_error" class="text-amber-600 dark:text-amber-300">
        降级提示：{{ responseMeta.semantic_error }}
      </span>
    </div>

    <div v-if="errorMessage" class="mt-4 flex items-start gap-2 rounded-lg border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive">
      <AlertCircle class="mt-0.5 h-4 w-4 shrink-0" />
      <span>{{ errorMessage }}</span>
    </div>

    <div v-if="results.length" class="mt-4 grid gap-3">
      <article
        v-for="item in results"
        :key="`${item.doc_type}:${item.source_id}`"
        class="rounded-lg border bg-background p-4 transition-colors hover:border-primary/40"
      >
        <div class="mb-2 flex flex-wrap items-start justify-between gap-2">
          <div class="min-w-0">
            <div class="flex flex-wrap items-center gap-2">
              <Badge variant="secondary">{{ docTypeLabel(item.doc_type) }}</Badge>
              <h3 class="font-semibold leading-snug">{{ item.title || item.title_snippet || item.source_id }}</h3>
            </div>
            <p class="mt-1 break-all text-xs text-muted-foreground">来源路径：{{ sourcePathFor(item) }}</p>
          </div>
          <div class="flex shrink-0 items-center gap-1.5 text-xs text-muted-foreground">
            <Badge variant="outline">{{ item.backend }}</Badge>
            <span v-if="scoreLabel(item.score)">score {{ scoreLabel(item.score) }}</span>
          </div>
        </div>
        <p class="text-sm leading-6 text-muted-foreground">{{ item.content_snippet || item.title_snippet || '该结果暂无片段。' }}</p>
      </article>
    </div>

    <div
      v-else-if="!isLoading && !errorMessage"
      class="mt-4 rounded-lg border border-dashed bg-muted/20 px-4 py-6 text-center text-sm text-muted-foreground"
    >
      {{ emptyMessage }}
    </div>

    <div v-if="isLoading && !results.length" class="mt-4 rounded-lg border bg-muted/20 px-4 py-6 text-center text-sm text-muted-foreground">
      <Loader2 class="mx-auto mb-2 h-5 w-5 animate-spin text-primary" />
      正在检索知识库…
    </div>

    <div v-if="hasSearched" class="mt-3 text-xs text-muted-foreground">
      当前模式：{{ mode === 'semantic' ? '语义检索' : '全文检索' }} · 当前筛选：{{ selectedTypes.map((type) => docTypeLabel(type)).join(' / ') }}
    </div>
  </section>
</template>
