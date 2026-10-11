<script setup lang="ts">
import { ref, watch, computed } from 'vue'
import { notifyApiError } from '@/api/http'
import { CheckCircle2, AlertTriangle, Lock, Unlock } from 'lucide-vue-next'
import { Button } from '@/components/ui/button'
import { toast } from 'vue-sonner'
import { scriptConfirmApi } from '@/api/client'

interface Props {
  projectId: string
  sessionId?: string
  episode: number
  /** 角色名 -> character_id 字典，便于 RAPTOR 检索元数据 */
  characterNameToId?: Record<string, string>
  /** 当前剧本是否有内容（空时按钮 disabled） */
  hasContent?: boolean
}

const props = withDefaults(defineProps<Props>(), {
  hasContent: true,
  sessionId: '',
  characterNameToId: () => ({}),
})

const emit = defineEmits<{ (e: 'confirmed'): void; (e: 'unconfirmed'): void }>()

const status = ref<'no_script' | 'draft' | 'confirmed' | 'stale' | 'loading'>('loading')
const confirmedAt = ref<string | null>(null)
const confirmedVersion = ref('')
const busy = ref(false)

const sessionId = computed(() => props.sessionId || props.projectId)

async function refresh() {
  if (!sessionId.value) {
    status.value = 'no_script'
    return
  }
  try {
    const { data } = await scriptConfirmApi.status({
      session_id: sessionId.value,
      episode: props.episode,
    })
    status.value = data.status
    confirmedAt.value = data.confirmed_at || null
    confirmedVersion.value = data.confirmed_version || ''
  } catch {
    status.value = 'no_script'
  }
}

async function doConfirm() {
  busy.value = true
  try {
    const { data } = await scriptConfirmApi.confirm({
      session_id: sessionId.value,
      episode: props.episode,
      project_id: props.projectId,
      character_name_to_id: props.characterNameToId || {},
    })
    if ((data as any).ok ?? true) {
      toast.success(`已确认 v${(data as any).version_number}，创作状态已更新`)
      emit('confirmed')
      await refresh()
    }
  } catch (e: any) {
    notifyApiError(toast.error, e, '确认失败')
  } finally {
    busy.value = false
  }
}

async function doUnconfirm() {
  if (!confirm('撤销确认会同步清理本集确认记录，确认继续？')) return
  busy.value = true
  try {
    await scriptConfirmApi.unconfirm({
      session_id: sessionId.value,
      episode: props.episode,
      project_id: props.projectId,
    })
    toast.success('已撤销确认')
    emit('unconfirmed')
    await refresh()
  } catch (e: any) {
    notifyApiError(toast.error, e, '撤销失败')
  } finally {
    busy.value = false
  }
}

watch(() => [props.projectId, props.episode, sessionId.value], () => refresh(), { immediate: true })
defineExpose({ refresh })
</script>

<template>
  <div class="inline-flex items-center gap-2">
    <!-- 已确认 -->
    <Button v-if="status === 'confirmed'" size="sm" variant="outline"
            class="border-emerald-500 text-emerald-700 dark:text-emerald-400"
            :disabled="busy" @click="doUnconfirm">
      <CheckCircle2 class="h-3.5 w-3.5 mr-1" />
      已确认 v{{ confirmedVersion }}
      <span class="text-xs opacity-60 ml-1">点击撤销</span>
    </Button>

    <!-- 已修改（stale）-->
    <Button v-else-if="status === 'stale'" size="sm" variant="default"
            class="bg-amber-500 hover:bg-amber-600 text-white"
            :disabled="busy || !hasContent" @click="doConfirm">
      <AlertTriangle class="h-3.5 w-3.5 mr-1" />
      内容已修改，重新确认
    </Button>

    <!-- 草稿 -->
    <Button v-else-if="status === 'draft'" size="sm" variant="default"
            :disabled="busy || !hasContent" @click="doConfirm">
      <Lock class="h-3.5 w-3.5 mr-1" />
      {{ busy ? '确认中...' : '确认保存' }}
    </Button>

    <!-- 无剧本 -->
    <Button v-else size="sm" variant="outline" disabled>
      <Lock class="h-3.5 w-3.5 mr-1" />
      请先编写剧本
    </Button>
  </div>
</template>
