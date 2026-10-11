/**
 * Chat brainstorm context is deliberately compiled without imports so it can be
 * exercised in isolation and so every caller uses the same budget rules.
 */
export const CHAT_CONTEXT_MAX_CHARS = 18_000
export const CHAT_MESSAGE_MAX_CHARS = 12_000
export const CHAT_VISIBLE_INITIAL_MESSAGES = 60

export type BrainstormChatRole = 'user' | 'ai'

export interface BrainstormChatMessage {
  id: string
  role: BrainstormChatRole
  content: string
  created_at: string
}

export interface ChatContextTrace {
  included_message_ids: string[]
  omitted_message_ids: string[]
  packet_chars: number
  total_chars: number
  max_chars: number
  created_at: string
}

export interface BuildChatContextPacketInput {
  messages: BrainstormChatMessage[]
  confirmedContext: string
  currentMessageId: string
  maxChars?: number
}

export interface BuildChatContextPacketResult {
  packet: string
  currentMessage: string
  trace: ChatContextTrace
}

export interface BuildBoundedConversationSourceInput {
  messages: BrainstormChatMessage[]
  confirmedContext: string
  maxChars?: number
}

export interface BuildBoundedConversationSourceResult {
  source: string
  trace: ChatContextTrace
}

export interface BrainstormChatState {
  schema_version: 2
  messages: BrainstormChatMessage[]
  last_context_trace?: Record<string, unknown>
  updated_at: string
}

const REQUEST_HEADER = '\n\n【本轮用户要求】\n'
const BOUNDARY = '【边界】未列出的历史材料仍保存为候选原文；不得假定自己已经读到。'
const LEGACY_MIGRATION_BASE_MS = Date.parse('2000-01-01T00:00:00.000Z')
export const LEGACY_CHAT_MIGRATION_SCOPE = 'legacy-workflow-context'

/** Uses Unicode code points, matching Python's len() contract for this API. */
export function countContextChars(text: string): number {
  return Array.from(text).length
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value && typeof value === 'object' && !Array.isArray(value))
}

function stableHash(value: string): string {
  let hash = 2_166_136_261
  for (let index = 0; index < value.length; index += 1) {
    hash ^= value.charCodeAt(index)
    hash = Math.imul(hash, 16_777_619)
  }
  return (hash >>> 0).toString(36)
}

function legacyMessageCreatedAt(index: number): string {
  return new Date(LEGACY_MIGRATION_BASE_MS + index * 1_000).toISOString()
}

function isNewer(left: string, right: string): boolean {
  return left > right
}

function chooseMessage(
  existing: BrainstormChatMessage,
  incoming: BrainstormChatMessage,
): BrainstormChatMessage {
  if (isNewer(incoming.created_at, existing.created_at)) return incoming
  if (isNewer(existing.created_at, incoming.created_at)) return existing
  if (countContextChars(incoming.content) > countContextChars(existing.content)) return incoming
  if (countContextChars(existing.content) > countContextChars(incoming.content)) return existing
  return incoming.content > existing.content ? incoming : existing
}

function compareMessages(left: BrainstormChatMessage, right: BrainstormChatMessage): number {
  if (left.created_at !== right.created_at) return left.created_at < right.created_at ? -1 : 1
  if (left.id === right.id) return 0
  return left.id < right.id ? -1 : 1
}

function normalizeMessages(raw: unknown, _projectId: string): BrainstormChatMessage[] {
  const rawMessages = Array.isArray(raw) ? raw : []
  const byId = new Map<string, BrainstormChatMessage>()

  rawMessages.forEach((value, index) => {
    if (!isRecord(value)) return
    const role: BrainstormChatRole | undefined = value.role === 'user' || value.role === 'ai' ? value.role : undefined
    const content = typeof value.content === 'string' ? value.content : undefined
    if (!role || content === undefined || !content.trim()) return
    const id = typeof value.id === 'string' && value.id.trim()
      ? value.id.trim()
      : `legacy-${stableHash(`${LEGACY_CHAT_MIGRATION_SCOPE}|${index}|${role}|${content}`)}`
    const createdAt = typeof value.created_at === 'string' && value.created_at.trim()
      ? value.created_at.trim()
      : legacyMessageCreatedAt(index)
    const message = { id, role, content, created_at: createdAt }
    const existing = byId.get(id)
    byId.set(id, existing ? chooseMessage(existing, message) : message)
  })

  return Array.from(byId.values()).sort(compareMessages)
}

