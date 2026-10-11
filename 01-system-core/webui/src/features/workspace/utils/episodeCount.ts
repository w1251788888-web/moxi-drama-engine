const CHINESE_DIGITS: Record<string, number> = {
  零: 0,
  一: 1,
  二: 2,
  两: 2,
  三: 3,
  四: 4,
  五: 5,
  六: 6,
  七: 7,
  八: 8,
  九: 9,
}

export type EpisodeCountStatus = 'unconfirmed' | 'confirmed' | 'legacy_needs_confirmation'

export function normalizeEpisodeCountValue(value: unknown) {
  const count = Math.round(Number(value) || 0)
  return Number.isFinite(count) && count > 0 ? Math.max(1, Math.min(200, count)) : 0
}

function chineseNumberToInt(text: string) {
  const value = String(text || '').trim()
  if (!value) return 0
  if (/^\d+$/.test(value)) return Number(value)
  if (value === '十') return 10
  const tenIndex = value.indexOf('十')
  if (tenIndex >= 0) {
    const left = value.slice(0, tenIndex)
    const right = value.slice(tenIndex + 1)
    const tens = left ? CHINESE_DIGITS[left] || 0 : 1
    const ones = right ? CHINESE_DIGITS[right] || 0 : 0
    return tens * 10 + ones
  }
  return CHINESE_DIGITS[value] || 0
}

export function extractExplicitEpisodeCount(input: string) {
  const text = String(input || '').replace(/\s+/g, '')
  if (!text) return 0
  const numericRange = text.match(/(?:第)?\d{1,3}(?:到|至|-|~)(\d{1,3})集/)
  if (numericRange?.[1]) return normalizeEpisodeCountValue(numericRange[1])
  const numeric = text.match(/(?:总共|共|做|写|生成|补全|想要|预计|目标|全剧|一共)?(\d{1,3})集/)
  if (numeric?.[1]) return normalizeEpisodeCountValue(numeric[1])
  const chineseRange = text.match(/[一二两三四五六七八九十]{1,4}(?:到|至|-|~)([一二两三四五六七八九十]{1,4})集/)
  if (chineseRange?.[1]) return normalizeEpisodeCountValue(chineseNumberToInt(chineseRange[1]))
  const chinese = text.match(/(?:总共|共|做|写|生成|补全|想要|预计|目标|全剧|一共)?([一二两三四五六七八九十]{1,4})集/)
  if (chinese?.[1]) return normalizeEpisodeCountValue(chineseNumberToInt(chinese[1]))
  return 0
}
