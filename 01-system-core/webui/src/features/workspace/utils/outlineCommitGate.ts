type EpisodeCountResolutionInput = {
  currentPacket?: unknown
  workflowOutlineState?: Record<string, any> | null
  projectRules?: Record<string, any> | null
  projectConfig?: Record<string, any> | null
  outlineEpisodeCount?: number
}

function _normalizedCount(value: unknown) {
  const count = Math.round(Number(value) || 0)
  return Number.isFinite(count) && count > 0 ? Math.max(1, Math.min(200, count)) : 0
}

function _isRecord(value: unknown): value is Record<string, any> {
  return Boolean(value && typeof value === 'object' && !Array.isArray(value))
}

function _fieldValue(field: unknown) {
  return _isRecord(field) && 'value' in field ? field.value : undefined
}

function _fieldText(value: unknown): string {
  if (value === null || value === undefined) return ''
  if (typeof value === 'string') return value.trim()
  if (typeof value === 'number' || typeof value === 'boolean') return String(value)
  if (Array.isArray(value)) return value.map(_fieldText).filter(Boolean).join('；')
  if (_isRecord(value)) return _fieldText(value.value ?? value.summary ?? value.text ?? value.title ?? value.description)
  return ''
}

function _resolveConfirmedEpisodeCount(packet: unknown) {
  if (!_isRecord(packet)) return 0
  const totalField = _isRecord(packet.episode_count_plan)
    ? packet.episode_count_plan.confirmed_total_episodes
    : undefined
  if (!_isRecord(totalField) || totalField.status !== 'confirmed') return 0
  if (!_fieldText(_fieldValue(totalField))) return 0
  return _normalizedCount(_fieldValue(totalField))
}

export function resolveStrictConfirmedTotalEpisodes(input: EpisodeCountResolutionInput) {
  const currentPacketCount = _resolveConfirmedEpisodeCount(input.currentPacket)
  if (currentPacketCount) return _normalizedCount(currentPacketCount)

  const statePacketCount = _resolveConfirmedEpisodeCount(input.workflowOutlineState?.standard_outline_packet)
  if (statePacketCount) return _normalizedCount(statePacketCount)

  const stateConfirmed = _normalizedCount(input.workflowOutlineState?.confirmed_total_episodes)
  if (stateConfirmed) return stateConfirmed

  const rulesConfirmed = _normalizedCount(input.projectRules?.confirmed_total_episodes)
  if (rulesConfirmed) return rulesConfirmed

  const configConfirmed = _normalizedCount(input.projectConfig?.confirmed_total_episodes)
  if (configConfirmed) return configConfirmed

  return 0
}

export function resolveCommitConfirmedTotalEpisodes(input: EpisodeCountResolutionInput) {
  const strictConfirmed = resolveStrictConfirmedTotalEpisodes(input)
  if (strictConfirmed) return strictConfirmed

  const outlineEpisodeCount = _normalizedCount(input.outlineEpisodeCount)
  if (!outlineEpisodeCount) return 0

  const rulesTotal = _normalizedCount(input.projectRules?.total_episodes)
  const configTotal = _normalizedCount(input.projectConfig?.total_episodes)
  const declaredTotal = rulesTotal || configTotal

  if (declaredTotal && declaredTotal !== outlineEpisodeCount) return 0
  return outlineEpisodeCount
}
