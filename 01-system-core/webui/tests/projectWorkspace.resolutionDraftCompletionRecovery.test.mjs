import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import test from 'node:test'

const webuiRoot = path.resolve(import.meta.dirname, '..')
const viewPath = path.join(webuiRoot, 'src/views/ProjectWorkspaceView.vue')

function readSource(filePath) {
  return fs.readFileSync(filePath, 'utf8')
}

function extractFunctionBlock(source, marker) {
  const start = source.indexOf(marker)
  assert.notEqual(start, -1, `${marker} must exist`)
  const open = source.indexOf('{', start)
  assert.notEqual(open, -1, `${marker} must have a body`)
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
  assert.fail(`${marker} body was not closed`)
}

function extractIfBlock(source, marker) {
  const start = source.indexOf(marker)
  assert.notEqual(start, -1, `${marker} must exist`)
  const open = source.indexOf('{', start)
  assert.notEqual(open, -1, `${marker} must have a body`)
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
  assert.fail(`${marker} body was not closed`)
}

test('confirmed old-state recovery must close draft completion before formal episode lock', () => {
  const viewSource = readSource(viewPath)
  const lockBlock = extractFunctionBlock(viewSource, 'async function lockCurrentEpisodeFromWorkspace()')
  const recoveryBlock = extractIfBlock(lockBlock, 'if (currentEpisodeNeedsDraftCompletionRecovery.value) {')

  assert.match(
    recoveryBlock,
    /episodeDraftCompletionApi\.closeEpisodeDraftCompletion\(/,
    'lock path must recover missing draft completion close for already-confirmed old state',
  )

  const closeIndex = recoveryBlock.indexOf('episodeDraftCompletionApi.closeEpisodeDraftCompletion(')
  const lockIndex = lockBlock.indexOf('collaborationApi.lockEpisode(')
  assert.notEqual(closeIndex, -1, 'lock path must attempt draft completion recovery for old confirmed state')
  assert.notEqual(lockIndex, -1, 'lock path must still preserve the real lock API call')
  assert.ok(
    lockBlock.indexOf('episodeDraftCompletionApi.closeEpisodeDraftCompletion(') < lockIndex,
    'draft completion recovery must happen before formal episode lock',
  )

  assert.match(
    lockBlock,
    /if \(!draftCompletionRecovered\) \{[\s\S]*return[\s\S]*\}/,
    'failed confirmed-state recovery must stop before formal lock',
  )

  assert.equal(
    recoveryBlock.includes('collaborationApi.lockEpisode('),
    false,
    'confirmed-state recovery branch itself must not hide a second lock call',
  )
  assert.match(
    recoveryBlock,
    /return true/,
    'successful confirmed-state recovery must let the same click continue to formal lock',
  )
  assert.match(
    recoveryBlock,
    /正在继续正式锁稿/,
    'user-facing copy must explain that formal locking continues in the same click',
  )
  assert.equal(
    recoveryBlock.includes('_clearCompletedEpisodeSegmentProgress('),
    false,
    'confirmed-state recovery must not clear local confirmed segment state',
  )
  assert.equal(
    recoveryBlock.includes('startRuleBackedScriptJob'),
    false,
    'confirmed-state recovery must not trigger any new generation job',
  )
})
