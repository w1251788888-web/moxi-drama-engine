<script setup lang="ts">
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { Bot, ShieldCheck, Target } from 'lucide-vue-next'

type StateCardKind = 'relationship' | 'info' | 'power' | 'promise' | 'locked_fact'

type Character = {
  id: string
  name: string
  role: string
  motivation?: string
  voice_style?: string
}

type StateCard = {
  id: string
  title: string
  state: string
  summary: string
  related_character_ids: string[]
}

withDefaults(defineProps<{
  showScriptGraph?: boolean
  characterHealth: any[]
  workflowChainStatus: any
  currentHeadContractItems: any[]
  headGateIssues: string[]
  scriptDeepAudit: any
  activeStoryStateCards: {
    relationship_cards: StateCard[]
    info_cards: StateCard[]
    power_cards: StateCard[]
    promise_cards: StateCard[]
    locked_fact_cards: StateCard[]
  }
  pendingStateCardSuggestions: any[]
  sceneRelationshipDiagnostics: any
  pendingRelationshipSuggestions: any[]
  characters: Character[]
  scriptSceneCharacters: string[]
  roleColors: Record<string, string>
  scriptRuleValidation: any
  selectedEpisode: number
  scriptNetCharCount: number
  sceneContent: string
  roleColorFor: (role: string) => string
}>(), {
  showScriptGraph: false,
})

defineEmits<{
  addStoryStateCard: [kind: StateCardKind]
  acceptStateCardSuggestion: [item: any]
  dismissStateCardSuggestion: [key: string]
  removeStoryStateCard: [kind: StateCardKind, id: string]
  toggleStateCardCharacter: [card: StateCard, characterId: string]
  acceptRelationshipSuggestion: [item: any]
  dismissRelationshipSuggestion: [key: string]
}>()
</script>

