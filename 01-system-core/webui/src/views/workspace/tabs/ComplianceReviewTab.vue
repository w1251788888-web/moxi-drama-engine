<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { AlertTriangle, CheckCircle2, Circle, RefreshCw, ShieldAlert, Wand2 } from 'lucide-vue-next'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { complianceApi, projectsV2Api, type ComplianceEpisode, type ComplianceFinding, type SceneV2 } from '@/api/client'
import { notifyApiError } from '@/api/http'
import { toast } from 'vue-sonner'

const props = defineProps<{
  projectId: string
}>()

const episodes = ref<ComplianceEpisode[]>([])
const findings = ref<ComplianceFinding[]>([])
const scenes = ref<SceneV2[]>([])
const selectedEpisode = ref<number>(1)
const isLoading = ref(false)
const isScanning = ref(false)
const patchPreview = ref<Record<string, string>>({})

const selectedEpisodeMeta = computed(() =>
  episodes.value.find(item => item.episode_number === selectedEpisode.value),
)

const hasEpisodes = computed(() => episodes.value.length > 0)

const selectedFindings = computed(() =>
  findings.value.filter(item => item.episode_number === selectedEpisode.value && item.status !== 'stale'),
)

const rawScriptText = computed(() =>
  scenes.value
    .map(scene => String(scene.content || '').trim())
    .filter(Boolean)
    .join('\n\n'),
)

const selectedEpisodeHasScriptBody = computed(() => Boolean(rawScriptText.value.trim()))

const hasRedline = computed(() =>
  findings.value.some(item => item.severity === 'redline' && item.status === 'open'),
)

type ScriptSegment = {
  key: string
  text: string
  severity: string
}

function severityLabel(severity: string) {
  if (severity === 'redline') return '不可通过'
  if (severity === 'high_risk') return '高风险'
  if (severity === 'warning') return '提示'
  return severity
}

function severityClass(severity: string) {
  if (severity === 'redline') return 'border-red-500/40 bg-red-500/10 text-red-700 dark:text-red-300'
  if (severity === 'high_risk') return 'border-orange-500/40 bg-orange-500/10 text-orange-700 dark:text-orange-300'
  if (severity === 'warning') return 'border-blue-500/40 bg-blue-500/10 text-blue-700 dark:text-blue-300'
  return 'border-emerald-500/40 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300'
}

function markClass(severity: string) {
  if (severity === 'redline') return 'compliance-mark-red'
  if (severity === 'high_risk') return 'compliance-mark-orange'
  if (severity === 'warning') return 'compliance-mark-blue'
  return ''
}

function statusLabel(status: string, verdict = '') {
  if (status === 'stale') return '已过期需重审'
  if (verdict === 'reject') return '不可通过'
  if (verdict === 'warning') return '需复核'
  if (verdict === 'pass') return '已通过'
  return '待审核'
}

const scriptSegments = computed<ScriptSegment[]>(() => {
  const text = rawScriptText.value
  if (!text) return []
  const rows = selectedFindings.value
    .filter(item => item.status === 'open' && item.start_offset >= 0 && item.end_offset > item.start_offset)
    .sort((a, b) => a.start_offset - b.start_offset)
  let cursor = 0
  const segments: ScriptSegment[] = []
  for (const finding of rows) {
    if (finding.start_offset < cursor) continue
    const plain = text.slice(cursor, finding.start_offset)
    if (plain) segments.push({ key: `plain-${cursor}`, text: plain, severity: '' })
    segments.push({
      key: finding.id,
      text: text.slice(finding.start_offset, finding.end_offset),
      severity: finding.severity,
    })
    cursor = finding.end_offset
  }
  const tail = text.slice(cursor)
  if (tail) segments.push({ key: `plain-${cursor}`, text: tail, severity: '' })
  return segments
})

async function loadEpisodes() {
  const { data } = await complianceApi.listEpisodes(props.projectId)
  episodes.value = data.items
  if (!episodes.value.some(item => item.episode_number === selectedEpisode.value)) {
    selectedEpisode.value = episodes.value[0]?.episode_number || 1
  }
}

async function loadEpisodeBody() {
  try {
    const { data } = await projectsV2Api.listScenes(props.projectId, selectedEpisode.value)
    scenes.value = data
  } catch {
    scenes.value = []
  }
}

async function loadFindings() {
  const { data } = await complianceApi.listFindings(props.projectId, selectedEpisode.value)
  findings.value = data.items
}

