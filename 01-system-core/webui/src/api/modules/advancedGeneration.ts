import api from '../http'

export interface AdvancedGenerationStep {
  id: string
  label: string
  purpose: string
  output_type: string
}

export interface AdvancedGenerationArtifact {
  id: string
  label: string
  description: string
}

export interface AdvancedGenerationProfile {
  id: string
  label: string
  status: 'active' | 'scaffold'
  project_type_aliases: string[]
  rule_scopes: string[]
  workflow_steps: AdvancedGenerationStep[]
  artifacts: AdvancedGenerationArtifact[]
  notes: string[]
}

export interface AdvancedGenerationProfileListResponse {
  mode_id: string
  mode_label: string
  profiles: AdvancedGenerationProfile[]
}

export interface AdvancedGenerationRoutePreview {
  step_id: string
  role: string
  role_label: string
  provider: string
  model: string
  temperature: number | null
  reason: string
}

export interface AdvancedGenerationPlanResponse {
  mode_id: string
  mode_label: string
  enabled: boolean
  profile_id: string
  profile_label: string
  routes: AdvancedGenerationRoutePreview[]
}

export interface AdvancedGenerationOrchestrationStatusResponse {
  workflow_id: string
  workflow_label: string
  available: boolean
  backend: string
  degraded: boolean
  langchain_available: boolean
  langgraph_available: boolean
  langchain_version: string
  langgraph_version: string
  compiled: boolean
  error: string
}

export interface AdvancedGenerationWorkflowNode {
  id: string
  role: string
  role_label: string
  step_id: string
  label: string
  provider: string
  model: string
  temperature: number | null
  purpose: string
}

export interface AdvancedGenerationWorkflowEdge {
  from: string
  to: string
  condition: string
}

export interface AdvancedGenerationOrchestrationPlanResponse {
  workflow_id: string
  workflow_label: string
  mode_id: string
  mode_label: string
  enabled: boolean
  profile_id: string
  profile_label: string
  backend: string
  available: boolean
  degraded: boolean
  compiled: boolean
  error: string
  max_review_rounds: number
  entrypoint: string
  nodes: AdvancedGenerationWorkflowNode[]
  edges: AdvancedGenerationWorkflowEdge[]
  probe_trace: string[]
  routes: AdvancedGenerationRoutePreview[]
}

export const advancedGenerationApi = {
  listProfiles: () =>
    api.get<AdvancedGenerationProfileListResponse>('/admin/short-drama/advanced-generation/profiles'),

  getProfile: (profileId: string) =>
    api.get<AdvancedGenerationProfile>(`/admin/short-drama/advanced-generation/profiles/${profileId}`),

  getPlan: (data: { metadata?: Record<string, unknown>; base_generation_kwargs?: Record<string, unknown> }) =>
    api.post<AdvancedGenerationPlanResponse>('/admin/short-drama/advanced-generation/plan', data),

  getOrchestrationStatus: () =>
    api.get<AdvancedGenerationOrchestrationStatusResponse>(
      '/admin/short-drama/advanced-generation/orchestration/status',
    ),

  getOrchestrationPlan: (data: {
    metadata?: Record<string, unknown>
    base_generation_kwargs?: Record<string, unknown>
    max_review_rounds?: number
  }) => api.post<AdvancedGenerationOrchestrationPlanResponse>(
    '/admin/short-drama/advanced-generation/orchestration/plan',
    data,
  ),
}
