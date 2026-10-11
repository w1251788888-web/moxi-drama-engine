<script setup lang="ts">
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Badge } from '@/components/ui/badge'
import { Link, Plus, X } from 'lucide-vue-next'

type OutlineCharacter = {
  id: string
  name: string
  role: string
  info: string
  relationships?: Array<Record<string, unknown> | string>
}

defineProps<{
  roleColors: Record<string, string>
  aiGenerated: boolean
}>()

const outlineCharacters = defineModel<OutlineCharacter[]>('outlineCharacters', { required: true })

defineEmits<{
  add: []
  remove: [id: string]
}>()

function textValue(value: unknown) {
  return String(value || '').trim()
}

function relationshipLabel(rel: Record<string, unknown> | string) {
  if (typeof rel === 'string') return rel.trim()
  const target = textValue(rel.targetName || rel.target_name || rel.target || rel.to || rel.name)
  const earlyType = textValue(rel.earlyType || rel.early_type || rel.early || rel.type || rel.relationship || rel.relation || rel.state)
  const lateType = textValue(rel.lateType || rel.late_type || rel.late || rel.afterType || rel.after_type)
  const transitionEpisode = textValue(rel.transitionEpisode || rel.transition_episode || rel.turningEpisode || rel.turning_episode)
  const finalBoundary = textValue(rel.finalBoundary || rel.final_boundary || rel.boundary)
  const description = textValue(rel.description || rel.desc || rel.detail || rel.summary)
  return [
    target && `与${target}`,
    earlyType && `· 早期关系：${earlyType}`,
    lateType && ` → 后期关系：${lateType}`,
    transitionEpisode && `（转折集：第${transitionEpisode}集）`,
    finalBoundary && `；禁止提前写出：${finalBoundary}`,
    description && `：${description}`,
  ].filter(Boolean).join('')
}

function relationshipRows(char: OutlineCharacter) {
  return Array.isArray(char.relationships) ? char.relationships : []
}

function relationshipCandidateStatus(rel: Record<string, unknown> | string) {
  if (typeof rel === 'string') return ''
  return textValue(rel.candidateStatus || rel.candidate_status || rel.status)
}

function isCandidateRelationship(rel: Record<string, unknown> | string) {
  if (typeof rel === 'string') return false
  const status = relationshipCandidateStatus(rel)
  return !status || status === 'needs_user_confirmation'
}

function confirmRelationshipLine(char: OutlineCharacter, relIndex: number) {
  outlineCharacters.value = outlineCharacters.value.map((item) => {
    if (item.id !== char.id) return item
    const relationships = relationshipRows(item).map((rel, index) => {
      if (index !== relIndex || typeof rel === 'string') return rel
      return {
        ...rel,
        candidateStatus: 'confirmed',
        candidate_status: 'confirmed',
        status: 'confirmed',
      }
    })
    return { ...item, relationships }
  })
}

