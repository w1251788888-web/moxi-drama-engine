<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  Archive,
  BookOpen,
  CheckCircle2,
  ClipboardList,
  FileCheck2,
  GitBranch,
  LayoutDashboard,
  Lock,
  MessageSquare,
  RefreshCw,
  Scale,
  ShieldCheck,
  Users,
} from 'lucide-vue-next'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import {
  collaborationApi,
  legalAssetsApi,
  projectsV2Api,
  type ApprovalTask,
  type CollaborationSummary,
  type ContributionV2,
  type EpisodeV2,
  type ProjectInvite,
  type ProjectMember,
  type ProjectV2,
  type RightsCheckResult,
} from '@/api/client'
import { notifyApiError } from '@/api/http'
import ComplianceReviewTab from '@/views/workspace/tabs/ComplianceReviewTab.vue'
import LegalAssetsTab from '@/views/workspace/tabs/LegalAssetsTab.vue'
import { toast } from 'vue-sonner'

type SectionId =
  | 'overview'
  | 'creation'
  | 'tasks'
  | 'room'
  | 'invites'
  | 'assignments'
  | 'scripts'
  | 'approvals'
  | 'contribution'
  | 'compliance'
  | 'legal'
  | 'delivery'

const route = useRoute()
const router = useRouter()
const projectId = computed(() => String(route.params.projectId || ''))

const sections: Array<{ id: SectionId; label: string; icon: any }> = [
  { id: 'overview', label: '总览', icon: LayoutDashboard },
  { id: 'creation', label: '剧本创作台', icon: BookOpen },
  { id: 'tasks', label: '我的任务', icon: ClipboardList },
  { id: 'room', label: '编剧室', icon: Users },
  { id: 'invites', label: '邀请与权限', icon: GitBranch },
  { id: 'assignments', label: '分集分工', icon: ClipboardList },
  { id: 'scripts', label: '剧本协作', icon: MessageSquare },
  { id: 'approvals', label: '审批队列', icon: CheckCircle2 },
  { id: 'contribution', label: '贡献与版权', icon: Scale },
  { id: 'compliance', label: '合规审核', icon: ShieldCheck },
  { id: 'legal', label: '法律资料', icon: FileCheck2 },
  { id: 'delivery', label: '导出交付', icon: Archive },
]

function normalizeSection(value: unknown): SectionId {
  const raw = Array.isArray(value) ? value[0] : value
  return sections.some(item => item.id === raw) ? raw as SectionId : 'overview'
}

const activeSection = ref<SectionId>(normalizeSection(route.query.section))
const project = ref<ProjectV2 | null>(null)
const summary = ref<CollaborationSummary | null>(null)
const members = ref<ProjectMember[]>([])
const invites = ref<ProjectInvite[]>([])
const approvals = ref<ApprovalTask[]>([])
const episodes = ref<EpisodeV2[]>([])
const contributions = ref<ContributionV2[]>([])
const gate = ref<RightsCheckResult | null>(null)
const isLoading = ref(false)
const createdInviteToken = ref('')
const selectedEpisode = ref(1)

const inviteForm = ref({
  target_contact: '',
  target_access_key_id: '',
  role: 'co_writer',
  legal_identity: 'commissioned_creator',
  scope_type: 'project',
  scope_id: '',
  permissions: ['view', 'comment', 'suggest'] as string[],
  allow_download: false,
  days_valid: 7,
  note: '',
})

const collabDraft = ref({
  action: 'suggest',
  title: '',
  body: '',
  scene_number: 0,
})

const assignmentDraft = ref({
  episode_number: 1,
  owner: '',
  collaborator: '',
  due_date: '',
})

const statusCards = computed(() => [
  { label: '成员', value: summary.value?.members.length ?? members.value.length, hint: `${summary.value?.pending_invites ?? 0} 个待接受` },
  { label: '待审批', value: summary.value?.pending_approvals ?? approvals.value.filter(item => item.status === 'pending').length, hint: '建议/锁稿/资料确认' },
  { label: '锁稿进度', value: `${summary.value?.locked_episodes ?? 0}/${project.value?.total_episodes || episodes.value.length || 0}`, hint: '锁稿后进入合规复审' },
  { label: '导出门禁', value: gate.value?.status || 'checking', hint: gate.value?.blockers?.[0] || '等待资料检查' },
])

