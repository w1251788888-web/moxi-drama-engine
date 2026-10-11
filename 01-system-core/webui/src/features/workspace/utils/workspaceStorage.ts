import { simpleHash } from '@/features/workspace/utils/workflowState'

const STORAGE_PREFIX = 'moxi-workspace'

function _safeSegment(value: string): string {
  return value.trim().replace(/[^a-zA-Z0-9:_-]/g, '_').slice(0, 80) || 'unknown'
}

function _readUserSession(): Record<string, any> | null {
  try {
    const raw = localStorage.getItem('user_access_session')
    return raw ? JSON.parse(raw) as Record<string, any> : null
  } catch {
    return null
  }
}

export function workspaceActorScope(): string {
  const userSession = _readUserSession()
  const userKey = String(userSession?.key_id || '').trim()
  if (userKey) return `user:${_safeSegment(userKey)}`

  const ownerName = String(userSession?.owner_name || '').trim()
  if (ownerName) return `user:${simpleHash(ownerName).slice(0, 12)}`

  const adminToken = localStorage.getItem('admin_token') || ''
  if (adminToken) return `admin:${simpleHash(adminToken).slice(0, 12)}`

  return 'anonymous'
}

export function workspaceStorageKey(bucket: string, projectId: string, scope = workspaceActorScope()): string {
  return [
    STORAGE_PREFIX,
    _safeSegment(scope),
    'project',
    _safeSegment(projectId),
    _safeSegment(bucket),
  ].join(':')
}

export function legacyWorkspaceStorageKey(bucket: string, projectId: string): string {
  if (bucket === 'completedTabs') return `workspace_${projectId}_completed`
  return `${bucket}_${projectId}`
}

function _canReadLegacyStorage(scope: string): boolean {
  return scope === 'anonymous' || scope.startsWith('admin:')
}

export function loadWorkspaceStorage(bucket: string, projectId: string): string | null {
  if (!projectId) return null
  try {
    const scope = workspaceActorScope()
    const scoped = localStorage.getItem(workspaceStorageKey(bucket, projectId, scope))
    if (scoped !== null) return scoped
    if (!_canReadLegacyStorage(scope)) return null
    return localStorage.getItem(legacyWorkspaceStorageKey(bucket, projectId))
  } catch {
    return null
  }
}

export function saveWorkspaceStorage(bucket: string, projectId: string, value: string): boolean {
  if (!projectId) return false
  try {
    localStorage.setItem(workspaceStorageKey(bucket, projectId), value)
    return true
  } catch {
    return false
  }
}
