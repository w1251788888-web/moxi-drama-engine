import api from '../http'

interface CacheStatusWireResponse {
  backend: string
  redis_configured: boolean
  redis_available: boolean
  redis_error: string
  memory_keys?: number
  memory_entries?: number
  degraded: boolean
  dashboard_ttl_seconds: number
}

export interface CacheStatusResponse {
  backend: string
  redis_configured: boolean
  redis_available: boolean
  redis_error: string
  memory_keys: number
  memory_entries?: number
  degraded: boolean
  dashboard_ttl_seconds: number
}

export interface CacheClearResponse {
  memory_deleted: number
  redis_deleted: number
  prefix: string
  status: CacheStatusResponse
}

function normalizeCacheStatus(data: CacheStatusWireResponse): CacheStatusResponse {
  return {
    ...data,
    memory_keys: data.memory_keys ?? data.memory_entries ?? 0,
  }
}

export const cacheApi = {
  status: async () => {
    const response = await api.get<CacheStatusWireResponse>('/admin/cache/status')
    return {
      ...response,
      data: normalizeCacheStatus(response.data),
    }
  },

  clear: async (prefix?: string) => {
    const response = await api.post<Omit<CacheClearResponse, 'status'> & { status: CacheStatusWireResponse }>(
      '/admin/cache/clear',
      null,
      { params: { prefix } },
    )
    return {
      ...response,
      data: {
        ...response.data,
        status: normalizeCacheStatus(response.data.status),
      },
    }
  },
}
