<script setup lang="ts">
import { ref } from 'vue'
import { CheckCircle2 } from 'lucide-vue-next'
import { Input } from '@/components/ui/input'

type OutlineData = {
  audience_axis: '男频' | '女频' | '混合' | ''
  genre_main: string
  format_type: '真人短剧' | '漫剧' | 'AI真人'
}

const outlineData = defineModel<OutlineData>('outlineData', { required: true })
const customGenreInput = ref('')
const genrePresets = ['甜宠先婚后爱', '重生逆袭', '虐恋情深', '悬疑推理', '古装权谋']

function applyCustomGenre() {
  const value = customGenreInput.value.trim()
  if (!value) return
  outlineData.value.genre_main = value
}
</script>

<template>
  <div class="flex flex-wrap items-center gap-x-4 gap-y-2 px-3 py-2.5 bg-primary/5 border border-primary/20 rounded-xl">
    <div class="flex items-center gap-1.5">
      <span class="text-[11px] font-medium text-muted-foreground whitespace-nowrap">受众</span>
      <button v-for="ax in ['女频', '男频', '混合']" :key="ax"
        class="text-[11px] px-2 py-0.5 rounded border transition-all"
        :class="outlineData.audience_axis === ax
          ? 'bg-primary text-primary-foreground border-primary'
          : 'text-muted-foreground hover:border-primary/50 hover:text-foreground'"
        @click="outlineData.audience_axis = ax as OutlineData['audience_axis']">
        {{ ax }}
      </button>
    </div>
    <div class="w-px h-4 bg-border hidden sm:block" />
    <div class="flex items-center gap-1.5 flex-wrap">
      <span class="text-[11px] font-medium text-muted-foreground whitespace-nowrap">题材</span>
      <button v-for="g in genrePresets" :key="g"
        class="text-[11px] px-2 py-0.5 rounded border transition-all"
        :class="outlineData.genre_main === g
          ? 'bg-purple-500 text-white border-purple-500'
          : 'text-muted-foreground hover:border-purple-400/50 hover:text-foreground'"
        @click="outlineData.genre_main = g === outlineData.genre_main ? '' : g">
        {{ g }}
      </button>
      <div class="flex items-center gap-1.5 min-w-[13rem]">
        <Input
          v-model.trim="customGenreInput"
          class="h-7 text-[11px]"
          placeholder="自定义题材"
          @keyup.enter="applyCustomGenre"
        />
        <button
          class="text-[11px] px-2 py-1 rounded border border-purple-300 text-purple-700 hover:bg-purple-50 whitespace-nowrap"
          @click="applyCustomGenre"
        >
          确认题材
        </button>
      </div>
    </div>
    <div class="w-px h-4 bg-border hidden sm:block" />
    <div class="flex items-center gap-1.5">
      <span class="text-[11px] font-medium text-muted-foreground whitespace-nowrap">格式</span>
      <button v-for="f in ['真人短剧', '漫剧', 'AI真人']" :key="f"
        class="text-[11px] px-2 py-0.5 rounded border transition-all"
        :class="outlineData.format_type === f
          ? 'bg-emerald-500 text-white border-emerald-500'
          : 'text-muted-foreground hover:border-emerald-400/50 hover:text-foreground'"
        @click="outlineData.format_type = f as OutlineData['format_type']">
        {{ f }}
      </button>
    </div>
    <div v-if="outlineData.audience_axis || outlineData.genre_main" class="text-[11px] text-primary flex items-center gap-1">
      <CheckCircle2 class="h-3 w-3" />
      已激活专属规则
    </div>
  </div>
</template>
