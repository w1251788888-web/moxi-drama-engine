// 剧本写作 Tab 的集 / 场 / 内容 / 缓存 / 自动保存 一站式状态。
//
// 从 ProjectWorkspaceView 抽出。目的：
// 1. 让 ProjectWorkspaceView 不再直接管理 12+ ref 和 8+ async 函数
// 2. 集切换的"内存缓存 + 邻集预热 + 防竞态"逻辑统一在这一个 composable
// 3. autosave 的"内容脏标记 + 失败 404 重建场"也封死在这里
// 4. 未来要换持久化方式（IndexedDB？）只改这一个文件
//
// 调用方需要传入：
// - projectId: 当前项目 id（响应式）
// - syncWorkflowContext: 保存成功后回调，给 ProjectWorkspaceView 同步 workflow
// - resetSegments: 切集时调用（清掉内部四段审阅状态）
// - closeSegmentPanel: 切集时调用（关闭分段面板）
//
// 返回的 refs 用 spread 解构后透传给 sidebar / editor 即可。

import { onUnmounted, ref, type ComputedRef, type Ref } from 'vue'
import { projectsV2Api } from '@/api/client'

interface UseEpisodeScenesOptions {
  projectId: ComputedRef<string>
  syncWorkflowContext: () => Promise<boolean | void> | boolean | void
  resetSegments: () => void
  closeSegmentPanel: () => void
}

const MAX_SCENE_CACHE_EPISODES = 24

