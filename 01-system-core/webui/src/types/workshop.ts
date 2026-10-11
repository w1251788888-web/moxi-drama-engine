// 工作流类型定义

export type WorkshopStage = 'outline' | 'character' | 'script'

// 大纲数据
export interface OutlineData {
  id: string
  title: string
  genre: string
  setting: string
  protagonist: {
    name: string
    background: string
    desire: string
  }
  coreConflict: {
    obstacle: string
    cost: string
  }
  goldenFinger?: string
  totalEpisodes: number
  rhythmPattern: string
  paywallDesign: {
    episode5: string
    episode10: string
  }
  twist: string
  ending: string
  episodes: Episode[]
}

export interface Episode {
  id: string
  episodeNumber: number
  title: string
  hook: string
  plotPoints: string[]
  cliffhanger: string
  wordCount: number
  status: 'draft' | 'ai_modified' | 'human_edited' | 'final'
  modifications?: Modification[]
}

// 修改记录
export interface Modification {
  id: string
  type: 'human' | 'ai_add' | 'ai_modify' | 'ai_delete'
  originalContent?: string
  newContent: string
  timestamp: Date
  applied: boolean
  author: string
}

// 角色数据
export interface CharacterData {
  characters: Character[]
  relationshipMap: Record<string, Relationship[]>
}

export interface Character {
  id: string
  name: string
  role: 'protagonist' | 'antagonist' | 'supporting' | 'minor'
  age: number
  occupation: string
  background: string
  motivation: string
  arc: string
  relationships: Relationship[]
  appearance?: {
    appearance: string
    clothing: string
    voice: string
  }
}

export interface Relationship {
  targetId: string
  targetName: string
  type: string
  earlyType?: string
  lateType?: string
  transitionEpisode?: number | null
  transitionTrigger?: string
  finalBoundary?: string
  candidateStatus?: string
  strength: number
  description: string
  episodes: number[]
}

// 剧本数据
export interface ScriptData {
  id: string
  title: string
  episodes: ScriptEpisode[]
  totalWordCount: number
  lastSaved: Date | null
}

export interface ScriptEpisode {
  id: string
  episodeNumber: number
  title: string
  content: string
  wordCount: number
  status: 'draft' | 'ai_modified' | 'human_edited' | 'final'
  modifications?: Modification[]
}

// AI 助手
export interface AIAssistantMessage {
  id: string
  role: 'user' | 'assistant'
  content: string
  type?: 'text' | 'suggestion' | 'action'
  actions?: QuickAction[]
  timestamp: Date
}

export interface QuickAction {
  id: string
  label: string
  icon: string
  prompt: string
}
