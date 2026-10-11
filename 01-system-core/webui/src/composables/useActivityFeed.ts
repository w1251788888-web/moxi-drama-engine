/**
 * 活动流翻译逻辑 — 将原始请求日志转换为人类可读的活动描述
 */

export interface FeedLog {
  id: string
  timestamp: string | null
  method: string
  path: string
  agent_id: string | null
  agent_name: string | null
  agent_role: string | null
  request_body: string | null
  response_status: number | null
}

export interface FeedAgent {
  id: string
  name: string
  role: string
  status: string
  total_score: number
  created_at: string | null
}

export interface TranslatedActivity {
  id: string
  icon: string        // Lucide 图标名
  verb: string
  colorClass: string  // Tailwind bg 颜色类
  agentName: string
  agentRole: string
  agentId: string
  objectName: string | null
  details: Record<string, string>
  rawMethod: string
  rawPath: string
  rawBody: string | null
  responseStatus: number | null
  timestamp: string | null
  relativeTime: string
}

// ============================================================
// 路由 → 人话映射规则（icon 改为 Lucide 组件名）
// ============================================================

interface RouteRule {
  pattern: RegExp
  icon: string
  verb: string
  colorClass: string
  extractFields?: string[]
}

const ROUTE_RULES: RouteRule[] = [
  { pattern: /POST \/api\/agents\/register/, icon: 'UserPlus', verb: '注册了新 Agent', colorClass: 'bg-emerald-500', extractFields: ['name', 'role'] },
  { pattern: /POST \/api\/tasks$/, icon: 'ListPlus', verb: '创建了任务', colorClass: 'bg-blue-500', extractFields: ['name'] },
  { pattern: /POST \/api\/tasks\/.*\/modules/, icon: 'FolderPlus', verb: '创建了模块', colorClass: 'bg-indigo-500', extractFields: ['name'] },
  { pattern: /POST \/api\/sub-tasks$/, icon: 'FilePlus', verb: '创建了子任务', colorClass: 'bg-violet-500', extractFields: ['name'] },
  { pattern: /POST \/api\/sub-tasks\/.*\/claim/, icon: 'Hand', verb: '认领了子任务', colorClass: 'bg-amber-500' },
  { pattern: /POST \/api\/sub-tasks\/.*\/start/, icon: 'Play', verb: '开始执行子任务', colorClass: 'bg-orange-500' },
  { pattern: /POST \/api\/sub-tasks\/.*\/submit/, icon: 'PackageCheck', verb: '提交了子任务', colorClass: 'bg-green-500' },
  { pattern: /PUT \/api\/sub-tasks\//, icon: 'Pencil', verb: '编辑了子任务', colorClass: 'bg-slate-500' },
  { pattern: /POST \/api\/review-records/, icon: 'FileSearch', verb: '提交了审查', colorClass: 'bg-purple-500', extractFields: ['score', 'comment', 'result'] },
  { pattern: /POST \/api\/logs/, icon: 'MessageSquare', verb: '写了活动日志', colorClass: 'bg-gray-500', extractFields: ['action', 'summary'] },
  { pattern: /POST \/api\/scores\/adjust/, icon: 'Trophy', verb: '调整了积分', colorClass: 'bg-yellow-500', extractFields: ['score_delta', 'reason'] },
  { pattern: /GET \/api\/rules/, icon: 'BookOpen', verb: '查询了规则指令', colorClass: 'bg-sky-500', extractFields: ['task_id', 'sub_task_id'] },
  { pattern: /GET \/api\/tasks$/, icon: 'Eye', verb: '查看了任务列表', colorClass: 'bg-slate-400', extractFields: ['status', 'type'] },
  { pattern: /GET \/api\/tasks\//, icon: 'Eye', verb: '查看了任务详情', colorClass: 'bg-slate-400' },
  { pattern: /GET \/api\/sub-tasks\/available/, icon: 'Search', verb: '查找可认领子任务', colorClass: 'bg-cyan-500', extractFields: ['status', 'priority', 'type'] },
  { pattern: /GET \/api\/sub-tasks\/mine/, icon: 'ClipboardList', verb: '查看了自己的子任务', colorClass: 'bg-slate-400', extractFields: ['status'] },
  { pattern: /GET \/api\/sub-tasks\/latest/, icon: 'FileText', verb: '查看最新子任务', colorClass: 'bg-slate-400' },
  { pattern: /GET \/api\/sub-tasks/, icon: 'ClipboardList', verb: '查看了子任务', colorClass: 'bg-slate-400', extractFields: ['status', 'assigned_agent'] },
  { pattern: /GET \/api\/scores\/me/, icon: 'Award', verb: '查看了自己的积分', colorClass: 'bg-amber-400' },
  { pattern: /GET \/api\/scores\/leaderboard/, icon: 'Medal', verb: '查看了排行榜', colorClass: 'bg-yellow-500' },
  { pattern: /GET \/api\/config\/notification/, icon: 'Bell', verb: '查询了通知配置', colorClass: 'bg-rose-500' },
  { pattern: /GET \/api\/logs\/mine/, icon: 'ScrollText', verb: '查看了自己的日志', colorClass: 'bg-gray-400', extractFields: ['action'] },
  { pattern: /GET \/api\/logs/, icon: 'ScrollText', verb: '查看了活动日志', colorClass: 'bg-gray-400', extractFields: ['action', 'agent_id'] },
  { pattern: /GET \/api\/review-records/, icon: 'FileSearch', verb: '查看了审查记录', colorClass: 'bg-purple-400', extractFields: ['sub_task_id'] },
]

const ROLE_LABELS: Record<string, string> = {
  planner: '规划者',
  executor: '执行者',
  reviewer: '审查者',
  patrol: '巡查者',
}

// query 参数中文标签
const PARAM_LABELS: Record<string, string> = {
  status: '状态',
  priority: '优先级',
  type: '类型',
  task_id: '任务',
  sub_task_id: '子任务',
  agent_id: 'Agent',
  assigned_agent: '执行者',
  action: '动作',
}

// ============================================================
// 翻译函数
// ============================================================

export function translateLog(log: FeedLog): TranslatedActivity {
  const key = `${log.method} ${log.path}`
  const rule = ROUTE_RULES.find((r) => r.pattern.test(key))

  let body: Record<string, unknown> = {}
  if (log.request_body) {
    try {
      body = JSON.parse(log.request_body)
    } catch {
      // ignore
    }
  }

  const details: Record<string, string> = {}
  let objectName: string | null = null

  if (rule?.extractFields) {
    for (const field of rule.extractFields) {
      const val = body[field]
      if (val !== undefined && val !== null && val !== '') {
        details[field] = String(val)
      }
    }
    if (details.name) {
      objectName = details.name
      delete details.name
    }
  }

  if (rule?.pattern.test('POST /api/review-records') && details.score) {
    objectName = `${details.score} 分`
    delete details.score
  }

  if (rule?.pattern.test('POST /api/logs') && details.action) {
    objectName = details.action
    delete details.action
  }

  return {
    id: log.id,
    icon: rule?.icon ?? 'Activity',
    verb: rule?.verb ?? `访问了 ${log.path}`,
    colorClass: rule?.colorClass ?? 'bg-slate-500',
    agentName: log.agent_name ?? '未知',
    agentRole: ROLE_LABELS[log.agent_role ?? ''] ?? log.agent_role ?? '',
    agentId: log.agent_id ?? '',
    objectName,
    details,
    rawMethod: log.method,
    rawPath: log.path,
    rawBody: log.request_body,
    responseStatus: log.response_status,
    timestamp: log.timestamp,
    relativeTime: formatRelativeTime(log.timestamp),
  }
}

export function formatRelativeTime(timestamp: string | null): string {
  if (!timestamp) return ''
  const now = Date.now()
  const then = new Date(timestamp).getTime()
  const diff = Math.floor((now - then) / 1000)

  if (diff < 10) return '刚刚'
  if (diff < 60) return `${diff}s`
  if (diff < 3600) return `${Math.floor(diff / 60)}m`
  if (diff < 86400) return `${Math.floor(diff / 3600)}h`
  if (diff < 604800) return `${Math.floor(diff / 86400)}d`
  return new Date(timestamp).toLocaleDateString('zh-CN')
}

// ============================================================
// Agent Summary 类型 + 动作分类
// ============================================================

export interface SubTaskBrief {
  id: string
  name: string
  module_name: string | null
}

export interface RecentAction {
  method: string
  path: string
  request_body: string | null
  response_status: number | null
  timestamp: string | null
}

export interface AgentSummary {
  id: string
  name: string
  role: string
  total_score: number
  today_request_count: number
  today_submit_count: number
  today_review_count: number
  current_sub_task: SubTaskBrief | null
  recent_actions: RecentAction[]
}

export type ActionCategory = 'complete' | 'execute' | 'create' | 'query' | 'score_up' | 'score_down'

export function getActionCategory(action: RecentAction): ActionCategory {
  const key = `${action.method} ${action.path}`

  // 积分调整 — 检查 score_delta
  if (/POST \/api\/scores\/adjust/.test(key) && action.request_body) {
    try {
      const body = JSON.parse(action.request_body)
      return (body.score_delta ?? 0) >= 0 ? 'score_up' : 'score_down'
    } catch { /* fall through */ }
  }

  // 完成类
  if (/POST .*\/submit/.test(key) || /POST .*\/review-records/.test(key)) return 'complete'

  // 执行类
  if (/POST .*\/claim/.test(key) || /POST .*\/start/.test(key) || /PUT \/api\/sub-tasks/.test(key)) return 'execute'

  // 创建类
  if (action.method === 'POST') return 'create'

  // 查询类
  return 'query'
}

export function getActionVerb(action: RecentAction): string {
  const key = `${action.method} ${action.path}`
  const rule = ROUTE_RULES.find((r) => r.pattern.test(key))
  return rule?.verb ?? `${action.method} ${action.path.split('/api')[1] ?? action.path}`
}