export function useEpisodeScenes(opts: UseEpisodeScenesOptions) {
  const episodes: Ref<any[]> = ref([])
  const selectedEpisode = ref(1)
  const scenes: Ref<any[]> = ref([])
  const selectedScene = ref(1)
  const sceneContent = ref('')
  const isHydratingSceneContent = ref(false)
  const scenesLoading = ref(false)

  // 缓存：同项目内已打开的集的 scenes 数据（按 episode_number 索引）。
  // 组件 unmount 时随 composable 释放，不跨项目串数据。
  const _scenesByEpCache = new Map<number, any[]>()
  const _scenesPrefetchInFlight = new Set<number>()
  const _scenesRefreshInFlight = new Set<number>()
  // 防竞态 token：每次切集递增；旧响应回包时 token 已变就丢弃
  let _loadScenesToken = 0
  let _activeLoadScenesController: AbortController | null = null
  let _disposed = false
  // 脏标记：autosave 只在内容真正变过时才写库
  const _lastSavedSceneContent = ref('')

  function trimScenesCache() {
    while (_scenesByEpCache.size > MAX_SCENE_CACHE_EPISODES) {
      const candidate = [..._scenesByEpCache.keys()].find((epNum) =>
        epNum !== selectedEpisode.value && !_scenesPrefetchInFlight.has(epNum),
      )
      const epNum = candidate ?? _scenesByEpCache.keys().next().value
      if (epNum == null) break
      _scenesByEpCache.delete(epNum)
    }
  }

  function rememberScenes(epNum: number, data: any[]) {
    _scenesByEpCache.delete(epNum)
    _scenesByEpCache.set(epNum, data)
    trimScenesCache()
  }

  function markSceneContentClean(content: string) {
    _lastSavedSceneContent.value = content
  }

  function hasUnsavedSceneChanges() {
    return sceneContent.value !== _lastSavedSceneContent.value
  }

  function applyScenesData(epNum: number, data: any[]) {
    if (_disposed) return
    isHydratingSceneContent.value = true
    try {
      scenes.value = data
      if (data.length > 0) {
        // 优先选第一个有内容的场（历史项目里 scene1 可能是空白预留场）
        const firstWithContent = data.find((s: any) => (s.content || '').trim().length > 0)
        const target = firstWithContent || data[0]
        selectedScene.value = target.scene_number
        sceneContent.value = target.content || ''
        markSceneContentClean(sceneContent.value)
      } else {
        selectedScene.value = 1
        sceneContent.value = ''
        markSceneContentClean('')
      }
      rememberScenes(epNum, data)
    } finally {
      queueMicrotask(() => {
        if (!_disposed) isHydratingSceneContent.value = false
      })
    }
  }

  function invalidateScenesCache(epNum?: number) {
    if (epNum == null) _scenesByEpCache.clear()
    else _scenesByEpCache.delete(epNum)
  }

  async function refreshScenesInBackground(epNum: number, expectedToken: number) {
    if (_disposed || _scenesRefreshInFlight.has(epNum)) return
    _scenesRefreshInFlight.add(epNum)
    try {
      const { data } = await projectsV2Api.listScenes(opts.projectId.value, epNum)
      if (_disposed) return
      if (expectedToken !== _loadScenesToken) {
        rememberScenes(epNum, data)
        return
      }
      const current = _scenesByEpCache.get(epNum)
      const sameLen = Array.isArray(current) && current.length === data.length
      const sameContent = sameLen && current!.every((s, i) =>
        (s?.scene_number === data[i]?.scene_number) &&
        ((s?.content || '') === (data[i]?.content || ''))
      )
      if (!sameContent) {
        rememberScenes(epNum, data)
        scenes.value = data
      }
    } catch { /* 静默 */ }
    finally {
      _scenesRefreshInFlight.delete(epNum)
    }
  }

  async function prefetchAdjacentScenes(currentEp: number, radius = 2) {
    const targets: number[] = []
    for (let offset = 1; offset <= radius; offset++) {
      targets.push(currentEp - offset, currentEp + offset)
    }
    await prefetchScenesBatch(targets)
  }

  async function prefetchScenesBatch(epNums: number[]) {
    const validEpisodeNumbers = new Set(
      episodes.value.map((episode: any) => Number(episode?.episode_number)).filter(Number.isFinite),
    )
    const targets: number[] = []
    for (const epNum of epNums) {
      if (!Number.isFinite(epNum) || epNum <= 0) continue
      if (_scenesByEpCache.has(epNum)) continue
      if (_scenesPrefetchInFlight.has(epNum)) continue
      if (!validEpisodeNumbers.has(epNum)) continue
      if (targets.includes(epNum)) continue
      targets.push(epNum)
      if (targets.length >= 20) break
    }
    if (targets.length === 0) return

    targets.forEach(epNum => _scenesPrefetchInFlight.add(epNum))
    try {
      const { data } = await projectsV2Api.listScenesBatch(opts.projectId.value, targets)
      if (_disposed) return
      for (const epNum of targets) {
        const scenesForEpisode = data?.[String(epNum)]
        rememberScenes(epNum, Array.isArray(scenesForEpisode) ? scenesForEpisode : [])
      }
    } catch {
      // 兼容旧后端或批量接口临时失败：退回有界单集预热，不影响当前编辑。
      for (const epNum of targets) {
        if (_scenesByEpCache.has(epNum)) continue
        try {
          const { data } = await projectsV2Api.listScenes(opts.projectId.value, epNum)
          if (_disposed) return
          rememberScenes(epNum, data)
        } catch { /* 静默 */ }
      }
    } finally {
      targets.forEach(epNum => _scenesPrefetchInFlight.delete(epNum))
    }
  }

  // 有界后台预热：只预热前几集，避免长剧本打开时持续占用后端和 SQLite。
  let _prefetchAllPending = false
  async function prefetchInitialScenes(limit = 3) {
    if (_prefetchAllPending) return
    _prefetchAllPending = true
    try {
      const list = episodes.value.slice(0, limit) // 快照，期间不受变更影响
      await prefetchScenesBatch(list.map((ep: any) => Number(ep?.episode_number)))
    } finally {
      _prefetchAllPending = false
    }
  }

  async function autoSaveCurrentScene() {
    const snapshotEp = selectedEpisode.value
    const snapshotScene = selectedScene.value
    const snapshotContent = sceneContent.value
    if (!snapshotContent.trim()) return
    if (snapshotContent === _lastSavedSceneContent.value) return

    const doSave = async () => {
      await projectsV2Api.saveSceneContent(
        opts.projectId.value,
        snapshotEp,
        snapshotScene,
        { content: snapshotContent },
      )
    }
    try {
      await doSave()
      _lastSavedSceneContent.value = snapshotContent
      invalidateScenesCache(snapshotEp)
      void refreshEpisodesSilently()
      await opts.syncWorkflowContext()
    } catch (e: any) {
      if (e?.response?.status === 404) {
        try {
          await projectsV2Api.createScene(opts.projectId.value, snapshotEp, {
            time: '',
            location_type: 'INT',
            location_name: '待填写',
            content: '',
          })
          if (selectedEpisode.value === snapshotEp) {
            const { data } = await projectsV2Api.listScenes(opts.projectId.value, snapshotEp)
            scenes.value = data
            if (data.length > 0 && data[0]) selectedScene.value = data[0].scene_number
          }
          await doSave()
          _lastSavedSceneContent.value = snapshotContent
          await opts.syncWorkflowContext()
        } catch { /* 静默 */ }
      }
      /* 其他错误静默失败，不阻塞切换流程 */
    }
  }

  async function loadScenes(epNum: number) {
    const token = ++_loadScenesToken
    _activeLoadScenesController?.abort()
    _activeLoadScenesController = null
    void autoSaveCurrentScene()

    selectedEpisode.value = epNum
    opts.resetSegments()
    opts.closeSegmentPanel()

    const cached = _scenesByEpCache.get(epNum)
    if (cached) {
      applyScenesData(epNum, cached)
      scenesLoading.value = false
      void refreshScenesInBackground(epNum, token)
      void prefetchAdjacentScenes(epNum)
      return
    }

    // 缓存未命中：保留上一集的内容显示 + loading 角标，避免"白屏一闪"。
    // 等真实数据回来再 applyScenesData 替换，token 守竞态。
    const controller = new AbortController()
    _activeLoadScenesController = controller
    scenesLoading.value = true

    try {
      const { data } = await projectsV2Api.listScenes(opts.projectId.value, epNum, { signal: controller.signal })
      if (_disposed || controller.signal.aborted || token !== _loadScenesToken) return
      applyScenesData(epNum, data)
      void prefetchAdjacentScenes(epNum)
    } catch {
      // 网络/404：保持已清空状态
    } finally {
      if (_activeLoadScenesController === controller) {
        _activeLoadScenesController = null
      }
      if (!_disposed && token === _loadScenesToken) scenesLoading.value = false
    }
  }

  async function loadEpisodes() {
    try {
      const { data } = await projectsV2Api.listEpisodes(opts.projectId.value)
      if (_disposed) return
      episodes.value = data
      if (episodes.value.length > 0 && scenes.value.length === 0) {
        await loadScenes(episodes.value[0].episode_number)
      }
      void prefetchInitialScenes()
    } catch { /* 静默 */ }
  }

  // 仅刷新 episodes 列表，不触发 loadScenes（避免把用户从当前集踢回 ep1）
  async function refreshEpisodesSilently() {
    try {
      const { data } = await projectsV2Api.listEpisodes(opts.projectId.value)
      if (_disposed) return
      episodes.value = data
    } catch { /* 静默 */ }
  }

  onUnmounted(() => {
    _disposed = true
    _activeLoadScenesController?.abort()
    _activeLoadScenesController = null
    _scenesPrefetchInFlight.clear()
    _scenesRefreshInFlight.clear()
  })

  return {
    // refs（透传给子组件）
    episodes,
    selectedEpisode,
    scenes,
    selectedScene,
    sceneContent,
    lastSavedSceneContent: _lastSavedSceneContent,
    isHydratingSceneContent,
    scenesLoading,
    // 函数（保存 / 切集 / 缓存）
    loadScenes,
    loadEpisodes,
    refreshEpisodesSilently,
    autoSaveCurrentScene,
    invalidateScenesCache,
    markSceneContentClean,
    hasUnsavedSceneChanges,
  }
}
