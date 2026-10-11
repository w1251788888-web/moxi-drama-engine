<script setup lang="ts">
import { Button } from '@/components/ui/button'
import { AlertTriangle, CheckCircle2, TrendingUp, Users } from 'lucide-vue-next'
import CharacterEditor from '@/components/workshop/CharacterEditor.vue'
import CharacterGraph from '@/components/workshop/CharacterGraph.vue'

type Character = {
  id: string
  name: string
  role: 'protagonist' | 'antagonist' | 'supporting' | 'minor'
  age: number
  occupation: string
  background: string
  motivation: string
  arc: string
  personality?: string
  voice_style?: string
  traits?: string
  notes?: string
  appearance?: string
  relationships: Array<{
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
  }>
}

defineProps<{
  projectId: string
  characters: Character[]
  roleColors: Record<string, string>
  sceneContent: string
  genre: string
}>()

const selectedCharacterId = defineModel<string | null>('selectedCharacterId', { required: true })
const showCharacterGraph = defineModel<boolean>('showCharacterGraph', { required: true })

const emit = defineEmits<{
  addCharacter: [character: Omit<Character, 'id'>]
  removeCharacter: [id: string]
  updateCharacter: [id: string, updates: Partial<Character>]
  addRelationship: [sourceId: string, relationship: Character['relationships'][number]]
  back: []
  next: []
}>()

</script>

<template>
  <div class="flex-1 flex flex-col overflow-hidden">
    <div class="flex-1 flex overflow-hidden">
      <div class="flex-1 flex flex-col overflow-hidden">
        <div class="flex items-center justify-between px-4 py-3 border-b shrink-0">
          <h2 class="text-lg font-semibold flex items-center gap-2">
            <Users class="h-5 w-5 text-primary" />
            角色库
          </h2>
          <div class="flex items-center gap-2">
            <Button
              variant="outline"
              size="sm"
              class="gap-2"
              @click="showCharacterGraph = !showCharacterGraph"
            >
              <TrendingUp class="h-4 w-4" />
              {{ showCharacterGraph ? '隐藏' : '显示' }}关系图
            </Button>
          </div>
        </div>

        <div class="flex-1 overflow-hidden p-4 flex gap-4">
          <div class="flex-1 min-w-0 overflow-auto">
            <div class="mb-3 rounded-lg border border-red-300 bg-red-50 px-3 py-2 text-sm font-semibold text-red-700 dark:border-red-900/60 dark:bg-red-950/20 dark:text-red-300">
              <div class="flex items-start gap-2">
                <AlertTriangle class="mt-0.5 h-4 w-4 shrink-0" />
                <span>角色库信息必须由用户手动补全：请逐一检查角色身份、人物小传、关系和动机弧线，再进入剧本写作。</span>
              </div>
            </div>
            <CharacterEditor
              :characters="characters"
              :selected-id="selectedCharacterId"
              :role-colors="roleColors"
              @add="emit('addCharacter', $event)"
              @remove="emit('removeCharacter', $event)"
              @update="(id, updates) => emit('updateCharacter', id, updates)"
              @add-relationship="(sourceId, relationship) => emit('addRelationship', sourceId, relationship)"
              @select="(id) => { selectedCharacterId = id }"
            />
          </div>

        </div>
      </div>

      <div
        v-if="showCharacterGraph"
        class="w-80 border-l bg-muted/20 flex flex-col shrink-0"
      >
        <div class="p-3 border-b">
          <h3 class="text-sm font-medium flex items-center gap-2">
            <TrendingUp class="h-4 w-4 text-primary" />
            实时关系图谱
          </h3>
        </div>
        <div class="flex-1 p-3">
          <CharacterGraph
            :characters="characters"
            :role-colors="roleColors"
            :script-content="sceneContent"
            mode="realtime"
            @select-character="(id: string) => { selectedCharacterId = id }"
          />
        </div>
        <div class="p-3 border-t">
          <div class="flex flex-wrap gap-2 text-xs">
            <span v-for="(color, role) in roleColors" :key="role" class="flex items-center gap-1">
              <span class="w-2.5 h-2.5 rounded-full" :style="{ background: color }" />
              {{ role === 'protagonist' ? '主角' : role === 'antagonist' ? '反派' : role === 'supporting' ? '配角' : '次要' }}
            </span>
          </div>
        </div>
      </div>
    </div>

    <div class="border-t bg-card px-6 py-3 flex justify-between shrink-0">
      <Button variant="ghost" @click="emit('back')">← 大纲编辑</Button>
      <Button class="gap-2 bg-gradient-to-r from-primary to-purple-600 hover:opacity-90" @click="emit('next')">
        <CheckCircle2 class="h-4 w-4" />
        角色完善 → 进入剧本写作
      </Button>
    </div>
  </div>
</template>
