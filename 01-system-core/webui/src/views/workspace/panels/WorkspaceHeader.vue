<script setup lang="ts">
import type { Component } from 'vue'
import { ArrowLeft, Bot, CheckCircle2, PanelRight } from 'lucide-vue-next'
import { Button } from '@/components/ui/button'

type WorkspaceTab = {
  id: string
  label: string
  icon: Component
}

defineProps<{
  projectName: string
  progressPercent: number
  tabs: WorkspaceTab[]
  activeTab: string
  completedTabs: Set<string>
  aiPanelOpen: boolean
  showAiPanel: boolean
}>()

defineEmits<{
  back: []
  toggleAiPanel: []
  switchTab: [tab: string]
}>()
</script>

<template>
  <header class="border-b bg-card shrink-0">
    <div class="flex items-center gap-4 px-4 pt-3 pb-2">
      <Button variant="ghost" size="icon" class="shrink-0" @click="$emit('back')">
        <ArrowLeft class="h-4 w-4" />
      </Button>
      <div class="flex-1 min-w-0">
        <h1 class="font-bold text-lg truncate">{{ projectName || '加载中...' }}</h1>
        <div class="flex items-center gap-3 mt-1">
          <div class="flex-1 max-w-xs">
            <div class="h-1.5 rounded-full bg-muted overflow-hidden">
              <div
                class="h-1.5 rounded-full bg-gradient-to-r from-primary to-purple-500 transition-all duration-500"
                :style="{ width: `${Math.max(progressPercent, 2)}%` }"
              />
            </div>
          </div>
          <span class="text-xs text-muted-foreground">{{ progressPercent }}% 完成</span>
        </div>
      </div>
      <Button
        v-if="showAiPanel"
        variant="ghost"
        size="sm"
        class="gap-2 shrink-0"
        @click="$emit('toggleAiPanel')"
      >
        <Bot class="h-4 w-4" />
        <span class="text-xs">AI助手</span>
        <PanelRight class="h-3.5 w-3.5" />
      </Button>
    </div>

    <div class="flex items-center gap-1 px-4 overflow-x-auto">
      <button
        v-for="tab in tabs"
        :key="tab.id"
        class="flex items-center gap-2 px-4 py-2.5 text-sm font-medium border-b-2 transition-all whitespace-nowrap"
        :class="activeTab === tab.id
          ? 'border-primary text-primary'
          : completedTabs.has(tab.id)
            ? 'border-transparent text-muted-foreground hover:text-foreground hover:border-muted-foreground/30'
            : 'border-transparent text-muted-foreground hover:text-foreground hover:border-muted-foreground/30'"
        @click="$emit('switchTab', tab.id)"
      >
        <CheckCircle2
          v-if="completedTabs.has(tab.id) && activeTab !== tab.id"
          class="h-4 w-4 text-emerald-500"
        />
        <component v-else :is="tab.icon" class="h-4 w-4" />
        {{ tab.label }}
      </button>
    </div>
  </header>
</template>
