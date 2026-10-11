import { computed, ref, type Component, type ComputedRef } from 'vue'
import type { Router, RouteLocationNormalizedLoaded } from 'vue-router'
import { Archive, BookOpen, Download, FileText, MessageSquare, ShieldCheck, Users, Wand2 } from 'lucide-vue-next'
import { loadWorkspaceStorage, saveWorkspaceStorage } from '@/features/workspace/utils/workspaceStorage'

export type WorkspaceTabId = 'chat' | 'outline' | 'characters' | 'script' | 'compliance' | 'storyboard' | 'export' | 'legal-assets'

export type WorkspaceTab = {
  id: WorkspaceTabId
  label: string
  icon: Component
  tip: string
}

const WORKSPACE_TAB_ORDER: WorkspaceTabId[] = ['chat', 'outline', 'characters', 'script', 'compliance', 'storyboard', 'export', 'legal-assets']

export const workspaceTabs: WorkspaceTab[] = [
  { id: 'chat', label: '聊天脑暴', icon: MessageSquare, tip: '自由创作与AI问答' },
  { id: 'outline', label: '大纲编辑', icon: FileText, tip: '结构化故事框架' },
  { id: 'characters', label: '角色设计', icon: Users, tip: '人物设定与关系' },
  { id: 'script', label: '剧本写作', icon: BookOpen, tip: '分集分场写作' },
  { id: 'compliance', label: '合规审核', icon: ShieldCheck, tip: '逐集标注与人工审核' },
  { id: 'storyboard', label: '分镜提示词', icon: Wand2, tip: '为外部 AI 视频平台生成分镜与提示词文本（不生成图像/视频）' },
  { id: 'export', label: '导出生成', icon: Download, tip: '多格式导出' },
  { id: 'legal-assets', label: '法律资产包', icon: Archive, tip: '确权资料与正式交付包' },
]

function normalizeTab(value: unknown): WorkspaceTabId {
  return WORKSPACE_TAB_ORDER.includes(value as WorkspaceTabId) ? value as WorkspaceTabId : 'chat'
}

export function useWorkspaceTabs(options: {
  route: RouteLocationNormalizedLoaded
  router: Router
  projectId: ComputedRef<string>
}) {
  const activeTab = ref<WorkspaceTabId>(normalizeTab(options.route.query.tab))
  const completedTabs = ref<Set<WorkspaceTabId>>(new Set())

  function loadTabState() {
    const saved = loadWorkspaceStorage('completedTabs', options.projectId.value)
    if (!saved) return
    try {
      completedTabs.value = new Set(JSON.parse(saved).map(normalizeTab))
    } catch {}
  }

  function saveTabState() {
    saveWorkspaceStorage('completedTabs', options.projectId.value, JSON.stringify([...completedTabs.value]))
  }

  function markTabComplete(tabId: WorkspaceTabId) {
    completedTabs.value.add(tabId)
    saveTabState()
  }

  const progressPercent = computed(() => {
    let done = 0
    for (const tab of WORKSPACE_TAB_ORDER) {
      if (completedTabs.value.has(tab)) done++
      else break
    }
    return Math.round((done / WORKSPACE_TAB_ORDER.length) * 100)
  })

  function switchTab(id: WorkspaceTabId) {
    activeTab.value = id
    options.router.replace({ query: { ...options.route.query, tab: id } })
  }

  function goToNextTab() {
    const index = WORKSPACE_TAB_ORDER.indexOf(activeTab.value)
    if (index < WORKSPACE_TAB_ORDER.length - 1) {
      markTabComplete(activeTab.value)
      const nextTab = WORKSPACE_TAB_ORDER[index + 1]
      if (nextTab) switchTab(nextTab)
    }
  }

  return {
    tabs: workspaceTabs,
    activeTab,
    completedTabs,
    progressPercent,
    loadTabState,
    markTabComplete,
    switchTab,
    goToNextTab,
  }
}
