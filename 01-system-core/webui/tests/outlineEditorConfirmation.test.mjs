import assert from 'node:assert/strict'
import { createRequire } from 'node:module'
import fs from 'node:fs'
import path from 'node:path'
import test from 'node:test'

const require = createRequire(import.meta.url)
const webuiRoot = path.resolve(import.meta.dirname, '..')
const jitiPath = require.resolve('jiti')
assert.ok(
  jitiPath.startsWith(path.join(webuiRoot, 'node_modules') + path.sep),
  `测试只能使用 webui/node_modules 中的 jiti，当前解析到：${jitiPath}`,
)
const createJiti = require(jitiPath)
const jiti = createJiti(import.meta.url, {
  interopDefault: false,
  moduleCache: false,
  fsCache: false,
})

const confirmationPath = path.join(
  webuiRoot,
  'src/features/workspace/utils/outlineEditorConfirmation.ts',
)

function loadConfirmationModule() {
  assert.ok(
    fs.existsSync(confirmationPath),
    '缺少编辑器字段确认模块：src/features/workspace/utils/outlineEditorConfirmation.ts',
  )
  const module = jiti(confirmationPath)
  for (const exportName of [
    'OUTLINE_EDITOR_CONFIRMATION_SECTIONS',
    'applyOutlineEditorSectionConfirmation',
    'createOutlineEditorConfirmationDraft',
    'outlineEditorSectionStatus',
  ]) {
    assert.ok(module[exportName], `编辑器字段确认模块必须导出 ${exportName}`)
  }
  return module
}

function candidatePacket() {
  const { createStandardOutlinePacket, standardOutlineField } = jiti(
    path.join(webuiRoot, 'src/features/workspace/utils/standardOutlinePacket.ts'),
  )
  const packet = createStandardOutlinePacket({
    outlineData: {
      audience_axis: '女频',
      genre_main: '悬疑情感',
      format_type: '真人短剧',
      logline: '记忆修复师调查自己失忆真相时，发现爱人正是删掉她记忆的人。',
      worldview: '近未来记忆修复行业合法存在。',
      goldenFinger: '女主能在修复时看见记忆残片。',
      conflict: '寻找真相会摧毁女主现有的亲密关系。',
      episode_count: 2,
      episodes: [
        {
          ep: 1,
          title: '残片',
          summary: '女主接到匿名修复委托。',
          conflict: '委托人拒绝透露身份。',
          turning: '残片里出现爱人的脸。',
          main_scene: '记忆诊疗室',
          relationship_change: '女主开始怀疑爱人',
          info_revealed: '匿名记忆属于女主自己',
          satisfaction_type: '身份反转',
          hook: '不可进入编辑器确认字段',
          start_state: '不可进入编辑器确认字段',
        },
        {
          ep: 2,
          title: '删改者',
          summary: '女主跟踪爱人进入档案库。',
          conflict: '爱人阻止她读取原档。',
          turning: '删除授权书上是女主自己的签名。',
          main_scene: '记忆档案库',
          relationship_change: '怀疑转为对峙',
          info_revealed: '女主曾主动申请删除记忆',
          satisfaction_type: '证据揭露',
        },
      ],
    },
    characters: [
      { id: 'c1', name: '林见夏', role: 'protagonist', info: '记忆修复师，执着追查自己的失忆。' },
      { id: 'c2', name: '周既明', role: 'antagonist', info: '女主爱人，掌握记忆删除真相。' },
    ],
  })
  packet.relationship_timeline = standardOutlineField([
    {
      source: '林见夏',
      targetName: '周既明',
      earlyType: '恋人',
      lateType: '互相审判的知情者',
      transitionEpisode: 2,
      finalBoundary: '第2集前不得揭露主动删除',
      description: '信任因失忆真相破裂',
    },
  ], 'candidate', 'model_suggested')
  return packet
}

