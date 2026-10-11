import {
  mergeStandardOutlinePacket,
  normalizeStandardOutlinePacket,
  standardOutlineField,
  type StandardOutlineField,
  type StandardOutlinePacket,
} from './standardOutlinePacket'

export const OUTLINE_EDITOR_CONFIRMATION_SECTIONS = [
  { id: 'creative_direction', label: '创作方向', description: '受众、题材、制作形式' },
  { id: 'logline', label: '一句话梗概', description: '故事的核心人物、目标与阻碍' },
  { id: 'world_and_conflict', label: '世界设定与核心冲突', description: '世界观、特殊设定、核心冲突与爽点' },
  { id: 'characters', label: '人物小传', description: '角色姓名、定位和完整人物信息' },
  { id: 'relationships', label: '人物关系', description: '人物之间的前后期关系与转折' },
  { id: 'episode_plan', label: '总集数', description: '用户明确确认的剧集总数' },
  { id: 'episode_outlines', label: '分集集纲', description: '编辑器实际使用的逐集事件字段' },
] as const

export type OutlineEditorConfirmationSectionId =
  typeof OUTLINE_EDITOR_CONFIRMATION_SECTIONS[number]['id']

export type OutlineEditorSectionStatus = 'confirmed' | 'candidate' | 'empty'

export interface CreativeDirectionDraft {
  audience_axis: string
  genre_main: string
  format_type: string
}

export interface WorldAndConflictDraft {
  worldview: string
  golden_finger: string
  conflict: string
}

export interface CharacterDraft {
  id: string
  name: string
  role: string
  info: string
}

export interface RelationshipDraft {
  source: string
  targetName: string
  earlyType: string
  lateType: string
  transitionEpisode: number | null
  finalBoundary: string
  description: string
}

export interface EpisodeOutlineDraft {
  ep: number
  title: string
  summary: string
  conflict: string
  turning: string
  main_scene: string
  relationship_change: string
  info_revealed: string
  satisfaction_type: string
}

export type OutlineEditorConfirmationDraft =
  | CreativeDirectionDraft
  | { logline: string }
  | WorldAndConflictDraft
  | CharacterDraft[]
  | RelationshipDraft[]
  | { total_episodes: number }
  | EpisodeOutlineDraft[]

function text(value: unknown): string {
  return value === null || value === undefined ? '' : String(value).trim()
}

function numberOrNull(value: unknown): number | null {
  const parsed = Math.round(Number(value))
  return Number.isFinite(parsed) && parsed > 0 ? parsed : null
}

function fieldValue<T>(field: StandardOutlineField<T> | undefined, fallback: T): T {
  return field && field.value !== undefined ? field.value : fallback
}

function recordValue(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {}
}

function arrayValue(field: StandardOutlineField<Array<Record<string, unknown>>>): Array<Record<string, unknown>> {
  return Array.isArray(field.value) ? field.value : []
}

function confirmedField<T>(value: T, updatedAt: string) {
  const hasValue = Array.isArray(value)
    ? value.length > 0
    : typeof value === 'number'
      ? Number.isFinite(value) && value > 0
      : text(value) !== ''
  return standardOutlineField(
    value,
    hasValue ? 'confirmed' : 'missing',
    hasValue ? 'user_confirmed' : 'system_inferred',
    updatedAt,
  )
}

function candidateRowsFromCharacters(packet: StandardOutlinePacket): RelationshipDraft[] {
  return arrayValue(packet.characters).flatMap((character) => {
    const source = text(character.name)
    const relationships = Array.isArray(character.relationships) ? character.relationships : []
    return relationships.map((relationship) => normalizeRelationshipDraft(relationship, source))
  }).filter((item): item is RelationshipDraft => item !== null)
}

