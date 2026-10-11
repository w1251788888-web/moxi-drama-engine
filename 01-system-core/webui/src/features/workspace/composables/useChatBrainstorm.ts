import { onUnmounted, ref, watch, type Ref } from 'vue'
import { projectsV2Api, userAccessApi } from '@/api/client'
import {
  extractAiError,
  formatAccessErrorMessage,
  formatAiErrorMessage,
  formatUserFacingErrorMessage,
} from '@/api/http'
import {
  OUTLINE_EDITOR_CONFIRMATION_SECTIONS,
  applyOutlineEditorSectionConfirmation,
  outlineEditorSectionStatus,
  type OutlineEditorConfirmationDraft,
  type OutlineEditorConfirmationSectionId,
} from '@/features/workspace/utils/outlineEditorConfirmation'
import {
  createStandardOutlinePacket,
  mergeStandardOutlinePacket,
  normalizeStandardOutlinePacket,
  projectStandardOutlinePacketToOutline,
  standardOutlineField,
  type StandardOutlineField,
  type StandardOutlinePacket,
} from '@/features/workspace/utils/standardOutlinePacket'
import {
  buildBoundedConversationSource,
  buildChatContextPacket,
  buildCurrentChatRequestSnapshot,
  CHAT_CONTEXT_MAX_CHARS,
  CHAT_MESSAGE_MAX_CHARS,
  countContextChars,
  createChatSendLock,
  createSequentialSaveCoordinator,
  mergeChatBrainstormState,
  normalizeChatBrainstormState,
  reconcileSavedChatBrainstormState,
  shouldApplyReconciledChatState,
  type BrainstormChatMessage,
  type BrainstormChatState,
  type ChatContextTrace,
} from '@/features/workspace/utils/chatBrainstormContext'
import { loadWorkspaceStorage, saveWorkspaceStorage } from '@/features/workspace/utils/workspaceStorage'

type ChatMessage = BrainstormChatMessage
type PendingChatMessage = Pick<ChatMessage, 'role' | 'content'> & Partial<Pick<ChatMessage, 'id' | 'created_at'>>

type OutlineEpisode = {
  ep: number
  title: string
  hook: string
  summary: string
  conflict?: string
  turning?: string
  main_scene?: string
  relationship_change?: string
  info_revealed?: string
  satisfaction_type?: string
  existing_script?: string
}

type RangeOutline = {
  start: number
  end: number
  title: string
  summary: string
}

type OutlineData = {
  audience_axis?: '男频' | '女频' | '混合' | ''
  genre_main?: string
  format_type?: '真人短剧' | '漫剧' | 'AI真人'
  logline?: string
  worldview?: string
  goldenFinger?: string
  conflict?: string
  episode_count?: number
  rangeOutlines?: RangeOutline[]
  episodes?: OutlineEpisode[]
}

type OutlineCharacter = {
  id: string
  name: string
  role: 'protagonist' | 'antagonist' | 'supporting' | 'minor'
  info: string
  relationships?: Array<Record<string, unknown> | string>
}

type AiChatParams = Parameters<typeof userAccessApi.aiChat>[0]

interface UseChatBrainstormOptions {
  projectId?: Ref<string>
  outlineData: Ref<OutlineData>
  outlineCharacters?: Ref<OutlineCharacter[]>
  standardOutlinePacket?: Ref<StandardOutlinePacket | Record<string, unknown>>
  episodeCount?: () => number
  switchToOutline: () => void
  markChatTabComplete: () => void
  notify: {
    success: (message: string) => void
    error?: (message: string) => void
    warning?: (message: string) => void
  }
  onOutlineGenerated?: (payload: {
    rawOutlineText: string
    standardOutlinePacket?: StandardOutlinePacket
  }) => boolean | void | Promise<boolean | void>
}

interface OrganizedOutlinePayload {
  creative_direction?: {
    audience_axis?: unknown
    genre_main?: unknown
    format_type?: unknown
  }
  logline?: unknown
  world_and_conflict?: {
    worldview?: unknown
    golden_finger?: unknown
    conflict?: unknown
  }
  characters?: unknown
  relationships?: unknown
  episode_plan?: {
    total_episodes?: unknown
  }
  episode_outlines?: unknown
  quality_gaps?: unknown
}

export interface ChatReferenceDocument {
  filename: string
  text: string
  truncated?: boolean
}

const CHAT_REFERENCE_MAX_CHARS = 60_000
const CHAT_REFERENCE_CHUNK_CHARS = 9_000

