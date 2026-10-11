import { computed, type Ref } from 'vue'
import {
  hasExecutableSeriesSimulationContracts,
  hasSeriesSimulationContracts,
  storySimulationContractCount,
} from './useStorySimulation'

type OutlineDataLike = {
  logline?: string
  worldview?: string
  goldenFinger?: string
  conflict?: string
  episodes?: Array<Record<string, any>>
}

const REQUIRED_FRONTMATTER_FIELDS = [
  { field: 'logline', label: '一句话梗概' },
  { field: 'worldview', label: '世界观' },
  { field: 'goldenFinger', label: '金手指/差异化' },
  { field: 'conflict', label: '核心冲突' },
]

const REQUIRED_EPISODE_FIELDS = [
  'summary',
  'conflict',
  'turning',
  'main_scene',
  'relationship_change',
  'info_revealed',
]

const REQUIRED_CHARACTER_BIO_FIELDS = [
  { field: 'voiceprint', label: '声纹' },
  { field: 'inner_need', label: '内在需求' },
  { field: 'resource', label: '资源/筹码' },
  { field: 'first_appearance_function', label: '首次出场功能' },
  { field: 'relationship_tension', label: '关系张力' },
]

const GENERIC_SCENES = new Set(['公司', '家里', '房间', '办公室', '某地', '室内', '会议室'])

const OUTLINE_GATE_REPAIR_GUIDES = [
  {
    prefix: '大纲草稿尚未确认进入角色设计',
    hint: '回到大纲页，先点击“完成 → 角色设计”，让当前大纲进入主生成链路。',
  },
  {
    prefix: '大纲前置信息缺少工业化字段',
    hint: '回到大纲页，按缺失项补齐一句可拍、可执行的信息；每项都要能指导写手，而不是只写概念词。',
  },
  {
    prefix: '大纲缺少分集结构',
    hint: '回到大纲页，先生成或手动补齐集纲，每集至少要有事件、冲突、转折和结尾钩子。',
  },
  {
    prefix: '大纲分集缺少可执行字段',
    hint: '回到大纲页对应集，把主线、冲突、转折、主场景、关系变化、信息揭露补成写手能直接执行的句子。',
  },
  {
    prefix: '大纲分集主场景过泛',
    hint: '回到大纲页，把主场景写成具体空间和压力现场，例如“档案室主控台与通风口”“早餐店收银台与后厨监控屏”。',
  },
  {
    prefix: '角色库尚未从大纲派生或确认',
    hint: '回到角色设计页，先确认主角、对手、关键配角，至少保证每个核心角色都有主线功能。',
  },
  {
    prefix: '人物小传缺少工业化字段',
    hint: '回到角色设计页，把上面缺的字段补成具体可拍信息；不要只写身份标签，要写这个角色如何制造剧情。',
  },
  {
    prefix: '全剧情推演尚未形成分集契约',
    hint: '回到大纲页，重新同步全剧情推演，让每集都有可继承的剧情契约，再进入剧本写作。',
  },
  {
    prefix: '全剧情推演分集契约不完整',
    hint: '回到大纲页，重新同步全剧情推演，确保每一集都有对应契约，避免后续剧本断档。',
  },
  {
    prefix: '全剧情推演分集契约内容不够可执行',
    hint: '回到大纲页，补齐每集摘要、冲突、主场景、关系变化和信息揭露；只编号齐不代表能进入剧本生成。',
  },
]

function hasSpecificText(value: unknown) {
  return String(value || '').trim().length >= 2
}

function hasIndustrialText(value: unknown, minLength = 6) {
  const text = String(value || '').trim()
  if (text.length < minLength) return false
  return !['无', '暂无', '待补充', '不适用', '后续补充'].includes(text)
}

function isGenericScene(value: unknown) {
  const text = String(value || '').trim()
  return !text || GENERIC_SCENES.has(text)
}

function hasCompleteSeriesSimulationContracts(packet: any, expectedEpisodes: number) {
  return hasExecutableSeriesSimulationContracts(packet, expectedEpisodes)
}

function escapeRegExp(value: string) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}

