<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import { storeToRefs } from 'pinia'
import { useRoute, useRouter } from 'vue-router'
import {
  Plus, Film, Clock, ChevronRight, Sparkles, Search,
  Trash2, MoreHorizontal, Play, BookOpen, Wand2, Users, Check, X
} from 'lucide-vue-next'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Badge } from '@/components/ui/badge'
import {
  advancedGenerationApi,
  collaborationApi,
  projectsV2Api,
  type AdvancedGenerationProfile,
  type ProjectInvite,
  type ProjectV2,
} from '@/api/client'
import { useProjectsStore } from '@/stores/projects'
import { notifyApiError } from '@/api/http'
import { extractExplicitEpisodeCount } from '@/features/workspace/utils/episodeCount'
import { toast } from 'vue-sonner'

const router = useRouter()
const route = useRoute()

const projectsStore = useProjectsStore()
const { projects, isLoading, lastError: loadError } = storeToRefs(projectsStore)
const searchQuery = ref('')
const showNewProjectModal = ref(false)
const isCreating = ref(false)
const quickStartPrompt = ref('')
const projectListMode = ref<'mine' | 'collab' | 'pending'>('mine')
const pendingInvites = ref<ProjectInvite[]>([])

const newProject = ref({
  name: '',
  description: '',
  profile_id: 'short_drama',
  project_type: '真人短剧',
  genre_main: '',
  creation_mode: 'solo' as 'solo' | 'collab',
})

const defaultProfileOptions: AdvancedGenerationProfile[] = [
  {
    id: 'short_drama',
    label: '短剧',
    status: 'active',
    project_type_aliases: ['真人短剧'],
    rule_scopes: [],
    workflow_steps: [],
    artifacts: [],
    notes: [],
  },
  {
    id: 'stage_play',
    label: '话剧',
    status: 'active',
    project_type_aliases: ['话剧'],
    rule_scopes: [],
    workflow_steps: [],
    artifacts: [],
    notes: [],
  },
  {
    id: 'film',
    label: '影视剧',
    status: 'active',
    project_type_aliases: ['影视剧'],
    rule_scopes: [],
    workflow_steps: [],
    artifacts: [],
    notes: [],
  },
  {
    id: 'long_series',
    label: '长剧/系列剧',
    status: 'active',
    project_type_aliases: ['长剧'],
    rule_scopes: [],
    workflow_steps: [],
    artifacts: [],
    notes: [],
  },
]

const profileOptions = ref<AdvancedGenerationProfile[]>(defaultProfileOptions)
const profileOptionsLoaded = ref(false)

const genreOptions = [
  '甜宠', '虐恋', '重生', '穿越', '悬疑', '古装', '都市', '奇幻', '系统流', '种田'
]

function isTimeoutError(e: unknown) {
  return String((e as { code?: string })?.code || '').includes('ECONNABORTED')
    || String((e as { message?: string })?.message || '').includes('timeout')
}

function isDuplicateNameError(e: unknown) {
  const detail = String((e as { response?: { data?: { detail?: string } } })?.response?.data?.detail || '')
  return detail.includes('项目名称已存在')
}

const visibleProjects = computed(() =>
  projectListMode.value === 'collab'
    ? projects.value.filter(p => p.creation_mode === 'collab')
    : projects.value
)

const filteredProjects = computed(() => {
  const rows = visibleProjects.value
  if (!searchQuery.value) return rows
  return rows.filter(p =>
    p.name.toLowerCase().includes(searchQuery.value.toLowerCase()) ||
    p.description?.toLowerCase().includes(searchQuery.value.toLowerCase())
  )
})

onMounted(() => {
  // 第一次进入：拉数据。返回此页面时缓存仍新鲜，store 会跳过请求，
  // 列表立即显示，不会再因 unmount/remount 而短暂消失。
  projectsStore.fetchProjects()
  loadPendingInvites()
  const newProfile = String(route.query.newProfile || '')
  if (newProfile) {
    openNewProjectModal(newProfile)
  }
})

