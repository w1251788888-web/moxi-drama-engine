<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useDebounceFn } from '@vueuse/core'
import {
    adminAgentApi,
    adminLogApi,
    type AdminActivityLogItem,
    type AdminAgentItem,
    type AdminPageResponse,
} from '@/api/client'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import {
    Search,
    RefreshCw,
    Loader2,
    AlertCircle,
    FileText,
    ArrowLeft,
    ArrowRight,
    ChevronDown,
    ChevronUp,
} from 'lucide-vue-next'

// ─── 状态 ───

const PAGE_SIZE = 20

const keyword = ref('')
const actionFilter = ref('all')
const agentFilter = ref('all')
const page = ref(1)

const loading = ref(false)
const error = ref('')
let requestId = 0

const pageData = ref<AdminPageResponse<AdminActivityLogItem>>(createEmptyPage())
const visibleLogItems = computed(() => pageData.value.items.slice(0, PAGE_SIZE))
const agentList = ref<AdminAgentItem[]>([])

const expandedIds = reactive(new Set<string>())

// ─── 选项 ───

const actionOptions = [
    { value: 'all', label: '全部类型' },
    { value: 'plan', label: '规划' },
    { value: 'coding', label: '执行' },
    { value: 'delivery', label: '交付' },
    { value: 'review', label: '审查' },
    { value: 'patrol', label: '巡查' },
    { value: 'reflection', label: '自省' },
    { value: 'blocked', label: '阻塞' },
]

// ─── 工具函数 ───

function createEmptyPage<T = unknown>(): AdminPageResponse<T> {
    return { items: [] as T[], total: 0, page: 1, page_size: PAGE_SIZE, total_pages: 1, has_more: false }
}

function formatAction(action: string) {
    return ({
        plan: '规划', coding: '执行', delivery: '交付', review: '审查',
        patrol: '巡查', reflection: '自省', blocked: '阻塞',
    } as Record<string, string>)[action] ?? action
}

function getActionBadgeClass(action: string) {
    return ({
        plan: 'border-violet-200 bg-violet-50 text-violet-700',
        coding: 'border-sky-200 bg-sky-50 text-sky-700',
        delivery: 'border-emerald-200 bg-emerald-50 text-emerald-700',
        review: 'border-amber-200 bg-amber-50 text-amber-700',
        patrol: 'border-teal-200 bg-teal-50 text-teal-700',
        reflection: 'border-indigo-200 bg-indigo-50 text-indigo-700',
        blocked: 'border-rose-200 bg-rose-50 text-rose-700',
    } as Record<string, string>)[action] ?? 'border-border bg-muted text-muted-foreground'
}

function getActionDotClass(action: string) {
    return ({
        plan: 'bg-violet-500',
        coding: 'bg-sky-500',
        delivery: 'bg-emerald-500',
        review: 'bg-amber-500',
        patrol: 'bg-teal-500',
        reflection: 'bg-indigo-500',
        blocked: 'bg-rose-500',
    } as Record<string, string>)[action] ?? 'bg-muted-foreground'
}

function formatRole(role: string) {
    return ({ planner: '规划者', executor: '执行者', reviewer: '审查者', patrol: '巡查者' }[role] ?? role)
}

function getRoleBadgeClass(role: string) {
    return ({
        planner: 'border-violet-200 bg-violet-50 text-violet-700',
        executor: 'border-sky-200 bg-sky-50 text-sky-700',
        reviewer: 'border-amber-200 bg-amber-50 text-amber-700',
        patrol: 'border-teal-200 bg-teal-50 text-teal-700',
    }[role] ?? 'border-border bg-muted text-muted-foreground')
}

function formatDate(value: string | null) {
    if (!value) return '—'
    const date = new Date(value)
    if (Number.isNaN(date.getTime())) return '—'
    return new Intl.DateTimeFormat('zh-CN', {
        month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit',
    }).format(date)
}

function formatRelativeTime(value: string | null) {
    if (!value) return ''
    const now = Date.now()
    const time = new Date(value).getTime()
    if (Number.isNaN(time)) return ''
    const diff = Math.floor((now - time) / 1000)
    if (diff < 60) return '刚刚'
    if (diff < 3600) return `${Math.floor(diff / 60)} 分钟前`
    if (diff < 86400) return `${Math.floor(diff / 3600)} 小时前`
    return `${Math.floor(diff / 86400)} 天前`
}

