import api from '../http'
import { v2Api } from '../http'

export interface YjsStatusResponse {
  feature_id: string
  feature_label: string
  available: boolean
  backend: string
  degraded: boolean
  package_json: string
  dependencies: Record<string, string>
  missing_dependencies: string[]
  transport: string
  fallback: string
  error: string
}

export interface YjsDocumentPlan {
  id: string
  label: string
  ydoc_key: string
  fallback_api: string
  conflict_policy: string
}

export interface YjsPresencePlan {
  enabled_when_available: boolean
  fields: string[]
  fallback: string
}

export interface YjsPlanResponse extends YjsStatusResponse {
  entrypoint: string
  documents: YjsDocumentPlan[]
  presence: YjsPresencePlan
  acceptance_gates: string[]
}

export interface ProjectInvite {
  id: string
  project_id: string
  invite_token?: string
  target_contact: string
  target_access_key_id: string
  role: string
  legal_identity: string
  scope_type: string
  scope_id: string
  permissions: string[]
  allow_download: boolean
  status: string
  invited_by: string
  invited_by_name: string
  note: string
  expires_at: string
  accepted_by: string
  created_at: string
}

export interface ProjectMember {
  id: string
  project_id: string
  access_key_id: string
  role: string
  legal_identity: string
  display_name: string
  status: string
  invited_by: string
  permissions: string[]
  accepted_at: string
  created_at: string
}

export interface CollabEvent {
  id: string
  action: string
  actor_name: string
  scope_type: string
  scope_id: string
  episode_number: number
  scene_number: number
  metadata: Record<string, any>
  created_at: string
}

export interface ApprovalTask {
  id: string
  project_id: string
  task_type: string
  title: string
  description: string
  scope_type: string
  scope_id: string
  priority: string
  status: string
  requested_by_name: string
  decided_by: string
  decision_note: string
  metadata: Record<string, any>
  created_at: string
  decided_at: string
}

export interface CollaborationSummary {
  project_id: string
  creation_mode: 'solo' | 'collab'
  members: ProjectMember[]
  pending_invites: number
  pending_approvals: number
  locked_episodes: number
}

export const collaborationApi = {
  yjsStatus: () => api.get<YjsStatusResponse>('/collaboration/yjs/status'),

  yjsPlan: () => api.get<YjsPlanResponse>('/collaboration/yjs/plan'),

  listPendingInvites: () =>
    v2Api.get<{ items: ProjectInvite[] }>('/projects/collaboration/invites/pending'),

  acceptInvite: (inviteId: string) =>
    v2Api.post<ProjectMember>(`/projects/collaboration/invites/${inviteId}/accept`),

  rejectInvite: (inviteId: string) =>
    v2Api.post<ProjectInvite>(`/projects/collaboration/invites/${inviteId}/reject`),

  getSummary: (projectId: string) =>
    v2Api.get<CollaborationSummary>(`/projects/${projectId}/collaboration/summary`),

  listMembers: (projectId: string) =>
    v2Api.get<{ items: ProjectMember[] }>(`/projects/${projectId}/collaboration/members`),

  createInvite: (projectId: string, data: {
    target_contact?: string
    target_access_key_id?: string
    role?: string
    legal_identity?: string
    scope_type?: string
    scope_id?: string
    permissions?: string[]
    allow_download?: boolean
    days_valid?: number
    note?: string
  }) => v2Api.post<ProjectInvite>(`/projects/${projectId}/collaboration/invites`, data),

  listInvites: (projectId: string) =>
    v2Api.get<{ items: ProjectInvite[] }>(`/projects/${projectId}/collaboration/invites`),

  listEvents: (projectId: string) =>
    v2Api.get<{ items: CollabEvent[] }>(`/projects/${projectId}/collaboration/events`),

  createEvent: (projectId: string, data: {
    action: string
    scope_type?: string
    scope_id?: string
    episode_number?: number
    scene_number?: number
    title?: string
    body?: string
    metadata?: Record<string, any>
  }) => v2Api.post<{ id: string; status: string }>(`/projects/${projectId}/collaboration/events`, data),

  lockEpisode: (projectId: string, episodeNumber: number, data: { note?: string }) =>
    v2Api.post<{ version_id: string; version_code: string; content_hash: string; status: string }>(
      `/projects/${projectId}/episodes/${episodeNumber}/lock`,
      data,
    ),

  listApprovals: (projectId: string, status?: string) =>
    v2Api.get<{ items: ApprovalTask[] }>(`/projects/${projectId}/approvals`, {
      params: status ? { status } : undefined,
    }),

  decideApproval: (projectId: string, approvalId: string, data: { decision: string; note?: string }) =>
    v2Api.post<ApprovalTask>(`/projects/${projectId}/approvals/${approvalId}/decision`, data),
}
