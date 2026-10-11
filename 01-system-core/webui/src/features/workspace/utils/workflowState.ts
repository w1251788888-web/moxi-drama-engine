// 工作区状态相关的纯函数（不依赖 Vue refs）。
// 从 ProjectWorkspaceView.vue 抽出。

export type StoryStateCardKind = 'relationship' | 'info' | 'power' | 'promise' | 'locked_fact'

export interface StoryStateCard {
  id: string
  title: string
  summary: string
  state: string
  related_character_ids: string[]
}

export interface StoryStateCardStore {
  relationship_cards: StoryStateCard[]
  info_cards: StoryStateCard[]
  power_cards: StoryStateCard[]
  promise_cards: StoryStateCard[]
  locked_fact_cards: StoryStateCard[]
}

export interface WorkflowContext {
  materials: Array<Record<string, any>>
  issue_feedback: Record<string, any>
  rule_profile: string
  world_rules: string
  golden_finger_rules: string
  conflict_plan: string
  quality_report: Record<string, any>
  compliance_report: Record<string, any>
  episode_novel_anchor: string
  rag_context: Record<string, any>
  series_simulation_packet: Record<string, any>
  rag_context_cards: Array<Record<string, any>>
  rag_evidence_log: Array<Record<string, any>>
  chat_brainstorm: Record<string, any>
  outline_state: Record<string, any>
  director_blueprint: Record<string, any>
  director_blueprints: Record<string, any>
  director_generation_trace: Record<string, any>
  script_segment_progress: Record<string, any>
  script_generation_failure_log: Array<Record<string, any>>
  manual_edit_context: Record<string, any>
  final_generation_contract: Record<string, any>
  core_generation_contract_hash: string
  rag_evidence_hash: string
  final_generation_contract_hash: string
  step_confirmation_overrides: Record<string, any>
  existing_script_opt_out: Record<string, any>
}

export function clonePlain<T>(value: T): T {
  return JSON.parse(JSON.stringify(value ?? null)) as T
}

export function emptyStoryStateCards(): StoryStateCardStore {
  return {
    relationship_cards: [],
    info_cards: [],
    power_cards: [],
    promise_cards: [],
    locked_fact_cards: [],
  }
}

export function normalizeStoryStateCards(raw?: any): StoryStateCardStore {
  const base = emptyStoryStateCards()
  if (!raw || typeof raw !== 'object') return base
  const normalizeList = (value: any): StoryStateCard[] => Array.isArray(value)
    ? value.map((item: any) => ({
        id: String(item?.id || Date.now() + Math.random()),
        title: String(item?.title || item?.label || '').trim(),
        summary: String(item?.summary || item?.description || '').trim(),
        state: String(item?.state || item?.status || '').trim(),
        related_character_ids: Array.isArray(item?.related_character_ids)
          ? item.related_character_ids.map((v: any) => String(v))
          : Array.isArray(item?.character_ids)
            ? item.character_ids.map((v: any) => String(v))
            : [],
      }))
    : []
  return {
    relationship_cards: normalizeList(raw.relationship_cards),
    info_cards: normalizeList(raw.info_cards),
    power_cards: normalizeList(raw.power_cards),
    promise_cards: normalizeList(raw.promise_cards),
    locked_fact_cards: normalizeList(raw.locked_fact_cards),
  }
}

export function emptyWorkflowContext(): WorkflowContext {
  return {
    materials: [],
    issue_feedback: {},
    rule_profile: '',
    world_rules: '',
    golden_finger_rules: '',
    conflict_plan: '',
    quality_report: {},
    compliance_report: {},
    episode_novel_anchor: '',
    rag_context: {},
    series_simulation_packet: {},
    rag_context_cards: [],
    rag_evidence_log: [],
    chat_brainstorm: {},
    outline_state: {},
    director_blueprint: {},
    director_blueprints: {},
    director_generation_trace: {},
    script_segment_progress: {},
    script_generation_failure_log: [],
    manual_edit_context: {},
    final_generation_contract: {},
    core_generation_contract_hash: '',
    rag_evidence_hash: '',
    final_generation_contract_hash: '',
    step_confirmation_overrides: {},
    existing_script_opt_out: {},
  }
}