const CHAT_BRAINSTORM_SYSTEM_PROMPT = `你是短剧选题策划，也是用户的创作脑暴伙伴。

当前窗口只负责自然对话、灵感发散和基于上下文继续讨论：
- 直接理解用户本轮自然语言，并结合完整聊天上下文给出有用的新灵感、修改方案或下一步内容。
- 用户说“继续”“下一步”或“好的”时，根据对话语义自然承接，不要复述上一轮，也不要宣称切换了隐藏流程。
- AI 的回复只是建议，不代表用户确认，不得自行把聊天内容写成已确认的大纲字段。
- 右侧大纲确认区由用户主动点击“整理当前讨论”后生成候选，再由用户逐项编辑和确认。
- 不连续盘问；信息不足时先给可用方案，再补一个真正影响方向的问题。
- 用中文，具体、简洁、有创作启发。`

const OUTLINE_ORGANIZER_SYSTEM_PROMPT = `你负责把聊天脑暴整理成“大纲编辑器可以直接识别”的候选字段。

边界：
1. 只整理聊天中已经出现的内容，不推断用户没有给出的事实。
2. 所有输出都是候选，不代表用户确认。
3. 只能使用下方 JSON 字段；不得输出范围集纲、长线结构、start_state、end_state、next_hook、hook 或其他编辑器没有的字段。
4. 人物小传只使用 name、role、info；人物关系单独放 relationships。
5. 分集集纲只使用 ep、title、summary、conflict、turning、main_scene、relationship_change、info_revealed、satisfaction_type。
6. 缺少的内容使用空字符串或空数组，并把缺口写入 quality_gaps。
7. 只输出合法 JSON，不输出 Markdown 或解释。`

const REFERENCE_SUMMARY_SYSTEM_PROMPT = `你是短剧选题策划。请读取用户上传剧本的当前分块，只提取可供后续脑暴引用的事实：
- 核心人物与身份
- 人物关系
- 已发生的关键事件及因果
- 世界设定
- 核心冲突
- 尚未解决的问题
不得补写原文没有的内容。用中文压缩成清晰摘要，不输出大纲确认状态。`

function text(value: unknown): string {
  return value === null || value === undefined ? '' : String(value).trim()
}

function integer(value: unknown): number {
  const parsed = Math.round(Number(value))
  return Number.isFinite(parsed) && parsed > 0 ? parsed : 0
}

function record(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {}
}

function array(value: unknown): unknown[] {
  return Array.isArray(value) ? value : []
}

function normalizeRole(value: unknown): OutlineCharacter['role'] {
  const normalized = text(value).toLowerCase()
  if (/主角|男主|女主|protagonist|lead/.test(normalized)) return 'protagonist'
  if (/反派|对手|antagonist|villain/.test(normalized)) return 'antagonist'
  if (/次要|客串|minor|cameo/.test(normalized)) return 'minor'
  return 'supporting'
}

function parseJsonObject(raw: string): OrganizedOutlinePayload {
  const fenced = raw.match(/```(?:json)?\s*([\s\S]*?)```/i)
  const body = (fenced?.[1] || raw).trim()
  const start = body.indexOf('{')
  const end = body.lastIndexOf('}')
  if (start < 0 || end <= start) throw new Error('AI 没有返回可解析的候选字段')
  return JSON.parse(body.slice(start, end + 1)) as OrganizedOutlinePayload
}

function normalizeCharacters(raw: unknown): Array<Record<string, unknown>> {
  return array(raw).map((item, index) => {
    const row = record(item)
    return {
      id: text(row.id) || `chat-candidate-character-${index + 1}`,
      name: text(row.name),
      role: normalizeRole(row.role),
      info: text(row.info),
    }
  }).filter(item => item.name || item.info)
}

function normalizeRelationships(raw: unknown): Array<Record<string, unknown>> {
  return array(raw).map((item) => {
    const row = record(item)
    return {
      source: text(row.source),
      targetName: text(row.targetName || row.target_name || row.target),
      earlyType: text(row.earlyType || row.early_type),
      lateType: text(row.lateType || row.late_type),
      transitionEpisode: integer(row.transitionEpisode || row.transition_episode) || null,
      finalBoundary: text(row.finalBoundary || row.final_boundary),
      description: text(row.description),
    }
  }).filter(item => (
    item.source || item.targetName || item.earlyType || item.lateType || item.description
  ))
}

