from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WEBUI = ROOT / "webui" / "src"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_script_step_confirmation_component_is_isolated_to_editor_stage():
    component = WEBUI / "views" / "workspace" / "tabs" / "ScriptStepConfirmationPanel.vue"
    workspace = WEBUI / "views" / "ProjectWorkspaceView.vue"

    assert component.exists()
    source = read(component)
    assert "分步确认" in source
    assert "确认完的步骤会收起" in source
    assert "重新生成本步" in source
    assert "可修改" in source
    assert "去下方正文编辑" in source
    assert "确认并进入下一步" in source

    workspace_source = read(workspace)
    assert "ScriptStepConfirmationPanel" in workspace_source
    status_pos = workspace_source.index("<ScriptSceneStatusPanel")
    step_pos = workspace_source.index("<ScriptStepConfirmationPanel")
    editor_pos = workspace_source.index("<ScriptEditorPanel")
    assert status_pos < step_pos < editor_pos


def test_script_step_confirmation_does_not_take_over_outer_workspace_regions():
    workspace_source = read(WEBUI / "views" / "ProjectWorkspaceView.vue")

    assert "<ScriptSidebar" in workspace_source
    assert "<AiAssistantPanel" in workspace_source
    assert "ScriptStepConfirmationPanel" not in read(WEBUI / "views" / "workspace" / "tabs" / "ScriptSidebar.vue")
    assert "ScriptStepConfirmationPanel" not in read(WEBUI / "views" / "workspace" / "panels" / "AiAssistantPanel.vue")


def test_script_editor_uses_single_outer_scroll_instead_of_nested_textarea_scroll():
    editor = read(WEBUI / "views" / "workspace" / "tabs" / "ScriptEditorPanel.vue")
    textarea = read(WEBUI / "components" / "ui" / "textarea" / "Textarea.vue")

    assert 'auto-resize' in editor
    assert 'data-script-editor-textarea="true"' in editor
    assert 'min-h-[70vh]' in editor
    assert 'flex-1 resize-none' not in editor
    assert 'overflow-auto' not in editor
    assert 'autoResize' in textarea
    assert 'textareaRef.value.style.height' in textarea
    assert 'textareaRef.value.style.overflowY = "hidden"' in textarea


def test_step_confirmation_uses_real_editable_packet_and_normal_collapse():
    component = read(WEBUI / "views" / "workspace" / "tabs" / "ScriptStepConfirmationPanel.vue")

    assert "confirmationPacket" in component
    assert "updateConfirmationItem" in component
    assert "editedBody" in component
    assert "点此收起" in component
    assert "去下方正文编辑" in component
    assert "expandedStepId.value === stepId ? 'blueprint' : stepId" not in component
    assert "expandedStepId.value = expandedStepId.value === stepId ? null : stepId" in component


def test_step_confirmation_edits_are_part_of_generation_request():
    workspace = read(WEBUI / "views" / "ProjectWorkspaceView.vue")

    assert "_buildStepConfirmationPacket" in workspace
    assert "_buildSegmentTaskCardItems" in workspace
    assert "_upsertStepConfirmationOverride" in workspace
    assert "step_confirmation_packet" in workspace
    assert "user_confirmed_generation_packet" in workspace
    assert ':confirmation-packet="currentStepConfirmationPacket"' in workspace
    assert '@update-confirmation-item="_upsertStepConfirmationOverride"' in workspace

    request_pos = workspace.index("step_confirmation_packet")
    build_pos = workspace.index("_buildRuleBackedScriptRequest")
    assert build_pos < request_pos


def test_generation_request_keeps_user_filled_outline_character_and_relation_fields():
    workspace = read(WEBUI / "views" / "ProjectWorkspaceView.vue")

    for snippet in [
        "brief: outlineData.value.logline",
        "golden_finger: outlineData.value.goldenFinger",
        "worldview: outlineData.value.worldview",
        "conflict: outlineData.value.conflict",
        "episode_title: epInfo?.title",
        "episode_summary: epInfo?.summary",
        "episode_conflict: epInfo?.conflict",
        "episode_hook: epInfo?.hook || epInfo?.turning",
        "info: char.info",
        "occupation: char.occupation",
        "background: char.background",
        "motivation: char.motivation",
        "traits: char.traits",
        "personality: char.personality",
        "voice_style: char.voice_style",
        "inner_need: char.inner_need",
        "relationship_tension: char.relationship_tension",
        "relationships: char.relationships",
        "previous_episode_briefs: _buildPreviousEpisodeBriefs()",
        "future_episode_briefs: _buildFutureEpisodeBriefs()",
        "previous_relationship_snapshot: _buildPreviousRelationshipSnapshot()",
        "relationship_timeline_context: _buildRelationshipTimelineContext(selectedEpisode.value)",
        "manual_edit_context: workflowContext.value.manual_edit_context",
        "step_confirmation_packet: stepConfirmationPacket",
        "user_confirmed_generation_packet: _buildUserConfirmedGenerationPacket(stepConfirmationPacket)",
        "series_simulation_packet: seriesSimulationPacket",
        "episode_contract: episodeContract",
        "...directorBlueprintPacket",
        "rag_context_pack:",
    ]:
        assert snippet in workspace


