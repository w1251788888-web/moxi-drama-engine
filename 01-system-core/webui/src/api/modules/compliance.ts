import { v2Api } from '../http'

export interface ComplianceEpisode {
  episode_number: number
  title: string
  status: string
  latest_scan_id: string
  verdict: string
  open_findings: number
}

export interface ComplianceFinding {
  id: string
  scan_id: string
  rule_id: string
  severity: 'redline' | 'high_risk' | 'warning' | string
  category: string
  episode_number: number
  scene_number: number
  start_offset: number
  end_offset: number
  quote: string
  reason: string
  suggestion: string
  confidence: number
  content_version_id: string
  content_hash: string
  status: string
  human_decision: string
  human_note: string
  created_at: string
}

export interface ComplianceScan {
  id: string
  project_id: string
  episode_number: number
  content_version_id: string
  content_hash: string
  status: string
  verdict: string
  summary: string
  findings: ComplianceFinding[]
  created_at: string
}

export const complianceApi = {
  listEpisodes: (projectId: string) =>
    v2Api.get<{ items: ComplianceEpisode[] }>(`/projects/${projectId}/compliance/episodes`),

  scanEpisode: (projectId: string, episodeNumber: number) =>
    v2Api.post<ComplianceScan>(`/projects/${projectId}/compliance/episodes/${episodeNumber}/scan`),

  listFindings: (projectId: string, episodeNumber?: number) =>
    v2Api.get<{ items: ComplianceFinding[] }>(`/projects/${projectId}/compliance/findings`, {
      params: episodeNumber ? { episode_number: episodeNumber } : undefined,
    }),

  decideFinding: (projectId: string, findingId: string, data: { decision: string; note?: string }) =>
    v2Api.post<ComplianceFinding>(`/projects/${projectId}/compliance/findings/${findingId}/decision`, data),

  createPatch: (projectId: string, findingId: string) =>
    v2Api.post<{ id: string; before_text: string; after_text: string; status: string }>(
      `/projects/${projectId}/compliance/findings/${findingId}/patch`,
    ),
}
