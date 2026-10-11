import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import test from 'node:test'

const webuiRoot = path.resolve(import.meta.dirname, '..')
const viewPath = path.join(webuiRoot, 'src/views/ProjectWorkspaceView.vue')
const apiPath = path.join(webuiRoot, 'src/api/modules/episodeDraftCompletion.ts')

function readSource(filePath) {
  return fs.readFileSync(filePath, 'utf8')
}

function extractArrowBlock(source, marker) {
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

test('final segment completion must call backend draft completion close before clearing local segmented progress', () => {
  assert.equal(
    fs.existsSync(apiPath),
    true,
    'episode draft completion API module must exist',
  )

  const apiSource = readSource(apiPath)
  const viewSource = readSource(viewPath)
  const completionBlock = extractArrowBlock(viewSource, 'onAllSegmentsComplete: async () =>')

  assert.match(
    apiSource,
    /closeEpisodeDraftCompletion:\s*\(\s*projectId:\s*string,\s*episodeNumber:\s*number,\s*sceneNumber\s*=\s*1\s*\)\s*=>[\s\S]*\/projects\/\$\{projectId\}\/episodes\/\$\{episodeNumber\}\/draft-completion\/close/,
    'frontend must expose a dedicated draft completion close API method',
  )
  assert.match(
    completionBlock,
    /episodeDraftCompletionApi\.closeEpisodeDraftCompletion\(\s*projectId\.value,\s*target\.episodeNo,\s*target\.sceneNo\s*\)/,
    'final segment completion must call the backend draft completion close API',
  )
  assert.match(
    completionBlock,
    /if \(!completionClosed\) \{[\s\S]*return[\s\S]*\}/,
    'when draft completion close fails, final completion must stop before pretending the episode is closable',
  )

  const closeIndex = completionBlock.indexOf('episodeDraftCompletionApi.closeEpisodeDraftCompletion(')
  const clearIndex = completionBlock.indexOf('_clearCompletedEpisodeSegmentProgress(')
  assert.notEqual(closeIndex, -1, 'completion callback must call draft completion close')
  assert.notEqual(clearIndex, -1, 'completion callback must still clear local progress after backend close succeeds')
  assert.ok(closeIndex < clearIndex, 'backend draft completion close must happen before local segmented progress is cleared')

  assert.equal(
    completionBlock.includes('startRuleBackedScriptJob'),
    false,
    'final segment completion close must not create a new generation job',
  )
})