def test_episode_meta_map_keeps_user_locked_outline_before_database_display_summary():
    workspace = read(WEBUI / "views" / "ProjectWorkspaceView.vue")

    assert "summary: String(episode.summary || previous?.summary || '')" not in workspace
    assert "summary: String(previous?.summary || episode.summary || '')" in workspace
    assert "title: String(previous?.title || episode.title || '')" in workspace
    assert "用户锁定的大纲/集纲字段优先" in workspace


def test_project_load_refreshes_locked_outline_snapshot_even_when_old_contract_exists():
    workspace = read(WEBUI / "views" / "ProjectWorkspaceView.vue")

    assert "&& !_hasSeriesSimulationContracts(workflowContext.value.series_simulation_packet)" not in workspace
    assert "let changed = false" in workspace
    assert "changed = true" in workspace
    assert "if (changed && options?.persist !== false)" in workspace
    assert "await _refreshSeriesSimulationPacket('project_loaded_outline_snapshot', { silent: true })" in workspace


def test_confirming_step_commits_current_confirmation_items_to_workflow_context():
    component = read(WEBUI / "views" / "workspace" / "tabs" / "ScriptStepConfirmationPanel.vue")
    workspace = read(WEBUI / "views" / "ProjectWorkspaceView.vue")

    assert "function commitStepItems(step: ConfirmationStep)" in component
    assert "for (const item of sectionItems(step.id))" in component
    assert "emit('commitConfirmationStep', { stepId: step.id, items })" in component
    assert "commitStepItems(step)" in component
    assert "@commit-confirmation-step=\"_commitStepConfirmationStep\"" in workspace
    assert "async function _commitStepConfirmationStep" in workspace


def test_regenerate_step_carries_step_id_and_candidate_save_forces_fresh_model_job():
    component = read(WEBUI / "views" / "workspace" / "tabs" / "ScriptStepConfirmationPanel.vue")
    workspace = read(WEBUI / "views" / "ProjectWorkspaceView.vue")
    segmented = read(WEBUI / "features" / "workspace" / "composables" / "useSegmentedWriting.ts")

    assert "regenerateStep: [payload: { stepId: ConfirmationStepId }]" in component
    assert "emit('regenerateStep', { stepId: step.id })" in component
    assert '@regenerate-step="_handleRegenerateConfirmationStep"' in workspace
    assert '@regenerate-step="runSegmentedWritingWithEpisode"' not in workspace
    assert "async function _handleRegenerateConfirmationStep" in workspace
    assert "payload?.stepId === 'candidate_save'" in workspace
    assert "forceRegenerateCurrentDraft: true" in workspace
    assert "await generateSegmented({ ...options, sourcePrechecked: true })" in workspace
    assert "forceRegenerateCurrentDraft?: boolean" in segmented
    assert "!generateOptions?.sourcePrechecked" in segmented
    assert "&& !generateOptions?.forceRegenerateCurrentDraft" in segmented
    assert "&& options.getSceneContent?.().trim()" in segmented


def test_segment_task_cards_carry_blueprint_contract_and_relationship_constraints():
    workspace = read(WEBUI / "views" / "ProjectWorkspaceView.vue")

    assert "`${def.desc}：目标约${def.target}净字。围绕本集蓝图推进，不能重复上一段。`" not in workspace
    assert "段落目标：" in workspace
    assert "本段具体写什么：" in workspace
    assert "承接依据：" in workspace
    assert "人物/关系约束：" in workspace
    assert "段尾交接：" in workspace
    assert "directorBlueprint" in workspace
    assert "contract" in workspace
    assert "relationshipContext" in workspace
    assert "segment_cards', _buildSegmentTaskCardItems" in workspace


