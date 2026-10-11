import api from '../http'

export interface AdminPageResponse<T> {
  items: T[]
  total: number
  page: number
  page_size: number
  total_pages: number
  has_more: boolean
}

export interface AdminTaskMetadata {
  lab_type?: string
  market_logic?: {
    big_categories?: string[]
    sub_categories?: string[]
    summary?: string
    benchmarks?: Array<{
      big_category: string
      sub_category: string
      audience_axis?: string
      script_summary?: string
      ip_core?: string[]
      unit_strategy?: string
      structure_rules?: string[]
      expression_rules?: string[]
      benchmark_features?: string[]
      patch_focus?: string[]
    }>
  }
  internal_test_plan?: {
    max_rounds?: number
    loop?: string[]
    pass_signal?: string[]
  }
  current_track?: string
  best_sample?: {
    title?: string
    score?: number
    passed?: boolean
    strengths?: string[]
    accepted_features?: string[]
    sample_preview?: string
    chapters?: string[]
  }
  rounds?: Array<{
    round: number
    score?: number
    passed?: boolean
    defects?: string[]
    strengths?: string[]
    patch_summary?: string
    rerun_reason?: string
  }>
  artifact_path?: string
  final_summary?: string
  [key: string]: unknown
}

export interface AdminSubTaskMetadata {
  sequence?: string
  module_stage?: string
  loop_required?: boolean
  market_snapshot?: string
  round?: number
  defects?: string[]
  strengths?: string[]
  patch_summary?: string
  rerun_reason?: string
  sample_preview?: string
  accepted_features?: string[]
  score?: number
  passed?: boolean
  chapter_titles?: string[]
  [key: string]: unknown
}


export interface AdminTaskItem {
  id: string
  name: string
  description: string
  type: string
  status: string
  module_count: number
  sub_task_count: number
  pending_count: number
  assigned_count: number
  in_progress_count: number
  review_count: number
  rework_count: number
  blocked_count: number
  done_count: number
  cancelled_count: number
  created_at: string | null
  updated_at: string | null
  metadata?: AdminTaskMetadata
}

export interface AdminTaskDetail extends AdminTaskItem {
  metadata: AdminTaskMetadata
}

export interface AdminModuleItem {
  id: string
  task_id: string
  name: string
  description: string
  sub_task_count: number
  pending_count: number
  assigned_count: number
  in_progress_count: number
  review_count: number
  rework_count: number
  blocked_count: number
  done_count: number
  cancelled_count: number
  created_at: string | null
}

export interface AdminSubTaskItem {
  id: string
  task_id: string
  task_name: string
  module_id: string | null
  module_name: string | null
  name: string
  description: string
  type: string
  status: string
  priority: string
  assigned_agent: string | null
  assigned_agent_name: string | null
  current_session_id: string | null
  rework_count: number
  created_at: string | null
  updated_at: string | null
  completed_at: string | null
  metadata?: AdminSubTaskMetadata
}

export interface AdminSubTaskDetail extends AdminSubTaskItem {
  deliverable: string
  acceptance: string
  metadata: AdminSubTaskMetadata
}

export interface AdminTaskListParams {
  page?: number
  page_size?: number
  status?: string
  type?: string
  keyword?: string
  sort_by?: string
  sort_order?: string
}

export interface AdminModuleListParams {
  page?: number
  page_size?: number
  sort_by?: string
  sort_order?: string
}

export interface AdminSubTaskListParams {
  page?: number
  page_size?: number
  module_id?: string
  status?: string
  assigned_agent?: string
  priority?: string
  type?: string
  keyword?: string
  sort_by?: string
  sort_order?: string
}

// ── Agent 管理端类型 ──

export interface AdminAgentItem {
  id: string
  name: string
  role: string
  description: string
  status: string
  total_score: number
  rank: number
  open_sub_task_count: number
  assigned_count: number
  in_progress_count: number
  review_count: number
  rework_count: number
  blocked_count: number
  last_request_at: string | null
  last_activity_at: string | null
  created_at: string | null
}

