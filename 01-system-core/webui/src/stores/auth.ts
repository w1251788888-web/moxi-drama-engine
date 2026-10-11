import { ref, computed } from 'vue'
import { defineStore } from 'pinia'
import { adminApi, userAccessApi, type UserAccessKeySession } from '@/api/client'

const isAdminEntry = typeof window !== 'undefined' && window.location.pathname.startsWith('/moxi-admin')
const USER_SESSION_VALIDATION_TTL_MS = 30_000

function safeParseUserSession(raw: string | null): UserAccessKeySession | null {
  if (!raw) return null
  try {
    return JSON.parse(raw) as UserAccessKeySession
  } catch {
    localStorage.removeItem('user_access_session')
    return null
  }
}

function isUserSessionExpired(session: UserAccessKeySession | null): boolean {
  const sessionToken = String(session?.session_token || '').trim()
  if (!sessionToken) return true
  const expiresAt = String(session?.session_expires_at || '').trim()
  if (!expiresAt) return false
  const expiresAtMs = Date.parse(expiresAt)
  if (!Number.isFinite(expiresAtMs)) return true
  return expiresAtMs <= Date.now()
}

function responseDetailFromError(error: unknown): string {
  const data = (error as { response?: { data?: unknown } } | undefined)?.response?.data
  if (typeof data === 'string') return data
  if (data && typeof data === 'object') {
    const detail = (data as { detail?: unknown; message?: unknown }).detail
      || (data as { message?: unknown }).message
    return typeof detail === 'string' ? detail : ''
  }
  return ''
}

function isDefinitiveUserSessionFailure(error: unknown): boolean {
  const status = Number((error as { response?: { status?: number } } | undefined)?.response?.status || 0)
  const detail = responseDetailFromError(error)
  if (status === 401) return true
  if (status !== 403) return false
  return (
    detail.includes('用户 Session')
    || detail.includes('用户 session')
    || detail.includes('用户密钥无效')
    || detail.includes('当前账号不可用，请重新登录')
    || detail.includes('无效或已过期')
  )
}

function isTransientUserSessionValidationError(error: unknown): boolean {
  return !isDefinitiveUserSessionFailure(error)
}

function toSafeUserSession(session: UserAccessKeySession): UserAccessKeySession {
  return {
    key_id: session.key_id,
    owner_name: session.owner_name,
    credit_balance: session.credit_balance,
    advanced_generation_enabled: session.advanced_generation_enabled,
    allow_copy_export: !!session.allow_copy_export,
    admin_role: session.admin_role === 'secondary_admin' ? 'secondary_admin' : 'user',
    status: session.status,
    session_token: session.session_token,
    session_expires_at: session.session_expires_at,
  }
}

export const useAuthStore = defineStore('auth', () => {
  const initialAdminToken = localStorage.getItem('admin_token')
  const parsedUserSession = safeParseUserSession(localStorage.getItem('user_access_session'))
  const initialUserSession = isUserSessionExpired(parsedUserSession) ? null : parsedUserSession
  if (parsedUserSession && !initialUserSession) {
    localStorage.removeItem('user_access_session')
  }
  if (initialAdminToken && initialUserSession) {
    if (isAdminEntry) {
      localStorage.removeItem('user_access_session')
    } else {
      localStorage.removeItem('admin_token')
    }
  }

  const token = ref<string | null>(initialAdminToken && (!initialUserSession || isAdminEntry) ? initialAdminToken : null)
  const userSession = ref<UserAccessKeySession | null>(initialUserSession && (!initialAdminToken || !isAdminEntry) ? initialUserSession : null)
  const sessionValidationCheckedAt = ref(0)
  let userSessionValidationPromise: Promise<boolean> | null = null

  const isAuthenticated = computed(() => !!token.value || !!userSession.value)
  const isAdminAuthenticated = computed(() => !!token.value)
  const isSecondaryAdmin = computed(() => userSession.value?.admin_role === 'secondary_admin')
  const advancedGenerationEnabled = computed(() => !!userSession.value?.advanced_generation_enabled || !!token.value)
  const copyExportAllowed = computed(() => !!token.value || !!userSession.value?.allow_copy_export)

  async function loginAdmin(username: string, password: string) {
    const { data } = await adminApi.login(username, password)
    userSession.value = null
    localStorage.removeItem('user_access_session')
    token.value = data.token
    localStorage.setItem('admin_token', data.token)
    return data
  }

  async function login(password: string) {
    return loginAdmin('admin', password)
  }

  async function loginWithAccessKey(accessKey: string) {
    const { data } = await userAccessApi.login(accessKey)
    setUserSession(data)
    return data
  }

  async function loginWithAccount(username: string, password: string) {
    const { data } = await userAccessApi.loginWithAccount(username, password)
    setUserSession(data)
    return data
  }

  async function registerWithInvite(data: {
    username: string
    password: string
    invite_code: string
    phone?: string
    email?: string
  }) {
    const { data: session } = await userAccessApi.register(data)
    setUserSession(session)
    return session
  }

  async function refreshUserSession() {
    const existingToken = userSession.value?.session_token
    if (!existingToken) return null
    const { data } = await userAccessApi.currentSession()
    setUserSession({
      ...data,
      session_token: data.session_token || existingToken,
      session_expires_at: data.session_expires_at || userSession.value?.session_expires_at || null,
    })
    sessionValidationCheckedAt.value = Date.now()
    return data
  }

  async function ensureUserSessionValid(options: { force?: boolean } = {}) {
    if (token.value) return true
    if (!userSession.value) return false
    if (isUserSessionExpired(userSession.value)) {
      clearUserSession()
      return false
    }
    if (!options.force && Date.now() - sessionValidationCheckedAt.value < USER_SESSION_VALIDATION_TTL_MS) return true
    if (!userSessionValidationPromise) {
      userSessionValidationPromise = refreshUserSession()
        .then(() => true)
        .catch((error) => {
          if (isDefinitiveUserSessionFailure(error)) {
            clearUserSession()
            return false
          }
          if (isTransientUserSessionValidationError(error)) {
            sessionValidationCheckedAt.value = Date.now()
          }
          return true
        })
        .finally(() => {
          userSessionValidationPromise = null
        })
    }
    return userSessionValidationPromise
  }

  function setUserSession(session: UserAccessKeySession) {
    const safeSession = toSafeUserSession(session)
    token.value = null
    localStorage.removeItem('admin_token')
    userSession.value = safeSession
    localStorage.setItem('user_access_session', JSON.stringify(safeSession))
  }

  function patchUserSession(patch: Partial<UserAccessKeySession>) {
    if (!userSession.value) return
    setUserSession({ ...userSession.value, ...patch })
  }

  function clearAdminToken() {
    token.value = null
    localStorage.removeItem('admin_token')
  }

  function clearUserSession() {
    userSession.value = null
    localStorage.removeItem('user_access_session')
  }

  function logout() {
    clearAdminToken()
    clearUserSession()
  }

  return {
    token,
    userSession,
    isAuthenticated,
    isAdminAuthenticated,
    isSecondaryAdmin,
    advancedGenerationEnabled,
    copyExportAllowed,
    login,
    loginAdmin,
    loginWithAccessKey,
    loginWithAccount,
    registerWithInvite,
    refreshUserSession,
    ensureUserSessionValid,
    setUserSession,
    patchUserSession,
    clearAdminToken,
    clearUserSession,
    logout,
  }
})
