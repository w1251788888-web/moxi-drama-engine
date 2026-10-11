import api from '../http'

// 分镜与提示词系统（一期）
// ═══════════════════════════════════════════════════════════════════════════

const VISUAL_FAST_WRITE_TIMEOUT_MS = 30000

// ── 剧本确认保存 ─────────────────────────────────────────
export const scriptConfirmApi = {
  confirm: (data: {
    session_id: string
    episode: number
    project_id: string
    character_name_to_id?: Record<string, string>
  }) => api.post('/script/confirm', data),

  unconfirm: (data: { session_id: string; episode: number; project_id: string }) =>
    api.post('/script/unconfirm', data),

  status: (params: { session_id: string; episode: number }) =>
    api.get<{
      status: 'no_script' | 'draft' | 'confirmed' | 'stale'
      msg: string
      current_version?: string
      confirmed_version?: string
      confirmed_at?: string | null
      rag_doc_ids?: { summary?: string; scene_cards?: string[]; beats?: string[] }
    }>('/script/confirm-status', { params }),
}

// ── 角色视觉档案 ─────────────────────────────────────────
export interface CharacterVisualText {
  age_look?: string
  gender?: string
  face?: string
  hair?: string
  body?: string
  skin?: string
  default_outfit?: string
  signature_props?: string
  voice_tone?: string
  style_tags?: string
}

export interface OutfitVariant {
  id: string
  scene?: string
  desc?: string
}

export interface CharacterVisualBase {
  id: string
  project_id: string
  character_id: string
  character_name: string
  visual_text: CharacterVisualText
  outfit_variants: OutfitVariant[]
  negative_prompt: string
  reference_images: string[]
  id_embedding_path: string
  lora_weights_path: string
  lora_trigger_word: string
  lora_training_status: string
  is_locked: boolean
  locked_at: string | null
  rag_doc_id: string
  version: number
  created_at: string | null
  updated_at: string | null
}

export const characterVisualApi = {
  generate: (data: {
    project_id: string
    character_id: string
    character_name?: string
    narrative_profile?: string
    genre?: string
    style_mode?: string
  }) => api.post<{
    ok: boolean
    visual_text: CharacterVisualText
    backend?: 'llm' | 'fallback'
    fallback_reason?: string
  }>(
    '/character-visual/generate', data, { timeout: 60000 },
  ),

  list: (project_id: string) =>
    api.get<{ items: CharacterVisualBase[] }>('/character-visual/list', {
      params: { project_id },
    }),

  byCharacter: (project_id: string, character_id: string) =>
    api.get<CharacterVisualBase>('/character-visual/by-character', {
      params: { project_id, character_id },
    }),

  upsert: (data: {
    project_id: string
    payload: {
      character_id: string
      character_name?: string
      visual_text?: CharacterVisualText
      outfit_variants?: OutfitVariant[]
      negative_prompt?: string
      reference_images?: string[]
    }
  }) => api.put<CharacterVisualBase & { shots_marked_stale: number }>(
    '/character-visual/upsert', data, { timeout: VISUAL_FAST_WRITE_TIMEOUT_MS },
  ),

  lock: (data: { project_id: string; character_id: string }) =>
    api.post<{ ok: boolean; locked_at?: string; rag_doc_id?: string }>(
      '/character-visual/lock', data, { timeout: VISUAL_FAST_WRITE_TIMEOUT_MS },
    ),

  unlock: (data: { project_id: string; character_id: string }) =>
    api.post<{ ok: boolean; shots_marked_stale?: number }>(
      '/character-visual/unlock', data, { timeout: VISUAL_FAST_WRITE_TIMEOUT_MS },
    ),
}

// ── 场景视觉档案 ─────────────────────────────────────────
export interface SceneVisualBase {
  id: string
  project_id: string
  scene_id: string
  episode: number
  scene_name: string
  environment: string
  time_of_day: string
  lighting: string
  color_palette: string
  props: string
  atmosphere: string
}

export const sceneVisualApi = {
  list: (project_id: string, episode?: number) =>
    api.get<{ items: SceneVisualBase[] }>('/scene-visual/list', {
      params: { project_id, episode },
    }),

  upsert: (data: SceneVisualBase | Omit<SceneVisualBase, 'id'>) =>
    api.post<SceneVisualBase>('/scene-visual/upsert', data),

  delete: (project_id: string, scene_id: string) =>
    api.delete<{ ok: boolean }>(`/scene-visual/${scene_id}`, {
      params: { project_id },
    }),
}

// ── 分镜 ─────────────────────────────────────────────────
export interface ShotSpec {
  shot_id: string
  scene_id: string
  order: number
  duration_sec: number
  beat_role: string
  entities: Array<{
    character_id: string
    outfit_variant_id?: string | null
    action: string
    expression: string
  }>
  scene_ref: string
  camera: {
    shot_size: string
    angle: string
    movement: string
    lens_mm?: number | null
    notes?: string
  }
  shot_delta: {
    framing: string
    lighting_delta: string
    mood: string
    extra: string
  }
  dialogue: string
  audio: { sfx: string; bgm_mood: string; voice_mood: string }
  anchor_frame_ref: string
}