function normalizeEpisodes(raw: unknown): Array<Record<string, unknown>> {
  return array(raw).map((item, index) => {
    const row = record(item)
    return {
      ep: integer(row.ep || row.episode || row.episode_number) || index + 1,
      title: text(row.title),
      summary: text(row.summary || row.episode_outline),
      conflict: text(row.conflict),
      turning: text(row.turning),
      main_scene: text(row.main_scene),
      relationship_change: text(row.relationship_change),
      info_revealed: text(row.info_revealed),
      satisfaction_type: text(row.satisfaction_type),
    }
  }).filter(item => item.title || item.summary)
}

function normalizeTextArray(value: unknown): string[] {
  return array(value).map(text).filter(Boolean)
}

function fieldIsConfirmed(field: StandardOutlineField | undefined) {
  return field?.status === 'confirmed' && field.source === 'user_confirmed'
}

function preserveConfirmedRecord(
  existing: Record<string, StandardOutlineField>,
  candidate: Record<string, StandardOutlineField>,
) {
  const entries = Object.keys({ ...existing, ...candidate }).flatMap((key) => {
    const value = fieldIsConfirmed(existing[key])
      ? existing[key]
      : candidate[key] || existing[key]
    return value ? [[key, value] as const] : []
  })
  return Object.fromEntries(entries) as Record<string, StandardOutlineField>
}

function preserveConfirmedField<T>(
  existing: StandardOutlineField<T>,
  candidate: StandardOutlineField<T>,
) {
  return fieldIsConfirmed(existing) ? existing : candidate
}

function firstUnconfirmedEditorSection(packet: StandardOutlinePacket) {
  return OUTLINE_EDITOR_CONFIRMATION_SECTIONS.find(
    section => outlineEditorSectionStatus(packet, section.id) !== 'confirmed',
  )?.id || ''
}

function mergeCandidateWithoutOverwritingConfirmed(
  existingRaw: unknown,
  candidateRaw: unknown,
): StandardOutlinePacket {
  const existing = normalizeStandardOutlinePacket(existingRaw)
  const candidate = normalizeStandardOutlinePacket(candidateRaw)
  let merged = mergeStandardOutlinePacket(existing, {
    source_material: candidate.source_material,
    project_profile: preserveConfirmedRecord(existing.project_profile, candidate.project_profile),
    story_core: preserveConfirmedRecord(existing.story_core, candidate.story_core),
    world_rules: preserveConfirmedRecord(existing.world_rules, candidate.world_rules),
    characters: preserveConfirmedField(existing.characters, candidate.characters),
    relationship_timeline: preserveConfirmedField(
      existing.relationship_timeline,
      candidate.relationship_timeline,
    ),
    episode_count_plan: preserveConfirmedRecord(
      existing.episode_count_plan,
      candidate.episode_count_plan,
    ),
    episode_outlines: preserveConfirmedField(existing.episode_outlines, candidate.episode_outlines),
    quality_gaps: candidate.quality_gaps,
    conflict_issues: candidate.conflict_issues,
    user_confirmed_fields: existing.user_confirmed_fields,
  })
  const currentStage = firstUnconfirmedEditorSection(merged)
  merged = mergeStandardOutlinePacket(merged, {
    current_stage: currentStage,
    status: currentStage ? 'needs_user_confirmation' : 'confirmed',
  })
  return merged
}

function candidatePacketFromPayload(
  payload: OrganizedOutlinePayload,
  sourceText: string,
): StandardOutlinePacket {
  const direction = record(payload.creative_direction)
  const world = record(payload.world_and_conflict)
  const episodePlan = record(payload.episode_plan)
  const characters = normalizeCharacters(payload.characters)
  const relationships = normalizeRelationships(payload.relationships)
  const episodes = normalizeEpisodes(payload.episode_outlines)
  const totalEpisodes = integer(episodePlan.total_episodes)
  const now = new Date().toISOString()
  const packet = createStandardOutlinePacket({
    outlineData: {
      audience_axis: text(direction.audience_axis),
      genre_main: text(direction.genre_main),
      format_type: text(direction.format_type),
      logline: text(payload.logline),
      worldview: text(world.worldview),
      goldenFinger: text(world.golden_finger),
      conflict: text(world.conflict),
      episode_count: totalEpisodes,
      episodes,
    },
    characters,
    source_material: {
      kind: 'chat_synthesis',
      raw_text: sourceText,
      captured_at: now,
    },
    confirmed: false,
    status: 'needs_user_confirmation',
    current_stage: 'creative_direction',
  })
  packet.relationship_timeline = standardOutlineField(
    relationships,
    relationships.length ? 'candidate' : 'missing',
    relationships.length ? 'model_suggested' : 'system_inferred',
    now,
  )
  packet.quality_gaps = normalizeTextArray(payload.quality_gaps)
  packet.range_outlines = standardOutlineField([], 'missing', 'system_inferred', now)
  packet.long_arc.summary = standardOutlineField('', 'missing', 'system_inferred', now)
  return packet
}

