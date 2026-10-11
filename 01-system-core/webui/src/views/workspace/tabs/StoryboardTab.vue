<script setup lang="ts">
import StoryboardPanel from '@/components/workshop/StoryboardPanel.vue'

type OutlineEpisode = {
  ep: number
  title: string
}

defineProps<{
  projectId: string
  outlineEpisodes: OutlineEpisode[]
  copyExportLocked?: boolean
}>()

const storyboardEpisode = defineModel<number>('storyboardEpisode', { required: true })

defineEmits<{
  mounted: []
}>()
</script>

<template>
  <div class="flex-1 overflow-auto">
    <div class="max-w-5xl mx-auto px-6 py-6 space-y-4">
      <div class="flex items-center gap-2">
        <select v-model="storyboardEpisode" class="h-9 px-3 rounded-lg border bg-background text-sm">
          <option v-for="ep in outlineEpisodes" :key="ep.ep" :value="ep.ep">
            第{{ ep.ep }}集 {{ ep.title }}
          </option>
          <option v-if="!outlineEpisodes.length" :value="1">第1集</option>
        </select>
      </div>
      <StoryboardPanel
        :project-id="projectId"
        :session-id="projectId"
        :episode="storyboardEpisode"
        :copy-export-locked="copyExportLocked"
        @vue:mounted="$emit('mounted')"
      />
    </div>
  </div>
</template>
