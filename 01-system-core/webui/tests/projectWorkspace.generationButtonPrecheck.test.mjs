import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import test from 'node:test'

const webuiRoot = path.resolve(import.meta.dirname, '..')
const viewPath = path.join(webuiRoot, 'src/views/ProjectWorkspaceView.vue')
const scriptEditorPanelPath = path.join(webuiRoot, 'src/views/workspace/tabs/ScriptEditorPanel.vue')

function readViewSource() {
  return fs.readFileSync(viewPath, 'utf8')
}

function readScriptEditorPanelSource() {
  return fs.readFileSync(scriptEditorPanelPath, 'utf8')
}

function extractFunction(source, name) {
  const marker = `async function ${name}`
  const start = source.indexOf(marker)
  assert.notEqual(start, -1, `${name} must exist`)
  const signatureStart = source.indexOf('(', start)
  assert.notEqual(signatureStart, -1, `${name} must have parameters`)
  let parenDepth = 0
  let signatureEnd = -1
  for (let index = signatureStart; index < source.length; index += 1) {
    const char = source[index]
    if (char === '(') parenDepth += 1
    if (char === ')') {
      parenDepth -= 1
      if (parenDepth === 0) {
        signatureEnd = index
        break
      }
    }
  }
  assert.notEqual(signatureEnd, -1, `${name} signature was not closed`)
  const open = source.indexOf('{', signatureEnd)
  assert.notEqual(open, -1, `${name} must have a body`)

  let depth = 0
  for (let index = open; index < source.length; index += 1) {
    const char = source[index]
    if (char === '{') depth += 1
    if (char === '}') {
      depth -= 1
      if (depth === 0) {
        return source.slice(start, index + 1)
      }
    }
  }
  assert.fail(`${name} body was not closed`)
}

test('backend-ready generation entry continues with sourcePrechecked instead of returning at local outline gate', () => {
  const source = readViewSource()
  const generationEntry = extractFunction(source, 'runSegmentedWritingWithEpisode')

  const previewIndex = generationEntry.indexOf('_previewBackendGenerationSource(previewPayload)')
  const localGateIndex = generationEntry.indexOf('ensureOutlineGatePassed')
  const episodeReadyIndex = generationEntry.indexOf('ensureScriptEpisodeReady')
  const segmentedIndex = generationEntry.indexOf('generateSegmented({ ...options, sourcePrechecked: true })')

  assert.notEqual(previewIndex, -1, 'safe generation entry must call backend source preview')
  assert.notEqual(localGateIndex, -1, 'safe generation entry should still keep the local outline gate as a warning check')
  assert.notEqual(episodeReadyIndex, -1, 'episode readiness must still be allowed to block')
  assert.notEqual(segmentedIndex, -1, 'backend-ready flow must continue with sourcePrechecked')
  assert.equal(
    generationEntry.includes('if (!ensureOutlineGatePassed({ episodeLimit: target.episodeNo })) return'),
    false,
    'backend-ready flow must not return at the outer local outline gate',
  )
  assert.ok(previewIndex < localGateIndex, 'backend source preview must run before local outline gate')
  assert.ok(localGateIndex < episodeReadyIndex, 'local outline gate warning check must run before episode readiness')
  assert.ok(episodeReadyIndex < segmentedIndex, 'segmented generation must start after episode readiness')
})

test('latest candidate restore forwards current user session to the API layer', () => {
  const source = readViewSource()
  const restoreFn = extractFunction(source, '_restoreLatestRuleBackedSegmentCandidate')
  const settingsSource = fs.readFileSync(path.join(webuiRoot, 'src/api/modules/settings.ts'), 'utf8')

  assert.match(
    settingsSource,
    /getLatestRuleBackedScriptJob:\s*\([\s\S]*params:[\s\S]*options\?:\s*UserScopedRequestOptions[\s\S]*\)\s*=>/,
    'latest candidate API method must accept optional user-scoped request options',
  )
  assert.match(
    settingsSource,
    /\/admin\/short-drama\/testing\/script-scene\/jobs\/latest[\s\S]*headers:\s*authHeaders\(options\)/,
    'latest candidate API method must send auth headers built from the current user session',
  )
  assert.match(
    restoreFn,
    /const authOptions = \{[\s\S]*userSessionToken:\s*auth\.userSession\?\.session_token,[\s\S]*adminToken:\s*auth\.token,[\s\S]*\}/,
    'latest candidate restore must build the same user-scoped auth options used by other job APIs',
  )
  assert.match(
    restoreFn,
    /getLatestRuleBackedScriptJob\(\s*\{[\s\S]*segment_id:\s*String\(step\.id \|\| ''\),[\s\S]*\}\s*,\s*authOptions\s*\)/,
    'latest candidate restore must pass auth options into the API call',
  )
})

