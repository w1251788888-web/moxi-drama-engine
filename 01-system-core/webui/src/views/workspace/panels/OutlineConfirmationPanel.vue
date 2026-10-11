<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import {
  BookOpenCheck,
  Check,
  ChevronDown,
  FilePenLine,
  Plus,
  Sparkles,
  Trash2,
} from 'lucide-vue-next'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Textarea } from '@/components/ui/textarea'
import {
  OUTLINE_EDITOR_CONFIRMATION_SECTIONS,
  createOutlineEditorConfirmationDraft,
  outlineEditorSectionStatus,
  type OutlineEditorConfirmationDraft,
  type OutlineEditorConfirmationSectionId,
} from '@/features/workspace/utils/outlineEditorConfirmation'
import type { StandardOutlinePacket } from '@/features/workspace/utils/standardOutlinePacket'

const props = defineProps<{
  packet: StandardOutlinePacket | Record<string, unknown>
  organizing: boolean
  confirmingSection: OutlineEditorConfirmationSectionId | ''
  referenceLoading: boolean
}>()

const emit = defineEmits<{
  organize: []
  confirm: [sectionId: OutlineEditorConfirmationSectionId, draft: OutlineEditorConfirmationDraft]
  openOutline: []
}>()

const drafts = ref<Record<OutlineEditorConfirmationSectionId, any>>({} as Record<OutlineEditorConfirmationSectionId, any>)

const confirmedCount = computed(() => (
  OUTLINE_EDITOR_CONFIRMATION_SECTIONS.filter(
    section => outlineEditorSectionStatus(props.packet, section.id) === 'confirmed',
  ).length
))

function resetDrafts() {
  drafts.value = Object.fromEntries(
    OUTLINE_EDITOR_CONFIRMATION_SECTIONS.map(section => [
      section.id,
      createOutlineEditorConfirmationDraft(props.packet, section.id),
    ]),
  ) as Record<OutlineEditorConfirmationSectionId, any>
}

function sectionStatus(sectionId: OutlineEditorConfirmationSectionId) {
  return outlineEditorSectionStatus(props.packet, sectionId)
}

function statusLabel(sectionId: OutlineEditorConfirmationSectionId) {
  const status = sectionStatus(sectionId)
  if (status === 'confirmed') return '已确认'
  if (status === 'candidate') return '待确认'
  return '待讨论'
}

function statusClass(sectionId: OutlineEditorConfirmationSectionId) {
  const status = sectionStatus(sectionId)
  if (status === 'confirmed') return 'border-emerald-200 bg-emerald-50 text-emerald-700'
  if (status === 'candidate') return 'border-amber-200 bg-amber-50 text-amber-700'
  return 'border-border bg-muted text-muted-foreground'
}

function cloneDraft(sectionId: OutlineEditorConfirmationSectionId) {
  return JSON.parse(JSON.stringify(drafts.value[sectionId])) as OutlineEditorConfirmationDraft
}

function confirmSection(sectionId: OutlineEditorConfirmationSectionId) {
  emit('confirm', sectionId, cloneDraft(sectionId))
}

function addCharacter() {
  drafts.value.characters.push({
    id: `outline-character-${Date.now()}`,
    name: '',
    role: 'supporting',
    info: '',
  })
}

function addRelationship() {
  drafts.value.relationships.push({
    source: '',
    targetName: '',
    earlyType: '',
    lateType: '',
    transitionEpisode: null,
    finalBoundary: '',
    description: '',
  })
}

function addEpisode() {
  const rows = drafts.value.episode_outlines
  const maxEpisode = rows.reduce((max: number, item: { ep?: number }) => Math.max(max, Number(item.ep || 0)), 0)
  rows.push({
    ep: maxEpisode + 1,
    title: '',
    summary: '',
    conflict: '',
    turning: '',
    main_scene: '',
    relationship_change: '',
    info_revealed: '',
    satisfaction_type: '',
  })
}

watch(
  () => String((props.packet as StandardOutlinePacket)?.updated_at || ''),
  () => {
    // 确认事务会临时替换资料包再做服务器保存。事务进行中不能重建草稿，
    // 否则保存失败回滚时会把用户刚刚手改、准备重试的内容清掉。
    if (props.confirmingSection) return
    resetDrafts()
  },
  { immediate: true },
)
</script>