def test_segment_task_cards_prioritize_user_confirmed_blueprint_fields():
    workspace = read(WEBUI / "views" / "ProjectWorkspaceView.vue")

    for snippet in [
        "_stepConfirmationOverrideBody('blueprint', 'episode_goal')",
        "_stepConfirmationOverrideBody('blueprint', 'control_loss')",
        "_stepConfirmationOverrideBody('blueprint', 'audience_payoff')",
        "_stepConfirmationOverrideBody('blueprint', 'ending_hook')",
        "_stepConfirmationOverrideBody('blueprint', 'character_boundary')",
    ]:
        assert snippet in workspace

    assert workspace.index("confirmedBlueprintEndingHook") < workspace.index("directorBlueprint.ending_hook")


def test_segment_confirm_trusts_reviewing_candidate_without_slow_revalidation():
    workspace = read(WEBUI / "views" / "ProjectWorkspaceView.vue")

    assert "function _isSegmentConfirmationTrustBoundary(step: SegmentStep)" in workspace
    assert "return step.status === 'reviewing' && Boolean(step.editedContent.trim())" in workspace
    assert "if (_isSegmentConfirmationTrustBoundary(step)) {\n    return true\n  }" in workspace
    assert workspace.index("if (_isSegmentConfirmationTrustBoundary(step))") < workspace.index("const previousConfirmed = segmentSteps.value")


def test_non_final_segment_confirmation_does_not_run_slow_runtime_refresh():
    workspace = read(WEBUI / "views" / "ProjectWorkspaceView.vue")

    after_confirm_pos = workspace.index("afterSegmentConfirmed: async deepAudit =>")
    save_pos = workspace.index("const saved = await persistCurrentScriptContent", after_confirm_pos)
    snippet = workspace[after_confirm_pos:save_pos]

    assert "refreshScriptRuntimeSignals" not in snippet


def test_final_segment_confirmation_runs_deep_audit_before_save_and_keeps_background_refresh_non_blocking():
    segmented = read(WEBUI / "features" / "workspace" / "composables" / "useSegmentedWriting.ts")
    workspace = read(WEBUI / "views" / "ProjectWorkspaceView.vue")

    assert "const scriptApproved = await options.approveFullScript(true)" in segmented
    assert "void options.approveFullScript(true)" not in segmented
    assert "整集深审仍有风险，已保留你确认的分段并保存为待复核稿，不自动覆盖重写。" in segmented

    complete_pos = workspace.index("onAllSegmentsComplete: async () =>")
    save_pos = workspace.index("const saved = await persistCurrentScriptContent", complete_pos)
    refresh_pos = workspace.index("void refreshScriptRuntimeSignals({ silent: true, autoApplySuggestions: true, deepAudit: true })", complete_pos)
    assert save_pos < refresh_pos


def test_final_segment_confirmation_closes_panel_and_clears_stale_progress():
    segmented = read(WEBUI / "features" / "workspace" / "composables" / "useSegmentedWriting.ts")
    workspace = read(WEBUI / "views" / "ProjectWorkspaceView.vue")

    confirm_pos = segmented.index("async function segmentConfirm")
    final_branch_pos = segmented.index("if (shouldDeepAudit) {", confirm_pos + 1)
    final_branch = segmented[final_branch_pos:segmented.index("await generateOneSegment(idx + 1)", final_branch_pos)]
    assert "showSegmentPanel.value = false" in final_branch
    assert "currentSegmentIdx.value = segmentSteps.value.length" in final_branch
    assert "await options.onAllSegmentsComplete?.()" in final_branch
    assert "return" in final_branch

    complete_pos = workspace.index("onAllSegmentsComplete: async () =>")
    complete_body = workspace[complete_pos:workspace.index("onConfirmedContentChanged:", complete_pos)]
    assert "_clearCompletedEpisodeSegmentProgress(selectedEpisode.value, 'internal_segmented_episode_completed')" in complete_body
    assert "_persistCurrentSegmentProgress({ immediate: true })" not in complete_body

    after_pos = workspace.index("afterSegmentConfirmed: async deepAudit =>")
    after_body = workspace[after_pos:workspace.index("getFailureAnalysis:", after_pos)]
    assert "if (!deepAudit) {" in after_body
    assert "_persistCurrentSegmentProgress({ immediate: true })" in after_body


