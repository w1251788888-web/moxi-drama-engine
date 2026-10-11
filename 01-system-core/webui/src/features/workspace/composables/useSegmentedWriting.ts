import { computed, ref } from 'vue'
import { formatUserFacingErrorMessage } from '@/api/http'
import { formatRuleBackedScriptStreamError } from './useRuleBackedScriptStream'

export const SEGMENT_DEFS = [
  { id: 'hook', label: '钩子段', desc: '开局钩子', target: 250 },
  { id: 'validation', label: '验证段', desc: '承接推进', target: 300 },
  { id: 'explosion', label: '爆发段', desc: '冲突爆发', target: 350 },
  { id: 'resolution', label: '收尾段', desc: '余波悬念', target: 300 },
] as const

export type SegmentId = typeof SEGMENT_DEFS[number]['id']
export type LineOrigin = 'ai-original' | 'ai-revised' | 'user-edited'

export interface SegmentStep {
  id: string
  label: string
  desc: string
  target: number
  status: 'pending' | 'generating' | 'reviewing' | 'confirmed' | 'error'
  versionA: string
  versionB: string
  activeVersion: 'A' | 'B'
  editedContent: string
  _editSnapshot: string
  lineOrigins: LineOrigin[]
  editMode: boolean
  suggestions: string[]
  isSuggesting: boolean
  patchInstruction: string
  patchSelectedText: string
  isPatching: boolean
  isPatchPanelOpen: boolean
  repairAttempts: number
  isGeneratingVariant: boolean
  generationAttempts: number
  lastErrorDetail: string
  lastErrorSuggestion: string
  lastErrorCode: string
  lastErrorIssues: string[]
}

export type SegmentStreamResult = {
  content: string
  warnings: string[]
}

export type SegmentRepairAnalysis = {
  repair_scope?: string
  rollback_recommendation?: string
  root_cause?: string
  fix_strategy?: string
  [key: string]: any
}

export function createEmptySegmentSteps(): SegmentStep[] {
  return SEGMENT_DEFS.map(d => ({
    ...d,
    status: 'pending',
    versionA: '',
    versionB: '',
    activeVersion: 'A' as const,
    editedContent: '',
    _editSnapshot: '',
    lineOrigins: [] as LineOrigin[],
    editMode: false,
    suggestions: [],
    isSuggesting: false,
    patchInstruction: '',
    patchSelectedText: '',
    isPatching: false,
    isPatchPanelOpen: false,
    repairAttempts: 0,
    isGeneratingVariant: false,
    generationAttempts: 0,
    lastErrorDetail: '',
    lastErrorSuggestion: '',
    lastErrorCode: '',
    lastErrorIssues: [],
  }))
}

export function initStepContent(step: SegmentStep, content: string) {
  step.editedContent = content
  step._editSnapshot = content
  step.lineOrigins = content.split('\n').map(() => 'ai-original' as LineOrigin)
  step.repairAttempts = 0
  clearSegmentError(step)
}

function clearSegmentError(step: SegmentStep) {
  step.lastErrorDetail = ''
  step.lastErrorSuggestion = ''
  step.lastErrorCode = ''
  step.lastErrorIssues = []
}

function applySegmentError(step: SegmentStep, error: unknown) {
  const info = formatRuleBackedScriptStreamError(error)
  step.lastErrorDetail = info.detail
  step.lastErrorSuggestion = info.suggestion
  step.lastErrorCode = info.code
  step.lastErrorIssues = info.issues
  return info
}

function sleep(ms: number) {
  return new Promise(resolve => setTimeout(resolve, ms))
}

export function updateStreamingStepPreview(step: SegmentStep, content: string) {
  step.editedContent = content
  step._editSnapshot = content
  step.lineOrigins = content.split('\n').map(() => 'ai-original' as LineOrigin)
}

function _isSegmentStatus(value: unknown): value is SegmentStep['status'] {
  return value === 'pending'
    || value === 'generating'
    || value === 'reviewing'
    || value === 'confirmed'
    || value === 'error'
}

function _isSegmentVersion(value: unknown): value is SegmentStep['activeVersion'] {
  return value === 'A' || value === 'B'
}

function _isLineOrigin(value: unknown): value is LineOrigin {
  return value === 'ai-original' || value === 'ai-revised' || value === 'user-edited'
}