function outlineOrganizerPrompt(source: string) {
  return `请把下面聊天记录整理成候选字段。

输出 JSON 结构：
{
  "creative_direction": {
    "audience_axis": "",
    "genre_main": "",
    "format_type": ""
  },
  "logline": "",
  "world_and_conflict": {
    "worldview": "",
    "golden_finger": "",
    "conflict": ""
  },
  "characters": [
    {"name": "", "role": "protagonist|antagonist|supporting|minor", "info": ""}
  ],
  "relationships": [
    {
      "source": "",
      "targetName": "",
      "earlyType": "",
      "lateType": "",
      "transitionEpisode": null,
      "finalBoundary": "",
      "description": ""
    }
  ],
  "episode_plan": {"total_episodes": null},
  "episode_outlines": [
    {
      "ep": 1,
      "title": "",
      "summary": "",
      "conflict": "",
      "turning": "",
      "main_scene": "",
      "relationship_change": "",
      "info_revealed": "",
      "satisfaction_type": ""
    }
  ],
  "quality_gaps": []
}

聊天记录：
${source}`
}

function defaultChatMessages(): ChatMessage[] {
  return [
    {
      id: 'chat-brainstorm-welcome-v3',
      role: 'ai',
      content: '把题材、人物、关系、场景或一句模糊的想法告诉我，我们先自由讨论。需要沉淀时，点击右侧“整理当前讨论”，再逐项修改和确认。',
      created_at: '2000-01-01T00:00:00.000Z',
    },
  ]
}

function newChatMessageId(): string {
  if (typeof globalThis.crypto?.randomUUID === 'function') return globalThis.crypto.randomUUID()
  return `chat-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 14)}`
}

function loadLocalChatState(projectId?: string): BrainstormChatState {
  if (!projectId) return normalizeChatBrainstormState([], 'unscoped')
  try {
    return normalizeChatBrainstormState(
      JSON.parse(loadWorkspaceStorage('chatBrainstorm', projectId) || '[]'),
      projectId,
    )
  } catch {
    return normalizeChatBrainstormState([], projectId)
  }
}

function defaultChatState(projectId?: string): BrainstormChatState {
  const messages = defaultChatMessages()
  return normalizeChatBrainstormState({
    schema_version: 2,
    messages,
    updated_at: messages[0]?.created_at,
  }, projectId || 'unscoped')
}

function confirmedContext(rawPacket: unknown) {
  const packet = normalizeStandardOutlinePacket(rawPacket)
  const lines: string[] = []
  const pushField = (label: string, field: StandardOutlineField | undefined) => {
    if (!fieldIsConfirmed(field)) return
    const value = field?.value
    if (Array.isArray(value)) {
      if (value.length) lines.push(`${label}：${JSON.stringify(value)}`)
      return
    }
    if (text(value)) lines.push(`${label}：${text(value)}`)
  }
  pushField('受众', packet.project_profile.audience_axis)
  pushField('题材', packet.project_profile.genre_main)
  pushField('制作形式', packet.project_profile.format_type)
  pushField('一句话梗概', packet.story_core.logline)
  pushField('世界观', packet.world_rules.worldview)
  pushField('特殊设定', packet.world_rules.golden_finger)
  pushField('核心冲突', packet.story_core.conflict)
  pushField('人物小传', packet.characters)
  pushField('人物关系', packet.relationship_timeline)
  pushField('总集数', packet.episode_count_plan.confirmed_total_episodes)
  pushField('分集集纲', packet.episode_outlines)
  return lines.length
    ? ['【用户已经在右侧明确确认的大纲资料】', ...lines, '这些内容优先于聊天中的旧候选。'].join('\n')
    : ''
}

function splitByCodePoints(value: string, chunkSize: number) {
  const points = Array.from(value)
  const chunks: string[] = []
  for (let index = 0; index < points.length; index += chunkSize) {
    chunks.push(points.slice(index, index + chunkSize).join(''))
  }
  return chunks
}

function transientAiChatError(error: unknown) {
  const status = (error as { response?: { status?: number } } | undefined)?.response?.status
  const code = text((error as { code?: string } | undefined)?.code).toLowerCase()
  const message = text((error as { message?: string } | undefined)?.message).toLowerCase()
  const aiError = extractAiError(error)
  if (!status && (code || message.includes('timeout') || message.includes('network'))) return true
  if (status && [408, 409, 429, 500, 502, 503, 504].includes(status)) return true
  return Boolean(aiError && ['network_error', 'upstream_error', 'generation_failed'].includes(aiError.error_code))
}