export interface AdminAgentDetail extends AdminAgentItem {
  total_agents: number
  reward_count: number
  penalty_count: number
  total_reward_records: number
  done_count: number
  cancelled_count: number
}

export interface AdminAgentListParams {
  page?: number
  page_size?: number
  role?: string
  status?: string
  keyword?: string
  last_request_within_days?: number
  last_activity_within_days?: number
  sort_by?: string
  sort_order?: string
}

// ============================================================
// API 模块
// ============================================================

export const adminApi = {
  login: (username: string, password: string) => api.post('/admin/login', { username, password }),
  resetKey: (agentId: string) => api.post(`/admin/agents/${agentId}/reset-key`),
}

export const adminAgentApi = {
  list: (params?: AdminAgentListParams) =>
    api.get<AdminPageResponse<AdminAgentItem>>('/admin/agents', { params }),
  get: (agentId: string) =>
    api.get<AdminAgentDetail>(`/admin/agents/${agentId}`),
  updateProfile: (
    agentId: string,
    data: { name?: string; role?: string; description?: string },
  ) => api.put(`/admin/agents/${agentId}`, data),
  updateStatus: (agentId: string, status: string) =>
    api.put(`/admin/agents/${agentId}/status`, { status }),
  scoreLogs: (agentId: string, params?: { page?: number; page_size?: number; sub_task_id?: string; sort_order?: string }) =>
    api.get(`/admin/agents/${agentId}/score-logs`, { params }),
  activityLogs: (agentId: string, params?: { page?: number; page_size?: number; action?: string; days?: number; sub_task_id?: string }) =>
    api.get(`/admin/agents/${agentId}/activity-logs`, { params }),
  requestLogs: (agentId: string, params?: { page?: number; page_size?: number; days?: number; method?: string; path_keyword?: string }) =>
    api.get(`/admin/agents/${agentId}/request-logs`, { params }),
  relatedCounts: (agentId: string) =>
    api.get(`/admin/agents/${agentId}/related-counts`),
  deleteAgent: (agentId: string, confirmName: string) =>
    api.delete(`/admin/agents/${agentId}`, { data: { confirm_name: confirmName } }),
}

export const adminTaskApi = {
  list: (params?: AdminTaskListParams) =>
    api.get<AdminPageResponse<AdminTaskItem>>('/admin/tasks', { params }),
  get: (id: string) => api.get<AdminTaskDetail>(`/admin/tasks/${id}`),
  listModules: (taskId: string, params?: AdminModuleListParams) =>
    api.get<AdminPageResponse<AdminModuleItem>>(`/admin/tasks/${taskId}/modules`, { params }),
  listSubTasks: (taskId: string, params?: AdminSubTaskListParams) =>
    api.get<AdminPageResponse<AdminSubTaskItem>>(`/admin/tasks/${taskId}/sub-tasks`, { params }),
  getSubTask: (subTaskId: string) => api.get<AdminSubTaskDetail>(`/admin/sub-tasks/${subTaskId}`),
  delete: (id: string) => api.delete(`/admin/tasks/${id}`),
  bulkDelete: (ids: string[]) =>
    api.post<{
      status: string
      deleted_count: number
      not_found_count: number
      cleaned_dir_count: number
      deleted: string[]
      not_found: string[]
    }>('/admin/tasks/bulk-delete', { task_ids: ids }),
}

export const taskApi = {
  list: (params?: { page?: number; page_size?: number; status?: string }) =>
    api.get('/tasks', { params }),
  get: (id: string) => api.get(`/tasks/${id}`),
  create: (data: { name: string; description?: string; type?: string }) => api.post('/tasks', data),
  update: (id: string, data: { name?: string; description?: string }) =>
    api.put(`/tasks/${id}`, data),
  updateStatus: (id: string, status: string) => api.put(`/tasks/${id}/status`, { status }),
  cancel: (id: string) => api.delete(`/tasks/${id}`),
}

