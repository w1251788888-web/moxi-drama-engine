import api from '../http'

export interface SearchResultItem {
  doc_type: 'rule' | 'material' | 'project' | 'skill'
  source_id: string
  title: string
  title_snippet: string
  content_snippet: string
  metadata: Record<string, unknown>
  updated_at: string
  score: number
  backend: string
}

export interface SearchResponse {
  items: SearchResultItem[]
  count: number
  indexed_count: number
  backend: string
  rebuilt: boolean
  semantic_degraded?: boolean
  semantic_error?: string
}

export interface SearchStatusResponse {
  available: boolean
  backend?: string
  indexed_count: number
  doc_type_counts: Record<string, number>
  collection?: string
  persist_path?: string
  degraded?: boolean
  error?: string
}

export const searchApi = {
  search: (params: {
    q: string
    types?: Array<'rule' | 'material' | 'project' | 'skill'> | string
    limit?: number
    offset?: number
    auto_rebuild?: boolean
  }) => api.get<SearchResponse>('/search', {
    params: {
      ...params,
      types: Array.isArray(params.types) ? params.types.join(',') : params.types,
    },
  }),

  status: () => api.get<SearchStatusResponse>('/search/status'),

  rebuild: () => api.post<SearchStatusResponse>('/search/rebuild'),

  semanticSearch: (params: {
    q: string
    types?: Array<'rule' | 'material' | 'project' | 'skill'> | string
    limit?: number
    auto_rebuild?: boolean
  }) => api.get<SearchResponse>('/search/semantic', {
    params: {
      ...params,
      types: Array.isArray(params.types) ? params.types.join(',') : params.types,
    },
  }),

  semanticStatus: () => api.get<SearchStatusResponse>('/search/semantic/status'),

  rebuildSemantic: () => api.post<SearchStatusResponse>('/search/semantic/rebuild'),
}
