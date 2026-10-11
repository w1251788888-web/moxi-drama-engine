import assert from 'node:assert/strict'
import { createRequire } from 'node:module'
import fs from 'node:fs'
import path from 'node:path'
import test from 'node:test'
import vm from 'node:vm'

const require = createRequire(import.meta.url)
const webuiRoot = path.resolve(import.meta.dirname, '..')
const sourcePath = path.join(
  webuiRoot,
  'src/features/workspace/utils/chatBrainstormContext.ts',
)

function loadTypescript() {
  try {
    return require('typescript')
  } catch (error) {
    assert.fail(
      `本项目 webui/node_modules 中缺少 TypeScript，不能借用其他工作区执行上下文测试：${error.message}`,
    )
  }
}

function loadChatContextModule() {
  assert.ok(
    fs.existsSync(sourcePath),
    '聊天上下文编译器缺失：请创建 src/features/workspace/utils/chatBrainstormContext.ts 并导出 buildChatContextPacket',
  )

  const ts = loadTypescript()
  const source = fs.readFileSync(sourcePath, 'utf8')
  const compiled = ts.transpileModule(source, {
    compilerOptions: {
      module: ts.ModuleKind.CommonJS,
      target: ts.ScriptTarget.ES2022,
    },
    fileName: sourcePath,
  }).outputText

  const module = { exports: {} }
  const context = vm.createContext({
    exports: module.exports,
    module,
    console,
    Date,
  })
  vm.runInContext(compiled, context, { filename: sourcePath })
  assert.equal(
    typeof module.exports.buildChatContextPacket,
    'function',
    '聊天上下文编译器必须导出 buildChatContextPacket',
  )
  return module.exports
}

function loadBuildChatContextPacket() {
  return loadChatContextModule().buildChatContextPacket
}

const sevenTurnMessages = []
for (let index = 1; index <= 6; index += 1) {
  sevenTurnMessages.push(
    {
      id: `u-${index}`,
      role: 'user',
      content: `用户第${index}轮：FACT_${index}`,
      created_at: '2026-07-17T00:00:00Z',
    },
    {
      id: `a-${index}`,
      role: 'ai',
      content: `助手第${index}轮回复`,
      created_at: '2026-07-17T00:00:01Z',
    },
  )
}
sevenTurnMessages.push({
  id: 'u-7',
  role: 'user',
  content: '第7轮最新要求：FACT_7',
  created_at: '2026-07-17T00:00:02Z',
})

test('six completed turns and the seventh current turn retain all seven facts', () => {
  const buildChatContextPacket = loadBuildChatContextPacket()
  const result = buildChatContextPacket({
    messages: sevenTurnMessages,
    confirmedContext: '',
    currentMessageId: 'u-7',
  })

  for (let index = 1; index <= 6; index += 1) {
    assert.match(result.packet, new RegExp(`FACT_${index}`))
  }
  assert.equal(result.currentMessage, '第7轮最新要求：FACT_7')
  assert.deepEqual(Array.from(result.trace.omitted_message_ids), [])
})

test('a historical message is whole or absent, never half present', () => {
  const buildChatContextPacket = loadBuildChatContextPacket()
  const longFragments = [
    'LONG_BLOCK_START_9f0456a1',
    'LONG_BLOCK_MIDDLE_a27d0c89',
    'LONG_BLOCK_END_6b3e4fd2',
  ]
  const longFact = longFragments.join('甲'.repeat(450))
  const result = buildChatContextPacket({
    messages: [
      { id: 'u-1', role: 'user', content: longFact, created_at: '2026-07-17T00:00:00Z' },
      { id: 'a-1', role: 'ai', content: '收到', created_at: '2026-07-17T00:00:01Z' },
      { id: 'u-2', role: 'user', content: '最新问题', created_at: '2026-07-17T00:00:02Z' },
    ],
    confirmedContext: '',
    currentMessageId: 'u-2',
    maxChars: 300,
  })

  for (const fragment of longFragments) {
    assert.equal(result.packet.includes(fragment), false)
  }
  assert.equal(result.packet.includes('甲'), false)
  assert.deepEqual(Array.from(result.trace.omitted_message_ids), ['u-1', 'a-1'])
  assert.deepEqual(Array.from(result.trace.included_message_ids), [])
  assert.equal(
    Array.from(result.trace.included_message_ids).some(id =>
      Array.from(result.trace.omitted_message_ids).includes(id),
    ),
    false,
  )
})