async function callUserAiChatWithRetry(params: AiChatParams, attempts = 2) {
  let lastError: unknown = null
  for (let attempt = 1; attempt <= attempts; attempt += 1) {
    try {
      return await userAccessApi.aiChat(params)
    } catch (error) {
      lastError = error
      if (attempt >= attempts || !transientAiChatError(error)) break
      await new Promise(resolve => setTimeout(resolve, 700 * attempt))
    }
  }
  throw lastError
}

export function _buildRawOutlineText(
  data: OutlineData,
  characters: OutlineCharacter[],
  _sourceMessages: ChatMessage[] = [],
) {
  const episodes = Array.isArray(data.episodes) ? data.episodes : []
  return [
    [data.audience_axis, data.genre_main, data.format_type].filter(Boolean).length
      ? `创作方向：${[data.audience_axis, data.genre_main, data.format_type].filter(Boolean).join(' / ')}`
      : '',
    data.logline ? `一句话梗概：${data.logline}` : '',
    data.worldview ? `世界观：${data.worldview}` : '',
    data.goldenFinger ? `金手指 / 特殊设定：${data.goldenFinger}` : '',
    data.conflict ? `核心冲突 / 爽点：${data.conflict}` : '',
    characters.length
      ? `人物小传：\n${characters.map(item => `${item.name}：${item.info}`).join('\n')}`
      : '',
    episodes.length
      ? `分集集纲：\n${episodes.map(item => `第${item.ep}集 ${item.title}：${item.summary}`).join('\n')}`
      : '',
  ].filter(Boolean).join('\n\n')
}

