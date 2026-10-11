import { computed, ref, type Ref } from 'vue'
import { userAccessApi } from '@/api/client'
import { extractAiError, formatAiErrorMessage, formatUserFacingErrorMessage } from '@/api/http'
import type { WorkspaceTabId } from './useWorkspaceTabs'

export type AiAssistantMessage = {
  role: 'user' | 'ai'
  content: string
  time: string
}

export type AiAssistantContext = {
  audience_axis?: string
  genre_main?: string
  format_type?: string
}

const QUICK_PROMPTS: Record<WorkspaceTabId, string[]> = {
  chat: ['帮我想一个爆款题材', '分析当前热门短剧趋势', '给我三个差异化故事方向', '这个想法有什么问题？'],
  outline: ['帮我完善一句话梗概', '分析我的大纲结构', '建议金手指设定', '优化分集节奏'],
  characters: ['帮我设计主角人设', '建议角色弧光', '优化人物关系张力', '设计配角'],
  script: ['续写当前集', '增加情绪张力', '优化台词', '检查节奏'],
  compliance: ['检查高风险表达', '给出改写建议', '说明审核依据'],
  storyboard: ['描述场景氛围', '建议镜头语言', '优化场景过渡'],
  export: ['检查整体完成度', '导出前建议', '格式说明'],
  'legal-assets': ['生成AI创作说明', '检查资料缺口', '整理投递包清单'],
}

export function useAiAssistant(options: {
  activeTab: Ref<WorkspaceTabId>
  getContext: () => AiAssistantContext
}) {
  const aiPanelOpen = ref(true)
  const aiMessages = ref<AiAssistantMessage[]>([
    {
      role: 'ai',
      content: '你好！无论是故事构思、角色设计还是台词打磨，都可以直接问我。',
      time: '现在',
    },
  ])
  const aiLoading = ref(false)

  const quickPrompts = computed(() => QUICK_PROMPTS[options.activeTab.value] || [])

  async function sendAIMessage(content: string) {
    const msg = content.trim()
    if (!msg) return
    aiMessages.value.push({ role: 'user', content: msg, time: '刚刚' })
    aiLoading.value = true
    const context = options.getContext()
    try {
      const { data } = await userAccessApi.aiChat({
        messages: aiMessages.value
          .filter(m => m.role !== 'ai' || aiMessages.value.indexOf(m) < aiMessages.value.length - 1)
          .map(m => ({ role: m.role === 'ai' ? 'assistant' : 'user', content: m.content })),
        context: options.activeTab.value,
        max_tokens: 600,
        audience_axis: context.audience_axis || '',
        genre: context.genre_main || '',
        format_type: context.format_type || '真人短剧',
      })
      aiMessages.value.push({ role: 'ai', content: data.content, time: '刚刚' })
    } catch (e: any) {
      const aiError = extractAiError(e)
      const errMsg = aiError
        ? formatAiErrorMessage(aiError)
        : formatUserFacingErrorMessage(e, 'AI助手暂时不可用')
      aiMessages.value.push({ role: 'ai', content: errMsg, time: '刚刚' })
    } finally {
      aiLoading.value = false
    }
  }

  return {
    aiPanelOpen,
    aiMessages,
    aiLoading,
    quickPrompts,
    sendAIMessage,
  }
}