export const subTaskApi = {
  list: (params?: { task_id?: string; status?: string; page?: number; page_size?: number }) =>
    api.get('/sub-tasks', { params }),
  get: (id: string) => api.get(`/sub-tasks/${id}`),
}

export const agentApi = {
  list: (params?: { role?: string }) => api.get('/agents', { params }),
  get: (id: string) => api.get(`/agents/${id}`),
}

// ── 管理端仪表盘类型 ──

export interface DashboardCoreCards {
  open_task_count: number
  active_sub_task_count: number
  review_queue_count: number
  blocked_sub_task_count: number
  active_agent_count: number
  today_completed_sub_task_count: number
}

export interface DashboardSecondaryCards {
  disabled_agent_count: number
  today_review_count: number
  today_rejected_review_count: number
  today_reject_rate: number
  today_net_score_delta: number
}

export interface DashboardDistributions {
  task_status_distribution: Record<string, number>
  sub_task_status_distribution: Record<string, number>
  agent_status_distribution: Record<string, number>
  agent_role_distribution: Record<string, number>
  review_result_distribution_7d: Record<string, number>
}

export interface DashboardOverview {
  generated_at: string
  review_window_days: number
  core_cards: DashboardCoreCards
  secondary_cards: DashboardSecondaryCards
  distributions: DashboardDistributions
}

export interface HighlightSubTask {
  id: string
  task_id: string
  task_name: string
  name: string
  status: string
  assigned_agent: string | null
  assigned_agent_name: string | null
  updated_at: string | null
  rework_count: number
}

export interface HighlightAgent {
  id: string
  name: string
  role: string
  status: string
  total_score: number
  open_sub_task_count: number
  last_request_at: string | null
  last_activity_at: string | null
}

export interface HighlightReview {
  id: string
  task_id: string
  task_name: string
  sub_task_id: string
  sub_task_name: string
  reviewer_agent: string
  reviewer_agent_name: string | null
  result: string
  score: number
  created_at: string | null
}

export interface DashboardHighlights {
  generated_at: string
  limit: number
  inactive_hours: number
  blocked_sub_tasks: HighlightSubTask[]
  pending_review_sub_tasks: HighlightSubTask[]
  busy_agents: HighlightAgent[]
  low_activity_agents: HighlightAgent[]
  recent_reviews: HighlightReview[]
}

export const adminDashboardApi = {
  overview: () => api.get<DashboardOverview>('/admin/dashboard/overview'),
  highlights: (params?: { limit?: number; inactive_hours?: number }) =>
    api.get<DashboardHighlights>('/admin/dashboard/highlights', { params }),
  trends: (params?: { days?: number }) =>
    api.get<DashboardTrends>('/admin/dashboard/trends', { params }),
}

export interface TrendPoint { date: string; count: number }
export interface ReviewTrendPoint { date: string; total: number; approved: number; rejected: number }
export interface ScoreTrendPoint { date: string; positive_score_delta: number; negative_score_delta: number; net_score_delta: number }

export interface DashboardTrends {
  generated_at: string
  days: number
  start_date: string
  end_date: string
  sub_task_created_trend: TrendPoint[]
  sub_task_completed_trend: TrendPoint[]
  review_trend: ReviewTrendPoint[]
  score_delta_trend: ScoreTrendPoint[]
  request_trend: TrendPoint[]
  activity_trend: TrendPoint[]
}

export const scoreApi = {
  leaderboard: () => api.get('/scores/leaderboard'),
  agentScore: (agentId: string) => api.get(`/scores/${agentId}`),
  agentLogs: (agentId: string, params?: { page?: number; page_size?: number }) =>
    api.get(`/scores/${agentId}/logs`, { params }),
  adjust: (data: { agent_id: string; score_delta: number; reason: string; sub_task_id?: string }) =>
    api.post('/scores/adjust', data),
}

