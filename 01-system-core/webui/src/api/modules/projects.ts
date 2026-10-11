import type { AxiosRequestConfig } from 'axios'
import { v2Api } from '../http'

export const v2ConfigApi = {
  getCurrent: () =>
    v2Api.get<{
      provider: string
      model: string
      base_url: string
      available_providers: string[]
    }>('/config/current'),
  listProviders: () =>
    v2Api.get<Array<{
      id: string
      name: string
      icon: string
      base_url: string
      models: Array<{ value: string; name: string }>
      features: string[]
    }>>('/config/providers'),
}

// V2 类型定义
export interface ProjectV2 {
  id: string
  name: string
  description: string
  project_type: string
  audience_axis: string
  genre_main: string
  genre_sub: string
  creation_mode: 'solo' | 'collab'
  rights_capture_enabled: boolean
  total_episodes: number
  completed_episodes: number
  current_episode: number
  status: string
  workspace_path: string
  config?: ProjectV2Config
  created_at: string
  updated_at: string
}

export interface ProjectV2Config {
  total_episodes?: number | null
  confirmed_total_episodes?: number | null
  suggested_total_episodes?: number | null
  episode_count_status?: 'unconfirmed' | 'confirmed' | 'legacy_needs_confirmation'
  episode_count_confirmation_source?: string
  episode_count_confirmed_at?: string
  word_count_per_episode: string
  scene_header_style: string
  episode_seconds: number
  episode_minutes: number
  manga_mode: boolean
  premium_mode: boolean
  advanced_generation_mode: boolean
  advanced_generation_profile_id?: string
  advanced_generation_providers?: Record<string, unknown>
  advanced_generation_routes?: Record<string, unknown>
  rights_capture_enabled?: boolean
  subgenre_track?: string
  sample_track?: string
  generation_provider?: string
  generation_model?: string
}

export interface EpisodeV2 {
  id: string
  episode_number: number
  title: string
  summary: string
  status: string
  total_scenes: number
  completed_scenes: number
  quality_score: number
  current_version: string
  created_at: string
  updated_at: string
}

export interface SceneV2 {
  id: string
  scene_number: number
  scene_code: string
  time: string
  location_type: string
  location_name: string
  content: string
  content_preview: string
  word_count: number
  status: string
  primary_author: string
  ai_generated: boolean
  created_at: string
  updated_at: string
}

export interface ContentVersionV2 {
  id: string
  version_code: string
  parent_version: string
  editor_type: string
  editor_name: string
  diff_stats: {
    added_chars: number
    deleted_chars: number
    added_lines: number
    deleted_lines: number
  }
  contribution_score: number
  change_note: string
  created_at: string
}

export interface ContributionV2 {
  user_id: string
  user_name: string
  episodes_touched: number
  scenes_written: number
  total_edits: number
  words_added: number
  words_deleted: number
  ai_generations_accepted: number
  ai_generations_modified: number
  base_score: number
  ai_collaboration_bonus: number
  final_score: number
  percentage: number
}

export interface ModelProviderV2 {
  id: string
  name: string
  provider_type: string
  base_url: string
  default_model: string
  models: string[]
  is_active: boolean
  is_default: boolean
  rate_limit_rpm: number
  rate_limit_tpm: number
}

export interface GenerationJobV2 {
  job_id: string
  status: string
  message: string
}

export interface GenerationResultV2 {
  job_id: string
  status: string
  content: string | null
  progress: number
  prompt_tokens: number
  completion_tokens: number
  total_tokens: number
  error_message: string | null
  gate_warning?: string
}

export interface ProjectWorkflowContextResponse {
  workflow_context: Record<string, any>
  canon_packet: Record<string, any>
  episode_memory_cards: Array<Record<string, any>>
  updated_at: string
}