export function normalizeWorkflowContext(raw?: any): WorkflowContext {
  const base = emptyWorkflowContext()
  if (!raw || typeof raw !== 'object') return base
  return {
    materials: Array.isArray(raw.materials) ? raw.materials : base.materials,
    issue_feedback: raw.issue_feedback && typeof raw.issue_feedback === 'object' ? raw.issue_feedback : base.issue_feedback,
    rule_profile: String(raw.rule_profile || '').trim(),
    world_rules: String(raw.world_rules || '').trim(),
    golden_finger_rules: String(raw.golden_finger_rules || '').trim(),
    conflict_plan: String(raw.conflict_plan || '').trim(),
    quality_report: raw.quality_report && typeof raw.quality_report === 'object' ? raw.quality_report : base.quality_report,
    compliance_report: raw.compliance_report && typeof raw.compliance_report === 'object' ? raw.compliance_report : base.compliance_report,
    episode_novel_anchor: String(raw.episode_novel_anchor || '').trim(),
    rag_context: raw.rag_context && typeof raw.rag_context === 'object' ? raw.rag_context : base.rag_context,
    series_simulation_packet: raw.series_simulation_packet && typeof raw.series_simulation_packet === 'object' ? raw.series_simulation_packet : base.series_simulation_packet,
    rag_context_cards: Array.isArray(raw.rag_context_cards) ? raw.rag_context_cards : base.rag_context_cards,
    rag_evidence_log: Array.isArray(raw.rag_evidence_log) ? raw.rag_evidence_log : base.rag_evidence_log,
    chat_brainstorm: raw.chat_brainstorm && typeof raw.chat_brainstorm === 'object' ? raw.chat_brainstorm : base.chat_brainstorm,
    outline_state: raw.outline_state && typeof raw.outline_state === 'object' ? raw.outline_state : base.outline_state,
    director_blueprint: raw.director_blueprint && typeof raw.director_blueprint === 'object' ? raw.director_blueprint : base.director_blueprint,
    director_blueprints: raw.director_blueprints && typeof raw.director_blueprints === 'object' ? raw.director_blueprints : base.director_blueprints,
    director_generation_trace: raw.director_generation_trace && typeof raw.director_generation_trace === 'object' ? raw.director_generation_trace : base.director_generation_trace,
    script_segment_progress: raw.script_segment_progress && typeof raw.script_segment_progress === 'object' ? raw.script_segment_progress : base.script_segment_progress,
    script_generation_failure_log: Array.isArray(raw.script_generation_failure_log) ? raw.script_generation_failure_log : base.script_generation_failure_log,
    manual_edit_context: raw.manual_edit_context && typeof raw.manual_edit_context === 'object' ? raw.manual_edit_context : base.manual_edit_context,
    final_generation_contract: raw.final_generation_contract && typeof raw.final_generation_contract === 'object' ? raw.final_generation_contract : base.final_generation_contract,
    core_generation_contract_hash: String(raw.core_generation_contract_hash || '').trim(),
    rag_evidence_hash: String(raw.rag_evidence_hash || '').trim(),
    final_generation_contract_hash: String(raw.final_generation_contract_hash || '').trim(),
    step_confirmation_overrides: raw.step_confirmation_overrides && typeof raw.step_confirmation_overrides === 'object' ? raw.step_confirmation_overrides : base.step_confirmation_overrides,
    existing_script_opt_out: raw.existing_script_opt_out && typeof raw.existing_script_opt_out === 'object' ? raw.existing_script_opt_out : base.existing_script_opt_out,
  }
}

export function simpleHash(text: string): string {
  let hash = 2166136261
  for (let i = 0; i < text.length; i += 1) {
    hash ^= text.charCodeAt(i)
    hash = Math.imul(hash, 16777619)
  }
  return (hash >>> 0).toString(16)
}

export const SCRIPT_CACHE_MAX = 18
export const RAG_EVIDENCE_LOG_MAX = 24

const MANUAL_EDIT_CANON_READY_STATUSES = new Set([
  'canon_synced',
  'passed',
  'next_generation_consumed',
])

