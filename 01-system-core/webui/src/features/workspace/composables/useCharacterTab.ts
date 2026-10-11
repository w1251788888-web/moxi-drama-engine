// 角色设计 Tab 状态：角色列表 + 关系 + 自动持久化（800ms debounce）。
//
// 从 ProjectWorkspaceView 抽出。关键点：
// - 同一个 800ms debounce 同时管 localStorage 和后端保存（避免每次 deep 触发就阻塞主线程）
// - watch 加 enabled 守卫：项目首次加载完成前不写库（防止覆盖空白数据）

import { onUnmounted, ref, watch, type ComputedRef, type Ref } from 'vue'
import { projectsV2Api } from '@/api/client'
import { saveWorkspaceStorage } from '@/features/workspace/utils/workspaceStorage'

export const ROLE_COLORS = {
  protagonist: '#3b82f6',
  antagonist: '#ef4444',
  supporting: '#10b981',
  minor: '#9ca3af',
} as const
export type CharacterRole = keyof typeof ROLE_COLORS

export function roleColorFor(role: string): string {
  return ROLE_COLORS[role as CharacterRole] || '#3b82f6'
}

interface UseCharacterTabOptions {
  /** 当前项目 id */
  projectId: ComputedRef<string>
  /** 项目数据是否已加载完。watch 在加载前不会写库。 */
  isReady: ComputedRef<boolean>
}

export function useCharacterTab(opts: UseCharacterTabOptions) {
  const characters: Ref<any[]> = ref([])
  const selectedCharacterId = ref<string | null>(null)
  const showCharacterGraph = ref(true)

  function addCharacter(char: any, notify?: (msg: string) => void) {
    const created = { id: String(Date.now()), relationships: [], ...char }
    characters.value.push(created)
    selectedCharacterId.value = created.id
    notify?.(`角色 ${char.name} 已添加`)
  }

  function removeCharacter(id: string) {
    characters.value = characters.value.filter(c => c.id !== id)
    characters.value.forEach(c => {
      if (c.relationships) c.relationships = c.relationships.filter((r: any) => r.targetId !== id)
    })
    if (selectedCharacterId.value === id) {
      selectedCharacterId.value = characters.value[0]?.id || null
    }
  }

  function updateCharacter(id: string, updates: any) {
    const c = characters.value.find(ch => ch.id === id)
    if (c) Object.assign(c, updates)
  }

  function addRelationship(sourceId: string, rel: any) {
    const c = characters.value.find(ch => ch.id === sourceId)
    if (c) { if (!c.relationships) c.relationships = []; c.relationships.push(rel) }
  }

  // 持久化：localStorage + 后端共用同一个 debounce
  let _characterSyncTimer: ReturnType<typeof setTimeout> | null = null
  watch(characters, (value) => {
    if (_characterSyncTimer) clearTimeout(_characterSyncTimer)
    _characterSyncTimer = setTimeout(async () => {
      try {
        saveWorkspaceStorage('characters', opts.projectId.value, JSON.stringify(value))
      } catch {}
      if (!opts.isReady.value) return
      try {
        await projectsV2Api.saveCharacters(opts.projectId.value, value as Array<Record<string, any>>)
      } catch {
        // 后端保存失败时本地副本仍在，不打断编辑
      }
    }, 800)
  }, { deep: true })

  // 组件卸载时清掉未结算的 debounce timer，避免离开页面后仍触发保存
  onUnmounted(() => {
    if (_characterSyncTimer) { clearTimeout(_characterSyncTimer); _characterSyncTimer = null }
  })

  return {
    characters,
    selectedCharacterId,
    showCharacterGraph,
    roleColors: ROLE_COLORS,
    roleColorFor,
    addCharacter,
    removeCharacter,
    updateCharacter,
    addRelationship,
  }
}
