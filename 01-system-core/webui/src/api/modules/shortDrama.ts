import api from '../http'
export {
  advancedGenerationApi,
  type AdvancedGenerationArtifact,
  type AdvancedGenerationProfile,
  type AdvancedGenerationProfileListResponse,
  type AdvancedGenerationStep,
} from './advancedGeneration'

// ── 写作工作台（短剧写作会话） ──

export type ShortDramaStepId =
  | 'project_init_check'
  | 'novel_analysis'
  | 'character_lock'
  | 'market_check'
  | 'concept'
  | 'characters'
  | 'beat_sheet'
  | 'scene_list'
  | 'script_draft'
  | 'quality_check'
  | 'compliance_check'
  | 'storyboard'

export interface StartupChecklistItem {
  key: string
  label: string
  done: boolean
  hint?: string
}

export interface StartupContextResponse {
  materials: Array<Record<string, unknown>>
  recommended_materials: Array<Record<string, unknown>>
  issue_feedback: Record<string, unknown>
  startup_checklist: StartupChecklistItem[]
}

export interface ShortDramaSessionMetadata {
  kind?: string
  project?: Record<string, unknown>
  inputs?: Record<string, unknown>
  materials?: Array<Record<string, unknown>>
  issue_feedback?: Record<string, unknown>
  startup_checklist?: StartupChecklistItem[]
  steps?: Record<string, unknown>
  exports?: Array<Record<string, unknown>>
  created_at?: string
  updated_at?: string
  [key: string]: unknown
}

export interface ShortDramaSessionItem {
  id: string
  name: string
  description: string
  status: string
  created_at: string | null
  updated_at: string | null
  metadata: ShortDramaSessionMetadata
}

export interface ShortDramaStepResult {
  step_id: ShortDramaStepId
  context_output: string
  full_output: string
  updated_at: string
  manual_override: boolean
  gate_warning?: string
  quality_verdict?: string
  repair_scope?: string
  revision_summary?: string
  rag_evidence?: Array<Record<string, unknown>>
}

export const shortDramaStudioApi = {
  createSession: (data: {
    name: string
    description?: string
    project?: Record<string, unknown>
    inputs?: Record<string, unknown>
  }) => api.post<ShortDramaSessionItem>('/admin/short-drama/sessions', data),

  listSessions: (params?: { limit?: number }) =>
    api.get<ShortDramaSessionItem[]>('/admin/short-drama/sessions', { params }),

  getSession: (id: string) => api.get<ShortDramaSessionItem>(`/admin/short-drama/sessions/${id}`),

  getStartupContext: (id: string) => api.get<StartupContextResponse>(`/admin/short-drama/sessions/${id}/startup-context`),

  recommendMaterials: (id: string) => api.post<{ materials: Array<Record<string, unknown>>; count: number }>(`/admin/short-drama/sessions/${id}/materials/recommend`),

  selectMaterials: (id: string, material_ids: string[]) =>
    api.post<{ materials: Array<Record<string, unknown>>; count: number }>(`/admin/short-drama/sessions/${id}/materials/select`, { material_ids }),

  refreshIssueFeedback: (id: string, category_path?: string) =>
    api.post<{ issue_feedback: Record<string, unknown>; startup_checklist: StartupChecklistItem[] }>(`/admin/short-drama/sessions/${id}/issue-feedback/refresh`, { category_path }),

  updateSession: (id: string, data: { metadata?: Record<string, unknown>; patch?: Record<string, unknown> }) =>
    api.put<ShortDramaSessionItem>(`/admin/short-drama/sessions/${id}`, data),

  // run-step 内部含 LLM 调用 + 二次重生 + acceptance 验收，10s 默认会超时
  runStep: (id: string, data: { step_id: ShortDramaStepId; draft_episode?: number; template_vars?: Record<string, unknown>; temperature?: number }) =>
    api.post<ShortDramaStepResult>(`/admin/short-drama/sessions/${id}/run-step`, data, { timeout: 180_000 }),

  /** 流式生成（SSE）— 推荐使用 composables/useRunStepStream.ts 替代直接调用 */
  runStepStreamUrl: (id: string, params: { step_id: ShortDramaStepId; draft_episode?: number; temperature?: number }) => {
    const qs = new URLSearchParams({ step_id: params.step_id })
    if (params.draft_episode != null) qs.set('draft_episode', String(params.draft_episode))
    if (params.temperature != null) qs.set('temperature', String(params.temperature))
    return `/api/admin/short-drama/sessions/${id}/run-step-stream?${qs}`
  },

  saveStep: (id: string, data: { step_id: ShortDramaStepId; context_output?: string; full_output?: string; manual_override?: boolean }) =>
    api.post<ShortDramaStepResult>(`/admin/short-drama/sessions/${id}/save-step`, data),

  export: (id: string, data: { format?: 'txt' | 'docx'; episode_no?: number; scope?: 'all_steps' | 'one_episode' }) =>
    api.post<{ path: string }>(`/admin/short-drama/sessions/${id}/export`, data),
}

