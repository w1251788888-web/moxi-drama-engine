export type StandardOutlineFieldStatus = 'confirmed' | 'candidate' | 'missing' | 'conflict' | 'side_note'
export type StandardOutlinePacketStatus = 'draft' | 'needs_user_confirmation' | 'confirmed' | 'blocked'
export type StandardOutlineFieldSource = 'user_confirmed' | 'user_provided' | 'model_suggested' | 'system_inferred'
export type StandardOutlineGateTarget = 'range_outlines' | 'episode_outlines' | 'script_generation'

export interface StandardOutlineNormalizationProgress {
  state: 'not_started' | 'running' | 'completed' | 'incomplete'
  total_chunks: number
  next_chunk_index: number
  failed_chunk_index?: number
}

export interface StandardOutlineSourceMaterial {
  kind: 'pasted_outline' | 'chat_synthesis' | 'none'
  raw_text: string
  captured_at: string
  normalization?: StandardOutlineNormalizationProgress
}

export interface StandardOutlineContentCorrectnessSummary {
  recognized: string[]
  inferred: string[]
  incomplete: string[]
  unrecognized: string[]
}

export interface StandardOutlineField<T = unknown> {
  value: T
  source: StandardOutlineFieldSource
  status: StandardOutlineFieldStatus
  updated_at: string
}

export interface StandardOutlinePacket {
  schema_version: 'chat_outline_packet_v1'
  status: StandardOutlinePacketStatus
  current_stage: string
  source_material: StandardOutlineSourceMaterial
  project_profile: Record<string, StandardOutlineField>
  story_core: Record<string, StandardOutlineField>
  world_rules: Record<string, StandardOutlineField>
  characters: StandardOutlineField<Array<Record<string, unknown>>>
  relationship_timeline: StandardOutlineField<Array<Record<string, unknown>>>
  episode_count_plan: Record<string, StandardOutlineField>
  long_arc: Record<string, StandardOutlineField>
  range_outlines: StandardOutlineField<Array<Record<string, unknown>>>
  episode_outlines: StandardOutlineField<Array<Record<string, unknown>>>
  content_correctness_summary: StandardOutlineContentCorrectnessSummary
  quality_gaps: string[]
  conflict_issues: string[]
  user_confirmed_fields: Record<string, true>
  generated_at: string
  updated_at: string
}

export interface StandardOutlineProjection {
  outlineData: Record<string, unknown>
  outlineCharacters: Array<Record<string, unknown>>
  rawOutlineText: string
}

export const STANDARD_OUTLINE_STAGE_ORDER = [
  'project_profile',
  'story_core',
  'world_rules',
  'characters',
  'relationship_timeline',
  'episode_count_plan',
  'long_arc',
  'range_outlines',
  'episode_outlines',
] as const

function _now() {
  return new Date().toISOString()
}

function _isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value && typeof value === 'object' && !Array.isArray(value))
}

function _text(value: unknown): string {
  if (value === null || value === undefined) return ''
  if (typeof value === 'string') return value.trim()
  if (typeof value === 'number' || typeof value === 'boolean') return String(value)
  if (Array.isArray(value)) return value.map(_text).filter(Boolean).join('；')
  if (_isRecord(value)) {
    return _text(value.value ?? value.summary ?? value.text ?? value.title ?? value.description)
  }
  return ''
}

function _array(value: unknown): Array<Record<string, unknown>> {
  if (!Array.isArray(value)) return []
  return value.filter(_isRecord)
}

export function standardOutlineField<T>(
  value: T,
  status: StandardOutlineFieldStatus,
  source: StandardOutlineFieldSource,
  updatedAt = _now(),
): StandardOutlineField<T> {
  return { value, status, source, updated_at: updatedAt }
}

function _candidate<T>(value: T, updatedAt: string) {
  return standardOutlineField(value, value ? 'candidate' : 'missing', value ? 'model_suggested' : 'system_inferred', updatedAt)
}

