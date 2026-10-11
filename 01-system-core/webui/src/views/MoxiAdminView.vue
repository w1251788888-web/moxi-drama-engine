<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import {
  AlertTriangle,
  BookOpen,
  Bot,
  ChartNoAxesCombined,
  CheckCircle2,
  Copy,
  KeyRound,
  ListChecks,
  LogOut,
  NotebookText,
  PackageCheck,
  PanelsTopLeft,
  PlayCircle,
  ReceiptText,
  RefreshCw,
  Search,
  Settings,
  ShieldCheck,
  Sparkles,
  Trash2,
  UserPlus,
  WalletCards,
  Workflow,
} from 'lucide-vue-next'
import { toast } from 'vue-sonner'
import { useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import {
  moxiAdminApi,
  type AccessKeyAdminItem,
  type AdvancedGenerationAdminConfig,
  type AdvancedGenerationRoleConfig,
  type CreatedAccessKey,
  type CreditLedgerItem,
  type FrontUserAdminItem,
  type InviteCodeItem,
  type KnowledgeBaseStatus,
  type LLMProviderItem,
  type MoxiAdminOverview,
  type OperatorAuditItem,
  type PaymentOrderItem,
  type SkillArtifactItem,
  type SkillBindingItem,
  type SkillCatalogItem,
  type SkillInvocationItem,
  type SkillQualityFeedbackItem,
  type SkillQualityFeedbackSummaryResponse,
  type SkillRecommendResponse,
  type SubscriptionPlanItem,
  skillWorkflowApi,
} from '@/api/client'
import { clipboardCopy } from '@/lib/clipboard'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'

const auth = useAuthStore()
const router = useRouter()

const username = ref('admin')
const password = ref('')
const secondaryAdminKey = ref('')
const loading = ref(false)
const secondaryAdminLoading = ref(false)
const error = ref('')
const activeSection = ref('总览看板')
const creatingKey = ref(false)
const newKeyOwner = ref('')
const newKeyCredit = ref(99)
const newKeyAdvanced = ref(true)
const newKeyCopyExport = ref(false)
const newKeyAdminRole = ref<'user' | 'secondary_admin'>('user')
const latestKey = ref<CreatedAccessKey | null>(null)
const inviteBatchName = ref('demo-internal')
const inviteCount = ref(5)
const inviteAssignedTo = ref('')
const inviteNote = ref('内测发放')
const latestInviteCodes = ref<InviteCodeItem[]>([])
const latestSeedUsers = ref<FrontUserAdminItem[]>([])
const overview = ref<MoxiAdminOverview | null>(null)
const accessKeys = ref<AccessKeyAdminItem[]>([])
const frontUsers = ref<FrontUserAdminItem[]>([])
const inviteCodes = ref<InviteCodeItem[]>([])
const llmProviders = ref<LLMProviderItem[]>([])
const knowledgeBaseStatus = ref<KnowledgeBaseStatus | null>(null)
const knowledgeBaseLoading = ref(false)
const creditLedger = ref<CreditLedgerItem[]>([])
const generationLogs = ref<CreditLedgerItem[]>([])
const exceptionItems = ref<CreditLedgerItem[]>([])
const subscriptionPlans = ref<SubscriptionPlanItem[]>([])
const paymentOrders = ref<PaymentOrderItem[]>([])
const operatorAuditLogs = ref<OperatorAuditItem[]>([])
const adminLoading = ref(false)
const searchKeyword = ref('')
const frontUserSearchKeyword = ref('')
const adminDataFailures = ref<string[]>([])
const adminDataLastRefreshedAt = ref('')
const selectedProvider = ref<LLMProviderItem | null>(null)
const providerApiKey = ref('')
const providerModelsText = ref('')
const providerModelsRefreshing = ref(false)
const providerModelSaving = ref(false)
const providerConfigSaving = ref(false)
const providerConfigMessage = ref('')
const providerConfigMessageType = ref<'success' | 'error'>('success')
const advancedGenerationConfig = ref<AdvancedGenerationAdminConfig | null>(null)
const advancedGenerationEnabled = ref(true)
const advancedGenerationProfileId = ref('short_drama')
const advancedRoleForms = ref<AdvancedGenerationRoleConfig[]>([])
const advancedGenerationConfigSaving = ref(false)
const advancedGenerationConfigMessage = ref('')
const advancedGenerationConfigMessageType = ref<'success' | 'error'>('success')
const rechargeAmount = ref(20)
const creatingFrontUser = ref(false)
const frontUserForm = ref({
  username: '',
  password: '',
  phone: '',
  email: '',
  note: '',
  initial_credit: 10,
  advanced_generation_enabled: true,
})
const savingPlan = ref(false)
const seedingPlans = ref(false)
const planForm = ref({
  plan_id: '',
  code: 'starter',
  name: '入门套餐',
  description: '适合短剧项目验证的小额订阅包',
  price_cny: 99,
  credit_amount: 99,
  advanced_generation_enabled: false,
  validity_days: 30,
  status: 'active',
  sort_order: 10,
})
const skillCatalog = ref<SkillCatalogItem[]>([])
const skillBindings = ref<SkillBindingItem[]>([])
const skillInvocations = ref<SkillInvocationItem[]>([])
const skillArtifacts = ref<SkillArtifactItem[]>([])
const skillFeedback = ref<SkillQualityFeedbackItem[]>([])
const skillFeedbackSummary = ref<SkillQualityFeedbackSummaryResponse | null>(null)
const skillRecommendation = ref<SkillRecommendResponse | null>(null)
const skillLoading = ref(false)
const savingSkillBinding = ref(false)
const startingSkillInvocation = ref(false)
const savingSkillArtifact = ref(false)
const runningSkillWorker = ref(false)
const savingSkillFeedback = ref(false)
const skillBindingForm = ref({
  skill_name: '',
  binding_type: 'failure_type',
  binding_key: 'format_break',
  priority: 50,
  config_text: '{\n  "reason": "按失败类型触发 Skill"\n}',
  metadata_text: '{}',
  is_enabled: true,
})
const skillRecommendForm = ref({
  failure_type: 'format_break',
  context: 'moxi-admin',
})
const skillWorkerForm = ref({
  failure_type: 'format_break',
  context: 'skill-worker',
  max_skills: 3,
})
const skillInvocationForm = ref({
  skill_name: '',
  binding_id: '',
  context: 'moxi-admin',
  failure_type: 'manual_check',
  input_summary: '',
})
const skillArtifactForm = ref({
  invocation_id: '',
  artifact_type: 'markdown',
  title: '',
  content: '',
  path: '',
})
const skillFeedbackForm = ref({
  invocation_id: '',
  score: 80,
  verdict: 'useful',
  notes: '',
})

const navItems = [
  { label: '总览看板', icon: ChartNoAxesCombined },
  { label: 'LLM接口配置', icon: Bot },
  { label: '知识库', icon: BookOpen },
  { label: '用户密钥管理', icon: KeyRound },
  { label: '额度流水', icon: ReceiptText },
  { label: '生成日志', icon: NotebookText },
  { label: '异常中心', icon: AlertTriangle },
  { label: '科研生成链路', icon: PanelsTopLeft },
  { label: 'Skill封装', icon: Workflow },
  { label: '注册用户框架', icon: ListChecks },
  { label: '套餐订阅框架', icon: WalletCards },
  { label: '操作者审计', icon: ShieldCheck },
  { label: '系统设置', icon: Settings },
]

const fallbackDashboardCards = [
  { label: '今日生成', value: '0次', hint: '接入真实生成日志后自动刷新', tone: 'blue' },
  { label: '今日扣费', value: '0额度', hint: '按实际成本 × 5 计算', tone: 'green' },
  { label: '活跃密钥', value: '0个', hint: '后台生成后进入统计', tone: 'purple' },
  { label: '异常事件', value: '0条', hint: '失败任务会进入异常中心', tone: 'amber' },
]

const providerCards = [
  { name: 'Kimi', desc: '当前主力中文创作模型', status: '可配置', tone: 'bg-[#ecfdf5] text-[#047857]' },
  { name: 'OpenAI', desc: '通用推理与结构生成', status: '待填Key', tone: 'bg-[#eff6ff] text-[#1d4ed8]' },
  { name: 'Claude', desc: '长文审稿与逻辑评估', status: '待填Key', tone: 'bg-[#f5f3ff] text-[#6d28d9]' },
  { name: 'DeepSeek', desc: '低成本辅助生成', status: '待填Key', tone: 'bg-[#fff7ed] text-[#c2410c]' },
  { name: '通义千问', desc: '国产兼容接口预留', status: '框架', tone: 'bg-[#f8fafc] text-[#475569]' },
  { name: '自定义接口', desc: 'OpenAI 兼容供应商', status: '框架', tone: 'bg-[#f8fafc] text-[#475569]' },
]

const humanLogs = [
  { time: '09:30', type: '成功', text: '密钥用户生成大纲成功，等待接入真实扣费流水。' },
  { time: '09:42', type: '提醒', text: '科研生成链路当前仅管理员授权用户可见。' },
  { time: '10:05', type: '待办', text: 'LLM Key 加密保存和真实成本统计还需要接入。' },
]

const costBars = [42, 58, 36, 72, 48, 64, 52]

const enabledText = computed(() => {
  if (auth.isAdminAuthenticated) return '管理员已登录'
  if (auth.isSecondaryAdmin) return '二级管理员已登录'
  return '请输入管理员账号密码'
})
const canUseMoxiAdmin = computed(() => auth.isAdminAuthenticated || auth.isSecondaryAdmin)
const canManageAllAdminSections = computed(() => auth.isAdminAuthenticated)
const visibleNavItems = computed(() =>
  canManageAllAdminSections.value
    ? navItems
    : navItems.filter((item) => item.label === '用户密钥管理'),
)
const dashboardCards = computed(() => overview.value?.cards?.length ? overview.value.cards.map((item) => ({
  label: item.label,
  value: item.value,
  hint: item.label === '今日扣费' ? '按实际成本 × 5 计算' : '来自后台真实查询',
})) : fallbackDashboardCards)
const selectedProviderModelOptions = computed(() => {
  const candidates = [
    ...(selectedProvider.value?.models || []),
    ...providerModelsText.value.split('\n'),
    selectedProvider.value?.default_model || '',
  ]
  const models: string[] = []
  for (const item of candidates) {
    const model = String(item || '').trim()
    if (model && !models.includes(model)) {
      models.push(model)
    }
  }
  return models
})
const advancedGenerationReadyRoles = computed(() =>
  advancedRoleForms.value.filter((role) => role.provider && role.model && role.has_api_key).length,
)
const advancedGenerationApiProviders = computed(() =>
  llmProviders.value.filter((provider) =>
    advancedRoleForms.value.some((role) => role.provider === provider.provider),
  ),
)

const filteredAccessKeys = computed(() => {
  const keyword = searchKeyword.value.trim()
  if (!keyword) return accessKeys.value
  return accessKeys.value.filter((item) =>
    [item.owner_name, item.plain_key, item.key_prefix, item.status].some((value) => String(value || '').includes(keyword)),
  )
})

function accessKeyDisplayValue(item: AccessKeyAdminItem) {
  return item.plain_key || item.key_prefix || '历史密钥无法还原完整值'
}

function accessKeyDisplayHint(item: AccessKeyAdminItem) {
  return item.plain_key ? '完整密钥' : '历史密钥仅保留前缀；旧库未保存明文，不能反推完整值'
}

const filteredFrontUsers = computed(() => {
  const keyword = frontUserSearchKeyword.value.trim()
  if (!keyword) return frontUsers.value
  return frontUsers.value.filter((item) =>
    [
      item.username,
      item.email,
      item.phone,
      item.note,
      item.key_prefix,
      item.status,
      item.key_status,
    ].some((value) => String(value || '').includes(keyword)),
  )
})

const frontUserStats = computed(() => ({
  active: frontUsers.value.filter((item) => item.status === 'active').length,
  disabled: frontUsers.value.filter((item) => item.status === 'disabled').length,
}))
const skillStats = computed(() => ({
  catalog: skillCatalog.value.length,
  enabledBindings: skillBindings.value.filter((item) => item.is_enabled && item.status === 'active').length,
  startedInvocations: skillInvocations.value.filter((item) => item.status === 'started').length,
  artifacts: skillArtifacts.value.length,
  feedback: skillFeedback.value.length,
}))
const skillFeedbackSummaryItems = computed(() => skillFeedbackSummary.value?.items || [])
const skillFeedbackVerdictCounts = computed(() => skillFeedbackSummary.value?.verdict_counts || {})
const skillVerdictLabels: Record<string, string> = {
  pending_review: '待复核',
  useful: '有用',
  not_useful: '无效',
  needs_followup: '需跟进',
  blocked: '阻塞',
}
const skillStatusLabels: Record<string, string> = {
  active: '启用',
  archived: '已归档',
  started: '进行中',
  success: '成功',
  failed: '失败',
  disabled: '停用',
}
const skillBindingKeyLabels: Record<string, string> = {
  global: '全局默认',
  format_break: '格式错误',
  logic_break: '逻辑断裂',
  character_drift: '角色跑偏',
  weak_hook: '钩子不足',
  repetition: '内容重复',
  manual_check: '人工检查',
  moxi_admin: '后台管理',
  skill_worker: 'Skill 自动处理',
}
const ledgerStatusLabels: Record<string, string> = {
  success: '成功（已扣费/已入账）',
  failed: '失败（未扣费）',
  pending: '处理中',
  cancelled: '已取消',
}
const ledgerEventTypeLabels: Record<string, string> = {
  charge: '生成扣费',
  recharge: '充值入账',
  refund: '退回补偿',
  adjustment: '后台调整',
}
const generationTypeLabels: Record<string, string> = {
  testing_script_scene: '剧本片段生成',
  testing_scene_suggest: '片段建议',
  testing_scene_patch: '片段改写',
  testing_script_validate: '规则校验',
  testing_script_deep_audit: '深度审校',
  testing_script_auto_fix: '自动修正',
  script: '剧本生成',
  scene_draft: '场景草稿',
  generation: '通用生成',
  subscription: '套餐订阅',
}
const skillBindingTypes = [
  { value: 'global', label: '全局' },
  { value: 'failure_type', label: '失败类型' },
  { value: 'step', label: '步骤' },
  { value: 'project_type', label: '项目类型' },
  { value: 'context', label: '上下文' },
]
const recommendedSkillNames = computed(() =>
  (skillRecommendation.value?.recommended_skills || [])
    .map((item) => String(item.name || ''))
    .filter(Boolean),
)
const knowledgeBaseModeLabel = computed(() => {
  if (!knowledgeBaseStatus.value) return '未检测'
  if (knowledgeBaseStatus.value.mode === 'connected') return '已连接'
  if (knowledgeBaseStatus.value.mode === 'disabled') return '未配置'
  return '已降级'
})
const knowledgeBaseToneClass = computed(() => {
  if (knowledgeBaseStatus.value?.mode === 'connected') return 'bg-[#ecfdf5] text-[#047857]'
  if (knowledgeBaseStatus.value?.mode === 'disabled') return 'bg-[#f3f7fb] text-[#667085]'
  return 'bg-[#fff7ed] text-[#c2410c]'
})

function statusBadgeClass(status: string) {
  if (status === 'active') return 'bg-[#ecfdf5] text-[#047857]'
  if (status === 'disabled') return 'bg-[#fff7ed] text-[#c2410c]'
  if (status === 'deleted') return 'bg-[#fef2f2] text-[#b91c1c]'
  return 'bg-[#f3f7fb] text-[#667085]'
}

async function handleAdminLogin() {
  loading.value = true
  error.value = ''
  try {
    await auth.loginAdmin(username.value, password.value)
    await loadAdminData()
  } catch (e: unknown) {
    const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
    error.value = detail || '管理员登录失败'
  } finally {
    loading.value = false
  }
}

async function handleSecondaryAdminLogin() {
  secondaryAdminLoading.value = true
  error.value = ''
  try {
    const session = await auth.loginWithAccessKey(secondaryAdminKey.value)
    if (session.admin_role !== 'secondary_admin') {
      auth.logout()
      error.value = '这个密钥不是二级管理员密钥'
      return
    }
    activeSection.value = '用户密钥管理'
    accessKeys.value = []
    latestKey.value = null
  } catch (e: unknown) {
    const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
    error.value = detail || '二级管理员登录失败'
  } finally {
    secondaryAdminLoading.value = false
  }
}

function handleAdminLogout() {
  auth.logout()
  error.value = ''
  activeSection.value = '总览看板'
  toast.success('已退出后台登录')
  router.replace('/login')
}

async function loadKnowledgeBaseStatus() {
  knowledgeBaseLoading.value = true
  try {
    knowledgeBaseStatus.value = (await moxiAdminApi.knowledgeBaseStatus()).data
  } finally {
    knowledgeBaseLoading.value = false
  }
}

async function loadAdminData() {
  if (auth.isSecondaryAdmin && !auth.isAdminAuthenticated) {
    activeSection.value = '用户密钥管理'
    adminDataFailures.value = []
    adminDataLastRefreshedAt.value = new Date().toLocaleTimeString('zh-CN', {
      hour: '2-digit',
      minute: '2-digit',
      hour12: false,
    })
    return
  }
  if (!auth.isAdminAuthenticated) return
  adminLoading.value = true
  const failures: string[] = []
  const capture = async (label: string, task: () => Promise<void>) => {
    try {
      await task()
    } catch (e: unknown) {
      failures.push(label)
      console.warn(`[MoxiAdmin] ${label} load failed`, e)
    }
  }
  try {
    await Promise.all([
      capture('总览', async () => { overview.value = (await moxiAdminApi.overview()).data }),
      capture('用户密钥', async () => { accessKeys.value = (await moxiAdminApi.listAccessKeys()).data.items }),
      capture('注册用户', async () => { frontUsers.value = (await moxiAdminApi.listFrontUsers()).data.items }),
      capture('邀请码', async () => { inviteCodes.value = (await moxiAdminApi.listInviteCodes()).data.items }),
      capture('LLM配置', async () => { llmProviders.value = (await moxiAdminApi.listLLMProviders()).data.items }),
      capture('知识库', loadKnowledgeBaseStatus),
      capture('科研生成链路', loadAdvancedGenerationConfig),
      capture('额度流水', async () => { creditLedger.value = (await moxiAdminApi.listCreditLedger()).data.items }),
      capture('生成日志', async () => { generationLogs.value = (await moxiAdminApi.listGenerationLogs()).data.items }),
      capture('异常中心', async () => { exceptionItems.value = (await moxiAdminApi.listExceptions()).data.items }),
      capture('套餐配置', async () => { subscriptionPlans.value = (await moxiAdminApi.listSubscriptionPlans()).data.items }),
      capture('支付订单', async () => { paymentOrders.value = (await moxiAdminApi.listPaymentOrders()).data.items }),
      capture('操作者审计', async () => { operatorAuditLogs.value = (await moxiAdminApi.listOperatorAuditLogs({ limit: 200 })).data.items }),
      capture('Skill封装', loadSkillWorkflowData),
    ])
    if (!selectedProvider.value && llmProviders.value.length) {
      const firstProvider = llmProviders.value[0]
      if (firstProvider) {
        selectProvider(firstProvider)
      }
    }
    adminDataFailures.value = failures
    adminDataLastRefreshedAt.value = new Date().toLocaleTimeString('zh-CN', {
      hour: '2-digit',
      minute: '2-digit',
      hour12: false,
    })
    if (failures.length) {
      toast.warning(`部分后台数据读取失败：${failures.join('、')}`)
    }
  } catch (e: unknown) {
    const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
    toast.error(detail || '后台数据读取失败')
  } finally {
    adminLoading.value = false
  }
}

async function loadSkillWorkflowData() {
  const [catalog, bindings, invocations, artifacts, feedback, feedbackSummary] = await Promise.all([
    skillWorkflowApi.catalog({ include_disabled: true }),
    skillWorkflowApi.listBindings({ include_disabled: true, limit: 200 }),
    skillWorkflowApi.listInvocations({ limit: 100 }),
    skillWorkflowApi.listArtifacts({ limit: 100 }),
    skillWorkflowApi.listQualityFeedback({ limit: 100 }),
    skillWorkflowApi.qualityFeedbackSummary({ limit: 500, min_feedback: 1 }),
  ])
  skillCatalog.value = catalog.data.skills
  skillBindings.value = bindings.data.items
  skillInvocations.value = invocations.data.items
  skillArtifacts.value = artifacts.data.items
  skillFeedback.value = feedback.data.items
  skillFeedbackSummary.value = feedbackSummary.data
  const firstSkill = skillCatalog.value[0]?.name || ''
  if (firstSkill) {
    if (!skillBindingForm.value.skill_name) skillBindingForm.value.skill_name = firstSkill
    if (!skillInvocationForm.value.skill_name) skillInvocationForm.value.skill_name = firstSkill
  }
  if (!skillArtifactForm.value.invocation_id && skillInvocations.value[0]?.id) {
    skillArtifactForm.value.invocation_id = skillInvocations.value[0].id
  }
  if (!skillFeedbackForm.value.invocation_id && skillInvocations.value[0]?.id) {
    skillFeedbackForm.value.invocation_id = skillInvocations.value[0].id
  }
}

function parseJsonRecord(raw: string, label: string): Record<string, unknown> {
  const text = raw.trim()
  if (!text) return {}
  const parsed = JSON.parse(text) as unknown
  if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
    throw new Error(`${label} 必须是 JSON 对象`)
  }
  return parsed as Record<string, unknown>
}

