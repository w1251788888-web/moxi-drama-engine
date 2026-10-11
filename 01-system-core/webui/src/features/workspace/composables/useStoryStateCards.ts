// 故事状态卡 CRUD composable。
//
// 从 ProjectWorkspaceView 抽出。原因：
// - 五种卡片（关系/信息差/权力位置/未完成承诺/禁改事实）的 add / upsert /
//   remove / toggleCharacter 一坨函数，主 View 留着只是噪音
// - 抽出后单独单测：CRUD 行为不依赖 Vue 组件树，纯函数 + ref
//
// 调用方需要：
// - storyStateCards: 卡片仓库 ref（已经由 useStoryStateAutosave 写库）
// - sceneCharacterIds: 当前场出场角色 id 集合（用于新卡片默认 related_character_ids）

import type { Ref } from 'vue'
import type { StoryStateCard, StoryStateCardKind, StoryStateCardStore } from '@/features/workspace/utils/workflowState'

const KIND_TO_KEY: Record<StoryStateCardKind, keyof StoryStateCardStore> = {
  relationship: 'relationship_cards',
  info: 'info_cards',
  power: 'power_cards',
  promise: 'promise_cards',
  locked_fact: 'locked_fact_cards',
}

const KIND_LABEL: Record<StoryStateCardKind, string> = {
  relationship: '关系状态',
  info: '信息差',
  power: '权力位置',
  promise: '未完成承诺',
  locked_fact: '禁改事实',
}

interface UseStoryStateCardsOptions {
  storyStateCards: Ref<StoryStateCardStore>
  /** 当前场出场角色 id（用于新卡片默认绑定的角色，最多取前 3 个） */
  sceneCharacterIds: Ref<Set<string> | string[]>
  /** 已被用户忽略的卡片建议 key 列表（外部 ref，便于其他 watcher 也读它） */
  dismissedSuggestionKeys: Ref<string[]>
}

export function useStoryStateCards(opts: UseStoryStateCardsOptions) {
  const dismissedSuggestionKeys = opts.dismissedSuggestionKeys

  function _defaultRelatedIds(): string[] {
    const raw = opts.sceneCharacterIds.value
    const arr = raw instanceof Set ? Array.from(raw) : (Array.isArray(raw) ? raw : [])
    return arr.slice(0, 3).map((v) => String(v))
  }

  function makeStateCard(kind: StoryStateCardKind, preset?: Partial<StoryStateCard>): StoryStateCard {
    return {
      id: `state-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
      title: preset?.title || KIND_LABEL[kind],
      summary: preset?.summary || '',
      state: preset?.state || (kind === 'locked_fact' ? 'locked' : 'active'),
      related_character_ids: Array.isArray(preset?.related_character_ids)
        ? preset!.related_character_ids
        : _defaultRelatedIds(),
    }
  }

  function addStoryStateCard(kind: StoryStateCardKind, preset?: Partial<StoryStateCard>) {
    const key = KIND_TO_KEY[kind]
    opts.storyStateCards.value[key] = [...opts.storyStateCards.value[key], makeStateCard(kind, preset)]
  }

  function upsertStoryStateCard(kind: StoryStateCardKind, preset?: Partial<StoryStateCard>): boolean {
    const key = KIND_TO_KEY[kind]
    const nextTitle = String(preset?.title || '').trim()
    const nextRelatedIds = Array.isArray(preset?.related_character_ids)
      ? Array.from(new Set(preset!.related_character_ids.map((item) => String(item))))
      : []
    const list = opts.storyStateCards.value[key]
    const existing = list.find((card) => {
      if (nextTitle && card.title === nextTitle) return true
      if (nextRelatedIds.length === 0) return false
      return card.related_character_ids.length === nextRelatedIds.length
        && card.related_character_ids.every((item) => nextRelatedIds.includes(String(item)))
    })

    if (!existing) {
      addStoryStateCard(kind, preset)
      return true
    }

    existing.title = nextTitle || existing.title
    existing.summary = String(preset?.summary || '').trim() || existing.summary
    existing.state = String(preset?.state || '').trim() || existing.state
    if (nextRelatedIds.length > 0) {
      existing.related_character_ids = nextRelatedIds
    }
    return true
  }

  function removeStoryStateCard(kind: StoryStateCardKind, id: string) {
    const key = KIND_TO_KEY[kind]
    opts.storyStateCards.value[key] = opts.storyStateCards.value[key].filter((item) => item.id !== id)
  }

  function toggleStateCardCharacter(card: StoryStateCard, characterId: string) {
    if (card.related_character_ids.includes(characterId)) {
      card.related_character_ids = card.related_character_ids.filter((id) => id !== characterId)
      return
    }
    card.related_character_ids = [...card.related_character_ids, characterId]
  }

  function dismissSuggestion(key: string) {
    if (!key) return
    if (dismissedSuggestionKeys.value.includes(key)) return
    dismissedSuggestionKeys.value = [...dismissedSuggestionKeys.value, key]
  }

  function resetDismissedSuggestions() {
    dismissedSuggestionKeys.value = []
  }

  return {
    dismissedSuggestionKeys,
    makeStateCard,
    addStoryStateCard,
    upsertStoryStateCard,
    removeStoryStateCard,
    toggleStateCardCharacter,
    dismissSuggestion,
    resetDismissedSuggestions,
  }
}
