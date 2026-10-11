<script setup lang="ts">
import { ref, watch, computed } from 'vue'
import { formatAccessErrorMessage, notifyApiError } from '@/api/http'
import { Lock, Unlock, Sparkles, Save, Plus, Trash2, X } from 'lucide-vue-next'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { Badge } from '@/components/ui/badge'
import { toast } from 'vue-sonner'
import {
  characterVisualApi,
  type CharacterVisualBase,
  type CharacterVisualText,
  type OutfitVariant,
} from '@/api/client'

interface Props {
  projectId: string
  characterId: string
  characterName: string
  narrativeProfile?: string
  genre?: string
  styleMode?: string
}

const props = defineProps<Props>()
const emit = defineEmits<{
  (e: 'locked'): void
  (e: 'unlocked'): void
  (e: 'saved'): void
  (e: 'close'): void
}>()

const loading = ref(false)
const saving = ref(false)
const generating = ref(false)
const locking = ref(false)

const data = ref<CharacterVisualBase | null>(null)
const visualText = ref<CharacterVisualText>({
  age_look: '', gender: '', face: '', hair: '', body: '', skin: '',
  default_outfit: '', signature_props: '', voice_tone: '', style_tags: '',
})
const outfitVariants = ref<OutfitVariant[]>([])
const negativePrompt = ref('')
const statusMessage = ref('')

const isLocked = computed(() => !!data.value?.is_locked)
const hasDraftContent = computed(() => {
  const textValues = Object.values(visualText.value || {})
  return textValues.some((value) => String(value || '').trim())
    || outfitVariants.value.length > 0
    || !!negativePrompt.value.trim()
})

const FIELD_LABELS: Record<keyof CharacterVisualText, string> = {
  age_look: '年龄外貌',
  gender: '性别',
  face: '面部特征',
  hair: '发型',
  body: '体型',
  skin: '肤色',
  default_outfit: '默认服装',
  signature_props: '标志性道具',
  voice_tone: '音色',
  style_tags: '风格标签',
}

function emptyVisualText(): CharacterVisualText {
  return {
    age_look: '', gender: '', face: '', hair: '', body: '', skin: '',
    default_outfit: '', signature_props: '', voice_tone: '', style_tags: '',
  }
}

function resetDraft() {
  data.value = null
  visualText.value = emptyVisualText()
  outfitVariants.value = []
  negativePrompt.value = ''
  statusMessage.value = ''
}

function accessStatusMessage(error: unknown): string {
  const accessMessage = formatAccessErrorMessage(error)
  if (accessMessage) return accessMessage
  return ''
}

function visualOperationMessage(error: unknown, fallback: string): string {
  const accessMessage = accessStatusMessage(error)
  if (accessMessage) return accessMessage
  const response = (error as { response?: { status?: number; data?: { detail?: string } } } | undefined)?.response
  const detail = String(response?.data?.detail || '')
  if (detail === 'character_visual_locked') {
    return '当前视觉档案已锁定，请先解锁后再保存。'
  }
  if (response?.status === 422) {
    return `档案字段格式不正确：${detail || '请检查必填字段后重试。'}`
  }
  if (detail === 'not_found') {
    return '请先保存档案，保存成功后再锁定视觉档案。'
  }
  return fallback
}

function isRequestTimeout(error: unknown): boolean {
  const code = String((error as { code?: string } | undefined)?.code || '')
  const message = String((error as { message?: string } | undefined)?.message || '')
  return code === 'ECONNABORTED' || message.includes('timeout')
}

async function recoverAfterTimeout(action: 'save' | 'lock'): Promise<boolean> {
  await load()
  if (action === 'save' && data.value) {
    statusMessage.value = data.value.is_locked
      ? `保存请求超时，但后端已返回锁定版本 v${data.value.version}。`
      : `保存请求超时，但后端已落库为版本 v${data.value.version}。`
    toast.success(statusMessage.value)
    emit('saved')
    return true
  }
  if (action === 'lock' && data.value?.is_locked) {
    statusMessage.value = `锁定请求超时，但后端已锁定版本 v${data.value.version}。`
    toast.success(statusMessage.value)
    emit('locked')
    return true
  }
  return false
}

