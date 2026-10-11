<script setup lang="ts">
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import { Lock, Wand2 } from 'lucide-vue-next'

type ProjectRules = {
  word_count_per_episode: string
}

type ManualEditMarker = {
  lineNo: number
  kind: 'added' | 'changed' | 'removed'
  text: string
}

defineProps<{
  scriptNetCharCount: number
  projectRules: ProjectRules
  selectedEpisode: number
  hasUnsavedChanges?: boolean
  isPendingModelCandidate?: boolean
  manualEditMarkers?: ManualEditMarker[]
  canLockCurrentEpisode: boolean
  isLockingCurrentEpisode: boolean
  canGenerateNextEpisode: boolean
  isGeneratingNextEpisode: boolean
  isSegmentedDraftIncomplete?: boolean
  nextEpisodeGateMessage?: string
}>()

const sceneContent = defineModel<string>('sceneContent', { required: true })

const emit = defineEmits<{
  lockCurrentEpisode: []
  next: []
  generateNextEpisodeResearch: []
}>()

function emitLockCurrentEpisode() {
  const runtime = window as typeof window & { __moxiLockTrace?: Array<Record<string, unknown>> }
  const appendTrace = (payload: Record<string, unknown>) => {
    console.info('[LOCK_TRACE]', JSON.stringify(payload))
    const trace = Array.isArray(runtime.__moxiLockTrace) ? runtime.__moxiLockTrace : []
    trace.push(payload)
    runtime.__moxiLockTrace = trace
  }
  appendTrace({ label: 'LOCK_T1_button_click', ts: new Date().toISOString() })
  appendTrace({ label: 'LOCK_T1_emit_lockCurrentEpisode', ts: new Date().toISOString() })
  emit('lockCurrentEpisode')
}
</script>

<template>
  <div class="shrink-0 p-3">
    <div class="flex min-h-[70vh] flex-col gap-2">
      <Textarea
        v-model="sceneContent"
        auto-resize
        data-script-editor-textarea="true"
        placeholder="开始写作这一集...&#10;&#10;【标准格式】&#10;【场1-1：夜  内  江家书房】 或 1-1  夜  内  江家书房&#10;人物：角色A，角色B&#10;△动作描写直接入正文&#10;角色名：台词&#10;&#10;一集可以包含多场戏，场次由正文内部自然呈现。"
        class="min-h-[70vh] resize-none overflow-hidden font-mono text-sm leading-relaxed"
        :class="hasUnsavedChanges ? 'border-amber-300 bg-amber-50/40 ring-1 ring-amber-200 dark:border-amber-700 dark:bg-amber-950/20 dark:ring-amber-900/40' : ''"
      />
      <div
        v-if="isPendingModelCandidate"
        class="rounded-md border border-blue-200 bg-blue-50/70 px-2.5 py-2 text-xs text-blue-900 dark:border-blue-800 dark:bg-blue-950/25 dark:text-blue-100"
      >
        <div class="font-medium">AI候选待确认</div>
        <div class="mt-1 text-blue-800/80 dark:text-blue-100/80">
          本集正文来自刚生成的候选稿。你可以直接修改，确认后点击保存，保存后才会成为下一集承接的正史。
        </div>
      </div>
      <div
        v-else-if="hasUnsavedChanges && manualEditMarkers?.length"
        class="rounded-md border border-amber-200 bg-amber-50/70 px-2.5 py-2 text-xs text-amber-900 dark:border-amber-800 dark:bg-amber-950/25 dark:text-amber-100"
      >
        <div class="mb-1 font-medium">人工修改标记</div>
        <div
          v-for="marker in manualEditMarkers"
          :key="`${marker.lineNo}-${marker.kind}-${marker.text}`"
          class="flex gap-2 rounded bg-amber-100/70 px-2 py-1 font-mono dark:bg-amber-900/40"
        >
          <span class="shrink-0 text-amber-700 dark:text-amber-200">第{{ marker.lineNo }}行</span>
          <span class="min-w-0 truncate">{{ marker.text }}</span>
        </div>
      </div>
    </div>
  </div>

  <div class="border-t px-4 py-2 text-xs text-muted-foreground flex items-center justify-between shrink-0 gap-3">
    <span>{{ scriptNetCharCount }} 净字（不含标点） / 目标 {{ projectRules.word_count_per_episode }}</span>
    <div class="flex items-center gap-2 shrink-0">
      <Button
        v-if="canLockCurrentEpisode"
        variant="outline"
        size="sm"
        class="gap-1 text-xs"
        :disabled="isLockingCurrentEpisode"
        @click.stop="emitLockCurrentEpisode"
      >
        <Lock class="h-3.5 w-3.5" />
        {{ isLockingCurrentEpisode ? '锁稿中...' : '锁定本集' }}
      </Button>
      <div v-if="canGenerateNextEpisode" class="relative">
        <button
          type="button"
          class="inline-flex h-8 items-center justify-center gap-1 whitespace-nowrap rounded-md border bg-background px-2.5 text-xs font-medium shadow-xs transition-all hover:bg-accent hover:text-accent-foreground disabled:pointer-events-none disabled:opacity-50"
          :disabled="isGeneratingNextEpisode"
          @click.stop="$emit('generateNextEpisodeResearch')"
        >
          <Wand2 class="h-3.5 w-3.5" />
          {{ isGeneratingNextEpisode ? '下一集准备中...' : `生成第${selectedEpisode + 1}集` }}
        </button>
      </div>
      <span v-else-if="nextEpisodeGateMessage" class="text-xs text-muted-foreground">
        {{ nextEpisodeGateMessage }}
      </span>
      <Button variant="ghost" size="sm" class="gap-1 text-xs" @click="$emit('next')">进入分镜提示词 →</Button>
    </div>
  </div>
</template>
