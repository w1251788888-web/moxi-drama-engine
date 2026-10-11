<script setup lang="ts">
import { Zap } from 'lucide-vue-next'

type SegmentVersion = 'A' | 'B'
type LineOrigin = 'ai-original' | 'ai-revised' | 'user-edited'

type SegmentStep = {
  id: string
  label: string
  desc: string
  target: number
  status: 'pending' | 'generating' | 'reviewing' | 'confirmed' | 'error'
  versionA: string
  versionB: string
  activeVersion: SegmentVersion
  editedContent: string
  _editSnapshot: string
  lineOrigins: LineOrigin[]
  editMode: boolean
  suggestions: string[]
  isSuggesting: boolean
  isPatchPanelOpen: boolean
  patchSelectedText: string
  patchInstruction: string
  isPatching: boolean
  repairAttempts: number
  isGeneratingVariant: boolean
  generationAttempts: number
  lastErrorDetail: string
  lastErrorSuggestion: string
  lastErrorCode: string
  lastErrorIssues: string[]
}

type GenerationTarget = {
  episodeNo: number
  sceneNo: number
}

defineProps<{
  segmentSteps: SegmentStep[]
  currentSegmentIdx: number
  currentSegmentStep: SegmentStep | null
  isSegmentGenerating: boolean
  countScriptChars: (content: string) => number
  generationTarget: GenerationTarget
}>()

const showSegmentPanel = defineModel<boolean>('showSegmentPanel', { required: true })

defineEmits<{
  switchVersion: [step: SegmentStep, version: SegmentVersion]
  enterEdit: [step: SegmentStep]
  exitEdit: [step: SegmentStep]
  applyPatch: [step: SegmentStep]
  retry: [index: number]
  confirm: [index: number]
  generateVariant: [index: number]
}>()
</script>