// ─────────────────────────────────────────────────────────
// 版本管理相关类型和API
// ─────────────────────────────────────────────────────────

export interface StepVersion {
  id: string
  session_id: string
  step_id: ShortDramaStepId
  version_number: string
  parent_version_id: string | null
  content_hash: string
  context_output: string
  full_output: string
  change_type: 'ai_generated' | 'manual_edit' | 'merged' | 'forked'
  change_log: string
  prompt_file: string
  input_summary: string
  is_current: boolean
  created_at: string
  created_by: string
}

export interface StepReview {
  id: string
  version_id: string
  session_id: string
  review_type: 'auto' | 'manual'
  verdict: 'pass' | 'needs_fix' | 'reject'
  score: number | null
  comments: string
  issues: Array<{
    field: string
    issue: string
    suggestion: string
  }>
  rewrite_hint: string
  created_at: string
  reviewed_by: string
}

export interface DynamicRule {
  id: string
  session_id: string | null
  content: string
  scope: 'global' | 'project' | 'step' | 'once'
  target_step: ShortDramaStepId | null
  target_episode: number | null
  apply_timing: 'immediate' | 'next_generation'
  applied_version_ids: string[]
  is_active: boolean
  created_at: string
  created_by: string
}

export interface StepDependencyStatus {
  id: string
  session_id: string
  upstream_step: string
  upstream_version_id: string
  downstream_step: string
  downstream_version_id: string
  dependency_type: 'hard' | 'soft'
  sync_status: 'synced' | 'pending' | 'conflict'
  sync_suggestion: string
  affected_scope: string[]
  created_at: string
  updated_at: string
}

