<script setup lang="ts">
import { inject, computed } from 'vue'

const props = defineProps<{
  value?: string
}>()

const accordion = inject<any>('accordion')
const isExpanded = computed(() =>
  accordion?.expandedItems?.value?.includes(props.value)
)
</script>

<template>
  <div v-show="isExpanded" class="accordion-content">
    <div class="content-inner">
      <slot />
    </div>
  </div>
</template>

<style scoped>
.accordion-content {
  overflow: hidden;
}

.content-inner {
  padding: 16px;
  border-top: 1px solid #e5e7eb;
}
</style>