<template>
  <div v-if="showSegmentPanel" class="border-b shrink-0 bg-background flex flex-col" style="max-height: min(380px, 42vh)">
    <div class="flex items-center justify-between px-3 py-1.5 border-b bg-primary/5 shrink-0">
      <span class="text-xs font-semibold text-primary flex items-center gap-1.5">
        <Zap class="h-3 w-3" />
        内部四段审阅
        <span v-if="currentSegmentIdx >= 0" class="text-muted-foreground font-normal">
          {{ currentSegmentIdx + 1 }} / {{ segmentSteps.length }}
        </span>
        <span class="text-muted-foreground font-normal">
          第{{ generationTarget.episodeNo }}集 · 第{{ generationTarget.sceneNo }}场
        </span>
      </span>
      <div class="flex items-center gap-1.5 flex-1 justify-center mx-3">
        <template v-for="(s, i) in segmentSteps" :key="s.id">
          <div class="flex items-center gap-1">
            <div class="w-2 h-2 rounded-full transition-all"
              :class="{
                'bg-emerald-500': s.status === 'confirmed',
                'bg-primary animate-pulse': s.status === 'generating',
                'bg-amber-400': s.status === 'reviewing',
                'bg-red-400': s.status === 'error',
                'bg-muted-foreground/25': s.status === 'pending',
              }" :title="s.label" />
            <span v-if="i < segmentSteps.length - 1" class="text-muted-foreground/30 text-[10px]">—</span>
          </div>
        </template>
      </div>
      <button v-if="!isSegmentGenerating" class="text-xs text-muted-foreground hover:text-foreground p-0.5 rounded"
        title="关闭面板" @click="showSegmentPanel = false">✕</button>
      <span v-else class="text-[11px] text-muted-foreground">生成中…</span>
    </div>

    <div class="flex-1 overflow-y-auto">
      <template v-for="(step, si) in segmentSteps" :key="step.id">
        <div v-if="step.status === 'confirmed' && si < currentSegmentIdx"
          class="px-3 py-2 border-b bg-emerald-50/30 dark:bg-emerald-950/10">
          <details class="group">
            <summary class="flex items-center gap-2 cursor-pointer list-none text-xs text-emerald-700 dark:text-emerald-400 select-none">
              <span class="font-medium">✓ {{ step.label }}</span>
              <span class="text-muted-foreground">{{ countScriptChars(step.editedContent) }}字</span>
              <span class="ml-auto text-[10px] text-muted-foreground group-open:hidden">▸ 展开</span>
              <span class="ml-auto text-[10px] text-muted-foreground hidden group-open:block">▾ 收起</span>
            </summary>
            <div class="mt-2 font-mono text-xs leading-relaxed rounded border bg-muted/20 p-2 max-h-40 overflow-auto whitespace-pre-wrap break-all">
              {{ step.editedContent }}
            </div>
          </details>
        </div>
      </template>

      <template v-if="currentSegmentStep">
        <div v-for="step in [currentSegmentStep]" :key="step.id" class="px-3 py-2">
          <div class="flex items-center gap-2 mb-2">
            <span class="text-xs font-semibold">{{ step.label }}</span>
            <span class="text-[11px] text-muted-foreground">{{ step.desc }}</span>
            <span v-if="step.status === 'generating'" class="text-[11px] text-primary animate-pulse ml-auto">AI 生成中…</span>
            <span v-else-if="step.status === 'error'" class="text-[11px] text-red-500 ml-auto">生成失败</span>
            <div v-else-if="step.status === 'reviewing'" class="ml-auto flex items-center gap-1">
              <span class="text-[10px] text-muted-foreground flex items-center gap-1">
                <span class="inline-block w-2 h-2 rounded-sm bg-green-200 dark:bg-green-800"></span>AI改
                <span class="inline-block w-2 h-2 rounded-sm bg-blue-200 dark:bg-blue-800 ml-1"></span>手改
              </span>
              <template v-if="step.versionB && step.versionB !== step.versionA">
                <button class="text-[11px] px-2 py-0.5 rounded border transition-all"
                  :class="step.activeVersion === 'A' ? 'bg-primary text-primary-foreground border-primary' : 'border-muted-foreground/30 text-muted-foreground hover:border-primary/50'"
                  @click="$emit('switchVersion', step, 'A')">版A</button>
                <button class="text-[11px] px-2 py-0.5 rounded border transition-all"
                  :class="step.activeVersion === 'B' ? 'bg-primary text-primary-foreground border-primary' : 'border-muted-foreground/30 text-muted-foreground hover:border-primary/50'"
                  @click="$emit('switchVersion', step, 'B')">版B</button>
              </template>
              <button v-else class="text-[11px] px-2 py-0.5 rounded border border-muted-foreground/30 text-muted-foreground hover:border-primary/50 hover:text-primary transition-all disabled:opacity-50"
                :disabled="isSegmentGenerating || step.isGeneratingVariant"
                @click="$emit('generateVariant', currentSegmentIdx)">
                {{ step.isGeneratingVariant ? 'B版生成中...' : '生成B版' }}
              </button>
              <span class="text-[11px] text-muted-foreground ml-1">{{ countScriptChars(step.editedContent) }}字</span>
            </div>
            <span v-else-if="step.status === 'confirmed'" class="text-[11px] text-emerald-600 ml-auto">✓ 已确认 {{ countScriptChars(step.editedContent) }}字</span>
          </div>

          <div v-if="step.status === 'generating'" class="py-3">
            <div v-if="step.editedContent.trim()"
              class="font-mono text-xs leading-relaxed rounded border bg-muted/20 p-2 overflow-auto"
              style="max-height:220px; white-space:pre-wrap; word-break:break-all">
              <div v-for="(line, li) in step.editedContent.split('\n')" :key="li">{{ line || '\u200b' }}</div>
            </div>
            <div v-else class="space-y-1.5">
              <div v-for="j in 6" :key="j" class="h-3 rounded bg-muted animate-pulse" :style="{ width: (60 + Math.random()*35) + '%' }"></div>
            </div>
          </div>

          <div v-else-if="step.status === 'error'" class="py-3 text-center">
            <p class="text-sm text-red-500 mb-2">{{ step.label }}生成失败，请重试</p>
            <div class="mx-auto mb-2 max-w-xl rounded-md border border-red-200 bg-red-50 px-3 py-2 text-left text-xs text-red-700 dark:border-red-900/60 dark:bg-red-950/20 dark:text-red-300">
              <p class="font-medium">失败原因：{{ step.lastErrorDetail || '暂未拿到后端详情' }}</p>
              <p v-if="step.lastErrorSuggestion" class="mt-1">处理建议：{{ step.lastErrorSuggestion }}</p>
              <p v-if="step.lastErrorCode" class="mt-1 text-red-600/80 dark:text-red-300/80">错误码：{{ step.lastErrorCode }}</p>
              <ul v-if="step.lastErrorIssues?.length" class="mt-1 list-disc pl-4">
                <li v-for="issue in step.lastErrorIssues.slice(0, 3)" :key="issue">{{ issue }}</li>
              </ul>
            </div>
            <button class="text-xs px-3 py-1 rounded border border-red-300 text-red-500 hover:bg-red-50 dark:hover:bg-red-950/30"
              :data-generation-episode="generationTarget.episodeNo"
              :data-generation-scene="generationTarget.sceneNo"
              :data-generation-segment="step.id"
              @click="$emit('retry', currentSegmentIdx)">重试此段</button>
          </div>

          <template v-else-if="step.status === 'reviewing' || step.status === 'confirmed'">
            <textarea v-if="step.editMode"
              v-model="step.editedContent"
              class="w-full font-mono text-xs leading-relaxed rounded border bg-background resize-none focus:outline-none focus:ring-1 focus:ring-primary p-2"
              style="min-height:140px; max-height:220px"
              placeholder="直接编辑内容…"
            />
            <div v-else
              class="font-mono text-xs leading-relaxed rounded border bg-muted/20 p-2 overflow-auto"
              style="max-height:220px; white-space:pre-wrap; word-break:break-all">
              <div v-for="(line, li) in step.editedContent.split('\n')" :key="li"
                class="rounded-sm px-0.5 transition-colors"
                :class="{
                  'bg-green-100 dark:bg-green-900/40': step.lineOrigins[li] === 'ai-revised',
                  'bg-blue-100 dark:bg-blue-900/40': step.lineOrigins[li] === 'user-edited',
                }">{{ line || '\u200b' }}</div>
            </div>

            <div v-if="step.status === 'reviewing'" class="mt-2">
              <div v-if="step.isSuggesting" class="flex items-center gap-1.5 text-[11px] text-muted-foreground py-1">
                <span class="inline-block w-3 h-3 border-2 border-primary border-t-transparent rounded-full animate-spin"></span>
                正在分析改进建议…
              </div>
              <div v-else-if="step.suggestions.length" class="space-y-1">
                <p class="text-[11px] font-medium text-muted-foreground">💡 AI 建议（可直接发给 AI 修改）</p>
                <div v-for="(sug, si) in step.suggestions" :key="si"
                  class="text-[11px] rounded border border-dashed border-muted-foreground/30 px-2 py-1 hover:border-primary/50 hover:bg-primary/5 cursor-pointer transition-all group"
                  @click="step.patchInstruction = sug; step.isPatchPanelOpen = true">
                  <span class="text-muted-foreground group-hover:text-foreground">{{ sug }}</span>
                  <span class="text-primary opacity-0 group-hover:opacity-100 ml-1 text-[10px]">→ 应用</span>
                </div>
              </div>
            </div>

            <div v-if="step.status === 'reviewing' && step.isPatchPanelOpen"
              class="mt-2 rounded-lg border border-amber-200 dark:border-amber-700 bg-amber-50 dark:bg-amber-950/20 p-2 space-y-1.5">
              <p class="text-[11px] font-medium text-amber-700 dark:text-amber-400">✏️ AI 局部修改（仅替换选中片段）</p>
              <textarea
                v-model="step.patchSelectedText"
                placeholder="粘贴或输入要修改的原文片段…"
                class="w-full text-xs font-mono rounded border bg-background resize-none p-1.5 focus:outline-none focus:ring-1 focus:ring-amber-400"
                rows="2"
              />
              <textarea
                v-model="step.patchInstruction"
                placeholder="修改指令，如：让这句话更有力量感，加强冲突…"
                class="w-full text-xs rounded border bg-background resize-none p-1.5 focus:outline-none focus:ring-1 focus:ring-amber-400"
                rows="2"
              />
              <div class="flex gap-1.5">
                <button class="text-xs px-3 py-1 rounded bg-amber-500 text-white hover:bg-amber-600 disabled:opacity-50 flex items-center gap-1"
                  :disabled="step.isPatching || !step.patchSelectedText.trim() || !step.patchInstruction.trim()"
                  @click="$emit('applyPatch', step)">
                  <span v-if="step.isPatching" class="inline-block w-3 h-3 border-2 border-white border-t-transparent rounded-full animate-spin"></span>
                  {{ step.isPatching ? 'AI改写中…' : '执行修改' }}
                </button>
                <button class="text-xs px-2 py-1 rounded border text-muted-foreground hover:text-foreground"
                  @click="step.isPatchPanelOpen = false">取消</button>
              </div>
            </div>

            <div v-if="step.status === 'reviewing'" class="mt-2.5 flex items-center gap-2 flex-wrap">
              <button class="text-[11px] px-2 py-1 rounded border border-muted-foreground/30 text-muted-foreground hover:border-primary/50 hover:text-primary transition-all"
                @click="step.editMode ? $emit('exitEdit', step) : $emit('enterEdit', step)">
                {{ step.editMode ? '完成编辑' : '手动编辑' }}
              </button>
              <button class="text-[11px] px-2 py-1 rounded border border-muted-foreground/30 text-muted-foreground hover:border-amber-500/70 hover:text-amber-600 transition-all"
                @click="step.isPatchPanelOpen = !step.isPatchPanelOpen">
                AI 修改
              </button>
              <button class="text-[11px] px-2 py-1 rounded border border-muted-foreground/30 text-muted-foreground hover:border-muted-foreground/60 transition-all"
                :disabled="isSegmentGenerating"
                :data-generation-episode="generationTarget.episodeNo"
                :data-generation-scene="generationTarget.sceneNo"
                :data-generation-segment="step.id"
                @click="$emit('retry', currentSegmentIdx)">重新生成</button>
              <button class="ml-auto text-xs px-4 py-1.5 rounded-full bg-primary text-primary-foreground hover:opacity-90 font-medium flex items-center gap-1 disabled:opacity-50"
                :disabled="isSegmentGenerating || step.editMode"
                @click="$emit('confirm', currentSegmentIdx)">
                确认
                <span v-if="currentSegmentIdx < segmentSteps.length - 1">→ 生成下一段</span>
                <span v-else>完成全部</span>
              </button>
            </div>
          </template>
        </div>
      </template>

      <div v-else class="px-3 py-4 text-center text-xs text-muted-foreground">
        正在准备…
      </div>
    </div>

    <div class="shrink-0 border-t px-3 py-1.5 flex items-center gap-0 bg-muted/10">
      <template v-for="(s, i) in segmentSteps" :key="s.id">
        <div class="flex-1 flex flex-col items-center gap-0.5 cursor-default"
          :title="`${s.label}（${s.status}）`">
          <div class="text-[10px] font-medium transition-colors"
            :class="{
              'text-emerald-600': s.status === 'confirmed',
              'text-primary': s.status === 'reviewing' || s.status === 'generating',
              'text-red-500': s.status === 'error',
              'text-muted-foreground/50': s.status === 'pending',
            }">{{ s.label }}</div>
          <div class="h-1 w-full rounded-full transition-all"
            :class="{
              'bg-emerald-500': s.status === 'confirmed',
              'bg-primary animate-pulse': s.status === 'generating',
              'bg-amber-400': s.status === 'reviewing',
              'bg-red-400': s.status === 'error',
              'bg-muted-foreground/20': s.status === 'pending',
            }" />
        </div>
        <div v-if="i < segmentSteps.length - 1" class="w-2 shrink-0" />
      </template>
    </div>
  </div>
</template>