function toggleExpand(id: string) {
    if (expandedIds.has(id)) {
        expandedIds.delete(id)
    } else {
        expandedIds.add(id)
    }
}

function isSummaryLong(summary: string) {
    return summary.length > 80
}

// ─── 数据加载 ───

const reloadDebounced = useDebounceFn(() => {
    page.value = 1
    void loadData()
}, 280)

watch([keyword, actionFilter, agentFilter], () => {
    loading.value = true
    reloadDebounced()
})

onMounted(() => {
    void loadAgentList()
    void loadData()
})

async function loadAgentList() {
    try {
        const response = await adminAgentApi.list({ page: 1, page_size: 100 })
        agentList.value = response.data.items
    } catch (e) {
        console.error('Failed to load agent list', e)
    }
}

async function loadData() {
    const rid = ++requestId
    loading.value = true
    error.value = ''

    try {
        const response = await adminLogApi.list({
            page: page.value,
            page_size: PAGE_SIZE,
            keyword: keyword.value.trim() || undefined,
            action: actionFilter.value === 'all' ? undefined : actionFilter.value,
            agent_id: agentFilter.value === 'all' ? undefined : agentFilter.value,
            sort_order: 'desc',
        })
        if (rid !== requestId) return
        pageData.value = response.data
        expandedIds.clear()
    } catch (e) {
        if (rid !== requestId) return
        console.error('Failed to load activity logs', e)
        error.value = '数据加载失败，请重试。'
    } finally {
        if (rid === requestId) loading.value = false
    }
}

function goToPage(p: number) {
    if (p < 1 || p > pageData.value.total_pages || p === page.value) return
    page.value = p
    void loadData()
}
</script>