export const stepVersionApi = {
  // 版本管理
  getVersionTree: (sessionId: string, stepId: ShortDramaStepId) =>
    api.get<{ versions: StepVersion[] }>(`/admin/short-drama/sessions/${sessionId}/steps/${stepId}/versions`),

  createVersion: (sessionId: string, stepId: ShortDramaStepId, data: {
    base_version_id?: string
    change_type: 'ai_generated' | 'manual_edit' | 'merged' | 'forked'
    change_log?: string
    context_output?: string
    full_output?: string
    prompt_file?: string
    input_summary?: string
  }) => api.post<{ version: StepVersion }>(`/admin/short-drama/sessions/${sessionId}/steps/${stepId}/versions`, data),

  switchVersion: (sessionId: string, stepId: ShortDramaStepId, versionId: string) =>
    api.put<{ version: StepVersion }>(`/admin/short-drama/sessions/${sessionId}/steps/${stepId}/current-version`, { version_id: versionId }),

  diffVersions: (sessionId: string, stepId: ShortDramaStepId, left: string, right: string) =>
    api.get<{ left: StepVersion; right: StepVersion; diff: any[]; stats: any }>(
      `/admin/short-drama/sessions/${sessionId}/steps/${stepId}/diff?left=${left}&right=${right}`
    ),

  // 依赖管理
  checkDependencies: (sessionId: string) =>
    api.get<{
      dependencies: StepDependencyStatus[]
      summary: { total: number; pending: number; synced: number; conflict: number }
      pending_suggestions: Array<{ upstream: string; downstream: string; suggestion: string }>
    }>(`/admin/short-drama/sessions/${sessionId}/dependency-check`),

  syncDownstream: (sessionId: string, fromStep: ShortDramaStepId, strategy: 'smart' | 'full' | 'manual') =>
    api.post<{ synced_steps: string[]; strategy: string }>(`/admin/short-drama/sessions/${sessionId}/sync-downstream`, {
      from_step: fromStep,
      strategy,
    }),

  // 动态规则
  addDynamicRule: (sessionId: string, data: {
    content: string
    scope: 'global' | 'project' | 'step' | 'once'
    target_step?: ShortDramaStepId
    target_episode?: number
    apply_timing?: 'immediate' | 'next_generation'
  }) => api.post<{ rule: DynamicRule }>(`/admin/short-drama/sessions/${sessionId}/rules`, data),

  getActiveRules: (sessionId: string, stepId?: ShortDramaStepId) =>
    api.get<{ rules: DynamicRule[] }>(`/admin/short-drama/sessions/${sessionId}/rules`, { params: { step_id: stepId } }),

  deactivateRule: (ruleId: string) =>
    api.delete<{ success: boolean }>(`/admin/short-drama/rules/${ruleId}`),

  // 评审循环
  createReview: (sessionId: string, data: {
    version_id: string
    verdict: 'pass' | 'needs_fix' | 'reject'
    comments?: string
    issues?: Array<{ field: string; issue: string; suggestion: string }>
    rewrite_hint?: string
    score?: number
  }) => api.post<{ review: StepReview }>(`/admin/short-drama/sessions/${sessionId}/reviews`, data),

  getVersionReviews: (versionId: string) =>
    api.get<{ reviews: StepReview[] }>(`/admin/short-drama/versions/${versionId}/reviews`),

  getReviewStatus: (versionId: string) =>
    api.get<{ needs_rewrite: boolean; rewrite_hint: string; latest_review: StepReview | null }>(
      `/admin/short-drama/versions/${versionId}/review-status`
    ),

  // 局部重写：调 LLM，需要长超时
  partialRegenerate: (sessionId: string, stepId: ShortDramaStepId, data: {
    base_version_id: string
    target_type: 'character' | 'episode' | 'scene' | 'line'
    target_name: string
    target_field?: string
    prompt: string
  }) => api.post<any>(
    `/admin/short-drama/sessions/${sessionId}/steps/${stepId}/partial-regenerate`,
    data,
    { timeout: 120_000 },
  ),

  // 综合状态
  getWorkflowStatus: (sessionId: string) =>
    api.get<{
      steps: Array<{
        step_id: ShortDramaStepId
        has_content: boolean
        current_version: StepVersion | null
        version_count: number
        versions: StepVersion[]
        needs_rewrite?: boolean
        rewrite_hint?: string
      }>
      dependencies: { total: number; pending: number; items: StepDependencyStatus[] }
      active_rules_count: number
    }>(`/admin/short-drama/sessions/${sessionId}/workflow-status`),
}

// ─────────────────────────────────────────────────────────
// 剧集段落任务拆分相关类型和API
// ─────────────────────────────────────────────────────────

export interface EpisodeSegment {
  id: string
  session_id: string
  step_id: string
  episode_no: number
  segment_type: 'hook' | 'validation' | 'explosion' | 'resolution'
  sequence: number
  content: string
  target_word_count: number
  actual_word_count: number
  status: 'pending' | 'red' | 'green' | 'refactor' | 'done'
  version_id: string | null
  acceptance_criteria: Array<{
    check: string
    min?: number
    max?: number
    required?: boolean
    weight?: number
    keywords?: string[]
  }>
  validation_results: Array<{
    criterion: string
    passed: boolean
    score: number
  }>
  validation_score: number
  refactor_count: number
  max_refactors: number
  can_refactor: boolean
  review_ids: string[]
  created_at: string
  updated_at: string
  completed_at: string | null
}

export interface SegmentReview {
  id: string
  segment_id: string
  session_id: string
  verdict: 'pass' | 'block' | 'request_changes'
  is_blocking: boolean
  comments: string
  issues: Array<{
    field: string
    issue: string
    suggestion: string
  }>
  rewrite_suggestion: string
  score: number | null
  created_at: string
  reviewed_by: string
}

