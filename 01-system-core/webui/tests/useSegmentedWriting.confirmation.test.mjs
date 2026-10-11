import assert from 'node:assert/strict'
import { createRequire } from 'node:module'
import fs from 'node:fs'
import path from 'node:path'
import test from 'node:test'
import vm from 'node:vm'

const require = createRequire(import.meta.url)
const webuiRoot = path.resolve(import.meta.dirname, '..')
const sourcePath = path.join(
  webuiRoot,
  'src/features/workspace/composables/useSegmentedWriting.ts',
)

function loadTypescript() {
  try {
    return require('typescript')
  } catch {
    return require('typescript')
  }
}

function loadUseSegmentedWriting() {
  const ts = loadTypescript()
  let source = fs.readFileSync(sourcePath, 'utf8')
  source = source
    .replace(
      "import { computed, ref } from 'vue'\n",
      [
        "const ref = value => ({ value })",
        "const computed = getter => ({ get value() { return getter() } })",
        '',
      ].join('\n'),
    )
    .replace(
      "import { formatUserFacingErrorMessage } from '@/api/http'\n",
      "const formatUserFacingErrorMessage = error => String(error?.message || error || '')\n",
    )
    .replace(
      "import { formatRuleBackedScriptStreamError } from './useRuleBackedScriptStream'\n",
      "const formatRuleBackedScriptStreamError = error => ({ detail: String(error?.message || error || ''), subtype: '', retryable: false })\n",
    )

  const compiled = ts.transpileModule(source, {
    compilerOptions: {
      module: ts.ModuleKind.CommonJS,
      target: ts.ScriptTarget.ES2022,
    },
    fileName: sourcePath,
  }).outputText

  const module = { exports: {} }
  const context = vm.createContext({
    exports: module.exports,
    module,
    console,
    Promise,
    setTimeout,
    clearTimeout,
  })
  vm.runInContext(compiled, context, { filename: sourcePath })
  return module.exports.useSegmentedWriting
}

test('confirming a reviewing explosion candidate resumes generation at resolution', async () => {
  const useSegmentedWriting = loadUseSegmentedWriting()
  const streamCalls = []
  const warnings = []

  const segmented = useSegmentedWriting({
    approveSegment: async idx => idx !== 2,
    approveFullScript: async () => true,
    buildSegmentRequest: (step, confirmedContent) => ({
      segment_id: step.id,
      confirmedContent,
    }),
    streamSegment: async request => {
      streamCalls.push(request)
      return { content: 'RESOLUTION_SAFE_TEXT', warnings: [] }
    },
    afterSegmentConfirmed: async () => {},
    onSegmentDraftReady: async () => {},
    notify: {
      error: message => warnings.push(`error:${message}`),
      warning: message => warnings.push(`warning:${message}`),
      success: () => {},
    },
  })

  segmented.hydrateSegmentProgress({
    current_segment_idx: 2,
    show_panel: true,
    steps: [
      { id: 'hook', status: 'confirmed', editedContent: 'HOOK_SAFE_TEXT', versionA: 'HOOK_SAFE_TEXT' },
      { id: 'validation', status: 'confirmed', editedContent: 'VALIDATION_SAFE_TEXT', versionA: 'VALIDATION_SAFE_TEXT' },
      { id: 'explosion', status: 'reviewing', editedContent: 'EXPLOSION_SAFE_TEXT', versionA: 'EXPLOSION_SAFE_TEXT' },
      { id: 'resolution', status: 'pending', editedContent: '', versionA: '' },
    ],
  })

  await segmented.segmentConfirm(2)

  const steps = segmented.segmentSteps.value
  assert.equal(steps[2].status, 'confirmed')
  assert.equal(segmented.currentSegmentIdx.value, 3)
  assert.equal(streamCalls.length, 1)
  assert.equal(streamCalls[0].segment_id, 'resolution')
  assert.equal(steps[3].status, 'reviewing')
  assert.equal(steps[3].editedContent, 'RESOLUTION_SAFE_TEXT')
})