function formatCompactJson(value: Record<string, unknown>) {
  const keys = Object.keys(value || {})
  if (!keys.length) return '{}'
  return JSON.stringify(value)
}

function skillBindingTypeLabel(value: string) {
  return skillBindingTypes.find((item) => item.value === value)?.label || value
}

function skillStatusLabel(value: string) {
  return skillStatusLabels[value] || value || '-'
}

function skillVerdictLabel(value: string) {
  return skillVerdictLabels[value] || value || '-'
}

function skillBindingKeyLabel(value: string) {
  if (!value) return '全局默认'
  return skillBindingKeyLabels[value] ? `${skillBindingKeyLabels[value]}（${value}）` : value
}

function ledgerStatusLabel(value: string) {
  return ledgerStatusLabels[value] || value || '-'
}

function ledgerEventTypeLabel(value: string) {
  return ledgerEventTypeLabels[value] || value || '-'
}

function generationTypeLabel(value: string) {
  return generationTypeLabels[value] || value || '-'
}

async function syncSkillCatalog() {
  skillLoading.value = true
  try {
    const { data } = await skillWorkflowApi.sync()
    toast.success(`Skill 目录已同步：${data.registry_count} 个`)
    await loadSkillWorkflowData()
  } catch (e: unknown) {
    const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
    toast.error(detail || '同步 Skill 目录失败')
  } finally {
    skillLoading.value = false
  }
}

async function createSkillBinding() {
  if (!skillBindingForm.value.skill_name) {
    toast.error('请选择 Skill')
    return
  }
  savingSkillBinding.value = true
  try {
    await skillWorkflowApi.createBinding({
      skill_name: skillBindingForm.value.skill_name,
      binding_type: skillBindingForm.value.binding_type,
      binding_key: skillBindingForm.value.binding_type === 'global' ? '' : skillBindingForm.value.binding_key.trim(),
      priority: Number(skillBindingForm.value.priority || 100),
      config: parseJsonRecord(skillBindingForm.value.config_text, '绑定配置'),
      metadata: parseJsonRecord(skillBindingForm.value.metadata_text, '绑定元数据'),
      is_enabled: skillBindingForm.value.is_enabled,
    })
    toast.success('Skill 绑定已保存')
    await loadSkillWorkflowData()
  } catch (e: unknown) {
    const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
    toast.error(detail || (e instanceof Error ? e.message : '保存 Skill 绑定失败'))
  } finally {
    savingSkillBinding.value = false
  }
}

async function toggleSkillBinding(item: SkillBindingItem) {
  try {
    await skillWorkflowApi.updateBinding(item.id, { is_enabled: !item.is_enabled })
    toast.success(item.is_enabled ? '绑定已停用' : '绑定已启用')
    await loadSkillWorkflowData()
  } catch (e: unknown) {
    const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
    toast.error(detail || '更新 Skill 绑定失败')
  }
}

async function archiveSkillBinding(item: SkillBindingItem) {
  try {
    await skillWorkflowApi.updateBinding(item.id, { status: 'archived', is_enabled: false })
    toast.success('绑定已归档')
    await loadSkillWorkflowData()
  } catch (e: unknown) {
    const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
    toast.error(detail || '归档 Skill 绑定失败')
  }
}

async function previewSkillRecommendation() {
  try {
    const { data } = await skillWorkflowApi.recommend({
      failure_type: skillRecommendForm.value.failure_type.trim(),
      context: skillRecommendForm.value.context.trim() || 'moxi-admin',
      blocking_issues: [],
      warnings: [],
    })
    skillRecommendation.value = data
    toast.success('推荐链路已刷新')
  } catch (e: unknown) {
    const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
    toast.error(detail || '读取 Skill 推荐失败')
  }
}

async function runSkillWorker() {
  runningSkillWorker.value = true
  try {
    const { data } = await skillWorkflowApi.runWorker({
      failure_type: skillWorkerForm.value.failure_type.trim(),
      context: skillWorkerForm.value.context.trim() || 'skill-worker',
      max_skills: Number(skillWorkerForm.value.max_skills || 3),
      actor_type: 'system',
      actor_id: 'moxi-admin',
    })
    skillRecommendation.value = data.recommendation
    toast.success(`Skill worker 已生成 ${data.planned_count} 条执行计划`)
    await loadSkillWorkflowData()
  } catch (e: unknown) {
    const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
    toast.error(detail || '运行 Skill worker 失败')
  } finally {
    runningSkillWorker.value = false
  }
}

async function startSkillInvocation() {
  if (!skillInvocationForm.value.skill_name) {
    toast.error('请选择要记录的 Skill')
    return
  }
  startingSkillInvocation.value = true
  try {
    const { data } = await skillWorkflowApi.startInvocation({
      skill_name: skillInvocationForm.value.skill_name,
      binding_id: skillInvocationForm.value.binding_id,
      actor_type: 'admin',
      context: skillInvocationForm.value.context.trim() || 'moxi-admin',
      failure_type: skillInvocationForm.value.failure_type.trim(),
      input_summary: skillInvocationForm.value.input_summary.trim(),
      metadata: { source: 'moxi-admin-ui' },
    })
    skillArtifactForm.value.invocation_id = data.id
    toast.success('Skill 调用已开始记录')
    await loadSkillWorkflowData()
  } catch (e: unknown) {
    const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
    toast.error(detail || '记录 Skill 调用失败')
  } finally {
    startingSkillInvocation.value = false
  }
}

async function finishSkillInvocation(item: SkillInvocationItem, status: 'success' | 'failed' | 'cancelled') {
  try {
    await skillWorkflowApi.finishInvocation(item.id, {
      status,
      output_summary: status === 'success' ? '管理员确认本次 Skill 调用完成' : '管理员手动结束本次 Skill 调用',
      metadata: { source: 'moxi-admin-ui' },
    })
    toast.success('Skill 调用状态已更新')
    await loadSkillWorkflowData()
  } catch (e: unknown) {
    const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
    toast.error(detail || '更新 Skill 调用失败')
  }
}

async function createSkillFeedback() {
  if (!skillFeedbackForm.value.invocation_id) {
    toast.error('请选择调用记录')
    return
  }
  savingSkillFeedback.value = true
  try {
    await skillWorkflowApi.createQualityFeedback(skillFeedbackForm.value.invocation_id, {
      score: Number(skillFeedbackForm.value.score || 0),
      verdict: skillFeedbackForm.value.verdict,
      reviewer_type: 'admin',
      reviewer_id: 'moxi-admin',
      notes: skillFeedbackForm.value.notes.trim(),
      metadata: { source: 'moxi-admin-ui' },
    })
    skillFeedbackForm.value.notes = ''
    toast.success('质量反馈已记录')
    await loadSkillWorkflowData()
  } catch (e: unknown) {
    const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
    toast.error(detail || '记录质量反馈失败')
  } finally {
    savingSkillFeedback.value = false
  }
}

async function createSkillArtifact() {
  if (!skillArtifactForm.value.invocation_id) {
    toast.error('请选择调用记录')
    return
  }
  savingSkillArtifact.value = true
  try {
    await skillWorkflowApi.createArtifact(skillArtifactForm.value.invocation_id, {
      artifact_type: skillArtifactForm.value.artifact_type.trim() || 'markdown',
      title: skillArtifactForm.value.title.trim(),
      content: skillArtifactForm.value.content,
      path: skillArtifactForm.value.path.trim(),
      metadata: { source: 'moxi-admin-ui' },
    })
    skillArtifactForm.value.title = ''
    skillArtifactForm.value.content = ''
    skillArtifactForm.value.path = ''
    toast.success('Skill 产物已记录')
    await loadSkillWorkflowData()
  } catch (e: unknown) {
    const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
    toast.error(detail || '记录 Skill 产物失败')
  } finally {
    savingSkillArtifact.value = false
  }
}

function editSubscriptionPlan(plan: SubscriptionPlanItem) {
  planForm.value = {
    plan_id: plan.plan_id,
    code: plan.code,
    name: plan.name,
    description: plan.description || '',
    price_cny: plan.price_cny,
    credit_amount: plan.credit_amount,
    advanced_generation_enabled: plan.advanced_generation_enabled,
    validity_days: plan.validity_days,
    status: plan.status,
    sort_order: plan.sort_order,
  }
}

function resetSubscriptionPlanForm() {
  planForm.value = {
    plan_id: '',
    code: '',
    name: '',
    description: '',
    price_cny: 0,
    credit_amount: 0,
    advanced_generation_enabled: false,
    validity_days: 30,
    status: 'active',
    sort_order: 10,
  }
}

async function saveSubscriptionPlan() {
  if (!planForm.value.code.trim() || !planForm.value.name.trim()) {
    toast.error('请填写套餐编码和名称')
    return
  }
  savingPlan.value = true
  try {
    await moxiAdminApi.saveSubscriptionPlan({
      plan_id: planForm.value.plan_id || undefined,
      code: planForm.value.code.trim(),
      name: planForm.value.name.trim(),
      description: planForm.value.description.trim(),
      price_cny: Number(planForm.value.price_cny || 0),
      credit_amount: Number(planForm.value.credit_amount || 0),
      advanced_generation_enabled: planForm.value.advanced_generation_enabled,
      validity_days: Number(planForm.value.validity_days || 0),
      status: planForm.value.status,
      sort_order: Number(planForm.value.sort_order || 0),
    })
    toast.success('套餐已保存')
    resetSubscriptionPlanForm()
    await loadAdminData()
  } catch (e: unknown) {
    const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
    toast.error(detail || '保存套餐失败')
  } finally {
    savingPlan.value = false
  }
}

async function seedDefaultSubscriptionPlans() {
  seedingPlans.value = true
  try {
    const { data } = await moxiAdminApi.seedDefaultSubscriptionPlans()
    subscriptionPlans.value = data.items
    toast.success(`默认套餐已补齐：${data.total} 个`)
  } catch (e: unknown) {
    const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
    toast.error(detail || '补齐默认套餐失败')
  } finally {
    seedingPlans.value = false
  }
}

async function createInviteCodes() {
  try {
    const { data } = await moxiAdminApi.createInviteCodes({
      count: Number(inviteCount.value || 1),
      batch_name: inviteBatchName.value.trim() || 'demo-internal',
      max_uses: 1,
      assigned_to: inviteAssignedTo.value.trim(),
      note: inviteNote.value.trim(),
    })
    latestInviteCodes.value = data.items
    toast.success(`已生成 ${data.total} 个邀请码`)
    await loadAdminData()
  } catch (e: unknown) {
    const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
    toast.error(detail || '生成邀请码失败')
  }
}

async function createFrontUser() {
  if (!frontUserForm.value.username.trim() || !frontUserForm.value.password.trim()) {
    toast.error('请填写用户名和初始密码')
    return
  }
  creatingFrontUser.value = true
  try {
    const { data } = await moxiAdminApi.createFrontUser({
      username: frontUserForm.value.username.trim(),
      password: frontUserForm.value.password,
      phone: frontUserForm.value.phone.trim(),
      email: frontUserForm.value.email.trim(),
      note: frontUserForm.value.note.trim(),
      initial_credit: Number(frontUserForm.value.initial_credit || 0),
      advanced_generation_enabled: frontUserForm.value.advanced_generation_enabled,
    })
    latestSeedUsers.value = [data]
    frontUserForm.value = {
      username: '',
      password: '',
      phone: '',
      email: '',
      note: '',
      initial_credit: 10,
      advanced_generation_enabled: true,
    }
    toast.success('注册用户已创建')
    await loadAdminData()
  } catch (e: unknown) {
    const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
    toast.error(detail || '创建注册用户失败')
  } finally {
    creatingFrontUser.value = false
  }
}

async function seedDefaultFrontUsers() {
  try {
    const { data } = await moxiAdminApi.seedDefaultFrontUsers()
    latestSeedUsers.value = data.items
    const newCount = data.items.filter((item) => item.plain_password).length
    toast.success(newCount ? `已生成 ${newCount} 个默认用户` : '默认用户已存在')
    await loadAdminData()
  } catch (e: unknown) {
    const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
    toast.error(detail || '生成默认用户失败')
  }
}

async function copyFrontUserCredential(item: FrontUserAdminItem) {
  const lines = [
    `用户名：${item.username}`,
    item.plain_password ? `密码：${item.plain_password}` : '',
    item.plain_key ? `使用密钥：${item.plain_key}` : '',
  ].filter(Boolean)
  if (!lines.length) return
  await clipboardCopy(lines.join('\n'))
  toast.success('用户登录信息已复制')
}