export interface Shot {
  id: string
  project_id: string
  episode: number
  scene_id: string
  shot_order: number
  spec: ShotSpec
  candidates: ShotSpec[]
  selected_candidate_idx: number
  is_stale: boolean
  rag_context_snapshot: string
  created_at: string | null
  updated_at: string | null
}

export interface PromptPack {
  platform: string
  prompt_text: string
  negative_prompt: string
  params: Record<string, any>
}

// 分镜 LLM 接口耗时较长（plan/compile/compileBatch/regenerate 都要调长模型），
// 全局 10s 超时撑不住，单独放宽到 120s。eligibility/list/prompts 是纯查询，沿用默认。
//
// 注意：120s 超时只在 LLM 真的能跑时才合理。LLM 没连通的场景由 StoryboardPanel
// onMounted 时调用 aiHealthApi.check()（5s 内返回）拦截，按钮直接置灰，
// 不会让用户点了之后死等 120s。两层防护组合起来才是对的。
const LONG_LLM_TIMEOUT_MS = 120_000

export const storyboardApi = {
  eligibility: (params: { session_id: string; project_id: string; episode: number }) =>
    api.get<{
      eligible: boolean
      reason: string
      detail: string
      confirmed_version?: string
      missing_locked_characters?: string[]
    }>('/storyboard/eligibility', { params }),

  plan: (data: {
    project_id: string
    episode: number
    session_id?: string
    target_shot_count?: number
    enable_multi_candidate?: boolean
  }) => api.post<{
    ok: boolean
    shots: Shot[]
    rag_used: boolean
    elapsed_ms: number
    msg: string
  }>('/storyboard/plan', data, { timeout: LONG_LLM_TIMEOUT_MS }),

  list: (project_id: string, episode: number) =>
    api.get<{ items: Shot[] }>('/storyboard/list', { params: { project_id, episode } }),

  compile: (data: { shot_id: string; platforms?: string[] }) =>
    api.post<{ ok: boolean; shot_id: string; packs: PromptPack[] }>(
      '/storyboard/compile', data, { timeout: LONG_LLM_TIMEOUT_MS },
    ),

  compileBatch: (data: { project_id: string; episode: number; platforms?: string[] }) =>
    api.post<{ ok: boolean; items: Array<{ shot_id: string; shot_order: number; packs?: PromptPack[]; error?: string }> }>(
      '/storyboard/compile-batch', data, { timeout: LONG_LLM_TIMEOUT_MS },
    ),

  regenerate: (data: { shot_id: string; pick_candidate_idx?: number | null }) =>
    api.post<{ ok: boolean; shot: Shot }>(
      '/storyboard/regenerate-shot', data, { timeout: LONG_LLM_TIMEOUT_MS },
    ),

  prompts: (shot_id: string) =>
    api.get<{ items: Array<{ id: string; shot_id: string; platform: string; prompt_text: string; negative_prompt: string; params: any }> }>(
      '/storyboard/prompts', { params: { shot_id } },
    ),
}

// ── 渲染服务商配置（二期占位）────────────────────────────
export interface RenderProviderConfig {
  name: string
  provider_kind: 'image' | 'video' | 'local'
  api_key: string
  endpoint: string
  enabled: boolean
  extra: Record<string, any>
  doc_hint?: string
  default_endpoint?: string
  last_test_at: string | null
  last_test_ok: boolean
  last_test_msg: string
  updated_at: string | null
}

export const renderConfigApi = {
  catalog: () =>
    api.get<{ items: Array<{ name: string; provider_kind: string; default_endpoint: string; doc_hint: string }> }>(
      '/render-config/catalog',
    ),

  list: () =>
    api.get<{ items: RenderProviderConfig[] }>('/render-config/list'),

  upsert: (data: {
    name: string
    provider_kind?: string
    api_key?: string
    endpoint?: string
    enabled?: boolean
    extra?: Record<string, any>
  }) => api.put<RenderProviderConfig>('/render-config/upsert', data),

  test: (name: string) =>
    api.post<{ ok: boolean; msg: string; latency_ms: number }>(
      `/render-config/test/${encodeURIComponent(name)}`,
    ),

  // 占位：一期会返回 501 + 提示
  renderImage: (data: { provider: string; prompt: string; negative?: string; aspect_ratio?: string }) =>
    api.post('/render-config/render-image', data),

  renderVideo: (data: { provider: string; prompt: string; negative?: string; duration_sec?: number; aspect_ratio?: string }) =>
    api.post('/render-config/render-video', data),
}

// ── 二期占位功能 ────────────────────────────────────────
export const phase2Api = {
  status: () =>
    api.get<{ policy: string; items: Array<{ feature: string; status: string; endpoint?: string }>; msg: string }>('/phase2/status'),
}