test('confirming an empty reviewing explosion candidate first restores backend candidate, then resumes resolution', async () => {
  const useSegmentedWriting = loadUseSegmentedWriting()
  const streamCalls = []
  const restoreCalls = []
  const draftReadySnapshots = []
  const confirmedSnapshots = []

  const segmented = useSegmentedWriting({
    approveSegment: async idx => idx !== 2,
    approveFullScript: async () => true,
    buildSegmentRequest: (step, confirmedContent) => ({
      segment_id: step.id,
      confirmedContent,
    }),
    streamSegment: async request => {
      streamCalls.push(request)
      return { content: 'RESOLUTION_SAFE_TEXT', warnings: [] }
    },
    recoverLatestSegmentCandidate: async (idx, step) => {
      restoreCalls.push({ idx, stepId: step.id })
      return step.id === 'explosion'
        ? { content: 'EXPLOSION_SAFE_TEXT', warnings: [] }
        : null
    },
    afterSegmentConfirmed: async () => {
      confirmedSnapshots.push(segmented.segmentSteps.value.map(item => ({ id: item.id, status: item.status })))
    },
    onSegmentDraftReady: async () => {
      draftReadySnapshots.push(segmented.segmentSteps.value.map(item => ({ id: item.id, status: item.status })))
    },
    notify: {
      error: () => {},
      warning: () => {},
      success: () => {},
    },
  })

  segmented.hydrateSegmentProgress({
    current_segment_idx: 2,
    show_panel: true,
    steps: [
      { id: 'hook', status: 'confirmed', editedContent: 'HOOK_SAFE_TEXT', versionA: 'HOOK_SAFE_TEXT' },
      { id: 'validation', status: 'confirmed', editedContent: 'VALIDATION_SAFE_TEXT', versionA: 'VALIDATION_SAFE_TEXT' },
      { id: 'explosion', status: 'reviewing', editedContent: '', versionA: '' },
      { id: 'resolution', status: 'pending', editedContent: '', versionA: '' },
    ],
  })

  await segmented.segmentConfirm(2)

  const steps = segmented.segmentSteps.value
  assert.equal(restoreCalls.length, 1)
  assert.equal(restoreCalls[0].idx, 2)
  assert.equal(restoreCalls[0].stepId, 'explosion')
  assert.equal(draftReadySnapshots.length, 2)
  assert.equal(
    draftReadySnapshots[0].find(item => item.id === 'explosion')?.status,
    'reviewing',
  )
  assert.equal(
    draftReadySnapshots[1].find(item => item.id === 'resolution')?.status,
    'reviewing',
  )
  assert.equal(confirmedSnapshots.length, 1)
  assert.equal(
    confirmedSnapshots[0].find(item => item.id === 'explosion')?.status,
    'confirmed',
  )
  assert.equal(steps[2].status, 'confirmed')
  assert.equal(steps[2].editedContent, 'EXPLOSION_SAFE_TEXT')
  assert.equal(segmented.currentSegmentIdx.value, 3)
  assert.equal(streamCalls.length, 1)
  assert.equal(streamCalls[0].segment_id, 'resolution')
  assert.equal(steps[3].status, 'reviewing')
  assert.equal(steps[3].editedContent, 'RESOLUTION_SAFE_TEXT')
})

