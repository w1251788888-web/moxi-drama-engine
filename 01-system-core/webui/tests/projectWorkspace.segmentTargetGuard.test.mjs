import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import test from 'node:test'

const webuiRoot = path.resolve(import.meta.dirname, '..')
const workspaceViewPath = path.join(webuiRoot, 'src/views/ProjectWorkspaceView.vue')
const segmentPanelPath = path.join(webuiRoot, 'src/views/workspace/tabs/SegmentReviewPanel.vue')

function read(filePath) {
  return fs.readFileSync(filePath, 'utf8')
}

test('segment retry and confirm actions pass through workspace target guard', () => {
  const source = read(workspaceViewPath)

  assert.match(
    source,
    /function _ensureActiveSegmentActionTarget\(idx: number, actionLabel: string\)/,
    'workspace must define a target guard for segment actions',
  )
  assert.match(
    source,
    /Number\(target\.episodeNo\) !== selectedEp \|\| Number\(target\.sceneNo\) !== selectedSc/,
    'target guard must compare active generation target with the selected page target',
  )
  assert.match(
    source,
    /idx !== Number\(currentSegmentIdx\.value\)/,
    'target guard must compare clicked segment index with the current panel segment',
  )
  assert.match(
    source,
    /async function _handleSegmentRetry\(idx: number\) \{[\s\S]*_ensureActiveSegmentActionTarget\(idx, '重新生成'\)[\s\S]*await segmentRetry\(idx\)/,
    'retry must pass through the workspace target guard before reaching the segment state machine',
  )
  assert.match(
    source,
    /async function _handleSegmentConfirm\(idx: number\) \{[\s\S]*_ensureActiveSegmentActionTarget\(idx, '确认当前段'\)[\s\S]*await segmentConfirm\(idx\)/,
    'confirm must pass through the same target guard before it can continue the next segment',
  )
  assert.match(
    source,
    /@retry="_handleSegmentRetry"/,
    'segment panel retry event must not call segmentRetry directly',
  )
  assert.match(
    source,
    /@confirm="_handleSegmentConfirm"/,
    'segment panel confirm event must not call segmentConfirm directly',
  )
  assert.match(
    source,
    /@generate-variant="_handleSegmentGenerateVariant"/,
    'segment panel variant generation event must not call segmentGenerateVariant directly',
  )
})

test('segment review panel exposes safe generation target attributes before retry', () => {
  const panel = read(segmentPanelPath)
  const source = read(workspaceViewPath)

  assert.match(
    panel,
    /generationTarget: GenerationTarget/,
    'segment review panel must receive the workspace generation target',
  )
  assert.match(
    source,
    /:generation-target="activeSegmentReviewTarget"/,
    'workspace must pass the active generation target into the panel',
  )
  assert.match(
    panel,
    /:data-generation-episode="generationTarget\.episodeNo"/,
    'retry buttons must expose the target episode for runtime verification',
  )
  assert.match(
    panel,
    /:data-generation-scene="generationTarget\.sceneNo"/,
    'retry buttons must expose the target scene for runtime verification',
  )
  assert.match(
    panel,
    /:data-generation-segment="step\.id"/,
    'retry buttons must expose the target segment for runtime verification',
  )
  assert.match(
    panel,
    /第\{\{ generationTarget\.episodeNo \}\}集 · 第\{\{ generationTarget\.sceneNo \}\}场/,
    'panel header must show the current generation target to the operator',
  )
})
