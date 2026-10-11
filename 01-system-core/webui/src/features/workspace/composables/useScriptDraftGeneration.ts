import { onUnmounted, ref } from 'vue'
import { formatRuleBackedScriptStreamError, RuleBackedScriptStreamError } from './useRuleBackedScriptStream'

type StreamResult = {
  content: string
  warnings: string[]
  overflow_content?: string
  candidate_needs_user_confirmation?: boolean
  saved_as_canon?: boolean
  [key: string]: any
}

export type ScriptWorkflowStep = {
  id: string
  label: string
  status: 'pending' | 'running' | 'completed' | 'action_required' | 'blocked'
  description?: string
}

type ScriptJobStatus = {
  job_id?: string
  status?: string
  public_message?: string
  public_progress?: number
  current_workflow_step?: string
  workflow_steps?: ScriptWorkflowStep[]
  candidate_returned_to_user?: boolean
  candidate_needs_user_confirmation?: boolean
  saved_as_canon?: boolean
  user_action_required?: string
  visible_issues?: string[]
  contract_conflicts?: Array<Record<string, unknown>>
  word_count_warning?: string | null
  final_generation_contract_hash?: string
  candidate?: {
    content?: string
    char_count_excluding_punctuation?: number
    warnings?: string[]
    rag_evidence?: Array<Record<string, unknown>>
    episode_memory_card?: Record<string, unknown>
    canon_packet?: Record<string, unknown>
  }
  [key: string]: any
}

function sleep(ms: number) {
  return new Promise(resolve => setTimeout(resolve, ms))
}

function makeAbortError() {
  const error = new Error('Aborted')
  ;(error as any).name = 'AbortError'
  return error
}

const SCRIPT_DRAFT_EPISODE_TARGET_MS = 300_000
const SCRIPT_DRAFT_STAGE_TARGET_MS = 150_000
const SCRIPT_DRAFT_STREAM_TIMEOUT_MS = 600_000
const SINGLE_EPISODE_WAIT_BUDGET = {
  single_episode_target_ms: SCRIPT_DRAFT_EPISODE_TARGET_MS,
  single_episode_timeout_ms: SCRIPT_DRAFT_STREAM_TIMEOUT_MS,
  stage_target_ms: SCRIPT_DRAFT_STAGE_TARGET_MS,
}
const PUBLIC_PROGRESS_GENERATING = '正在生成本集，请稍候…'
const PUBLIC_PROGRESS_RECOVERING = '正在整理正文，请稍候…'
const PUBLIC_BLOCKED_DETAIL = '本集暂时没有生成出可用正文，请回到集纲检查主场景、冲突和角色目标后再试。'
const PUBLIC_BLOCKED_SUGGESTION = '补齐本集主场景、冲突、转折和角色变化后重新生成。'
const PUBLIC_CONTRACT_RECONCILIATION_SUGGESTION = '请确认本集到底以你的修改为准，还是以原集纲为准；确认后再重新生成。'
const PUBLIC_CANDIDATE_DETAIL = '已生成候选内容，需要人工确认后保存。'
const EMPTY_WORKFLOW_STEPS: ScriptWorkflowStep[] = []

function isWordCountWarning(value: string) {
  return /字数|净字|要求至少|要求至多/.test(String(value || ''))
}

function userFacingWarningSummary(warnings: string[]) {
  const clean = warnings.map(item => String(item || '').trim()).filter(Boolean)
  if (clean.length === 0) return ''
  if (clean.every(isWordCountWarning)) return clean[0]
  return '本次生成已放行，但仍有提醒：' + clean.slice(0, 2).join('；')
}

type LengthPolicy = {
  alreadySatisfied?: boolean
  alreadyOverflow?: boolean
  [key: string]: any
}

type GenerationFailureLog = {
  status: string
  source: string
  detail: string
  suggestion?: string
  display?: string
  public_detail?: string
  public_suggestion?: string
  retryable?: boolean
  attempt?: number
  elapsed_ms?: number
  had_streamed_content?: boolean
  streamed_chars?: number
  request_context?: Record<string, unknown>
  [key: string]: any
}