test('an overflowing newest historical block stops selection instead of skipping back to older facts', () => {
  const buildChatContextPacket = loadBuildChatContextPacket()
  const result = buildChatContextPacket({
    messages: [
      { id: 'u-old', role: 'user', content: 'OLDER_FACT_MUST_NOT_LEAK', created_at: '2026-07-17T00:00:00Z' },
      { id: 'a-old', role: 'ai', content: '旧回复', created_at: '2026-07-17T00:00:01Z' },
      {
        id: 'u-new',
        role: 'user',
        content: `NEWEST_BLOCK_TOO_LONG_${'乙'.repeat(900)}`,
        created_at: '2026-07-17T00:00:02Z',
      },
      { id: 'a-new', role: 'ai', content: '最新回复', created_at: '2026-07-17T00:00:03Z' },
      { id: 'u-current', role: 'user', content: '本轮问题', created_at: '2026-07-17T00:00:04Z' },
    ],
    confirmedContext: '',
    currentMessageId: 'u-current',
    maxChars: 300,
  })

  const omitted = Array.from(result.trace.omitted_message_ids)
  assert.deepEqual(omitted, ['u-old', 'a-old', 'u-new', 'a-new'])
  assert.equal(result.packet.includes('OLDER_FACT_MUST_NOT_LEAK'), false)
  assert.equal(result.packet.includes('乙'), false)
  assert.deepEqual(Array.from(result.trace.included_message_ids), [])
})

test('packet and current user request share one strict context budget', () => {
  const buildChatContextPacket = loadBuildChatContextPacket()
  const maxChars = 500
  const result = buildChatContextPacket({
    messages: [
      { id: 'u-1', role: 'user', content: '历史事实：BUDGET_FACT', created_at: '2026-07-17T00:00:00Z' },
      { id: 'a-1', role: 'ai', content: '历史回复', created_at: '2026-07-17T00:00:01Z' },
      { id: 'u-2', role: 'user', content: '当前原话：CURRENT_FACT', created_at: '2026-07-17T00:00:02Z' },
    ],
    confirmedContext: '',
    currentMessageId: 'u-2',
    maxChars,
  })

  assert.ok(
    result.packet.length + '\n\n【本轮用户要求】\n'.length + result.currentMessage.length <= maxChars,
    '上下文包和当前用户原话合计不得突破 maxChars',
  )
})

test('confirmed context over budget stops instead of truncating confirmed facts', () => {
  const buildChatContextPacket = loadBuildChatContextPacket()

  assert.throws(
    () =>
      buildChatContextPacket({
        messages: [
          { id: 'u-1', role: 'user', content: '当前问题', created_at: '2026-07-17T00:00:00Z' },
        ],
        confirmedContext: `CONFIRMED_FACT_${'丙'.repeat(500)}`,
        currentMessageId: 'u-1',
        maxChars: 300,
      }),
    /已确认设定超过聊天上下文预算/,
  )
})

test('current message over budget wins over confirmed context over budget', () => {
  const buildChatContextPacket = loadBuildChatContextPacket()

  assert.throws(
    () =>
      buildChatContextPacket({
        messages: [
          { id: 'u-1', role: 'user', content: '甲'.repeat(500), created_at: '2026-07-17T00:00:00Z' },
        ],
        confirmedContext: '已确认事实',
        currentMessageId: 'u-1',
        maxChars: 300,
      }),
    /当前用户消息超过聊天上下文预算/,
  )
})

test('context budget must be a positive finite integer', () => {
  const buildChatContextPacket = loadBuildChatContextPacket()
  const input = {
    messages: [
      { id: 'u-1', role: 'user', content: '当前问题', created_at: '2026-07-17T00:00:00Z' },
    ],
    confirmedContext: '',
    currentMessageId: 'u-1',
  }

  for (const maxChars of [Number.NaN, Number.POSITIVE_INFINITY, 0, -1]) {
    assert.throws(
      () => buildChatContextPacket({ ...input, maxChars }),
      /聊天上下文预算必须是正整数/,
    )
  }
})

