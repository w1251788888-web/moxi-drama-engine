<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import { Paperclip, Send } from 'lucide-vue-next'
import { Button } from '@/components/ui/button'
import { ScrollArea } from '@/components/ui/scroll-area'
import {
  CHAT_VISIBLE_INITIAL_MESSAGES,
  countContextChars,
  type BrainstormChatMessage,
  type ChatContextTrace,
} from '@/features/workspace/utils/chatBrainstormContext'

const props = defineProps<{
  messages: BrainstormChatMessage[]
  loading: boolean
  submitChat: (content: string) => Promise<boolean>
  maxMessageChars: number
  contextTrace?: ChatContextTrace
  contextBlocked: boolean
  openOutlineForContext: () => void
  saveStatus: 'saved' | 'unsaved'
  retrySave: () => Promise<boolean>
  referenceLoading: boolean
}>()

const emit = defineEmits<{
  'upload-reference': [file: File]
}>()

const input = ref('')
const fileInput = ref<HTMLInputElement | null>(null)
const isComposing = ref(false)
const isSubmitting = ref(false)
const visibleMessageCount = ref(CHAT_VISIBLE_INITIAL_MESSAGES)
const messageEnd = ref<HTMLElement | null>(null)
const quickSuggestions = ['帮我评估这个选题', '给我三个可做选题方向', '分析热门短剧趋势']
const visibleMessages = computed(() => props.messages.slice(Math.max(0, props.messages.length - visibleMessageCount.value)))
const hasEarlierMessages = computed(() => visibleMessages.value.length < props.messages.length)
const inputCharCount = computed(() => countContextChars(input.value))
const includedMessageCount = computed(() => (
  Array.isArray(props.contextTrace?.included_message_ids) ? props.contextTrace.included_message_ids.length : 0
))
const excludedMessageCount = computed(() => (
  Array.isArray(props.contextTrace?.omitted_message_ids) ? props.contextTrace.omitted_message_ids.length : 0
))

interface AssistantMessageBlock {
  type: 'gap' | 'heading' | 'list' | 'paragraph'
  text: string
}