// ── 管理端积分类型 ──

export interface AdminScoreSummary {
  total_agents: number
  positive_score_agents: number
  zero_score_agents: number
  negative_score_agents: number
  top_score: number
  average_score: number
  last_score_at: string | null
}

export interface AdminScoreLeaderboardItem {
  rank: number
  agent_id: string
  agent_name: string
  role: string
  status: string
  total_score: number
  reward_count: number
  penalty_count: number
  total_records: number
  last_score_at: string | null
  created_at: string | null
}

export interface AdminScoreLeaderboardParams {
  page?: number
  page_size?: number
  role?: string
  status?: string
  keyword?: string
  score_min?: number
  score_max?: number
  sort_by?: string
  sort_order?: string
}

export interface AdminScoreLogItem {
  id: string
  agent_id: string
  agent_name: string
  sub_task_id: string | null
  reason: string
  score_delta: number
  created_at: string | null
}

export interface AdminScoreLogParams {
  page?: number
  page_size?: number
  agent_id?: string
  sub_task_id?: string
  score_sign?: string
  keyword?: string
  sort_order?: string
}

export const adminScoreApi = {
  summary: () =>
    api.get<AdminScoreSummary>('/admin/scores/summary'),
  leaderboard: (params?: AdminScoreLeaderboardParams) =>
    api.get<AdminPageResponse<AdminScoreLeaderboardItem>>('/admin/scores/leaderboard', { params }),
  logs: (params?: AdminScoreLogParams) =>
    api.get<AdminPageResponse<AdminScoreLogItem>>('/admin/scores/logs', { params }),
  adjust: (data: { agent_id: string; score_delta: number; reason: string; sub_task_id?: string }) =>
    api.post('/admin/scores/adjust', data),
}

export const reviewApi = {
  list: (params?: { sub_task_id?: string; page?: number; page_size?: number }) =>
    api.get('/review-records', { params }),
  get: (id: string) => api.get(`/review-records/${id}`),
}

// ── 管理端审查记录类型 ──

export interface AdminReviewListItem {
  id: string
  task_id: string
  task_name: string
  module_id: string | null
  module_name: string | null
  sub_task_id: string
  sub_task_name: string
  reviewer_agent: string
  reviewer_agent_name: string | null
  round: number
  result: string
  score: number
  issues: string
  comment: string
  rework_agent: string | null
  rework_agent_name: string | null
  created_at: string | null
}

export interface AdminReviewDetail extends AdminReviewListItem {
  sub_task_description: string
  sub_task_deliverable: string
  sub_task_acceptance: string
}

export interface AdminReviewParams {
  page?: number
  page_size?: number
  task_id?: string
  sub_task_id?: string
  reviewer_agent?: string
  result?: string
  keyword?: string
  days?: number
  sort_order?: string
}

export const adminReviewApi = {
  list: (params?: AdminReviewParams) =>
    api.get<AdminPageResponse<AdminReviewListItem>>('/admin/review-records', { params }),
  get: (id: string) =>
    api.get<AdminReviewDetail>(`/admin/review-records/${id}`),
}

export const logApi = {
  list: (params?: { sub_task_id?: string; action?: string; days?: number; limit?: number }) =>
    api.get('/logs', { params }),
}

// ── 管理端活动日志类型 ──

export interface AdminActivityLogItem {
  id: string
  agent_id: string
  agent_name: string
  agent_role: string
  sub_task_id: string | null
  action: string
  summary: string
  session_id: string | null
  created_at: string | null
}

export interface AdminLogParams {
  page?: number
  page_size?: number
  agent_id?: string
  action?: string
  sub_task_id?: string
  keyword?: string
  days?: number
  sort_order?: string
}

export const adminLogApi = {
  list: (params?: AdminLogParams) =>
    api.get<AdminPageResponse<AdminActivityLogItem>>('/admin/logs', { params }),
}
