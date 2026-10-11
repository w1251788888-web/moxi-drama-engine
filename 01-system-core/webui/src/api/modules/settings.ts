import api from '../http'

type UserScopedRequestOptions = {
  userSessionToken?: string | null
  adminToken?: string | null
}

function authHeaders(options?: UserScopedRequestOptions) {
  if (options?.userSessionToken) {
    return { 'X-User-Session': options.userSessionToken }
  }
  if (options?.adminToken) {
    return { 'X-Admin-Token': options.adminToken }
  }
  return {}
}

export type RuleBackedScriptJobStatus = {
  job_id: string
  project_id?: string
  episode_no?: number
  scene_no?: number
  status: string
  public_message?: string
  public_progress?: number
  visible_route_count?: number
  candidate_returned_to_user?: boolean
  candidate_needs_user_confirmation?: boolean
  saved_as_canon?: boolean
  user_action_required?: string
  visible_issues?: string[]
  contract_conflicts?: Array<Record<string, unknown>>
  word_count_warning?: string | null
  final_generation_contract_hash?: string
  single_episode_time_budget?: Record<string, unknown>
  candidate?: {
    content?: string
    content_hash?: string
    char_count_excluding_punctuation?: number
    warnings?: string[]
    rag_evidence?: Array<Record<string, unknown>>
    episode_memory_card?: Record<string, unknown>
    canon_packet?: Record<string, unknown>
  }
}

export type RuleBackedGenerationSourcePreview = {
  status: 'ready' | 'blocked'
  reason_code?: string
  detail?: Record<string, unknown>
  safe_summary?: {
    source?: string
    source_packet_version?: string
    project_id?: string
    episode_no?: number
    scene_no?: number
    segment_id?: string
    previous_episode_continuity?: {
      source?: string
      previous_episode_no?: number | null
      content_version_id?: string | null
      content_hash?: string | null
      episode_locked_event_id?: string | null
      ready?: boolean
    }
    blocking_issues_count?: number
    warnings_count?: number
    frontend_packet?: {
      source?: string
      input_present?: boolean
      used_as_authority_source?: boolean
    }
  }
  blocking_issues?: string[]
  warnings?: string[]
}

