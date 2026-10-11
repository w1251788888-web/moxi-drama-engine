<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, nextTick } from 'vue'
import { feedApi } from '@/api/client'
import { translateLog } from '@/composables/useActivityFeed'
import type { FeedLog, TranslatedActivity, AgentSummary } from '@/composables/useActivityFeed'
import ActivityCard from '@/components/feed/ActivityCard.vue'
import FeedAgentList from '@/components/feed/FeedAgentList.vue'
import { Button } from '@/components/ui/button'
import { Separator } from '@/components/ui/separator'
import {
    Sheet, SheetContent, SheetHeader, SheetTitle, SheetTrigger,
} from '@/components/ui/sheet'
import { ChevronLeft, ChevronRight, Inbox, Loader2, Lock, Pause, Play, RefreshCw, Users, X } from 'lucide-vue-next'

const enabled = ref<boolean | null>(null)
const loading = ref(true)
const activities = ref<TranslatedActivity[]>([])
const agentSummaries = ref<AgentSummary[]>([])
const flashingAgentIds = ref<Set<string>>(new Set())
const selectedAgentId = ref<string | null>(null)
const paused = ref(false)
const autoPaused = ref(false)
const newIds = ref<Set<string>>(new Set())
const mobileSheetOpen = ref(false)
const sidebarCollapsed = ref(false)
const timelineRef = ref<HTMLElement | null>(null)
const feedListKey = ref(0)

let pollTimer: ReturnType<typeof setInterval> | null = null
let autoTimer: ReturnType<typeof setTimeout> | null = null
const AUTO_PAUSE_MS = 5 * 60 * 1000 // 5 分钟

const filteredActivities = computed(() => {
    if (!selectedAgentId.value) return activities.value
    return activities.value.filter((a) => a.agentId === selectedAgentId.value)
})

const selectedAgentName = computed(() => {
    if (!selectedAgentId.value) return null
    return agentSummaries.value.find((a) => a.id === selectedAgentId.value)?.name ?? null
})

// ============================================================
// 数据加载
// ============================================================

async function checkStatus() {
    try {
        const res = await feedApi.status()
        enabled.value = res.data.enabled
    } catch { enabled.value = false }
}

async function loadAgentSummaries() {
    try {
        const res = await feedApi.agentSummary()
        agentSummaries.value = res.data
    } catch { /* ignore */ }
}

async function loadLogs(incremental = false) {
    try {
        const params: { after?: string; limit?: number } = { limit: 100 }
        if (incremental && activities.value.length > 0) {
            const ts = activities.value[0]?.timestamp
            if (ts) params.after = ts
        }

        const res = await feedApi.logs(params)
        const newLogs: FeedLog[] = res.data
        const translated = newLogs.map(translateLog)

        if (incremental && translated.length > 0) {
            const ids = new Set(translated.map((t) => t.id))
            newIds.value = ids
            setTimeout(() => { newIds.value = new Set() }, 3000)

            activities.value = [...translated, ...activities.value].slice(0, 300)

            const agentIds = new Set(translated.map((t) => t.agentId).filter(Boolean))
            flashingAgentIds.value = agentIds
            setTimeout(() => { flashingAgentIds.value = new Set() }, 2000)

            // 自动滚到顶部
            await nextTick()
            timelineRef.value?.scrollTo({ top: 0, behavior: 'smooth' })
        } else if (!incremental) {
            activities.value = translated
            feedListKey.value++
        }
    } catch { /* ignore */ }
}

async function init() {
    loading.value = true
    await checkStatus()
    if (enabled.value) {
        await Promise.all([loadAgentSummaries(), loadLogs(false)])
    }
    loading.value = false
}

function startPolling() {
    pollTimer = setInterval(() => {
        if (!paused.value && !autoPaused.value && enabled.value) {
            loadLogs(true)
            loadAgentSummaries()
        }
    }, 5000)

    // 5 分钟后自动暂停，不做任何判断
    autoTimer = setTimeout(() => {
        autoPaused.value = true
    }, AUTO_PAUSE_MS)
}