test('counts Unicode code points and shares the exact budget with the current request', () => {
  const { buildChatContextPacket, countContextChars } = loadChatContextModule()
  assert.equal(typeof countContextChars, 'function', '必须导出 countContextChars')
  assert.equal(countContextChars('A😀𠮷'), Array.from('A😀𠮷').length)

  const input = {
    messages: [
      { id: 'u-1', role: 'user', content: '当前😀原话', created_at: '2026-07-17T00:00:00Z' },
    ],
    confirmedContext: '',
    currentMessageId: 'u-1',
  }
  const roomy = buildChatContextPacket({ ...input, maxChars: 1_000 })
  const exactBudget =
    Array.from(roomy.packet).length +
    Array.from('\n\n【本轮用户要求】\n').length +
    Array.from(roomy.currentMessage).length
  const exact = buildChatContextPacket({ ...input, maxChars: exactBudget })

  assert.equal(exact.trace.packet_chars, Array.from(exact.packet).length)
  assert.equal(exact.trace.total_chars, exactBudget)
  assert.equal(exact.trace.total_chars <= exact.trace.max_chars, true)
})

test('rejects a whitespace-only current message while preserving nonblank raw content', () => {
  const buildChatContextPacket = loadBuildChatContextPacket()

  assert.throws(
    () =>
      buildChatContextPacket({
        messages: [
          { id: 'u-blank', role: 'user', content: ' \n\t ', created_at: '2026-07-17T00:00:00Z' },
        ],
        confirmedContext: '',
        currentMessageId: 'u-blank',
      }),
    /当前用户消息不能为空/,
  )

  const raw = '  保留首尾空格  '
  const result = buildChatContextPacket({
    messages: [
      { id: 'u-raw', role: 'user', content: raw, created_at: '2026-07-17T00:00:00Z' },
    ],
    confirmedContext: '',
    currentMessageId: 'u-raw',
  })
  assert.equal(result.currentMessage, raw)
})

test('preserves confirmed context source text after using trim only to decide emptiness', () => {
  const buildChatContextPacket = loadBuildChatContextPacket()
  const confirmedContext = '  已确认事实首尾空格  '
  const result = buildChatContextPacket({
    messages: [
      { id: 'u-1', role: 'user', content: '当前问题', created_at: '2026-07-17T00:00:00Z' },
    ],
    confirmedContext,
    currentMessageId: 'u-1',
  })

  assert.match(result.packet, new RegExp(`【已确认设定】\\n${confirmedContext}`))
})

test('keeps a leading assistant message as one block and consecutive assistant replies with their user', () => {
  const buildChatContextPacket = loadBuildChatContextPacket()
  const result = buildChatContextPacket({
    messages: [
      { id: 'a-open', role: 'ai', content: '开场欢迎', created_at: '2026-07-17T00:00:00Z' },
      { id: 'u-1', role: 'user', content: '第一问', created_at: '2026-07-17T00:00:01Z' },
      { id: 'a-1', role: 'ai', content: '第一答', created_at: '2026-07-17T00:00:02Z' },
      { id: 'a-2', role: 'ai', content: '补充答复', created_at: '2026-07-17T00:00:03Z' },
      { id: 'u-current', role: 'user', content: '当前问题', created_at: '2026-07-17T00:00:04Z' },
    ],
    confirmedContext: '',
    currentMessageId: 'u-current',
  })

  assert.deepEqual(
    Array.from(result.trace.included_message_ids),
    ['a-open', 'u-1', 'a-1', 'a-2'],
  )
})