function _confirmed<T>(value: T, updatedAt: string) {
  return standardOutlineField(value, 'confirmed', 'user_confirmed', updatedAt)
}

function _normalizeField<T>(raw: unknown, fallback: T, updatedAt: string): StandardOutlineField<T> {
  if (_isRecord(raw) && 'status' in raw && 'value' in raw) {
    const status = String(raw.status || 'candidate') as StandardOutlineFieldStatus
    const source = String(raw.source || (status === 'confirmed' ? 'user_confirmed' : 'model_suggested')) as StandardOutlineFieldSource
    return {
      value: (raw.value === undefined ? fallback : raw.value) as T,
      status,
      source,
      updated_at: String(raw.updated_at || updatedAt),
    }
  }
  return _candidate((raw === undefined ? fallback : raw) as T, updatedAt)
}

function _normalizeFieldRecord(raw: unknown, defaults: Record<string, unknown>, updatedAt: string) {
  const source = _isRecord(raw) ? raw : {}
  return Object.fromEntries(
    Object.entries(defaults).map(([key, fallback]) => [key, _normalizeField(source[key], fallback, updatedAt)]),
  )
}

function _isConfirmedField(field: unknown) {
  if (!_isRecord(field) || field.status !== 'confirmed' || field.value === undefined) return false
  if (Array.isArray(field.value)) return field.value.length > 0
  return _text(field.value) !== ''
}

function _isExplicitlyConfirmedField(field: unknown) {
  return Boolean(
    _isRecord(field)
    && field.status === 'confirmed'
    && field.source === 'user_confirmed'
    && field.value !== undefined,
  )
}

function _fieldValue<T>(field: unknown, fallback: T): T {
  if (_isRecord(field) && 'value' in field) return (field.value === undefined ? fallback : field.value) as T
  return fallback
}

function _fieldText(field: unknown) {
  return _text(_fieldValue(field, ''))
}

function _fieldArray(field: unknown) {
  return _array(_fieldValue(field, []))
}

function _normalizeTextArray(value: unknown): string[] {
  return Array.isArray(value) ? value.map(_text).filter(Boolean) : []
}

function _emptyContentCorrectnessSummary(): StandardOutlineContentCorrectnessSummary {
  return { recognized: [], inferred: [], incomplete: [], unrecognized: [] }
}

function _normalizeContentCorrectnessSummary(raw: unknown): StandardOutlineContentCorrectnessSummary {
  if (!_isRecord(raw)) return _emptyContentCorrectnessSummary()
  return {
    recognized: _normalizeTextArray(raw.recognized),
    inferred: _normalizeTextArray(raw.inferred),
    incomplete: _normalizeTextArray(raw.incomplete),
    unrecognized: _normalizeTextArray(raw.unrecognized),
  }
}

function _emptySourceMaterial(): StandardOutlineSourceMaterial {
  return { kind: 'none', raw_text: '', captured_at: '' }
}

