import axios from 'axios'
import { useAuthStore } from '@/stores/auth'

export interface AiErrorPayload {
  error_code: string
  detail: string
  suggestion: string
  raw?: string
}

const AI_ERROR_CODES = new Set([
  'config_missing',
  'auth_failed',
  'rate_limited',
  'context_too_long',
  'output_truncated',
  'network_error',
  'upstream_error',
  'generation_failed',
])

export function extractAiError(error: unknown): AiErrorPayload | null {
  // axios 错误形态：error.response.data.{error_code, detail, suggestion}
  const data = (error as { response?: { data?: any } } | undefined)?.response?.data
  if (data && typeof data === 'object' && typeof data.error_code === 'string' && AI_ERROR_CODES.has(data.error_code)) {
    return {
      error_code: data.error_code,
      detail: typeof data.detail === 'string' ? data.detail : 'AI 生成失败',
      suggestion: typeof data.suggestion === 'string' ? data.suggestion : '请稍后重试。',
      raw: typeof data.raw === 'string' ? data.raw : undefined,
    }
  }
  return null
}

export function formatAiErrorMessage(payload: AiErrorPayload): string {
  return `${toChineseErrorDetail(payload.detail, 'AI 生成失败')}\n${toChineseErrorDetail(payload.suggestion, '请稍后重试，或联系管理员检查模型配置。')}`
}

export function formatAccessErrorMessage(error: unknown): string | null {
  const response = (error as { response?: { status?: number; data?: { detail?: string } } } | undefined)?.response
  const status = response?.status
  const detail = response?.data?.detail || (error as { message?: string } | undefined)?.message || ''
  if (status === 402) {
    return `额度不足：${detail || '当前账号余额不足'}。请前往「我的账号」查看余额，或联系管理员充值。`
  }
  if (status === 403) {
    if (detail.includes('高级生成权限') || detail.includes('未开通高级生成') || detail.includes('科研生成权限')) {
      return `权限未开通：${detail}。请联系管理员开启科研生成权限。`
    }
    if (detail.includes('无权访问') || detail.includes('权限') || detail.includes('登录')) {
      return `访问受限：${detail || '当前账号没有权限访问该内容'}。请确认登录账号是否正确。`
    }
    return `访问受限：${detail || '当前账号没有权限执行此操作'}。`
  }
  return null
}

function hasChinese(text: string): boolean {
  return /[\u4e00-\u9fff]/.test(text)
}

function stringifyErrorDetail(value: unknown): string {
  if (typeof value === 'string') return value
  if (value == null) return ''
  if (typeof value === 'object') {
    const detail = (value as { detail?: unknown; message?: unknown; error?: unknown }).detail
      || (value as { message?: unknown }).message
      || (value as { error?: unknown }).error
    if (typeof detail === 'string') return detail
    try {
      return JSON.stringify(value)
    } catch {
      return ''
    }
  }
  return String(value)
}

export function toChineseErrorDetail(raw: unknown, fallback = '请稍后重试'): string {
  const text = stringifyErrorDetail(raw).trim()
  if (!text) return fallback
  if (hasChinese(text)) return text

  const lower = text.toLowerCase()
  if (
    lower.includes('timeout')
    || lower.includes('timed out')
    || lower.includes('exceeded')
    || lower.includes('econnaborted')
    || lower.includes('etimedout')
    || lower.includes('abort')
  ) {
    return '请求等待时间过长，请稍后重试；如果是长篇生成，请分批生成或联系管理员检查模型响应速度。'
  }
  if (
    lower.includes('failed to fetch')
    || lower.includes('network error')
    || lower.includes('load failed')
    || lower.includes('err_network')
    || lower.includes('connection')
    || lower.includes('connecterror')
  ) {
    return '网络连接失败，请检查网络是否正常，或联系管理员确认服务器和模型中转站是否在线。'
  }
  if (lower.includes('rate limit') || lower.includes('too many requests') || lower.includes('429')) {
    return '模型服务请求过于频繁，请稍后再试，或联系管理员切换模型通道。'
  }
  if (lower.includes('unauthorized') || lower.includes('invalid api key') || lower.includes('401')) {
    return '模型密钥无效或权限不足，请联系管理员检查模型配置。'
  }
  if (lower.includes('forbidden') || lower.includes('403')) {
    return '当前账号没有权限执行此操作，请确认登录状态或联系管理员。'
  }
  if (lower.includes('not found') || lower.includes('404')) {
    return '请求的内容不存在或已被删除，请刷新页面后重试。'
  }
  if (lower.includes('context length') || lower.includes('maximum context') || lower.includes('token')) {
    return '输入内容太长，模型一次处理不完，请缩短文本或分段生成。'
  }
  if (lower.includes('output_truncated') || lower.includes('finish_reason') || lower.includes('finish reason')) {
    return '模型输出被截断，内容不完整；请分阶段确认或减少单次生成内容。'
  }
  if (lower.includes('json') || lower.includes('parse') || lower.includes('syntaxerror')) {
    return '服务返回格式异常，请重试；如果多次出现，请联系管理员检查模型返回内容。'
  }
  if (lower.includes('internal server error') || lower.includes('server error') || lower.includes('500')) {
    return '服务器处理失败，请稍后重试；如果反复出现，请联系管理员查看后台日志。'
  }
  if (lower.includes('bad gateway') || lower.includes('502') || lower.includes('503') || lower.includes('504')) {
    return '模型服务或中转站暂时不可用，请稍后重试，或联系管理员切换模型。'
  }
  if (lower.includes('empty') || lower.includes('no content')) {
    return '模型没有返回可用内容，请重试或换一个更明确的输入。'
  }
  return fallback
}

