<script setup lang="ts">
import { computed } from 'vue'
import type { AgentSummary } from '@/composables/useActivityFeed'
import AgentCard from '@/components/feed/AgentCard.vue'

const props = defineProps<{
    agents: AgentSummary[]
    flashingAgentIds: Set<string>
    selectedAgentId: string | null
}>()

const emit = defineEmits<{
    (e: 'select', agentId: string | null): void
}>()

function handleSelect(id: string) {
    emit('select', props.selectedAgentId === id ? null : id)
}

const sortedAgents = computed(() => props.agents)
</script>

<template>
    <div class="flex flex-col gap-2 p-3">
        <AgentCard v-for="agent in sortedAgents" :key="agent.id" :agent="agent" :selected="selectedAgentId === agent.id"
            :flashing="flashingAgentIds.has(agent.id)" @select="handleSelect(agent.id)" />
        <div v-if="!sortedAgents.length" class="w-full text-center text-xs text-muted-foreground/40 py-6">
            暂无 Agent
        </div>
    </div>
</template>
