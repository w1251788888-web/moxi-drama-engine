<script setup lang="ts">
import { ref, watch, computed } from 'vue'
import { Sparkles, RefreshCw, Copy, FileText } from 'lucide-vue-next'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs'
import { toast } from 'vue-sonner'
import {
  aiHealthApi,
  storyboardApi,
  type Shot, type PromptPack,
} from '@/api/client'
import { formatUserFacingErrorMessage } from '@/api/http'

interface Props {
  projectId: string
  sessionId?: string
  episode: number
  copyExportLocked?: boolean
}

const props = defineProps<Props>()

const PLATFORMS = [
  { id: 'jimeng', label: '即梦/Seedance' },
  { id: 'kling', label: '可灵' },
  { id: 'hailuo', label: '海螺' },
  { id: 'sora', label: 'Sora' },
  { id: 'generic', label: '通用版' },
] as const

const BEAT_LABELS: Record<string, string> = {
  establish: '建立', setup: '铺垫', conflict: '冲突',
  reaction: '反应', reveal: '揭示', transition: '转场', payoff: '收束',
}
const SIZE_LABELS: Record<string, string> = {
  ELS: '大远景', LS: '全景', MS: '中景',
  MCU: '中近景', CU: '特写', ECU: '大特写',
}
const MOVE_LABELS: Record<string, string> = {
  static: '固定', push_in: '推进', pull_out: '拉出',
  pan_left: '左摇', pan_right: '右摇', tilt_up: '上摇', tilt_down: '下摇',
  tracking: '跟拍', handheld: '手持',
}

const eligibility = ref<{
  eligible: boolean
  reason: string
  detail: string
  missing_locked_characters?: string[]
} | null>(null)

// LLM 连通性：进入面板就探活，连不通直接禁按钮 + 顶部红字提示，
// 避免用户点了之后死等几十秒才报 timeout。
const aiHealth = ref<{ ok: boolean; detail: string; latency_ms: number } | null>(null)
const aiHealthChecking = ref(false)

const shots = ref<Shot[]>([])
const promptsByShot = ref<Record<string, PromptPack[]>>({})
const loading = ref(false)
const planning = ref(false)
const compiling = ref(false)
const activePlatform = ref<string>('jimeng')
const targetCount = ref(14)

const sessionId = computed(() => props.sessionId || props.projectId)
const llmUnavailable = computed(() => Boolean(aiHealth.value && !aiHealth.value.ok))

async function checkAiHealth() {
  aiHealthChecking.value = true
  try {
    const { data } = await aiHealthApi.check()
    aiHealth.value = data
  } catch (e: any) {
    aiHealth.value = {
      ok: false,
      detail: formatUserFacingErrorMessage(e, 'LLM 连通检查失败'),
      latency_ms: 0,
    }
  } finally {
    aiHealthChecking.value = false
  }
}

async function loadEligibility() {
  try {
    const { data } = await storyboardApi.eligibility({
      session_id: sessionId.value,
      project_id: props.projectId,
      episode: props.episode,
    })
    eligibility.value = data
  } catch (e: any) {
    eligibility.value = { eligible: false, reason: 'error', detail: formatUserFacingErrorMessage(e, '检查生成条件失败') }
  }
}

async function loadShots() {
  loading.value = true
  try {
    const { data } = await storyboardApi.list(props.projectId, props.episode)
    shots.value = data.items || []
    promptsByShot.value = {}
    for (const s of shots.value) {
      try {
        const { data: pr } = await storyboardApi.prompts(s.id)
        promptsByShot.value[s.id] = (pr.items || []).map(it => ({
          platform: it.platform,
          prompt_text: it.prompt_text,
          negative_prompt: it.negative_prompt,
          params: it.params,
        }))
      } catch {}
    }
  } finally {
    loading.value = false
  }
}

async function refresh() {
  // 顺序：先探活 LLM，再查分镜资格，再拉已有镜头。
  // LLM 没连通的话用户根本走不到生成步骤，这里就该把状态露出来。
  await checkAiHealth()
  await loadEligibility()
  await loadShots()
}

async function generate() {
  if (!aiHealth.value?.ok) {
    toast.error('LLM 未联通，请联系管理员')
    return
  }
  if (!eligibility.value?.eligible) {
    toast.error(eligibility.value?.detail || '不满足生成条件')
    return
  }
  planning.value = true
  try {
    const { data } = await storyboardApi.plan({
      project_id: props.projectId,
      session_id: sessionId.value,
      episode: props.episode,
      target_shot_count: targetCount.value,
      enable_multi_candidate: true,
    })
    if (data.ok) {
      shots.value = data.shots || []
      toast.success(data.msg || `已生成 ${data.shots?.length || 0} 个镜头`)
      await batchCompile()
    } else {
      toast.error('生成失败')
    }
  } catch (e: any) {
    toast.error(formatUserFacingErrorMessage(e, '分镜生成失败'))
  } finally {
    planning.value = false
  }
}

