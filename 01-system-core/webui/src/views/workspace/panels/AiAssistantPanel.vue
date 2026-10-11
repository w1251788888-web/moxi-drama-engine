<script setup lang="ts">
import { ref } from 'vue'
import { Sparkles, Send, X } from 'lucide-vue-next'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { ScrollArea } from '@/components/ui/scroll-area'

export interface AiAssistantMessage {
  role: 'user' | 'ai'
  content: string
  time: string
}

defineProps<{
  messages: AiAssistantMessage[]
  quickPrompts: string[]
  loading: boolean
}>()

const emit = defineEmits<{
  close: []
  send: [content: string]
}>()

const input = ref('')

function sendCurrentInput() {
  const content = input.value.trim()
  if (!content) return
  input.value = ''
  emit('send', content)
}

function sendQuickPrompt(content: string) {
  input.value = ''
  emit('send', content)
}
</script>

<template>
  <div class="w-80 border-l bg-card flex flex-col shrink-0">
    <div class="flex items-center justify-between p-3 border-b bg-muted/30">
      <div class="flex items-center gap-2">
        <div class="w-7 h-7 rounded-lg bg-primary/10 flex items-center justify-center">
          <Sparkles class="h-4 w-4 text-primary" />
        </div>
        <span class="font-medium text-sm">AI创作助手</span>
      </div>
      <button class="text-muted-foreground hover:text-foreground p-1 rounded" @click="emit('close')">
        <X class="h-4 w-4" />
      </button>
    </div>

    <ScrollArea class="flex-1">
      <div class="p-3 space-y-3">
        <div
          v-for="(msg, i) in messages"
          :key="i"
          class="flex gap-2"
          :class="msg.role === 'user' ? 'flex-row-reverse' : ''"
        >
          <div
            class="w-6 h-6 rounded-full flex items-center justify-center shrink-0 text-[10px] font-bold"
            :class="msg.role === 'ai' ? 'bg-primary/10 text-primary' : 'bg-muted'"
          >
            {{ msg.role === 'ai' ? 'AI' : '我' }}
          </div>
          <div
            class="max-w-[85%] rounded-xl px-3 py-2 text-xs leading-relaxed whitespace-pre-wrap"
            :class="msg.role === 'ai' ? 'bg-muted text-foreground' : 'bg-primary text-primary-foreground'"
          >
            {{ msg.content }}
          </div>
        </div>
        <div v-if="loading" class="flex gap-2 items-center">
          <div class="w-6 h-6 rounded-full bg-primary/10 flex items-center justify-center text-[10px] font-bold text-primary">AI</div>
          <div class="flex gap-1 px-3 py-2 bg-muted rounded-xl">
            <div class="w-1.5 h-1.5 rounded-full bg-muted-foreground/50 animate-bounce" style="animation-delay:0ms" />
            <div class="w-1.5 h-1.5 rounded-full bg-muted-foreground/50 animate-bounce" style="animation-delay:150ms" />
            <div class="w-1.5 h-1.5 rounded-full bg-muted-foreground/50 animate-bounce" style="animation-delay:300ms" />
          </div>
        </div>
      </div>
    </ScrollArea>

    <div class="p-3 border-t space-y-2">
      <p class="text-[10px] text-muted-foreground uppercase tracking-wider">快捷指令</p>
      <div class="flex flex-wrap gap-1.5">
        <button
          v-for="q in quickPrompts"
          :key="q"
          class="text-[11px] px-2.5 py-1 rounded-full border hover:bg-primary/10 hover:border-primary/40 hover:text-primary transition-all"
          @click="sendQuickPrompt(q)"
        >
          {{ q }}
        </button>
      </div>
    </div>

    <div class="p-3 border-t">
      <div class="flex gap-2">
        <Input
          v-model="input"
          placeholder="问AI任何创作问题..."
          class="flex-1 h-9 text-sm"
          @keyup.enter="sendCurrentInput"
        />
        <Button size="icon" class="h-9 w-9 shrink-0" :disabled="loading || !input.trim()" @click="sendCurrentInput">
          <Send class="h-4 w-4" />
        </Button>
      </div>
    </div>
  </div>
</template>