test('candidate save step confirms a stale active segment before falling back to plain save', () => {
  const source = readViewSource()
  const candidateSaveFn = extractFunction(source, '_handleStepCandidateSave')
  const recoverBeforeSaveFn = extractFunction(source, '_confirmSegmentCandidateBeforeStepSave')
  const recoverByIndexFn = extractFunction(source, '_recoverEmptySegmentCandidateForIndex')
  const hydrateFn = extractFunction(source, '_hydrateSegmentProgressForEpisode')
  const staleProgressFn = source.slice(
    source.indexOf('function _canRecoverStaleSegmentProgress'),
    source.indexOf('function _currentScriptSegmentProgressSnapshot'),
  )
  const confirmIndexFn = source.slice(
    source.indexOf('function _candidateSaveSegmentConfirmIndex'),
    source.indexOf('async function _confirmSegmentCandidateBeforeStepSave'),
  )

  assert.match(
    confirmIndexFn,
    /activeStep\.status === 'reviewing' \|\| activeStep\.status === 'generating'/,
    'candidate-save recovery must treat stale generating segments as recoverable confirmation targets',
  )
  assert.match(
    staleProgressFn,
    /currentContent\.trim\(\)\.startsWith\(savedContent\.trim\(\)\)/,
    'stale progress recovery must only run when the current saved script still contains the previously confirmed segment draft',
  )
  assert.match(
    staleProgressFn,
    /status === 'reviewing' \|\| status === 'generating'/,
    'stale progress recovery must only target active unconfirmed segment states',
  )
  assert.match(
    staleProgressFn,
    /&& !hasDraft/,
    'stale progress recovery must not overwrite an existing segment draft',
  )
  assert.match(
    hydrateFn,
    /currentHash !== savedHash && !canRecoverStaleProgress/,
    'hash mismatch must still block hydration unless it is a recoverable stale segment progress case',
  )
  assert.match(
    hydrateFn,
    /activeSegmentDraftContent\.value = canRecoverStaleProgress \? currentContent : savedContent \|\| currentContent/,
    'recoverable stale progress must preserve the newer saved script instead of reverting to old progress text',
  )
  assert.match(
    recoverByIndexFn,
    /await recoverLatestCandidateForSegment\(segmentIdx\)/,
    'workspace-level recovery must call the segmented latest-candidate recovery method',
  )
  assert.match(
    recoverByIndexFn,
    /await _persistCurrentSegmentProgress\(\{ immediate: true \}\)/,
    'successful recovery must persist and wait for corrected segment progress before lock decisions',
  )
  assert.match(
    recoverBeforeSaveFn,
    /await _recoverEmptySegmentCandidateForIndex\(segmentIdx\)/,
    'candidate-save recovery must first restore a backend candidate for an empty active segment',
  )
  assert.match(
    recoverBeforeSaveFn,
    /_ensureActiveSegmentActionTarget\(segmentIdx, '确认候选并保存'\)/,
    'candidate-save recovery must still pass through the segment target guard',
  )
  assert.match(
    recoverBeforeSaveFn,
    /await segmentConfirm\(segmentIdx\)/,
    'candidate-save recovery must reuse the segmented confirmation state machine',
  )
  assert.ok(
    candidateSaveFn.indexOf('await _confirmSegmentCandidateBeforeStepSave()') < candidateSaveFn.indexOf('await persistCurrentScriptContent'),
    'candidate-save must try segmented confirmation before plain content saving',
  )
  assert.match(
    hydrateFn,
    /await _recoverEmptySegmentCandidateForIndex\(recoverIdx\)/,
    'segment progress hydration must restore empty stale segment candidates from backend state',
  )
})