function normalizeTrace(raw: unknown): Record<string, unknown> | undefined {
  if (!isRecord(raw) || Object.keys(raw).length === 0) return undefined
  const createdAt = typeof raw.created_at === 'string' ? raw.created_at.trim() : ''
  if (!createdAt) return undefined
  return { ...raw, created_at: createdAt }
}

function newestTimestamp(...timestamps: Array<string | undefined>): string {
  const normalized = timestamps.filter((value): value is string => Boolean(value)).sort()
  return normalized[normalized.length - 1] || legacyMessageCreatedAt(0)
}

/**
 * Converts both legacy persisted forms (a bare array and {messages}) into the
 * v2 state shape without shortening user text or limiting message count.
 */
export function normalizeChatBrainstormState(raw: unknown, projectId = LEGACY_CHAT_MIGRATION_SCOPE): BrainstormChatState {
  const source = isRecord(raw) ? raw : {}
  const messages = normalizeMessages(Array.isArray(raw) ? raw : source.messages, projectId)
  const lastContextTrace = normalizeTrace(source.last_context_trace)
  const updatedAt = newestTimestamp(
    typeof source.updated_at === 'string' && source.updated_at.trim() ? source.updated_at.trim() : undefined,
    ...messages.map(message => message.created_at),
    lastContextTrace?.created_at as string | undefined,
  )

  return {
    schema_version: 2,
    messages,
    ...(lastContextTrace ? { last_context_trace: lastContextTrace } : {}),
    updated_at: updatedAt,
  }
}

/**
 * Unions concurrent local/server states. A missing incoming trace never clears
 * a previous trace, and one message identifier has one deterministic winner.
 */
export function mergeChatBrainstormState(
  existingRaw: unknown,
  incomingRaw: unknown,
  projectId = LEGACY_CHAT_MIGRATION_SCOPE,
): BrainstormChatState {
  const existing = normalizeChatBrainstormState(existingRaw, projectId)
  const incoming = normalizeChatBrainstormState(incomingRaw, projectId)
  const byId = new Map<string, BrainstormChatMessage>()
  for (const message of existing.messages) byId.set(message.id, message)
  for (const message of incoming.messages) {
    const previous = byId.get(message.id)
    byId.set(message.id, previous ? chooseMessage(previous, message) : message)
  }

  const existingTrace = normalizeTrace(existing.last_context_trace)
  const incomingTrace = normalizeTrace(incoming.last_context_trace)
  const trace = !existingTrace
    ? incomingTrace
    : !incomingTrace
      ? existingTrace
      : isNewer(String(incomingTrace.created_at), String(existingTrace.created_at))
        ? incomingTrace
        : existingTrace

  return normalizeChatBrainstormState({
    schema_version: 2,
    messages: Array.from(byId.values()).sort(compareMessages),
    ...(trace ? { last_context_trace: trace } : {}),
    updated_at: newestTimestamp(
      existing.updated_at,
      incoming.updated_at,
      ...Array.from(byId.values()).map(message => message.created_at),
      existingTrace?.created_at as string | undefined,
      incomingTrace?.created_at as string | undefined,
    ),
  }, projectId)
}

/**
 * Freezes one tab's current user turn for the outbound request. A concurrent
 * server reconciliation can sort another tab's later messages after it, but
 * that must not turn the other tab's request into this round's current input.
 */
export function buildCurrentChatRequestSnapshot(
  messages: readonly BrainstormChatMessage[],
  currentMessage: BrainstormChatMessage,
): BrainstormChatMessage[] {
  const historicalMessages = messages
    .filter(message => message.id !== currentMessage.id)
    .map(message => ({ ...message }))
  return [...historicalMessages, { ...currentMessage }]
}

/** Merges a successful workflow save readback into the browser's current state. */
export function reconcileSavedChatBrainstormState(
  currentState: unknown,
  workflowContext: unknown,
  projectId = LEGACY_CHAT_MIGRATION_SCOPE,
): BrainstormChatState {
  const serverState = isRecord(workflowContext) ? workflowContext.chat_brainstorm : undefined
  return isRecord(serverState)
    ? mergeChatBrainstormState(currentState, serverState, projectId)
    : normalizeChatBrainstormState(currentState, projectId)
}

function stableSerialize(value: unknown): string {
  if (value === null) return 'null'
  if (value === undefined) return 'undefined'
  if (Array.isArray(value)) return `[${value.map(stableSerialize).join(',')}]`
  if (isRecord(value)) {
    return `{${Object.keys(value).sort().map(key => `${JSON.stringify(key)}:${stableSerialize(value[key])}`).join(',')}}`
  }
  return JSON.stringify(value)
}

