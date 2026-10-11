from pathlib import Path

from app.routers.projects._helpers import _normalize_project_config_payload
from app.routers.projects._schemas import ProjectConfig


ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text()


def test_project_config_has_no_formal_80_episode_default():
    config = ProjectConfig()

    assert config.confirmed_total_episodes is None
    assert config.suggested_total_episodes is None
    assert config.episode_count_status == "unconfirmed"
    assert config.total_episodes is None


def test_project_config_normalizer_does_not_invent_80_without_user_confirmation():
    normalized = _normalize_project_config_payload({})

    assert normalized["confirmed_total_episodes"] is None
    assert normalized["suggested_total_episodes"] is None
    assert normalized["episode_count_status"] == "unconfirmed"
    assert normalized.get("total_episodes") in (None, 0)


def test_project_config_normalizer_preserves_user_confirmed_episode_count_as_truth():
    normalized = _normalize_project_config_payload({
        "confirmed_total_episodes": 12,
        "episode_count_confirmation_source": "quick_start_prompt",
        "episode_count_confirmed_at": "2026-06-15T00:00:00.000Z",
    })

    assert normalized["confirmed_total_episodes"] == 12
    assert normalized["total_episodes"] == 12
    assert normalized["episode_count_status"] == "confirmed"
    assert normalized["episode_count_confirmation_source"] == "quick_start_prompt"


def test_project_config_normalizer_marks_legacy_total_as_needing_confirmation():
    normalized = _normalize_project_config_payload({"total_episodes": 80})

    assert normalized["confirmed_total_episodes"] is None
    assert normalized["suggested_total_episodes"] == 80
    assert normalized["episode_count_status"] == "legacy_needs_confirmation"
    assert normalized["total_episodes"] == 80


def test_backend_source_has_no_80_episode_default_in_formal_creation_chain():
    schemas = read("app/routers/projects/_schemas.py")
    helpers = read("app/routers/projects/_helpers.py")
    model = read("app/models/project_v2.py")
    routes = read("app/routers/projects/routes_projects.py")

    assert "total_episodes: int = Field(default=80" not in schemas
    assert 'payload["total_episodes"] = 80' not in helpers
    assert "total_episodes = Column(Integer, default=80)" not in model
    assert "total_episodes=req.config.total_episodes" not in routes


def test_generation_routes_do_not_default_formal_episode_count_to_30():
    source = read("app/routers/projects/routes_generation.py")
    step_routes = read("app/routers/short_drama/step_routes.py")
    rag_injection = read("app/services/short_drama_rag_injection.py")

    assert "target_episodes: int = Field(30" not in source
    assert "target_episodes or 30" not in source
    assert "episode_count_unconfirmed" in source
    assert "episode_count\") or 30" not in step_routes
    assert "episode_count\") or 30" not in rag_injection
    assert "_require_project_episode_count" in step_routes


def test_frontend_episode_count_contract_uses_confirmed_and_suggested_fields():
    api = read("webui/src/api/modules/projects.ts")
    rules = read("webui/src/features/workspace/composables/useOutlineWorkflow.ts")
    packet = read("webui/src/features/workspace/utils/standardOutlinePacket.ts")
    workspace = read("webui/src/views/ProjectWorkspaceView.vue")
    projects_view = read("webui/src/views/ProjectsView.vue")

    assert "confirmed_total_episodes" in api
    assert "suggested_total_episodes" in api
    assert "episode_count_status" in api
    assert "Number(raw?.total_episodes) || 80" not in rules
    assert "confirmed_total_episodes" in packet
    assert "suggested_total_episodes" in packet
    assert "episode_count_plan.total_episodes" not in packet.split("function resolveConfirmedEpisodeCount", 1)[1].split("}", 1)[0]
    assert "episodeCount: () => _effectiveUserConfirmedTotalEpisodes()" in workspace
    assert "completedTabs.value.has('chat')" not in workspace.split("function hasPreparedOutlineFromChat", 1)[1].split("}", 1)[0]
    assert "extractExplicitEpisodeCount" in projects_view


def test_script_generation_request_requires_confirmed_episode_count_without_fallbacks():
    source = read("webui/src/views/ProjectWorkspaceView.vue")
    body = source.split("function _buildRuleBackedScriptRequest", 1)[1].split("function _scriptSegmentProgressStore", 1)[0]

    assert "const confirmedEpisodeCount = _effectiveUserConfirmedTotalEpisodes()" in body
    assert "episode_count: confirmedEpisodeCount" in body
    assert "outlineData.value.episodes.length || project.value?.total_episodes" not in body
    assert "episodes.value.length || 1" not in body


def test_legacy_outline_editor_import_cannot_commit_main_chain_directly():
    source = read("webui/src/views/OutlineEditorView.vue")
    body = source.split("outline_state:", 1)[1].split("merge: true", 1)[0]

    assert "candidate_source: 'legacy_import'" in body
    assert "main_chain_committed: false" in body
    assert "downstream_generation_allowed: false" in body
    assert "main_chain_committed: true" not in body


def test_blocked_tab_switch_and_next_step_share_the_guarded_parent_route():
    workspace = read("webui/src/views/ProjectWorkspaceView.vue")
    switch_body = workspace.split("async function switchTab", 1)[1].split("async function importAndAnalyze", 1)[0]
    next_body = workspace.split("async function goToNextWorkspaceTab", 1)[1].split("async function switchTab", 1)[0]
    tabs_source = read("webui/src/features/workspace/composables/useWorkspaceTabs.ts")

    assert "_switchWorkspaceTab(tab)" in switch_body
    assert switch_body.index("if (tab !== 'chat' && tab !== 'outline'") < switch_body.index("_switchWorkspaceTab(tab)")
    assert "function switchTab(id: WorkspaceTabId)" in tabs_source
    assert "await switchTab(nextTab)" in next_body
    assert "if (activeTab.value === nextTab) markTabComplete(currentTab)" in next_body
    assert "@next=\"goToNextTab\"" not in workspace
