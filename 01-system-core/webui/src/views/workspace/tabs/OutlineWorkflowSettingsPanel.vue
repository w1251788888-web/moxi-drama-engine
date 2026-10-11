<script setup lang="ts">
import { Input } from '@/components/ui/input'
import { Zap } from 'lucide-vue-next'

type ProjectRules = {
  total_episodes: number
  episode_seconds: number
  word_count_per_episode: string
  scene_header_style: 'bracket' | 'plain'
  generation_provider: string
  generation_model: string
  advanced_generation_mode: boolean
}

type Provider = {
  id: string
  name: string
}

type ModelOption = {
  value: string
  name: string
}

defineProps<{
  generationProviders: Provider[]
  availableGenerationModels: ModelOption[]
}>()

const projectRules = defineModel<ProjectRules>('projectRules', { required: true })
</script>

<template>
  <details class="border rounded-xl overflow-hidden">
    <summary class="px-4 py-2.5 cursor-pointer text-xs font-medium text-muted-foreground hover:bg-muted/30 transition-colors select-none flex items-center gap-2 list-none">
      <Zap class="h-3.5 w-3.5" />工作流参数（总集数 / 单集时长 / 场标格式）
    </summary>
    <div class="px-4 pb-4 pt-3 space-y-3">
      <div class="grid grid-cols-2 gap-3">
        <div class="space-y-1">
          <label class="text-xs text-muted-foreground">总集数</label>
          <Input v-model.number="projectRules.total_episodes" type="number" min="1" max="200" class="h-8" />
        </div>
        <div class="space-y-1">
          <label class="text-xs text-muted-foreground">单集时长（秒）</label>
          <Input v-model.number="projectRules.episode_seconds" type="number" min="30" max="600" class="h-8" />
        </div>
      </div>
      <div class="space-y-1">
        <label class="text-xs text-muted-foreground">剧本净字区间（自动折算）</label>
        <div class="h-8 rounded-md border bg-muted/30 px-3 flex items-center justify-between text-sm">
          <span>{{ projectRules.word_count_per_episode }}</span>
          <span class="text-xs text-muted-foreground">90秒建议1000-1550净字</span>
        </div>
      </div>
      <div class="space-y-1.5">
        <label class="text-xs text-muted-foreground">场次标头格式</label>
        <div class="flex gap-2 flex-wrap">
          <button class="px-3 py-1.5 rounded-lg border text-xs transition-all"
            :class="projectRules.scene_header_style === 'bracket' ? 'bg-primary text-primary-foreground border-primary' : 'text-muted-foreground hover:border-primary/50'"
            @click="projectRules.scene_header_style = 'bracket'">
            中文场标 · 【场1-1：夜  内  书房】
          </button>
          <button class="px-3 py-1.5 rounded-lg border text-xs transition-all"
            :class="projectRules.scene_header_style === 'plain' ? 'bg-primary text-primary-foreground border-primary' : 'text-muted-foreground hover:border-primary/50'"
            @click="projectRules.scene_header_style = 'plain'">
            简洁场标 · 1-1  夜  内  书房
          </button>
        </div>
      </div>
      <div class="rounded-md border bg-muted/20 px-3 py-2 text-xs leading-relaxed">
        <span>
          <span class="block font-medium text-foreground">统一科研生成链路</span>
          <span class="block text-muted-foreground">生成时统一走规划、执笔、评审的科研链路；这里不再提供普通/高级两套开关。</span>
        </span>
      </div>
      <div class="rounded-md border bg-muted/20 px-3 py-2 text-[11px] text-muted-foreground leading-relaxed">
        剧本生成、逐集头部对标和连续性审计，都会进入同一条科研生成链路；模型职务由后台统一管理。
      </div>
    </div>
  </details>
</template>
