<script setup lang="ts">
import type { Component } from 'vue'
import {
  BookOpen,
  CheckCircle2,
  Clapperboard,
  FileStack,
  Film,
  PanelsTopLeft,
  ScrollText,
  Theater,
} from 'lucide-vue-next'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import type { AdvancedGenerationProfile } from '@/api/client'
import { aliasesText, footerText, statusLabel } from '../presentation'

defineProps<{
  profile: AdvancedGenerationProfile
}>()

defineEmits<{
  create: [profile: AdvancedGenerationProfile]
}>()

const iconMap: Record<string, Component> = {
  short_drama: Film,
  stage_play: Theater,
  film: Clapperboard,
  long_series: FileStack,
}
</script>

<template>
  <article
    class="group border bg-[#fdfcf7] transition duration-200"
    :class="profile.status === 'active'
      ? 'border-[#1f4f46]/35 shadow-[0_16px_40px_rgba(31,79,70,0.10)]'
      : 'border-[#26312c]/12 opacity-85'"
  >
    <div class="grid min-h-full grid-rows-[auto_1fr_auto]">
      <header class="flex items-start justify-between gap-4 border-b border-[#26312c]/10 p-5">
        <div class="flex items-center gap-4">
          <div
            class="flex h-12 w-12 items-center justify-center border"
            :class="profile.status === 'active'
              ? 'border-[#1f4f46]/25 bg-[#e8f2ee] text-[#1f4f46]'
              : 'border-[#9ca3af]/25 bg-[#f2f0e8] text-[#5d675f]'"
          >
            <component :is="iconMap[profile.id] || PanelsTopLeft" class="h-6 w-6" />
          </div>
          <div>
            <h2 class="text-xl font-semibold">{{ profile.label }}</h2>
            <p class="mt-1 text-xs text-[#6d766f]">
              {{ aliasesText(profile) }}
            </p>
          </div>
        </div>
        <Badge
          class="rounded-sm"
          :class="profile.status === 'active'
            ? 'bg-[#1f4f46] text-[#fdfcf7] hover:bg-[#1f4f46]'
            : 'bg-[#e7e1d4] text-[#6b4e16] hover:bg-[#e7e1d4]'"
        >
          {{ statusLabel(profile) }}
        </Badge>
      </header>

      <div class="grid gap-5 p-5 md:grid-cols-[1fr_0.82fr]">
        <section>
          <div class="mb-3 flex items-center gap-2 text-sm font-medium">
            <ScrollText class="h-4 w-4 text-[#1f4f46]" />
            工作流骨架
          </div>
          <div class="space-y-2">
            <div
              v-for="(step, index) in profile.workflow_steps"
              :key="step.id"
              class="grid grid-cols-[2rem_1fr] gap-3 border-l border-[#26312c]/15 py-1.5 pl-3"
            >
              <div class="flex h-6 w-6 items-center justify-center bg-[#1f2723] text-[11px] text-[#fdfcf7]">
                {{ index + 1 }}
              </div>
              <div>
                <div class="text-sm font-medium">{{ step.label }}</div>
                <div class="mt-0.5 text-xs leading-5 text-[#6d766f]">{{ step.purpose }}</div>
              </div>
            </div>
          </div>
        </section>

        <section class="space-y-5">
          <div>
            <div class="mb-3 flex items-center gap-2 text-sm font-medium">
              <BookOpen class="h-4 w-4 text-[#b45309]" />
              产物类型
            </div>
            <div class="space-y-2">
              <div
                v-for="artifact in profile.artifacts"
                :key="artifact.id"
                class="border border-[#26312c]/10 bg-white/60 px-3 py-2"
              >
                <div class="text-sm font-medium">{{ artifact.label }}</div>
                <div class="mt-1 text-xs leading-5 text-[#6d766f]">{{ artifact.description }}</div>
              </div>
            </div>
          </div>

          <div>
            <div class="mb-3 flex items-center gap-2 text-sm font-medium">
              <CheckCircle2 class="h-4 w-4 text-[#1f4f46]" />
              规则层级
            </div>
            <div class="flex flex-wrap gap-2">
              <span
                v-for="scope in profile.rule_scopes"
                :key="scope"
                class="border border-[#26312c]/12 bg-[#f2f0e8] px-2 py-1 text-xs text-[#4f5a53]"
              >
                {{ scope }}
              </span>
            </div>
          </div>
        </section>
      </div>

      <footer
        class="flex items-center justify-between gap-3 border-t border-[#26312c]/10 px-5 py-3 text-sm"
        :class="profile.status === 'active' ? 'text-[#1f4f46]' : 'text-[#8a5a13]'"
      >
        <span>{{ footerText(profile) }}</span>
        <Button size="sm" class="rounded-sm bg-[#1f4f46] text-[#fdfcf7] hover:bg-[#173d36]" @click="$emit('create', profile)">
          创建这种项目
        </Button>
      </footer>
    </div>
  </article>
</template>