function infoRelationshipLabels(info: string) {
  return String(info || '')
    .split('\n')
    .map(line => line.trim())
    .filter(line => /^(人物关系|角色关系|关系)\s*[：:]/.test(line) || /^与[^（(：:，,；;。\n]{1,16}[（(]/.test(line))
    .flatMap(line => line.replace(/^(人物关系|角色关系|关系)\s*[：:]\s*/, '').split(/[；;]/))
    .map(item => item.trim())
    .filter(Boolean)
}

function relationshipLabels(char: OutlineCharacter) {
  const items = Array.isArray(char.relationships)
    ? char.relationships.map(relationshipLabel).filter(Boolean)
    : []
  const fromInfo = infoRelationshipLabels(char.info)
  return Array.from(new Set([...items, ...fromInfo]))
}
</script>

<template>
  <div class="space-y-2">
    <div class="flex items-center justify-between">
      <span class="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
        角色 <span class="text-primary font-bold">{{ outlineCharacters.length }}</span>
        <Badge v-if="aiGenerated" variant="secondary" class="ml-1 text-[10px] px-1.5 py-0">AI补全</Badge>
      </span>
      <Button variant="outline" size="sm" class="h-6 text-xs gap-1 px-2" @click="$emit('add')">
        <Plus class="h-3 w-3" />添加角色
      </Button>
    </div>
    <div
      v-if="outlineCharacters.length"
      class="rounded-md border border-amber-200 bg-amber-50 px-2.5 py-2 text-[11px] leading-relaxed text-amber-800 dark:border-amber-900/60 dark:bg-amber-950/20 dark:text-amber-300"
    >
      请确认角色身份和人物关系是否符合原大纲；自动识别只能作为初稿，关系会直接影响后续剧本生成。
    </div>
    <div class="space-y-2">
      <div v-for="char in outlineCharacters" :key="char.id"
        class="border rounded-lg p-2.5 group"
        :class="{
          'border-blue-200 bg-blue-50/40 dark:bg-blue-950/20 dark:border-blue-800': char.role === 'protagonist',
          'border-red-200 bg-red-50/40 dark:bg-red-950/20 dark:border-red-800': char.role === 'antagonist',
          'border-green-200 bg-green-50/40 dark:bg-green-950/20 dark:border-green-800': char.role === 'supporting',
          'border-border bg-muted/20': char.role === 'minor'
        }">
        <div class="flex items-center gap-2 mb-2">
          <div class="w-7 h-7 rounded-full flex items-center justify-center text-white text-xs font-bold shrink-0"
            :style="{ background: roleColors[char.role] || '#94a3b8' }">
            {{ char.name ? char.name[0] : '?' }}
          </div>
          <Input v-model="char.name" placeholder="角色姓名" class="h-7 text-sm font-medium flex-1 min-w-0" />
          <select v-model="char.role" class="h-7 px-1.5 rounded border bg-background text-xs shrink-0">
            <option value="protagonist">主角</option>
            <option value="antagonist">反派</option>
            <option value="supporting">配角</option>
            <option value="minor">次要</option>
          </select>
          <button class="text-muted-foreground/40 hover:text-destructive transition-colors shrink-0"
            title="删除角色"
            @click="$emit('remove', char.id)">
            <X class="h-3.5 w-3.5" />
          </button>
        </div>
        <textarea v-model="char.info"
          :placeholder="`${char.name || '角色'}的所有信息：职业、外貌、性格、说话方式、背景、动机、特殊能力、人物关系等（直接填写，不用分类）`"
          class="w-full text-xs rounded border bg-background/80 px-2 py-1.5 resize-y focus:outline-none focus:ring-1 focus:ring-primary leading-relaxed"
          rows="4" />
        <div class="mt-2 rounded-md border bg-background/70 px-2 py-1.5">
          <div class="mb-1 flex items-center gap-1 text-[10px] font-medium text-muted-foreground">
            <Link class="h-3 w-3" />
            关系设计
          </div>
          <div
            v-if="relationshipRows(char).length"
            class="mb-1.5 rounded border border-dashed border-amber-300 bg-amber-50 px-2 py-1 text-[10px] leading-relaxed text-amber-800 dark:border-amber-900/60 dark:bg-amber-950/20 dark:text-amber-300"
          >
            AI识别关系候选：候选状态为 <span class="font-mono">needs_user_confirmation</span> 的关系线，需要用户确认后再作为生成依据。
          </div>
          <div v-if="relationshipRows(char).length" class="mb-1.5 space-y-1">
            <div
              v-for="(rel, relIndex) in relationshipRows(char)"
              :key="`${char.id}-rel-${relIndex}`"
              class="flex items-center justify-between gap-2 rounded bg-muted/40 px-2 py-1"
            >
              <span class="min-w-0 truncate text-[10px]" :title="relationshipLabel(rel)">
                {{ relationshipLabel(rel) }}
              </span>
              <button
                v-if="isCandidateRelationship(rel)"
                type="button"
                class="h-5 shrink-0 rounded-md border bg-background px-1.5 text-[10px] transition-colors hover:bg-accent hover:text-accent-foreground"
                title="确认关系线"
                @click="confirmRelationshipLine(char, relIndex)"
              >
                确认关系线
              </button>
              <Badge v-else variant="secondary" class="shrink-0 text-[10px]">已确认</Badge>
            </div>
          </div>
          <div v-if="relationshipLabels(char).length" class="flex flex-wrap gap-1">
            <Badge
              v-for="item in relationshipLabels(char)"
              :key="item"
              variant="secondary"
              class="max-w-full truncate text-[10px] font-normal"
              :title="item"
            >
              {{ item }}
            </Badge>
          </div>
          <div v-else class="text-[10px] leading-relaxed text-muted-foreground">
            暂未提取关系；可在上方小传中写“关系：与某某（类型，说明）”，进入角色设计时会同步为关系图。
          </div>
        </div>
      </div>
      <div v-if="outlineCharacters.length === 0"
        class="text-center py-6 border-2 border-dashed rounded-lg text-muted-foreground text-xs">
        自动分割后会显示原文中识别到的角色；没有识别到的角色请手动添加
      </div>
    </div>
  </div>
</template>
