import type { AdvancedGenerationProfile } from '@/api/client'

export function statusLabel(profile: AdvancedGenerationProfile) {
  return profile.status === 'active' ? '已接入' : '准备中'
}

export function footerText(profile: AdvancedGenerationProfile) {
  return profile.status === 'active'
    ? '已接入项目创建和通用生成提示。'
    : '准备中，仅展示未来接入框架。'
}

export function aliasesText(profile: AdvancedGenerationProfile) {
  return profile.project_type_aliases.join(' / ')
}