const pendingApprovals = computed(() => approvals.value.filter(item => item.status === 'pending'))

function sectionTitle(id: SectionId) {
  return sections.find(item => item.id === id)?.label || ''
}

function switchSection(id: SectionId) {
  activeSection.value = id
  const nextQuery = { ...route.query }
  if (id === 'overview') delete nextQuery.section
  else nextQuery.section = id
  router.replace({ query: nextQuery }).catch(() => {})
}

function openEpisodeCollab(episodeNumber: number) {
  selectedEpisode.value = episodeNumber
  switchSection('scripts')
}

function openWorkspace(tab: 'chat' | 'outline' | 'characters' | 'script') {
  router.push(`/projects/${projectId.value}/workspace?tab=${tab}`)
}

function permissionLabel(value: string) {
  const map: Record<string, string> = {
    view: '查看',
    comment: '评论',
    suggest: '建议',
    edit: '编辑',
    approve: '审批',
    manage: '管理',
    export: '导出',
  }
  return map[value] || value
}

async function loadAll() {
  isLoading.value = true
  try {
    const [projectRes, summaryRes, membersRes, invitesRes, approvalsRes, episodesRes, contributionRes, gateRes] = await Promise.all([
      projectsV2Api.get(projectId.value),
      collaborationApi.getSummary(projectId.value),
      collaborationApi.listMembers(projectId.value),
      collaborationApi.listInvites(projectId.value),
      collaborationApi.listApprovals(projectId.value),
      projectsV2Api.listEpisodes(projectId.value),
      projectsV2Api.getContributions(projectId.value),
      legalAssetsApi.getExportGate(projectId.value),
    ])
    project.value = projectRes.data
    summary.value = summaryRes.data
    members.value = membersRes.data.items
    invites.value = invitesRes.data.items
    approvals.value = approvalsRes.data.items
    episodes.value = episodesRes.data
    contributions.value = contributionRes.data
    gate.value = gateRes.data
    selectedEpisode.value = episodes.value[0]?.episode_number || 1
    assignmentDraft.value.episode_number = episodes.value[0]?.episode_number || 1
  } catch (e) {
    notifyApiError(toast.error, e, '加载总编剧工作台失败')
  } finally {
    isLoading.value = false
  }
}

async function createInvite() {
  if (!inviteForm.value.target_access_key_id.trim()) {
    toast.error('请填写被邀请人的密钥ID，协作邀请需要绑定到具体账号')
    return
  }
  try {
    const { data } = await collaborationApi.createInvite(projectId.value, inviteForm.value)
    createdInviteToken.value = data.invite_token || ''
    toast.success('邀请已创建')
    await loadAll()
  } catch (e) {
    notifyApiError(toast.error, e, '创建邀请失败')
  }
}

async function createCollabEvent(action = collabDraft.value.action) {
  if (!collabDraft.value.title.trim() && !collabDraft.value.body.trim()) {
    toast.error('请填写标题或内容')
    return
  }
  try {
    await collaborationApi.createEvent(projectId.value, {
      action,
      scope_type: 'episode',
      scope_id: String(selectedEpisode.value),
      episode_number: selectedEpisode.value,
      scene_number: Number(collabDraft.value.scene_number || 0),
      title: collabDraft.value.title,
      body: collabDraft.value.body,
    })
    toast.success(action === 'comment' ? '评论已记录' : action === 'lock_request' ? '锁稿申请已提交' : '建议已进入审批')
    collabDraft.value.title = ''
    collabDraft.value.body = ''
    await loadAll()
  } catch (e) {
    notifyApiError(toast.error, e, '提交协作事件失败')
  }
}