test('确认区只使用大纲编辑器真实存在的七组字段', () => {
  const { OUTLINE_EDITOR_CONFIRMATION_SECTIONS } = loadConfirmationModule()
  assert.deepEqual(
    Array.from(OUTLINE_EDITOR_CONFIRMATION_SECTIONS, item => item.id),
    [
      'creative_direction',
      'logline',
      'world_and_conflict',
      'characters',
      'relationships',
      'episode_plan',
      'episode_outlines',
    ],
  )
  const serialized = JSON.stringify(OUTLINE_EDITOR_CONFIRMATION_SECTIONS)
  for (const legacyStage of ['long_arc', 'range_outlines', 'start_state', 'next_hook']) {
    assert.equal(serialized.includes(legacyStage), false, `确认区不得暴露编辑器没有的字段：${legacyStage}`)
  }
})

test('确认一句话梗概时不能顺带确认核心冲突或其他阶段', () => {
  const {
    applyOutlineEditorSectionConfirmation,
    createOutlineEditorConfirmationDraft,
  } = loadConfirmationModule()
  const before = candidatePacket()
  const draft = createOutlineEditorConfirmationDraft(before, 'logline')
  const after = applyOutlineEditorSectionConfirmation(before, 'logline', draft)

  assert.equal(after.story_core.logline.status, 'confirmed')
  assert.equal(after.story_core.logline.source, 'user_confirmed')
  assert.equal(after.story_core.conflict.status, 'candidate')
  assert.equal(after.user_confirmed_fields.logline, true)
  assert.equal(after.user_confirmed_fields.story_core, undefined)
  assert.equal(after.current_stage, 'world_and_conflict')
})

test('确认人物关系时同步回人物小传可识别的 relationships 字段', () => {
  const {
    applyOutlineEditorSectionConfirmation,
    createOutlineEditorConfirmationDraft,
  } = loadConfirmationModule()
  const before = candidatePacket()
  const draft = createOutlineEditorConfirmationDraft(before, 'relationships')
  const after = applyOutlineEditorSectionConfirmation(before, 'relationships', draft)
  const protagonist = after.characters.value.find(item => item.name === '林见夏')

  assert.equal(after.relationship_timeline.status, 'confirmed')
  assert.equal(after.user_confirmed_fields.relationships, true)
  assert.ok(Array.isArray(protagonist.relationships))
  assert.equal(protagonist.relationships[0].targetName, '周既明')
  assert.equal(protagonist.relationships[0].candidateStatus, 'confirmed')
})

test('先确认人物关系再确认人物小传时，已确认关系不能被覆盖', () => {
  const {
    applyOutlineEditorSectionConfirmation,
    createOutlineEditorConfirmationDraft,
  } = loadConfirmationModule()
  let packet = candidatePacket()
  packet = applyOutlineEditorSectionConfirmation(
    packet,
    'relationships',
    createOutlineEditorConfirmationDraft(packet, 'relationships'),
  )
  packet = applyOutlineEditorSectionConfirmation(
    packet,
    'characters',
    createOutlineEditorConfirmationDraft(packet, 'characters'),
  )
  const protagonist = packet.characters.value.find(item => item.name === '林见夏')

  assert.equal(packet.relationship_timeline.status, 'confirmed')
  assert.ok(Array.isArray(protagonist.relationships))
  assert.equal(protagonist.relationships[0].targetName, '周既明')
})

