import api from '../http'

export interface AiHealthResult {
  ok: boolean
  detail: string
  latency_ms: number
}

/**
 * 探活当前 LLM 配置是否真的连通。
 * 后端会向配置的 base_url 发一个 max_tokens=1 的最小请求，5 秒超时。
 * 前端用法：分镜 / 剧本生成等 LLM-依赖页面挂载时调用，
 *   ok=false 时直接禁用相关按钮 + 显示 detail，避免用户死等。
 */
export const aiHealthApi = {
  check: () => api.get<AiHealthResult>('/admin/ai/health', { timeout: 8_000 }),
}
