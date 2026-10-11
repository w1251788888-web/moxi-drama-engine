import json
import sys
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

sys.path.append(str(Path(__file__).resolve().parent))

from test_short_drama_scene_generation_jobs import (
    _research_chain_request,
    _seed_source_packet_backend_materials as _seed_backend_generation_materials,
    isolated_script_job_client,
)


def _assert_public_payload_has_no_internal_leak(payload: dict) -> None:
    serialized = json.dumps(payload, ensure_ascii=False).lower()
    for forbidden in (
        "provider",
        "model",
        "internal",
        "raw",
        "secret",
        "authorization",
        "credential",
        "session",
        "url",
    ):
        assert forbidden not in serialized


def _prepare_workspace(tmp_path, monkeypatch, name: str) -> None:
    from app.routers.projects import _helpers as project_helpers

    workspace_root = tmp_path / name
    workspace_root.mkdir()
    monkeypatch.setattr(project_helpers, "WORKSPACE_ROOT", workspace_root)
    monkeypatch.setattr(project_helpers, "LEGACY_WORKSPACE_ROOT", workspace_root)


def _create_logged_in_user_project(
    client,
    Session,
    *,
    owner_name: str,
    project_name: str,
    initial_credit: str = "1.00",
) -> tuple[dict, str]:
    from app.services.saas_access_service import create_access_key

    with Session() as db:
        user = create_access_key(owner_name=owner_name, initial_credit=Decimal(initial_credit), db=db)

    login = client.post("/api/user/access-key/login", json={"access_key": user.plain_key})
    assert login.status_code == 200, login.text
    headers = {"X-User-Session": login.json()["session_token"]}

    created = client.post(
        "/api/v2/projects/",
        json={"name": f"{project_name}-{uuid4().hex[:8]}", "config": {"total_episodes": 6}},
        headers=headers,
    )
    assert created.status_code == 200, created.text
    return {"user": user, "headers": headers}, created.json()["id"]


def test_job_start_recompiles_backend_packets_when_old_fields_are_spoofed(
    tmp_path,
    monkeypatch,
    isolated_script_job_client,
):
    from app.models.short_drama_generation_job import ShortDramaGenerationJob
    from app.routers.short_drama import scene_routes
    from app.services.short_drama_final_generation_contract import final_generation_contract_hash

    _, client, Session = isolated_script_job_client
    _prepare_workspace(tmp_path, monkeypatch, "package10-old-field-spoof-workspaces")
    actor, project_id = _create_logged_in_user_project(
        client,
        Session,
        owner_name="旧字段污染用户",
        project_name="旧字段污染项目",
    )
    _seed_backend_generation_materials(Session, project_id)

    async def fake_worker(_job_id):
        return None

    monkeypatch.setattr(scene_routes, "_script_scene_generation_job_run", fake_worker)
    fake_contract = {
        "source": "frontend_fake_final_generation_contract",
        "authority_trace": {
            "generation_source_packet": {
                "source": "frontend_fake_generation_source_packet",
            }
        },
        "blocking_conflicts": [
            {"field": "frontend_fake_conflict"},
        ],
        "final_generation_contract_hash": "",
    }
    fake_contract["final_generation_contract_hash"] = final_generation_contract_hash(fake_contract)

    start = client.post(
        "/api/admin/short-drama/testing/script-scene/jobs/start",
        json=_research_chain_request(
            project_id,
            previous_episode_briefs=[{"source": "frontend_fake_previous_brief"}],
            manual_edit_context={"source": "frontend_fake_manual_context"},
            episode_memory_cards=[{"source": "frontend_fake_memory_card"}],
            canon_packet={"source": "frontend_fake_canon"},
            generation_source_packet={
                "source": "frontend_fake_generation_source_packet",
                "blocking_issues": [],
            },
            final_generation_contract=fake_contract,
        ),
        headers=actor["headers"],
    )

    assert start.status_code == 200, start.text
    payload = start.json()
    assert payload["status"] != "blocked"

    with Session() as db:
        job = db.query(ShortDramaGenerationJob).filter(ShortDramaGenerationJob.project_id == project_id).one()
        request_payload = json.loads(job.request_json)
        source_packet = request_payload["generation_source_packet"]
        final_contract = request_payload["final_generation_contract"]
        assert source_packet["source"] == "backend_compiled_generation_source_packet"
        assert source_packet["authority_trace"]["frontend_packet"]["source"] == "compatibility_input_only"
        assert final_contract["authority_trace"]["generation_source_packet"]["source"] == "backend_compiled_generation_source_packet"
        assert final_contract["blocking_conflicts"] == []
        serialized = json.dumps(request_payload, ensure_ascii=False)
        assert "frontend_fake_generation_source_packet" not in serialized
        assert "frontend_fake_final_generation_contract" not in serialized