async function batchCompile() {
  compiling.value = true
  try {
    const { data } = await storyboardApi.compileBatch({
      project_id: props.projectId,
      episode: props.episode,
      platforms: PLATFORMS.map(p => p.id) as any,
    })
    for (const item of data.items || []) {
      if (item.packs) {
        promptsByShot.value[item.shot_id] = item.packs
      }
    }
    toast.success('五平台提示词编译完成')
  } catch (e: any) {
    toast.error('批量编译失败')
  } finally {
    compiling.value = false
  }
}

async function recompileShot(shot: Shot) {
  try {
    const { data } = await storyboardApi.compile({
      shot_id: shot.id,
      platforms: PLATFORMS.map(p => p.id) as any,
    })
    if (data.ok) {
      promptsByShot.value[shot.id] = data.packs
      shot.is_stale = false
      toast.success('已重新编译')
    }
  } catch (e: any) {
    toast.error('编译失败')
  }
}

async function regenerateShot(shot: Shot) {
  try {
    const { data } = await storyboardApi.regenerate({ shot_id: shot.id })
    if (data.ok) {
      const idx = shots.value.findIndex(s => s.id === shot.id)
      if (idx >= 0) shots.value[idx] = data.shot
      await recompileShot(data.shot)
    }
  } catch {
    toast.error('重新生成失败')
  }
}

async function pickCandidate(shot: Shot, idx: number) {
  try {
    const { data } = await storyboardApi.regenerate({ shot_id: shot.id, pick_candidate_idx: idx })
    if (data.ok) {
      const i = shots.value.findIndex(s => s.id === shot.id)
      if (i >= 0) shots.value[i] = data.shot
      await recompileShot(data.shot)
    }
  } catch {}
}

function getPack(shot: Shot, platform: string): PromptPack | null {
  return (promptsByShot.value[shot.id] || []).find(p => p.platform === platform) || null
}

async function copyPrompt(text: string) {
  if (props.copyExportLocked) {
    toast.warning('当前密钥未开启复制导出权限，请联系管理员开启。')
    return
  }
  try {
    await navigator.clipboard.writeText(text)
    toast.success('已复制提示词')
  } catch {
    toast.error('复制失败')
  }
}

async function copyAllForPlatform() {
  const lines: string[] = []
  for (const s of shots.value) {
    const p = getPack(s, activePlatform.value)
    if (p) {
      lines.push(`# 镜${s.shot_order} (${BEAT_LABELS[s.spec.beat_role] || s.spec.beat_role}, ${s.spec.duration_sec}s)`)
      lines.push(p.prompt_text)
      if (p.negative_prompt) lines.push(`负面：${p.negative_prompt}`)
      lines.push('')
    }
  }
  await copyPrompt(lines.join('\n'))
}

watch(() => [props.projectId, props.episode], () => refresh(), { immediate: true })
</script>