function loadProjects() {
  return projectsStore.fetchProjects(true)
}

async function loadPendingInvites() {
  try {
    const { data } = await collaborationApi.listPendingInvites()
    pendingInvites.value = data.items
  } catch {
    pendingInvites.value = []
  }
}

async function loadProfileOptions() {
  if (profileOptionsLoaded.value) return
  try {
    const { data } = await advancedGenerationApi.listProfiles()
    profileOptions.value = data.profiles.length ? data.profiles : defaultProfileOptions
  } catch {
    profileOptions.value = defaultProfileOptions
  } finally {
    profileOptionsLoaded.value = true
  }
}

function projectTypeFromProfile(profile: AdvancedGenerationProfile) {
  return profile.project_type_aliases[0] || profile.label
}

function selectedProfile() {
  return profileOptions.value.find((item) => item.id === newProject.value.profile_id) || profileOptions.value[0]
}

function selectProfile(profile: AdvancedGenerationProfile) {
  newProject.value.profile_id = profile.id
  newProject.value.project_type = projectTypeFromProfile(profile)
}

function openNewProjectModal(profileId = 'short_drama') {
  void loadProfileOptions()
  const profile = profileOptions.value.find((item) => item.id === profileId) || profileOptions.value[0]
  if (!profile) return
  newProject.value = {
    name: '',
    description: '',
    profile_id: profile.id,
    project_type: projectTypeFromProfile(profile),
    genre_main: '',
    creation_mode: 'solo',
  }
  showNewProjectModal.value = true
}

async function recoverCreatedProject(name: string, prompt = '') {
  await projectsStore.fetchProjects(true)
  const existing = projectsStore.findByName(name)
  if (!existing) return false
  projectsStore.clearError()
  toast.success('项目已创建，正在进入创作空间...')
  const query = prompt ? `?tab=chat&prompt=${encodeURIComponent(prompt)}` : ''
  router.push(`/projects/${existing.id}/workspace${query}`)
  return true
}

async function createProject() {
  if (!newProject.value.name.trim()) {
    toast.error('请先填写项目名称')
    return
  }
  const projectName = newProject.value.name.trim()
  isCreating.value = true
  try {
    const { data } = await projectsV2Api.create({
      name: projectName,
      description: newProject.value.description,
      project_type: newProject.value.project_type,
      genre_main: newProject.value.genre_main,
      creation_mode: newProject.value.creation_mode,
      audience_axis: newProject.value.profile_id === 'short_drama' ? '男频' : '混合',
      config: {
        advanced_generation_mode: true,
        advanced_generation_profile_id: newProject.value.profile_id,
        confirmed_total_episodes: null,
        suggested_total_episodes: null,
        total_episodes: null,
        episode_count_status: 'unconfirmed',
        episode_count_confirmation_source: '',
        episode_count_confirmed_at: '',
      },
    })
    showNewProjectModal.value = false
    projectsStore.upsertProject(data)
    toast.success(`项目「${data.name}」已创建`)
    openProject(data)
  } catch (e: any) {
    if (isTimeoutError(e) && await recoverCreatedProject(projectName)) return
    notifyApiError(toast.error, e, '创建失败')
  } finally {
    isCreating.value = false
  }
}