function resumeFromAutoPause() {
    autoPaused.value = false
    paused.value = false
    // 恢复后再给 5 分钟
    if (autoTimer) clearTimeout(autoTimer)
    autoTimer = setTimeout(() => {
        autoPaused.value = true
    }, AUTO_PAUSE_MS)
}

const switchingAgent = ref(false)

function handleSelectAgent(agentId: string | null) {
    if (agentId === selectedAgentId.value) {
        // 取消选中 — 无需骨架屏
        selectedAgentId.value = null
        mobileSheetOpen.value = false
        return
    }
    switchingAgent.value = true
    selectedAgentId.value = agentId
    mobileSheetOpen.value = false
    feedListKey.value++
    setTimeout(() => { switchingAgent.value = false }, 300)
}

onMounted(() => { init(); startPolling() })
onUnmounted(() => {
    if (pollTimer) clearInterval(pollTimer)
    if (autoTimer) clearTimeout(autoTimer)
})
</script>

<template>
    <div class="h-screen flex flex-col bg-background text-foreground">
        <!-- 加载 -->
        <div v-if="loading" class="flex-1 flex items-center justify-center">
            <Loader2 class="h-6 w-6 animate-spin text-muted-foreground" />
        </div>

        <!-- 未启用 -->
        <div v-else-if="!enabled"
            class="flex-1 flex flex-col items-center justify-center gap-3 text-muted-foreground/60 px-6">
            <Lock class="w-10 h-10 mb-1" />
            <p class="text-base font-semibold text-foreground/80">活动流展示页尚未开启</p>
            <p class="text-sm text-muted-foreground/50 text-center max-w-sm leading-relaxed">
                开启后，所有 Agent 的 API 活动将在此页面实时展示，
                无需登录即可查看。
            </p>
            <p class="text-xs text-muted-foreground/40 mt-1">在后台设置中开启，或修改 <code
                    class="bg-muted px-1.5 py-0.5 rounded text-[11px]">config.yaml → webui.public_feed: true</code></p>
        </div>

        <!-- 正常 -->
        <template v-else>
            <!-- 顶栏 -->
            <header class="shrink-0 flex items-center justify-between px-4 h-11 border-b border-border/40">
                <div class="flex items-center gap-2 min-w-0">
                    <div
                        class="flex h-6 w-6 items-center justify-center rounded-md bg-primary text-primary-foreground text-[10px] font-bold shrink-0">
                        F</div>
                    <span class="text-sm font-medium truncate">活动流</span>
                    <span class="text-[10px] text-muted-foreground/40 tabular-nums">{{ filteredActivities.length
                        }}</span>

                    <template v-if="selectedAgentName">
                        <Separator orientation="vertical" class="h-3 mx-0.5 opacity-30" />
                        <span class="text-[11px] text-muted-foreground truncate max-w-[100px]">{{ selectedAgentName
                            }}</span>
                        <button class="text-muted-foreground/40 hover:text-foreground" @click="selectedAgentId = null">
                            <X class="w-2.5 h-2.5" />
                        </button>
                    </template>
                </div>

                <div class="flex items-center gap-0.5">
                    <Button variant="ghost" size="icon" class="h-7 w-7" @click="paused = !paused">
                        <component :is="paused ? Play : Pause" class="w-3 h-3" />
                    </Button>
                    <Button variant="ghost" size="icon" class="h-7 w-7" @click="loadLogs(true)">
                        <RefreshCw class="w-3 h-3" />
                    </Button>

                    <!-- 手机端 Agent -->
                    <Sheet v-model:open="mobileSheetOpen">
                        <SheetTrigger as-child>
                            <Button variant="ghost" size="icon" class="h-7 w-7 lg:hidden">
                                <Users class="w-3 h-3" />
                            </Button>
                        </SheetTrigger>
                        <SheetContent side="bottom" class="max-h-[60vh] rounded-t-xl">
                            <SheetHeader>
                                <SheetTitle class="text-sm">Agents</SheetTitle>
                            </SheetHeader>
                            <div class="overflow-y-auto">
                                <FeedAgentList :agents="agentSummaries" :flashing-agent-ids="flashingAgentIds"
                                    :selected-agent-id="selectedAgentId" @select="handleSelectAgent" />
                            </div>
                        </SheetContent>
                    </Sheet>
                </div>
            </header>

            <!-- 主体 -->
            <div class="flex flex-1 min-h-0">
                <!-- 日志 -->
                <div ref="timelineRef" class="flex-1 overflow-y-auto p-4">
                    <div class="max-w-3xl mx-auto rounded-xl border border-border/40 bg-card overflow-hidden">
                        <!-- 切换加载 -->
                        <div v-if="switchingAgent" class="flex items-center justify-center py-16">
                            <Loader2 class="h-5 w-5 animate-spin text-muted-foreground" />
                        </div>

                        <template v-else>
                            <TransitionGroup name="feed-slide" tag="div" class="divide-y divide-border/30">
                                <ActivityCard v-for="(act, idx) in filteredActivities" :key="act.id" :activity="act"
                                    :is-new="newIds.has(act.id)" class="animate-slide-up"
                                    :style="{ animationDelay: `${Math.min(idx, 15) * 30}ms` }" />
                            </TransitionGroup>
                        </template>

                        <div v-if="!switchingAgent && filteredActivities.length === 0"
                            class="flex flex-col items-center justify-center py-20 text-muted-foreground/40">
                            <Inbox class="w-6 h-6 mb-2" />
                            <p class="text-xs">暂无活动记录</p>
                            <p class="text-[10px] mt-1 text-muted-foreground/30">Agent 发起 API 请求后，活动会自动出现在这里</p>
                        </div>
                    </div>
                </div>

                <!-- Agent 侧栏 (PC) — 右侧可折叠 -->
                <aside
                    class="hidden lg:flex flex-col shrink-0 border-l border-border/40 overflow-hidden transition-all duration-300 ease-in-out"
                    :class="sidebarCollapsed ? 'w-10' : 'w-[400px]'">
                    <!-- 折叠头 -->
                    <div class="flex items-center h-8 shrink-0"
                        :class="sidebarCollapsed ? 'justify-center' : 'px-3 justify-between'">
                        <span v-if="!sidebarCollapsed"
                            class="text-[10px] text-muted-foreground/40 font-medium uppercase tracking-wider">
                            Agents · {{ agentSummaries.length }}
                        </span>
                        <Button variant="ghost" size="icon" class="h-6 w-6"
                            @click="sidebarCollapsed = !sidebarCollapsed">
                            <component :is="sidebarCollapsed ? ChevronLeft : ChevronRight" class="w-3 h-3" />
                        </Button>
                    </div>
                    <!-- 内容 -->
                    <div v-if="!sidebarCollapsed" class="flex-1 overflow-y-auto">
                        <FeedAgentList :agents="agentSummaries" :flashing-agent-ids="flashingAgentIds"
                            :selected-agent-id="selectedAgentId" @select="handleSelectAgent" />
                    </div>
                </aside>
            </div>

            <!-- 底栏 -->
            <footer
                class="shrink-0 flex items-center justify-center gap-2 h-6 text-[10px] text-muted-foreground/30 border-t border-border/20">
                <span class="flex items-center gap-1">
                    <span class="inline-block w-1 h-1 rounded-full"
                        :class="(paused || autoPaused) ? 'bg-amber-400' : 'bg-emerald-400 animate-pulse'" />
                    {{ autoPaused ? '已自动暂停（5分钟未操作）' : paused ? '已暂停' : '实时更新中' }}
                </span>
                <template v-if="autoPaused">
                    <span>·</span>
                    <button class="text-primary hover:underline cursor-pointer" @click="resumeFromAutoPause">点击恢复</button>
                </template>
                <span>·</span>
                <span class="tabular-nums">{{ agentSummaries.length }} 个 Agent</span>
            </footer>
        </template>
    </div>
</template>

<style scoped>
.feed-slide-enter-active {
    transition: all 0.25s cubic-bezier(0.16, 1, 0.3, 1);
}

.feed-slide-enter-from {
    opacity: 0;
    transform: translateY(-8px);
}

@keyframes slide-up-fade-in {
    from {
        opacity: 0;
        transform: translateY(12px);
    }

    to {
        opacity: 1;
        transform: translateY(0);
    }
}

.animate-slide-up {
    animation: slide-up-fade-in 0.35s ease-out both;
}
</style>