test('rejects duplicate identifiers and a current message that is not last', () => {
  const buildChatContextPacket = loadBuildChatContextPacket()
  const message = { id: 'u-1', role: 'user', content: '当前问题', created_at: '2026-07-17T00:00:00Z' }

  assert.throws(
    () => buildChatContextPacket({ messages: [message, message], confirmedContext: '', currentMessageId: 'u-1' }),
    /聊天消息编号重复/,
  )
  assert.throws(
    () =>
      buildChatContextPacket({
        messages: [message, { id: 'a-1', role: 'ai', content: '后续回复', created_at: message.created_at }],
        confirmedContext: '',
        currentMessageId: 'u-1',
      }),
    /当前用户消息必须是最后一条消息/,
  )
})

function loadChatStateHelpers() {
  const module = loadChatContextModule()
  assert.equal(
    typeof module.normalizeChatBrainstormState,
    'function',
    '聊天状态迁移器必须导出 normalizeChatBrainstormState',
  )
  assert.equal(
    typeof module.mergeChatBrainstormState,
    'function',
    '聊天状态合并器必须导出 mergeChatBrainstormState',
  )
  return module
}

test('migrates every valid legacy message to schema v2 with deterministic identity', () => {
  const { normalizeChatBrainstormState } = loadChatStateHelpers()
  const legacyMessages = Array.from({ length: 81 }, (_, index) => ({
    role: index % 2 === 0 ? 'user' : 'ai',
    content: ` 原始第 ${index + 1} 条，不得截断 `,
  }))
  legacyMessages.push(
    { role: 'system', content: '非法角色' },
    { role: 'user', content: '  \n\t ' },
    { role: 'ai', content: 42 },
  )

  const first = normalizeChatBrainstormState(legacyMessages, 'project-legacy')
  const second = normalizeChatBrainstormState({ messages: legacyMessages }, 'project-legacy')

  assert.equal(first.schema_version, 2)
  assert.equal(first.messages.length, 81, '81 条合法记录必须全部保留')
  assert.deepEqual(first.messages, second.messages, '裸数组和旧 messages 状态迁移结果必须一致')
  assert.equal(first.messages[0].content, ' 原始第 1 条，不得截断 ')
  assert.equal(first.messages[0].id, second.messages[0].id)
  assert.equal(first.messages[0].created_at, '2000-01-01T00:00:00.000Z')
  assert.equal(first.messages[80].created_at, '2000-01-01T00:01:20.000Z')
})

test('merges local and remote state by message id without deleting newer data or trace', () => {
  const { normalizeChatBrainstormState, mergeChatBrainstormState } = loadChatStateHelpers()
  const local = normalizeChatBrainstormState({
    schema_version: 2,
    messages: [
      { id: 'same', role: 'user', content: '旧内容', created_at: '2026-07-17T00:00:01.000Z' },
      { id: 'local-only', role: 'ai', content: '本地独有', created_at: '2026-07-17T00:00:03.000Z' },
    ],
    last_context_trace: { created_at: '2026-07-17T00:00:03.000Z', included_message_ids: ['same'] },
    updated_at: '2026-07-17T00:00:03.000Z',
  }, 'project-merge')
  const remote = normalizeChatBrainstormState({
    schema_version: 2,
    messages: [
      { id: 'same', role: 'user', content: '更新后的完整内容', created_at: '2026-07-17T00:00:02.000Z' },
      { id: 'remote-only', role: 'ai', content: '远端独有', created_at: '2026-07-17T00:00:04.000Z' },
    ],
    updated_at: '2026-07-17T00:00:04.000Z',
  }, 'project-merge')

  const merged = mergeChatBrainstormState(local, remote, 'project-merge')
  assert.deepEqual(
    Array.from(merged.messages, message => message.id),
    ['same', 'local-only', 'remote-only'],
  )
  assert.equal(merged.messages[0].content, '更新后的完整内容')
  assert.deepEqual(merged.last_context_trace, local.last_context_trace)
  assert.equal(merged.updated_at, '2026-07-17T00:00:04.000Z')

  const equalTime = mergeChatBrainstormState(
    normalizeChatBrainstormState({
      messages: [{ id: 'tie', role: 'user', content: '短', created_at: '2026-07-17T00:00:05.000Z' }],
    }, 'project-merge'),
    normalizeChatBrainstormState({
      messages: [{ id: 'tie', role: 'user', content: '同一时间但更完整的内容', created_at: '2026-07-17T00:00:05.000Z' }],
    }, 'project-merge'),
    'project-merge',
  )
  assert.equal(equalTime.messages[0].content, '同一时间但更完整的内容')
})