function _normalizeSourceMaterial(raw: unknown): StandardOutlineSourceMaterial {
  if (!_isRecord(raw)) return _emptySourceMaterial()
  if (raw.kind !== 'pasted_outline' && raw.kind !== 'chat_synthesis' && raw.kind !== 'none') {
    return _emptySourceMaterial()
  }
  if (raw.kind === 'none') return _emptySourceMaterial()
  const source: StandardOutlineSourceMaterial = {
    kind: raw.kind,
    raw_text: typeof raw.raw_text === 'string' ? raw.raw_text : '',
    captured_at: typeof raw.captured_at === 'string' ? raw.captured_at : '',
  }
  if (_isRecord(raw.normalization)) {
    const requestedState = String(raw.normalization.state || '')
    const totalChunks = Number(raw.normalization.total_chunks)
    const nextChunkIndex = Number(raw.normalization.next_chunk_index)
    const failedChunkIndex = Number(raw.normalization.failed_chunk_index)
    if (
      (requestedState === 'not_started' || requestedState === 'running' || requestedState === 'completed' || requestedState === 'incomplete')
      && Number.isInteger(totalChunks)
      && totalChunks >= 0
      && Number.isInteger(nextChunkIndex)
    ) {
      const clampedNextIndex = Math.max(0, Math.min(totalChunks, nextChunkIndex))
      const state: StandardOutlineNormalizationProgress['state'] = requestedState === 'completed' && clampedNextIndex !== totalChunks
        ? 'incomplete'
        : requestedState === 'running' && nextChunkIndex !== clampedNextIndex
          ? 'incomplete'
          : requestedState as StandardOutlineNormalizationProgress['state']
      source.normalization = {
        state,
        total_chunks: totalChunks,
        next_chunk_index: clampedNextIndex,
        ...(Number.isInteger(failedChunkIndex) && failedChunkIndex >= 0 && failedChunkIndex < totalChunks
          ? { failed_chunk_index: failedChunkIndex }
          : {}),
      }
    }
  }
  return source
}

export function createStandardOutlinePacket(seed: {
  outlineData?: Record<string, unknown>
  characters?: Array<Record<string, unknown>>
  rawOutlineText?: string
  source_material?: StandardOutlineSourceMaterial
  confirmed?: boolean
  status?: StandardOutlinePacketStatus
  current_stage?: string
} = {}): StandardOutlinePacket {
  const updatedAt = _now()
  const outline = seed.outlineData || {}
  const confirmed = seed.confirmed === true
  const makeField = confirmed ? _confirmed : _candidate
  const characters = Array.isArray(seed.characters) ? seed.characters : []
  const rangeOutlines = _array(outline.rangeOutlines || outline.range_outlines)
  const episodeOutlines = _array(outline.episodes || outline.episode_outlines)
  const totalEpisodes = Number(outline.episode_count || episodeOutlines.length || 0)

  return {
    schema_version: 'chat_outline_packet_v1',
    status: seed.status || (confirmed ? 'confirmed' : 'needs_user_confirmation'),
    current_stage: seed.current_stage || 'project_profile',
    source_material: _normalizeSourceMaterial(seed.source_material),
    project_profile: {
      audience_axis: makeField(_text(outline.audience_axis), updatedAt),
      genre_main: makeField(_text(outline.genre_main), updatedAt),
      format_type: makeField(_text(outline.format_type), updatedAt),
    },
    story_core: {
      logline: makeField(_text(outline.logline), updatedAt),
      conflict: makeField(_text(outline.conflict), updatedAt),
    },
    world_rules: {
      worldview: makeField(_text(outline.worldview), updatedAt),
      golden_finger: makeField(_text(outline.goldenFinger || outline.golden_finger), updatedAt),
      raw_outline_text: makeField(_text(seed.rawOutlineText), updatedAt),
    },
    characters: makeField(characters, updatedAt),
    relationship_timeline: makeField(_extractRelationships(characters), updatedAt),
    episode_count_plan: {
      // 用户未确认总集数，不得生成范围集纲。
      confirmed_total_episodes: confirmed ? makeField(totalEpisodes || '', updatedAt) : _normalizeField(undefined, '', updatedAt),
      suggested_total_episodes: confirmed ? _normalizeField(undefined, '', updatedAt) : makeField(totalEpisodes || '', updatedAt),
      episode_count_reason: makeField(_text(outline.episode_count_reason), updatedAt),
    },
    long_arc: {
      summary: makeField('', updatedAt),
    },
    range_outlines: makeField(rangeOutlines, updatedAt),
    episode_outlines: makeField(episodeOutlines, updatedAt),
    content_correctness_summary: _emptyContentCorrectnessSummary(),
    quality_gaps: [],
    conflict_issues: [],
    user_confirmed_fields: confirmed ? {
      project_profile: true,
      story_core: true,
      world_rules: true,
      characters: true,
      relationship_timeline: true,
      episode_count_plan: true,
      range_outlines: true,
      episode_outlines: true,
    } : {},
    generated_at: updatedAt,
    updated_at: updatedAt,
  }
}