// V2 API 方法
export const projectsV2Api = {
  // 项目管理
  create: (data: {
    name: string
    description?: string
    project_type?: string
    audience_axis?: string
    genre_main?: string
    genre_sub?: string
    creation_mode?: 'solo' | 'collab'
    config?: Partial<ProjectV2Config>
  }) => v2Api.post<ProjectV2>('/projects/', data),

  list: (params?: { limit?: number; offset?: number }, config?: AxiosRequestConfig) =>
    v2Api.get<ProjectV2[]>('/projects/', {
      timeout: 8000,
      ...config,
      params,
    }),

  get: (id: string) => v2Api.get<ProjectV2>(`/projects/${id}`),

  update: (id: string, data: {
    description?: string
    project_type?: string
    audience_axis?: string
    genre_main?: string
    genre_sub?: string
    creation_mode?: 'solo' | 'collab'
    config?: Partial<ProjectV2Config>
  }) => v2Api.put<ProjectV2>(`/projects/${id}`, data),

  delete: (id: string, deleteWorkspace?: boolean) =>
    v2Api.delete(`/projects/${id}`, { params: { delete_workspace: deleteWorkspace } }),

  getCharacters: (projectId: string) =>
    v2Api.get<{ characters: Array<Record<string, any>> }>(`/projects/${projectId}/characters`),

  saveCharacters: (projectId: string, characters: Array<Record<string, any>>) =>
    v2Api.put<{ characters: Array<Record<string, any>> }>(`/projects/${projectId}/characters`, { characters }),

  getStateCards: (projectId: string) =>
    v2Api.get<{
      relationship_cards: Array<Record<string, any>>
      info_cards: Array<Record<string, any>>
      power_cards: Array<Record<string, any>>
      promise_cards: Array<Record<string, any>>
      locked_fact_cards: Array<Record<string, any>>
    }>(`/projects/${projectId}/state-cards`),

  saveStateCards: (projectId: string, stateCards: {
    relationship_cards: Array<Record<string, any>>
    info_cards: Array<Record<string, any>>
    power_cards: Array<Record<string, any>>
    promise_cards: Array<Record<string, any>>
    locked_fact_cards: Array<Record<string, any>>
  }) =>
    v2Api.put(`/projects/${projectId}/state-cards`, stateCards),

  getWorkflowContext: (projectId: string) =>
    v2Api.get<ProjectWorkflowContextResponse>(`/projects/${projectId}/workflow-context`),

  saveWorkflowContext: (projectId: string, data: {
    workflow_context?: Record<string, any>
    canon_packet?: Record<string, any>
    episode_memory_cards?: Array<Record<string, any>>
    merge?: boolean
  }, config?: AxiosRequestConfig) =>
    v2Api.put<ProjectWorkflowContextResponse>(`/projects/${projectId}/workflow-context`, data, {
      timeout: 120000,
      ...config,
    }),

  // 集管理
  createEpisode: (projectId: string, data: { title?: string; summary?: string; status?: string }, episodeNumber?: number) =>
    v2Api.post<EpisodeV2>(`/projects/${projectId}/episodes`, data, { params: episodeNumber ? { episode_number: episodeNumber } : undefined }),

  listEpisodes: (projectId: string) =>
    v2Api.get<EpisodeV2[]>(`/projects/${projectId}/episodes`),

  getEpisode: (projectId: string, episodeNumber: number) =>
    v2Api.get<EpisodeV2>(`/projects/${projectId}/episodes/${episodeNumber}`),

  deleteEpisode: (projectId: string, episodeNumber: number) =>
    v2Api.delete<{ ok: boolean; episode_number: number; deleted_scenes: number }>(`/projects/${projectId}/episodes/${episodeNumber}`),

  // 场景管理
  createScene: (projectId: string, episodeNumber: number, data: {
    time?: string
    location_type?: string
    location_name?: string
    content?: string
  }) => v2Api.post<SceneV2>(`/projects/${projectId}/episodes/${episodeNumber}/scenes`, data),

  listScenes: (projectId: string, episodeNumber: number, options?: { signal?: AbortSignal }) =>
    v2Api.get<SceneV2[]>(`/projects/${projectId}/episodes/${episodeNumber}/scenes`, {
      signal: options?.signal,
    }),

  listScenesBatch: (projectId: string, episodeNumbers: number[]) =>
    v2Api.get<Record<string, SceneV2[]>>(`/projects/${projectId}/scenes`, {
      params: { episode_numbers: episodeNumbers.join(',') },
    }),

  saveSceneContent: (projectId: string, episodeNumber: number, sceneNumber: number, data: {
    content: string
    editor_type?: string
    editor_id?: string
    editor_name?: string
    change_note?: string
    create_checkpoint?: boolean
    c19_178_materialization?: boolean
    manual_edit_evidence?: Record<string, any>
  }) => v2Api.post<ContentVersionV2>(`/projects/${projectId}/episodes/${episodeNumber}/scenes/${sceneNumber}/save`, data),

  // 版本管理
  listVersions: (projectId: string, episodeNumber: number, sceneNumber: number) =>
    v2Api.get<ContentVersionV2[]>(`/projects/${projectId}/episodes/${episodeNumber}/scenes/${sceneNumber}/versions`),

  getDiff: (projectId: string, versionId: string) =>
    v2Api.get<{
      old_version: string
      new_version: string
      added_lines: string[]
      deleted_lines: string[]
      modified_blocks: any[]
      stats: any
    }>(`/projects/${projectId}/versions/${versionId}/diff`),

  restoreVersion: (projectId: string, episodeNumber: number, sceneNumber: number, versionCode: string, editorId?: string, editorName?: string) =>
    v2Api.post<SceneV2>(`/projects/${projectId}/episodes/${episodeNumber}/scenes/${sceneNumber}/restore`, null, {
      params: { version_code: versionCode, editor_id: editorId, editor_name: editorName }
    }),

  // 贡献度统计
  getContributions: (projectId: string) =>
    v2Api.get<ContributionV2[]>(`/projects/${projectId}/contributions`),

  getContributionHeatmap: (projectId: string) =>
    v2Api.get<any[]>(`/projects/${projectId}/contributions/heatmap`),

  // 模型提供商管理
  addModelProvider: (data: {
    name: string
    provider_type: string
    base_url: string
    api_key: string
    default_model: string
    models?: string[]
    rate_limit_rpm?: number
    rate_limit_tpm?: number
  }) => v2Api.post<{ id: string; message: string }>('/projects/model-providers', data),

  listModelProviders: () =>
    v2Api.get<ModelProviderV2[]>('/projects/model-providers'),

  setDefaultProvider: (providerId: string) =>
    v2Api.post(`/projects/model-providers/${providerId}/set-default`),

  // AI生成任务
  createGenerationJob: (projectId: string, data: {
    job_type: string
    episode_number: number
    scene_number?: number
    provider_id?: string
    model_name?: string
    prompt_override?: string
    temperature?: number
    extra_params?: Record<string, any>
  }) => v2Api.post<GenerationJobV2>(`/projects/${projectId}/generate`, data),

  getGenerationStatus: (projectId: string, jobId: string) =>
    v2Api.get<GenerationResultV2>(`/projects/${projectId}/generate/${jobId}`),

  /** 智能大纲分析 — 替代 OutlineEditorView 中的 mock 数据 */
  extractOutlineFile: (file: File) => {
    const formData = new FormData()
    formData.append('file', file)
    return v2Api.post<{
      filename: string
      kind: 'docx' | 'markdown' | 'txt'
      text: string
      chars: number
      truncated: boolean
    }>('/projects/outline/extract-file', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: 60000,
    })
  },

  analyzeOutline: (outline: string, temperature = 0.3, targetEpisodes?: number) =>
    v2Api.post<Record<string, unknown>>('/projects/outline/analyze', {
      outline,
      temperature,
      target_episodes: targetEpisodes,
    }, { timeout: 60000 }),

  generateEpisodeOutlines: (params: {
    outline: string
    target_episodes: number
    temperature?: number
    project_id?: string
    generation_provider?: string
    generation_model?: string
    seed_analysis?: Record<string, unknown>
  }) =>
    v2Api.post<{
      episodes: Array<Record<string, unknown>>
      global_prediction_used?: boolean
      fallback?: boolean
      fallback_reason?: string
      candidate_source?: string
      needs_user_confirmation?: boolean
      main_chain_committed?: boolean
      downstream_generation_allowed?: boolean
      candidate_boundary_reason?: string
    }>('/projects/outline/episodes/generate', params, { timeout: 90000 }),

  predictOutline: (params: {
    outline: string
    target_episodes?: number
    temperature?: number
    seed_analysis?: Record<string, unknown>
  }) =>
    v2Api.post<Record<string, unknown>>('/projects/outline/predict', params, { timeout: 90000 }),

  // 集纲生成后台任务：start 立即返回 job_id，前端轮询 status 取进度/结果
  startEpisodeOutlinesJob: (params: {
    outline: string
    target_episodes: number
    temperature?: number
    project_id?: string
    generation_provider?: string
    generation_model?: string
    seed_analysis?: Record<string, unknown>
  }) =>
    v2Api.post<{ job_id: string; status: string; total: number }>(
      '/projects/outline/episodes/start',
      params,
      { timeout: 30000 },
    ),

  getEpisodeOutlinesJobStatus: (jobId: string) =>
    v2Api.get<{
      job_id: string
      status: 'pending' | 'running' | 'done' | 'error' | 'unknown'
      progress?: { done: number; total: number }
      episodes?: Array<Record<string, unknown>>
      prediction?: Record<string, unknown>
      fallback?: boolean
      fallback_reason?: string
      candidate_source?: string
      needs_user_confirmation?: boolean
      main_chain_committed?: boolean
      downstream_generation_allowed?: boolean
      candidate_boundary_reason?: string
      error?: string
    }>(`/projects/outline/episodes/status/${jobId}`, { timeout: 30000 }),
}