const CHARACTER_FIELD_ALIASES: Record<string, string[]> = {
  voiceprint: ['voiceprint', 'voicePrint', 'voice_style', 'voiceStyle'],
  inner_need: ['inner_need', 'innerNeed', 'motivation', 'goal'],
  resource: ['resource', 'resources', 'leverage'],
  first_appearance_function: ['first_appearance_function', 'firstSceneFunction', 'first_scene_function', 'traits'],
  relationship_tension: ['relationship_tension', 'relationshipTension', 'relationship_pressure'],
}

const CHARACTER_TEXT_LABELS: Record<string, string[]> = {
  voiceprint: ['声纹', '说话方式', '声线', '音色', '语言风格', '压力选择模式'],
  inner_need: ['内在需求', '深层需求', '核心需求', '动机', '目标', '欲望', '恐惧或代价', '情感弧线'],
  resource: ['资源/筹码', '资源', '筹码', '底牌', '证据', '能力边界'],
  first_appearance_function: ['首次出场功能', '出场功能', '剧情功能', '功能', '与核心冲突关系'],
  relationship_tension: ['关系张力', '关系压力', '关系', '人物关系', '角色关系', '与核心冲突关系', '情感弧线'],
}

const CHARACTER_TEXT_SOURCE_FIELDS = [
  'info',
  'background',
  'notes',
  'personality',
  'motivation',
  'arc',
  'traits',
  'voice_style',
]

function extractCharacterTextField(character: Record<string, any>, field: string) {
  const labels = CHARACTER_TEXT_LABELS[field] || []
  if (labels.length === 0) return ''
  const text = CHARACTER_TEXT_SOURCE_FIELDS
    .map((key) => String(character[key] || '').trim())
    .filter(Boolean)
    .join('\n')
  if (!text) return ''

  const labelPattern = labels.map(escapeRegExp).join('|')
  const match = text.match(new RegExp(`(?:^|[\\n；;])\\s*(?:${labelPattern})\\s*[：:=＝]\\s*([^\\n；;]{4,180})`))
  const value = match?.[1]?.trim() || ''
  return hasIndustrialText(value, 8) ? value : ''
}

function getCharacterField(character: Record<string, any>, field: string) {
  const bio = character.bio && typeof character.bio === 'object' ? character.bio : {}
  const keys = CHARACTER_FIELD_ALIASES[field] || [field]
  for (const key of keys) {
    const value = character[key] ?? bio[key]
    if (hasIndustrialText(value, 8)) return String(value).trim()
  }
  const labeledText = extractCharacterTextField(character, field)
  if (labeledText) return labeledText
  if (field === 'relationship_tension') {
    const relationships = Array.isArray(character.relationships) ? character.relationships : []
    if (relationships.some((rel) => hasIndustrialText(rel?.description, 12) && hasIndustrialText(rel?.trigger, 4) && hasIndustrialText(rel?.consequence, 6))) {
      return 'relationships'
    }
    if (relationships.some((rel) => hasIndustrialText(rel?.description, 20) && hasIndustrialText(rel?.type, 2))) {
      return 'relationships'
    }
  }
  return ''
}

function buildOutlineGateRepairHint(issue: string) {
  const guide = OUTLINE_GATE_REPAIR_GUIDES.find((item) => issue.startsWith(item.prefix))
  return guide?.hint || '回到大纲页，先补齐当前阻断项要求的信息，再进入剧本写作。'
}