test('confirming an empty reviewing validation candidate restores current candidate before continuing explosion', async () => {
  const useSegmentedWriting = loadUseSegmentedWriting()
  const streamCalls = []
  const restoreCalls = []
  const draftReadyCalls = []
  const confirmSequence = []

  const segmented = useSegmentedWriting({
    approveSegment: async idx => idx !== 1,
    approveFullScript: async () => true,
    buildSegmentRequest: (step, confirmedContent) => ({
      segment_id: step.id,
      confirmedContent,
    }),
    streamSegment: async request => {
      streamCalls.push(request)
      return { content: 'EXPLOSION_SAFE_TEXT', warnings: [] }
    },
    recoverLatestSegmentCandidate: async (idx, step) => {
      restoreCalls.push({ idx, stepId: step.id })
      return step.id === 'validation'
        ? { content: 'VALIDATION_SAFE_TEXT', warnings: [] }
        : null
    },
    onSegmentDraftReady: async (idx, content) => {
      draftReadyCalls.push({ idx, content })
      confirmSequence.push(`draft:${idx}`)
    },
    afterSegmentConfirmed: async () => {
      confirmSequence.push(`confirmed:${segmented.currentSegmentIdx.value}`)
    },
    notify: {
      error: () => {},
      warning: () => {},
      success: () => {},
    },
  })

  segmented.hydrateSegmentProgress({
    current_segment_idx: 1,
    show_panel: true,
    steps: [
      { id: 'hook', status: 'confirmed', editedContent: 'HOOK_SAFE_TEXT', versionA: 'HOOK_SAFE_TEXT' },
      { id: 'validation', status: 'reviewing', editedContent: '', versionA: '' },
      { id: 'explosion', status: 'pending', editedContent: '', versionA: '' },
      { id: 'resolution', status: 'pending', editedContent: '', versionA: '' },
    ],
  })

  await segmented.segmentConfirm(1)

  const steps = segmented.segmentSteps.value
  assert.equal(restoreCalls.length, 1)
  assert.deepEqual(restoreCalls[0], { idx: 1, stepId: 'validation' })
  assert.equal(draftReadyCalls.length, 2)
  assert.deepEqual(draftReadyCalls[0], { idx: 1, content: 'VALIDATION_SAFE_TEXT' })
  assert.deepEqual(draftReadyCalls[1], { idx: 2, content: 'EXPLOSION_SAFE_TEXT' })
  assert.deepEqual(confirmSequence, ['draft:1', 'confirmed:1', 'draft:2'])
  assert.equal(steps[1].status, 'confirmed')
  assert.equal(steps[1].editedContent, 'VALIDATION_SAFE_TEXT')
  assert.equal(segmented.currentSegmentIdx.value, 2)
  assert.equal(streamCalls.length, 1)
  assert.equal(streamCalls[0].segment_id, 'explosion')
  assert.equal(steps[2].status, 'reviewing')
  assert.equal(steps[2].editedContent, 'EXPLOSION_SAFE_TEXT')
})

test('confirming stale generating resolution restores backend candidate before completing episode', async () => {
  const useSegmentedWriting = loadUseSegmentedWriting()
  const restoreCalls = []
  const completionSnapshots = []
  const warnings = []

  const segmented = useSegmentedWriting({
    approveSegment: async () => true,
    approveFullScript: async () => true,
    buildSegmentRequest: step => ({
      segment_id: step.id,
    }),
    streamSegment: async () => {
      throw new Error('streamSegment must not be called when latest candidate is recoverable')
    },
    recoverLatestSegmentCandidate: async (idx, step) => {
      restoreCalls.push({ idx, stepId: step.id })
      return step.id === 'resolution'
        ? { content: 'RESOLUTION_SAFE_TEXT', warnings: [] }
        : null
    },
    afterSegmentConfirmed: async () => {
      completionSnapshots.push(segmented.segmentSteps.value.map(item => ({ id: item.id, status: item.status })))
    },
    onAllSegmentsComplete: async () => {
      completionSnapshots.push(segmented.segmentSteps.value.map(item => ({ id: item.id, status: item.status })))
    },
    notify: {
      error: message => warnings.push(`error:${message}`),
      warning: message => warnings.push(`warning:${message}`),
      success: () => {},
    },
  })

  segmented.hydrateSegmentProgress({
    current_segment_idx: 3,
    show_panel: true,
    steps: [
      { id: 'hook', status: 'confirmed', editedContent: 'HOOK_SAFE_TEXT', versionA: 'HOOK_SAFE_TEXT' },
      { id: 'validation', status: 'confirmed', editedContent: 'VALIDATION_SAFE_TEXT', versionA: 'VALIDATION_SAFE_TEXT' },
      { id: 'explosion', status: 'confirmed', editedContent: 'EXPLOSION_SAFE_TEXT', versionA: 'EXPLOSION_SAFE_TEXT' },
      { id: 'resolution', status: 'generating', editedContent: '', versionA: '' },
    ],
  })

  assert.equal(typeof segmented.recoverLatestCandidateForSegment, 'function')
  await segmented.recoverLatestCandidateForSegment(3)
  await segmented.segmentConfirm(3)

  const steps = segmented.segmentSteps.value
  assert.deepEqual(restoreCalls, [{ idx: 3, stepId: 'resolution' }])
  assert.equal(steps[3].status, 'confirmed')
  assert.equal(steps[3].editedContent, 'RESOLUTION_SAFE_TEXT')
  assert.equal(segmented.showSegmentPanel.value, false)
  assert.equal(segmented.currentSegmentIdx.value, 4)
  assert.equal(warnings.length, 0)
  assert.ok(
    completionSnapshots.some(snapshot => snapshot.every(item => item.status === 'confirmed')),
    'completion callbacks must see all four segments confirmed',
  )
})

