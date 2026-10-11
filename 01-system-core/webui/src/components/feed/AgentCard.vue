<script setup lang="ts">
import { computed } from 'vue'
import { Separator } from '@/components/ui/separator'
import type { AgentSummary } from '@/composables/useActivityFeed'
import { getActionCategory, getActionVerb, formatRelativeTime } from '@/composables/useActivityFeed'

const props = defineProps<{
    agent: AgentSummary
    selected: boolean
    flashing: boolean
}>()

defineEmits<{
    (e: 'select'): void
}>()

const roleLabels: Record<string, string> = {
    planner: 'P', executor: 'E', reviewer: 'R', patrol: 'D',
}

const roleFullName: Record<string, string> = {
    planner: '规划者', executor: '执行者', reviewer: '审查者', patrol: '巡查者',
}

const categoryColors: Record<string, string> = {
    complete: 'bg-emerald-500',
    execute: 'bg-amber-500',
    create: 'bg-blue-500',
    query: 'bg-muted-foreground/40',
    score_up: 'bg-emerald-500',
    score_down: 'bg-rose-500',
}

const actions = computed(() =>
    props.agent.recent_actions.map((a) => ({
        verb: getActionVerb(a),
        time: formatRelativeTime(a.timestamp),
        category: getActionCategory(a),
    }))
)
</script>

<template>
    <div class="w-full shrink-0 rounded-xl border bg-background p-3.5 cursor-pointer transition-all select-none hover:shadow-sm"
        :class="[
            selected ? 'border-primary/60 ring-1 ring-primary/20 bg-accent/30' : 'border-border/60 hover:border-border',
            flashing ? 'agent-card-flash' : '',
        ]" @click="$emit('select')">
        <!-- 头部 -->
        <div class="flex items-center gap-2.5">
            <div
                class="flex items-center justify-center w-8 h-8 rounded-full bg-muted text-xs font-bold text-foreground/70 shrink-0">
                {{ roleLabels[agent.role] || '?' }}
            </div>
            <div class="min-w-0 flex-1">
                <div class="text-sm font-semibold text-foreground truncate leading-5">{{ agent.name }}</div>
                <div class="flex items-center gap-1.5 mt-0.5">
                    <span class="text-xs text-muted-foreground">{{ roleFullName[agent.role] || agent.role }}</span>
                    <span class="text-muted-foreground/30">·</span>
                    <span class="text-xs font-semibold text-foreground tabular-nums">{{ agent.total_score }}</span>
                    <span class="text-[10px] text-muted-foreground">pt</span>
                </div>
            </div>
        </div>

        <Separator class="my-2.5 opacity-40" />

        <!-- 今日统计 -->
        <div class="space-y-1">
            <div class="text-[10px] font-medium text-muted-foreground/50 uppercase tracking-wider">今日</div>
            <div class="flex gap-4 text-xs tabular-nums">
                <span><span class="font-semibold text-foreground">{{ agent.today_request_count }}</span> <span
                        class="text-muted-foreground">请求</span></span>
                <span><span class="font-semibold text-foreground">{{ agent.today_submit_count }}</span> <span
                        class="text-muted-foreground">提交</span></span>
                <span><span class="font-semibold text-foreground">{{ agent.today_review_count }}</span> <span
                        class="text-muted-foreground">审查</span></span>
            </div>
        </div>

        <!-- 当前任务 -->
        <div class="mt-3">
            <div v-if="agent.current_sub_task" class="text-xs">
                <div class="flex items-center gap-1.5">
                    <span class="inline-block w-2 h-2 rounded-full bg-amber-400 animate-pulse shrink-0" />
                    <span class="font-medium text-foreground truncate">{{ agent.current_sub_task.name }}</span>
                </div>
                <div v-if="agent.current_sub_task.module_name"
                    class="text-[11px] text-muted-foreground ml-3.5 truncate mt-0.5">
                    {{ agent.current_sub_task.module_name }}
                </div>
            </div>
            <div v-else class="text-xs text-muted-foreground/50 italic">空闲</div>
        </div>

        <!-- 近期动作 -->
        <div v-if="actions.length" class="mt-3 space-y-1">
            <div class="text-[10px] font-medium text-muted-foreground/50 uppercase tracking-wider">近期</div>
            <div v-for="(act, i) in actions" :key="i" class="flex items-center gap-1.5 text-[11px] leading-4">
                <span class="inline-block w-1.5 h-1.5 rounded-full shrink-0" :class="categoryColors[act.category]" />
                <span class="text-foreground/80 truncate flex-1">{{ act.verb }}</span>
                <span class="text-muted-foreground/50 tabular-nums text-[10px] shrink-0">{{ act.time }}</span>
            </div>
        </div>
    </div>
</template>

<style scoped>
.agent-card-flash {
    animation: card-flash 1.5s ease;
}

@keyframes card-flash {

    0%,
    100% {
        box-shadow: none;
    }

    30%,
    70% {
        box-shadow: 0 0 0 2px hsl(var(--primary) / 0.25);
    }
}
</style>