export function applyAiReplacement(step: SegmentStep, selectedText: string, replacement: string) {
  if (!step.editedContent.includes(selectedText)) return false
  const before = step.editedContent
  const after = before.replace(selectedText, replacement)
  const beforeLines = before.split('\n')
  const afterLines = after.split('\n')
  step.lineOrigins = afterLines.map((line, i) => {
    if (i < beforeLines.length && beforeLines[i] === line) return step.lineOrigins[i] ?? 'ai-original'
    return 'ai-revised'
  })
  step.editedContent = after
  step.isPatchPanelOpen = false
  step.patchInstruction = ''
  step.patchSelectedText = ''
  return true
}

export function replaceStepWithRevisedContent(step: SegmentStep, content: string) {
  step.editedContent = content
  step._editSnapshot = content
  step.lineOrigins = content.split('\n').map(() => 'ai-revised' as LineOrigin)
  step.status = 'reviewing'
}

export function buildSegmentRepairInstruction({
  blockingIssues,
  fixStrategy,
}: {
  blockingIssues: string[]
  fixStrategy: string
}) {
  return [
    '只修当前这一段，不要重写已确认的前文，也不要改动剧情主干。',
    blockingIssues.length ? `优先修掉这些阻断项：${blockingIssues.slice(0, 4).join('；')}` : '',
    fixStrategy || '优先局部修复格式、字数或单句表达问题。',
  ].filter(Boolean).join('\n')
}