function cleanInlineMarkdown(value: string) {
  return value
    .replace(/\*\*(.*?)\*\*/g, '$1')
    .replace(/`([^`]+)`/g, '$1')
}

function parseAssistantMessageBlocks(content: string): AssistantMessageBlock[] {
  const blocks = content
    .replace(/\r\n/g, '\n')
    .split('\n')
    .map(line => line.trimEnd())
    .filter(line => !/^[-*_]{3,}$/.test(line.trim()))
    .map((line) => {
    const trimmed = line.trim()
    if (!trimmed) return { type: 'gap', text: '' } as AssistantMessageBlock
    if (/^#{1,4}\s+/.test(trimmed)) {
      return { type: 'heading', text: cleanInlineMarkdown(trimmed.replace(/^#{1,4}\s+/, '')) } as AssistantMessageBlock
    }
    if (/^\d+[.、]\s+/.test(trimmed) || /^[-•]\s+/.test(trimmed)) {
      return {
        type: 'list',
        text: cleanInlineMarkdown(trimmed.replace(/^\d+[.、]\s+/, '').replace(/^[-•]\s+/, '')),
      } as AssistantMessageBlock
    }
    return { type: 'paragraph', text: cleanInlineMarkdown(trimmed) } as AssistantMessageBlock
  })

  return blocks.length ? blocks : [{ type: 'paragraph', text: '' }]
}

function renderAssistantMessage(content: string): AssistantMessageBlock[] {
  return parseAssistantMessageBlocks(content)
}

async function sendCurrentInput() {
  const content = input.value
  if (!content.trim()) return
  const accepted = await submitChatOnce(content)
  if (!accepted) return
  // 用户可在请求等待期间继续输入；不能因为上一轮成功而清掉新写的文字。
  if (input.value === content) input.value = ''
}

async function submitChatOnce(content: string): Promise<boolean> {
  if (isSubmitting.value || props.loading || props.referenceLoading) return false
  isSubmitting.value = true
  try {
    return await props.submitChat(content)
  } finally {
    isSubmitting.value = false
  }
}

async function sendSuggestion(content: string) {
  await submitChatOnce(content)
}

function handleCompositionStart() {
  isComposing.value = true
}

function handleCompositionEnd() {
  isComposing.value = false
}

function handleComposerKeydown(event: KeyboardEvent) {
  if (event.key !== 'Enter' || event.shiftKey || event.isComposing || isComposing.value || event.keyCode === 229) return
  event.preventDefault()
  void sendCurrentInput()
}

function expandEarlierMessages() {
  visibleMessageCount.value += CHAT_VISIBLE_INITIAL_MESSAGES
}

function openFilePicker() {
  fileInput.value?.click()
}

function handleFileSelected(event: Event) {
  const target = event.target as HTMLInputElement
  const file = target.files?.[0]
  target.value = ''
  if (!file) return
  emit('upload-reference', file)
}

async function scrollToLatestMessage() {
  await nextTick()
  messageEnd.value?.scrollIntoView({ block: 'end', behavior: 'smooth' })
}

watch(
  [
    () => props.messages.length,
    () => props.messages[props.messages.length - 1]?.content || '',
    () => props.loading,
  ],
  () => { void scrollToLatestMessage() },
  { immediate: true },
)
</script>

<template>
  <div class="flex-1 min-w-0 flex flex-col overflow-hidden">
    <ScrollArea class="flex-1">
      <div class="max-w-3xl mx-auto px-6 py-6 space-y-4">
        <div v-if="hasEarlierMessages" class="flex justify-center">
          <Button variant="outline" size="sm" @click="expandEarlierMessages">
            展开更早记录（每次 {{ CHAT_VISIBLE_INITIAL_MESSAGES }} 条）
          </Button>
        </div>
        <div
          v-for="msg in visibleMessages"
          :key="msg.id"
          class="flex gap-3"
          :class="msg.role === 'user' ? 'flex-row-reverse' : ''"
        >
          <div
            class="w-8 h-8 rounded-full flex items-center justify-center shrink-0 text-xs font-bold"
            :class="msg.role === 'ai' ? 'bg-primary/10 text-primary' : 'bg-muted text-muted-foreground'"
          >
            {{ msg.role === 'ai' ? 'AI' : '我' }}
          </div>
          <div
            class="max-w-[75%] rounded-2xl px-4 py-3 text-sm leading-relaxed whitespace-pre-wrap"
            :class="msg.role === 'ai'
              ? 'bg-card border text-foreground rounded-tl-sm'
              : 'bg-primary text-primary-foreground rounded-tr-sm'"
          >
            <div v-if="msg.role === 'ai'" class="chat-message-rendered">
              <template
                v-for="(block, blockIndex) in renderAssistantMessage(msg.content)"
                :key="blockIndex"
              >
                <div v-if="block.type === 'gap'" class="chat-gap" />
                <div v-else-if="block.type === 'heading'" class="chat-heading">{{ block.text }}</div>
                <div v-else-if="block.type === 'list'" class="chat-list-row">{{ block.text }}</div>
                <p v-else>{{ block.text }}</p>
              </template>
            </div>
            <template v-else>{{ msg.content }}</template>
          </div>
        </div>
        <div v-if="props.loading" class="flex gap-3">
          <div class="w-8 h-8 rounded-full bg-primary/10 flex items-center justify-center text-xs font-bold text-primary shrink-0">AI</div>
          <div class="bg-card border rounded-2xl rounded-tl-sm px-4 py-3">
            <div class="flex gap-1">
              <div class="w-2 h-2 rounded-full bg-muted-foreground/50 animate-bounce" style="animation-delay:0ms" />
              <div class="w-2 h-2 rounded-full bg-muted-foreground/50 animate-bounce" style="animation-delay:150ms" />
              <div class="w-2 h-2 rounded-full bg-muted-foreground/50 animate-bounce" style="animation-delay:300ms" />
            </div>
          </div>
        </div>
        <div ref="messageEnd" class="h-1" />
      </div>
    </ScrollArea>

    <div class="border-t bg-card p-4">
      <div class="max-w-3xl mx-auto space-y-3">
        <div class="flex flex-wrap gap-2">
          <button
            v-for="q in quickSuggestions"
            :key="q"
            class="text-xs px-3 py-1.5 rounded-full border bg-muted/50 hover:bg-primary/10 hover:border-primary/40 hover:text-primary transition-all disabled:cursor-not-allowed disabled:opacity-50"
            :disabled="props.loading || props.referenceLoading || isSubmitting"
            @click="void sendSuggestion(q)"
          >
            {{ q }}
          </button>
        </div>
        <div class="rounded-xl border bg-background px-3 py-2 shadow-sm focus-within:ring-2 focus-within:ring-primary/30">
          <textarea
            v-model="input"
            placeholder="聊天脑暴负责选题和创作探讨。自然语言直接发给大模型；只有右侧明确确认的内容才进入大纲资料。"
            rows="3"
            class="chat-composer block w-full resize-y border-0 bg-transparent text-sm leading-6 outline-none placeholder:text-muted-foreground"
            :disabled="props.referenceLoading"
            @compositionstart="handleCompositionStart"
            @compositionend="handleCompositionEnd"
            @keydown="handleComposerKeydown"
          />
          <div class="mt-2 flex items-center justify-between gap-3">
            <div class="flex min-w-0 items-center gap-2">
              <input
                ref="fileInput"
                type="file"
                class="hidden"
                accept=".docx,.md,.markdown,.txt"
                @change="handleFileSelected"
              />
              <Button
                type="button"
                variant="ghost"
                size="sm"
                class="h-8 shrink-0 gap-1.5 px-2 text-xs text-muted-foreground"
                :disabled="props.loading || props.referenceLoading || isSubmitting"
                @click="openFilePicker"
              >
                <Paperclip class="h-4 w-4" />
                {{ props.referenceLoading ? '正在读取...' : '上传剧本' }}
              </Button>
              <div
                class="truncate text-xs text-muted-foreground"
                :class="{ 'text-destructive': inputCharCount > props.maxMessageChars }"
              >
                {{ inputCharCount.toLocaleString() }} / {{ props.maxMessageChars.toLocaleString() }} 字符
              </div>
            </div>
            <Button class="h-9 px-4" :disabled="props.loading || props.referenceLoading || isSubmitting || !input.trim()" @click="sendCurrentInput">
              <Send class="h-4 w-4" />
              <span class="ml-1">发送</span>
            </Button>
          </div>
        </div>
        <div class="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
          <span v-if="props.referenceLoading">正在读取剧本并整理聊天参考摘要。</span>
          <span v-else-if="props.loading">本轮已发送，正在生成回复。</span>
          <span v-else-if="isSubmitting">本轮正在提交并保存。</span>
          <span v-else-if="props.contextTrace">最近一次已发送。</span>
          <span v-else>本轮尚未发送。</span>
          <span v-if="props.contextTrace">
            最近一次上下文：纳入 {{ includedMessageCount }} 条，未纳入 {{ excludedMessageCount }} 条。
          </span>
          <span v-if="props.saveStatus === 'saved'">聊天记录已保存。</span>
          <template v-else>
            <span class="text-amber-700 dark:text-amber-400">聊天记录尚未保存，正在等待重试。</span>
            <button class="underline underline-offset-2 hover:text-foreground" @click="void props.retrySave()">重试保存</button>
          </template>
          <template v-if="props.contextBlocked">
            <span class="text-amber-700 dark:text-amber-400">本轮上下文被完整性保护阻断，原文已保留。</span>
            <button class="underline underline-offset-2 hover:text-foreground" @click="props.openOutlineForContext">进入大纲资料包确认</button>
          </template>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.chat-message-rendered p {
  margin: 0 0 0.55rem;
}

.chat-message-rendered p:last-child {
  margin-bottom: 0;
}

.chat-message-rendered .chat-heading {
  margin: 0.65rem 0 0.35rem;
  font-weight: 700;
}

.chat-message-rendered .chat-heading:first-child {
  margin-top: 0;
}

.chat-message-rendered .chat-list-row {
  position: relative;
  margin: 0.35rem 0;
  padding-left: 1rem;
}

.chat-message-rendered .chat-list-row::before {
  content: '';
  position: absolute;
  left: 0.15rem;
  top: 0.72em;
  width: 0.28rem;
  height: 0.28rem;
  border-radius: 999px;
  background: currentColor;
  opacity: 0.55;
}

.chat-message-rendered .chat-gap {
  height: 0.35rem;
}

.chat-composer {
  min-height: 4.5rem;
  max-height: 14rem;
}
</style>