async function createAssignment() {
  if (!assignmentDraft.value.owner.trim()) {
    toast.error('请填写负责人')
    return
  }
  try {
    await collaborationApi.createEvent(projectId.value, {
      action: 'assignment',
      scope_type: 'episode',
      scope_id: String(assignmentDraft.value.episode_number),
      episode_number: assignmentDraft.value.episode_number,
      title: `第${assignmentDraft.value.episode_number}集分工`,
      body: `负责人：${assignmentDraft.value.owner}`,
      metadata: {
        owner: assignmentDraft.value.owner,
        collaborator: assignmentDraft.value.collaborator,
        due_date: assignmentDraft.value.due_date,
      },
    })
    toast.success('分工已记录')
    assignmentDraft.value.owner = ''
    assignmentDraft.value.collaborator = ''
    assignmentDraft.value.due_date = ''
    await loadAll()
  } catch (e) {
    notifyApiError(toast.error, e, '记录分工失败')
  }
}

async function lockEpisode(episodeNumber: number) {
  try {
    await collaborationApi.lockEpisode(projectId.value, episodeNumber, { note: `锁定第${episodeNumber}集最终稿` })
    toast.success(`第${episodeNumber}集已锁稿`)
    await loadAll()
  } catch (e) {
    notifyApiError(toast.error, e, '锁稿失败')
  }
}

async function decideApproval(task: ApprovalTask, decision: string) {
  try {
    await collaborationApi.decideApproval(projectId.value, task.id, { decision })
    toast.success('审批已处理')
    await loadAll()
  } catch (e) {
    notifyApiError(toast.error, e, '审批处理失败')
  }
}

onMounted(loadAll)
</script>

