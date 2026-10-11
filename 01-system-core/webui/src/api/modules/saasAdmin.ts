import api from '../http'

export interface UserAccessKeySession {
  key_id: string
  owner_name: string
  credit_balance: number
  advanced_generation_enabled: boolean
  allow_copy_export: boolean
  admin_role: 'user' | 'secondary_admin'
  status: string
  session_token?: string | null
  session_expires_at?: string | null
}

export interface CreatedAccessKey {
  key_id: string
  plain_key: string
  owner_name: string
  credit_balance: number
  advanced_generation_enabled: boolean
  allow_copy_export: boolean
  admin_role: 'user' | 'secondary_admin'
}

export interface FrontUserRegisterPayload {
  username: string
  password: string
  invite_code: string
  phone?: string
  email?: string
}

export interface FrontUserRegisterResponse extends UserAccessKeySession {
  front_user_id: string
  plain_key?: string | null
}

export interface SubscriptionPlanItem {
  plan_id: string
  code: string
  name: string
  description: string
  price_cny: number
  credit_amount: number
  advanced_generation_enabled: boolean
  validity_days: number
  status: string
  sort_order: number
  created_at?: string | null
  updated_at?: string | null
}

export interface PaymentOrderItem {
  order_id: string
  order_no: string
  access_key_id: string
  front_user_id: string
  plan_id: string
  plan_code: string
  plan_name?: string
  amount_cny: number
  credit_amount: number
  provider: string
  status: string
  human_reason: string
  paid_at?: string | null
  created_at?: string | null
  user_session?: UserAccessKeySession | null
  credit_balance?: number | null
  advanced_generation_enabled?: boolean | null
}

export interface OperatorAuditItem {
  audit_id: string
  actor_type: string
  actor_id: string
  actor_label: string
  action: string
  target_type: string
  target_id: string
  status: string
  summary: string
  metadata: Record<string, unknown>
  created_at: string | null
}

export interface MoxiAdminOverview {
  billing_rule: string
  credit_unit: string
  cards: Array<{ label: string; value: string | number }>
  sections: string[]
  cost_health?: {
    actual_cost_cny: number
    billed_credit: number
    gross_margin_credit: number
  }
}

export interface KnowledgeBaseStatus {
  ok: boolean
  mode: 'connected' | 'degraded' | 'disabled' | string
  backend: string
  configured: boolean
  base_url: string
  datasets_configured: number
  dataset_names: string[]
  dify_dataset_total: number | null
  matched_dataset_count: number
  unmatched_dataset_names: string[]
  checked_at: string
  message: string
  error_type?: string
  status_code?: number
}

export interface AdminListResponse<T> {
  items: T[]
  total: number
}

export interface AccessKeyAdminItem extends UserAccessKeySession {
  key_prefix: string
  plain_key: string
  contact: string
  last_used_at: string | null
  created_at: string | null
}

export interface FrontUserAdminItem {
  user_id: string
  username: string
  phone: string
  email: string
  status: string
  note: string
  access_key_id: string
  key_status: string
  key_prefix: string
  credit_balance: number
  advanced_generation_enabled: boolean
  created_at: string | null
  updated_at: string | null
  plain_key?: string | null
  plain_password?: string | null
}

export interface LLMProviderItem {
  id: string
  provider: string
  display_name: string
  base_url: string
  default_model: string
  models: string[]
  is_active: boolean
  is_default: boolean
  has_api_key: boolean
  api_key_masked: string
  input_cost_cny_per_1k: number
  output_cost_cny_per_1k: number
  billing_multiplier: number
  minimum_actual_cost_cny: number
}

export interface AdvancedGenerationRoleConfig {
  role: string
  label: string
  provider: string
  provider_name: string
  model: string
  temperature: number
  duty: string
  steps: string[]
  has_api_key: boolean
  api_key_masked: string
  is_active: boolean
}

export interface AdvancedGenerationAdminConfig {
  enabled: boolean
  profile_id: string
  roles: AdvancedGenerationRoleConfig[]
  updated_at: string | null
}

