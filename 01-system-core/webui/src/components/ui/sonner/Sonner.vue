<script lang="ts" setup>
import type { ToasterProps } from "vue-sonner"
import { CircleCheckIcon, InfoIcon, Loader2Icon, OctagonXIcon, TriangleAlertIcon, XIcon } from "lucide-vue-next"
import { Toaster as Sonner } from "vue-sonner"
import { cn } from "@/lib/utils"

const props = defineProps<ToasterProps>()
</script>

<template>
  <Sonner :class="cn('toaster group', props.class)" :style="{
    '--normal-bg': 'var(--popover)',
    '--normal-text': 'var(--popover-foreground)',
    '--normal-border': 'var(--border)',
    '--border-radius': 'var(--radius)',
  }" v-bind="props">
    <template #success-icon>
      <CircleCheckIcon class="size-4" />
    </template>
    <template #info-icon>
      <InfoIcon class="size-4" />
    </template>
    <template #warning-icon>
      <TriangleAlertIcon class="size-4" />
    </template>
    <template #error-icon>
      <OctagonXIcon class="size-4" />
    </template>
    <template #loading-icon>
      <div>
        <Loader2Icon class="size-4 animate-spin" />
      </div>
    </template>
    <template #close-icon>
      <XIcon class="size-4" />
    </template>
  </Sonner>
</template>

<style>
.toaster[data-sonner-toaster] {
  z-index: 2147483647 !important;
}

.toaster [data-sonner-toast] {
  width: min(420px, calc(100vw - 32px));
  border-radius: 14px !important;
  border: 1px solid hsl(var(--border) / 0.9) !important;
  box-shadow: 0 18px 50px hsl(var(--foreground) / 0.18) !important;
  backdrop-filter: blur(14px);
}

.toaster [data-title] {
  font-size: 14px;
  font-weight: 700;
  line-height: 1.35;
}

.toaster [data-description] {
  font-size: 13px;
  line-height: 1.45;
}

@media (max-width: 640px) {
  .toaster [data-sonner-toast] {
    width: calc(100vw - 28px);
  }
}
</style>
