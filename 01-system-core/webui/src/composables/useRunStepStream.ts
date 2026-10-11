/**
 * useRunStepStream — 流式生成短剧写作步骤
 *
 * 用法：
 * ```ts
 * const { run, tokens, fullText, isRunning, isDone, error } = useRunStepStream()
 * await run(sessionId, 'concept')
 * ```
 *
 * 事件流协议（SSE）：
 *   event: token   { text: string }          — 实时 token
 *   event: progress { message: string }      — 进度文字
 *   event: done    { step_id, context_output, full_output, updated_at } — 完成
 *   event: error   { detail: string }        — 失败
 */
import { getCurrentInstance, onBeforeUnmount, ref, readonly } from 'vue'
import type { ShortDramaStepId, ShortDramaStepResult } from '@/api/client'
import { useAuthStore } from '@/stores/auth'

export interface RunStepStreamOptions {
  temperature?: number
  draft_episode?: number
  onToken?: (token: string) => void
  onProgress?: (message: string) => void
  onDone?: (result: ShortDramaStepResult) => void
  onError?: (detail: string) => void
}

export function useRunStepStream() {
  const tokens = ref<string[]>([])
  const fullText = ref('')
  const progressMessage = ref('')
  const isRunning = ref(false)
  const isDone = ref(false)
  const error = ref<string | null>(null)
  const result = ref<ShortDramaStepResult | null>(null)
  let activeController: AbortController | null = null
  let activeRunId = 0

  function clearState() {
    tokens.value = []
    fullText.value = ''
    progressMessage.value = ''
    isRunning.value = false
    isDone.value = false
    error.value = null
    result.value = null
  }

  function cancel() {
    const controller = activeController
    if (!controller) return
    activeController = null
    activeRunId += 1
    controller.abort()
    isRunning.value = false
  }

  function reset() {
    cancel()
    clearState()
  }

  async function run(
    sessionId: string,
    stepId: ShortDramaStepId,
    options: RunStepStreamOptions = {},
  ): Promise<ShortDramaStepResult | null> {
    cancel()
    clearState()
    isRunning.value = true

    const auth = useAuthStore()
    const controller = new AbortController()
    activeController = controller
    const runId = ++activeRunId
    const isCurrentRun = () => activeController === controller && activeRunId === runId && !controller.signal.aborted
    const params = new URLSearchParams({ step_id: stepId })
    if (options.temperature != null) params.set('temperature', String(options.temperature))
    if (options.draft_episode != null) params.set('draft_episode', String(options.draft_episode))

    const url = `/api/admin/short-drama/sessions/${sessionId}/run-step-stream?${params}`

    return new Promise((resolve, reject) => {
      // fetch + ReadableStream — 比 EventSource 更灵活（支持自定义请求头）
      fetch(url, {
        signal: controller.signal,
        headers: {
          'X-Admin-Token': auth.token ?? '',
          Accept: 'text/event-stream',
        },
      })
        .then((res) => {
          if (!res.ok || !res.body) {
            throw new Error(`HTTP ${res.status}`)
          }

          const reader = res.body.getReader()
          const decoder = new TextDecoder()
          let buffer = ''

          function processChunk(chunk: string) {
            if (!isCurrentRun()) return
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

              try {
                const data = JSON.parse(dataLine)

                if (eventType === 'token') {
                  const token: string = data.text ?? ''
                  if (!isCurrentRun()) return
                  tokens.value.push(token)
                  fullText.value += token
                  options.onToken?.(token)
                } else if (eventType === 'progress') {
                  if (!isCurrentRun()) return
                  progressMessage.value = data.message ?? ''
                  options.onProgress?.(progressMessage.value)
                } else if (eventType === 'done') {
                  if (!isCurrentRun()) return
                  const stepResult = data as ShortDramaStepResult
                  result.value = stepResult
                  isDone.value = true
                  isRunning.value = false
                  activeController = null
                  options.onDone?.(stepResult)
                  resolve(stepResult)
                } else if (eventType === 'error') {
                  if (!isCurrentRun()) return
                  error.value = data.detail ?? '生成失败'
                  isRunning.value = false
                  activeController = null
                  options.onError?.(error.value!)
                  reject(new Error(error.value!))
                }
              } catch {
                // JSON 解析失败，跳过
              }
            }
          }

          function pump(): Promise<void> {
            return reader.read().then(({ done, value }) => {
              if (!isCurrentRun()) {
                void reader.cancel()
                resolve(null)
                return
              }
              if (done) {
                isRunning.value = false
                activeController = null
                if (!isDone.value && !error.value) {
                  resolve(result.value)
                }
                return
              }
              processChunk(decoder.decode(value, { stream: true }))
              return pump()
            })
          }

          pump().catch((err) => {
            if (controller.signal.aborted || !isCurrentRun()) {
              resolve(null)
              return
            }
            error.value = String(err)
            isRunning.value = false
            activeController = null
            reject(err)
          })
        })
        .catch((err) => {
          if (controller.signal.aborted || !isCurrentRun()) {
            resolve(null)
            return
          }
          error.value = String(err)
          isRunning.value = false
          activeController = null
          reject(err)
        })
    })
  }

  if (getCurrentInstance()) {
    onBeforeUnmount(cancel)
  }

  return {
    run,
    cancel,
    reset,
    tokens: readonly(tokens),
    fullText: readonly(fullText),
    progressMessage: readonly(progressMessage),
    isRunning: readonly(isRunning),
    isDone: readonly(isDone),
    error: readonly(error),
    result: readonly(result),
  }
}
