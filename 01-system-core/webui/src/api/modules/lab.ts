import api from '../http'

export const ruleApi = {
  list: (params?: { task_id?: string; sub_task_id?: string }) => api.get('/rules', { params }),
}

export const adminRuleApi = {
  list: (scope?: string) => api.get('/rules/list', { params: scope ? { scope } : undefined }),
  create: (data: { scope: string; content: string; task_id?: string; sub_task_id?: string }) =>
    api.post('/rules', data),
  update: (id: string, content: string) => api.put(`/rules/${id}`, { content }),
  delete: (id: string) => api.delete(`/rules/${id}`),
}

export const feedApi = {
  status: () => api.get('/feed/status'),
  logs: (params?: { after?: string; agent_id?: string; limit?: number }) =>
    api.get('/feed/logs', { params }),
  agents: () => api.get('/feed/agents'),
  agentSummary: () => api.get('/feed/agent-summary'),
}

export const setupApi = {
  status: () => api.get<{ initialized: boolean; has_external_url: boolean }>('/setup/status'),
  initialize: (data: {
    admin_password: string
    current_password?: string
    project_name: string
    workspace_root: string
    registration_token?: string
    allow_registration?: boolean
    external_url?: string
    notification?: {
      enabled: boolean
      channels: string[]
      events: string[]
    }
  }) => api.post('/setup/initialize', data),
}

// ── 灵感实验室 ──────────────────────────────────────────

export const marketApi = {
  aiTopics: (params?: { keyword?: string; style_axis?: string; count?: number }) =>
    api.post<{
      searchSummary?: string
      hotWords?: Array<{ word: string; weight: number }>
      trending: Array<{
        id?: number; title: string; heat: number; change: string; category: string; tags: string[]
        platforms?: string[]; vacancy?: number; trendHistory?: number[]
      }>
      recommended: Array<{
        id?: number; title: string; type: string; score: number; reason: string; novelty: number
        competition?: number; marketGap?: number; platforms?: Record<string, number>
      }>
      cases: Array<{
        id?: number; title: string; category: string; views: string; hook: string; structure: string
        nodes?: Array<{ label: string; desc: string; type: string }>
        emotionCurve?: number[]; highlights?: string[]
      }>
      inspirations: Array<{
        id?: number; quadrant?: string; type: string; title: string; desc: string; heat: number; tags?: string[]
      }>
    }>('/user/market/ai-topics', params || {}, { timeout: 90000 }),
}

// ── 提示词管理 ──────────────────────────────────────────

export interface PromptTemplate {
  role: string
  filename: string
  content: string
}

export interface AgentPromptMeta {
  slug: string
  filename: string
  name: string
  role: string
  description: string
  created_at: string
  example: boolean
  has_frontmatter: boolean
  status: 'ok' | 'rename_suggested' | 'unconfigured'
}

export interface AgentPromptDetail extends AgentPromptMeta {
  content: string
}

export const promptsApi = {
  // 模板
  listTemplates: () => api.get<PromptTemplate[]>('/admin/prompts/templates'),
  getTemplate: (role: string) => api.get<PromptTemplate>(`/admin/prompts/templates/${role}`),
  updateTemplate: (role: string, content: string) =>
    api.put(`/admin/prompts/templates/${role}`, { content }),

  // Agent 提示词
  listAgents: () => api.get<AgentPromptMeta[]>('/admin/prompts/agents'),
  getAgent: (slug: string) => api.get<AgentPromptDetail>(`/admin/prompts/agents/${slug}`),
  createAgent: (data: {
    slug: string
    name: string
    role: string
    description?: string
    content: string
  }) => api.post('/admin/prompts/agents', data),
  updateAgent: (slug: string, data: {
    name?: string
    role?: string
    description?: string
    content?: string
  }) => api.put(`/admin/prompts/agents/${slug}`, data),
  deleteAgent: (slug: string) => api.delete(`/admin/prompts/agents/${slug}`),

  // 组合（一键复制）
  compose: (slug: string) => api.get<{ slug: string; prompt: string }>(`/admin/prompts/compose/${slug}`),

  // 平台对接指引
  getOnboarding: (role: string) => api.get<{ role: string; content: string }>(`/admin/prompts/onboarding/${role}`),
}

// ============================================================
// AUTO-FIX API - OpenSpace 启发的自动修复
// ============================================================
