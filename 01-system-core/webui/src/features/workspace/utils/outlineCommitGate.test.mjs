import assert from 'node:assert/strict'
import {
  resolveCommitConfirmedTotalEpisodes,
  resolveStrictConfirmedTotalEpisodes,
} from './outlineCommitGate.ts'

const legacyOutlineState = {
  standard_outline_packet: {
    schema_version: 'chat_outline_packet_v1',
    status: 'needs_user_confirmation',
    current_stage: 'project_profile',
    project_profile: {},
    story_core: {},
    world_rules: {},
    characters: { value: [], status: 'missing', source: 'system_inferred' },
    relationship_timeline: { value: [], status: 'missing', source: 'system_inferred' },
    episode_count_plan: {
      confirmed_total_episodes: { value: '', status: 'missing', source: 'system_inferred' },
      suggested_total_episodes: { value: '', status: 'missing', source: 'system_inferred' },
      episode_count_reason: { value: '', status: 'missing', source: 'system_inferred' },
    },
    long_arc: {},
    range_outlines: { value: [], status: 'missing', source: 'system_inferred' },
    episode_outlines: { value: [], status: 'missing', source: 'system_inferred' },
    content_correctness_summary: { recognized: [], inferred: [], incomplete: [], unrecognized: [] },
    quality_gaps: [],
    conflict_issues: [],
    user_confirmed_fields: {},
    generated_at: '2026-06-15T00:00:00.000Z',
    updated_at: '2026-06-15T00:00:00.000Z',
  },
}

assert.equal(
  resolveStrictConfirmedTotalEpisodes({
    workflowOutlineState: legacyOutlineState,
    projectRules: { total_episodes: 30, confirmed_total_episodes: null },
    projectConfig: { total_episodes: 30, confirmed_total_episodes: null },
  }),
  0,
  '未盖用户确认章时，普通总集数不能被静默当成正式确认',
)

assert.equal(
  resolveCommitConfirmedTotalEpisodes({
    workflowOutlineState: legacyOutlineState,
    projectRules: { total_episodes: 30, confirmed_total_episodes: null },
    projectConfig: { total_episodes: 30, confirmed_total_episodes: null },
    outlineEpisodeCount: 30,
  }),
  30,
  '用户点击完成时，当前 30 集完整集纲可以被升级为用户确认总集数',
)

assert.equal(
  resolveCommitConfirmedTotalEpisodes({
    workflowOutlineState: legacyOutlineState,
    projectRules: { total_episodes: 32, confirmed_total_episodes: null },
    projectConfig: { total_episodes: 32, confirmed_total_episodes: null },
    outlineEpisodeCount: 30,
  }),
  0,
  '如果用户目标是 32 集但页面只有 30 集，不能放行进入角色设计',
)

console.log('outlineCommitGate regression passed')
