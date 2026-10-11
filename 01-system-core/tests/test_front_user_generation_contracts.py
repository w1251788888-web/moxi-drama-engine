from pathlib import Path

from app.models.step_version import StepDependency
from app.routers.projects.routes_generation import OutlineEpisodesGenerateRequest


ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app"
SRC = ROOT / "webui" / "src"


def test_step_dependency_serializes_downstream_version_id():
    dependency = StepDependency(
        id="dep-1",
        session_id="task-1",
        upstream_step="concept",
        upstream_version_id="up-v1",
        downstream_step="script_draft",
        downstream_version_id="down-v1",
        affected_scope='["episode_1"]',
    )

    payload = dependency.to_dict()

    assert payload["downstream_version_id"] == "down-v1"
    assert payload["affected_scope"] == ["episode_1"]


def test_outline_episode_generation_accepts_seed_analysis():
    req = OutlineEpisodesGenerateRequest(
        outline="A long enough outline for generation context.",
        target_episodes=3,
        seed_analysis={"sellingPoints": {"logline": "hook"}},
    )

    assert req.seed_analysis == {"sellingPoints": {"logline": "hook"}}


def test_task_status_contract_allows_cancelled():
    task_service = (APP / "services" / "task_service.py").read_text(encoding="utf-8")
    tasks_router = (APP / "routers" / "tasks.py").read_text(encoding="utf-8")

    assert '"cancelled"' in task_service
    assert "planning/active/in_progress/completed/archived/cancelled" in tasks_router


def test_testing_script_routes_accept_project_actor_auth():
    for filename in ("scene_routes.py", "audit_routes.py", "scene_edit_routes.py"):
        text = (APP / "routers" / "short_drama" / filename).read_text(encoding="utf-8")
        assert "verify_project_actor" in text
        assert "verify_admin" not in text
        assert "_get_project_for_actor_or_404" in text or "ensure_short_drama_project_access" in text


def test_frontend_stream_forwards_user_session_header():
    stream = (
        SRC
        / "features"
        / "workspace"
        / "composables"
        / "useRuleBackedScriptStream.ts"
    ).read_text(encoding="utf-8")
    workspace = (SRC / "views" / "ProjectWorkspaceView.vue").read_text(encoding="utf-8")

    assert "userSessionToken?: string | null" in stream
    assert "'X-User-Session': userSessionToken" in stream
    assert "'X-Admin-Token': token" in stream
    assert "userSessionToken: auth.userSession?.session_token" in workspace
    assert "project_id: projectId.value" in workspace


def test_generation_job_charges_before_exposing_result():
    text = (APP / "routers" / "projects" / "routes_generation.py").read_text(encoding="utf-8")

    charge_index = text.index("charge_access_key_for_generation(")
    result_path_index = text.index("job.result_path = str(result_path)")
    completed_index = text.index('job.status = "completed"')

    assert charge_index < result_path_index < completed_index
