<script setup lang="ts">
import { nextTick, onMounted, ref, watch } from 'vue'

const props = defineProps<{
  modelValue?: string
  placeholder?: string
  rows?: number
  disabled?: boolean
  autoResize?: boolean
}>()

const emit = defineEmits<{
  (e: 'update:modelValue', value: string): void
  (e: 'blur'): void
  (e: 'change', value: string): void
}>()

const localValue = ref(props.modelValue || '')
const textareaRef = ref<HTMLTextAreaElement | null>(null)

async function resizeToContent() {
  if (!props.autoResize) return
  await nextTick()
  if (!textareaRef.value) return
  textareaRef.value.style.height = 'auto'
  textareaRef.value.style.height = `${textareaRef.value.scrollHeight}px`
  textareaRef.value.style.overflowY = "hidden"
}

watch(() => props.modelValue, (newVal) => {
  localValue.value = newVal || ''
  resizeToContent()
})

watch(localValue, (newVal) => {
  emit('update:modelValue', newVal)
  resizeToContent()
})

watch(() => props.autoResize, () => {
  resizeToContent()
})

onMounted(() => {
  resizeToContent()
})

const handleBlur = () => {
  emit('blur')
  emit('change', localValue.value)
}
</script>

<template>
  <textarea
    ref="textareaRef"
    v-model="localValue"
    :placeholder="placeholder"
    :rows="rows || 3"
    :disabled="disabled"
    class="textarea"
    @blur="handleBlur"
  />
</template>

<style scoped>
.textarea {
  width: 100%;
  min-height: 80px;
  padding: 10px 12px;
  font-size: 14px;
  line-height: 1.6;
  color: #374151;
  background: white;
  border: 1px solid #d1d5db;
  border-radius: 6px;
  resize: vertical;
  transition: all 0.2s;
  font-family: inherit;
}

.textarea:focus {
  outline: none;
  border-color: #3b82f6;
  box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.1);
}

.textarea:disabled {
  background: #f3f4f6;
  cursor: not-allowed;
}

.textarea::placeholder {
  color: #9ca3af;
}
</style>