def test_legacy_sync_entry_blocks_source_packet_gap_before_model_call(
    tmp_path,
    monkeypatch,
    isolated_script_job_client,
):
    from app.routers.short_drama import scene_routes

    _, client, Session = isolated_script_job_client
    _prepare_workspace(tmp_path, monkeypatch, "package10-legacy-sync-block-workspaces")
    actor, project_id = _create_logged_in_user_project(
        client,
        Session,
        owner_name="旧同步入口用户",
        project_name="旧同步入口项目",
    )

    def model_must_not_run(*_args, **_kwargs):
        raise AssertionError("legacy sync entry must not call model before backend gate")

    monkeypatch.setattr(scene_routes, "generate_research_script_candidate", model_must_not_run)

    response = client.post(
        "/api/admin/short-drama/testing/script-scene",
        json=_research_chain_request(
            project_id,
            generation_source_packet={
                "source": "frontend_fake_generation_source_packet",
                "blocking_issues": [],
            },
            final_generation_contract={
                "source": "frontend_fake_final_generation_contract",
                "blocking_conflicts": [],
            },
        ),
        headers=actor["headers"],
    )

    assert response.status_code == 409, response.text
    detail = response.json()["detail"]
    assert detail["stage"] == "generation_source_packet"
    assert detail["retryable"] is False


def test_legacy_stream_entry_blocks_source_packet_gap_before_model_call(
    tmp_path,
    monkeypatch,
    isolated_script_job_client,
):
    from app.routers.short_drama import scene_routes

    _, client, Session = isolated_script_job_client
    _prepare_workspace(tmp_path, monkeypatch, "package10-legacy-stream-block-workspaces")
    actor, project_id = _create_logged_in_user_project(
        client,
        Session,
        owner_name="旧流式入口用户",
        project_name="旧流式入口项目",
    )

    def model_must_not_run(*_args, **_kwargs):
        raise AssertionError("legacy stream entry must not call model before backend gate")

    monkeypatch.setattr(scene_routes, "generate_research_script_candidate", model_must_not_run)

    response = client.post(
        "/api/admin/short-drama/testing/script-scene/stream",
        json=_research_chain_request(
            project_id,
            generation_source_packet={
                "source": "frontend_fake_generation_source_packet",
                "blocking_issues": [],
            },
            final_generation_contract={
                "source": "frontend_fake_final_generation_contract",
                "blocking_conflicts": [],
            },
        ),
        headers=actor["headers"],
    )

    assert response.status_code == 409, response.text
    detail = response.json()["detail"]
    assert detail["stage"] == "generation_source_packet"
    assert detail["retryable"] is False


def test_cross_user_cannot_start_or_read_another_users_script_jobs(
    tmp_path,
    monkeypatch,
    isolated_script_job_client,
):
    from app.models.short_drama_generation_job import ShortDramaGenerationJob
    from app.routers.short_drama import scene_routes

    _, client, Session = isolated_script_job_client
    _prepare_workspace(tmp_path, monkeypatch, "package10-cross-user-workspaces")
    owner, project_id = _create_logged_in_user_project(
        client,
        Session,
        owner_name="项目归属用户",
        project_name="跨用户隔离项目",
    )
    intruder, _ = _create_logged_in_user_project(
        client,
        Session,
        owner_name="无权访问用户",
        project_name="无关项目",
    )
    _seed_backend_generation_materials(Session, project_id)

    def worker_must_not_start(_job_id):
        raise AssertionError("cross-user start must not enqueue worker")

    monkeypatch.setattr(scene_routes, "_script_scene_generation_job_run", worker_must_not_start)

    denied_start = client.post(
        "/api/admin/short-drama/testing/script-scene/jobs/start",
        json=_research_chain_request(project_id),
        headers=intruder["headers"],
    )
    assert denied_start.status_code in {403, 404}, denied_start.text

    with Session() as db:
        assert db.query(ShortDramaGenerationJob).filter(ShortDramaGenerationJob.project_id == project_id).count() == 0
        db.add(ShortDramaGenerationJob(
            id="owner-candidate-job",
            project_id=project_id,
            owner_key=owner["user"].key_id,
            owner_is_admin=False,
            status="candidate_ready",
            episode_no=1,
            scene_no=1,
            public_message="候选稿已准备好，等待用户确认。",
            public_progress=100,
            result_json=json.dumps({
                "content": "安全占位候选文本",
                "char_count_excluding_punctuation": 8,
                "warnings": [],
            }, ensure_ascii=False),
        ))
        db.commit()

    denied_status = client.get(
        "/api/admin/short-drama/testing/script-scene/jobs/status/owner-candidate-job",
        headers=intruder["headers"],
    )
    assert denied_status.status_code == 404, denied_status.text

    denied_latest = client.get(
        "/api/admin/short-drama/testing/script-scene/jobs/latest",
        params={"project_id": project_id, "episode_no": 1, "scene_no": 1},
        headers=intruder["headers"],
    )
    assert denied_latest.status_code in {403, 404}, denied_latest.text