<template>
  <div class="h-[calc(100vh-3.5rem)] overflow-hidden bg-background">
    <div class="flex h-full">
      <aside class="w-64 shrink-0 border-r bg-card">
        <div class="border-b p-4">
          <button class="text-sm text-muted-foreground hover:text-foreground" @click="router.push('/projects')">返回项目</button>
          <h1 class="mt-2 truncate text-lg font-semibold">{{ project?.name || '总编剧工作台' }}</h1>
          <p class="mt-1 text-xs text-muted-foreground">多人协作 · 确权资料自动沉淀</p>
        </div>
        <nav class="space-y-1 p-3">
          <button
            v-for="item in sections"
            :key="item.id"
            class="flex w-full items-center gap-2 rounded-lg px-3 py-2 text-left text-sm transition-colors"
            :class="activeSection === item.id ? 'bg-primary text-primary-foreground' : 'text-muted-foreground hover:bg-muted hover:text-foreground'"
            @click="switchSection(item.id)"
          >
            <component :is="item.icon" class="h-4 w-4" />
            {{ item.label }}
          </button>
        </nav>
      </aside>

      <main class="min-w-0 flex-1 overflow-auto">
        <div class="sticky top-0 z-10 flex items-center justify-between border-b bg-background/95 px-6 py-4 backdrop-blur">
          <div>
            <h2 class="text-xl font-semibold">{{ sectionTitle(activeSection) }}</h2>
            <p class="text-sm text-muted-foreground">创作协作、合规审核、确权交付在同一项目链路内闭合</p>
          </div>
          <Button size="sm" variant="outline" class="gap-1.5" :disabled="isLoading" @click="loadAll">
            <RefreshCw class="h-4 w-4" />
            刷新
          </Button>
        </div>

        <div class="p-6">
          <section v-if="activeSection === 'overview'" class="space-y-4">
            <div class="flex items-center justify-between gap-4 rounded-lg border bg-card p-4">
              <div>
                <h3 class="font-semibold">剧本创作台</h3>
                <p class="mt-1 text-sm text-muted-foreground">总编剧可先开写，邀请和分工可以稍后进行。</p>
              </div>
              <div class="flex gap-2">
                <Button variant="outline" @click="openWorkspace('outline')">编辑大纲</Button>
                <Button @click="openWorkspace('script')">开始写作</Button>
              </div>
            </div>
            <div class="grid gap-3 md:grid-cols-4">
              <div v-for="card in statusCards" :key="card.label" class="rounded-lg border bg-card p-4">
                <p class="text-xs text-muted-foreground">{{ card.label }}</p>
                <p class="mt-1 text-2xl font-semibold">{{ card.value }}</p>
                <p class="mt-2 line-clamp-2 text-xs text-muted-foreground">{{ card.hint }}</p>
              </div>
            </div>
            <div class="grid gap-4 lg:grid-cols-2">
              <div class="rounded-lg border bg-card p-4">
                <h3 class="font-semibold">项目阶段</h3>
                <div class="mt-3 grid gap-2 text-sm">
                  <div class="flex justify-between"><span class="text-muted-foreground">创作模式</span><span>{{ project?.creation_mode === 'collab' ? '多人协作' : '独立完成' }}</span></div>
                  <div class="flex justify-between"><span class="text-muted-foreground">确权沉淀</span><span>{{ project?.rights_capture_enabled ? '已开启' : '未开启' }}</span></div>
                  <div class="flex justify-between"><span class="text-muted-foreground">项目状态</span><span>{{ project?.status }}</span></div>
                </div>
              </div>
              <div class="rounded-lg border bg-card p-4">
                <h3 class="font-semibold">风险摘要</h3>
                <div class="mt-3 space-y-2 text-sm">
                  <template v-if="gate?.blockers.length">
                    <p v-for="item in gate.blockers" :key="item" class="rounded-md bg-red-500/10 px-3 py-2 text-red-700 dark:text-red-300">{{ item }}</p>
                  </template>
                  <template v-if="gate?.warnings.length">
                    <p v-for="item in gate.warnings" :key="item" class="rounded-md bg-orange-500/10 px-3 py-2 text-orange-700 dark:text-orange-300">{{ item }}</p>
                  </template>
                  <p v-if="!gate?.blockers.length && !gate?.warnings.length" class="rounded-md bg-emerald-500/10 px-3 py-2 text-emerald-700 dark:text-emerald-300">当前没有导出门禁阻塞。</p>
                </div>
              </div>
            </div>
          </section>

          <section v-else-if="activeSection === 'creation'" class="space-y-4">
            <div class="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
              <button
                class="rounded-lg border bg-card p-4 text-left transition-colors hover:bg-muted"
                @click="openWorkspace('chat')"
              >
                <p class="font-semibold">聊天脑暴</p>
                <p class="mt-2 text-sm text-muted-foreground">选题、设定、方向判断</p>
              </button>
              <button
                class="rounded-lg border bg-card p-4 text-left transition-colors hover:bg-muted"
                @click="openWorkspace('outline')"
              >
                <p class="font-semibold">大纲编辑</p>
                <p class="mt-2 text-sm text-muted-foreground">分集结构、钩子、主线</p>
              </button>
              <button
                class="rounded-lg border bg-card p-4 text-left transition-colors hover:bg-muted"
                @click="openWorkspace('characters')"
              >
                <p class="font-semibold">角色设计</p>
                <p class="mt-2 text-sm text-muted-foreground">人物设定、关系张力</p>
              </button>
              <button
                class="rounded-lg border bg-card p-4 text-left transition-colors hover:bg-muted"
                @click="openWorkspace('script')"
              >
                <p class="font-semibold">剧本写作</p>
                <p class="mt-2 text-sm text-muted-foreground">分集分场正文创作</p>
              </button>
            </div>
            <div class="rounded-lg border bg-card p-4">
              <h3 class="font-semibold">协作进入点</h3>
              <div class="mt-3 grid gap-2 md:grid-cols-3">
                <Button variant="outline" @click="switchSection('invites')">邀请成员</Button>
                <Button variant="outline" @click="switchSection('assignments')">分集分工</Button>
                <Button variant="outline" @click="switchSection('scripts')">提交建议</Button>
              </div>
            </div>
          </section>

          <section v-else-if="activeSection === 'tasks'" class="grid gap-4 lg:grid-cols-[360px_minmax(0,1fr)]">
            <div class="rounded-lg border bg-card p-4">
              <h3 class="font-semibold">我的待处理</h3>
              <div class="mt-4 space-y-3">
                <template v-if="pendingApprovals.length">
                  <button
                    v-for="task in pendingApprovals"
                    :key="task.id"
                    class="w-full rounded-lg border p-3 text-left text-sm transition-colors hover:bg-muted"
                    @click="switchSection('approvals')"
                  >
                    <Badge variant="outline">{{ task.task_type }}</Badge>
                    <p class="mt-2 font-medium">{{ task.title }}</p>
                    <p class="mt-1 line-clamp-2 text-xs text-muted-foreground">{{ task.description }}</p>
                  </button>
                </template>
                <p v-else class="rounded-lg border border-dashed p-4 text-sm text-muted-foreground">
                  当前没有待处理审批、建议或锁稿申请。
                </p>
              </div>
            </div>
            <div class="rounded-lg border bg-card p-4">
              <h3 class="font-semibold">可协作内容</h3>
              <div class="mt-4 space-y-3">
                <template v-if="episodes.length">
                  <div
                    v-for="episode in episodes"
                    :key="episode.id"
                    class="flex items-center justify-between gap-3 rounded-lg border px-4 py-3 text-sm"
                  >
                    <div>
                      <p class="font-medium">第{{ episode.episode_number }}集 · {{ episode.title || '未命名' }}</p>
                      <p class="mt-1 text-xs text-muted-foreground">{{ episode.status }}</p>
                    </div>
                    <Button size="sm" variant="outline" @click="openEpisodeCollab(episode.episode_number)">
                      去协作
                    </Button>
                  </div>
                </template>
                <div v-else class="rounded-lg border border-dashed p-5 text-sm leading-6 text-muted-foreground">
                  暂无分集任务。项目完成大纲或分集分工后，这里会直接显示可评论、建议和申请锁稿的内容。
                </div>
              </div>
            </div>
          </section>

          <section v-else-if="activeSection === 'room'" class="rounded-lg border bg-card">
            <div class="grid grid-cols-[1.2fr_1fr_1fr_1.4fr] border-b px-4 py-3 text-xs font-medium text-muted-foreground">
              <span>成员</span><span>创作角色</span><span>法律身份</span><span>权限</span>
            </div>
            <div v-for="member in members" :key="member.id" class="grid grid-cols-[1.2fr_1fr_1fr_1.4fr] items-center border-b px-4 py-3 text-sm last:border-0">
              <span class="font-medium">{{ member.display_name || member.access_key_id }}</span>
              <span>{{ member.role }}</span>
              <span>{{ member.legal_identity }}</span>
              <span class="flex flex-wrap gap-1">
                <Badge v-for="perm in member.permissions" :key="perm" variant="outline">{{ perm.split(':')[perm.split(':').length - 1] }}</Badge>
              </span>
            </div>
          </section>

          <section v-else-if="activeSection === 'invites'" class="grid gap-4 lg:grid-cols-[360px_minmax(0,1fr)]">
            <div class="rounded-lg border bg-card p-4">
              <h3 class="font-semibold">发起邀请</h3>
              <div class="mt-4 space-y-3">
                <Input v-model="inviteForm.target_contact" placeholder="被邀请人邮箱/姓名" />
                <Input v-model="inviteForm.target_access_key_id" placeholder="绑定被邀请人的密钥ID（必填）" />
                <div class="grid grid-cols-2 gap-2">
                  <Input v-model="inviteForm.role" placeholder="创作角色" />
                  <Input v-model="inviteForm.legal_identity" placeholder="法律身份" />
                </div>
                <div class="grid grid-cols-2 gap-2">
                  <Input v-model="inviteForm.scope_type" placeholder="project / episode" />
                  <Input v-model="inviteForm.scope_id" placeholder="范围ID" />
                </div>
                <div class="flex flex-wrap gap-2">
                  <button
                    v-for="perm in ['view','comment','suggest','edit','approve','manage','export']"
                    :key="perm"
                    class="rounded-md border px-2 py-1 text-xs"
                    :class="inviteForm.permissions.includes(perm) ? 'border-primary bg-primary/10 text-primary' : 'hover:bg-muted'"
                    @click="inviteForm.permissions.includes(perm)
                      ? inviteForm.permissions = inviteForm.permissions.filter(item => item !== perm)
                      : inviteForm.permissions = [...inviteForm.permissions, perm]"
                  >
                    {{ permissionLabel(perm) }}
                  </button>
                </div>
                <Button class="w-full" @click="createInvite">创建邀请</Button>
                <p v-if="createdInviteToken" class="break-all rounded-md bg-muted p-3 text-xs">{{ createdInviteToken }}</p>
              </div>
            </div>
            <div class="rounded-lg border bg-card">
              <div class="border-b px-4 py-3 font-semibold">邀请记录</div>
              <div v-for="invite in invites" :key="invite.id" class="border-b px-4 py-3 text-sm last:border-0">
                <div class="flex items-center justify-between gap-3">
                  <span class="font-medium">{{ invite.target_contact || invite.target_access_key_id || '未绑定账号' }}</span>
                  <Badge variant="outline">{{ invite.status }}</Badge>
                </div>
                <p class="mt-1 text-xs text-muted-foreground">{{ invite.role }} · {{ invite.legal_identity }} · {{ invite.permissions.join(' / ') }}</p>
              </div>
            </div>
          </section>

          <section v-else-if="activeSection === 'assignments'" class="space-y-4">
            <div class="rounded-lg border bg-card p-4">
              <h3 class="font-semibold">分配负责人</h3>
              <div class="mt-3 grid gap-2 md:grid-cols-[140px_1fr_1fr_160px_120px]">
                <select v-model="assignmentDraft.episode_number" class="h-10 rounded-md border bg-background px-3 text-sm">
                  <option v-for="episode in episodes" :key="episode.id" :value="episode.episode_number">第{{ episode.episode_number }}集</option>
                </select>
                <Input v-model="assignmentDraft.owner" placeholder="负责人" />
                <Input v-model="assignmentDraft.collaborator" placeholder="协作者" />
                <Input v-model="assignmentDraft.due_date" placeholder="截止时间" />
                <Button @click="createAssignment">记录分工</Button>
              </div>
            </div>
            <div class="rounded-lg border bg-card">
            <div class="grid grid-cols-[80px_1fr_140px_150px] border-b px-4 py-3 text-xs font-medium text-muted-foreground">
              <span>集数</span><span>标题</span><span>状态</span><span>操作</span>
            </div>
            <div v-for="episode in episodes" :key="episode.id" class="grid grid-cols-[80px_1fr_140px_150px] items-center border-b px-4 py-3 text-sm last:border-0">
              <span>第{{ episode.episode_number }}集</span>
              <span>{{ episode.title || '未命名' }}</span>
              <span>{{ episode.status }}</span>
              <Button size="sm" variant="outline" class="gap-1.5" @click="lockEpisode(episode.episode_number)">
                <Lock class="h-3.5 w-3.5" />
                锁稿
              </Button>
            </div>
            </div>
          </section>

          <section v-else-if="activeSection === 'scripts'" class="grid gap-4 lg:grid-cols-[360px_minmax(0,1fr)]">
            <div class="rounded-lg border bg-card p-4">
              <h3 class="font-semibold">提交评论/建议</h3>
              <div class="mt-4 space-y-3">
                <select v-model="selectedEpisode" class="h-10 w-full rounded-md border bg-background px-3 text-sm">
                  <option v-for="episode in episodes" :key="episode.id" :value="episode.episode_number">第{{ episode.episode_number }}集</option>
                </select>
                <Input v-model="collabDraft.title" placeholder="标题" />
                <textarea v-model="collabDraft.body" class="min-h-28 w-full rounded-md border bg-background px-3 py-2 text-sm" placeholder="建议内容、修改说明或锁稿理由" />
                <div class="grid grid-cols-3 gap-2">
                  <Button size="sm" variant="outline" @click="createCollabEvent('comment')">评论</Button>
                  <Button size="sm" @click="createCollabEvent('suggest')">建议</Button>
                  <Button size="sm" variant="outline" @click="createCollabEvent('lock_request')">申请锁稿</Button>
                </div>
              </div>
            </div>
            <div class="rounded-lg border bg-card p-4">
              <h3 class="font-semibold">REST 协作 MVP</h3>
              <p class="mt-3 text-sm leading-6 text-muted-foreground">
                当前版本先用评论、建议、采纳、驳回和锁稿申请承载协作；实时 Tiptap + Yjs/Hocuspocus 上线前，仍保留现有保存接口作为兜底。
              </p>
            </div>
          </section>

          <section v-else-if="activeSection === 'approvals'" class="rounded-lg border bg-card">
            <div v-for="task in approvals" :key="task.id" class="border-b p-4 last:border-0">
              <div class="flex items-start justify-between gap-3">
                <div>
                  <Badge variant="outline">{{ task.task_type }}</Badge>
                  <h3 class="mt-2 font-semibold">{{ task.title }}</h3>
                  <p class="mt-1 text-sm text-muted-foreground">{{ task.description }}</p>
                </div>
                <Badge>{{ task.status }}</Badge>
              </div>
              <div v-if="task.status === 'pending'" class="mt-3 flex gap-2">
                <Button size="sm" @click="decideApproval(task, 'approved')">通过</Button>
                <Button size="sm" variant="outline" @click="decideApproval(task, 'rework')">返工</Button>
                <Button size="sm" variant="destructive" @click="decideApproval(task, 'rejected')">拒绝</Button>
              </div>
            </div>
          </section>

          <section v-else-if="activeSection === 'contribution'" class="space-y-4">
            <div class="rounded-lg border border-amber-500/30 bg-amber-500/10 p-4 text-sm text-amber-700 dark:text-amber-300">
              贡献统计是事实记录，不等于最终版权归属；最终权属以合同、身份、授权、锁稿审批和法律资料为准。
            </div>
            <div class="rounded-lg border bg-card">
              <div v-for="item in contributions" :key="item.user_id" class="grid grid-cols-[1fr_120px_120px_120px] border-b px-4 py-3 text-sm last:border-0">
                <span class="font-medium">{{ item.user_name || item.user_id }}</span>
                <span>{{ item.total_edits }} 次编辑</span>
                <span>{{ item.words_added }} 字新增</span>
                <span>{{ item.percentage }}%</span>
              </div>
            </div>
          </section>

          <ComplianceReviewTab v-else-if="activeSection === 'compliance'" :project-id="projectId" />
          <LegalAssetsTab v-else-if="activeSection === 'legal'" :project-id="projectId" />

          <section v-else-if="activeSection === 'delivery'" class="space-y-4">
            <div class="rounded-lg border bg-card p-4">
              <h3 class="font-semibold">导出交付门禁</h3>
              <p class="mt-2 text-sm text-muted-foreground">正式交付包必须经过后端生成并写入证据事件；原浏览器本地导出只作为草稿导出。</p>
              <div class="mt-4 rounded-lg border p-4" :class="gate?.status === 'blocked' ? 'border-red-500/40 bg-red-500/10' : 'border-emerald-500/40 bg-emerald-500/10'">
                <p class="font-medium">状态：{{ gate?.status || 'checking' }}</p>
                <p v-for="item in gate?.blockers || []" :key="item" class="mt-2 text-sm text-red-700 dark:text-red-300">{{ item }}</p>
              </div>
              <Button class="mt-4 gap-1.5" :disabled="gate?.status === 'blocked'" @click="switchSection('legal')">
                <Archive class="h-4 w-4" />
                前往生成资产包
              </Button>
            </div>
          </section>
        </div>
      </main>
    </div>
  </div>
</template>