function chatBrainstormStatesEqual(left: BrainstormChatState, right: BrainstormChatState): boolean {
  if (left.schema_version !== right.schema_version || left.updated_at !== right.updated_at) return false
  if (stableSerialize(left.last_context_trace) !== stableSerialize(right.last_context_trace)) return false
  if (left.messages.length !== right.messages.length) return false
  return left.messages.every((message, index) => {
    const other = right.messages[index]
    if (!other) return false
    return message.id === other.id
      && message.role === other.role
      && message.content === other.content
      && message.created_at === other.created_at
  })
}

/** True only when a server reconciliation carries a real state change to render. */
export function shouldApplyReconciledChatState(
  currentState: unknown,
  reconciledState: unknown,
  projectId = LEGACY_CHAT_MIGRATION_SCOPE,
): boolean {
  return !chatBrainstormStatesEqual(
    normalizeChatBrainstormState(currentState, projectId),
    normalizeChatBrainstormState(reconciledState, projectId),
  )
}

export interface SequentialSaveResult<T> {
  revision: number
  isLatest: boolean
  ok: boolean
  value?: T
  error?: unknown
}

/** Serializes save attempts while exposing whether a completion is still current. */
export function createSequentialSaveCoordinator() {
  let latestRevision = 0
  let tail: Promise<void> = Promise.resolve()

  async function submit<T>(operation: () => Promise<T>): Promise<SequentialSaveResult<T>> {
    const revision = ++latestRevision
    const queued = tail.then(operation, operation)
    tail = queued.then(() => undefined, () => undefined)
    try {
      const value = await queued
      return { revision, isLatest: revision === latestRevision, ok: true, value }
    } catch (error: unknown) {
      return { revision, isLatest: revision === latestRevision, ok: false, error }
    }
  }

  return { submit }
}

/**
 * Guards one in-flight chat send across every caller (UI and URL bootstrap).
 * The holder acquires synchronously before it can append a user message, then
 * releases in the caller's finally block after all persistence and AI work.
 */
export function createChatSendLock() {
  let locked = false

  return {
    tryAcquire(): boolean {
      if (locked) return false
      locked = true
      return true
    },
    release() {
      locked = false
    },
    isLocked(): boolean {
      return locked
    },
  }
}

function hasDuplicateMessageId(messages: BrainstormChatMessage[]): boolean {
  const ids = new Set<string>()
  for (const message of messages) {
    if (ids.has(message.id)) return true
    ids.add(message.id)
  }
  return false
}

function groupHistoricalMessages(messages: BrainstormChatMessage[]): BrainstormChatMessage[][] {
  const blocks: BrainstormChatMessage[][] = []
  let activeUserBlock: BrainstormChatMessage[] | null = null

  for (const message of messages) {
    if (message.role === 'user') {
      activeUserBlock = [message]
      blocks.push(activeUserBlock)
      continue
    }

    if (activeUserBlock) {
      activeUserBlock.push(message)
    } else {
      // A greeting or other assistant message without a preceding user turn
      // has no user-owned turn to join, so it remains its own atomic block.
      blocks.push([message])
    }
  }

  return blocks
}

function renderMessage(message: BrainstormChatMessage): string {
  return `${message.role === 'user' ? '用户：' : '助手：'}${message.content}`
}

function buildPacket(
  confirmedContext: string,
  includedBlocks: BrainstormChatMessage[][],
): string {
  const parts: string[] = []

  if (confirmedContext) {
    parts.push(`【已确认设定】\n${confirmedContext}`)
  }

  const includedMessages = includedBlocks.flat()
  if (includedMessages.length > 0) {
    parts.push(`【相关聊天记录】\n${includedMessages.map(renderMessage).join('\n\n')}`)
  }

  parts.push(BOUNDARY)
  return parts.join('\n\n')
}

/**
 * Compiles an entire conversation for outline confirmation. Unlike the normal
 * chat compiler, the final message may be an assistant response, so it does
 * not invent a current user request or relax that compiler's contract.
 */