export interface StepGate {
  id: string
  session_id: string
  step_id: string
  status: 'open' | 'passed' | 'failed' | 'bypassed'
  min_score: number
  actual_score: number | null
  check_items: Array<{
    item: string
    required?: boolean
  }>
  check_results: Array<{
    item: string
    passed: boolean
    detail?: string
  }>
  summary: string
  passed_by: string | null
  passed_at: string | null
  created_at: string
  updated_at: string
}

export const episodeSegmentApi = {
  // 段落管理
  getEpisodeSegments: (sessionId: string, episodeNo: number) =>
    api.get<{ segments: EpisodeSegment[]; progress: any }>(
      `/admin/short-drama/sessions/${sessionId}/episodes/${episodeNo}/segments`
    ),

  generateSegment: (segmentId: string, data: { content: string; version_id?: string }) =>
    api.post<{ segment: EpisodeSegment; validation: { passed: boolean; score: number } }>(
      `/admin/short-drama/segments/${segmentId}/generate`,
      data
    ),

  refactorSegment: (segmentId: string, data: { content: string; reason?: string }) =>
    api.post<{ segment: EpisodeSegment; remaining_refactors: number }>(
      `/admin/short-drama/segments/${segmentId}/refactor`,
      data
    ),

  completeSegment: (segmentId: string) =>
    api.post<{ segment: EpisodeSegment }>(`/admin/short-drama/segments/${segmentId}/complete`),

  getSegmentProgress: (sessionId: string, episodeNo: number) =>
    api.get<{
      total_segments: number
      completed: number
      in_progress: number
      percent: number
      can_proceed: boolean
      blocking_reason: string
      segments: EpisodeSegment[]
    }>(`/admin/short-drama/sessions/${sessionId}/episodes/${episodeNo}/progress`),

  getEpisodeAssembly: (sessionId: string, episodeNo: number) =>
    api.get<{ content: string }>(`/admin/short-drama/sessions/${sessionId}/episodes/${episodeNo}/assembly`),

  // 阻塞式评审
  createSegmentReview: (segmentId: string, data: {
    verdict: 'pass' | 'block' | 'request_changes'
    comments?: string
    issues?: Array<{ field: string; issue: string; suggestion: string }>
    rewrite_suggestion?: string
    is_blocking?: boolean
    score?: number
  }) =>
    api.post<{ review: SegmentReview; blocking: boolean }>(
      `/admin/short-drama/segments/${segmentId}/reviews`,
      data
    ),

  getSegmentReviews: (segmentId: string) =>
    api.get<{ reviews: SegmentReview[] }>(`/admin/short-drama/segments/${segmentId}/reviews`),

  resolveReview: (reviewId: string) =>
    api.post<{ review: SegmentReview }>(`/admin/short-drama/reviews/${reviewId}/resolve`),

  // 步骤质量门（阻塞式）
  getStepGate: (sessionId: string, stepId: string) =>
    api.get<{ gate: StepGate; can_pass: boolean; reason: string }>(
      `/admin/short-drama/sessions/${sessionId}/steps/${stepId}/gate`
    ),

  passStepGate: (sessionId: string, stepId: string, data?: { bypass?: boolean; reason?: string }) =>
    api.post<{ gate: StepGate; bypassed: boolean }>(
      `/admin/short-drama/sessions/${sessionId}/steps/${stepId}/gate/pass`,
      data || {}
    ),

  canProceedToNextStep: (sessionId: string, currentStep: string) =>
    api.get<{ can_proceed: boolean; reason: string; current_step: string }>(
      `/admin/short-drama/sessions/${sessionId}/can-proceed`,
      { params: { current_step: currentStep } }
    ),

  // 并行生成
  getParallelReadySegments: (sessionId: string) =>
    api.get<{ segments: EpisodeSegment[]; count: number }>(
      `/admin/short-drama/sessions/${sessionId}/parallel-ready`
    ),

  // 批量操作
  initializeEpisodeSegments: (sessionId: string, episodeNo: number) =>
    api.post<{ segments: EpisodeSegment[]; message: string }>(
      `/admin/short-drama/sessions/${sessionId}/episodes/${episodeNo}/initialize`
    ),

  getAllSessionSegments: (sessionId: string) =>
    api.get<{
      episodes: Record<number, EpisodeSegment[]>
      summary: { total_segments: number; completed: number; percent: number }
    }>(`/admin/short-drama/sessions/${sessionId}/all-segments`),
}
