// 全局项目列表 store。
//
// 目的：
// 1. 离开页面再回来时，列表不再因组件重挂而消失。
// 2. 工作台等其他页面要"项目元数据"时直接读 store，不重复请求。
// 3. 后端 API 改动只需要改这个 store 一个地方，组件不耦合接口形态。
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { projectsV2Api, type ProjectV2 } from '@/api/client'
import { formatUserFacingErrorMessage } from '@/api/http'

const REFRESH_AFTER_MS = 30_000  // 30s 内的缓存视为新鲜
const PROJECT_LIST_TIMEOUT_MS = 8_000

function simpleHash(text: string): string {
  let hash = 2166136261
  for (let i = 0; i < text.length; i += 1) {
    hash ^= text.charCodeAt(i)
    hash = Math.imul(hash, 16777619)
  }
  return (hash >>> 0).toString(16)
}

function safeParseUserSession(raw: string | null): Record<string, unknown> | null {
  if (!raw) return null
  try {
    const parsed = JSON.parse(raw)
    return parsed && typeof parsed === 'object' ? parsed as Record<string, unknown> : null
  } catch {
    return null
  }
}

function currentProjectListScope(): string {
  if (typeof window === 'undefined') return 'server'
  const session = safeParseUserSession(window.localStorage.getItem('user_access_session'))
  const keyId = typeof session?.key_id === 'string' ? session.key_id.trim() : ''
  const sessionToken = typeof session?.session_token === 'string' ? session.session_token.trim() : ''
  if (keyId) return `user:${keyId}`
  if (sessionToken) return `user-session:${simpleHash(sessionToken).slice(0, 12)}`
  const adminToken = window.localStorage.getItem('admin_token') || ''
  if (adminToken) return `admin:${simpleHash(adminToken).slice(0, 12)}`
  return 'anonymous'
}

export const useProjectsStore = defineStore('projects', () => {
  const projects = ref<ProjectV2[]>([])
  const isLoading = ref(false)
  const lastError = ref('')
  const lastFetchedAt = ref(0)
  let activeListController: AbortController | null = null
  let activeAuthScope = currentProjectListScope()

  const isFresh = computed(() => Date.now() - lastFetchedAt.value < REFRESH_AFTER_MS)
  const hasData = computed(() => projects.value.length > 0)

  function resetForAuthScope(scope = currentProjectListScope()): void {
    if (scope === activeAuthScope) return
    activeListController?.abort()
    activeListController = null
    projects.value = []
    lastError.value = ''
    lastFetchedAt.value = 0
    isLoading.value = false
    activeAuthScope = scope
  }

  function findById(id: string): ProjectV2 | undefined {
    resetForAuthScope()
    return projects.value.find(p => p.id === id)
  }

  function findByName(name: string): ProjectV2 | undefined {
    resetForAuthScope()
    return projects.value.find(p => p.name === name)
  }

  /**
   * 拉取项目列表。
   * - force=false（默认）：缓存新鲜则跳过；过期才重新请求
   * - force=true：强制刷新（用户主动点刷新按钮 / 创建/删除项目后）
   *
   * 失败时不清空已有列表 —— 用户在 UI 上看到的卡片不会因为一次网络抖动消失。
   */
  async function fetchProjects(force = false): Promise<void> {
    const scope = currentProjectListScope()
    resetForAuthScope(scope)
    if (!force && isFresh.value && hasData.value) return
    if (isLoading.value) {
      if (!force) return  // 非强制刷新并发去重
      activeListController?.abort()
    }

    isLoading.value = true
    lastError.value = ''
    const controller = new AbortController()
    activeListController = controller
    try {
      const { data } = await projectsV2Api.list(
        { limit: 50 },
        { signal: controller.signal, timeout: PROJECT_LIST_TIMEOUT_MS },
      )
      if (Array.isArray(data)) {
        if (activeAuthScope !== scope) return
        projects.value = data
        lastFetchedAt.value = Date.now()
      } else {
        lastError.value = '服务返回异常，已保留上次项目列表'
      }
    } catch (e: any) {
      if (e?.code === 'ERR_CANCELED') return
      lastError.value = formatUserFacingErrorMessage(
        e,
        `加载失败`,
      )
    } finally {
      if (activeListController === controller) {
        activeListController = null
        isLoading.value = false
      }
    }
  }

  function upsertProject(project: ProjectV2): void {
    resetForAuthScope()
    const idx = projects.value.findIndex(p => p.id === project.id)
    if (idx >= 0) projects.value[idx] = project
    else projects.value.unshift(project)
    lastError.value = ''
    lastFetchedAt.value = Date.now()
  }

  function removeProject(id: string): void {
    resetForAuthScope()
    projects.value = projects.value.filter(p => p.id !== id)
  }

  function clearError(): void {
    lastError.value = ''
  }

  function invalidate(): void {
    resetForAuthScope()
    lastFetchedAt.value = 0
  }

  return {
    projects,
    isLoading,
    lastError,
    isFresh,
    hasData,
    resetForAuthScope,
    findById,
    findByName,
    fetchProjects,
    upsertProject,
    removeProject,
    clearError,
    invalidate,
  }
})
