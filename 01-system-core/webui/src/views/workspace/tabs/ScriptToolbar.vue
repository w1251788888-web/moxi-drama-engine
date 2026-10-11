<script setup lang="ts">
import { Button } from '@/components/ui/button'
import { AlertCircle, FileText, Save, Square, TrendingUp, Wand2 } from 'lucide-vue-next'

type ProjectRules = {
  episode_seconds: number
  word_count_per_episode: string
  scene_header_style: string
  advanced_generation_mode: boolean
}

const props = defineProps<{
  projectId: string
  selectedEpisode: number
  selectedScene: number
  projectRules: ProjectRules
  showFloatingGraph: boolean
  currentEpExistingScript: string
  sceneContent: string
  isValidatingScriptRules: boolean
  isGeneratingScript: boolean
  isSegmentGenerating: boolean
  isSavingScript: boolean
  isSegmentedInProgress?: boolean
}>()

defineEmits<{
  'open-floating-graph': []
  'load-existing-script': []
  'run-script-rule-validation': []
  'generate-script': []
  'stop-generating-script': []
  'save-script': []
}>()
</script>

<template>
  <div class="border-b px-3 py-2 flex flex-col lg:flex-row lg:items-center lg:justify-between bg-muted/20 shrink-0 gap-2">
    <div class="min-w-0 flex-1">
      <div class="text-sm text-muted-foreground whitespace-nowrap truncate">第{{ selectedEpisode }}集 · 整集写作</div>
    </div>
    <div class="flex gap-1 flex-wrap lg:flex-nowrap lg:overflow-x-auto shrink-0 justify-start lg:justify-end">
      <Button variant="outline" size="sm" class="text-xs gap-1 h-8 shrink-0"
        :title="isSegmentedInProgress ? '接管已有生成进度，从当前内容后继续生成' : '按分步确认生成当前集'"
        :disabled="isGeneratingScript || isSegmentGenerating" @click="$emit('generate-script')">
        <Wand2 class="h-3.5 w-3.5" />{{ isGeneratingScript ? '生成中...' : (isSegmentedInProgress ? '继续生成' : '生成本集') }}
      </Button>
      <Button v-if="isGeneratingScript" variant="outline" size="sm"
        class="text-xs gap-1 h-8 shrink-0 border-red-300 text-red-600 hover:bg-red-50 dark:hover:bg-red-950/30"
        @click="$emit('stop-generating-script')">
        <Square class="h-3.5 w-3.5" />停止
      </Button>
      <Button variant="outline" size="sm" class="text-xs gap-1 h-8 shrink-0" :disabled="isSavingScript" @click="$emit('save-script')">
        <Save class="h-3.5 w-3.5" />{{ isSavingScript ? '保存中...' : '保存' }}
      </Button>
      <Button variant="outline" size="sm" class="text-xs gap-1 h-8 shrink-0"
        :class="showFloatingGraph ? 'bg-primary/10 border-primary/50 text-primary' : ''"
        @click="$emit('open-floating-graph')">
        <TrendingUp class="h-3.5 w-3.5" />关系图
      </Button>
      <Button v-if="currentEpExistingScript" variant="outline" size="sm"
        class="text-xs gap-1 h-8 shrink-0 border-amber-300 text-amber-600 hover:bg-amber-50 dark:hover:bg-amber-950/30"
        @click="$emit('load-existing-script')">
        <FileText class="h-3.5 w-3.5" />原稿
      </Button>
      <Button variant="outline" size="sm" class="text-xs gap-1 h-8 shrink-0"
        title="规则/合规预检：检查本集字数、格式、角色、连续性和明显风险"
        :disabled="isValidatingScriptRules" @click="$emit('run-script-rule-validation')">
        <AlertCircle class="h-3.5 w-3.5" />{{ isValidatingScriptRules ? '审查中...' : '审查本集' }}
      </Button>
    </div>
  </div>
</template>
