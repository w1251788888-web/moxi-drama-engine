// 故事状态卡 / 工作流上下文 的自动持久化 composable。
//
// 从 ProjectWorkspaceView 抽出。原因：
// - 这两条 watch（storyStateCards 800ms / workflow+canon+memory 1000ms）
//   纯粹是"哪个 ref 变了就 debounce 写库"的副作用，
//   留在 3000 行的 View 里只会让人误以为它们和别的逻辑有耦合
// - 单独成一个 composable 后，Tab 卸载时能在 onUnmounted 里清掉 timer，
//   不会出现"离开页面后还在偷偷写库"
//
// 调用方只要透传 refs + 一个 saver，watcher 就接管掉 debounce/失败容忍。

import { onUnmounted, watch, type Ref } from 'vue'
import { projectsV2Api } from '@/api/client'
import type { StoryStateCardStore, WorkflowContext } from '@/features/workspace/utils/workflowState'
import { saveWorkspaceStorage } from '@/features/workspace/utils/workspaceStorage'
import { createAutosaveExclusiveGate } from '@/features/workspace/utils/storyStateAutosaveCoordinator'

interface UseStoryStateAutosaveOptions {
  projectId: Ref<string>
  // 项目尚未加载完时，watcher 不能写库（否则会把空白 stub 推上去覆盖真实数据）
  isReady: Ref<boolean>

  storyStateCards: Ref<StoryStateCardStore>
  workflowContext: Ref<WorkflowContext>
  canonPacket: Ref<Record<string, any>>
  episodeMemoryCards: Ref<Array<Record<string, any>>>

  // 工作流上下文写库的真实实现：留给调用方注入，
  // 这样 composable 不感知 saveWorkflowContext 的高级语义（merge / response apply）
  syncWorkflowContext: (options?: { silent?: boolean }) => Promise<boolean | void> | boolean | void
}

export function useStoryStateAutosave(opts: UseStoryStateAutosaveOptions) {
  let _stateCardsTimer: ReturnType<typeof setTimeout> | null = null
  let _workflowTimer: ReturnType<typeof setTimeout> | null = null
  let _disposed = false
  const gate = createAutosaveExclusiveGate()

  const _scheduleStateCardsSave = (value: StoryStateCardStore) => {
    if (_disposed) return
    if (gate.isExclusive()) {
      gate.defer('stateCards', () => _scheduleStateCardsSave(opts.storyStateCards.value))
      return
    }
    if (_stateCardsTimer) clearTimeout(_stateCardsTimer)
    _stateCardsTimer = setTimeout(() => {
      _stateCardsTimer = null
      gate.clearPending('stateCards')
      const save = (async () => {
        try {
          saveWorkspaceStorage('stateCards', opts.projectId.value, JSON.stringify(value))
        } catch { /* localStorage 满了不影响内存编辑 */ }
        if (!opts.isReady.value) return
        try {
          await projectsV2Api.saveStateCards(opts.projectId.value, value as any)
        } catch { /* 网络抖动不打断编辑 */ }
      })()
      void gate.track(save)
    }, 800)
    gate.registerPending(
      'stateCards',
      () => {
        if (_stateCardsTimer) clearTimeout(_stateCardsTimer)
        _stateCardsTimer = null
      },
      () => _scheduleStateCardsSave(opts.storyStateCards.value),
    )
  }

  const _scheduleWorkflowSave = () => {
    if (_disposed) return
    if (gate.isExclusive()) {
      gate.defer('workflow', _scheduleWorkflowSave)
      return
    }
    if (_workflowTimer) clearTimeout(_workflowTimer)
    _workflowTimer = setTimeout(() => {
      _workflowTimer = null
      gate.clearPending('workflow')
      const save = Promise.resolve(opts.syncWorkflowContext({ silent: true }))
      void gate.track(save)
    }, 1000)
    gate.registerPending(
      'workflow',
      () => {
        if (_workflowTimer) clearTimeout(_workflowTimer)
        _workflowTimer = null
      },
      _scheduleWorkflowSave,
    )
  }

  // 状态卡：localStorage + 后端共用一个 800ms debounce
  // 把每次 deep 触发就 JSON.stringify 的负担降到 800ms 最多一次
  watch(opts.storyStateCards, (value) => {
    _scheduleStateCardsSave(value)
  }, { deep: true })

  // 工作流上下文：1000ms debounce
  watch(
    [opts.workflowContext, opts.canonPacket, opts.episodeMemoryCards],
    () => {
      if (!opts.isReady.value) return
      _scheduleWorkflowSave()
    },
    { deep: true },
  )

  // 卸载时清掉未结算的 timer，避免离开页面后还在写库
  onUnmounted(() => {
    _disposed = true
    if (_stateCardsTimer) { clearTimeout(_stateCardsTimer); _stateCardsTimer = null }
    if (_workflowTimer) { clearTimeout(_workflowTimer); _workflowTimer = null }
  })

  return {
    runExclusive: gate.runExclusive,
  }
}