function normalizeRelationshipDraft(raw: unknown, fallbackSource = ''): RelationshipDraft | null {
  if (typeof raw === 'string') {
    const description = raw.trim()
    return description
      ? {
          source: fallbackSource,
          targetName: '',
          earlyType: '',
          lateType: '',
          transitionEpisode: null,
          finalBoundary: '',
          description,
        }
      : null
  }
  const row = recordValue(raw)
  const normalized = {
    source: text(row.source || row.sourceName || row.source_name || fallbackSource),
    targetName: text(row.targetName || row.target_name || row.target || row.to || row.name),
    earlyType: text(row.earlyType || row.early_type || row.early || row.type || row.relationship),
    lateType: text(row.lateType || row.late_type || row.late || row.afterType || row.after_type),
    transitionEpisode: numberOrNull(
      row.transitionEpisode || row.transition_episode || row.turningEpisode || row.turning_episode,
    ),
    finalBoundary: text(row.finalBoundary || row.final_boundary || row.boundary),
    description: text(row.description || row.desc || row.detail || row.summary),
  }
  return Object.values(normalized).some(value => value !== '' && value !== null) ? normalized : null
}

function normalizeCharacterDraft(raw: unknown, index: number): CharacterDraft {
  const row = recordValue(raw)
  return {
    id: text(row.id) || `outline-character-${index + 1}`,
    name: text(row.name),
    role: text(row.role) || 'supporting',
    info: text(row.info || row.bio),
  }
}

function normalizeEpisodeDraft(raw: unknown, index: number): EpisodeOutlineDraft {
  const row = recordValue(raw)
  return {
    ep: numberOrNull(row.ep || row.episode || row.episode_number) || index + 1,
    title: text(row.title),
    summary: text(row.summary || row.episode_outline),
    conflict: text(row.conflict),
    turning: text(row.turning),
    main_scene: text(row.main_scene),
    relationship_change: text(row.relationship_change),
    info_revealed: text(row.info_revealed),
    satisfaction_type: text(row.satisfaction_type),
  }
}

export function createOutlineEditorConfirmationDraft(
  packet: unknown,
  sectionId: OutlineEditorConfirmationSectionId,
): OutlineEditorConfirmationDraft {
  const normalized = normalizeStandardOutlinePacket(packet)
  if (sectionId === 'creative_direction') {
    return {
      audience_axis: text(fieldValue(normalized.project_profile.audience_axis, '')),
      genre_main: text(fieldValue(normalized.project_profile.genre_main, '')),
      format_type: text(fieldValue(normalized.project_profile.format_type, '')),
    }
  }
  if (sectionId === 'logline') {
    return { logline: text(fieldValue(normalized.story_core.logline, '')) }
  }
  if (sectionId === 'world_and_conflict') {
    return {
      worldview: text(fieldValue(normalized.world_rules.worldview, '')),
      golden_finger: text(fieldValue(normalized.world_rules.golden_finger, '')),
      conflict: text(fieldValue(normalized.story_core.conflict, '')),
    }
  }
  if (sectionId === 'characters') {
    return arrayValue(normalized.characters).map(normalizeCharacterDraft)
  }
  if (sectionId === 'relationships') {
    const directRows = arrayValue(normalized.relationship_timeline)
      .map(item => normalizeRelationshipDraft(item))
      .filter((item): item is RelationshipDraft => item !== null)
    return directRows.length ? directRows : candidateRowsFromCharacters(normalized)
  }
  if (sectionId === 'episode_plan') {
    const confirmed = Number(fieldValue(normalized.episode_count_plan.confirmed_total_episodes, 0))
    const suggested = Number(fieldValue(normalized.episode_count_plan.suggested_total_episodes, 0))
    return { total_episodes: numberOrNull(confirmed || suggested) || 0 }
  }
  return arrayValue(normalized.episode_outlines).map(normalizeEpisodeDraft)
}

