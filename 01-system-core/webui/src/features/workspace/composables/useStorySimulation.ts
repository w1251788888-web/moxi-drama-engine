export function hasSeriesSimulationContracts(packet?: any): boolean {
  return Array.isArray(packet?.episode_contracts) && packet.episode_contracts.length > 0
}

export function storySimulationContractCount(packet?: any): number {
  return Array.isArray(packet?.episode_contracts) ? packet.episode_contracts.length : 0
}

const GENERIC_CONTRACT_TEXT = new Set([
  '承接前序已经落地的结果，不重启同一场开局。',
  '本集必须把压力写到现实现场，不只停在人物心里或口头争执。',
  '本集必须有当场代价或局势变化，不能只提出问题。',
  '反派不能只放狠话，必须给出具体动作或利益威胁。',
])

const EXECUTABLE_MUST_HAPPEN_MARKERS = [
  '兑现本集摘要',
  '推进本集核心冲突',
  '主场景必须落地',
  '关系变化必须落地',
  '信息揭露必须落地',
]

function normalizeEpisodeNo(item: any): number {
  const value = Number(item?.episode_no || item?.episodeNumber || item?.episode || item?.ep || 0)
  return Number.isFinite(value) && value > 0 ? Math.round(value) : 0
}

function hasExecutableText(value: unknown, minLength = 12): boolean {
  const text = String(value || '').replace(/\s+/g, ' ').trim()
  return text.length >= minLength && !GENERIC_CONTRACT_TEXT.has(text)
}

function hasExecutableSeriesSimulationContract(item: any, episodeNo: number): boolean {
  if (!item || typeof item !== 'object' || Array.isArray(item)) return false
  const mustHappen = Array.isArray(item.must_happen)
    ? item.must_happen.map((value: unknown) => String(value || '').trim()).filter(Boolean)
    : []
  if (!mustHappen.length) return false
  if (!EXECUTABLE_MUST_HAPPEN_MARKERS.every(marker => mustHappen.some((text: string) => text.includes(marker)))) {
    return false
  }
  if (episodeNo > 1 && !hasExecutableText(item.start_state || item.incoming_hook, 20)) {
    return false
  }
  return hasExecutableText(item.ending_state || item.outgoing_hook || item.ending_hook, 20)
}

export function hasExecutableSeriesSimulationContracts(packet?: any, expectedEpisodes = 0): boolean {
  const contracts = Array.isArray(packet?.episode_contracts) ? packet.episode_contracts : []
  if (!contracts.length) return false
  const expected = Math.max(0, Math.round(Number(expectedEpisodes) || 0))
  const byEpisode = new Map<number, any>()
  contracts.forEach((item: any) => {
    const episodeNo = normalizeEpisodeNo(item)
    if (episodeNo > 0 && !byEpisode.has(episodeNo)) byEpisode.set(episodeNo, item)
  })

  if (expected > 0) {
    for (let episodeNo = 1; episodeNo <= expected; episodeNo += 1) {
      if (!hasExecutableSeriesSimulationContract(byEpisode.get(episodeNo), episodeNo)) return false
    }
    return true
  }

  return Array.from(byEpisode.entries()).every(([episodeNo, item]) =>
    hasExecutableSeriesSimulationContract(item, episodeNo),
  )
}