test('source-prechecked segmented generation continues past duplicate local outline gate', async () => {
  const useSegmentedWriting = loadUseSegmentedWriting()
  const streamCalls = []
  let outlineGateCalls = 0

  const segmented = useSegmentedWriting({
    ensureOutlineGatePassed: () => {
      outlineGateCalls += 1
      return false
    },
    persistProjectRules: async () => true,
    approveSegment: async () => true,
    approveFullScript: async () => true,
    buildSegmentRequest: step => ({
      segment_id: step.id,
    }),
    streamSegment: async request => {
      streamCalls.push(request)
      return { content: 'HOOK_SAFE_TEXT', warnings: [] }
    },
    resolveFirstSegmentLengthPolicy: () => ({ min: 600, max: 900 }),
    notify: {
      error: () => {},
      warning: () => {},
      success: () => {},
    },
  })

  await segmented.generateSegmented({ sourcePrechecked: true })

  assert.equal(outlineGateCalls, 0)
  assert.equal(streamCalls.length, 1)
  assert.equal(streamCalls[0].segment_id, 'hook')
  assert.equal(segmented.segmentSteps.value[0].status, 'reviewing')
  assert.equal(segmented.segmentSteps.value[0].editedContent, 'HOOK_SAFE_TEXT')
})

test('source-prechecked segmented generation ignores stale editor draft full-script gate', async () => {
  const useSegmentedWriting = loadUseSegmentedWriting()
  const streamCalls = []
  let fullScriptApprovalCalls = 0

  const segmented = useSegmentedWriting({
    persistProjectRules: async () => true,
    approveSegment: async () => true,
    approveFullScript: async () => {
      fullScriptApprovalCalls += 1
      return false
    },
    getSceneContent: () => 'STALE_EDITOR_DRAFT_SAFE_TEXT',
    buildSegmentRequest: step => ({
      segment_id: step.id,
    }),
    streamSegment: async request => {
      streamCalls.push(request)
      return { content: 'HOOK_SAFE_TEXT', warnings: [] }
    },
    resolveFirstSegmentLengthPolicy: () => ({ min: 600, max: 900 }),
    notify: {
      error: () => {},
      warning: () => {},
      success: () => {},
    },
  })

  await segmented.generateSegmented({ sourcePrechecked: true })

  assert.equal(fullScriptApprovalCalls, 0)
  assert.equal(streamCalls.length, 1)
  assert.equal(streamCalls[0].segment_id, 'hook')
  assert.equal(segmented.segmentSteps.value[0].status, 'reviewing')
})

test('failed explosion generation exits generating state and keeps retry details visible', async () => {
  const useSegmentedWriting = loadUseSegmentedWriting()
  const errors = []
  const progressMessages = []

  const segmented = useSegmentedWriting({
    buildSegmentRequest: step => ({
      segment_id: step.id,
    }),
    streamSegment: async () => {
      throw new Error('SAFE_TEXT_GENERATION_FAILED')
    },
    onSegmentProgress: message => progressMessages.push(message),
    notify: {
      error: message => errors.push(message),
      warning: () => {},
      success: () => {},
    },
  })

  segmented.hydrateSegmentProgress({
    current_segment_idx: 2,
    show_panel: true,
    steps: [
      { id: 'hook', status: 'confirmed', editedContent: 'HOOK_SAFE_TEXT', versionA: 'HOOK_SAFE_TEXT' },
      { id: 'validation', status: 'confirmed', editedContent: 'VALIDATION_SAFE_TEXT', versionA: 'VALIDATION_SAFE_TEXT' },
      { id: 'explosion', status: 'pending', editedContent: '', versionA: '' },
      { id: 'resolution', status: 'pending', editedContent: '', versionA: '' },
    ],
  })

  await segmented.resumeSegmentedProgress()

  const steps = segmented.segmentSteps.value
  assert.equal(steps[2].status, 'error')
  assert.equal(segmented.isSegmentGenerating.value, false)
  assert.equal(steps[2].editedContent, '')
  assert.equal(steps[2].lastErrorDetail, 'SAFE_TEXT_GENERATION_FAILED')
  assert.equal(errors.length, 1)
  assert.match(errors[0], /爆发段生成失败/)
  assert.equal(progressMessages.at(-1), '')
})
