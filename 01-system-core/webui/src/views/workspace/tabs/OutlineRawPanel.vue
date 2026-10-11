<script setup lang="ts">
import { ref } from 'vue'
import { Button } from '@/components/ui/button'
import { FileText, Sparkles, Upload } from 'lucide-vue-next'

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
  existing_script?: string
}

defineProps<{
  characters: OutlineCharacter[]
  episodes: OutlineEpisode[]
  loading: boolean
  predicting: boolean
  statusMessage?: string
}>()

const rawOutlineText = defineModel<string>('rawOutlineText', { required: true })

const emit = defineEmits<{
  analyze: []
  uploadFile: [file: File]
}>()

const fileInput = ref<HTMLInputElement | null>(null)
const isDragging = ref(false)
const fileError = ref('')

function chooseFile() {
  fileInput.value?.click()
}

function acceptFile(file?: File | null) {
  if (!file) return
  const lowerName = file.name.toLowerCase()
  if (!/\.(docx|md|markdown|txt)$/.test(lowerName)) {
    fileError.value = '当前只支持 Word(.docx)、Markdown(.md) 和 TXT'
    return
  }
  fileError.value = ''
  emit('uploadFile', file)
}

function onFileChange(event: Event) {
  const input = event.target as HTMLInputElement
  acceptFile(input.files?.[0])
  input.value = ''
}

function onDrop(event: DragEvent) {
  event.preventDefault()
  isDragging.value = false
  acceptFile(event.dataTransfer?.files?.[0])
}
</script>

<template>
  <div class="w-72 xl:w-80 border-r flex flex-col shrink-0 bg-muted/10">
    <div class="px-3 py-2 border-b flex items-center justify-between shrink-0">
      <span class="text-xs font-medium text-muted-foreground">大纲原文</span>
      <span class="text-[10px] text-muted-foreground">粘贴 / 上传后自动分割</span>
    </div>
    <div class="px-3 pt-3 shrink-0">
      <button
        type="button"
        class="w-full rounded-lg border border-dashed bg-background px-3 py-3 text-left transition-colors hover:border-primary hover:bg-primary/5"
        :class="isDragging ? 'border-primary bg-primary/10' : 'border-border'"
        @click="chooseFile"
        @dragover.prevent="isDragging = true"
        @dragleave.prevent="isDragging = false"
        @drop="onDrop"
      >
        <input
          ref="fileInput"
          type="file"
          accept=".docx,.md,.markdown,.txt,application/vnd.openxmlformats-officedocument.wordprocessingml.document,text/markdown,text/plain"
          class="hidden"
          @change="onFileChange"
        />
        <div class="flex items-center gap-2 text-xs font-medium text-foreground">
          <span class="flex h-8 w-8 items-center justify-center rounded-md bg-muted">
            <Upload class="h-4 w-4" />
          </span>
          <span>可以拖拽文件进入 / 点击上传</span>
        </div>
        <div class="mt-1 flex items-center gap-1.5 pl-10 text-[11px] text-muted-foreground">
          <FileText class="h-3 w-3" />
          支持 Word、Markdown、TXT，大纲会先读取到下方文本框
        </div>
      </button>
      <p v-if="fileError" class="mt-1 text-[11px] text-destructive">{{ fileError }}</p>
    </div>
    <textarea
      v-model="rawOutlineText"
      placeholder="粘贴完整大纲文本…&#10;&#10;人物、分集、金手指、世界观等都放在这里。系统只会自动分割原文中已有的内容，没有识别到的字段会留空。"
      class="flex-1 resize-none p-3 text-xs bg-transparent leading-relaxed focus:outline-none placeholder:text-muted-foreground/50"
    />
    <div v-if="characters.length || episodes.length" class="px-3 py-2 border-t text-[11px] text-muted-foreground space-y-0.5">
      <div v-if="characters.length">
        👤 {{ characters.length }} 个角色：{{ characters.map(c => c.name).join('、') }}
      </div>
      <div v-if="episodes.length">
        📺 {{ episodes.length }} 集纲
        <span v-if="episodes.some(e => e.existing_script)" class="text-amber-500 ml-1">· 含原稿</span>
      </div>
    </div>
    <div class="p-3 border-t shrink-0">
      <div
        v-if="statusMessage"
        aria-live="polite"
        class="mb-2 rounded-md border border-primary/20 bg-primary/5 px-2.5 py-2 text-[11px] leading-relaxed text-primary"
      >
        {{ statusMessage }}
      </div>
      <Button class="w-full gap-2" :disabled="loading || predicting" @click="emit('analyze')">
        <Sparkles class="h-4 w-4" :class="{ 'animate-spin': loading }" />
        {{ loading ? '自动分割中...' : predicting ? '处理中...' : '自动分割内容' }}
      </Button>
      <p class="mt-2 text-[11px] leading-relaxed text-muted-foreground">
        自动分割后请重点核对角色身份、人物关系、集纲顺序和首尾承接；复杂格式可能需要手动补全。
      </p>
    </div>
  </div>
</template>