async function quickStart() {
  const prompt = quickStartPrompt.value.trim()
  if (!prompt) return
  const explicitEpisodeCount = extractExplicitEpisodeCount(prompt)
  const confirmedAt = explicitEpisodeCount ? new Date().toISOString() : ''
  isCreating.value = true
  try {
    const name = prompt.length > 20 ? prompt.slice(0, 20) + '...' : prompt
    const { data } = await projectsV2Api.create({
      name,
      description: prompt,
      project_type: '真人短剧',
      creation_mode: 'solo',
      config: {
        advanced_generation_mode: true,
        advanced_generation_profile_id: 'short_drama',
        confirmed_total_episodes: explicitEpisodeCount || null,
        suggested_total_episodes: null,
        total_episodes: explicitEpisodeCount || null,
        episode_count_status: explicitEpisodeCount ? 'confirmed' : 'unconfirmed',
        episode_count_confirmation_source: explicitEpisodeCount ? 'quick_start_prompt' : '',
        episode_count_confirmed_at: confirmedAt,
      },
    })
    projectsStore.upsertProject(data)
    toast.success('项目已创建，正在进入创作空间...')
    router.push(`/projects/${data.id}/workspace?tab=chat&prompt=${encodeURIComponent(prompt)}`)
  } catch (e: any) {
    const name = prompt.length > 20 ? prompt.slice(0, 20) + '...' : prompt
    if ((isTimeoutError(e) || isDuplicateNameError(e)) && await recoverCreatedProject(name, prompt)) return
    notifyApiError(toast.error, e, '创建失败')
  } finally {
    isCreating.value = false
  }
}

async function deleteProject(project: ProjectV2) {
  if (!confirm(`确认删除项目「${project.name}」？此操作不可撤销。`)) return
  try {
    await projectsV2Api.delete(project.id)
    toast.success(`项目已删除`)
    projectsStore.removeProject(project.id)
  } catch (e) {
    toast.error('删除失败')
  }
}

function openProject(project: ProjectV2, query = '') {
  if (project.creation_mode === 'collab') {
    const sectionQuery = query || (projectListMode.value === 'collab' ? '?section=tasks' : '')
    router.push(`/projects/${project.id}/showrunner${sectionQuery}`)
    return
  }
  router.push(`/projects/${project.id}/workspace${query}`)
}

async function acceptInvite(invite: ProjectInvite) {
  try {
    await collaborationApi.acceptInvite(invite.id)
    toast.success('已接受协作邀请')
    await loadPendingInvites()
    await projectsStore.fetchProjects(true)
    const acceptedProject = projectsStore.findById(invite.project_id)
    if (acceptedProject) {
      router.push(`/projects/${acceptedProject.id}/showrunner?section=tasks`)
      return
    }
    projectListMode.value = 'collab'
  } catch (e) {
    notifyApiError(toast.error, e, '接受邀请失败')
  }
}

async function rejectInvite(invite: ProjectInvite) {
  try {
    await collaborationApi.rejectInvite(invite.id)
    toast.success('已拒绝协作邀请')
    await loadPendingInvites()
  } catch (e) {
    notifyApiError(toast.error, e, '拒绝邀请失败')
  }
}

function getProjectTotalEpisodes(project: ProjectV2) {
  return Math.max(0, Math.round(Number(project.config?.confirmed_total_episodes || project.total_episodes || 0)))
}

function getCompletedEpisodes(project: ProjectV2) {
  return Math.max(0, Math.round(Number(project.completed_episodes || 0)))
}

function getProgressPercent(project: ProjectV2) {
  const totalEpisodes = getProjectTotalEpisodes(project)
  if (!totalEpisodes) return 0
  return Math.max(0, Math.min(100, Math.round((getCompletedEpisodes(project) / totalEpisodes) * 100)))
}

function getProgressStage(project: ProjectV2) {
  const pct = getProgressPercent(project)
  if (getCompletedEpisodes(project) > 0) return { label: '写作中', color: 'text-emerald-500' }
  if (pct === 0) return { label: '刚刚创建', color: 'text-muted-foreground' }
  if (pct < 20) return { label: '脑暴中', color: 'text-blue-500' }
  if (pct < 50) return { label: '大纲完成', color: 'text-amber-500' }
  if (pct < 80) return { label: '角色设计中', color: 'text-purple-500' }
  return { label: '写作中', color: 'text-emerald-500' }
}

function formatDate(dateStr: string) {
  const d = new Date(dateStr)
  const now = new Date()
  const diff = now.getTime() - d.getTime()
  const hours = Math.floor(diff / 3600000)
  if (hours < 1) return '刚刚'
  if (hours < 24) return `${hours}小时前`
  const days = Math.floor(hours / 24)
  if (days < 7) return `${days}天前`
  return d.toLocaleDateString('zh-CN')
}
</script>

