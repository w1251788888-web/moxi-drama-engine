<script setup lang="ts">
import { Button } from '@/components/ui/button'
import { AlertTriangle, CheckCircle2 } from 'lucide-vue-next'
import OutlineCharacterListPanel from '@/views/workspace/tabs/OutlineCharacterListPanel.vue'
import OutlineCoreFieldsPanel from '@/views/workspace/tabs/OutlineCoreFieldsPanel.vue'
import OutlineCreativeDirectionPanel from '@/views/workspace/tabs/OutlineCreativeDirectionPanel.vue'
import OutlineEpisodeFrameworkPanel from '@/views/workspace/tabs/OutlineEpisodeFrameworkPanel.vue'
import OutlineRawPanel from '@/views/workspace/tabs/OutlineRawPanel.vue'
import OutlineWorkflowSettingsPanel from '@/views/workspace/tabs/OutlineWorkflowSettingsPanel.vue'

type OutlineCharacter = {
  id: string
  name: string
  role: string
  info: string
}

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

type OutlineData = {
  logline: string
  worldview: string
  goldenFinger: string
  conflict: string
  episodes: OutlineEpisode[]
  audience_axis: '男频' | '女频' | '混合' | ''
  genre_main: string
  format_type: '真人短剧' | '漫剧' | 'AI真人'
}

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
  roleColors: Record<string, string>
  isAnalyzingOutline: boolean
  outlineAnalyzeStatus: string
  isPredictingOutline: boolean
  outlineAiGeneratedFields: Record<string, string>
  isGeneratingEpisodes: boolean
  projectRulesSaving: boolean
  sectionLoading: Record<string, boolean>
  sectionSuggestions: Record<string, string>
  generationProviders: Provider[]
  availableGenerationModels: ModelOption[]
  aiFeaturesPaused: boolean
  outlineMainChainStatusText: string
  outlineMainChainCommitBlocked: boolean
  outlineMainChainCommitBlockReason: string
}>()

const rawOutlineText = defineModel<string>('rawOutlineText', { required: true })
const outlineData = defineModel<OutlineData>('outlineData', { required: true })
const outlineCharacters = defineModel<OutlineCharacter[]>('outlineCharacters', { required: true })
const projectRules = defineModel<ProjectRules>('projectRules', { required: true })

defineEmits<{
  analyzeOutline: []
  uploadOutlineFile: [file: File]
  getAiSuggestion: [field: string, value: string]
  addOutlineCharacter: []
  removeOutlineCharacter: [id: string]
  generateEpisodes: [count: number]
  addEpisode: []
  switchTab: [tab: 'chat' | 'outline' | 'characters' | 'script' | 'storyboard' | 'export']
  saveOutlineAndContinue: []
}>()
</script>

<template>
  <div class="flex-1 min-w-0 flex overflow-hidden">
    <OutlineRawPanel
      v-model:raw-outline-text="rawOutlineText"
      :characters="outlineCharacters"
      :episodes="outlineData.episodes"
      :loading="isAnalyzingOutline"
      :predicting="isPredictingOutline"
      :status-message="outlineAnalyzeStatus"
      @analyze="$emit('analyzeOutline')"
      @upload-file="$emit('uploadOutlineFile', $event)"
    />

    <!-- ═══ 右：提取结果 ═══ -->
    <div class="flex-1 min-w-[420px] overflow-auto">
      <div class="max-w-3xl mx-auto p-4 space-y-4 pb-10">
        <div class="rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-900 dark:border-amber-900/60 dark:bg-amber-950/20 dark:text-amber-100">
          <div class="flex items-start gap-2">
            <AlertTriangle class="mt-0.5 h-4 w-4 shrink-0" />
            <span>
              {{ outlineMainChainStatusText }}
              <template v-if="outlineMainChainCommitBlocked">
                当前不能进入角色设计：{{ outlineMainChainCommitBlockReason }}。
              </template>
            </span>
          </div>
        </div>

        <OutlineCreativeDirectionPanel v-model:outline-data="outlineData" />

        <OutlineCoreFieldsPanel
          v-model:outline-data="outlineData"
          :ai-generated-fields="outlineAiGeneratedFields"
          :section-loading="sectionLoading"
          :section-suggestions="sectionSuggestions"
          :ai-features-paused="aiFeaturesPaused"
          @get-ai-suggestion="(field, value) => $emit('getAiSuggestion', field, value)"
        />

        <OutlineCharacterListPanel
          v-model:outline-characters="outlineCharacters"
          :role-colors="roleColors"
          :ai-generated="Boolean(outlineAiGeneratedFields.characters)"
          @add="$emit('addOutlineCharacter')"
          @remove="$emit('removeOutlineCharacter', $event)"
        />

        <OutlineEpisodeFrameworkPanel
          v-model:episodes="outlineData.episodes"
          v-model:project-rules="projectRules"
          :ai-generated="Boolean(outlineAiGeneratedFields.episodes)"
          :is-generating-episodes="isGeneratingEpisodes"
          :project-rules-saving="projectRulesSaving"
          :ai-features-paused="aiFeaturesPaused"
          @generate="$emit('generateEpisodes', $event)"
          @add="$emit('addEpisode')"
        />

        <OutlineWorkflowSettingsPanel
          v-model:project-rules="projectRules"
          :generation-providers="generationProviders"
          :available-generation-models="availableGenerationModels"
        />

        <div class="flex justify-between pt-2 pb-4">
          <Button variant="ghost" @click="$emit('switchTab', 'chat')">← 返回聊天脑暴</Button>
          <Button
            class="gap-2 bg-gradient-to-r from-primary to-purple-600 hover:opacity-90"
            :disabled="outlineMainChainCommitBlocked"
            :title="outlineMainChainCommitBlockReason || '完成大纲后进入角色设计'"
            @click="$emit('saveOutlineAndContinue')"
          >
            <CheckCircle2 class="h-4 w-4" />大纲完成 → 角色设计
          </Button>
        </div>

        <div class="rounded-lg border border-red-300 bg-red-50 px-3 py-2 text-sm font-semibold text-red-700 dark:border-red-900/60 dark:bg-red-950/20 dark:text-red-300">
          <div class="flex items-start gap-2">
            <AlertTriangle class="mt-0.5 h-4 w-4 shrink-0" />
            <span>功能尚未开发完全，需要用户手动完成所有信息的补全。</span>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
