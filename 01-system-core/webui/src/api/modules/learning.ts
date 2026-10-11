import api from '../http'

export interface FailurePatternItem {
  code: string
  name: string
  triggered: number
  fixed: number
  success_rate: number
}

export interface StrategyItem {
  code: string
  name: string
  applied: number
  success: number
  success_rate: number
  avg_iterations: number
}

export interface FixResponse {
  success: boolean
  pattern_code: string
  strategy_code: string
  fix_prompt?: string
  system_prompt?: string
  message: string
}

export interface SuccessPatternItem {
  id: string
  features: Record<string, any>
  key_elements: string[]
  score: number
  usage_count: number
}

export const autoFixApi = {
  // 检测失败模式并获取修复提示词
  detectAndFix: (segmentId: string, validationResult: Record<string, any>, maxIterations = 3) =>
    api.post<FixResponse>('/auto-fix/detect', {
      segment_id: segmentId,
      validation_result: validationResult,
      max_iterations: maxIterations,
    }),

  // 记录修复结果
  recordResult: (data: {
    segment_id: string
    fixed_content: string
    final_score: number
    iterations: number
    success: boolean
  }) => api.post('/auto-fix/record-result', data),

  // 获取分析报告
  getAnalysis: () =>
    api.get<{
      failure_distribution: FailurePatternItem[]
      strategy_effectiveness: StrategyItem[]
    }>('/auto-fix/analysis'),

  // 获取推荐成功模式
  getRecommendedPatterns: (segmentType: string, limit = 3) =>
    api.get<{ patterns: SuccessPatternItem[] }>(`/auto-fix/patterns/${segmentType}`, { params: { limit } }),

  // 获取性能瓶颈
  getBottlenecks: (limit = 5) =>
    api.get<{
      bottlenecks: Array<{
        segment_id: string
        refactors: number
        avg_score: number
        pass_rate: number
        failure_dist: Record<string, number>
      }>
    }>('/auto-fix/bottlenecks', { params: { limit } }),
}

// ============================================================
// Project Learning API - 智能沉淀闭环
// ============================================================

export interface UserEditResponse {
  edit_id: string
  materialized: boolean
  material_id?: string
  improvement_score: number
  message: string
}

export interface RuleExtractionResponse {
  job_id: string
  status: string
  total_materials: number
  extracted_rules: any[]
  suggested_rule_content?: string
  confidence_score: number
}

export interface OptimizePromptResponse {
  optimized_prompt: string
  cached: boolean
  token_reduction: number
  materials_injected: string[]
  materials_count: number
}

export interface EfficiencyReportResponse {
  period_days: number
  total_tokens: number
  total_segments: number
  avg_tokens_per_segment: number
  auto_fix_success_rate: number
  total_auto_fix: number
  trend: any[]
}

export interface ProjectMaterialItem {
  id: string
  material_type: string
  title: string
  quality_score: number
  usage_count: number
  tags: string[]
  status: string
  created_at: string
}

export const projectLearningApi = {
  // 捕获用户编辑
  captureEdit: (data: {
    project_id: string
    target_type: string
    target_id: string
    before_content: string
    after_content: string
    edit_reason?: string
    session_id?: string
  }) => api.post<UserEditResponse>('/project-learning/capture-edit', data),

  // 启动规则提取
  extractRules: (projectId: string) =>
    api.post<RuleExtractionResponse>('/project-learning/extract-rules', { project_id: projectId }),

  // 应用提取的规则
  applyExtractedRule: (jobId: string, approve: boolean = true, targetScope: string = 'task') =>
    api.post('/project-learning/apply-extracted-rule', {
      job_id: jobId,
      approve,
      target_scope: targetScope,
    }),

  // 优化提示词
  optimizePrompt: (data: {
    project_id: string
    original_prompt: string
    context: Record<string, any>
  }) => api.post<OptimizePromptResponse>('/project-learning/optimize-prompt', data),

  // 获取效率报告
  getEfficiencyReport: (projectId: string, days: number = 7) =>
    api.get<EfficiencyReportResponse>(`/project-learning/efficiency-report/${projectId}`, {
      params: { days },
    }),

  // 获取学习洞察
  getInsights: (projectId: string) =>
    api.get<{ insights: any[] }>(`/project-learning/insights/${projectId}`),

  // 获取项目素材
  getMaterials: (projectId: string, params?: { material_type?: string; status?: string; limit?: number }) =>
    api.get<ProjectMaterialItem[]>(`/project-learning/materials/${projectId}`, { params }),

  // 记录生成指标
  recordMetrics: (data: {
    project_id: string
    tokens_used: number
    segment_count?: number
    auto_fix_used?: boolean
    material_applied?: boolean
  }) => api.post('/project-learning/record-metrics', data),
}

// ============================================================
// 极简自学习 API - 三明治注入法
// ============================================================

export interface LightweightOptimizeResponse {
  final_prompt: string
  user_prompt: string
  mode: string
  has_optimization: boolean
  message: string
}

export interface LightweightStatsResponse {
  total_segments: number
  current_mode: string
  input_length_saved: string
  message: string
}

export const lightweightLearningApi = {
  // 极简提示词优化（100%保留用户规则，只追加参考）
  optimize: (data: {
    project_id: string
    user_prompt: string
    segment_type: string
    episode_no: number
  }) => api.post<LightweightOptimizeResponse>('/lightweight-learning/optimize', data),

  // 记录生成结果（自动学习，无感知）
  recordGeneration: (data: {
    project_id: string
    segment_type: string
    episode_no: number
    content: string
    validation_score?: number
  }) => api.post('/lightweight-learning/record-generation', data),

  // 记录用户编辑（自动学习改进）
  recordEdit: (data: {
    project_id: string
    segment_type: string
    before_content: string
    after_content: string
  }) => api.post('/lightweight-learning/record-edit', data),

  // 获取项目学习统计
  getStats: (projectId: string) =>
    api.get<LightweightStatsResponse>(`/lightweight-learning/stats/${projectId}`),

  // ═══════════════════════════════════════════════════════════
  // 自我进化相关 API (OpenSpace AUTO-IMPROVE)
  // ═══════════════════════════════════════════════════════════

  // 获取项目自我进化状态
  getEvolutionStatus: (projectId: string) =>
    api.get<{
      project_id: string
      learning_stage: 'observing' | 'learning' | 'optimizing' | 'mature'
      total_samples: number
      high_quality_samples: number
      patterns_extracted: number
      input_savings_percent: number
      evolution_message: string
      next_milestone: {
        samples_needed: number
        description: string
      }
    }>(`/lightweight-learning/evolution/${projectId}`),

  // 获取成功模式列表
  getSuccessPatterns: (projectId: string, minQuality?: number) =>
    api.get<{
      segment_type: string
      sample_count: number
      avg_word_count: number
      word_count_range: number[]
      quality_score_avg: number
      confidence: number
      prompt_hint: string
    }[]>(`/lightweight-learning/patterns/${projectId}`, { params: { min_quality: minQuality } }),

  // 生成优化规则
  generateOptimizedRules: (projectId: string) =>
    api.post<{
      project_id: string
      rules_content: string | null
      generated_at: string
      message: string
    }>(`/lightweight-learning/generate-rules/${projectId}`),
}


// ═══════════════════════════════════════════════════════════════════════════
