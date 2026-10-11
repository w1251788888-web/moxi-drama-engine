import api from '../http'

export interface SkillCatalogItem {
  id: string
  name: string
  display_name: string
  description: string
  source: string
  target: string
  upstream_repo: string
  category: string
  recommended_for: string[]
  why: string
  mode: string
  status: string
  is_enabled: boolean
  version: number
  manifest_hash: string
  metadata: Record<string, unknown>
  synced_at: string
  updated_at: string
}

export interface SkillBindingItem {
  id: string
  skill_id: string
  skill_name: string
  binding_type: string
  binding_key: string
  priority: number
  config: Record<string, unknown>
  metadata: Record<string, unknown>
  status: string
  is_enabled: boolean
  created_at: string
  updated_at: string
}

export interface SkillInvocationItem {
  id: string
  skill_id: string
  skill_name: string
  binding_id: string
  actor_type: string
  actor_id: string
  context: string
  failure_type: string
  status: string
  input_summary: string
  output_summary: string
  metadata: Record<string, unknown>
  started_at: string
  finished_at: string
  duration_ms: number
  created_at: string
  updated_at: string
}

export interface SkillArtifactItem {
  id: string
  invocation_id: string
  skill_id: string
  skill_name: string
  artifact_type: string
  title: string
  content: string
  path: string
  metadata: Record<string, unknown>
  created_at: string
}

export interface SkillQualityFeedbackItem {
  id: string
  invocation_id: string
  skill_id: string
  skill_name: string
  score: number
  verdict: string
  reviewer_type: string
  reviewer_id: string
  notes: string
  metadata: Record<string, unknown>
  created_at: string
}

export interface SkillQualityFeedbackSummaryItem {
  skill_name: string
  feedback_count: number
  average_score: number
  useful_rate: number
  negative_rate: number
  verdict_counts: Record<string, number>
  failure_type_breakdown: Array<{ failure_type: string; count: number }>
  binding_priority_hint: {
    action: string
    suggested_priority_delta: number
    binding_type: string
    binding_key: string
    reason: string
  }
  last_feedback_at: string
}

export interface SkillQualityFeedbackSummaryResponse {
  generated_at: string
  source: string
  total_feedback_count: number
  skill_count: number
  average_score: number
  verdict_counts: Record<string, number>
  min_feedback: number
  items: SkillQualityFeedbackSummaryItem[]
}

export interface SkillCatalogResponse {
  source: string
  skill_count: number
  skills: SkillCatalogItem[]
}

export interface SkillListResponse<T> {
  count: number
  items: T[]
}

export interface SkillSyncResponse {
  source: string
  manifest_skill_count: number
  created_count: number
  updated_count: number
  unchanged_count: number
  archived_count: number
  registry_count: number
}

export interface SkillRecommendResponse {
  context: string
  failure_type: string
  blocking_issue_count: number
  warning_count: number
  catalog_source: string
  matched_bindings: SkillBindingItem[]
  stages: Array<{
    stage: string
    title: string
    why: string
    action_hint: string
    skills: Array<Record<string, unknown>>
  }>
  recommended_skills: Array<Record<string, unknown>>
  next_actions: string[]
}

export interface SkillWorkerRunResponse {
  worker: string
  catalog_source: string
  failure_type: string
  planned_count: number
  recommendation: SkillRecommendResponse
  invocations: SkillInvocationItem[]
  artifacts: SkillArtifactItem[]
}

export interface SkillExternalRunnerResponse {
  worker: string
  status: string
  will_execute: boolean
  skill_name: string
  runner_name: string
  binding_id: string
  timeout_seconds: number
  parameters: Record<string, unknown>
  invocation: SkillInvocationItem
  artifact: SkillArtifactItem
}

export interface SkillExternalRunnerExecutionResponse extends SkillExternalRunnerResponse {
  request_invocation_id: string
  request_invocation: SkillInvocationItem
  execution: {
    status: string
    returncode: number | null
    timed_out: boolean
    duration_ms: number
    stdout: string
    stderr: string
    stdout_truncated: boolean
    stderr_truncated: boolean
    command_key: string
  }
}