test('单人物故事可以显式确认暂无人物关系', () => {
  const {
    applyOutlineEditorSectionConfirmation,
    outlineEditorSectionStatus,
  } = loadConfirmationModule()
  const { createStandardOutlinePacket, diagnoseStandardOutlinePacketGate } = jiti(
    path.join(webuiRoot, 'src/features/workspace/utils/standardOutlinePacket.ts'),
  )
  let packet = createStandardOutlinePacket({
    outlineData: { episode_count: 1 },
    characters: [{ id: 'solo', name: '独角戏主角', role: 'protagonist', info: '独自完成一次审判。' }],
  })
  packet.characters.status = 'confirmed'
  packet.characters.source = 'user_confirmed'
  packet = applyOutlineEditorSectionConfirmation(packet, 'relationships', [])

  assert.equal(outlineEditorSectionStatus(packet, 'relationships'), 'confirmed')
  assert.equal(packet.relationship_timeline.status, 'confirmed')
  assert.deepEqual(Array.from(packet.relationship_timeline.value), [])
  assert.equal(
    diagnoseStandardOutlinePacketGate(packet, 'range_outlines').includes('请先确认角色关系'),
    false,
  )
})

test('分集确认只保留编辑器可编辑字段，隐藏旧字段不得进入确认结果', () => {
  const {
    applyOutlineEditorSectionConfirmation,
    createOutlineEditorConfirmationDraft,
  } = loadConfirmationModule()
  let before = candidatePacket()
  before = applyOutlineEditorSectionConfirmation(before, 'episode_plan', { total_episodes: 2 })
  const draft = createOutlineEditorConfirmationDraft(before, 'episode_outlines')
  const after = applyOutlineEditorSectionConfirmation(before, 'episode_outlines', draft)
  const first = after.episode_outlines.value[0]

  assert.deepEqual(
    Object.keys(first),
    [
      'ep',
      'title',
      'summary',
      'conflict',
      'turning',
      'main_scene',
      'relationship_change',
      'info_revealed',
      'satisfaction_type',
    ],
  )
  assert.equal(Object.hasOwn(first, 'hook'), false)
  assert.equal(Object.hasOwn(first, 'start_state'), false)
})

test('七组字段逐项显式确认后资料包才变为 confirmed', () => {
  const {
    OUTLINE_EDITOR_CONFIRMATION_SECTIONS,
    applyOutlineEditorSectionConfirmation,
    createOutlineEditorConfirmationDraft,
    outlineEditorSectionStatus,
  } = loadConfirmationModule()
  let packet = candidatePacket()

  for (const section of OUTLINE_EDITOR_CONFIRMATION_SECTIONS) {
    const draft = createOutlineEditorConfirmationDraft(packet, section.id)
    packet = applyOutlineEditorSectionConfirmation(packet, section.id, draft)
    assert.equal(outlineEditorSectionStatus(packet, section.id), 'confirmed')
  }

  assert.equal(packet.status, 'confirmed')
  assert.equal(packet.current_stage, '')
  assert.notEqual(packet.range_outlines.status, 'confirmed', '不可把不可见的范围集纲偷偷标记为已确认')
  assert.notEqual(packet.long_arc.summary.status, 'confirmed', '不可把不可见的长线结构偷偷标记为已确认')
})

test('不可见的范围集纲不能阻断已确认编辑器字段进入后续链路', () => {
  const {
    OUTLINE_EDITOR_CONFIRMATION_SECTIONS,
    applyOutlineEditorSectionConfirmation,
    createOutlineEditorConfirmationDraft,
  } = loadConfirmationModule()
  const { diagnoseStandardOutlinePacketGate } = jiti(
    path.join(webuiRoot, 'src/features/workspace/utils/standardOutlinePacket.ts'),
  )
  let packet = candidatePacket()
  for (const section of OUTLINE_EDITOR_CONFIRMATION_SECTIONS) {
    packet = applyOutlineEditorSectionConfirmation(
      packet,
      section.id,
      createOutlineEditorConfirmationDraft(packet, section.id),
    )
  }

  assert.deepEqual(
    Array.from(diagnoseStandardOutlinePacketGate(packet, 'script_generation')),
    [],
    '编辑器没有范围集纲字段，不能要求用户确认一个看不见的字段',
  )
})

