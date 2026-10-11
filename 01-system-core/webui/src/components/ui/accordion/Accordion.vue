<script setup lang="ts">
import { ref, provide } from 'vue'

const props = defineProps<{
  modelValue?: string[]
  type?: 'single' | 'multiple'
  collapsible?: boolean
}>()

const emit = defineEmits<{
  (e: 'update:modelValue', value: string[]): void
}>()

const expandedItems = ref<string[]>(props.modelValue || [])

const toggleItem = (item: string) => {
  if (props.type === 'single') {
    expandedItems.value = expandedItems.value.includes(item) && props.collapsible
      ? []
      : [item]
  } else {
    const index = expandedItems.value.indexOf(item)
    if (index > -1 && props.collapsible) {
      expandedItems.value.splice(index, 1)
    } else if (index === -1) {
      expandedItems.value.push(item)
    }
  }
  emit('update:modelValue', [...expandedItems.value])
}

provide('accordion', {
  expandedItems,
  toggleItem
})
</script>

<template>
  <div class="accordion">
    <slot />
  </div>
</template>

<style scoped>
.accordion {
  display: flex;
  flex-direction: column;
  gap: 1px;
}
</style>