<template>
  <aside class="w-72 xl:w-80 shrink-0 border-l bg-card flex flex-col overflow-hidden">
    <div class="border-b px-4 py-3">
      <div class="flex items-center justify-between gap-2">
        <div class="flex min-w-0 items-center gap-2">
          <span class="flex h-8 w-8 shrink-0 items-center justify-center rounded-md border bg-background">
            <BookOpenCheck class="h-4 w-4 text-primary" />
          </span>
          <div class="min-w-0">
            <h2 class="truncate text-sm font-semibold">大纲确认</h2>
            <p class="text-[11px] text-muted-foreground">{{ confirmedCount }} / 7 项已确认</p>
          </div>
        </div>
        <Button variant="ghost" size="sm" class="h-8 px-2 text-xs" @click="emit('openOutline')">
          大纲编辑
        </Button>
      </div>
      <p class="mt-2 text-[11px] leading-relaxed text-muted-foreground">
        AI 只把讨论整理成候选。你可以展开修改；点击“确认本项”后，这一项才进入大纲资料。
      </p>
      <Button
        variant="outline"
        size="sm"
        class="mt-3 w-full gap-2"
        :disabled="organizing || referenceLoading || Boolean(confirmingSection)"
        @click="emit('organize')"
      >
        <Sparkles class="h-4 w-4" :class="{ 'animate-spin': organizing }" />
        {{ organizing ? '正在整理讨论...' : '整理当前讨论' }}
      </Button>
    </div>

    <ScrollArea class="flex-1">
      <div class="space-y-2 p-3">
        <details
          v-for="(section, sectionIndex) in OUTLINE_EDITOR_CONFIRMATION_SECTIONS"
          :key="section.id"
          class="group rounded-lg border bg-background open:shadow-sm"
          :open="sectionIndex === 0 && sectionStatus(section.id) !== 'confirmed'"
        >
          <summary class="flex min-h-12 cursor-pointer list-none items-center gap-2 px-3 py-2 [&::-webkit-details-marker]:hidden">
            <span
              class="flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-[11px] font-semibold"
              :class="sectionStatus(section.id) === 'confirmed'
                ? 'bg-emerald-100 text-emerald-700'
                : 'bg-muted text-muted-foreground'"
            >
              <Check v-if="sectionStatus(section.id) === 'confirmed'" class="h-3.5 w-3.5" />
              <template v-else>{{ sectionIndex + 1 }}</template>
            </span>
            <span class="min-w-0 flex-1">
              <span class="block truncate text-xs font-semibold">{{ section.label }}</span>
              <span class="block truncate text-[10px] text-muted-foreground">{{ section.description }}</span>
            </span>
            <Badge variant="outline" class="shrink-0 text-[10px]" :class="statusClass(section.id)">
              {{ statusLabel(section.id) }}
            </Badge>
            <ChevronDown class="h-3.5 w-3.5 shrink-0 text-muted-foreground transition-transform group-open:rotate-180" />
          </summary>

          <div class="space-y-3 border-t p-3">
            <template v-if="section.id === 'creative_direction'">
              <label class="field-label">
                <span>受众</span>
                <select v-model="drafts.creative_direction.audience_axis" class="field-control">
                  <option value="">请选择</option>
                  <option value="女频">女频</option>
                  <option value="男频">男频</option>
                  <option value="混合">混合</option>
                </select>
              </label>
              <label class="field-label">
                <span>题材</span>
                <Input v-model="drafts.creative_direction.genre_main" placeholder="例：悬疑情感" class="h-8 text-xs" />
              </label>
              <label class="field-label">
                <span>制作形式</span>
                <select v-model="drafts.creative_direction.format_type" class="field-control">
                  <option value="">请选择</option>
                  <option value="真人短剧">真人短剧</option>
                  <option value="漫剧">漫剧</option>
                  <option value="AI真人">AI真人</option>
                </select>
              </label>
            </template>

            <template v-else-if="section.id === 'logline'">
              <label class="field-label">
                <span>一句话梗概</span>
                <Textarea
                  v-model="drafts.logline.logline"
                  class="min-h-28 resize-y text-xs leading-relaxed"
                  placeholder="主角是谁、想做什么、受到什么阻碍？"
                />
              </label>
            </template>

            <template v-else-if="section.id === 'world_and_conflict'">
              <label class="field-label">
                <span>世界观</span>
                <Textarea v-model="drafts.world_and_conflict.worldview" class="min-h-20 resize-y text-xs" />
              </label>
              <label class="field-label">
                <span>金手指 / 特殊设定</span>
                <Textarea v-model="drafts.world_and_conflict.golden_finger" class="min-h-20 resize-y text-xs" />
              </label>
              <label class="field-label">
                <span>核心冲突 / 爽点</span>
                <Textarea v-model="drafts.world_and_conflict.conflict" class="min-h-20 resize-y text-xs" />
              </label>
            </template>

            <template v-else-if="section.id === 'characters'">
              <div
                v-for="(character, index) in drafts.characters"
                :key="character.id || index"
                class="space-y-2 rounded-md border bg-muted/20 p-2"
              >
                <div class="flex gap-2">
                  <Input v-model="character.name" placeholder="角色姓名" class="h-8 min-w-0 flex-1 text-xs" />
                  <select v-model="character.role" class="field-control w-20 shrink-0">
                    <option value="protagonist">主角</option>
                    <option value="antagonist">反派</option>
                    <option value="supporting">配角</option>
                    <option value="minor">次要</option>
                  </select>
                  <button class="icon-button" title="删除角色" @click="drafts.characters.splice(index, 1)">
                    <Trash2 class="h-3.5 w-3.5" />
                  </button>
                </div>
                <Textarea
                  v-model="character.info"
                  class="min-h-24 resize-y text-xs leading-relaxed"
                  placeholder="人物小传：身份、性格、背景、动机、能力等"
                />
              </div>
              <Button variant="outline" size="sm" class="w-full gap-1 text-xs" @click="addCharacter">
                <Plus class="h-3.5 w-3.5" />添加角色
              </Button>
            </template>

            <template v-else-if="section.id === 'relationships'">
              <p
                v-if="drafts.relationships.length === 0"
                class="rounded-md border border-dashed bg-muted/30 px-2 py-2 text-[11px] leading-relaxed text-muted-foreground"
              >
                当前没有人物关系。若这是单人物故事或明确没有关系线，可以直接点击“确认本项”。
              </p>
              <div
                v-for="(relationship, index) in drafts.relationships"
                :key="index"
                class="space-y-2 rounded-md border bg-muted/20 p-2"
              >
                <div class="grid grid-cols-2 gap-2">
                  <Input v-model="relationship.source" placeholder="人物 A" class="h-8 text-xs" />
                  <Input v-model="relationship.targetName" placeholder="人物 B" class="h-8 text-xs" />
                  <Input v-model="relationship.earlyType" placeholder="早期关系" class="h-8 text-xs" />
                  <Input v-model="relationship.lateType" placeholder="后期关系" class="h-8 text-xs" />
                  <Input
                    v-model.number="relationship.transitionEpisode"
                    type="number"
                    min="1"
                    placeholder="转折集"
                    class="h-8 text-xs"
                  />
                  <Input v-model="relationship.finalBoundary" placeholder="禁止提前揭露" class="h-8 text-xs" />
                </div>
                <Textarea v-model="relationship.description" class="min-h-16 resize-y text-xs" placeholder="关系说明" />
                <Button variant="ghost" size="sm" class="h-7 w-full gap-1 text-xs text-destructive" @click="drafts.relationships.splice(index, 1)">
                  <Trash2 class="h-3.5 w-3.5" />删除关系
                </Button>
              </div>
              <Button variant="outline" size="sm" class="w-full gap-1 text-xs" @click="addRelationship">
                <Plus class="h-3.5 w-3.5" />添加关系
              </Button>
            </template>

            <template v-else-if="section.id === 'episode_plan'">
              <label class="field-label">
                <span>总集数</span>
                <Input
                  v-model.number="drafts.episode_plan.total_episodes"
                  type="number"
                  min="1"
                  max="200"
                  class="h-8 text-xs"
                />
              </label>
            </template>

            <template v-else-if="section.id === 'episode_outlines'">
              <details
                v-for="(episode, index) in drafts.episode_outlines"
                :key="`${episode.ep}-${index}`"
                class="rounded-md border bg-muted/20"
              >
                <summary class="flex cursor-pointer list-none items-center gap-2 px-2 py-2 text-xs font-semibold [&::-webkit-details-marker]:hidden">
                  <span class="flex h-5 w-5 items-center justify-center rounded-full bg-primary/10 text-[10px] text-primary">
                    {{ episode.ep }}
                  </span>
                  <span class="min-w-0 flex-1 truncate">{{ episode.title || `第${episode.ep}集` }}</span>
                  <ChevronDown class="h-3.5 w-3.5 text-muted-foreground" />
                </summary>
                <div class="space-y-2 border-t p-2">
                  <div class="grid grid-cols-[56px_1fr] gap-2">
                    <Input v-model.number="episode.ep" type="number" min="1" class="h-8 text-xs" />
                    <Input v-model="episode.title" placeholder="标题" class="h-8 text-xs" />
                  </div>
                  <Textarea v-model="episode.summary" class="min-h-24 resize-y text-xs" placeholder="单集集纲" />
                  <Textarea v-model="episode.conflict" class="min-h-16 resize-y text-xs" placeholder="本集冲突" />
                  <Textarea v-model="episode.turning" class="min-h-16 resize-y text-xs" placeholder="转折 / 爆点" />
                  <Input v-model="episode.main_scene" placeholder="主场景" class="h-8 text-xs" />
                  <Input v-model="episode.satisfaction_type" placeholder="爽点类型" class="h-8 text-xs" />
                  <Input v-model="episode.relationship_change" placeholder="关系变化" class="h-8 text-xs" />
                  <Input v-model="episode.info_revealed" placeholder="信息揭露" class="h-8 text-xs" />
                  <Button variant="ghost" size="sm" class="h-7 w-full gap-1 text-xs text-destructive" @click="drafts.episode_outlines.splice(index, 1)">
                    <Trash2 class="h-3.5 w-3.5" />删除本集
                  </Button>
                </div>
              </details>
              <Button variant="outline" size="sm" class="w-full gap-1 text-xs" @click="addEpisode">
                <Plus class="h-3.5 w-3.5" />添加分集
              </Button>
            </template>

            <Button
              class="w-full gap-2"
              size="sm"
              :disabled="Boolean(confirmingSection) || organizing || referenceLoading"
              @click="confirmSection(section.id)"
            >
              <FilePenLine v-if="confirmingSection === section.id" class="h-4 w-4 animate-pulse" />
              <Check v-else class="h-4 w-4" />
              {{ confirmingSection === section.id ? '正在保存...' : '确认本项' }}
            </Button>
          </div>
        </details>
      </div>
    </ScrollArea>
  </aside>
</template>

<style scoped>
.field-label {
  display: grid;
  gap: 0.375rem;
  font-size: 0.75rem;
  font-weight: 600;
  color: hsl(var(--muted-foreground));
}

.field-control {
  height: 2rem;
  width: 100%;
  border-radius: calc(var(--radius) - 4px);
  border: 1px solid hsl(var(--border));
  background: hsl(var(--background));
  padding: 0 0.5rem;
  font-size: 0.75rem;
  color: hsl(var(--foreground));
  outline: none;
}

.field-control:focus {
  border-color: hsl(var(--ring));
  box-shadow: 0 0 0 1px hsl(var(--ring));
}

.icon-button {
  display: inline-flex;
  height: 2rem;
  width: 2rem;
  flex-shrink: 0;
  align-items: center;
  justify-content: center;
  border-radius: calc(var(--radius) - 4px);
  color: hsl(var(--muted-foreground));
}

.icon-button:hover {
  background: hsl(var(--destructive) / 0.1);
  color: hsl(var(--destructive));
}
</style>
