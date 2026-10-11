<script setup lang="ts">
import { computed } from 'vue'
import { BookOpen, Plus, Loader2, Save, Trash2 } from 'lucide-vue-next'
import { ScrollArea } from '@/components/ui/scroll-area'

type Episode = {
  episode_number: number
  title?: string
}

type Scene = {
  scene_number: number
  content?: string
}

const props = defineProps<{
  episodes: Episode[]
  scenes: Scene[]
  selectedEpisode: number
  selectedScene: number
  isCreatingEpisode: boolean
  isCreatingScene: boolean
  scenesLoading?: boolean
  totalEpisodes?: number
}>()

defineEmits<{
  loadEpisode: [episodeNumber: number]
  selectScene: [scene: Scene]
  createEpisode: []
  createEpisodesBatch: []
  createScene: []
  saveEpisode: [episodeNumber: number]
  deleteEpisode: [episodeNumber: number]
}>()

const isAtEpisodeLimit = computed(() => (
  props.totalEpisodes ? props.episodes.length >= props.totalEpisodes : false
))
</script>

<template>
  <div class="w-44 border-r bg-muted/20 flex flex-col shrink-0">
    <div class="p-3 border-b text-sm font-medium flex items-center gap-2">
      <BookOpen class="h-4 w-4" />分集
    </div>
    <ScrollArea class="flex-1">
      <div class="p-2 space-y-1">
        <div
          v-for="ep in episodes"
          :key="ep.episode_number"
          class="group rounded-lg p-2 cursor-pointer text-sm transition-colors"
          :class="selectedEpisode === ep.episode_number ? 'bg-primary/10 text-primary' : 'hover:bg-muted'"
          @click="$emit('loadEpisode', ep.episode_number)"
        >
          <div class="flex items-center gap-1">
            <span class="font-medium">第{{ ep.episode_number }}集</span>
            <Loader2
              v-if="scenesLoading && selectedEpisode === ep.episode_number"
              class="h-3 w-3 animate-spin opacity-60"
            />
            <span class="ml-auto flex items-center gap-0.5 opacity-0 transition-opacity group-hover:opacity-100 group-focus-within:opacity-100">
              <button
                v-if="selectedEpisode === ep.episode_number"
                class="rounded p-1 text-muted-foreground hover:bg-background hover:text-foreground"
                title="保存当前集"
                @click.stop="$emit('saveEpisode', ep.episode_number)"
              >
                <Save class="h-3.5 w-3.5" />
              </button>
              <button
                class="rounded p-1 text-muted-foreground hover:bg-destructive/10 hover:text-destructive"
                title="删除本集"
                @click.stop="$emit('deleteEpisode', ep.episode_number)"
              >
                <Trash2 class="h-3.5 w-3.5" />
              </button>
            </span>
          </div>
        </div>
        <button
          class="w-full flex items-center gap-1.5 px-2 py-1.5 text-xs rounded-lg border border-dashed border-primary/40 text-primary/70 hover:bg-primary/5 hover:border-primary/60 transition-all"
          :disabled="isCreatingEpisode || isAtEpisodeLimit"
          :title="isAtEpisodeLimit ? '已达到项目总集数上限' : undefined"
          @click="$emit('createEpisode')"
        >
          <Plus class="h-3 w-3 shrink-0" />
          <span>{{ isCreatingEpisode ? '创建中...' : '新建集' }}</span>
        </button>
        <button
          class="w-full flex items-center gap-1.5 px-2 py-1.5 text-xs rounded-lg border border-dashed border-emerald-400/50 text-emerald-700 hover:bg-emerald-50 hover:border-emerald-500 transition-all disabled:opacity-50"
          title="补齐到总集数"
          :disabled="isCreatingEpisode || isAtEpisodeLimit"
          @click="$emit('createEpisodesBatch')"
        >
          <Plus class="h-3 w-3 shrink-0" />
          <span>{{ isCreatingEpisode ? '创建中...' : '批量建集' }}</span>
        </button>
        <div v-if="episodes.length === 0" class="text-center py-2 text-xs text-muted-foreground">点击上方新建第1集</div>
      </div>
    </ScrollArea>
  </div>
</template>
