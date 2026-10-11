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

const standardOutlinePacketPath = path.join(
  webuiRoot,
  'src/features/workspace/utils/standardOutlinePacket.ts',
)

function loadStandardOutlinePacketModule() {
  assert.ok(
    fs.existsSync(standardOutlinePacketPath),
    '标准大纲资料包模块缺失：请保留 src/features/workspace/utils/standardOutlinePacket.ts',
  )
  const packetModule = jiti(standardOutlinePacketPath)
  for (const exportName of [
    'createStandardOutlinePacket',
    'mergeStandardOutlinePacket',
    'normalizeStandardOutlinePacket',
    'projectStandardOutlinePacketToOutline',
  ]) {
    assert.equal(
      typeof packetModule[exportName],
      'function',
      `标准大纲资料包模块必须导出 ${exportName}`,
    )
  }
  return packetModule
}

test('旧版标准资料包归一化时补齐空来源材料，编辑投影不泄漏展示文本', () => {
  const {
    normalizeStandardOutlinePacket,
    projectStandardOutlinePacketToOutline,
  } = loadStandardOutlinePacketModule()
  const rawSource = `# 历史粘贴原文\n\nSOURCE_ONLY_DO_NOT_COPY_TO_EDITOR\n\n第1集：旧案重启。`
  const legacyPacket = {
    schema_version: 'chat_outline_packet_v1',
    status: 'needs_user_confirmation',
    current_stage: 'story_core',
    story_core: {
      logline: { value: '女主为姐姐旧案回到故乡取证', status: 'candidate', source: 'model_suggested' },
      conflict: { value: '证据与亲情冲突', status: 'candidate', source: 'model_suggested' },
    },
    world_rules: {
      worldview: { value: '当代县城', status: 'candidate', source: 'model_suggested' },
      golden_finger: { value: '', status: 'missing', source: 'system_inferred' },
      raw_outline_text: { value: rawSource, status: 'candidate', source: 'user_confirmed' },
    },
  }

  const normalized = normalizeStandardOutlinePacket(legacyPacket)
  assert.ok(normalized.source_material, '旧版 JSON 归一化后必须补齐 source_material')
  assert.deepEqual(normalized.source_material, {
    kind: 'none',
    raw_text: '',
    captured_at: '',
  })
  assert.equal(normalized.world_rules.raw_outline_text.value, rawSource)

  const projection = projectStandardOutlinePacketToOutline(normalized)
  assert.equal(
    Object.hasOwn(projection.outlineData, 'source_material'),
    false,
    '供标准编辑器使用的结构化投影不得混入 source_material 原文对象',
  )
  assert.equal(
    projection.rawOutlineText.includes('SOURCE_ONLY_DO_NOT_COPY_TO_EDITOR'),
    false,
    '标准编辑器可读投影不得把仅用于溯源的原文直接混入编辑内容',
  )

  projection.outlineData.logline = '编辑器中的局部修改'
  assert.equal(normalized.source_material.raw_text, '', '编辑投影不得推断或写入来源原文')
})

test('显式来源材料原样保存，rawOutlineText 不推断为用户来源', () => {
  const { createStandardOutlinePacket } = loadStandardOutlinePacketModule()
  const sourceRawText = '  原文首尾\n'
  const packet = createStandardOutlinePacket({
    rawOutlineText: '这是标准展示文本，不是来源原文。',
    source_material: {
      kind: 'pasted_outline',
      raw_text: sourceRawText,
      captured_at: '2026-07-17T00:00:00.000Z',
    },
  })
  assert.deepEqual(packet.source_material, {
    kind: 'pasted_outline',
    raw_text: sourceRawText,
    captured_at: '2026-07-17T00:00:00.000Z',
  })

  const noExplicitSource = createStandardOutlinePacket({
    rawOutlineText: sourceRawText,
  })
  assert.deepEqual(noExplicitSource.source_material, {
    kind: 'none',
    raw_text: '',
    captured_at: '',
  })

  const explicitNoneWithPayload = createStandardOutlinePacket({
    source_material: {
      kind: 'none',
      raw_text: 'SOURCE_NONE_SENTINEL',
      captured_at: '2026-07-17T00:00:00.000Z',
    },
  })
  assert.deepEqual(explicitNoneWithPayload.source_material, {
    kind: 'none',
    raw_text: '',
    captured_at: '',
  })

  const invalidKind = createStandardOutlinePacket({
    source_material: {
      kind: 'unsupported_kind',
      raw_text: sourceRawText,
      captured_at: '2026-07-17T00:00:00.000Z',
    },
  })
  assert.deepEqual(invalidKind.source_material, {
    kind: 'none',
    raw_text: '',
    captured_at: '',
  })
})

test('合并资料包时空来源补丁保留原来源，非空有效来源替换原来源', () => {
  const {
    createStandardOutlinePacket,
    mergeStandardOutlinePacket,
  } = loadStandardOutlinePacketModule()
  const base = createStandardOutlinePacket({
    source_material: {
      kind: 'pasted_outline',
      raw_text: '用户粘贴的原始大纲',
      captured_at: '2026-07-17T00:00:00.000Z',
    },
  })

  const retained = mergeStandardOutlinePacket(base, {
    source_material: { kind: 'none', raw_text: '', captured_at: '' },
  })
  assert.deepEqual(retained.source_material, base.source_material)

  const replacement = {
    kind: 'chat_synthesis',
    raw_text: '聊天整理的来源原文',
    captured_at: '2026-07-17T01:00:00.000Z',
  }
  const replaced = mergeStandardOutlinePacket(base, { source_material: replacement })
  assert.deepEqual(replaced.source_material, replacement)
})

test('标准编辑投影隔离有效来源原文，且不修改资料包内的来源', () => {
  const {
    createStandardOutlinePacket,
    projectStandardOutlinePacketToOutline,
  } = loadStandardOutlinePacketModule()
  const sourceMaterial = {
    kind: 'pasted_outline',
    raw_text: '原始素材\nSOURCE_MATERIAL_SENTINEL_DO_NOT_PROJECT\n第1集：案件重启。',
    captured_at: '2026-07-17T02:00:00.000Z',
  }
  const packet = createStandardOutlinePacket({
    source_material: sourceMaterial,
  })
  const projection = projectStandardOutlinePacketToOutline(packet)

  assert.equal(projection.rawOutlineText.includes('SOURCE_MATERIAL_SENTINEL_DO_NOT_PROJECT'), false)
  assert.equal(JSON.stringify(projection.outlineData).includes('SOURCE_MATERIAL_SENTINEL_DO_NOT_PROJECT'), false)
  assert.deepEqual(packet.source_material, sourceMaterial)
})
