<script setup lang="ts">
import { computed, ref, onMounted } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { setupApi } from '@/api/client'
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@/components/ui/tooltip'
import { Button } from '@/components/ui/button'
import {
  ScrollText,
  Settings,
  FolderOpen,
  FlaskConical,
} from 'lucide-vue-next'

const router = useRouter()
const route = useRoute()
const auth = useAuthStore()

const showUrlMissing = ref(false)

// 路由守卫已经查过 setup 初始化状态。这里只是检查 external_url 是否配置，
// 用 then/catch 不 await，避免阻塞页面渲染。
onMounted(() => {
  setupApi.status()
    .then(({ data }) => {
      if (data.initialized && !data.has_external_url) {
        showUrlMissing.value = true
      }
    })
    .catch(() => { /* 静默 */ })
})

const primaryMenuItems = [
  { title: '我的项目', icon: FolderOpen, path: '/projects' },
  { title: '灵感实验室', icon: FlaskConical, path: '/lab' },
]

const secondaryMenuItems = computed(() => (
  auth.isAdminAuthenticated
    ? [{ title: '活动日志', icon: ScrollText, path: '/logs' }]
    : []
))

const allMenuItems = computed(() => [...primaryMenuItems, ...secondaryMenuItems.value])

function handleLogout() {
  auth.logout()
  router.push('/login')
}
</script>

<template>
  <TooltipProvider>
    <div class="flex h-screen bg-background">
      <!-- 左侧细条导航栏 -->
      <aside class="w-16 border-r bg-card flex flex-col items-center py-4 shrink-0">
        <!-- Logo -->
        <div class="mb-6">
          <div class="flex h-10 w-10 items-center justify-center rounded-xl bg-primary text-primary-foreground text-base font-bold shadow-sm">
            M
          </div>
        </div>

        <!-- 主导航 -->
        <nav class="flex-1 flex flex-col items-center gap-1">
          <Tooltip v-for="item in primaryMenuItems" :key="item.path">
            <TooltipTrigger as-child>
              <router-link
                :to="item.path"
                class="flex h-11 w-11 items-center justify-center rounded-lg transition-all duration-200"
                :class="route.path.startsWith(item.path)
                  ? 'bg-primary/10 text-primary'
                  : 'text-muted-foreground hover:bg-muted hover:text-foreground'"
              >
                <component :is="item.icon" class="h-5 w-5" />
              </router-link>
            </TooltipTrigger>
            <TooltipContent side="right">
              {{ item.title }}
            </TooltipContent>
          </Tooltip>

          <Tooltip v-for="item in secondaryMenuItems" :key="item.path">
            <TooltipTrigger as-child>
              <router-link
                :to="item.path"
                class="flex h-11 w-11 items-center justify-center rounded-lg transition-all duration-200"
                :class="route.path.startsWith(item.path)
                  ? 'bg-primary/10 text-primary'
                  : 'text-muted-foreground hover:bg-muted hover:text-foreground'"
              >
                <component :is="item.icon" class="h-5 w-5" />
              </router-link>
            </TooltipTrigger>
            <TooltipContent side="right">
              {{ item.title }}
            </TooltipContent>
          </Tooltip>
        </nav>

        <!-- 底部功能 -->
        <div class="flex flex-col items-center gap-1 mt-auto">
          <!-- 设置/账号 -->
          <Tooltip>
            <TooltipTrigger as-child>
              <router-link
                to="/settings"
                class="flex h-11 w-11 items-center justify-center rounded-lg transition-all duration-200"
                :class="route.path === '/settings'
                  ? 'bg-primary/10 text-primary'
                  : 'text-muted-foreground hover:bg-muted hover:text-foreground'"
              >
                <Settings class="h-5 w-5" />
              </router-link>
            </TooltipTrigger>
            <TooltipContent side="right">
              设置
            </TooltipContent>
          </Tooltip>
        </div>
      </aside>

      <!-- 主内容区 -->
      <div class="flex-1 flex flex-col min-w-0">
        <header class="flex h-14 items-center gap-3 border-b px-4 bg-background/80 backdrop-blur-md sticky top-0 z-10">
          <h1 class="text-sm font-medium">
            {{ route.path.startsWith('/projects/') && route.path.includes('/workspace')
              ? '创作空间'
              : [...allMenuItems, { title: '设置', path: '/settings' }].find(i => route.path.startsWith(i.path))?.title || '墨戏生花' }}
          </h1>
        </header>
        <main class="flex-1 overflow-auto">
          <router-view />
        </main>
      </div>
    </div>

    <!-- 服务地址未配置提示弹窗 -->
    <Teleport to="body">
      <Transition name="fade">
        <div v-if="showUrlMissing" class="fixed inset-0 z-50 flex items-center justify-center">
          <div class="absolute inset-0 bg-black/40 backdrop-blur-sm" @click="showUrlMissing = false" />
          <div
            class="relative z-10 w-full max-w-sm rounded-2xl border bg-background/95 backdrop-blur-xl p-6 shadow-lg animate-in fade-in zoom-in-95 duration-200">
            <div class="space-y-2 text-center">
              <div class="text-3xl mb-2">⚠️</div>
              <h2 class="text-lg font-semibold">请配置服务访问地址</h2>
              <p class="text-sm text-muted-foreground">
                墨戏生花 需要一个外网可访问的地址，用于：
              </p>
              <ul class="text-sm text-muted-foreground text-left ml-4 list-disc space-y-1">
                <li>Agent 下载工具脚本</li>
                <li>Agent 对接任务系统</li>
                <li>生成 Agent 入驻 Prompt</li>
              </ul>
              <p class="text-xs text-muted-foreground mt-2">
                示例：https://moss.example.com
              </p>
            </div>
            <div class="mt-6 flex gap-3">
              <Button variant="outline" class="flex-1" @click="showUrlMissing = false">稍后再说</Button>
              <Button class="flex-1" @click="showUrlMissing = false; router.push('/settings')">前往设置</Button>
            </div>
          </div>
        </div>
      </Transition>
    </Teleport>
  </TooltipProvider>
</template>

<style scoped>
.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.2s ease;
}

.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}
</style>