function _extractRelationships(characters: Array<Record<string, unknown>>) {
  const rows: Array<Record<string, unknown>> = []
  characters.forEach((character) => {
    const source = _text(character.name)
    const relationships = Array.isArray(character.relationships) ? character.relationships : []
    relationships.forEach((rel) => {
      if (_isRecord(rel)) {
        rows.push({ source, ...rel })
      } else {
        const description = _text(rel)
        if (description) rows.push({ source, description })
      }
    })
  })
  return rows
}

export function normalizeStandardOutlinePacket(raw: unknown): StandardOutlinePacket {
  if (!_isRecord(raw) || raw.schema_version !== 'chat_outline_packet_v1') {
    return createStandardOutlinePacket()
  }
  const updatedAt = String(raw.updated_at || _now())
  const rawEpisodeCountPlan = _isRecord(raw.episode_count_plan) ? raw.episode_count_plan : {}
  const episodeCountPlan = _normalizeFieldRecord(rawEpisodeCountPlan, {
    confirmed_total_episodes: '',
    suggested_total_episodes: '',
    episode_count_reason: '',
  }, updatedAt)
  const legacyTotalField = rawEpisodeCountPlan.total_episodes
  if (!_fieldHasValue(episodeCountPlan.confirmed_total_episodes) && _isConfirmedField(legacyTotalField)) {
    episodeCountPlan.confirmed_total_episodes = _normalizeField(legacyTotalField, '', updatedAt)
  } else if (!_fieldHasValue(episodeCountPlan.suggested_total_episodes) && _fieldHasValue(legacyTotalField)) {
    episodeCountPlan.suggested_total_episodes = _normalizeField(legacyTotalField, '', updatedAt)
  }
  const sourceMaterial = _normalizeSourceMaterial(raw.source_material)
  return {
    schema_version: 'chat_outline_packet_v1',
    status: String(raw.status || 'needs_user_confirmation') as StandardOutlinePacketStatus,
    current_stage: String(raw.current_stage || 'project_profile'),
    source_material: sourceMaterial,
    project_profile: _normalizeFieldRecord(raw.project_profile, { audience_axis: '', genre_main: '', format_type: '' }, updatedAt),
    story_core: _normalizeFieldRecord(raw.story_core, { logline: '', conflict: '' }, updatedAt),
    world_rules: _normalizeFieldRecord(raw.world_rules, { worldview: '', golden_finger: '', raw_outline_text: '' }, updatedAt),
    characters: _normalizeField<Array<Record<string, unknown>>>(_isRecord(raw.characters) ? raw.characters : undefined, [], updatedAt),
    relationship_timeline: _normalizeField<Array<Record<string, unknown>>>(_isRecord(raw.relationship_timeline) ? raw.relationship_timeline : undefined, [], updatedAt),
    episode_count_plan: episodeCountPlan,
    long_arc: _normalizeFieldRecord(raw.long_arc, { summary: '' }, updatedAt),
    range_outlines: _normalizeField<Array<Record<string, unknown>>>(_isRecord(raw.range_outlines) ? raw.range_outlines : undefined, [], updatedAt),
    episode_outlines: _normalizeField<Array<Record<string, unknown>>>(_isRecord(raw.episode_outlines) ? raw.episode_outlines : undefined, [], updatedAt),
    content_correctness_summary: _normalizeContentCorrectnessSummary(raw.content_correctness_summary),
    quality_gaps: Array.isArray(raw.quality_gaps) ? raw.quality_gaps.map(_text).filter(Boolean) : [],
    conflict_issues: Array.isArray(raw.conflict_issues) ? raw.conflict_issues.map(_text).filter(Boolean) : [],
    user_confirmed_fields: _isRecord(raw.user_confirmed_fields) ? raw.user_confirmed_fields as Record<string, true> : {},
    generated_at: String(raw.generated_at || updatedAt),
    updated_at: updatedAt,
  }
}

