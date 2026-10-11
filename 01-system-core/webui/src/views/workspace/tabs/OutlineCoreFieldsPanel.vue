<script setup lang="ts">
import { Textarea } from '@/components/ui/textarea'
import { Badge } from '@/components/ui/badge'
import { Sparkles } from 'lucide-vue-next'

type OutlineData = {
  logline: string
  worldview: string
  goldenFinger: string
  conflict: string
}

defineProps<{
  aiGeneratedFields: Record<string, string>
  sectionLoading: Record<string, boolean>
  sectionSuggestions: Record<string, string>
  aiFeaturesPaused: boolean
}>()

const outlineData = defineModel<OutlineData>('outlineData', { required: true })

defineEmits<{
  getAiSuggestion: [field: string, value: string]
}>()
</script>

<template>
  <div class="space-y-3">
    <div class="space-y-1">
      <div class="flex items-center justify-between">
        <label class="text-xs font-semibold text-muted-foreground uppercase tracking-wide flex items-center gap-1.5">
          一句话梗概
          <Badge v-if="aiGeneratedFields.logline" variant="secondary" class="text-[10px] px-1.5 py-0">AI补全</Badge>
        </label>
        <button
          class="text-[11px] flex items-center gap-1"
          :class="aiFeaturesPaused ? 'cursor-not-allowed text-muted-foreground opacity-60' : 'text-primary hover:underline'"
          :disabled="aiFeaturesPaused || sectionLoading['logline']"
          :title="aiFeaturesPaused ? '功能尚未开发完全，暂时关闭' : '获取 AI 优化建议'"
          @click="$emit('getAiSuggestion', 'logline', outlineData.logline)">
          <Sparkles class="h-3 w-3" />{{ aiFeaturesPaused ? 'AI优化暂停' : sectionLoading['logline'] ? '生成中...' : 'AI优化' }}
        </button>
      </div>
      <Textarea v-model="outlineData.logline"
        placeholder="[主角] 因 [处境/事件] 不得不 [行动]，与 [对手] 展开 [冲突]"
        class="text-sm resize-none min-h-[56px]" />
      <div v-if="sectionSuggestions['logline']" class="bg-blue-50 dark:bg-blue-950/20 border border-blue-200 rounded-lg p-2.5 text-xs text-blue-800 dark:text-blue-300 whitespace-pre-line">
        💡 {{ sectionSuggestions['logline'] }}
      </div>
    </div>

    <div class="grid grid-cols-2 gap-3">
      <div class="space-y-1">
        <label class="text-xs font-semibold text-muted-foreground uppercase tracking-wide flex items-center gap-1.5">
          世界观 / 背景
          <Badge v-if="aiGeneratedFields.worldview" variant="secondary" class="text-[10px] px-1.5 py-0">AI补全</Badge>
        </label>
        <Textarea v-model="outlineData.worldview"
          placeholder="时代背景、地点、特殊规则..."
          class="text-xs resize-none min-h-[72px]" />
      </div>
      <div class="space-y-1">
        <label class="text-xs font-semibold text-muted-foreground uppercase tracking-wide flex items-center gap-1.5">
          金手指 / 特殊设定
          <Badge v-if="aiGeneratedFields.goldenFinger" variant="secondary" class="text-[10px] px-1.5 py-0">AI补全</Badge>
        </label>
        <Textarea v-model="outlineData.goldenFinger"
          placeholder="主角特殊能力、系统外挂、重生/穿越优势..."
          class="text-xs resize-none min-h-[72px]" />
      </div>
    </div>

    <div class="space-y-1">
      <label class="text-xs font-semibold text-muted-foreground uppercase tracking-wide flex items-center gap-1.5">
        核心冲突 / 爽点
        <Badge v-if="aiGeneratedFields.conflict" variant="secondary" class="text-[10px] px-1.5 py-0">AI补全</Badge>
      </label>
      <Textarea v-model="outlineData.conflict"
        placeholder="主要矛盾是什么？观众追看的核心动力是什么？"
        class="text-xs resize-none min-h-[56px]" />
    </div>
  </div>
</template>
