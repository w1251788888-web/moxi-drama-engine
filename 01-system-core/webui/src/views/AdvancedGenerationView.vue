<script setup lang="ts">
import { onMounted, watch } from 'vue'
import { useRouter } from 'vue-router'
import { AlertCircle, RefreshCw } from 'lucide-vue-next'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import type { AdvancedGenerationProfile } from '@/api/client'
import { notifyApiError } from '@/api/http'
import { toast } from 'vue-sonner'
import AdvancedGenerationCapabilityOverview from '@/features/advanced-generation/components/AdvancedGenerationCapabilityOverview.vue'
import AdvancedGenerationProfileCard from '@/features/advanced-generation/components/AdvancedGenerationProfileCard.vue'
import { useAdvancedGenerationProfiles } from '@/features/advanced-generation/composables/useAdvancedGenerationProfiles'

const router = useRouter()

const {
  profiles,
  isLoading,
  loadError,
  activeProfiles,
  scaffoldProfiles,
  loadProfiles,
} = useAdvancedGenerationProfiles()

onMounted(loadProfiles)

watch(loadError, (message) => {
  if (message) {
    notifyApiError(toast.error, { message }, '读取失败')
  }
})

function createProject(profile: AdvancedGenerationProfile) {
  router.push({ path: '/projects', query: { newProfile: profile.id } })
}
</script>

<template>
  <div class="min-h-[calc(100vh-3.5rem)] bg-[#f7f6f1] text-[#1f2723]">
    <div class="mx-auto flex max-w-7xl flex-col gap-8 px-6 py-8">
      <section class="relative overflow-hidden border-y border-[#26312c]/15 bg-[#fdfcf7] px-6 py-7 shadow-[0_18px_60px_rgba(31,39,35,0.08)]">
        <div class="absolute inset-y-0 right-0 hidden w-1/2 opacity-70 md:block">
          <div class="h-full w-full bg-[linear-gradient(135deg,transparent_0%,transparent_42%,rgba(17,94,89,0.12)_42%,rgba(17,94,89,0.12)_48%,transparent_48%),linear-gradient(90deg,rgba(180,83,9,0.10),rgba(22,78,99,0.08))]" />
        </div>
        <div class="relative grid gap-6 lg:grid-cols-[1.3fr_0.7fr] lg:items-end">
          <div class="space-y-4">
            <div class="flex flex-wrap items-center gap-2">
              <Badge class="rounded-sm bg-[#1f4f46] px-2.5 py-1 text-[#fdfcf7] hover:bg-[#1f4f46]">
                科研生成链路
              </Badge>
              <Badge variant="outline" class="rounded-sm border-[#b45309]/35 bg-[#fff7ed] text-[#9a3412]">
                生成入口已接入
              </Badge>
            </div>
            <div>
              <h1 class="text-3xl font-semibold tracking-normal md:text-4xl">
                多形态创作框架
              </h1>
              <p class="mt-3 max-w-3xl text-sm leading-7 text-[#5d675f] md:text-base">
                短剧继续作为当前主流程运行；话剧、影视剧、长剧已接入项目创建和通用生成提示，后续会继续细化专属工作台。
              </p>
            </div>
          </div>
          <div class="grid grid-cols-3 gap-3 text-center">
            <div class="border border-[#26312c]/10 bg-white/70 px-3 py-4">
              <div class="text-2xl font-semibold">{{ profiles.length || 4 }}</div>
              <div class="mt-1 text-xs text-[#6d766f]">创作形态</div>
            </div>
            <div class="border border-[#26312c]/10 bg-white/70 px-3 py-4">
              <div class="text-2xl font-semibold">{{ activeProfiles.length }}</div>
              <div class="mt-1 text-xs text-[#6d766f]">已接入</div>
            </div>
            <div class="border border-[#26312c]/10 bg-white/70 px-3 py-4">
              <div class="text-2xl font-semibold">{{ scaffoldProfiles.length }}</div>
              <div class="mt-1 text-xs text-[#6d766f]">准备中</div>
            </div>
          </div>
        </div>
      </section>

      <div v-if="loadError" class="flex items-center justify-between gap-3 border border-amber-500/35 bg-amber-50 px-4 py-3 text-sm text-amber-800">
        <div class="flex items-center gap-2">
          <AlertCircle class="h-4 w-4" />
          <span>{{ loadError }}</span>
        </div>
        <Button size="sm" variant="outline" class="rounded-sm" @click="loadProfiles">
          <RefreshCw class="mr-2 h-4 w-4" />
          重试
        </Button>
      </div>

      <AdvancedGenerationCapabilityOverview />

      <div v-if="isLoading" class="grid gap-4 lg:grid-cols-2">
        <div v-for="i in 4" :key="i" class="h-64 animate-pulse border border-[#26312c]/10 bg-white/70" />
      </div>

      <div v-else class="grid gap-4 lg:grid-cols-2">
        <AdvancedGenerationProfileCard
          v-for="profile in profiles"
          :key="profile.id"
          :profile="profile"
          @create="createProject"
        />
      </div>
    </div>
  </div>
</template>