export function mergeStandardOutlinePacket(base: unknown, patch: Partial<StandardOutlinePacket>): StandardOutlinePacket {
  const normalized = normalizeStandardOutlinePacket(base)
  const updatedAt = _now()
  const patchedSourceMaterial = patch.source_material === undefined
    ? undefined
    : _normalizeSourceMaterial(patch.source_material)
  const shouldApplyPatchedSourceMaterial = Boolean(
    patchedSourceMaterial
    && patchedSourceMaterial.kind !== 'none'
    && patchedSourceMaterial.raw_text !== '',
  )
  return {
    ...normalized,
    ...patch,
    project_profile: { ...normalized.project_profile, ...(patch.project_profile || {}) },
    story_core: { ...normalized.story_core, ...(patch.story_core || {}) },
    world_rules: { ...normalized.world_rules, ...(patch.world_rules || {}) },
    episode_count_plan: { ...normalized.episode_count_plan, ...(patch.episode_count_plan || {}) },
    long_arc: { ...normalized.long_arc, ...(patch.long_arc || {}) },
    source_material: shouldApplyPatchedSourceMaterial
      ? patchedSourceMaterial as StandardOutlineSourceMaterial
      : normalized.source_material,
    user_confirmed_fields: { ...normalized.user_confirmed_fields, ...(patch.user_confirmed_fields || {}) },
    updated_at: updatedAt,
  }
}

export function nextStandardOutlineStage(stage: string): string {
  const index = STANDARD_OUTLINE_STAGE_ORDER.findIndex(item => item === stage)
  if (index < 0) return STANDARD_OUTLINE_STAGE_ORDER[0]
  return STANDARD_OUTLINE_STAGE_ORDER[index + 1] || ''
}

function _fieldHasValue(field: unknown) {
  if (!_isRecord(field) || !('value' in field)) return false
  const value = field.value
  if (Array.isArray(value)) return value.length > 0
  return _text(value) !== ''
}

function _confirmCandidateField<T>(field: StandardOutlineField<T>): StandardOutlineField<T> {
  if (!_fieldHasValue(field)) {
    return {
      ...field,
      status: 'missing',
      source: field.source || 'system_inferred',
      updated_at: _now(),
    }
  }
  return {
    ...field,
    status: 'confirmed',
    source: 'user_confirmed',
    updated_at: _now(),
  }
}

function _confirmFieldRecord(record: Record<string, StandardOutlineField>) {
  return Object.fromEntries(
    Object.entries(record).map(([key, field]) => [key, _confirmCandidateField(field)]),
  )
}

export function standardOutlineStageHasCandidate(packet: unknown, stage: string): boolean {
  const normalized = normalizeStandardOutlinePacket(packet)
  if (stage === 'characters') return _fieldHasValue(normalized.characters)
  if (stage === 'relationship_timeline') return _fieldHasValue(normalized.relationship_timeline)
  if (stage === 'range_outlines') return _fieldHasValue(normalized.range_outlines)
  if (stage === 'episode_outlines') return _fieldHasValue(normalized.episode_outlines)
  const record = (normalized as unknown as Record<string, unknown>)[stage]
  if (!_isRecord(record)) return false
  return Object.values(record).some(_fieldHasValue)
}