export interface CreditLedgerItem {
  id: string
  access_key_id: string
  event_type: string
  amount: number
  balance_after: number
  actual_cost_cny: number
  billing_multiplier: number
  provider: string
  model: string
  prompt_tokens: number
  completion_tokens: number
  generation_type: string
  status: string
  human_reason: string
  created_at: string | null
}

export interface InviteCodeItem {
  invite_id: string
  plain_code?: string | null
  code_prefix: string
  batch_name: string
  status: string
  max_uses: number
  used_count: number
  assigned_to: string
  note: string
  created_at: string | null
}

export const userAccessApi = {
  login: (accessKey: string) =>
    api.post<UserAccessKeySession>('/user/access-key/login', { access_key: accessKey }),
  loginWithAccount: (username: string, password: string) =>
    api.post<UserAccessKeySession>('/user/account/login', { username, password }),
  currentSession: () =>
    api.get<UserAccessKeySession>('/user/session'),
  register: (data: FrontUserRegisterPayload) =>
    api.post<FrontUserRegisterResponse>('/user/register', data),
  listSubscriptionPlans: () =>
    api.get<AdminListResponse<SubscriptionPlanItem>>('/user/subscription-plans'),
  createSubscriptionOrder: (data: { plan_id: string; checkout_mode?: 'demo' | 'pending'; provider?: string }) =>
    api.post<PaymentOrderItem>('/user/subscription-orders', data),
  listSubscriptionOrders: () =>
    api.get<AdminListResponse<PaymentOrderItem>>('/user/subscription-orders'),
  aiChat: (params: {
    messages: Array<{ role: string; content: string }>
    context?: string
    chat_context_packet?: string
    system_prompt?: string
    max_tokens?: number
    audience_axis?: string
    genre?: string
    format_type?: string
  }) =>
    api.post<{ content: string; role: string }>(
      '/user/ai/chat',
      params,
      { timeout: 90000 },
    ),
}