async function reloadAll() {
  isLoading.value = true
  try {
    await loadEpisodes()
    await Promise.all([loadEpisodeBody(), loadFindings()])
  } catch (e) {
    notifyApiError(toast.error, e, '加载合规审核失败')
  } finally {
    isLoading.value = false
  }
}

async function scanSelectedEpisode() {
  if (!hasEpisodes.value) {
    toast.error('请先创建或生成分集内容')
    return
  }
  if (!selectedEpisodeHasScriptBody.value) {
    toast.error('本集暂无正文，不能审核通过。请先回到剧本写作生成或保存正文。')
    return
  }
  isScanning.value = true
  try {
    await complianceApi.scanEpisode(props.projectId, selectedEpisode.value)
    toast.success(`第${selectedEpisode.value}集扫描完成`)
    await reloadAll()
  } catch (e) {
    notifyApiError(toast.error, e, '合规扫描失败')
  } finally {
    isScanning.value = false
  }
}

async function decide(finding: ComplianceFinding, decision: string) {
  try {
    await complianceApi.decideFinding(props.projectId, finding.id, { decision })
    toast.success('人工审核结论已记录')
    await loadFindings()
    await loadEpisodes()
  } catch (e) {
    notifyApiError(toast.error, e, '处理合规问题失败')
  }
}

async function createPatch(finding: ComplianceFinding) {
  try {
    const { data } = await complianceApi.createPatch(props.projectId, finding.id)
    patchPreview.value[finding.id] = data.after_text
    toast.success('AI 修改建议已生成')
  } catch (e) {
    notifyApiError(toast.error, e, '生成修改建议失败')
  }
}

watch(selectedEpisode, async () => {
  await Promise.all([loadEpisodeBody(), loadFindings()])
})

onMounted(reloadAll)
</script>

