from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKSPACE = ROOT / "webui" / "src" / "views" / "ProjectWorkspaceView.vue"


def read_workspace() -> str:
    return WORKSPACE.read_text(encoding="utf-8")


def test_segmented_generation_locks_episode_target_for_request_save_and_progress():
    workspace = read_workspace()

    assert "const activeSegmentGenerationTarget = ref<ScriptGenerationTarget | null>(null)" in workspace
    assert "function _startSegmentedGenerationTarget" in workspace
    assert "targetEpisodeNo?: number" in workspace
    assert "targetSceneNo?: number" in workspace
    assert "contentOverride?: string" in workspace

    request_body = workspace.split("function _buildRuleBackedScriptRequest", 1)[1].split("// ── 内部四段审阅", 1)[0]
    assert "const episodeNo = _normalizeEpisodeNo(options?.targetEpisodeNo ?? selectedEpisode.value)" in request_body
    assert "const sceneNo = _normalizeSceneNo(options?.targetSceneNo ?? selectedScene.value)" in request_body
    assert "episode_no: episodeNo" in request_body
    assert "scene_no: sceneNo" in request_body
    request_payload = request_body.split("return {", 1)[1].split("advanced_generation_routes:", 1)[0]
    assert "selectedEpisode.value" not in request_payload, (
        "生成请求进入 return payload 后不能再读取页面当前集数，否则切集会污染任务目标"
    )

    assert "function _activeSegmentPersistenceTarget()" in workspace
    assert "function _activeSegmentContentForSave()" in workspace
    assert "function _isActiveSegmentTargetSelected()" in workspace

    draft_ready_body = workspace.split("onSegmentDraftReady: async", 1)[1].split("approveSegment:", 1)[0]
    assert "const target = _activeSegmentPersistenceTarget()" in draft_ready_body
    assert "contentOverride: _activeSegmentContentForSave()" in draft_ready_body
    assert "targetEpisodeNo: target.episodeNo" in draft_ready_body
    assert "targetSceneNo: target.sceneNo" in draft_ready_body

    progress_body = workspace.split("function _currentScriptSegmentProgressSnapshot", 1)[1].split("function _persistCurrentSegmentProgress", 1)[0]
    assert "const target = _activeSegmentPersistenceTarget()" in progress_body
    assert "const content = _activeSegmentContentForSave()" in progress_body
    assert "episode_no: target.episodeNo" in progress_body
    assert "scene_no: target.sceneNo" in progress_body

    confirmed_changed_body = workspace.split("onConfirmedContentChanged: content =>", 1)[1].split("onSegmentDraftReady:", 1)[0]
    assert "activeSegmentDraftContent.value = content" in confirmed_changed_body
    assert "if (_isActiveSegmentTargetSelected())" in confirmed_changed_body
    assert "sceneContent.value = content" in confirmed_changed_body