function draftHasContent(sectionId: OutlineEditorConfirmationSectionId, draft: OutlineEditorConfirmationDraft) {
  if (sectionId === 'characters') {
    return (draft as CharacterDraft[]).some(item => item.name || item.info)
  }
  if (sectionId === 'relationships') {
    return (draft as RelationshipDraft[]).some(item => (
      item.source || item.targetName || item.earlyType || item.lateType || item.description
    ))
  }
  if (sectionId === 'episode_plan') {
    return numberOrNull((draft as { total_episodes: number }).total_episodes) !== null
  }
  if (sectionId === 'episode_outlines') {
    return (draft as EpisodeOutlineDraft[]).some(item => item.title || item.summary)
  }
  return Object.values(draft as Record<string, unknown>).some(value => text(value) !== '')
}

function sectionWasPreviouslyConfirmed(
  packet: StandardOutlinePacket,
  sectionId: OutlineEditorConfirmationSectionId,
) {
  const confirmed = packet.user_confirmed_fields
  if (confirmed[sectionId]) return true
  if (sectionId === 'creative_direction') return confirmed.project_profile === true
  if (sectionId === 'logline') return confirmed.story_core === true
  if (sectionId === 'world_and_conflict') {
    return confirmed.story_core === true && confirmed.world_rules === true
  }
  if (sectionId === 'characters') return confirmed.characters === true
  if (sectionId === 'relationships') return confirmed.relationship_timeline === true
  if (sectionId === 'episode_plan') return confirmed.episode_count_plan === true
  return confirmed.episode_outlines === true
}

function editorConfirmedFields(packet: StandardOutlinePacket) {
  return Object.fromEntries(
    OUTLINE_EDITOR_CONFIRMATION_SECTIONS
      .filter(section => sectionWasPreviouslyConfirmed(packet, section.id))
      .map(section => [section.id, true] as const),
  ) as Record<string, true>
}

function requireFields(
  groupLabel: string,
  fields: Array<{ label: string; value: unknown }>,
) {
  const missing = fields.filter(item => text(item.value) === '').map(item => item.label)
  if (missing.length) throw new Error(`${groupLabel}还缺少：${missing.join('、')}`)
}

function validateConfirmationDraft(
  packet: StandardOutlinePacket,
  sectionId: OutlineEditorConfirmationSectionId,
  draft: OutlineEditorConfirmationDraft,
) {
  if (sectionId === 'creative_direction') {
    const value = draft as CreativeDirectionDraft
    requireFields('创作方向', [
      { label: '受众', value: value.audience_axis },
      { label: '题材', value: value.genre_main },
      { label: '制作形式', value: value.format_type },
    ])
    return
  }
  if (sectionId === 'logline') {
    requireFields('一句话梗概', [
      { label: '一句话梗概', value: (draft as { logline: string }).logline },
    ])
    return
  }
  if (sectionId === 'world_and_conflict') {
    const value = draft as WorldAndConflictDraft
    requireFields('世界设定与核心冲突', [
      { label: '世界观', value: value.worldview },
      { label: '特殊设定', value: value.golden_finger },
      { label: '核心冲突', value: value.conflict },
    ])
    return
  }
  if (sectionId === 'characters') {
    const characters = (draft as CharacterDraft[]).map(normalizeCharacterDraft)
    if (!characters.length) throw new Error('人物小传至少需要一名角色')
    characters.forEach((character, index) => {
      requireFields(`第${index + 1}个人物`, [
        { label: '角色姓名', value: character.name },
        { label: '人物小传', value: character.info },
      ])
    })
    const names = characters.map(character => character.name)
    if (new Set(names).size !== names.length) throw new Error('人物姓名不能重复')
    return
  }
  if (sectionId === 'relationships') {
    const relationships = draft as RelationshipDraft[]
    relationships.forEach((relationship, index) => {
      requireFields(`第${index + 1}条人物关系`, [
        { label: '人物 A', value: relationship.source },
        { label: '人物 B', value: relationship.targetName },
      ])
      if (!text(relationship.earlyType) && !text(relationship.lateType) && !text(relationship.description)) {
        throw new Error(`第${index + 1}条人物关系还缺少关系类型或关系说明`)
      }
    })
    return
  }
  if (sectionId === 'episode_plan') {
    if (numberOrNull((draft as { total_episodes: number }).total_episodes) === null) {
      throw new Error('总集数必须是大于 0 的整数')
    }
    return
  }

  const totalField = packet.episode_count_plan.confirmed_total_episodes
  const totalEpisodes = (
    totalField?.status === 'confirmed'
    && totalField.source === 'user_confirmed'
  ) ? numberOrNull(fieldValue(totalField, 0)) : null
  if (!totalEpisodes) throw new Error('请先确认总集数，再确认分集集纲')
  const episodes = (draft as EpisodeOutlineDraft[]).map(normalizeEpisodeDraft)
  if (episodes.length !== totalEpisodes) {
    throw new Error(`总集数为 ${totalEpisodes} 集，当前只有 ${episodes.length} 集分集集纲`)
  }
  const episodeNumbers = episodes.map(item => item.ep)
  const expectedNumbers = Array.from({ length: totalEpisodes }, (_, index) => index + 1)
  if (
    new Set(episodeNumbers).size !== episodeNumbers.length
    || episodeNumbers.some((episode, index) => episode !== expectedNumbers[index])
  ) {
    throw new Error(`分集编号必须完整覆盖第 1-${totalEpisodes} 集，且不能重复`)
  }
  episodes.forEach((episode) => {
    requireFields(`第${episode.ep}集`, [
      { label: '标题', value: episode.title },
      { label: '单集集纲', value: episode.summary },
      { label: '本集冲突', value: episode.conflict },
      { label: '转折 / 爆点', value: episode.turning },
      { label: '主场景', value: episode.main_scene },
      { label: '关系变化', value: episode.relationship_change },
      { label: '信息揭露', value: episode.info_revealed },
      { label: '爽点类型', value: episode.satisfaction_type },
    ])
  })
}