export function useScriptDraftGeneration(options: {
  ensureOutlineGatePassed: () => boolean
  persistProjectRules: () => Promise<boolean>
  getSceneContent: () => string
  setSceneContent: (content: string) => void
  ensureScriptApproved: () => Promise<boolean>
  resolveLengthPolicy: () => LengthPolicy | null
  ensureManualEditSyncReady?: () => boolean | Promise<boolean>
  buildRequest: (currentContent: string) => Record<string, unknown>
  startScriptJob: (requestPayload: Record<string, unknown>) => Promise<ScriptJobStatus>
  getScriptJobStatus: (jobId: string) => Promise<ScriptJobStatus>
  ingestWorkflowUpdates: (payload: StreamResult) => void
  refreshRuntimeSignals: () => Promise<void>
  autoSaveCurrentScene: () => Promise<boolean | void>
  recordCandidateSnapshot?: (content: string, payload: StreamResult) => Promise<boolean | void> | boolean | void
  markManualEditConsumedAfterGeneration?: () => Promise<boolean | void> | boolean | void
  recordGenerationFailure?: (payload: GenerationFailureLog) => Promise<boolean | void> | boolean | void
  scriptNetCharCount: () => number
  notify: {
    success: (message: string) => void
    error: (message: string) => void
    warning: (message: string) => void
  }
}) {
  const isGeneratingScript = ref(false)
  const scriptStreamStatus = ref('')
  const scriptWorkflowSteps = ref<ScriptWorkflowStep[]>(EMPTY_WORKFLOW_STEPS)
  let activeController: AbortController | null = null
  let stopRequested = false

  async function recordGenerationFailure(payload: GenerationFailureLog) {
    try {
      await options.recordGenerationFailure?.(payload)
    } catch {
      // 页面失败提示优先，失败日志写入不能反过来打断用户操作。
    }
  }

  function compactRequestContext(payload: Record<string, unknown> | null) {
    if (!payload) return {}
    return {
      episode_no: payload.episode_no,
      scene_no: payload.scene_no,
      mode: payload.mode,
      segment_id: payload.segment_id,
      generation_provider: payload.generation_provider,
      generation_model: payload.generation_model,
      advanced_generation_mode: payload.advanced_generation_mode,
      word_count_min: payload.word_count_min,
      word_count_max: payload.word_count_max,
      target_chars: payload.target_chars,
      research_generation_mode: payload.research_generation_mode,
      client_retry_attempt: payload.client_retry_attempt,
      current_job_id: payload.current_job_id,
    }
  }

  function stopGeneratingScript() {
    if (!activeController || activeController.signal.aborted) return
    stopRequested = true
    scriptStreamStatus.value = '正在停止生成…'
    activeController.abort()
  }

  function streamResultFromScriptJobStatus(status: ScriptJobStatus): StreamResult {
    const candidate = status.candidate || {}
    const candidateWarnings = Array.isArray(candidate.warnings)
      ? candidate.warnings.map(item => String(item || '')).filter(Boolean)
      : []
    const wordCountWarning = String(status.word_count_warning || '').trim()
    const warnings = Array.from(new Set([
      ...candidateWarnings,
      ...(wordCountWarning ? [wordCountWarning] : []),
    ]))
    return {
      content: String(candidate.content || ''),
      warnings,
      char_count_excluding_punctuation: Number(candidate.char_count_excluding_punctuation || 0),
      rag_evidence: Array.isArray(candidate.rag_evidence) ? candidate.rag_evidence : [],
      episode_memory_card: candidate.episode_memory_card || {},
      canon_packet: candidate.canon_packet || {},
      candidate_status: status.status || '',
      candidate_needs_user_confirmation: status.candidate_needs_user_confirmation !== false,
      saved_as_canon: Boolean(status.saved_as_canon),
    }
  }

  function normalizeWorkflowSteps(status: ScriptJobStatus | null | undefined): ScriptWorkflowStep[] {
    const rawSteps = Array.isArray(status?.workflow_steps) ? status.workflow_steps : []
    return rawSteps
      .map((item) => {
        const stepStatus = String(item?.status || '').trim()
        if (!['pending', 'running', 'completed', 'action_required', 'blocked'].includes(stepStatus)) return null
        const id = String(item?.id || '').trim()
        const label = String(item?.label || '').trim()
        if (!id || !label) return null
        return {
          id,
          label,
          status: stepStatus as ScriptWorkflowStep['status'],
          description: String(item?.description || '').trim(),
        }
      })
      .filter(Boolean) as ScriptWorkflowStep[]
  }

  function ingestJobPublicStatus(status: ScriptJobStatus | null | undefined) {
    const steps = normalizeWorkflowSteps(status)
    if (steps.length) scriptWorkflowSteps.value = steps
    if (status?.public_message) scriptStreamStatus.value = status.public_message
  }

  async function pollScriptJobUntilReady(jobId: string, signal?: AbortSignal): Promise<StreamResult> {
    const startedAt = Date.now()
    while (Date.now() - startedAt < SCRIPT_DRAFT_STREAM_TIMEOUT_MS) {
      if (signal?.aborted) throw makeAbortError()
      const status = await options.getScriptJobStatus(jobId)
      ingestJobPublicStatus(status)
      if (
        (status.status === 'candidate_ready' || status.status === 'candidate_review_required')
        && status.candidate?.content
      ) {
        return streamResultFromScriptJobStatus(status)
      }
      if (['blocked', 'failed', 'error'].includes(String(status.status || ''))) {
        const action = String(status.user_action_required || '').trim()
        const visibleIssues = Array.isArray(status.visible_issues)
          ? status.visible_issues.map(item => String(item || '').trim()).filter(Boolean)
          : []
        if (status.status === 'blocked' && action === 'confirm_generation_contract') {
          throw new RuleBackedScriptStreamError({
            error_code: 'confirm_generation_contract',
            detail: status.public_message || '本集生成依据存在冲突，需要先确认。',
            suggestion: visibleIssues.length ? visibleIssues.join('；') : PUBLIC_CONTRACT_RECONCILIATION_SUGGESTION,
            retryable: false,
            blocking_issues: visibleIssues,
            user_action_required: action,
            contract_conflicts: status.contract_conflicts || [],
            final_generation_contract_hash: status.final_generation_contract_hash || '',
          })
        }
        throw new RuleBackedScriptStreamError({
          error_code: `script_scene_job_${status.status || 'failed'}`,
          detail: status.public_message || PUBLIC_BLOCKED_DETAIL,
          suggestion: PUBLIC_BLOCKED_SUGGESTION,
          retryable: status.status !== 'blocked',
        })
      }
      await sleep(2000)
    }
    throw makeAbortError()
  }

  async function generateScript() {
    if (!options.ensureOutlineGatePassed()) return
    const persisted = await options.persistProjectRules()
    if (!persisted) {
      options.notify.error('项目规则同步失败，暂时无法执行测试生成')
      return
    }
    if (options.ensureManualEditSyncReady) {
      const manualEditReady = await options.ensureManualEditSyncReady()
      if (!manualEditReady) return
    }
    if (options.getSceneContent().trim()) {
      const approved = await options.ensureScriptApproved()
      if (!approved) {
        options.notify.error('当前正文仍未通过质量检查，暂时不能继续生成')
        return
      }
    }
    const lengthPolicy = options.resolveLengthPolicy()
    if (!lengthPolicy) {
      options.notify.error('当前项目未配置可用的字数规则，暂时无法执行测试生成')
      return
    }
    if (lengthPolicy.alreadySatisfied) {
      options.notify.error('当前正文净字数已经落在目标区间，请先精修或清空后再继续生成')
      return
    }
    if (lengthPolicy.alreadyOverflow) {
      options.notify.error('当前正文净字数已超过上限，请先裁剪再继续生成')
      return
    }

    isGeneratingScript.value = true
    scriptStreamStatus.value = PUBLIC_PROGRESS_GENERATING
    scriptWorkflowSteps.value = EMPTY_WORKFLOW_STEPS
    const originalContent = options.getSceneContent()
    const separator = originalContent ? '\n\n' : ''
    let streamedContent = ''
    let lastError: ReturnType<typeof formatRuleBackedScriptStreamError> | null = null
    let lastRequestPayload: Record<string, unknown> | null = null
    const generationStartedAt = Date.now()
    try {
      let streamed: StreamResult | null = null
      const maxAttempts = 2
      for (let attempt = 1; attempt <= maxAttempts; attempt += 1) {
        let streamTimeout: ReturnType<typeof setTimeout> | null = null
        let streamTimedOut = false
        try {
          activeController = new AbortController()
          streamTimeout = setTimeout(() => {
            streamTimedOut = true
            scriptStreamStatus.value = PUBLIC_PROGRESS_RECOVERING
            activeController?.abort()
          }, SCRIPT_DRAFT_STREAM_TIMEOUT_MS)
          const requestPayload = {
            ...options.buildRequest(options.getSceneContent()),
            client_retry_attempt: attempt,
            client_retry_reason: attempt > 1 ? lastError?.detail || '' : '',
          }
          lastRequestPayload = requestPayload
          streamedContent = ''
          scriptStreamStatus.value = attempt > 1 ? PUBLIC_PROGRESS_RECOVERING : PUBLIC_PROGRESS_GENERATING
          const job = await options.startScriptJob(requestPayload)
          const jobId = String(job.job_id || '')
          if (!jobId) {
            throw new RuleBackedScriptStreamError({
              error_code: 'script_scene_job_missing_id',
              detail: '后台生成任务没有返回任务编号。',
              suggestion: '请稍后重试；如果连续失败，请联系管理员查看后台任务日志。',
              retryable: true,
            })
          }
          lastRequestPayload = { ...requestPayload, current_job_id: jobId }
          ingestJobPublicStatus(job)
          streamed = job.status === 'candidate_ready' && job.candidate?.content
            ? streamResultFromScriptJobStatus(job)
            : await pollScriptJobUntilReady(jobId, activeController.signal)
          break
        } catch (error: unknown) {
          if (stopRequested || activeController?.signal.aborted || (error as any)?.name === 'AbortError') {
            options.setSceneContent(originalContent)
            if (streamTimedOut) {
              const detail = '生成超过10分钟仍未返回正文，本次已自动停止，没有保存空内容。'
              const suggestion = '请稍后重试；如果连续出现，请检查本集集纲、模型连接和参考素材记录。'
              scriptStreamStatus.value = PUBLIC_BLOCKED_DETAIL
              await recordGenerationFailure({
                status: 'timeout',
                source: 'research_chain_job_timeout',
                detail,
                suggestion,
                display: `${detail}\n建议：${suggestion}`,
                public_detail: PUBLIC_BLOCKED_DETAIL,
                public_suggestion: PUBLIC_BLOCKED_SUGGESTION,
                retryable: true,
                attempt,
                elapsed_ms: Date.now() - generationStartedAt,
                had_streamed_content: Boolean(streamedContent.trim()),
                streamed_chars: streamedContent.length,
                request_context: compactRequestContext(lastRequestPayload),
                time_budget: SINGLE_EPISODE_WAIT_BUDGET,
              })
              options.notify.error(PUBLIC_BLOCKED_DETAIL)
            } else {
              scriptStreamStatus.value = ''
              scriptWorkflowSteps.value = EMPTY_WORKFLOW_STEPS
              options.notify.warning('已停止生成，本次未完成内容没有保存。')
            }
            return
          }
          lastError = formatRuleBackedScriptStreamError(error)
          options.setSceneContent(originalContent)
          if (attempt < maxAttempts && lastError.retryable) {
            scriptStreamStatus.value = PUBLIC_PROGRESS_RECOVERING
            await sleep(900 * attempt)
            continue
          }
          throw error
        } finally {
          if (streamTimeout) clearTimeout(streamTimeout)
        }
      }
      if (!streamed) throw new Error('AI 生成失败')
      if (!String(streamed.content || '').trim()) {
        throw new RuleBackedScriptStreamError({
          error_code: 'EMPTY_SCRIPT_DRAFT',
          detail: '模型生成链路结束但没有返回可保存正文。',
          suggestion: '请检查本集集纲/主场景契约是否过窄，或先人工保存候选稿后再继续。',
          retryable: false,
        })
      }
      options.setSceneContent(originalContent + separator + streamed.content)
      await options.recordCandidateSnapshot?.(streamed.content, streamed)
      scriptStreamStatus.value = ''
      const candidateNeedsConfirmation = Boolean(streamed.candidate_needs_user_confirmation)
      if (!candidateNeedsConfirmation) {
        options.ingestWorkflowUpdates(streamed)
        await options.refreshRuntimeSignals()
      }
      const warningSummary = userFacingWarningSummary(streamed.warnings)
      if (warningSummary) options.notify.warning(warningSummary)
      if (streamed.overflow_content) {
        options.notify.warning('有部分删减内容适合顺延到下一集，请在大纲或下一集开头人工确认后再使用。')
      }
      if (candidateNeedsConfirmation) {
        scriptStreamStatus.value = [
          PUBLIC_CANDIDATE_DETAIL,
          '候选内容尚未自动保存。',
        ].join('\n')
        options.notify.warning('候选内容已放入编辑器，请确认修改后手动保存。')
        return
      }

      const saved = await options.autoSaveCurrentScene()
      if (saved === false) {
        options.notify.error('AI生成已写入编辑器，但自动保存失败。请先点击保存，再切换页面或进入下一集。')
        return
      }
      const consumed = await options.markManualEditConsumedAfterGeneration?.()
      if (consumed === false) {
        options.notify.warning('AI生成已保存，但上一集用户改稿接续状态回写失败。请刷新后确认再继续生成下一集。')
      }
      options.notify.success('AI生成完成，当前净字数 ' + options.scriptNetCharCount() + '，内容已自动保存')
    } catch (e: any) {
      const info = formatRuleBackedScriptStreamError(e)
      if (streamedContent.trim()) {
        options.setSceneContent(originalContent + separator + streamedContent)
        scriptStreamStatus.value = [
          PUBLIC_CANDIDATE_DETAIL,
          '候选内容尚未自动保存。',
        ].join('\n')
        await recordGenerationFailure({
          status: 'failed_with_candidate',
          source: 'research_chain_job_error',
          detail: info.detail,
          suggestion: info.suggestion,
          display: scriptStreamStatus.value,
          public_detail: PUBLIC_CANDIDATE_DETAIL,
          public_suggestion: '请人工确认候选内容，确认后再保存为本集正文。',
          retryable: info.retryable,
          elapsed_ms: Date.now() - generationStartedAt,
          had_streamed_content: true,
          streamed_chars: streamedContent.length,
          error_code: info.code,
          issues: info.issues,
          request_context: compactRequestContext(lastRequestPayload),
          time_budget: SINGLE_EPISODE_WAIT_BUDGET,
        })
      } else {
        const isContractReconciliation = info.code === 'confirm_generation_contract'
        const publicDetail = isContractReconciliation ? info.detail : PUBLIC_BLOCKED_DETAIL
        const publicSuggestion = isContractReconciliation ? (info.suggestion || PUBLIC_CONTRACT_RECONCILIATION_SUGGESTION) : PUBLIC_BLOCKED_SUGGESTION
        options.setSceneContent(originalContent)
        scriptStreamStatus.value = publicDetail
        await recordGenerationFailure({
          status: isContractReconciliation ? 'contract_reconciliation_required' : 'failed_empty',
          source: 'research_chain_job_error',
          detail: info.detail,
          suggestion: info.suggestion,
          display: info.display,
          public_detail: publicDetail,
          public_suggestion: publicSuggestion,
          retryable: info.retryable,
          elapsed_ms: Date.now() - generationStartedAt,
          had_streamed_content: false,
          streamed_chars: 0,
          error_code: info.code,
          issues: info.issues,
          request_context: compactRequestContext(lastRequestPayload),
          time_budget: SINGLE_EPISODE_WAIT_BUDGET,
        })
      }
      if (info.code === 'confirm_generation_contract') {
        options.notify.error(info.detail || '本集生成依据存在冲突，需要先确认。')
      } else if (info.detail && info.detail !== String(e?.message || '')) {
        options.notify.error(PUBLIC_BLOCKED_DETAIL)
      } else {
        options.notify.error(PUBLIC_BLOCKED_DETAIL)
      }
    } finally {
      activeController = null
      stopRequested = false
      isGeneratingScript.value = false
    }
  }

  onUnmounted(() => {
    stopGeneratingScript()
  })

  return {
    isGeneratingScript,
    scriptStreamStatus,
    scriptWorkflowSteps,
    generateScript,
    stopGeneratingScript,
  }
}
