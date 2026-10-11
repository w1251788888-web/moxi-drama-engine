import { computed, ref } from 'vue'
import { searchApi, type SearchResponse, type SearchResultItem, type SearchStatusResponse } from '@/api/client'
import { formatUserFacingErrorMessage } from '@/api/http'

export type KnowledgeSearchMode = 'fulltext' | 'semantic'
export type KnowledgeDocType = 'rule' | 'material' | 'project' | 'skill'

export interface KnowledgeTypeOption {
  value: KnowledgeDocType
  label: string
  shortLabel: string
}

export const knowledgeTypeOptions: KnowledgeTypeOption[] = [
  { value: 'rule', label: '规则 rule', shortLabel: '规则' },
  { value: 'material', label: '素材 material', shortLabel: '素材' },
  { value: 'project', label: '项目 project', shortLabel: '项目' },
  { value: 'skill', label: '技能 skill', shortLabel: '技能' },
]

const DEFAULT_LIMIT = 8

function extractErrorMessage(error: unknown) {
  return formatUserFacingErrorMessage(error, '检索失败')
}

function normalizeMetadataPath(item: SearchResultItem) {
  const metadata = item.metadata || {}
  const path = metadata.path || metadata.source_path || metadata.file_path || metadata.relative_path
  return typeof path === 'string' && path.trim() ? path : item.source_id
}

export function useKnowledgeSearch() {
  const query = ref('')
  const mode = ref<KnowledgeSearchMode>('semantic')
  const selectedTypes = ref<KnowledgeDocType[]>(['rule', 'material', 'skill'])
  const status = ref<SearchStatusResponse | null>(null)
  const results = ref<SearchResultItem[]>([])
  const responseMeta = ref<Pick<SearchResponse, 'backend' | 'count' | 'indexed_count' | 'rebuilt' | 'semantic_degraded' | 'semantic_error'> | null>(null)
  const isLoading = ref(false)
  const isStatusLoading = ref(false)
  const errorMessage = ref('')
  const statusError = ref('')
  const hasSearched = ref(false)

  const selectedTypeLabels = computed(() => (
    knowledgeTypeOptions
      .filter((option) => selectedTypes.value.includes(option.value))
      .map((option) => option.shortLabel)
  ))

  const statusSummary = computed(() => {
    if (!status.value) return '索引状态未读取'
    const backend = status.value.backend || 'unknown'
    const count = status.value.indexed_count ?? 0
    const degraded = status.value.degraded ? '，当前降级' : ''
    return `${backend} · 已索引 ${count} 条${degraded}`
  })

  const typeCounts = computed(() => {
    const counts = status.value?.doc_type_counts ?? {}
    return knowledgeTypeOptions.map((option) => ({
      ...option,
      count: counts[option.value] ?? 0,
    }))
  })

  const emptyMessage = computed(() => {
    if (!hasSearched.value) return '输入关键词后，可以从规则、素材和项目库里召回可复用片段。'
    if (!query.value.trim()) return '请输入要检索的关键词。'
    return '没有找到匹配内容，可以放宽类型筛选或换一个关键词。'
  })

  const canSearch = computed(() => query.value.trim().length > 0 && selectedTypes.value.length > 0 && !isLoading.value)

  function toggleType(type: KnowledgeDocType) {
    if (selectedTypes.value.includes(type)) {
      if (selectedTypes.value.length === 1) return
      selectedTypes.value = selectedTypes.value.filter((item) => item !== type)
      return
    }
    selectedTypes.value = [...selectedTypes.value, type]
  }

  function sourcePathFor(item: SearchResultItem) {
    return normalizeMetadataPath(item)
  }

  async function loadStatus() {
    isStatusLoading.value = true
    statusError.value = ''
    try {
      const { data } = await searchApi.status()
      status.value = data
    } catch (error) {
      statusError.value = extractErrorMessage(error)
    } finally {
      isStatusLoading.value = false
    }
  }

  async function runSearch() {
    const normalizedQuery = query.value.trim()
    hasSearched.value = true
    errorMessage.value = ''
    responseMeta.value = null

    if (!normalizedQuery) {
      results.value = []
      return
    }

    isLoading.value = true
    try {
      const params = {
        q: normalizedQuery,
        types: selectedTypes.value,
        limit: DEFAULT_LIMIT,
        auto_rebuild: true,
      }
      const { data } = mode.value === 'semantic'
        ? await searchApi.semanticSearch(params)
        : await searchApi.search(params)

      results.value = data.items
      responseMeta.value = {
        backend: data.backend,
        count: data.count,
        indexed_count: data.indexed_count,
        rebuilt: data.rebuilt,
        semantic_degraded: data.semantic_degraded,
        semantic_error: data.semantic_error,
      }
    } catch (error) {
      results.value = []
      errorMessage.value = extractErrorMessage(error)
    } finally {
      isLoading.value = false
    }
  }

  return {
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
    selectedTypeLabels,
    selectedTypes,
    sourcePathFor,
    status,
    statusError,
    statusSummary,
    toggleType,
    typeCounts,
  }
}