export function outlineEditorSectionStatus(
  packet: unknown,
  sectionId: OutlineEditorConfirmationSectionId,
): OutlineEditorSectionStatus {
  const normalized = normalizeStandardOutlinePacket(packet)
  if (sectionWasPreviouslyConfirmed(normalized, sectionId)) return 'confirmed'
  const draft = createOutlineEditorConfirmationDraft(normalized, sectionId)
  return draftHasContent(sectionId, draft) ? 'candidate' : 'empty'
}

function nextUnconfirmedSection(
  confirmedFields: Record<string, true>,
  currentSection: OutlineEditorConfirmationSectionId,
) {
  const currentIndex = OUTLINE_EDITOR_CONFIRMATION_SECTIONS.findIndex(item => item.id === currentSection)
  const later = OUTLINE_EDITOR_CONFIRMATION_SECTIONS
    .slice(currentIndex + 1)
    .find(item => !confirmedFields[item.id])
  if (later) return later.id
  return OUTLINE_EDITOR_CONFIRMATION_SECTIONS.find(item => !confirmedFields[item.id])?.id || ''
}

function attachRelationshipsToCharacters(
  characters: Array<Record<string, unknown>>,
  relationships: RelationshipDraft[],
) {
  return characters.map((character) => {
    const name = text(character.name)
    const rows = relationships
      .filter(item => item.source === name)
      .map(item => ({
        targetName: item.targetName,
        earlyType: item.earlyType,
        lateType: item.lateType,
        transitionEpisode: item.transitionEpisode,
        finalBoundary: item.finalBoundary,
        description: item.description,
        candidateStatus: 'confirmed',
        candidate_status: 'confirmed',
        status: 'confirmed',
      }))
    return {
      ...character,
      relationships: rows,
    }
  })
}

