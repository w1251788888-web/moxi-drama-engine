import assert from 'node:assert/strict'
import { createRequire } from 'node:module'
import path from 'node:path'
import test from 'node:test'

const require = createRequire(import.meta.url)
const webuiRoot = path.resolve(import.meta.dirname, '..')
const createJiti = require(require.resolve('jiti'))
const jiti = createJiti(import.meta.url, { interopDefault: false, moduleCache: false, fsCache: false })
const { createAutosaveExclusiveGate } = jiti(path.join(
  webuiRoot,
  'src/features/workspace/utils/storyStateAutosaveCoordinator.ts',
))

test('直接保存事务先等待在途 autosave，事务内的新 autosave 延后且不并发', async () => {
  const gate = createAutosaveExclusiveGate()
  const events = []
  let finishSlow
  const slowAutosave = new Promise(resolve => { finishSlow = resolve })
  gate.track(slowAutosave.then(() => events.push('slow:end')))
  events.push('slow:start')

  const transaction = gate.runExclusive(async () => {
    events.push('direct:start')
    gate.defer('workflow', () => events.push('deferred:autosave'))
    assert.equal(events.includes('deferred:autosave'), false)
    events.push('direct:end')
  })
  await Promise.resolve()
  assert.equal(events.includes('direct:start'), false, 'direct 必须等待慢 autosave')
  finishSlow()
  await transaction
  assert.deepEqual(events, ['slow:start', 'slow:end', 'direct:start', 'direct:end', 'deferred:autosave'])
})

test('进入事务会取消待执行 timer，并在事务结束后恢复一次', async () => {
  const gate = createAutosaveExclusiveGate()
  const events = []
  gate.registerPending('workflow', () => events.push('timer:cancel'), () => events.push('timer:resume'))
  await gate.runExclusive(async () => events.push('direct'))
  assert.deepEqual(events, ['timer:cancel', 'direct', 'timer:resume'])
})

test('两个直接保存事务本身也严格串行', async () => {
  const gate = createAutosaveExclusiveGate()
  const events = []
  let releaseFirst
  const first = gate.runExclusive(async () => {
    events.push('first:start')
    await new Promise(resolve => { releaseFirst = resolve })
    events.push('first:end')
  })
  await Promise.resolve()
  const second = gate.runExclusive(async () => events.push('second'))
  await Promise.resolve()
  assert.deepEqual(events, ['first:start'])
  releaseFirst()
  await Promise.all([first, second])
  assert.deepEqual(events, ['first:start', 'first:end', 'second'])
})
