<script setup lang="ts">
import { ref, computed, type Component } from 'vue'
import { Button } from '@/components/ui/button'
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip'
import type { TranslatedActivity } from '@/composables/useActivityFeed'
import {
    Activity, Award, Bell, BookOpen, ChevronDown, ChevronRight, ClipboardList,
    Eye, FileSearch, FilePlus, FileText, FolderPlus, Hand,
    ListPlus, Medal, MessageSquare, PackageCheck, Pencil, Play,
    ScrollText, Search, Trophy, UserPlus,
} from 'lucide-vue-next'

const props = defineProps<{
    activity: TranslatedActivity
    isNew?: boolean
}>()

const expanded = ref(false)
const showRaw = ref(false)

const roleMap: Record<string, string> = {
    planner: '规划者',
    executor: '执行者',
    reviewer: '审查者',
    patrol: '巡查者',
}

const roleName = computed(() => roleMap[props.activity.agentRole] || props.activity.agentRole)

const hasDetails = computed(() => Object.keys(props.activity.details).length > 0)
const hasBody = computed(() => !!props.activity.rawBody)

const iconMap: Record<string, Component> = {
    Activity, Award, Bell, BookOpen, ClipboardList,
    Eye, FileSearch, FilePlus, FileText, FolderPlus, Hand,
    ListPlus, Medal, MessageSquare, PackageCheck, Pencil, Play,
    ScrollText, Search, Trophy, UserPlus,
}

const detailLabels: Record<string, string> = {
    comment: '评语', result: '结果', summary: '摘要',
    score_delta: '分值', reason: '原因', role: '角色',
    status: '状态', priority: '优先级', type: '类型',
    task_id: '任务', sub_task_id: '子任务', agent_id: 'Agent',
    assigned_agent: '执行者', action: '动作',
}

type RawBodyToken = {
    text: string
    kind: 'plain' | 'key' | 'string' | 'number' | 'bool'
}

const rawBodyTokens = computed(() => tokenizeRawBody(props.activity.rawBody))

function tokenizeRawBody(rawBody?: string | null): RawBodyToken[] {
    if (!rawBody) return []
    let text: string
    try { text = JSON.stringify(JSON.parse(rawBody), null, 2) }
    catch { return [{ text: rawBody, kind: 'plain' }] }

    const tokens: RawBodyToken[] = []
    const tokenPattern = /("(?:[^"\\]|\\.)*")(?=\s*:)|("(?:[^"\\]|\\.)*")|(-?\d+(?:\.\d+)?)|\b(true|false|null)\b/g
    let cursor = 0
    let match: RegExpExecArray | null
    while ((match = tokenPattern.exec(text)) !== null) {
        if (match.index > cursor) {
            tokens.push({ text: text.slice(cursor, match.index), kind: 'plain' })
        }
        if (match[1]) {
            tokens.push({ text: match[1], kind: 'key' })
        } else if (match[2]) {
            tokens.push({ text: match[2], kind: 'string' })
        } else if (match[3]) {
            tokens.push({ text: match[3], kind: 'number' })
        } else if (match[4]) {
            tokens.push({ text: match[4], kind: 'bool' })
        }
        cursor = match.index + match[0].length
    }
    if (cursor < text.length) {
        tokens.push({ text: text.slice(cursor), kind: 'plain' })
    }
    return tokens
}

function tokenClass(kind: RawBodyToken['kind']): string | undefined {
    return kind === 'plain' ? undefined : `json-${kind}`
}
</script>

<template>
    <div class="flex gap-3 px-4 py-2.5 cursor-pointer transition-colors hover:bg-muted/40"
        :class="{ 'bg-primary/[0.03]': isNew }" @click="expanded = !expanded">
        <!-- 图标 -->
        <div class="relative shrink-0 mt-0.5">
            <div class="flex items-center justify-center w-7 h-7 rounded-lg bg-muted text-muted-foreground">
                <component :is="iconMap[activity.icon] || iconMap.Activity" class="w-3.5 h-3.5" />
            </div>
        </div>

        <!-- 内容 -->
        <div class="flex-1 min-w-0 pb-0.5">
            <div class="flex items-baseline gap-1.5 text-sm flex-wrap leading-5">
                <TooltipProvider :delay-duration="300">
                    <Tooltip>
                        <TooltipTrigger as-child>
                            <span class="font-semibold text-foreground">{{ activity.agentName }}</span>
                            <span class="text-[10px] text-muted-foreground/50">{{ roleName }}</span>
                        </TooltipTrigger>
                        <TooltipContent side="top" class="text-xs">
                            {{ activity.agentRole }} · {{ activity.agentId.slice(0, 8) }}
                        </TooltipContent>
                    </Tooltip>
                </TooltipProvider>
                <span class="text-foreground/70">{{ activity.verb }}</span>
                <span v-if="activity.objectName"
                    class="font-semibold text-foreground truncate max-w-[200px] sm:max-w-[300px] lg:max-w-[400px]">
                    {{ activity.objectName }}
                </span>
                <span class="text-xs text-muted-foreground/60 tabular-nums ml-auto shrink-0">{{
                    activity.relativeTime }}</span>
            </div>

            <!-- 展开详情 -->
            <Transition name="expand">
                <div v-if="expanded" class="mt-1.5 space-y-1.5">
                    <div v-if="hasDetails" class="flex flex-wrap gap-x-4 gap-y-0.5">
                        <div v-for="(value, key) in activity.details" :key="key" class="text-xs">
                            <span class="text-muted-foreground/60">{{ detailLabels[key] || key }}</span>
                            <span class="text-foreground/70 ml-1">{{ value }}</span>
                        </div>
                    </div>

                    <div v-if="hasBody">
                        <Button variant="ghost" size="sm"
                            class="h-5 px-1 text-[10px] text-muted-foreground/50 hover:text-muted-foreground gap-0.5"
                            @click.stop="showRaw = !showRaw">
                            <component :is="showRaw ? ChevronDown : ChevronRight" class="w-2.5 h-2.5" />
                            raw
                        </Button>
                        <Transition name="expand">
                            <pre v-if="showRaw"
                                class="mt-1 rounded-lg bg-muted/50 border border-border/40 p-2.5 text-[11px] whitespace-pre-wrap break-all leading-relaxed m-0 font-mono"><template
                                    v-for="(token, index) in rawBodyTokens" :key="index"><span
                                        :class="tokenClass(token.kind)">{{ token.text }}</span></template></pre>
                        </Transition>
                    </div>
                </div>
            </Transition>
        </div>
    </div>
</template>

<style scoped>
.expand-enter-active,
.expand-leave-active {
    transition: all 0.15s ease;
    overflow: hidden;
}

.expand-enter-from,
.expand-leave-to {
    opacity: 0;
    max-height: 0;
}

.expand-enter-to,
.expand-leave-from {
    opacity: 1;
    max-height: 500px;
}

.json-key {
    color: hsl(270, 60%, 65%);
}

.json-string {
    color: hsl(140, 50%, 55%);
}

.json-number {
    color: hsl(35, 80%, 55%);
}

.json-bool {
    color: hsl(210, 70%, 60%);
}
</style>