async function load() {
  if (!props.projectId || !props.characterId) return
  loading.value = true
  resetDraft()
  try {
    const { data: row } = await characterVisualApi.byCharacter(props.projectId, props.characterId)
    data.value = row
    visualText.value = { ...emptyVisualText(), ...row.visual_text }
    outfitVariants.value = row.outfit_variants || []
    negativePrompt.value = row.negative_prompt || ''
    statusMessage.value = row.is_locked ? `已加载锁定版本 v${row.version}` : `已加载草稿版本 v${row.version}`
  } catch (e: any) {
    if (e?.response?.status === 404) {
      resetDraft()
      statusMessage.value = '当前角色还没有视觉档案，可以点击 AI 生成后保存档案。'
    } else {
      const message = accessStatusMessage(e) || '加载视觉档案失败，请稍后重试。'
      statusMessage.value = message
      toast.error(message)
    }
  } finally {
    loading.value = false
  }
}

async function aiGenerate() {
  generating.value = true
  statusMessage.value = '正在生成角色视觉档案...'
  try {
    const { data: r } = await characterVisualApi.generate({
      project_id: props.projectId,
      character_id: props.characterId,
      character_name: props.characterName,
      narrative_profile: props.narrativeProfile || '',
      genre: props.genre || '',
      style_mode: props.styleMode || 'realistic',
    })
    if (r?.ok && r.visual_text) {
      visualText.value = { ...emptyVisualText(), ...visualText.value, ...r.visual_text }
      const message = r.backend === 'fallback'
        ? 'AI 暂不可用，已生成本地视觉档案草稿，请审阅后点击保存档案。'
        : '已通过 AI 模型生成视觉档案草稿，请审阅后点击保存档案。'
      statusMessage.value = message
      toast.success(message)
    } else {
      statusMessage.value = 'AI 没有返回可用内容，请稍后重试。'
      toast.error('AI 没有返回可用内容')
    }
  } catch (e: any) {
    statusMessage.value = accessStatusMessage(e) || 'AI 生成失败，请检查账号权限或 AI 配置。'
    notifyApiError(toast.error, e, 'AI 生成失败')
  } finally {
    generating.value = false
  }
}

async function save() {
  if (isLocked.value) {
    toast.error('已锁定，请先解锁再修改')
    return
  }
  saving.value = true
  try {
    const { data: row } = await characterVisualApi.upsert({
      project_id: props.projectId,
      payload: {
        character_id: props.characterId,
        character_name: props.characterName,
        visual_text: visualText.value,
        outfit_variants: outfitVariants.value,
        negative_prompt: negativePrompt.value,
        reference_images: data.value?.reference_images || [],
      },
    })
    data.value = row
    statusMessage.value = `保存成功，当前视觉档案版本 v${row.version}`
    if (row.shots_marked_stale) {
      toast.warning(`已标记 ${row.shots_marked_stale} 个镜头需重新编译提示词`)
    } else {
      toast.success('视觉档案保存成功')
    }
    emit('saved')
  } catch (e: any) {
    if (isRequestTimeout(e) && await recoverAfterTimeout('save')) return
    statusMessage.value = visualOperationMessage(e, '保存档案失败，请稍后重试。')
    notifyApiError(toast.error, e, '保存失败')
  } finally {
    saving.value = false
  }
}

async function lock() {
  locking.value = true
  try {
    if (!data.value) {
      const message = hasDraftContent.value
        ? '请先点击“保存档案”，保存成功后再锁定视觉档案。'
        : '当前角色还没有视觉档案，请先生成或填写后保存。'
      statusMessage.value = message
      toast.warning(message)
      return
    }
    const { data: r } = await characterVisualApi.lock({
      project_id: props.projectId,
      character_id: props.characterId,
    })
    if (r?.ok) {
      toast.success('已锁定，可用于分镜生成')
      await load()
      emit('locked')
    }
  } catch (e: any) {
    if (isRequestTimeout(e) && await recoverAfterTimeout('lock')) return
    statusMessage.value = visualOperationMessage(e, '锁定失败，请先确认档案已经保存。')
    notifyApiError(toast.error, e, '锁定失败')
  } finally {
    locking.value = false
  }
}

async function unlock() {
  if (!confirm('解锁会标记所有引用此角色的镜头为「需重新编译」，确认继续？')) return
  locking.value = true
  try {
    const { data: r } = await characterVisualApi.unlock({
      project_id: props.projectId,
      character_id: props.characterId,
    })
    if (r?.ok) {
      const n = r.shots_marked_stale ?? 0
      toast.success(`已解锁，标记 ${n} 个镜头待重新编译`)
      await load()
      emit('unlocked')
    }
  } catch (e: any) {
    notifyApiError(toast.error, e, '解锁失败')
  } finally {
    locking.value = false
  }
}