export const skillWorkflowApi = {
  catalog: (params?: { include_disabled?: boolean }) =>
    api.get<SkillCatalogResponse>('/admin/skill-workflows/catalog', { params }),
  sync: () =>
    api.post<SkillSyncResponse>('/admin/skill-workflows/sync'),
  recommend: (data: {
    failure_type?: string
    blocking_issues?: string[]
    warnings?: string[]
    context?: string
  }) => api.post<SkillRecommendResponse>('/admin/skill-workflows/recommend', data),
  runWorker: (data: {
    failure_type?: string
    blocking_issues?: string[]
    warnings?: string[]
    context?: string
    actor_type?: string
    actor_id?: string
    max_skills?: number
  }) => api.post<SkillWorkerRunResponse>('/admin/skill-workflows/worker/run', data),
  prepareRunner: (data: {
    skill_name: string
    binding_id?: string
    parameters?: Record<string, unknown>
    context?: string
    actor_type?: string
    actor_id?: string
    runner_name?: string
    timeout_seconds?: number
    confirm_execution?: boolean
    confirmation_phrase?: string
    confirmed_by?: string
  }) => api.post<SkillExternalRunnerResponse>('/admin/skill-workflows/runner/prepare', data),
  executeRunner: (data: {
    request_invocation_id: string
    runner_name?: string
    context?: string
    actor_type?: string
    actor_id?: string
    confirm_execution?: boolean
    confirmation_phrase?: string
    confirmed_by?: string
  }) => api.post<SkillExternalRunnerExecutionResponse>('/admin/skill-workflows/runner/execute', data),
  listBindings: (params?: {
    skill_name?: string
    binding_type?: string
    binding_key?: string
    include_disabled?: boolean
    limit?: number
  }) => api.get<SkillListResponse<SkillBindingItem>>('/admin/skill-workflows/bindings', { params }),
  createBinding: (data: {
    skill_name: string
    binding_type: string
    binding_key?: string
    priority?: number
    config?: Record<string, unknown>
    metadata?: Record<string, unknown>
    is_enabled?: boolean
  }) => api.post<SkillBindingItem>('/admin/skill-workflows/bindings', data),
  updateBinding: (bindingId: string, data: {
    binding_key?: string
    priority?: number
    config?: Record<string, unknown>
    metadata?: Record<string, unknown>
    status?: string
    is_enabled?: boolean
  }) => api.put<SkillBindingItem>(`/admin/skill-workflows/bindings/${bindingId}`, data),
  resolveBindings: (params?: {
    failure_type?: string
    step_id?: string
    project_type?: string
    context?: string
    limit?: number
  }) => api.get<SkillListResponse<SkillBindingItem>>('/admin/skill-workflows/bindings/resolve', { params }),
  startInvocation: (data: {
    skill_name: string
    binding_id?: string
    actor_type?: string
    actor_id?: string
    context?: string
    failure_type?: string
    input_summary?: string
    metadata?: Record<string, unknown>
  }) => api.post<SkillInvocationItem>('/admin/skill-workflows/invocations', data),
  listInvocations: (params?: {
    skill_name?: string
    status?: string
    context?: string
    limit?: number
  }) => api.get<SkillListResponse<SkillInvocationItem>>('/admin/skill-workflows/invocations', { params }),
  finishInvocation: (invocationId: string, data: {
    status: string
    output_summary?: string
    metadata?: Record<string, unknown>
  }) => api.put<SkillInvocationItem>(`/admin/skill-workflows/invocations/${invocationId}/finish`, data),
  createArtifact: (invocationId: string, data: {
    artifact_type?: string
    title?: string
    content?: string
    path?: string
    metadata?: Record<string, unknown>
  }) => api.post<SkillArtifactItem>(`/admin/skill-workflows/invocations/${invocationId}/artifacts`, data),
  createQualityFeedback: (invocationId: string, data: {
    score?: number
    verdict?: string
    reviewer_type?: string
    reviewer_id?: string
    notes?: string
    metadata?: Record<string, unknown>
  }) => api.post<SkillQualityFeedbackItem>(`/admin/skill-workflows/invocations/${invocationId}/feedback`, data),
  listArtifacts: (params?: {
    invocation_id?: string
    skill_name?: string
    artifact_type?: string
    limit?: number
  }) => api.get<SkillListResponse<SkillArtifactItem>>('/admin/skill-workflows/artifacts', { params }),
  listQualityFeedback: (params?: {
    invocation_id?: string
    skill_name?: string
    verdict?: string
    limit?: number
  }) => api.get<SkillListResponse<SkillQualityFeedbackItem>>('/admin/skill-workflows/quality-feedback', { params }),
  qualityFeedbackSummary: (params?: {
    skill_name?: string
    limit?: number
    min_feedback?: number
  }) => api.get<SkillQualityFeedbackSummaryResponse>('/admin/skill-workflows/quality-feedback/summary', { params }),
}