<template>
  <div class="space-y-4">
    <!-- 顶部状态条 -->
    <div class="flex items-center justify-between gap-2 flex-wrap">
      <div class="flex items-center gap-2">
        <h2 class="font-semibold text-lg">分镜提示词 · 第 {{ episode }} 集</h2>
        <template v-if="!llmUnavailable">
          <Badge v-if="eligibility?.eligible" class="bg-emerald-500 text-white">可生成</Badge>
          <Badge v-else variant="destructive">{{ eligibility?.reason || '加载中' }}</Badge>
        </template>
      </div>
      <div class="flex items-center gap-2">
        <label class="text-xs text-muted-foreground">目标镜数</label>
        <input v-model.number="targetCount" type="number" min="4" max="40"
               class="w-16 h-8 px-2 rounded border bg-background text-sm" />
        <Button size="sm" variant="outline" :disabled="planning" @click="refresh">
          <RefreshCw class="h-3.5 w-3.5 mr-1" /> 刷新
        </Button>
        <Button size="sm" :disabled="planning || !eligibility?.eligible || !aiHealth?.ok" @click="generate">
          <Sparkles class="h-3.5 w-3.5 mr-1" />
          {{ planning ? '生成中...' : '生成分镜提示词' }}
        </Button>
      </div>
    </div>
    <!-- 一句话说明：本面板只产出文字提示词，外部 AI 视频平台才出图/视频 -->
    <div class="text-xs text-muted-foreground -mt-2">
      为即梦 / 可灵 / 海螺 / Sora 等平台生成分镜文字 + 提示词。<strong>本系统不生成图像或视频</strong>，只输出可复制的文本，请粘贴到对应平台。
    </div>

    <!-- LLM 连通失败时只展示一句统一提示 -->
    <div v-if="llmUnavailable" class="text-sm text-muted-foreground">
      LLM 未联通，请联系管理员
    </div>
    <div v-else-if="aiHealth && aiHealth.ok"
         class="text-xs text-emerald-700 dark:text-emerald-400 -mt-1">
      ✓ LLM 已连通（{{ aiHealth.detail }}，{{ aiHealth.latency_ms }}ms）
    </div>

    <!-- 平台 Tab + 一键复制 -->
    <Tabs v-if="shots.length > 0" v-model="activePlatform">
      <div class="flex items-center justify-between gap-2">
        <TabsList>
          <TabsTrigger v-for="p in PLATFORMS" :key="p.id" :value="p.id">
            {{ p.label }}
          </TabsTrigger>
        </TabsList>
        <div class="flex items-center gap-2">
          <Button size="sm" variant="outline" :disabled="compiling" @click="batchCompile">
            <RefreshCw class="h-3.5 w-3.5 mr-1" /> 重新编译
          </Button>
          <Button size="sm" variant="outline" :disabled="copyExportLocked" @click="copyAllForPlatform">
            <Copy class="h-3.5 w-3.5 mr-1" /> 复制本集所有
          </Button>
        </div>
      </div>

      <TabsContent v-for="p in PLATFORMS" :key="p.id" :value="p.id">
        <div class="space-y-3">
          <div v-for="shot in shots" :key="shot.id"
               class="rounded-lg border bg-card p-4"
               :class="shot.is_stale ? 'border-amber-400 bg-amber-50/30 dark:bg-amber-950/20' : ''">
            <!-- 镜头头部 -->
            <div class="flex items-start justify-between gap-2 mb-2 flex-wrap">
              <div class="flex items-center gap-2 flex-wrap">
                <span class="font-mono font-bold text-sm">
                  镜 {{ String(shot.shot_order).padStart(2, '0') }}
                </span>
                <span class="text-xs px-2 py-0.5 rounded bg-primary/10 text-primary">
                  {{ BEAT_LABELS[shot.spec.beat_role] || shot.spec.beat_role }}
                </span>
                <span class="text-xs text-muted-foreground">{{ shot.spec.duration_sec }}s</span>
                <span class="text-xs text-muted-foreground">
                  {{ SIZE_LABELS[shot.spec.camera.shot_size] || shot.spec.camera.shot_size }}
                  · {{ MOVE_LABELS[shot.spec.camera.movement] || shot.spec.camera.movement }}
                </span>
                <span v-if="shot.is_stale"
                      class="text-xs px-1.5 py-0.5 rounded bg-amber-500/20 text-amber-700 dark:text-amber-400">
                  待重新编译
                </span>
                <span v-if="shot.candidates?.length"
                      class="text-xs text-muted-foreground">候选 {{ shot.candidates.length }}</span>
              </div>
              <div class="flex items-center gap-1">
                <button class="text-xs px-2 py-1 rounded hover:bg-muted"
                        @click="regenerateShot(shot)">
                  重新生成
                </button>
                <button v-if="shot.is_stale"
                        class="text-xs px-2 py-1 rounded hover:bg-muted"
                        @click="recompileShot(shot)">
                  编译
                </button>
              </div>
            </div>

            <!-- 镜头内容 -->
            <div class="text-sm space-y-1 mb-3">
              <div v-if="shot.spec.shot_delta?.framing" class="text-muted-foreground">
                <span class="text-xs">画面：</span>{{ shot.spec.shot_delta.framing }}
              </div>
              <div v-if="shot.spec.dialogue" class="text-foreground/90">
                <span class="text-xs text-muted-foreground">台词：</span>"{{ shot.spec.dialogue }}"
              </div>
              <div v-if="shot.spec.shot_delta?.mood" class="text-xs text-muted-foreground">
                情绪：{{ shot.spec.shot_delta.mood }}
              </div>
            </div>

            <!-- 多候选 -->
            <div v-if="shot.candidates?.length" class="flex items-center gap-2 mb-2">
              <span class="text-xs text-muted-foreground">候选：</span>
              <button v-for="(c, i) in shot.candidates" :key="i"
                      class="text-xs px-2 py-0.5 rounded border hover:bg-muted"
                      @click="pickCandidate(shot, i)">
                {{ i + 1 }}
              </button>
            </div>

            <!-- 当前平台提示词 -->
            <div v-if="getPack(shot, p.id)"
                 class="rounded-md bg-muted/50 p-3 text-sm space-y-2">
              <div class="whitespace-pre-wrap">{{ getPack(shot, p.id)!.prompt_text }}</div>
              <div v-if="getPack(shot, p.id)!.negative_prompt"
                   class="text-xs text-muted-foreground">
                负面词：{{ getPack(shot, p.id)!.negative_prompt }}
              </div>
              <div class="flex items-center justify-between gap-2 pt-2 border-t border-border/50">
                <div class="text-xs text-muted-foreground truncate">
                  参数：{{ JSON.stringify(getPack(shot, p.id)!.params) }}
                </div>
                <div class="flex items-center gap-1">
                  <button class="text-xs px-2 py-1 rounded hover:bg-muted"
                          :disabled="copyExportLocked"
                          @click="copyPrompt(getPack(shot, p.id)!.prompt_text)">
                    复制
                  </button>
                </div>
              </div>
            </div>
            <div v-else class="text-xs text-muted-foreground italic">
              本平台尚未编译；点上方"重新编译"
            </div>
          </div>
        </div>
      </TabsContent>
    </Tabs>

    <!-- 空状态 -->
    <div v-else-if="!loading" class="text-center text-muted-foreground py-12">
      <FileText class="h-10 w-10 mx-auto mb-2 opacity-40" />
      <div class="text-sm">尚无分镜，点上方"生成分镜提示词"开始</div>
    </div>
  </div>
</template>