test('retains adjacent identical legal messages when they have distinct identifiers', () => {
  const { normalizeChatBrainstormState, mergeChatBrainstormState } = loadChatStateHelpers()
  const duplicated = normalizeChatBrainstormState({
    schema_version: 2,
    messages: [
      { id: 'repeat-a', role: 'user', content: '  同一条原文  ', created_at: '2026-07-17T00:00:01.000Z' },
      { id: 'repeat-b', role: 'user', content: '  同一条原文  ', created_at: '2026-07-17T00:00:02.000Z' },
    ],
  }, 'project-duplicates')

  assert.equal(duplicated.messages.length, 2)
  assert.deepEqual(Array.from(duplicated.messages, message => message.id), ['repeat-a', 'repeat-b'])
  assert.equal(duplicated.messages[0].content, '  同一条原文  ')

  const merged = mergeChatBrainstormState(
    { messages: [duplicated.messages[0]] },
    { messages: [duplicated.messages[1]] },
    'project-duplicates',
  )
  assert.deepEqual(Array.from(merged.messages, message => message.id), ['repeat-a', 'repeat-b'])
})

test('state updated_at is the newest state message or trace timestamp', () => {
  const { mergeChatBrainstormState } = loadChatStateHelpers()
  const merged = mergeChatBrainstormState(
    {
      updated_at: '2026-07-17T00:00:01.000Z',
      messages: [{ id: 'old', role: 'user', content: '旧消息', created_at: '2026-07-17T00:00:09.000Z' }],
      last_context_trace: { created_at: '2026-07-17T00:00:10.000Z' },
    },
    {
      updated_at: '2026-07-17T00:00:02.000Z',
      messages: [{ id: 'new', role: 'ai', content: '最新消息', created_at: '2026-07-17T00:00:12.000Z' }],
      last_context_trace: { created_at: '2026-07-17T00:00:13.000Z' },
    },
    'project-updated-at',
  )
  assert.equal(merged.updated_at, '2026-07-17T00:00:13.000Z')
})

test('legacy message identity uses one shared scope instead of the project identifier', () => {
  const module = loadChatStateHelpers()
  assert.equal(
    module.LEGACY_CHAT_MIGRATION_SCOPE,
    'legacy-workflow-context',
    '前后端旧聊天迁移必须公开同一个固定 scope',
  )
  const legacyMessages = [
    { role: 'user', content: 'LEGACY_SHARED_ID' },
    { role: 'user', content: 'LEGACY_SHARED_ID' },
  ]
  const projectA = module.normalizeChatBrainstormState(legacyMessages, 'project-a')
  const projectB = module.normalizeChatBrainstormState(legacyMessages, 'project-b')

  assert.deepEqual(
    Array.from(projectA.messages, message => ({ id: message.id, created_at: message.created_at })),
    Array.from(projectB.messages, message => ({ id: message.id, created_at: message.created_at })),
  )
  assert.notEqual(projectA.messages[0].id, projectA.messages[1].id, '索引仍须区分两条旧消息')
})

test('bounded outline conversation keeps a final user and assistant pair intact', () => {
  const module = loadChatContextModule()
  assert.equal(typeof module.buildBoundedConversationSource, 'function')
  const result = module.buildBoundedConversationSource({
    messages: [
      { id: 'u-1', role: 'user', content: '用户最终事实：FACT_USER', created_at: '2026-07-17T00:00:01.000Z' },
      { id: 'a-1', role: 'ai', content: '助手最终反馈：FACT_AI', created_at: '2026-07-17T00:00:02.000Z' },
    ],
    confirmedContext: '',
  })
  assert.match(result.source, /FACT_USER/)
  assert.match(result.source, /FACT_AI/)
  assert.deepEqual(Array.from(result.trace.included_message_ids), ['u-1', 'a-1'])
})