async function updateFrontUserStatus(item: FrontUserAdminItem, status: 'active' | 'disabled') {
  try {
    await moxiAdminApi.updateFrontUser(item.user_id, { status })
    toast.success(status === 'active' ? '用户已启用' : '用户已停用')
    await loadAdminData()
  } catch (e: unknown) {
    const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
    toast.error(detail || '更新用户状态失败')
  }
}

async function deleteFrontUser(item: FrontUserAdminItem) {
  if (!window.confirm(`确认软删除用户 ${item.username}？关联密钥和会话会被停用。`)) return
  try {
    await moxiAdminApi.deleteFrontUser(item.user_id)
    toast.success('用户已软删除')
    await loadAdminData()
  } catch (e: unknown) {
    const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
    toast.error(detail || '删除用户失败')
  }
}

async function disableInviteCode(item: InviteCodeItem) {
  await moxiAdminApi.setInviteCodeStatus(item.invite_id, 'disabled')
  toast.success('邀请码已停用')
  await loadAdminData()
}

async function createAccessKey() {
  if (!newKeyOwner.value.trim()) {
    toast.error('请先填写客户备注')
    return
  }
  creatingKey.value = true
  try {
    const payload = {
      owner_name: newKeyOwner.value.trim(),
      initial_credit: Number(newKeyCredit.value || 0),
      advanced_generation_enabled: canManageAllAdminSections.value ? newKeyAdvanced.value : false,
      allow_copy_export: canManageAllAdminSections.value ? newKeyCopyExport.value : false,
      admin_role: canManageAllAdminSections.value ? newKeyAdminRole.value : 'user',
    } as const
    const { data } = canManageAllAdminSections.value
      ? await moxiAdminApi.createAccessKey(payload)
      : await moxiAdminApi.createAccessKeyBySecondaryAdmin(payload)
    latestKey.value = data
    toast.success('密钥已生成')
    if (canManageAllAdminSections.value) {
      await loadAdminData()
    }
  } catch (e: unknown) {
    const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
    toast.error(detail || '生成密钥失败')
  } finally {
    creatingKey.value = false
  }
}

async function copyLatestKey() {
  if (!latestKey.value?.plain_key) return
  await clipboardCopy(latestKey.value.plain_key)
  toast.success('密钥已复制')
}

async function copyInviteCode(code: string | null | undefined) {
  if (!code) return
  await clipboardCopy(code)
  toast.success('邀请码已复制')
}

function selectProvider(provider: LLMProviderItem) {
  selectedProvider.value = { ...provider }
  providerApiKey.value = ''
  providerModelsText.value = provider.models.join('\n')
  providerConfigMessage.value = ''
}

function applyAdvancedGenerationConfig(config: AdvancedGenerationAdminConfig) {
  advancedGenerationConfig.value = config
  advancedGenerationEnabled.value = config.enabled
  advancedGenerationProfileId.value = config.profile_id || 'short_drama'
  advancedRoleForms.value = config.roles.map((role) => ({
    ...role,
    temperature: Number(role.temperature || 0),
  }))
}

async function loadAdvancedGenerationConfig() {
  const { data } = await moxiAdminApi.getAdvancedGenerationConfig()
  applyAdvancedGenerationConfig(data)
}

function providerForRole(providerKey: string) {
  return llmProviders.value.find((provider) => provider.provider === providerKey)
}

function modelOptionsForProvider(providerKey: string, currentModel = '') {
  const provider = providerForRole(providerKey)
  const candidates = [
    ...(provider?.models || []),
    provider?.default_model || '',
    currentModel,
  ]
  const models: string[] = []
  for (const item of candidates) {
    const model = String(item || '').trim()
    if (model && !models.includes(model)) {
      models.push(model)
    }
  }
  return models
}

function syncAdvancedRoleProvider(role: AdvancedGenerationRoleConfig) {
  const provider = providerForRole(role.provider)
  role.provider_name = provider?.display_name || role.provider
  role.has_api_key = Boolean(provider?.has_api_key)
  role.api_key_masked = provider?.api_key_masked || ''
  role.is_active = Boolean(provider?.is_active)
  role.model = provider?.default_model || provider?.models?.[0] || ''
}

function openProviderConfig(providerKey?: string) {
  activeSection.value = 'LLM接口配置'
  const provider = llmProviders.value.find((item) => item.provider === providerKey) || llmProviders.value[0]
  if (provider) {
    selectProvider(provider)
  }
}

async function saveAdvancedGenerationConfig() {
  advancedGenerationConfigSaving.value = true
  advancedGenerationConfigMessage.value = ''
  try {
    const { data } = await moxiAdminApi.saveAdvancedGenerationConfig({
      enabled: advancedGenerationEnabled.value,
      profile_id: advancedGenerationProfileId.value,
      roles: advancedRoleForms.value.map((role) => ({
        role: role.role,
        provider: role.provider,
        model: role.model,
        temperature: Number(role.temperature || 0),
        duty: role.duty,
      })),
    })
    applyAdvancedGenerationConfig(data)
    advancedGenerationConfigMessageType.value = 'success'
    advancedGenerationConfigMessage.value = '保存成功：科研生成链路模型分工已更新'
    toast.success('科研生成链路已保存')
  } catch (e: unknown) {
    const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
    advancedGenerationConfigMessageType.value = 'error'
    advancedGenerationConfigMessage.value = detail || '科研生成链路保存失败'
    toast.error(detail || '科研生成链路保存失败')
  } finally {
    advancedGenerationConfigSaving.value = false
  }
}

function syncSelectedProviderActive(isActive: boolean) {
  if (!selectedProvider.value) return
  selectedProvider.value.is_active = isActive
  if (isActive) {
    llmProviders.value = llmProviders.value.map((item) => ({
      ...item,
      is_active: item.provider === selectedProvider.value?.provider,
    }))
  }
}

function syncSelectedProviderStatusFromList() {
  if (!selectedProvider.value) return
  const freshProvider = llmProviders.value.find((item) => item.provider === selectedProvider.value?.provider)
  if (!freshProvider) return
  selectedProvider.value.is_active = freshProvider.is_active
  selectedProvider.value.is_default = freshProvider.is_default
}

function replaceProviderInList(provider: LLMProviderItem) {
  llmProviders.value = llmProviders.value.map((item) =>
    item.provider === provider.provider ? { ...provider } : item,
  )
}

function buildProviderSavePayload(provider: LLMProviderItem, apiKey = '') {
  return {
    display_name: provider.display_name,
    base_url: provider.base_url,
    api_key: apiKey,
    default_model: provider.default_model,
    models: provider.models,
    is_active: provider.is_active,
    is_default: provider.is_default,
    input_cost_cny_per_1k: Number(provider.input_cost_cny_per_1k || 0),
    output_cost_cny_per_1k: Number(provider.output_cost_cny_per_1k || 0),
    billing_multiplier: Number(provider.billing_multiplier || 5),
    minimum_actual_cost_cny: Number(provider.minimum_actual_cost_cny || 0),
  }
}

async function refreshSelectedProviderModels(options: { silent?: boolean } = {}) {
  if (!selectedProvider.value) return
  providerModelsRefreshing.value = true
  const providerKey = selectedProvider.value.provider
  const providerLabel = selectedProvider.value.display_name || selectedProvider.value.provider
  try {
    if (!options.silent || providerApiKey.value.trim()) {
      const provider = {
        ...selectedProvider.value,
        models: providerModelsText.value.split('\n').map((item) => item.trim()).filter(Boolean),
      }
      const { data: savedConfig } = await moxiAdminApi.saveLLMProvider(providerKey, buildProviderSavePayload(provider, providerApiKey.value))
      selectedProvider.value = savedConfig
      providerApiKey.value = ''
      providerModelsText.value = savedConfig.models.join('\n')
      replaceProviderInList(savedConfig)
    }

    const { data } = await moxiAdminApi.refreshProviderModels(providerKey)
    selectedProvider.value = data
    providerModelsText.value = data.models.join('\n')
    replaceProviderInList(data)
    if (!options.silent) {
      toast.success(`${providerLabel} 模型列表已更新`)
    }
  } catch (e: unknown) {
    const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
    if (options.silent) {
      console.warn('[MoxiAdmin] provider model refresh failed', e)
    } else {
      toast.error(detail || '模型列表拉取失败')
    }
  } finally {
    providerModelsRefreshing.value = false
  }
}

async function switchSelectedProviderModel() {
  if (!selectedProvider.value) return
  if (!selectedProvider.value.default_model) return
  providerModelSaving.value = true
  try {
    const provider = {
      ...selectedProvider.value,
      models: selectedProviderModelOptions.value,
    }
    const { data } = await moxiAdminApi.saveLLMProvider(provider.provider, buildProviderSavePayload(provider, providerApiKey.value))
    selectedProvider.value = data
    providerApiKey.value = ''
    providerModelsText.value = data.models.join('\n')
    replaceProviderInList(data)
    toast.success(`${data.display_name || data.provider} 模型已切换为 ${data.default_model}`)
  } catch (e: unknown) {
    const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
    toast.error(detail || '模型切换失败')
  } finally {
    providerModelSaving.value = false
  }
}

async function setProviderActive(provider: LLMProviderItem, isActive: boolean) {
  const nextProvider = { ...provider, is_active: isActive }
  try {
    await moxiAdminApi.saveLLMProvider(provider.provider, buildProviderSavePayload(nextProvider))
    if (selectedProvider.value?.provider === provider.provider) {
      selectedProvider.value.is_active = isActive
    }
    toast.success(isActive ? '供应商已启用，其它供应商已关闭' : '供应商已关闭')
    await loadAdminData()
    syncSelectedProviderStatusFromList()
  } catch (e: unknown) {
    const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
    toast.error(detail || '切换供应商状态失败')
  }
}

async function saveProviderConfig() {
  if (!selectedProvider.value) return
  providerConfigSaving.value = true
  providerConfigMessage.value = ''
  const provider = {
    ...selectedProvider.value,
    models: selectedProviderModelOptions.value,
  }
  try {
    const { data } = await moxiAdminApi.saveLLMProvider(provider.provider, buildProviderSavePayload(provider, providerApiKey.value))
    selectedProvider.value = data
    providerApiKey.value = ''
    providerModelsText.value = data.models.join('\n')
    replaceProviderInList(data)
    providerConfigMessageType.value = 'success'
    providerConfigMessage.value = `保存成功：${data.display_name || data.provider} 已更新`
    toast.success('保存配置成功')
    await loadAdminData()
  } catch (e: unknown) {
    const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
    providerConfigMessageType.value = 'error'
    providerConfigMessage.value = detail || '保存配置失败'
    toast.error(detail || '保存配置失败')
  } finally {
    providerConfigSaving.value = false
  }
}

async function toggleAccessKeyStatus(item: AccessKeyAdminItem) {
  const nextStatus = item.status === 'active' ? 'disabled' : 'active'
  if (nextStatus === 'disabled' && !window.confirm(`确认禁用密钥 ${accessKeyDisplayValue(item)}？已登录用户会话会立即失效。`)) return
  try {
    await moxiAdminApi.setAccessKeyStatus(item.key_id, nextStatus)
    toast.success(nextStatus === 'active' ? '密钥已启用' : '密钥已禁用，已登录会话已失效')
    await loadAdminData()
  } catch (e: unknown) {
    const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
    toast.error(detail || (nextStatus === 'active' ? '启用密钥失败' : '禁用密钥失败'))
  }
}

async function deleteAccessKey(item: AccessKeyAdminItem) {
  if (!window.confirm(`确认删除密钥 ${accessKeyDisplayValue(item)}？删除后该密钥不能再登录，该密钥名下项目数据、独立用户库和已登录会话会一起清理。`)) return
  try {
    await moxiAdminApi.deleteAccessKey(item.key_id)
    toast.success('密钥已删除，已登录会话已失效')
    await loadAdminData()
  } catch (e: unknown) {
    const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
    toast.error(detail || '删除密钥失败')
  }
}

async function rechargeAccessKey(item: AccessKeyAdminItem) {
  await moxiAdminApi.rechargeAccessKey(item.key_id, { amount: Number(rechargeAmount.value || 0), reason: '后台手动充值' })
  toast.success('充值成功')
  await loadAdminData()
}

async function toggleCopyExportPermission(item: AccessKeyAdminItem) {
  try {
    const enabled = !item.allow_copy_export
    await moxiAdminApi.setCopyExportPermission(item.key_id, enabled)
    toast.success(enabled ? '已开启复制导出权限' : '已关闭复制导出权限')
    await loadAdminData()
  } catch (e: unknown) {
    const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
    toast.error(detail || '更新复制导出权限失败')
  }
}

function formatTime(value: string | null) {
  if (!value) return '-'
  return value.replace('T', ' ').slice(0, 16)
}

function formatOrderTime(order: PaymentOrderItem) {
  return (order.paid_at || order.created_at || '-').replace('T', ' ').slice(0, 16)
}

onMounted(() => { void loadAdminData() })
watch(canUseMoxiAdmin, (ok) => {
  if (ok) void loadAdminData()
})
watch(canManageAllAdminSections, (ok) => {
  if (!ok && auth.isSecondaryAdmin) {
    activeSection.value = '用户密钥管理'
  }
})
</script>

