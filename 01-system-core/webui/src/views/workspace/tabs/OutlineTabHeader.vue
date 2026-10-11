<script setup lang="ts">
import { FileText, Save, CheckCircle2 } from 'lucide-vue-next'
import { Button } from '@/components/ui/button'

defineProps<{
  characterCount: number
  episodeCount: number
  saving: boolean
  commitBlocked: boolean
  commitBlockReason: string
}>()

const emit = defineEmits<{
  save: []
  continue: []
}>()
</script>

<template>
  <div class="flex items-center justify-between px-4 py-2.5 border-b shrink-0 bg-card">
    <h2 class="text-sm font-semibold flex items-center gap-2">
      <FileText class="h-4 w-4 text-primary" />大纲编辑器
      <span v-if="characterCount || episodeCount" class="text-xs text-muted-foreground font-normal">
        · {{ characterCount }} 角色 · {{ episodeCount }} 集
      </span>
    </h2>
    <div class="flex gap-2">
      <Button variant="outline" size="sm" class="gap-1.5 h-7 text-xs" :disabled="saving" @click="emit('save')">
        <Save class="h-3.5 w-3.5" />保存
      </Button>
      <Button
        size="sm"
        class="gap-1.5 h-7 text-xs bg-gradient-to-r from-primary to-purple-600"
        :disabled="saving || commitBlocked"
        :title="commitBlockReason || '完成大纲后进入角色设计'"
        @click="emit('continue')"
      >
        <CheckCircle2 class="h-3.5 w-3.5" />完成 → 角色设计
      </Button>
    </div>
  </div>
</template>