def test_same_user_different_projects_do_not_reuse_active_job(
    tmp_path,
    monkeypatch,
    isolated_script_job_client,
):
    from app.models.short_drama_generation_job import ShortDramaGenerationJob
    from app.routers.short_drama import scene_routes

    _, client, Session = isolated_script_job_client
    _prepare_workspace(tmp_path, monkeypatch, "package10-cross-project-workspaces")
    actor, first_project_id = _create_logged_in_user_project(
        client,
        Session,
        owner_name="多项目用户",
        project_name="第一个项目",
    )
    second_created = client.post(
        "/api/v2/projects/",
        json={"name": f"第二个项目-{uuid4().hex[:8]}", "config": {"total_episodes": 6}},
        headers=actor["headers"],
    )
    assert second_created.status_code == 200, second_created.text
    second_project_id = second_created.json()["id"]
    _seed_backend_generation_materials(Session, first_project_id)
    _seed_backend_generation_materials(Session, second_project_id)

    with Session() as db:
        db.add(ShortDramaGenerationJob(
            id="first-project-active-job",
            project_id=first_project_id,
            owner_key=actor["user"].key_id,
            owner_is_admin=False,
            status="running",
            episode_no=1,
            scene_no=1,
            public_message="第一个项目正在运行。",
            public_progress=42,
            request_json=json.dumps(_research_chain_request(first_project_id), ensure_ascii=False),
        ))
        db.commit()

    async def fake_worker(_job_id):
        return None

    monkeypatch.setattr(scene_routes, "_script_scene_generation_job_run", fake_worker)

    start = client.post(
        "/api/admin/short-drama/testing/script-scene/jobs/start",
        json=_research_chain_request(second_project_id),
        headers=actor["headers"],
    )

    assert start.status_code == 200, start.text
    payload = start.json()
    assert payload["job_id"] != "first-project-active-job"

    with Session() as db:
        jobs = db.query(ShortDramaGenerationJob).all()
        assert len(jobs) == 2
        second_job = db.query(ShortDramaGenerationJob).filter(
            ShortDramaGenerationJob.project_id == second_project_id,
        ).one()
        assert second_job.id == payload["job_id"]


def test_admin_entry_cannot_bypass_source_packet_gate_or_start_worker(
    tmp_path,
    monkeypatch,
    isolated_script_job_client,
):
    from app.models.short_drama_generation_job import ShortDramaGenerationJob
    from app.routers.admin import create_admin_token
    from app.routers.short_drama import scene_routes

    _, client, Session = isolated_script_job_client
    _prepare_workspace(tmp_path, monkeypatch, "package10-admin-gate-workspaces")
    _, project_id = _create_logged_in_user_project(
        client,
        Session,
        owner_name="管理员边界项目用户",
        project_name="管理员边界项目",
    )
    with Session() as db:
        admin_token = create_admin_token(db)

    def worker_must_not_start(_job_id):
        raise AssertionError("admin gate must not enqueue worker when source packet blocks")

    def model_must_not_run(*_args, **_kwargs):
        raise AssertionError("admin gate must not call model when source packet blocks")

    monkeypatch.setattr(scene_routes, "_script_scene_generation_job_run", worker_must_not_start)
    monkeypatch.setattr(scene_routes, "generate_research_script_candidate", model_must_not_run)

    start = client.post(
        "/api/admin/short-drama/testing/script-scene/jobs/start",
        json=_research_chain_request(project_id),
        headers={"X-Admin-Token": admin_token},
    )

    assert start.status_code == 200, start.text
    payload = start.json()
    assert payload["status"] == "blocked"
    assert payload["public_progress"] == 100
    assert payload["user_action_required"] == "complete_generation_source_packet"
    _assert_public_payload_has_no_internal_leak(payload)

    with Session() as db:
        job = db.query(ShortDramaGenerationJob).filter(ShortDramaGenerationJob.project_id == project_id).one()
        assert job.status == "blocked"


def test_research_and_edit_entrypoints_do_not_write_official_source():
    root = Path(__file__).resolve().parents[1]
    for relative_path in (
        "app/routers/short_drama/advanced_generation_routes.py",
        "app/routers/short_drama/scene_edit_routes.py",
    ):
        source = (root / relative_path).read_text(encoding="utf-8")
        assert "ContentVersion(" not in source
        assert "EvidenceEvent(" not in source
        assert "episode_locked" not in source
        assert "scene_number=0" not in source