export const adminConfigApi = {
  get: () => api.get('/admin/config'),
  update: (data: Record<string, unknown>) => api.put('/admin/config', data),
  updatePassword: (oldPassword: string, newPassword: string) =>
    api.put('/admin/config/password', {
      old_password: oldPassword,
      new_password: newPassword,
    }),
  aiTest: (params: { provider: string; api_key: string; base_url: string; model: string }) =>
    api.post<{ success: boolean; message: string; model?: string; response_preview?: string }>(
      '/admin/config/ai-test',
      params,
      { timeout: 60000 },
    ),
  aiChat: (params: {
    messages: Array<{ role: string; content: string }>
    context?: string
    system_prompt?: string
    max_tokens?: number
    audience_axis?: string
    genre?: string
    format_type?: string
  }) =>
    api.post<{ content: string; role: string }>(
      '/admin/config/ai/chat',
      params,
      { timeout: 60000 },
    ),
  generateRuleBackedScript: (params: {
    project_id?: string
    project_type?: string
    audience_axis?: string
    genre_main?: string
    genre_sub?: string
    subgenre_track?: string
    sample_track?: string
    format_type?: string
    episode_count?: number
    episode_minutes?: number
    scene_header_style?: string
    brief?: string
    golden_finger?: string
    worldview?: string
    conflict?: string
    relationship_guardrails?: string
    episode_no: number
    scene_no: number
    episode_title?: string
    episode_summary?: string
    episode_conflict?: string
    episode_hook?: string
    current_content?: string
    continuity_notes?: string
    word_count_target?: number
    word_count_min?: number
    word_count_max?: number
    exclude_punctuation_for_count?: boolean
    enforce_standard_format?: boolean
    target_chars?: number
    mode?: 'scene' | 'segment'
    segment_id?: 'hook' | 'validation' | 'explosion' | 'resolution'
    selected_character_ids?: string[]
    characters?: Array<Record<string, unknown>>
    state_cards?: Record<string, unknown>
    series_title?: string
    episode_content?: string
    previous_episode_briefs?: Array<Record<string, unknown>>
    future_episode_briefs?: Array<Record<string, unknown>>
    previous_relationship_snapshot?: Array<Record<string, unknown>>
    episode_memory_cards?: Array<Record<string, unknown>>
    canon_packet?: Record<string, unknown>
    series_simulation_packet?: Record<string, unknown>
    episode_contract?: Record<string, unknown>
    rag_context_pack?: Record<string, unknown>
    materials?: Array<Record<string, unknown>>
    issue_feedback?: Record<string, unknown>
    rule_profile?: string
    world_rules?: string
    golden_finger_rules?: string
    conflict_plan?: string
    quality_report?: Record<string, unknown>
    compliance_report?: Record<string, unknown>
    episode_novel_anchor?: string
    rag_asset_references?: string
    rag_market_signals?: string
    rag_novel_chapters?: string
    rag_script_references?: string
    rag_character_references?: string
    rag_beat_references?: string
    rag_review_references?: string
    generation_provider?: string
    generation_model?: string
    advanced_generation_mode?: boolean
    advanced_generation_providers?: Record<string, unknown>
    advanced_generation_routes?: Record<string, unknown>
    temperature?: number
  }) =>
    api.post<{
      content: string
      char_count_excluding_punctuation: number
      overflow_content?: string
      warnings?: string[]
      benchmark_assessment?: Record<string, unknown>
      continuity_assessment?: Record<string, unknown>
      episode_memory_card?: Record<string, unknown>
      canon_packet?: Record<string, unknown>
      rag_evidence?: Array<Record<string, unknown>>
    }>(
      '/admin/short-drama/testing/script-scene',
      params,
      { timeout: 60000 },
    ),
  generateRuleBackedScriptStreamUrl: () =>
    '/api/admin/short-drama/testing/script-scene/stream',
  previewRuleBackedGenerationSource: (params: Record<string, unknown>, options?: UserScopedRequestOptions) =>
    api.post<RuleBackedGenerationSourcePreview>(
      '/admin/short-drama/testing/script-scene/source-packet/preview',
      params,
      { timeout: 60000, headers: authHeaders(options) },
    ),
  startRuleBackedScriptJob: (params: Record<string, unknown>, options?: UserScopedRequestOptions) =>
    api.post<RuleBackedScriptJobStatus>(
      '/admin/short-drama/testing/script-scene/jobs/start',
      params,
      { timeout: 60000, headers: authHeaders(options) },
    ),
  getRuleBackedScriptJobStatus: (jobId: string, options?: UserScopedRequestOptions) =>
    api.get<RuleBackedScriptJobStatus>(
      `/admin/short-drama/testing/script-scene/jobs/status/${jobId}`,
      { timeout: 60000, headers: authHeaders(options) },
    ),
  getLatestRuleBackedScriptJob: (
    params: { project_id: string; episode_no: number; scene_no: number; segment_id?: string },
    options?: UserScopedRequestOptions,
  ) =>
    api.get<RuleBackedScriptJobStatus>(
      '/admin/short-drama/testing/script-scene/jobs/latest',
      {
        params,
        timeout: 60000,
        headers: authHeaders(options),
      },
    ),
  validateRuleBackedScript: (params: {
    project_id?: string
    project_type?: string
    audience_axis?: string
    genre_main?: string
    genre_sub?: string
    subgenre_track?: string
    sample_track?: string
    format_type?: string
    episode_count?: number
    episode_minutes?: number
    scene_header_style?: string
    brief?: string
    golden_finger?: string
    worldview?: string
    conflict?: string
    relationship_guardrails?: string
    episode_no: number
    scene_no: number
    episode_title?: string
    episode_summary?: string
    episode_conflict?: string
    episode_hook?: string
    current_content?: string
    scene_content: string
    continuity_notes?: string
    word_count_target?: number
    word_count_min?: number
    word_count_max?: number
    exclude_punctuation_for_count?: boolean
    enforce_standard_format?: boolean
    target_chars?: number
    mode?: 'scene' | 'segment'
    segment_id?: 'hook' | 'validation' | 'explosion' | 'resolution'
    selected_character_ids?: string[]
    characters?: Array<Record<string, unknown>>
    state_cards?: Record<string, unknown>
    series_title?: string
    episode_content?: string
    previous_episode_briefs?: Array<Record<string, unknown>>
    future_episode_briefs?: Array<Record<string, unknown>>
    previous_relationship_snapshot?: Array<Record<string, unknown>>
    episode_memory_cards?: Array<Record<string, unknown>>
    canon_packet?: Record<string, unknown>
    series_simulation_packet?: Record<string, unknown>
    episode_contract?: Record<string, unknown>
    rag_context_pack?: Record<string, unknown>
    materials?: Array<Record<string, unknown>>
    issue_feedback?: Record<string, unknown>
    rule_profile?: string
    world_rules?: string
    golden_finger_rules?: string
    conflict_plan?: string
    quality_report?: Record<string, unknown>
    compliance_report?: Record<string, unknown>
    episode_novel_anchor?: string
    rag_asset_references?: string
    rag_market_signals?: string
    rag_novel_chapters?: string
    rag_script_references?: string
    rag_character_references?: string
    rag_beat_references?: string
    rag_review_references?: string
    generation_provider?: string
    generation_model?: string
    advanced_generation_mode?: boolean
    advanced_generation_providers?: Record<string, unknown>
    advanced_generation_routes?: Record<string, unknown>
  }) =>
    api.post<{
      char_count_excluding_punctuation: number
      warnings: string[]
      blocking_issues: string[]
      present_character_ids: string[]
      health_items: Array<Record<string, unknown>>
      relationship_suggestions: Array<Record<string, unknown>>
      state_card_suggestions: Array<Record<string, unknown>>
      benchmark_assessment: Record<string, unknown>
      continuity_assessment: Record<string, unknown>
      failure_analysis: Record<string, unknown>
      episode_memory_card: Record<string, unknown>
      canon_packet: Record<string, unknown>
    }>(
      '/admin/short-drama/testing/script-scene/validate',
      params,
      { timeout: 60000 },
    ),
  deepAuditRuleBackedScript: (params: {
    project_id?: string
    project_type?: string
    audience_axis?: string
    genre_main?: string
    genre_sub?: string
    subgenre_track?: string
    sample_track?: string
    format_type?: string
    episode_count?: number
    episode_minutes?: number
    scene_header_style?: string
    brief?: string
    golden_finger?: string
    worldview?: string
    conflict?: string
    relationship_guardrails?: string
    episode_no: number
    scene_no: number
    episode_title?: string
    episode_summary?: string
    episode_conflict?: string
    episode_hook?: string
    current_content?: string
    scene_content: string
    continuity_notes?: string
    word_count_target?: number
    word_count_min?: number
    word_count_max?: number
    exclude_punctuation_for_count?: boolean
    enforce_standard_format?: boolean
    target_chars?: number
    mode?: 'scene' | 'segment'
    segment_id?: 'hook' | 'validation' | 'explosion' | 'resolution'
    selected_character_ids?: string[]
    characters?: Array<Record<string, unknown>>
    state_cards?: Record<string, unknown>
    series_title?: string
    episode_content?: string
    previous_episode_briefs?: Array<Record<string, unknown>>
    future_episode_briefs?: Array<Record<string, unknown>>
    previous_relationship_snapshot?: Array<Record<string, unknown>>
    episode_memory_cards?: Array<Record<string, unknown>>
    canon_packet?: Record<string, unknown>
    series_simulation_packet?: Record<string, unknown>
    episode_contract?: Record<string, unknown>
    rag_context_pack?: Record<string, unknown>
    materials?: Array<Record<string, unknown>>
    issue_feedback?: Record<string, unknown>
    rule_profile?: string
    world_rules?: string
    golden_finger_rules?: string
    conflict_plan?: string
    quality_report?: Record<string, unknown>
    compliance_report?: Record<string, unknown>
    episode_novel_anchor?: string
    rag_asset_references?: string
    rag_market_signals?: string
    rag_novel_chapters?: string
    rag_script_references?: string
    rag_character_references?: string
    rag_beat_references?: string
    rag_review_references?: string
    generation_provider?: string
    generation_model?: string
    advanced_generation_mode?: boolean
    advanced_generation_providers?: Record<string, unknown>
    advanced_generation_routes?: Record<string, unknown>
  }) =>
    api.post<{
      benchmark_assessment: Record<string, unknown>
      continuity_assessment: Record<string, unknown>
    }>(
      '/admin/short-drama/testing/script-scene/deep-audit',
      params,
      { timeout: 60000 },
    ),

  autoFixRuleBackedScript: (params: {
    project_id?: string
    project_type?: string
    audience_axis?: string
    genre_main?: string
    genre_sub?: string
    subgenre_track?: string
    sample_track?: string
    format_type?: string
    episode_count?: number
    episode_minutes?: number
    scene_header_style?: string
    brief?: string
    golden_finger?: string
    worldview?: string
    conflict?: string
    relationship_guardrails?: string
    episode_no: number
    scene_no: number
    episode_title?: string
    episode_summary?: string
    episode_conflict?: string
    episode_hook?: string
    current_content?: string
    scene_content: string
    continuity_notes?: string
    word_count_target?: number
    word_count_min?: number
    word_count_max?: number
    exclude_punctuation_for_count?: boolean
    enforce_standard_format?: boolean
    target_chars?: number
    mode?: 'scene' | 'segment'
    segment_id?: 'hook' | 'validation' | 'explosion' | 'resolution'
    selected_character_ids?: string[]
    characters?: Array<Record<string, unknown>>
    state_cards?: Record<string, unknown>
    series_title?: string
    episode_content?: string
    previous_episode_briefs?: Array<Record<string, unknown>>
    future_episode_briefs?: Array<Record<string, unknown>>
    previous_relationship_snapshot?: Array<Record<string, unknown>>
    episode_memory_cards?: Array<Record<string, unknown>>
    canon_packet?: Record<string, unknown>
    series_simulation_packet?: Record<string, unknown>
    episode_contract?: Record<string, unknown>
    rag_context_pack?: Record<string, unknown>
    materials?: Array<Record<string, unknown>>
    issue_feedback?: Record<string, unknown>
    rule_profile?: string
    world_rules?: string
    golden_finger_rules?: string
    conflict_plan?: string
    quality_report?: Record<string, unknown>
    compliance_report?: Record<string, unknown>
    episode_novel_anchor?: string
    rag_asset_references?: string
    rag_market_signals?: string
    rag_novel_chapters?: string
    rag_script_references?: string
    rag_character_references?: string
    rag_beat_references?: string
    rag_review_references?: string
    generation_provider?: string
    generation_model?: string
    advanced_generation_mode?: boolean
    advanced_generation_providers?: Record<string, unknown>
    advanced_generation_routes?: Record<string, unknown>
  }) =>
    api.post<{
      success: boolean
      content: string
      char_count_excluding_punctuation: number
      warnings: string[]
      blocking_issues: string[]
      present_character_ids: string[]
      health_items: Array<Record<string, unknown>>
      relationship_suggestions: Array<Record<string, unknown>>
      state_card_suggestions: Array<Record<string, unknown>>
      benchmark_assessment: Record<string, unknown>
      continuity_assessment: Record<string, unknown>
      failure_analysis: Record<string, unknown>
      episode_memory_card: Record<string, unknown>
      canon_packet: Record<string, unknown>
      message: string
    }>(
      '/admin/short-drama/testing/script-scene/auto-fix',
      params,
      { timeout: 90000 },
    ),

  suggestSceneImprovement: (params: {
    project_id?: string
    scene_content: string
    audience_axis?: string
    genre_main?: string
    episode_title?: string
    episode_summary?: string
    episode_conflict?: string
    episode_hook?: string
    segment_id?: string
    confirmed_content?: string
    relationship_guardrails?: string
    characters?: Array<Record<string, unknown>>
    previous_episode_briefs?: Array<Record<string, unknown>>
    episode_contract?: Record<string, unknown>
    issue_feedback?: Record<string, unknown>
    rule_profile?: string
  }) =>
    api.post<{ suggestions: string[] }>(
      '/admin/short-drama/testing/script-scene/suggest',
      params,
      { timeout: 30000 },
    ),

  patchSceneText: (params: {
    project_id?: string
    full_text: string
    selected_text: string
    instruction: string
    scene_header_style?: string
  }) =>
    api.post<{ replacement: string }>(
      '/admin/short-drama/testing/script-scene/patch',
      params,
      { timeout: 30000 },
    ),
}
