<script setup lang="ts">
import { TrendingUp } from 'lucide-vue-next'
import CharacterGraph from '@/components/workshop/CharacterGraph.vue'

defineProps<{
  characters: any[]
  roleColors: Record<string, string>
  presentCharacterIds: string[]
  activeRelationKeys: string[]
  scriptContent: string
  position: { x: number; y: number }
}>()

const showFloatingGraph = defineModel<boolean>('showFloatingGraph', { required: true })

defineEmits<{
  startDrag: [event: MouseEvent]
  selectCharacter: [id: string]
}>()
</script>

<template>
  <Teleport to="body">
    <div v-if="showFloatingGraph"
      class="fixed z-50 rounded-xl border bg-background shadow-2xl flex flex-col overflow-hidden select-none"
      :style="{ left: position.x + 'px', top: position.y + 'px', width: '520px', height: '440px' }">
      <div class="flex items-center justify-between px-3 py-2 bg-muted/60 border-b cursor-move shrink-0"
        @mousedown.prevent="$emit('startDrag', $event)">
        <span class="text-xs font-semibold flex items-center gap-1.5 pointer-events-none">
          <TrendingUp class="h-3.5 w-3.5" />角色关系图谱
          <span class="text-[10px] text-muted-foreground font-normal ml-1">拖拽移动</span>
        </span>
        <button class="text-muted-foreground hover:text-foreground p-1 rounded transition-colors"
          @mousedown.stop @click="showFloatingGraph = false">✕</button>
      </div>
      <div class="flex-1 min-h-0">
        <CharacterGraph
          :characters="characters"
          :role-colors="roleColors"
          :present-character-ids="presentCharacterIds"
          :active-relation-keys="activeRelationKeys"
          :script-content="scriptContent"
          mode="realtime"
          @select-character="$emit('selectCharacter', $event)"
        />
      </div>
    </div>
  </Teleport>
</template>
