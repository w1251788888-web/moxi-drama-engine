import { toChineseErrorDetail } from '@/api/http'

export type RuleBackedScriptStreamResult = {
  content: string
  warnings: string[]
  overflow_content: string
  episode_memory_card: Record<string, any>
  canon_packet: Record<string, any>
  rag_evidence: Array<Record<string, any>>
  director_blueprint: Record<string, any>
  generation_trace: Record<string, any>
}

export type RuleBackedScriptStreamErrorPayload = {
  error_code?: string
  detail?: string
  suggestion?: string
  retryable?: boolean
  stage?: string
  raw?: string
  http_status?: number
  blocking_issues?: string[]
  quality_issues?: string[]
  warnings?: string[]
  failure_analysis?: Record<string, any>
  [key: string]: any
}

export class RuleBackedScriptStreamError extends Error {
  payload: RuleBackedScriptStreamErrorPayload

  constructor(payload: RuleBackedScriptStreamErrorPayload) {
    super(String(payload.detail || payload.raw || '流式生成失败'))
    this.name = 'RuleBackedScriptStreamError'
    this.payload = payload
  }
}

function normalizeStreamErrorPayload(raw: any, fallback = '流式生成失败'): RuleBackedScriptStreamErrorPayload {
  const detail = raw?.detail
  if (detail && typeof detail === 'object') {
    return {
      ...detail,
      detail: String(detail.detail || fallback),
    }
  }
  if (raw && typeof raw === 'object') {
    return {
      ...raw,
      detail: String(raw.detail || fallback),
    }
  }
  return { detail: String(raw || fallback), retryable: true }
}

async function buildHttpErrorPayload(res: Response): Promise<RuleBackedScriptStreamErrorPayload> {
  const fallback = `HTTP ${res.status}`
  try {
    const text = await res.text()
    if (!text) return { detail: fallback, http_status: res.status, retryable: res.status >= 500 || res.status === 429 }
    const parsed = JSON.parse(text)
    const payload = normalizeStreamErrorPayload(parsed, fallback)
    payload.http_status = res.status
    return payload
  } catch {
    return { detail: fallback, http_status: res.status, retryable: res.status >= 500 || res.status === 429 }
  }
}

export function formatRuleBackedScriptStreamError(error: unknown) {
  const payload = error instanceof RuleBackedScriptStreamError
    ? error.payload
    : normalizeStreamErrorPayload((error as any)?.payload || (error as any)?.response?.data || (error as any)?.message || error)
  const detail = toChineseErrorDetail(payload.detail || payload.raw || '', '生成失败，请重试。')
  const suggestion = toChineseErrorDetail(payload.suggestion || '', '').trim()
  const code = String(payload.error_code || payload.stage || '').trim()
  const issues = [
    ...(Array.isArray(payload.blocking_issues) ? payload.blocking_issues : []),
    ...(Array.isArray(payload.quality_issues) ? payload.quality_issues : []),
  ].map(item => String(item || '').trim()).filter(Boolean)
  return {
    payload,
    detail,
    suggestion,
    code,
    retryable: payload.retryable !== false,
    issues,
    display: [
      detail,
      issues.length ? `问题：${issues.slice(0, 3).join('；')}` : '',
      suggestion ? `建议：${suggestion}` : '',
      code ? `错误码：${code}` : '',
    ].filter(Boolean).join('\n'),
  }
}

export type RuleBackedScriptStreamOptions = {
  requestPayload: Record<string, unknown>
  url: string
  token?: string | null
  userSessionToken?: string | null
  normalizeEpisodeMemoryCard?: (raw: any) => Record<string, any>
  normalizeCanonPacket?: (raw: any) => Record<string, any>
  onToken?: (token: string, aggregate: string) => void
  onProgress?: (message: string) => void
  signal?: AbortSignal
}

export async function streamRuleBackedScript({
  requestPayload,
  url,
  token,
  userSessionToken,
  normalizeEpisodeMemoryCard = raw => raw && typeof raw === 'object' ? raw : {},
  normalizeCanonPacket = raw => raw && typeof raw === 'object' ? raw : {},
  onToken,
  onProgress,
  signal,
}: RuleBackedScriptStreamOptions): Promise<RuleBackedScriptStreamResult> {
  const authHeaders: Record<string, string> = userSessionToken
    ? { 'X-User-Session': userSessionToken }
    : token
      ? { 'X-Admin-Token': token }
      : {}
  const res = await fetch(url, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...authHeaders,
      Accept: 'text/event-stream',
    },
    body: JSON.stringify(requestPayload),
    signal,
  })
  if (!res.ok || !res.body) {
    throw new RuleBackedScriptStreamError(await buildHttpErrorPayload(res))
  }

  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  let content = ''
  let warnings: string[] = []
  let overflowContent = ''
  let episodeMemoryCard: Record<string, any> = {}
  let resolvedCanonPacket: Record<string, any> = {}
  let ragEvidence: Array<Record<string, any>> = []
  let directorBlueprint: Record<string, any> = {}
  let generationTrace: Record<string, any> = {}

  const processChunk = (chunk: string) => {
    buffer += chunk
    const parts = buffer.split('\n\n')
    buffer = parts.pop() ?? ''

    for (const part of parts) {
      const lines = part.trim().split('\n')
      let eventType = 'message'
      let dataLine = ''
      for (const line of lines) {
        if (line.startsWith('event: ')) eventType = line.slice(7).trim()
        if (line.startsWith('data: ')) dataLine = line.slice(6).trim()
      }
      if (!dataLine) continue
      const data = JSON.parse(dataLine)
      if (eventType === 'token') {
        const streamedToken = String(data.text || '')
        content += streamedToken
        onToken?.(streamedToken, content)
      } else if (eventType === 'progress') {
        onProgress?.(String(data.message || ''))
      } else if (eventType === 'error') {
        throw new RuleBackedScriptStreamError(normalizeStreamErrorPayload(data))
      } else if (eventType === 'done') {
        content = String(data.content || content || '')
        overflowContent = String((data as any).overflow_content || '')
        warnings = Array.isArray(data.warnings) ? data.warnings.map((item: unknown) => String(item || '')) : []
        episodeMemoryCard = normalizeEpisodeMemoryCard((data as any).episode_memory_card)
        resolvedCanonPacket = normalizeCanonPacket((data as any).canon_packet)
        ragEvidence = Array.isArray((data as any).rag_evidence)
          ? (data as any).rag_evidence.filter((item: unknown) => item && typeof item === 'object')
          : []
        directorBlueprint = (data as any).director_blueprint && typeof (data as any).director_blueprint === 'object'
          ? (data as any).director_blueprint
          : {}
        generationTrace = (data as any).generation_trace && typeof (data as any).generation_trace === 'object'
          ? (data as any).generation_trace
          : {}
      }
    }
  }

  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    processChunk(decoder.decode(value, { stream: true }))
  }
  processChunk(decoder.decode())

  return {
    content,
    warnings,
    overflow_content: overflowContent,
    episode_memory_card: episodeMemoryCard,
    canon_packet: resolvedCanonPacket,
    rag_evidence: ragEvidence,
    director_blueprint: directorBlueprint,
    generation_trace: generationTrace,
  }
}