export function confirmStandardOutlinePacketStage(packet: unknown, stage: string): StandardOutlinePacket {
  const normalized = normalizeStandardOutlinePacket(packet)
  const updatedAt = _now()
  const confirmedFields = { ...normalized.user_confirmed_fields }
  const hasCandidate = standardOutlineStageHasCandidate(normalized, stage)
  if (hasCandidate) confirmedFields[stage] = true

  const patch: Partial<StandardOutlinePacket> = {
    user_confirmed_fields: confirmedFields,
    current_stage: hasCandidate ? nextStandardOutlineStage(stage) : stage,
    status: hasCandidate && !nextStandardOutlineStage(stage) ? 'confirmed' : 'needs_user_confirmation',
    updated_at: updatedAt,
  }

  if (stage === 'project_profile') patch.project_profile = _confirmFieldRecord(normalized.project_profile)
  if (stage === 'story_core') patch.story_core = _confirmFieldRecord(normalized.story_core)
  if (stage === 'world_rules') patch.world_rules = _confirmFieldRecord(normalized.world_rules)
  if (stage === 'characters') patch.characters = _confirmCandidateField(normalized.characters)
  if (stage === 'relationship_timeline') patch.relationship_timeline = _confirmCandidateField(normalized.relationship_timeline)
  if (stage === 'episode_count_plan') {
    const confirmedRecord = _confirmFieldRecord(normalized.episode_count_plan)
    const suggestedTotal = normalized.episode_count_plan.suggested_total_episodes
    if (
      !_fieldHasValue(confirmedRecord.confirmed_total_episodes)
      && suggestedTotal
      && _fieldHasValue(suggestedTotal)
    ) {
      confirmedRecord.confirmed_total_episodes = _confirmCandidateField(suggestedTotal)
    }
    patch.episode_count_plan = confirmedRecord
  }
  if (stage === 'long_arc') patch.long_arc = _confirmFieldRecord(normalized.long_arc)
  if (stage === 'range_outlines') patch.range_outlines = _confirmCandidateField(normalized.range_outlines)
  if (stage === 'episode_outlines') patch.episode_outlines = _confirmCandidateField(normalized.episode_outlines)

  return mergeStandardOutlinePacket(normalized, patch)
}

export function resolveConfirmedEpisodeCount(packet: unknown, fallback = 0): number {
  const normalized = normalizeStandardOutlinePacket(packet)
  const totalField = normalized.episode_count_plan.confirmed_total_episodes
  if (!_isConfirmedField(totalField)) return 0
  const count = Number(_fieldValue(totalField, 0))
  return Number.isFinite(count) && count > 0 ? Math.round(count) : Math.max(0, Math.round(fallback))
}

export function diagnoseStandardOutlinePacketGate(packet: unknown, target: StandardOutlineGateTarget = 'script_generation'): string[] {
  const normalized = normalizeStandardOutlinePacket(packet)
  const issues: string[] = []
  const confirmedEpisodeCount = resolveConfirmedEpisodeCount(normalized)
  const characters = _fieldArray(normalized.characters)
  const episodes = _fieldArray(normalized.episode_outlines)

  if (!confirmedEpisodeCount) issues.push('请先确认总集数')
  if (!characters.length || !_isConfirmedField(normalized.characters)) issues.push('请先确认角色库')
  if (!_isExplicitlyConfirmedField(normalized.relationship_timeline)) issues.push('请先确认角色关系')
  if (target === 'script_generation' && (!episodes.length || !_isConfirmedField(normalized.episode_outlines))) {
    issues.push('请先确认分集集纲')
  }

  return Array.from(new Set(issues))
}

export function projectStandardOutlinePacketToOutline(packet: unknown): StandardOutlineProjection {
  const normalized = normalizeStandardOutlinePacket(packet)
  const outlineData: Record<string, unknown> = {
    audience_axis: _fieldText(normalized.project_profile.audience_axis),
    genre_main: _fieldText(normalized.project_profile.genre_main),
    format_type: _fieldText(normalized.project_profile.format_type),
    logline: _fieldText(normalized.story_core.logline),
    worldview: _fieldText(normalized.world_rules.worldview),
    goldenFinger: _fieldText(normalized.world_rules.golden_finger),
    conflict: _fieldText(normalized.story_core.conflict),
    episode_count: resolveConfirmedEpisodeCount(normalized) || undefined,
    rangeOutlines: _fieldArray(normalized.range_outlines),
    episodes: _fieldArray(normalized.episode_outlines),
  }
  const outlineCharacters = _fieldArray(normalized.characters)
  const rawOutlineText = _buildReadableOutline(normalized)
  return { outlineData, outlineCharacters, rawOutlineText }
}

