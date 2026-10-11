<script setup lang="ts">
const props = defineProps<{
  class?: string
}>()
</script>

<template>
  <div :class="['scroll-area', props.class]">
    <div class="scroll-viewport">
      <slot />
    </div>
  </div>
</template>

<style scoped>
.scroll-area {
  position: relative;
  overflow: hidden;
  height: 100%;
}

.scroll-viewport {
  height: 100%;
  overflow-y: auto;
  overflow-x: hidden;
}

/* 自定义滚动条 */
.scroll-viewport::-webkit-scrollbar {
  width: 6px;
}

.scroll-viewport::-webkit-scrollbar-track {
  background: transparent;
}

.scroll-viewport::-webkit-scrollbar-thumb {
  background: #d1d5db;
  border-radius: 3px;
}

.scroll-viewport::-webkit-scrollbar-thumb:hover {
  background: #9ca3af;
}
</style>