export function formatUserFacingErrorMessage(error: unknown, fallbackPrefix = '操作失败'): string {
  const aiErr = extractAiError(error)
  if (aiErr) return formatAiErrorMessage(aiErr)

  const accessErr = formatAccessErrorMessage(error)
  if (accessErr) return accessErr

  const response = (error as { response?: { status?: number; data?: unknown } } | undefined)?.response
  const data = response?.data
  const detail = stringifyErrorDetail(data) || (error as { message?: string } | undefined)?.message || ''
  const status = response?.status
  const statusFallback = status && status >= 500
    ? '服务器处理失败，请稍后重试；如果反复出现，请联系管理员查看后台日志。'
    : '请稍后重试'
  return `${fallbackPrefix}：${toChineseErrorDetail(detail, statusFallback)}`
}

/**
 * 统一通知 AI/接口错误。
 * - 如果后端返回的是结构化 AI 错误（含 error_code），用 detail+suggestion 两行展示
 * - 否则回退到 fallbackPrefix + 后端 detail / e.message
 *
 * 用法：catch (e) { notifyApiError(toast.error, e, '保存失败') }
 */
export function notifyApiError(
  notify: (msg: string) => void,
  error: unknown,
  fallbackPrefix: string,
): void {
  const aiErr = extractAiError(error)
  if (aiErr) {
    notify(formatAiErrorMessage(aiErr))
    return
  }
  const accessErr = formatAccessErrorMessage(error)
  if (accessErr) {
    notify(accessErr)
    return
  }
  notify(formatUserFacingErrorMessage(error, fallbackPrefix))
}

const api = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || '/api',
  timeout: 30000,
})

api.interceptors.request.use((config) => {
  const auth = useAuthStore()
  if (auth.userSession?.session_token) {
    config.headers['X-User-Session'] = auth.userSession.session_token
  } else if (auth.token) {
    config.headers['X-Admin-Token'] = auth.token
  }
  return config
})

let _apiAuthRedirecting = false
function responseDetail(error: unknown): string {
  return (error as { response?: { data?: { detail?: string } } } | undefined)?.response?.data?.detail || ''
}

function isAdminSessionFailure(detail: string): boolean {
  return detail.includes('管理员 Token') || detail.includes('管理员 session token')
}

function isUserSessionFailure(detail: string): boolean {
  return (
    detail.includes('用户 Session')
    || detail.includes('用户密钥无效')
    || detail.includes('请先登录前台用户账号')
    || detail.includes('当前账号不可用，请重新登录')
  )
}

api.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 403 && !error.config?.url?.includes('/admin/login')) {
      const auth = useAuthStore()
      const detail = responseDetail(error)
      if (auth.token && isAdminSessionFailure(detail)) {
        auth.clearAdminToken()
      }
      if (isUserSessionFailure(detail) && auth.userSession) {
        auth.clearUserSession()
      }
      if (!auth.token && !auth.userSession && !_apiAuthRedirecting && window.location.pathname !== '/login') {
        _apiAuthRedirecting = true
        window.location.href = '/login'
      }
    }
    return Promise.reject(error)
  },
)

export const v2Api = axios.create({
  baseURL: '/api/v2',
  timeout: 30000,
})

v2Api.interceptors.request.use((config) => {
  const auth = useAuthStore()
  if (auth.userSession?.session_token) {
    config.headers['X-User-Session'] = auth.userSession.session_token
  } else if (auth.token) {
    config.headers['X-Admin-Token'] = auth.token
  }
  return config
})

let _v2AuthRedirecting = false
v2Api.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 403) {
      const auth = useAuthStore()
      const detail = responseDetail(error)
      if (auth.token && isAdminSessionFailure(detail)) {
        auth.clearAdminToken()
      }
      if (isUserSessionFailure(detail) && auth.userSession) {
        auth.clearUserSession()
      }
      if (!auth.token && !auth.userSession && !_v2AuthRedirecting && window.location.pathname !== '/login') {
        _v2AuthRedirecting = true
        window.location.href = '/login'
      }
    }
    return Promise.reject(error)
  },
)

export default api
