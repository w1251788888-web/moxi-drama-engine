import { computed, ref } from 'vue'
import {
  advancedGenerationApi,
  cacheApi,
  collaborationApi,
  searchApi,
  type AdvancedGenerationOrchestrationPlanResponse,
  type AdvancedGenerationOrchestrationStatusResponse,
  type CacheStatusResponse,
  type SearchStatusResponse,
  type YjsPlanResponse,
  type YjsStatusResponse,
} from '@/api/client'

type CapabilityState = 'ready' | 'degraded' | 'offline' | 'unknown'

export interface AdvancedCapabilityItem {
  id: string
  label: string
  family: string
  state: CapabilityState
  backend: string
  headline: string
  details: string[]
  metrics: Array<{ label: string; value: string }>
}

function capabilityState(available?: boolean, degraded?: boolean): CapabilityState {
  if (available === undefined) {
    return 'unknown'
  }
  if (degraded) {
    return 'degraded'
  }
  return available ? 'ready' : 'offline'
}

function countLabel(value: number | undefined) {
  return String(value ?? 0)
}

function versionLabel(value: string | undefined) {
  return value?.trim() || '未检测'
}

function errorDetail(error: string | undefined) {
  return error ? `降级原因：${error}` : ''
}

export function useAdvancedGenerationCapabilities() {
  const orchestrationStatus = ref<AdvancedGenerationOrchestrationStatusResponse | null>(null)
  const orchestrationPlan = ref<AdvancedGenerationOrchestrationPlanResponse | null>(null)
  const yjsStatus = ref<YjsStatusResponse | null>(null)
  const yjsPlan = ref<YjsPlanResponse | null>(null)
  const ftsStatus = ref<SearchStatusResponse | null>(null)
  const semanticStatus = ref<SearchStatusResponse | null>(null)
  const cacheStatus = ref<CacheStatusResponse | null>(null)
  const isLoading = ref(false)
  const loadError = ref('')

  const capabilities = computed<AdvancedCapabilityItem[]>(() => {
    const orchestration = orchestrationStatus.value
    const plan = orchestrationPlan.value
    const yjs = yjsStatus.value
    const yjsPlanValue = yjsPlan.value
    const fts = ftsStatus.value
    const semantic = semanticStatus.value
    const cache = cacheStatus.value

    return [
      {
        id: 'langgraph',
        label: 'LangGraph 编排',
        family: '生成工作流',
        state: capabilityState(orchestration?.available, orchestration?.degraded),
        backend: orchestration?.backend || 'pending',
        headline: plan?.workflow_label || orchestration?.workflow_label || 'writer-reviewer-decision',
        details: [
          `入口：${plan?.entrypoint || 'writer'}`,
          `节点：${countLabel(plan?.nodes.length)} 个，边：${countLabel(plan?.edges.length)} 条`,
          errorDetail(orchestration?.error || plan?.error),
        ].filter(Boolean),
        metrics: [
          { label: 'LangChain', value: versionLabel(orchestration?.langchain_version) },
          { label: 'LangGraph', value: versionLabel(orchestration?.langgraph_version) },
          { label: '评审轮次', value: countLabel(plan?.max_review_rounds) },
        ],
      },
      {
        id: 'yjs',
        label: 'Yjs 协作',
        family: '多人编辑',
        state: capabilityState(yjs?.available, yjs?.degraded),
        backend: yjs?.backend || 'pending',
        headline: yjsPlanValue?.entrypoint || yjs?.feature_label || '实时协作计划',
        details: [
          `传输：${yjs?.transport || 'REST fallback'}`,
          `文档：${countLabel(yjsPlanValue?.documents.length)} 类同步对象`,
          yjs?.missing_dependencies.length ? `缺少依赖：${yjs.missing_dependencies.join(', ')}` : '',
          errorDetail(yjs?.error),
        ].filter(Boolean),
        metrics: [
          { label: 'Presence', value: yjs?.available && yjsPlanValue?.presence.enabled_when_available ? '可启用' : '回退' },
          { label: '验收门禁', value: countLabel(yjsPlanValue?.acceptance_gates.length) },
          { label: '依赖', value: countLabel(Object.keys(yjs?.dependencies ?? {}).length) },
        ],
      },
      {
        id: 'fts5',
        label: 'FTS5 全文检索',
        family: '知识召回',
        state: capabilityState(fts?.available, fts?.degraded),
        backend: fts?.backend || 'pending',
        headline: '规则、素材、项目文本索引',
        details: [
          `索引文档：${countLabel(fts?.indexed_count)} 条`,
          `类型覆盖：${Object.keys(fts?.doc_type_counts ?? {}).join(' / ') || '等待索引'}`,
          errorDetail(fts?.error),
        ].filter(Boolean),
        metrics: [
          { label: 'Rules', value: countLabel(fts?.doc_type_counts?.rule) },
          { label: 'Materials', value: countLabel(fts?.doc_type_counts?.material) },
          { label: 'Projects', value: countLabel(fts?.doc_type_counts?.project) },
        ],
      },
      {
        id: 'chroma',
        label: 'Chroma 语义检索',
        family: '向量召回',
        state: capabilityState(semantic?.available, semantic?.degraded),
        backend: semantic?.backend || 'pending',
        headline: semantic?.collection || 'semantic_documents',
        details: [
          `索引文档：${countLabel(semantic?.indexed_count)} 条`,
          semantic?.persist_path ? `持久化：${semantic.persist_path}` : '不可用时自动回退 FTS5',
          errorDetail(semantic?.error),
        ].filter(Boolean),
        metrics: [
          { label: '后端', value: semantic?.backend || 'pending' },
          { label: '降级', value: semantic?.degraded ? '是' : '否' },
          { label: '集合', value: semantic?.collection || '默认' },
        ],
      },
      {
        id: 'redis',
        label: 'Redis 缓存',
        family: '响应加速',
        state: cache ? capabilityState(cache.redis_available || !cache.redis_configured, cache.degraded) : 'unknown',
        backend: cache?.backend || 'pending',
        headline: cache?.redis_configured ? 'Redis 外部缓存' : '内存缓存回退',
        details: [
          cache?.redis_configured ? '已配置 Redis URL' : '未配置 Redis，使用进程内缓存',
          `内存键：${countLabel(cache?.memory_keys)}`,
          errorDetail(cache?.redis_error),
        ].filter(Boolean),
        metrics: [
          { label: 'Redis', value: cache?.redis_available ? '可用' : '未连接' },
          { label: 'Backend', value: cache?.backend || 'pending' },
          { label: 'Degraded', value: cache?.degraded ? '是' : '否' },
        ],
      },
    ]
  })

  const readyCount = computed(() => capabilities.value.filter((item) => item.state === 'ready').length)
  const degradedCount = computed(() => capabilities.value.filter((item) => item.state === 'degraded').length)

  async function loadCapabilities() {
    isLoading.value = true
    loadError.value = ''

    const results = await Promise.allSettled([
      advancedGenerationApi.getOrchestrationStatus(),
      advancedGenerationApi.getOrchestrationPlan({
        metadata: { project: { config: { advanced_generation_mode: true } } },
        base_generation_kwargs: { provider: 'default', model: 'default' },
        max_review_rounds: 2,
      }),
      collaborationApi.yjsStatus(),
      collaborationApi.yjsPlan(),
      searchApi.status(),
      searchApi.semanticStatus(),
      cacheApi.status(),
    ])

    const [
      orchestrationStatusResult,
      orchestrationPlanResult,
      yjsStatusResult,
      yjsPlanResult,
      ftsStatusResult,
      semanticStatusResult,
      cacheStatusResult,
    ] = results

    if (orchestrationStatusResult.status === 'fulfilled') orchestrationStatus.value = orchestrationStatusResult.value.data
    if (orchestrationPlanResult.status === 'fulfilled') orchestrationPlan.value = orchestrationPlanResult.value.data
    if (yjsStatusResult.status === 'fulfilled') yjsStatus.value = yjsStatusResult.value.data
    if (yjsPlanResult.status === 'fulfilled') yjsPlan.value = yjsPlanResult.value.data
    if (ftsStatusResult.status === 'fulfilled') ftsStatus.value = ftsStatusResult.value.data
    if (semanticStatusResult.status === 'fulfilled') semanticStatus.value = semanticStatusResult.value.data
    if (cacheStatusResult.status === 'fulfilled') cacheStatus.value = cacheStatusResult.value.data

    const failedCount = results.filter((result) => result.status === 'rejected').length
    if (failedCount === results.length) {
      loadError.value = '高级能力状态读取失败'
    } else if (failedCount > 0) {
      loadError.value = `${failedCount} 个能力状态暂时无法读取`
    }

    isLoading.value = false
  }

  return {
    capabilities,
    degradedCount,
    isLoading,
    loadCapabilities,
    loadError,
    orchestrationPlan,
    orchestrationStatus,
    readyCount,
    yjsPlan,
    yjsStatus,
  }
}