def test_candidate_save_confirms_active_segment_before_plain_save():
    workspace = read(WEBUI / "views" / "ProjectWorkspaceView.vue")

    assert '@save-candidate="_handleStepCandidateSave"' in workspace
    assert "async function _handleStepCandidateSave()" in workspace
    handler_pos = workspace.index("async function _handleStepCandidateSave()")
    handler_body = workspace[handler_pos:workspace.index("async function prepareNextEpisodeForWriting", handler_pos)]
    confirm_pos = workspace.index("async function _confirmSegmentCandidateBeforeStepSave()")
    confirm_body = workspace[confirm_pos:handler_pos]
    selector_pos = workspace.index("function _candidateSaveSegmentConfirmIndex()")
    selector_body = workspace[selector_pos:confirm_pos]
    assert "currentSegmentIdx.value" in selector_body
    assert "step.status === 'reviewing' || step.status === 'generating'" in selector_body
    assert "await _recoverEmptySegmentCandidateForIndex(segmentIdx)" in confirm_body
    assert "await segmentConfirm(segmentIdx)" in confirm_body
    assert "await _confirmSegmentCandidateBeforeStepSave()" in handler_body
    assert "requireNonEmptyContent: true" in handler_body
    assert "changeNote: '确认候选并保存'" in handler_body
    assert handler_body.index("await _confirmSegmentCandidateBeforeStepSave()") < handler_body.index("requireNonEmptyContent: true")


def test_candidate_save_empty_content_is_blocked_before_becoming_canon():
    workspace = read(WEBUI / "views" / "ProjectWorkspaceView.vue")

    assert "requireNonEmptyContent?: boolean" in workspace
    assert "候选正文为空，不能保存为下一集承接正史" in workspace
    persist_pos = workspace.index("async function persistCurrentScriptContent")
    persist_body = workspace[persist_pos:workspace.index("async function saveScript", persist_pos)]
    assert "if (options?.requireNonEmptyContent && !snapshotContent.trim())" in persist_body
    assert "return false" in persist_body.split("if (options?.requireNonEmptyContent && !snapshotContent.trim())", 1)[1].split("const shouldRecordManualEdit", 1)[0]


def test_continue_generation_confirms_reviewing_segment_candidate():
    segmented = read(WEBUI / "features" / "workspace" / "composables" / "useSegmentedWriting.ts")

    resume_pos = segmented.index("async function resumeSegmentedProgress()")
    reviewing_pos = segmented.index("if (step.status === 'reviewing')", resume_pos)
    branch_body = segmented[reviewing_pos:segmented.index("if (step.status === 'error')", reviewing_pos)]
    assert "await segmentConfirm(idx)" in branch_body
    assert "正在等待确认，确认后会继续下一段" not in branch_body


def test_toolbar_generate_sets_visible_status_and_empty_failure_message():
    workspace = read(WEBUI / "views" / "ProjectWorkspaceView.vue")

    handler_pos = workspace.index("async function runSegmentedWritingWithEpisode")
    handler_body = workspace[handler_pos:workspace.index("async function _handleRegenerateConfirmationStep", handler_pos)]
    assert "scriptStreamStatus.value = '正在生成本集正文，请不要关闭页面。'" in handler_body
    assert "生成失败：本次没有保存空内容" in handler_body
    generation_call = "await generateSegmented({ ...options, sourcePrechecked: true })"
    assert generation_call in handler_body
    assert handler_body.index("scriptStreamStatus.value = '正在生成本集正文，请不要关闭页面。'") < handler_body.index(generation_call)


def test_generation_result_persists_full_director_blueprint_per_episode():
    workspace = read(WEBUI / "views" / "ProjectWorkspaceView.vue")
    stream = read(WEBUI / "features" / "workspace" / "composables" / "useRuleBackedScriptStream.ts")

    assert "director_blueprint: Record<string, any>" in stream
    assert "directorBlueprint = (data as any).director_blueprint" in stream
    assert "director_blueprint: directorBlueprint" in stream
    assert "payload.director_blueprint" in workspace
    assert "workflowPatch.director_blueprints" in workspace
    assert "payload.generation_trace?.director_blueprint" not in workspace


def test_satisfaction_codes_are_translated_before_user_visible_confirmation():
    workspace = read(WEBUI / "views" / "ProjectWorkspaceView.vue")

    assert "SATISFACTION_TYPE_LABELS" in workspace
    assert "S6: '关系反转'" in workspace
    assert "_formatSatisfactionTypeForUser" in workspace
    assert "_formatSatisfactionTypeForUser(epInfo.satisfaction_type" in workspace
    assert "爽点类型必须落地：${satisfactionType}" in workspace


def test_step_confirmation_overrides_survive_workflow_context_normalizers():
    frontend_state = read(WEBUI / "features" / "workspace" / "utils" / "workflowState.ts")
    project_helpers = read(ROOT / "app" / "routers" / "projects" / "_helpers.py")
    backend_normalizers = read(ROOT / "app" / "services" / "short_drama_testing_normalizers.py")

    assert "step_confirmation_overrides" in frontend_state
    assert "step_confirmation_overrides" in project_helpers
    assert "step_confirmation_overrides" in backend_normalizers