export function applyOutlineEditorSectionConfirmation(
  packet: unknown,
  sectionId: OutlineEditorConfirmationSectionId,
  draft: OutlineEditorConfirmationDraft,
): StandardOutlinePacket {
  if (!OUTLINE_EDITOR_CONFIRMATION_SECTIONS.some(item => item.id === sectionId)) {
    throw new Error(`未知的大纲编辑器确认区：${sectionId}`)
  }

  const normalized = normalizeStandardOutlinePacket(packet)
  validateConfirmationDraft(normalized, sectionId, draft)
  const updatedAt = new Date().toISOString()
  const patch: Partial<StandardOutlinePacket> = {}

  if (sectionId === 'creative_direction') {
    const value = draft as CreativeDirectionDraft
    patch.project_profile = {
      ...normalized.project_profile,
      audience_axis: confirmedField(text(value.audience_axis), updatedAt),
      genre_main: confirmedField(text(value.genre_main), updatedAt),
      format_type: confirmedField(text(value.format_type), updatedAt),
    }
  } else if (sectionId === 'logline') {
    const value = draft as { logline: string }
    patch.story_core = {
      ...normalized.story_core,
      logline: confirmedField(text(value.logline), updatedAt),
    }
  } else if (sectionId === 'world_and_conflict') {
    const value = draft as WorldAndConflictDraft
    patch.world_rules = {
      ...normalized.world_rules,
      worldview: confirmedField(text(value.worldview), updatedAt),
      golden_finger: confirmedField(text(value.golden_finger), updatedAt),
    }
    patch.story_core = {
      ...normalized.story_core,
      conflict: confirmedField(text(value.conflict), updatedAt),
    }
  } else if (sectionId === 'characters') {
    let characters = (draft as CharacterDraft[])
      .map(normalizeCharacterDraft)
      .filter(item => item.name || item.info)
    if (
      normalized.relationship_timeline.status === 'confirmed'
      && normalized.relationship_timeline.source === 'user_confirmed'
    ) {
      const confirmedRelationships = arrayValue(normalized.relationship_timeline)
        .map(item => normalizeRelationshipDraft(item))
        .filter((item): item is RelationshipDraft => item !== null)
      characters = attachRelationshipsToCharacters(
        characters as unknown as Array<Record<string, unknown>>,
        confirmedRelationships,
      ) as unknown as CharacterDraft[]
    }
    patch.characters = confirmedField(
      characters as unknown as Array<Record<string, unknown>>,
      updatedAt,
    )
  } else if (sectionId === 'relationships') {
    const relationships = (draft as RelationshipDraft[])
      .map(item => normalizeRelationshipDraft(item))
      .filter((item): item is RelationshipDraft => item !== null)
    patch.relationship_timeline = standardOutlineField(
      relationships as unknown as Array<Record<string, unknown>>,
      'confirmed',
      'user_confirmed',
      updatedAt,
    )
    patch.characters = {
      ...normalized.characters,
      value: attachRelationshipsToCharacters(arrayValue(normalized.characters), relationships),
      updated_at: updatedAt,
    }
  } else if (sectionId === 'episode_plan') {
    const total = numberOrNull((draft as { total_episodes: number }).total_episodes) || 0
    patch.episode_count_plan = {
      ...normalized.episode_count_plan,
      confirmed_total_episodes: confirmedField(total, updatedAt),
    }
  } else if (sectionId === 'episode_outlines') {
    const episodes = (draft as EpisodeOutlineDraft[])
      .map(normalizeEpisodeDraft)
      .filter(item => item.title || item.summary)
      .sort((left, right) => left.ep - right.ep)
    patch.episode_outlines = confirmedField(
      episodes as unknown as Array<Record<string, unknown>>,
      updatedAt,
    )
  }

  const confirmedFields: Record<string, true> = {
    ...normalized.user_confirmed_fields,
    ...editorConfirmedFields(normalized),
    [sectionId]: true,
  }
  const nextStage = nextUnconfirmedSection(confirmedFields, sectionId)
  const fullyConfirmed = OUTLINE_EDITOR_CONFIRMATION_SECTIONS.every(
    item => confirmedFields[item.id] === true,
  )
  patch.user_confirmed_fields = confirmedFields
  patch.current_stage = fullyConfirmed ? '' : nextStage
  patch.status = fullyConfirmed ? 'confirmed' : 'needs_user_confirmation'
  patch.updated_at = updatedAt

  return mergeStandardOutlinePacket(normalized, patch)
}
