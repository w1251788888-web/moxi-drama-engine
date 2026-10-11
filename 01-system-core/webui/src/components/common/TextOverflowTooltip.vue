<script setup lang="ts">
import { computed } from 'vue'
import type { HTMLAttributes } from 'vue'
import { cn } from '@/lib/utils'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'

const props = withDefaults(
  defineProps<{
    text?: string | null
    as?: string
    lines?: number
    side?: 'top' | 'right' | 'bottom' | 'left'
    class?: HTMLAttributes['class']
    fallback?: string
  }>(),
  {
    as: 'div',
    lines: 1,
    side: 'top',
    fallback: '-',
  },
)

const displayText = computed(() => {
  if (!props.text || !props.text.trim()) {
    return props.fallback
  }
  return props.text
})

const clampStyle = computed<Record<string, string> | undefined>(() => {
  if (props.lines <= 1) {
    return undefined
  }

  return {
    display: '-webkit-box',
    WebkitBoxOrient: 'vertical',
    WebkitLineClamp: String(props.lines),
    overflow: 'hidden',
  }
})

const textClass = computed(() =>
  cn(props.lines <= 1 ? 'truncate' : 'overflow-hidden break-words', props.class),
)
</script>

<template>
  <Tooltip>
    <TooltipTrigger as-child>
      <component :is="as" :class="textClass" :style="clampStyle" :title="displayText">
        {{ displayText }}
      </component>
    </TooltipTrigger>

    <TooltipContent :side="side" class="max-w-sm whitespace-pre-wrap break-words">
      {{ displayText }}
    </TooltipContent>
  </Tooltip>
</template>