function _formatRelationshipOutlineLine(relationship: Record<string, unknown>) {
  const source = _text(
    relationship.source
    || relationship.sourceName
    || relationship.source_name,
  )
  const target = _text(
    relationship.targetName
    || relationship.target_name
    || relationship.target
    || relationship.to,
  )
  const earlyType = _text(
    relationship.earlyType
    || relationship.early_type
    || relationship.early
    || relationship.type,
  )
  const lateType = _text(
    relationship.lateType
    || relationship.late_type
    || relationship.late
    || relationship.afterType
    || relationship.after_type,
  )
  const transitionEpisode = _text(
    relationship.transitionEpisode
    || relationship.transition_episode
    || relationship.turningEpisode
    || relationship.turning_episode,
  )
  const finalBoundary = _text(
    relationship.finalBoundary
    || relationship.final_boundary
    || relationship.boundary,
  )
  const description = _text(
    relationship.description
    || relationship.desc
    || relationship.detail
    || relationship.summary,
  )
  return [
    source && `人物A：${source}`,
    target && `人物B：${target}`,
    earlyType && `早期关系：${earlyType}`,
    lateType && `后期关系：${lateType}`,
    transitionEpisode && `转折集：第${transitionEpisode}集`,
    finalBoundary && `禁止提前揭露：${finalBoundary}`,
    description && `说明：${description}`,
  ].filter(Boolean).join('；')
}

function _buildReadableOutline(packet: StandardOutlinePacket) {
  const lines = [
    _fieldText(packet.project_profile.genre_main) || _fieldText(packet.project_profile.format_type)
      ? `创作方向：${[_fieldText(packet.project_profile.audience_axis), _fieldText(packet.project_profile.genre_main), _fieldText(packet.project_profile.format_type)].filter(Boolean).join(' / ')}`
      : '',
    resolveConfirmedEpisodeCount(packet) ? `用户确认总集数：${resolveConfirmedEpisodeCount(packet)}集` : '',
    _fieldText(packet.story_core.logline) ? `一句话梗概：${_fieldText(packet.story_core.logline)}` : '',
    _fieldText(packet.world_rules.worldview) ? `世界观：${_fieldText(packet.world_rules.worldview)}` : '',
    _fieldText(packet.world_rules.golden_finger) ? `金手指/特殊设定：${_fieldText(packet.world_rules.golden_finger)}` : '',
    _fieldText(packet.story_core.conflict) ? `核心冲突：${_fieldText(packet.story_core.conflict)}` : '',
    _fieldArray(packet.characters).length
      ? `角色库：\n${_fieldArray(packet.characters).map(char => `${_text(char.name)}：${_text(char.info || char.bio || char.identity)}`).join('\n')}`
      : '',
    _fieldArray(packet.relationship_timeline).length
      ? `角色关系：\n${_fieldArray(packet.relationship_timeline).map(_formatRelationshipOutlineLine).join('\n')}`
      : '',
    _fieldArray(packet.range_outlines).length
      ? `范围集纲：\n${_fieldArray(packet.range_outlines).map(item => `第${_text(item.start)}-${_text(item.end)}集：${_text(item.title)} ${_text(item.summary)}`).join('\n')}`
      : '',
    _fieldArray(packet.episode_outlines).length
      ? `分集集纲：\n${_fieldArray(packet.episode_outlines).map(item => `第${_text(item.ep)}集：${_text(item.title)} ${_text(item.summary || item.episode_outline)}`).join('\n')}`
      : '',
  ].filter(Boolean)
  return lines.join('\n\n')
}