test('bounded outline conversation carries confirmed original text and blocks an oversized confirmed context', () => {
  const module = loadChatContextModule()
  const input = {
    messages: [
      { id: 'u-1', role: 'user', content: '普通聊天原文', created_at: '2026-07-17T00:00:01.000Z' },
      { id: 'a-1', role: 'ai', content: '最后一条助手回复', created_at: '2026-07-17T00:00:02.000Z' },
    ],
    confirmedContext: 'confirmed.characters[0].relationship：完整确认原文',
  }
  const result = module.buildBoundedConversationSource(input)
  assert.match(result.source, /完整确认原文/)
  assert.throws(
    () => module.buildBoundedConversationSource({ ...input, confirmedContext: `CONFIRMED_${'甲'.repeat(500)}`, maxChars: 300 }),
    /已确认设定超过聊天上下文预算/,
  )
})

test('save response reconciliation merges the server union into the current browser state', () => {
  const module = loadChatContextModule()
  assert.equal(typeof module.reconcileSavedChatBrainstormState, 'function')
  const current = {
    messages: [{ id: 'b', role: 'user', content: 'FACT_B', created_at: '2026-07-17T00:00:02.000Z' }],
    updated_at: '2026-07-17T00:00:02.000Z',
  }
  const responseWorkflowContext = {
    chat_brainstorm: {
      messages: [
        { id: 'a', role: 'user', content: 'FACT_A', created_at: '2026-07-17T00:00:01.000Z' },
        { id: 'b', role: 'user', content: 'FACT_B', created_at: '2026-07-17T00:00:02.000Z' },
      ],
      updated_at: '2026-07-17T00:00:02.000Z',
    },
  }
  const reconciled = module.reconcileSavedChatBrainstormState(current, responseWorkflowContext, 'project-save-response')
  assert.deepEqual(Array.from(reconciled.messages, message => message.id), ['a', 'b'])
})

test('sequential save coordinator keeps a newer failed save unsaved after an older success', async () => {
  const module = loadChatContextModule()
  assert.equal(typeof module.createSequentialSaveCoordinator, 'function')
  const coordinator = module.createSequentialSaveCoordinator()
  let resolveOlder
  let rejectNewer
  let newerStarted = false
  const older = coordinator.submit(() => new Promise(resolve => { resolveOlder = resolve }))
  const newer = coordinator.submit(() => new Promise((resolve, reject) => {
    newerStarted = true
    rejectNewer = reject
  }))

  await Promise.resolve()
  await Promise.resolve()
  assert.equal(typeof resolveOlder, 'function')
  assert.equal(newerStarted, false, '新保存必须等待旧保存结束后才发出')
  resolveOlder({ workflow_context: {} })
  const olderResult = await older
  await Promise.resolve()
  assert.equal(newerStarted, true)
  rejectNewer(new Error('network failed'))

  const newerResult = await newer
  assert.equal(olderResult.isLatest, false)
  assert.equal(newerResult.isLatest, true)
  assert.equal(newerResult.ok, false)
})

test('chat send lock rejects a second send before it can append or call AI', async () => {
  const module = loadChatContextModule()
  assert.equal(typeof module.createChatSendLock, 'function')
  const lock = module.createChatSendLock()
  let resolveFirst
  const started = []

  async function protectedSend(name) {
    if (!lock.tryAcquire()) return false
    started.push(name)
    try {
      await new Promise(resolve => { resolveFirst = resolve })
      return true
    } finally {
      lock.release()
    }
  }

  const first = protectedSend('url-bootstrap')
  const second = await protectedSend('manual-click')
  assert.equal(second, false)
  assert.deepEqual(started, ['url-bootstrap'], '第二次调用不得追加用户消息或触发第二个 AI 请求')

  resolveFirst()
  assert.equal(await first, true)
  assert.equal(lock.isLocked(), false)
})

test('same-id same-time message conflicts use Unicode code point length', () => {
  const { mergeChatBrainstormState } = loadChatStateHelpers()
  const merged = mergeChatBrainstormState(
    { messages: [{ id: 'emoji-tie', role: 'user', content: '😀', created_at: '2026-07-17T00:00:01.000Z' }] },
    { messages: [{ id: 'emoji-tie', role: 'user', content: 'ab', created_at: '2026-07-17T00:00:01.000Z' }] },
    'project-emoji',
  )
  assert.equal(merged.messages[0].content, 'ab')
})