function addOutfit() {
  outfitVariants.value.push({
    id: 'of_' + Math.random().toString(36).slice(2, 8),
    scene: '',
    desc: '',
  })
}

function removeOutfit(idx: number) {
  outfitVariants.value.splice(idx, 1)
}

watch(() => [props.projectId, props.characterId], () => load(), { immediate: true })
</script>

<template>
  <div class="space-y-4">
    <!-- 顶部状态条 -->
    <div class="flex flex-col gap-3 xl:flex-row xl:items-center xl:justify-between">
      <div class="min-w-0 flex items-center gap-2">
        <h3 class="min-w-0 break-words text-base font-semibold leading-tight">{{ characterName }} · 视觉档案</h3>
        <Badge v-if="isLocked" class="bg-emerald-500 text-white">
          <Lock class="h-3 w-3 mr-1" /> 已锁定 v{{ data?.version }}
        </Badge>
        <Badge v-else variant="outline">未锁定</Badge>
      </div>
      <div class="flex flex-wrap items-center justify-end gap-2">
        <Button v-if="!isLocked" size="sm" variant="outline" :disabled="generating"
                @click="aiGenerate">
          <Sparkles class="h-3.5 w-3.5 mr-1" />
          {{ generating ? 'AI 生成中...' : 'AI 生成' }}
        </Button>
        <Button v-if="!isLocked" size="sm" :disabled="saving" @click="save">
          <Save class="h-3.5 w-3.5 mr-1" /> {{ saving ? '保存档案中...' : '保存档案' }}
        </Button>
        <Button v-if="!isLocked" size="sm" variant="default"
                class="bg-emerald-600 hover:bg-emerald-700" :disabled="locking" @click="lock">
          <Lock class="h-3.5 w-3.5 mr-1" /> {{ locking ? '锁定中...' : '锁定' }}
        </Button>
        <Button v-else size="sm" variant="outline" :disabled="locking" @click="unlock">
          <Unlock class="h-3.5 w-3.5 mr-1" /> 解锁
        </Button>
        <Button size="icon" variant="ghost" class="h-8 w-8" title="关闭视觉档案" @click="emit('close')">
          <X class="h-4 w-4" />
        </Button>
      </div>
    </div>

    <div
      v-if="statusMessage"
      aria-live="polite"
      class="rounded-md border border-primary/20 bg-primary/5 px-3 py-2 text-xs text-primary"
    >
      {{ statusMessage }}
    </div>

    <!-- 视觉文本字段 -->
    <div class="grid grid-cols-2 gap-3">
      <div v-for="(label, key) in FIELD_LABELS" :key="key" class="space-y-1">
        <label class="text-xs text-muted-foreground">{{ label }}</label>
        <Input v-model="visualText[key as keyof CharacterVisualText]"
               :disabled="isLocked"
               :placeholder="'例：' + label" />
      </div>
    </div>

    <!-- 服装变体 -->
    <div class="space-y-2">
      <div class="flex items-center justify-between">
        <label class="text-xs font-medium text-muted-foreground">服装变体（场景特定服装）</label>
        <Button size="sm" variant="ghost" :disabled="isLocked" @click="addOutfit">
          <Plus class="h-3.5 w-3.5" />
        </Button>
      </div>
      <div v-for="(v, idx) in outfitVariants" :key="v.id" class="flex items-center gap-2">
        <Input v-model="v.scene" placeholder="场景（如：职场）" :disabled="isLocked" class="w-32" />
        <Input v-model="v.desc" placeholder="服装描述" :disabled="isLocked" class="flex-1" />
        <Button size="icon" variant="ghost" :disabled="isLocked" @click="removeOutfit(idx)">
          <Trash2 class="h-3.5 w-3.5 text-destructive" />
        </Button>
      </div>
    </div>

    <!-- 负面词 -->
    <div class="space-y-1">
      <label class="text-xs text-muted-foreground">角色级负面词（用顿号或逗号分隔）</label>
      <Textarea v-model="negativePrompt" :disabled="isLocked" :rows="2"
                placeholder="例：双下巴，刘海过厚，塌鼻梁" />
    </div>

    <!-- 平台接入提示 -->
    <div class="p-3 rounded-md bg-muted/50 text-xs text-muted-foreground space-y-1">
      <div class="font-medium text-foreground">角色视觉档案用途</div>
      <div>• 作为分镜提示词的人物外观基准</div>
      <div>• 后续如接入外部平台 API，可直接复用这些固定描述</div>
    </div>
  </div>
</template>