test('segment progress writes wait for immediate workflow-context sync at critical steps', () => {
  const source = readViewSource()
  const persistProgressFn = source.slice(
    source.indexOf('async function _persistCurrentSegmentProgress'),
    source.indexOf('function _ruleBackedJobStatusToSegmentResult'),
  )
  const segmentedOptions = source.slice(
    source.indexOf('onSegmentDraftReady: async'),
    source.indexOf('getFailureAnalysis: () => scriptRuleValidation.value.failure_analysis || {}'),
  )

  assert.match(
    persistProgressFn,
    /async function _persistCurrentSegmentProgress/,
    'segment progress persistence must be awaitable',
  )
  assert.match(
    persistProgressFn,
    /await _syncProjectWorkflowContext\(\{ immediate: true, silent: true \}\)/,
    'immediate segment progress persistence must wait until workflow-context is saved',
  )
  assert.match(
    segmentedOptions,
    /await _persistCurrentSegmentProgress\(\{ immediate: true \}\)/,
    'segment draft and confirmation hooks must wait for immediate progress persistence',
  )
  assert.doesNotMatch(
    persistProgressFn,
    /void _syncProjectWorkflowContext\(\{ immediate: true, silent: true \}\)/,
    'critical segment progress persistence must not fire-and-forget workflow-context sync',
  )
})

test('stored incomplete segment progress blocks official episode lock even when hydration misses it', () => {
  const source = readViewSource()
  const storedProgressFn = source.slice(
    source.indexOf('function _hasStoredIncompleteSegmentProgress'),
    source.indexOf('const isSegmentedDraftIncomplete'),
  )
  const incompleteComputed = source.slice(
    source.indexOf('const isSegmentedDraftIncomplete = computed'),
    source.indexOf('const currentEpisodeOfficiallyLocked'),
  )

  assert.match(
    storedProgressFn,
    /_scriptSegmentProgressStore\(\)\[_scriptSegmentProgressKey\(episodeNumber\)\]/,
    'lock guard must read stored per-episode segment progress from workflow-context',
  )
  assert.match(
    storedProgressFn,
    /draft_completion_close_status \|\| ''\) === 'completed'/,
    'lock guard must not block an episode whose draft completion was already closed',
  )
  assert.match(
    storedProgressFn,
    /status !== 'confirmed' \|\| !hasDraft/,
    'stored progress is incomplete when any segment is unconfirmed or missing saved draft text',
  )
  assert.match(
    incompleteComputed,
    /liveIncomplete \|\| _hasStoredIncompleteSegmentProgress\(selectedEpisode\.value\)/,
    'official lock must be blocked by stored incomplete progress even if live hydration missed it',
  )
})

test('episode one must expose an official lock action before next-episode generation becomes executable', () => {
  const source = readViewSource()
  const scriptEditorPanel = readScriptEditorPanelSource()

  assert.match(
    source,
    /const currentEpisodeOfficiallyLocked = computed\(\(\) => \{/,
    'workspace must compute whether the current episode already has an official lock',
  )
  assert.match(
    source,
    /return Boolean\(sceneContent\.value\.trim\(\)\) && !isGeneratingScript\.value && !isSegmentGenerating\.value && !isSegmentedDraftIncomplete\.value && currentEpisodeOfficiallyLocked\.value/,
    'next-episode execution must require the current episode to be officially locked',
  )
  assert.match(
    source,
    /async function lockCurrentEpisodeFromWorkspace\(\) \{[\s\S]*collaborationApi\.lockEpisode\(projectId\.value, selectedEpisode\.value, \{ note: `锁定第\$\{selectedEpisode\.value\}集最终稿` \}\)/,
    'workspace must reuse the existing lock API from the current script-writing path',
  )
  assert.match(
    scriptEditorPanel,
    /canLockCurrentEpisode:\s*boolean/,
    'script editor panel must accept a dedicated lock-action state from the workspace',
  )
  assert.match(
    scriptEditorPanel,
    /@click\.stop=\"emitLockCurrentEpisode\"/,
    'script editor panel must surface a lock action in the same user path before next-episode generation',
  )
  assert.match(
    scriptEditorPanel,
    /emit\('lockCurrentEpisode'\)/,
    'script editor panel lock helper must emit the official lock event to the workspace',
  )
  assert.match(
    scriptEditorPanel,
    /nextEpisodeGateMessage\?:\s*string/,
    'script editor panel must accept a dedicated gate message for next-episode blocking',
  )
  assert.match(
    scriptEditorPanel,
    /\{\{\s*nextEpisodeGateMessage\s*\}\}/,
    'script editor panel must render the next-episode blocking message in the current writing path',
  )
  assert.match(
    source,
    /return `请先正式锁定第\$\{selectedEpisode\.value\}集，再生成第\$\{selectedEpisode\.value \+ 1\}集`/,
    'when the episode is not officially locked yet, the workspace must compute a clear next-episode blocking message',
  )
})