test('旧项目已经确认的资料映射到新版七项状态时不能倒退为待确认', () => {
  const {
    OUTLINE_EDITOR_CONFIRMATION_SECTIONS,
    outlineEditorSectionStatus,
  } = loadConfirmationModule()
  const { createStandardOutlinePacket } = jiti(
    path.join(webuiRoot, 'src/features/workspace/utils/standardOutlinePacket.ts'),
  )
  const packet = createStandardOutlinePacket({
    outlineData: {
      audience_axis: '女频',
      genre_main: '悬疑情感',
      format_type: '真人短剧',
      logline: '女主追查被删除的记忆。',
      worldview: '近未来记忆行业。',
      goldenFinger: '可读取记忆残片。',
      conflict: '真相与亲密关系互相冲突。',
      episode_count: 1,
      episodes: [{ ep: 1, title: '残片', summary: '女主发现第一块证据。' }],
    },
    characters: [{ id: 'c1', name: '林见夏', role: 'protagonist', info: '记忆修复师。' }],
    confirmed: true,
  })

  assert.deepEqual(
    Array.from(
      OUTLINE_EDITOR_CONFIRMATION_SECTIONS,
      section => outlineEditorSectionStatus(packet, section.id),
    ),
    Array(7).fill('confirmed'),
  )
})

test('创作方向和世界设定不能只填一部分就确认整组', () => {
  const { applyOutlineEditorSectionConfirmation } = loadConfirmationModule()
  const packet = candidatePacket()

  assert.throws(
    () => applyOutlineEditorSectionConfirmation(packet, 'creative_direction', {
      audience_axis: '',
      genre_main: '悬疑情感',
      format_type: '',
    }),
    /受众、制作形式/,
  )
  assert.throws(
    () => applyOutlineEditorSectionConfirmation(packet, 'world_and_conflict', {
      worldview: '近未来记忆行业。',
      golden_finger: '',
      conflict: '',
    }),
    /特殊设定、核心冲突/,
  )
})

test('分集集纲数量和可编辑字段不完整时不能标记整组确认', () => {
  const {
    applyOutlineEditorSectionConfirmation,
    createOutlineEditorConfirmationDraft,
  } = loadConfirmationModule()
  let packet = candidatePacket()
  packet = applyOutlineEditorSectionConfirmation(
    packet,
    'episode_plan',
    { total_episodes: 2 },
  )
  const onlyOneEpisode = createOutlineEditorConfirmationDraft(packet, 'episode_outlines').slice(0, 1)
  assert.throws(
    () => applyOutlineEditorSectionConfirmation(packet, 'episode_outlines', onlyOneEpisode),
    /总集数为 2 集，当前只有 1 集/,
  )

  const twoEpisodes = createOutlineEditorConfirmationDraft(packet, 'episode_outlines')
  twoEpisodes[1].relationship_change = ''
  assert.throws(
    () => applyOutlineEditorSectionConfirmation(packet, 'episode_outlines', twoEpisodes),
    /第2集.*关系变化/,
  )
})

test('最终可读大纲完整保留人物关系双方、前后期变化和边界', () => {
  const {
    applyOutlineEditorSectionConfirmation,
    createOutlineEditorConfirmationDraft,
  } = loadConfirmationModule()
  const { projectStandardOutlinePacketToOutline } = jiti(
    path.join(webuiRoot, 'src/features/workspace/utils/standardOutlinePacket.ts'),
  )
  let packet = candidatePacket()
  packet = applyOutlineEditorSectionConfirmation(
    packet,
    'relationships',
    createOutlineEditorConfirmationDraft(packet, 'relationships'),
  )
  const rawText = projectStandardOutlinePacketToOutline(packet).rawOutlineText

  for (const expected of [
    '林见夏',
    '周既明',
    '早期关系：恋人',
    '后期关系：互相审判的知情者',
    '转折集：第2集',
    '禁止提前揭露：第2集前不得揭露主动删除',
    '信任因失忆真相破裂',
  ]) {
    assert.equal(rawText.includes(expected), true, `可读大纲缺少人物关系内容：${expected}`)
  }
})