<template>
  <div class="h-[calc(100vh-3.5rem)] overflow-auto bg-gradient-to-br from-background via-background to-primary/5">
    <div class="max-w-6xl mx-auto px-6 py-10">

      <!-- 顶部标题区 -->
      <div class="mb-10">
        <h1 class="text-4xl font-bold tracking-tight mb-2">
          创作你的下一个
          <span class="bg-gradient-to-r from-primary to-purple-500 bg-clip-text text-transparent">爆款短剧</span>
        </h1>
        <p class="text-muted-foreground text-lg">AI驱动的完整剧本创作工作流，从灵感到成品</p>
      </div>

      <!-- 快速开始输入框 -->
      <div class="bg-card border rounded-2xl p-6 mb-10 shadow-sm">
        <div class="flex gap-3">
          <div class="relative flex-1">
            <Wand2 class="absolute left-4 top-1/2 -translate-y-1/2 h-5 w-5 text-muted-foreground" />
            <Input
              v-model="quickStartPrompt"
              placeholder="描述你的故事想法，AI帮你一键创建项目并开始创作..."
              class="h-14 pl-12 pr-4 text-base rounded-xl border-muted bg-muted/30"
              @keyup.enter="quickStart"
            />
          </div>
          <Button
            size="lg"
            class="h-14 px-8 rounded-xl font-semibold bg-gradient-to-r from-primary to-purple-600 hover:opacity-90 transition-opacity"
            :disabled="isCreating || !quickStartPrompt.trim()"
            @click="quickStart"
          >
            <Sparkles class="mr-2 h-5 w-5" />
            {{ isCreating ? '创建中...' : '一键开始创作' }}
          </Button>
        </div>
        <p class="text-xs text-muted-foreground mt-3 pl-1">
          或者选择下方已有项目继续创作
        </p>
      </div>

      <!-- 项目列表区 -->
      <div class="flex items-center justify-between mb-6">
        <div class="space-y-3">
          <div class="flex items-center gap-3">
            <h2 class="text-xl font-semibold">
              {{ projectListMode === 'pending' ? '待接受' : projectListMode === 'collab' ? '协作项目' : '我的项目' }}
            </h2>
            <Badge variant="secondary">{{ projectListMode === 'pending' ? pendingInvites.length : filteredProjects.length }}</Badge>
          </div>
          <div class="inline-flex rounded-lg border bg-card p-1">
            <button
              class="rounded-md px-3 py-1.5 text-sm transition-colors"
              :class="projectListMode === 'mine' ? 'bg-primary text-primary-foreground' : 'text-muted-foreground hover:bg-muted'"
              @click="projectListMode = 'mine'"
            >
              我的项目
            </button>
            <button
              class="rounded-md px-3 py-1.5 text-sm transition-colors"
              :class="projectListMode === 'collab' ? 'bg-primary text-primary-foreground' : 'text-muted-foreground hover:bg-muted'"
              @click="projectListMode = 'collab'"
            >
              协作项目
            </button>
            <button
              class="rounded-md px-3 py-1.5 text-sm transition-colors"
              :class="projectListMode === 'pending' ? 'bg-primary text-primary-foreground' : 'text-muted-foreground hover:bg-muted'"
              @click="projectListMode = 'pending'"
            >
              待接受
            </button>
          </div>
        </div>
        <div class="flex items-center gap-3">
          <div class="relative">
            <Search class="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
            <Input v-model="searchQuery" placeholder="搜索项目..." class="pl-9 w-52 h-9" :disabled="projectListMode === 'pending'" />
          </div>
          <Button @click="() => openNewProjectModal()" class="gap-2">
            <Plus class="h-4 w-4" />
            新建项目
          </Button>
        </div>
      </div>

      <!-- 错误提示 -->
      <div v-if="loadError" class="mb-4 rounded-xl border border-amber-500/40 bg-amber-500/10 text-amber-700 dark:text-amber-300 px-4 py-3 text-sm flex items-center justify-between gap-3">
        <span>{{ loadError }}</span>
        <Button size="sm" variant="outline" @click="loadProjects">重试</Button>
      </div>

      <!-- 加载状态 -->
      <div v-if="isLoading && projectListMode !== 'pending'" class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        <div v-for="i in 3" :key="i" class="h-48 bg-card border rounded-2xl animate-pulse" />
      </div>

      <div v-else-if="projectListMode === 'pending' && pendingInvites.length === 0" class="text-center py-16 text-muted-foreground">
        暂无待接受邀请
      </div>

      <div v-else-if="projectListMode === 'pending'" class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        <div
          v-for="invite in pendingInvites"
          :key="invite.id"
          class="bg-card border rounded-2xl p-5 shadow-sm"
        >
          <div class="flex items-start justify-between gap-3">
            <div>
              <div class="flex items-center gap-2">
                <Users class="h-4 w-4 text-primary" />
                <h3 class="font-semibold">接受邀请</h3>
              </div>
              <p class="mt-2 text-sm text-muted-foreground">
                {{ invite.invited_by_name || '项目负责人' }} 邀请你加入项目
              </p>
            </div>
            <Badge variant="outline">{{ invite.role }}</Badge>
          </div>
          <div class="mt-4 space-y-2 text-sm">
            <div class="flex justify-between gap-3">
              <span class="text-muted-foreground">法律身份</span>
              <span class="font-medium">{{ invite.legal_identity }}</span>
            </div>
            <div class="flex justify-between gap-3">
              <span class="text-muted-foreground">权限范围</span>
              <span class="text-right">{{ invite.permissions.join(' / ') }}</span>
            </div>
            <div class="flex justify-between gap-3">
              <span class="text-muted-foreground">下载权限</span>
              <span>{{ invite.allow_download ? '允许' : '不允许' }}</span>
            </div>
            <div class="flex justify-between gap-3">
              <span class="text-muted-foreground">有效期</span>
              <span>{{ invite.expires_at ? new Date(invite.expires_at).toLocaleDateString('zh-CN') : '-' }}</span>
            </div>
          </div>
          <div class="mt-5 flex gap-2">
            <Button size="sm" class="flex-1 gap-1.5" @click="acceptInvite(invite)">
              <Check class="h-4 w-4" />
              接受
            </Button>
            <Button size="sm" variant="outline" class="flex-1 gap-1.5" @click="rejectInvite(invite)">
              <X class="h-4 w-4" />
              拒绝
            </Button>
          </div>
        </div>
      </div>

      <!-- 空状态 -->
      <div v-else-if="filteredProjects.length === 0 && !searchQuery" class="text-center py-20">
        <div class="w-20 h-20 rounded-2xl bg-primary/10 flex items-center justify-center mx-auto mb-4">
          <Film class="h-10 w-10 text-primary" />
        </div>
        <h3 class="text-xl font-semibold mb-2">还没有项目</h3>
        <p class="text-muted-foreground mb-6">在上方输入你的故事想法，一键创建第一个项目</p>
        <Button @click="() => openNewProjectModal()" size="lg" class="gap-2">
          <Plus class="h-5 w-5" />
          新建项目
        </Button>
      </div>

      <!-- 搜索无结果 -->
      <div v-else-if="filteredProjects.length === 0" class="text-center py-16 text-muted-foreground">
        没有找到匹配"{{ searchQuery }}"的项目
      </div>

      <!-- 项目卡片网格 -->
      <div v-else class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        <!-- 新建项目卡片 -->
        <button
          class="h-48 border-2 border-dashed rounded-2xl flex flex-col items-center justify-center gap-3 text-muted-foreground hover:text-primary hover:border-primary/50 hover:bg-primary/5 transition-all group"
          @click="() => openNewProjectModal()"
        >
          <div class="w-12 h-12 rounded-xl bg-muted group-hover:bg-primary/10 flex items-center justify-center transition-colors">
            <Plus class="h-6 w-6" />
          </div>
          <span class="font-medium">新建项目</span>
        </button>

        <!-- 项目卡片 -->
        <div
          v-for="project in filteredProjects"
          :key="project.id"
          class="bg-card border rounded-2xl p-5 hover:shadow-lg hover:border-primary/30 transition-all cursor-pointer group relative overflow-hidden"
          @click="openProject(project)"
        >
          <!-- 背景装饰 -->
          <div class="absolute top-0 right-0 w-32 h-32 bg-gradient-to-br from-primary/5 to-purple-500/5 rounded-bl-full" />

          <!-- 头部 -->
          <div class="flex items-start justify-between mb-3 relative">
            <div class="flex-1 min-w-0">
              <h3 class="font-semibold text-lg truncate group-hover:text-primary transition-colors">
                {{ project.name }}
              </h3>
              <p v-if="project.description" class="text-xs text-muted-foreground mt-1 line-clamp-2">
                {{ project.description }}
              </p>
            </div>
            <button
              class="ml-2 shrink-0 opacity-0 group-hover:opacity-100 transition-opacity text-muted-foreground hover:text-destructive p-1 rounded"
              @click.stop="deleteProject(project)"
            >
              <Trash2 class="h-4 w-4" />
            </button>
          </div>

          <!-- 标签 -->
          <div class="flex flex-wrap gap-1.5 mb-4">
            <Badge v-if="project.genre_main" variant="secondary" class="text-xs">
              {{ project.genre_main }}
            </Badge>
            <Badge variant="secondary" class="text-xs">
              {{ project.creation_mode === 'collab' ? '多人协作' : '独立完成' }}
            </Badge>
            <Badge v-if="project.rights_capture_enabled" variant="outline" class="text-xs">
              确权资料沉淀
            </Badge>
            <Badge variant="outline" class="text-xs" :class="getProgressStage(project).color">
              {{ getProgressStage(project).label }}
            </Badge>
          </div>

          <!-- 进度条 -->
          <div class="mb-4">
            <div class="flex items-center justify-between text-xs text-muted-foreground mb-1.5">
              <span>创作进度</span>
              <span>{{ getCompletedEpisodes(project) }}/{{ getProjectTotalEpisodes(project) }}集 · {{ getProgressPercent(project) }}%</span>
            </div>
            <div class="h-1.5 rounded-full bg-muted overflow-hidden">
              <div
                class="h-1.5 rounded-full bg-gradient-to-r from-primary to-purple-500 transition-all"
                :style="{ width: `${Math.max(getProgressPercent(project), 3)}%` }"
              />
            </div>
          </div>

          <!-- 底部 -->
          <div class="flex items-center justify-between text-xs text-muted-foreground">
            <div class="flex items-center gap-1.5">
              <Clock class="h-3.5 w-3.5" />
              {{ formatDate(project.updated_at) }}
            </div>
            <div class="flex items-center gap-1 text-primary font-medium opacity-0 group-hover:opacity-100 transition-opacity">
              <Play class="h-3.5 w-3.5 fill-current" />
              {{ project.creation_mode === 'collab' ? '进入工作台' : '继续创作' }}
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- 新建项目弹窗（自定义 overlay） -->
    <Transition name="modal">
      <div v-if="showNewProjectModal" class="fixed inset-0 z-50 flex items-center justify-center p-4">
        <div class="absolute inset-0 bg-black/50 backdrop-blur-sm" @click="showNewProjectModal = false" />
        <div class="relative z-10 w-full max-w-md bg-background border rounded-2xl shadow-2xl p-6">
          <div class="mb-5">
            <h2 class="text-xl font-bold">新建创作项目</h2>
            <p class="text-sm text-muted-foreground mt-1">创建一个新的短剧剧本创作项目</p>
          </div>

          <div class="space-y-4">
            <div>
              <label class="text-sm font-medium mb-1.5 block">创作模式</label>
              <div class="grid grid-cols-2 gap-2">
                <button
                  class="rounded-lg border px-4 py-3 text-center text-sm font-medium transition-all"
                  :class="newProject.creation_mode === 'solo'
                    ? 'border-primary bg-primary/10 text-primary'
                    : 'border-border hover:bg-muted'"
                  @click="newProject.creation_mode = 'solo'"
                >
                  独立完成
                </button>
                <button
                  class="rounded-lg border px-4 py-3 text-center text-sm font-medium transition-all"
                  :class="newProject.creation_mode === 'collab'
                    ? 'border-primary bg-primary/10 text-primary'
                    : 'border-border hover:bg-muted'"
                  @click="newProject.creation_mode = 'collab'"
                >
                  多人协作
                </button>
              </div>
            </div>

            <div>
              <label class="text-sm font-medium mb-1.5 block">创作形态</label>
              <div class="grid grid-cols-2 gap-2">
                <button
                  v-for="profile in profileOptions"
                  :key="profile.id"
                  class="rounded-lg border px-3 py-2 text-left text-sm transition-all"
                  :class="newProject.profile_id === profile.id
                    ? 'border-primary bg-primary/10 text-primary'
                    : 'border-border hover:bg-muted'"
                  @click="selectProfile(profile)"
                >
                  <span class="block font-medium">{{ profile.label }}</span>
                  <span class="mt-0.5 block text-xs text-muted-foreground">
                    {{ profile.id === 'short_drama' ? '当前主流程' : '科研链路已接入' }}
                  </span>
                </button>
              </div>
            </div>

            <div>
              <label class="text-sm font-medium mb-1.5 block">项目名称</label>
              <Input
                v-model="newProject.name"
                placeholder="例如：总裁的秘密恋人"
                class="h-11"
                @keyup.enter="createProject"
              />
            </div>

            <div>
              <label class="text-sm font-medium mb-1.5 block">
                主题类型
                <span class="text-muted-foreground font-normal ml-1">（可选）</span>
              </label>
              <div class="flex flex-wrap gap-2">
                <button
                  v-for="genre in genreOptions"
                  :key="genre"
                  class="px-3 py-1.5 rounded-lg border text-sm transition-all"
                  :class="newProject.genre_main === genre
                    ? 'bg-primary text-primary-foreground border-primary'
                    : 'hover:bg-muted border-border'"
                  @click="newProject.genre_main = newProject.genre_main === genre ? '' : genre"
                >
                  {{ genre }}
                </button>
              </div>
            </div>

            <div>
              <label class="text-sm font-medium mb-1.5 block">
                简单描述
                <span class="text-muted-foreground font-normal ml-1">（可选）</span>
              </label>
              <textarea
                v-model="newProject.description"
                :placeholder="`简单说说你的${selectedProfile()?.label || '项目'}想法...`"
                class="w-full min-h-[80px] rounded-lg border bg-background px-3 py-2 text-sm resize-none focus:outline-none focus:ring-2 focus:ring-ring"
              />
            </div>
          </div>

          <div class="flex gap-3 mt-6">
            <Button variant="outline" class="flex-1" @click="showNewProjectModal = false">
              取消
            </Button>
            <Button
              class="flex-1 bg-gradient-to-r from-primary to-purple-600 hover:opacity-90"
              :disabled="isCreating"
              @click="createProject"
            >
              <Sparkles class="mr-2 h-4 w-4" />
              {{ isCreating ? '创建中...' : '创建并开始' }}
            </Button>
          </div>
        </div>
      </div>
    </Transition>
  </div>
</template>

<style scoped>
.modal-enter-active,
.modal-leave-active {
  transition: opacity 0.2s ease;
}
.modal-enter-from,
.modal-leave-to {
  opacity: 0;
}
</style>
