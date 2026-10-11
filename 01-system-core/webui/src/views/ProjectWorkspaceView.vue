<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import { onBeforeRouteLeave, useRoute, useRouter } from 'vue-router'
import {
  ChevronRight, ChevronLeft, Sparkles, CheckCircle2,
  AlertCircle, Lock, Wand2, Send, Plus, Trash2, Save, RefreshCw,
  LayoutGrid, Zap, TrendingUp, X, Target, ShieldCheck
} from 'lucide-vue-next'
import { projectsV2Api, adminConfigApi, collaborationApi, episodeDraftCompletionApi, userAccessApi, v2ConfigApi, type CollaborationSummary, type ProjectV2 } from '@/api/client'
import { formatUserFacingErrorMessage, notifyApiError } from '@/api/http'
import { useAuthStore } from '@/stores/auth'
import { useProjectsStore } from '@/stores/projects'
import AiAssistantPanel from '@/views/workspace/panels/AiAssistantPanel.vue'
import FloatingCharacterGraph from '@/views/workspace/panels/FloatingCharacterGraph.vue'
import OutlineConfirmationPanel from '@/views/workspace/panels/OutlineConfirmationPanel.vue'
import WorkspaceHeader from '@/views/workspace/panels/WorkspaceHeader.vue'
import CharacterTab from '@/views/workspace/tabs/CharacterTab.vue'
import ChatTab from '@/views/workspace/tabs/ChatTab.vue'
import ComplianceReviewTab from '@/views/workspace/tabs/ComplianceReviewTab.vue'
import ExportTab from '@/views/workspace/tabs/ExportTab.vue'
import LegalAssetsTab from '@/views/workspace/tabs/LegalAssetsTab.vue'
import OutlineTabBody from '@/views/workspace/tabs/OutlineTabBody.vue'
import OutlineTabHeader from '@/views/workspace/tabs/OutlineTabHeader.vue'
import RagEvidenceHistoryPanel from '@/views/workspace/tabs/RagEvidenceHistoryPanel.vue'
import SegmentReviewPanel from '@/views/workspace/tabs/SegmentReviewPanel.vue'
import ScriptEditorPanel from '@/views/workspace/tabs/ScriptEditorPanel.vue'
import ScriptHealthPanel from '@/views/workspace/tabs/ScriptHealthPanel.vue'
import ScriptSceneStatusPanel from '@/views/workspace/tabs/ScriptSceneStatusPanel.vue'
import ScriptSidebar from '@/views/workspace/tabs/ScriptSidebar.vue'
import ScriptStepConfirmationPanel from '@/views/workspace/tabs/ScriptStepConfirmationPanel.vue'
import ScriptToolbar from '@/views/workspace/tabs/ScriptToolbar.vue'
import StoryboardTab from '@/views/workspace/tabs/StoryboardTab.vue'
import { useAiAssistant } from '@/features/workspace/composables/useAiAssistant'
import { useOutlineGate } from '@/features/workspace/composables/useOutlineGate'
import {
  deriveWordCountRangeBySeconds,
  normalizeProjectRules,
  useOutlineWorkflow,
  type SceneHeaderStyle,
} from '@/features/workspace/composables/useOutlineWorkflow'
import { useProjectExport } from '@/features/workspace/composables/useProjectExport'
import {
  SEGMENT_DEFS,
  useSegmentedWriting,
  type LineOrigin,
  type SegmentStep,
} from '@/features/workspace/composables/useSegmentedWriting'
import { RuleBackedScriptStreamError } from '@/features/workspace/composables/useRuleBackedScriptStream'
import { useScriptDraftGeneration } from '@/features/workspace/composables/useScriptDraftGeneration'
import { useEpisodeScenes } from '@/features/workspace/composables/useEpisodeScenes'
import { _buildRawOutlineText, useChatBrainstorm } from '@/features/workspace/composables/useChatBrainstorm'
import { CHAT_MESSAGE_MAX_CHARS } from '@/features/workspace/utils/chatBrainstormContext'
import { useCharacterTab } from '@/features/workspace/composables/useCharacterTab'
import { useStoryStateAutosave } from '@/features/workspace/composables/useStoryStateAutosave'
import { useStoryStateCards } from '@/features/workspace/composables/useStoryStateCards'
import { hasSeriesSimulationContracts } from '@/features/workspace/composables/useStorySimulation'
import { useWorkspaceTabs, type WorkspaceTabId } from '@/features/workspace/composables/useWorkspaceTabs'
import {
  createStandardOutlinePacket,
  diagnoseStandardOutlinePacketGate,
  normalizeStandardOutlinePacket,
  projectStandardOutlinePacketToOutline,
  type StandardOutlinePacket,
  type StandardOutlineGateTarget,
} from '@/features/workspace/utils/standardOutlinePacket'
import {
  resolveCommitConfirmedTotalEpisodes,
  resolveStrictConfirmedTotalEpisodes as resolveConfirmedEpisodeCount,
} from '@/features/workspace/utils/outlineCommitGate'
import {
  buildValidationCacheKey,
  buildWorkflowAuditPatch,
  clonePlain,
  emptyStoryStateCards,
  emptyWorkflowContext,
  findBlockingManualEditSyncGate,
  markManualEditGateConsumed,
  normalizeStoryStateCards,
  normalizeWorkflowContext,
  RAG_EVIDENCE_LOG_MAX,
  setBoundedCache,
  simpleHash,
  SCRIPT_CACHE_MAX,
  type StoryStateCard,
  type StoryStateCardKind,
} from '@/features/workspace/utils/workflowState'
import { loadWorkspaceStorage, saveWorkspaceStorage } from '@/features/workspace/utils/workspaceStorage'
import { toast } from 'vue-sonner'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const projectsStore = useProjectsStore()

const projectId = computed(() => route.params.projectId as string)
const project = ref<ProjectV2 | null>(null)
const collaborationSummary = ref<CollaborationSummary | null>(null)
const isLoading = ref(true)
const lastWorkflowContextSyncError = ref<unknown>(null)
const copyExportLocked = computed(() => Boolean(auth.userSession && !auth.copyExportAllowed))
const copyExportLockedMessage = '当前密钥未开启复制导出权限，只允许粘贴和编辑；如需复制或导出，请联系管理员开启。'
let copyExportPermissionRefresh: Promise<unknown> | null = null

type ScriptGenerationTarget = {
  episodeNo: number
  sceneNo: number
}

function _normalizeEpisodeNo(value: unknown) {
  return Math.max(1, Math.round(Number(value || 1) || 1))
}

function _normalizeSceneNo(value: unknown) {
  return Math.max(1, Math.round(Number(value || 1) || 1))
}

async function refreshUserPermissionSnapshot() {
  if (!auth.userSession?.session_token) return
  if (!copyExportPermissionRefresh) {
    copyExportPermissionRefresh = auth.refreshUserSession().catch(() => null).finally(() => {
      copyExportPermissionRefresh = null
    })
  }
  await copyExportPermissionRefresh
}

function preventCopyExport(event: Event) {
  if (!copyExportLocked.value) return
  event.preventDefault()
  event.stopPropagation()
  toast.warning(copyExportLockedMessage)
}

function handleWorkspaceKeydown(event: KeyboardEvent) {
  if (!copyExportLocked.value) return
  const key = event.key.toLowerCase()
  if ((event.metaKey || event.ctrlKey) && ['c', 'x', 'p', 's'].includes(key)) {
    preventCopyExport(event)
  }
}
const {
  tabs,
  activeTab,
  completedTabs,
  progressPercent,
  loadTabState,
  markTabComplete,
  switchTab: _switchWorkspaceTab,
} = useWorkspaceTabs({ route, router, projectId })

// ─── 大纲编辑 Tab ─────────────────────────────────────────────────────────────
const {
  outlineData,
  projectRules,
  generationProviders,
  fallbackGenerationConfig,
  projectRulesSaving,
  lastProjectRulesSignature,
  outlineCharacters,
  isAnalyzingOutline,
  outlineImportText,
  showImportArea,
  rawOutlineText,
  isGeneratingEpisodes,
  sectionSuggestions,
  sectionLoading,
  availableGenerationModels,
  applyGenerationDefaults,
} = useOutlineWorkflow()

const standardOutlinePacket = ref<StandardOutlinePacket>(createStandardOutlinePacket())
let _runStoryStateAutosaveExclusive: <T>(work: () => Promise<T>) => Promise<T> = async work => await work()

function _normalizeTotalEpisodeCount(value: unknown) {
  const count = Math.round(Number(value || 0))
  return Number.isFinite(count) && count > 0 ? Math.max(1, Math.min(200, count)) : 0
}

function _outlineEpisodeCount() {
  return Array.isArray(outlineData.value.episodes) ? outlineData.value.episodes.length : 0
}

function _episodeCountResolutionInput() {
  return {
    currentPacket: standardOutlinePacket.value,
    workflowOutlineState: (workflowContext.value?.outline_state || {}) as Record<string, any>,
    projectRules: projectRules.value as unknown as Record<string, any>,
    projectConfig: (project.value?.config || {}) as Record<string, any>,
    outlineEpisodeCount: _outlineEpisodeCount(),
  }
}

function _effectiveUserConfirmedTotalEpisodes() {
  return resolveConfirmedEpisodeCount(_episodeCountResolutionInput())
}

function _confirmableUserTotalEpisodesForOutlineCommit() {
  return resolveCommitConfirmedTotalEpisodes(_episodeCountResolutionInput())
}

function _declaredTotalEpisodesForOutlineCommit() {
  return _normalizeTotalEpisodeCount(projectRules.value.total_episodes)
    || _normalizeTotalEpisodeCount((project.value?.config as any)?.total_episodes)
}

function _applyUserConfirmedTotalEpisodesForOutlineCommit(count: number) {
  const normalized = _normalizeTotalEpisodeCount(count)
  if (!normalized) return false
  ;(outlineData.value as any).episode_count = normalized
  projectRules.value.total_episodes = normalized
  projectRules.value.confirmed_total_episodes = normalized
  projectRules.value.episode_count_status = 'confirmed'
  projectRules.value.episode_count_confirmation_source = 'outline_complete_button'
  projectRules.value.episode_count_confirmed_at = new Date().toISOString()
  return true
}

function _syncProjectRulesTotalEpisodesFromConfirmedCount() {
  const confirmedCount = _effectiveUserConfirmedTotalEpisodes()
  if (!confirmedCount) return false
  if (projectRules.value.total_episodes !== confirmedCount) {
    projectRules.value.total_episodes = confirmedCount
  }
  projectRules.value.confirmed_total_episodes = confirmedCount
  projectRules.value.episode_count_status = 'confirmed'
  if (!projectRules.value.episode_count_confirmation_source) {
    projectRules.value.episode_count_confirmation_source = 'standard_outline_packet'
  }
  if (!projectRules.value.episode_count_confirmed_at) {
    projectRules.value.episode_count_confirmed_at = new Date().toISOString()
  }
  return true
}

// ─── 聊天脑暴 Tab ─────────────────────────────────────────────────────────────
// 实现搬到 useChatBrainstorm composable。需要在 useOutlineWorkflow 之后初始化（依赖 outlineData）。
const {
  chatMessages,
  chatLoading,
  outlineLoading,
  confirmingSection,
  chatSaveStatus,
  chatContextBlocked,
  lastContextTrace,
  hydrateChatBrainstormState,
  bootstrapFromQueryPrompt,
  retryChatBrainstormSave,
  openOutlineForChatContext,
  sendChatMessage,
  sendChatReferenceDocument,
  generateOutlineFromChat,
  confirmOutlineEditorSection,
} = useChatBrainstorm({
  projectId,
  outlineData,
  outlineCharacters,
  standardOutlinePacket,
  episodeCount: () => _effectiveUserConfirmedTotalEpisodes(),
  switchToOutline: () => {
    activeTab.value = 'outline'
    router.replace({ query: { ...route.query, tab: 'outline' } })
  },
  markChatTabComplete: () => markTabComplete('chat'),
  notify: {
    success: (m: string) => toast.success(m),
    error: (m: string) => toast.error(m),
    warning: (m: string) => toast.warning(m),
  },
  onOutlineGenerated: async ({ rawOutlineText: generatedRawOutlineText, standardOutlinePacket: generatedStandardOutlinePacket }) => {
    return await _runStoryStateAutosaveExclusive(async () => {
      const previousStandardOutlinePacket = standardOutlinePacket.value
      const previousRawOutlineText = rawOutlineText.value
      const previousWorkflowContext = JSON.parse(JSON.stringify(workflowContext.value))
      const previousOutlineData = JSON.parse(JSON.stringify(outlineData.value))
      const previousOutlineCharacters = JSON.parse(JSON.stringify(outlineCharacters.value))
      let nextRawOutlineText = previousRawOutlineText
      if (generatedStandardOutlinePacket) {
        standardOutlinePacket.value = normalizeStandardOutlinePacket(generatedStandardOutlinePacket)
        if (generatedStandardOutlinePacket.status === 'confirmed') {
          const confirmedProjection = projectStandardOutlinePacketToOutline(generatedStandardOutlinePacket)
          outlineData.value = { ...outlineData.value, ...(confirmedProjection.outlineData as any) }
          outlineCharacters.value = confirmedProjection.outlineCharacters as any
          // 使用标准资料包投影出的可读文本，保留用户确认的总集数和人物关系。
          nextRawOutlineText = generatedRawOutlineText
        }
      } else {
        nextRawOutlineText = generatedRawOutlineText
      }
      rawOutlineText.value = nextRawOutlineText
      saveWorkspaceStorage('outline', projectId.value, JSON.stringify(outlineData.value))
      saveWorkspaceStorage('outlineChars', projectId.value, JSON.stringify(outlineCharacters.value))
      saveWorkspaceStorage('rawOutline', projectId.value, nextRawOutlineText)
      if (!generatedStandardOutlinePacket) {
        if (outlineCharacters.value.length) _markOutlineAiGenerated('characters')
        if (outlineData.value.episodes.length) _markOutlineAiGenerated('episodes')
      }
      const persisted = await _persistOutlineDraft('chat_brainstorm_outline_draft', {
        silent: true,
        preserveEditorData: generatedStandardOutlinePacket?.status !== 'confirmed',
      })
      if (persisted !== true) {
        standardOutlinePacket.value = previousStandardOutlinePacket
        rawOutlineText.value = previousRawOutlineText
        outlineData.value = previousOutlineData
        outlineCharacters.value = previousOutlineCharacters
        workflowContext.value = previousWorkflowContext
        saveWorkspaceStorage('outline', projectId.value, JSON.stringify(previousOutlineData))
        saveWorkspaceStorage('outlineChars', projectId.value, JSON.stringify(previousOutlineCharacters))
        saveWorkspaceStorage('rawOutline', projectId.value, previousRawOutlineText)
        return false
      }
      _syncProjectRulesTotalEpisodesFromConfirmedCount()
      return true
    })
  },
})

const chatReferenceLoading = ref(false)

async function handleChatReferenceUpload(file: File) {
  if (chatLoading.value || outlineLoading.value || confirmingSection.value || chatReferenceLoading.value) {
    toast.warning('当前操作完成后再上传剧本。')
    return
  }
  chatReferenceLoading.value = true
  try {
    const { data } = await projectsV2Api.extractOutlineFile(file)
    const sourceText = String(data.text || '').trim()
    if (!sourceText) {
      toast.error('文件中没有可识别的文字')
      return
    }
    const accepted = await sendChatReferenceDocument({
      filename: String(data.filename || file.name),
      text: sourceText,
      truncated: Boolean(data.truncated),
    })
    if (!accepted) toast.error('剧本没有进入聊天参考，请等待当前操作完成后重新上传。')
  } catch (error: unknown) {
    notifyApiError(toast.error, error, '剧本读取失败')
  } finally {
    chatReferenceLoading.value = false
  }
}

const consumedQueryPrompts = new Set<string>()

// URL ?prompt= 只能在项目数据和聊天历史回灌后消费一次，避免返回页面时重复发送。
async function bootstrapQueryPromptFromRoute() {
  const rawPrompt = route.query.prompt
  const promptText = Array.isArray(rawPrompt)
    ? rawPrompt.find((item): item is string => typeof item === 'string') || ''
    : typeof rawPrompt === 'string' ? rawPrompt : ''
  const prompt = promptText.trim()
  if (!prompt) return
  const promptKey = `${projectId.value}:${simpleHash(prompt)}`
  if (consumedQueryPrompts.has(promptKey)) return
  consumedQueryPrompts.add(promptKey)
  await bootstrapFromQueryPrompt(prompt)
  const nextQuery = { ...route.query }
  delete nextQuery.prompt
  await router.replace({ query: nextQuery })
}

const _deriveWordCountRangeBySeconds = deriveWordCountRangeBySeconds
const _normalizeProjectRules = normalizeProjectRules
const outlineAnalyzeStatus = ref('')
const isPredictingOutline = ref(false)
const outlinePrediction = ref<Record<string, any> | null>(null)
const outlineAiGeneratedFields = ref<Record<string, string>>({})
const outlineFallbackCandidateBoundary = ref<Record<string, any> | null>(null)
const outlineAiFeaturesPaused = false

function _applyGenerationDefaults() {
  applyGenerationDefaults()
}

const {
  aiPanelOpen,
  aiMessages,
  aiLoading,
  quickPrompts,
  sendAIMessage,
} = useAiAssistant({
  activeTab,
  getContext: () => ({
    audience_axis: outlineData.value.audience_axis || '',
    genre_main: outlineData.value.genre_main || '',
    format_type: outlineData.value.format_type || '真人短剧',
  }),
})

async function getAISuggestion(section: string, currentValue: string) {
  if (outlineAiFeaturesPaused) {
    toast.warning('大纲 AI 优化功能暂时关闭，请先手动补全。')
    return
  }
  if (!currentValue.trim()) { toast.error('请先填写内容再获取AI建议'); return }
  sectionLoading.value[section] = true
  const sectionNames: Record<string, string> = {
    logline: '一句话梗概', worldview: '世界观设定', goldenFinger: '金手指/特殊设定', conflict: '核心冲突与爽点'
  }
  const allContext = [
    outlineData.value.logline && `梗概：${outlineData.value.logline}`,
    outlineData.value.worldview && `世界观：${outlineData.value.worldview}`,
    outlineData.value.conflict && `冲突：${outlineData.value.conflict}`,
    outlineCharacters.value.length > 0 && `角色：${outlineCharacters.value.map(c=>c.name+'('+c.role+')').join('、')}`,
  ].filter(Boolean).join('\n')
  try {
    const { data } = await userAccessApi.aiChat({
      messages: [{ role: 'user', content: `请针对以下短剧大纲的「${sectionNames[section] || section}」内容，给出3条具体优化建议（每条50字以内，编号1-3）：\n\n当前内容：${currentValue}\n\n全局背景：\n${allContext}` }],
      context: 'outline', max_tokens: 400,
      audience_axis: outlineData.value.audience_axis || '',
      genre: outlineData.value.genre_main || '',
      format_type: outlineData.value.format_type || '真人短剧',
    })
    sectionSuggestions.value[section] = data.content
  } catch (e: unknown) { notifyApiError(toast.error, e, 'AI建议获取失败') }
  finally { sectionLoading.value[section] = false }
}

function _currentProjectRulesSignature() {
  return JSON.stringify({
    audience_axis: outlineData.value.audience_axis || '',
    genre_main: outlineData.value.genre_main || '',
    format_type: outlineData.value.format_type || '真人短剧',
    project_type: _resolveWorkspaceProjectType(),
    total_episodes: projectRules.value.total_episodes,
    confirmed_total_episodes: projectRules.value.confirmed_total_episodes,
    suggested_total_episodes: projectRules.value.suggested_total_episodes,
    episode_count_status: projectRules.value.episode_count_status,
    episode_count_confirmation_source: projectRules.value.episode_count_confirmation_source,
    episode_count_confirmed_at: projectRules.value.episode_count_confirmed_at,
    episode_seconds: projectRules.value.episode_seconds,
    word_count_per_episode: projectRules.value.word_count_per_episode,
    scene_header_style: projectRules.value.scene_header_style,
    subgenre_track: projectRules.value.subgenre_track,
    sample_track: projectRules.value.sample_track,
    generation_provider: projectRules.value.generation_provider,
    generation_model: projectRules.value.generation_model,
    advanced_generation_mode: projectRules.value.advanced_generation_mode,
  })
}

function _applyProjectRules(config?: Partial<{
  total_episodes: number | null
  confirmed_total_episodes: number | null
  suggested_total_episodes: number | null
  episode_count_status: 'unconfirmed' | 'confirmed' | 'legacy_needs_confirmation'
  episode_count_confirmation_source: string
  episode_count_confirmed_at: string
  episode_seconds: number
  episode_minutes: number
  word_count_per_episode: string
  scene_header_style: string
  subgenre_track: string
  sample_track: string
  generation_provider: string
  generation_model: string
  advanced_generation_mode: boolean
}>) {
  const normalized = _normalizeProjectRules({
    total_episodes: config?.total_episodes,
    confirmed_total_episodes: config?.confirmed_total_episodes,
    suggested_total_episodes: config?.suggested_total_episodes,
    episode_count_status: config?.episode_count_status,
    episode_count_confirmation_source: config?.episode_count_confirmation_source,
    episode_count_confirmed_at: config?.episode_count_confirmed_at,
    episode_seconds: config?.episode_seconds ?? (config?.episode_minutes ? Math.round(config.episode_minutes * 60) : undefined),
    word_count_per_episode: config?.word_count_per_episode,
    scene_header_style: config?.scene_header_style,
    subgenre_track: config?.subgenre_track,
    sample_track: config?.sample_track,
    generation_provider: config?.generation_provider,
    generation_model: config?.generation_model,
    advanced_generation_mode: config?.advanced_generation_mode,
  })
  projectRules.value = normalized
  _applyGenerationDefaults()
}

async function persistProjectRules(options?: { silent?: boolean }) {
  if (!project.value) return true
  const signature = _currentProjectRulesSignature()
  if (signature === lastProjectRulesSignature.value) return true

  const normalizedRules = _normalizeProjectRules(projectRules.value)
  projectRules.value = normalizedRules
  projectRulesSaving.value = true
  try {
    const { data } = await projectsV2Api.update(projectId.value, {
      description: project.value.description,
      project_type: _resolveWorkspaceProjectType(),
      audience_axis: outlineData.value.audience_axis || project.value.audience_axis,
      genre_main: outlineData.value.genre_main || project.value.genre_main,
      genre_sub: project.value.genre_sub,
      config: {
        total_episodes: normalizedRules.total_episodes || null,
        confirmed_total_episodes: normalizedRules.confirmed_total_episodes,
        suggested_total_episodes: normalizedRules.suggested_total_episodes,
        episode_count_status: normalizedRules.episode_count_status,
        episode_count_confirmation_source: normalizedRules.episode_count_confirmation_source,
        episode_count_confirmed_at: normalizedRules.episode_count_confirmed_at,
        episode_seconds: normalizedRules.episode_seconds,
        episode_minutes: Number((normalizedRules.episode_seconds / 60).toFixed(3)),
        word_count_per_episode: normalizedRules.word_count_per_episode,
        scene_header_style: normalizedRules.scene_header_style,
        subgenre_track: normalizedRules.subgenre_track,
        sample_track: normalizedRules.sample_track,
        generation_provider: normalizedRules.generation_provider,
        generation_model: normalizedRules.generation_model,
        advanced_generation_mode: normalizedRules.advanced_generation_mode,
        manga_mode: project.value.config?.manga_mode ?? false,
        premium_mode: project.value.config?.premium_mode ?? false,
      },
    })
    project.value = data
    _applyProjectRules(data.config)
    lastProjectRulesSignature.value = _currentProjectRulesSignature()
    if (!options?.silent) toast.success('项目规则已同步到正式工作流')
    return true
  } catch (e: any) {
    if (!options?.silent) {
      notifyApiError(toast.error, e, '项目规则同步失败')
    }
    return false
  } finally {
    projectRulesSaving.value = false
  }
}

async function persistWorkspaceCharacters(options?: { silent?: boolean }) {
  if (!project.value) return true
  try {
    saveWorkspaceStorage('characters', projectId.value, JSON.stringify(characters.value))
    await projectsV2Api.saveCharacters(projectId.value, characters.value as Array<Record<string, any>>)
    return true
  } catch (e: any) {
    if (!options?.silent) {
      notifyApiError(toast.error, e, '角色设计保存失败')
    }
    return false
  }
}

function _outlineTextValue(value: any): string {
  if (!value) return ''
  if (typeof value === 'string') return value
  if (Array.isArray(value)) return value.map(_outlineTextValue).filter(Boolean).join(' → ')
  if (typeof value === 'object') {
    return String(value.content || value.summary || value.text || value.title || value.main_event || '')
  }
  return String(value)
}

function _isGeneratedOutlineNoiseEpisode(ep: any) {
  const text = [
    ep?.title,
    ep?.summary,
    ep?.conflict,
    ep?.turning,
    ep?.main_scene,
    ep?.relationship_change,
    ep?.info_revealed,
    ep?.satisfaction_type,
    ep?.stage,
  ].map(item => String(item || '')).join('\n')
  return /第\d{1,3}-\d{1,3}集范围集纲内的第\d+个事件|围绕“.*”推进具体事件|推进具体行动|开端阶段|升级阶段|收束阶段|首付墙｜|抢入｜|蓄势｜|爬升｜|风暴｜|二付墙｜|终局｜|阻止真相\/筹码外流|法庭外|学校礼堂|酒店电梯|董事会|出租屋/.test(text)
}

function _normalizeEditorEpisode(ep: any, index: number) {
  const episodeNo = Number(ep?.episodeNumber || ep?.episode_no || ep?.episode || ep?.ep || index + 1) || index + 1
  const plotSummary = Array.isArray(ep?.plotPoints)
    ? ep.plotPoints.map((pp: any) => _outlineTextValue(pp)).filter(Boolean).join(' → ')
    : ''
  return {
    ep: episodeNo,
    title: ep?.title || `第${episodeNo}集`,
    hook: _outlineTextValue(ep?.hook || ep?.ending_hook || ep?.cliffhanger || ep?.opening_hook || ep?.tail_hook),
    summary: _outlineTextValue(ep?.episode_outline || ep?.summary || ep?.main_event || ep?.event || ep?.plot || plotSummary),
    conflict: _outlineTextValue(ep?.conflict || ep?.core_conflict),
    turning: _outlineTextValue(ep?.turning || ep?.turning_point || ep?.reversal),
    main_scene: _outlineTextValue(ep?.main_scene),
    relationship_change: _outlineTextValue(ep?.relationship_change),
    info_revealed: _outlineTextValue(ep?.info_revealed),
    satisfaction_type: _outlineTextValue(ep?.satisfaction_type),
    stage: _outlineTextValue(ep?.stage),
    existing_script: ep?.existing_script || '',
  }
}

const OUTLINE_ANALYZE_FAST_PARSE_CHARS = 5000
const OUTLINE_ANALYZE_LOCAL_EPISODE_CAP = 60

function _compactOutlineText(value: string, limit = 240) {
  return String(value || '')
    .replace(/\r/g, '\n')
    .replace(/[ \t]+/g, ' ')
    .replace(/\n{3,}/g, '\n\n')
    .trim()
    .slice(0, limit)
}

function _splitOutlineSentences(outline: string) {
  return String(outline || '')
    .replace(/\r/g, '\n')
    .split(/[。！？!?；;\n]+/)
    .map(item => item.replace(/\s+/g, ' ').trim())
    .filter(item => item.length >= 8)
}

function _pickOutlineSentence(outline: string, keywords: string[], fallbackIndex = 0) {
  const sentences = _splitOutlineSentences(outline)
  const matched = sentences.find(sentence => keywords.some(keyword => sentence.includes(keyword)))
  return _compactOutlineText(matched || sentences[fallbackIndex] || outline, 180)
}

function _isOutlineCategorySummary(text: string) {
  const compact = _compactOutlineText(text, 120)
  if (!compact) return false
  const categoryHits = ['现代', '都市', '悬疑', '男频', '女频', '短剧', '真人', '题材', '类型']
    .filter(word => compact.includes(word)).length
  const storyHits = ['男主', '女主', '主角', '发现', '卷入', '为了', '必须', '却', '被迫', '想要', '追查', '保护', '复仇']
    .filter(word => compact.includes(word)).length
  return categoryHits >= 2 && storyHits === 0
}

function _isOutlineScaffoldValue(text: string) {
  const compact = _compactOutlineText(text, 180)
  if (!compact) return true
  if ([
    '我已有大纲文件',
    '已有大纲文件',
    '请先帮我',
    '系统能稳定识别',
    '点击上传',
    '拖拽文件',
    '.docx',
    '.markdown',
    '.txt',
  ].some(marker => compact.includes(marker))) {
    return true
  }
  if (/^(主场景|关系变化|信息揭露|爽点类型|本集冲突|转折\/爆点|转折爆点|核心冲突\/爽点|卖点概述|主卖点|次卖点|参考对标|改编问题及解决方案)\s*[：:]/.test(compact)) {
    return true
  }
  if (/^(世界观|核心冲突\/爽点|核心冲突|爽点|一句话梗概)\s*([：:]|\s+)(次卖点|主卖点|卖点概述|信息揭露|关系变化|主场景|爽点类型|转折\/爆点|转折爆点)/.test(compact)) {
    return true
  }
  return ['卖点概述', '主卖点', '次卖点', '参考对标'].some(prefix => compact.startsWith(prefix))
}

function _deriveLocalOutlineLogline(outline: string) {
  const summary = _pickLabeledOutlineValue(outline, ['故事概括', '故事简介', '剧情概括', '故事梗概'], 260)
  if (summary) return summary
  const sentences = _splitOutlineSentences(outline)
  for (const sentence of sentences) {
    const cleaned = _compactOutlineText(
      sentence.replace(/故事大纲[：:]/g, '').replace(/一句话梗概[：:]/g, '').replace(/故事概括[：:]?/g, ''),
      220,
    )
    if (!cleaned || _isOutlineCategorySummary(cleaned) || _isOutlineScaffoldValue(cleaned)) continue
    if (['男主', '女主', '主角', '发现', '卷入', '为了', '必须', '被迫', '追查', '保护', '复仇', '秘密', '证据']
      .some(word => cleaned.includes(word))) {
      return cleaned
    }
  }
  return sentences
    .map(sentence => _compactOutlineText(sentence, 220))
    .find(sentence => sentence && !_isOutlineCategorySummary(sentence) && !_isOutlineScaffoldValue(sentence)) || ''
}

function _pickLabeledOutlineValue(outline: string, labels: string[], limit = 220) {
  const escaped = labels.map(label => label.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('|')
  const stopLabels = '故事大纲|一句话梗概|故事概括|故事简介|剧情概括|故事梗概|作品名|卖点概述|主卖点|次卖点|核心卖点|定位|作品体量|用户定位|受众定位|受众|题材|类型|格式|参考对标|创作方向|人物|主要角色|角色库|角色列表|世界观|背景设定|金手指|特殊设定|核心冲突(?:/爽点)?|爽点|人物小传|人物设定|角色设定|人物关系|角色关系|关系设计|视觉档案|视觉文档|第\\s*[一二三四五六七八九十百\\d]{1,4}\\s*集|分集|集纲'
  const re = new RegExp(
    `(?:^|[\\n\\r])\\s*(?:${escaped})\\s*(?:[：:]|\\s+|\\s*[|｜]\\s*)\\s*([\\s\\S]*?)(?=\\n\\s*(?:${stopLabels})\\s*(?:[：:]|\\s+|\\s*[|｜]\\s*)|$)`,
  )
  const match = outline.match(re)
  if (match?.[1]) {
    const rawValue = (match[1] || '')
      .replace(/^[|｜：:\s]+/, '')
      .split(/\n\s*(?:外貌参考|视觉档案|视觉文档|人物关系|角色关系|关系设计|[\u4e00-\u9fa5]{2,8}\s*[（(](?:protagonist|supporting|antagonist|main|lead|主角|配角|反派|男主|女主))/u)[0] || ''
    const value = _compactOutlineText(rawValue, limit)
    return _isOutlineScaffoldValue(value) ? '' : value
  }
  const sentence = _splitOutlineSentences(outline).find(item => labels.some(label => item.includes(label)))
  if (!sentence) return ''
  const value = _compactOutlineText(sentence, limit)
  return _isOutlineScaffoldValue(value) ? '' : value
}

function _pickOutlineSingleLineValue(outline: string, labels: string[]) {
  const escaped = labels.map(label => label.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('|')
  const match = String(outline || '').match(new RegExp(`(?:^|[\\n\\r|｜])\\s*(?:${escaped})\\s*(?:[：:]|\\s*[|｜]\\s*|\\s+)\\s*([^\\n\\r|｜。；;]{1,80})`))
  return _compactOutlineText(match?.[1] || '', 80)
}

function _inferLocalOutlineTarget(outline: string): '男频' | '女频' | '混合' {
  if (outlineData.value.audience_axis) return outlineData.value.audience_axis
  const explicitTarget = _pickOutlineSingleLineValue(outline, ['用户定位', '受众定位', '受众轴', '受众', '频道', '赛道', '定位'])
  if (/男频/.test(explicitTarget)) return '男频'
  if (/女频/.test(explicitTarget)) return '女频'
  if (/混合|双频/.test(explicitTarget)) return '混合'
  if (/男频/.test(outline)) return '男频'
  if (/女频/.test(outline)) return '女频'

  const firstLead = String(outline || '').match(/(?:^|[\n\r|｜：:，,。；;\s])((?:男|女)主)[\s：:：]?[\u4e00-\u9fa5]{2,6}/)
  if (firstLead?.[1] === '男主') return '男频'
  if (firstLead?.[1] === '女主') return '女频'

  const maleHits = (outline.match(/男主|男频|男反|男二/g) || []).length
  const femaleHits = (outline.match(/女主|女频|女反|女二/g) || []).length
  if (maleHits > femaleHits) return '男频'
  if (femaleHits > maleHits) return '女频'
  return '混合'
}

function _inferLocalOutlineGenre(outline: string) {
  const target = _inferLocalOutlineTarget(outline)
  let subCategory = outlineData.value.genre_main || ''
  if (!subCategory) {
    const explicitGenre = _pickOutlineSingleLineValue(outline, ['题材', '类型', '主类型', '细分题材', '赛道'])
    if (explicitGenre && !/^(男频|女频|混合|真人短剧|漫剧|AI真人)$/.test(explicitGenre)) subCategory = explicitGenre
    else if (/志怪|堂仙|巫观|献祭/.test(outline)) subCategory = '古装志怪'
    else if (/民国|药局|药案|商会/.test(outline)) subCategory = '民国悬疑'
    else if (/权谋|古装|朝堂|兵符|皇子|王/.test(outline)) subCategory = '古装权谋'
    else if (/商战|股权|董事会|合同陷阱|公司/.test(outline)) subCategory = '逆袭商战'
    else if (/系统|绑定|倒计时|平台|外卖/.test(outline)) subCategory = '系统逆袭'
    else if (/悬疑|推理|凶|杀|秘密|诡|鬼|恐怖|真相|证据/.test(outline)) subCategory = '悬疑惊悚'
    else if (/重生|逆袭|系统|爽/.test(outline)) subCategory = '重生逆袭'
    else if (/婚|总裁|豪门|恋|爱/.test(outline)) subCategory = '都市情感'
    else subCategory = '都市短剧'
  }
  return { target, category: target, subCategory }
}

const OUTLINE_LOCAL_NAME_EXCLUDES = new Set([
  '故事大纲', '人物小传', '人物设定', '角色小传', '角色设定', '角色介绍', '核心冲突', '金手指', '世界观',
  '外貌参考', '外貌', '外观', '视觉档案', '视觉文档', '视觉设定',
  '一句话梗概', '梗概',
  '第一集', '第二集', '第三集', '第四集', '第五集',
  '第六集', '第七集', '第八集', '第九集', '第十集', '第一场', '第二场', '第三场', '第四场', '第五场',
  '场景', '时间', '地点', '正文', '原文', '范围集纲', '详细集纲', '分集集纲', '分集框架', '集纲',
  '剧情大纲', '故事背景', '特殊设定', '爽点', '尾钩', '钩子', '转折', '爆点', '处理方式', '主卖点',
  '核心卖点', '高位弃', '主要角色', '主要人物', '角色关系', '人物关系',
  '豪族', '百姓', '乡民', '民众', '女将', '木匠', '学徒', '少年学徒', '守城女将',
  '年龄', '性别', '性格', '背景', '遭遇', '身份', '职业', '阵营', '动机', '目标',
  '公开', '曝光', '揭露', '设局', '追杀', '反派公开', '反派动作', '证据公开',
  '系统', '新角色', '人物', '主卖点', '次卖点', '一阶段主线', '二阶段主线', '三阶段主线',
  '其余改编处理', '必须付出代价', '赢下当场', '资源减少', '筹码增多', '当场换策略',
  '最不愿怀疑的', '下场', '新想法', '震惊宣布', '颠覆突转', '重要决定',
])

const OUTLINE_NON_CHARACTER_RE = /年龄|性别|性格|背景|遭遇|身份|职业|阵营|动机|目标|方式|处理|设定|冲突|集纲|剧情|正文|原文|角色|人物|关系|主线|支线|爽点|钩子|尾钩|卖点|世界观|金手指|内容|阶段|事件|反转|爆点|场景|时间|地点|规则|模板|框架|外貌|外观|视觉档案|视觉文档|视觉设定|高位弃|低位|地位|公开|曝光|揭露|设局|追杀|阻止|压制|逼迫|威胁|控制|旁观|被动|解释|主动|真正|目标|轻视|代价|赢下|当场|资源|筹码|策略|怀疑|站队|围剿|结盟|承担|风险|证据|确认|知道|震惊|宣布|颠覆|突转|决定|第[一二三四五六七八九十百\d]{1,4}(集|场)/
const OUTLINE_CHARACTER_INFO_STOP_RE = /(^|\n|\r|\s)(主场景|关系变化|信息揭露|爽点类型|本集冲突|转折\/爆点|转折爆点|第\s*[一二三四五六七八九十百\d]{1,4}\s*(集|级)|改编问题及解决方案|卖点概述|参考对标|故事概括|范围集纲|详细集纲|分集集纲|一阶段主线|二阶段主线|三阶段主线)\s*[：:]?/u
const OUTLINE_CHARACTER_BIO_HINTS = [
  '年龄', '岁', '身份', '职业', '外貌', '外观', '性格', '说话', '语气', '音色',
  '动机', '目标', '欲望', '弱点', '弧线', '成长', '背景', '出身', '身世',
  '关系', '阵营', '功能', '主角', '配角', '反派', '龙套', '少年', '少女',
  '青年', '中年', '首领', '领袖', '继承人', '证据持有人', '巫观', '堂仙',
]
const OUTLINE_PLOT_ACTION_HINTS = [
  '第', '集', '场', '正文', '主场景', '关系变化', '信息揭露', '爽点类型',
  '发现', '拿到', '进入', '追查', '追杀', '围堵', '拦住', '递来', '封山',
  '承认', '派人', '逼迫', '偷袭', '吞噬', '安排', '站队', '揭露', '反制',
  '转为', '继续', '开始', '随后', '最终', '当场', '赢下', '失效',
]
const OUTLINE_CHARACTER_TABLE_LABELS = new Set([
  '人物小传', '人物设定', '角色小传', '角色设定', '角色介绍', '角色库', '主要角色', '角色列表',
])
const OUTLINE_CHARACTER_TABLE_SUBFIELDS = new Set([
  '年龄', '身份', '职业', '阵营', '外貌', '外貌参考', '外观', '参考例图', '视觉档案', '视觉文档', '视觉设定',
  '人物性格', '性格', '说话方式', '声线', '音色', '动机', '目标', '弱点', '人物弧线', '弧线', '成长',
  '背景', '身世背景', '出身', '功能', '关系', '人物关系', '角色关系', '备注',
])

function _cleanLocalCharacterName(value: string) {
  return String(value || '')
    .replace(/[（(].*?[）)]/g, '')
    .replace(/^(和|与|及|、|是|叫|为|的|了)+/g, '')
    .replace(/(是|为|作为|，|,|。|；|;).*$/g, '')
    .replace(/(为了|被迫|想要|发现|掌握|保护|追查|提出|进入|作为|因为|需要|可能|身份|地位).*$/g, '')
    .trim()
}

function _isValidLocalCharacterName(value: string) {
  const cleanName = _cleanLocalCharacterName(value)
  if (!cleanName || cleanName.length < 2 || cleanName.length > 6) return false
  if (!/^[\u4e00-\u9fa5]{2,6}$/.test(cleanName)) return false
  if (OUTLINE_LOCAL_NAME_EXCLUDES.has(cleanName)) return false
  if (OUTLINE_NON_CHARACTER_RE.test(cleanName)) return false
  return true
}

function _looksLikePlotText(value: string) {
  const text = _compactOutlineText(value, 600)
  if (!text) return false
  if (/【\s*场|场\s*\d+[-－]\d+|(?:^|[；;\n])\s*(?!(?:年龄|身份|职业|阵营|外貌|外观|视觉档案|视觉文档|视觉设定|人物性格|性格|说话方式|声线|音色|动机|目标|弱点|人物弧线|弧线|成长|背景|身世背景|身世|出身|功能|关系)\s*[：:])[\u4e00-\u9fa5]{2,6}\s*[：:][“"「]?/.test(text)) return true
  if (/第\s*[一二三四五六七八九十百\d]{1,4}\s*(集|场|级)/.test(text)) return true
  const bioHits = OUTLINE_CHARACTER_BIO_HINTS.filter(word => text.includes(word)).length
  const actionHits = OUTLINE_PLOT_ACTION_HINTS.filter(word => text.includes(word)).length
  return bioHits === 0 && actionHits >= 2
}

function _sanitizeLocalCharacterInfo(value: any, name = '', limit = 1000) {
  const cleanName = _cleanLocalCharacterName(name)
  const raw = String(value || '').replace(/\u00a0/g, ' ').replace(/\r/g, '\n')
  if (!raw.trim()) return ''
  const kept: string[] = []
  for (const line of raw.split('\n')) {
    const compact = line.split(/\s+/).join(' ').trim().replace(/^[ 　|]+|[ 　|]+$/g, '')
    if (!compact) continue
    if (OUTLINE_CHARACTER_INFO_STOP_RE.test(compact)) break
    if (_looksLikePlotText(compact)) break
    if (compact === '外貌参考') {
      if (kept.length) break
      continue
    }
    const visualLine = compact.match(/^([\u4e00-\u9fa5]{2,6})\s+(\d{1,3}\s*岁|少年|少女|青年|中年|老年|男性|女性|男|女)/)
    if (visualLine && kept.length) {
      const otherName = _cleanLocalCharacterName(visualLine[1] || '')
      if (otherName && otherName !== cleanName) break
    }
    kept.push(compact)
  }
  let text = kept.join('\n').trim()
  const stop = text.search(OUTLINE_CHARACTER_INFO_STOP_RE)
  if (stop >= 0) text = text.slice(0, stop).trim()
  text = _compactOutlineText(text, limit)
  if (_looksLikePlotText(text)) return ''
  if (/^[-—~\s\d岁）()（）]+$/.test(text)) return ''
  return text
}

function _sanitizeOutlineCharacters(rows: any[]) {
  if (!Array.isArray(rows)) return []
  const seen = new Set<string>()
  return rows
    .map((row, index) => {
      if (!row || typeof row !== 'object') return null
      const name = _cleanLocalCharacterName(row.name || '')
      if (!_isValidLocalCharacterName(name) || seen.has(name)) return null
      seen.add(name)
      const info = _sanitizeLocalCharacterInfo(row.info || row.background || '', name, 1200)
      const role = row.role === 'cameo' ? 'minor' : (row.role || (index === 0 ? 'protagonist' : 'supporting'))
      return {
        ...row,
        id: row.id || String(Date.now() + index),
        name,
        role,
        info,
        background: _sanitizeLocalCharacterInfo(row.background || info, name, 1200),
        relationships: Array.isArray(row.relationships)
          ? row.relationships.filter((rel: any) => {
              const targetName = String(rel?.targetName || rel?.target || '')
              return !targetName || _isValidLocalCharacterName(targetName)
            })
          : [],
      }
    })
    .filter(Boolean) as any[]
}

function _sanitizeWorkspaceCharacterRows(rows: any[]) {
  if (!Array.isArray(rows)) return []
  const textFields = [
    'info',
    'background',
    'notes',
    'appearance',
    'personality',
    'motivation',
    'arc',
    'traits',
    'voice_style',
    'voiceprint',
    'inner_need',
    'resource',
    'first_appearance_function',
    'relationship_tension',
  ]
  const seen = new Set<string>()
  return rows
    .map((row, index) => {
      if (!row || typeof row !== 'object') return null
      const name = _cleanLocalCharacterName(row.name || '')
      if (!_isValidLocalCharacterName(name) || seen.has(name)) return null
      seen.add(name)
      const item: any = { ...row, id: row.id || String(Date.now() + index), name }
      textFields.forEach((field) => {
        if (typeof item[field] === 'string' && item[field].trim()) {
          item[field] = _sanitizeLocalCharacterInfo(item[field], name, 1200)
        }
      })
      if (Array.isArray(item.relationships)) {
        item.relationships = item.relationships.filter((rel: any) => {
          const targetName = String(rel?.targetName || rel?.target || '')
          return !targetName || _isValidLocalCharacterName(targetName)
        })
      }
      return item
    })
    .filter(Boolean) as any[]
}

function _localCharacterRole(label: string, index: number): 'protagonist' | 'antagonist' | 'supporting' | 'minor' {
  if (/男主|女主|主角/.test(label)) return 'protagonist'
  if (/男反|女反|反派|反角|对手|敌方/.test(label)) return 'antagonist'
  if (index === 0) return 'protagonist'
  if (/刁难|构陷|陷害|觊觎|妄图|操控|终极对决|幕后|黑手/.test(label)) return 'antagonist'
  if (/男二|女二|配角/.test(label)) return 'supporting'
  if (/徒弟|师兄|师妹|丈夫|妻子|父亲|母亲|朋友|队友|伙伴|同盟|保护/.test(label)) return 'supporting'
  if (/龙套/.test(label)) return 'minor'
  return index === 1 ? 'supporting' : 'minor'
}

function _outlineCharacterScanText(outline: string) {
  const marker = outline.match(/(人物小传|人物设定|角色小传|角色设定|角色介绍|角色库|主要角色|角色列表|人物)(?:[（(][^）)]{1,40}[）)])?\s*[：:\n|]/)
  if (!marker || marker.index === undefined) return ''
  const tail = outline.slice(marker.index + marker[0].length)
  const end = tail.search(/\n\s*(第\s*[一二三四五六七八九十百\d]{1,4}\s*集|分集|集纲|剧情大纲|故事大纲|人物关系|角色关系|关系设计)\s*[：:\-、]?/)
  return end >= 0 ? tail.slice(0, end) : tail
}

function _outlineCharacterTableFieldLabel(label: string) {
  if (['参考例图', '外貌参考', '外貌', '外观', '视觉设定', '视觉文档'].includes(label)) return '视觉档案'
  if (label === '人物性格') return '性格'
  return label
}

function _appendLocalCharacterInfo(
  byName: Map<string, { name: string; role: 'protagonist' | 'antagonist' | 'supporting' | 'minor'; info: string }>,
  name: string,
  roleHint = '',
  ...parts: string[]
) {
  const cleanName = _cleanLocalCharacterName(name)
  if (!_isValidLocalCharacterName(cleanName)) return ''
  const text = parts.map(part => String(part || '').trim()).filter(Boolean).join('；')
  const info = _sanitizeLocalCharacterInfo(text, cleanName, 900)
  const existing = byName.get(cleanName)
  if (existing) {
    if (info && !existing.info.includes(info)) existing.info = _compactOutlineText(`${existing.info}\n${info}`, 1200)
    const role = _localCharacterRole(roleHint, byName.size)
    if (existing.role === 'minor' && role !== 'minor') existing.role = role
  } else {
    byName.set(cleanName, { name: cleanName, role: _localCharacterRole(roleHint, byName.size), info })
  }
  return cleanName
}

function _appendLocalCharacterSubfield(
  byName: Map<string, { name: string; role: 'protagonist' | 'antagonist' | 'supporting' | 'minor'; info: string }>,
  name: string,
  label: string,
  ...parts: string[]
) {
  const current = byName.get(name)
  if (!current) return
  const text = parts.map(part => String(part || '').trim()).filter(Boolean).join('；')
  const info = _sanitizeLocalCharacterInfo(text, name, 900)
  if (!info) return
  const field = _outlineCharacterTableFieldLabel(label)
  const line = field ? `${field}：${info}` : info
  if (!current.info.includes(line)) current.info = _compactOutlineText(`${current.info}\n${line}`, 1200)
}

function _extractLocalOutlineCharacterTableRows(
  byName: Map<string, { name: string; role: 'protagonist' | 'antagonist' | 'supporting' | 'minor'; info: string }>,
  outline: string,
) {
  let currentName = ''
  let insideCharacterTable = false
  String(outline || '').split('\n').forEach((line) => {
    if (!/[|｜]/.test(line)) return
    const cells = _splitOutlineRowCells(line)
    if (cells.length < 2) return
    const first = cells[0] || ''
    let subject = ''
    let payload: string[] = []
    if (OUTLINE_CHARACTER_TABLE_LABELS.has(first)) {
      insideCharacterTable = true
      subject = cells[1] || ''
      payload = cells.slice(2)
    } else if (insideCharacterTable && OUTLINE_CHARACTER_TABLE_SUBFIELDS.has(first) && currentName) {
      _appendLocalCharacterSubfield(byName, currentName, first, ...cells.slice(1))
      return
    } else if (insideCharacterTable && _isValidLocalCharacterName(first)) {
      subject = first
      payload = cells.slice(1)
    } else {
      return
    }
    if (OUTLINE_CHARACTER_TABLE_SUBFIELDS.has(subject)) {
      _appendLocalCharacterSubfield(byName, currentName, subject, ...payload)
      return
    }
    const nextName = _appendLocalCharacterInfo(byName, subject, payload.join(' '), ...payload)
    if (nextName) currentName = nextName
  })
}

function _addLocalCharacter(
  byName: Map<string, { name: string; role: 'protagonist' | 'antagonist' | 'supporting' | 'minor'; info: string }>,
  name: string,
  roleHint = '',
  info = '',
) {
  const cleanName = _cleanLocalCharacterName(name)
  if (!_isValidLocalCharacterName(cleanName)) return
  const role = _localCharacterRole(roleHint, byName.size)
  const compactInfo = _sanitizeLocalCharacterInfo(info, cleanName, 800)
  const existing = byName.get(cleanName)
  if (existing) {
    if (compactInfo && !existing.info.includes(compactInfo)) {
      existing.info = _compactOutlineText(`${existing.info}\n${compactInfo}`, 1000)
    }
    if (existing.role === 'minor' && role !== 'minor') existing.role = role
    return
  }
  byName.set(cleanName, { name: cleanName, role, info: compactInfo })
}

const OUTLINE_CHARACTER_SUBFIELD_LINE_RE = /(?:年龄|性别|身份|职业|阵营|性格|人物性格|背景|身世背景|遭遇|动机|目标|弱点|人物弧线|弧线|成长|外貌|外观|关系|人物关系|角色关系)\s*[：:=＝]/

function _extractLocalOutlineNameBlocks(
  byName: Map<string, { name: string; role: 'protagonist' | 'antagonist' | 'supporting' | 'minor'; info: string }>,
  scanText: string,
) {
  const blockHeaderRe = /(?:^|\n)\s*(?:[-*•]\s*)?([\u4e00-\u9fa5]{2,6})(?:[（(]([^）)]{1,16})[）)])?\s*(?=\n\s*(?:年龄|性别|身份|职业|阵营|性格|人物性格|背景|身世背景|遭遇|动机|目标|弱点|人物弧线|弧线|成长|外貌|外观|关系|人物关系|角色关系)\s*[：:=＝])/g
  const blocks = [...String(scanText || '').matchAll(blockHeaderRe)]
  blocks.forEach((match, index) => {
    const start = (match.index ?? 0) + match[0].length
    const nextStart = blocks[index + 1]?.index ?? scanText.length
    const info = scanText.slice(start, nextStart).trim()
    if (!OUTLINE_CHARACTER_SUBFIELD_LINE_RE.test(info)) return
    _addLocalCharacter(byName, match[1] || '', `${match[2] || ''} ${info.slice(0, 220)}`, info)
  })
}

function _extractLocalInlineCharacterListRows(
  byName: Map<string, { name: string; role: 'protagonist' | 'antagonist' | 'supporting' | 'minor'; info: string }>,
  scanText: string,
) {
  const inlineCharacterRe = /(?:^|[。；;\n\r])\s*(?:[-*•]\s*)?([\u4e00-\u9fa5]{2,6})\s*[，,、]\s*([^。；;\n\r]{2,260})/g
  const characterSignalRe = /男主|女主|主角|反派|反角|对手|配角|龙套|男二|女二|身份|职业|动机|目标|弧线|背景|身世|性格|外冷|内热|守城|女将|木匠|学徒|少年|少女|青年|中年|豪族|重生|首领|领袖/
  for (const match of String(scanText || '').matchAll(inlineCharacterRe)) {
    const name = _cleanLocalCharacterName(match[1] || '')
    const info = _compactOutlineText(match[2] || '', 260)
    if (!_isValidLocalCharacterName(name) || !info || !characterSignalRe.test(info)) continue
    if (_looksLikePlotText(info)) continue
    _addLocalCharacter(byName, name, info.slice(0, 120), info)
  }
}

function _extractLabeledCharacterBlock(outline: string) {
  const text = String(outline || '').replace(/\r/g, '\n')
  const labelRe = /(?:^|[\n。；;])\s*(?:角色|主要角色|人物|人物小传|角色库)\s*[：:]\s*/u
  const match = labelRe.exec(text)
  if (!match || match.index === undefined) return ''
  const start = match.index + match[0].length
  const rest = text.slice(start)
  const stopRe = /(?:^|[\n。；;]\s*|\s{2,})(?:分集|集纲|第\s*[一二三四五六七八九十百\d]{1,4}\s*(?:集|级)|世界观|核心冲突|金手指|特殊设定|范围集纲)\s*[：:]?/u
  const stop = rest.search(stopRe)
  return _compactOutlineText(stop >= 0 ? rest.slice(0, stop) : rest, 2600)
}

function _extractCharactersFromLabeledBlock(outline: string) {
  const block = _extractLabeledCharacterBlock(outline)
  if (!block) return []
  const entryRe = /(?:^|[\n。；;]\s*|\s+)(?:(男主|女主|男反|女反|男二|女二|反派|反角|配角|龙套|主角|对手)\s*)?([\u4e00-\u9fa5]{2,6})(?:[（(]([^）)]{1,16})[）)])?\s*[：:]\s*/g
  const entries = [...block.matchAll(entryRe)].filter((match) => _isValidLocalCharacterName(match[2] || ''))
  return entries
    .map((match, index) => {
      const name = _cleanLocalCharacterName(match[2] || '')
      const nextStart = entries[index + 1]?.index ?? block.length
      const rawInfo = block.slice((match.index ?? 0) + match[0].length, nextStart)
      const info = _sanitizeLocalCharacterInfo(rawInfo, name, 700)
      if (!info) return null
      return {
        name,
        roleHint: `${match[1] || ''} ${match[3] || ''}`.trim(),
        info,
      }
    })
    .filter(Boolean) as Array<{ name: string; roleHint: string; info: string }>
}

function _extractLocalOutlineCharacters(outline: string) {
  const byName = new Map<string, { name: string; role: 'protagonist' | 'antagonist' | 'supporting' | 'minor'; info: string }>()
  _extractLocalOutlineCharacterTableRows(byName, outline)
  _extractCharactersFromLabeledBlock(outline).forEach(character => {
    _addLocalCharacter(byName, character.name, character.roleHint, character.info)
  })
  const scanText = _outlineCharacterScanText(outline)
  _extractLocalInlineCharacterListRows(byName, scanText)
  _extractLocalOutlineNameBlocks(byName, scanText)
  const labelRe = /(?:^|\n)\s*(?:[-*•]\s*)?(?:(男主|女主|男反|女反|男二|女二|反派|反角|配角|龙套|主角|对手)\s*)?([\u4e00-\u9fa5]{2,6})(?:[（(]([^）)]{1,16})[）)])?\s*[：:]\s*/g
  const labels = [...scanText.matchAll(labelRe)]
  labels.forEach((match, index) => {
    const nextStart = labels[index + 1]?.index ?? scanText.length
    const info = scanText.slice((match.index ?? 0) + match[0].length, nextStart).trim()
    _addLocalCharacter(byName, match[2] || '', `${match[1] || match[3] || ''} ${info.slice(0, 220)}`, info)
  })
  const rolePhraseRe = /(男主|女主|男反|女反|男二|女二|反派|反角|配角|龙套|主角|对手)\s*([\u4e00-\u9fa5]{2,6})/g
  for (const match of scanText.matchAll(rolePhraseRe)) {
    const index = match.index ?? 0
    const nearby = scanText.slice(Math.max(0, index - 40), index + 240)
    _addLocalCharacter(byName, match[2] || '', match[1] || '', nearby)
  }
  const visualLineRe = /(?:^|\n)\s*(?:[-*•]\s*)?([\u4e00-\u9fa5]{2,6})(?:[（(][^）)]{1,16}[）)])?\s+((?:\d{1,3}\s*岁|少年|少女|青年|中年|老年|男性|女性|男|女)[^\n\r]{4,160})/g
  for (const match of scanText.matchAll(visualLineRe)) {
    _addLocalCharacter(byName, match[1] || '', '', match[2] || '')
  }

  return [...byName.values()].slice(0, 12)
}

function _inferLocalRelationshipType(text: string) {
  if (/反派|仇敌|敌对|对抗|阻止|掩盖|陷害|纠缠|威胁|追杀|刁难|构陷|幕后|压迫|伪证|施压|阻断|围剿|反制|设局/.test(text)) return '对抗'
  if (/同盟|合作|帮助|保护|救|扶持|掌握证据|共同|联手/.test(text)) return '协作'
  if (/夫妻|丈夫|妻子|老公|老婆|前夫|前妻/.test(text)) return '夫妻/婚姻'
  if (/父子|父女|母子|母女|亲子|儿子|女儿|父亲|母亲/.test(text)) return '亲子/亲属'
  if (/师徒|师父|徒弟/.test(text)) return '师徒'
  if (/兄弟|姐妹|兄妹|姐弟|兄长|阿兄/.test(text)) return '手足'
  if (/暗恋|喜欢|爱|恋/.test(text)) return '情感牵引'
  return '关系'
}

function _relationshipLooksAntagonistic(text: string) {
  return /反派|仇敌|敌对|对抗|阻止|掩盖|陷害|纠缠|威胁|追杀|刁难|构陷|幕后|压迫|伪证|施压|阻断|围剿|反制|设局/.test(text)
}

function _relationshipLooksSupportive(text: string) {
  return /同盟|合作|帮助|保护|救|扶持|掌握证据|共同|联手|短暂结盟|承担风险/.test(text)
}

function _pushLocalRelationship(
  rows: any[],
  seen: Set<string>,
  source: string,
  target: string,
  raw: string,
) {
  const description = _compactOutlineText(raw || '', 140)
  if (!description) return
  const type = _inferLocalRelationshipType(description)
  const key = `${source}__${target}__${type}`
  if (seen.has(key)) return
  seen.add(key)
  rows.push({ source, target, type, description, strength: type === '对抗' ? 82 : 70 })
}

function _extractLocalOutlineRelationships(outline: string, chars: Array<{ name: string }>) {
  const names = chars.map(char => String(char.name || '').trim()).filter(_isValidLocalCharacterName)
  if (names.length < 2) return []
  const sectionMatch = outline.match(/(?:人物关系|角色关系|关系设计|关系表)\s*[：:\n]([\s\S]{0,1600})/)
  let text = sectionMatch?.[1] || _outlineCharacterScanText(outline)
  if (!text) text = String(outline || '').slice(0, 5000)
  if (!text) return []
  const stop = text.search(/\n\s*(?:第\s*[一二三四五六七八九十百\d]{1,4}\s*集|分集|集纲|剧情大纲|故事大纲|视觉档案|视觉文档)\s*[：:\-、]?/)
  if (stop >= 0) text = text.slice(0, stop)
  const rows: any[] = []
  const seen = new Set<string>()
  const relationMarkerRe = /夫妻|丈夫|妻子|亲子|父亲|母亲|师徒|徒弟|师父|仇敌|敌对|对抗|阻止|掩盖|陷害|纠缠|威胁|追杀|合作|同盟|保护|掌握证据|共同|联手|幕后|反派|压迫|伪证|施压|阻断|围剿|反制|设局/
  names.forEach((source) => {
    names.forEach((target) => {
      if (source === target) return
      const pattern = new RegExp(`${source}\\s*(?:与|和|对|vs|VS|—|-)\\s*${target}(?:[（(]([^）)]{1,80})[）)]|[：:，,]\\s*([^。！？!?；;\\n，,]{1,120})|\\s*(合作|协作|联手|保护|对抗|敌对|仇敌|情感牵引|夫妻|师徒))?`, 'g')
      for (const match of text.matchAll(pattern)) {
        const raw = _compactOutlineText(match[1] || match[2] || match[3] || '', 120)
        _pushLocalRelationship(rows, seen, source, target, raw)
      }
    })
  })
  const sentences = String(text || '').split(/[。！？!?；;\n，,]+/).map(item => item.trim()).filter(Boolean)
  sentences.forEach((sentence) => {
    const owner = names.find(name => new RegExp(`^\\s*${name}\\s*[：:]`).test(sentence))
    if (owner) {
      names.forEach((target) => {
        if (owner !== target && sentence.includes(target)) {
          _pushLocalRelationship(rows, seen, owner, target, sentence)
        }
      })
      return
    }
    const presentNames = names.filter(name => sentence.includes(name))
    if (presentNames.length < 2) return
    if (presentNames.length === 2) {
      const [source, target] = presentNames
      if (source && target && relationMarkerRe.test(sentence)) {
        _pushLocalRelationship(rows, seen, source, target, sentence)
      }
      return
    }
    for (let i = 0; i < presentNames.length; i += 1) {
      for (let j = i + 1; j < presentNames.length; j += 1) {
        const source = presentNames[i]
        const target = presentNames[j]
        if (!source || !target) continue
        const sourceIdx = sentence.indexOf(source)
        const targetIdx = sentence.indexOf(target)
        if (sourceIdx < 0 || targetIdx < 0) continue
        const start = Math.max(0, Math.min(sourceIdx, targetIdx) - 24)
        const end = Math.min(sentence.length, Math.max(sourceIdx + source.length, targetIdx + target.length) + 36)
        const near = sentence.slice(start, end)
        if (relationMarkerRe.test(near)) _pushLocalRelationship(rows, seen, source, target, near)
      }
    }
  })
  return rows.slice(0, 24)
}

function _splitOutlineRowCells(line: string) {
  return String(line || '')
    .split(/[|｜]/)
    .map(cell => cell.trim())
    .filter(Boolean)
    .filter(cell => !/^:?-{2,}:?$/.test(cell))
}

function _parseChineseEpisodeNumber(value: string) {
  const digit = value.match(/\d{1,3}/)?.[0]
  if (digit) return Number(digit)
  const nums: Record<string, number> = {
    一: 1, 二: 2, 三: 3, 四: 4, 五: 5, 六: 6, 七: 7, 八: 8, 九: 9,
  }
  if (value === '十') return 10
  if (value.startsWith('十')) return 10 + (nums[value.slice(1)] || 0)
  if (value.includes('十')) {
    const [ten = '', one = ''] = value.split('十')
    return (nums[ten] || 1) * 10 + (nums[one] || 0)
  }
  return nums[value] || 0
}

function _stripEpisodeHeading(chunk: string) {
  return String(chunk || '')
    .trim()
    .replace(/^\s*(?:第\s*)?[一二三四五六七八九十百\d]{1,4}\s*(?:集|级)[：:、\-\.\s]*[^\n\r]*/u, '')
    .trim()
}

function _outlineChunkHasScriptBody(chunk: string) {
  const text = _stripEpisodeHeading(chunk)
  if (text.length < 24) return false
  const dialogueLines = text.match(/^\s*[\u4e00-\u9fa5]{2,6}\s*[：:].{2,}/gm) || []
  const sceneHeaders = text.match(/(【[^】]{2,40}】|\b(内|外|日|夜)\b|场\s*\d+|第\s*\d+\s*场)/g) || []
  const actionMarks = (text.match(/△/g) || []).length + (text.match(/^\s*[动作景]?描写\s*[：:]/gm) || []).length
  return dialogueLines.length >= 2 || (dialogueLines.length >= 1 && sceneHeaders.length >= 1) || actionMarks >= 1
}

function _extractRangeOutlineEpisodes(outline: string, episodeCap: number) {
  const pattern = /(?:第\s*)?(\d{1,3})\s*[-~～—至到]\s*(\d{1,3})\s*集\s*[：:、\-\s]*([^\n\r]*)/g
  const matches = [...outline.matchAll(pattern)]
  if (!matches.length) return []
  const episodes: any[] = []
  matches.forEach((match, index) => {
    const start = Number(match[1])
    const end = Number(match[2])
    if (!Number.isFinite(start) || !Number.isFinite(end) || start <= 0 || end < start || end > 200) return
    const nextIndex = matches[index + 1]?.index ?? outline.length
    const body = _compactOutlineText(`${match[3] || ''}\n${outline.slice((match.index ?? 0) + match[0].length, nextIndex)}`, 600)
    if (!body) return
    for (let ep = start; ep <= Math.min(end, episodeCap); ep += 1) {
      episodes.push({
        episodeNumber: ep,
        title: `第${ep}集`,
        summary: _compactOutlineText(body, 260),
        conflict: _pickOutlineSentence(body, ['冲突', '阻碍', '危险', '对抗', '追查', '揭露'], 0),
        turning: _pickOutlineSentence(body, ['转折', '爆点', '却', '突然', '发现', '反转'], 1),
      })
    }
  })
  return episodes.slice(0, episodeCap)
}

function _extractTableOutlineEpisodes(outline: string, episodeCap: number) {
  const episodes: any[] = []
  let insideEpisodeTable = false
  let epIndex = 0
  let titleIndex = 1
  let contentIndex = 2
  String(outline || '').split('\n').forEach((line) => {
    if (!/[|｜]/.test(line)) return
    const cells = _splitOutlineRowCells(line)
    if (cells.length < 2) return
    const normalized = cells.map(cell => cell.replace(/\s+/g, ''))
    const hasEpisodeHeader = normalized.some(cell => /^(集数|集|序号|集次|episode)$/i.test(cell))
    const hasTitleHeader = normalized.some(cell => /^(标题|本集标题|集名)$/.test(cell))
    const hasContentHeader = normalized.some(cell => /^(内容|集纲|剧情|梗概|单集集纲|summary)$/i.test(cell))
    if (hasEpisodeHeader && (hasTitleHeader || hasContentHeader)) {
      insideEpisodeTable = true
      epIndex = Math.max(0, normalized.findIndex(cell => /^(集数|集|序号|集次|episode)$/i.test(cell)))
      const nextTitleIndex = normalized.findIndex(cell => /^(标题|本集标题|集名)$/.test(cell))
      const nextContentIndex = normalized.findIndex(cell => /^(内容|集纲|剧情|梗概|单集集纲|summary)$/i.test(cell))
      titleIndex = nextTitleIndex >= 0 ? nextTitleIndex : 1
      contentIndex = nextContentIndex >= 0 ? nextContentIndex : Math.min(cells.length - 1, titleIndex + 1)
      return
    }
    if (!insideEpisodeTable) return
    const epNo = _parseChineseEpisodeNumber(cells[epIndex] || '')
    if (!epNo || epNo > episodeCap) return
    const title = _compactOutlineText(cells[titleIndex] || `第${epNo}集`, 120)
    const summary = _compactOutlineText(cells[contentIndex] || cells.slice(1).join('，'), 260)
    if (!summary && !title) return
    episodes.push({
      episodeNumber: epNo,
      title: title || `第${epNo}集`,
      summary,
      conflict: _pickOutlineSentence(summary, ['冲突', '阻碍', '危险', '对抗', '追查', '揭露', '压迫'], 0),
      turning: _pickOutlineSentence(summary, ['转折', '爆点', '却', '突然', '发现', '反转', '公开'], 1),
    })
  })
  return episodes.slice(0, episodeCap)
}

function _extractLocalOutlineEpisodes(outline: string, targetEpisodes?: number) {
  const episodeCap = Math.min(targetEpisodes || OUTLINE_ANALYZE_LOCAL_EPISODE_CAP, OUTLINE_ANALYZE_LOCAL_EPISODE_CAP)
  const headingRe = /(?:^|[\n\r])\s*(?:#{1,6}\s*)?(?:第\s*)?([一二三四五六七八九十百\d]{1,4})\s*(?:集|级)[：:、\-\.\s]*([^\n\r。！？!?]{0,220})/g
  const headings: Array<{ index: number; ep: number; lineText: string }> = []
  let match: RegExpExecArray | null
  while ((match = headingRe.exec(outline)) !== null) {
    headings.push({
      index: match.index,
      ep: _parseChineseEpisodeNumber(match[1] || '') || headings.length + 1,
      lineText: _compactOutlineText(match[2] || '', 260),
    })
  }

  if (headings.length > 0) {
    const episodes = headings.slice(0, OUTLINE_ANALYZE_LOCAL_EPISODE_CAP).map((heading, index) => {
      const next = headings[index + 1]?.index ?? outline.length
      const chunk = outline.slice(heading.index, next)
      const sentences = _splitOutlineSentences(chunk)
      const existingScript = _outlineChunkHasScriptBody(chunk) ? _stripEpisodeHeading(chunk) : ''
      const summary = heading.lineText || _compactOutlineText(sentences.slice(0, 3).join('。'), 260) || (existingScript ? '原稿正文已识别，剧本写作中将直接承接原文。' : '')
      return {
        episodeNumber: heading.ep,
        title: `第${heading.ep}集`,
        summary,
        conflict: _pickOutlineSentence(chunk, ['冲突', '发现', '分手', '危险', '追', '逃', '杀', '秘密'], 1),
        turning: _pickOutlineSentence(chunk, ['转折', '爆点', '却', '突然', '没想到', '发现'], 2),
        existing_script: existingScript,
      }
    })
    const merged = new Map<number, any>()
    episodes.forEach((episode) => {
      const epNo = Number(episode.episodeNumber || 0)
      if (!epNo || epNo > OUTLINE_ANALYZE_LOCAL_EPISODE_CAP) return
      const current = merged.get(epNo)
      if (!current) {
        merged.set(epNo, episode)
        return
      }
      if (episode.existing_script && !current.existing_script) current.existing_script = episode.existing_script
      if (!current.summary && episode.summary) current.summary = episode.summary
      if (!current.conflict && episode.conflict) current.conflict = episode.conflict
      if (!current.turning && episode.turning) current.turning = episode.turning
    })
    return [...merged.values()].sort((a, b) => Number(a.episodeNumber) - Number(b.episodeNumber))
  }

  const tableEpisodes = _extractTableOutlineEpisodes(outline, episodeCap)
  if (tableEpisodes.length) return tableEpisodes

  const rangeEpisodes = _extractRangeOutlineEpisodes(outline, episodeCap)
  if (rangeEpisodes.length) return rangeEpisodes

  return []
}

function _buildLocalOutlineAnalysis(outline: string, targetEpisodes?: number) {
  const genre = _inferLocalOutlineGenre(outline)
  const characters = _extractLocalOutlineCharacters(outline)
  const episodes = _extractLocalOutlineEpisodes(outline, targetEpisodes)
  return {
    genre,
    sellingPoints: {
      logline: _deriveLocalOutlineLogline(outline),
      worldview: _pickLabeledOutlineValue(outline, ['世界观', '背景设定', '故事背景', '时代背景'], 260),
      uniqueness: _pickLabeledOutlineValue(outline, ['金手指', '特殊设定', '差异化', '核心设定'], 260),
      conflict: _pickLabeledOutlineValue(outline, ['核心冲突', '主要矛盾', '全剧冲突'], 260),
    },
    characters,
    relationships: _extractLocalOutlineRelationships(outline, characters),
    episodes,
  }
}

function _hasUsefulOutlineAnalysis(result: any) {
  return Boolean(
    result?.sellingPoints?.logline
    || result?.sellingPoints?.conflict
    || result?.characters?.length
    || result?.episodes?.length,
  )
}

function _applyOutlineAnalysisResult(result: any) {
  // 一句话梗概必须描述故事本身，不再用 hook/题材标签兜底。
  const extractedLogline = result.sellingPoints?.logline || ''
  if (extractedLogline && _outlinePredictionHasEvidence(extractedLogline, 2)) {
    outlineData.value.logline = extractedLogline
  }
  // 若 logline 未被AI填充，保持用户原有内容不变

  // 世界观/金手指/冲突没有明确提取时保持空白，提醒用户自行补充或手动触发 AI 优化。
  const extractedWorldview = result.sellingPoints?.worldview || ''
  if (extractedWorldview && _outlinePredictionHasEvidence(extractedWorldview, 1)) {
    outlineData.value.worldview = extractedWorldview
  }

  // 角色 → 简单映射：name + role + info（所有字段合并进 info）
  if (result.characters?.length) {
    const safeCharacters = result.characters
      .map((c: any, i: number) => ({ c, i, name: _cleanLocalCharacterName(c?.name || `角色${i + 1}`) }))
      .filter((item: any) => _isValidLocalCharacterName(item.name))
      .filter((item: any) => _outlineNameHasEvidence(item.name))
    outlineCharacters.value = _sanitizeOutlineCharacters(safeCharacters.map(({ c, i, name }: any) => {
      const role = (c.role === 'cameo' ? 'minor' : c.role) || 'supporting'
      // 优先直接用 info 字段；否则把所有细分字段拼合成一段自由文本
      let info = c.info || ''
      if (!info) {
        const parts: string[] = []
        const traits = Array.isArray(c.traits) ? c.traits.join('、') : (c.traits || '')
        if (c.occupation) parts.push(`职业：${c.occupation}`)
        if (c.appearance) parts.push(`外貌：${c.appearance}`)
        if (traits) parts.push(`性格标签：${traits}`)
        if (c.personality) parts.push(`性格：${c.personality}`)
        if (c.voice_style) parts.push(`说话方式：${c.voice_style}`)
        if (c.background) parts.push(`背景：${c.background}`)
        if (c.motivation) parts.push(`动机：${c.motivation}`)
        if (c.arc) parts.push(`弧线：${c.arc}`)
        if (c.notes) parts.push(`补充：${c.notes}`)
        if (Array.isArray(c.relationships) && c.relationships.length) {
          const relText = c.relationships
            .filter((r: any) => r.target_name)
            .map((r: any) => `与${r.target_name}（${r.type}${r.description ? '，' + r.description : ''}）`)
            .join('；')
          if (relText) parts.push(`关系：${relText}`)
        }
        info = parts.join('\n')
      }
      return {
        id: String(Date.now() + i),
        name,
        role,
        info: _sanitizeLocalCharacterInfo(info, name, 1200),
        relationships: Array.isArray(c.relationships) ? c.relationships : [],
      }
    }))
    const relationshipRows = Array.isArray(result.relationships)
      ? result.relationships
      : Array.isArray(result.relationship_table)
        ? result.relationship_table
        : []
    _attachAnalysisRelationshipsToOutlineCharacters(relationshipRows)
  }

  // 金手指 = uniqueness（差异化卖点）= 大纲中的核心特殊设定
  // suggestions 是改进建议，不放进金手指字段
  const uniqueness = result.sellingPoints?.uniqueness || ''
  if (uniqueness && _outlinePredictionHasEvidence(uniqueness, 1)) {
    outlineData.value.goldenFinger = uniqueness
  }

  // 受众轴 → 从 genre.target 推断
  const target = result.genre?.target || ''
  if (target.includes('男') || result.genre?.category?.includes('男频')) {
    outlineData.value.audience_axis = '男频'
  } else if (target.includes('女') || result.genre?.category?.includes('女频')) {
    outlineData.value.audience_axis = '女频'
  } else if (outlineData.value.audience_axis === '') {
    outlineData.value.audience_axis = '混合'
  }

  // 主题材 → 从 genre.subCategory 或 category
  const genreMain = result.genre?.subCategory || result.genre?.category || ''
  if (genreMain) {
    outlineData.value.genre_main = genreMain
  }

  // 核心冲突 = sellingPoints.conflict
  if (result.sellingPoints?.conflict && _outlinePredictionHasEvidence(result.sellingPoints.conflict, 1)) {
    outlineData.value.conflict = result.sellingPoints.conflict
  }

  // 集纲 = episodes[]
  if (result.episodes?.length) {
    outlineData.value.episodes = result.episodes
      .map(_normalizeEditorEpisode)
      .filter((ep: any) => (
        !_isGeneratedOutlineNoiseEpisode(ep)
        && _outlinePredictionHasEvidence([ep.title, ep.summary, ep.conflict, ep.turning, ep.hook].filter(Boolean).join('\n'), 1)
      ))
  }
}

async function _persistOutlineAnalysis(outline: string) {
  if (outline) saveWorkspaceStorage('rawOutline', projectId.value, outline)
  await _persistOutlineDraft('outline_analyzed_draft', { silent: true })
}

function _standardOutlinePacketForGeneration() {
  const stored = workflowContext.value.outline_state?.standard_outline_packet
  if (stored && typeof stored === 'object') {
    return normalizeStandardOutlinePacket(stored)
  }
  return normalizeStandardOutlinePacket(standardOutlinePacket.value)
}

function _standardOutlinePacketGateIssues(target: StandardOutlineGateTarget = 'episode_outlines') {
  return diagnoseStandardOutlinePacketGate(_standardOutlinePacketForGeneration(), target)
}

const STANDARD_OUTLINE_GATE_USER_HINTS = [
  '请先确认总集数',
  '请先确认分集集纲',
]

function _buildOutlineGenerationText() {
  const packetProjection = projectStandardOutlinePacketToOutline(_standardOutlinePacketForGeneration())
  const packetOutline = packetProjection.rawOutlineText
  const context = [
    packetOutline,
    rawOutlineText.value,
    outlineData.value.logline ? `简介：${outlineData.value.logline}` : '',
    outlineData.value.worldview ? `世界观：${outlineData.value.worldview}` : '',
    outlineData.value.goldenFinger ? `差异化/金手指：${outlineData.value.goldenFinger}` : '',
    outlineData.value.conflict ? `核心冲突：${outlineData.value.conflict}` : '',
    outlineCharacters.value.length > 0
      ? `主要角色：${outlineCharacters.value.map(c => `${c.name}(${c.role}，${c.info})`).join('；')}`
      : '',
  ].filter(Boolean).join('\n')
  return context
}

function _outlinePredictionSeedAnalysis() {
  return {
    sellingPoints: {
      logline: outlineData.value.logline,
      worldview: outlineData.value.worldview,
      conflict: outlineData.value.conflict,
      uniqueness: outlineData.value.goldenFinger,
      goldenFinger: outlineData.value.goldenFinger,
    },
    characters: outlineCharacters.value.map(c => ({ name: c.name, role: c.role, info: c.info })),
    episodes: outlineData.value.episodes.map(ep => ({
      episodeNumber: ep.ep,
      title: ep.title,
      episode_outline: ep.summary,
      conflict: ep.conflict,
      turning: ep.turning,
      main_scene: (ep as any).main_scene,
      relationship_change: (ep as any).relationship_change,
      info_revealed: (ep as any).info_revealed,
      satisfaction_type: (ep as any).satisfaction_type,
      stage: (ep as any).stage,
      existing_script: (ep as any).existing_script || '',
    })),
  }
}

function _predictionText(value: any): string {
  if (value === null || value === undefined) return ''
  if (typeof value === 'string') return value.trim()
  if (Array.isArray(value)) return value.map(_predictionText).filter(Boolean).join('；')
  if (typeof value === 'object') {
    return _predictionText(value.content || value.summary || value.text || value.title || value.episode_outline || value.description)
  }
  return String(value).trim()
}

function _outlinePredictionEvidenceText() {
  return [
    rawOutlineText.value,
    outlineData.value.logline,
    outlineData.value.worldview,
    outlineData.value.goldenFinger,
    outlineData.value.conflict,
    outlineCharacters.value.map((char: any) => `${char.name}\n${char.info || ''}`).join('\n'),
    outlineData.value.episodes
      .map((ep: any) => `${ep.title || ''}\n${ep.summary || ''}\n${ep.conflict || ''}\n${ep.turning || ''}\n${ep.hook || ''}`)
      .join('\n'),
  ].filter(Boolean).join('\n')
}

function _outlinePredictionEvidenceTokens(value: any) {
  const stop = /^(本集|主角|反派|配角|角色|人物|关系|冲突|剧情|故事|大纲|继续|推进|发现|突然|秘密|真相|证据|目标|核心|阶段|开场|结尾|尾钩)$/
  return Array.from(new Set(
    _predictionText(value)
      .match(/[\u4e00-\u9fa5]{2,8}/g)
      ?.map(token => token.trim())
      .filter(token => token.length >= 2 && !stop.test(token))
      .slice(0, 30) || [],
  ))
}

function _outlinePredictionHasEvidence(value: any, minHits = 1) {
  const evidence = _outlinePredictionEvidenceText()
  const text = _predictionText(value)
  if (!text || !evidence.trim()) return false
  if (text.length >= 6 && evidence.includes(text.slice(0, Math.min(24, text.length)))) return true
  const hits = _outlinePredictionEvidenceTokens(text).filter(token => evidence.includes(token))
  return hits.length >= minHits
}

function _outlineNameHasEvidence(name: string) {
  const cleanName = _cleanLocalCharacterName(name)
  return Boolean(cleanName && _outlinePredictionEvidenceText().includes(cleanName))
}

function _markOutlineAiGenerated(field: string) {
  outlineAiGeneratedFields.value = { ...outlineAiGeneratedFields.value, [field]: 'AI补全' }
}

function _outlineFallbackCandidateBoundaryFromPayload(payload: any, reason = 'local_fallback') {
  if (!payload || typeof payload !== 'object') return null
  if (!payload.fallback && payload.candidate_source !== 'local_fallback') return null
  return {
    candidate_source: 'local_fallback',
    needs_user_confirmation: true,
    main_chain_committed: false,
    downstream_generation_allowed: false,
    fallback_reason: _predictionText(payload.fallback_reason || ''),
    candidate_boundary_reason: _predictionText(payload.candidate_boundary_reason || reason),
    updated_at: new Date().toISOString(),
  }
}

function _setOutlineFallbackCandidateBoundary(payload: any, reason = 'local_fallback') {
  const boundary = _outlineFallbackCandidateBoundaryFromPayload(payload, reason)
  if (boundary) outlineFallbackCandidateBoundary.value = boundary
  return boundary
}

function _clearOutlineFallbackCandidateBoundary() {
  outlineFallbackCandidateBoundary.value = null
}

function _outlineFieldNeedsPredictionFill(field: 'logline' | 'worldview' | 'goldenFinger' | 'conflict') {
  const current = String(outlineData.value[field] || '').trim()
  if (!current) return true
  if (field === 'logline') {
    return _isOutlineCategorySummary(current) || /^故事大纲[：:]\s*(现代|都市|男频|女频|悬疑|短剧)/.test(current)
  }
  if (field === 'worldview') {
    return /^故事大纲[：:]/.test(current) && _isOutlineCategorySummary(current)
  }
  if (field === 'goldenFinger') {
    return /核心冲突|主要矛盾|全剧冲突/.test(current) || current === String(outlineData.value.conflict || '').trim()
  }
  return false
}

function _fillMissingOutlineField(field: 'logline' | 'worldview' | 'goldenFinger' | 'conflict', value: any) {
  const text = _predictionText(value)
  if (!text || !_outlineFieldNeedsPredictionFill(field)) return false
  if (!_outlinePredictionHasEvidence(text, field === 'logline' ? 2 : 1)) return false
  outlineData.value[field] = text as any
  _markOutlineAiGenerated(field)
  return true
}

function _normalizePredictedOutlineCharacter(char: any, index: number): {
  id: string
  name: string
  role: 'protagonist' | 'antagonist' | 'supporting' | 'minor'
  info: string
  relationships?: Array<Record<string, unknown> | string>
} | null {
  const name = _cleanLocalCharacterName(_predictionText(char?.name || char?.character_name).replace(/[()（）].*/g, ''))
  if (!_isValidLocalCharacterName(name)) return null
  if (!_outlineNameHasEvidence(name)) return null
  const roleText = _predictionText(char?.role || char?.position || char?.type)
  const role: 'protagonist' | 'antagonist' | 'supporting' | 'minor' = /主角|男主|女主|protagonist|lead/i.test(roleText)
    ? 'protagonist'
    : /反派|对手|敌|antagonist|villain/i.test(roleText)
      ? 'antagonist'
      : /客串|路人|minor|cameo/i.test(roleText)
        ? 'minor'
        : 'supporting'
  const info = [
    _predictionText(char?.info || char?.description || char?.background),
    _predictionText(char?.identity || char?.occupation) && `身份：${_predictionText(char?.identity || char?.occupation)}`,
    _predictionText(char?.motivation || char?.goal) && `动机：${_predictionText(char?.motivation || char?.goal)}`,
    _predictionText(char?.arc || char?.growth) && `弧线：${_predictionText(char?.arc || char?.growth)}`,
  ].filter(Boolean).join('\n')
  const safeInfo = _sanitizeLocalCharacterInfo(info, name, 1000)
  const relationships = Array.isArray(char?.relationships)
    ? char.relationships
        .map(_normalizeOutlineRelationshipRecord)
        .filter(Boolean)
        .map((rel: any) => ({
          ...rel,
          candidateStatus: rel.candidateStatus || 'needs_user_confirmation',
        }))
    : []
  return {
    id: String(Date.now() + index),
    name,
    role,
    info: safeInfo,
    relationships,
  }
}

function _mergePredictedOutlineCharacters(items: any[]) {
  let changed = false
  const existing = new Map(outlineCharacters.value.map(char => [char.name.trim(), char]))
  items.forEach((item, index) => {
    const normalized = _normalizePredictedOutlineCharacter(item, index)
    if (!normalized) return
    const current = existing.get(normalized.name)
    if (current) {
      if (!current.info.trim() && normalized.info) {
        current.info = normalized.info
        changed = true
      }
      if (!current.role && normalized.role) {
        current.role = normalized.role
        changed = true
      }
      if ((!Array.isArray((current as any).relationships) || !(current as any).relationships.length) && normalized.relationships?.length) {
        ;(current as any).relationships = normalized.relationships
        changed = true
      }
      return
    }
    outlineCharacters.value.push(normalized as any)
    existing.set(normalized.name, normalized as any)
    changed = true
  })
  if (changed) {
    _markOutlineAiGenerated('characters')
  }
  return changed
}

function _outlineEpisodeFieldIsLowQuality(value: any) {
  const text = String(value || '').trim()
  if (!text) return true
  return /尾钩|结尾钩子|开场钩子|cliffhanger|opening_hook|ending_hook|hook/i.test(text)
    || /继续推进|继续调查|继续冲突|主线事件继续|围绕“|开端阶段|升级阶段|收束阶段|铺垫/.test(text)
}

function _episodeNeedsPredictionFill(ep: any) {
  return _outlineEpisodeFieldIsLowQuality(ep?.summary)
}

function _mergePredictedOutlineEpisodes(items: any[]) {
  const predicted = items
    .map(_normalizeEditorEpisode)
    .filter(ep => (
      (ep.summary || ep.title)
      && !_isGeneratedOutlineNoiseEpisode(ep)
      && _outlinePredictionHasEvidence([ep.title, ep.summary, ep.conflict, ep.turning, ep.hook].filter(Boolean).join('\n'), 1)
    ))
  if (!predicted.length) return false
  let changed = false
  const byEp = new Map(outlineData.value.episodes.map(ep => [Number(ep.ep), ep]))
  predicted.forEach(newEp => {
    const current = byEp.get(Number(newEp.ep))
    if (!current) {
      outlineData.value.episodes.push(newEp)
      changed = true
      return
    }
    if (!String(current.title || '').trim() || /^第\d+集$/.test(String(current.title || ''))) {
      current.title = newEp.title
      changed = true
    }
    if (_episodeNeedsPredictionFill(current) && newEp.summary) {
      current.summary = newEp.summary
      changed = true
    }
    if (_outlineEpisodeFieldIsLowQuality(current.conflict) && newEp.conflict) {
      current.conflict = newEp.conflict
      changed = true
    }
    if (_outlineEpisodeFieldIsLowQuality(current.turning) && newEp.turning) {
      current.turning = newEp.turning
      changed = true
    }
    ;(['main_scene', 'relationship_change', 'info_revealed', 'satisfaction_type', 'stage'] as const).forEach(field => {
      if (!String((current as any)[field] || '').trim() && (newEp as any)[field]) {
        ;(current as any)[field] = (newEp as any)[field]
        changed = true
      }
    })
    if (current.hook) {
      current.hook = ''
      changed = true
    }
  })
  outlineData.value.episodes.sort((a, b) => Number(a.ep) - Number(b.ep))
  if (changed) _markOutlineAiGenerated('episodes')
  return changed
}

function _applyOutlinePredictionResult(
  data: any,
  options: { exposePrediction?: boolean; mergeEpisodes?: boolean; mergeCharacters?: boolean; ensureRelationships?: boolean } = {},
) {
  const exposePrediction = options.exposePrediction !== false
  const mergeEpisodes = options.mergeEpisodes !== false
  const mergeCharacters = options.mergeCharacters !== false
  const ensureRelationships = options.ensureRelationships === true
  const prediction = (data?.prediction && typeof data.prediction === 'object') ? data.prediction : data
  outlinePrediction.value = exposePrediction ? (prediction || null) : null
  if (_setOutlineFallbackCandidateBoundary(data, 'outline_prediction') === null && data?.fallback === false) {
    _clearOutlineFallbackCandidateBoundary()
  }
  let changed = false
  const details = prediction?.details || {}
  changed = _fillMissingOutlineField('logline', prediction?.logline) || changed
  changed = _fillMissingOutlineField('worldview', prediction?.worldview || details.worldview) || changed
  changed = _fillMissingOutlineField('goldenFinger', prediction?.goldenFinger || details.goldenFinger || details.specialSettings) || changed
  changed = _fillMissingOutlineField('conflict', prediction?.conflict || details.coreConflict || details.sellingPoints) || changed
  if (mergeCharacters && Array.isArray(prediction?.characters)) {
    changed = _mergePredictedOutlineCharacters(prediction.characters) || changed
  }
  if (mergeEpisodes && Array.isArray(prediction?.episodes)) {
    changed = _mergePredictedOutlineEpisodes(prediction.episodes) || changed
  }
  if (ensureRelationships) {
    changed = _ensureOutlineCharacterRelationships() || changed
  }
  const generated = Array.isArray(data?.generated_fields) ? data.generated_fields : []
  generated.forEach((field: any) => {
    if (typeof field === 'string' && ['logline', 'worldview', 'goldenFinger', 'conflict', 'characters', 'relationships', 'episodes', 'mainline'].includes(field)) {
      if (!mergeEpisodes && field === 'episodes') return
      if (!exposePrediction && field === 'mainline') return
      _markOutlineAiGenerated(field)
    }
  })
  return changed
}

async function _runOutlinePredictionFill(context: string, options?: { fromAnalyze?: boolean; metadataOnly?: boolean }) {
  if (!context.trim()) {
    if (!options?.fromAnalyze) toast.error('请先填写或粘贴大纲内容')
    return false
  }
  isPredictingOutline.value = true
  outlineAnalyzeStatus.value = options?.metadataOnly
    ? '大纲结构已提取，正在整理世界观、金手指、核心冲突和角色关系候选...'
    : options?.fromAnalyze
      ? '大纲结构已提取，正在整理缺失项候选...'
      : '正在进行剧本预测，并准备生成缺失项候选建议...'
  try {
    const target = _effectiveUserConfirmedTotalEpisodes()
    if (!options?.metadataOnly && !target) {
      toast.warning('请先确认总集数；用户确认多少集，系统就按多少集生成候选集纲。')
      outlineAnalyzeStatus.value = '总集数尚未确认，不能用默认集数继续预测'
      return false
    }
    const predictionTarget = options?.metadataOnly
      ? Math.max(1, Math.min(3, outlineData.value.episodes.length || 1))
      : target
    const { data } = await projectsV2Api.predictOutline({
      outline: context,
      target_episodes: predictionTarget,
      temperature: 0.25,
      seed_analysis: _outlinePredictionSeedAnalysis(),
    })
    const changed = _applyOutlinePredictionResult(data, {
      exposePrediction: !options?.metadataOnly,
      mergeEpisodes: !options?.metadataOnly,
    })
    _syncProjectRulesTotalEpisodesFromConfirmedCount()
    await _persistOutlineAnalysis(rawOutlineText.value.trim() || context)
    const fallbackBoundary = _outlineFallbackCandidateBoundaryFromPayload(data, 'outline_prediction')
    outlineAnalyzeStatus.value = options?.metadataOnly
      ? `大纲解析完成：${outlineCharacters.value.length} 个角色 / ${outlineData.value.episodes.length} 集纲，缺失字段已标出，候选字段等待确认`
      : `剧本预测完成：${outlinePrediction.value?.character_count || outlineCharacters.value.length} 个角色 / ${outlineData.value.episodes.length} 集候选集纲`
    if (fallbackBoundary) {
      toast.warning(options?.metadataOnly ? 'AI暂不可用，系统只整理出本地候选占位，请确认或补写' : 'AI预测暂不可用，系统只整理出本地候选占位，请确认或补写')
    } else {
      toast.success(changed ? '解析完成，候选建议已整理' : '解析完成，当前字段已较完整')
    }
    return true
  } catch (e: any) {
    notifyApiError(toast.error, e, options?.metadataOnly ? '大纲候选整理失败' : '剧本预测失败')
    outlineAnalyzeStatus.value = options?.metadataOnly ? '候选整理失败，请检查 AI 配置或稍后重试' : '剧本预测失败，请检查 AI 配置或稍后重试'
    return false
  } finally {
    isPredictingOutline.value = false
  }
}

async function predictOutlineAndFill() {
  if (outlineAiFeaturesPaused) {
    toast.warning('全局预测功能暂时关闭，请先手动补全大纲。')
    return
  }
  if (isPredictingOutline.value) return
  await _runOutlinePredictionFill(_buildOutlineGenerationText())
}

async function generateEpisodes(count: number) {
  if (outlineAiFeaturesPaused) {
    toast.warning('AI生成集纲功能暂时关闭，请先手动补全集纲。')
    return
  }
  const confirmedCount = _effectiveUserConfirmedTotalEpisodes()
  const normalizedCount = confirmedCount || _normalizeTotalEpisodeCount(count)
  if (!normalizedCount) {
    toast.warning('请先确认总集数；用户确认多少集，系统就生成多少集候选集纲。')
    outlineAnalyzeStatus.value = '总集数尚未确认，不能用默认集数生成集纲'
    return
  }
  projectRules.value.total_episodes = normalizedCount
  const persisted = await persistProjectRules({ silent: true })
  if (!persisted) {
    toast.error('请先把项目规则同步成功，再生成集纲')
    return
  }
  const gateIssues = _standardOutlinePacketGateIssues('episode_outlines')
  if (gateIssues.length) {
    const message = gateIssues.find(item => STANDARD_OUTLINE_GATE_USER_HINTS.includes(item)) || gateIssues[0] || '请先补全大纲前置资料'
    outlineAnalyzeStatus.value = `生成集纲前置资料未完成：${gateIssues.join('；')}`
    toast.warning(message)
    return
  }
  const context = _buildOutlineGenerationText()
  if (!context.trim()) { toast.error('请先填写梗概和冲突'); return }
  isGeneratingEpisodes.value = true
  outlineAnalyzeStatus.value = '正在排队生成逐集集纲（后台任务，请稍候）...'
  try {
    // 启动后台任务，立即拿到 job_id（不再卡 90s 同步超时）
    const { data: startData } = await projectsV2Api.startEpisodeOutlinesJob({
      outline: context,
      target_episodes: normalizedCount,
      temperature: 0.25,
      project_id: projectId.value,
      generation_provider: projectRules.value.generation_provider,
      generation_model: projectRules.value.generation_model,
      seed_analysis: _outlinePredictionSeedAnalysis(),
    })
    const jobId = (startData as any)?.job_id
    if (!jobId) throw new Error('任务启动失败，请重试')

    // 轮询任务进度（每 2.5s 一次，上限约 20 分钟）
    const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms))
    const maxPolls = 480
    let final: any = null
    let pollErrors = 0
    for (let i = 0; i < maxPolls; i++) {
      await sleep(2500)
      let status: any
      try {
        const { data } = await projectsV2Api.getEpisodeOutlinesJobStatus(jobId)
        status = data
      } catch (pollErr: any) {
        pollErrors += 1
        if (pollErrors > 5) throw pollErr
        continue
      }
      const done = status?.progress?.done ?? 0
      const total = status?.progress?.total ?? normalizedCount
      if (status?.status === 'done') { final = status; break }
      if (status?.status === 'error') throw new Error(status?.error || '生成失败')
      outlineAnalyzeStatus.value = `逐集集纲生成中… ${done}/${total} 集（后台任务，可继续等待）`
    }
    if (!final) throw new Error('生成超时，请稍后重试')

    _applyOutlinePredictionResult(final, {
      exposePrediction: true,
      mergeEpisodes: false,
      mergeCharacters: false,
    })
    const parsed = Array.isArray(final.episodes) ? final.episodes : []
    if (parsed.length) {
      outlineData.value.episodes = parsed.map(_normalizeEditorEpisode)
      _markOutlineAiGenerated('episodes')
      await _persistOutlineDraft('ai_generate_episodes_draft', { silent: true })
      if (_outlineFallbackCandidateBoundaryFromPayload(final, 'local_episode_frameworks')) {
        outlineAnalyzeStatus.value = `已整理 ${outlineData.value.episodes.length} 集候选集纲，等待确认`
        toast.warning(`AI生成未完整返回，系统只整理出 ${outlineData.value.episodes.length} 集候选占位，请确认或补写后再继续`)
      } else {
        outlineAnalyzeStatus.value = `已生成 ${outlineData.value.episodes.length} 集集纲，等待确认后进入主链`
        toast.success(`已生成 ${outlineData.value.episodes.length} 集集纲，等待确认`)
      }
    } else {
      outlineAnalyzeStatus.value = '没有返回集纲，请重试'
      toast.error('集纲为空，请重试')
    }
  } catch (e: any) {
    notifyApiError(toast.error, e, '生成失败')
    const detail = String(e?.message || '').trim().slice(0, 220)
    outlineAnalyzeStatus.value = detail ? `生成集纲失败：${detail}` : '生成集纲失败，请检查 AI 配置或稍后重试'
  } finally { isGeneratingEpisodes.value = false }
}

function addOutlineCharacter() {
  outlineCharacters.value.push({ id: String(Date.now()), name: '', role: 'supporting', info: '' })
}
function removeOutlineCharacter(id: string) {
  outlineCharacters.value = outlineCharacters.value.filter(c => c.id !== id)
}

// 将大纲角色同步到角色设计 Tab
// info 作为 background 字段传入，设计 Tab 里可再细化
function _extractOutlineCharacterField(info: string, label: string) {
  const pattern = new RegExp(`${label}[：:]\\s*([^\\n；;]+)`)
  return String(info || '').match(pattern)?.[1]?.trim() || ''
}

function _extractOutlineCharacterAnyField(info: string, labels: string[]) {
  for (const label of labels) {
    const value = _extractOutlineCharacterField(info, label)
    if (value) return value
  }
  return ''
}

function _extractOutlineCharacterAge(info: string, fallback: number) {
  const text = _extractOutlineCharacterField(info, '年龄') || String(info || '').match(/(\d{1,3})\s*岁/)?.[1] || ''
  const value = Number(text.replace(/[^\d]/g, ''))
  return Number.isFinite(value) && value > 0 ? value : fallback
}

function _cleanRelationshipTargetName(value: any) {
  return String(value || '')
    .replace(/^与/, '')
    .replace(/的关系$/, '')
    .replace(/[()（）].*$/g, '')
    .trim()
}

function _coerceRelationshipEpisode(value: any) {
  if (value == null || value === '') return null
  const match = String(value).match(/\d+/)
  const episodeNo = Number(match?.[0] || value)
  return Number.isFinite(episodeNo) && episodeNo > 0 ? episodeNo : null
}

function _normalizeOutlineRelationshipRecord(raw: any) {
  if (!raw) return null
  if (typeof raw === 'string') {
    const text = raw.trim()
    const bracketMatch = text.match(/与?([^（(：:，,；;。\n]{1,16})[（(]([^）)]{1,80})[）)]/)
    const colonMatch = text.match(/与?([^：:，,；;。\n]{1,16})[：:，,]\s*(.{1,80})/)
    const targetName = _cleanRelationshipTargetName(bracketMatch?.[1] || colonMatch?.[1] || '')
    const body = String(bracketMatch?.[2] || colonMatch?.[2] || '').trim()
    if (!targetName || !body) return null
    const [type, ...rest] = body.split(/[，,、]/).map(item => item.trim()).filter(Boolean)
    return {
      targetName,
      type: type || '关系',
      earlyType: type || '关系',
      lateType: type || '关系',
      transitionEpisode: null,
      transitionTrigger: '',
      finalBoundary: '',
      candidateStatus: 'needs_user_confirmation',
      description: rest.join('，') || body,
      strength: 70,
      episodes: [] as number[],
    }
  }
  if (typeof raw !== 'object') return null
  const item = raw as Record<string, any>
  const targetName = _cleanRelationshipTargetName(
    item.targetName || item.target_name || item.target || item.to || item.name || item.character || item.with,
  )
  const type = _predictionText(item.type || item.relationship || item.relation || item.state || item.label) || '关系'
  const earlyType = _predictionText(
    item.earlyType || item.early_type || item.early || item.beforeType || item.before_type || item.initialType || item.initial_type || type,
  ) || type
  const lateType = _predictionText(
    item.lateType || item.late_type || item.late || item.afterType || item.after_type || item.finalType || item.final_type || item.toType || item.to_type,
  ) || earlyType
  const transitionEpisode = _coerceRelationshipEpisode(
    item.transitionEpisode || item.transition_episode || item.turningEpisode || item.turning_episode || item.changeEpisode || item.change_episode,
  )
  const transitionTrigger = _predictionText(
    item.transitionTrigger || item.transition_trigger || item.turningPoint || item.turning_point || item.trigger || item.condition,
  )
  const finalBoundary = _predictionText(item.finalBoundary || item.final_boundary || item.boundary || item.mustNot || item.must_not)
  const candidateStatus = _predictionText(item.candidateStatus || item.candidate_status || item.status) || 'needs_user_confirmation'
  const description = _predictionText(item.description || item.desc || item.detail || item.summary || item.note)
  const strength = Math.max(1, Math.min(100, Math.round(Number(item.strength || item.weight || 70) || 70)))
  if (!targetName) return null
  return {
    targetName,
    type: earlyType || type,
    earlyType: earlyType || type,
    lateType,
    transitionEpisode,
    transitionTrigger,
    finalBoundary,
    candidateStatus,
    description,
    strength,
    episodes: Array.isArray(item.episodes) ? item.episodes.map((ep: any) => Number(ep)).filter(Boolean) : [],
  }
}

function _extractRelationshipTextItems(info: string) {
  const text = String(info || '')
  const relationLines = text
    .split('\n')
    .map(line => line.trim())
    .filter(line => /^(人物关系|角色关系|关系)\s*[：:]/.test(line) || /^与[^（(：:，,；;。\n]{1,16}[（(]/.test(line))
    .map(line => line.replace(/^(人物关系|角色关系|关系)\s*[：:]\s*/, ''))
  const bracketItems = Array.from(text.matchAll(/与[^（(：:，,；;。\n]{1,16}[（(][^）)]{1,80}[）)]/g)).map(match => match[0])
  const splitItems = relationLines.flatMap(line => line.split(/[；;\n]/).map(item => item.trim()).filter(Boolean))
  return [...bracketItems, ...splitItems]
}

function _extractOutlineCharacterRelationships(source: any) {
  const structured = Array.isArray(source?.relationships)
    ? source.relationships.map(_normalizeOutlineRelationshipRecord).filter(Boolean)
    : []
  const fromInfo = _extractRelationshipTextItems(source?.info || '')
    .map(_normalizeOutlineRelationshipRecord)
    .filter(Boolean)
  const seen = new Set<string>()
  return [...structured, ...fromInfo].filter((rel: any) => {
    const key = `${rel.targetName}__${rel.type}__${rel.description || ''}`
    if (seen.has(key)) return false
    seen.add(key)
    return true
  }) as Array<{
    targetName: string
    type: string
    earlyType?: string
    lateType?: string
    transitionEpisode?: number | null
    transitionTrigger?: string
    finalBoundary?: string
    candidateStatus?: string
    description: string
    strength: number
    episodes: number[]
  }>
}

function _attachAnalysisRelationshipsToOutlineCharacters(rows: any[]) {
  if (!Array.isArray(rows) || !rows.length || !outlineCharacters.value.length) return
  const byName = new Map(outlineCharacters.value.map(char => [String(char.name || '').trim(), char]))
  rows.forEach((row) => {
    if (!row || typeof row !== 'object') return
    const sourceName = _cleanRelationshipTargetName(row.sourceName || row.source_name || row.source || row.from || row.character || '')
    const targetName = _cleanRelationshipTargetName(row.targetName || row.target_name || row.target || row.to || row.object || '')
    if (!sourceName || !targetName || sourceName === targetName) return
    const source = byName.get(sourceName)
      || outlineCharacters.value.find(char => char.name.includes(sourceName) || sourceName.includes(char.name))
    const target = byName.get(targetName)
      || outlineCharacters.value.find(char => char.name.includes(targetName) || targetName.includes(char.name))
    if (!source || !target || source.name === target.name) return
    if (!Array.isArray((source as any).relationships)) (source as any).relationships = []
    const type = String(row.earlyType || row.early_type || row.type || row.relationship || row.relation || row.state || '关系').trim()
    const lateType = String(row.lateType || row.late_type || row.afterType || row.after_type || type).trim()
    const description = String(row.description || row.desc || row.detail || row.summary || '').trim()
    const transitionEpisode = _coerceRelationshipEpisode(row.transitionEpisode || row.transition_episode || row.turningEpisode || row.turning_episode)
    const transitionTrigger = String(row.transitionTrigger || row.transition_trigger || row.trigger || row.condition || '').trim()
    const finalBoundary = String(row.finalBoundary || row.final_boundary || row.boundary || row.must_not || '').trim()
    const candidateStatus = String(row.candidateStatus || row.candidate_status || row.status || 'needs_user_confirmation').trim()
    const exists = (source as any).relationships.some((rel: any) => {
      const relTarget = typeof rel === 'string' ? rel : String(rel.targetName || rel.target_name || rel.target || rel.to || '')
      const relType = typeof rel === 'string' ? rel : String(rel.earlyType || rel.early_type || rel.type || rel.relationship || rel.relation || '')
      return relTarget.includes(target.name) && (!relType || relType === type)
    })
    if (!exists) {
      ;(source as any).relationships.push({
        targetName: target.name,
        type,
        earlyType: type,
        lateType,
        transitionEpisode,
        transitionTrigger,
        finalBoundary,
        candidateStatus,
        description,
        strength: Math.max(1, Math.min(100, Math.round(Number(row.strength || row.weight || 70) || 70))),
        episodes: Array.isArray(row.episodes) ? row.episodes.map((ep: any) => Number(ep)).filter(Boolean) : [],
      })
    }
  })
}

function _ensureOutlineCharacterRelationships() {
  if (outlineCharacters.value.length < 2) return false
  const protagonist = outlineCharacters.value.find(char => char.role === 'protagonist') || outlineCharacters.value[0]
  if (!protagonist) return false
  if (!Array.isArray((protagonist as any).relationships)) (protagonist as any).relationships = []
  let changed = false

  outlineCharacters.value.forEach((target) => {
    if (target.name === protagonist.name) return
    const exists = (protagonist as any).relationships.some((rel: any) => {
      const targetName = String(rel?.targetName || rel?.target_name || rel?.target || rel?.to || '')
      return targetName && (targetName.includes(target.name) || target.name.includes(targetName))
    })
    if (exists) return
    const type = target.role === 'antagonist'
      ? '对抗'
      : target.role === 'minor'
        ? '剧情关联'
        : '协作/牵引'
    ;(protagonist as any).relationships.push({
      targetName: target.name,
      type,
      earlyType: type,
      lateType: type,
      transitionEpisode: null,
      transitionTrigger: '',
      finalBoundary: '未确认前不能写成稳定关系结论',
      candidateStatus: 'needs_user_confirmation',
      description: `${protagonist.name}与${target.name}围绕主线目标形成${type}关系，后续可在角色设计中继续细化。`,
      strength: target.role === 'antagonist' ? 82 : 68,
      episodes: [],
    })
    changed = true
  })
  if (changed) _markOutlineAiGenerated('relationships')
  return changed
}

function _resolveImportedRelationships(source: any, allCharacters: any[], existingRelationships: any[] = []) {
  const byName = new Map(allCharacters.map(char => [String(char.name || '').trim(), char]))
  const byId = new Map(allCharacters.map(char => [String(char.id || ''), char]))
  const merged = Array.isArray(existingRelationships)
    ? existingRelationships.map((rel) => {
        const target = byId.get(String(rel?.targetId || ''))
      || byName.get(String(rel?.targetName || '').trim())
        const item = { ...rel, episodes: Array.isArray(rel.episodes) ? rel.episodes : [] }
        item.earlyType = item.earlyType || item.early_type || item.type || '关系'
        item.lateType = item.lateType || item.late_type || item.earlyType
        item.transitionEpisode = _coerceRelationshipEpisode(item.transitionEpisode || item.transition_episode)
        item.transitionTrigger = item.transitionTrigger || item.transition_trigger || ''
        item.finalBoundary = item.finalBoundary || item.final_boundary || ''
        item.candidateStatus = item.candidateStatus || item.candidate_status || 'confirmed'
        const sourceRole = String(source?.role || '')
        const targetRole = String(target?.role || '')
        const relationText = `${item.type || ''}\n${item.description || ''}\n${sourceRole}\n${targetRole}`
        if (sourceRole !== 'antagonist' && targetRole !== 'antagonist' && _relationshipLooksSupportive(relationText)) {
          item.type = '协作'
          item.earlyType = item.earlyType || item.type
          item.strength = Math.max(Number(item.strength || 0) || 0, 70)
          return item
        }
        if (
          (sourceRole === 'antagonist' || targetRole === 'antagonist')
          && _relationshipLooksAntagonistic(relationText)
        ) {
          item.type = '对抗'
          item.earlyType = item.earlyType || item.type
          item.strength = Math.max(Number(item.strength || 0) || 0, 82)
        }
        return item
      })
    : []
  for (const rel of _extractOutlineCharacterRelationships(source)) {
    const target = byName.get(rel.targetName)
      || allCharacters.find(char => {
        const name = String(char.name || '').trim()
        return name && (name.includes(rel.targetName) || rel.targetName.includes(name))
      })
    if (!target || String(target.id) === String(source?.id || '')) continue
    if (
      source?.role !== 'antagonist'
      && target.role !== 'antagonist'
      && _relationshipLooksSupportive(`${rel.type}\n${rel.description}`)
    ) {
      rel.type = '协作'
      rel.strength = Math.max(Number(rel.strength || 0) || 0, 70)
    } else if (
      (source?.role === 'antagonist' || target.role === 'antagonist')
      && _relationshipLooksAntagonistic(`${rel.type}\n${rel.description}\n${source?.role || ''}\n${target.role}`)
    ) {
      rel.type = '对抗'
      rel.strength = Math.max(Number(rel.strength || 0) || 0, 82)
    }
    const existing = merged.find(item => String(item.targetId) === String(target.id) && String(item.type || '') === rel.type)
    if (existing) {
      if (!existing.description && rel.description) existing.description = rel.description
      if (!existing.strength && rel.strength) existing.strength = rel.strength
      continue
    }
    merged.push({
      targetId: String(target.id),
      targetName: target.name,
      type: rel.type,
      earlyType: rel.earlyType || rel.type,
      lateType: rel.lateType || rel.earlyType || rel.type,
      transitionEpisode: rel.transitionEpisode || null,
      transitionTrigger: rel.transitionTrigger || '',
      finalBoundary: rel.finalBoundary || '',
      candidateStatus: rel.candidateStatus || 'needs_user_confirmation',
      strength: rel.strength || 70,
      description: rel.description || '',
      episodes: rel.episodes || [],
    })
  }
  return merged
}

function _currentOutlineRelationshipScanText() {
  return [
    rawOutlineText.value,
    outlineData.value.logline,
    outlineData.value.worldview,
    outlineData.value.conflict,
    outlineCharacters.value.map((char: any) => `${char.name}：${char.info || ''}`).join('\n'),
    outlineData.value.episodes
      .map((ep: any) => `第${ep.ep || ''}集 ${ep.title || ''}\n${ep.summary || ''}\n${ep.hook || ''}`)
      .join('\n'),
  ].filter(Boolean).join('\n')
}

function _ensureOutlineRelationshipsBeforeSync(cleanOutlineCharacters: any[]) {
  if (!Array.isArray(cleanOutlineCharacters) || cleanOutlineCharacters.length < 2) return cleanOutlineCharacters
  const hasRelationships = cleanOutlineCharacters.some((char: any) => Array.isArray(char.relationships) && char.relationships.length)
  if (hasRelationships) return cleanOutlineCharacters
  const inferredRows = _extractLocalOutlineRelationships(_currentOutlineRelationshipScanText(), cleanOutlineCharacters)
  if (inferredRows.length) {
    _attachAnalysisRelationshipsToOutlineCharacters(inferredRows)
  } else {
    _ensureOutlineCharacterRelationships()
  }
  return _sanitizeOutlineCharacters(outlineCharacters.value as any[])
}

function syncOutlineCharsToDesign(options: { selectFirst?: boolean } = {}) {
  let cleanOutlineCharacters = _sanitizeOutlineCharacters(outlineCharacters.value as any[])
  if (JSON.stringify(cleanOutlineCharacters) !== JSON.stringify(outlineCharacters.value)) {
    outlineCharacters.value = cleanOutlineCharacters as any
  }
  cleanOutlineCharacters = _ensureOutlineRelationshipsBeforeSync(cleanOutlineCharacters)
  if (outlineCharacters.value.length === 0) return 0
  const existingChars = [...(characters.value as any[])]

  const mapped = cleanOutlineCharacters
    .filter(c => c.name.trim())
    .map((c, i) => {
      const existing = existingChars.find(e => e.name?.trim() === c.name.trim())
      const info = _sanitizeLocalCharacterInfo(c.info || existing?.background || '', c.name, 1200)
      const identity = _extractOutlineCharacterField(info, '身份')
      const occupation = _extractOutlineCharacterField(info, '职业') || identity
      return {
        id: existing?.id || String(Date.now() + i),
        name: c.name,
        role: c.role,
        age: _extractOutlineCharacterAge(info, existing?.age ?? 25),
        // info 作为 background（设计 tab 可再拆分细化）
        background: info,
        // 保留设计 tab 已有的细化字段
        occupation: existing?.occupation || occupation || '',
        appearance: existing?.appearance || '',
        personality: existing?.personality || _extractOutlineCharacterField(info, '性格') || '',
        voice_style: existing?.voice_style || _extractOutlineCharacterField(info, '声线') || '',
        voiceprint: existing?.voiceprint || _extractOutlineCharacterAnyField(info, ['声纹', '说话方式', '声线', '音色', '语言风格']) || '',
        inner_need: existing?.inner_need || _extractOutlineCharacterAnyField(info, ['内在需求', '深层需求', '核心需求', '动机', '目标']) || '',
        resource: existing?.resource || _extractOutlineCharacterAnyField(info, ['资源/筹码', '资源', '筹码', '底牌', '证据']) || '',
        first_appearance_function: existing?.first_appearance_function || _extractOutlineCharacterAnyField(info, ['首次出场功能', '出场功能', '剧情功能', '功能']) || '',
        relationship_tension: existing?.relationship_tension || _extractOutlineCharacterAnyField(info, ['关系张力', '关系压力', '关系', '人物关系', '角色关系']) || '',
        motivation: existing?.motivation || _extractOutlineCharacterField(info, '动机') || _extractOutlineCharacterField(info, '目标') || '',
        arc: existing?.arc || _extractOutlineCharacterField(info, '弧线') || '',
        traits: existing?.traits || _extractOutlineCharacterField(info, '功能') || '',
        notes: existing?.notes || '',
        relationships: [] as any[],
        importedRelationships: (c as any).relationships || [],
        existingRelationships: existing?.relationships || [],
      }
    })

  const extras = existingChars.filter(
    e => !mapped.some(m => m.id === e.id || m.name.trim() === e.name?.trim())
  )

  if (mapped.length > 0) {
    const allCharacters = [...mapped, ...extras]
    mapped.forEach((character) => {
      const source = cleanOutlineCharacters.find(item => item.name.trim() === character.name.trim())
      character.relationships = _resolveImportedRelationships(
        { ...source, id: character.id, info: character.background, relationships: character.importedRelationships },
        allCharacters,
        character.existingRelationships,
      )
      delete character.importedRelationships
      delete character.existingRelationships
    })
    characters.value = _sanitizeWorkspaceCharacterRows([...mapped, ...extras]) as any
    if (
      options.selectFirst
      && !characters.value.some(char => String(char.id) === String(selectedCharacterId.value || ''))
    ) {
      selectedCharacterId.value = mapped[0]?.id || null
    }
    saveWorkspaceStorage('characters', projectId.value, JSON.stringify(characters.value))
  }
  return mapped.length
}

function hasPreparedOutlineFromChat() {
  return Boolean(
    String(outlineData.value.logline || '').trim()
    && outlineData.value.episodes.length > 0
    && outlineCharacters.value.length > 0
    && _effectiveUserConfirmedTotalEpisodes() > 0,
  )
}

function ensureChatPreparationGate(options: { silent?: boolean } = {}) {
  if (activeTab.value === 'chat' || activeTab.value === 'outline' || hasPreparedOutlineFromChat()) return false
  activeTab.value = 'chat'
  router.replace({ query: { ...route.query, tab: 'chat' } })
  if (!options.silent) {
    toast.warning('请先在聊天脑暴完成选题，或在大纲页上传/解析已有大纲。')
  }
  return true
}

function _outlineStateHasMainChainFlag(state?: Record<string, any>) {
  return Object.prototype.hasOwnProperty.call(state || {}, 'main_chain_committed')
}

function _stableOutlineSignatureValue(value: any): any {
  if (Array.isArray(value)) return value.map(item => _stableOutlineSignatureValue(item))
  if (value && typeof value === 'object') {
    return Object.fromEntries(
      Object.keys(value)
        .sort()
        .map(key => [key, _stableOutlineSignatureValue(value[key])]),
    )
  }
  return value
}

function _outlineMainChainSignatureFromParts(payload: {
  outline_data?: any
  outline_characters?: any
  raw_outline_text?: any
}) {
  return simpleHash(JSON.stringify(_stableOutlineSignatureValue({
    outline_data: payload.outline_data || {},
    outline_characters: Array.isArray(payload.outline_characters) ? payload.outline_characters : [],
    raw_outline_text: String(payload.raw_outline_text || ''),
  })))
}

function _currentOutlineMainChainSignature() {
  return _outlineMainChainSignatureFromParts({
    outline_data: JSON.parse(JSON.stringify(outlineData.value)),
    outline_characters: _sanitizeOutlineCharacters(outlineCharacters.value as any[]),
    raw_outline_text: rawOutlineText.value || '',
  })
}

function _savedOutlineMainChainSignature(state?: Record<string, any>) {
  return _outlineMainChainSignatureFromParts({
    outline_data: state?.outline_data,
    outline_characters: state?.outline_characters,
    raw_outline_text: state?.raw_outline_text,
  })
}

function _outlineCurrentDraftDiffersFromMainChain() {
  const state = (workflowContext.value.outline_state || {}) as Record<string, any>
  if (!state.outline_data && !state.raw_outline_text && !Array.isArray(state.outline_characters)) {
    return hasPreparedOutlineFromChat()
  }
  return _currentOutlineMainChainSignature() !== _savedOutlineMainChainSignature(state)
}

function _isOutlineCommittedToMainChain() {
  const state = (workflowContext.value.outline_state || {}) as Record<string, any>
  if (_outlineCurrentDraftDiffersFromMainChain()) return false
  if (_outlineStateHasMainChainFlag(state)) {
    return state.main_chain_committed === true && state.main_chain_dirty !== true
  }
  return _hasSeriesSimulationContracts(workflowContext.value.series_simulation_packet)
}

function _outlineNeedsMainChainCommit() {
  const state = (workflowContext.value.outline_state || {}) as Record<string, any>
  if (_outlineCurrentDraftDiffersFromMainChain()) return true
  if (_outlineStateHasMainChainFlag(state)) {
    return state.main_chain_committed !== true || state.main_chain_dirty === true
  }
  return !_hasSeriesSimulationContracts(workflowContext.value.series_simulation_packet)
}

const outlineMainChainStatusText = computed(() => {
  const state = (workflowContext.value.outline_state || {}) as Record<string, any>
  if (state.main_chain_committed === true && state.main_chain_dirty !== true) {
    return '已锁定为主生成链路，后续剧本会读取这版大纲、集纲和人物小传。'
  }
  if (outlineFallbackCandidateBoundary.value || state.candidate_source === 'local_fallback') {
    return '本地候选草稿，需确认后才会进入主生成链路。'
  }
  if (state.main_chain_source === 'chat_brainstorm_candidate' || state.updated_reason === 'chat_brainstorm_outline_draft') {
    return '聊天脑暴候选草稿，需点击“大纲完成 → 角色设计”确认后，才会进入主生成链路。'
  }
  return '大纲草稿尚未锁定，进入剧本写作前需要先确认到主生成链路。'
})

const outlineMainChainCommitIssues = computed(() => {
  const issues: string[] = []
  const confirmedCount = _confirmableUserTotalEpisodesForOutlineCommit()
  const episodeCount = _outlineEpisodeCount()
  const declaredTotal = _declaredTotalEpisodesForOutlineCommit()

  if (!confirmedCount) {
    if (declaredTotal && episodeCount < declaredTotal) {
      issues.push(`请先补齐分集集纲：当前 ${episodeCount}/${declaredTotal} 集`)
    } else {
      issues.push('请先确认总集数')
    }
  } else if (outlineData.value.episodes.length < confirmedCount) {
    issues.push(`请先补齐分集集纲：当前 ${episodeCount}/${confirmedCount} 集`)
  }

  if (!_outlineTextValue(outlineData.value.logline).trim()) {
    issues.push('请先补齐一句话梗概')
  }
  if (!_outlineTextValue(outlineData.value.conflict).trim()) {
    issues.push('请先补齐核心冲突')
  }
  if (!outlineCharacters.value.length) {
    issues.push('请先确认角色库')
  }

  return issues
})

const outlineMainChainCommitBlocked = computed(() => outlineMainChainCommitIssues.value.length > 0)
const outlineMainChainCommitBlockReason = computed(() => outlineMainChainCommitIssues.value[0] || '')

function _ensureOutlineMainChainCommitGatePassed(options?: { silent?: boolean }) {
  if (!outlineMainChainCommitBlocked.value) return true
  const primaryIssue = outlineMainChainCommitBlockReason.value || '大纲前置资料未完成'
  const remainingIssueCount = Math.max(0, outlineMainChainCommitIssues.value.length - 1)
  const detail = remainingIssueCount > 0 ? `${primaryIssue}；另有 ${remainingIssueCount} 项待补` : primaryIssue
  if (!options?.silent) toast.warning(`暂不能进入角色设计：${detail}`)
  return false
}

function _hasSavedScriptContentForEpisode(episodeNumber: number) {
  const target = Math.max(1, Math.round(Number(episodeNumber || 1) || 1))
  return (episodes.value as any[]).some((episode) => {
    const ep = Math.round(Number(episode?.episode_number || episode?.ep || episode?.number || 0) || 0)
    return ep === target && Math.max(0, Math.round(Number(episode?.completed_scenes || 0) || 0)) > 0
  })
}

async function _ensureStoryboardHasSavedScriptContent() {
  const target = Math.max(1, Math.round(Number(selectedEpisode.value || storyboardEpisode.value || 1) || 1))
  await refreshEpisodesSilently()
  if (_hasSavedScriptContentForEpisode(target)) return true
  toast.warning('本集还没有正文，不能生成分镜提示词。请先完成剧本写作。')
  return false
}

async function goToNextWorkspaceTab() {
  const currentTab = activeTab.value
  const index = tabs.findIndex(tab => tab.id === currentTab)
  const nextTab = tabs[index + 1]?.id as WorkspaceTabId | undefined
  if (!nextTab) return
  await switchTab(nextTab)
  if (activeTab.value === nextTab) markTabComplete(currentTab)
}

async function switchTab(tab: WorkspaceTabId) {
  if (tab !== 'chat' && tab !== 'outline' && !hasPreparedOutlineFromChat()) {
    ensureChatPreparationGate()
    return
  }
  if (activeTab.value === 'script' && tab !== 'script' && hasUnsavedSceneChanges()) {
    const saved = await persistCurrentScriptContent({
      silent: true,
      changeNote: '切换页面前自动保存',
      editorType: 'human',
    })
    if (!saved) {
      toast.error('正文保存失败，请先保存成功后再切换页面')
      return
    }
  }
  if (tab !== 'chat' && tab !== 'outline' && _outlineNeedsMainChainCommit()) {
    const ok = await commitOutlineToMainChain()
    if (!ok) return
  }
  if (tab === 'storyboard' && !(await _ensureStoryboardHasSavedScriptContent())) {
    return
  }
  _switchWorkspaceTab(tab)
}

// 从导入文本框触发解析（保存原文再分析）
async function importAndAnalyze() {
  if (!outlineImportText.value.trim()) {
    toast.error('请先粘贴大纲内容')
    return
  }
  rawOutlineText.value = outlineImportText.value
  showImportArea.value = false
  await analyzeOutline()
}

async function handleOutlineFileUpload(file: File) {
  if (isAnalyzingOutline.value || isPredictingOutline.value) return
  outlineAnalyzeStatus.value = `正在读取文件：${file.name}`
  try {
    const { data } = await projectsV2Api.extractOutlineFile(file)
    const text = String(data.text || '').trim()
    if (!text) {
      toast.error('文件中没有可识别的大纲文本')
      outlineAnalyzeStatus.value = ''
      return
    }
    rawOutlineText.value = text
    saveWorkspaceStorage('rawOutline', projectId.value, text)
    outlineAnalyzeStatus.value = `已读取 ${data.filename || file.name}，可直接自动分割；也可以先手动校对文本`
    toast.success((data as any).truncated ? '文件已读取，因内容较长已自动截断到安全范围' : '文件已读取到大纲原文')
  } catch (e: any) {
    notifyApiError(toast.error, e, '文件读取失败')
    outlineAnalyzeStatus.value = ''
  }
}

async function analyzeOutline() {
  if (isAnalyzingOutline.value) return
  isAnalyzingOutline.value = true
  outlinePrediction.value = null
  outlineAnalyzeStatus.value = '正在自动分割大纲内容...'
  try {
    // 优先用完整原始大纲文本；若没有则拼接现有字段内容
    const outline = rawOutlineText.value.trim() || [
      outlineData.value.logline,
      outlineData.value.worldview,
      outlineData.value.goldenFinger,
      outlineData.value.conflict,
    ].filter(Boolean).join('\n')

    if (!outline.trim()) {
      outlineAnalyzeStatus.value = ''
      toast.error('请先填写一些大纲内容')
      return
    }

    const result = _buildLocalOutlineAnalysis(outline, projectRules.value.total_episodes)
    if (_hasUsefulOutlineAnalysis(result)) {
      _applyOutlineAnalysisResult(result)
    }
    await _persistOutlineAnalysis(outline)
    outlineAnalyzeStatus.value = `自动分割完成：${outlineCharacters.value.length} 个角色 / ${outlineData.value.episodes.length} 集纲；原文没有识别到的内容已留空，需要用户手动补全`
    toast.success('自动分割完成；缺失内容已留空，请手动补全')
  } catch (e: any) {
    outlineAnalyzeStatus.value = '自动分割失败，请检查文本格式后重试'
    toast.error(formatUserFacingErrorMessage(e, '自动分割失败'))
  } finally {
    isAnalyzingOutline.value = false
  }
}

function addEpisode() {
  outlineData.value.episodes.push({
    ep: outlineData.value.episodes.length + 1,
    title: `第${outlineData.value.episodes.length + 1}集`,
    hook: '',
    summary: ''
  })
}

async function saveOutline() {
  const outlinePersisted = await _persistOutlineDraft('outline_saved_draft', { silent: true })
  if (project.value && !outlinePersisted) {
    notifyApiError(toast.error, lastWorkflowContextSyncError.value, '大纲草稿保存失败')
    return false
  }
  const persisted = await persistProjectRules({ silent: true })
  if (project.value && !persisted) return false
  toast.success('大纲草稿已保存，点击“完成 → 角色设计”后才会进入主生成链路')
  return true
}

async function commitOutlineToMainChain(options?: { silent?: boolean; allowFallbackCandidatePromotion?: boolean }) {
  if (outlineFallbackCandidateBoundary.value && options?.allowFallbackCandidatePromotion !== true) {
    if (!options?.silent) toast.warning('本地候选草稿需先在大纲页确认后，再进入主生成链路')
    return false
  }
  const confirmedEpisodeCount = _confirmableUserTotalEpisodesForOutlineCommit()
  if (confirmedEpisodeCount) {
    _applyUserConfirmedTotalEpisodesForOutlineCommit(confirmedEpisodeCount)
  }
  await _persistOutlineDraft('outline_commit_precheck', { silent: true, sync: false })
  if (!_ensureOutlineMainChainCommitGatePassed({ silent: options?.silent })) return false
  const syncedCharacters = syncOutlineCharsToDesign({ selectFirst: true })
  if (!_syncProjectRulesTotalEpisodesFromConfirmedCount()) {
    if (!options?.silent) toast.warning('请先确认总集数；用户确认多少集，系统就按多少集进入主生成链路。')
    return false
  }
  const charactersPersisted = await persistWorkspaceCharacters({ silent: true })
  if (project.value && !charactersPersisted) {
    if (!options?.silent) toast.error('角色设计保存失败，请稍后重试')
    return false
  }
  const persisted = await persistProjectRules({ silent: true })
  if (project.value && !persisted) {
    if (!options?.silent) toast.error('项目规则保存失败，请稍后重试')
    return false
  }
  const seededScripts = await _seedExistingScriptsFromOutline()
  outlineExistingScriptSeedSignature.value = _outlineExistingScriptSeedSignature()
  await _refreshSeriesSimulationPacket('outline_committed', { silent: true })
  standardOutlinePacket.value = createStandardOutlinePacket({
    outlineData: outlineData.value as Record<string, unknown>,
    characters: outlineCharacters.value as Array<Record<string, unknown>>,
    rawOutlineText: rawOutlineText.value,
    confirmed: true,
    status: 'confirmed',
    current_stage: 'episode_outlines',
  })
  const snapshotPersisted = await _persistOutlineSnapshot('outline_committed', { silent: true, mainChainCommitted: true })
  if (project.value && !snapshotPersisted) {
    if (!options?.silent) notifyApiError(toast.error, lastWorkflowContextSyncError.value, '大纲主链同步失败')
    return false
  }
  _clearOutlineFallbackCandidateBoundary()
  const episodesReady = await createEpisodesBatch({ silent: true })
  if (!episodesReady) {
    if (!options?.silent) toast.error('大纲已同步，但分集创建失败，请稍后重试')
    return false
  }
  if (!options?.silent) {
    toast.success(seededScripts > 0
      ? `已确认进入主链路：同步 ${syncedCharacters} 个角色，并导入 ${seededScripts} 集原稿`
      : `已确认进入主链路：同步 ${syncedCharacters} 个角色`)
  }
  return true
}

async function saveOutlineAndContinue() {
  const ok = await commitOutlineToMainChain({ allowFallbackCandidatePromotion: true })
  if (ok) await goToNextWorkspaceTab()
}

// Load outline + outlineCharacters + characters from localStorage
onMounted(() => {
  const saved = loadWorkspaceStorage('outline', projectId.value)
  if (saved) { try { outlineData.value = JSON.parse(saved) } catch {} }

  // 恢复原始大纲文本（用于重新分析时发送完整文本给AI）
  const raw = loadWorkspaceStorage('rawOutline', projectId.value)
  if (raw) rawOutlineText.value = raw

  // 恢复结构化大纲角色
  const oc = loadWorkspaceStorage('outlineChars', projectId.value)
  if (oc) { try { const p = JSON.parse(oc); if (Array.isArray(p) && p.length > 0) outlineCharacters.value = _sanitizeOutlineCharacters(p) as any } catch {} }

// 恢复角色设计 tab 的角色
  const savedChars = loadWorkspaceStorage('characters', projectId.value)
  if (savedChars) {
    try {
      const parsed = JSON.parse(savedChars)
      if (Array.isArray(parsed) && parsed.length > 0) characters.value = _sanitizeWorkspaceCharacterRows(parsed) as any
    } catch {}
  }

  const savedStateCards = loadWorkspaceStorage('stateCards', projectId.value)
  if (savedStateCards) {
    try { storyStateCards.value = normalizeStoryStateCards(JSON.parse(savedStateCards)) } catch {}
  }
})

watch(() => projectRules.value.episode_seconds, (value) => {
  const normalized = Math.max(30, Math.min(600, Math.round(Number(value) || 90)))
  const derived = _deriveWordCountRangeBySeconds(normalized)
  if (projectRules.value.episode_seconds !== normalized) {
    projectRules.value.episode_seconds = normalized
    return
  }
  if (projectRules.value.word_count_per_episode !== derived.text) {
    projectRules.value.word_count_per_episode = derived.text
  }
})

watch(() => projectRules.value.total_episodes, (value) => {
  const normalized = _normalizeTotalEpisodeCount(value)
  if (projectRules.value.total_episodes !== normalized) {
    projectRules.value.total_episodes = normalized
  }
})

watch(() => projectRules.value.generation_provider, () => {
  _applyGenerationDefaults()
})


let _projectRuleSyncTimer: ReturnType<typeof setTimeout> | null = null
watch(
  [
    () => projectRules.value.total_episodes,
    () => projectRules.value.episode_seconds,
    () => projectRules.value.scene_header_style,
    () => projectRules.value.generation_provider,
    () => projectRules.value.generation_model,
    () => projectRules.value.advanced_generation_mode,
    () => outlineData.value.audience_axis,
    () => outlineData.value.genre_main,
    () => outlineData.value.format_type,
  ],
  () => {
    if (!project.value || isLoading.value) return
    if (_projectRuleSyncTimer) clearTimeout(_projectRuleSyncTimer)
    _projectRuleSyncTimer = setTimeout(() => {
      persistProjectRules({ silent: true })
    }, 1000)
  }
)

// ─── 角色设计 Tab ─────────────────────────────────────────────────────────────
// 角色 Tab 全部由 useCharacterTab composable 管理（state + 持久化 watch）。
const _isProjectReady = computed(() => !!project.value && !isLoading.value)
const {
  characters,
  selectedCharacterId,
  showCharacterGraph,
  roleColors,
  roleColorFor,
  addCharacter: _addCharacter,
  removeCharacter,
  updateCharacter,
  addRelationship,
} = useCharacterTab({ projectId, isReady: _isProjectReady })
function addCharacter(char: any) {
  _addCharacter(char, msg => toast.success(msg))
}

function ensureCharacterSelection() {
  if (activeTab.value !== 'characters') return
  const available = (characters.value as any[]).filter(char => String(char?.id || '').trim())
  if (available.length === 0) {
    selectedCharacterId.value = null
    return
  }
  const selectedExists = available.some(char => String(char.id) === String(selectedCharacterId.value || ''))
  if (!selectedExists) {
    selectedCharacterId.value = String(available[0].id)
  }
}

watch(
  () => [activeTab.value, (characters.value as any[]).map(char => String(char?.id || '')).join('|')],
  () => ensureCharacterSelection(),
  { immediate: true },
)






const storyStateCards = ref(emptyStoryStateCards())
const workflowContext = ref(normalizeWorkflowContext())
const canonPacket = ref<Record<string, any>>({})
const episodeMemoryCards = ref<Array<Record<string, any>>>([])
const {
  outlineGateIssues,
  outlineGateIssuesForEpisodeLimit,
  outlineGateFixHints,
  canGenerateScript: outlineGateAllowsScript,
  firstBlockingMessage: firstOutlineGateBlockingMessage,
  firstRepairHint: firstOutlineGateRepairHint,
} = useOutlineGate({ outlineData, characters, workflowContext })
const dismissedStateCardSuggestionKeys = ref<string[]>([])
// 状态卡 / 工作流上下文 的 800ms / 1000ms debounce 写库副作用，已抽到
// useStoryStateAutosave；调用在 _syncProjectWorkflowContext 定义之后挂上。
const _scriptValidationCache = new Map<string, ScriptRuleValidationState>()
const _scriptDeepAuditCache = new Map<string, ScriptDeepAuditState>()
const _scriptValidationInFlight = new Map<string, Promise<{ raw: any; normalized: ScriptRuleValidationState }>>()



function _workflowRagText(...keys: string[]) {
  const ragContext = workflowContext.value.rag_context && typeof workflowContext.value.rag_context === 'object'
    ? workflowContext.value.rag_context
    : {}
  for (const key of keys) {
    const text = String((ragContext as Record<string, any>)[key] || '').trim()
    if (text) return text
  }
  return ''
}

function _normalizeRagEvidenceItems(raw?: any) {
  if (!Array.isArray(raw)) return []
  return raw
    .filter((item: any) => item && typeof item === 'object')
    .map((item: any) => ({
      kind: String(item.kind || item.backend || '').trim(),
      backend: String(item.backend || '').trim(),
      source: String(item.source || '').trim(),
      inject_as: String(item.inject_as || '').trim(),
      query: String(item.query || '').trim(),
      count: Number(item.count || 0),
      doc_types: Array.isArray(item.doc_types) ? item.doc_types.map((v: any) => String(v || '')).filter(Boolean) : [],
      items: Array.isArray(item.items)
        ? item.items
            .filter((row: any) => row && typeof row === 'object')
            .map((row: any) => ({
              source_type: String(row.source_type || '').trim(),
              source_path: String(row.source_path || '').trim(),
              chunk_index: Number(row.chunk_index || 0),
              title: String(row.title || row.source_path || '').trim(),
              excerpt: String(row.excerpt || '').trim(),
            }))
        : [],
    }))
    .filter((item: any) => item.source || item.inject_as || item.items.length > 0)
}

function _summarizeRagEvidence(items: Array<Record<string, any>>) {
  const localCount = items.filter(item => String(item.kind || '').includes('local') || String(item.backend || '').includes('knowledge')).length
  const difyCount = items.filter(item => String(item.kind || '') === 'dify' || String(item.backend || '') === 'dify').length
  const slots = Array.from(new Set(items.map(item => String(item.inject_as || '').trim()).filter(Boolean)))
  const parts = [
    localCount ? `项目资料 ${localCount}` : '',
    difyCount ? `外部参考 ${difyCount}` : '',
    slots.length ? `用途 ${slots.join('、')}` : '',
  ].filter(Boolean)
  return parts.join(' · ') || `召回 ${items.length} 条`
}

const MANUAL_EDIT_LOG_MAX = 30

function _manualEditSceneKey(episodeNo: number, sceneNo: number) {
  return `${Math.max(1, Math.round(Number(episodeNo || 1) || 1))}:${Math.max(1, Math.round(Number(sceneNo || 1) || 1))}`
}

function _manualEditExcerpt(text: string, limit = 260) {
  const compact = String(text || '').replace(/\s+/g, ' ').trim()
  if (compact.length <= limit) return compact
  return compact.slice(0, limit - 1).trimEnd() + '…'
}

function _manualEditTailExcerpt(text: string, limit = 360) {
  const compact = String(text || '').replace(/\s+/g, ' ').trim()
  if (compact.length <= limit) return compact
  return '…' + compact.slice(Math.max(0, compact.length - limit + 1)).trimStart()
}

function _manualEditContextRaw() {
  const raw = workflowContext.value.manual_edit_context
  return raw && typeof raw === 'object' && !Array.isArray(raw)
    ? raw as Record<string, any>
    : {}
}

function _setManualEditContext(context: Record<string, any>) {
  workflowContext.value = normalizeWorkflowContext({
    ...workflowContext.value,
    manual_edit_context: clonePlain(context),
  })
}

function _manualEditSnapshot(episodeNo: number, sceneNo: number) {
  const snapshots = _manualEditContextRaw().scene_snapshots
  const store = snapshots && typeof snapshots === 'object' && !Array.isArray(snapshots)
    ? snapshots as Record<string, any>
    : {}
  const item = store[_manualEditSceneKey(episodeNo, sceneNo)]
  return item && typeof item === 'object' ? item as Record<string, any> : {}
}

function _modelCandidateSnapshot(episodeNo: number, sceneNo: number) {
  const snapshots = _manualEditContextRaw().model_candidate_snapshot
  const store = snapshots && typeof snapshots === 'object' && !Array.isArray(snapshots)
    ? snapshots as Record<string, any>
    : {}
  const item = store[_manualEditSceneKey(episodeNo, sceneNo)]
  return item && typeof item === 'object' ? item as Record<string, any> : {}
}

function _restoreCandidateSnapshotIfEditorBlank(episodeNo = selectedEpisode.value, sceneNo = selectedScene.value) {
  if (String(sceneContent.value || '').trim()) return false
  const snapshot = _modelCandidateSnapshot(episodeNo, sceneNo)
  const content = String(snapshot.content || '').trim()
  if (!content) return false
  sceneContent.value = content
  _markSceneContentClean(content)
  toast.info('候选稿已恢复到编辑器，请确认后保存')
  return true
}

async function _restoreLatestJobCandidateIfEditorBlank(episodeNo = selectedEpisode.value, sceneNo = selectedScene.value) {
  if (String(sceneContent.value || '').trim()) return false
  try {
    const { data } = await adminConfigApi.getLatestRuleBackedScriptJob({
      project_id: projectId.value,
      episode_no: Math.max(1, Math.round(Number(episodeNo || 1) || 1)),
      scene_no: Math.max(1, Math.round(Number(sceneNo || 1) || 1)),
    })
    const content = String(data?.candidate?.content || '').trim()
    if (!content) return false
    sceneContent.value = content
    _markSceneContentClean(content)
    await _recordModelCandidateSnapshot(content)
    toast.info('后台候选稿已恢复到编辑器，请确认后保存')
    return true
  } catch (error: any) {
    if (error?.response?.status && error.response.status !== 404) {
      console.warn('restore latest script job candidate failed', error)
    }
    return false
  }
}

async function _recordModelCandidateSnapshot(content: string) {
  const episodeNo = Math.max(1, Math.round(Number(selectedEpisode.value || 1) || 1))
  const sceneNo = Math.max(1, Math.round(Number(selectedScene.value || 1) || 1))
  const context = { ..._manualEditContextRaw() }
  const key = _manualEditSceneKey(episodeNo, sceneNo)
  const snapshots = context.model_candidate_snapshot && typeof context.model_candidate_snapshot === 'object' && !Array.isArray(context.model_candidate_snapshot)
    ? { ...context.model_candidate_snapshot }
    : {}
  snapshots[key] = {
    episode_no: episodeNo,
    scene_no: sceneNo,
    pending_confirmation: true,
    content_hash: simpleHash(content),
    clean_chars: scriptNetCharCount.value,
    head_excerpt: _manualEditExcerpt(content, 360),
    tail_excerpt: _manualEditTailExcerpt(content, 360),
    content: String(content || '').slice(0, 8000),
    updated_at: new Date().toISOString(),
  }
  context.model_candidate_snapshot = snapshots
  _setManualEditContext(context)
  return await _syncProjectWorkflowContext({ immediate: true, silent: true })
}

function _markModelCandidateSnapshotConfirmed(episodeNo: number, sceneNo: number, content: string) {
  const context = { ..._manualEditContextRaw() }
  const key = _manualEditSceneKey(episodeNo, sceneNo)
  const snapshots = context.model_candidate_snapshot && typeof context.model_candidate_snapshot === 'object' && !Array.isArray(context.model_candidate_snapshot)
    ? { ...context.model_candidate_snapshot }
    : {}
  const current = snapshots[key]
  if (!current || typeof current !== 'object') return false
  const contentHash = simpleHash(content)
  if (String(current.content_hash || '') !== contentHash) return false
  snapshots[key] = {
    ...current,
    pending_confirmation: false,
    saved_as_canon: true,
    confirmed_at: new Date().toISOString(),
  }
  context.model_candidate_snapshot = snapshots
  _setManualEditContext(context)
  return true
}

function _upsertManualEditSnapshot(context: Record<string, any>, episodeNo: number, sceneNo: number, content: string) {
  const key = _manualEditSceneKey(episodeNo, sceneNo)
  const snapshots = context.scene_snapshots && typeof context.scene_snapshots === 'object' && !Array.isArray(context.scene_snapshots)
    ? { ...context.scene_snapshots }
    : {}
  snapshots[key] = {
    episode_no: episodeNo,
    scene_no: sceneNo,
    content_hash: simpleHash(content),
    clean_chars: scriptNetCharCount.value,
    excerpt: _manualEditExcerpt(content),
    head_excerpt: _manualEditExcerpt(content, 360),
    tail_excerpt: _manualEditTailExcerpt(content, 360),
    updated_at: new Date().toISOString(),
  }
  return snapshots
}

function _recordManualEditContext(episodeNo: number, sceneNo: number, content: string, changeNote: string, previousSnapshot: Record<string, any>) {
  const previousHash = String(previousSnapshot.content_hash || '')
  const currentHash = simpleHash(content)
  const candidateSnapshot = _modelCandidateSnapshot(episodeNo, sceneNo)
  const previousCandidateContent = String(candidateSnapshot.content || '')
  const previousCandidateHash = String(candidateSnapshot.content_hash || '')
  const manualAddedText = previousCandidateContent && String(content || '').startsWith(previousCandidateContent)
    ? String(content || '').slice(previousCandidateContent.length).trim()
    : ''
  const manualRemovedText = previousCandidateContent && !String(content || '').includes(previousCandidateContent.trim())
    ? _manualEditExcerpt(previousCandidateContent, 220)
    : ''
  const manualAddedExcerpt = _manualEditExcerpt(manualAddedText, 260)
  const manualRemovedExcerpt = _manualEditExcerpt(manualRemovedText, 260)
  const previousCleanChars = Number(previousSnapshot.clean_chars || 0)
  const currentCleanChars = scriptNetCharCount.value
  const context = { ..._manualEditContextRaw() }
  const logs = Array.isArray(context.logs) ? context.logs.slice() : []
  const changed = previousHash ? previousHash !== currentHash : Boolean(String(content || '').trim())
  context.scene_snapshots = _upsertManualEditSnapshot(context, episodeNo, sceneNo, content)
  if (changed) {
    const createdAt = new Date().toISOString()
    const delta = {
      episode_no: episodeNo,
      scene_no: sceneNo,
      previous_content_hash: previousHash,
      current_content_hash: currentHash,
      previous_candidate_hash: previousCandidateHash,
      previous_clean_chars: previousCleanChars,
      current_clean_chars: currentCleanChars,
      clean_char_delta: currentCleanChars - previousCleanChars,
      previous_excerpt: String(previousSnapshot.excerpt || ''),
      current_excerpt: _manualEditExcerpt(content),
      head_excerpt: _manualEditExcerpt(content, 360),
      tail_excerpt: _manualEditTailExcerpt(content, 360),
      candidate_head_excerpt: String(candidateSnapshot.head_excerpt || ''),
      candidate_tail_excerpt: String(candidateSnapshot.tail_excerpt || ''),
      manual_added_excerpt: manualAddedExcerpt,
      manual_removed_excerpt: manualRemovedExcerpt,
      changed,
    }
    const lockedFacts = [`第${episodeNo}集第${sceneNo}场以用户手动保存稿为下一集生成正史。`]
    if (manualAddedExcerpt) {
      lockedFacts.push(`第${episodeNo}集用户新增：${manualAddedExcerpt}`)
    }
    lockedFacts.push(`第${episodeNo}集用户定稿尾部：${_manualEditTailExcerpt(content, 220)}`)
    logs.unshift({
      id: `manual-${Date.now()}-${simpleHash(`${episodeNo}:${sceneNo}:${currentHash}`)}`,
      created_at: createdAt,
      episode_no: episodeNo,
      scene_no: sceneNo,
      change_note: changeNote || '手动编辑',
      manual_edit_delta: delta,
      canon_patch: {
        source: 'user_manual_edit',
        status: 'canon_synced',
        locked_facts: lockedFacts,
        timeline_anchors: [`ep${episodeNo}-scene${sceneNo}:manual_edit:${currentHash}`],
      },
      next_episode_context_sync_gate: {
        status: 'canon_synced',
        next_episode_no: episodeNo + 1,
        must_read_manual_edit: true,
        previous_episode_user_final_hash: currentHash,
        canon_packet_source: 'user_final_content',
        must_not_read_previous_ai_draft: true,
        old_fact_leak_count: null,
      },
    })
  }
  context.logs = logs.slice(0, MANUAL_EDIT_LOG_MAX)
  context.latest = context.logs[0] || context.latest || null
  _setManualEditContext(context)
}

function _buildManualEditEvidenceForSave(
  episodeNo: number,
  sceneNo: number,
  content: string,
  previousSnapshot: Record<string, any>,
) {
  const modelCandidateSnapshot = _modelCandidateSnapshot(episodeNo, sceneNo)
  const modelCandidateHash = String(modelCandidateSnapshot.content_hash || '')
  if (!modelCandidateHash && !String(modelCandidateSnapshot.content || '').trim()) return undefined
  const savedContentHash = simpleHash(content)
  return {
    model_candidate_snapshot: modelCandidateSnapshot,
    model_candidate_hash: modelCandidateHash,
    saved_content_hash: savedContentHash,
    before_content: String(modelCandidateSnapshot.content || ''),
    manual_edit_delta: {
      episode_no: episodeNo,
      scene_no: sceneNo,
      previous_candidate_hash: modelCandidateHash,
      current_content_hash: savedContentHash,
      previous_excerpt: String(previousSnapshot.excerpt || ''),
      current_excerpt: _manualEditExcerpt(content),
      tail_excerpt: _manualEditTailExcerpt(content, 360),
      candidate_head_excerpt: String(modelCandidateSnapshot.head_excerpt || ''),
      candidate_tail_excerpt: String(modelCandidateSnapshot.tail_excerpt || ''),
      clean_char_delta: scriptNetCharCount.value - Number(previousSnapshot.clean_chars || 0),
    },
  }
}

function _touchManualEditSnapshot(episodeNo: number, sceneNo: number, content: string) {
  const context = { ..._manualEditContextRaw() }
  context.scene_snapshots = _upsertManualEditSnapshot(context, episodeNo, sceneNo, content)
  _setManualEditContext(context)
}

function _markManualEditSyncFailed(episodeNo: number, sceneNo: number, content: string) {
  const currentHash = simpleHash(content)
  const context = { ..._manualEditContextRaw() }
  const logs = Array.isArray(context.logs) ? context.logs.slice() : []
  const nextLogs = logs.map((log: any) => {
    const delta = log?.manual_edit_delta && typeof log.manual_edit_delta === 'object' ? log.manual_edit_delta : {}
    if (
      Number(delta.episode_no || log?.episode_no || 0) !== Number(episodeNo)
      || Number(delta.scene_no || log?.scene_no || 0) !== Number(sceneNo)
      || String(delta.current_content_hash || '') !== currentHash
    ) {
      return log
    }
    return {
      ...log,
      canon_patch: {
        ...(log.canon_patch || {}),
        status: 'canon_sync_failed',
      },
      next_episode_context_sync_gate: {
        ...(log.next_episode_context_sync_gate || {}),
        status: 'canon_sync_failed',
        failure_reason: 'workflow_context_sync_failed_after_human_save',
      },
    }
  })
  context.logs = nextLogs
  context.latest = nextLogs[0] || context.latest || null
  _setManualEditContext(context)
}

function _ensureManualEditReadyForGeneration() {
  const result = findBlockingManualEditSyncGate(
    workflowContext.value.manual_edit_context,
    selectedEpisode.value,
  )
  if (result.blocked) {
    toast.error(result.message)
    return false
  }
  return true
}

async function _markManualEditGateConsumedAfterGeneration() {
  const before = workflowContext.value.manual_edit_context || {}
  const next = markManualEditGateConsumed(before, selectedEpisode.value, {
    generated_content_hash: simpleHash(String(sceneContent.value || '')),
    generated_at: new Date().toISOString(),
  })
  if (JSON.stringify(next) === JSON.stringify(before)) return true
  _setManualEditContext(next)
  return await _syncProjectWorkflowContext({ immediate: true, silent: true })
}



function _applyWorkflowContextResponse(payload?: {
  workflow_context?: Record<string, any>
  canon_packet?: Record<string, any>
  episode_memory_cards?: Array<Record<string, any>>
} | null) {
  if (!payload || typeof payload !== 'object') return
  if (payload.workflow_context && typeof payload.workflow_context === 'object') {
    const next = normalizeWorkflowContext(payload.workflow_context)
    if (JSON.stringify(next) !== JSON.stringify(workflowContext.value)) {
      workflowContext.value = next
    }
  }
  if (payload.canon_packet && typeof payload.canon_packet === 'object') {
    const next = _normalizeCanonPacket(payload.canon_packet)
    if (JSON.stringify(next) !== JSON.stringify(canonPacket.value)) {
      canonPacket.value = next
    }
  }
  if (Array.isArray(payload.episode_memory_cards)) {
    const next = _normalizeEpisodeMemoryCards(payload.episode_memory_cards)
    if (JSON.stringify(next) !== JSON.stringify(episodeMemoryCards.value)) {
      episodeMemoryCards.value = next
    }
  }
}

function _hydrateOutlineStateFromWorkflow(raw?: any) {
  if (!raw || typeof raw !== 'object') return
  const nextOutline = raw.outline_data
  if (nextOutline && typeof nextOutline === 'object') {
    outlineData.value = {
      ...outlineData.value,
      ...nextOutline,
      episodes: Array.isArray(nextOutline.episodes) ? nextOutline.episodes : outlineData.value.episodes,
    }
  }
  if (Array.isArray(raw.outline_characters) && raw.outline_characters.length > 0) {
    outlineCharacters.value = _sanitizeOutlineCharacters(raw.outline_characters) as any
  }
  if (typeof raw.raw_outline_text === 'string' && raw.raw_outline_text.trim()) {
    rawOutlineText.value = raw.raw_outline_text
  }
  if (raw.standard_outline_packet && typeof raw.standard_outline_packet === 'object') {
    standardOutlinePacket.value = normalizeStandardOutlinePacket(raw.standard_outline_packet)
  }
  if (raw.candidate_source === 'local_fallback' && raw.main_chain_committed !== true) {
    outlineFallbackCandidateBoundary.value = {
      candidate_source: 'local_fallback',
      needs_user_confirmation: true,
      main_chain_committed: false,
      downstream_generation_allowed: false,
      fallback_reason: String(raw.fallback_reason || ''),
      candidate_boundary_reason: String(raw.candidate_boundary_reason || 'local_fallback'),
      updated_at: String(raw.updated_at || new Date().toISOString()),
    }
  } else if (raw.main_chain_committed === true) {
    _clearOutlineFallbackCandidateBoundary()
  }
}

async function _persistOutlineDraft(reason = 'outline_draft_updated', options?: { silent?: boolean; sync?: boolean; preserveEditorData?: boolean }) {
  saveWorkspaceStorage('outline', projectId.value, JSON.stringify(outlineData.value))
  saveWorkspaceStorage('outlineChars', projectId.value, JSON.stringify(outlineCharacters.value))
  if (rawOutlineText.value) saveWorkspaceStorage('rawOutline', projectId.value, rawOutlineText.value)
  return await _persistOutlineSnapshot(reason, {
    silent: options?.silent,
    sync: options?.sync,
    mainChainCommitted: false,
    sanitizeOutlineCharacters: options?.preserveEditorData !== true,
  })
}

async function _persistOutlineSnapshot(
  reason = 'outline_updated',
  options?: { silent?: boolean; sync?: boolean; mainChainCommitted?: boolean; sanitizeOutlineCharacters?: boolean },
) {
  if (options?.sanitizeOutlineCharacters !== false) {
    outlineCharacters.value = _sanitizeOutlineCharacters(outlineCharacters.value as any[]) as any
  }
  const now = new Date().toISOString()
  const mainChainCommitted = options?.mainChainCommitted === true
  const fallbackBoundary = outlineFallbackCandidateBoundary.value
  const mainChainSource = mainChainCommitted
    ? 'user_confirmed_outline'
    : reason === 'chat_brainstorm_outline_draft'
      ? 'chat_brainstorm_candidate'
      : fallbackBoundary?.candidate_source === 'local_fallback'
        ? 'local_fallback_candidate'
      : 'outline_editor_draft'
  const snapshot = {
    outline_data: JSON.parse(JSON.stringify(outlineData.value)),
    outline_characters: JSON.parse(JSON.stringify(outlineCharacters.value)),
    raw_outline_text: rawOutlineText.value || '',
    standard_outline_packet: JSON.parse(JSON.stringify(standardOutlinePacket.value)),
    confirmed_total_episodes: _effectiveUserConfirmedTotalEpisodes() || null,
    updated_reason: reason,
    updated_at: now,
    main_chain_status: mainChainCommitted ? 'user_locked_main_chain' : 'candidate_draft_needs_user_confirmation',
    main_chain_source: mainChainSource,
    candidate_source: !mainChainCommitted && fallbackBoundary?.candidate_source
      ? fallbackBoundary.candidate_source
      : mainChainSource,
    fallback_reason: fallbackBoundary?.fallback_reason || '',
    candidate_boundary_reason: fallbackBoundary?.candidate_boundary_reason || '',
    main_chain_committed: mainChainCommitted,
    main_chain_dirty: !mainChainCommitted,
    main_chain_committed_at: mainChainCommitted ? now : '',
    main_chain_reason: mainChainCommitted ? reason : '',
    user_confirmation_required: !mainChainCommitted,
    downstream_generation_allowed: mainChainCommitted,
    promoted_from_candidate_source: mainChainCommitted && fallbackBoundary?.candidate_source
      ? fallbackBoundary.candidate_source
      : '',
  }
  workflowContext.value = normalizeWorkflowContext(_deepMergeRecord(workflowContext.value, {
    outline_state: snapshot,
  }))
  if (options?.sync !== false) {
    return await _syncProjectWorkflowContext({ silent: options?.silent ?? true })
  }
  return true
}

function _ingestWorkflowUpdates(payload?: any, options?: { persist?: boolean }) {
  if (!payload || typeof payload !== 'object') return
  let nextWorkflowContext = workflowContext.value
  let dirty = false
  const hasBlockingIssues = Array.isArray(payload.blocking_issues)
    && payload.blocking_issues.some((item: any) => String(item || '').trim())
  const canPromoteRuntimeState = !hasBlockingIssues && payload.success !== false

  const memoryCard = canPromoteRuntimeState ? _normalizeEpisodeMemoryCard(payload.episode_memory_card) : ({} as any)
  if (canPromoteRuntimeState && memoryCard.episode_no) {
    const mergedCards = _mergeEpisodeMemoryCards(episodeMemoryCards.value, [memoryCard])
    if (JSON.stringify(mergedCards) !== JSON.stringify(episodeMemoryCards.value)) {
      episodeMemoryCards.value = mergedCards
      dirty = true
    }
  }

  const incomingCanon = canPromoteRuntimeState ? _normalizeCanonPacket(payload.canon_packet) : {}
  if (canPromoteRuntimeState && Object.keys(incomingCanon).length > 0) {
    const mergedCanon = _deepMergeRecord(canonPacket.value, incomingCanon)
    if (JSON.stringify(mergedCanon) !== JSON.stringify(canonPacket.value)) {
      canonPacket.value = mergedCanon
      dirty = true
    }
  }

  const workflowPatch: Record<string, any> = {}
  const ragEvidence = _normalizeRagEvidenceItems(payload.rag_evidence)
  if (ragEvidence.length > 0) {
    const existingLog = Array.isArray(workflowContext.value.rag_evidence_log)
      ? workflowContext.value.rag_evidence_log
      : []
    const createdAt = new Date().toISOString()
    const entry = {
      id: `rag-${Date.now()}-${simpleHash(JSON.stringify(ragEvidence).slice(0, 1200))}`,
      created_at: createdAt,
      episode_no: Number(selectedEpisode.value || 0),
      scene_no: Number(selectedScene.value || 0),
      summary: _summarizeRagEvidence(ragEvidence),
      items: ragEvidence,
    }
    workflowPatch.rag_evidence_log = [entry, ...existingLog].slice(0, RAG_EVIDENCE_LOG_MAX)
  }
  if (payload.quality_report && typeof payload.quality_report === 'object') {
    workflowPatch.quality_report = payload.quality_report
  }
  if (payload.compliance_report && typeof payload.compliance_report === 'object') {
    workflowPatch.compliance_report = payload.compliance_report
  }
  if (payload.benchmark_assessment || payload.continuity_assessment) {
    Object.assign(workflowPatch, buildWorkflowAuditPatch(payload))
  }
  if (
    payload.director_blueprint
    && typeof payload.director_blueprint === 'object'
    && !Array.isArray(payload.director_blueprint)
    && Object.keys(payload.director_blueprint).length > 0
  ) {
    const existingBlueprints = workflowContext.value.director_blueprints && typeof workflowContext.value.director_blueprints === 'object'
      ? workflowContext.value.director_blueprints as Record<string, any>
      : {}
    const key = String(Number(selectedEpisode.value || 1) || 1)
    workflowPatch.director_blueprints = {
      ...existingBlueprints,
      [key]: {
        ...payload.director_blueprint,
        episode_no: Number(selectedEpisode.value || 1) || 1,
        scene_no: Number(selectedScene.value || 1) || 1,
        updated_at: new Date().toISOString(),
      },
    }
  }
  if (payload.generation_trace && typeof payload.generation_trace === 'object') {
    const existingTrace = workflowContext.value.director_generation_trace && typeof workflowContext.value.director_generation_trace === 'object'
      ? workflowContext.value.director_generation_trace as Record<string, any>
      : {}
    const key = String(Number(selectedEpisode.value || 1) || 1)
    workflowPatch.director_generation_trace = {
      ...existingTrace,
      [key]: {
        ...payload.generation_trace,
        episode_no: Number(selectedEpisode.value || 1) || 1,
        scene_no: Number(selectedScene.value || 1) || 1,
        updated_at: new Date().toISOString(),
      },
    }
  }
  if (Object.keys(workflowPatch).length > 0) {
    nextWorkflowContext = normalizeWorkflowContext(_deepMergeRecord(workflowContext.value, workflowPatch))
    if (JSON.stringify(nextWorkflowContext) !== JSON.stringify(workflowContext.value)) {
      workflowContext.value = nextWorkflowContext
      dirty = true
    }
  }

  if (dirty && options?.persist) {
    _syncProjectWorkflowContext({ immediate: false })
  }
}

function _hasSeriesSimulationContracts(packet?: any) {
  return hasSeriesSimulationContracts(packet)
}

function ensureOutlineGatePassed(options?: { episodeLimit?: number }) {
  const scopedIssues = options?.episodeLimit
    ? outlineGateIssuesForEpisodeLimit(options.episodeLimit)
    : outlineGateIssues.value
  if (options?.episodeLimit ? scopedIssues.length === 0 : outlineGateAllowsScript.value) return true
  const primaryIssue = scopedIssues[0] || firstOutlineGateBlockingMessage(options?.episodeLimit) || '上游信息未完成'
  const remainingIssueCount = Math.max(0, scopedIssues.length - 1)
  const detail = remainingIssueCount > 0 ? `${primaryIssue}；另有 ${remainingIssueCount} 项待补` : primaryIssue
  const repair = firstOutlineGateRepairHint(options?.episodeLimit)
  toast.error(`请先完成大纲锁定门：${detail}${repair ? `。处理方式：${repair}` : ''}`)
  return false
}

async function _refreshSeriesSimulationPacket(reason = 'outline_updated', options?: { persist?: boolean; silent?: boolean }) {
  const packet = _buildSeriesSimulationPacket()
  if (!_hasSeriesSimulationContracts(packet)) return packet

  const currentPacket = workflowContext.value.series_simulation_packet || {}
  let changed = false
  if (JSON.stringify(currentPacket) !== JSON.stringify(packet)) {
    workflowContext.value = normalizeWorkflowContext(_deepMergeRecord(workflowContext.value, {
      series_simulation_packet: {
        ...packet,
        updated_reason: reason,
        updated_at: new Date().toISOString(),
      },
    }))
    changed = true
  }

  if (changed && options?.persist !== false) {
    await _syncProjectWorkflowContext({ silent: options?.silent ?? true })
  }
  return packet
}

async function _syncProjectWorkflowContext(options?: { immediate?: boolean; silent?: boolean }) {
  if (!project.value || isLoading.value) return false
  try {
    lastWorkflowContextSyncError.value = null
    const { data } = await projectsV2Api.saveWorkflowContext(projectId.value, {
      workflow_context: workflowContext.value,
      canon_packet: canonPacket.value,
      episode_memory_cards: episodeMemoryCards.value,
      merge: true,
    })
    _applyWorkflowContextResponse(data)
    return true
  } catch (e) {
    lastWorkflowContextSyncError.value = e
    if (!options?.silent) {
      console.warn('workflow context sync failed', e)
    }
    return false
  }
}

// 状态卡 / 工作流上下文 的 debounce 写库副作用：抽到 useStoryStateAutosave。
// onUnmounted 时 timer 也会被自动清掉（不再像以前那样在 main onUnmounted 里手动清）。
const storyStateAutosave = useStoryStateAutosave({
  projectId,
  isReady: computed(() => !!project.value && !isLoading.value),
  storyStateCards,
  workflowContext,
  canonPacket,
  episodeMemoryCards,
  syncWorkflowContext: _syncProjectWorkflowContext,
})
_runStoryStateAutosaveExclusive = storyStateAutosave.runExclusive

// 状态卡 CRUD（add / upsert / remove / toggleCharacter / makeStateCard）
// 已搬到 useStoryStateCards composable。
// 实例化挂在 scriptSceneCharacters 定义之后（见下方）。

// 角色相关 watch / 函数已搬到 useCharacterTab composable

// ─── 剧本写作 Tab ─────────────────────────────────────────────────────────────
// 集 / 场 / 内容 / 缓存 / autosave 全部由 useEpisodeScenes composable 统一管理。
// 这一 composable 内部封死了"防竞态切集 + 内存缓存 + 邻集预热 + 脏标记 autosave + 404 重建场"，
// 进一步改这套逻辑只需要改 useEpisodeScenes.ts 一个文件。
const {
  episodes,
  selectedEpisode,
  scenes,
  selectedScene,
  sceneContent,
  lastSavedSceneContent,
  isHydratingSceneContent,
  scenesLoading,
  loadScenes,
  loadEpisodes,
  refreshEpisodesSilently,
  autoSaveCurrentScene: _autoSaveCurrentScene,  // 保留下划线别名给老调用点
  invalidateScenesCache: _invalidateScenesCache,
  markSceneContentClean: _markSceneContentClean,
  hasUnsavedSceneChanges,
} = useEpisodeScenes({
  projectId,
  // 下面 3 个回调引用的变量在更晚的位置定义。在 onMounted 之前不会被调用，
  // 等 useSegmentedWriting / _syncProjectWorkflowContext 都已就绪再生效。
  syncWorkflowContext: () => _syncProjectWorkflowContext({ immediate: true, silent: true }),
  resetSegments: () => resetSegments(),
  closeSegmentPanel: () => { showSegmentPanel.value = false },
})
let isPreparingScriptPersistence = false
const isSavingScript = ref(false)
const isCreatingEpisode = ref(false)
const isCreatingScene = ref(false)
const isGeneratingNextEpisode = ref(false)
const quickWriteTakeoverMode = ref(false)
const showRagEvidenceDiagnostics = computed(() => {
  return route.query.debug === 'rag'
})

function handleBeforeUnload(event: BeforeUnloadEvent) {
  if (!hasUnsavedSceneChanges()) return
  event.preventDefault()
  event.returnValue = ''
}

onBeforeRouteLeave(async () => {
  if (!hasUnsavedSceneChanges()) return true
  const saved = await persistCurrentScriptContent({
    silent: true,
    changeNote: '离开页面前自动保存',
    editorType: 'human',
  })
  if (saved !== false) return true
  toast.error('正文保存失败，请先保存成功后再离开页面')
  return false
})

// 真实写作进度：基于 episodes 列表里每集的 completed_scenes / total_scenes，
// 而不是早期 useWorkspaceTabs 那个 "Tab 走过几个" 的伪进度。
// 每次保存后会 void loadEpisodes() 刷新数据，进度自动跟进。
const realProgressPercent = computed(() => {
  const totalEps = _effectiveUserConfirmedTotalEpisodes()
  if (totalEps <= 0) return 0
  const eps = episodes.value || []
  if (eps.length === 0) return 0
  let totalScore = 0
  for (const ep of eps) {
    const status = String(ep?.status || 'draft')
    if (status === 'completed') {
      totalScore += 1
      continue
    }
    const totalScenes = Number(ep?.total_scenes || 0)
    const doneScenes = Number(ep?.completed_scenes || 0)
    if (totalScenes > 0) {
      totalScore += Math.min(1, doneScenes / totalScenes)
    }
  }
  return Math.min(100, Math.round((totalScore / totalEps) * 100))
})
const latestRagEvidenceLog = computed(() => {
  const logs = Array.isArray(workflowContext.value.rag_evidence_log)
    ? workflowContext.value.rag_evidence_log
    : []
  return logs[0] || null
})
const latestManualEditLog = computed(() => {
  const context = workflowContext.value.manual_edit_context
  if (!context || typeof context !== 'object' || Array.isArray(context)) return null
  const logs = Array.isArray((context as Record<string, any>).logs)
    ? (context as Record<string, any>).logs
    : []
  return logs[0] || null
})
const latestDirectorGenerationTrace = computed(() => {
  const traces = workflowContext.value.director_generation_trace
  if (!traces || typeof traces !== 'object' || Array.isArray(traces)) return null
  const current = (traces as Record<string, any>)[String(selectedEpisode.value)]
  return current && typeof current === 'object' && !Array.isArray(current) ? current : null
})
const ragEvidenceLogs = computed(() => {
  return Array.isArray(workflowContext.value.rag_evidence_log)
    ? workflowContext.value.rag_evidence_log
    : []
})
const latestScriptGenerationFailureLog = computed(() => {
  const logs = Array.isArray(workflowContext.value.script_generation_failure_log)
    ? workflowContext.value.script_generation_failure_log
    : []
  return logs[0] || null
})

const isCurrentPendingModelCandidate = computed(() => {
  const snapshot = _modelCandidateSnapshot(selectedEpisode.value, selectedScene.value)
  const contentHash = String(snapshot.content_hash || '')
  return Boolean(
    contentHash
    && contentHash === simpleHash(String(sceneContent.value || ''))
    && snapshot.pending_confirmation !== false
  )
})

function _clearCandidatePendingStatusAfterSave() {
  const current = String(scriptStreamStatus.value || '')
  if (/已生成候选内容|候选内容尚未自动保存|候选稿已恢复/.test(current)) {
    scriptStreamStatus.value = ''
  }
}

const manualEditLineMarkers = computed(() => {
  if (!hasUnsavedSceneChanges()) return []
  if (isCurrentPendingModelCandidate.value) return []
  const beforeLines = String(lastSavedSceneContent.value || '').split('\n')
  const afterLines = String(sceneContent.value || '').split('\n')
  const markers: Array<{ lineNo: number, kind: 'added' | 'changed' | 'removed', text: string }> = []
  const total = Math.max(beforeLines.length, afterLines.length)
  for (let index = 0; index < total; index += 1) {
    const before = String(beforeLines[index] || '').trim()
    const after = String(afterLines[index] || '').trim()
    if (before === after) continue
    if (!after && before) {
      markers.push({ lineNo: index + 1, kind: 'removed', text: `已删除：${before.slice(0, 160)}` })
    } else {
      markers.push({ lineNo: index + 1, kind: before ? 'changed' : 'added', text: after.slice(0, 160) })
    }
    if (markers.length >= 6) break
  }
  return markers
})

const SCRIPT_GENERATION_FAILURE_LOG_MAX = 30

async function _recordScriptGenerationFailure(payload: Record<string, any>) {
  const requestContext = payload.request_context && typeof payload.request_context === 'object'
    ? payload.request_context as Record<string, any>
    : {}
  const episodeNo = Math.max(1, Math.round(Number(requestContext.episode_no || selectedEpisode.value || 1) || 1))
  const sceneNo = Math.max(1, Math.round(Number(requestContext.scene_no || selectedScene.value || 1) || 1))
  const existing = Array.isArray(workflowContext.value.script_generation_failure_log)
    ? workflowContext.value.script_generation_failure_log
    : []
  const latestManual = latestManualEditLog.value
  const entry = {
    id: `script-fail-${Date.now()}-${simpleHash(`${episodeNo}:${sceneNo}:${payload.status || ''}:${payload.detail || ''}`)}`,
    created_at: new Date().toISOString(),
    episode_no: episodeNo,
    scene_no: sceneNo,
    status: String(payload.status || 'failed'),
    source: String(payload.source || 'research_chain_job'),
    detail: String(payload.detail || '生成失败'),
    suggestion: String(payload.suggestion || ''),
    public_detail: String(payload.public_detail || ''),
    public_suggestion: String(payload.public_suggestion || ''),
    display: String(payload.display || ''),
    retryable: payload.retryable !== false,
    elapsed_ms: Number(payload.elapsed_ms || 0),
    attempt: Number(payload.attempt || requestContext.client_retry_attempt || 0),
    error_code: String(payload.error_code || ''),
    issues: Array.isArray(payload.issues) ? payload.issues.map((item: any) => String(item || '')).filter(Boolean) : [],
    had_streamed_content: Boolean(payload.had_streamed_content),
    streamed_chars: Number(payload.streamed_chars || 0),
    current_content_hash: simpleHash(String(sceneContent.value || '')),
    current_clean_chars: scriptNetCharCount.value,
    request_context: requestContext,
    manual_edit_gate: latestManual?.next_episode_context_sync_gate || null,
  }
  workflowContext.value = normalizeWorkflowContext(_deepMergeRecord(workflowContext.value, {
    script_generation_failure_log: [entry, ...existing].slice(0, SCRIPT_GENERATION_FAILURE_LOG_MAX),
  }))
  return await _syncProjectWorkflowContext({ immediate: true, silent: true })
}
const {
  isGeneratingScript,
  scriptStreamStatus,
  scriptWorkflowSteps,
  generateScript: generateScriptDraft,
  stopGeneratingScript,
} = useScriptDraftGeneration({
  ensureOutlineGatePassed: () => ensureOutlineGatePassed({ episodeLimit: Number(selectedEpisode.value || 1) || 1 }),
  persistProjectRules: () => persistProjectRules({ silent: true }),
  ensureManualEditSyncReady: _ensureManualEditReadyForGeneration,
  getSceneContent: () => sceneContent.value,
  setSceneContent: content => { sceneContent.value = content },
  ensureScriptApproved: () => quickWriteTakeoverMode.value
    ? Promise.resolve(true)
    : ensureScriptInternallyApproved({ silent: true, allowAutoFix: false }),
  resolveLengthPolicy: () => _resolveRequestLengthPolicy({
    mode: 'scene',
    currentContent: sceneContent.value,
  }),
  buildRequest: currentContent => ({
    ..._buildRuleBackedScriptRequest({
      mode: 'scene',
      currentContent,
    }),
    issue_feedback: _buildQuickWriteIssueFeedback(),
    rule_profile: _appendRuleProfileTag(workflowContext.value.rule_profile, 'research_chain_draft'),
    draft_mode: 'research_chain',
    research_generation_mode: true,
    temperature: 0.62,
  }),
  startScriptJob: async requestPayload => {
    const { data } = await adminConfigApi.startRuleBackedScriptJob(requestPayload)
    return data
  },
  getScriptJobStatus: async jobId => {
    const { data } = await adminConfigApi.getRuleBackedScriptJobStatus(jobId)
    return data
  },
  ingestWorkflowUpdates: payload => _ingestWorkflowUpdates(payload, { persist: true }),
  refreshRuntimeSignals: async () => {
    await refreshScriptRuntimeSignals({ silent: true, autoApplySuggestions: true, deepAudit: true })
  },
  autoSaveCurrentScene: async () => persistCurrentScriptContent({
    silent: true,
    changeNote: '主链路生成自动保存',
    editorType: 'ai',
  }),
  recordCandidateSnapshot: content => _recordModelCandidateSnapshot(content),
  markManualEditConsumedAfterGeneration: _markManualEditGateConsumedAfterGeneration,
  recordGenerationFailure: payload => _recordScriptGenerationFailure(payload),
  scriptNetCharCount: () => scriptNetCharCount.value,
  notify: {
    success: message => toast.success(message),
    error: message => toast.error(message),
    warning: message => toast.warning(message),
  },
})

// 集/场/缓存/autosave 实现已移到 useEpisodeScenes composable


// 新建集（自动从大纲集纲获取标题和简介）
async function createEpisode() {
  const persisted = await persistProjectRules({ silent: true })
  if (!persisted) {
    toast.error('项目规则尚未同步成功，暂时不能继续建集')
    return
  }
  isCreatingEpisode.value = true
  const nextEp = episodes.value.length > 0
    ? Math.max(...episodes.value.map((e: any) => e.episode_number)) + 1
    : 1
  const confirmedTotal = _effectiveUserConfirmedTotalEpisodes()
  if (!confirmedTotal) {
    isCreatingEpisode.value = false
    toast.warning('请先确认总集数；用户确认多少集，系统就创建多少集。')
    return
  }
  if (nextEp > confirmedTotal) {
    isCreatingEpisode.value = false
    toast.error(`当前项目总集数上限为 ${confirmedTotal} 集，请先回大纲编辑调整`)
    return
  }
  const epInfo = outlineData.value.episodes.find((e: any) => e.ep === nextEp)
  try {
    await projectsV2Api.createEpisode(projectId.value, {
      title: epInfo?.title || `第${nextEp}集`,
      summary: epInfo?.summary || '',
      status: 'draft',
    }, nextEp)
    await projectsV2Api.createScene(projectId.value, nextEp, {
      time: '',
      location_type: 'INT',
      location_name: '待填写',
      content: ''
    })
    toast.success(`第${nextEp}集已创建`)
    await loadEpisodes()
    await loadScenes(nextEp)
  } catch (e: any) {
    notifyApiError(toast.error, e, '创建集失败')
  } finally {
    isCreatingEpisode.value = false
  }
}

async function createEpisodesBatch(options?: { silent?: boolean }) {
  const persisted = await persistProjectRules({ silent: true })
  if (!persisted) {
    if (!options?.silent) toast.error('项目规则尚未同步成功，暂时不能批量建集')
    return false
  }
  const total = _effectiveUserConfirmedTotalEpisodes()
  if (!total) {
    if (!options?.silent) toast.warning('请先确认总集数；用户确认多少集，系统就创建多少集。')
    return false
  }
  await loadEpisodes()
  const existingNumbers = new Set(
    episodes.value
      .map((episode: any) => Number(episode?.episode_number))
      .filter(Number.isFinite),
  )
  const missingNumbers: number[] = []
  for (let epNo = 1; epNo <= total; epNo += 1) {
    if (!existingNumbers.has(epNo)) missingNumbers.push(epNo)
  }
  if (!missingNumbers.length) {
    if (!options?.silent) toast.success(`当前已补齐 ${projectRules.value.total_episodes} 集`)
    return true
  }

  isCreatingEpisode.value = true
  const createdNumbers: number[] = []
  try {
    for (const epNo of missingNumbers) {
      const epInfo = outlineData.value.episodes.find((episode: any) => Number(episode.ep) === epNo)
      try {
        await projectsV2Api.createEpisode(projectId.value, {
          title: epInfo?.title || `第${epNo}集`,
          summary: epInfo?.summary || '',
          status: 'draft',
        }, epNo)
      } catch (e: any) {
        if (!_isEpisodeAlreadyExistsError(e)) throw e
        continue
      }
      await projectsV2Api.createScene(projectId.value, epNo, {
        time: '',
        location_type: 'INT',
        location_name: '待填写',
        content: '',
      })
      createdNumbers.push(epNo)
    }
    if (!options?.silent) toast.success(`已批量创建 ${createdNumbers.length} 集，补齐到总集数`)
    await loadEpisodes()
    await loadScenes(createdNumbers[0] || selectedEpisode.value)
    return true
  } catch (e: any) {
    if (!options?.silent) notifyApiError(toast.error, e, '批量创建集失败')
    return false
  } finally {
    isCreatingEpisode.value = false
  }
}

async function saveEpisodeFromSidebar(episodeNumber: number) {
  if (Number(episodeNumber) !== Number(selectedEpisode.value)) {
    toast.warning('请先切到这一集，再保存当前正文')
    return
  }
  await saveScript()
}

async function deleteEpisode(episodeNumber: number) {
  const targetEp = Math.max(1, Math.round(Number(episodeNumber) || 0))
  if (!targetEp) return
  if (isGeneratingScript.value || isSegmentGenerating.value || isSavingScript.value) {
    toast.warning('当前正在生成或保存，请完成后再删除分集')
    return
  }
  const ok = confirm(`确认删除第${targetEp}集吗？这一集的正文、版本和分段进度都会一起删除。`)
  if (!ok) return

  const remainingEpisodeNumbers = episodes.value
    .map((ep: any) => Number(ep?.episode_number || 0))
    .filter(ep => ep > 0 && ep !== targetEp)
    .sort((a, b) => a - b)
  const nextEp = remainingEpisodeNumbers.find(ep => ep > targetEp)
    || remainingEpisodeNumbers[remainingEpisodeNumbers.length - 1]
    || 0

  try {
    await projectsV2Api.deleteEpisode(projectId.value, targetEp)
    _invalidateScenesCache(targetEp)
    const progress = workflowContext.value.script_segment_progress
    if (progress && typeof progress === 'object') {
      delete (progress as Record<string, unknown>)[String(targetEp)]
    }
    if (Number(selectedEpisode.value) === targetEp) {
      selectedEpisode.value = nextEp || 1
      selectedScene.value = 1
      sceneContent.value = ''
      _markSceneContentClean('')
      resetSegments()
      showSegmentPanel.value = false
    }
    await _syncProjectWorkflowContext({ immediate: true, silent: true })
    await loadEpisodes()
    if (nextEp) {
      selectedEpisode.value = nextEp
      selectedScene.value = 1
      sceneContent.value = ''
      _markSceneContentClean('')
      await loadScenes(nextEp)
      await ensureCurrentEpisodeExistingScriptVisible(nextEp, { silent: true })
      await _hydrateSegmentProgressForEpisode(nextEp)
    } else {
      scenes.value = []
      selectedScene.value = 1
      sceneContent.value = ''
      _markSceneContentClean('')
    }
    toast.success(`第${targetEp}集已删除`)
  } catch (e: any) {
    notifyApiError(toast.error, e, '删除分集失败')
  }
}

async function ensureScriptEpisodeReady(targetEpisode?: number) {
  const targetEp = Math.max(1, Math.round(Number(targetEpisode ?? selectedEpisode.value) || 1))
  await _markExistingScriptOptOutIfEditorBlank(targetEp)
  await ensureOutlineExistingScriptsSeeded({ silent: true })
  if (episodes.value.length === 0) {
    await loadEpisodes()
  }

  const hasEpisode = () => episodes.value.some((ep: any) => Number(ep?.episode_number) === targetEp)
  try {
    if (!hasEpisode()) {
      const totalEpisodes = _effectiveUserConfirmedTotalEpisodes()
      if (!totalEpisodes) {
        toast.warning('请先确认总集数；确认后才能进入正式剧本写作。')
        return false
      }
      if (targetEp > totalEpisodes) {
        toast.error(`当前项目总集数上限为 ${totalEpisodes} 集，请先回大纲编辑调整`)
        return false
      }
      const persisted = await persistProjectRules({ silent: true })
      if (!persisted) {
        toast.error('项目规则尚未同步成功，暂时不能继续写作')
        return false
      }

      const epInfo = outlineData.value.episodes.find((e: any) => Number(e.ep) === targetEp)
      isCreatingEpisode.value = true
      try {
        await projectsV2Api.createEpisode(projectId.value, {
          title: epInfo?.title || `第${targetEp}集`,
          summary: epInfo?.summary || '',
          status: 'draft',
        }, targetEp)
      } catch (e: any) {
        if (!_isEpisodeAlreadyExistsError(e)) throw e
      }
      try {
        await projectsV2Api.createScene(projectId.value, targetEp, {
          time: '',
          location_type: 'INT',
          location_name: '待填写',
          content: '',
        })
      } catch (e: any) {
        if (e?.response?.status !== 409) throw e
      }
      _invalidateScenesCache(targetEp)
      await loadEpisodes()
      await loadScenes(targetEp)
      await ensureCurrentEpisodeExistingScriptVisible(targetEp, { silent: true })
      await _hydrateSegmentProgressForEpisode(targetEp)
      toast.success(`第${targetEp}集已自动建立，可以开始写作`)
      return true
    }

    if (Number(selectedEpisode.value) !== targetEp || scenes.value.length === 0) {
      await loadScenes(targetEp)
    }
    if (scenes.value.length === 0) {
      await projectsV2Api.createScene(projectId.value, targetEp, {
        time: '',
        location_type: 'INT',
        location_name: '待填写',
        content: '',
      })
      _invalidateScenesCache(targetEp)
      await loadScenes(targetEp)
    }
    await ensureCurrentEpisodeExistingScriptVisible(targetEp, { silent: true })
    await _hydrateSegmentProgressForEpisode(targetEp)
    return true
  } catch (e: any) {
    notifyApiError(toast.error, e, '准备写作分集失败')
    return false
  } finally {
    isCreatingEpisode.value = false
  }
}

async function loadScriptEpisode(episodeNumber: number) {
  const targetEpisode = _normalizeEpisodeNo(episodeNumber)
  const activeTarget = activeSegmentGenerationTarget.value
  if ((isSegmentGenerating.value || showSegmentPanel.value) && activeTarget && targetEpisode !== activeTarget.episodeNo) {
    toast.warning(`第${activeTarget.episodeNo}集正在生成或等待确认，请先完成当前集后再切换。`)
    return
  }
  await _persistCurrentSegmentProgress()
  const saved = await persistCurrentScriptContent({
    silent: true,
    changeNote: '切集前自动保存',
    editorType: 'human',
  })
  if (!saved) {
    toast.error('正文保存失败，请先保存成功后再切换集数')
    return
  }
  await loadScenes(episodeNumber)
  await ensureCurrentEpisodeExistingScriptVisible(episodeNumber, { silent: true })
  if (!_restoreCandidateSnapshotIfEditorBlank(episodeNumber)) {
    await _restoreLatestJobCandidateIfEditorBlank(episodeNumber)
  }
  await _hydrateSegmentProgressForEpisode(episodeNumber)
}

async function selectScriptScene(scene: any) {
  const nextScene = Math.max(1, Math.round(Number(scene?.scene_number || 1) || 1))
  if (nextScene === Number(selectedScene.value || 1)) return
  if (hasUnsavedSceneChanges()) {
    const saved = await persistCurrentScriptContent({
      silent: true,
      changeNote: '切场前自动保存',
      editorType: 'human',
    })
    if (!saved) {
      toast.error('当前场景保存失败，请先保存成功后再切换场景')
      return
    }
  }
  selectedScene.value = nextScene
  sceneContent.value = String(scene?.content || '')
  _markSceneContentClean(sceneContent.value)
}

async function runSegmentedWritingWithEpisode(options?: { forceRegenerateCurrentDraft?: boolean }) {
  const target = _startSegmentedGenerationTarget(selectedEpisode.value, selectedScene.value)
  try {
    await _refreshSeriesSimulationPacket('script_generation_preflight', { silent: true })
    const previewPayload = _buildRuleBackedScriptRequest({
      mode: 'segment',
      segmentId: 'hook',
      currentContent: sceneContent.value,
      targetEpisodeNo: target.episodeNo,
      targetSceneNo: target.sceneNo,
    })
    if (!(await _previewBackendGenerationSource(previewPayload))) return
    const outlineGateReady = ensureOutlineGatePassed({ episodeLimit: target.episodeNo })
    if (!outlineGateReady) {
      scriptStreamStatus.value = '后端生成资料包预检通过，本地大纲检查有提醒，继续按后端裁决启动生成。'
    }
    if (!(await ensureScriptEpisodeReady(target.episodeNo))) return
    scriptStreamStatus.value = '正在生成本集正文，请不要关闭页面。'
    await generateSegmented({ ...options, sourcePrechecked: true })
  } catch (error: any) {
    scriptStreamStatus.value = '生成失败：本次没有保存空内容。请稍后重试，或检查本集集纲和模型连接。'
    notifyApiError(toast.error, error, '生成失败')
  } finally {
    if (!isSegmentGenerating.value && !showSegmentPanel.value) {
      _clearSegmentedGenerationTarget(target.episodeNo)
    }
    if (!isSegmentGenerating.value && !isGeneratingScript.value && sceneContent.value.trim()) {
      scriptStreamStatus.value = ''
    }
  }
}

async function _handleRegenerateConfirmationStep(payload?: { stepId?: string }) {
  if (payload?.stepId === 'candidate_save') {
    await runSegmentedWritingWithEpisode({ forceRegenerateCurrentDraft: true })
    return
  }
  await runSegmentedWritingWithEpisode()
}

function _candidateSaveSegmentConfirmIndex() {
  const activeSegmentIdx = Number(currentSegmentIdx.value ?? -1)
  const activeStep = segmentSteps.value[activeSegmentIdx]
  if (
    activeSegmentIdx >= 0
    && activeStep
    && (activeStep.status === 'reviewing' || activeStep.status === 'generating')
  ) {
    return activeSegmentIdx
  }
  return segmentSteps.value.findIndex(step => step.status === 'reviewing' || step.status === 'generating')
}

async function _recoverEmptySegmentCandidateForIndex(segmentIdx: number) {
  const step = segmentSteps.value[segmentIdx]
  if (!step) return false
  if (step.editedContent.trim() || step.versionA.trim() || step.versionB.trim()) return false
  if (step.status !== 'reviewing' && step.status !== 'generating') return false
  const recovered = await recoverLatestCandidateForSegment(segmentIdx)
  if (recovered) {
    await _persistCurrentSegmentProgress({ immediate: true })
  }
  return recovered
}

async function _confirmSegmentCandidateBeforeStepSave() {
  const segmentIdx = _candidateSaveSegmentConfirmIndex()
  if (segmentIdx < 0) return false
  await _recoverEmptySegmentCandidateForIndex(segmentIdx)
  if (!_ensureActiveSegmentActionTarget(segmentIdx, '确认候选并保存')) return true
  await segmentConfirm(segmentIdx)
  return true
}

async function _handleStepCandidateSave() {
  if (await _confirmSegmentCandidateBeforeStepSave()) {
    return
  }
  await persistCurrentScriptContent({
    silent: false,
    changeNote: '确认候选并保存',
    editorType: 'human',
    c19_178_materialization: true,
    recordManualEdit: true,
    requireNonEmptyContent: true,
  })
}

async function _handleSegmentRetry(idx: number) {
  if (!_ensureActiveSegmentActionTarget(idx, '重新生成')) return
  await segmentRetry(idx)
}

async function _handleSegmentConfirm(idx: number) {
  if (!_ensureActiveSegmentActionTarget(idx, '确认当前段')) return
  await segmentConfirm(idx)
}

async function _handleSegmentGenerateVariant(idx: number) {
  if (!_ensureActiveSegmentActionTarget(idx, '生成B版')) return
  await segmentGenerateVariant(idx)
}

async function prepareNextEpisodeForWriting() {
  const nextEp = Number(selectedEpisode.value || 1) + 1
  const totalEpisodes = _effectiveUserConfirmedTotalEpisodes()
  if (!totalEpisodes) {
    toast.warning('请先确认总集数；确认后才能生成下一集。')
    return
  }
  if (nextEp > totalEpisodes) {
    toast.error('已经是最后一集，不能继续生成下一集')
    return
  }
  if (isGeneratingScript.value || isSegmentGenerating.value || isGeneratingNextEpisode.value) return

  isGeneratingNextEpisode.value = true
  try {
    const saved = await persistCurrentScriptContent({
      silent: false,
      changeNote: '进入下一集前保存',
      editorType: 'human',
      recordManualEdit: true,
      requireNonEmptyContent: true,
    })
    if (!saved) return
    await _refreshSeriesSimulationPacket('script_generation_preflight', { silent: true })
    if (!ensureOutlineGatePassed({ episodeLimit: nextEp })) return
    const ready = await ensureScriptEpisodeReady(nextEp)
    if (!ready) return
    await runSegmentedWritingWithEpisode()
  } finally {
    isGeneratingNextEpisode.value = false
  }
}

async function runNextEpisodeSegmentedWriting() {
  await prepareNextEpisodeForWriting()
}

// 新建场（在当前集里追加一个空场景）
async function createScene() {
  isCreatingScene.value = true
  try {
    await projectsV2Api.createScene(projectId.value, selectedEpisode.value, {
      time: '',
      location_type: 'INT',
      location_name: '待填写',
      content: ''
    })
    const nextNum = scenes.value.length > 0
      ? Math.max(...scenes.value.map((s: any) => s.scene_number)) + 1
      : 1
    toast.success(`第${nextNum}场已创建`)
    await loadScenes(selectedEpisode.value)
    // 跳到新场
    const last = scenes.value[scenes.value.length - 1]
    if (last) { selectedScene.value = last.scene_number; sceneContent.value = ''; _markSceneContentClean('') }
  } catch (e: any) {
    notifyApiError(toast.error, e, '创建场景失败')
  } finally {
    isCreatingScene.value = false
  }
}

// 当前选集的已有原始剧本（来自大纲导入）
const currentEpExistingScript = computed(() => {
  const ep = outlineData.value.episodes.find(e => Number(e.ep) === Number(selectedEpisode.value))
  return ep?.existing_script?.trim() || ''
})

function _existingScriptForEpisode(episodeNumber = selectedEpisode.value) {
  const targetEp = Math.max(1, Math.round(Number(episodeNumber || 1) || 1))
  const ep = outlineData.value.episodes.find((item: any) => Number(item?.ep || 0) === targetEp)
  return String(ep?.existing_script || '').trim()
}

function _existingScriptOptOutStore() {
  const raw = (workflowContext.value as any).existing_script_opt_out
  return raw && typeof raw === 'object' && !Array.isArray(raw) ? raw as Record<string, any> : {}
}

function _existingScriptOptOutKey(episodeNumber = selectedEpisode.value) {
  return String(Math.max(1, Math.round(Number(episodeNumber || 1) || 1)))
}

function _isExistingScriptOptedOut(episodeNumber = selectedEpisode.value) {
  const key = _existingScriptOptOutKey(episodeNumber)
  return Boolean(_existingScriptOptOutStore()[key])
}

function _markExistingScriptOptOut(episodeNumber = selectedEpisode.value, reason = 'user_cleared_imported_script') {
  const targetEp = Math.max(1, Math.round(Number(episodeNumber || 1) || 1))
  if (!_existingScriptForEpisode(targetEp)) return false
  const key = _existingScriptOptOutKey(targetEp)
  const store = {
    ..._existingScriptOptOutStore(),
    [key]: {
      episode_no: targetEp,
      reason,
      updated_at: new Date().toISOString(),
    },
  }
  workflowContext.value = normalizeWorkflowContext(_deepMergeRecord(workflowContext.value, {
    existing_script_opt_out: store,
  }))
  return true
}

function _clearExistingScriptOptOut(episodeNumber = selectedEpisode.value) {
  const key = _existingScriptOptOutKey(episodeNumber)
  const store = { ..._existingScriptOptOutStore() }
  if (!store[key]) return false
  delete store[key]
  workflowContext.value = normalizeWorkflowContext(_deepMergeRecord(workflowContext.value, {
    existing_script_opt_out: store,
  }))
  return true
}

function _segmentProgressHasDraft(progress: Record<string, any>) {
  const steps = Array.isArray(progress.steps) ? progress.steps : []
  return steps.some((step: any) => {
    const status = String(step?.status || 'pending')
    return status !== 'pending'
      || Boolean(String(step?.versionA || '').trim())
      || Boolean(String(step?.versionB || '').trim())
      || Boolean(String(step?.editedContent || '').trim())
  })
}

function _clearBlankEpisodeSegmentProgress(episodeNumber = selectedEpisode.value, reason = 'user_blank_episode_generation') {
  const targetEp = Math.max(1, Math.round(Number(episodeNumber || 1) || 1))
  const key = _scriptSegmentProgressKey(targetEp)
  const store = _scriptSegmentProgressStore()
  const progress = store[key]
  if (!progress || typeof progress !== 'object' || Array.isArray(progress)) return false
  if (_segmentProgressHasDraft(progress)) return false

  const savedContent = String(progress.scene_content || '')
  const savedHash = String(progress.content_hash || '')
  if (!savedContent.trim() && savedHash === simpleHash('')) return false

  workflowContext.value = normalizeWorkflowContext(_deepMergeRecord(workflowContext.value, {
    script_segment_progress: {
      ...store,
      [key]: {
        ...progress,
        scene_content: '',
        content_hash: simpleHash(''),
        blank_generation_reason: reason,
        updated_at: new Date().toISOString(),
      },
    },
  }))
  return true
}

function _clearCompletedEpisodeSegmentProgress(episodeNumber = selectedEpisode.value, reason = 'internal_segmented_episode_completed') {
  const targetEp = Math.max(1, Math.round(Number(episodeNumber || 1) || 1))
  const key = _scriptSegmentProgressKey(targetEp)
  const store = _scriptSegmentProgressStore()
  if (!Object.prototype.hasOwnProperty.call(store, key)) return false

  workflowContext.value = normalizeWorkflowContext(_deepMergeRecord(workflowContext.value, {
    script_segment_progress: {
      ...store,
      [key]: {
        episode_no: targetEp,
        scene_no: Math.max(1, Math.round(Number(selectedScene.value || 1) || 1)),
        has_progress: false,
        current_segment_idx: -1,
        show_panel: false,
        steps: [],
        scene_content: '',
        content_hash: simpleHash(''),
        completed_generation_reason: reason,
        updated_at: new Date().toISOString(),
      },
    },
  }))
  return true
}

function _markConfirmedEpisodeDraftCompletionRecovered(
  episodeNumber = selectedEpisode.value,
  sceneNumber = selectedScene.value,
  contentVersionId = '',
) {
  const targetEp = Math.max(1, Math.round(Number(episodeNumber || 1) || 1))
  const key = _scriptSegmentProgressKey(targetEp)
  const store = _scriptSegmentProgressStore()
  const progress = store[key]
  if (!progress || typeof progress !== 'object' || Array.isArray(progress)) return false

  workflowContext.value = normalizeWorkflowContext(_deepMergeRecord(workflowContext.value, {
    script_segment_progress: {
      ...store,
      [key]: {
        ...progress,
        draft_completion_close_status: 'completed',
        draft_completion_closed_at: new Date().toISOString(),
        draft_completion_scene_no: Math.max(1, Math.round(Number(sceneNumber || 1) || 1)),
        draft_completion_content_version_id: String(contentVersionId || ''),
      },
    },
  }))
  return true
}

async function _markExistingScriptOptOutIfEditorBlank(episodeNumber = selectedEpisode.value) {
  if (Number(selectedEpisode.value) !== Number(episodeNumber)) return false
  if (String(sceneContent.value || '').trim()) return false
  const marked = _markExistingScriptOptOut(episodeNumber, 'user_started_rewrite_from_blank')
  const cleared = _clearBlankEpisodeSegmentProgress(episodeNumber, 'user_started_rewrite_from_blank')
  if (marked || cleared) {
    await _syncProjectWorkflowContext({ immediate: true, silent: true })
  }
  return marked || cleared
}

// 加载大纲中已有的原始剧本到编辑器
async function loadExistingScript() {
  const script = currentEpExistingScript.value
  if (!script) return
  if (sceneContent.value.trim() && !confirm('编辑区已有内容，确认替换为大纲原稿？')) return
  _clearExistingScriptOptOut(selectedEpisode.value)
  sceneContent.value = script
  const saved = await persistCurrentScriptContent({
    silent: true,
    changeNote: '手动加载大纲原稿',
    editorType: 'human',
  })
  if (saved) {
    toast.success('已加载并保存大纲原稿，可按当前科研生成链路继续优化升级')
  } else {
    toast.error('大纲原稿已显示，但保存失败，请点击保存后再继续')
  }
}

const outlineExistingScriptSeedSignature = ref('')

function _outlineExistingScriptSeedSignature() {
  return outlineData.value.episodes
    .map((ep: any) => {
      const epNo = Math.max(1, Math.round(Number(ep?.ep) || 0))
      const script = String(ep?.existing_script || '').trim()
      if (!epNo || !script) return ''
      let hash = 0
      for (let i = 0; i < script.length; i += 1) {
        hash = ((hash << 5) - hash + script.charCodeAt(i)) | 0
      }
      return `${epNo}:${script.length}:${hash}`
    })
    .filter(Boolean)
    .join('|')
}

async function ensureOutlineExistingScriptsSeeded(options?: { silent?: boolean }) {
  const signature = _outlineExistingScriptSeedSignature()
  if (!signature || outlineExistingScriptSeedSignature.value === signature) return 0
  const seeded = await _seedExistingScriptsFromOutline()
  outlineExistingScriptSeedSignature.value = signature
  if (seeded && !options?.silent) {
    toast.success(`已把大纲原稿导入 ${seeded} 集正文`)
  }
  return seeded
}

function _isPlaceholderScriptContent(content: string) {
  const text = String(content || '').trim()
  if (!text) return true
  return /^开始写作(这个场景|这一集)/.test(text)
    || /^点击上方新建第?\d*集/.test(text)
    || text === '请先编写剧本'
}

function _isEpisodeAlreadyExistsError(error: any) {
  const status = Number(error?.response?.status || 0)
  const detail = String(error?.response?.data?.detail || '')
  return status === 409 || (status === 400 && detail.includes('集已存在'))
}

async function _seedExistingScriptsFromOutline() {
  const items = outlineData.value.episodes
    .map((ep: any) => ({
      ep: Math.max(1, Math.round(Number(ep.ep) || 0)),
      title: String(ep.title || '').trim(),
      summary: String(ep.summary || '').trim(),
      script: String(ep.existing_script || '').trim(),
    }))
    .filter(item => item.ep > 0 && item.script && !_isExistingScriptOptedOut(item.ep))
  if (!items.length) return 0

  let seeded = 0
  for (const item of items) {
    try {
      let episodeScenes: any[] = []
      let episodeMissing = false
      try {
        const { data } = await projectsV2Api.listScenes(projectId.value, item.ep)
        episodeScenes = Array.isArray(data) ? data : []
      } catch (e: any) {
        if (e?.response?.status === 404) {
          episodeMissing = true
        } else {
          throw e
        }
      }

      if (episodeMissing) {
        try {
          await projectsV2Api.createEpisode(projectId.value, {
            title: item.title || `第${item.ep}集`,
            summary: item.summary || '原稿正文已从大纲导入',
            status: 'draft',
          }, item.ep)
        } catch (e: any) {
          if (!_isEpisodeAlreadyExistsError(e)) throw e
        }
      }

      episodeScenes.sort((a, b) => Number(a.scene_number || 0) - Number(b.scene_number || 0))
      let sceneNo = Number(episodeScenes[0]?.scene_number || 1)
      if (!episodeScenes.length) {
        const { data } = await projectsV2Api.createScene(projectId.value, item.ep, {
          time: '',
          location_type: 'INT',
          location_name: '原稿导入',
          content: '',
        })
        sceneNo = Number(data?.scene_number || 1)
      } else if (!_isPlaceholderScriptContent(String(episodeScenes[0]?.content || ''))) {
        continue
      }

      await projectsV2Api.saveSceneContent(projectId.value, item.ep, sceneNo, {
        content: item.script,
        editor_type: 'human',
        change_note: '大纲原文导入正文',
      })
      _invalidateScenesCache(item.ep)
      seeded += 1
    } catch (e) {
      console.warn('seed existing script from outline failed', e)
    }
  }
  if (seeded) {
    await loadEpisodes()
    if (items.some(item => item.ep === selectedEpisode.value)) {
      await loadScenes(selectedEpisode.value)
    }
  }
  return seeded
}

async function ensureCurrentEpisodeExistingScriptVisible(targetEpisode?: number, options?: { silent?: boolean }) {
  const targetEp = Math.max(1, Math.round(Number(targetEpisode ?? selectedEpisode.value) || 1))
  const ep = outlineData.value.episodes.find((item: any) => Number(item?.ep || 0) === targetEp)
  const script = String(ep?.existing_script || '').trim()
  if (!script) return false
  if (_isExistingScriptOptedOut(targetEp)) return false
  if (Number(selectedEpisode.value) !== targetEp) return false
  if (!_isPlaceholderScriptContent(sceneContent.value)) return false

  let sceneNo = Math.max(1, Math.round(Number(selectedScene.value || 1) || 1))
  const sorted = [...scenes.value].sort((a, b) => Number(a.scene_number || 0) - Number(b.scene_number || 0))
  if (sorted[0]?.scene_number) {
    sceneNo = Math.max(1, Math.round(Number(sorted[0].scene_number) || 1))
    selectedScene.value = sceneNo
  } else {
    try {
      const { data } = await projectsV2Api.createScene(projectId.value, targetEp, {
        time: '',
        location_type: 'INT',
        location_name: '原稿导入',
        content: '',
      })
      sceneNo = Math.max(1, Math.round(Number(data?.scene_number || 1) || 1))
      selectedScene.value = sceneNo
    } catch (e: any) {
      if (e?.response?.status !== 409) throw e
    }
  }

  sceneContent.value = script
  await projectsV2Api.saveSceneContent(projectId.value, targetEp, sceneNo, {
    content: script,
    editor_type: 'human',
    change_note: '大纲原文导入正文',
  })
  _markSceneContentClean(script)
  _invalidateScenesCache(targetEp)
  _touchManualEditSnapshot(targetEp, sceneNo, script)
  await _syncProjectWorkflowContext({ immediate: true, silent: true })
  if (!options?.silent) {
    toast.success('已把大纲原稿带入本集写作区')
  }
  return true
}

async function persistCurrentScriptContent(options?: {
  silent?: boolean
  changeNote?: string
  editorType?: 'human' | 'ai'
  c19_178_materialization?: boolean
  recordManualEdit?: boolean
  requireNonEmptyContent?: boolean
  targetEpisodeNo?: number
  targetSceneNo?: number
  contentOverride?: string
  skipEpisodeReadyCheck?: boolean
}) {
  const snapshotEp = _normalizeEpisodeNo(options?.targetEpisodeNo ?? selectedEpisode.value)
  let snapshotScene = _normalizeSceneNo(options?.targetSceneNo ?? selectedScene.value)
  const snapshotContent = String(options?.contentOverride ?? sceneContent.value ?? '')
  const previousManualSnapshot = _manualEditSnapshot(snapshotEp, snapshotScene)
  if (!options?.skipEpisodeReadyCheck && !isPreparingScriptPersistence) {
    isPreparingScriptPersistence = true
    try {
      if (!(await ensureScriptEpisodeReady(snapshotEp))) {
        return false
      }
    } finally {
      isPreparingScriptPersistence = false
    }
  }
  if (options?.requireNonEmptyContent && !snapshotContent.trim()) {
    if (!options?.silent) {
      toast.error('候选正文为空，不能保存为下一集承接正史。请先生成或手动填写正文。')
    }
    return false
  }
  if (!snapshotContent.trim()) {
    _markExistingScriptOptOut(snapshotEp, 'user_saved_blank_over_imported_script')
    _clearBlankEpisodeSegmentProgress(snapshotEp, 'user_saved_blank_over_imported_script')
  }

  const shouldRecordManualEdit = options?.recordManualEdit ?? (options?.editorType || 'human') === 'human'
  const manualEditEvidence = shouldRecordManualEdit
    ? _buildManualEditEvidenceForSave(snapshotEp, snapshotScene, snapshotContent, previousManualSnapshot)
    : undefined

  const savePayload = {
    content: snapshotContent,
    editor_type: options?.editorType || 'human',
    change_note: options?.changeNote || '自动保存',
    ...(options?.c19_178_materialization ? { c19_178_materialization: true } : {}),
    ...(manualEditEvidence ? { manual_edit_evidence: manualEditEvidence } : {}),
  }

  try {
    try {
      await projectsV2Api.saveSceneContent(projectId.value, snapshotEp, snapshotScene, savePayload)
    } catch (e: any) {
      if (e?.response?.status !== 404) throw e
      const { data } = await projectsV2Api.createScene(projectId.value, snapshotEp, {
        time: '',
        location_type: 'INT',
        location_name: '待填写',
        content: '',
      })
      snapshotScene = Math.max(1, Math.round(Number(data?.scene_number || snapshotScene) || snapshotScene))
      if (Number(selectedEpisode.value) === snapshotEp) {
        selectedScene.value = snapshotScene
      }
      await projectsV2Api.saveSceneContent(projectId.value, snapshotEp, snapshotScene, savePayload)
    }

    if (Number(selectedEpisode.value) === snapshotEp && sceneContent.value === snapshotContent) {
      _markSceneContentClean(snapshotContent)
    }
    const confirmedCandidate = _markModelCandidateSnapshotConfirmed(snapshotEp, snapshotScene, snapshotContent)
    if (confirmedCandidate) _clearCandidatePendingStatusAfterSave()
    _invalidateScenesCache(snapshotEp)
    void refreshEpisodesSilently()
    const manualEditBeforeSaveRecord = workflowContext.value.manual_edit_context || {}
    const consumedManualEditContext = markManualEditGateConsumed(manualEditBeforeSaveRecord, snapshotEp, {
      generated_content_hash: simpleHash(snapshotContent),
      generated_at: new Date().toISOString(),
    })
    if (JSON.stringify(consumedManualEditContext) !== JSON.stringify(manualEditBeforeSaveRecord)) {
      _setManualEditContext(consumedManualEditContext)
    }
    if (shouldRecordManualEdit) {
      _recordManualEditContext(
        snapshotEp,
        snapshotScene,
        snapshotContent,
        options?.changeNote || '手动编辑',
        previousManualSnapshot,
      )
    } else {
      _touchManualEditSnapshot(snapshotEp, snapshotScene, snapshotContent)
    }
    const workflowSynced = await _syncProjectWorkflowContext({ immediate: true, silent: true })
    if (!workflowSynced && shouldRecordManualEdit) {
      _markManualEditSyncFailed(snapshotEp, snapshotScene, snapshotContent)
      if (!options?.silent) {
        toast.error('正文已保存，但用户改稿正史同步失败。请再点一次保存，确认后再生成下一集。')
      }
      return false
    }
    if (!options?.silent) toast.success('保存成功')
    return true
  } catch (e: any) {
    if (!options?.silent) {
      notifyApiError(toast.error, e, '保存失败')
    }
    return false
  }
}

async function saveScript() {
  isSavingScript.value = true
  try {
    await persistCurrentScriptContent({
      silent: false,
      changeNote: '手动编辑',
      editorType: 'human',
      recordManualEdit: true,
    })
  } finally {
    isSavingScript.value = false
  }
}

function _appendRuleProfileTag(rawProfile: unknown, tag: string) {
  const profile = String(rawProfile || '').trim()
  if (!profile) return tag
  if (profile.split(/[,\s|/]+/).includes(tag)) return profile
  return `${profile}|${tag}`
}

function _buildQuickWriteIssueFeedback() {
  const base = workflowContext.value.issue_feedback && typeof workflowContext.value.issue_feedback === 'object'
    ? workflowContext.value.issue_feedback as Record<string, any>
    : {}
  const reviewFocus = Array.isArray(base.review_focus) ? base.review_focus : []
  const negativeHints = Array.isArray(base.negative_prompt_hints) ? base.negative_prompt_hints : []
  return {
    ...base,
    summary: [
      String(base.summary || '').trim(),
      quickWriteTakeoverMode.value
        ? '主链路接管模式：用户已在内部审段中产生部分正文，本轮必须紧接当前正文继续写后续剧情，不能重写已完成内容。'
        : '',
      '科研链路：按分步确认和最终生成合同写当前集；如果当前集已有正文，就紧接现有正文继续写，不重写前文。正文内部可以自然包含多场戏和多个场标；必须落实蓝图、四段任务卡、人物关系、冲突推进和结尾悬点。',
    ].filter(Boolean).join('；'),
    review_focus: [
      ...reviewFocus,
      '输出必须是当前集可继续编辑的正文候选，不要只给提纲、分析或后台计划。',
      '优先保证本集事件连续、角色关系不跳、场景可拍，并承接用户定稿正史。',
    ].slice(0, 6),
    negative_prompt_hints: [
      ...negativeHints,
      '不要输出后台分析说明。',
      '不要一次生成 A/B 双版本。',
    ].slice(0, 6),
  }
}

function _hasSegmentedWritingProgress() {
  if (!showSegmentPanel.value && segmentSteps.value.length > 0 && segmentSteps.value.every(step => step.status === 'confirmed')) {
    return false
  }
  return segmentSteps.value.some(step => {
    return step.status !== 'pending'
      || Boolean(step.versionA || step.versionB || step.editedContent.trim())
  })
}

function _hasStoredIncompleteSegmentProgress(episodeNumber = selectedEpisode.value) {
  const progress = _scriptSegmentProgressStore()[_scriptSegmentProgressKey(episodeNumber)]
  if (!progress || typeof progress !== 'object' || Array.isArray(progress)) return false
  if (String(progress.draft_completion_close_status || '') === 'completed') return false
  const steps = Array.isArray(progress.steps) ? progress.steps : []
  if (!steps.length) return false
  return steps.some((step: any) => {
    const status = String(step?.status || '')
    const hasDraft = Boolean(String(step?.editedContent || step?.versionA || step?.versionB || '').trim())
    return status !== 'confirmed' || !hasDraft
  })
}

const isSegmentedDraftIncomplete = computed(() => {
  const liveIncomplete = _hasSegmentedWritingProgress() && !segmentSteps.value.every(step => step.status === 'confirmed')
  return liveIncomplete || _hasStoredIncompleteSegmentProgress(selectedEpisode.value)
})
const currentEpisodeOfficiallyLocked = computed(() => {
  const lockedEpisodes = Math.max(0, Number(collaborationSummary.value?.locked_episodes || 0))
  return lockedEpisodes >= Number(selectedEpisode.value || 1)
})
const currentEpisodeNeedsDraftCompletionRecovery = computed(() => {
  if (currentEpisodeOfficiallyLocked.value) return false
  if (!sceneContent.value.trim()) return false
  const progress = _scriptSegmentProgressStore()[_scriptSegmentProgressKey(selectedEpisode.value)]
  if (!progress || typeof progress !== 'object' || Array.isArray(progress)) return false
  if (String(progress.draft_completion_close_status || '') === 'completed') return false
  const steps = Array.isArray(progress.steps) ? progress.steps : []
  return steps.length > 0 && steps.every((step: any) => String(step?.status || '') === 'confirmed')
})
const canLockCurrentEpisode = computed(() => {
  return Boolean(sceneContent.value.trim())
    && !isGeneratingScript.value
    && !isSegmentGenerating.value
    && !isSegmentedDraftIncomplete.value
    && !currentEpisodeOfficiallyLocked.value
})

type LockTraceGuardName =
  | 'already_locked'
  | 'generating_script'
  | 'segment_generating'
  | 'generating_next_episode'
  | 'segmented_incomplete'
  | 'empty_content'
  | 'missing_project_or_episode'
  | 'draft_completion_recovery_required'
  | 'other_safe_guard'

function _recordLockTrace(
  label: string,
  extra: Record<string, boolean | number | string | null | undefined> = {},
) {
  const payload = {
    label,
    ts: new Date().toISOString(),
    selectedEpisode: Number(selectedEpisode.value || 0) || 0,
    content_length: String(sceneContent.value || '').trim().length,
    locked_episodes_count: Math.max(0, Number(collaborationSummary.value?.locked_episodes || 0)),
    is_generating_script: Boolean(isGeneratingScript.value),
    is_segment_generating: Boolean(isSegmentGenerating.value),
    is_generating_next_episode: Boolean(isGeneratingNextEpisode.value),
    is_segmented_draft_incomplete: Boolean(isSegmentedDraftIncomplete.value),
    current_episode_officially_locked: Boolean(currentEpisodeOfficiallyLocked.value),
    ...extra,
  }
  console.info('[LOCK_TRACE]', JSON.stringify(payload))
  const runtime = window as typeof window & { __moxiLockTrace?: Array<typeof payload> }
  const trace = Array.isArray(runtime.__moxiLockTrace) ? runtime.__moxiLockTrace : []
  trace.push(payload)
  runtime.__moxiLockTrace = trace
}

function _classifyLockTraceError(error: unknown) {
  const maybeObject = error && typeof error === 'object' ? (error as Record<string, any>) : {}
  const response = maybeObject.response && typeof maybeObject.response === 'object'
    ? (maybeObject.response as Record<string, any>)
    : {}
  const status = Number(response.status ?? maybeObject.status ?? 0) || 0
  if (status === 401 || status === 403) return 'auth_or_permission'
  if (status === 404) return 'not_found'
  if (status >= 500) return 'server_error'
  if (status > 0) return 'request_error'
  if (String(maybeObject.name || '') === 'TypeError') return 'runtime_type_error'
  return 'runtime_or_network_error'
}

function _prepareSegmentedProgressForQuickWrite() {
  const current = currentSegmentStep.value
  if (current?.editMode) {
    segmentExitEdit(current)
  }
  const confirmedContent = confirmedSegmentContent().trim()
  if (!sceneContent.value.trim() && confirmedContent) {
    sceneContent.value = confirmedContent
  }
  showSegmentPanel.value = false
}
// 剧本写作：角色图谱显示控制
const showFloatingGraph = ref(false)
const floatGraphPos = ref({ x: 0, y: 80 })
const floatGraphDragging = ref(false)

function startFloatGraphDrag(e: MouseEvent) {
  const startX = e.clientX - floatGraphPos.value.x
  const startY = e.clientY - floatGraphPos.value.y
  floatGraphDragging.value = true
  const onMove = (ev: MouseEvent) => {
    floatGraphPos.value = {
      x: Math.max(0, Math.min(window.innerWidth - 480, ev.clientX - startX)),
      y: Math.max(0, Math.min(window.innerHeight - 420, ev.clientY - startY)),
    }
  }
  const onUp = () => {
    floatGraphDragging.value = false
    window.removeEventListener('mousemove', onMove)
    window.removeEventListener('mouseup', onUp)
  }
  window.addEventListener('mousemove', onMove)
  window.addEventListener('mouseup', onUp)
}

function openFloatingGraph() {
  if (!showFloatingGraph.value) {
    // Default position: top-right corner offset from viewport
    floatGraphPos.value = { x: Math.max(0, window.innerWidth - 520), y: 80 }
    showFloatingGraph.value = true
  }
}

const autoSceneCharacterIds = ref<string[]>([])
const manualSceneCharacterIds = ref<string[]>([])
const scriptSceneCharacters = computed(() => Array.from(new Set([
  ...autoSceneCharacterIds.value,
  ...manualSceneCharacterIds.value,
]))) // 当前场景出场角色ID

function _syncAutoSceneCharacterIds(ids: string[]) {
  const next = Array.from(new Set(ids.map(id => String(id)).filter(Boolean)))
  const same = next.length === autoSceneCharacterIds.value.length
    && next.every((id, index) => autoSceneCharacterIds.value[index] === id)
  if (!same) autoSceneCharacterIds.value = next
}

// 状态卡 CRUD：现在 scriptSceneCharacters 已就绪，挂载 composable。
const {
  addStoryStateCard,
  upsertStoryStateCard,
  removeStoryStateCard,
  toggleStateCardCharacter,
} = useStoryStateCards({
  storyStateCards,
  sceneCharacterIds: scriptSceneCharacters,
  dismissedSuggestionKeys: dismissedStateCardSuggestionKeys,
})

const scriptRightTab = ref<'graph' | 'health'>('graph') // 右侧面板 tab
const isValidatingScriptRules = ref(false)
const isAutoFixingScript = ref(false)
const dismissedRelationshipSuggestionKeys = ref<string[]>([])
function _emptyBenchmarkAssessment() {
  return {
    track_name: '',
    score: 0,
    passed: false,
    summary: '',
    matched_signals: [] as string[],
    gaps: [] as string[],
    rule_upgrades: [] as string[],
  }
}

function _emptyContinuityAssessment() {
  return {
    checked_episode_span: '',
    score: 0,
    passed: false,
    summary: '',
    preserved_anchors: [] as string[],
    relationship_risks: [] as string[],
    plot_risks: [] as string[],
  }
}

interface ScriptRuleValidationState {
  char_count_excluding_punctuation: number
  warnings: string[]
  blocking_issues: string[]
  present_character_ids: string[]
  health_items: Array<Record<string, any>>
  relationship_suggestions: Array<Record<string, any>>
  state_card_suggestions: Array<Record<string, any>>
  failure_analysis: Record<string, any>
  episode_memory_card: Record<string, any>
  canon_packet: Record<string, any>
}

interface ScriptDeepAuditState {
  benchmark_assessment: ReturnType<typeof _emptyBenchmarkAssessment>
  continuity_assessment: ReturnType<typeof _emptyContinuityAssessment>
}


function _emptyScriptRuleValidation(): ScriptRuleValidationState {
  return {
    char_count_excluding_punctuation: 0,
    warnings: [],
    blocking_issues: [],
    present_character_ids: [],
    health_items: [],
    relationship_suggestions: [],
    state_card_suggestions: [],
    failure_analysis: {},
    episode_memory_card: {},
    canon_packet: {},
  }
}

function _emptyScriptDeepAudit(): ScriptDeepAuditState {
  return {
    benchmark_assessment: _emptyBenchmarkAssessment(),
    continuity_assessment: _emptyContinuityAssessment(),
  }
}

function _deepMergeRecord<T extends Record<string, any>>(base: T, patch?: Record<string, any> | null): T {
  const next = clonePlain(base)
  if (!patch || typeof patch !== 'object') return next
  Object.entries(patch).forEach(([key, value]) => {
    if (Array.isArray(value)) {
      ;(next as any)[key] = [...value]
      return
    }
    if (value && typeof value === 'object' && !Array.isArray(value) && (next as any)[key] && typeof (next as any)[key] === 'object' && !Array.isArray((next as any)[key])) {
      ;(next as any)[key] = _deepMergeRecord((next as any)[key], value as Record<string, any>)
      return
    }
    ;(next as any)[key] = value
  })
  return next
}

function _normalizeCanonPacket(raw?: any) {
  if (!raw || typeof raw !== 'object') return {}
  const base = {
    premise: '',
    hard_constraints: [] as string[],
    relationship_limits: [] as string[],
    information_schedule: [] as string[],
    locked_facts: [] as string[],
    timeline_anchors: [] as string[],
    last_updated_episode: 0,
    notes: '',
  }
  const normalized = {
    ...base,
    premise: String(raw.premise || '').trim(),
    hard_constraints: Array.isArray(raw.hard_constraints) ? raw.hard_constraints.map((item: any) => String(item || '').trim()).filter(Boolean) : [],
    relationship_limits: Array.isArray(raw.relationship_limits) ? raw.relationship_limits.map((item: any) => String(item || '').trim()).filter(Boolean) : [],
    information_schedule: Array.isArray(raw.information_schedule) ? raw.information_schedule.map((item: any) => String(item || '').trim()).filter(Boolean) : [],
    locked_facts: Array.isArray(raw.locked_facts) ? raw.locked_facts.map((item: any) => String(item || '').trim()).filter(Boolean) : [],
    timeline_anchors: Array.isArray(raw.timeline_anchors) ? raw.timeline_anchors.map((item: any) => String(item || '').trim()).filter(Boolean) : [],
    last_updated_episode: Number(raw.last_updated_episode || 0) || 0,
    notes: String(raw.notes || '').trim(),
  }
  return Object.entries(raw).reduce((acc, [key, value]) => {
    if (!(key in normalized)) (acc as any)[key] = value
    return acc
  }, normalized as Record<string, any>)
}

function _normalizeEpisodeMemoryCards(raw?: any) {
  if (!Array.isArray(raw)) return [] as Array<Record<string, any>>
  const normalized: Array<Record<string, any>> = raw.map((item: any) => {
    const episodeNo = Number(item?.episode_no || item?.ep || 0) || 0
    if (episodeNo <= 0) return null
    return {
      episode_no: episodeNo,
      title: String(item?.title || '').trim(),
      summary: String(item?.summary || '').trim(),
      opening_state: String(item?.opening_state || '').trim(),
      ending_state: String(item?.ending_state || '').trim(),
      relationship_delta: Array.isArray(item?.relationship_delta) ? item.relationship_delta.map((value: any) => String(value || '').trim()).filter(Boolean) : [],
      information_delta: Array.isArray(item?.information_delta) ? item.information_delta.map((value: any) => String(value || '').trim()).filter(Boolean) : [],
      power_delta: Array.isArray(item?.power_delta) ? item.power_delta.map((value: any) => String(value || '').trim()).filter(Boolean) : [],
      unresolved_hooks: Array.isArray(item?.unresolved_hooks) ? item.unresolved_hooks.map((value: any) => String(value || '').trim()).filter(Boolean) : [],
      spoiler_guard: Array.isArray(item?.spoiler_guard) ? item.spoiler_guard.map((value: any) => String(value || '').trim()).filter(Boolean) : [],
      body_excerpt: String(item?.body_excerpt || item?.actual_progress || '').trim(),
      quality_summary: String(item?.quality_summary || '').trim(),
    }
  }).filter((item: Record<string, any> | null): item is Record<string, any> => Boolean(item)) as Array<Record<string, any>>
  return normalized.sort((a, b) => Number(a.episode_no || 0) - Number(b.episode_no || 0))
}

function _normalizeEpisodeMemoryCard(raw?: any) {
  return _normalizeEpisodeMemoryCards(raw ? [raw] : [])[0] || {}
}

function _mergeEpisodeMemoryCards(existing: Array<Record<string, any>>, incoming: Array<Record<string, any>>) {
  const merged = new Map<number, Record<string, any>>()
  _normalizeEpisodeMemoryCards(existing).forEach((item) => {
    merged.set(Number(item.episode_no || 0), item)
  })
  _normalizeEpisodeMemoryCards(incoming).forEach((item) => {
    merged.set(Number(item.episode_no || 0), item)
  })
  return Array.from(merged.entries())
    .sort((a, b) => a[0] - b[0])
    .map(([, value]) => value)
}

function _normalizeScriptRuleValidation(raw?: any): ScriptRuleValidationState {
  const base = _emptyScriptRuleValidation()
  if (!raw || typeof raw !== 'object') return base
  return {
    char_count_excluding_punctuation: Number(raw.char_count_excluding_punctuation || 0),
    warnings: Array.isArray(raw.warnings) ? raw.warnings.map((item: any) => String(item || '')).filter(Boolean) : [],
    blocking_issues: Array.isArray(raw.blocking_issues) ? raw.blocking_issues.map((item: any) => String(item || '')).filter(Boolean) : [],
    present_character_ids: Array.isArray(raw.present_character_ids) ? raw.present_character_ids.map((item: any) => String(item || '')).filter(Boolean) : [],
    health_items: Array.isArray(raw.health_items) ? raw.health_items : [],
    relationship_suggestions: Array.isArray(raw.relationship_suggestions) ? raw.relationship_suggestions : [],
    state_card_suggestions: Array.isArray(raw.state_card_suggestions) ? raw.state_card_suggestions : [],
    failure_analysis: raw.failure_analysis && typeof raw.failure_analysis === 'object' ? raw.failure_analysis : {},
    episode_memory_card: _normalizeEpisodeMemoryCard(raw.episode_memory_card),
    canon_packet: _normalizeCanonPacket(raw.canon_packet),
  }
}

function _normalizeScriptDeepAudit(raw?: any): ScriptDeepAuditState {
  return {
    benchmark_assessment: {
      ..._emptyBenchmarkAssessment(),
      ...((raw && typeof raw === 'object' ? raw.benchmark_assessment : null) || {}),
    },
    continuity_assessment: {
      ..._emptyContinuityAssessment(),
      ...((raw && typeof raw === 'object' ? raw.continuity_assessment : null) || {}),
    },
  }
}

const scriptRuleValidation = ref<ScriptRuleValidationState>(_emptyScriptRuleValidation())
const scriptDeepAudit = ref<ScriptDeepAuditState>(_emptyScriptDeepAudit())

function _normalizeScriptCountText(content: string) {
  try {
    return content.replace(/[\p{P}\p{S}\s]/gu, '')
  } catch {
    return content.replace(/[，。！？、；：“”‘’（）【】《》〈〉—…,.!?;:'"()\-_\[\]{}<>/\s]/g, '')
  }
}

function _countScriptChars(content: string) {
  return _normalizeScriptCountText(content).length
}

const scriptNetCharCount = computed(() => _countScriptChars(sceneContent.value))

function focusScriptEditor() {
  window.requestAnimationFrame(() => {
    const editor = document.querySelector<HTMLTextAreaElement>('[data-script-editor-textarea="true"]')
    editor?.scrollIntoView({ behavior: 'smooth', block: 'center' })
    editor?.focus()
  })
}

function _completedEpisodeWordCountWarning() {
  const policy = _resolveEpisodeLengthPolicy(_resolveWorkspaceFormatType())
  if (!policy) return ''
  const count = scriptNetCharCount.value
  if (count < policy.min) {
    return `本集生成已完成，但当前净字数 ${count}，低于目标 ${policy.min}-${policy.max}。你可以直接保留，也可以继续补写。`
  }
  if (count > policy.max) {
    return `本集生成已完成，但当前净字数 ${count}，高于目标 ${policy.min}-${policy.max}。你可以直接保留，也可以手动裁剪。`
  }
  return ''
}
const canGenerateNextEpisode = computed(() => {
  const totalEpisodes = _effectiveUserConfirmedTotalEpisodes()
  if (!totalEpisodes || Number(selectedEpisode.value || 1) >= totalEpisodes) return false
  return Boolean(sceneContent.value.trim()) && !isGeneratingScript.value && !isSegmentGenerating.value && !isSegmentedDraftIncomplete.value && currentEpisodeOfficiallyLocked.value
})
const nextEpisodeGateMessage = computed(() => {
  const totalEpisodes = _effectiveUserConfirmedTotalEpisodes()
  if (!totalEpisodes || Number(selectedEpisode.value || 1) >= totalEpisodes) return ''
  if (isSegmentedDraftIncomplete.value) return '当前集未完成，确认四段后再生成下一集'
  if (sceneContent.value.trim() && !currentEpisodeOfficiallyLocked.value) {
    return `请先正式锁定第${selectedEpisode.value}集，再生成第${selectedEpisode.value + 1}集`
  }
  return ''
})

async function lockCurrentEpisodeFromWorkspace() {
  _recordLockTrace('LOCK_T2_parent_method_enter')
  if (!projectId.value || !selectedEpisode.value) {
    _recordLockTrace('LOCK_T3_guard_return', { guard: 'missing_project_or_episode' })
    return
  }
  if (currentEpisodeOfficiallyLocked.value) {
    _recordLockTrace('LOCK_T3_guard_return', { guard: 'already_locked' })
    return
  }
  if (isGeneratingScript.value) {
    _recordLockTrace('LOCK_T3_guard_return', { guard: 'generating_script' })
    return
  }
  if (isSegmentGenerating.value) {
    _recordLockTrace('LOCK_T3_guard_return', { guard: 'segment_generating' })
    return
  }
  if (isGeneratingNextEpisode.value) {
    _recordLockTrace('LOCK_T3_guard_return', { guard: 'generating_next_episode' })
    return
  }
  if (isSegmentedDraftIncomplete.value) {
    _recordLockTrace('LOCK_T3_guard_return', { guard: 'segmented_incomplete' })
    toast.warning('请先确认当前集四段草稿，再正式锁定本集。')
    return
  }
  if (!sceneContent.value.trim()) {
    _recordLockTrace('LOCK_T3_guard_return', { guard: 'empty_content' })
    toast.error('当前正文为空，不能正式锁定本集。')
    return
  }

  isGeneratingNextEpisode.value = true
  try {
    if (currentEpisodeNeedsDraftCompletionRecovery.value) {
      _recordLockTrace('LOCK_T3_draft_completion_recovery', { guard: 'draft_completion_recovery_required' })
      const recoveryProgress = _scriptSegmentProgressStore()[_scriptSegmentProgressKey(selectedEpisode.value)]
      const recoverySceneNo = Math.max(1, Math.round(Number(recoveryProgress?.scene_no || selectedScene.value || 1) || 1))
      const draftCompletionRecovered = await episodeDraftCompletionApi.closeEpisodeDraftCompletion(
        projectId.value,
        selectedEpisode.value,
        recoverySceneNo,
      )
        .then(async ({ data }) => {
          if (String(data?.status || '') !== 'completed') {
            const issues = Array.isArray(data?.blocking_issues) ? data.blocking_issues : []
            toast.error(`本集草稿收口未完成：${issues[0] || '后端未返回 completed 状态'}`)
            return false
          }
          const markedRecovered = _markConfirmedEpisodeDraftCompletionRecovered(
            selectedEpisode.value,
            recoverySceneNo,
            String(data?.content_version_id || ''),
          )
          if (markedRecovered) {
            await _syncProjectWorkflowContext({ immediate: true, silent: true })
          }
          toast.success(`第${selectedEpisode.value}集草稿完成收口已补齐，正在继续正式锁稿。`)
          return true
        })
        .catch((e) => {
          notifyApiError(toast.error, e, '本集草稿收口失败')
          return false
        })
      if (!draftCompletionRecovered) {
        return
      }
    }
    _recordLockTrace('LOCK_T4_call_api')
    await collaborationApi.lockEpisode(projectId.value, selectedEpisode.value, { note: `锁定第${selectedEpisode.value}集最终稿` })
    const { data } = await collaborationApi.getSummary(projectId.value)
    collaborationSummary.value = data
    _recordLockTrace('LOCK_T5_api_success', {
      locked_episodes_count: Math.max(0, Number(data?.locked_episodes || 0)),
    })
    toast.success(`第${selectedEpisode.value}集已正式锁稿`)
  } catch (e) {
    _recordLockTrace('LOCK_T6_api_error', { error_class: _classifyLockTraceError(e) })
    notifyApiError(toast.error, e, '正式锁稿失败')
  } finally {
    isGeneratingNextEpisode.value = false
  }
}

function toggleManualSceneCharacter(id: string) {
  if (manualSceneCharacterIds.value.includes(id)) {
    manualSceneCharacterIds.value = manualSceneCharacterIds.value.filter(item => item !== id)
    return
  }
  manualSceneCharacterIds.value = [...manualSceneCharacterIds.value, id]
}

// 性能闸：剧本相关重 watcher 只在剧本 Tab 活跃时跑。
// 用户切到大纲/角色/分镜等 Tab 时，sceneContent 被切集 / autosave 改动也不会
// 触发字数扫描、规则校验、角色识别等 CPU 密集操作。
const _isScriptTabActive = computed(() => activeTab.value === 'script')
const _characterDetectionCatalogSignature = computed(() => simpleHash(
  (characters.value as any[])
    .map(c => `${String(c?.id || '')}:${String(c?.name || '')}`)
    .join('|'),
))

// 实时解析场景内容，自动识别出场角色（800ms 防抖，避免每次按键都扫全部角色）
let _charDetectTimer: ReturnType<typeof setTimeout> | null = null
let _lastCharacterDetectionSignature = ''
watch([sceneContent, _characterDetectionCatalogSignature], ([content, catalogSignature]) => {
  if (!_isScriptTabActive.value) return  // 不在剧本 Tab 上不跑
  if (isHydratingSceneContent.value || scenesLoading.value) return
  const detectionSignature = `${catalogSignature}:${simpleHash(content || '')}`
  if (detectionSignature === _lastCharacterDetectionSignature) return
  if (_charDetectTimer) clearTimeout(_charDetectTimer)
  _charDetectTimer = setTimeout(() => {
    if (detectionSignature !== `${_characterDetectionCatalogSignature.value}:${simpleHash(sceneContent.value || '')}`) return
    _lastCharacterDetectionSignature = detectionSignature
    if (!characters.value.length) return
    if (isSegmentGenerating.value || isGeneratingScript.value) return
    const found = (characters.value as any[])
      .filter(c => c.name && content.includes(c.name))
      .map(c => c.id)
    _syncAutoSceneCharacterIds(found)
  }, 800)
})

watch(selectedScene, () => {
  // 切场场景的状态重置必须无条件跑，否则切回剧本 Tab 时残留旧场的诊断
  manualSceneCharacterIds.value = []
  dismissedRelationshipSuggestionKeys.value = []
  dismissedStateCardSuggestionKeys.value = []
  scriptRuleValidation.value = _emptyScriptRuleValidation()
  scriptDeepAudit.value = _emptyScriptDeepAudit()
})

let _ruleValidationTimer: ReturnType<typeof setTimeout> | null = null
let _lastQueuedRuleValidationKey = ''
watch(
  [sceneContent, scriptSceneCharacters, () => projectRules.value.episode_seconds, () => projectRules.value.scene_header_style],
  () => {
    if (!_isScriptTabActive.value) return  // 大纲/角色 Tab 上不跑规则校验
    if (isHydratingSceneContent.value || scenesLoading.value) return
    if (_ruleValidationTimer) clearTimeout(_ruleValidationTimer)
    if (!sceneContent.value.trim()) return
    _ruleValidationTimer = setTimeout(() => {
      if (!isSegmentGenerating.value && !isGeneratingScript.value) {
        const requestPayload = _buildScriptValidationRequest()
        const cacheKey = buildValidationCacheKey('validate', requestPayload)
        if (cacheKey === _lastQueuedRuleValidationKey || _scriptValidationInFlight.has(cacheKey)) return
        _lastQueuedRuleValidationKey = cacheKey
        runScriptRuleValidation({ silent: true, requestPayload, cacheKey })
      }
    }, 1500)
  },
)

// 角色健康分析输入源：用 800ms 节流后的内容副本，避免每次按键都扫全文
const sceneContentForAnalysis = ref('')
let _analysisContentTimer: ReturnType<typeof setTimeout> | null = null
watch(sceneContent, (content) => {
  if (!_isScriptTabActive.value) return  // 不在剧本 Tab 不算字
  if (isHydratingSceneContent.value || scenesLoading.value) return
  if (_analysisContentTimer) clearTimeout(_analysisContentTimer)
  _analysisContentTimer = setTimeout(() => {
    sceneContentForAnalysis.value = content
  }, 800)
}, { immediate: true })

// 切回剧本 Tab 时主动触发一次延迟很短的同步，让分析数据从空白追上当前内容。
watch(_isScriptTabActive, (active) => {
  if (!active) return
  if (sceneContent.value && sceneContent.value !== sceneContentForAnalysis.value) {
    sceneContentForAnalysis.value = sceneContent.value
  }
})

// ── 角色健康分析（前端即时 + 后端校验融合）────────────────────
const localCharacterHealth = computed(() => {
  const content = sceneContentForAnalysis.value
  const netCount = _countScriptChars(content)
  const lines = content ? content.split('\n') : []
  return (characters.value as any[]).map(c => {
    const name: string = c.name || ''
    if (!name) return { ...c, present: false, dialogueCount: 0, osCount: 0, total: 0, status: 'idle', reason: '' }
    const dialogueCount = lines.filter(l => l.startsWith(name + '：') || l.startsWith(name + ':')).length
    const osCount = lines.filter(l => l.includes(name + 'OS：') || (l.includes(name + '（') && l.includes('）OS：'))).length
    const total = content ? (content.match(new RegExp(name.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'), 'g')) || []).length : 0
    const present = total > 0

    let status = 'normal'
    let reason = ''
    if (!present) {
      if (c.role === 'protagonist') { status = 'absent'; reason = '主角未出场' }
      else if (c.role === 'antagonist') { status = 'absent'; reason = '反派未出场' }
      else { status = 'idle'; reason = '未出场' }
    } else if (dialogueCount === 0) {
      status = 'warning'; reason = '出场但无台词'
    } else if (c.role === 'protagonist' && netCount > 500 && osCount === 0) {
      status = 'warning'; reason = '缺少OS独白'
    }
    return { ...c, present, dialogueCount, osCount, total, status, reason }
  })
})

const characterHealth = computed(() => {
  const remoteItems = Array.isArray(scriptRuleValidation.value.health_items)
    ? scriptRuleValidation.value.health_items
    : []
  if (remoteItems.length === 0) return localCharacterHealth.value

  const localMap = new Map(localCharacterHealth.value.map((item: any) => [String(item.id), item]))
  return (characters.value as any[]).map((char) => {
    const local = localMap.get(String(char.id)) || {
      ...char,
      present: false,
      dialogueCount: 0,
      osCount: 0,
      total: 0,
      status: 'idle',
      reason: '',
    }
    const remote = remoteItems.find((item: any) => String(item?.id || '') === String(char.id))
    if (!remote) return local
    return {
      ...local,
      present: Boolean(remote.present),
      dialogueCount: Number(remote.dialogue_count ?? local.dialogueCount ?? 0),
      osCount: Number(remote.os_count ?? local.osCount ?? 0),
      status: String(remote.status || local.status || 'normal'),
      reason: String(remote.reason || local.reason || ''),
    }
  })
})

function _pairKey(a: string, b: string) {
  return [a, b].sort().join('__')
}

const sceneRelationshipDiagnostics = computed(() => {
  const byId = new Map((characters.value as any[]).map(char => [String(char.id), char]))
  const presentIds = new Set(scriptSceneCharacters.value)
  const activeKeys: string[] = []
  const summaryLines: string[] = []
  const warnings: string[] = []
  const seenPairs = new Set<string>()
  const presentChars = [...presentIds]
    .map(id => byId.get(id))
    .filter(Boolean) as any[]

  const protagonist = (characters.value as any[]).find(c => c.role === 'protagonist')
  const antagonist = (characters.value as any[]).find(c => c.role === 'antagonist')

  presentChars.forEach((char) => {
    ;(char.relationships || []).forEach((rel: any) => {
      const targetId = String(rel?.targetId || '')
      if (!targetId || !presentIds.has(targetId) || !byId.has(targetId)) return
      const target = byId.get(targetId)
      const pair = _pairKey(String(char.id), targetId)
      if (seenPairs.has(pair)) return
      seenPairs.add(pair)
      activeKeys.push(pair)
      const strength = typeof rel?.strength === 'number' ? `·强度${Math.round(rel.strength)}` : ''
      const desc = rel?.description ? `·${rel.description}` : ''
      summaryLines.push(`${char.name} ↔ ${target?.name}：${rel?.type || '关系待定'}${strength}${desc}`)
    })
  })

  if (presentChars.length >= 2 && summaryLines.length === 0) {
    warnings.push('当前出场角色在角色库中没有直接关系定义，容易写到后面关系漂移。')
  }
  if (protagonist && !presentIds.has(String(protagonist.id)) && scriptNetCharCount.value > 180) {
    warnings.push(`正文已超过 ${scriptNetCharCount.value} 净字，主角仍未进场，容易偏离主线。`)
  }
  if (protagonist && antagonist && presentIds.has(String(protagonist.id)) && presentIds.has(String(antagonist.id))) {
    const mainPair = _pairKey(String(protagonist.id), String(antagonist.id))
    if (!activeKeys.includes(mainPair)) {
      warnings.push('主角与反派已同时出场，但角色库里没有明确主线关系定义，请谨慎写关系跳变。')
    }
  }
  if (presentChars.length > 0) {
    const nonMainChars = presentChars.filter(char => !['protagonist', 'antagonist'].includes(char.role))
    if (nonMainChars.length >= presentChars.length && scriptNetCharCount.value > 260) {
      warnings.push('当前场面主要由配角承担，主线推动力偏弱。')
    }
  }

  const activeRelationCards = storyStateCards.value.relationship_cards.filter((card) => {
    if (!Array.isArray(card.related_character_ids) || card.related_character_ids.length === 0) return false
    return card.related_character_ids.some(id => presentIds.has(String(id)))
  })
  activeRelationCards.forEach((card) => {
    const relatedNames = (card.related_character_ids || [])
      .map(id => (byId.get(String(id)) as any)?.name)
      .filter(Boolean)
    summaryLines.push(`状态卡：${card.title}${card.state ? `（${card.state}）` : ''}${relatedNames.length ? ` · ${relatedNames.join('、')}` : ''}`)
  })

  const guardrailLines = [
    protagonist ? `主线主角：${protagonist.name}，写法必须始终围绕他的目标、代价和选择。` : '',
    antagonist ? `主线对抗：${antagonist.name}若出场，必须提供阻碍、压迫、诱导或代价。` : '',
    summaryLines.length
      ? `当前关系护栏：${summaryLines.join('；')}`
      : presentChars.length >= 2
        ? `当前出场角色：${presentChars.map(char => char.name).join('、')}。若角色库未定义直接关系，不得突然跳成恋爱、背叛或生死绑定。`
        : '',
    outlineData.value.conflict ? `主线冲突：${outlineData.value.conflict}` : '',
    warnings.length ? `漂移预警：${warnings.join('；')}` : '',
    '若本场要推进关系，只能推进半步到一步，并且必须用动作、对白冲突和即时后果把变化写实。',
  ].filter(Boolean)

  return {
    activeKeys,
    summaryLines,
    warnings,
    guardrailText: guardrailLines.join('\n'),
  }
})

const activeStoryStateCards = computed(() => {
  const activeIds = new Set(scriptSceneCharacters.value)
  const filterCards = (cards: StoryStateCard[]) => cards.filter((card) => {
    if (!Array.isArray(card.related_character_ids) || card.related_character_ids.length === 0) return true
    return card.related_character_ids.some(id => activeIds.has(String(id)))
  })
  return {
    relationship_cards: filterCards(storyStateCards.value.relationship_cards),
    info_cards: filterCards(storyStateCards.value.info_cards),
    power_cards: filterCards(storyStateCards.value.power_cards),
    promise_cards: filterCards(storyStateCards.value.promise_cards),
    locked_fact_cards: filterCards(storyStateCards.value.locked_fact_cards),
  }
})

const pendingRelationshipSuggestions = computed(() => {
  return (scriptRuleValidation.value.relationship_suggestions || []).filter((item: any) => {
    const key = String(item?.key || '')
    return key && !dismissedRelationshipSuggestionKeys.value.includes(key)
  })
})

const pendingStateCardSuggestions = computed(() => {
  return (scriptRuleValidation.value.state_card_suggestions || []).filter((item: any) => {
    const key = String(item?.key || '')
    return key && !dismissedStateCardSuggestionKeys.value.includes(key)
  })
})

function _upsertCharacterRelationship(sourceId: string, targetId: string, type: string, strength: number, description: string) {
  const source = (characters.value as any[]).find(char => String(char.id) === String(sourceId))
  const target = (characters.value as any[]).find(char => String(char.id) === String(targetId))
  if (!source || !target) return

  const nextStrength = Math.max(1, Math.min(100, Math.round(Number(strength) || 50)))
  const upsertOneSide = (from: any, to: any) => {
    if (!Array.isArray(from.relationships)) from.relationships = []
    const existing = from.relationships.find((rel: any) => String(rel.targetId) === String(to.id))
    if (existing) {
      existing.targetName = to.name
      existing.type = type
      existing.strength = Math.max(existing.strength || 0, nextStrength)
      existing.description = description || existing.description || ''
      if (!Array.isArray(existing.episodes)) existing.episodes = [selectedEpisode.value]
      if (!existing.episodes.includes(selectedEpisode.value)) existing.episodes.push(selectedEpisode.value)
      return
    }
    from.relationships.push({
      targetId: to.id,
      targetName: to.name,
      type,
      strength: nextStrength,
      description,
      episodes: [selectedEpisode.value],
    })
  }

  upsertOneSide(source, target)
  upsertOneSide(target, source)
}

function acceptRelationshipSuggestion(item: any, options?: { silent?: boolean }) {
  if ((scriptRuleValidation.value.blocking_issues || []).length > 0) {
    if (!options?.silent) {
      toast.error('当前剧本仍有阻断项，先修复通过后再同步关系图谱')
    }
    return false
  }
  const sourceId = String(item?.source_id || '')
  const targetId = String(item?.target_id || '')
  const relationType = String(item?.suggested_type || '').trim()
  if (!sourceId || !targetId || !relationType) return false
  _upsertCharacterRelationship(
    sourceId,
    targetId,
    relationType,
    Number(item?.suggested_strength || 60),
    String(item?.description || '来自当前场景的确认关系推进').trim(),
  )
  const relationTitle = `${item?.source_name} ↔ ${item?.target_name}`
  upsertStoryStateCard('relationship', {
    title: relationTitle,
    summary: String(item?.description || '来自当前场景的关系推进').trim(),
    state: relationType,
    related_character_ids: [sourceId, targetId],
  })
  const suggestionKey = String(item?.key || '')
  if (suggestionKey && !dismissedRelationshipSuggestionKeys.value.includes(suggestionKey)) {
    dismissedRelationshipSuggestionKeys.value = [...dismissedRelationshipSuggestionKeys.value, suggestionKey]
  }
  if (!options?.silent) {
    toast.success(`已把 ${item?.source_name} / ${item?.target_name} 的关系和状态同步写回`)
  }
  return true
}

function dismissRelationshipSuggestion(key: string) {
  if (!key || dismissedRelationshipSuggestionKeys.value.includes(key)) return
  dismissedRelationshipSuggestionKeys.value = [...dismissedRelationshipSuggestionKeys.value, key]
}

function acceptStateCardSuggestion(item: any, options?: { silent?: boolean }) {
  const kindMap: Record<string, StoryStateCardKind> = {
    relationship: 'relationship',
    info: 'info',
    power: 'power',
    promise: 'promise',
    locked_fact: 'locked_fact',
  }
  const kind = kindMap[String(item?.kind || '').trim()]
  if (!kind) return false
  upsertStoryStateCard(kind, {
    title: String(item?.title || '').trim(),
    summary: String(item?.summary || '').trim(),
    related_character_ids: Array.isArray(item?.related_character_ids) ? item.related_character_ids.map((v: any) => String(v)) : [],
    state: kind === 'locked_fact' ? 'locked' : 'active',
  })
  const suggestionKey = String(item?.key || '')
  if (suggestionKey && !dismissedStateCardSuggestionKeys.value.includes(suggestionKey)) {
    dismissedStateCardSuggestionKeys.value = [...dismissedStateCardSuggestionKeys.value, suggestionKey]
  }
  if (!options?.silent) {
    toast.success('已把当前场景建议写入状态卡')
  }
  return true
}

function dismissStateCardSuggestion(key: string) {
  if (!key || dismissedStateCardSuggestionKeys.value.includes(key)) return
  dismissedStateCardSuggestionKeys.value = [...dismissedStateCardSuggestionKeys.value, key]
}

function _buildScriptValidationRequest() {
  const episodePolicy = _resolveEpisodeLengthPolicy(_resolveWorkspaceFormatType())
  const confirmedCount = segmentSteps.value.filter(step => step.status === 'confirmed').length
  const segmentedInProgress = showSegmentPanel.value && confirmedCount > 0 && confirmedCount < segmentSteps.value.length
  return {
    ..._buildRuleBackedScriptRequest({
      mode: 'scene',
      currentContent: '',
    }),
    scene_content: sceneContent.value,
    current_content: '',
    word_count_target: episodePolicy?.target,
    word_count_min: segmentedInProgress ? 0 : episodePolicy?.min,
    word_count_max: episodePolicy?.max,
    target_chars: episodePolicy?.target,
  }
}

async function runScriptRuleValidation(options?: {
  silent?: boolean
  force?: boolean
  deepAudit?: boolean
  requestPayload?: ReturnType<typeof _buildScriptValidationRequest>
  cacheKey?: string
}) {
  if (!sceneContent.value.trim()) {
    scriptRuleValidation.value = _emptyScriptRuleValidation()
    scriptDeepAudit.value = _emptyScriptDeepAudit()
    return { ok: true, data: scriptRuleValidation.value }
  }

  const requestPayload = options?.requestPayload || _buildScriptValidationRequest()
  const cacheKey = options?.cacheKey || buildValidationCacheKey('validate', requestPayload)
  if (!options?.force && _scriptValidationCache.has(cacheKey)) {
    scriptRuleValidation.value = clonePlain(_scriptValidationCache.get(cacheKey)!)
    _ingestWorkflowUpdates(scriptRuleValidation.value)
    if (scriptRuleValidation.value.present_character_ids.length > 0) {
      _syncAutoSceneCharacterIds(scriptRuleValidation.value.present_character_ids)
    }
    let ok = scriptRuleValidation.value.blocking_issues.length === 0
    if ((options?.force || !options?.silent) && options?.deepAudit !== false) {
      await runScriptDeepAudit({ silent: options?.silent, requestPayload })
      ok = ok && _collectContinuityBlockingIssues().length === 0
    }
    return { ok, data: scriptRuleValidation.value }
  }

  isValidatingScriptRules.value = true
  try {
    let pending = _scriptValidationInFlight.get(cacheKey)
    if (!pending) {
      pending = adminConfigApi.validateRuleBackedScript(requestPayload).then(({ data }) => ({
        raw: data,
        normalized: _normalizeScriptRuleValidation(data),
      }))
      _scriptValidationInFlight.set(cacheKey, pending)
    }
    const { raw, normalized } = await pending
    setBoundedCache(_scriptValidationCache, cacheKey, normalized)
    const currentCacheKey = buildValidationCacheKey('validate', _buildScriptValidationRequest())
    if (currentCacheKey !== cacheKey) {
      if (_lastQueuedRuleValidationKey === cacheKey) {
        _lastQueuedRuleValidationKey = ''
      }
      return { ok: false, data: normalized, stale: true }
    }
    scriptRuleValidation.value = clonePlain(normalized)
    setBoundedCache(_scriptValidationCache, cacheKey, scriptRuleValidation.value)
    _ingestWorkflowUpdates(raw)
    if (scriptRuleValidation.value.present_character_ids.length > 0) {
      _syncAutoSceneCharacterIds(scriptRuleValidation.value.present_character_ids)
    }
    let ok = scriptRuleValidation.value.blocking_issues.length === 0
    if ((options?.force || !options?.silent) && options?.deepAudit !== false) {
      await runScriptDeepAudit({ silent: options?.silent, requestPayload })
      ok = ok && _collectContinuityBlockingIssues().length === 0
    }
    if (!ok && !options?.silent) {
      toast.error(_collectContinuityBlockingIssues()[0] || '当前正文未通过内部审段，请继续调整当前内容')
    }
    return { ok, data: raw }
  } catch (e: any) {
    if (_lastQueuedRuleValidationKey === cacheKey) {
      _lastQueuedRuleValidationKey = ''
    }
    if (!options?.silent) {
      notifyApiError(toast.error, e, '规则校验失败')
    }
    return { ok: false, data: null as any }
  } finally {
    _scriptValidationInFlight.delete(cacheKey)
    isValidatingScriptRules.value = false
  }
}

async function runScriptDeepAudit(options?: {
  silent?: boolean
  force?: boolean
  requestPayload?: Parameters<typeof adminConfigApi.deepAuditRuleBackedScript>[0]
}) {
  if (!_buildEpisodeDraftContent()) {
    scriptDeepAudit.value = _emptyScriptDeepAudit()
    return { ok: true, data: scriptDeepAudit.value }
  }

  const requestPayload = (options?.requestPayload || _buildScriptValidationRequest()) as Parameters<typeof adminConfigApi.deepAuditRuleBackedScript>[0]
  const cacheKey = buildValidationCacheKey('audit', requestPayload)
  if (!options?.force && _scriptDeepAuditCache.has(cacheKey)) {
    scriptDeepAudit.value = clonePlain(_scriptDeepAuditCache.get(cacheKey)!)
    _ingestWorkflowUpdates({
      benchmark_assessment: scriptDeepAudit.value.benchmark_assessment,
      continuity_assessment: scriptDeepAudit.value.continuity_assessment,
    })
    return { ok: true, data: scriptDeepAudit.value }
  }

  try {
    const { data } = await adminConfigApi.deepAuditRuleBackedScript(requestPayload)
    scriptDeepAudit.value = _normalizeScriptDeepAudit(data)
    setBoundedCache(_scriptDeepAuditCache, cacheKey, scriptDeepAudit.value)
    _ingestWorkflowUpdates(data, { persist: true })
    if (!options?.silent) {
      toast.success('已完成逐集头部对标与连续性审计')
    }
    return { ok: true, data: scriptDeepAudit.value }
  } catch (e: any) {
    if (!options?.silent) {
      notifyApiError(toast.error, e, '深度审计失败')
    }
    return { ok: false, data: null as any }
  }
}

async function refreshScriptRuntimeSignals(options?: { silent?: boolean; autoApplySuggestions?: boolean; deepAudit?: boolean }) {
  const result = await runScriptRuleValidation({
    silent: options?.silent,
    force: true,
    deepAudit: options?.deepAudit,
  })
  if (!result.data || !options?.autoApplySuggestions) return result
  if (Array.isArray((result.data as any).blocking_issues) && (result.data as any).blocking_issues.length > 0) {
    return result
  }

  let appliedCount = 0
  for (const item of (result.data as any).relationship_suggestions || []) {
    if (acceptRelationshipSuggestion(item, { silent: true })) appliedCount += 1
  }
  for (const item of (result.data as any).state_card_suggestions || []) {
    if (acceptStateCardSuggestion(item, { silent: true })) appliedCount += 1
  }
  if (appliedCount > 0 && !options?.silent) {
    toast.success(`已根据最新剧本同步 ${appliedCount} 条关系/状态信号`)
  }
  return result
}

function _hasContinuityAssessment() {
  const assessment = scriptDeepAudit.value.continuity_assessment
  return Boolean(
    assessment.checked_episode_span
    || assessment.summary
    || assessment.score
    || assessment.relationship_risks.length
    || assessment.plot_risks.length,
  )
}

function _collectContinuityBlockingIssues() {
  const assessment = scriptDeepAudit.value.continuity_assessment
  if (!_hasContinuityAssessment() || assessment.passed !== false) return [] as string[]

  const issues = [
    ...assessment.relationship_risks.map(item => `连续性风险：${item}`),
    ...assessment.plot_risks.map(item => `剧情风险：${item}`),
  ]
  if (issues.length === 0 && assessment.summary) {
    issues.push(`连续性未通过：${assessment.summary}`)
  }
  return issues.slice(0, 3)
}

function _isScriptApprovalPassed() {
  return scriptRuleValidation.value.blocking_issues.length === 0
    && _collectContinuityBlockingIssues().length === 0
}

const acceptedWordCountIssueKeys = new Set<string>()

function _isWordCountIssue(issue: string) {
  return /字数|净字|word[_\s-]?count|过短|过长|不足|超出|超过上限/.test(String(issue || ''))
}

function _splitWordCountIssues(issues: string[]) {
  const wordCountIssues = issues.filter(_isWordCountIssue)
  const otherIssues = issues.filter(issue => !_isWordCountIssue(issue))
  return { wordCountIssues, otherIssues }
}

function _acceptWordCountIssuesAsWarning(issues: string[]) {
  const { wordCountIssues, otherIssues } = _splitWordCountIssues(issues)
  scriptRuleValidation.value.blocking_issues = otherIssues
  scriptRuleValidation.value.warnings = [
    ...scriptRuleValidation.value.warnings,
    ...wordCountIssues.map(issue => `用户已确认接受当前字数：${issue}`),
  ]
}

function _confirmWordCountIssueOnce(payload: {
  scope: string
  label: string
  content: string
  issues: string[]
  targetLabel: string
}) {
  const { wordCountIssues, otherIssues } = _splitWordCountIssues(payload.issues)
  if (!wordCountIssues.length || otherIssues.length) return false
  if (typeof window === 'undefined') return false

  const count = _countScriptChars(payload.content)
  const key = [
    projectId.value,
    selectedEpisode.value,
    selectedScene.value,
    payload.scope,
    count,
    wordCountIssues.join('|'),
  ].join('__')
  if (acceptedWordCountIssueKeys.has(key)) {
    _acceptWordCountIssuesAsWarning(payload.issues)
    return true
  }

  const confirmed = window.confirm([
    `${payload.label}存在字数问题。`,
    `当前净字：${count}`,
    `目标：${payload.targetLabel}`,
    `问题：${wordCountIssues.slice(0, 3).join('；')}`,
    '',
    '确定：接受当前字数，不因字数打回重写。',
    '取消：不放行，返回页面手动调整或重新生成。',
  ].join('\n'))

  if (!confirmed) return false
  acceptedWordCountIssueKeys.add(key)
  _acceptWordCountIssuesAsWarning(payload.issues)
  toast.warning(`${payload.label}已按你的确认放行字数问题`)
  return true
}

async function ensureScriptInternallyApproved(options?: { silent?: boolean; deepAudit?: boolean; allowAutoFix?: boolean }) {
  if (!sceneContent.value.trim()) return true
  const validation = await runScriptRuleValidation({ silent: true, force: true })
  if (validation.ok && _isScriptApprovalPassed()) return true
  if (_confirmWordCountIssueOnce({
    scope: 'full_script',
    label: `第${selectedEpisode.value}集整集`,
    content: sceneContent.value,
    issues: scriptRuleValidation.value.blocking_issues,
    targetLabel: projectRules.value.word_count_per_episode,
  })) {
    return true
  }

  if (!options?.allowAutoFix) {
    return false
  }

  try {
    const { data } = await adminConfigApi.autoFixRuleBackedScript(_buildScriptValidationRequest())
    sceneContent.value = String(data.content || sceneContent.value)
    scriptRuleValidation.value = _normalizeScriptRuleValidation(data)
    _ingestWorkflowUpdates(data, { persist: true })
    if (scriptRuleValidation.value.present_character_ids.length > 0) {
      _syncAutoSceneCharacterIds(scriptRuleValidation.value.present_character_ids)
    }
    await refreshScriptRuntimeSignals({
      silent: true,
      autoApplySuggestions: true,
      deepAudit: options?.deepAudit ?? true,
    })
    const approved = _isScriptApprovalPassed()
    if (!approved && !options?.silent) {
      toast.error(_collectContinuityBlockingIssues()[0] || '内部修正后仍未通过审段，请继续润色当前内容')
    }
    return approved
  } catch (e: any) {
    if (!options?.silent) {
      notifyApiError(toast.error, e, '内部审段失败')
    }
    return false
  }
}

async function ensureSegmentInternallyApproved(idx: number, options?: { silent?: boolean; allowAutoFix?: boolean }) {
  const step = segmentSteps.value[idx]
  if (!step || !step.editedContent.trim()) return false

  if (_isSegmentConfirmationTrustBoundary(step)) {
    return true
  }

  const previousConfirmed = segmentSteps.value
    .filter((s, i) => i < idx && s.status === 'confirmed')
    .map((s) => s.editedContent)
    .join('\n\n')

  const requestPayload = {
    ..._buildRuleBackedScriptRequest({
      mode: 'segment',
      segmentId: step.id as 'hook' | 'validation' | 'explosion' | 'resolution',
      currentContent: previousConfirmed,
    }),
    scene_content: step.editedContent,
    current_content: previousConfirmed,
  }

  try {
    const { data } = await adminConfigApi.validateRuleBackedScript(requestPayload)
    scriptRuleValidation.value = _normalizeScriptRuleValidation(data)
    _ingestWorkflowUpdates(data, { persist: true })
    if (!scriptRuleValidation.value.blocking_issues.length) {
      return true
    }
    const segmentDef = SEGMENT_DEFS.find(item => item.id === step.id)
    if (_confirmWordCountIssueOnce({
      scope: `segment_${step.id}`,
      label: `${step.label}`,
      content: step.editedContent,
      issues: scriptRuleValidation.value.blocking_issues,
      targetLabel: segmentDef ? `${Math.max(120, segmentDef.target - 50)}-${segmentDef.target + 50}净字` : '当前分段目标字数',
    })) {
      return true
    }
  } catch (e: any) {
    if (!options?.silent) {
      notifyApiError(toast.error, e, '当前段内部审段失败')
    }
    return false
  }

  if (!options?.allowAutoFix) {
    return false
  }

  try {
    const { data } = await adminConfigApi.autoFixRuleBackedScript(requestPayload)
    const fixedContent = String((data as any).content || step.editedContent)
    step.editedContent = fixedContent
    step._editSnapshot = fixedContent
    step.lineOrigins = fixedContent.split('\n').map(() => 'ai-revised' as LineOrigin)
    scriptRuleValidation.value = _normalizeScriptRuleValidation(data)
    _ingestWorkflowUpdates(data, { persist: true })
    return !scriptRuleValidation.value.blocking_issues.length
  } catch (e: any) {
    if (!options?.silent) {
      notifyApiError(toast.error, e, '当前段静默修正失败')
    }
    return false
  }
}

function _isSegmentConfirmationTrustBoundary(step: SegmentStep) {
  return step.status === 'reviewing' && Boolean(step.editedContent.trim())
}

async function autoFixBlockingIssues() {
  if (!sceneContent.value.trim()) {
    toast.error('当前正文为空，无法一键修复')
    return
  }
  if (scriptRuleValidation.value.blocking_issues.length === 0) {
    const checked = await runScriptRuleValidation({ silent: true, force: true })
    if (!checked.data?.blocking_issues?.length) {
      toast.success('当前正文没有阻断项')
      return
    }
  }

  isAutoFixingScript.value = true
  try {
    const { data } = await adminConfigApi.autoFixRuleBackedScript(_buildScriptValidationRequest())
    sceneContent.value = String(data.content || sceneContent.value)
    scriptRuleValidation.value = _normalizeScriptRuleValidation(data)
    _ingestWorkflowUpdates(data, { persist: true })
    if (scriptRuleValidation.value.present_character_ids.length > 0) {
      _syncAutoSceneCharacterIds(scriptRuleValidation.value.present_character_ids)
    }
    await refreshScriptRuntimeSignals({ silent: true, autoApplySuggestions: true, deepAudit: true })
    if (data.success) {
      toast.success(data.message || '阻断项已自动修复')
    } else {
      scriptRightTab.value = 'health'
      toast.warning(data.message || '已尝试自动修复，但仍有阻断项')
    }
  } catch (e: any) {
    notifyApiError(toast.error, e, '一键修复失败')
  } finally {
    isAutoFixingScript.value = false
  }
}

// ── 提取复用函数 ──────────────────────────────────────────────
function _formatRelationshipTimelineForPrompt(rel: any, episodeNo = Number(selectedEpisode.value)) {
  if (!rel) return ''
  const targetName = String(rel.targetName || rel.target_name || rel.target || rel.to || '').trim()
  const earlyType = String(rel.earlyType || rel.early_type || rel.type || rel.relationship || '关系').trim()
  const lateType = String(rel.lateType || rel.late_type || rel.afterType || rel.after_type || earlyType).trim()
  const transitionEpisode = _coerceRelationshipEpisode(rel.transitionEpisode || rel.transition_episode)
  const transitionTrigger = String(rel.transitionTrigger || rel.transition_trigger || rel.trigger || '').trim()
  const finalBoundary = String(rel.finalBoundary || rel.final_boundary || rel.boundary || '').trim()
  const candidateStatus = String(rel.candidateStatus || rel.candidate_status || rel.status || 'confirmed').trim()
  const currentType = transitionEpisode && episodeNo >= transitionEpisode ? lateType : earlyType
  const beforeBoundary = transitionEpisode && episodeNo < transitionEpisode && lateType && lateType !== earlyType
    ? `第${transitionEpisode}集前不能写成${lateType}`
    : ''
  return [
    targetName && `与${targetName}`,
    `当前关系：${currentType}`,
    `早期关系：${earlyType}`,
    lateType && `后期关系：${lateType}`,
    transitionEpisode && `转折集：第${transitionEpisode}集`,
    transitionTrigger && `转折条件：${transitionTrigger}`,
    (finalBoundary || beforeBoundary) && `禁止提前写出：${finalBoundary || beforeBoundary}`,
    candidateStatus && `确认状态：${candidateStatus}`,
  ].filter(Boolean).join('；')
}

function _buildCharacterSummary(): string {
  return (characters.value as any[]).map(c => {
    const roleLabel = c.role === 'protagonist' ? '主角' : c.role === 'antagonist' ? '反派' : c.role === 'supporting' ? '配角' : '次要'
    const relationships = (c.relationships || [])
      .map((r: any) => _formatRelationshipTimelineForPrompt(r))
      .filter(Boolean)
      .join('、')
    return `【${c.name}】(${roleLabel})\n  背景：${c.background || '未设定'}\n  动机：${c.motivation || '未设定'}\n  弧线：${c.arc || '未设定'}\n  关系：${relationships || '无'}`
  }).join('\n')
}

function _buildContinuityNote(content: string): string {
  if (!characters.value.length || !content.trim()) return ''
  const lines = content.split('\n')
  const netCount = _countScriptChars(content)
  const absent: string[] = []
  const warns: string[] = []

  ;(characters.value as any[]).forEach((c) => {
    const name = c.name || ''
    if (!name) return
    const total = (content.match(new RegExp(name.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'), 'g')) || []).length
    const dialogueCount = lines.filter(l => l.startsWith(name + '：') || l.startsWith(name + ':')).length
    const osCount = lines.filter(l => l.includes(name + 'OS：') || (l.includes(name + '（') && l.includes('）OS：'))).length
    if (total === 0) {
      if (c.role === 'protagonist' || c.role === 'antagonist') absent.push(name)
      return
    }
    if (dialogueCount === 0) warns.push(`${name}出场但无台词`)
    if (c.role === 'protagonist' && netCount > 500 && osCount === 0) warns.push(`${name}当前段落缺少OS`)
  })

  const parts: string[] = []
  if (absent.length) parts.push(`重要角色尚未出场：${absent.join('、')}`)
  if (warns.length) parts.push(`连贯性提醒：${warns.join('；')}`)
  return parts.join('；')
}

function _resolveWorkspaceFormatType(): '真人短剧' | '漫剧' | 'AI真人' {
  if (outlineData.value.format_type) return outlineData.value.format_type
  const projectType = project.value?.project_type || ''
  if (projectType.includes('AI真人')) return 'AI真人'
  if (projectType.includes('漫剧')) return '漫剧'
  return '真人短剧'
}

function _resolveWorkspaceProjectType(): string {
  if (project.value?.project_type) return project.value.project_type
  const axis = outlineData.value.audience_axis || project.value?.audience_axis || '混合'
  return `${_resolveWorkspaceFormatType()}-${axis}`
}

function _parseWordCountRange(raw?: string | null) {
  const text = String(raw || '').trim()
  const match = text.match(/(\d+)\s*[-~～]\s*(\d+)/)
  if (!match) return null
  const min = Number(match[1])
  const max = Number(match[2])
  if (!Number.isFinite(min) || !Number.isFinite(max) || min <= 0 || max < min) return null
  return { min, max, target: Math.round((min + max) / 2) }
}

function _resolveSceneHeaderStyle(): 'bracket' | 'plain' {
  return projectRules.value.scene_header_style === 'plain' ? 'plain' : 'bracket'
}

function _resolveEpisodeMinutes() {
  return Number((projectRules.value.episode_seconds / 60).toFixed(3))
}

function _resolveEpisodeLengthPolicy(_formatType: '真人短剧' | '漫剧' | 'AI真人') {
  const configured = _parseWordCountRange(projectRules.value.word_count_per_episode)
  return configured || _deriveWordCountRangeBySeconds(projectRules.value.episode_seconds)
}

function _resolveRequestLengthPolicy(options?: {
  mode?: 'scene' | 'segment'
  segmentId?: 'hook' | 'validation' | 'explosion' | 'resolution'
  currentContent?: string
}) {
  const formatType = _resolveWorkspaceFormatType()
  if (options?.mode === 'segment') {
    const segmentDef = SEGMENT_DEFS.find(item => item.id === options.segmentId)
    if (!segmentDef) return null
    const episodePolicy = _resolveEpisodeLengthPolicy(formatType)
    const existingCount = _countScriptChars(options?.currentContent || '')
    if (!episodePolicy) {
      return {
        target: segmentDef.target,
        min: Math.max(120, segmentDef.target - 50),
        max: segmentDef.target + 50,
      }
    }
    const currentSegmentIndex = SEGMENT_DEFS.findIndex(item => item.id === options.segmentId)
    const remainingSegments = Math.max(1, SEGMENT_DEFS.length - currentSegmentIndex)
    const remainingTarget = Math.max(0, episodePolicy.target - existingCount)
    const remainingMax = Math.max(0, episodePolicy.max - existingCount)
    const minimumViableSegmentChars = Math.max(180, Math.round(segmentDef.target * 0.72))
    const cappedSegmentMax = Math.min(
      segmentDef.target + 80,
      Math.max(minimumViableSegmentChars, Math.floor(remainingMax / remainingSegments)),
    )
    const cappedSegmentTarget = Math.min(
      cappedSegmentMax,
      Math.max(minimumViableSegmentChars, Math.floor(remainingTarget / remainingSegments)),
    )
    const target = cappedSegmentTarget
    const min = Math.min(Math.max(minimumViableSegmentChars, target - 50), cappedSegmentMax)
    const max = cappedSegmentMax
    return {
      target,
      min,
      max,
      total: episodePolicy,
      existingCount,
      remainingTarget,
      remainingMax,
      remainingSegments,
    }
  }

  const episodePolicy = _resolveEpisodeLengthPolicy(formatType)
  if (!episodePolicy) return null

  const existingCount = _countScriptChars(options?.currentContent || '')
  const remainingMin = Math.max(0, episodePolicy.min - existingCount)
  const remainingMax = Math.max(0, episodePolicy.max - existingCount)
  const remainingTarget = Math.max(0, episodePolicy.target - existingCount)

  if (existingCount >= episodePolicy.min && existingCount <= episodePolicy.max) {
    return {
      target: 0,
      min: 0,
      max: 0,
      alreadySatisfied: true,
      total: episodePolicy,
    }
  }

  if (remainingMax <= 0) {
    return {
      target: 0,
      min: 0,
      max: 0,
      alreadyOverflow: true,
      total: episodePolicy,
    }
  }

  return {
    target: remainingTarget || episodePolicy.target,
    min: remainingMin,
    max: remainingMax,
    total: episodePolicy,
  }
}

function _buildEpisodeDraftContent() {
  const orderedScenes = [...scenes.value].sort((a, b) => Number(a.scene_number || 0) - Number(b.scene_number || 0))
  const parts = orderedScenes
    .map((scene) => {
      if (Number(scene.scene_number) === Number(selectedScene.value)) return String(sceneContent.value || '').trim()
      return String(scene.content || '').trim()
    })
    .filter(Boolean)
  return parts.join('\n\n').trim()
}

function _buildEpisodeExcerpt(content?: string | null, limit = 180) {
  const lines = String(content || '')
    .split(/\n+/)
    .map(line => line.replace(/\s+/g, ' ').trim())
    .filter(Boolean)
  const normalized = (lines.length ? lines.slice(-6).join(' ') : String(content || '').replace(/\s+/g, ' ').trim())
  if (!normalized) return ''
  return normalized.length > limit ? `…${normalized.slice(-limit).trim()}` : normalized
}

function _buildEpisodeMetaMap() {
  const map = new Map<number, {
    title: string
    summary: string
    conflict: string
    hook: string
    main_scene?: string
    relationship_change?: string
    info_revealed?: string
    satisfaction_type?: string
    stage?: string
    existing_script?: string
  }>()

  ;(outlineData.value.episodes || []).forEach((episode: any) => {
    const episodeNo = Number(episode.ep || 0)
    if (!episodeNo) return
    map.set(episodeNo, {
      title: String(episode.title || ''),
      summary: String(episode.summary || ''),
      conflict: String(episode.conflict || ''),
      hook: String(episode.hook || ''),
      main_scene: String(episode.main_scene || ''),
      relationship_change: String(episode.relationship_change || ''),
      info_revealed: String(episode.info_revealed || ''),
      satisfaction_type: String(episode.satisfaction_type || ''),
      stage: String(episode.stage || ''),
      existing_script: String(episode.existing_script || ''),
    })
  })

  ;(episodes.value || []).forEach((episode: any) => {
    const episodeNo = Number(episode.episode_number || 0)
    if (!episodeNo) return
    const previous = map.get(episodeNo)
    map.set(episodeNo, {
      // 用户锁定的大纲/集纲字段优先；episodes 表里的短标题/短摘要只做列表展示，不能覆盖模型请求。
      title: String(previous?.title || episode.title || ''),
      summary: String(previous?.summary || episode.summary || ''),
      conflict: String(previous?.conflict || ''),
      hook: String(previous?.hook || ''),
      main_scene: String(previous?.main_scene || ''),
      relationship_change: String(previous?.relationship_change || ''),
      info_revealed: String(previous?.info_revealed || ''),
      satisfaction_type: String(previous?.satisfaction_type || ''),
      stage: String(previous?.stage || ''),
      existing_script: String(previous?.existing_script || ''),
    })
  })

  return map
}

function _buildEpisodeBriefByNo(episodeNo: number): Record<string, unknown> | undefined {
  const meta = _buildEpisodeMetaMap().get(episodeNo)
  if (!meta) return undefined
  const actualProgress = _buildEpisodeExcerpt(meta.existing_script)
  return {
    episode_no: episodeNo,
    title: meta.title,
    summary: meta.summary,
    conflict: meta.conflict,
    hook: meta.hook,
    main_scene: meta.main_scene,
    relationship_change: meta.relationship_change,
    info_revealed: meta.info_revealed,
    satisfaction_type: meta.satisfaction_type,
    stage: meta.stage,
    actual_progress: actualProgress,
  }
}

function _buildPreviousEpisodeBriefs(limit = 9, beforeEpisodeNo = selectedEpisode.value) {
  const episodeNos = Array.from(_buildEpisodeMetaMap().keys())
    .filter((episodeNo) => episodeNo < Number(beforeEpisodeNo))
    .sort((a, b) => a - b)
    .slice(-limit)
  const briefs: Array<Record<string, unknown>> = []
  episodeNos.forEach((episodeNo) => {
    const item = _buildEpisodeBriefByNo(episodeNo)
    if (item) briefs.push(item)
  })
  return briefs
}

function _buildFutureEpisodeBriefs(limit = 5, afterEpisodeNo = selectedEpisode.value) {
  const episodeNos = Array.from(_buildEpisodeMetaMap().keys())
    .filter((episodeNo) => episodeNo > Number(afterEpisodeNo))
    .sort((a, b) => a - b)
    .slice(0, limit)
  const briefs: Array<Record<string, unknown>> = []
  episodeNos.forEach((episodeNo) => {
    const item = _buildEpisodeBriefByNo(episodeNo)
    if (item) briefs.push(item)
  })
  return briefs
}

function _buildSelectedEpisodeRelationshipTimelineContext() {
  return {
    previous_episode_briefs: _buildPreviousEpisodeBriefs(),
    future_episode_briefs: _buildFutureEpisodeBriefs(),
    relationship_timeline_context: _buildRelationshipTimelineContext(selectedEpisode.value),
  }
}

function _inferEpisodeContractGuardrails() {
  const joined = [
    outlineData.value.logline,
    outlineData.value.worldview,
    outlineData.value.conflict,
    outlineData.value.genre_main,
    project.value?.genre_sub,
  ].filter(Boolean).join('\n')
  const guardrails = [
    '不能重演前序集已经落地的开场动作、公开表态或冲突结论，必须从上一集结果继续推进。',
    '不能提前兑现后续集摘要里的大反转、定案、身份揭露、感情定性或最终胜负。',
    '关系变化必须有触发动作、台词反应和当场后果，不能直接把关系改成新状态。',
    '民间线索、个人判断、传闻和官方结论必须分层，不能从线索直接跳到权威裁定。',
  ]
  if (/(债务|欠债|欠款|借据|债主|顶债|抵债|还债|还钱)/.test(joined)) {
    guardrails.push('债务/责任口径必须单义：原始债、挂名债、篡改债、女主承认的数额必须分层，不能在同一集漂移。')
  }
  if (/(婚书|婚约|契约|文书|判词|族规|家法|登记|盖章|手印|民政)/.test(joined)) {
    guardrails.push('婚书/契约/口头承诺/族规/官府或机构文书必须分层，不能混成同一种法律效力。')
  }
  if (/(证据|账本|账页|缺页|录音|监控|仓单|日志|口供|传唤|监管|县里|官府|警方|立案|冻结)/.test(joined)) {
    guardrails.push('证据链只能按发现、验真、递交、第三方核验、权威动作逐步推进，不能省掉中间桥。')
  }
  if (/(身份|血脉|亲子|真假|替身|嫡|继承)/.test(joined)) {
    guardrails.push('身份线必须区分怀疑、线索、证人、物证和公开确认，不能一句话直接坐实。')
  }
  if (/(系统|金手指|异能|修为|境界|法宝)/.test(joined)) {
    guardrails.push('系统/金手指/修炼规则必须保持同一套代价和生效边界，不能临场改规则救场。')
  }
  return Array.from(new Set(guardrails)).slice(0, 10)
}

function _buildEpisodeContractFromMeta(episodeNo: number, meta: any) {
  const previous = _buildEpisodeBriefByNo(episodeNo - 1)
  const currentExisting = _buildEpisodeExcerpt(meta?.existing_script)
  const episodeSummary = String(meta?.summary || meta?.conflict || '').trim()
  const inferredMainScene = String(meta?.main_scene || '').trim()
    || (episodeSummary ? `围绕本集摘要落地的核心现场：${episodeSummary}` : '')
  const inferredRelationshipChange = String(meta?.relationship_change || '').trim()
    || (episodeSummary ? `本集人物关系随事件推进小步变化：${episodeSummary}` : '')
  const inferredInfoRevealed = String(meta?.info_revealed || '').trim()
    || (episodeSummary ? `本集新信息由现场动作或证据揭露：${episodeSummary}` : '')
  const inferredHook = String(meta?.hook || '').trim()
    || (episodeSummary ? `以本集结果形成下一步追查压力：${episodeSummary}` : '')
  const combined = [
    meta?.summary,
    meta?.conflict,
    meta?.hook,
    outlineData.value.conflict,
    outlineData.value.logline,
  ].filter(Boolean).join('\n')
  const publicPressure = /投诉|砸摊|举报|围观|当众|直播|黑心|连锁|房东|封|赶走/.test(combined)
    ? '本集必须出现公开压迫或第三方见证，让主角的处境被本题材内成立的旁观者、权力方或关系方看见。'
    : '本集必须把压力写到现实现场，不只停在人物心里或口头争执。'
  const realLoss = /早餐|馒头|摊|订单|配方|连锁|债|钱|生意/.test(combined)
    ? '本集必须落下本赛道成立的可见后果：生意、名声、现金、物件、证据、场地、合作或第三方站队至少动一项。'
    : '本集必须有当场代价或局势变化，不能只提出问题。'
  const evidenceObject = /馒头|老面|酵母|面团|蒸笼|配方/.test(combined)
    ? '优先使用大纲中已有的食物、器具、票据、证据、手机信息或现场物件承载钩子，禁止凭空换赛道。'
    : /证据|账|录音|合同|回执|检测/.test(combined)
      ? '用本集真实证据物件承载推进，不要套用通用合同/录音补丁。'
      : '结尾钩子必须落到本集真实物件、动作、证据或手机提示。'
  const villainPressureAction = /连锁|早餐|品牌|黑心|供应商|投诉/.test(combined)
    ? '反派压制必须具体到本赛道成立的商业动作、资源截断、证据造假、第三方施压或舆论反咬。'
    : '反派不能只放狠话，必须给出具体动作或利益威胁。'
  const mustHappen = [
    meta?.summary && `兑现本集摘要：${meta.summary}`,
    meta?.conflict && `推进本集核心冲突：${meta.conflict}`,
    inferredMainScene && `主场景必须落地：${inferredMainScene}`,
    inferredRelationshipChange && `关系变化必须落地：${inferredRelationshipChange}`,
    inferredInfoRevealed && `信息揭露必须落地：${inferredInfoRevealed}`,
    meta?.satisfaction_type && `爽点类型必须落地：${meta.satisfaction_type}`,
    inferredHook && `结尾钩子落到具体画面：${inferredHook}`,
    `公开压迫必须落地：${publicPressure}`,
    `当场后果必须可见：${realLoss}`,
  ].filter(Boolean)
  return {
    episode_no: episodeNo,
    title: meta?.title || '',
    start_state: String((previous?.actual_progress || previous?.summary || '承接前序已经落地的结果，不重启同一场开局。') as string),
    incoming_hook: String((previous?.actual_progress || previous?.summary || '承接前序已经落地的结果，不重启同一场开局。') as string),
    must_happen: mustHappen,
    must_not_happen: _inferEpisodeContractGuardrails(),
    relationship_delta: [meta?.relationship_change || '若本集关系推进，只能小步变化，并写出触发动作、反应和代价。'],
    character_delta: ['人物立场变化必须由动作触发，不能靠OS自我宣布。'],
    information_delta: [
      meta?.info_revealed ? `本集信息揭露：${meta.info_revealed}` : '',
      '本集只推进当前集应揭露的信息，不提前吃掉后续集大反转。',
      currentExisting ? `已有正文落地：${currentExisting}` : '',
    ].filter(Boolean),
    public_pressure: publicPressure,
    real_loss: realLoss,
    evidence_object: evidenceObject,
    villain_pressure_action: villainPressureAction,
    dialogue_style_contract: '现实短剧台词短句化，单句尽量25字以内；长信息拆成短对白和动作。',
    rag_benchmark_pattern: '对标头部短剧：开场压力可见，中段证据/关系推进，爆点有当场后果，结尾物件拉钩。',
    evidence_chain_step: /证据|账|录音|监控|仓单|日志|口供|传唤|监管|县里|官府|警方|立案|冻结/.test([meta?.summary, meta?.conflict, meta?.hook, outlineData.value.conflict].filter(Boolean).join('\n'))
      ? '本集证据链必须只推进一到两步：发现/验真/递交/第三方核验/权威动作，禁止从线索直接跳最终定案。'
      : '',
    ending_state: meta?.summary || inferredHook || '',
    outgoing_hook: inferredHook || '',
    ending_hook: inferredHook || '',
    source: 'frontend_outline_simulation',
  }
}

function _buildSeriesSimulationPacket() {
  const metaMap = _buildEpisodeMetaMap()
  const episodeContracts = Array.from(metaMap.entries())
    .sort(([a], [b]) => a - b)
    .map(([episodeNo, meta]) => _buildEpisodeContractFromMeta(episodeNo, meta))
  return {
    source: 'frontend_outline_inferred',
    simulation_goal: '先以全剧沙盘锁定因果、关系、信息揭露和规则边界，再生成正文。',
    global_must_not: _inferEpisodeContractGuardrails(),
    locked_series_facts: [
      outlineData.value.logline && `故事前提：${outlineData.value.logline}`,
      outlineData.value.conflict && `核心冲突：${outlineData.value.conflict}`,
    ].filter(Boolean),
    episode_contracts: episodeContracts,
  }
}

function _buildSeriesSimulationWindowPacket(packet?: ReturnType<typeof _buildSeriesSimulationPacket>) {
  const full = packet || _buildSeriesSimulationPacket()
  const current = Number(selectedEpisode.value)
  const episodeContracts = (full.episode_contracts || []).filter((item: any) => {
    const ep = Number(item.episode_no || 0)
    return ep === current || (ep >= current - 2 && ep <= current + 3)
  })
  return {
    ...full,
    source: `${full.source || 'frontend_outline'}_windowed`,
    episode_contracts: episodeContracts,
    window: {
      current_episode: current,
      previous: 2,
      future: 3,
      full_contract_count: (full.episode_contracts || []).length,
    },
  }
}

function _buildCurrentEpisodeContract() {
  const packet = _buildSeriesSimulationPacket()
  return packet.episode_contracts.find((item: any) => Number(item.episode_no || 0) === Number(selectedEpisode.value)) || {}
}

const currentEpisodeContract = computed<Record<string, any>>(() => _buildCurrentEpisodeContract() as Record<string, any>)

const currentHeadContractItems = computed(() => {
  const contract = currentEpisodeContract.value || {}
  return [
    { key: 'incoming_hook', label: '承接', value: String(contract.incoming_hook || contract.start_state || '').trim() },
    { key: 'public_pressure', label: '公开压迫', value: String(contract.public_pressure || '').trim() },
    { key: 'real_loss', label: '当场后果', value: String(contract.real_loss || '').trim() },
    { key: 'evidence_object', label: '物件钩子', value: String(contract.evidence_object || '').trim() },
    { key: 'villain_pressure_action', label: '反派动作', value: String(contract.villain_pressure_action || '').trim() },
    { key: 'dialogue_style_contract', label: '台词', value: String(contract.dialogue_style_contract || '').trim() },
  ].filter((item) => item.value)
})

type StepConfirmationStepId = 'prerequisite' | 'blueprint' | 'segment_cards' | 'candidate_save'

type StepConfirmationItem = {
  key: string
  title: string
  body: string
  helper?: string
  editable?: boolean
  source?: string
}

const SATISFACTION_TYPE_LABELS: Record<string, string> = {
  S1: '亮牌逆袭',
  S2: '围观打脸',
  S3: '规则兑现',
  S4: '资源碾压',
  S5: '伤害被看见',
  S6: '关系反转',
  S7: '反击得偿',
  S8: '偏爱公开',
  S9: '夸张反差',
  S10: '弹幕金句',
  S11: '表情包时刻',
  S12: '身份暴露',
  S13: '连续反转',
  S14: '现实代价',
  S15: '情感共鸣落泪',
}

const DIRECTOR_BLUEPRINT_USER_LABELS = [
  '本集目标',
  '本集任务目标',
  '开场钩子',
  '开场任务卡',
  '谁失去控制',
  '失控点',
  '控制损失',
  '观众当场收益',
  '当场兑现',
  '观众收益',
  '结尾新钩子',
  '结尾钩子',
  '尾钩',
  '写手执行卡',
  '写手任务卡',
  '复核合同',
  '评审合同',
]

function _formatSatisfactionTypeForUser(raw: any): string {
  const text = String(raw || '').trim()
  if (!text) return ''
  const match = text.match(/\bS\d{1,2}\b/i)
  if (!match) return text
  const code = match[0].toUpperCase()
  const label = SATISFACTION_TYPE_LABELS[code]
  if (!label) return text
  const detail = text.replace(new RegExp(`\\b${code}\\b`, 'i'), '').replace(/[：:，,、+\-—\s]+/g, ' ').trim()
  if (!detail || detail.includes(label)) return `${label}（${code}）`
  return `${label}（${code}）：${detail}`
}

function _stepConfirmationRecord(raw: any): Record<string, any> {
  return raw && typeof raw === 'object' && !Array.isArray(raw) ? raw as Record<string, any> : {}
}

function _escapeConfirmationRegExp(raw: string) {
  return raw.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}

function _extractDirectorBlueprintLabel(rawText: any, labels: string[]) {
  const text = String(rawText || '').replace(/\r\n/g, '\n').replace(/\r/g, '\n').trim()
  if (!text) return ''
  const labelGroup = labels.map(_escapeConfirmationRegExp).join('|')
  const allLabelGroup = DIRECTOR_BLUEPRINT_USER_LABELS.map(_escapeConfirmationRegExp).join('|')
  const pattern = new RegExp(
    `(?:^|\\n)\\s*(?:[-*#\\d\\.、\\)\\s]*)?(?:${labelGroup})\\s*[：:]\\s*` +
    `([\\s\\S]+?)(?=\\n\\s*(?:[-*#\\d\\.、\\)\\s]*)?(?:${allLabelGroup})\\s*[：:]|$)`,
  )
  const match = text.match(pattern)
  return match ? String(match[1] || '').replace(/\n{2,}/g, '\n').trim() : ''
}

function _directorBlueprintLabelText(directorBlueprint: Record<string, any>, labels: string[]) {
  return _firstConfirmationText(
    _extractDirectorBlueprintLabel(directorBlueprint.raw_text, labels),
    _extractDirectorBlueprintLabel(directorBlueprint.writer_brief, labels),
    _extractDirectorBlueprintLabel(directorBlueprint.episode_objective, labels),
  )
}

function _stepConfirmationEpisodeKey(episodeNo = selectedEpisode.value) {
  return String(Math.max(1, Math.round(Number(episodeNo || 1) || 1)))
}

function _stepConfirmationOverrideStore() {
  const raw = (workflowContext.value as any).step_confirmation_overrides
  return raw && typeof raw === 'object' && !Array.isArray(raw)
    ? raw as Record<string, any>
    : {}
}

function _stepConfirmationOverridesForEpisode(episodeNo = selectedEpisode.value) {
  const store = _stepConfirmationOverrideStore()
  const episodeKey = _stepConfirmationEpisodeKey(episodeNo)
  const raw = store[episodeKey]
  return raw && typeof raw === 'object' && !Array.isArray(raw)
    ? raw as Record<string, any>
    : {}
}

function _stepConfirmationItem(
  key: string,
  title: string,
  body: string,
  options?: { helper?: string; editable?: boolean; source?: string },
): StepConfirmationItem {
  return {
    key,
    title,
    body: String(body || '').trim(),
    helper: options?.helper || '',
    editable: options?.editable !== false,
    source: options?.source || '系统推断',
  }
}

function _applyStepConfirmationOverrides(stepId: StepConfirmationStepId, items: StepConfirmationItem[]) {
  const scoped = _stepConfirmationOverridesForEpisode()
  const stepOverrides = scoped[stepId] && typeof scoped[stepId] === 'object' && !Array.isArray(scoped[stepId])
    ? scoped[stepId] as Record<string, any>
    : {}
  return items.map((item) => {
    if (!Object.prototype.hasOwnProperty.call(stepOverrides, item.key)) return item
    return {
      ...item,
      body: String(stepOverrides[item.key] || ''),
      source: '用户修改',
    }
  })
}

function _stepConfirmationOverrideBody(stepId: StepConfirmationStepId, itemKey: string, episodeNo = selectedEpisode.value) {
  const scoped = _stepConfirmationOverridesForEpisode(episodeNo)
  const stepOverrides = scoped[stepId] && typeof scoped[stepId] === 'object' && !Array.isArray(scoped[stepId])
    ? scoped[stepId] as Record<string, any>
    : {}
  if (!Object.prototype.hasOwnProperty.call(stepOverrides, itemKey)) return ''
  return String(stepOverrides[itemKey] || '').trim()
}

function _flattenStepConfirmationItems(packet: any) {
  const rows: Array<Record<string, unknown>> = []
  ;(['prerequisite', 'blueprint', 'segment_cards', 'candidate_save'] as StepConfirmationStepId[]).forEach((stepId) => {
    const section = packet?.[stepId]
    const items = Array.isArray(section?.items) ? section.items : []
    items.forEach((item: any) => {
      const title = String(item?.title || '').trim()
      const body = String(item?.body || '').trim()
      if (!title && !body) return
      rows.push({
        step_id: stepId,
        key: String(item?.key || '').trim(),
        title,
        body,
        source: String(item?.source || '').trim(),
      })
    })
  })
  return rows
}

function _confirmationText(raw: any, limit = 6, depth = 0): string {
  if (raw == null || depth > 2) return ''
  if (typeof raw === 'string' || typeof raw === 'number' || typeof raw === 'boolean') {
    return String(raw).trim()
  }
  if (Array.isArray(raw)) {
    return raw
      .map(item => _confirmationText(item, 1, depth + 1))
      .filter(Boolean)
      .slice(0, limit)
      .join('；')
  }
  if (typeof raw === 'object') {
    const preferredKeys = [
      'title',
      'label',
      'summary',
      'goal',
      'task',
      'body',
      'content',
      'description',
      'focus',
      'requirement',
      'payoff',
      'hook',
      'ending',
      'value',
      'text',
    ]
    const keys = [...preferredKeys, ...Object.keys(raw)].filter((key, index, arr) => arr.indexOf(key) === index)
    return keys
      .map(key => _confirmationText(raw[key], 1, depth + 1))
      .filter(Boolean)
      .slice(0, limit)
      .join('；')
  }
  return ''
}

function _firstConfirmationText(...values: any[]): string {
  for (const value of values) {
    const text = _confirmationText(value)
    if (text) return text
  }
  return ''
}

function _confirmationLines(lines: Array<string | false | null | undefined>) {
  return lines
    .map(line => String(line || '').trim())
    .filter(Boolean)
    .join('\n')
}

function _lookupSegmentBlueprint(raw: any, segmentId: string, label: string): string {
  if (!raw) return ''
  if (typeof raw === 'string') return ''
  if (Array.isArray(raw)) {
    const matched = raw.find((item: any) => {
      if (!item || typeof item !== 'object') return false
      const marker = String(item.id || item.key || item.segment_id || item.segment || item.label || item.title || '').toLowerCase()
      return marker === segmentId || marker.includes(segmentId) || (!!label && marker.includes(label.toLowerCase()))
    })
    return _confirmationText(matched)
  }
  if (typeof raw === 'object') {
    return _firstConfirmationText(
      raw[segmentId],
      raw[`${segmentId}_segment`],
      raw[`${segmentId}_card`],
      raw[`${segmentId}_task`],
    )
  }
  return ''
}

function _segmentBlueprintText(directorBlueprint: Record<string, any>, segmentId: string, label: string) {
  return _firstConfirmationText(
    _lookupSegmentBlueprint(directorBlueprint.segment_cards, segmentId, label),
    _lookupSegmentBlueprint(directorBlueprint.four_part_cards, segmentId, label),
    _lookupSegmentBlueprint(directorBlueprint.segments, segmentId, label),
    _lookupSegmentBlueprint(directorBlueprint.writer_brief?.segment_cards, segmentId, label),
    _lookupSegmentBlueprint(directorBlueprint.writer_brief?.four_part_cards, segmentId, label),
  )
}

function _withExistingSegmentDraft(plan: string, existing?: SegmentStep) {
  const draft = String(existing?.editedContent || existing?.versionA || existing?.versionB || '').trim()
  if (!draft) return plan
  return `${plan}\n\n【当前四段草稿/已确认内容】\n${draft}`
}

function _buildSegmentTaskCardItems(options: {
  epInfo: Record<string, any>
  previousBrief: Record<string, any>
  relationshipContext: Record<string, any>
  contract: Record<string, any>
  directorBlueprint: Record<string, any>
  mustHappen: string
  relationshipDelta: string
  characterDelta: string
  informationDelta: string
}): StepConfirmationItem[] {
  const { epInfo, previousBrief, relationshipContext, contract, directorBlueprint } = options
  const payoffTarget = _stepConfirmationRecord(directorBlueprint.payoff_target_contract)
  const visibleStakesContract = _stepConfirmationRecord(directorBlueprint.episode_visible_stakes_contract)
  const payoffStrengthContract = _stepConfirmationRecord(directorBlueprint.episode_payoff_strength_contract)
  const evidenceChain = _stepConfirmationRecord(directorBlueprint.evidence_chain)
  const continuityContract = _stepConfirmationRecord(directorBlueprint.continuity_contract)
  const confirmedBlueprintEpisodeGoal = _stepConfirmationOverrideBody('blueprint', 'episode_goal')
  const confirmedBlueprintControlLoss = _stepConfirmationOverrideBody('blueprint', 'control_loss')
  const confirmedBlueprintAudiencePayoff = _stepConfirmationOverrideBody('blueprint', 'audience_payoff')
  const confirmedBlueprintEndingHook = _stepConfirmationOverrideBody('blueprint', 'ending_hook')
  const confirmedBlueprintCharacterBoundary = _stepConfirmationOverrideBody('blueprint', 'character_boundary')
  const satisfactionType = _formatSatisfactionTypeForUser(epInfo.satisfaction_type || directorBlueprint.satisfaction_type || contract.satisfaction_type)
  const episodeGoal = _firstConfirmationText(
    confirmedBlueprintEpisodeGoal,
    directorBlueprint.episode_goal,
    directorBlueprint.goal,
    _directorBlueprintLabelText(directorBlueprint, ['本集目标', '本集任务目标']),
    directorBlueprint.episode_objective,
    options.mustHappen,
    contract.must_happen,
    epInfo.summary,
  ) || '本集目标未明确，请先回到集纲或导演蓝图补齐。'
  const incomingCanon = _firstConfirmationText(
    contract.incoming_hook,
    contract.start_state,
    previousBrief.actual_progress,
    previousBrief.summary,
  ) || '第1集可直接开场；非第1集必须承接上一集用户保存稿。'
  const mainScene = _firstConfirmationText(
    epInfo.main_scene,
    contract.main_scene,
    directorBlueprint.main_scene,
  ) || '本集主场景未明确，请从集纲补齐。'
  const conflict = _firstConfirmationText(
    epInfo.conflict,
    contract.core_conflict,
    directorBlueprint.conflict,
  ) || '本集核心冲突未明确，请从集纲补齐。'
  const evidenceOrInfo = _firstConfirmationText(
    contract.evidence_object,
    contract.information_delta,
    directorBlueprint.evidence_object,
    directorBlueprint.information_delta,
    options.informationDelta,
  ) || '本集需要让观众看到具体证据、信息增量或反转。'
  const controlLoss = _firstConfirmationText(
    confirmedBlueprintControlLoss,
    directorBlueprint.control_loss,
    payoffTarget.control_loss,
    payoffTarget.opponent_control_loss,
    visibleStakesContract.visible_stakes_or_loss,
    visibleStakesContract.micro_reversal_or_payoff,
    _directorBlueprintLabelText(directorBlueprint, ['谁失去控制', '失控点', '控制损失']),
    directorBlueprint.visible_stakes,
    contract.public_pressure,
    contract.villain_pressure_action,
  ) || '必须明确谁在这一集失去控制，不能只做铺垫。'
  const payoff = _firstConfirmationText(
    confirmedBlueprintAudiencePayoff,
    directorBlueprint.audience_payoff,
    payoffTarget.audience_visible_payoff,
    payoffTarget.visible_gain,
    payoffStrengthContract.audience_payoff_emotion,
    evidenceChain.visible_consequence,
    _directorBlueprintLabelText(directorBlueprint, ['观众当场收益', '当场兑现', '观众收益']),
    directorBlueprint.payoff,
    contract.real_loss,
    contract.public_pressure,
  ) || '必须给观众当场可见收益，避免内容过于保守。'
  const endingHook = _firstConfirmationText(
    confirmedBlueprintEndingHook,
    directorBlueprint.ending_hook,
    directorBlueprint.outgoing_hook,
    continuityContract.outgoing_hook,
    continuityContract.ending_hook,
    _directorBlueprintLabelText(directorBlueprint, ['结尾新钩子', '结尾钩子', '尾钩']),
    contract.outgoing_hook,
    contract.ending_hook,
    epInfo.hook,
  ) || '结尾必须留下可接下一集的具体动作、物件、台词或信息。'
  const relationshipGuard = _firstConfirmationText(
    confirmedBlueprintCharacterBoundary,
    options.relationshipDelta,
    options.characterDelta,
    relationshipContext.summary,
  ) || '人物关系变化必须由动作触发，不能突然变脸。'

  return SEGMENT_DEFS.map((def) => {
    const existing = segmentSteps.value.find(step => step.id === def.id)
    const directorSegmentNote = _segmentBlueprintText(directorBlueprint, def.id, def.label)
    let body = ''
    if (def.id === 'hook') {
      body = _confirmationLines([
        '段落目标：开场先承接上一集正史，把本集问题推到用户能立刻看懂的现场。',
        `本段具体写什么：在${mainScene}里引出“${conflict}”，不要只解释设定。`,
        `承接依据：${incomingCanon}`,
        `人物/关系约束：${relationshipGuard}`,
        satisfactionType && `爽点类型必须落地：${satisfactionType}`,
        directorSegmentNote && `导演补充：${directorSegmentNote}`,
        `段尾交接：停在“${evidenceOrInfo}”即将被看见、质问或验证的位置，交给验证段。`,
        `字数参考：约${def.target}净字；轻微偏差可以提示放行，但不能牺牲信息完整性。`,
      ])
    } else if (def.id === 'validation') {
      body = _confirmationLines([
        '段落目标：把钩子段抛出的疑问落到可检查的证据、人物动作或关系反应上。',
        `本段具体写什么：围绕“${evidenceOrInfo}”推进验证，让观众获得新的确定信息。`,
        `承接依据：${episodeGoal}`,
        `人物/关系约束：${relationshipGuard}`,
        satisfactionType && `爽点类型必须落地：${satisfactionType}`,
        directorSegmentNote && `导演补充：${directorSegmentNote}`,
        `段尾交接：验证不能提前收束，要把压力推向“${controlLoss}”，交给爆发段。`,
        `字数参考：约${def.target}净字；轻微偏差可以提示放行，但不能牺牲信息完整性。`,
      ])
    } else if (def.id === 'explosion') {
      body = _confirmationLines([
        '段落目标：把本集最强冲突和情绪兑现写出来，不能只做克制铺垫。',
        `本段具体写什么：围绕“${controlLoss}”写出当场失控、反压、反转或公开压力。`,
        `承接依据：${episodeGoal}`,
        `人物/关系约束：${relationshipGuard}`,
        satisfactionType && `爽点类型必须落地：${satisfactionType}`,
        directorSegmentNote && `导演补充：${directorSegmentNote}`,
        `段尾交接：让观众看到“${payoff}”，但不要提前吃掉结尾钩子。`,
        `字数参考：约${def.target}净字；轻微偏差可以提示放行，但不能牺牲信息完整性。`,
      ])
    } else {
      body = _confirmationLines([
        '段落目标：收住本集当场后果，更新人物关系或信息状态，并自然拉出下一集。',
        `本段具体写什么：兑现“${payoff}”后的余波，明确本集结果，不把矛盾写散。`,
        `承接依据：${episodeGoal}`,
        `人物/关系约束：${relationshipGuard}`,
        satisfactionType && `爽点类型必须落地：${satisfactionType}`,
        directorSegmentNote && `导演补充：${directorSegmentNote}`,
        `段尾交接：结尾落在“${endingHook}”，保存后成为下一集承接正史。`,
        `字数参考：约${def.target}净字；轻微偏差可以提示放行，但不能牺牲信息完整性。`,
      ])
    }
    return _stepConfirmationItem(
      def.id,
      def.label,
      _withExistingSegmentDraft(body, existing),
      {
        helper: existing?.editedContent ? '上方是本段任务书，下方是当前四段草稿；用户改过会进入正式生成链路。' : '四段生成前必须确认本段具体写什么，而不是只确认字数。',
        source: existing?.editedContent ? '四段草稿+任务书' : '集纲/导演蓝图/剧作契约',
      },
    )
  })
}

function _buildStepConfirmationPacket(targetEpisodeNo = selectedEpisode.value) {
  const episodeNo = _normalizeEpisodeNo(targetEpisodeNo)
  const epInfo = (outlineData.value.episodes.find((e: any) => Number(e.ep || 0) === episodeNo) || {}) as Record<string, any>
  const previousBrief = _buildEpisodeBriefByNo(episodeNo - 1) || {}
  const relationshipContext = _buildRelationshipTimelineContext(episodeNo)
  const fullSeriesSimulationPacket = _buildSeriesSimulationPacket()
  const contract = (fullSeriesSimulationPacket.episode_contracts.find((item: any) => Number(item.episode_no || 0) === episodeNo)
    || currentEpisodeContract.value
    || {}) as Record<string, any>
  const directorBlueprintPacket = _currentDirectorBlueprintPacket(contract)
  const directorBlueprint = directorBlueprintPacket.director_blueprint || {}
  const mustHappen = Array.isArray(contract.must_happen) ? contract.must_happen.join('\n') : ''
  const relationshipDelta = Array.isArray(contract.relationship_delta) ? contract.relationship_delta.join('\n') : ''
  const characterDelta = Array.isArray(contract.character_delta) ? contract.character_delta.join('\n') : ''
  const informationDelta = Array.isArray(contract.information_delta) ? contract.information_delta.join('\n') : ''
  const payoffTarget = _stepConfirmationRecord(directorBlueprint.payoff_target_contract)
  const visibleStakesContract = _stepConfirmationRecord(directorBlueprint.episode_visible_stakes_contract)
  const payoffStrengthContract = _stepConfirmationRecord(directorBlueprint.episode_payoff_strength_contract)
  const evidenceChain = _stepConfirmationRecord(directorBlueprint.evidence_chain)
  const continuityContract = _stepConfirmationRecord(directorBlueprint.continuity_contract)
  const satisfactionType = _formatSatisfactionTypeForUser(epInfo.satisfaction_type || directorBlueprint.satisfaction_type || contract.satisfaction_type)
  const blueprintEpisodeGoal = _firstConfirmationText(
    directorBlueprint.episode_goal,
    directorBlueprint.goal,
    _directorBlueprintLabelText(directorBlueprint, ['本集目标', '本集任务目标']),
    directorBlueprint.episode_objective,
  )
  const blueprintControlLoss = _firstConfirmationText(
    directorBlueprint.control_loss,
    payoffTarget.control_loss,
    payoffTarget.opponent_control_loss,
    visibleStakesContract.visible_stakes_or_loss,
    visibleStakesContract.micro_reversal_or_payoff,
    _directorBlueprintLabelText(directorBlueprint, ['谁失去控制', '失控点', '控制损失']),
    directorBlueprint.visible_stakes,
  )
  const blueprintPayoff = _firstConfirmationText(
    directorBlueprint.audience_payoff,
    payoffTarget.audience_visible_payoff,
    payoffTarget.visible_gain,
    payoffStrengthContract.audience_payoff_emotion,
    evidenceChain.visible_consequence,
    _directorBlueprintLabelText(directorBlueprint, ['观众当场收益', '当场兑现', '观众收益']),
    directorBlueprint.payoff,
  )
  const blueprintEndingHook = _firstConfirmationText(
    directorBlueprint.ending_hook,
    directorBlueprint.outgoing_hook,
    continuityContract.outgoing_hook,
    continuityContract.ending_hook,
    _directorBlueprintLabelText(directorBlueprint, ['结尾新钩子', '结尾钩子', '尾钩']),
  )
  const blockingIssues = [
    ...(scriptRuleValidation.value.blocking_issues || []),
    ...(scriptDeepAudit.value.benchmark_assessment.gaps || []),
  ].map(item => String(item || '').trim()).filter(Boolean).slice(0, 6)
  const prerequisiteItems = _applyStepConfirmationOverrides('prerequisite', [
    _stepConfirmationItem(
      'episode_outline',
      '当前集集纲',
      [
        epInfo.title && `标题：${epInfo.title}`,
        epInfo.summary && `摘要：${epInfo.summary}`,
        epInfo.conflict && `冲突：${epInfo.conflict}`,
        epInfo.hook && `钩子：${epInfo.hook}`,
        epInfo.main_scene && `主场景：${epInfo.main_scene}`,
        satisfactionType && `爽点类型：${satisfactionType}`,
      ].filter(Boolean).join('\n') || '当前集纲为空，请先回到大纲页补齐。',
      { helper: '这一步决定本集写作方向。', source: '集纲' },
    ),
    _stepConfirmationItem(
      'previous_canon',
      '上一集正史',
      String(previousBrief.actual_progress || previousBrief.summary || '没有找到上一集已保存正史；第1集可忽略。'),
      { helper: '下一集必须承接用户保存稿，不读旧模型草稿。', source: '保存历史' },
    ),
    _stepConfirmationItem(
      'relationship_context',
      '人物关系',
      relationshipContext.summary || '当前未形成可用人物关系摘要，请检查角色库关系。',
      { helper: '关系阶段错误会直接影响人物一致性。', source: '角色库' },
    ),
  ])
  const blueprintItems = _applyStepConfirmationOverrides('blueprint', [
    _stepConfirmationItem(
      'episode_goal',
      '本集目标',
      String(blueprintEpisodeGoal || mustHappen || epInfo.summary || '请明确本集必须完成的剧情推进。'),
      { helper: '用户在这里改过后，会进入正式生成链路。', source: blueprintEpisodeGoal ? '导演蓝图' : '集纲推断' },
    ),
    _stepConfirmationItem(
      'control_loss',
      '谁失去控制',
      String(blueprintControlLoss || contract.public_pressure || contract.villain_pressure_action || '请明确本集谁在关系、证据、舆论或局面上失去控制。'),
      { helper: '没有失控点，正文容易只写事件，不产生爽点。', source: blueprintControlLoss ? '导演蓝图' : '剧作契约' },
    ),
    _stepConfirmationItem(
      'audience_payoff',
      '观众当场收益',
      String(blueprintPayoff || contract.real_loss || informationDelta || '请明确观众这一集能看到的信息增量、反转或情绪兑现。'),
      { helper: '这是防止内容过于保守的核心项。', source: blueprintPayoff ? '导演蓝图' : '剧作契约' },
    ),
    _stepConfirmationItem(
      'character_boundary',
      '人物边界',
      [relationshipDelta, characterDelta].filter(Boolean).join('\n') || '人物关系变化必须由动作触发，不能突然变脸。',
      { helper: '这项保护人物一致性和关系阶段。', source: '角色关系' },
    ),
    _stepConfirmationItem(
      'ending_hook',
      '结尾钩子',
      String(blueprintEndingHook || contract.outgoing_hook || contract.ending_hook || epInfo.hook || '请明确结尾落在哪个具体动作、台词、物件或信息上。'),
      { helper: '结尾钩子必须拉下一集，但不能提前吃掉后续真相。', source: blueprintEndingHook ? '导演蓝图' : '剧作契约' },
    ),
  ])
  const segmentItems = _applyStepConfirmationOverrides('segment_cards', _buildSegmentTaskCardItems({
    epInfo,
    previousBrief,
    relationshipContext,
    contract,
    directorBlueprint,
    mustHappen,
    relationshipDelta,
    characterDelta,
    informationDelta,
  }))
  const candidateItems = _applyStepConfirmationOverrides('candidate_save', [
    _stepConfirmationItem(
      'candidate_summary',
      '正文候选摘要',
      [
        `当前净字：${scriptNetCharCount.value}`,
        sceneContent.value.trim() ? `正文尾部：${_manualEditTailExcerpt(sceneContent.value, 420)}` : '当前正文为空。',
        blockingIssues.length ? `质量提醒：${blockingIssues.join('；')}` : '当前没有阻断性质量提醒。',
      ].join('\n'),
      { editable: false, helper: '完整正文请在下方正文编辑区修改；保存后才成为下一集正史。', source: '正文编辑区' },
    ),
  ])
  const packet = {
    episode_no: episodeNo,
    updated_at: new Date().toISOString(),
    prerequisite: {
      summary: '确认大纲、集纲、人物关系和上一集保存稿是否已进入本集依据。',
      note: '前提资料不准，后面正文会跟着偏。',
      items: prerequisiteItems,
    },
    blueprint: {
      summary: '确认本集真正要兑现的剧作目标、失控点、爽点和结尾钩子。',
      note: '这里改过的内容会进入后续生成请求，不再只读旧蓝图。',
      items: blueprintItems,
    },
    segment_cards: {
      summary: '确认四段写作任务是否清楚，避免写手拿到模糊任务。',
      note: '四段卡控制写手先写什么、后写什么。',
      items: segmentItems,
    },
    candidate_save: {
      summary: '确认正文候选和质量提醒；正文细改在下方编辑区完成。',
      note: '正文保存后才会变成下一集承接的正史。',
      items: candidateItems,
    },
  }
  return {
    ...packet,
    items: _flattenStepConfirmationItems(packet),
  }
}

const currentStepConfirmationPacket = computed(() => _buildStepConfirmationPacket())

function _buildUserConfirmedGenerationPacket(packet = _buildStepConfirmationPacket()) {
  const result: Record<string, Record<string, string>> = {}
  ;(['prerequisite', 'blueprint', 'segment_cards', 'candidate_save'] as StepConfirmationStepId[]).forEach((stepId) => {
    const section = (packet as any)[stepId]
    const items = Array.isArray(section?.items) ? section.items : []
    const bucket: Record<string, string> = {}
    result[stepId] = bucket
    items.forEach((item: any) => {
      const key = String(item?.key || '').trim()
      if (!key) return
      bucket[key] = String(item?.body || '').trim()
    })
  })
  return {
    episode_no: (packet as any).episode_no || selectedEpisode.value,
    source: 'workspace_step_confirmation_panel',
    updated_at: (packet as any).updated_at || new Date().toISOString(),
    ...result,
  }
}

function _upsertStepConfirmationOverride(payload: { stepId: StepConfirmationStepId; itemKey: string; body: string }) {
  const stepId = payload?.stepId
  const itemKey = String(payload?.itemKey || '').trim()
  if (!stepId || !itemKey) return
  const episodeKey = _stepConfirmationEpisodeKey()
  const store = { ..._stepConfirmationOverrideStore() }
  const episodeStore = store[episodeKey] && typeof store[episodeKey] === 'object' && !Array.isArray(store[episodeKey])
    ? { ...store[episodeKey] }
    : {}
  const stepStore = episodeStore[stepId] && typeof episodeStore[stepId] === 'object' && !Array.isArray(episodeStore[stepId])
    ? { ...episodeStore[stepId] }
    : {}
  stepStore[itemKey] = String(payload.body || '')
  episodeStore[stepId] = stepStore
  store[episodeKey] = episodeStore
  workflowContext.value = normalizeWorkflowContext(_deepMergeRecord(workflowContext.value, {
    step_confirmation_overrides: store,
    step_confirmation_updated_at: new Date().toISOString(),
  }))
}

async function _commitStepConfirmationOverride(payload: { stepId: StepConfirmationStepId; itemKey: string; body: string }) {
  _upsertStepConfirmationOverride(payload)
  await _syncProjectWorkflowContext({ silent: true })
}

async function _commitStepConfirmationStep(payload: { stepId: StepConfirmationStepId; items: Array<{ itemKey: string; body: string }> }) {
  const items = Array.isArray(payload?.items) ? payload.items : []
  items.forEach((item) => {
    _upsertStepConfirmationOverride({
      stepId: payload.stepId,
      itemKey: String(item.itemKey || ''),
      body: String(item.body || ''),
    })
  })
  if (items.length) {
    await _syncProjectWorkflowContext({ silent: true })
  }
}

const workflowChainStatus = computed(() => {
  const packet = workflowContext.value.series_simulation_packet || {}
  const contracts = Array.isArray(packet.episode_contracts) ? packet.episode_contracts : []
  const issueFeedback = workflowContext.value.issue_feedback || {}
  const issues = Array.isArray((issueFeedback as any).issues) ? (issueFeedback as any).issues : []
  const ragCards = Array.isArray(workflowContext.value.rag_context_cards) ? workflowContext.value.rag_context_cards : []
  return {
    contractCount: contracts.length || _buildSeriesSimulationPacket().episode_contracts.length,
    windowCount: (_buildSeriesSimulationWindowPacket().episode_contracts || []).length,
    ragCardCount: ragCards.length,
    issueCount: Number((issueFeedback as any).issue_count || issues.length || 0),
    hasCurrentContract: Boolean(currentEpisodeContract.value?.episode_no),
  }
})

const headGateIssues = computed(() => {
  const items = [
    ...scriptRuleValidation.value.blocking_issues,
    ...scriptRuleValidation.value.warnings,
    ...scriptDeepAudit.value.benchmark_assessment.gaps,
    ...scriptDeepAudit.value.benchmark_assessment.rule_upgrades,
  ].map((item) => String(item || '').trim()).filter(Boolean)
  return items.filter((item) => /头部|公开压迫|当场后果|反派|模板污染|终局|物件|RAG|钩子|OS|小说化/.test(item)).slice(0, 6)
})

function _buildPreviousRelationshipSnapshot(limit = 20) {
  const namesById = new Map(
    (characters.value as any[]).map((char) => [String(char.id || ''), String(char.name || '')]),
  )
  const rows: Array<Record<string, unknown>> = []

  ;(characters.value as any[]).forEach((char) => {
    const sourceId = String(char.id || char.name || '').trim()
    const sourceName = String(char.name || '').trim()
    if (!sourceId) return
    ;(char.relationships || []).forEach((rel: any) => {
      const targetId = String(rel.targetId || rel.target_id || '').trim()
      const targetName = String(rel.targetName || namesById.get(targetId) || '').trim()
      if (!targetId) return
      rows.push({
        source: sourceId,
        source_name: sourceName,
        target: targetId,
        target_name: targetName,
        type: String(rel.type || '').trim(),
        earlyType: String(rel.earlyType || rel.early_type || rel.type || '').trim(),
        lateType: String(rel.lateType || rel.late_type || rel.earlyType || rel.type || '').trim(),
        transitionEpisode: _coerceRelationshipEpisode(rel.transitionEpisode || rel.transition_episode),
        transitionTrigger: String(rel.transitionTrigger || rel.transition_trigger || '').trim(),
        finalBoundary: String(rel.finalBoundary || rel.final_boundary || '').trim(),
        candidateStatus: String(rel.candidateStatus || rel.candidate_status || 'confirmed').trim(),
        strength: Number(rel.strength || 0),
        note: String(rel.note || rel.notes || '').trim(),
      })
    })
  })

  const deduped = new Map<string, Record<string, unknown>>()
  rows.forEach((item) => {
    const key = `${item.source}__${item.target}`
    deduped.set(key, item)
  })
  return Array.from(deduped.values()).slice(0, limit)
}

function _buildRelationshipTimelineContext(episodeNo = Number(selectedEpisode.value)) {
  const namesById = new Map(
    (characters.value as any[]).map((char) => [String(char.id || ''), String(char.name || '')]),
  )
  const relationships: Array<Record<string, unknown>> = []
  ;(characters.value as any[]).forEach((char) => {
    const sourceId = String(char.id || char.name || '').trim()
    const sourceName = String(char.name || '').trim()
    if (!sourceId || !sourceName) return
    ;(char.relationships || []).forEach((rel: any) => {
      const targetId = String(rel.targetId || rel.target_id || '').trim()
      const targetName = String(rel.targetName || rel.target_name || namesById.get(targetId) || '').trim()
      if (!targetName) return
      const earlyType = String(rel.earlyType || rel.early_type || rel.type || '关系').trim()
      const lateType = String(rel.lateType || rel.late_type || rel.afterType || rel.after_type || earlyType).trim()
      const transitionEpisode = _coerceRelationshipEpisode(rel.transitionEpisode || rel.transition_episode)
      const currentType = transitionEpisode && episodeNo >= transitionEpisode ? lateType : earlyType
      const boundary = String(rel.finalBoundary || rel.final_boundary || '').trim()
      relationships.push({
        source: sourceId,
        source_name: sourceName,
        target: targetId || targetName,
        target_name: targetName,
        current_episode: episodeNo,
        current_type: currentType,
        earlyType,
        lateType,
        transitionEpisode,
        transitionTrigger: String(rel.transitionTrigger || rel.transition_trigger || '').trim(),
        finalBoundary: boundary || (transitionEpisode && episodeNo < transitionEpisode && lateType !== earlyType ? `第${transitionEpisode}集前不能写成${lateType}` : ''),
        candidateStatus: String(rel.candidateStatus || rel.candidate_status || 'confirmed').trim(),
        strength: Number(rel.strength || 0),
        description: String(rel.description || rel.desc || '').trim(),
      })
    })
  })
  return {
    current_episode: episodeNo,
    rule: '用户确认过的关系线是生成依据；needs_user_confirmation 只能作为候选提醒，不能替代用户确认事实。',
    relationships,
    summary: relationships
      .map((rel) => `${String(rel.source_name || '')} -> ${String(rel.target_name || '')}：${String(rel.current_type || '')}`)
      .join('；'),
  }
}

function _episodeScopedRecord(raw: any, episodeNo = selectedEpisode.value) {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return {}
  const direct = raw[String(episodeNo)] || raw[Number(episodeNo)] || raw[`ep${episodeNo}`] || raw[`episode_${episodeNo}`]
  return direct && typeof direct === 'object' && !Array.isArray(direct) ? direct : {}
}

function _currentDirectorBlueprintPacket(episodeContract?: Record<string, any>) {
  const workflow = workflowContext.value as any
  const scopedBlueprint = _episodeScopedRecord(workflow.director_blueprints)
  const scopedTrace = _episodeScopedRecord(workflow.director_generation_trace)
  const directBlueprint = workflow.director_blueprint && typeof workflow.director_blueprint === 'object'
    ? workflow.director_blueprint
    : {}
  const contractBlueprint = episodeContract?.director_blueprint && typeof episodeContract.director_blueprint === 'object'
    ? episodeContract.director_blueprint as Record<string, any>
    : {}
  const blueprint = Object.keys(scopedBlueprint).length
    ? scopedBlueprint
    : Object.keys(contractBlueprint).length
      ? contractBlueprint
      : directBlueprint
  const trace = scopedTrace && typeof scopedTrace === 'object' ? scopedTrace : {}
  return {
    director_blueprint: blueprint,
    director_blueprint_hash: String(trace.director_blueprint_hash || blueprint.director_blueprint_hash || ''),
    writer_brief_hash: String(trace.writer_brief_hash || blueprint.writer_brief_hash || ''),
    review_contract_hash: String(trace.review_contract_hash || blueprint.review_contract_hash || ''),
  }
}

function _buildRuleBackedScriptRequest(options?: {
  mode?: 'scene' | 'segment'
  segmentId?: 'hook' | 'validation' | 'explosion' | 'resolution'
  currentContent?: string
  targetEpisodeNo?: number
  targetSceneNo?: number
}) {
  const episodeNo = _normalizeEpisodeNo(options?.targetEpisodeNo ?? selectedEpisode.value)
  const sceneNo = _normalizeSceneNo(options?.targetSceneNo ?? selectedScene.value)
  const epInfo = outlineData.value.episodes.find((e: any) => Number(e.ep || 0) === episodeNo)
  const currentContent = options?.currentContent ?? sceneContent.value
  const formatType = _resolveWorkspaceFormatType()
  const lengthPolicy = _resolveRequestLengthPolicy({
    mode: options?.mode,
    segmentId: options?.segmentId,
    currentContent,
  })
  const ragAssetReferences = _workflowRagText('asset_references', 'asset_reference', 'materials')
  const ragMarketSignals = _workflowRagText('market_signals', 'market', 'market_notes')
  const ragNovelChapters = _workflowRagText('novel_chapters', 'novel_analysis', 'novel_anchor')
  const ragScriptReferences = _workflowRagText('script_references', 'script_reference', 'top_script_references', 'benchmark_scripts')
  const ragReviewReferences = _workflowRagText('review_references', 'quality_review', 'benchmark_review', 'top_script_review')
  const ragCharacterReferences = _workflowRagText('character_references', 'character_reference')
  const ragBeatReferences = _workflowRagText('beat_references', 'beat_reference', 'structure_references')
  const fullSeriesSimulationPacket = _buildSeriesSimulationPacket()
  const seriesSimulationPacket = _buildSeriesSimulationWindowPacket(fullSeriesSimulationPacket)
  const episodeContract = fullSeriesSimulationPacket.episode_contracts.find((item: any) => Number(item.episode_no || 0) === episodeNo) || {}
  const directorBlueprintPacket = _currentDirectorBlueprintPacket(episodeContract)
  const stepConfirmationPacket = _buildStepConfirmationPacket(episodeNo)
  const confirmedEpisodeCount = _effectiveUserConfirmedTotalEpisodes()
  if (!confirmedEpisodeCount) {
    throw new Error('请先确认总集数；用户确认多少集，系统就按多少集生成剧本。')
  }
  return {
    project_id: projectId.value,
    project_type: _resolveWorkspaceProjectType(),
    audience_axis: outlineData.value.audience_axis || project.value?.audience_axis || '',
    genre_main: outlineData.value.genre_main || project.value?.genre_main || '',
    genre_sub: project.value?.genre_sub || '',
    subgenre_track: projectRules.value.subgenre_track,
    sample_track: projectRules.value.sample_track,
    format_type: formatType,
    episode_count: confirmedEpisodeCount,
    episode_minutes: _resolveEpisodeMinutes(),
    scene_header_style: _resolveSceneHeaderStyle(),
    brief: outlineData.value.logline || '',
    golden_finger: outlineData.value.goldenFinger || '',
    worldview: outlineData.value.worldview || '',
    conflict: outlineData.value.conflict || '',
    relationship_guardrails: sceneRelationshipDiagnostics.value.guardrailText,
    episode_no: episodeNo,
    scene_no: sceneNo,
    episode_title: epInfo?.title || '',
    episode_summary: epInfo?.summary || '',
    episode_conflict: epInfo?.conflict || '',
    episode_hook: epInfo?.hook || epInfo?.turning || '',
    current_content: currentContent,
    continuity_notes: _buildContinuityNote(currentContent),
    word_count_target: lengthPolicy?.target,
    word_count_min: lengthPolicy?.min,
    word_count_max: lengthPolicy?.max,
    segment_existing_chars: lengthPolicy?.existingCount,
    segment_remaining_chars_max: lengthPolicy?.remainingMax,
    segment_remaining_parts: lengthPolicy?.remainingSegments,
    exclude_punctuation_for_count: true,
    enforce_standard_format: true,
    target_chars: lengthPolicy?.target,
    mode: options?.mode || 'scene',
    segment_id: options?.segmentId,
    selected_character_ids: [...scriptSceneCharacters.value],
    characters: (characters.value as any[]).map((char) => ({
      id: char.id,
      name: char.name,
      role: char.role,
      age: char.age,
      info: char.info || '',            // 大纲阶段的完整信息段（AI 首选读这个）
      occupation: char.occupation,
      appearance: char.appearance || '',
      background: char.background,
      motivation: char.motivation,
      traits: char.traits,
      personality: char.personality || '',
      voice_style: char.voice_style || '',
      voiceprint: char.voiceprint || '',
      inner_need: char.inner_need || '',
      resource: char.resource || '',
      first_appearance_function: char.first_appearance_function || '',
      relationship_tension: char.relationship_tension || '',
      arc: char.arc,
      notes: char.notes || '',
      relationships: char.relationships || [],
    })),
    state_cards: storyStateCards.value,
    series_title: project.value?.name || '',
    episode_content: _buildEpisodeDraftContent(),
    previous_episode_briefs: _buildPreviousEpisodeBriefs(9, episodeNo),
    previous_episode_briefs_authority: 'reference_only',
    future_episode_briefs: _buildFutureEpisodeBriefs(5, episodeNo),
    previous_relationship_snapshot: _buildPreviousRelationshipSnapshot(),
    relationship_timeline_context: _buildRelationshipTimelineContext(episodeNo),
    episode_memory_cards: episodeMemoryCards.value,
    canon_packet: canonPacket.value,
    manual_edit_context: workflowContext.value.manual_edit_context || {},
    step_confirmation_packet: stepConfirmationPacket,
    user_confirmed_generation_packet: _buildUserConfirmedGenerationPacket(stepConfirmationPacket),
    series_simulation_packet: seriesSimulationPacket,
    episode_contract: episodeContract,
    ...directorBlueprintPacket,
    rag_context_pack: {
      cards: workflowContext.value.rag_context_cards || [],
      source: 'project_workflow_context',
    },
    materials: workflowContext.value.materials,
    issue_feedback: workflowContext.value.issue_feedback,
    rule_profile: workflowContext.value.rule_profile,
    world_rules: workflowContext.value.world_rules,
    golden_finger_rules: workflowContext.value.golden_finger_rules,
    conflict_plan: workflowContext.value.conflict_plan,
    quality_report: workflowContext.value.quality_report,
    compliance_report: workflowContext.value.compliance_report,
    episode_novel_anchor: workflowContext.value.episode_novel_anchor,
    rag_asset_references: ragAssetReferences,
    rag_market_signals: ragMarketSignals,
    rag_novel_chapters: ragNovelChapters,
    rag_script_references: ragScriptReferences,
    rag_character_references: ragCharacterReferences,
    rag_beat_references: ragBeatReferences,
    rag_review_references: ragReviewReferences,
    generation_provider: projectRules.value.generation_provider,
    generation_model: projectRules.value.generation_model,
    advanced_generation_mode: projectRules.value.advanced_generation_mode,
    advanced_generation_providers: (project.value?.config as any)?.advanced_generation_providers || {},
    advanced_generation_routes: (project.value?.config as any)?.advanced_generation_routes || {},
  }
}

const activeSegmentGenerationTarget = ref<ScriptGenerationTarget | null>(null)
const activeSegmentDraftContent = ref('')
const backendGenerationSourcePreview = ref<Record<string, unknown> | null>(null)
const backendGenerationSourceStatus = ref<'idle' | 'ready' | 'blocked'>('idle')

function _activeSegmentPersistenceTarget() {
  const target = activeSegmentGenerationTarget.value
  return {
    episodeNo: _normalizeEpisodeNo(target?.episodeNo ?? selectedEpisode.value),
    sceneNo: _normalizeSceneNo(target?.sceneNo ?? selectedScene.value),
  }
}

function _activeSegmentContentForSave() {
  return activeSegmentGenerationTarget.value
    ? String(activeSegmentDraftContent.value || '')
    : String(sceneContent.value || '')
}

function _isActiveSegmentTargetSelected() {
  const target = activeSegmentGenerationTarget.value
  if (!target) return true
  return Number(selectedEpisode.value) === Number(target.episodeNo)
    && Number(selectedScene.value) === Number(target.sceneNo)
}

const activeSegmentReviewTarget = computed(() => _activeSegmentPersistenceTarget())

function _ensureActiveSegmentActionTarget(idx: number, actionLabel: string) {
  const target = activeSegmentGenerationTarget.value
  const selectedEp = _normalizeEpisodeNo(selectedEpisode.value)
  const selectedSc = _normalizeSceneNo(selectedScene.value)
  const step = segmentSteps.value[idx]
  if (!target) {
    scriptStreamStatus.value = '分段生成目标还没有建立，请先重新选择本集后再操作。'
    toast.error('分段生成目标还没有建立，请先重新选择本集后再操作。')
    return false
  }
  if (idx !== Number(currentSegmentIdx.value)) {
    scriptStreamStatus.value = `${actionLabel}已停止：当前按钮段落和页面当前段落不一致。`
    toast.error(`${actionLabel}已停止：当前按钮段落和页面当前段落不一致。`)
    return false
  }
  if (!step) {
    scriptStreamStatus.value = `${actionLabel}已停止：当前段落不存在。`
    toast.error(`${actionLabel}已停止：当前段落不存在。`)
    return false
  }
  if (Number(target.episodeNo) !== selectedEp || Number(target.sceneNo) !== selectedSc) {
    scriptStreamStatus.value = `${actionLabel}已停止：页面当前是第${selectedEp}集第${selectedSc}场，但分段生成目标是第${target.episodeNo}集第${target.sceneNo}场。请先切回正确集数再操作。`
    toast.error('分段生成目标和当前页面不一致，已停止本次操作。')
    return false
  }
  return true
}

function _startSegmentedGenerationTarget(episodeNo = selectedEpisode.value, sceneNo = selectedScene.value) {
  activeSegmentGenerationTarget.value = {
    episodeNo: _normalizeEpisodeNo(episodeNo),
    sceneNo: _normalizeSceneNo(sceneNo),
  }
  activeSegmentDraftContent.value = String(sceneContent.value || '')
  return activeSegmentGenerationTarget.value
}

function _clearSegmentedGenerationTarget(episodeNo?: number) {
  const target = activeSegmentGenerationTarget.value
  if (episodeNo && target && Number(target.episodeNo) !== Number(episodeNo)) return
  activeSegmentGenerationTarget.value = null
  activeSegmentDraftContent.value = ''
}

// ── 内部四段审阅（后台观察模式）─────────────────────────────────────
const {
  segmentSteps,
  isSegmentGenerating,
  showSegmentPanel,
  currentSegmentIdx,
  currentSegmentStep,
  resetSegments,
  confirmedSegmentContent,
  segmentSwitchVersion,
  segmentEnterEdit,
  segmentExitEdit,
  segmentApplyPatch,
  generateOneSegment,
  segmentConfirm,
  generateSegmented,
  segmentRetry,
  segmentGenerateVariant,
  serializeSegmentProgress,
  hydrateSegmentProgress,
  recoverLatestCandidateForSegment,
} = useSegmentedWriting({
  loadSuggestions: step => _loadSuggestionsAsync(step),
  patchSceneText: async payload => {
    const { data } = await adminConfigApi.patchSceneText({
      ...payload,
      project_id: projectId.value,
      scene_header_style: _resolveSceneHeaderStyle(),
    })
    return { replacement: data.replacement }
  },
  buildSegmentRequest: (step, confirmedContent) => ({
    ..._buildRuleBackedScriptRequest({
      mode: 'segment',
      segmentId: step.id as 'hook' | 'validation' | 'explosion' | 'resolution',
      currentContent: confirmedContent,
      targetEpisodeNo: _activeSegmentPersistenceTarget().episodeNo,
      targetSceneNo: _activeSegmentPersistenceTarget().sceneNo,
    }),
    temperature: 0.55,
  }),
  streamSegment: (requestPayload, _onToken, onProgress) => _runRuleBackedScriptJob(requestPayload, onProgress),
  recoverLatestSegmentCandidate: (idx, step) => _restoreLatestRuleBackedSegmentCandidate(idx, step),
  onSegmentProgress: message => {
    scriptStreamStatus.value = message
  },
  onAllSegmentsComplete: async () => {
    scriptStreamStatus.value = ''
    const target = _activeSegmentPersistenceTarget()
    const saved = await persistCurrentScriptContent({
      silent: true,
      changeNote: '内部四段审阅完成',
      editorType: 'ai',
      targetEpisodeNo: target.episodeNo,
      targetSceneNo: target.sceneNo,
      contentOverride: _activeSegmentContentForSave(),
      skipEpisodeReadyCheck: true,
    })
    if (!saved) {
      toast.error('内部四段审阅已生成，但自动保存失败。请先点击保存，再切换页面或进入下一集。')
      return
    }
    const completionClosed = await episodeDraftCompletionApi.closeEpisodeDraftCompletion(projectId.value, target.episodeNo, target.sceneNo)
      .then(({ data }) => {
        if (String(data?.status || '') !== 'completed') {
          const issues = Array.isArray(data?.blocking_issues) ? data.blocking_issues : []
          toast.error(`本集草稿收口未完成：${issues[0] || '后端未返回 completed 状态'}`)
          return false
        }
        return true
      })
      .catch((e) => {
        notifyApiError(toast.error, e, '本集草稿收口失败')
        return false
      })
    if (!completionClosed) {
      return
    }
    const clearedSegmentProgress = target.episodeNo === selectedEpisode.value
      ? _clearCompletedEpisodeSegmentProgress(selectedEpisode.value, 'internal_segmented_episode_completed')
      : _clearCompletedEpisodeSegmentProgress(target.episodeNo, 'internal_segmented_episode_completed')
    if (clearedSegmentProgress) {
      await _syncProjectWorkflowContext({ immediate: true, silent: true })
    }
    const consumed = await _markManualEditGateConsumedAfterGeneration()
    if (!consumed) {
      toast.warning('内部四段审阅已保存，但上一集用户改稿接续状态回写失败。请刷新后确认再继续生成下一集。')
    }
    toast.success('内部四段审阅完成，共 ' + scriptNetCharCount.value + ' 净字，内容已自动保存')
    const wordCountWarning = _completedEpisodeWordCountWarning()
    if (wordCountWarning) toast.warning(wordCountWarning)
    void refreshScriptRuntimeSignals({ silent: true, autoApplySuggestions: true, deepAudit: true })
      .catch(() => {
        toast.warning('整集审查仍在后台处理，正文已保存，不影响继续生成下一集。')
      })
    _clearSegmentedGenerationTarget(target.episodeNo)
  },
  onConfirmedContentChanged: content => {
    activeSegmentDraftContent.value = content
    if (_isActiveSegmentTargetSelected()) {
      sceneContent.value = content
    }
  },
  onSegmentDraftReady: async () => {
    const target = _activeSegmentPersistenceTarget()
    const saved = await persistCurrentScriptContent({
      silent: true,
      changeNote: '分段草稿自动保存',
      editorType: 'ai',
      targetEpisodeNo: target.episodeNo,
      targetSceneNo: target.sceneNo,
      contentOverride: _activeSegmentContentForSave(),
      skipEpisodeReadyCheck: true,
    })
    await _persistCurrentSegmentProgress({ immediate: true })
    if (!saved) {
      toast.warning('当前段草稿已显示，但自动保存失败。请先点击保存后再切换页面。')
    }
  },
  approveSegment: idx => ensureSegmentInternallyApproved(idx, { silent: true, allowAutoFix: false }),
  approveFullScript: deepAudit => ensureScriptInternallyApproved({ silent: true, deepAudit, allowAutoFix: false }),
  afterSegmentConfirmed: async deepAudit => {
    const target = _activeSegmentPersistenceTarget()
    const saved = await persistCurrentScriptContent({
      silent: true,
      changeNote: '分段确认自动保存',
      editorType: 'ai',
      targetEpisodeNo: target.episodeNo,
      targetSceneNo: target.sceneNo,
      contentOverride: _activeSegmentContentForSave(),
      skipEpisodeReadyCheck: true,
    })
    if (!deepAudit) {
      await _persistCurrentSegmentProgress({ immediate: true })
    }
    if (!saved) {
      toast.warning('当前段已写入编辑器，但自动保存失败。请先点击保存后再继续切换页面。')
    }
  },
  getFailureAnalysis: () => scriptRuleValidation.value.failure_analysis || {},
  getBlockingIssues: () => _currentBlockingScriptIssues(),
  ensureOutlineGatePassed: () => ensureOutlineGatePassed({ episodeLimit: _activeSegmentPersistenceTarget().episodeNo }),
  persistProjectRules: () => persistProjectRules({ silent: true }),
  ensureManualEditSyncReady: _ensureManualEditReadyForGeneration,
  getSceneContent: () => _activeSegmentContentForSave(),
  resolveFirstSegmentLengthPolicy: () => _resolveRequestLengthPolicy({ mode: 'segment', segmentId: 'hook', currentContent: '' }),
  notify: {
    success: message => toast.success(message),
    error: message => toast.error(message),
    warning: message => toast.warning(message),
  },
})

let _segmentProgressSyncTimer: ReturnType<typeof setTimeout> | null = null
let _isHydratingSegmentProgress = false

function _scriptSegmentProgressStore() {
  const raw = (workflowContext.value as any).script_segment_progress
  return raw && typeof raw === 'object' && !Array.isArray(raw) ? raw as Record<string, any> : {}
}

function _scriptSegmentProgressKey(episodeNumber = selectedEpisode.value) {
  return String(Math.max(1, Math.round(Number(episodeNumber || 1) || 1)))
}

function _canRecoverStaleSegmentProgress(progress: any, savedContent: string, currentContent: string) {
  if (!currentContent.trim() || !savedContent.trim()) return false
  if (!currentContent.trim().startsWith(savedContent.trim())) return false
  const steps = Array.isArray(progress?.steps) ? progress.steps : []
  if (!steps.length) return false
  return steps.some((step: any) => {
    const status = String(step?.status || '')
    const hasDraft = Boolean(String(step?.editedContent || step?.versionA || step?.versionB || '').trim())
    return (status === 'reviewing' || status === 'generating') && !hasDraft
  })
}

function _currentScriptSegmentProgressSnapshot() {
  const progress = serializeSegmentProgress()
  const target = _activeSegmentPersistenceTarget()
  const content = _activeSegmentContentForSave()
  return {
    ...progress,
    episode_no: target.episodeNo,
    scene_no: target.sceneNo,
    scene_content: content,
    content_hash: simpleHash(content),
    updated_at: new Date().toISOString(),
  }
}

async function _persistCurrentSegmentProgress(options?: { immediate?: boolean }) {
  if (!project.value || isLoading.value || _isHydratingSegmentProgress) return
  const snapshot = _currentScriptSegmentProgressSnapshot()
  if (!snapshot.has_progress) return
  const key = _scriptSegmentProgressKey(snapshot.episode_no)
  const store = {
    ..._scriptSegmentProgressStore(),
    [key]: snapshot,
  }
  workflowContext.value = normalizeWorkflowContext(_deepMergeRecord(workflowContext.value, {
    script_segment_progress: store,
  }))
  if (options?.immediate) {
    await _syncProjectWorkflowContext({ immediate: true, silent: true })
  }
}

function _ruleBackedJobStatusToSegmentResult(latest: any, jobId = '') {
  const status = String(latest?.status || '')
  const candidate = latest?.candidate || {}
  const content = String(candidate.content || '').trim()
  if (!((status === 'candidate_ready' || status === 'candidate_review_required') && content)) {
    return null
  }
  return {
    content,
    warnings: [
      ...(Array.isArray(candidate.warnings) ? candidate.warnings.map((item: unknown) => String(item || '')).filter(Boolean) : []),
      latest?.word_count_warning ? String(latest.word_count_warning) : '',
    ].filter(Boolean),
    overflow_content: '',
    episode_memory_card: _normalizeEpisodeMemoryCard(candidate.episode_memory_card),
    canon_packet: _normalizeCanonPacket(candidate.canon_packet),
    rag_evidence: Array.isArray(candidate.rag_evidence) ? candidate.rag_evidence : [],
    director_blueprint: {},
    generation_trace: {
      backend_job_id: jobId,
      final_generation_contract_hash: String(latest?.final_generation_contract_hash || ''),
    },
  }
}

async function _hydrateSegmentProgressForEpisode(episodeNumber = selectedEpisode.value) {
  const key = _scriptSegmentProgressKey(episodeNumber)
  const progress = _scriptSegmentProgressStore()[key]
  if (!progress || typeof progress !== 'object') return false

  const savedContent = String(progress.scene_content || '')
  const currentContent = String(sceneContent.value || '')
  const savedHash = String(progress.content_hash || '')
  const currentHash = simpleHash(currentContent)
  const canRecoverStaleProgress = _canRecoverStaleSegmentProgress(progress, savedContent, currentContent)
  if (!currentContent.trim() && savedContent.trim() && _isExistingScriptOptedOut(episodeNumber)) {
    const cleared = _clearBlankEpisodeSegmentProgress(episodeNumber, 'skip_opted_out_existing_script_progress')
    if (cleared) {
      await _syncProjectWorkflowContext({ immediate: true, silent: true })
    }
    return false
  }
  if (currentContent.trim() && savedHash && currentHash !== savedHash && !canRecoverStaleProgress) {
    return false
  }

  _isHydratingSegmentProgress = true
  try {
    _startSegmentedGenerationTarget(episodeNumber, Number(progress.scene_no || selectedScene.value || 1))
    activeSegmentDraftContent.value = canRecoverStaleProgress ? currentContent : savedContent || currentContent
    if (!currentContent.trim() && savedContent.trim()) {
      sceneContent.value = savedContent
      await persistCurrentScriptContent({
        silent: true,
        changeNote: '恢复内部四段审阅草稿',
        editorType: 'ai',
        targetEpisodeNo: _activeSegmentPersistenceTarget().episodeNo,
        targetSceneNo: _activeSegmentPersistenceTarget().sceneNo,
        contentOverride: savedContent,
        skipEpisodeReadyCheck: true,
      })
    }
    const restored = hydrateSegmentProgress(progress)
    if (restored && savedContent.trim()) {
      _markSceneContentClean(sceneContent.value)
    }
    if (restored) {
      const recoverIdx = _candidateSaveSegmentConfirmIndex()
      if (recoverIdx >= 0) {
        await _recoverEmptySegmentCandidateForIndex(recoverIdx)
      }
    }
    return restored
  } finally {
    _isHydratingSegmentProgress = false
  }
}

watch(
  [segmentSteps, currentSegmentIdx, showSegmentPanel, selectedEpisode],
  () => {
    if (!_isScriptTabActive.value || _isHydratingSegmentProgress || isHydratingSceneContent.value || scenesLoading.value) return
    if (_segmentProgressSyncTimer) clearTimeout(_segmentProgressSyncTimer)
    _segmentProgressSyncTimer = setTimeout(() => {
      void _persistCurrentSegmentProgress()
    }, 800)
  },
  { deep: true },
)

async function _runRuleBackedScriptJob(
  requestPayload: Record<string, unknown>,
  onProgress?: (message: string) => void,
) {
  const authOptions = {
    userSessionToken: auth.userSession?.session_token,
    adminToken: auth.token,
  }
  const { data: started } = await adminConfigApi.startRuleBackedScriptJob(requestPayload, authOptions)
  const jobId = String(started.job_id || '')
  if (!jobId) {
    throw new RuleBackedScriptStreamError({
      detail: '后台生成任务没有返回任务编号',
      retryable: true,
      stage: 'script_scene_job_start',
    })
  }

  let latest = started
  const deadline = Date.now() + 8 * 60 * 1000
  while (Date.now() < deadline) {
    onProgress?.(String(latest.public_message || '正在生成本集正文...'))
    const status = String(latest.status || '')
    const candidateResult = _ruleBackedJobStatusToSegmentResult(latest, jobId)
    if (candidateResult) return candidateResult
    if (['failed', 'blocked', 'cancelled'].includes(status)) {
      throw new RuleBackedScriptStreamError({
        detail: String(latest.public_message || latest.user_action_required || '后台生成任务未产出可用候选稿'),
        suggestion: Array.isArray(latest.visible_issues) && latest.visible_issues.length
          ? latest.visible_issues.slice(0, 3).join('；')
          : '',
        retryable: status !== 'blocked',
        stage: status || 'script_scene_job',
        blocking_issues: Array.isArray(latest.visible_issues) ? latest.visible_issues : [],
      })
    }
    await new Promise(resolve => setTimeout(resolve, 2500))
    const { data } = await adminConfigApi.getRuleBackedScriptJobStatus(jobId, authOptions)
    latest = data
  }

  throw new RuleBackedScriptStreamError({
    detail: '后台生成任务超过 8 分钟仍未返回候选稿',
    suggestion: '请稍后从当前任务继续，或检查本集集纲、人物关系和模型配置。',
    retryable: true,
    stage: 'script_scene_job_timeout',
  })
}

async function _previewBackendGenerationSource(requestPayload: Record<string, unknown>) {
  const authOptions = {
    userSessionToken: auth.userSession?.session_token,
    adminToken: auth.token,
  }
  const { data } = await adminConfigApi.previewRuleBackedGenerationSource(requestPayload, authOptions)
  backendGenerationSourcePreview.value = (data.safe_summary || data) as unknown as Record<string, unknown>
  backendGenerationSourceStatus.value = data.status === 'ready' ? 'ready' : 'blocked'
  if (data.status !== 'ready') {
    const issues = Array.isArray(data.blocking_issues) ? data.blocking_issues : []
    scriptStreamStatus.value = '后端生成资料包未通过，请先补齐资料。'
    toast.error(issues.length ? `后端生成资料包未通过：${issues.join('；')}` : '后端生成资料包未通过')
    return false
  }
  scriptStreamStatus.value = '后端生成资料包预检通过，正在启动生成。'
  return true
}

async function _restoreLatestRuleBackedSegmentCandidate(idx: number, step: SegmentStep) {
  void idx
  const target = _activeSegmentPersistenceTarget()
  const authOptions = {
    userSessionToken: auth.userSession?.session_token,
    adminToken: auth.token,
  }
  try {
    const { data } = await adminConfigApi.getLatestRuleBackedScriptJob({
      project_id: projectId.value,
      episode_no: target.episodeNo,
      scene_no: target.sceneNo,
      segment_id: String(step.id || ''),
    }, authOptions)
    return _ruleBackedJobStatusToSegmentResult(data, String(data.job_id || ''))
  } catch (error: any) {
    if (error?.response?.status && error.response.status !== 404) {
      console.warn('restore latest segment candidate failed', error)
    }
    return null
  }
}

function _loadSuggestionsAsync(step: SegmentStep) {
  if (!step.editedContent.trim()) return
  step.isSuggesting = true
  const requestContext = _buildRuleBackedScriptRequest({
    mode: 'segment',
    segmentId: step.id as 'hook' | 'validation' | 'explosion' | 'resolution',
    currentContent: step.editedContent,
  })
  adminConfigApi.suggestSceneImprovement({
    project_id: projectId.value,
    scene_content: step.editedContent,
    audience_axis: outlineData.value.audience_axis || '',
    genre_main: outlineData.value.genre_main || '',
    episode_title: String(requestContext.episode_title || ''),
    episode_summary: String(requestContext.episode_summary || ''),
    episode_conflict: String(requestContext.episode_conflict || ''),
    episode_hook: String(requestContext.episode_hook || ''),
    segment_id: String(step.id || ''),
    confirmed_content: confirmedSegmentContent(),
    relationship_guardrails: String(requestContext.relationship_guardrails || ''),
    characters: Array.isArray(requestContext.characters) ? requestContext.characters : [],
    previous_episode_briefs: Array.isArray(requestContext.previous_episode_briefs) ? requestContext.previous_episode_briefs : [],
    episode_contract: requestContext.episode_contract && typeof requestContext.episode_contract === 'object' ? requestContext.episode_contract as Record<string, unknown> : {},
    issue_feedback: requestContext.issue_feedback && typeof requestContext.issue_feedback === 'object' ? requestContext.issue_feedback as Record<string, unknown> : {},
    rule_profile: String(requestContext.rule_profile || ''),
  }).then(({ data }) => {
    step.suggestions = data.suggestions || []
  }).catch(() => {
    step.suggestions = []
  }).finally(() => {
    step.isSuggesting = false
  })
}

function _currentBlockingScriptIssues() {
  return Array.isArray(scriptRuleValidation.value.blocking_issues)
    ? scriptRuleValidation.value.blocking_issues.map((item: any) => String(item || '').trim()).filter(Boolean)
    : []
}

// ─── 项目加载 ─────────────────────────────────────────────────────────────────
onMounted(async () => {
  isLoading.value = true
  window.addEventListener('beforeunload', handleBeforeUnload)
  loadTabState()
  await refreshUserPermissionSnapshot()
  // 乐观显示：如果项目列表 store 里已经有这个项目的元数据，先用它填充顶部，
  // 让用户在等服务器响应那一秒不至于看到空标题。await 之后会被服务端最新数据覆盖。
  const cached = projectsStore.findById(projectId.value)
  if (cached) project.value = cached as ProjectV2
  try {
    const [{ data }, providerRes, currentRes, summaryRes] = await Promise.all([
      projectsV2Api.get(projectId.value),
      v2ConfigApi.listProviders().catch(() => ({ data: [] as any[] })),
      v2ConfigApi.getCurrent().catch(() => ({ data: { provider: '', model: '', base_url: '', available_providers: [] } })),
      collaborationApi.getSummary(projectId.value).catch(() => ({ data: null as CollaborationSummary | null })),
    ])
    project.value = data
    collaborationSummary.value = summaryRes.data
    // 同步回 store：进编辑器后改动了项目元数据，列表页下次进来也是新的。
    projectsStore.upsertProject(data)
    generationProviders.value = Array.isArray(providerRes.data)
      ? providerRes.data.map((item: any) => ({
          id: String(item.id || ''),
          name: String(item.name || item.id || ''),
          models: Array.isArray(item.models)
            ? item.models.map((model: any) => ({
                value: String(model.value || ''),
                name: String(model.name || model.value || ''),
              }))
            : [],
        })).filter((item: any) => item.id)
      : []
    fallbackGenerationConfig.value = {
      provider: String(currentRes.data?.provider || ''),
      model: String(currentRes.data?.model || ''),
    }
    if (!outlineData.value.audience_axis && data.audience_axis) outlineData.value.audience_axis = data.audience_axis as any
    if (!outlineData.value.genre_main && data.genre_main) outlineData.value.genre_main = data.genre_main
    _applyProjectRules(data.config)
    _applyGenerationDefaults()
    try {
      const characterStore = await projectsV2Api.getCharacters(projectId.value)
      if (Array.isArray(characterStore.data.characters) && characterStore.data.characters.length > 0) {
        const sanitizedCharacters = _sanitizeWorkspaceCharacterRows(characterStore.data.characters as any[])
        characters.value = sanitizedCharacters as any[]
        if (JSON.stringify(sanitizedCharacters) !== JSON.stringify(characterStore.data.characters)) {
          await projectsV2Api.saveCharacters(projectId.value, sanitizedCharacters as Array<Record<string, any>>)
        }
      }
    } catch {}
    try {
      const stateCardStore = await projectsV2Api.getStateCards(projectId.value)
      storyStateCards.value = normalizeStoryStateCards(stateCardStore.data)
    } catch {}
    try {
      const workflowStore = await projectsV2Api.getWorkflowContext(projectId.value)
      _applyWorkflowContextResponse(workflowStore.data)
      hydrateChatBrainstormState(workflowStore.data.workflow_context?.chat_brainstorm)
      _hydrateOutlineStateFromWorkflow(workflowStore.data.workflow_context?.outline_state)
    } catch {}
    lastProjectRulesSignature.value = _currentProjectRulesSignature()
  } catch (e: any) {
    // 服务端 404 / 项目真不存在 → 跳回项目中心
    // 否则（网络抖动、超时）：只在用户没有缓存数据时跳转，否则保留当前 UI 让用户继续看
    const status = e?.response?.status
    if (status === 404) {
      toast.error('项目不存在或已被删除')
      router.push('/projects')
      return
    }
    if (!cached) {
      notifyApiError(toast.error, e, '项目加载失败')
      router.push('/projects')
      return
    }
    // 有缓存就软提示，不强制跳转
    toast.warning('项目数据加载失败，正在使用缓存数据')
  } finally {
    isLoading.value = false
  }

  await bootstrapQueryPromptFromRoute()

  if (ensureChatPreparationGate({ silent: true })) {
    toast.warning('请先在聊天脑暴完成选题，或在大纲页上传/解析已有大纲。')
  }

  if (_isOutlineCommittedToMainChain() && outlineData.value.episodes.length) {
    await _refreshSeriesSimulationPacket('project_loaded_outline_snapshot', { silent: true })
  }

  // load episodes if script tab
  if (activeTab.value === 'script') {
    await ensureOutlineExistingScriptsSeeded({ silent: true })
    await loadEpisodes()
    await ensureCurrentEpisodeExistingScriptVisible(selectedEpisode.value, { silent: true })
    if (!_restoreCandidateSnapshotIfEditorBlank(selectedEpisode.value)) {
      await _restoreLatestJobCandidateIfEditorBlank(selectedEpisode.value)
    }
    await _hydrateSegmentProgressForEpisode(selectedEpisode.value)
  }
})

watch(activeTab, async (tab) => {
  if (tab === 'script') {
    await ensureOutlineExistingScriptsSeeded({ silent: true })
    await loadEpisodes()
    await ensureCurrentEpisodeExistingScriptVisible(selectedEpisode.value, { silent: true })
    if (!_restoreCandidateSnapshotIfEditorBlank(selectedEpisode.value)) {
      await _restoreLatestJobCandidateIfEditorBlank(selectedEpisode.value)
    }
    await _hydrateSegmentProgressForEpisode(selectedEpisode.value)
  }
  if (tab === 'export' || tab === 'storyboard') await refreshUserPermissionSnapshot()
})

// ─── 组件卸载清理：清除剩余防抖定时器 ───────────────────────────────────
// stateCards / workflowContext 的 timer 已搬到 useStoryStateAutosave 自管理；
// _characterSyncTimer 已搬到 useCharacterTab；这里只负责剩下的本地 timer。
onUnmounted(() => {
  window.removeEventListener('beforeunload', handleBeforeUnload)
  if (_projectRuleSyncTimer) { clearTimeout(_projectRuleSyncTimer); _projectRuleSyncTimer = null }
  if (_charDetectTimer) { clearTimeout(_charDetectTimer); _charDetectTimer = null }
  if (_ruleValidationTimer) { clearTimeout(_ruleValidationTimer); _ruleValidationTimer = null }
  if (_segmentProgressSyncTimer) { clearTimeout(_segmentProgressSyncTimer); _segmentProgressSyncTimer = null }
  if (_analysisContentTimer) { clearTimeout(_analysisContentTimer); _analysisContentTimer = null }
})

// ─── 分镜提示词 Tab ──────────────────────────────────────────────────────────
const storyboardContent = ref('')
const storyboardEpisode = ref(1)
// 切到分镜 Tab 时，自动跟随你正在写的那一集，避免每次都要再下拉选一遍。
// 如果切到分镜后用户在分镜里手动改集，那个改动会留下不被覆盖。
watch(activeTab, (tab, prevTab) => {
  if (tab === 'storyboard' && prevTab !== 'storyboard') {
    if (selectedEpisode.value > 0) storyboardEpisode.value = selectedEpisode.value
  }
})

// ─── 导出 Tab ─────────────────────────────────────────────────────────────────
const savedScriptSceneCount = computed(() => {
  return (episodes.value as any[]).reduce((total, episode) => {
    return total + Math.max(0, Math.round(Number(episode?.completed_scenes || 0) || 0))
  }, 0)
})

const exportReadinessItems = computed(() => [
  {
    id: 'chat',
    label: '聊天脑暴',
    ready: hasPreparedOutlineFromChat(),
    message: '未形成可保存资料包',
  },
  {
    id: 'outline',
    label: '大纲编辑',
    ready: _isOutlineCommittedToMainChain(),
    message: '大纲尚未锁定',
  },
  {
    id: 'characters',
    label: '角色设计',
    ready: (characters.value as any[]).length > 0,
    message: '角色库为空',
  },
  {
    id: 'script',
    label: '剧本写作',
    ready: savedScriptSceneCount.value > 0,
    message: '暂无已保存正文',
  },
])

const { exportFormats, exportProject } = useProjectExport({
  project,
  projectRules,
  outlineData,
  characters,
  sceneContent,
  selectedEpisode,
  selectedScene,
  storyboardEpisode,
  storyboardContent,
  markTabComplete: () => markTabComplete('export'),
})

async function guardedExportProject(format: string) {
  await refreshUserPermissionSnapshot()
  if (copyExportLocked.value) {
    toast.warning(copyExportLockedMessage)
    return
  }
  await exportProject(format)
}
</script>

<template>
  <div
    v-if="!isLoading"
    class="h-[calc(100vh-3.5rem)] flex flex-col bg-background"
    @copy.capture="preventCopyExport"
    @cut.capture="preventCopyExport"
    @dragstart.capture="preventCopyExport"
    @keydown.capture="handleWorkspaceKeydown"
  >

    <WorkspaceHeader
      :project-name="project?.name || ''"
      :progress-percent="realProgressPercent"
      :tabs="tabs"
      :active-tab="activeTab"
      :completed-tabs="completedTabs"
      :ai-panel-open="activeTab !== 'chat' && aiPanelOpen"
      :show-ai-panel="activeTab !== 'chat'"
      @back="router.push('/projects')"
      @toggle-ai-panel="aiPanelOpen = !aiPanelOpen"
      @switch-tab="(tab) => switchTab(tab as WorkspaceTabId)"
    />

    <!-- ── 主内容区 ── -->
    <div class="flex-1 flex overflow-hidden relative">

      <!-- Tab内容 -->
      <div class="flex-1 min-w-0 overflow-hidden flex flex-col">

        <!-- ══ 聊天脑暴 ══ -->
        <template v-if="activeTab === 'chat'">
          <div class="flex-1 min-w-0 flex overflow-hidden">
            <ChatTab
              :messages="chatMessages"
              :loading="chatLoading"
              :submit-chat="sendChatMessage"
              :max-message-chars="CHAT_MESSAGE_MAX_CHARS"
              :context-trace="lastContextTrace"
              :context-blocked="chatContextBlocked"
              :open-outline-for-context="openOutlineForChatContext"
              :save-status="chatSaveStatus"
              :retry-save="retryChatBrainstormSave"
              :reference-loading="chatReferenceLoading"
              @upload-reference="handleChatReferenceUpload"
            />
            <OutlineConfirmationPanel
              :packet="standardOutlinePacket"
              :organizing="outlineLoading"
              :confirming-section="confirmingSection"
              :reference-loading="chatReferenceLoading"
              @organize="generateOutlineFromChat"
              @confirm="confirmOutlineEditorSection"
              @open-outline="openOutlineForChatContext"
            />
          </div>
        </template>

        <!-- ══ 大纲编辑 ══ -->
        <template v-if="activeTab === 'outline'">
          <div class="flex-1 flex flex-col overflow-hidden">
            <!-- 顶栏 -->
            <OutlineTabHeader
              :character-count="outlineCharacters.length"
              :episode-count="outlineData.episodes.length"
              :saving="projectRulesSaving"
              :commit-blocked="outlineMainChainCommitBlocked"
              :commit-block-reason="outlineMainChainCommitBlockReason"
              @save="saveOutline"
              @continue="saveOutlineAndContinue"
            />

            <OutlineTabBody
              v-model:raw-outline-text="rawOutlineText"
              v-model:outline-data="outlineData"
              v-model:outline-characters="outlineCharacters"
              v-model:project-rules="projectRules"
              :role-colors="roleColors"
              :is-analyzing-outline="isAnalyzingOutline"
              :outline-analyze-status="outlineAnalyzeStatus"
              :is-predicting-outline="isPredictingOutline"
              :outline-ai-generated-fields="outlineAiGeneratedFields"
              :is-generating-episodes="isGeneratingEpisodes"
              :project-rules-saving="projectRulesSaving"
              :section-loading="sectionLoading"
              :section-suggestions="sectionSuggestions"
              :generation-providers="generationProviders"
              :available-generation-models="availableGenerationModels"
              :ai-features-paused="outlineAiFeaturesPaused"
              :outline-main-chain-status-text="outlineMainChainStatusText"
              :outline-main-chain-commit-blocked="outlineMainChainCommitBlocked"
              :outline-main-chain-commit-block-reason="outlineMainChainCommitBlockReason"
              @analyze-outline="analyzeOutline"
              @upload-outline-file="handleOutlineFileUpload"
              @get-ai-suggestion="getAISuggestion"
              @add-outline-character="addOutlineCharacter"
              @remove-outline-character="removeOutlineCharacter"
              @generate-episodes="generateEpisodes"
              @add-episode="addEpisode"
              @switch-tab="switchTab"
              @save-outline-and-continue="saveOutlineAndContinue"
            />
          </div>
        </template>


        <!-- ══ 角色设计 ══ -->
        <template v-if="activeTab === 'characters'">
          <CharacterTab
            v-model:selected-character-id="selectedCharacterId"
            v-model:show-character-graph="showCharacterGraph"
            :project-id="projectId"
            :characters="characters"
            :role-colors="roleColors"
            :scene-content="sceneContent"
            :genre="outlineData.genre_main || ''"
            @add-character="addCharacter"
            @remove-character="removeCharacter"
            @update-character="updateCharacter"
            @add-relationship="addRelationship"
            @back="switchTab('outline')"
            @next="goToNextWorkspaceTab"
          />
        </template>

        <!-- ══ 剧本写作 ══ -->
        <template v-if="activeTab === 'script'">
          <div class="flex-1 flex overflow-hidden">
            <ScriptSidebar
              :episodes="episodes"
              :scenes="scenes"
              :selected-episode="selectedEpisode"
              :selected-scene="selectedScene"
              :is-creating-episode="isCreatingEpisode"
              :is-creating-scene="isCreatingScene"
              :scenes-loading="scenesLoading"
              :total-episodes="projectRules.total_episodes"
              @load-episode="loadScriptEpisode"
              @select-scene="selectScriptScene"
              @create-episode="createEpisode"
              @create-episodes-batch="createEpisodesBatch"
              @create-scene="createScene"
              @save-episode="saveEpisodeFromSidebar"
              @delete-episode="deleteEpisode"
            />

            <!-- 中间：编辑器 -->
            <div class="flex-1 flex flex-col min-w-0 overflow-y-auto">
              <ScriptToolbar
                :project-id="projectId"
                :selected-episode="selectedEpisode"
                :selected-scene="selectedScene"
                :project-rules="projectRules"
                :show-floating-graph="showFloatingGraph"
                :current-ep-existing-script="currentEpExistingScript"
                :scene-content="sceneContent"
                :is-validating-script-rules="isValidatingScriptRules"
                :is-generating-script="isGeneratingScript"
                :is-segment-generating="isSegmentGenerating"
                :is-saving-script="isSavingScript"
                :is-segmented-in-progress="_hasSegmentedWritingProgress()"
                @open-floating-graph="openFloatingGraph"
                @load-existing-script="loadExistingScript"
                @run-script-rule-validation="runScriptRuleValidation()"
                @generate-script="runSegmentedWritingWithEpisode"
                @stop-generating-script="stopGeneratingScript"
                @save-script="saveScript"
              />

              <SegmentReviewPanel
                v-model:show-segment-panel="showSegmentPanel"
                :segment-steps="segmentSteps"
                :current-segment-idx="currentSegmentIdx"
                :current-segment-step="currentSegmentStep"
                :is-segment-generating="isSegmentGenerating"
                :count-script-chars="_countScriptChars"
                :generation-target="activeSegmentReviewTarget"
                @switch-version="segmentSwitchVersion"
                @enter-edit="segmentEnterEdit"
                @exit-edit="segmentExitEdit"
                @apply-patch="segmentApplyPatch"
                @retry="_handleSegmentRetry"
                @confirm="_handleSegmentConfirm"
                @generate-variant="_handleSegmentGenerateVariant"
              />

              <ScriptSceneStatusPanel
                :characters="characters"
                :script-scene-characters="scriptSceneCharacters"
                :is-validating-script-rules="isValidatingScriptRules"
                :is-auto-fixing-script="isAutoFixingScript"
                :script-stream-status="scriptStreamStatus"
                :workflow-chain-status="workflowChainStatus"
                :show-rag-evidence="showRagEvidenceDiagnostics"
                :latest-rag-evidence-log="latestRagEvidenceLog"
                :role-color-for="roleColorFor"
                @toggle-character="toggleManualSceneCharacter"
              />

              <ScriptStepConfirmationPanel
                :selected-episode="selectedEpisode"
                :workflow-steps="scriptWorkflowSteps"
                :script-stream-status="scriptStreamStatus"
                :is-generating-script="isGeneratingScript || isSegmentGenerating"
                :confirmation-packet="currentStepConfirmationPacket"
                @regenerate-step="_handleRegenerateConfirmationStep"
                @save-candidate="_handleStepCandidateSave"
                @focus-editor="focusScriptEditor"
                @update-confirmation-item="_upsertStepConfirmationOverride"
                @commit-confirmation-item="_commitStepConfirmationOverride"
                @commit-confirmation-step="_commitStepConfirmationStep"
              />

              <RagEvidenceHistoryPanel
                v-if="showRagEvidenceDiagnostics"
                :logs="ragEvidenceLogs"
                :selected-episode="selectedEpisode"
              />

              <ScriptEditorPanel
                v-model:scene-content="sceneContent"
                :script-net-char-count="scriptNetCharCount"
                :project-rules="projectRules"
                :selected-episode="selectedEpisode"
                :has-unsaved-changes="hasUnsavedSceneChanges()"
                :is-pending-model-candidate="isCurrentPendingModelCandidate"
                :manual-edit-markers="manualEditLineMarkers"
                :can-lock-current-episode="canLockCurrentEpisode"
                :is-locking-current-episode="isGeneratingNextEpisode && !currentEpisodeOfficiallyLocked"
                :can-generate-next-episode="canGenerateNextEpisode"
                :is-generating-next-episode="isGeneratingNextEpisode"
                :is-segmented-draft-incomplete="isSegmentedDraftIncomplete"
                :next-episode-gate-message="nextEpisodeGateMessage"
                @lock-current-episode="lockCurrentEpisodeFromWorkspace"
                @next="goToNextWorkspaceTab"
                @generate-next-episode-research="runNextEpisodeSegmentedWriting"
              />
            </div>

            <!--
              健康侧栏对用户隐藏（v-if=false）。下面 props 关联的 computed
              （characterHealth、scriptDeepAudit、scriptRuleValidation、
              activeStoryStateCards 等）数据流保留——AI 生成与提示词构造
              仍消费这些值。Vue computed 惰性：没模板订阅就不会在切集时
              频繁重算，顺手解决一部分卡顿。
            -->
            <ScriptHealthPanel
              v-if="false"
              :character-health="characterHealth"
              :workflow-chain-status="workflowChainStatus"
              :current-head-contract-items="currentHeadContractItems"
              :head-gate-issues="headGateIssues"
              :script-deep-audit="scriptDeepAudit"
              :active-story-state-cards="activeStoryStateCards"
              :pending-state-card-suggestions="pendingStateCardSuggestions"
              :scene-relationship-diagnostics="sceneRelationshipDiagnostics"
              :pending-relationship-suggestions="pendingRelationshipSuggestions"
              :characters="characters"
              :script-scene-characters="scriptSceneCharacters"
              :role-colors="roleColors"
              :script-rule-validation="scriptRuleValidation"
              :selected-episode="selectedEpisode"
              :script-net-char-count="scriptNetCharCount"
              :scene-content="sceneContent"
              :role-color-for="roleColorFor"
              @add-story-state-card="addStoryStateCard"
              @accept-state-card-suggestion="acceptStateCardSuggestion"
              @dismiss-state-card-suggestion="dismissStateCardSuggestion"
              @remove-story-state-card="removeStoryStateCard"
              @toggle-state-card-character="toggleStateCardCharacter"
              @accept-relationship-suggestion="acceptRelationshipSuggestion"
              @dismiss-relationship-suggestion="dismissRelationshipSuggestion"
            />
          </div>
        </template>

        <FloatingCharacterGraph
          v-model:show-floating-graph="showFloatingGraph"
          :characters="characters"
          :role-colors="roleColors"
          :present-character-ids="scriptSceneCharacters"
          :active-relation-keys="sceneRelationshipDiagnostics.activeKeys"
          :script-content="sceneContent"
          :position="floatGraphPos"
          @start-drag="startFloatGraphDrag"
          @select-character="toggleManualSceneCharacter"
        />

        <!-- ══ 合规审核 ══ -->
        <template v-if="activeTab === 'compliance'">
          <ComplianceReviewTab
            :project-id="projectId"
          />
        </template>

        <!-- ══ 分镜预览（升级版：结构化分镜 + 五平台提示词） ══ -->
        <template v-if="activeTab === 'storyboard'">
          <StoryboardTab
            v-model:storyboard-episode="storyboardEpisode"
            :project-id="projectId"
            :outline-episodes="outlineData.episodes"
            :copy-export-locked="copyExportLocked"
            @mounted="markTabComplete('storyboard')"
          />
        </template>

        <!-- ══ 导出生成 ══ -->
        <template v-if="activeTab === 'export'">
          <ExportTab
            :readiness-items="exportReadinessItems"
            :export-formats="exportFormats"
            :copy-export-locked="copyExportLocked"
            @export-project="guardedExportProject"
          />
        </template>

        <!-- ══ 法律资产包 ══ -->
        <template v-if="activeTab === 'legal-assets'">
          <LegalAssetsTab
            :project-id="projectId"
          />
        </template>

      </div>

      <!-- ── 右侧 AI 辅助面板 ── -->
      <AiAssistantPanel
        v-if="aiPanelOpen && activeTab !== 'chat'"
        class="relative inset-auto z-auto shadow-none xl:relative"
        :messages="aiMessages"
        :quick-prompts="quickPrompts"
        :loading="aiLoading"
        @send="sendAIMessage"
        @close="aiPanelOpen = false"
      />

    </div>
  </div>

  <!-- 加载中 -->
  <div v-else class="h-[calc(100vh-3.5rem)] flex items-center justify-center">
    <div class="text-center">
      <RefreshCw class="h-8 w-8 animate-spin text-primary mx-auto mb-3" />
      <p class="text-muted-foreground">加载项目中...</p>
    </div>
  </div>
</template>
