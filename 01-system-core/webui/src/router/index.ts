import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { setupApi } from '@/api/client'

// 缓存初始化状态，避免每次路由跳转都请求
let _setupChecked = false
let _isInitialized = true // 默认 true，避免闪烁

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes: [
    {
      path: '/setup',
      name: 'setup',
      component: () => import('@/views/SetupView.vue'),
      meta: { requiresAuth: false },
    },
    {
      path: '/feed',
      name: 'feed',
      component: () => import('@/views/FeedView.vue'),
      meta: { requiresAuth: false },
    },
    {
      path: '/login',
      name: 'login',
      component: () => import('@/views/LoginView.vue'),
      meta: { requiresAuth: false },
    },
    {
      path: '/moxi-admin',
      name: 'moxi-admin',
      component: () => import('@/views/MoxiAdminView.vue'),
      meta: { requiresAuth: false },
    },
    {
      path: '/',
      redirect: '/login',
      meta: { requiresAuth: false },
    },
    {
      path: '/',
      component: () => import('@/views/AppLayout.vue'),
      meta: { requiresAuth: true },
      children: [
        // ── 新：项目中心 ──
        {
          path: 'projects',
          name: 'projects',
          component: () => import('@/views/ProjectsView.vue'),
        },
        {
          path: 'projects/:projectId/workspace',
          name: 'project-workspace',
          component: () => import('@/views/ProjectWorkspaceView.vue'),
        },
        {
          path: 'projects/:projectId/showrunner',
          name: 'project-showrunner',
          component: () => import('@/views/ShowrunnerWorkspaceView.vue'),
        },
        // ── 兼容旧入口：统一重定向到当前主工作台 ──
        {
          path: 'tasks',
          name: 'tasks',
          redirect: '/projects',
        },
        {
          path: 'create',
          name: 'create',
          redirect: '/projects',  // 已由"我的项目"替代，重定向避免旧链接404
        },
        {
          path: 'outline-editor',
          name: 'outline-editor',
          component: () => import('@/views/OutlineEditorView.vue'),
        },
        {
          path: 'outline-editor/:projectId',
          name: 'outline-editor-with-project',
          component: () => import('@/views/OutlineEditorView.vue'),
        },
        {
          path: 'script-writing/:projectId',
          name: 'script-writing',
          redirect: to => `/projects/${to.params.projectId}/workspace?tab=script`,
        },
        {
          path: 'lab',
          name: 'lab',
          component: () => import('@/views/LabView.vue'),
        },
        {
          path: 'advanced-generation',
          name: 'advanced-generation',
          redirect: '/projects',  // 前台只保留项目工作区正式科研生成链路
        },
        {
          path: 'logs',
          name: 'logs',
          component: () => import('@/views/LogsView.vue'),
          meta: { requiresAdmin: true },
        },
        {
          path: 'settings',
          name: 'settings',
          component: () => import('@/views/SettingsView.vue'),
        },
      ],
    },
  ],
})

// 路由守卫：初始化检查 + 登录检查
router.beforeEach(async (to) => {
  const auth = useAuthStore()

  // 检查初始化状态（仅一次）
  if (!_setupChecked) {
    try {
      const { data } = await setupApi.status()
      _isInitialized = data.initialized
    } catch {
      // 接口不存在或出错，视为已初始化（兼容旧版本）
      _isInitialized = true
    }
    _setupChecked = true
  }

  // 未初始化 → 强制跳转 /setup
  if (!_isInitialized && to.name !== 'setup') {
    return { name: 'setup' }
  }
  // 已初始化 → 不允许访问 /setup
  if (_isInitialized && to.name === 'setup') {
    return { name: 'login' }
  }

  // 原有的登录检查：本地保存的前台用户会话要先向后端验票，
  // 避免过期或已停用 session 直接放进项目首页。
  if (to.meta.requiresAuth !== false || to.name === 'login') {
    await auth.ensureUserSessionValid()
  }
  if (to.meta.requiresAuth !== false && !auth.isAuthenticated) {
    return { name: 'login' }
  }
  if (to.meta.requiresAdmin && !auth.isAdminAuthenticated) {
    return { name: 'projects' }
  }
  if (to.meta.requiresAdvancedGeneration && !auth.advancedGenerationEnabled) {
    return { name: 'projects' }
  }
})

export default router

/** 重置初始化状态缓存（初始化完成后调用） */
export function resetSetupCache() {
  _setupChecked = false
  _isInitialized = true
}
