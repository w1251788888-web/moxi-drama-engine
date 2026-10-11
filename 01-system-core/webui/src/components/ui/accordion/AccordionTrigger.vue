<script setup lang="ts">
import { inject, getCurrentInstance } from 'vue'

const accordion = inject<any>('accordion')
const instance = getCurrentInstance()

function handleClick() {
  const value = (instance?.parent?.props?.value as string) || ''
  accordion?.toggleItem(value)
}
</script>

<template>
  <button class="accordion-trigger" @click="handleClick">
    <slot />
    <span class="chevron">▼</span>
  </button>
</template>

<style scoped>
.accordion-trigger {
  width: 100%;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 16px;
  background: white;
  border: none;
  font-size: 14px;
  font-weight: 500;
  cursor: pointer;
  transition: background 0.2s;
}

.accordion-trigger:hover {
  background: #f9fafb;
}

.chevron {
  font-size: 12px;
  color: #6b7280;
  transition: transform 0.2s;
}
</style>