export const moxiAdminApi = {
  overview: () => api.get<MoxiAdminOverview>('/moxi-admin/overview'),
  knowledgeBaseStatus: () =>
    api.get<KnowledgeBaseStatus>('/moxi-admin/knowledge-base/status', { timeout: 5000 }),
  listAccessKeys: (params?: { keyword?: string; status?: string }) =>
    api.get<AdminListResponse<AccessKeyAdminItem>>('/moxi-admin/access-keys', { params }),
  createAccessKey: (data: {
    owner_name: string
    initial_credit?: number
    advanced_generation_enabled?: boolean
    allow_copy_export?: boolean
    admin_role?: 'user' | 'secondary_admin'
  }) => api.post<CreatedAccessKey>('/moxi-admin/access-keys', data),
  createAccessKeyBySecondaryAdmin: (data: {
    owner_name: string
    initial_credit?: number
  }) => api.post<CreatedAccessKey>('/moxi-admin/secondary/access-keys', data),
  setAccessKeyStatus: (keyId: string, status: 'active' | 'disabled') =>
    api.put<UserAccessKeySession>(`/moxi-admin/access-keys/${keyId}/status`, { status }),
  deleteAccessKey: (keyId: string) =>
    api.delete<UserAccessKeySession>(`/moxi-admin/access-keys/${keyId}`),
  rechargeAccessKey: (keyId: string, data: { amount: number; reason?: string }) =>
    api.post<UserAccessKeySession>(`/moxi-admin/access-keys/${keyId}/recharge`, data),
  listInviteCodes: (params?: { status?: string; batch_name?: string }) =>
    api.get<AdminListResponse<InviteCodeItem>>('/moxi-admin/invite-codes', { params }),
  createInviteCodes: (data: {
    count: number
    batch_name?: string
    max_uses?: number
    assigned_to?: string
    note?: string
  }) => api.post<AdminListResponse<InviteCodeItem>>('/moxi-admin/invite-codes', data),
  setInviteCodeStatus: (inviteId: string, status: 'active' | 'disabled') =>
    api.put<InviteCodeItem>(`/moxi-admin/invite-codes/${inviteId}/status`, { status }),
  listFrontUsers: (params?: { keyword?: string; status?: string }) =>
    api.get<AdminListResponse<FrontUserAdminItem>>('/moxi-admin/front-users', { params }),
  createFrontUser: (data: {
    username: string
    password: string
    phone?: string
    email?: string
    note?: string
    initial_credit?: number
    advanced_generation_enabled?: boolean
  }) => api.post<FrontUserAdminItem>('/moxi-admin/front-users', data),
  updateFrontUser: (userId: string, data: {
    username?: string
    password?: string
    phone?: string
    email?: string
    status?: 'active' | 'disabled'
    note?: string
  }) => api.put<FrontUserAdminItem>(`/moxi-admin/front-users/${userId}`, data),
  deleteFrontUser: (userId: string) =>
    api.delete<FrontUserAdminItem>(`/moxi-admin/front-users/${userId}`),
  seedDefaultFrontUsers: () =>
    api.post<AdminListResponse<FrontUserAdminItem>>('/moxi-admin/front-users/seed-defaults'),
  setAdvancedGeneration: (keyId: string, enabled: boolean) =>
    api.put<UserAccessKeySession>(`/moxi-admin/access-keys/${keyId}/advanced-generation`, { enabled }),
  setCopyExportPermission: (keyId: string, enabled: boolean) =>
    api.put<UserAccessKeySession>(`/moxi-admin/access-keys/${keyId}/copy-export`, { enabled }),
  listLLMProviders: () =>
    api.get<AdminListResponse<LLMProviderItem>>('/moxi-admin/llm-providers'),
  saveLLMProvider: (provider: string, data: {
    display_name?: string
    base_url?: string
    api_key?: string
    default_model?: string
    models?: string[]
    is_active?: boolean
    is_default?: boolean
    input_cost_cny_per_1k?: number
    output_cost_cny_per_1k?: number
    billing_multiplier?: number
    minimum_actual_cost_cny?: number
  }) => api.put<LLMProviderItem>(`/moxi-admin/llm-providers/${provider}`, data),
  refreshProviderModels: (provider: string) =>
    api.post<LLMProviderItem>(`/moxi-admin/llm-providers/${provider}/models/refresh`),
  refreshKimiModels: () =>
    api.post<LLMProviderItem>('/moxi-admin/llm-providers/kimi/models/refresh'),
  getAdvancedGenerationConfig: () =>
    api.get<AdvancedGenerationAdminConfig>('/moxi-admin/advanced-generation/config'),
  saveAdvancedGenerationConfig: (data: {
    enabled: boolean
    profile_id: string
    roles: Array<{
      role: string
      provider: string
      model: string
      temperature: number
      duty: string
    }>
  }) => api.put<AdvancedGenerationAdminConfig>('/moxi-admin/advanced-generation/config', data),
  listCreditLedger: () =>
    api.get<AdminListResponse<CreditLedgerItem>>('/moxi-admin/credit-ledger'),
  listGenerationLogs: () =>
    api.get<AdminListResponse<CreditLedgerItem>>('/moxi-admin/generation-logs'),
  listExceptions: () =>
    api.get<AdminListResponse<CreditLedgerItem>>('/moxi-admin/exceptions'),
  listSubscriptionPlans: () =>
    api.get<AdminListResponse<SubscriptionPlanItem>>('/moxi-admin/subscription-plans'),
  seedDefaultSubscriptionPlans: () =>
    api.post<AdminListResponse<SubscriptionPlanItem>>('/moxi-admin/subscription-plans/seed-defaults'),
  saveSubscriptionPlan: (data: {
    plan_id?: string
    code: string
    name: string
    description: string
    price_cny: number
    credit_amount: number
    advanced_generation_enabled: boolean
    validity_days: number
    status: string
    sort_order: number
  }) => api.post<SubscriptionPlanItem>('/moxi-admin/subscription-plans', data),
  listPaymentOrders: () =>
    api.get<AdminListResponse<PaymentOrderItem>>('/moxi-admin/payment-orders'),
  listOperatorAuditLogs: (params?: {
    actor_type?: string
    action?: string
    target_type?: string
    status?: string
    limit?: number
  }) => api.get<AdminListResponse<OperatorAuditItem>>('/moxi-admin/operator-audit-logs', { params }),
}
