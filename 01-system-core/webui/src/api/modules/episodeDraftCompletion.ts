import { v2Api } from '../http'

export interface EpisodeDraftCompletionCloseResponse {
  status: string
  episode_number: number
  scene_number: number
  created_confirmation_count: number
  reused_confirmation_count: number
  completion_checkpoint_created: boolean
  completion_checkpoint_reused: boolean
  active_job_count: number
  content_version_id: string
  blocking_issues: string[]
  candidate_lengths: Record<string, number>
  confirmed_segment_ids: string[]
  structured_confirmed_segment_ids: string[]
  legacy_confirmed_segment_ids: string[]
  legacy_confirmation_count: number
}

export const episodeDraftCompletionApi = {
  closeEpisodeDraftCompletion: (projectId: string, episodeNumber: number, sceneNumber = 1) =>
    v2Api.post<EpisodeDraftCompletionCloseResponse>(
      `/projects/${projectId}/episodes/${episodeNumber}/draft-completion/close`,
      null,
      { params: { scene_number: sceneNumber } },
    ),
}
