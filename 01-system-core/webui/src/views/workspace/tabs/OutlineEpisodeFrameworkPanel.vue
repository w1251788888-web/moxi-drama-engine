<script setup lang="ts">
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { Badge } from '@/components/ui/badge'
import { ChevronDown, Plus, Wand2, X } from 'lucide-vue-next'

type OutlineEpisode = {
  ep: number
  title: string
  hook: string
  summary: string
  conflict?: string
  turning?: string
  main_scene?: string
  relationship_change?: string
  info_revealed?: string
  satisfaction_type?: string
  stage?: string
  existing_script?: string
}

type ProjectRules = {
  total_episodes: number
}

defineProps<{
  isGeneratingEpisodes: boolean
  projectRulesSaving: boolean
  aiGenerated: boolean
  aiFeaturesPaused: boolean
}>()

const episodes = defineModel<OutlineEpisode[]>('episodes', { required: true })
const projectRules = defineModel<ProjectRules>('projectRules', { required: true })

defineEmits<{
  generate: [count: number]
  add: []
}>()
</script>

<template>
  <div class="space-y-2">
    <div class="flex items-center justify-between flex-wrap gap-2">
      <div class="flex items-center gap-2">
        <span class="text-xs font-semibold uppercase tracking-wide text-muted-foreground">集纲</span>
        <Badge variant="secondary" class="text-[10px]">{{ episodes.length }} / {{ projectRules.total_episodes }} 集</Badge>
        <Badge v-if="aiGenerated" variant="secondary" class="text-[10px] px-1.5 py-0">AI补全</Badge>
      </div>
      <div class="flex items-center gap-1.5 flex-wrap">
        <Input v-model.number="projectRules.total_episodes" type="number" min="1" max="200" class="h-6 w-14 text-xs" />
        <Button
          size="sm"
          class="h-7 text-xs gap-1"
          :class="aiFeaturesPaused ? 'bg-muted text-muted-foreground hover:bg-muted' : 'bg-gradient-to-r from-primary to-purple-600'"
          :disabled="aiFeaturesPaused || isGeneratingEpisodes || projectRulesSaving"
          :title="aiFeaturesPaused ? '全局预测和 AI 集纲生成功能暂时关闭，请手动补全' : 'AI生成集纲'"
          @click="$emit('generate', projectRules.total_episodes)">
          <Wand2 class="h-3 w-3" />{{ aiFeaturesPaused ? 'AI生成集纲（暂停）' : isGeneratingEpisodes ? '生成中...' : 'AI生成集纲' }}
        </Button>
        <Button variant="outline" size="sm" class="h-7 text-xs gap-1 px-2" @click="$emit('add')">
          <Plus class="h-3 w-3" />手动
        </Button>
      </div>
    </div>
    <div
      v-if="episodes.length"
      class="rounded-md border border-amber-200 bg-amber-50 px-2.5 py-2 text-[11px] leading-relaxed text-amber-800 dark:border-amber-900/60 dark:bg-amber-950/20 dark:text-amber-300"
    >
      请确认每集事件顺序、关键钩子和上一集结尾是否能接上；范围集纲和表格集纲已尽量识别，但仍需要人工检查。
    </div>

    <div class="space-y-2">
      <details
        v-for="(ep, i) in episodes"
        :key="`${ep.ep}-${i}`"
        class="group rounded-lg border bg-background/80 transition-colors open:bg-muted/20"
      >
        <summary class="flex min-h-12 cursor-pointer list-none items-center gap-2 px-3 py-2 [&::-webkit-details-marker]:hidden">
          <div class="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-primary/10 text-xs font-bold text-primary">
            {{ ep.ep }}
          </div>
          <div class="min-w-0 flex-1">
            <div class="flex items-center gap-2">
              <span class="truncate text-sm font-semibold">{{ ep.title || `第${ep.ep}集` }}</span>
              <span v-if="ep.existing_script" class="shrink-0 rounded-full bg-amber-500/10 px-1.5 py-0.5 text-[10px] text-amber-600">
                原稿
              </span>
            </div>
            <p class="truncate text-[11px] text-muted-foreground">
              {{ ep.summary || '点开填写本集具体事件' }}
            </p>
          </div>
          <button
            class="shrink-0 rounded-md p-1 text-muted-foreground/50 transition-colors hover:bg-destructive/10 hover:text-destructive"
            title="删除本集"
            @click.stop.prevent="episodes.splice(i, 1)"
          >
            <X class="h-3.5 w-3.5" />
          </button>
          <ChevronDown class="h-4 w-4 shrink-0 text-muted-foreground transition-transform group-open:rotate-180" />
        </summary>

        <div class="border-t px-3 py-3">
          <div class="grid gap-3">
            <div class="grid gap-1.5 sm:grid-cols-[72px_1fr] sm:items-center">
              <label class="text-xs font-semibold text-muted-foreground">标题</label>
              <Input v-model="ep.title" :placeholder="`第${ep.ep}集标题`" class="h-8 text-sm" />
            </div>

            <div class="grid gap-1.5">
              <label class="text-xs font-semibold text-muted-foreground">单集集纲</label>
              <Textarea
                v-model="ep.summary"
                class="min-h-[96px] resize-y text-sm leading-relaxed"
                placeholder="这一集具体发生了什么？写清事件、动作、因果推进，方便后续生成剧本。"
              />
            </div>

            <div class="grid gap-3 md:grid-cols-2">
              <div class="grid gap-1.5">
                <label class="text-xs font-semibold text-muted-foreground">本集冲突</label>
                <Textarea
                  v-model="ep.conflict"
                  class="min-h-[72px] resize-y text-xs leading-relaxed"
                  placeholder="本集最主要的矛盾焦点"
                />
              </div>
              <div class="grid gap-1.5">
                <label class="text-xs font-semibold text-muted-foreground">转折 / 爆点</label>
                <Textarea
                  v-model="ep.turning"
                  class="min-h-[72px] resize-y text-xs leading-relaxed"
                  placeholder="本集发生的关键变化或剧情爆点"
                />
              </div>
            </div>

            <div class="grid gap-2 rounded-md border bg-muted/20 p-2">
              <div class="flex items-center justify-between gap-2">
                <span class="text-xs font-semibold text-muted-foreground">规则结构</span>
                <Badge v-if="ep.stage" variant="secondary" class="text-[10px] px-1.5 py-0">{{ ep.stage }}</Badge>
              </div>
              <div class="grid gap-2 md:grid-cols-2">
                <div class="grid gap-1">
                  <label class="text-[11px] font-medium text-muted-foreground">主场景</label>
                  <Input v-model="ep.main_scene" placeholder="例：公司会议室 / 医院走廊" class="h-7 text-xs" />
                </div>
                <div class="grid gap-1">
                  <label class="text-[11px] font-medium text-muted-foreground">爽点类型</label>
                  <Input v-model="ep.satisfaction_type" placeholder="例：S2 围观打脸" class="h-7 text-xs" />
                </div>
                <div class="grid gap-1">
                  <label class="text-[11px] font-medium text-muted-foreground">关系变化</label>
                  <Input v-model="ep.relationship_change" placeholder="谁和谁的关系发生什么变化" class="h-7 text-xs" />
                  <p class="text-[10px] leading-relaxed text-amber-700 dark:text-amber-300">
                    关系联动提示：改动本集关系变化后，请回到角色关系线核对，避免下一集承接到旧关系。
                  </p>
                </div>
                <div class="grid gap-1">
                  <label class="text-[11px] font-medium text-muted-foreground">信息揭露</label>
                  <Input v-model="ep.info_revealed" placeholder="本集新增或兑现的信息点" class="h-7 text-xs" />
                </div>
              </div>
            </div>
          </div>
        </div>
      </details>

      <div v-if="episodes.length === 0"
        class="text-center py-6 border-2 border-dashed rounded-lg text-muted-foreground text-xs">
        自动分割后会显示已有集纲；没有识别到的集纲请手动添加
      </div>
    </div>
  </div>
</template>
