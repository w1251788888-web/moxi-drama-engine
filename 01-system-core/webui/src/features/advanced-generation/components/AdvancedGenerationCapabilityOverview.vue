<script setup lang="ts">
import { computed, onMounted } from 'vue'
import type { Component } from 'vue'
import {
  AlertCircle,
  CheckCircle2,
  Database,
  GitBranch,
  Network,
  RefreshCw,
  Search,
  Server,
} from 'lucide-vue-next'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  type AdvancedCapabilityItem,
  useAdvancedGenerationCapabilities,
} from '../composables/useAdvancedGenerationCapabilities'

const {
  capabilities,
  degradedCount,
  isLoading,
  loadCapabilities,
  loadError,
  readyCount,
} = useAdvancedGenerationCapabilities()

const iconMap: Record<string, Component> = {
  chroma: Network,
  fts5: Search,
  langgraph: GitBranch,
  redis: Server,
  yjs: Database,
}

const stateClass: Record<AdvancedCapabilityItem['state'], string> = {
  degraded: 'border-amber-300 bg-amber-50 text-amber-800',
  offline: 'border-rose-300 bg-rose-50 text-rose-800',
  ready: 'border-emerald-300 bg-emerald-50 text-emerald-800',
  unknown: 'border-[#26312c]/15 bg-[#f2f0e8] text-[#5d675f]',
}

const stateLabel: Record<AdvancedCapabilityItem['state'], string> = {
  degraded: '降级',
  offline: '离线',
  ready: '可用',
  unknown: '读取中',
}

const summaryText = computed(() => {
  if (isLoading.value) {
    return '正在读取后端能力契约'
  }
  return `${readyCount.value} 个可用，${degradedCount.value} 个降级`
})

onMounted(loadCapabilities)
</script>

<template>
  <section class="border border-[#26312c]/10 bg-[#fdfcf7]">
    <header class="flex flex-col gap-4 border-b border-[#26312c]/10 px-5 py-4 lg:flex-row lg:items-center lg:justify-between">
      <div>
        <div class="flex flex-wrap items-center gap-2">
          <Badge variant="outline" class="rounded-sm border-[#1f4f46]/30 bg-[#e8f2ee] text-[#1f4f46]">
            开源能力概览
          </Badge>
          <span class="text-xs text-[#6d766f]">{{ summaryText }}</span>
        </div>
        <h2 class="mt-2 text-lg font-semibold tracking-normal">检索、缓存、编排与协作状态</h2>
      </div>
      <div class="flex items-center gap-3">
        <span v-if="loadError" class="flex items-center gap-1.5 text-xs text-amber-700">
          <AlertCircle class="h-3.5 w-3.5" />
          {{ loadError }}
        </span>
        <Button size="sm" variant="outline" class="rounded-sm" :disabled="isLoading" @click="loadCapabilities">
          <RefreshCw class="mr-2 h-4 w-4" :class="{ 'animate-spin': isLoading }" />
          刷新
        </Button>
      </div>
    </header>

    <div class="grid gap-px bg-[#26312c]/10 md:grid-cols-2 xl:grid-cols-5">
      <article
        v-for="item in capabilities"
        :key="item.id"
        class="min-h-[18rem] bg-[#fdfcf7] p-4"
      >
        <div class="flex items-start justify-between gap-3">
          <div class="flex items-center gap-3">
            <div class="flex h-10 w-10 items-center justify-center border border-[#26312c]/12 bg-white text-[#1f4f46]">
              <component :is="iconMap[item.id] || CheckCircle2" class="h-5 w-5" />
            </div>
            <div>
              <div class="text-sm font-semibold">{{ item.label }}</div>
              <div class="mt-0.5 text-xs text-[#6d766f]">{{ item.family }}</div>
            </div>
          </div>
          <span class="border px-2 py-1 text-[11px] font-medium" :class="stateClass[item.state]">
            {{ stateLabel[item.state] }}
          </span>
        </div>

        <div class="mt-4">
          <div class="text-xs uppercase tracking-normal text-[#8a5a13]">{{ item.backend }}</div>
          <p class="mt-1 min-h-10 text-sm font-medium leading-5">{{ item.headline }}</p>
        </div>

        <dl class="mt-4 grid grid-cols-3 gap-2">
          <div
            v-for="metric in item.metrics"
            :key="`${item.id}-${metric.label}`"
            class="border border-[#26312c]/10 bg-white/65 px-2 py-2"
          >
            <dt class="truncate text-[11px] text-[#6d766f]">{{ metric.label }}</dt>
            <dd class="mt-1 truncate text-xs font-semibold text-[#1f2723]">{{ metric.value }}</dd>
          </div>
        </dl>

        <ul class="mt-4 space-y-2">
          <li
            v-for="detail in item.details"
            :key="`${item.id}-${detail}`"
            class="border-l border-[#26312c]/15 pl-3 text-xs leading-5 text-[#5d675f]"
          >
            {{ detail }}
          </li>
        </ul>
      </article>
    </div>
  </section>
</template>