export function useOutlineGate(options: {
  outlineData: Ref<OutlineDataLike>
  characters: Ref<Array<Record<string, any>>>
  workflowContext: Ref<Record<string, any>>
}) {
  function buildOutlineGateIssues(episodeLimit?: number) {
    const issues: string[] = []
    const outline = options.outlineData.value
    const allEpisodes = Array.isArray(outline.episodes) ? outline.episodes : []
    const requestedEpisodeCount = Math.round(Number(episodeLimit) || 0)
    const expectedEpisodeCount = requestedEpisodeCount > 0
      ? Math.max(1, Math.min(allEpisodes.length || requestedEpisodeCount, requestedEpisodeCount))
      : allEpisodes.length
    const episodes = expectedEpisodeCount > 0 ? allEpisodes.slice(0, expectedEpisodeCount) : allEpisodes
    const characters = Array.isArray(options.characters.value) ? options.characters.value : []
    const outlineState = options.workflowContext.value?.outline_state || {}
    const hasMainChainCommitFlag = Object.prototype.hasOwnProperty.call(outlineState, 'main_chain_committed')
    const simulationPacket = options.workflowContext.value?.series_simulation_packet
    const simulationContractCount = storySimulationContractCount(simulationPacket)
    const hasCompleteSimulationContracts = hasCompleteSeriesSimulationContracts(simulationPacket, expectedEpisodeCount)

    if (hasMainChainCommitFlag && (outlineState.main_chain_committed !== true || outlineState.main_chain_dirty === true)) {
      issues.push('大纲草稿尚未确认进入角色设计')
    }

    const missingFrontmatter = REQUIRED_FRONTMATTER_FIELDS
      .filter((item) => !hasIndustrialText((outline as Record<string, any>)[item.field], item.field === 'logline' ? 10 : 8))
      .map((item) => item.label)
    if (missingFrontmatter.length > 0) {
      issues.push(`大纲前置信息缺少工业化字段：${missingFrontmatter.join('、')}`)
    }

    if (episodes.length === 0 && !hasCompleteSimulationContracts) {
      issues.push(hasSeriesSimulationContracts(simulationPacket)
        ? '全剧情推演分集契约内容不够可执行'
        : '大纲缺少分集结构')
    } else if (outlineState.main_chain_committed === true && !hasCompleteSimulationContracts) {
      const weakEpisode = episodes.findIndex((episode) =>
        REQUIRED_EPISODE_FIELDS.some((field) => !hasSpecificText(episode?.[field])),
      )
      if (weakEpisode >= 0) {
        issues.push(`大纲分集缺少可执行字段：第${weakEpisode + 1}集需补齐主线、冲突、转折、主场景、关系变化和信息揭露`)
      }
      const genericSceneEpisode = episodes.findIndex((episode) => isGenericScene(episode?.main_scene || episode?.mainScene))
      if (genericSceneEpisode >= 0) {
        issues.push(`大纲分集主场景过泛：第${genericSceneEpisode + 1}集需补成可拍空间和场域压力`)
      }
    }

    if (characters.length === 0) {
      issues.push('角色库尚未从大纲派生或确认')
    } else if (outlineState.main_chain_committed === true) {
      const weakCharacter = characters.find((character) =>
        REQUIRED_CHARACTER_BIO_FIELDS.some((item) => !getCharacterField(character, item.field)),
      )
      if (weakCharacter) {
        const missing = REQUIRED_CHARACTER_BIO_FIELDS
          .filter((item) => !getCharacterField(weakCharacter, item.field))
          .map((item) => item.label)
        issues.push(`人物小传缺少工业化字段：${String(weakCharacter.name || '未命名角色')} 需补齐${missing.join('、')}`)
      }
    }

    if (!hasSeriesSimulationContracts(simulationPacket)) {
      issues.push('全剧情推演尚未形成分集契约')
    } else if (expectedEpisodeCount > 0 && simulationContractCount < expectedEpisodeCount) {
      issues.push('全剧情推演分集契约不完整')
    } else if (!hasCompleteSimulationContracts) {
      issues.push('全剧情推演分集契约内容不够可执行')
    }

    return issues
  }

  const outlineGateIssues = computed(() => buildOutlineGateIssues())

  function outlineGateIssuesForEpisodeLimit(episodeLimit: number) {
    return buildOutlineGateIssues(episodeLimit)
  }

  const canGenerateScript = computed(() => outlineGateIssues.value.length === 0)
  const outlineGateFixHints = computed(() =>
    outlineGateIssues.value
      .map(buildOutlineGateRepairHint)
      .filter((hint, index, list) => hint && list.indexOf(hint) === index),
  )

  function firstBlockingMessage(episodeLimit?: number) {
    const issues = episodeLimit ? buildOutlineGateIssues(episodeLimit) : outlineGateIssues.value
    return issues[0] || ''
  }

  function firstRepairHint(episodeLimit?: number) {
    const hints = episodeLimit
      ? buildOutlineGateIssues(episodeLimit)
        .map(buildOutlineGateRepairHint)
        .filter((hint, index, list) => hint && list.indexOf(hint) === index)
      : outlineGateFixHints.value
    return hints[0] || ''
  }

  return {
    outlineGateIssues,
    outlineGateIssuesForEpisodeLimit,
    outlineGateFixHints,
    canGenerateScript,
    firstBlockingMessage,
    firstRepairHint,
  }
}
