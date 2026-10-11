import { computed, ref } from 'vue'
import { normalizeEpisodeCountValue, type EpisodeCountStatus } from '@/features/workspace/utils/episodeCount'

export type SceneHeaderStyle = 'bracket' | 'plain'

export type OutlineCharacter = {
  id: string
  name: string
  role: 'protagonist' | 'antagonist' | 'supporting' | 'minor'
  info: string
}

export type GenerationProviderOption = {
  id: string
  name: string
  models: Array<{ value: string; name: string }>
}

export function deriveWordCountRangeBySeconds(rawSeconds: number) {
  const seconds = Math.max(30, Math.min(600, Math.round(Number(rawSeconds) || 90)))
  const target = Math.max(300, Math.round((seconds / 90) * 1200))
  const min = Math.max(100, Math.round((seconds / 90) * 1000))
  const max = Math.max(min, Math.round((seconds / 90) * 1550))
  return {
    min,
    max,
    target,
    text: `${min}-${max}`,
  }
}

export function normalizeProjectRules(raw?: Partial<{
  total_episodes: number | null
  confirmed_total_episodes: number | null
  suggested_total_episodes: number | null
  episode_count_status: EpisodeCountStatus
  episode_count_confirmation_source: string
  episode_count_confirmed_at: string
  episode_seconds: number
  word_count_per_episode: string
  scene_header_style: string
  subgenre_track: string
  sample_track: string
  generation_provider: string
  generation_model: string
  advanced_generation_mode: boolean
}>) {
  const confirmedEpisodes = normalizeEpisodeCountValue(raw?.confirmed_total_episodes)
  const suggestedEpisodes = normalizeEpisodeCountValue(raw?.suggested_total_episodes)
  const legacyEpisodes = normalizeEpisodeCountValue(raw?.total_episodes)
  const rawStatus = String(raw?.episode_count_status || '').trim() as EpisodeCountStatus
  const episodeCountStatus: EpisodeCountStatus = confirmedEpisodes
    ? 'confirmed'
    : rawStatus === 'legacy_needs_confirmation' || (!rawStatus && legacyEpisodes)
      ? 'legacy_needs_confirmation'
      : 'unconfirmed'
  const totalEpisodes = confirmedEpisodes || (episodeCountStatus === 'legacy_needs_confirmation' ? legacyEpisodes : 0)
  const episodeSeconds = Math.max(30, Math.min(600, Math.round(Number(raw?.episode_seconds) || 90)))
  const derivedRange = deriveWordCountRangeBySeconds(episodeSeconds)
  const rawText = String(raw?.word_count_per_episode || '').trim()
  const isLegacyNinetySecondRange = episodeSeconds === 90 && rawText === '1080-1320'
  const text = (!rawText || isLegacyNinetySecondRange) ? derivedRange.text : rawText
  const sceneHeaderStyle: SceneHeaderStyle = String(raw?.scene_header_style || '').trim().toLowerCase() === 'plain' ? 'plain' : 'bracket'
  return {
    total_episodes: totalEpisodes,
    confirmed_total_episodes: confirmedEpisodes || null,
    suggested_total_episodes: suggestedEpisodes || (episodeCountStatus === 'legacy_needs_confirmation' ? legacyEpisodes : null),
    episode_count_status: episodeCountStatus,
    episode_count_confirmation_source: String(raw?.episode_count_confirmation_source || '').trim(),
    episode_count_confirmed_at: String(raw?.episode_count_confirmed_at || '').trim(),
    episode_seconds: episodeSeconds,
    word_count_per_episode: text,
    scene_header_style: sceneHeaderStyle,
    subgenre_track: String(raw?.subgenre_track || '').trim(),
    sample_track: String(raw?.sample_track || '').trim(),
    generation_provider: String(raw?.generation_provider || '').trim(),
    generation_model: String(raw?.generation_model || '').trim(),
    advanced_generation_mode: Boolean(raw?.advanced_generation_mode),
  }
}

export function useOutlineWorkflow() {
  const outlineData = ref({
    logline: '',
    worldview: '',
    goldenFinger: '',
    conflict: '',
    episodes: [] as Array<{
      ep: number
      title: string
      hook: string
      summary: string
      conflict?: string
      turning?: string
      existing_script?: string
    }>,
    audience_axis: '' as '男频' | '女频' | '混合' | '',
    genre_main: '',
    format_type: '真人短剧' as '真人短剧' | '漫剧' | 'AI真人',
  })
  const projectRules = ref(normalizeProjectRules())
  const generationProviders = ref<GenerationProviderOption[]>([])
  const fallbackGenerationConfig = ref({ provider: '', model: '' })
  const projectRulesSaving = ref(false)
  const lastProjectRulesSignature = ref('')
  const outlineCharacters = ref<OutlineCharacter[]>([])
  const isAnalyzingOutline = ref(false)
  const outlineImportText = ref('')
  const showImportArea = ref(false)
  const rawOutlineText = ref('')
  const isGeneratingEpisodes = ref(false)
  const sectionSuggestions = ref<Record<string, string>>({})
  const sectionLoading = ref<Record<string, boolean>>({})

  const availableGenerationModels = computed(() => {
    return generationProviders.value.find(item => item.id === projectRules.value.generation_provider)?.models || []
  })

  function applyGenerationDefaults() {
    if (!projectRules.value.generation_provider && fallbackGenerationConfig.value.provider) {
      projectRules.value.generation_provider = fallbackGenerationConfig.value.provider
    }
    if (!projectRules.value.generation_provider && generationProviders.value.length > 0) {
      projectRules.value.generation_provider = generationProviders.value[0]?.id || ''
    }
    const providerModels = generationProviders.value.find(item => item.id === projectRules.value.generation_provider)?.models || []
    if (!projectRules.value.generation_model) {
      projectRules.value.generation_model = (
        providerModels.find(item => item.value === fallbackGenerationConfig.value.model)?.value
        || providerModels[0]?.value
        || fallbackGenerationConfig.value.model
        || ''
      )
      return
    }
    if (providerModels.length > 0 && !providerModels.some(item => item.value === projectRules.value.generation_model)) {
      projectRules.value.generation_model = providerModels[0]?.value || ''
    }
  }

  return {
    outlineData,
    projectRules,
    generationProviders,
    fallbackGenerationConfig,
    projectRulesSaving,
    lastProjectRulesSignature,
    outlineCharacters,
    isAnalyzingOutline,
    outlineImportText,
    showImportArea,
    rawOutlineText,
    isGeneratingEpisodes,
    sectionSuggestions,
    sectionLoading,
    availableGenerationModels,
    applyGenerationDefaults,
  }
}
