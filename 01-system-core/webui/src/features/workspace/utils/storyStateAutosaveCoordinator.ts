export interface AutosaveExclusiveGate {
  isExclusive: () => boolean
  track: <T>(promise: Promise<T>) => Promise<T>
  defer: (key: string, resume: () => void) => void
  registerPending: (key: string, cancel: () => void, resume: () => void) => void
  clearPending: (key: string) => void
  runExclusive: <T>(work: () => Promise<T>) => Promise<T>
}

interface PendingAutosave {
  cancel: () => void
  resume: () => void
}

/**
 * 直接保存与 debounce 自动保存共用的事务闸门。
 *
 * 进入事务时会取消尚未启动的 timer，等待已经发出的写库完成；事务期间
 * 新触发的自动保存只记为一次待恢复任务，等直接保存结束后再启动。
 */
export function createAutosaveExclusiveGate(): AutosaveExclusiveGate {
  let exclusiveDepth = 0
  let transactionTail: Promise<void> = Promise.resolve()
  const inFlight = new Set<Promise<unknown>>()
  const pending = new Map<string, PendingAutosave>()
  const deferred = new Map<string, () => void>()

  const track = <T>(promise: Promise<T>): Promise<T> => {
    const tracked = Promise.resolve(promise)
    inFlight.add(tracked)
    void tracked.then(
      () => inFlight.delete(tracked),
      () => inFlight.delete(tracked),
    )
    return tracked
  }

  const waitForInFlight = async () => {
    while (inFlight.size) {
      await Promise.allSettled(Array.from(inFlight))
    }
  }

  return {
    isExclusive: () => exclusiveDepth > 0,
    track,
    defer(key, resume) {
      deferred.set(key, resume)
    },
    registerPending(key, cancel, resume) {
      const previous = pending.get(key)
      previous?.cancel()
      pending.set(key, { cancel, resume })
    },
    clearPending(key) {
      pending.delete(key)
    },
    async runExclusive<T>(work: () => Promise<T>): Promise<T> {
      const previousTransaction = transactionTail
      let releaseTransaction = () => {}
      transactionTail = new Promise<void>(resolve => { releaseTransaction = resolve })
      await previousTransaction
      exclusiveDepth = 1
      for (const [key, task] of pending.entries()) {
        try { task.cancel() } catch { /* 一个 timer 的清理失败不能打破保存队列 */ }
        deferred.set(key, task.resume)
      }
      pending.clear()
      await waitForInFlight()
      try {
        return await work()
      } finally {
        exclusiveDepth = 0
        const resumes = Array.from(deferred.values())
        deferred.clear()
        releaseTransaction()
        for (const resume of resumes) {
          try { resume() } catch { /* 恢复一次 autosave 失败不影响后续直接保存事务 */ }
        }
      }
    },
  }
}