const MANUAL_EDIT_GATE_READY_STATUSES = new Set([
  'canon_synced',
  'passed',
  'next_generation_consumed',
])

function _manualEditLogs(manualEditContext?: Record<string, any>): Array<Record<string, any>> {
  const raw = manualEditContext && typeof manualEditContext === 'object' && !Array.isArray(manualEditContext)
    ? manualEditContext
    : {}
  const logs = Array.isArray(raw.logs) ? raw.logs.filter((item: any) => item && typeof item === 'object') : []
  if (logs.length > 0) return logs
  const latest = raw.latest && typeof raw.latest === 'object' && !Array.isArray(raw.latest) ? raw.latest : null
  return latest ? [latest] : []
}

function _targetsNextEpisode(log: Record<string, any>, targetEpisodeNo: number) {
  const target = Math.max(1, Math.round(Number(targetEpisodeNo || 1) || 1))
  const delta = log.manual_edit_delta && typeof log.manual_edit_delta === 'object' ? log.manual_edit_delta : {}
  const gate = log.next_episode_context_sync_gate && typeof log.next_episode_context_sync_gate === 'object'
    ? log.next_episode_context_sync_gate
    : {}
  const nextEpisode = Math.round(Number(gate.next_episode_no || 0) || 0)
  const sourceEpisode = Math.round(Number(delta.episode_no || log.episode_no || 0) || 0)
  return Boolean(gate.must_read_manual_edit)
    && (nextEpisode === target || (!nextEpisode && sourceEpisode === target - 1))
}

export function findBlockingManualEditSyncGate(manualEditContext: Record<string, any> | undefined, targetEpisodeNo: number) {
  const relevantLogs = _manualEditLogs(manualEditContext).filter(log => _targetsNextEpisode(log, targetEpisodeNo))
  const blockingLogs = relevantLogs.filter((log) => {
    const delta = log.manual_edit_delta && typeof log.manual_edit_delta === 'object' ? log.manual_edit_delta : {}
    const patch = log.canon_patch && typeof log.canon_patch === 'object' ? log.canon_patch : {}
    const gate = log.next_episode_context_sync_gate && typeof log.next_episode_context_sync_gate === 'object'
      ? log.next_episode_context_sync_gate
      : {}
    const patchStatus = String(patch.status || '').trim()
    const gateStatus = String(gate.status || '').trim()
    const userFinalHash = String(delta.current_content_hash || gate.previous_episode_user_final_hash || '').trim()
    return !userFinalHash
      || !MANUAL_EDIT_CANON_READY_STATUSES.has(patchStatus)
      || !MANUAL_EDIT_GATE_READY_STATUSES.has(gateStatus)
  })

  if (blockingLogs.length > 0) {
    return {
      blocked: true,
      message: '上一集用户改稿还没有同步成正史，暂时不能生成下一集。请先保存上一集，等系统显示已锁定为正史后再继续。',
      relevantLogs,
      blockingLogs,
    }
  }
  return {
    blocked: false,
    message: '',
    relevantLogs,
    blockingLogs: [],
  }
}

export function markManualEditGateConsumed(
  manualEditContext: Record<string, any> | undefined,
  targetEpisodeNo: number,
  options?: {
    generated_content_hash?: string
    generated_at?: string
  },
) {
  const raw = manualEditContext && typeof manualEditContext === 'object' && !Array.isArray(manualEditContext)
    ? clonePlain(manualEditContext)
    : {}
  const logs = _manualEditLogs(raw)
  if (logs.length === 0) return raw

  const generatedAt = String(options?.generated_at || new Date().toISOString())
  const generatedHash = String(options?.generated_content_hash || '').trim()
  const nextLogs = logs.map((log) => {
    if (!_targetsNextEpisode(log, targetEpisodeNo)) return log
    const gate = log.next_episode_context_sync_gate && typeof log.next_episode_context_sync_gate === 'object'
      ? log.next_episode_context_sync_gate
      : {}
    return {
      ...log,
      next_episode_context_sync_gate: {
        ...gate,
        status: 'next_generation_consumed',
        consumed_by_episode_no: Math.max(1, Math.round(Number(targetEpisodeNo || 1) || 1)),
        consumed_at: generatedAt,
        generated_content_hash: generatedHash,
      },
    }
  })

  return {
    ...raw,
    logs: nextLogs,
    latest: nextLogs[0] || raw.latest || null,
  }
}