export function useChatBrainstorm(opts: UseChatBrainstormOptions) {
  const localState = loadLocalChatState(opts.projectId?.value)
  const initialState = localState.messages.length ? localState : defaultChatState(opts.projectId?.value)
  const chatMessages = ref<ChatMessage[]>(initialState.messages)
  const chatLoading = ref(false)
  const outlineLoading = ref(false)
  const confirmingSection = ref<OutlineEditorConfirmationSectionId | ''>('')
  const lastContextTrace = ref<ChatContextTrace | undefined>(
    initialState.last_context_trace as ChatContextTrace | undefined,
  )
  const chatSaveStatus = ref<'saved' | 'unsaved'>('saved')
  const chatContextBlocked = ref(false)
  const chatStateUpdatedAt = ref(initialState.updated_at)
  const chatSendLock = createChatSendLock()
  const chatSaveCoordinator = createSequentialSaveCoordinator()
  let chatSyncTimer: ReturnType<typeof setTimeout> | null = null
  let localStorageWarningIssued = false

  function currentChatState(): BrainstormChatState {
    return normalizeChatBrainstormState({
      schema_version: 2,
      messages: chatMessages.value,
      ...(lastContextTrace.value ? { last_context_trace: lastContextTrace.value } : {}),
      updated_at: chatStateUpdatedAt.value,
    }, opts.projectId?.value || 'unscoped')
  }

  function applyChatState(state: BrainstormChatState) {
    chatMessages.value = state.messages
    lastContextTrace.value = state.last_context_trace as ChatContextTrace | undefined
    chatStateUpdatedAt.value = state.updated_at
  }

  function markChatUpdated() {
    chatStateUpdatedAt.value = new Date().toISOString()
  }

  function appendChatMessage(message: PendingChatMessage): ChatMessage | undefined {
    if (!message.content.trim()) return undefined
    const appended: ChatMessage = {
      id: message.id?.trim() || newChatMessageId(),
      role: message.role,
      content: message.content,
      created_at: message.created_at?.trim() || new Date().toISOString(),
    }
    chatMessages.value.push(appended)
    markChatUpdated()
    return appended
  }

  async function saveChatState(critical: boolean): Promise<boolean> {
    const projectId = opts.projectId?.value
    const state = currentChatState()
    const localSaved = projectId
      ? saveWorkspaceStorage('chatBrainstorm', projectId, JSON.stringify(state))
      : false
    if (!localSaved && critical && !localStorageWarningIssued) {
      localStorageWarningIssued = true
      opts.notify.warning?.('本机缓存空间不足；当前页面仍保留聊天内容，服务器保存继续执行。')
    }
    if (!projectId) {
      chatSaveStatus.value = 'unsaved'
      return false
    }
    const result = await chatSaveCoordinator.submit(() => projectsV2Api.saveWorkflowContext(projectId, {
      workflow_context: { chat_brainstorm: state },
      merge: true,
    }))
    if (result.ok) {
      const reconciled = reconcileSavedChatBrainstormState(
        currentChatState(),
        result.value?.data?.workflow_context,
        projectId,
      )
      if (shouldApplyReconciledChatState(currentChatState(), reconciled, projectId)) {
        applyChatState(reconciled)
      }
      if (result.isLatest) chatSaveStatus.value = 'saved'
      return true
    }
    if (result.isLatest) {
      chatSaveStatus.value = 'unsaved'
      if (critical) opts.notify.warning?.('聊天内容尚未保存到项目；请在网络恢复后点击重试保存。')
    }
    return false
  }

  async function flushChatBrainstormState() {
    return saveChatState(true)
  }

  async function retryChatBrainstormSave() {
    return flushChatBrainstormState()
  }

  function hydrateChatBrainstormState(raw: unknown) {
    const merged = mergeChatBrainstormState(
      currentChatState(),
      raw,
      opts.projectId?.value || 'unscoped',
    )
    if (JSON.stringify(currentChatState()) === JSON.stringify(merged)) return
    applyChatState(merged)
  }

  const openOutlineForChatContext = () => opts.switchToOutline()

  watch(chatMessages, () => {
    if (chatSyncTimer) clearTimeout(chatSyncTimer)
    chatSyncTimer = setTimeout(() => {
      void saveChatState(false)
    }, 500)
  }, { deep: true })

  onUnmounted(() => {
    if (chatSyncTimer) clearTimeout(chatSyncTimer)
    chatSyncTimer = null
  })

  async function sendChatMessage(content: string, lockHeld = false): Promise<boolean> {
    const rawMessage = content
    if (!rawMessage.trim() || chatLoading.value) return false
    if (countContextChars(rawMessage) > CHAT_MESSAGE_MAX_CHARS) {
      opts.notify.error?.(`聊天单条最多 ${CHAT_MESSAGE_MAX_CHARS.toLocaleString()} 个字符；长剧本请使用“上传剧本”。`)
      return false
    }
    if (!lockHeld) {
      if (!chatSendLock.tryAcquire()) return false
      return sendChatMessage(rawMessage, true).finally(() => chatSendLock.release())
    }

    const currentUserMessage = appendChatMessage({ role: 'user', content: rawMessage })
    if (!currentUserMessage) return false
    await flushChatBrainstormState()
    chatLoading.value = true
    try {
      let compiled: ReturnType<typeof buildChatContextPacket>
      try {
        compiled = buildChatContextPacket({
          messages: buildCurrentChatRequestSnapshot(chatMessages.value, currentUserMessage),
          confirmedContext: confirmedContext(opts.standardOutlinePacket?.value),
          currentMessageId: currentUserMessage.id,
          maxChars: CHAT_CONTEXT_MAX_CHARS,
        })
        lastContextTrace.value = compiled.trace
        chatContextBlocked.value = false
        markChatUpdated()
      } catch (contextError: unknown) {
        chatContextBlocked.value = true
        appendChatMessage({
          role: 'ai',
          content: `本轮没有发送给 AI：${contextError instanceof Error ? contextError.message : '聊天上下文无法完整编译'}。原文已经保留。`,
        })
        await flushChatBrainstormState()
        opts.notify.warning?.('本轮内容未发送给 AI，原文已保留。')
        return true
      }

      const { data } = await callUserAiChatWithRetry({
        messages: [{ role: 'user', content: compiled.currentMessage }],
        chat_context_packet: compiled.packet,
        context: 'chat',
        max_tokens: 800,
        system_prompt: CHAT_BRAINSTORM_SYSTEM_PROMPT,
        audience_axis: opts.outlineData.value.audience_axis || '',
        genre: opts.outlineData.value.genre_main || '',
        format_type: opts.outlineData.value.format_type || '真人短剧',
      })
      appendChatMessage({ role: 'ai', content: data.content })
      await flushChatBrainstormState()
      return true
    } catch (error: unknown) {
      const aiError = extractAiError(error)
      const accessError = formatAccessErrorMessage(error)
      appendChatMessage({
        role: 'ai',
        content: aiError
          ? formatAiErrorMessage(aiError)
          : accessError || formatUserFacingErrorMessage(error, 'AI暂时不可用'),
      })
      await flushChatBrainstormState()
      return true
    } finally {
      chatLoading.value = false
    }
  }

  async function generateOutlineFromChat(): Promise<boolean> {
    if (chatLoading.value || outlineLoading.value || confirmingSection.value) return false
    if (!chatSendLock.tryAcquire()) return false
    outlineLoading.value = true
    try {
      const userMessages = chatMessages.value.filter(message => message.role === 'user')
      if (!userMessages.length) {
        opts.notify.error?.('请先完成至少一轮聊天，再整理当前讨论。')
        return false
      }
      if (chatSaveStatus.value === 'unsaved' && await flushChatBrainstormState() !== true) {
        opts.notify.error?.('聊天记录尚未保存，已停止整理。')
        return false
      }

      const emptyPromptChars = countContextChars(outlineOrganizerPrompt(''))
      const sourceBudget = CHAT_CONTEXT_MAX_CHARS - emptyPromptChars
      if (sourceBudget <= 0) throw new Error('大纲整理指令超过上下文预算')
      const compiled = buildBoundedConversationSource({
        messages: chatMessages.value,
        confirmedContext: confirmedContext(opts.standardOutlinePacket?.value),
        maxChars: sourceBudget,
      })
      const prompt = outlineOrganizerPrompt(compiled.source)
      if (countContextChars(prompt) > CHAT_CONTEXT_MAX_CHARS) {
        throw new Error('聊天记录无法按完整消息边界放入整理上下文')
      }
      lastContextTrace.value = compiled.trace
      chatContextBlocked.value = false
      markChatUpdated()

      const { data } = await callUserAiChatWithRetry({
        context: 'outline_structuring',
        max_tokens: 4096,
        system_prompt: OUTLINE_ORGANIZER_SYSTEM_PROMPT,
        messages: [{ role: 'user', content: prompt }],
      })
      const candidate = candidatePacketFromPayload(parseJsonObject(data.content || ''), compiled.source)
      const packet = mergeCandidateWithoutOverwritingConfirmed(
        opts.standardOutlinePacket?.value,
        candidate,
      )
      const projection = projectStandardOutlinePacketToOutline(packet)
      const persisted = await opts.onOutlineGenerated?.({
        rawOutlineText: projection.rawOutlineText,
        standardOutlinePacket: packet,
      })
      if (persisted !== true) {
        opts.notify.error?.('候选字段已经生成，但没有保存成功；原聊天记录未受影响。')
        return false
      }
      if (opts.standardOutlinePacket) opts.standardOutlinePacket.value = packet
      appendChatMessage({
        role: 'ai',
        content: '已把当前讨论整理成右侧候选字段。请展开核对和修改；只有点击“确认本项”的内容才进入大纲资料。',
      })
      await flushChatBrainstormState()
      opts.notify.success('当前讨论已整理到右侧，等待逐项确认。')
      return true
    } catch (error: unknown) {
      const aiError = extractAiError(error)
      const message = aiError
        ? formatAiErrorMessage(aiError)
        : formatUserFacingErrorMessage(error, '讨论整理失败')
      appendChatMessage({ role: 'ai', content: `本次没有生成候选字段：${message}` })
      await flushChatBrainstormState()
      opts.notify.error?.(message)
      return false
    } finally {
      outlineLoading.value = false
      chatSendLock.release()
    }
  }

  async function confirmOutlineEditorSection(
    sectionId: OutlineEditorConfirmationSectionId,
    draft: OutlineEditorConfirmationDraft,
  ): Promise<boolean> {
    if (chatLoading.value || outlineLoading.value || confirmingSection.value) return false
    confirmingSection.value = sectionId
    try {
      const packet = applyOutlineEditorSectionConfirmation(
        opts.standardOutlinePacket?.value,
        sectionId,
        draft,
      )
      const projection = projectStandardOutlinePacketToOutline(packet)
      const persisted = await opts.onOutlineGenerated?.({
        rawOutlineText: projection.rawOutlineText,
        standardOutlinePacket: packet,
      })
      if (persisted !== true) {
        opts.notify.error?.('本项没有保存成功，确认状态未改变。')
        return false
      }
      if (opts.standardOutlinePacket) opts.standardOutlinePacket.value = packet
      if (packet.status === 'confirmed') {
        opts.markChatTabComplete()
        opts.notify.success('七项大纲资料已全部确认；请进入大纲编辑器做最终检查。')
      } else {
        const label = OUTLINE_EDITOR_CONFIRMATION_SECTIONS.find(item => item.id === sectionId)?.label || '当前项目'
        opts.notify.success(`${label}已确认。`)
      }
      return true
    } catch (error: unknown) {
      opts.notify.error?.(formatUserFacingErrorMessage(error, '确认失败'))
      return false
    } finally {
      confirmingSection.value = ''
    }
  }

  async function summarizeReferenceChunk(chunk: string, index: number, total: number) {
    const { data } = await callUserAiChatWithRetry({
      context: 'chat',
      max_tokens: 700,
      system_prompt: REFERENCE_SUMMARY_SYSTEM_PROMPT,
      messages: [{
        role: 'user',
        content: `这是上传剧本的第 ${index + 1}/${total} 块。请严格根据原文提取参考摘要：\n\n${chunk}`,
      }],
    })
    return text(data.content)
  }

  async function consolidateReferenceSummaries(filename: string, summaries: string[]) {
    if (summaries.length === 1) return summaries[0]
    const { data } = await callUserAiChatWithRetry({
      context: 'chat',
      max_tokens: 900,
      system_prompt: REFERENCE_SUMMARY_SYSTEM_PROMPT,
      messages: [{
        role: 'user',
        content: `请把《${filename}》的分块摘要合并成一份无重复、保留人物关系和关键因果的聊天参考摘要：\n\n${summaries.join('\n\n')}`,
      }],
    })
    return text(data.content)
  }

  async function sendChatReferenceDocument(document: ChatReferenceDocument): Promise<boolean> {
    if (chatLoading.value || outlineLoading.value || confirmingSection.value) return false
    if (!chatSendLock.tryAcquire()) return false
    chatLoading.value = true
    try {
      const source = document.text.trim()
      const sourceChars = countContextChars(source)
      if (!source) {
        opts.notify.error?.('文件中没有可识别的文字。')
        return false
      }
      if (sourceChars > CHAT_REFERENCE_MAX_CHARS) {
        opts.notify.error?.(`聊天参考文件最多 ${CHAT_REFERENCE_MAX_CHARS.toLocaleString()} 个字符；请拆分剧本后上传。`)
        return false
      }
      const chunks = splitByCodePoints(source, CHAT_REFERENCE_CHUNK_CHARS)
      appendChatMessage({
        role: 'user',
        content: [
          `【上传剧本参考：${document.filename}】`,
          `原文 ${sourceChars.toLocaleString()} 字符，请只作为聊天参考读取，不要自动写入或确认大纲字段。`,
          document.truncated ? '上传接口已明确标记原文件超过读取上限；本次只读取服务器返回的可读部分。' : '',
        ].filter(Boolean).join('\n'),
      })
      await flushChatBrainstormState()
      const summaries: string[] = []
      for (let index = 0; index < chunks.length; index += 1) {
        summaries.push(await summarizeReferenceChunk(chunks[index] || '', index, chunks.length))
      }
      const summary = await consolidateReferenceSummaries(document.filename, summaries)
      appendChatMessage({
        role: 'ai',
        content: [
        `【剧本参考摘要（AI 整理，需核对）：${document.filename}】`,
        `已分 ${chunks.length} 块读取。以下摘要只参与聊天，不自动写入或确认右侧大纲字段。`,
        '',
        summary,
        '',
        '接下来可以直接讨论人物、关系、剧情方向或改法。',
        ].join('\n'),
      })
      await flushChatBrainstormState()
      opts.notify.success('剧本已作为聊天参考读取。')
      return true
    } catch (error: unknown) {
      const aiError = extractAiError(error)
      const message = aiError
        ? formatAiErrorMessage(aiError)
        : formatUserFacingErrorMessage(error, '剧本参考读取失败')
      appendChatMessage({
        role: 'ai',
        content: `上传记录已保留，但模型没有完成剧本参考摘要：${message}`,
      })
      await flushChatBrainstormState()
      opts.notify.error?.(message)
      return false
    } finally {
      chatLoading.value = false
      chatSendLock.release()
    }
  }

  async function bootstrapFromQueryPrompt(prompt: string) {
    if (!prompt.trim()) return
    if (chatMessages.value.some(message => (
      message.role === 'user' && message.content.trim() === prompt.trim()
    ))) return
    await sendChatMessage(prompt)
  }

  return {
    chatMessages,
    chatLoading,
    outlineLoading,
    confirmingSection,
    chatSaveStatus,
    chatContextBlocked,
    lastContextTrace,
    hydrateChatBrainstormState,
    flushChatBrainstormState,
    retryChatBrainstormSave,
    openOutlineForChatContext,
    bootstrapFromQueryPrompt,
    sendChatMessage,
    sendChatReferenceDocument,
    generateOutlineFromChat,
    confirmOutlineEditorSection,
  }
}