test('identical current and reconciled chat states do not request a replacement', () => {
  const module = loadChatContextModule()
  assert.equal(typeof module.shouldApplyReconciledChatState, 'function')
  const state = {
    schema_version: 2,
    messages: [{ id: 'same', role: 'user', content: '保持原引用', created_at: '2026-07-17T00:00:01.000Z' }],
    last_context_trace: { created_at: '2026-07-17T00:00:01.000Z', included_message_ids: ['same'] },
    updated_at: '2026-07-17T00:00:01.000Z',
  }
  assert.equal(module.shouldApplyReconciledChatState(state, state, 'project-loop'), false)
})

test('a server union applies once and the identical readback does not queue another save', () => {
  const module = loadChatContextModule()
  const current = {
    schema_version: 2,
    messages: [{ id: 'b', role: 'user', content: 'FACT_B', created_at: '2026-07-17T00:00:02.000Z' }],
    updated_at: '2026-07-17T00:00:02.000Z',
  }
  const serverWorkflow = {
    chat_brainstorm: {
      schema_version: 2,
      messages: [
        { id: 'a', role: 'user', content: 'FACT_A', created_at: '2026-07-17T00:00:01.000Z' },
        { id: 'b', role: 'user', content: 'FACT_B', created_at: '2026-07-17T00:00:02.000Z' },
      ],
      updated_at: '2026-07-17T00:00:02.000Z',
    },
  }
  const union = module.reconcileSavedChatBrainstormState(current, serverWorkflow, 'project-loop')
  assert.equal(module.shouldApplyReconciledChatState(current, union, 'project-loop'), true)
  assert.equal(
    module.shouldApplyReconciledChatState(union, module.reconcileSavedChatBrainstormState(union, serverWorkflow, 'project-loop'), 'project-loop'),
    false,
    '下一次相同回读不得替换状态，因此 debounce 不会再排队保存',
  )
})

test('the current request snapshot keeps this tab user message current after a later server union', () => {
  const module = loadChatContextModule()
  assert.equal(typeof module.buildCurrentChatRequestSnapshot, 'function')
  const currentUserMessage = {
    id: 'u-b',
    role: 'user',
    content: '本轮请求 B：保留我的完整原文',
    created_at: '2026-07-17T00:00:02.000Z',
  }
  const localState = {
    schema_version: 2,
    messages: [
      { id: 'b', role: 'ai', content: '本地已有 B', created_at: '2026-07-17T00:00:01.000Z' },
      currentUserMessage,
    ],
    updated_at: currentUserMessage.created_at,
  }
  const serverWorkflow = {
    chat_brainstorm: {
      schema_version: 2,
      messages: [
        { id: 'a-user', role: 'user', content: '另一标签页更晚的 A 用户消息', created_at: '2026-07-17T00:00:04.000Z' },
        { id: 'a-ai', role: 'ai', content: '另一标签页更晚的 A 回复', created_at: '2026-07-17T00:00:05.000Z' },
      ],
      updated_at: '2026-07-17T00:00:05.000Z',
    },
  }

  const reconciled = module.reconcileSavedChatBrainstormState(localState, serverWorkflow, 'project-current')
  const snapshot = module.buildCurrentChatRequestSnapshot(reconciled.messages, currentUserMessage)
  const result = module.buildChatContextPacket({
    messages: snapshot,
    confirmedContext: '',
    currentMessageId: currentUserMessage.id,
  })

  assert.equal(snapshot.at(-1).id, 'u-b')
  assert.equal(snapshot.at(-1).content, currentUserMessage.content)
  assert.match(result.packet, /另一标签页更晚的 A 用户消息/)
  assert.match(result.packet, /另一标签页更晚的 A 回复/)
  assert.equal(result.currentMessage, currentUserMessage.content)
  assert.doesNotMatch(result.currentMessage, /A 用户消息/)
})