export function setBoundedCache<T>(cache: Map<string, T>, key: string, value: T, max: number = SCRIPT_CACHE_MAX): void {
  if (cache.has(key)) cache.delete(key)
  cache.set(key, clonePlain(value))
  while (cache.size > max) {
    const oldest = cache.keys().next().value
    if (!oldest) break
    cache.delete(oldest)
  }
}

export function buildWorkflowAuditPatch(audit?: any) {
  const benchmark = audit?.benchmark_assessment || {}
  const continuity = audit?.continuity_assessment || {}
  const gaps = Array.isArray(benchmark.gaps) ? benchmark.gaps.map((item: any) => String(item || '').trim()).filter(Boolean) : []
  const upgrades = Array.isArray(benchmark.rule_upgrades) ? benchmark.rule_upgrades.map((item: any) => String(item || '').trim()).filter(Boolean) : []
  const continuityRisks = [
    ...(Array.isArray(continuity.relationship_risks) ? continuity.relationship_risks : []),
    ...(Array.isArray(continuity.plot_risks) ? continuity.plot_risks : []),
  ].map((item: any) => String(item || '').trim()).filter(Boolean)
  return {
    quality_report: {
      summary: String(benchmark.summary || '').trim(),
      focus: gaps.slice(0, 4).join('；'),
      next_fix: upgrades.slice(0, 4).join('；'),
    },
    compliance_report: {
      summary: String(continuity.summary || '').trim(),
      risks: continuityRisks.slice(0, 6),
    },
  }
}

export function buildValidationCacheKey(kind: 'validate' | 'audit', payload: Record<string, any>): string {
  const digest = simpleHash(JSON.stringify({
    project_id: String(payload.project_id || ''),
    episode_no: Number(payload.episode_no || 0),
    scene_no: Number(payload.scene_no || 0),
    mode: String(payload.mode || 'scene'),
    segment_id: String(payload.segment_id || ''),
    scene_content: String(payload.scene_content || '').slice(0, 6000),
    current_content: String(payload.current_content || '').slice(0, 3000),
    episode_content: String(payload.episode_content || '').slice(0, 6000),
    continuity_notes: String(payload.continuity_notes || '').slice(0, 800),
    word_count_target: Number(payload.word_count_target || 0),
    word_count_min: Number(payload.word_count_min || 0),
    word_count_max: Number(payload.word_count_max || 0),
    selected_character_ids: Array.isArray(payload.selected_character_ids) ? payload.selected_character_ids : [],
    characters: Array.isArray(payload.characters)
      ? payload.characters.map((item: any) => ({
          id: String(item?.id || ''),
          name: String(item?.name || ''),
          age: String(item?.age || ''),
          personality: String(item?.personality || ''),
          traits: String(item?.traits || ''),
          relationships: Array.isArray(item?.relationships)
            ? item.relationships.map((rel: any) => ({
                targetId: String(rel?.targetId || rel?.target_id || ''),
                type: String(rel?.type || ''),
                strength: Number(rel?.strength || 0),
              }))
            : [],
        }))
      : [],
    state_cards: payload.state_cards || {},
    previous_episode_briefs: payload.previous_episode_briefs || [],
    future_episode_briefs: payload.future_episode_briefs || [],
    previous_relationship_snapshot: payload.previous_relationship_snapshot || [],
    episode_memory_cards: payload.episode_memory_cards || [],
    canon_packet: payload.canon_packet || {},
    director_blueprint: payload.director_blueprint || {},
    director_generation_trace: payload.director_generation_trace || {},
    series_simulation_packet: payload.series_simulation_packet || {},
    episode_contract: payload.episode_contract || {},
    issue_feedback: payload.issue_feedback || {},
    quality_report: payload.quality_report || {},
    compliance_report: payload.compliance_report || {},
  }))
  return `${kind}:${digest}`
}