<template>
    <div class="flex flex-col h-[calc(100vh-3.5rem)]">
        <!-- ─── 顶栏 ─── -->
        <header class="shrink-0 border-b border-border/40 bg-background px-4 py-3 space-y-2.5">
            <div class="flex items-center gap-3">
                <div class="relative flex-1 max-w-sm">
                    <Search
                        class="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
                    <Input v-model="keyword" class="h-9 bg-muted/30 pl-10 text-sm" placeholder="搜索摘要内容…" />
                </div>

                <!-- Agent 筛选 -->
                <select v-model="agentFilter"
                    class="h-9 rounded-md border border-input bg-muted/30 px-3 text-sm text-foreground outline-none focus:ring-1 focus:ring-ring shrink-0 max-w-[180px] truncate">
                    <option value="all">全部 Agent</option>
                    <option v-for="agent in agentList" :key="agent.id" :value="agent.id">
                        {{ agent.name }}（{{ formatRole(agent.role) }}）
                    </option>
                </select>

                <Badge variant="secondary" class="h-7 px-2.5 text-xs tabular-nums shrink-0">
                    {{ pageData.total }} 条
                </Badge>

                <Button variant="ghost" size="icon" class="h-8 w-8 shrink-0" :disabled="loading" @click="loadData">
                    <RefreshCw class="h-3.5 w-3.5" :class="loading ? 'animate-spin' : ''" />
                </Button>
            </div>

            <!-- 动作类型筛选 -->
            <div class="flex items-center gap-1.5 flex-wrap">
                <Button v-for="option in actionOptions" :key="option.value" size="sm"
                    :variant="actionFilter === option.value ? 'default' : 'ghost'" class="h-7 rounded-full px-3 text-xs"
                    @click="actionFilter = option.value">
                    <span v-if="option.value !== 'all'" class="inline-block w-1.5 h-1.5 rounded-full mr-1"
                        :class="getActionDotClass(option.value)" />
                    {{ option.label }}
                </Button>
            </div>
        </header>

        <!-- ─── 主内容 ─── -->
        <div class="flex-1 min-h-0 overflow-y-auto">
            <!-- 错误 -->
            <div v-if="error" class="flex flex-col items-center justify-center py-16">
                <AlertCircle class="h-5 w-5 text-muted-foreground" />
                <p class="mt-2 text-sm">{{ error }}</p>
                <Button class="mt-3" size="sm" @click="loadData">重新加载</Button>
            </div>

            <!-- 加载中 -->
            <div v-else-if="loading" class="flex items-center justify-center py-16">
                <Loader2 class="h-6 w-6 animate-spin text-muted-foreground" />
            </div>

            <!-- 日志列表 -->
            <template v-else>
                <div v-if="visibleLogItems.length" class="divide-y divide-border/30">
                    <div v-for="(log, idx) in visibleLogItems" :key="log.id"
                        class="px-5 py-3.5 hover:bg-muted/20 transition-colors animate-slide-up"
                        :style="{ animationDelay: `${idx * 25}ms` }">
                        <div class="flex items-start gap-3">
                            <!-- 左侧：动作圆点 -->
                            <div class="mt-1.5 w-2 h-2 rounded-full shrink-0" :class="getActionDotClass(log.action)" />

                            <!-- 中间：主内容 -->
                            <div class="flex-1 min-w-0">
                                <!-- 第一行：Agent + Action + 时间 -->
                                <div class="flex items-center gap-1.5 flex-wrap">
                                    <span class="text-sm font-semibold">{{ log.agent_name }}</span>
                                    <Badge variant="outline" :class="getRoleBadgeClass(log.agent_role)"
                                        class="text-[10px] px-1.5">
                                        {{ formatRole(log.agent_role) }}
                                    </Badge>
                                    <Badge variant="outline" :class="getActionBadgeClass(log.action)"
                                        class="text-[10px] px-1.5">
                                        {{ formatAction(log.action) }}
                                    </Badge>
                                    <span class="text-[11px] text-muted-foreground/50 ml-auto shrink-0 tabular-nums">
                                        {{ formatRelativeTime(log.created_at) }}
                                        <span class="hidden sm:inline ml-1 text-muted-foreground/40">{{
                                            formatDate(log.created_at) }}</span>
                                    </span>
                                </div>

                                <!-- 摘要 -->
                                <div class="mt-1">
                                    <p class="text-sm text-muted-foreground leading-relaxed"
                                        :class="!expandedIds.has(log.id) && isSummaryLong(log.summary) ? 'line-clamp-2' : ''">
                                        {{ log.summary || '（无摘要）' }}
                                    </p>
                                    <button v-if="isSummaryLong(log.summary)"
                                        class="inline-flex items-center gap-0.5 mt-0.5 text-xs text-primary/70 hover:text-primary transition-colors"
                                        @click="toggleExpand(log.id)">
                                        <template v-if="expandedIds.has(log.id)">
                                            <ChevronUp class="h-3 w-3" /> 收起
                                        </template>
                                        <template v-else>
                                            <ChevronDown class="h-3 w-3" /> 展开
                                        </template>
                                    </button>
                                </div>

                                <!-- 关联信息 -->
                                <div v-if="log.sub_task_id"
                                    class="mt-1 text-[11px] text-muted-foreground/50 tabular-nums">
                                    子任务 {{ log.sub_task_id.slice(0, 8) }}…
                                </div>
                            </div>
                        </div>
                    </div>
                </div>

                <!-- 空状态 -->
                <div v-else class="flex flex-col items-center justify-center py-16 text-muted-foreground/40">
                    <FileText class="h-6 w-6 mb-2" />
                    <p class="text-sm">暂无活动日志</p>
                </div>

                <!-- 分页 -->
                <div v-if="pageData.total_pages > 1"
                    class="flex items-center justify-center gap-2 py-3 border-t border-border/30 text-xs text-muted-foreground">
                    <Button variant="ghost" size="icon" class="h-7 w-7" :disabled="pageData.page <= 1 || loading"
                        @click="goToPage(pageData.page - 1)">
                        <ArrowLeft class="h-3 w-3" />
                    </Button>
                    <span class="tabular-nums">{{ pageData.page }} / {{ pageData.total_pages }}</span>
                    <Button variant="ghost" size="icon" class="h-7 w-7"
                        :disabled="pageData.page >= pageData.total_pages || loading"
                        @click="goToPage(pageData.page + 1)">
                        <ArrowRight class="h-3 w-3" />
                    </Button>
                </div>
            </template>
        </div>
    </div>
</template>

<style scoped>
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