<template>
  <div v-if="showScriptGraph" class="w-72 border-l bg-muted/10 flex flex-col shrink-0">
    <div class="flex items-center justify-between px-3 py-2 border-b shrink-0">
      <span class="text-xs font-semibold flex items-center gap-1.5 text-foreground">
        <Bot class="h-3.5 w-3.5" />状态与健康
      </span>
      <span v-if="characterHealth.some((c: any) => c.status === 'absent' || c.status === 'warning')"
        class="w-2 h-2 rounded-full bg-red-500 shrink-0"></span>
    </div>

    <div class="border-b p-2 space-y-2 shrink-0">
      <div class="rounded border bg-card/80 px-2 py-2 space-y-1.5">
        <div class="flex items-center justify-between text-[10px]">
          <span class="font-medium text-muted-foreground flex items-center gap-1">
            <Target class="h-3 w-3" />本集生成契约
          </span>
          <span :class="workflowChainStatus.hasCurrentContract ? 'text-emerald-600' : 'text-amber-600'">
            {{ workflowChainStatus.hasCurrentContract ? '已接入' : '未接入' }}
          </span>
        </div>
        <div v-if="currentHeadContractItems.length > 0" class="space-y-1">
          <div v-for="item in currentHeadContractItems" :key="item.key" class="rounded bg-muted/50 px-2 py-1">
            <div class="text-[10px] font-medium text-muted-foreground">{{ item.label }}</div>
            <div class="text-[10px] leading-relaxed text-foreground">{{ item.value }}</div>
          </div>
        </div>
        <div v-else class="text-[10px] text-muted-foreground">当前集还没有可用契约字段。</div>
      </div>

      <div class="rounded border bg-card/80 px-2 py-2 space-y-1.5">
        <div class="flex items-center justify-between text-[10px]">
          <span class="font-medium text-muted-foreground flex items-center gap-1">
            <ShieldCheck class="h-3 w-3" />头部质量门禁
          </span>
          <span :class="headGateIssues.length === 0 ? 'text-emerald-600' : 'text-amber-600'">
            {{ headGateIssues.length === 0 ? '暂无阻断' : `${headGateIssues.length}项` }}
          </span>
        </div>
        <div v-if="headGateIssues.length > 0" class="space-y-1">
          <div v-for="item in headGateIssues" :key="item" class="rounded bg-amber-50 px-2 py-1 text-[10px] leading-relaxed text-amber-700 dark:bg-amber-950/20 dark:text-amber-300">
            {{ item }}
          </div>
        </div>
        <div v-else class="text-[10px] text-muted-foreground">公开压迫、当场后果、物件钩子、OS控制等暂未触发提醒。</div>
      </div>

      <div class="rounded border bg-card/80 px-2 py-2 space-y-1.5">
        <div class="flex items-center justify-between text-[10px]">
          <span class="font-medium text-muted-foreground">逐集头部对标</span>
          <span :class="scriptDeepAudit.benchmark_assessment.passed ? 'text-emerald-600' : 'text-amber-600'">
            {{ scriptDeepAudit.benchmark_assessment.score || 0 }}分
          </span>
        </div>
        <div class="text-[11px] leading-relaxed text-foreground">
          {{ scriptDeepAudit.benchmark_assessment.track_name || '尚未运行深度审计' }}
        </div>
        <div v-if="scriptDeepAudit.benchmark_assessment.summary" class="text-[10px] text-muted-foreground leading-relaxed">
          {{ scriptDeepAudit.benchmark_assessment.summary }}
        </div>
        <div v-if="scriptDeepAudit.benchmark_assessment.gaps.length > 0" class="space-y-1">
          <div v-for="item in scriptDeepAudit.benchmark_assessment.gaps" :key="item" class="rounded bg-amber-50 px-2 py-1 text-[10px] text-amber-700 dark:bg-amber-950/20 dark:text-amber-300">
            {{ item }}
          </div>
        </div>
        <div v-if="scriptDeepAudit.benchmark_assessment.rule_upgrades.length > 0" class="space-y-1">
          <div class="text-[10px] font-medium text-muted-foreground">建议沉淀到项目规则层</div>
          <div v-for="item in scriptDeepAudit.benchmark_assessment.rule_upgrades" :key="item" class="rounded bg-sky-50 px-2 py-1 text-[10px] text-sky-700 dark:bg-sky-950/20 dark:text-sky-300">
            {{ item }}
          </div>
        </div>
        <div v-if="scriptDeepAudit.benchmark_assessment.gaps.length === 0 && scriptDeepAudit.benchmark_assessment.rule_upgrades.length === 0" class="text-[10px] text-muted-foreground">当前集暂无明显对标缺口。</div>
      </div>

      <div class="rounded border bg-card/80 px-2 py-2 space-y-1.5">
        <div class="flex items-center justify-between text-[10px]">
          <span class="font-medium text-muted-foreground">10集连续性</span>
          <span :class="scriptDeepAudit.continuity_assessment.passed ? 'text-emerald-600' : 'text-amber-600'">
            {{ scriptDeepAudit.continuity_assessment.score || 0 }}分
          </span>
        </div>
        <div class="text-[11px] leading-relaxed text-foreground">
          {{ scriptDeepAudit.continuity_assessment.checked_episode_span || '尚未运行深度审计' }}
        </div>
        <div v-if="scriptDeepAudit.continuity_assessment.summary" class="text-[10px] text-muted-foreground leading-relaxed">
          {{ scriptDeepAudit.continuity_assessment.summary }}
        </div>
        <div v-if="scriptDeepAudit.continuity_assessment.relationship_risks.length > 0 || scriptDeepAudit.continuity_assessment.plot_risks.length > 0" class="space-y-1">
          <div v-for="item in [...scriptDeepAudit.continuity_assessment.relationship_risks, ...scriptDeepAudit.continuity_assessment.plot_risks]" :key="item" class="rounded bg-rose-50 px-2 py-1 text-[10px] text-rose-700 dark:bg-rose-950/20 dark:text-rose-300">
            {{ item }}
          </div>
        </div>
        <div v-else class="text-[10px] text-muted-foreground">当前未发现明显角色关系或剧情推进漂移。</div>
      </div>
    </div>

    <div class="border-b p-2 space-y-1.5 shrink-0 max-h-72 overflow-y-auto">
      <div class="flex items-center justify-between">
        <div class="text-[10px] font-medium text-muted-foreground">状态卡</div>
        <div class="text-[10px] text-muted-foreground">
          当前场命中 {{
            activeStoryStateCards.relationship_cards.length
            + activeStoryStateCards.info_cards.length
            + activeStoryStateCards.power_cards.length
            + activeStoryStateCards.promise_cards.length
            + activeStoryStateCards.locked_fact_cards.length
          }} 张
        </div>
      </div>
      <div class="flex flex-wrap gap-1">
        <Button variant="outline" size="sm" class="h-6 px-2 text-[10px]" @click="$emit('addStoryStateCard', 'relationship')">+关系</Button>
        <Button variant="outline" size="sm" class="h-6 px-2 text-[10px]" @click="$emit('addStoryStateCard', 'info')">+信息</Button>
        <Button variant="outline" size="sm" class="h-6 px-2 text-[10px]" @click="$emit('addStoryStateCard', 'power')">+权力</Button>
        <Button variant="outline" size="sm" class="h-6 px-2 text-[10px]" @click="$emit('addStoryStateCard', 'promise')">+承诺</Button>
        <Button variant="outline" size="sm" class="h-6 px-2 text-[10px]" @click="$emit('addStoryStateCard', 'locked_fact')">+事实</Button>
      </div>

      <div v-if="pendingStateCardSuggestions.length > 0" class="space-y-1.5">
        <div class="text-[10px] font-medium text-muted-foreground">状态建议</div>
        <div
          v-for="item in pendingStateCardSuggestions"
          :key="String((item as any).key)"
          class="rounded border bg-card px-2 py-1.5 text-[10px] leading-relaxed space-y-1.5">
          <div class="font-medium text-foreground">{{ (item as any).title }}</div>
          <div class="text-muted-foreground">{{ (item as any).summary }}</div>
          <div class="flex gap-1.5">
            <Button size="sm" class="h-6 text-[10px] px-2" @click="$emit('acceptStateCardSuggestion', item)">写入状态卡</Button>
            <Button variant="outline" size="sm" class="h-6 text-[10px] px-2" @click="$emit('dismissStateCardSuggestion', String((item as any).key))">忽略</Button>
          </div>
        </div>
      </div>

      <div
        v-for="group in [
          { key: 'relationship_cards', label: '关系', cards: activeStoryStateCards.relationship_cards, kind: 'relationship' },
          { key: 'info_cards', label: '信息', cards: activeStoryStateCards.info_cards, kind: 'info' },
          { key: 'power_cards', label: '权力', cards: activeStoryStateCards.power_cards, kind: 'power' },
          { key: 'promise_cards', label: '承诺', cards: activeStoryStateCards.promise_cards, kind: 'promise' },
          { key: 'locked_fact_cards', label: '事实', cards: activeStoryStateCards.locked_fact_cards, kind: 'locked_fact' },
        ]"
        :key="group.key"
        class="space-y-1"
      >
        <div v-if="group.cards.length > 0" class="text-[10px] font-medium text-muted-foreground">{{ group.label }}</div>
        <div
          v-for="card in group.cards"
          :key="card.id"
          class="rounded border bg-card/80 px-2 py-1.5 space-y-1"
        >
          <div class="flex items-center gap-1.5">
            <Input v-model="card.title" class="h-6 text-[10px]" placeholder="状态标题" />
            <Button variant="ghost" size="sm" class="h-6 px-1.5 text-[10px]" @click="$emit('removeStoryStateCard', group.kind as StateCardKind, card.id)">删</Button>
          </div>
          <Input v-model="card.state" class="h-6 text-[10px]" placeholder="当前状态" />
          <Textarea v-model="card.summary" class="min-h-[52px] text-[10px] leading-relaxed resize-none" placeholder="写清现在到哪了、不能写错什么" />
          <div class="flex flex-wrap gap-1">
            <button
              v-for="char in characters"
              :key="char.id"
              class="text-[10px] px-1.5 py-0.5 rounded-full border transition-all"
              :class="card.related_character_ids.includes(char.id)
                ? 'text-white border-transparent'
                : 'border-muted-foreground/30 text-muted-foreground'"
              :style="card.related_character_ids.includes(char.id) ? { background: roleColorFor(char.role) } : {}"
              @click="$emit('toggleStateCardCharacter', card, char.id)"
            >
              {{ char.name }}
            </button>
          </div>
        </div>
      </div>

      <div
        v-if="
          activeStoryStateCards.relationship_cards.length === 0
          && activeStoryStateCards.info_cards.length === 0
          && activeStoryStateCards.power_cards.length === 0
          && activeStoryStateCards.promise_cards.length === 0
          && activeStoryStateCards.locked_fact_cards.length === 0
        "
        class="rounded border border-dashed px-2 py-2 text-[10px] text-muted-foreground"
      >
        当前场还没有命中的状态卡。先补“信息差 / 权力位置 / 未完成承诺”最有效。
      </div>
    </div>

    <div class="border-b p-2 space-y-1.5 shrink-0 max-h-52 overflow-y-auto">
      <div class="text-[10px] font-medium text-muted-foreground">关系护栏</div>
      <div v-if="sceneRelationshipDiagnostics.summaryLines.length > 0" class="space-y-1">
        <div
          v-for="line in sceneRelationshipDiagnostics.summaryLines"
          :key="line"
          class="rounded bg-muted/40 px-2 py-1 text-[10px] text-foreground leading-relaxed">
          {{ line }}
        </div>
      </div>
      <div v-else class="rounded border border-dashed px-2 py-1.5 text-[10px] text-muted-foreground">
        暂无明确护栏
      </div>
      <div
        v-for="warning in sceneRelationshipDiagnostics.warnings"
        :key="warning"
        class="rounded bg-amber-50 text-amber-700 dark:bg-amber-950/20 dark:text-amber-300 px-2 py-1 text-[10px] leading-relaxed">
        {{ warning }}
      </div>
      <div v-if="pendingRelationshipSuggestions.length > 0" class="space-y-1.5 pt-0.5">
        <div class="text-[10px] font-medium text-muted-foreground">关系变化</div>
        <div
          v-for="item in pendingRelationshipSuggestions"
          :key="String((item as any).key)"
          class="rounded border bg-card px-2 py-1.5 text-[10px] leading-relaxed space-y-1.5">
          <div class="font-medium text-foreground">
            {{ (item as any).source_name }} ↔ {{ (item as any).target_name }} → {{ (item as any).suggested_type }}
          </div>
          <div class="text-muted-foreground">{{ (item as any).description }}</div>
          <div class="flex gap-1.5">
            <Button size="sm" class="h-6 text-[10px] px-2" @click="$emit('acceptRelationshipSuggestion', item)">写回</Button>
            <Button variant="outline" size="sm" class="h-6 text-[10px] px-2" @click="$emit('dismissRelationshipSuggestion', String((item as any).key))">忽略</Button>
          </div>
        </div>
      </div>
    </div>

    <div class="border-b p-2 space-y-1 max-h-44 overflow-y-auto shrink-0">
      <div class="text-[10px] font-medium text-muted-foreground mb-1">出场角色档案</div>
      <div v-for="char in characters.filter((c: Character) => scriptSceneCharacters.includes(c.id))" :key="char.id"
        class="rounded p-1.5 text-xs space-y-0.5"
        :style="{ borderLeft: `3px solid ${roleColors[char.role] || '#94a3b8'}`, background: 'rgba(0,0,0,0.02)' }">
        <div class="font-medium">{{ char.name }}</div>
        <div v-if="char.motivation" class="text-[10px] text-muted-foreground">{{ char.motivation }}</div>
        <div v-if="char.voice_style" class="text-[10px] text-amber-600 dark:text-amber-400">{{ char.voice_style }}</div>
      </div>
      <div v-if="scriptSceneCharacters.length === 0" class="text-[10px] text-muted-foreground text-center py-2">
        点击角色标签选中出场角色
      </div>
    </div>

    <div class="flex-1 overflow-y-auto">
      <div class="p-2 space-y-1">
        <div v-if="scriptRuleValidation.warnings.length > 0" class="rounded-lg border border-sky-200 bg-sky-50 p-2 text-xs space-y-1">
          <div class="font-medium text-sky-700">规则提醒</div>
          <div v-for="item in scriptRuleValidation.warnings" :key="item" class="text-sky-700 leading-relaxed">
            {{ item }}
          </div>
        </div>

        <div class="rounded-lg p-2 bg-muted/40 text-xs space-y-1 mb-2">
          <div class="font-medium text-foreground">第{{ selectedEpisode }}集 · 净字数 {{ scriptNetCharCount }}</div>
          <div class="flex gap-3 text-muted-foreground">
            <span>主角OS: {{ characterHealth.find((c: any) => c.role === 'protagonist')?.osCount ?? 0 }}/最多1-2处</span>
            <span>出场: {{ characterHealth.filter((c: any) => c.present).length }}/{{ characters.length }}</span>
          </div>
          <div v-if="characterHealth.find((c: any) => c.role === 'protagonist')" class="mt-1">
            <div class="flex items-center gap-1">
              <span class="text-muted-foreground">OS频率：</span>
              <span :class="{
                'text-emerald-600': (characterHealth.find((c: any) => c.role === 'protagonist')?.osCount ?? 0) <= 2,
                'text-red-500': (characterHealth.find((c: any) => c.role === 'protagonist')?.osCount ?? 0) > 2,
              }">
                {{ (() => {
                  const n = characterHealth.find((c: any) => c.role === 'protagonist')?.osCount ?? 0
                  if (n === 0 && scriptNetCharCount < 100) return '—'
                  if (n <= 2) return '✓ 现实动作承载(' + n + '处)'
                  return '⚠ 过多(' + n + '处)'
                })() }}
              </span>
            </div>
          </div>
        </div>

        <div v-for="ch in characterHealth" :key="ch.id"
          class="flex items-center gap-2 rounded-lg px-2 py-1.5 text-xs transition-colors"
          :class="{
            'bg-red-50 dark:bg-red-950/20': ch.status === 'absent',
            'bg-amber-50 dark:bg-amber-950/20': ch.status === 'warning',
            'bg-muted/30': ch.status === 'idle',
            'hover:bg-muted/50': ch.status === 'normal',
          }">
          <div class="w-2.5 h-2.5 rounded-full shrink-0"
            :style="{ background: roleColors[ch.role] || '#94a3b8' }"
            :class="{ 'opacity-30': !ch.present }"></div>
          <span class="font-medium w-14 truncate shrink-0"
            :class="{ 'text-muted-foreground/50': !ch.present }">{{ ch.name }}</span>
          <span class="w-10 text-center text-muted-foreground">
            <span v-if="ch.present" :class="ch.dialogueCount > 0 ? 'text-foreground' : 'text-amber-500'">
              {{ ch.dialogueCount }}台词
            </span>
            <span v-else class="opacity-40">—</span>
          </span>
          <span class="w-10 text-center text-muted-foreground text-[10px]">
            <span v-if="ch.role === 'protagonist' && ch.present"
              :class="[3,4,5,6].includes(ch.osCount) ? 'text-emerald-600' : ch.osCount > 0 ? 'text-amber-500' : 'text-red-500'">
              {{ ch.osCount }}OS
            </span>
          </span>
          <span class="ml-auto text-[10px] font-medium shrink-0"
            :class="{
              'text-red-500': ch.status === 'absent',
              'text-amber-500': ch.status === 'warning',
              'text-emerald-600': ch.status === 'normal',
              'text-muted-foreground/40': ch.status === 'idle',
            }">
            <span v-if="ch.status === 'absent'">🔴 {{ ch.reason }}</span>
            <span v-else-if="ch.status === 'warning'">⚠ {{ ch.reason }}</span>
            <span v-else-if="ch.status === 'normal'">✓</span>
            <span v-else>—</span>
          </span>
        </div>

        <div v-if="!characters.length" class="text-xs text-muted-foreground text-center py-6">
          请先在角色设计中添加角色
        </div>
        <div v-else-if="!sceneContent" class="text-xs text-muted-foreground text-center py-4">
          开始写作后实时显示角色健康数据
        </div>
      </div>
    </div>

    <div class="border-t p-2 shrink-0">
      <div class="text-[10px] text-muted-foreground leading-relaxed space-y-0.5">
        <div>• 现实题材OS最多1-2处，优先用动作和物件承载情绪</div>
        <div>• 每场戏出场角色都应有台词</div>
        <div>• 反派每集至少1场正面冲突</div>
      </div>
    </div>
  </div>
</template>