export function buildBoundedConversationSource(
  input: BuildBoundedConversationSourceInput,
): BuildBoundedConversationSourceResult {
  const maxChars = input.maxChars ?? CHAT_CONTEXT_MAX_CHARS
  if (!Number.isSafeInteger(maxChars) || maxChars <= 0) {
    throw new Error('聊天上下文预算必须是正整数')
  }
  if (hasDuplicateMessageId(input.messages)) {
    throw new Error('聊天消息编号重复')
  }

  const confirmedContext = input.confirmedContext.trim() ? input.confirmedContext : ''
  const packetWithoutConfirmedContext = buildPacket('', [])
  const packetWithoutHistory = buildPacket(confirmedContext, [])
  if (countContextChars(packetWithoutConfirmedContext) > maxChars) {
    throw new Error('聊天上下文预算不足')
  }
  if (confirmedContext && countContextChars(packetWithoutHistory) > maxChars) {
    throw new Error('已确认设定超过聊天上下文预算')
  }

  const blocks = groupHistoricalMessages(input.messages)
  const includedBlocks: BrainstormChatMessage[][] = []
  let omittedBlocks: BrainstormChatMessage[][] = []
  for (let index = blocks.length - 1; index >= 0; index -= 1) {
    const block = blocks[index]
    if (!block) continue
    const candidateBlocks = [block, ...includedBlocks]
    if (countContextChars(buildPacket(confirmedContext, candidateBlocks)) > maxChars) {
      omittedBlocks = blocks.slice(0, index + 1)
      break
    }
    includedBlocks.unshift(block)
  }

  const source = buildPacket(confirmedContext, includedBlocks)
  const sourceChars = countContextChars(source)
  if (sourceChars > maxChars) throw new Error('聊天上下文编译长度超限')
  return {
    source,
    trace: {
      included_message_ids: includedBlocks.flat().map(message => message.id),
      omitted_message_ids: omittedBlocks.flat().map(message => message.id),
      packet_chars: sourceChars,
      total_chars: sourceChars,
      max_chars: maxChars,
      created_at: new Date().toISOString(),
    },
  }
}

/**
 * Builds a bounded model context while preserving every included historical
 * message verbatim. The current user message is returned separately because
 * the API appends it after the packet under REQUEST_HEADER.
 */
export function buildChatContextPacket(
  input: BuildChatContextPacketInput,
): BuildChatContextPacketResult {
  const { messages, currentMessageId } = input
  const maxChars = input.maxChars ?? CHAT_CONTEXT_MAX_CHARS

  if (!Number.isSafeInteger(maxChars) || maxChars <= 0) {
    throw new Error('聊天上下文预算必须是正整数')
  }

  if (hasDuplicateMessageId(messages)) {
    throw new Error('聊天消息编号重复')
  }

  const currentIndex = messages.findIndex(message => message.id === currentMessageId)
  const current = currentIndex >= 0 ? messages[currentIndex] : undefined
  if (!current || current.role !== 'user') {
    throw new Error('当前用户消息不存在')
  }
  if (currentIndex !== messages.length - 1) {
    throw new Error('当前用户消息必须是最后一条消息')
  }

  const currentMessage = current.content
  if (!currentMessage.trim()) {
    throw new Error('当前用户消息不能为空')
  }

  const requestSuffix = `${REQUEST_HEADER}${currentMessage}`
  const requestSuffixChars = countContextChars(requestSuffix)
  const confirmedContext = input.confirmedContext.trim() ? input.confirmedContext : ''
  const packetWithoutConfirmedContext = buildPacket('', [])
  const packetWithoutHistory = buildPacket(confirmedContext, [])

  if (countContextChars(packetWithoutConfirmedContext) + requestSuffixChars > maxChars) {
    throw new Error('当前用户消息超过聊天上下文预算')
  }
  if (confirmedContext && countContextChars(packetWithoutHistory) + requestSuffixChars > maxChars) {
    throw new Error('已确认设定超过聊天上下文预算')
  }

  const historicalBlocks = groupHistoricalMessages(messages.slice(0, currentIndex))
  const includedBlocks: BrainstormChatMessage[][] = []
  let omittedBlocks: BrainstormChatMessage[][] = []

  for (let index = historicalBlocks.length - 1; index >= 0; index -= 1) {
    const block = historicalBlocks[index]
    if (!block) continue
    const candidateBlocks = [block, ...includedBlocks]
    const candidatePacket = buildPacket(confirmedContext, candidateBlocks)
    if (countContextChars(candidatePacket) + requestSuffixChars > maxChars) {
      omittedBlocks = historicalBlocks.slice(0, index + 1)
      break
    }
    includedBlocks.unshift(block)
  }

  const packet = buildPacket(confirmedContext, includedBlocks)
  const packetChars = countContextChars(packet)
  const totalChars = packetChars + requestSuffixChars
  if (totalChars > maxChars) {
    throw new Error('聊天上下文编译长度超限')
  }

  return {
    packet,
    currentMessage,
    trace: {
      included_message_ids: includedBlocks.flat().map(message => message.id),
      omitted_message_ids: omittedBlocks.flat().map(message => message.id),
      packet_chars: packetChars,
      total_chars: totalChars,
      max_chars: maxChars,
      created_at: new Date().toISOString(),
    },
  }
}
