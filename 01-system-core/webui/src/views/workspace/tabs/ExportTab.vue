<script setup lang="ts">
import { Badge } from '@/components/ui/badge'
import { CheckCircle2, Download } from 'lucide-vue-next'

type ExportFormat = {
  id: string
  label: string
  desc: string
  icon: string
}

type ExportReadinessItem = {
  id: string
  label: string
  ready: boolean
  message: string
}

defineProps<{
  readinessItems: ExportReadinessItem[]
  exportFormats: ExportFormat[]
  copyExportLocked?: boolean
}>()

defineEmits<{
  exportProject: [format: string]
}>()
</script>

<template>
  <div class="flex-1 overflow-auto">
    <div class="max-w-2xl mx-auto px-6 py-10">
      <div class="text-center mb-8">
        <Download class="h-12 w-12 text-primary mx-auto mb-3" />
        <h2 class="text-2xl font-bold mb-2">导出你的作品</h2>
        <p class="text-muted-foreground">选择导出格式，生成完整的剧本文件</p>
      </div>

      <div
        v-if="copyExportLocked"
        class="mb-6 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800"
      >
        当前密钥未开启复制导出权限，作品可继续编辑，导出需联系管理员开启。
      </div>

      <div class="bg-card border rounded-xl p-5 mb-6">
        <h3 class="font-medium mb-4">完成度检查</h3>
        <div class="space-y-3">
          <div v-for="item in readinessItems" :key="item.id" class="flex items-center gap-3">
            <CheckCircle2
              class="h-5 w-5 shrink-0"
              :class="item.ready ? 'text-emerald-500' : 'text-muted-foreground/30'"
            />
            <span class="text-sm" :class="item.ready ? '' : 'text-muted-foreground'">
              {{ item.label }}
            </span>
            <Badge
              variant="outline"
              class="ml-auto text-xs"
              :class="item.ready ? 'text-emerald-600 border-emerald-300' : 'text-amber-600 border-amber-300'"
            >
              {{ item.ready ? '已完成' : item.message }}
            </Badge>
          </div>
        </div>
      </div>

      <div class="grid grid-cols-2 gap-4">
        <button
          v-for="fmt in exportFormats"
          :key="fmt.id"
          class="bg-card border rounded-xl p-5 text-left transition-all group"
          :class="copyExportLocked ? 'cursor-not-allowed opacity-55' : 'hover:border-primary/40 hover:shadow-sm'"
          :disabled="copyExportLocked"
          @click="$emit('exportProject', fmt.id)"
        >
          <div class="text-3xl mb-2">{{ fmt.icon }}</div>
          <div class="font-medium group-hover:text-primary transition-colors">{{ fmt.label }}</div>
          <p class="text-xs text-muted-foreground mt-1">{{ fmt.desc }}</p>
        </button>
      </div>
    </div>
  </div>
</template>