export function useSegmentedWriting(options?: {
  loadSuggestions?: (step: SegmentStep) => void
  patchSceneText?: (payload: {
    full_text: string
    selected_text: string
    instruction: string
  }) => Promise<{ replacement: string }>
  notify?: {
    success: (message: string) => void
    error: (message: string) => void
    warning: (message: string) => void
  }
  buildSegmentRequest?: (step: SegmentStep, confirmedContent: string) => Record<string, unknown>
  streamSegment?: (
    requestPayload: Record<string, unknown>,
    onToken: (token: string, aggregate: string) => void,
    onProgress: (message: string) => void,
  ) => Promise<SegmentStreamResult>
  recoverLatestSegmentCandidate?: (idx: number, step: SegmentStep) => Promise<SegmentStreamResult | null | undefined>
  onSegmentProgress?: (message: string) => void
  onAllSegmentsComplete?: () => Promise<void> | void
  onConfirmedContentChanged?: (content: string) => void
  onSegmentDraftReady?: (idx: number, content: string) => Promise<void> | void
  approveSegment?: (idx: number) => Promise<boolean>
  approveFullScript?: (deepAudit: boolean) => Promise<boolean>
  afterSegmentConfirmed?: (deepAudit: boolean) => Promise<void> | void
  getFailureAnalysis?: () => SegmentRepairAnalysis
  getBlockingIssues?: () => string[]
  allowAutomaticSegmentPatch?: boolean
  ensureOutlineGatePassed?: () => boolean
  persistProjectRules?: () => Promise<boolean>
  ensureManualEditSyncReady?: () => boolean | Promise<boolean>
  getSceneContent?: () => string
  resolveFirstSegmentLengthPolicy?: () => any | null
}) {
  const segmentSteps = ref<SegmentStep[]>(createEmptySegmentSteps())
  const isSegmentGenerating = ref(false)
  const showSegmentPanel = ref(false)
  const currentSegmentIdx = ref(-1)
  const currentSegmentStep = computed<SegmentStep | null>(() => segmentSteps.value[currentSegmentIdx.value] ?? null)

  function resetSegments() {
    segmentSteps.value = createEmptySegmentSteps()
    currentSegmentIdx.value = -1
  }

  function hasSegmentProgress() {
    return segmentSteps.value.some(step => {
      return step.status !== 'pending'
        || Boolean(step.versionA || step.versionB || step.editedContent.trim())
    })
  }

  function serializeSegmentProgress() {
    return {
      current_segment_idx: currentSegmentIdx.value,
      show_panel: showSegmentPanel.value,
      has_progress: hasSegmentProgress(),
      steps: segmentSteps.value.map(step => ({
        id: step.id,
        status: step.status,
        versionA: step.versionA,
        versionB: step.versionB,
        activeVersion: step.activeVersion,
        editedContent: step.editedContent,
        lineOrigins: step.lineOrigins,
        editMode: step.editMode,
        suggestions: step.suggestions,
        repairAttempts: step.repairAttempts,
        generationAttempts: step.generationAttempts,
        lastErrorDetail: step.lastErrorDetail,
        lastErrorSuggestion: step.lastErrorSuggestion,
        lastErrorCode: step.lastErrorCode,
        lastErrorIssues: step.lastErrorIssues,
      })),
    }
  }

  function hydrateSegmentProgress(raw: any) {
    if (!raw || typeof raw !== 'object' || !Array.isArray(raw.steps)) return false
    const nextSteps = createEmptySegmentSteps()
    for (const step of nextSteps) {
      const saved = raw.steps.find((item: any) => String(item?.id || '') === step.id)
      if (!saved || typeof saved !== 'object') continue
      step.status = _isSegmentStatus(saved.status) ? saved.status : step.status
      if (step.status === 'generating') step.status = 'reviewing'
      step.versionA = String(saved.versionA || '')
      step.versionB = String(saved.versionB || '')
      step.activeVersion = _isSegmentVersion(saved.activeVersion) ? saved.activeVersion : 'A'
      step.editedContent = String(saved.editedContent || '')
      step._editSnapshot = step.editedContent
      step.lineOrigins = Array.isArray(saved.lineOrigins)
        ? saved.lineOrigins.map((item: unknown) => _isLineOrigin(item) ? item : 'ai-original')
        : step.editedContent.split('\n').map(() => 'ai-original' as LineOrigin)
      step.editMode = Boolean(saved.editMode)
      step.suggestions = Array.isArray(saved.suggestions) ? saved.suggestions.map((item: any) => String(item || '')).filter(Boolean).slice(0, 8) : []
      step.repairAttempts = Math.max(0, Number(saved.repairAttempts || 0))
      step.generationAttempts = Math.max(0, Number(saved.generationAttempts || 0))
      step.lastErrorDetail = String(saved.lastErrorDetail || '')
      step.lastErrorSuggestion = String(saved.lastErrorSuggestion || '')
      step.lastErrorCode = String(saved.lastErrorCode || '')
      step.lastErrorIssues = Array.isArray(saved.lastErrorIssues) ? saved.lastErrorIssues.map((item: any) => String(item || '')).filter(Boolean).slice(0, 8) : []
    }
    segmentSteps.value = nextSteps
    const savedIdx = Math.round(Number(raw.current_segment_idx))
    currentSegmentIdx.value = Number.isFinite(savedIdx)
      ? Math.max(-1, Math.min(nextSteps.length - 1, savedIdx))
      : findSegmentResumeIndex()
    showSegmentPanel.value = Boolean(raw.show_panel) && hasSegmentProgress()
    isSegmentGenerating.value = false
    return hasSegmentProgress()
  }

  function findSegmentResumeIndex() {
    const activeIdx = segmentSteps.value.findIndex(step =>
      step.status === 'generating'
      || step.status === 'reviewing'
      || step.status === 'error',
    )
    if (activeIdx >= 0) return activeIdx
    const pendingIdx = segmentSteps.value.findIndex(step => step.status === 'pending')
    if (pendingIdx >= 0) return pendingIdx
    return segmentSteps.value.length
  }

  function confirmedSegmentContent() {
    return segmentSteps.value
      .filter(step => step.status === 'confirmed')
      .map(step => step.editedContent)
      .join('\n\n')
  }

  function confirmedSegmentContentBefore(idx: number) {
    return segmentSteps.value
      .filter((step, stepIdx) => stepIdx < idx && step.status === 'confirmed')
      .map(step => step.editedContent)
      .join('\n\n')
  }

  function composeSegmentDraftContent(idx: number, draftContent: string) {
    return [
      confirmedSegmentContentBefore(idx),
      draftContent,
    ].map(item => item.trim()).filter(Boolean).join('\n\n')
  }

  function syncSegmentDraftContent(idx: number, draftContent: string) {
    options?.onConfirmedContentChanged?.(composeSegmentDraftContent(idx, draftContent))
  }

  async function recoverLatestCandidateIntoSegment(idx: number, reason: string) {
    const step = segmentSteps.value[idx]
    if (!step || !options?.recoverLatestSegmentCandidate) return false
    try {
      const result = await options.recoverLatestSegmentCandidate(idx, step)
      const content = String(result?.content || '').trim()
      if (!content) return false

      showSegmentPanel.value = true
      currentSegmentIdx.value = idx
      isSegmentGenerating.value = false
      step.versionA = content
      step.versionB = ''
      step.activeVersion = 'A'
      step.isGeneratingVariant = false
      step.editMode = false
      step.isPatching = false
      step.isPatchPanelOpen = false
      initStepContent(step, content)
      step.status = 'reviewing'
      clearSegmentError(step)
      syncSegmentDraftContent(idx, content)

      const warnings = Array.isArray(result?.warnings)
        ? result.warnings.map(item => String(item || '').trim()).filter(Boolean)
        : []
      if (warnings.length > 0) {
        options.notify?.warning(`${step.label}已从后台恢复候选，但仍有提醒：${warnings.slice(0, 2).join('；')}`)
      }
      options.onSegmentProgress?.('后台候选已恢复，请确认后继续下一段')
      options.loadSuggestions?.(step)
      await options.onSegmentDraftReady?.(idx, content)
      return true
    } catch {
      return false
    }
  }

  async function recoverLatestCandidateForSegment(idx: number) {
    return recoverLatestCandidateIntoSegment(idx, 'manual_recover')
  }

  function resetSegmentsFrom(startIdx: number) {
    for (let i = startIdx; i < segmentSteps.value.length; i += 1) {
      const step = segmentSteps.value[i]
      if (!step) continue
      step.status = 'pending'
      step.versionA = ''
      step.versionB = ''
      step.activeVersion = 'A'
      step.editedContent = ''
      step._editSnapshot = ''
      step.lineOrigins = []
      step.editMode = false
      step.suggestions = []
      step.patchInstruction = ''
      step.patchSelectedText = ''
      step.isPatching = false
      step.isPatchPanelOpen = false
      step.repairAttempts = 0
      step.isGeneratingVariant = false
      step.generationAttempts = 0
      clearSegmentError(step)
    }
    currentSegmentIdx.value = Math.max(-1, startIdx - 1)
    options?.onConfirmedContentChanged?.(confirmedSegmentContent())
  }

  function hasUnconfirmedPriorSegment(idx: number) {
    return segmentSteps.value.some((step, stepIdx) => {
      if (stepIdx >= idx) return false
      return Boolean(step.editedContent.trim()) && step.status !== 'confirmed'
    })
  }

  function firstUnconfirmedPriorSegmentIndex(idx: number) {
    return segmentSteps.value.findIndex((step, stepIdx) => {
      if (stepIdx >= idx) return false
      return Boolean(step.editedContent.trim()) && step.status !== 'confirmed'
    })
  }

  function markSegmentConfirmedForNextRequest(idx: number) {
    const liveStep = segmentSteps.value[idx]
    if (!liveStep) return false
    if (liveStep.editMode) segmentExitEdit(liveStep)
    liveStep.status = 'confirmed'
    currentSegmentIdx.value = Math.max(currentSegmentIdx.value, idx)
    options?.onConfirmedContentChanged?.(confirmedSegmentContent())
    return true
  }

  function segmentSwitchVersion(step: SegmentStep, ver: 'A' | 'B') {
    step.activeVersion = ver
    const content = ver === 'A' ? step.versionA : step.versionB
    initStepContent(step, content)
    step.suggestions = []
    const idx = segmentSteps.value.indexOf(step)
    if (idx >= 0) syncSegmentDraftContent(idx, content)
    options?.loadSuggestions?.(step)
  }

  function segmentEnterEdit(step: SegmentStep) {
    step._editSnapshot = step.editedContent
    step.editMode = true
  }

  function segmentExitEdit(step: SegmentStep) {
    const beforeLines = step._editSnapshot.split('\n')
    const afterLines = step.editedContent.split('\n')
    step.lineOrigins = afterLines.map((line, i) => {
      if (i < beforeLines.length && beforeLines[i] === line) return step.lineOrigins[i] ?? 'ai-original'
      return 'user-edited'
    })
    step.editMode = false
    const idx = segmentSteps.value.indexOf(step)
    if (idx >= 0) syncSegmentDraftContent(idx, step.editedContent)
  }

  async function segmentApplyPatch(step: SegmentStep) {
    const selectedText = step.patchSelectedText.trim()
    const instruction = step.patchInstruction.trim()
    if (!selectedText || !instruction) return
    if (!step.editedContent.includes(selectedText)) {
      options?.notify?.error('选中文字与当前内容不匹配，请重新选择')
      return
    }
    if (!options?.patchSceneText) {
      options?.notify?.error('AI 修改暂时不可用，请稍后重试')
      return
    }
    step.isPatching = true
    try {
      const data = await options.patchSceneText({
        full_text: step.editedContent,
        selected_text: selectedText,
        instruction,
      })
      applyAiReplacement(step, selectedText, data.replacement)
      const idx = segmentSteps.value.indexOf(step)
      if (idx >= 0) syncSegmentDraftContent(idx, step.editedContent)
      options?.notify?.success('已应用 AI 修改（绿色行为 AI 改动）')
    } catch (e: any) {
      options?.notify?.error(formatUserFacingErrorMessage(e, 'AI 修改失败'))
    } finally {
      step.isPatching = false
    }
  }

  async function attemptLocalizedSegmentRepair(
    idx: number,
    analysis: SegmentRepairAnalysis,
    blockingIssues: string[],
  ) {
    const step = segmentSteps.value[idx]
    if (!step || !step.editedContent.trim()) return false
    if (step.repairAttempts >= 1) return false
    if (!options?.patchSceneText || !options.approveSegment) return false

    const fixStrategy = String(analysis.fix_strategy || '').trim()
    const rootCause = String(analysis.root_cause || '').trim()
    const localInstruction = buildSegmentRepairInstruction({ blockingIssues, fixStrategy })

    step.repairAttempts += 1
    step.isPatching = true
    try {
      const data = await options.patchSceneText({
        full_text: step.editedContent,
        selected_text: step.editedContent,
        instruction: localInstruction,
      })
      const patchedContent = String(data.replacement || '').trim()
      if (!patchedContent) return false

      replaceStepWithRevisedContent(step, patchedContent)
      syncSegmentDraftContent(idx, patchedContent)
      step.patchInstruction = fixStrategy || localInstruction
      step.patchSelectedText = patchedContent
      step.isPatchPanelOpen = false
      options.loadSuggestions?.(step)

      const approved = await options.approveSegment(idx)
      if (approved) {
        options.notify?.success(`${step.label} 已优先完成局部修复，请确认这一段`)
      } else {
        step.status = 'reviewing'
        step.patchInstruction = fixStrategy || localInstruction
        step.patchSelectedText = step.editedContent
        step.isPatchPanelOpen = true
        options.notify?.warning(rootCause || `${step.label} 已先做当前段局部修复，请继续微调，不再直接回滚重写`)
      }
      return true
    } catch {
      step.repairAttempts = Math.max(0, step.repairAttempts - 1)
      options.notify?.warning('局部修复失败，准备切回重写/回滚策略')
      return false
    } finally {
      step.isPatching = false
    }
  }

  async function generateOneSegment(idx: number) {
    if (idx >= segmentSteps.value.length) {
      isSegmentGenerating.value = false
      showSegmentPanel.value = false
      await options?.onAllSegmentsComplete?.()
      return
    }
    const step = segmentSteps.value[idx]
    if (!step) return
    if (!options?.buildSegmentRequest || !options.streamSegment) {
      options?.notify?.error('分段生成暂时不可用，请稍后重试')
      return
    }
    if (idx > 0 && hasUnconfirmedPriorSegment(idx)) {
      const resumeIdx = firstUnconfirmedPriorSegmentIndex(idx)
      currentSegmentIdx.value = resumeIdx >= 0 ? resumeIdx : Math.max(0, idx - 1)
      showSegmentPanel.value = true
      isSegmentGenerating.value = false
      options.notify?.error('上一段还未确认，不能生成下一段。请先确认上一段内容。')
      return
    }

    showSegmentPanel.value = true
    step.status = 'generating'
    currentSegmentIdx.value = idx
    isSegmentGenerating.value = true
    step.versionA = ''
    step.versionB = ''
    step.activeVersion = 'A'
    step.isGeneratingVariant = false
    step.generationAttempts = 0
    clearSegmentError(step)
    updateStreamingStepPreview(step, '')

    const confirmedContent = confirmedSegmentContentBefore(idx)
    const baseReq = options.buildSegmentRequest(step, confirmedContent)
    const maxBusinessAttempts = 2
    let lastInfo: ReturnType<typeof formatRuleBackedScriptStreamError> | null = null
    for (let attempt = 1; attempt <= maxBusinessAttempts; attempt += 1) {
      step.generationAttempts = attempt
      options.onSegmentProgress?.(`${step.label}第${attempt}次生成中…`)
      try {
        const resA = await options.streamSegment({
          ...baseReq,
          client_retry_attempt: attempt,
          client_retry_reason: attempt > 1 ? lastInfo?.detail || '' : '',
        }, (_token, aggregate) => {
          step.versionA = aggregate
          if (step.activeVersion === 'A' && !step.editMode) {
            updateStreamingStepPreview(step, aggregate)
            syncSegmentDraftContent(idx, aggregate)
          }
        }, message => options.onSegmentProgress?.(message))

        step.versionA = resA.content
        step.versionB = ''
        step.activeVersion = 'A'
        initStepContent(step, step.versionA)
        syncSegmentDraftContent(idx, step.versionA)
        step.status = 'reviewing'
        isSegmentGenerating.value = false
        options.onSegmentProgress?.('')
        if (resA.warnings.length > 0) {
          options.notify?.warning(`${step.label}已放行，但仍有提醒：` + resA.warnings.slice(0, 2).join('；'))
        }
        options.onSegmentProgress?.('正在等待确认，确认后会继续下一段')
        options.loadSuggestions?.(step)
        await options.onSegmentDraftReady?.(idx, step.versionA)
        return
      } catch (error: unknown) {
        lastInfo = applySegmentError(step, error)
        if (attempt < maxBusinessAttempts && lastInfo.retryable) {
          step.versionA = ''
          updateStreamingStepPreview(step, '')
          syncSegmentDraftContent(idx, '')
          options.notify?.warning(`${step.label}第${attempt}次生成失败：${lastInfo.detail}。正在自动重试第${attempt + 1}次。`)
          await sleep(900 * attempt)
          continue
        }
        break
      }
    }
    step.status = 'error'
    syncSegmentDraftContent(idx, '')
    const finalInfo = lastInfo || formatRuleBackedScriptStreamError(new Error('生成失败'))
    options.notify?.error(`${step.label}生成失败：${finalInfo.detail}${finalInfo.suggestion ? `。${finalInfo.suggestion}` : ''}`)
    isSegmentGenerating.value = false
    options.onSegmentProgress?.('')
  }

  async function resumeSegmentedProgress() {
    showSegmentPanel.value = true
    const idx = findSegmentResumeIndex()
    if (idx >= segmentSteps.value.length) {
      isSegmentGenerating.value = false
      showSegmentPanel.value = false
      options?.notify?.success('内部四段审阅已经全部完成')
      await options?.onAllSegmentsComplete?.()
      return
    }

    const step = segmentSteps.value[idx]
    if (!step) return
    currentSegmentIdx.value = idx
    if (step.status === 'generating') {
      if (await recoverLatestCandidateIntoSegment(idx, 'stale_generating')) return
      options?.notify?.warning(`${step.label} 正在生成中，请稍等`)
      return
    }
    if (step.status === 'reviewing') {
      if (!step.editedContent.trim() && !step.versionA.trim() && !step.versionB.trim()) {
        if (await recoverLatestCandidateIntoSegment(idx, 'empty_reviewing')) return
        await segmentRetry(idx)
        return
      }
      syncSegmentDraftContent(idx, step.editedContent)
      await segmentConfirm(idx)
      return
    }
    if (step.status === 'error') {
      if (await recoverLatestCandidateIntoSegment(idx, 'error_resume')) return
      await segmentRetry(idx)
      return
    }
    await generateOneSegment(idx)
  }

  async function segmentGenerateVariant(idx: number) {
    const step = segmentSteps.value[idx]
    if (!step) return
    if (step.status !== 'reviewing') return
    if (!options?.buildSegmentRequest || !options.streamSegment) {
      options?.notify?.error('B版生成暂时不可用，请稍后重试')
      return
    }
    if (!step.versionA) step.versionA = step.editedContent

    const previousActiveVersion = step.activeVersion
    const previousEditedContent = step.editedContent
    const previousLineOrigins = [...step.lineOrigins]
    const confirmedContent = confirmedSegmentContentBefore(idx)
    const baseReq = options.buildSegmentRequest(step, confirmedContent)

    step.isGeneratingVariant = true
    isSegmentGenerating.value = true
    step.versionB = ''
    step.activeVersion = 'B'
    updateStreamingStepPreview(step, '')

    try {
      const resB = await options.streamSegment({
        ...baseReq,
        temperature: 0.72,
        variant: 'B',
        variant_instruction: '在同一剧情前提下提供另一个表达版本；不要改动已确认前文、角色事实和本段剧情目标。',
      }, (_token, aggregate) => {
        step.versionB = aggregate
        if (step.activeVersion === 'B' && !step.editMode) {
          updateStreamingStepPreview(step, aggregate)
          syncSegmentDraftContent(idx, aggregate)
        }
      }, message => options.onSegmentProgress?.(message))

      step.versionB = resB.content
      step.activeVersion = 'B'
      initStepContent(step, step.versionB)
      syncSegmentDraftContent(idx, step.versionB)
      if (resB.warnings.length > 0) {
        options.notify?.warning(`${step.label} B版已生成，但仍有提醒：` + resB.warnings.slice(0, 2).join('；'))
      } else {
        options.notify?.success(`${step.label} B版已生成，可在 A/B 间切换`)
      }
      options.loadSuggestions?.(step)
    } catch (error: unknown) {
      const info = applySegmentError(step, error)
      step.activeVersion = previousActiveVersion
      step.editedContent = previousEditedContent
      step._editSnapshot = previousEditedContent
      step.lineOrigins = previousLineOrigins
      step.versionB = ''
      syncSegmentDraftContent(idx, previousEditedContent)
      options.notify?.error(`${step.label} B版生成失败：${info.detail}，已保留当前版本`)
    } finally {
      step.isGeneratingVariant = false
      isSegmentGenerating.value = false
      options.onSegmentProgress?.('')
    }
  }

  async function handleSegmentApprovalFailure(
    idx: number,
    analysis: SegmentRepairAnalysis = options?.getFailureAnalysis?.() || {},
    blockingIssues: string[] = options?.getBlockingIssues?.() || [],
  ) {
    const step = segmentSteps.value[idx]
    if (!step) return
    const repairScope = String(analysis.repair_scope || '').trim()
    const rollbackRecommendation = String(analysis.rollback_recommendation || '').trim()
    const rootCause = String(analysis.root_cause || '').trim()
    const fixStrategy = String(analysis.fix_strategy || '').trim()
    const maxAutomaticRepairAttempts = 2

    if (repairScope === 'patchable' && options?.allowAutomaticSegmentPatch) {
      const locallyHandled = await attemptLocalizedSegmentRepair(idx, analysis, blockingIssues)
      if (locallyHandled) return
    }

    if (!options?.allowAutomaticSegmentPatch) {
      step.status = 'reviewing'
      isSegmentGenerating.value = false
      options?.onSegmentProgress?.('')
      options?.notify?.warning(
        fixStrategy
          || rootCause
          || blockingIssues[0]
          || `${step.label} 需要你确认后手动调整或主动重新生成。`,
      )
      return
    }

    if (step.repairAttempts >= maxAutomaticRepairAttempts) {
      step.status = 'reviewing'
      options?.notify?.warning(fixStrategy || `${step.label} 已完成自动重写仍未通过，请先手动调整或重新生成。`)
      return
    }

    if (step.repairAttempts < 1) {
      const failedRepairAttempts = step.repairAttempts + 1
      step.repairAttempts = failedRepairAttempts
      step.status = 'generating'
      options?.notify?.warning(rootCause || `${step.label} 前提还不够稳，正在静默重写当前段…`)
      resetSegmentsFrom(idx)
      const regeneratedStep = segmentSteps.value[idx]
      if (regeneratedStep) regeneratedStep.repairAttempts = failedRepairAttempts
      await generateOneSegment(idx)
      return
    }

    const rollbackIdx = rollbackRecommendation === 'rollback_previous_segment' && idx > 0 ? idx - 1 : idx
    const rollbackStep = segmentSteps.value[rollbackIdx]
    const rollbackRepairAttempts = (rollbackStep?.repairAttempts || 0) + 1
    if (rollbackStep) {
      rollbackStep.repairAttempts = rollbackRepairAttempts
    }
    options?.notify?.warning(
      rollbackIdx === idx
        ? (fixStrategy || `${step.label} 仍不够稳，已回滚重写当前段。`)
        : (fixStrategy || `${step.label} 的问题来自上一段前提，已回滚到 ${segmentSteps.value[rollbackIdx]?.label || '上一段'} 重写。`),
    )
    resetSegmentsFrom(rollbackIdx)
    const regeneratedStep = segmentSteps.value[rollbackIdx]
    if (regeneratedStep) regeneratedStep.repairAttempts = rollbackRepairAttempts
    await generateOneSegment(rollbackIdx)
  }

  function canConfirmReviewingSegmentByUser(step: SegmentStep, shouldDeepAudit: boolean) {
    return !shouldDeepAudit
      && !options?.allowAutomaticSegmentPatch
      && step.status === 'reviewing'
      && Boolean(step.editedContent.trim())
  }

  async function segmentConfirm(idx: number) {
    const step = segmentSteps.value[idx]
    if (!step) return
    if (!options?.approveSegment || !options.approveFullScript) {
      options?.notify?.error('分段审阅暂时不可用，请稍后重试')
      return
    }

    const shouldDeepAudit = idx >= segmentSteps.value.length - 1
    if (step.editMode) segmentExitEdit(step)
    if ((step.status === 'reviewing' || step.status === 'generating') && !step.editedContent.trim()) {
      const recovered = await recoverLatestCandidateIntoSegment(idx, 'empty_confirm')
      if (!recovered && !step.editedContent.trim()) {
        options.notify?.warning(`${step.label}还没有可确认的候选，请等待后台候选恢复后再确认。`)
        return
      }
    }
    const segmentApproved = await options.approveSegment(idx)
    if (!segmentApproved) {
      if (!canConfirmReviewingSegmentByUser(step, shouldDeepAudit)) {
        await handleSegmentApprovalFailure(idx)
        return
      }
      options.notify?.warning(`${step.label} 已按你的确认继续，后续仍会保留复核提醒。`)
    }
    if (!markSegmentConfirmedForNextRequest(idx)) return

    if (shouldDeepAudit) {
      const scriptApproved = await options.approveFullScript(true)
      if (!scriptApproved) {
        options.notify?.warning('整集深审仍有风险，已保留你确认的分段并保存为待复核稿，不自动覆盖重写。')
      }
    }

    await options.afterSegmentConfirmed?.(shouldDeepAudit)
    if (!markSegmentConfirmedForNextRequest(idx)) return
    if (shouldDeepAudit) {
      isSegmentGenerating.value = false
      showSegmentPanel.value = false
      currentSegmentIdx.value = segmentSteps.value.length
      await options.onAllSegmentsComplete?.()
      return
    }
    await generateOneSegment(idx + 1)
  }

  async function generateSegmented(generateOptions?: { forceRegenerateCurrentDraft?: boolean; sourcePrechecked?: boolean }) {
    if (!options) {
      return
    }
    if (!generateOptions?.sourcePrechecked && !options.ensureOutlineGatePassed?.()) {
      return
    }
    if (!options.persistProjectRules || !options.approveFullScript || !options.resolveFirstSegmentLengthPolicy) {
      options.notify?.error('内部四段审阅暂时不可用，请稍后重试')
      return
    }
    const persisted = await options.persistProjectRules()
    if (!persisted) {
      options.notify?.error('项目规则同步失败，暂时无法执行内部四段审阅')
      return
    }
    if (options.ensureManualEditSyncReady) {
      const manualEditReady = await options.ensureManualEditSyncReady()
      if (!manualEditReady) {
        return
      }
    }
    if (hasSegmentProgress()) {
      if (!generateOptions?.forceRegenerateCurrentDraft) {
        await resumeSegmentedProgress()
        return
      }
      resetSegments()
    }
    if (
      !generateOptions?.sourcePrechecked
      && !generateOptions?.forceRegenerateCurrentDraft
      && options.getSceneContent?.().trim()
    ) {
      const approved = await options.approveFullScript(false)
      if (!approved) {
        options.notify?.error('当前正文仍未通过内部审段，暂时不能继续精写')
        return
      }
    }
    if (!options.resolveFirstSegmentLengthPolicy()) {
      options.notify?.error('当前项目未配置可用的字数规则，暂时无法执行内部四段审阅')
      return
    }
    resetSegments()
    showSegmentPanel.value = true
    await generateOneSegment(0)
  }

  async function segmentRetry(idx: number) {
    const step = segmentSteps.value[idx]
    if (!step) return
    step.versionA = ''
    step.versionB = ''
    step.editedContent = ''
    step.suggestions = []
    step.isPatchPanelOpen = false
    step.repairAttempts = 0
    step.isGeneratingVariant = false
    step.generationAttempts = 0
    clearSegmentError(step)
    await generateOneSegment(idx)
  }

  return {
    segmentSteps,
    isSegmentGenerating,
    showSegmentPanel,
    currentSegmentIdx,
    currentSegmentStep,
    resetSegments,
    confirmedSegmentContent,
    serializeSegmentProgress,
    hydrateSegmentProgress,
    recoverLatestCandidateForSegment,
    resetSegmentsFrom,
    segmentSwitchVersion,
    segmentEnterEdit,
    segmentExitEdit,
    segmentApplyPatch,
    attemptLocalizedSegmentRepair,
    generateOneSegment,
    handleSegmentApprovalFailure,
    segmentConfirm,
    generateSegmented,
    segmentRetry,
    segmentGenerateVariant,
    hasSegmentProgress,
    resumeSegmentedProgress,
    composeSegmentDraftContent,
    applyAiReplacement,
    replaceStepWithRevisedContent,
    initStepContent,
    updateStreamingStepPreview,
  }
}