<template>
  <div class="min-h-screen bg-[#dff3ff] p-5 text-[#101828]">
    <div class="mx-auto flex min-h-[calc(100vh-2.5rem)] max-w-7xl overflow-hidden rounded-[28px] bg-white shadow-[0_30px_100px_rgba(34,116,178,0.22)]">
      <aside class="w-40 shrink-0 overflow-y-auto border-r border-[#edf2f7] bg-white px-3 py-5 sm:w-56 sm:px-4 lg:w-64">
        <div class="mb-6 flex items-center gap-2 sm:gap-3">
          <div class="flex h-10 w-10 shrink-0 items-center justify-center rounded-2xl bg-gradient-to-br from-[#6fbef3] to-[#8368e8] text-white sm:h-11 sm:w-11">
            M
          </div>
          <div class="min-w-0">
            <div class="truncate text-base font-semibold sm:text-lg">墨戏后台</div>
            <div class="text-xs text-[#8a94a6]">运营控制台</div>
          </div>
        </div>

        <nav class="space-y-1" aria-label="切换后台板块">
          <button
            v-for="item in visibleNavItems"
            :key="item.label"
            class="flex w-full items-center gap-2 rounded-2xl px-2.5 py-2.5 text-left text-xs leading-4 transition sm:gap-3 sm:px-3 sm:text-sm"
            :class="activeSection === item.label
              ? 'bg-[#6656df] text-white shadow-[0_12px_24px_rgba(102,86,223,0.22)]'
              : 'text-[#667085] hover:bg-[#f2f7ff] hover:text-[#2e8bd1]'"
            @click="activeSection = item.label"
          >
            <component :is="item.icon" class="h-4 w-4 shrink-0" />
            <span class="min-w-0">{{ item.label }}</span>
          </button>
        </nav>
      </aside>

      <main class="min-w-0 flex-1 overflow-auto bg-[#f8fbff]">
        <header class="flex flex-wrap items-center justify-between gap-4 border-b border-[#edf2f7] bg-white/90 px-6 py-4 backdrop-blur">
          <div>
            <p class="text-sm text-[#667085]">{{ enabledText }}</p>
            <h1 class="text-2xl font-semibold">{{ canUseMoxiAdmin ? activeSection : '欢迎回来' }}</h1>
          </div>
          <div class="flex items-center gap-3">
            <div class="hidden items-center gap-2 rounded-full bg-[#f3f7fb] px-3 py-2 text-sm text-[#667085] md:flex">
              <Search class="h-4 w-4" />
              搜索密钥 / 日志 / 异常
            </div>
            <Button
              v-if="canUseMoxiAdmin"
              variant="outline"
              class="rounded-2xl"
              @click="handleAdminLogout"
            >
              <LogOut class="mr-2 h-4 w-4" />
              退出登录
            </Button>
          </div>
        </header>

        <section v-if="!canUseMoxiAdmin" class="mx-auto mt-16 grid max-w-4xl gap-5 lg:grid-cols-2">
          <article class="rounded-[24px] bg-white p-6 shadow-sm">
          <h2 class="text-xl font-semibold">管理员登录</h2>
          <p class="mt-2 text-sm text-[#667085]">后台用于管理模型接口、用户密钥、额度和科研生成链路。</p>
          <form class="mt-6 space-y-4" @submit.prevent="handleAdminLogin">
            <Input v-model="username" class="h-11 rounded-2xl" placeholder="管理员账号" />
            <Input v-model="password" class="h-11 rounded-2xl" type="password" placeholder="管理员密码" />
            <p v-if="error" class="rounded-xl bg-red-50 px-3 py-2 text-sm text-red-600">{{ error }}</p>
            <Button class="h-11 w-full rounded-2xl bg-[#6656df] text-white hover:bg-[#5848cf]" :disabled="loading">
              {{ loading ? '登录中...' : '进入后台' }}
            </Button>
          </form>
          </article>
          <article class="rounded-[24px] bg-white p-6 shadow-sm">
            <h2 class="text-xl font-semibold">二级管理员入口</h2>
            <p class="mt-2 text-sm leading-6 text-[#667085]">使用一级管理员生成的二级管理员密钥登录，只能生成新的普通用户申请密钥。</p>
            <form class="mt-6 space-y-4" @submit.prevent="handleSecondaryAdminLogin">
              <Input v-model="secondaryAdminKey" class="h-11 rounded-2xl" type="password" placeholder="二级管理员密钥，例如 MOXI-XXXX-XXXX-XXXX" />
              <p v-if="error" class="rounded-xl bg-red-50 px-3 py-2 text-sm text-red-600">{{ error }}</p>
              <Button class="h-11 w-full rounded-2xl bg-[#101828] text-white hover:bg-[#263142]" :disabled="secondaryAdminLoading">
                {{ secondaryAdminLoading ? '验证中...' : '进入二级后台' }}
              </Button>
            </form>
          </article>
        </section>

        <section v-else class="space-y-6 p-6">
          <template v-if="activeSection === '总览看板'">
            <div class="flex flex-wrap items-center justify-between gap-3">
              <div class="text-sm text-[#667085]">
                {{ adminDataLastRefreshedAt ? `最后刷新 ${adminDataLastRefreshedAt}` : '后台数据尚未刷新' }}
                <span v-if="adminDataFailures.length" class="ml-2 text-[#c2410c]">
                  {{ adminDataFailures.length }} 个非核心分区读取失败
                </span>
              </div>
              <Button variant="outline" class="rounded-2xl" :disabled="adminLoading" @click="loadAdminData">
                {{ adminLoading ? '刷新中...' : '刷新后台数据' }}
              </Button>
            </div>

            <div class="grid gap-4 md:grid-cols-4">
              <article v-for="card in dashboardCards" :key="card.label" class="rounded-[22px] bg-white p-5 shadow-sm">
                <div class="text-sm text-[#667085]">{{ card.label }}</div>
                <div class="mt-3 text-2xl font-semibold">{{ card.value }}</div>
                <div class="mt-2 text-xs text-[#98a2b3]">{{ card.hint }}</div>
              </article>
            </div>

            <div class="grid gap-5 xl:grid-cols-[1.15fr_0.85fr]">
              <article class="rounded-[24px] bg-white p-5 shadow-sm">
                <div class="mb-5 flex items-center justify-between">
                  <div>
                    <h2 class="text-lg font-semibold">成本健康</h2>
                    <p class="text-sm text-[#667085]">真实成本、扣费和毛利来自额度流水。</p>
                  </div>
                  <span class="rounded-full bg-[#ecfdf5] px-3 py-1 text-xs text-[#047857]">健康</span>
                </div>
                <div class="mb-4 grid gap-3 text-sm md:grid-cols-3">
                  <div class="rounded-2xl bg-[#f8fbff] p-3">
                    <div class="text-[#98a2b3]">真实成本</div>
                    <div class="mt-1 font-semibold">{{ overview?.cost_health?.actual_cost_cny ?? 0 }} 元</div>
                  </div>
                  <div class="rounded-2xl bg-[#f8fbff] p-3">
                    <div class="text-[#98a2b3]">用户扣费</div>
                    <div class="mt-1 font-semibold">{{ overview?.cost_health?.billed_credit ?? 0 }} 额度</div>
                  </div>
                  <div class="rounded-2xl bg-[#f8fbff] p-3">
                    <div class="text-[#98a2b3]">毛利空间</div>
                    <div class="mt-1 font-semibold">{{ overview?.cost_health?.gross_margin_credit ?? 0 }} 额度</div>
                  </div>
                </div>
                <div class="flex h-48 items-end gap-3 rounded-2xl bg-[#f8fbff] p-5">
                  <div v-for="(bar, index) in costBars" :key="index" class="flex flex-1 flex-col items-center gap-2">
                    <div class="w-full rounded-t-xl bg-gradient-to-t from-[#6bb8ef] to-[#8368e8]" :style="{ height: `${bar}%` }" />
                    <span class="text-xs text-[#98a2b3]">{{ index + 1 }}</span>
                  </div>
                </div>
              </article>

              <article class="rounded-[24px] bg-white p-5 shadow-sm">
                <h2 class="text-lg font-semibold">人话日志</h2>
                <div class="mt-4 space-y-3">
                  <div v-for="item in humanLogs" :key="item.time + item.text" class="rounded-2xl border border-[#edf2f7] p-3">
                    <div class="flex items-center justify-between text-xs">
                      <span class="text-[#98a2b3]">{{ item.time }}</span>
                      <span class="rounded-full bg-[#f3f7fb] px-2 py-1 text-[#667085]">{{ item.type }}</span>
                    </div>
                    <p class="mt-2 text-sm leading-6 text-[#344054]">{{ item.text }}</p>
                  </div>
                </div>
              </article>
            </div>
          </template>

          <template v-else-if="activeSection === 'LLM接口配置'">
            <article class="rounded-[24px] bg-white p-5 shadow-sm">
              <div class="mb-4 flex items-center justify-between">
                <h2 class="text-lg font-semibold">LLM接口配置</h2>
                <span class="rounded-full bg-[#eef7ff] px-3 py-1 text-xs text-[#2e8bd1]">前台不可见</span>
              </div>
              <div class="grid gap-5 xl:grid-cols-[0.9fr_1.1fr]">
                <div class="grid gap-3">
                  <div
                    v-for="provider in llmProviders"
                    :key="provider.provider"
                    role="button"
                    tabindex="0"
                    class="rounded-2xl border p-4 text-left transition"
                    :class="selectedProvider?.provider === provider.provider ? 'border-[#6656df] bg-[#f5f3ff]' : 'border-[#edf2f7] bg-white hover:bg-[#f8fbff]'"
                    @click="selectProvider(provider)"
                    @keydown.enter.prevent="selectProvider(provider)"
                  >
                    <div class="flex items-center justify-between gap-3">
                      <div>
                        <div class="font-medium">{{ provider.display_name }}</div>
                        <div class="mt-1 text-xs" :class="provider.is_active ? 'text-[#047857]' : 'text-[#98a2b3]'">
                          {{ provider.is_active ? '已启用' : '未启用' }}
                        </div>
                      </div>
                      <button
                        type="button"
                        role="switch"
                        :aria-checked="provider.is_active"
                        :aria-label="`${provider.display_name}启用状态`"
                        class="relative h-7 w-12 shrink-0 rounded-full transition"
                        :class="provider.is_active ? 'bg-[#16a34a]' : 'bg-[#d9e1ec]'"
                        @click.stop="setProviderActive(provider, !provider.is_active)"
                      >
                        <span
                          class="absolute top-1 h-5 w-5 rounded-full bg-white shadow-sm transition"
                          :class="provider.is_active ? 'left-6' : 'left-1'"
                        />
                      </button>
                    </div>
                    <div class="mt-2 text-sm text-[#667085]">{{ provider.default_model || '未设置模型' }}</div>
                    <div class="mt-2 text-xs text-[#98a2b3]">{{ provider.has_api_key ? provider.api_key_masked : '未填写 API Key' }}</div>
                  </div>
                </div>

                <div v-if="selectedProvider" class="rounded-2xl border border-[#edf2f7] bg-[#f8fbff] p-4">
                  <div class="flex items-center justify-between">
                    <h3 class="font-semibold">保存配置</h3>
                    <span class="rounded-full bg-white px-2 py-1 text-xs text-[#667085]">{{ selectedProvider.provider }}</span>
                  </div>
                  <div class="mt-4 grid gap-3">
                    <Input v-model="selectedProvider.display_name" class="rounded-2xl" placeholder="显示名称" />
                    <Input v-model="selectedProvider.base_url" class="rounded-2xl" placeholder="Base URL" />
                    <Input v-model="providerApiKey" class="rounded-2xl" placeholder="API Key，留空则不修改" />
                    <div class="rounded-2xl bg-white px-4 py-3">
                      <div class="mb-2 flex items-center justify-between gap-3">
                        <div>
                          <div class="text-sm font-medium text-[#101828]">{{ selectedProvider.display_name || selectedProvider.provider }} 默认模型</div>
                          <div class="mt-1 text-xs text-[#667085]">拉取上游模型列表，选择后立即保存切换；也可在下方手工补充模型名。</div>
                        </div>
                        <Button
                          variant="outline"
                          size="sm"
                          class="rounded-2xl"
                          :disabled="providerModelsRefreshing || providerModelSaving"
                          @click="refreshSelectedProviderModels()"
                        >
                          <RefreshCw class="mr-1 h-3.5 w-3.5" :class="providerModelsRefreshing ? 'animate-spin' : ''" />
                          {{ providerModelsRefreshing ? '拉取中' : '拉取模型' }}
                        </Button>
                      </div>
                      <select
                        v-model="selectedProvider.default_model"
                        class="h-11 w-full rounded-2xl border border-[#d0d5dd] bg-white px-3 text-sm outline-none focus:border-[#6656df]"
                        :disabled="providerModelsRefreshing || providerModelSaving || !selectedProviderModelOptions.length"
                        aria-label="默认模型"
                        @change="switchSelectedProviderModel"
                      >
                        <option v-if="!selectedProviderModelOptions.length" value="">请先拉取或填写模型</option>
                        <option v-for="model in selectedProviderModelOptions" :key="model" :value="model">
                          {{ model }}
                        </option>
                      </select>
                      <div class="mt-3 max-h-24 overflow-auto rounded-2xl bg-[#f8fbff] p-3">
                        <div class="text-xs text-[#667085]">已记录 {{ selectedProviderModelOptions.length }} 个模型</div>
                        <div class="mt-2 flex flex-wrap gap-2">
                          <span
                            v-for="model in selectedProviderModelOptions"
                            :key="model"
                            class="rounded-full bg-white px-2 py-1 text-xs text-[#475467]"
                          >
                            {{ model }}
                          </span>
                        </div>
                      </div>
                    </div>
                    <textarea v-model="providerModelsText" class="min-h-28 rounded-2xl border border-[#d0d5dd] bg-white px-3 py-2 text-sm outline-none focus:border-[#6656df]" placeholder="每行一个模型；拉取失败时可手工补充" />
                    <div class="grid gap-3 md:grid-cols-2">
                      <label class="rounded-2xl bg-white px-4 py-3 text-sm">
                        <span class="flex items-center justify-between gap-3">
                          <span class="font-medium text-[#101828]">输入单价</span>
                          <span class="text-xs text-[#98a2b3]">元 / 1K tokens</span>
                        </span>
                        <Input v-model.number="selectedProvider.input_cost_cny_per_1k" class="mt-2 rounded-2xl" type="number" min="0" step="0.000001" placeholder="例如 0.002" />
                        <span class="mt-2 block text-xs leading-5 text-[#667085]">用于计算用户提示词、上下文等输入 token 的模型成本。</span>
                      </label>
                      <label class="rounded-2xl bg-white px-4 py-3 text-sm">
                        <span class="flex items-center justify-between gap-3">
                          <span class="font-medium text-[#101828]">输出单价</span>
                          <span class="text-xs text-[#98a2b3]">元 / 1K tokens</span>
                        </span>
                        <Input v-model.number="selectedProvider.output_cost_cny_per_1k" class="mt-2 rounded-2xl" type="number" min="0" step="0.000001" placeholder="例如 0.008" />
                        <span class="mt-2 block text-xs leading-5 text-[#667085]">用于计算模型回复、剧本正文等输出 token 的模型成本。</span>
                      </label>
                      <label class="rounded-2xl bg-white px-4 py-3 text-sm">
                        <span class="flex items-center justify-between gap-3">
                          <span class="font-medium text-[#101828]">扣费倍率</span>
                          <span class="text-xs text-[#98a2b3]">倍</span>
                        </span>
                        <Input v-model.number="selectedProvider.billing_multiplier" class="mt-2 rounded-2xl" type="number" min="0.01" step="0.01" placeholder="例如 10" />
                        <span class="mt-2 block text-xs leading-5 text-[#667085]">用户扣费 = 真实成本 × 扣费倍率，倍率越高扣费越高。</span>
                      </label>
                      <label class="rounded-2xl bg-white px-4 py-3 text-sm">
                        <span class="flex items-center justify-between gap-3">
                          <span class="font-medium text-[#101828]">最低真实成本</span>
                          <span class="text-xs text-[#98a2b3]">元 / 次</span>
                        </span>
                        <Input v-model.number="selectedProvider.minimum_actual_cost_cny" class="mt-2 rounded-2xl" type="number" min="0" step="0.0001" placeholder="例如 0.01" />
                        <span class="mt-2 block text-xs leading-5 text-[#667085]">单次生成成本低于该值时按这个最低值记录，避免小请求成本为零。</span>
                      </label>
                    </div>
                    <label class="flex items-center justify-between rounded-2xl bg-white px-4 py-3 text-sm">
                      <span>启用这个供应商</span>
                      <button
                        type="button"
                        role="switch"
                        :aria-checked="selectedProvider.is_active"
                        aria-label="启用这个供应商"
                        class="relative h-7 w-12 rounded-full transition"
                        :class="selectedProvider.is_active ? 'bg-[#16a34a]' : 'bg-[#d9e1ec]'"
                        @click="syncSelectedProviderActive(!selectedProvider.is_active)"
                      >
                        <span
                          class="absolute top-1 h-5 w-5 rounded-full bg-white shadow-sm transition"
                          :class="selectedProvider.is_active ? 'left-6' : 'left-1'"
                        />
                      </button>
                    </label>
                    <label class="flex items-center justify-between rounded-2xl bg-white px-4 py-3 text-sm">
                      <span>设为默认供应商</span>
                      <input v-model="selectedProvider.is_default" type="checkbox" class="h-4 w-4 accent-[#6656df]" />
                    </label>
                    <Button
                      class="rounded-2xl bg-[#6656df] text-white hover:bg-[#5848cf]"
                      :disabled="providerConfigSaving"
                      @click="saveProviderConfig"
                    >
                      {{ providerConfigSaving ? '保存中...' : '保存配置' }}
                    </Button>
                    <div
                      v-if="providerConfigMessage"
                      class="flex items-center gap-2 rounded-2xl px-4 py-3 text-sm"
                      :class="providerConfigMessageType === 'success'
                        ? 'bg-[#ecfdf5] text-[#047857]'
                        : 'bg-[#fef2f2] text-[#b42318]'"
                    >
                      <CheckCircle2 v-if="providerConfigMessageType === 'success'" class="h-4 w-4" />
                      <AlertTriangle v-else class="h-4 w-4" />
                      <span>{{ providerConfigMessage }}</span>
                    </div>
                  </div>
                </div>
              </div>
            </article>
          </template>

          <template v-else-if="activeSection === '知识库'">
            <div class="grid gap-5 xl:grid-cols-[1.1fr_0.9fr]">
              <article class="rounded-[24px] bg-white p-5 shadow-sm">
                <div class="flex flex-wrap items-center justify-between gap-3">
                  <div>
                    <h2 class="text-lg font-semibold">知识库状态</h2>
                    <p class="mt-2 text-sm text-[#667085]">只给后台管理员看，用来判断 Dify 知识库有没有接上。</p>
                  </div>
                  <div class="flex items-center gap-2">
                    <span class="rounded-full px-3 py-1 text-xs" :class="knowledgeBaseToneClass">
                      {{ knowledgeBaseModeLabel }}
                    </span>
                    <Button variant="outline" class="rounded-2xl" :disabled="knowledgeBaseLoading" @click="loadKnowledgeBaseStatus">
                      <RefreshCw class="mr-2 h-4 w-4" />
                      {{ knowledgeBaseLoading ? '检测中...' : '重新检测' }}
                    </Button>
                  </div>
                </div>

                <div
                  class="mt-5 rounded-2xl border px-4 py-4 text-sm leading-6"
                  :class="knowledgeBaseStatus?.ok
                    ? 'border-[#bbf7d0] bg-[#f0fdf4] text-[#166534]'
                    : 'border-[#fed7aa] bg-[#fff7ed] text-[#9a3412]'"
                >
                  {{ knowledgeBaseStatus?.message || '还没有检测知识库状态。' }}
                </div>

                <div class="mt-5 grid gap-3 md:grid-cols-2">
                  <div class="rounded-2xl bg-[#f8fbff] p-4">
                    <div class="text-xs text-[#98a2b3]">连接地址</div>
                    <div class="mt-2 break-all text-sm font-medium">{{ knowledgeBaseStatus?.base_url || '未配置' }}</div>
                  </div>
                  <div class="rounded-2xl bg-[#f8fbff] p-4">
                    <div class="text-xs text-[#98a2b3]">配置的数据集</div>
                    <div class="mt-2 text-sm font-medium">{{ knowledgeBaseStatus?.datasets_configured ?? 0 }} 个</div>
                  </div>
                  <div class="rounded-2xl bg-[#f8fbff] p-4">
                    <div class="text-xs text-[#98a2b3]">Dify 返回的数据集</div>
                    <div class="mt-2 text-sm font-medium">{{ knowledgeBaseStatus?.dify_dataset_total ?? '未连接' }}</div>
                  </div>
                  <div class="rounded-2xl bg-[#f8fbff] p-4">
                    <div class="text-xs text-[#98a2b3]">已匹配的数据集</div>
                    <div class="mt-2 text-sm font-medium">{{ knowledgeBaseStatus?.matched_dataset_count ?? 0 }} 个</div>
                  </div>
                </div>

                <div v-if="knowledgeBaseStatus?.error_type" class="mt-4 rounded-2xl bg-[#fef2f2] px-4 py-3 text-sm text-[#b42318]">
                  连接失败类型：{{ knowledgeBaseStatus.error_type }}
                  <span v-if="knowledgeBaseStatus.status_code"> · 状态码 {{ knowledgeBaseStatus.status_code }}</span>
                </div>
              </article>

              <article class="rounded-[24px] bg-white p-5 shadow-sm">
                <h3 class="font-semibold">线上降级保护</h3>
                <div class="mt-4 space-y-3 text-sm leading-6 text-[#667085]">
                  <p>当前不会在这台服务器强行安装 Dify，避免占用别人的服务资源。</p>
                  <p>如果知识库不可用，剧本生成会跳过知识库增强，继续走正常 AI 生成链路。</p>
                  <p>普通用户不会看到 Dify、RAG、知识库接口等内部错误；后台只在这里提示管理员。</p>
                </div>
                <div class="mt-5 rounded-2xl bg-[#f8fbff] p-4">
                  <div class="text-sm font-medium text-[#101828]">后续开启条件</div>
                  <ul class="mt-3 space-y-2 text-sm leading-6 text-[#667085]">
                    <li>1. 服务器空闲空间充足，建议至少 12G 以上。</li>
                    <li>2. Dify 有独立内部访问地址，不再使用容器里的 localhost。</li>
                    <li>3. 后台检测显示“已连接”后，再允许生成链路接入知识库增强。</li>
                  </ul>
                </div>
                <div class="mt-5 rounded-2xl border border-[#edf2f7] px-4 py-3 text-sm text-[#667085]">
                  这里就是后台知识库入口。真正的 Dify 控制台暂不公开，等服务器条件满足后再接入可打开地址。
                </div>
              </article>
            </div>
          </template>

          <template v-else-if="activeSection === '用户密钥管理'">
            <div class="grid gap-5 xl:grid-cols-[0.85fr_1.15fr]">
              <article class="rounded-[24px] bg-white p-5 shadow-sm">
                <h2 class="text-lg font-semibold">生成密钥</h2>
                <p class="mt-2 text-sm text-[#667085]">
                  {{ canManageAllAdminSections ? '前台用户只用这个密钥登录，不接触任何模型接口。' : '二级管理员只能生成普通用户申请密钥，不能开启科研生成权限或创建新的管理员。' }}
                </p>
                <div class="mt-5 space-y-4">
                  <Input v-model="newKeyOwner" class="h-11 rounded-2xl" placeholder="客户备注，例如：张总内测" />
                  <Input v-model.number="newKeyCredit" class="h-11 rounded-2xl" type="number" min="0" placeholder="初始额度" />
                  <label v-if="canManageAllAdminSections" class="rounded-2xl bg-[#f8fbff] px-4 py-3 text-sm">
                    <span class="font-medium text-[#101828]">管理权限</span>
                    <select
                      v-model="newKeyAdminRole"
                      class="mt-2 h-11 w-full rounded-2xl border border-[#d0d5dd] bg-white px-3 text-sm outline-none focus:border-[#6656df]"
                    >
                      <option value="user">普通用户密钥</option>
                      <option value="secondary_admin">二级管理员</option>
                    </select>
                    <span class="mt-2 block text-xs leading-5 text-[#667085]">二级管理员只能进入受限后台并生成新的普通用户申请密钥。</span>
                  </label>
                  <label v-if="canManageAllAdminSections" class="flex items-center justify-between rounded-2xl bg-[#f8fbff] px-4 py-3 text-sm">
                    <span>允许科研生成</span>
                    <input v-model="newKeyAdvanced" type="checkbox" class="h-4 w-4 accent-[#6656df]" />
                  </label>
                  <label v-if="canManageAllAdminSections" class="flex items-center justify-between rounded-2xl bg-[#fff7ed] px-4 py-3 text-sm">
                    <span>
                      <span class="block">允许复制/导出</span>
                      <span class="mt-1 block text-xs text-[#9a3412]">内测默认关闭，用户仍可粘贴和编辑。</span>
                    </span>
                    <input v-model="newKeyCopyExport" type="checkbox" class="h-4 w-4 accent-[#ea580c]" />
                  </label>
                  <div v-else class="rounded-2xl bg-[#f8fbff] px-4 py-3 text-sm text-[#667085]">
                    当前权限：二级管理员 · 只允许生成普通用户密钥
                  </div>
                  <Button class="h-11 w-full rounded-2xl bg-[#6656df] text-white hover:bg-[#5848cf]" :disabled="creatingKey" @click="createAccessKey">
                    {{ creatingKey ? '生成中...' : '生成密钥' }}
                  </Button>
                </div>
              </article>

              <article class="rounded-[24px] bg-white p-5 shadow-sm">
                <h2 class="text-lg font-semibold">最近生成的密钥</h2>
                <div v-if="latestKey" class="mt-4 rounded-2xl border border-[#dbeafe] bg-[#eff6ff] p-4">
                  <div class="text-sm text-[#667085]">{{ latestKey.owner_name }}</div>
                  <div class="mt-3 flex items-center justify-between gap-3 rounded-2xl bg-white px-4 py-3 font-mono text-sm">
                    <span>{{ latestKey.plain_key }}</span>
                    <button class="text-[#2e8bd1]" @click="copyLatestKey">
                      <Copy class="h-4 w-4" />
                    </button>
                  </div>
                  <div class="mt-3 grid gap-2 text-sm text-[#344054] md:grid-cols-2">
                    <span>额度：{{ latestKey.credit_balance }}</span>
                    <span>科研生成：{{ latestKey.advanced_generation_enabled ? '已开启' : '未开启' }}</span>
                    <span>复制导出：{{ latestKey.allow_copy_export ? '已开启' : '未开启' }}</span>
                    <span>管理权限：{{ latestKey.admin_role === 'secondary_admin' ? '二级管理员' : '普通用户' }}</span>
                  </div>
                </div>
                <div v-else class="mt-4 rounded-2xl border border-dashed border-[#d0d5dd] p-6 text-sm text-[#667085]">
                  生成后会在这里显示一次明文密钥，方便你发给用户。
                </div>
              </article>
            </div>

            <article v-if="canManageAllAdminSections" class="rounded-[24px] bg-white p-5 shadow-sm">
              <div class="mb-4 flex flex-wrap items-center justify-between gap-3">
                <h2 class="text-lg font-semibold">密钥列表</h2>
                <Input v-model="searchKeyword" class="h-10 max-w-xs rounded-2xl" placeholder="搜索客户 / 完整密钥 / 状态" />
              </div>
              <div class="overflow-hidden rounded-2xl border border-[#edf2f7]">
                <table class="w-full text-left text-sm">
                  <thead class="bg-[#f8fbff] text-[#667085]">
                    <tr>
                      <th class="px-4 py-3">客户</th>
                      <th class="px-4 py-3">完整密钥</th>
                      <th class="px-4 py-3">管理权限</th>
                      <th class="px-4 py-3">额度</th>
                      <th class="px-4 py-3">科研生成</th>
                      <th class="px-4 py-3">复制/导出</th>
                      <th class="px-4 py-3">状态</th>
                      <th class="px-4 py-3">操作</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr v-for="item in filteredAccessKeys" :key="item.key_id" class="border-t border-[#edf2f7]">
                      <td class="px-4 py-3">{{ item.owner_name }}</td>
                      <td class="px-4 py-3">
                        <div class="break-all font-mono text-xs">{{ accessKeyDisplayValue(item) }}</div>
                        <div class="mt-1 text-xs text-[#98a2b3]">{{ accessKeyDisplayHint(item) }}</div>
                      </td>
                      <td class="px-4 py-3">{{ item.admin_role === 'secondary_admin' ? '二级管理员' : '普通用户' }}</td>
                      <td class="px-4 py-3">{{ item.credit_balance }}</td>
                      <td class="px-4 py-3">{{ item.advanced_generation_enabled ? '已开启' : '未开启' }}</td>
                      <td class="px-4 py-3">
                        <span
                          class="rounded-full px-2 py-1 text-xs"
                          :class="item.allow_copy_export ? 'bg-[#ecfdf3] text-[#027a48]' : 'bg-[#fff7ed] text-[#c2410c]'"
                        >
                          {{ item.allow_copy_export ? '已开启' : '未开启' }}
                        </span>
                      </td>
                      <td class="px-4 py-3">
                        <span class="rounded-full px-2 py-1 text-xs" :class="statusBadgeClass(item.status)">
                          {{ item.status }}
                        </span>
                      </td>
                      <td class="flex flex-wrap gap-2 px-4 py-3">
                        <Button size="sm" variant="outline" class="rounded-xl" @click="rechargeAccessKey(item)">充值</Button>
                        <Button size="sm" variant="outline" class="rounded-xl" @click="toggleCopyExportPermission(item)">
                          {{ item.allow_copy_export ? '关闭复制导出' : '开启复制导出' }}
                        </Button>
                        <Button size="sm" variant="outline" class="rounded-xl" @click="toggleAccessKeyStatus(item)">
                          {{ item.status === 'active' ? '禁用' : '启用' }}
                        </Button>
                        <Button size="sm" variant="outline" class="rounded-xl border-[#fecaca] text-[#b42318] hover:bg-[#fef2f2]" @click="deleteAccessKey(item)">删除</Button>
                      </td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </article>
          </template>

          <template v-else-if="activeSection === '额度流水' || activeSection === '生成日志' || activeSection === '异常中心'">
            <article class="rounded-[24px] bg-white p-5 shadow-sm">
              <h2 class="text-lg font-semibold">{{ activeSection }}</h2>
              <p class="mt-2 text-sm text-[#667085]">
                {{ activeSection === '额度流水' ? '所有充值、扣费和补偿都会进这里。' : activeSection === '生成日志' ? '每次 AI 生成都会记录成本、模型和状态。' : '失败会翻译成人话，方便你判断该不该处理。' }}
              </p>
              <div class="mt-5 overflow-hidden rounded-2xl border border-[#edf2f7]">
                <table class="w-full text-left text-sm">
                  <thead class="bg-[#f8fbff] text-[#667085]">
                    <tr>
                      <th class="px-4 py-3">时间</th>
                      <th class="px-4 py-3">类型/功能</th>
                      <th class="px-4 py-3">金额/额度</th>
                      <th class="px-4 py-3">模型</th>
                      <th class="px-4 py-3">状态</th>
                      <th class="px-4 py-3">人话说明</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr
                      v-for="item in (activeSection === '额度流水' ? creditLedger : activeSection === '生成日志' ? generationLogs : exceptionItems)"
                      :key="item.id"
                      class="border-t border-[#edf2f7]"
                    >
                      <td class="px-4 py-3">{{ formatTime(item.created_at) }}</td>
                      <td class="px-4 py-3">
                        <div>{{ ledgerEventTypeLabel(item.event_type) }}</div>
                        <div class="mt-1 text-xs text-[#98a2b3]">{{ generationTypeLabel(item.generation_type) }}</div>
                      </td>
                      <td class="px-4 py-3">{{ item.amount }}</td>
                      <td class="px-4 py-3">{{ item.provider || '-' }} / {{ item.model || '-' }}</td>
                      <td class="px-4 py-3">{{ ledgerStatusLabel(item.status) }}</td>
                      <td class="px-4 py-3">{{ item.human_reason || '-' }}</td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </article>
          </template>

          <template v-else-if="activeSection === '科研生成链路'">
            <div class="space-y-5">
              <article class="rounded-[24px] bg-white p-5 shadow-sm">
                <div class="flex flex-wrap items-start justify-between gap-4">
                  <div>
                    <h2 class="text-lg font-semibold">科研生成链路</h2>
                    <p class="mt-2 max-w-2xl text-sm leading-6 text-[#667085]">
                      在这里指定每个模型的职务。API Key、Base URL 和模型列表复用 LLM 接口配置，用户侧只看到统一科研生成入口。
                    </p>
                  </div>
                  <div class="flex flex-wrap items-center gap-2">
                    <span class="rounded-full bg-[#eef7ff] px-3 py-1 text-xs text-[#2e8bd1]">
                      {{ advancedGenerationReadyRoles }}/{{ advancedRoleForms.length || 3 }} 个职务可调用
                    </span>
                    <span class="rounded-full bg-[#fff7ed] px-3 py-1 text-xs text-[#c2410c]">管理员授权</span>
                  </div>
                </div>

                <div class="mt-5 grid gap-3 lg:grid-cols-[0.8fr_1fr_auto]">
                  <label class="flex items-center justify-between rounded-2xl bg-[#f8fbff] px-4 py-3 text-sm">
                    <span>
                      <span class="block font-medium text-[#101828]">启用高级链路默认配置</span>
                      <span class="mt-1 block text-xs text-[#667085]">关闭后保留配置，但不作为默认链路展示。</span>
                    </span>
                    <button
                      type="button"
                      role="switch"
                      :aria-checked="advancedGenerationEnabled"
                      aria-label="启用高级链路默认配置"
                      class="relative h-7 w-12 rounded-full transition"
                      :class="advancedGenerationEnabled ? 'bg-[#16a34a]' : 'bg-[#d9e1ec]'"
                      @click="advancedGenerationEnabled = !advancedGenerationEnabled"
                    >
                      <span
                        class="absolute top-1 h-5 w-5 rounded-full bg-white shadow-sm transition"
                        :class="advancedGenerationEnabled ? 'left-6' : 'left-1'"
                      />
                    </button>
                  </label>
                  <label class="rounded-2xl bg-[#f8fbff] px-4 py-3 text-sm">
                    <span class="font-medium text-[#101828]">创作形态 ID</span>
                    <Input v-model="advancedGenerationProfileId" class="mt-2 rounded-2xl bg-white" placeholder="short_drama" />
                  </label>
                  <Button
                    class="h-full rounded-2xl bg-[#6656df] px-6 text-white hover:bg-[#5848cf]"
                    :disabled="advancedGenerationConfigSaving || !advancedRoleForms.length"
                    @click="saveAdvancedGenerationConfig"
                  >
                    {{ advancedGenerationConfigSaving ? '保存中...' : '保存链路' }}
                  </Button>
                </div>

                <div
                  v-if="advancedGenerationConfigMessage"
                  class="mt-4 flex items-center gap-2 rounded-2xl px-4 py-3 text-sm"
                  :class="advancedGenerationConfigMessageType === 'success'
                    ? 'bg-[#ecfdf5] text-[#047857]'
                    : 'bg-[#fef2f2] text-[#b42318]'"
                >
                  <CheckCircle2 v-if="advancedGenerationConfigMessageType === 'success'" class="h-4 w-4" />
                  <AlertTriangle v-else class="h-4 w-4" />
                  <span>{{ advancedGenerationConfigMessage }}</span>
                </div>
              </article>

              <div class="grid gap-5 xl:grid-cols-[1.25fr_0.75fr]">
                <article class="rounded-[24px] bg-white p-5 shadow-sm">
                  <div class="flex items-center justify-between">
                    <h3 class="font-semibold">模型职务分配</h3>
                    <span class="text-xs text-[#98a2b3]">Provider / Model / Temperature</span>
                  </div>

                  <div v-if="advancedRoleForms.length" class="mt-5 grid gap-4">
                    <div
                      v-for="role in advancedRoleForms"
                      :key="role.role"
                      class="rounded-[22px] border border-[#edf2f7] bg-[#f8fbff] p-4"
                    >
                      <div class="flex flex-wrap items-start justify-between gap-3">
                        <div>
                          <div class="flex items-center gap-2">
                            <Sparkles class="h-4 w-4 text-[#6656df]" />
                            <div class="font-medium text-[#101828]">{{ role.label }}</div>
                          </div>
                          <div class="mt-2 flex flex-wrap gap-2">
                            <span
                              v-for="step in role.steps"
                              :key="`${role.role}-${step}`"
                              class="rounded-full bg-white px-2.5 py-1 text-xs text-[#667085]"
                            >
                              {{ step }}
                            </span>
                          </div>
                        </div>
                        <div class="flex flex-wrap gap-2 text-xs">
                          <span
                            class="rounded-full px-2.5 py-1"
                            :class="role.has_api_key ? 'bg-[#ecfdf5] text-[#047857]' : 'bg-[#fff7ed] text-[#c2410c]'"
                          >
                            {{ role.has_api_key ? 'API 已配置' : 'API 未配置' }}
                          </span>
                          <span
                            class="rounded-full px-2.5 py-1"
                            :class="role.is_active ? 'bg-[#eef7ff] text-[#2e8bd1]' : 'bg-white text-[#98a2b3]'"
                          >
                            {{ role.is_active ? '当前启用供应商' : '备用供应商' }}
                          </span>
                        </div>
                      </div>

                      <div class="mt-4 grid gap-3 lg:grid-cols-[0.8fr_1fr_0.45fr]">
                        <label class="text-sm">
                          <span class="font-medium text-[#344054]">供应商</span>
                          <select
                            v-model="role.provider"
                            class="mt-2 h-11 w-full rounded-2xl border border-[#d0d5dd] bg-white px-3 text-sm outline-none focus:border-[#6656df]"
                            @change="syncAdvancedRoleProvider(role)"
                          >
                            <option v-for="provider in llmProviders" :key="`${role.role}-${provider.provider}`" :value="provider.provider">
                              {{ provider.display_name }}
                            </option>
                          </select>
                        </label>
                        <label class="text-sm">
                          <span class="font-medium text-[#344054]">具体模型</span>
                          <select
                            v-model="role.model"
                            class="mt-2 h-11 w-full rounded-2xl border border-[#d0d5dd] bg-white px-3 text-sm outline-none focus:border-[#6656df]"
                          >
                            <option
                              v-for="model in modelOptionsForProvider(role.provider, role.model)"
                              :key="`${role.role}-${role.provider}-${model}`"
                              :value="model"
                            >
                              {{ model }}
                            </option>
                          </select>
                        </label>
                        <label class="text-sm">
                          <span class="font-medium text-[#344054]">温度</span>
                          <Input v-model.number="role.temperature" class="mt-2 rounded-2xl bg-white" type="number" min="0" max="2" step="0.05" />
                        </label>
                      </div>

                      <label class="mt-3 block text-sm">
                        <span class="font-medium text-[#344054]">它负责什么职务</span>
                        <textarea
                          v-model="role.duty"
                          class="mt-2 min-h-20 w-full rounded-2xl border border-[#d0d5dd] bg-white px-3 py-2 text-sm leading-6 outline-none focus:border-[#6656df]"
                          placeholder="说明这个模型在科研生成链路里负责什么"
                        />
                      </label>
                    </div>
                  </div>

                  <div v-else class="mt-5 rounded-2xl bg-[#f8fbff] p-4 text-sm text-[#667085]">
                    正在读取科研生成链路配置。
                  </div>
                </article>

                <div class="space-y-5">
                  <article class="rounded-[24px] bg-white p-5 shadow-sm">
                    <div class="flex items-center justify-between gap-3">
                      <div>
                        <h3 class="font-semibold">API 接口配置状态</h3>
                        <p class="mt-2 text-sm leading-6 text-[#667085]">
                          每个职务选中的供应商都需要先配置 Base URL、API Key 和模型列表。
                        </p>
                      </div>
                      <Button variant="outline" class="rounded-2xl" @click="openProviderConfig()">
                        <Settings class="mr-2 h-4 w-4" />
                        打开接口配置
                      </Button>
                    </div>

                    <div class="mt-4 grid gap-3">
                      <div
                        v-for="provider in advancedGenerationApiProviders"
                        :key="`advanced-api-${provider.provider}`"
                        class="rounded-2xl border border-[#edf2f7] bg-[#f8fbff] p-4"
                      >
                        <div class="flex items-start justify-between gap-3">
                          <div>
                            <div class="font-medium text-[#101828]">{{ provider.display_name }}</div>
                            <div class="mt-1 text-xs text-[#667085]">{{ provider.default_model || '未设置默认模型' }}</div>
                          </div>
                          <span
                            class="rounded-full px-2.5 py-1 text-xs"
                            :class="provider.has_api_key ? 'bg-[#ecfdf5] text-[#047857]' : 'bg-[#fff7ed] text-[#c2410c]'"
                          >
                            {{ provider.has_api_key ? 'Key 已填' : 'Key 未填' }}
                          </span>
                        </div>
                        <div class="mt-3 space-y-1 text-xs text-[#667085]">
                          <div>Base URL：{{ provider.base_url || '未填写' }}</div>
                          <div>API Key：{{ provider.has_api_key ? provider.api_key_masked : '未填写' }}</div>
                          <div>模型数量：{{ provider.models.length }}</div>
                        </div>
                        <Button variant="outline" size="sm" class="mt-3 rounded-2xl" @click="openProviderConfig(provider.provider)">
                          配置 {{ provider.display_name }}
                        </Button>
                      </div>
                    </div>
                  </article>

                  <article class="rounded-[24px] bg-white p-5 shadow-sm">
                    <h3 class="font-semibold">生效说明</h3>
                    <div class="mt-4 space-y-3 text-sm leading-6 text-[#667085]">
                      <p>链路保存的是默认模型分工：规划、执笔、评审各自绑定一个供应商和模型。</p>
                      <p>前台用户仍由密钥控制科研生成权限；API Key 不会暴露给前台。</p>
                      <p>如果某个职务显示 API 未配置，先到接口配置页补 Key，再回来保存链路。</p>
                    </div>
                  </article>
                </div>
              </div>
            </div>
          </template>

          <template v-else-if="activeSection === 'Skill封装'">
            <div class="flex flex-wrap items-center justify-between gap-3">
              <div>
                <h2 class="text-lg font-semibold">Skill 数据库封装</h2>
                <p class="mt-2 text-sm text-[#667085]">目录、绑定、调用记录和产物都从数据库读取，后台只做治理入口。</p>
              </div>
              <div class="flex flex-wrap gap-2">
                <Button variant="outline" class="rounded-2xl" :disabled="skillLoading" @click="loadSkillWorkflowData">
                  <RefreshCw class="mr-2 h-4 w-4" />
                  刷新
                </Button>
                <Button class="rounded-2xl bg-[#6656df] text-white hover:bg-[#5848cf]" :disabled="skillLoading" @click="syncSkillCatalog">
                  <PackageCheck class="mr-2 h-4 w-4" />
                  同步目录
                </Button>
              </div>
            </div>

            <div class="grid gap-4 md:grid-cols-4">
              <article class="rounded-[22px] bg-white p-5 shadow-sm">
                <div class="text-sm text-[#667085]">Skill 目录</div>
                <div class="mt-3 text-2xl font-semibold">{{ skillStats.catalog }}</div>
                <div class="mt-2 text-xs text-[#98a2b3]">来自 manifest 同步后的数据库事实源</div>
              </article>
              <article class="rounded-[22px] bg-white p-5 shadow-sm">
                <div class="text-sm text-[#667085]">启用绑定</div>
                <div class="mt-3 text-2xl font-semibold">{{ skillStats.enabledBindings }}</div>
                <div class="mt-2 text-xs text-[#98a2b3]">按失败类型、步骤或上下文触发</div>
              </article>
              <article class="rounded-[22px] bg-white p-5 shadow-sm">
                <div class="text-sm text-[#667085]">进行中调用</div>
                <div class="mt-3 text-2xl font-semibold">{{ skillStats.startedInvocations }}</div>
                <div class="mt-2 text-xs text-[#98a2b3]">用于审计当前人工/系统动作</div>
              </article>
              <article class="rounded-[22px] bg-white p-5 shadow-sm">
                <div class="text-sm text-[#667085]">产物记录</div>
                <div class="mt-3 text-2xl font-semibold">{{ skillStats.artifacts }}</div>
                <div class="mt-2 text-xs text-[#98a2b3]">保存路径、摘要和文本产物</div>
              </article>
              <article class="rounded-[22px] bg-white p-5 shadow-sm">
                <div class="text-sm text-[#667085]">质量反馈</div>
                <div class="mt-3 text-2xl font-semibold">{{ skillStats.feedback }}</div>
                <div class="mt-2 text-xs text-[#98a2b3]">人工或系统对调用效果打分</div>
              </article>
            </div>

            <div class="grid gap-5 xl:grid-cols-[0.75fr_1.25fr]">
              <article class="rounded-[24px] bg-white p-5 shadow-sm">
                <div class="flex items-center justify-between">
                  <h2 class="text-lg font-semibold">质量反馈聚合</h2>
                  <span class="rounded-full bg-[#eef7ff] px-3 py-1 text-xs text-[#2e8bd1]">
                    {{ skillFeedbackSummary?.skill_count || 0 }} 个 Skill
                  </span>
                </div>
                <div class="mt-5 grid grid-cols-2 gap-3">
                  <div class="rounded-2xl bg-[#f8fbff] p-4">
                    <div class="text-xs text-[#667085]">反馈总数</div>
                    <div class="mt-2 text-2xl font-semibold">{{ skillFeedbackSummary?.total_feedback_count || 0 }}</div>
                  </div>
                  <div class="rounded-2xl bg-[#f8fbff] p-4">
                    <div class="text-xs text-[#667085]">平均分</div>
                    <div class="mt-2 text-2xl font-semibold">{{ skillFeedbackSummary?.average_score || 0 }}</div>
                  </div>
                </div>
                <div class="mt-4 flex flex-wrap gap-2 text-xs">
                  <span v-for="(count, verdict) in skillFeedbackVerdictCounts" :key="verdict" class="rounded-full bg-[#f3f7fb] px-3 py-1 text-[#667085]">
                    {{ skillVerdictLabel(String(verdict)) }} · {{ count }}
                  </span>
                </div>
              </article>

              <article class="rounded-[24px] bg-white p-5 shadow-sm">
                <div class="mb-4 flex items-center justify-between">
                  <h2 class="text-lg font-semibold">绑定优先级建议</h2>
                  <span class="rounded-full bg-[#f3f7fb] px-3 py-1 text-xs text-[#667085]">只读建议</span>
                </div>
                <div class="overflow-hidden rounded-2xl border border-[#edf2f7]">
                  <table class="w-full text-left text-sm">
                    <thead class="bg-[#f8fbff] text-[#667085]">
                      <tr>
                        <th class="px-4 py-3">Skill</th>
                        <th class="px-4 py-3">样本</th>
                        <th class="px-4 py-3">均分</th>
                        <th class="px-4 py-3">建议</th>
                        <th class="px-4 py-3">绑定范围</th>
                      </tr>
                    </thead>
                    <tbody>
                      <tr v-for="item in skillFeedbackSummaryItems" :key="item.skill_name" class="border-t border-[#edf2f7]">
                        <td class="px-4 py-3">{{ item.skill_name }}</td>
                        <td class="px-4 py-3">{{ item.feedback_count }}</td>
                        <td class="px-4 py-3">{{ item.average_score }}</td>
                        <td class="px-4 py-3">
                          <div class="font-medium">{{ item.binding_priority_hint.action }}</div>
                          <div class="mt-1 text-xs text-[#98a2b3]">{{ item.binding_priority_hint.reason }}</div>
                        </td>
                        <td class="px-4 py-3">
                          {{ skillBindingTypeLabel(item.binding_priority_hint.binding_type) }}
                          <span v-if="item.binding_priority_hint.binding_key"> · {{ skillBindingKeyLabel(item.binding_priority_hint.binding_key) }}</span>
                        </td>
                      </tr>
                      <tr v-if="!skillFeedbackSummaryItems.length">
                        <td colspan="5" class="px-4 py-6 text-center text-[#98a2b3]">暂无可聚合反馈</td>
                      </tr>
                    </tbody>
                  </table>
                </div>
              </article>
            </div>

            <div class="grid gap-5 xl:grid-cols-[0.85fr_1.15fr]">
              <article class="rounded-[24px] bg-white p-5 shadow-sm">
                <div class="mb-4 flex items-center justify-between">
                  <h2 class="text-lg font-semibold">创建 Skill 绑定</h2>
                  <Workflow class="h-5 w-5 text-[#6656df]" />
                </div>
                <div class="grid gap-3">
                  <select v-model="skillBindingForm.skill_name" class="h-11 rounded-2xl border border-[#d0d5dd] bg-white px-3 text-sm outline-none focus:border-[#6656df]">
                    <option value="">选择 Skill</option>
                    <option v-for="skill in skillCatalog" :key="skill.id" :value="skill.name">
                      {{ skill.display_name || skill.name }}
                    </option>
                  </select>
                  <div class="grid gap-3 md:grid-cols-3">
                    <select v-model="skillBindingForm.binding_type" class="h-11 rounded-2xl border border-[#d0d5dd] bg-white px-3 text-sm outline-none focus:border-[#6656df]">
                      <option v-for="item in skillBindingTypes" :key="item.value" :value="item.value">
                        {{ item.label }}
                      </option>
                    </select>
                    <Input v-model="skillBindingForm.binding_key" class="h-11 rounded-2xl" :disabled="skillBindingForm.binding_type === 'global'" placeholder="绑定键，例如：格式错误 / format_break" />
                    <Input v-model.number="skillBindingForm.priority" class="h-11 rounded-2xl" type="number" min="0" placeholder="优先级" />
                  </div>
                  <textarea v-model="skillBindingForm.config_text" class="min-h-24 rounded-2xl border border-[#d0d5dd] bg-white px-3 py-2 font-mono text-xs outline-none focus:border-[#6656df]" placeholder="config JSON" />
                  <textarea v-model="skillBindingForm.metadata_text" class="min-h-20 rounded-2xl border border-[#d0d5dd] bg-white px-3 py-2 font-mono text-xs outline-none focus:border-[#6656df]" placeholder="metadata JSON" />
                  <label class="flex items-center justify-between rounded-2xl bg-[#f8fbff] px-4 py-3 text-sm">
                    <span>创建后立即启用</span>
                    <input v-model="skillBindingForm.is_enabled" type="checkbox" class="h-4 w-4 accent-[#6656df]" />
                  </label>
                  <Button class="h-11 rounded-2xl bg-[#6656df] text-white hover:bg-[#5848cf]" :disabled="savingSkillBinding" @click="createSkillBinding">
                    {{ savingSkillBinding ? '保存中...' : '保存绑定' }}
                  </Button>
                </div>
              </article>

              <article class="rounded-[24px] bg-white p-5 shadow-sm">
                <div class="mb-4 flex items-center justify-between">
                  <h2 class="text-lg font-semibold">绑定列表</h2>
                  <span class="rounded-full bg-[#eef7ff] px-3 py-1 text-xs text-[#2e8bd1]">{{ skillBindings.length }} 条</span>
                </div>
                <div class="overflow-hidden rounded-2xl border border-[#edf2f7]">
                  <table class="w-full text-left text-sm">
                    <thead class="bg-[#f8fbff] text-[#667085]">
                      <tr>
                        <th class="px-4 py-3">Skill</th>
                        <th class="px-4 py-3">绑定</th>
                        <th class="px-4 py-3">优先级</th>
                        <th class="px-4 py-3">状态</th>
                        <th class="px-4 py-3">操作</th>
                      </tr>
                    </thead>
                    <tbody>
                      <tr v-for="item in skillBindings" :key="item.id" class="border-t border-[#edf2f7]">
                        <td class="px-4 py-3">
                          <div class="font-medium">{{ item.skill_name }}</div>
                          <div class="mt-1 max-w-[260px] truncate font-mono text-xs text-[#98a2b3]">{{ formatCompactJson(item.config) }}</div>
                        </td>
                        <td class="px-4 py-3">
                          <div>{{ skillBindingTypeLabel(item.binding_type) }}</div>
                          <div class="mt-1 text-xs text-[#98a2b3]">{{ skillBindingKeyLabel(item.binding_key) }}</div>
                        </td>
                        <td class="px-4 py-3">{{ item.priority }}</td>
                        <td class="px-4 py-3">
                          <span class="rounded-full px-2 py-1 text-xs" :class="item.is_enabled && item.status === 'active' ? 'bg-[#ecfdf5] text-[#047857]' : 'bg-[#f3f7fb] text-[#667085]'">
                            {{ item.is_enabled && item.status === 'active' ? '启用' : skillStatusLabel(item.status) }}
                          </span>
                        </td>
                        <td class="px-4 py-3">
                          <div class="flex flex-wrap gap-2">
                            <Button size="sm" variant="outline" class="rounded-xl" @click="toggleSkillBinding(item)">
                            {{ item.is_enabled ? '停用' : '启用' }}
                            </Button>
                            <Button size="sm" variant="outline" class="rounded-xl" @click="archiveSkillBinding(item)">
                              归档
                            </Button>
                          </div>
                        </td>
                      </tr>
                      <tr v-if="!skillBindings.length">
                        <td colspan="5" class="px-4 py-6 text-center text-[#98a2b3]">暂无 Skill 绑定</td>
                      </tr>
                    </tbody>
                  </table>
                </div>
              </article>
            </div>

            <div class="grid gap-5 xl:grid-cols-[0.9fr_1.1fr]">
              <article class="rounded-[24px] bg-white p-5 shadow-sm">
                <h2 class="text-lg font-semibold">推荐预览</h2>
                <p class="mt-2 text-sm text-[#667085]">输入失败类型后，可看到数据库绑定如何注入推荐链路。</p>
                <div class="mt-4 grid gap-3 md:grid-cols-[1fr_1fr_auto]">
                  <Input v-model="skillRecommendForm.failure_type" class="h-11 rounded-2xl" placeholder="失败类型，例如：format_break" />
                  <Input v-model="skillRecommendForm.context" class="h-11 rounded-2xl" placeholder="context" />
                  <Button class="h-11 rounded-2xl bg-[#6656df] text-white hover:bg-[#5848cf]" @click="previewSkillRecommendation">
                    <PlayCircle class="mr-2 h-4 w-4" />
                    预览
                  </Button>
                </div>
                <div v-if="skillRecommendation" class="mt-4 rounded-2xl bg-[#f8fbff] p-4">
                  <div class="flex flex-wrap gap-2 text-xs">
                    <span class="rounded-full bg-white px-3 py-1 text-[#667085]">{{ skillRecommendation.catalog_source }}</span>
                    <span class="rounded-full bg-white px-3 py-1 text-[#667085]">{{ skillBindingKeyLabel(skillRecommendation.failure_type) }}</span>
                    <span class="rounded-full bg-white px-3 py-1 text-[#667085]">{{ skillRecommendation.matched_bindings.length }} 条绑定</span>
                  </div>
                  <div class="mt-4 grid gap-2">
                    <div v-for="name in recommendedSkillNames" :key="name" class="rounded-xl bg-white px-3 py-2 text-sm">
                      {{ name }}
                    </div>
                  </div>
                  <div class="mt-4 space-y-2 text-sm text-[#344054]">
                    <div v-for="action in skillRecommendation.next_actions" :key="action" class="leading-6">
                      {{ action }}
                    </div>
                  </div>
                </div>
              </article>

              <article class="rounded-[24px] bg-white p-5 shadow-sm">
                <h2 class="text-lg font-semibold">内部编排 worker</h2>
                <p class="mt-2 text-sm text-[#667085]">生成可审计的调用记录和执行计划产物，不执行任意本地脚本。</p>
                <div class="mt-4 grid gap-3">
                  <div class="grid gap-3 md:grid-cols-[1fr_1fr_120px]">
                    <Input v-model="skillWorkerForm.failure_type" class="h-11 rounded-2xl" placeholder="失败类型，例如：format_break" />
                    <Input v-model="skillWorkerForm.context" class="h-11 rounded-2xl" placeholder="context" />
                    <Input v-model.number="skillWorkerForm.max_skills" class="h-11 rounded-2xl" type="number" min="1" max="10" placeholder="数量" />
                  </div>
                  <Button class="h-11 rounded-2xl bg-[#6656df] text-white hover:bg-[#5848cf]" :disabled="runningSkillWorker" @click="runSkillWorker">
                    <PlayCircle class="mr-2 h-4 w-4" />
                    {{ runningSkillWorker ? '运行中...' : '运行 worker' }}
                  </Button>
                </div>
              </article>
            </div>

            <div class="grid gap-5 xl:grid-cols-[0.9fr_1.1fr]">
              <article class="rounded-[24px] bg-white p-5 shadow-sm">
                <h2 class="text-lg font-semibold">记录 Skill 调用</h2>
                <div class="mt-4 grid gap-3">
                  <select v-model="skillInvocationForm.skill_name" class="h-11 rounded-2xl border border-[#d0d5dd] bg-white px-3 text-sm outline-none focus:border-[#6656df]">
                    <option value="">选择 Skill</option>
                    <option v-for="skill in skillCatalog" :key="skill.id" :value="skill.name">
                      {{ skill.display_name || skill.name }}
                    </option>
                  </select>
                  <select v-model="skillInvocationForm.binding_id" class="h-11 rounded-2xl border border-[#d0d5dd] bg-white px-3 text-sm outline-none focus:border-[#6656df]">
                    <option value="">不绑定具体策略</option>
                    <option v-for="item in skillBindings" :key="item.id" :value="item.id">
                      {{ item.skill_name }} · {{ skillBindingTypeLabel(item.binding_type) }} · {{ skillBindingKeyLabel(item.binding_key) }}
                    </option>
                  </select>
                  <div class="grid gap-3 md:grid-cols-2">
                    <Input v-model="skillInvocationForm.context" class="h-11 rounded-2xl" placeholder="使用场景，例如：后台管理" />
                    <Input v-model="skillInvocationForm.failure_type" class="h-11 rounded-2xl" placeholder="失败类型，例如：format_break" />
                  </div>
                  <textarea v-model="skillInvocationForm.input_summary" class="min-h-24 rounded-2xl border border-[#d0d5dd] bg-white px-3 py-2 text-sm outline-none focus:border-[#6656df]" placeholder="输入摘要" />
                  <Button class="h-11 rounded-2xl bg-[#6656df] text-white hover:bg-[#5848cf]" :disabled="startingSkillInvocation" @click="startSkillInvocation">
                    {{ startingSkillInvocation ? '记录中...' : '开始记录调用' }}
                  </Button>
                </div>
              </article>

              <article class="rounded-[24px] bg-white p-5 shadow-sm">
                <h2 class="text-lg font-semibold">记录质量反馈</h2>
                <div class="mt-4 grid gap-3">
                  <select v-model="skillFeedbackForm.invocation_id" class="h-11 rounded-2xl border border-[#d0d5dd] bg-white px-3 text-sm outline-none focus:border-[#6656df]">
                    <option value="">选择调用记录</option>
                    <option v-for="item in skillInvocations" :key="item.id" :value="item.id">
                      {{ item.skill_name }} · {{ formatTime(item.created_at) }} · {{ skillStatusLabel(item.status) }}
                    </option>
                  </select>
                  <div class="grid gap-3 md:grid-cols-2">
                    <Input v-model.number="skillFeedbackForm.score" class="h-11 rounded-2xl" type="number" min="0" max="100" placeholder="评分 0-100" />
                    <select v-model="skillFeedbackForm.verdict" class="h-11 rounded-2xl border border-[#d0d5dd] bg-white px-3 text-sm outline-none focus:border-[#6656df]">
                      <option value="pending_review">待复核</option>
                      <option value="useful">有用</option>
                      <option value="not_useful">无效</option>
                      <option value="needs_followup">需跟进</option>
                      <option value="blocked">阻塞</option>
                    </select>
                  </div>
                  <textarea v-model="skillFeedbackForm.notes" class="min-h-24 rounded-2xl border border-[#d0d5dd] bg-white px-3 py-2 text-sm outline-none focus:border-[#6656df]" placeholder="反馈说明" />
                  <Button class="h-11 rounded-2xl bg-[#6656df] text-white hover:bg-[#5848cf]" :disabled="savingSkillFeedback" @click="createSkillFeedback">
                    {{ savingSkillFeedback ? '记录中...' : '记录反馈' }}
                  </Button>
                </div>
              </article>
            </div>

            <article class="rounded-[24px] bg-white p-5 shadow-sm">
              <div class="mb-4 flex items-center justify-between">
                <h2 class="text-lg font-semibold">调用历史</h2>
                <span class="rounded-full bg-[#f3f7fb] px-3 py-1 text-xs text-[#667085]">{{ skillInvocations.length }} 条</span>
              </div>
              <div class="overflow-hidden rounded-2xl border border-[#edf2f7]">
                <table class="w-full text-left text-sm">
                  <thead class="bg-[#f8fbff] text-[#667085]">
                    <tr>
                      <th class="px-4 py-3">时间</th>
                      <th class="px-4 py-3">Skill</th>
                      <th class="px-4 py-3">上下文</th>
                      <th class="px-4 py-3">状态</th>
                      <th class="px-4 py-3">摘要</th>
                      <th class="px-4 py-3">操作</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr v-for="item in skillInvocations" :key="item.id" class="border-t border-[#edf2f7]">
                      <td class="px-4 py-3">{{ formatTime(item.created_at) }}</td>
                      <td class="px-4 py-3">
                        <div class="font-medium">{{ item.skill_name }}</div>
                        <div class="font-mono text-xs text-[#98a2b3]">{{ item.binding_id || '无绑定' }}</div>
                      </td>
                      <td class="px-4 py-3">
                        <div>{{ item.context || '后台管理' }}</div>
                        <div class="text-xs text-[#98a2b3]">{{ skillBindingKeyLabel(item.failure_type) }}</div>
                      </td>
                      <td class="px-4 py-3">{{ skillStatusLabel(item.status) }}</td>
                      <td class="max-w-sm px-4 py-3">
                        <div class="line-clamp-2">{{ item.output_summary || item.input_summary || '-' }}</div>
                      </td>
                      <td class="px-4 py-3">
                        <div class="flex flex-wrap gap-2">
                          <Button size="sm" variant="outline" class="rounded-xl" :disabled="item.status !== 'started'" @click="finishSkillInvocation(item, 'success')">
                            完成
                          </Button>
                          <Button size="sm" variant="outline" class="rounded-xl" :disabled="item.status !== 'started'" @click="finishSkillInvocation(item, 'failed')">
                            失败
                          </Button>
                        </div>
                      </td>
                    </tr>
                    <tr v-if="!skillInvocations.length">
                      <td colspan="6" class="px-4 py-6 text-center text-[#98a2b3]">暂无 Skill 调用记录</td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </article>

            <div class="grid gap-5 xl:grid-cols-[0.85fr_1.15fr]">
              <article class="rounded-[24px] bg-white p-5 shadow-sm">
                <h2 class="text-lg font-semibold">记录调用产物</h2>
                <div class="mt-4 grid gap-3">
                  <select v-model="skillArtifactForm.invocation_id" class="h-11 rounded-2xl border border-[#d0d5dd] bg-white px-3 text-sm outline-none focus:border-[#6656df]">
                    <option value="">选择调用记录</option>
                    <option v-for="item in skillInvocations" :key="item.id" :value="item.id">
                      {{ item.skill_name }} · {{ formatTime(item.created_at) }} · {{ skillStatusLabel(item.status) }}
                    </option>
                  </select>
                  <div class="grid gap-3 md:grid-cols-2">
                    <Input v-model="skillArtifactForm.artifact_type" class="h-11 rounded-2xl" placeholder="产物类型，例如：markdown" />
                    <Input v-model="skillArtifactForm.title" class="h-11 rounded-2xl" placeholder="标题" />
                  </div>
                  <Input v-model="skillArtifactForm.path" class="h-11 rounded-2xl" placeholder="文件路径，可留空" />
                  <textarea v-model="skillArtifactForm.content" class="min-h-28 rounded-2xl border border-[#d0d5dd] bg-white px-3 py-2 text-sm outline-none focus:border-[#6656df]" placeholder="产物摘要或内容" />
                  <Button class="h-11 rounded-2xl bg-[#6656df] text-white hover:bg-[#5848cf]" :disabled="savingSkillArtifact" @click="createSkillArtifact">
                    {{ savingSkillArtifact ? '记录中...' : '记录产物' }}
                  </Button>
                </div>
              </article>

              <article class="rounded-[24px] bg-white p-5 shadow-sm">
                <div class="mb-4 flex items-center justify-between">
                  <h2 class="text-lg font-semibold">产物列表</h2>
                  <span class="rounded-full bg-[#eef7ff] px-3 py-1 text-xs text-[#2e8bd1]">{{ skillArtifacts.length }} 个</span>
                </div>
                <div class="space-y-3">
                  <div v-for="item in skillArtifacts" :key="item.id" class="rounded-2xl border border-[#edf2f7] bg-[#f8fbff] p-4">
                    <div class="flex items-start justify-between gap-3">
                      <div>
                        <div class="font-semibold">{{ item.title || item.artifact_type }}</div>
                        <div class="mt-1 font-mono text-xs text-[#98a2b3]">{{ item.skill_name }} · {{ item.artifact_type }}</div>
                      </div>
                      <span class="rounded-full bg-white px-2 py-1 text-xs text-[#667085]">{{ formatTime(item.created_at) }}</span>
                    </div>
                    <p class="mt-3 line-clamp-3 text-sm leading-6 text-[#344054]">{{ item.content || item.path || '无内容' }}</p>
                    <div v-if="item.path" class="mt-2 break-all font-mono text-xs text-[#98a2b3]">{{ item.path }}</div>
                  </div>
                  <div v-if="!skillArtifacts.length" class="rounded-2xl border border-dashed border-[#d0d5dd] p-6 text-sm text-[#667085]">
                    暂无 Skill 产物记录。
                  </div>
                </div>
              </article>
            </div>

            <article class="rounded-[24px] bg-white p-5 shadow-sm">
              <div class="mb-4 flex items-center justify-between">
                <h2 class="text-lg font-semibold">质量反馈列表</h2>
                <span class="rounded-full bg-[#f3f7fb] px-3 py-1 text-xs text-[#667085]">{{ skillFeedback.length }} 条</span>
              </div>
              <div class="overflow-hidden rounded-2xl border border-[#edf2f7]">
                <table class="w-full text-left text-sm">
                  <thead class="bg-[#f8fbff] text-[#667085]">
                    <tr>
                      <th class="px-4 py-3">时间</th>
                      <th class="px-4 py-3">Skill</th>
                      <th class="px-4 py-3">评分</th>
                      <th class="px-4 py-3">结论</th>
                      <th class="px-4 py-3">说明</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr v-for="item in skillFeedback" :key="item.id" class="border-t border-[#edf2f7]">
                      <td class="px-4 py-3">{{ formatTime(item.created_at) }}</td>
                      <td class="px-4 py-3">{{ item.skill_name }}</td>
                      <td class="px-4 py-3">{{ item.score }}</td>
                      <td class="px-4 py-3">{{ skillVerdictLabel(item.verdict) }}</td>
                      <td class="px-4 py-3">{{ item.notes || '-' }}</td>
                    </tr>
                    <tr v-if="!skillFeedback.length">
                      <td colspan="5" class="px-4 py-6 text-center text-[#98a2b3]">暂无质量反馈</td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </article>
          </template>

          <template v-else-if="activeSection === '注册用户框架'">
            <div class="grid gap-5 xl:grid-cols-[0.85fr_1.15fr]">
              <article class="rounded-[24px] bg-white p-5 shadow-sm">
                <h2 class="text-lg font-semibold">生成邀请码</h2>
                <p class="mt-2 text-sm text-[#667085]">邀请码先用于内测发放，后续可升级为正式注册入口。</p>
                <div class="mt-5 space-y-4">
                  <Input v-model="inviteBatchName" class="h-11 rounded-2xl" placeholder="批次名称" />
                  <Input v-model.number="inviteCount" class="h-11 rounded-2xl" type="number" min="1" max="100" placeholder="生成数量" />
                  <Input v-model="inviteAssignedTo" class="h-11 rounded-2xl" placeholder="预分配对象，可留空" />
                  <Input v-model="inviteNote" class="h-11 rounded-2xl" placeholder="备注" />
                  <Button class="h-11 w-full rounded-2xl bg-[#6656df] text-white hover:bg-[#5848cf]" @click="createInviteCodes">
                    批量生成邀请码
                  </Button>
                </div>
              </article>

              <article class="rounded-[24px] bg-white p-5 shadow-sm">
                <h2 class="text-lg font-semibold">本次生成</h2>
                <div v-if="latestInviteCodes.length" class="mt-4 space-y-3">
                  <div
                    v-for="item in latestInviteCodes"
                    :key="item.invite_id"
                    class="flex items-center justify-between gap-3 rounded-2xl border border-[#dbeafe] bg-[#eff6ff] px-4 py-3"
                  >
                    <div>
                      <div class="font-mono text-sm">{{ item.plain_code }}</div>
                      <div class="mt-1 text-xs text-[#667085]">{{ item.batch_name }} · {{ item.note || '无备注' }}</div>
                    </div>
                    <button class="text-[#2e8bd1]" @click="copyInviteCode(item.plain_code)">
                      <Copy class="h-4 w-4" />
                    </button>
                  </div>
                </div>
                <div v-else class="mt-4 rounded-2xl border border-dashed border-[#d0d5dd] p-6 text-sm text-[#667085]">
                  邀请码明文只在生成后显示一次，列表中只保留前缀和状态。
                </div>
              </article>
            </div>

            <article class="rounded-[24px] bg-white p-5 shadow-sm">
              <div class="mb-4 flex items-center justify-between">
                <h2 class="text-lg font-semibold">邀请码池</h2>
                <span class="rounded-full bg-[#eef7ff] px-3 py-1 text-xs text-[#2e8bd1]">
                  {{ inviteCodes.length }} 个
                </span>
              </div>
              <div class="overflow-hidden rounded-2xl border border-[#edf2f7]">
                <table class="w-full text-left text-sm">
                  <thead class="bg-[#f8fbff] text-[#667085]">
                    <tr>
                      <th class="px-4 py-3">批次</th>
                      <th class="px-4 py-3">邀请码前缀</th>
                      <th class="px-4 py-3">使用</th>
                      <th class="px-4 py-3">状态</th>
                      <th class="px-4 py-3">备注</th>
                      <th class="px-4 py-3">操作</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr v-for="item in inviteCodes" :key="item.invite_id" class="border-t border-[#edf2f7]">
                      <td class="px-4 py-3">{{ item.batch_name }}</td>
                      <td class="px-4 py-3 font-mono text-xs">{{ item.code_prefix }}</td>
                      <td class="px-4 py-3">{{ item.used_count }} / {{ item.max_uses }}</td>
                      <td class="px-4 py-3">{{ item.status }}</td>
                      <td class="px-4 py-3">{{ item.note || '-' }}</td>
                      <td class="px-4 py-3">
                        <Button
                          size="sm"
                          variant="outline"
                          class="rounded-xl"
                          :disabled="item.status === 'disabled'"
                          @click="disableInviteCode(item)"
                        >
                          停用
                        </Button>
                      </td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </article>

            <div class="grid gap-5 xl:grid-cols-[0.85fr_1.15fr]">
              <article class="rounded-[24px] bg-white p-5 shadow-sm">
                <div class="mb-4 flex items-center justify-between">
                  <div>
                    <h2 class="text-lg font-semibold">注册用户管理</h2>
                    <p class="mt-2 text-sm text-[#667085]">用户可通过邀请码注册，也可由后台预设账号后直接登录。</p>
                  </div>
                  <UserPlus class="h-5 w-5 text-[#6656df]" />
                </div>
                <div class="grid gap-3">
                  <Input v-model="frontUserForm.username" class="h-11 rounded-2xl" placeholder="用户名" />
                  <Input v-model="frontUserForm.password" class="h-11 rounded-2xl" type="password" placeholder="初始密码，至少 6 位" />
                  <div class="grid gap-3 md:grid-cols-2">
                    <Input v-model="frontUserForm.email" class="h-11 rounded-2xl" placeholder="邮箱，可选" />
                    <Input v-model="frontUserForm.phone" class="h-11 rounded-2xl" placeholder="手机号，可选" />
                    <Input v-model.number="frontUserForm.initial_credit" class="h-11 rounded-2xl" type="number" min="0" placeholder="初始额度" />
                    <label class="flex h-11 items-center justify-between rounded-2xl bg-[#f8fbff] px-4 text-sm">
                      <span>开通科研生成</span>
                      <input v-model="frontUserForm.advanced_generation_enabled" type="checkbox" class="h-4 w-4 accent-[#6656df]" />
                    </label>
                  </div>
                  <Input v-model="frontUserForm.note" class="h-11 rounded-2xl" placeholder="备注" />
                  <div class="grid gap-3 sm:grid-cols-2">
                    <Button class="h-11 rounded-2xl bg-[#6656df] text-white hover:bg-[#5848cf]" :disabled="creatingFrontUser" @click="createFrontUser">
                      {{ creatingFrontUser ? '创建中...' : '创建注册用户' }}
                    </Button>
                    <Button variant="outline" class="h-11 rounded-2xl" @click="seedDefaultFrontUsers">
                      生成默认用户
                    </Button>
                  </div>
                </div>
              </article>

              <article class="rounded-[24px] bg-white p-5 shadow-sm">
                <h2 class="text-lg font-semibold">最近生成的用户登录信息</h2>
                <div v-if="latestSeedUsers.length" class="mt-4 space-y-3">
                  <div
                    v-for="item in latestSeedUsers"
                    :key="item.user_id"
                    class="rounded-2xl border border-[#dbeafe] bg-[#eff6ff] px-4 py-3"
                  >
                    <div class="flex items-start justify-between gap-3">
                      <div class="min-w-0">
                        <div class="font-semibold">{{ item.username }}</div>
                        <div class="mt-1 break-all font-mono text-xs text-[#344054]">
                          {{ item.plain_password ? `密码 ${item.plain_password}` : '已存在用户，密码不会再次显示' }}
                        </div>
                        <div v-if="item.plain_key" class="mt-1 break-all font-mono text-xs text-[#344054]">
                          {{ item.plain_key }}
                        </div>
                      </div>
                      <button class="text-[#2e8bd1]" :disabled="!item.plain_password && !item.plain_key" @click="copyFrontUserCredential(item)">
                        <Copy class="h-4 w-4" />
                      </button>
                    </div>
                  </div>
                </div>
                <div v-else class="mt-4 rounded-2xl border border-dashed border-[#d0d5dd] p-6 text-sm text-[#667085]">
                  后台创建或生成默认用户后，会在这里显示一次密码和使用密钥。
                </div>
              </article>
            </div>

            <article class="rounded-[24px] bg-white p-5 shadow-sm">
              <div class="mb-4 flex flex-wrap items-center justify-between gap-3">
                <div>
                  <h2 class="text-lg font-semibold">注册用户列表</h2>
                  <div class="mt-2 flex flex-wrap gap-2 text-xs">
                    <span class="rounded-full bg-[#eef7ff] px-3 py-1 text-[#2e8bd1]">{{ frontUsers.length }} 个用户</span>
                    <span class="rounded-full bg-[#ecfdf5] px-3 py-1 text-[#047857]">启用 {{ frontUserStats.active }}</span>
                    <span class="rounded-full bg-[#fff7ed] px-3 py-1 text-[#c2410c]">停用 {{ frontUserStats.disabled }}</span>
                  </div>
                </div>
                <Input v-model="frontUserSearchKeyword" class="h-10 max-w-xs rounded-2xl" placeholder="搜索用户 / 邮箱 / 手机 / 密钥" />
              </div>
              <div class="overflow-hidden rounded-2xl border border-[#edf2f7]">
                <table class="w-full text-left text-sm">
                  <thead class="bg-[#f8fbff] text-[#667085]">
                    <tr>
                      <th class="px-4 py-3">用户</th>
                      <th class="px-4 py-3">联系方式</th>
                      <th class="px-4 py-3">额度</th>
                      <th class="px-4 py-3">状态</th>
                      <th class="px-4 py-3">创建时间</th>
                      <th class="px-4 py-3">操作</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr v-for="item in filteredFrontUsers" :key="item.user_id" class="border-t border-[#edf2f7]">
                      <td class="px-4 py-3">
                        <div class="font-medium">{{ item.username }}</div>
                        <div class="mt-1 font-mono text-xs text-[#98a2b3]">{{ item.key_prefix || '未绑定密钥' }}</div>
                      </td>
                      <td class="px-4 py-3">
                        <div>{{ item.email || '-' }}</div>
                        <div class="mt-1 text-xs text-[#98a2b3]">{{ item.phone || '-' }}</div>
                      </td>
                      <td class="px-4 py-3">{{ item.credit_balance }} 额度</td>
                      <td class="px-4 py-3">
                        <div class="flex flex-wrap gap-2">
                          <span class="rounded-full px-2 py-1 text-xs" :class="statusBadgeClass(item.status)">
                            用户 {{ item.status }}
                          </span>
                          <span class="rounded-full px-2 py-1 text-xs" :class="statusBadgeClass(item.key_status)">
                            密钥 {{ item.key_status || '-' }}
                          </span>
                        </div>
                      </td>
                      <td class="px-4 py-3">{{ formatTime(item.created_at) }}</td>
                      <td class="px-4 py-3">
                        <div class="flex flex-wrap gap-2">
                          <Button
                            size="sm"
                            variant="outline"
                            class="rounded-xl"
                            @click="updateFrontUserStatus(item, item.status === 'active' ? 'disabled' : 'active')"
                          >
                            {{ item.status === 'active' ? '停用' : '启用' }}
                          </Button>
                          <Button size="sm" variant="outline" class="rounded-xl text-red-600" @click="deleteFrontUser(item)">
                            <Trash2 class="mr-1 h-3.5 w-3.5" />
                            删除
                          </Button>
                        </div>
                      </td>
                    </tr>
                    <tr v-if="!filteredFrontUsers.length">
                      <td colspan="6" class="px-4 py-6 text-center text-[#98a2b3]">
                        {{ frontUsers.length ? '没有匹配的注册用户' : '暂无注册用户' }}
                      </td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </article>
          </template>

          <template v-else-if="activeSection === '套餐订阅框架'">
            <div class="grid gap-5 xl:grid-cols-[0.85fr_1.15fr]">
              <article class="rounded-[24px] bg-white p-5 shadow-sm">
                <div class="mb-4 flex items-center justify-between">
                  <h2 class="text-lg font-semibold">保存/新增套餐</h2>
                  <Button size="sm" variant="outline" class="rounded-xl" @click="resetSubscriptionPlanForm">
                    新增套餐
                  </Button>
                </div>
                <div class="grid gap-3">
                  <Input v-model="planForm.code" class="h-11 rounded-2xl" placeholder="套餐编码，例如 pro_monthly" />
                  <Input v-model="planForm.name" class="h-11 rounded-2xl" placeholder="套餐名称" />
                  <textarea v-model="planForm.description" class="min-h-24 rounded-2xl border border-[#d0d5dd] bg-white px-3 py-2 text-sm outline-none focus:border-[#6656df]" placeholder="套餐描述" />
                  <div class="grid gap-3 md:grid-cols-2">
                    <Input v-model.number="planForm.price_cny" class="h-11 rounded-2xl" type="number" min="0" step="0.01" placeholder="价格/元" />
                    <Input v-model.number="planForm.credit_amount" class="h-11 rounded-2xl" type="number" min="0" placeholder="到账额度" />
                    <Input v-model.number="planForm.validity_days" class="h-11 rounded-2xl" type="number" min="1" placeholder="有效天数" />
                    <Input v-model.number="planForm.sort_order" class="h-11 rounded-2xl" type="number" placeholder="排序" />
                  </div>
                  <label class="flex items-center justify-between rounded-2xl bg-[#f8fbff] px-4 py-3 text-sm">
                    <span>开通科研生成</span>
                    <input v-model="planForm.advanced_generation_enabled" type="checkbox" class="h-4 w-4 accent-[#6656df]" />
                  </label>
                  <select v-model="planForm.status" class="h-11 rounded-2xl border border-[#d0d5dd] bg-white px-3 text-sm outline-none focus:border-[#6656df]">
                    <option value="active">active</option>
                    <option value="disabled">disabled</option>
                    <option value="draft">draft</option>
                  </select>
                  <Button class="h-11 rounded-2xl bg-[#6656df] text-white hover:bg-[#5848cf]" :disabled="savingPlan" @click="saveSubscriptionPlan">
                    {{ savingPlan ? '保存中...' : '保存套餐' }}
                  </Button>
                </div>
              </article>

              <article class="rounded-[24px] bg-white p-5 shadow-sm">
                <div class="mb-4 flex items-center justify-between">
                  <h2 class="text-lg font-semibold">套餐列表</h2>
                  <div class="flex items-center gap-2">
                    <Button size="sm" variant="outline" class="rounded-xl" :disabled="seedingPlans" @click="seedDefaultSubscriptionPlans">
                      {{ seedingPlans ? '补齐中...' : '补齐默认套餐' }}
                    </Button>
                    <span class="rounded-full bg-[#eef7ff] px-3 py-1 text-xs text-[#2e8bd1]">
                      {{ subscriptionPlans.length }} 个
                    </span>
                  </div>
                </div>
                <div class="space-y-3">
                  <button
                    v-for="plan in subscriptionPlans"
                    :key="plan.plan_id"
                    class="w-full rounded-2xl border border-[#edf2f7] bg-[#f8fbff] p-4 text-left transition hover:border-[#6656df]"
                    @click="editSubscriptionPlan(plan)"
                  >
                    <div class="flex items-start justify-between gap-3">
                      <div>
                        <div class="font-semibold">{{ plan.name }}</div>
                        <div class="mt-1 text-xs text-[#98a2b3]">{{ plan.code }} · {{ plan.status }}</div>
                      </div>
                      <div class="text-right">
                        <div class="font-semibold">¥{{ plan.price_cny }}</div>
                        <div class="text-xs text-[#667085]">{{ plan.credit_amount }} 额度</div>
                      </div>
                    </div>
                    <p class="mt-2 text-sm leading-6 text-[#667085]">{{ plan.description || '暂无描述' }}</p>
                    <div class="mt-3 text-xs text-[#344054]">
                      {{ plan.validity_days }} 天 · {{ plan.advanced_generation_enabled ? '含科研生成' : '基础权限' }} · 排序 {{ plan.sort_order }}
                    </div>
                  </button>
                  <div v-if="!subscriptionPlans.length" class="rounded-2xl border border-dashed border-[#d0d5dd] p-6 text-sm text-[#667085]">
                    暂无套餐，保存左侧表单后会显示在这里。
                  </div>
                </div>
              </article>
            </div>

            <article class="rounded-[24px] bg-white p-5 shadow-sm">
              <div class="mb-4 flex items-center justify-between">
                <h2 class="text-lg font-semibold">支付订单</h2>
                <span class="rounded-full bg-[#f3f7fb] px-3 py-1 text-xs text-[#667085]">
                  {{ paymentOrders.length }} 笔
                </span>
              </div>
              <div class="overflow-hidden rounded-2xl border border-[#edf2f7]">
                <table class="w-full text-left text-sm">
                  <thead class="bg-[#f8fbff] text-[#667085]">
                    <tr>
                      <th class="px-4 py-3">订单</th>
                      <th class="px-4 py-3">套餐</th>
                      <th class="px-4 py-3">金额</th>
                      <th class="px-4 py-3">额度</th>
                      <th class="px-4 py-3">状态</th>
                      <th class="px-4 py-3">时间</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr v-for="order in paymentOrders" :key="order.order_id" class="border-t border-[#edf2f7]">
                      <td class="px-4 py-3 font-mono text-xs">{{ order.order_no }}</td>
                      <td class="px-4 py-3">{{ order.plan_name || order.plan_id }}</td>
                      <td class="px-4 py-3">¥{{ order.amount_cny }}</td>
                      <td class="px-4 py-3">{{ order.credit_amount }}</td>
                      <td class="px-4 py-3">{{ order.status }}</td>
                      <td class="px-4 py-3">{{ formatOrderTime(order) }}</td>
                    </tr>
                    <tr v-if="!paymentOrders.length">
                      <td colspan="6" class="px-4 py-6 text-center text-[#98a2b3]">暂无支付订单</td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </article>
          </template>

          <template v-else-if="activeSection === '操作者审计'">
            <article class="rounded-[24px] bg-white p-5 shadow-sm">
              <div class="mb-4 flex items-center justify-between gap-3">
                <div>
                  <h2 class="text-lg font-semibold">操作者审计</h2>
                  <p class="mt-2 text-sm text-[#667085]">
                    记录管理员和前台用户的关键业务动作，用于回溯谁在什么时间改了什么。
                  </p>
                </div>
                <span class="rounded-full bg-[#eef7ff] px-3 py-1 text-xs text-[#2e8bd1]">
                  {{ operatorAuditLogs.length }} 条
                </span>
              </div>
              <div class="overflow-hidden rounded-2xl border border-[#edf2f7]">
                <table class="w-full text-left text-sm">
                  <thead class="bg-[#f8fbff] text-[#667085]">
                    <tr>
                      <th class="px-4 py-3">时间</th>
                      <th class="px-4 py-3">操作者</th>
                      <th class="px-4 py-3">动作</th>
                      <th class="px-4 py-3">目标</th>
                      <th class="px-4 py-3">摘要</th>
                      <th class="px-4 py-3">状态</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr v-for="item in operatorAuditLogs" :key="item.audit_id" class="border-t border-[#edf2f7]">
                      <td class="px-4 py-3">{{ formatTime(item.created_at) }}</td>
                      <td class="px-4 py-3">
                        <div class="font-medium">{{ item.actor_label || item.actor_type }}</div>
                        <div class="font-mono text-xs text-[#98a2b3]">{{ item.actor_type }} · {{ item.actor_id || '-' }}</div>
                      </td>
                      <td class="px-4 py-3 font-mono text-xs">{{ item.action }}</td>
                      <td class="px-4 py-3">
                        <div>{{ item.target_type || '-' }}</div>
                        <div class="font-mono text-xs text-[#98a2b3]">{{ item.target_id || '-' }}</div>
                      </td>
                      <td class="px-4 py-3">{{ item.summary || '-' }}</td>
                      <td class="px-4 py-3">{{ item.status }}</td>
                    </tr>
                    <tr v-if="!operatorAuditLogs.length">
                      <td colspan="6" class="px-4 py-6 text-center text-[#98a2b3]">
                        暂无操作者审计记录。
                      </td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </article>
          </template>

          <template v-else>
            <article class="rounded-[24px] bg-white p-6 shadow-sm">
              <div class="flex items-center gap-3">
                <ShieldCheck class="h-6 w-6 text-[#6656df]" />
                <h2 class="text-lg font-semibold">{{ activeSection }}</h2>
              </div>
              <p class="mt-3 text-sm leading-6 text-[#667085]">
                这一页已经放入后台导航，后续继续接真实数据、筛选、导出和操作按钮。
              </p>
              <div class="mt-5 flex items-center gap-2 rounded-2xl bg-[#f8fbff] px-4 py-3 text-sm text-[#344054]">
                <CheckCircle2 class="h-4 w-4 text-[#047857]" />
                框架已预留，升级时不用重做入口。
              </div>
            </article>
          </template>
        </section>
      </main>
    </div>
  </div>
</template>
