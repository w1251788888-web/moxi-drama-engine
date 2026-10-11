<script setup lang="ts">
import { inject } from 'vue'

const props = defineProps<{
  value: string
}>()

const accordion = inject<any>('accordion')
</script>

<template>
  <div class="accordion-item">
    <slot />
  </div>
</template>

<style scoped>
.accordion-item {
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  overflow: hidden;
  background: white;
}
</style>