<template>
  <section class="h-full min-h-[680px] bg-background">
    <div class="grid h-full grid-cols-[220px_minmax(0,1fr)_340px] gap-4">
      <aside class="rounded-lg border bg-card p-3">
        <div class="mb-3 flex items-center justify-between">
          <div>
            <h2 class="text-sm font-semibold">逐集审核</h2>
            <p class="text-xs text-muted-foreground">人工最终确认</p>
          </div>
          <Button size="icon" variant="ghost" class="h-8 w-8" :disabled="isLoading" @click="reloadAll">
            <RefreshCw class="h-4 w-4" />
          </Button>
        </div>
        <div class="space-y-2">
          <div v-if="!hasEpisodes" class="rounded-lg border border-dashed p-4 text-xs leading-5 text-muted-foreground">
            暂无分集。请先在剧本写作中创建或生成分集，再回来逐集审核。
          </div>
          <button
            v-for="episode in episodes"
            :key="episode.episode_number"
            class="w-full rounded-lg border px-3 py-2 text-left transition-colors"
            :class="selectedEpisode === episode.episode_number ? 'border-primary bg-primary/10' : 'hover:bg-muted'"
            @click="selectedEpisode = episode.episode_number"
          >
            <div class="flex items-center justify-between gap-2">
              <span class="text-sm font-medium">第{{ episode.episode_number }}集</span>
              <Badge variant="outline" class="text-[11px]">{{ episode.open_findings }}</Badge>
            </div>
            <div class="mt-1 flex items-center gap-1.5 text-xs text-muted-foreground">
              <ShieldAlert v-if="episode.verdict === 'reject'" class="h-3.5 w-3.5 text-red-500" />
              <AlertTriangle v-else-if="episode.verdict === 'warning' || episode.status === 'stale'" class="h-3.5 w-3.5 text-orange-500" />
              <CheckCircle2 v-else-if="episode.verdict === 'pass'" class="h-3.5 w-3.5 text-emerald-500" />
              <Circle v-else class="h-3.5 w-3.5" />
              {{ statusLabel(episode.status, episode.verdict) }}
            </div>
          </button>
        </div>
      </aside>

      <main class="rounded-lg border bg-card">
        <div class="flex items-center justify-between border-b px-4 py-3">
          <div>
            <h2 class="font-semibold">{{ hasEpisodes ? `第${selectedEpisode}集剧本标注` : '暂无可审核分集' }}</h2>
            <p class="text-xs text-muted-foreground">{{ hasEpisodes ? (selectedEpisodeMeta?.title || '只读审查视图') : '等待剧本写作产出后进入人工审核' }}</p>
          </div>
          <div class="flex items-center gap-2">
            <Badge v-if="hasRedline" class="bg-red-500 text-white">正式导出受限</Badge>
            <Button size="sm" class="gap-1.5" :disabled="isScanning || !hasEpisodes || !selectedEpisodeHasScriptBody" @click="scanSelectedEpisode">
              <ShieldAlert class="h-4 w-4" />
              {{ isScanning ? '扫描中...' : '扫描本集' }}
            </Button>
          </div>
        </div>
        <article class="h-[620px] overflow-auto whitespace-pre-wrap px-6 py-5 text-sm leading-7">
          <div v-if="!hasEpisodes" class="flex h-full items-center justify-center text-center text-sm text-muted-foreground">
            暂无分集内容。先完成大纲或剧本写作后，这里会按集展示红色、橙色和蓝色标注。
          </div>
          <div v-else-if="!selectedEpisodeHasScriptBody" class="rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-800">
            本集暂无正文，不能审核通过。请先回到剧本写作生成或保存正文。
          </div>
          <template v-else>
            <span
              v-for="segment in scriptSegments"
              :key="segment.key"
              :class="markClass(segment.severity)"
            >{{ segment.text }}</span>
          </template>
        </article>
      </main>

      <aside class="rounded-lg border bg-card">
        <div class="border-b px-4 py-3">
          <h2 class="font-semibold">问题详情</h2>
          <p class="text-xs text-muted-foreground">红色不可通过，橙色高风险，蓝色提示</p>
        </div>
        <div class="h-[620px] space-y-3 overflow-auto p-4">
          <div v-if="!hasEpisodes" class="rounded-lg border border-dashed p-4 text-sm leading-6 text-muted-foreground">
            当前项目还没有可审核的分集。合规结论必须绑定到具体集数、文本片段和版本 hash 后才能进入人工审核。
          </div>
          <div v-else-if="!selectedEpisodeHasScriptBody" class="rounded-lg border border-amber-500/30 bg-amber-500/10 p-4 text-sm text-amber-700 dark:text-amber-300">
            当前无法审核：本集没有正文。
          </div>
          <div v-else-if="selectedFindings.length === 0" class="rounded-lg border border-emerald-500/30 bg-emerald-500/10 p-4 text-sm text-emerald-700 dark:text-emerald-300">
            当前没有待处理问题。
          </div>
          <div
            v-for="finding in selectedFindings"
            :key="finding.id"
            class="rounded-lg border p-4"
            :class="severityClass(finding.severity)"
          >
            <div class="mb-2 flex items-start justify-between gap-2">
              <div>
                <Badge variant="outline">{{ severityLabel(finding.severity) }}</Badge>
                <h3 class="mt-2 text-sm font-semibold">{{ finding.category }}</h3>
              </div>
              <span class="text-xs">{{ finding.rule_id }}</span>
            </div>
            <p class="text-xs leading-5"><strong>原文：</strong>{{ finding.quote }}</p>
            <p class="mt-2 text-xs leading-5"><strong>原因：</strong>{{ finding.reason }}</p>
            <p class="mt-2 text-xs leading-5"><strong>建议：</strong>{{ finding.suggestion }}</p>
            <div v-if="patchPreview[finding.id]" class="mt-3 rounded-md bg-background/80 p-3 text-xs leading-5">
              {{ patchPreview[finding.id] }}
            </div>
            <div class="mt-3 grid grid-cols-2 gap-2">
              <Button size="sm" variant="outline" @click="decide(finding, 'approved')">通过</Button>
              <Button size="sm" variant="outline" @click="decide(finding, 'false_positive')">误报</Button>
              <Button size="sm" variant="outline" @click="decide(finding, 'rewrite_required')">要求重写</Button>
              <Button size="sm" class="gap-1.5" @click="createPatch(finding)">
                <Wand2 class="h-3.5 w-3.5" />
                AI建议
              </Button>
            </div>
          </div>
        </div>
      </aside>
    </div>
  </section>
</template>

<style scoped>
:deep(.compliance-mark-red) {
  border-radius: 4px;
  background: rgba(239, 68, 68, 0.22);
  color: inherit;
  outline: 1px solid rgba(239, 68, 68, 0.42);
}

:deep(.compliance-mark-orange) {
  border-radius: 4px;
  background: rgba(249, 115, 22, 0.22);
  color: inherit;
  outline: 1px solid rgba(249, 115, 22, 0.42);
}

:deep(.compliance-mark-blue) {
  border-radius: 4px;
  background: rgba(59, 130, 246, 0.18);
  color: inherit;
  outline: 1px solid rgba(59, 130, 246, 0.32);
}
</style>
