import json
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest


@pytest.fixture()
def isolated_script_job_client(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app import database
    from app.database import get_db
    from app.main import app

    engine = create_engine(
        f"sqlite:///{tmp_path / 'short-drama-generation-jobs.db'}",
        connect_args={"check_same_thread": False},
    )
    Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    database.Base.metadata.create_all(bind=engine)

    monkeypatch.setattr(database, "engine", engine)
    monkeypatch.setattr(database, "SessionLocal", Session)

    def override_db():
        db = Session()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_db
    try:
        yield app, TestClient(app), Session
    finally:
        app.dependency_overrides.pop(get_db, None)
        engine.dispose()


def _research_chain_request(project_id: str, **updates) -> dict:
    payload = {
        "project_id": project_id,
        "brief": "林若岚守住示例家庭剧",
        "episode_no": 1,
        "episode_summary": "林若岚发现旧字据。",
        "advanced_generation_mode": True,
        "advanced_generation_providers": {
            "logic": {"provider": "deepseek", "model": "deepseek-v4-pro"},
            "creative": {"provider": "kimi", "model": "kimi-k2.6"},
            "review": {"provider": "deepseek", "model": "deepseek-v4-pro"},
        },
    }
    payload.update(updates)
    return payload


def _seed_source_packet_backend_materials(
    Session,
    project_id: str,
    *,
    confirmed_total_episodes: int = 3,
) -> None:
    import json

    from app.models.project_v2 import ProjectV2
    from app.services import workspace_service

    with Session() as db:
        project = db.query(ProjectV2).filter(ProjectV2.id == project_id).first()
        assert project is not None
        config = project.get_config()
        config["confirmed_total_episodes"] = confirmed_total_episodes
        config["total_episodes"] = confirmed_total_episodes
        project.set_config(config)
        workspace = Path(project.workspace_path)
        workspace_service.WORKSPACE_ROOT = workspace.parent
        workspace_service.LEGACY_WORKSPACE_ROOT = workspace.parent
        workspace.mkdir(parents=True, exist_ok=True)
        project_json = workspace / "project.json"
        payload = {}
        if project_json.exists():
            payload = json.loads(project_json.read_text(encoding="utf-8") or "{}")
        payload["characters"] = [{"name": "backend-character"}]
        payload["workflow_context"] = {
            "outline_state": {"source": "backend-outline-state"},
            "materials": [{"id": "material-1"}],
        }
        payload["state_cards"] = {"episode_1": {"status": "ready"}}
        project_json.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        db.add(project)
        db.commit()


def _seed_source_packet_locked_official_source(
    Session,
    project_id: str,
    *,
    episode_number: int = 1,
) -> str:
    import hashlib

    from app.models.evidence import EvidenceEvent
    from app.models.project_v2 import ContentVersion, Episode, ProjectV2

    with Session() as db:
        project = db.query(ProjectV2).filter(ProjectV2.id == project_id).first()
        assert project is not None
        workspace = Path(project.workspace_path)
        workspace.mkdir(parents=True, exist_ok=True)
        official_dir = workspace / "official"
        official_dir.mkdir(parents=True, exist_ok=True)
        content_path = official_dir / f"episode-{episode_number}-locked.md"
        content = f"safe locked official episode {episode_number}"
        content_path.write_text(content, encoding="utf-8")
        content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
        db.add(Episode(
            project_id=project_id,
            episode_number=episode_number,
            status="completed",
            title=f"Episode {episode_number}",
        ))
        version = ContentVersion(
            id=f"locked-version-ep{episode_number}-{uuid4().hex[:8]}",
            project_id=project_id,
            episode_number=episode_number,
            scene_number=0,
            version_code="v001",
            content_path=str(content_path),
            content_hash=content_hash,
        )
        db.add(version)
        db.flush()
        db.add(EvidenceEvent(
            project_id=project_id,
            event_type="episode_locked",
            target_type="episode",
            target_id=str(episode_number),
            content_version_id=version.id,
            content_hash=content_hash,
            summary="episode locked for source packet test",
        ))
        db.commit()
        return version.id


def _spoofed_previous_episode_brief(previous_episode_no: int = 1) -> dict:
    return {
        "source": "episode_locked_content_version",
        "previous_episode_no": previous_episode_no,
        "content_version_id": f"frontend-spoofed-version-{previous_episode_no}",
        "content_hash": "a" * 64,
        "episode_locked_event_id": f"frontend-spoofed-event-{previous_episode_no}",
        "ready": True,
    }


def test_source_packet_preview_ready_does_not_create_generation_job(
    tmp_path,
    monkeypatch,
    isolated_script_job_client,
):
    from app.models.short_drama_generation_job import ShortDramaGenerationJob
    from app.routers.projects import _helpers as project_helpers
    from app.services.saas_access_service import create_access_key

    _, client, Session = isolated_script_job_client
    workspace_root = tmp_path / "source-packet-preview-ready-workspaces"
    workspace_root.mkdir()
    monkeypatch.setattr(project_helpers, "WORKSPACE_ROOT", workspace_root)
    monkeypatch.setattr(project_helpers, "LEGACY_WORKSPACE_ROOT", workspace_root)

    with Session() as db:
        user = create_access_key(owner_name="preview-ready-user", initial_credit=Decimal("1.00"), db=db)

    login = client.post("/api/user/access-key/login", json={"access_key": user.plain_key})
    assert login.status_code == 200, login.text
    headers = {"X-User-Session": login.json()["session_token"]}

    created = client.post(
        "/api/v2/projects/",
        json={
            "name": f"preview-ready-{uuid4().hex[:8]}",
            "config": {"confirmed_total_episodes": 3, "total_episodes": 3},
        },
        headers=headers,
    )
    assert created.status_code == 200, created.text
    project_id = created.json()["id"]
    _seed_source_packet_backend_materials(Session, project_id)

    with Session() as db:
        before_count = db.query(ShortDramaGenerationJob).count()

    preview = client.post(
        "/api/admin/short-drama/testing/script-scene/source-packet/preview",
        json=_research_chain_request(project_id, episode_no=1, scene_no=1),
        headers=headers,
    )

    assert preview.status_code == 200, preview.text
    payload = preview.json()
    assert payload["status"] == "ready"
    assert payload["safe_summary"]["source"] == "backend_compiled_generation_source_packet"
    assert payload["safe_summary"]["episode_no"] == 1
    assert payload["blocking_issues"] == []
    assert isinstance(payload["warnings"], list)

    with Session() as db:
        after_count = db.query(ShortDramaGenerationJob).count()
    assert after_count == before_count


def test_source_packet_preview_blocks_missing_previous_official_source(
    tmp_path,
    monkeypatch,
    isolated_script_job_client,
):
    from app.models.short_drama_generation_job import ShortDramaGenerationJob
    from app.routers.projects import _helpers as project_helpers
    from app.services.saas_access_service import create_access_key

    _, client, Session = isolated_script_job_client
    workspace_root = tmp_path / "source-packet-preview-blocked-workspaces"
    workspace_root.mkdir()
    monkeypatch.setattr(project_helpers, "WORKSPACE_ROOT", workspace_root)
    monkeypatch.setattr(project_helpers, "LEGACY_WORKSPACE_ROOT", workspace_root)

    with Session() as db:
        user = create_access_key(owner_name="preview-blocked-user", initial_credit=Decimal("1.00"), db=db)

    login = client.post("/api/user/access-key/login", json={"access_key": user.plain_key})
    assert login.status_code == 200, login.text
    headers = {"X-User-Session": login.json()["session_token"]}

    created = client.post(
        "/api/v2/projects/",
        json={
            "name": f"preview-blocked-{uuid4().hex[:8]}",
            "config": {"confirmed_total_episodes": 3, "total_episodes": 3},
        },
        headers=headers,
    )
    assert created.status_code == 200, created.text
    project_id = created.json()["id"]
    _seed_source_packet_backend_materials(Session, project_id)

    with Session() as db:
        before_count = db.query(ShortDramaGenerationJob).count()

    preview = client.post(
        "/api/admin/short-drama/testing/script-scene/source-packet/preview",
        json=_research_chain_request(project_id, episode_no=2, scene_no=1),
        headers=headers,
    )

    assert preview.status_code == 200, preview.text
    payload = preview.json()
    assert payload["status"] == "blocked"
    assert payload["reason_code"] == "previous_official_source_missing"
    assert payload["detail"]["episode_no"] == 2

    with Session() as db:
        after_count = db.query(ShortDramaGenerationJob).count()
    assert after_count == before_count


def test_source_packet_preview_rejects_frontend_previous_brief_spoof(
    tmp_path,
    monkeypatch,
    isolated_script_job_client,
):
    from app.models.short_drama_generation_job import ShortDramaGenerationJob
    from app.routers.projects import _helpers as project_helpers
    from app.services.saas_access_service import create_access_key

    _, client, Session = isolated_script_job_client
    workspace_root = tmp_path / "source-packet-preview-spoof-workspaces"
    workspace_root.mkdir()
    monkeypatch.setattr(project_helpers, "WORKSPACE_ROOT", workspace_root)
    monkeypatch.setattr(project_helpers, "LEGACY_WORKSPACE_ROOT", workspace_root)

    with Session() as db:
        user = create_access_key(owner_name="preview-spoof-user", initial_credit=Decimal("1.00"), db=db)

    login = client.post("/api/user/access-key/login", json={"access_key": user.plain_key})
    assert login.status_code == 200, login.text
    headers = {"X-User-Session": login.json()["session_token"]}

    created = client.post(
        "/api/v2/projects/",
        json={
            "name": f"preview-spoof-{uuid4().hex[:8]}",
            "config": {"confirmed_total_episodes": 3, "total_episodes": 3},
        },
        headers=headers,
    )
    assert created.status_code == 200, created.text
    project_id = created.json()["id"]
    _seed_source_packet_backend_materials(Session, project_id)

    with Session() as db:
        before_count = db.query(ShortDramaGenerationJob).count()

    preview = client.post(
        "/api/admin/short-drama/testing/script-scene/source-packet/preview",
        json=_research_chain_request(
            project_id,
            episode_no=2,
            scene_no=1,
            previous_episode_briefs=[_spoofed_previous_episode_brief()],
        ),
        headers=headers,
    )

    assert preview.status_code == 200, preview.text
    payload = preview.json()
    assert payload["status"] == "blocked"
    assert payload["reason_code"] in {
        "previous_official_source_missing",
        "previous_official_source_required",
    }

    with Session() as db:
        after_count = db.query(ShortDramaGenerationJob).count()
    assert after_count == before_count


def test_script_scene_jobs_start_blocks_when_previous_official_source_missing_without_background_task(
    tmp_path,
    monkeypatch,
    isolated_script_job_client,
):
    import json

    from app.models.short_drama_generation_job import ShortDramaGenerationJob
    from app.routers.projects import _helpers as project_helpers
    from app.routers.short_drama import scene_routes
    from app.services.saas_access_service import create_access_key

    _, client, Session = isolated_script_job_client
    workspace_root = tmp_path / "jobs-start-ready-guard-blocked-workspaces"
    workspace_root.mkdir()
    monkeypatch.setattr(project_helpers, "WORKSPACE_ROOT", workspace_root)
    monkeypatch.setattr(project_helpers, "LEGACY_WORKSPACE_ROOT", workspace_root)

    with Session() as db:
        user = create_access_key(owner_name="ready-guard-blocked-user", initial_credit=Decimal("1.00"), db=db)

    login = client.post("/api/user/access-key/login", json={"access_key": user.plain_key})
    assert login.status_code == 200, login.text
    headers = {"X-User-Session": login.json()["session_token"]}

    created = client.post(
        "/api/v2/projects/",
        json={
            "name": f"ready-guard-blocked-{uuid4().hex[:8]}",
            "config": {"confirmed_total_episodes": 3, "total_episodes": 3},
        },
        headers=headers,
    )
    assert created.status_code == 200, created.text
    project_id = created.json()["id"]
    _seed_source_packet_backend_materials(Session, project_id)

    async def background_must_not_run(*_args, **_kwargs):
        raise AssertionError("blocked ready guard must not add background generation task")

    def model_must_not_run(*_args, **_kwargs):
        raise AssertionError("blocked ready guard must not call model generation")

    monkeypatch.setattr(scene_routes, "_script_scene_generation_job_run", background_must_not_run)
    monkeypatch.setattr(scene_routes, "generate_research_script_candidate", model_must_not_run)

    start = client.post(
        "/api/admin/short-drama/testing/script-scene/jobs/start",
        json=_research_chain_request(project_id, episode_no=2, scene_no=1),
        headers=headers,
    )

    assert start.status_code == 200, start.text
    payload = start.json()
    assert payload["status"] == "blocked"
    assert payload["public_progress"] == 100

    with Session() as db:
        jobs = db.query(ShortDramaGenerationJob).filter(ShortDramaGenerationJob.project_id == project_id).all()
        assert len(jobs) == 1
        job = jobs[0]
        assert job.status == "blocked"
        internal = json.loads(job.internal_json or "{}")
        request = json.loads(job.request_json or "{}")
    assert internal["stage"] == "generation_source_packet"
    assert internal["reason_code"] == "previous_official_source_missing"
    assert internal["ready_guard_passed"] is False
    assert internal["generation_source_safe_summary"]["blocking_issues_count"] >= 1
    assert request == {
        "project_id": project_id,
        "episode_no": 2,
        "scene_no": 1,
        "segment_id": "",
    }


def test_script_scene_jobs_start_rejects_frontend_previous_brief_spoof_before_pending(
    tmp_path,
    monkeypatch,
    isolated_script_job_client,
):
    from app.models.short_drama_generation_job import ShortDramaGenerationJob
    from app.routers.projects import _helpers as project_helpers
    from app.routers.short_drama import scene_routes
    from app.services.saas_access_service import create_access_key

    _, client, Session = isolated_script_job_client
    workspace_root = tmp_path / "jobs-start-ready-guard-spoof-workspaces"
    workspace_root.mkdir()
    monkeypatch.setattr(project_helpers, "WORKSPACE_ROOT", workspace_root)
    monkeypatch.setattr(project_helpers, "LEGACY_WORKSPACE_ROOT", workspace_root)

    with Session() as db:
        user = create_access_key(owner_name="ready-guard-spoof-user", initial_credit=Decimal("1.00"), db=db)

    login = client.post("/api/user/access-key/login", json={"access_key": user.plain_key})
    assert login.status_code == 200, login.text
    headers = {"X-User-Session": login.json()["session_token"]}

    created = client.post(
        "/api/v2/projects/",
        json={
            "name": f"ready-guard-spoof-{uuid4().hex[:8]}",
            "config": {"confirmed_total_episodes": 3, "total_episodes": 3},
        },
        headers=headers,
    )
    assert created.status_code == 200, created.text
    project_id = created.json()["id"]
    _seed_source_packet_backend_materials(Session, project_id)

    async def background_must_not_run(*_args, **_kwargs):
        raise AssertionError("spoofed previous brief must not add background generation task")

    monkeypatch.setattr(scene_routes, "_script_scene_generation_job_run", background_must_not_run)

    start = client.post(
        "/api/admin/short-drama/testing/script-scene/jobs/start",
        json=_research_chain_request(
            project_id,
            episode_no=2,
            scene_no=1,
            previous_episode_briefs=[_spoofed_previous_episode_brief()],
        ),
        headers=headers,
    )

    assert start.status_code == 200, start.text
    assert start.json()["status"] == "blocked"

    with Session() as db:
        jobs = db.query(ShortDramaGenerationJob).filter(ShortDramaGenerationJob.project_id == project_id).all()
    assert len(jobs) == 1
    assert jobs[0].status == "blocked"


def test_script_scene_jobs_start_ready_path_still_creates_pending_job_and_background_task(
    tmp_path,
    monkeypatch,
    isolated_script_job_client,
):
    from app.models.short_drama_generation_job import ShortDramaGenerationJob
    from app.routers.projects import _helpers as project_helpers
    from app.routers.short_drama import scene_routes
    from app.services.saas_access_service import create_access_key

    _, client, Session = isolated_script_job_client
    workspace_root = tmp_path / "jobs-start-ready-guard-ready-workspaces"
    workspace_root.mkdir()
    monkeypatch.setattr(project_helpers, "WORKSPACE_ROOT", workspace_root)
    monkeypatch.setattr(project_helpers, "LEGACY_WORKSPACE_ROOT", workspace_root)

    with Session() as db:
        user = create_access_key(owner_name="ready-guard-ready-user", initial_credit=Decimal("1.00"), db=db)

    login = client.post("/api/user/access-key/login", json={"access_key": user.plain_key})
    assert login.status_code == 200, login.text
    headers = {"X-User-Session": login.json()["session_token"]}

    created = client.post(
        "/api/v2/projects/",
        json={
            "name": f"ready-guard-ready-{uuid4().hex[:8]}",
            "config": {"confirmed_total_episodes": 3, "total_episodes": 3},
        },
        headers=headers,
    )
    assert created.status_code == 200, created.text
    project_id = created.json()["id"]
    _seed_source_packet_backend_materials(Session, project_id)

    background_calls: list[str] = []

    async def fake_background(job_id: str):
        background_calls.append(job_id)

    monkeypatch.setattr(scene_routes, "_script_scene_generation_job_run", fake_background)

    start = client.post(
        "/api/admin/short-drama/testing/script-scene/jobs/start",
        json=_research_chain_request(project_id, episode_no=1, scene_no=1),
        headers=headers,
    )

    assert start.status_code == 200, start.text
    payload = start.json()
    assert payload["status"] == "pending"
    assert payload["job_id"]
    assert background_calls == [payload["job_id"]]

    with Session() as db:
        job = db.query(ShortDramaGenerationJob).filter(ShortDramaGenerationJob.id == payload["job_id"]).one()
    assert job.status == "pending"


def _create_ready_script_job_that_fails_text_generation(tmp_path, monkeypatch, isolated_script_job_client):
    import json

    from app.models.short_drama_generation_job import ShortDramaGenerationJob
    from app.routers.projects import _helpers as project_helpers
    from app.routers.short_drama import scene_routes
    from app.services.saas_access_service import create_access_key
    from app.services.text_generation_service import TextGenerationError

    _, client, Session = isolated_script_job_client
    workspace_root = tmp_path / f"script-scene-safe-observability-{uuid4().hex[:8]}"
    workspace_root.mkdir()
    monkeypatch.setattr(project_helpers, "WORKSPACE_ROOT", workspace_root)
    monkeypatch.setattr(project_helpers, "LEGACY_WORKSPACE_ROOT", workspace_root)

    with Session() as db:
        user = create_access_key(owner_name="安全观测用户", initial_credit=Decimal("1.00"), db=db)

    login = client.post("/api/user/access-key/login", json={"access_key": user.plain_key})
    assert login.status_code == 200, login.text
    headers = {"X-User-Session": login.json()["session_token"]}

    created = client.post(
        "/api/v2/projects/",
        json={
            "name": f"安全观测项目-{uuid4().hex[:8]}",
            "description": "safe failure observability",
            "project_type": "真人短剧-女频",
            "audience_axis": "女频",
            "genre_main": "家庭",
            "config": {"confirmed_total_episodes": 3, "total_episodes": 3},
        },
        headers=headers,
    )
    assert created.status_code == 200, created.text
    project_id = created.json()["id"]
    _seed_source_packet_backend_materials(Session, project_id)

    async def fake_rag(*_args, **_kwargs):
        return []

    def fake_generate_research_chain(*_args, **_kwargs):
        raise TextGenerationError("unit-test generation failure")

    monkeypatch.setattr(scene_routes, "apply_rag_injection", fake_rag)
    monkeypatch.setattr(scene_routes, "generate_research_script_candidate", fake_generate_research_chain)

    start = client.post(
        "/api/admin/short-drama/testing/script-scene/jobs/start",
        json=_research_chain_request(
            project_id,
            episode_no=1,
            scene_no=1,
            episode_count=3,
            segment_id="hook",
            characters=[{"name": "backend-character"}],
            materials=[{"id": "material-1"}],
            state_cards={"episode_1": {"status": "ready"}},
        ),
        headers=headers,
    )
    assert start.status_code == 200, start.text
    job_id = start.json()["job_id"]

    status = client.get(
        f"/api/admin/short-drama/testing/script-scene/jobs/status/{job_id}",
        headers=headers,
    )
    assert status.status_code == 200, status.text

    with Session() as db:
        job = db.query(ShortDramaGenerationJob).filter(ShortDramaGenerationJob.id == job_id).first()
        assert job is not None
        internal = json.loads(job.internal_json or "{}")

    return status.json(), internal


def test_script_scene_failed_job_records_safe_failure_observability(
    tmp_path,
    monkeypatch,
    isolated_script_job_client,
):
    payload, internal = _create_ready_script_job_that_fails_text_generation(
        tmp_path,
        monkeypatch,
        isolated_script_job_client,
    )

    assert payload["status"] == "failed"
    assert payload["safe_failure_subtype"] == "text_generation_failed"
    assert payload["reason_code"] == "text_generation_failed"
    assert internal["safe_failure_subtype"] == "text_generation_failed"
    assert internal["reason_code"] == "text_generation_failed"

    expected = {
        "text_generation_detail_category": "unknown_text_generation_error",
        "text_generation_failure_family": "provider_or_runtime",
        "text_generation_failure_source": "provider_call",
        "exception_class_safe": "TextGenerationError",
        "provider_call_boundary": "during_provider_call",
        "candidate_delivery_state": "no_candidate_delivered",
        "safe_failure_observation_version": "v2",
        "text_generation_unknown_reason": "classifier_no_specific_match",
        "text_generation_stage": "text_generation",
        "terminal_write_reason": "text_generation_error",
        "failure_observed_at": "text_generation_exception",
        "http_status_bucket": "none",
        "timeout_bucket": "none",
        "retry_count_bucket": "unknown",
    }
    for key, value in expected.items():
        assert internal[key] == value
        assert payload[key] == value

    serialized = json.dumps({"payload": payload, "internal": internal}, ensure_ascii=False, sort_keys=True)
    for token in [
        "raw_prompt",
        "raw_request",
        "raw_response",
        "raw_error",
        "provider_url",
        "api_key",
        "Authorization",
        "Bearer",
        "credential",
        "secret",
        "session",
        "unit-test generation failure",
    ]:
        assert token not in serialized


def test_script_scene_ready_job_persists_generation_source_safe_summary(
    tmp_path,
    monkeypatch,
    isolated_script_job_client,
):
    payload, internal = _create_ready_script_job_that_fails_text_generation(
        tmp_path,
        monkeypatch,
        isolated_script_job_client,
    )

    summary = payload["generation_source_safe_summary"]
    assert internal["generation_source_safe_summary"] == summary
    assert internal["ready_guard_passed"] is True
    assert payload["ready_guard_passed"] is True
    assert summary["episode_no"] == 1
    assert summary["scene_no"] == 1
    assert summary["segment_id"] == "hook"
    assert summary["blocking_issues_count"] == 0
    assert summary["warnings_count"] == 0
    assert summary["previous_episode_continuity"]["source"] == "series_start"
    assert summary["previous_episode_continuity"]["ready"] is True


def test_script_scene_job_status_expires_stale_running_job_after_restart(
    tmp_path,
    monkeypatch,
    isolated_script_job_client,
):
    from datetime import datetime, timedelta

    from app.models.project_v2 import ContentVersion, Scene
    from app.models.short_drama_generation_job import ShortDramaGenerationJob
    from app.routers.projects import _helpers as project_helpers
    from app.services.saas_access_service import create_access_key

    _, client, Session = isolated_script_job_client
    workspace_root = tmp_path / "script-scene-stale-running-safe-workspaces"
    workspace_root.mkdir()
    monkeypatch.setattr(project_helpers, "WORKSPACE_ROOT", workspace_root)
    monkeypatch.setattr(project_helpers, "LEGACY_WORKSPACE_ROOT", workspace_root)

    with Session() as db:
        user = create_access_key(owner_name="stale running safe user", initial_credit=Decimal("1.00"), db=db)

    login = client.post("/api/user/access-key/login", json={"access_key": user.plain_key})
    assert login.status_code == 200, login.text
    headers = {"X-User-Session": login.json()["session_token"]}
    stale_project_id = "stale-running-safe-project"
    fresh_project_id = "fresh-running-safe-project"
    safe_summary = {
        "episode_no": 1,
        "scene_no": 1,
        "segment_id": "validation",
        "previous_episode_continuity": {"source": "series_start", "ready": True},
        "blocking_issues_count": 0,
        "warnings_count": 0,
    }

    with Session() as db:
        db.add(ShortDramaGenerationJob(
            id="stale-running-safe-job",
            project_id=stale_project_id,
            owner_key=user.key_id,
            owner_is_admin=False,
            status="running",
            episode_no=1,
            scene_no=1,
            public_message="正在生成本集正文...",
            public_progress=65,
            request_json=json.dumps({
                "project_id": stale_project_id,
                "episode_no": 1,
                "scene_no": 1,
                "segment_id": "validation",
            }, ensure_ascii=False),
            internal_json=json.dumps({
                "stage": "text_generation",
                "current_step_id": "W1_writer_validation",
                "ready_guard_passed": True,
                "generation_source_safe_summary": safe_summary,
            }, ensure_ascii=False),
            created_at=datetime.now() - timedelta(minutes=20),
            updated_at=datetime.now() - timedelta(minutes=20),
        ))
        db.add(ShortDramaGenerationJob(
            id="fresh-running-safe-job",
            project_id=fresh_project_id,
            owner_key=user.key_id,
            owner_is_admin=False,
            status="running",
            episode_no=1,
            scene_no=1,
            public_message="正在生成本集正文...",
            public_progress=65,
            internal_json=json.dumps({
                "stage": "text_generation",
                "ready_guard_passed": True,
                "generation_source_safe_summary": safe_summary,
            }, ensure_ascii=False),
            created_at=datetime.now() - timedelta(minutes=5),
            updated_at=datetime.now() - timedelta(minutes=5),
        ))
        db.commit()

    stale_status = client.get(
        "/api/admin/short-drama/testing/script-scene/jobs/status/stale-running-safe-job",
        headers=headers,
    )
    assert stale_status.status_code == 200, stale_status.text
    stale_payload = stale_status.json()
    serialized = json.dumps(stale_payload, ensure_ascii=False, sort_keys=True)
    assert stale_payload["status"] == "failed"
    assert stale_payload["candidate_returned_to_user"] is False
    assert stale_payload["candidate"] == {}
    assert stale_payload["safe_failure_subtype"] == "stale_running_job"
    assert stale_payload["reason_code"] == "stale_running_job"
    assert stale_payload["ready_guard_passed"] is True
    assert stale_payload["generation_source_safe_summary"] == safe_summary
    assert "raw" not in serialized.lower()
    assert "provider" not in serialized.lower()

    fresh_status = client.get(
        "/api/admin/short-drama/testing/script-scene/jobs/status/fresh-running-safe-job",
        headers=headers,
    )
    assert fresh_status.status_code == 200, fresh_status.text
    fresh_payload = fresh_status.json()
    assert fresh_payload["status"] == "running"

    with Session() as db:
        stale_job = db.query(ShortDramaGenerationJob).filter(ShortDramaGenerationJob.id == "stale-running-safe-job").one()
        fresh_job = db.query(ShortDramaGenerationJob).filter(ShortDramaGenerationJob.id == "fresh-running-safe-job").one()
        internal = json.loads(stale_job.internal_json or "{}")
        assert stale_job.status == "failed"
        assert stale_job.result_json in {"", None}
        assert internal["safe_failure_subtype"] == "stale_running_job"
        assert internal["reason_code"] == "stale_running_job"
        assert internal["ready_guard_passed"] is True
        assert internal["generation_source_safe_summary"] == safe_summary
        assert fresh_job.status == "running"
        assert db.query(ContentVersion).filter(ContentVersion.project_id == stale_project_id).count() == 0
        assert db.query(ContentVersion).filter(
            ContentVersion.project_id == stale_project_id,
            ContentVersion.scene_number == 0,
        ).count() == 0
        assert db.query(Scene).count() == 0


def test_script_scene_job_auto_resolves_contract_reconciliation_before_model_call(
    tmp_path,
    monkeypatch,
    isolated_script_job_client,
):
    from app.routers.projects import _helpers as project_helpers
    from app.routers.short_drama import scene_routes
    from app.services.saas_access_service import create_access_key

    _, client, Session = isolated_script_job_client
    workspace_root = tmp_path / "script-scene-contract-conflict-workspaces"
    workspace_root.mkdir()
    monkeypatch.setattr(project_helpers, "WORKSPACE_ROOT", workspace_root)
    monkeypatch.setattr(project_helpers, "LEGACY_WORKSPACE_ROOT", workspace_root)

    with Session() as db:
        user = create_access_key(owner_name="合同冲突用户", initial_credit=Decimal("1.00"), db=db)

    login = client.post("/api/user/access-key/login", json={"access_key": user.plain_key})
    assert login.status_code == 200, login.text
    headers = {"X-User-Session": login.json()["session_token"]}

    created = client.post(
        "/api/v2/projects/",
        json={"name": f"合同冲突项目-{uuid4().hex[:8]}", "config": {"total_episodes": 3}},
        headers=headers,
    )
    assert created.status_code == 200, created.text
    project_id = created.json()["id"]
    _seed_source_packet_backend_materials(Session, project_id)
    _seed_source_packet_locked_official_source(Session, project_id, episode_number=12)

    async def fake_rag(*_args, **_kwargs):
        return []

    def fake_generate_research_chain(*_args, **_kwargs):
        return {
            "content": "SAFE_CONTRACT_RECONCILED_CANDIDATE",
            "char_count_excluding_punctuation": 34,
            "warnings": [],
            "blocking_issues": [],
            "benchmark_assessment": None,
            "continuity_assessment": None,
            "episode_memory_card": {"episode_no": 13},
            "canon_packet": {"locked_facts": ["SAFE_CONTRACT_RECONCILED_FACT"]},
        }

    monkeypatch.setattr(scene_routes, "apply_rag_injection", fake_rag)
    monkeypatch.setattr(scene_routes, "generate_research_script_candidate", fake_generate_research_chain)
    monkeypatch.setattr(scene_routes, "apply_scene_level_gate", lambda _req, approved, _contract: approved)

    start = client.post(
        "/api/admin/short-drama/testing/script-scene/jobs/start",
        json=_research_chain_request(
            project_id,
            episode_no=13,
            user_confirmed_generation_packet={
                "blueprint": {
                    "items": [
                        {"itemKey": "required_main_scene", "body": "东厢门口找到旧钥匙"},
                    ]
                }
            },
            episode_contract={
                "episode_no": 13,
                "must_happen": ["主场景必须落地：手艺人摆满旧零件的小屋"],
            },
        ),
        headers=headers,
    )

    assert start.status_code == 200, start.text
    start_payload = start.json()
    assert start_payload["status"] in {"pending", "running", "candidate_ready"}

    status = client.get(
        f"/api/admin/short-drama/testing/script-scene/jobs/status/{start_payload['job_id']}",
        headers=headers,
    )

    assert status.status_code == 200, status.text
    payload = status.json()
    assert payload["status"] == "candidate_ready"
    assert payload["candidate_returned_to_user"] is True
    assert payload["final_generation_contract_hash"]
    assert payload["contract_conflicts"]
    assert payload["blocking_conflicts"] == []
    assert all(item.get("auto_resolved") is True for item in payload["contract_conflicts"])


def test_script_scene_latest_job_status_restores_late_candidate_for_same_project_episode(
    tmp_path,
    monkeypatch,
    isolated_script_job_client,
):
    import json

    from app.models.short_drama_generation_job import ShortDramaGenerationJob
    from app.routers.projects import _helpers as project_helpers
    from app.services.saas_access_service import create_access_key

    _, client, Session = isolated_script_job_client
    workspace_root = tmp_path / "script-scene-latest-job-workspaces"
    workspace_root.mkdir()
    monkeypatch.setattr(project_helpers, "WORKSPACE_ROOT", workspace_root)
    monkeypatch.setattr(project_helpers, "LEGACY_WORKSPACE_ROOT", workspace_root)

    with Session() as db:
        user = create_access_key(owner_name="晚到候选用户", initial_credit=Decimal("1.00"), db=db)

    login = client.post("/api/user/access-key/login", json={"access_key": user.plain_key})
    assert login.status_code == 200, login.text
    headers = {"X-User-Session": login.json()["session_token"]}

    created = client.post(
        "/api/v2/projects/",
        json={"name": f"晚到候选项目-{uuid4().hex[:8]}", "config": {"total_episodes": 3}},
        headers=headers,
    )
    assert created.status_code == 200, created.text
    project_id = created.json()["id"]
    _seed_source_packet_backend_materials(Session, project_id)

    with Session() as db:
        db.add(ShortDramaGenerationJob(
            id="late-candidate-job",
            project_id=project_id,
            owner_key=user.key_id,
            owner_is_admin=False,
            status="candidate_review_required",
            episode_no=2,
            scene_no=1,
            public_message="已生成候选稿，但需要你确认修改后保存。",
            public_progress=100,
            result_json=json.dumps({
                "content": "【场2-1 日 内 示例家庭剧】\n林若岚：这份晚到候选稿必须能恢复。",
                "char_count_excluding_punctuation": 28,
                "warnings": ["字数超限 12 字：当前 1562，目标 1000-1550，已先放行。"],
                "rag_evidence": [{"kind": "dify", "count": 2}],
            }, ensure_ascii=False),
        ))
        db.commit()

    latest = client.get(
        "/api/admin/short-drama/testing/script-scene/jobs/latest",
        params={"project_id": project_id, "episode_no": 2, "scene_no": 1},
        headers=headers,
    )
    assert latest.status_code == 200, latest.text
    payload = latest.json()

    assert payload["job_id"] == "late-candidate-job"
    assert payload["status"] == "candidate_review_required"
    assert payload["candidate_returned_to_user"] is True
    assert payload["candidate_needs_user_confirmation"] is True
    assert payload["saved_as_canon"] is False
    assert payload["candidate"]["content"].startswith("【场2-1")
    assert payload["candidate"]["rag_evidence"] == [{"kind": "dify", "count": 2}]


def test_script_scene_latest_job_status_restores_project_member_candidate(
    tmp_path,
    monkeypatch,
    isolated_script_job_client,
):
    import json

    from app.models.collaboration import ProjectMember, ProjectPermission
    from app.models.short_drama_generation_job import ShortDramaGenerationJob
    from app.routers.projects import _helpers as project_helpers
    from app.services.saas_access_service import create_access_key

    _, client, Session = isolated_script_job_client
    workspace_root = tmp_path / "script-scene-member-latest-job-workspaces"
    workspace_root.mkdir()
    monkeypatch.setattr(project_helpers, "WORKSPACE_ROOT", workspace_root)
    monkeypatch.setattr(project_helpers, "LEGACY_WORKSPACE_ROOT", workspace_root)

    with Session() as db:
        owner = create_access_key(owner_name="候选创建者", initial_credit=Decimal("1.00"), db=db)
        reviewer = create_access_key(owner_name="项目协作者", initial_credit=Decimal("1.00"), db=db)

    owner_login = client.post("/api/user/access-key/login", json={"access_key": owner.plain_key})
    assert owner_login.status_code == 200, owner_login.text
    owner_headers = {"X-User-Session": owner_login.json()["session_token"]}

    created = client.post(
        "/api/v2/projects/",
        json={"name": f"成员恢复候选项目-{uuid4().hex[:8]}", "config": {"total_episodes": 3}},
        headers=owner_headers,
    )
    assert created.status_code == 200, created.text
    project_id = created.json()["id"]

    with Session() as db:
        member = ProjectMember(
            project_id=project_id,
            access_key_id=reviewer.key_id,
            role="co_writer",
            display_name="项目协作者",
            status="active",
        )
        db.add(member)
        db.flush()
        db.add(ProjectPermission(
            project_id=project_id,
            member_id=member.id,
            scope_type="project",
            scope_id="",
            permission="edit",
        ))
        db.add(ShortDramaGenerationJob(
            id="member-visible-candidate-job",
            project_id=project_id,
            owner_key=owner.key_id,
            owner_is_admin=False,
            status="candidate_ready",
            episode_no=2,
            scene_no=1,
            public_message="收尾段候选已生成。",
            public_progress=100,
            request_json=json.dumps({"segment_id": "resolution"}, ensure_ascii=False),
            result_json=json.dumps({
                "content": "收尾段：只用于测试同项目成员恢复候选。",
                "char_count_excluding_punctuation": 18,
            }, ensure_ascii=False),
        ))
        db.commit()

    reviewer_login = client.post("/api/user/access-key/login", json={"access_key": reviewer.plain_key})
    assert reviewer_login.status_code == 200, reviewer_login.text
    reviewer_headers = {"X-User-Session": reviewer_login.json()["session_token"]}

    latest = client.get(
        "/api/admin/short-drama/testing/script-scene/jobs/latest",
        params={
            "project_id": project_id,
            "episode_no": 2,
            "scene_no": 1,
            "segment_id": "resolution",
        },
        headers=reviewer_headers,
    )
    assert latest.status_code == 200, latest.text
    payload = latest.json()

    assert payload["job_id"] == "member-visible-candidate-job"
    assert payload["segment_id"] == "resolution"
    assert payload["candidate_returned_to_user"] is True
    assert payload["candidate"]["content"].startswith("收尾段")


def test_script_scene_job_status_marks_stale_running_job_failed_without_candidate(
    tmp_path,
    monkeypatch,
    isolated_script_job_client,
):
    import json
    from datetime import datetime, timedelta

    from app.models.short_drama_generation_job import ShortDramaGenerationJob
    from app.routers.projects import _helpers as project_helpers
    from app.services.saas_access_service import create_access_key

    _, client, Session = isolated_script_job_client
    workspace_root = tmp_path / "script-scene-stale-running-workspaces"
    workspace_root.mkdir()
    monkeypatch.setattr(project_helpers, "WORKSPACE_ROOT", workspace_root)
    monkeypatch.setattr(project_helpers, "LEGACY_WORKSPACE_ROOT", workspace_root)

    with Session() as db:
        user = create_access_key(owner_name="stale running user", initial_credit=Decimal("1.00"), db=db)

    login = client.post("/api/user/access-key/login", json={"access_key": user.plain_key})
    assert login.status_code == 200, login.text
    headers = {"X-User-Session": login.json()["session_token"]}

    stale_time = datetime.now() - timedelta(hours=2)
    with Session() as db:
        db.add(ShortDramaGenerationJob(
            id="stale-running-job",
            project_id="stale-project",
            owner_key=user.key_id,
            owner_is_admin=False,
            status="running",
            episode_no=4,
            scene_no=1,
            public_message="正在生成本集正文...",
            public_progress=45,
            internal_json=json.dumps({"current_step_id": "W1_writer_hook"}, ensure_ascii=False),
            created_at=stale_time,
            updated_at=stale_time,
        ))
        db.commit()

    status = client.get(
        "/api/admin/short-drama/testing/script-scene/jobs/status/stale-running-job",
        headers=headers,
    )

    assert status.status_code == 200, status.text
    payload = status.json()
    assert payload["status"] == "failed"
    assert payload["candidate_returned_to_user"] is False
    assert payload["public_progress"] == 100

    with Session() as db:
        job = db.query(ShortDramaGenerationJob).filter(ShortDramaGenerationJob.id == "stale-running-job").one()
        internal = json.loads(job.internal_json)
        assert internal["safe_failure_subtype"] == "stale_running_job"
        assert internal["reason_code"] == "stale_running_job"
        assert "raw" not in str(internal).lower()


def test_script_scene_job_start_reuses_active_job_instead_of_creating_duplicate(
    tmp_path,
    monkeypatch,
    isolated_script_job_client,
):
    import json

    from app.models.short_drama_generation_job import ShortDramaGenerationJob
    from app.routers.projects import _helpers as project_helpers
    from app.routers.short_drama import scene_routes
    from app.services.saas_access_service import create_access_key

    _, client, Session = isolated_script_job_client
    workspace_root = tmp_path / "script-scene-duplicate-reuse-workspaces"
    workspace_root.mkdir()
    monkeypatch.setattr(project_helpers, "WORKSPACE_ROOT", workspace_root)
    monkeypatch.setattr(project_helpers, "LEGACY_WORKSPACE_ROOT", workspace_root)

    with Session() as db:
        user = create_access_key(owner_name="duplicate reuse user", initial_credit=Decimal("1.00"), db=db)

    login = client.post("/api/user/access-key/login", json={"access_key": user.plain_key})
    assert login.status_code == 200, login.text
    headers = {"X-User-Session": login.json()["session_token"]}

    created = client.post(
        "/api/v2/projects/",
        json={"name": f"duplicate reuse project-{uuid4().hex[:8]}", "config": {"total_episodes": 4}},
        headers=headers,
    )
    assert created.status_code == 200, created.text
    project_id = created.json()["id"]
    _seed_source_packet_backend_materials(Session, project_id)

    with Session() as db:
        db.add(ShortDramaGenerationJob(
            id="active-reusable-job",
            project_id=project_id,
            owner_key=user.key_id,
            owner_is_admin=False,
            status="running",
            episode_no=1,
            scene_no=1,
            public_message="正在生成本集正文...",
            public_progress=45,
            request_json=json.dumps(_research_chain_request(project_id), ensure_ascii=False),
        ))
        db.commit()

    def job_worker_must_not_start(_job_id):
        raise AssertionError("duplicate start must reuse the active job and not enqueue a second worker")

    monkeypatch.setattr(scene_routes, "_script_scene_generation_job_run", job_worker_must_not_start)

    start = client.post(
        "/api/admin/short-drama/testing/script-scene/jobs/start",
        json=_research_chain_request(project_id),
        headers=headers,
    )

    assert start.status_code == 200, start.text
    payload = start.json()
    assert payload["job_id"] == "active-reusable-job"
    assert payload["status"] == "running"

    with Session() as db:
        jobs = db.query(ShortDramaGenerationJob).filter(ShortDramaGenerationJob.project_id == project_id).all()
        assert [job.id for job in jobs] == ["active-reusable-job"]


def test_script_scene_job_provider_timeout_fails_safely_without_candidate_or_raw_leakage(
    tmp_path,
    monkeypatch,
    isolated_script_job_client,
):
    import json

    from app.models.short_drama_generation_job import ShortDramaGenerationJob
    from app.routers.projects import _helpers as project_helpers
    from app.routers.short_drama import scene_routes
    from app.services.saas_access_service import create_access_key
    from app.services.text_generation_service import TextGenerationNetworkError

    _, client, Session = isolated_script_job_client
    workspace_root = tmp_path / "script-scene-provider-timeout-workspaces"
    workspace_root.mkdir()
    monkeypatch.setattr(project_helpers, "WORKSPACE_ROOT", workspace_root)
    monkeypatch.setattr(project_helpers, "LEGACY_WORKSPACE_ROOT", workspace_root)

    with Session() as db:
        user = create_access_key(owner_name="provider timeout user", initial_credit=Decimal("1.00"), db=db)

    login = client.post("/api/user/access-key/login", json={"access_key": user.plain_key})
    assert login.status_code == 200, login.text
    headers = {"X-User-Session": login.json()["session_token"]}

    created = client.post(
        "/api/v2/projects/",
        json={"name": f"provider-timeout-project-{uuid4().hex[:8]}", "config": {"total_episodes": 3}},
        headers=headers,
    )
    assert created.status_code == 200, created.text
    project_id = created.json()["id"]
    _seed_source_packet_backend_materials(Session, project_id)
    _seed_source_packet_locked_official_source(Session, project_id, episode_number=1)

    def timeout_generate(*_args, **_kwargs):
        raise TextGenerationNetworkError(
            "read timeout from https://provider.example with Authorization Bearer secret and protected text"
        )

    monkeypatch.setattr(scene_routes, "generate_research_script_candidate", timeout_generate)

    start = client.post(
        "/api/admin/short-drama/testing/script-scene/jobs/start",
        json=_research_chain_request(project_id, episode_no=2, scene_no=1),
        headers=headers,
    )
    assert start.status_code == 200, start.text
    job_id = start.json()["job_id"]

    status = client.get(
        f"/api/admin/short-drama/testing/script-scene/jobs/status/{job_id}",
        headers=headers,
    )
    assert status.status_code == 200, status.text
    payload = status.json()
    assert payload["status"] == "failed"
    assert not payload["candidate"]
    assert payload["candidate_returned_to_user"] is False

    with Session() as db:
        job = db.query(ShortDramaGenerationJob).filter(ShortDramaGenerationJob.id == job_id).one()
        internal = json.loads(job.internal_json)
        assert internal["stage"] == "text_generation"
        assert internal["safe_failure_subtype"] == "read_timeout"
        assert internal["provider_observability"]["safe_failure_subtype"] == "read_timeout"
        serialized = json.dumps(internal, ensure_ascii=False).lower()
        assert "provider.example" not in serialized
        assert "authorization" not in serialized
        assert "bearer" not in serialized
        assert "protected text" not in serialized


def test_script_scene_latest_job_status_rejects_orphan_candidate_result_target(tmp_path, monkeypatch, isolated_script_job_client):
    import json

    from app.models.short_drama_generation_job import ShortDramaGenerationJob
    from app.routers.projects import _helpers as project_helpers
    from app.services.saas_access_service import create_access_key

    _, client, Session = isolated_script_job_client
    workspace_root = tmp_path / "script-scene-orphan-candidate-workspaces"
    workspace_root.mkdir()
    monkeypatch.setattr(project_helpers, "WORKSPACE_ROOT", workspace_root)
    monkeypatch.setattr(project_helpers, "LEGACY_WORKSPACE_ROOT", workspace_root)

    with Session() as db:
        user = create_access_key(owner_name="orphan candidate user", initial_credit=Decimal("1.00"), db=db)

    login = client.post("/api/user/access-key/login", json={"access_key": user.plain_key})
    assert login.status_code == 200, login.text
    headers = {"X-User-Session": login.json()["session_token"]}

    created = client.post(
        "/api/v2/projects/",
        json={"name": f"orphan candidate project-{uuid4().hex[:8]}", "config": {"total_episodes": 4}},
        headers=headers,
    )
    assert created.status_code == 200, created.text
    project_id = created.json()["id"]

    with Session() as db:
        db.add(ShortDramaGenerationJob(
            id="orphan-candidate-job",
            project_id=project_id,
            owner_key=user.key_id,
            owner_is_admin=False,
            status="candidate_review_required",
            episode_no=2,
            scene_no=1,
            public_message="已生成候选稿，但需要你确认修改后保存。",
            public_progress=100,
            result_json=json.dumps({
                "content": "safe orphan candidate placeholder",
                "char_count_excluding_punctuation": 28,
                "job_target": {
                    "project_id": project_id,
                    "episode_no": 3,
                    "scene_no": 1,
                },
            }, ensure_ascii=False),
        ))
        db.commit()

    latest = client.get(
        "/api/admin/short-drama/testing/script-scene/jobs/latest",
        params={"project_id": project_id, "episode_no": 2, "scene_no": 1},
        headers=headers,
    )

    assert latest.status_code == 404
    assert "暂无可恢复候选稿" in latest.text

    with Session() as db:
        job = db.query(ShortDramaGenerationJob).filter(ShortDramaGenerationJob.id == "orphan-candidate-job").one()
        assert job.status == "failed"
        internal = json.loads(job.internal_json)
        assert internal["recovery"]["reason_code"] == "orphan_candidate_result_target_mismatch"


def test_script_scene_latest_job_status_filters_by_segment_id(
    tmp_path,
    monkeypatch,
    isolated_script_job_client,
):
    import json

    from app.models.short_drama_generation_job import ShortDramaGenerationJob
    from app.routers.projects import _helpers as project_helpers
    from app.services.saas_access_service import create_access_key

    _, client, Session = isolated_script_job_client
    workspace_root = tmp_path / "script-scene-segment-filter-workspaces"
    workspace_root.mkdir()
    monkeypatch.setattr(project_helpers, "WORKSPACE_ROOT", workspace_root)
    monkeypatch.setattr(project_helpers, "LEGACY_WORKSPACE_ROOT", workspace_root)

    with Session() as db:
        user = create_access_key(owner_name="分段候选用户", initial_credit=Decimal("1.00"), db=db)

    login = client.post("/api/user/access-key/login", json={"access_key": user.plain_key})
    assert login.status_code == 200, login.text
    headers = {"X-User-Session": login.json()["session_token"]}

    created = client.post(
        "/api/v2/projects/",
        json={"name": f"分段候选项目-{uuid4().hex[:8]}", "config": {"total_episodes": 3}},
        headers=headers,
    )
    assert created.status_code == 200, created.text
    project_id = created.json()["id"]

    with Session() as db:
        db.add_all([
            ShortDramaGenerationJob(
                id="hook-candidate-job",
                project_id=project_id,
                owner_key=user.key_id,
                owner_is_admin=False,
                status="candidate_ready",
                episode_no=1,
                scene_no=1,
                public_message="钩子段候选已生成。",
                public_progress=100,
                request_json=json.dumps({"segment_id": "hook"}, ensure_ascii=False),
                result_json=json.dumps({
                    "content": "钩子段：主角被刀抵住，还敢开口要锅。",
                    "char_count_excluding_punctuation": 18,
                }, ensure_ascii=False),
            ),
            ShortDramaGenerationJob(
                id="validation-candidate-job",
                project_id=project_id,
                owner_key=user.key_id,
                owner_is_admin=False,
                status="candidate_ready",
                episode_no=1,
                scene_no=1,
                public_message="验证段候选已生成。",
                public_progress=100,
                request_json=json.dumps({"segment_id": "validation"}, ensure_ascii=False),
                result_json=json.dumps({
                    "content": "验证段：土匪喝完第一口，现场所有人都安静。",
                    "char_count_excluding_punctuation": 20,
                }, ensure_ascii=False),
            ),
        ])
        db.commit()

    latest = client.get(
        "/api/admin/short-drama/testing/script-scene/jobs/latest",
        params={"project_id": project_id, "episode_no": 1, "scene_no": 1, "segment_id": "hook"},
        headers=headers,
    )
    assert latest.status_code == 200, latest.text
    payload = latest.json()

    assert payload["job_id"] == "hook-candidate-job"
    assert payload["segment_id"] == "hook"
    assert payload["candidate"]["content"].startswith("钩子段")


def test_script_scene_job_status_uses_internal_current_step_for_public_workflow(
    tmp_path,
    monkeypatch,
    isolated_script_job_client,
):
    import json

    from app.models.short_drama_generation_job import ShortDramaGenerationJob
    from app.routers.projects import _helpers as project_helpers
    from app.services.saas_access_service import create_access_key

    _, client, Session = isolated_script_job_client
    workspace_root = tmp_path / "script-scene-current-step-workspaces"
    workspace_root.mkdir()
    monkeypatch.setattr(project_helpers, "WORKSPACE_ROOT", workspace_root)
    monkeypatch.setattr(project_helpers, "LEGACY_WORKSPACE_ROOT", workspace_root)

    with Session() as db:
        user = create_access_key(owner_name="步骤状态用户", initial_credit=Decimal("1.00"), db=db)

    login = client.post("/api/user/access-key/login", json={"access_key": user.plain_key})
    assert login.status_code == 200, login.text
    headers = {"X-User-Session": login.json()["session_token"]}

    created = client.post(
        "/api/v2/projects/",
        json={"name": f"步骤状态项目-{uuid4().hex[:8]}", "config": {"total_episodes": 3}},
        headers=headers,
    )
    assert created.status_code == 200, created.text
    project_id = created.json()["id"]

    with Session() as db:
        db.add(ShortDramaGenerationJob(
            id="running-d1-job",
            project_id=project_id,
            owner_key=user.key_id,
            owner_is_admin=False,
            status="running",
            episode_no=2,
            scene_no=1,
            public_message="正在生成本集正文...",
            public_progress=25,
            internal_json=json.dumps({
                "current_step_id": "D1_director_blueprint",
                "started_steps": ["D1_director_blueprint"],
            }, ensure_ascii=False),
        ))
        db.commit()

    status = client.get(
        "/api/admin/short-drama/testing/script-scene/jobs/status/running-d1-job",
        headers=headers,
    )

    assert status.status_code == 200, status.text
    payload = status.json()
    public_text = str(payload).lower()

    assert payload["current_workflow_step"] == "director_blueprint"
    assert [item["status"] for item in payload["workflow_steps"]] == [
        "completed",
        "running",
        "pending",
        "pending",
        "pending",
    ]
    assert "d1_director_blueprint" not in public_text
    assert "deepseek" not in public_text


def test_script_scene_job_step_observer_persists_public_workflow_progress(
    tmp_path,
    monkeypatch,
    isolated_script_job_client,
):
    from app.models.short_drama_generation_job import ShortDramaGenerationJob
    from app.routers.projects import _helpers as project_helpers
    from app.routers.short_drama import scene_routes
    from app.services.saas_access_service import create_access_key

    _, client, Session = isolated_script_job_client
    workspace_root = tmp_path / "script-scene-step-observer-workspaces"
    workspace_root.mkdir()
    monkeypatch.setattr(project_helpers, "WORKSPACE_ROOT", workspace_root)
    monkeypatch.setattr(project_helpers, "LEGACY_WORKSPACE_ROOT", workspace_root)

    with Session() as db:
        user = create_access_key(owner_name="步骤观察用户", initial_credit=Decimal("1.00"), db=db)
        db.add(ShortDramaGenerationJob(
            id="observer-job",
            project_id="observer-project",
            owner_key=user.key_id,
            owner_is_admin=False,
            status="running",
            episode_no=3,
            scene_no=1,
            public_message="正在生成本集正文...",
            public_progress=25,
        ))
        db.commit()

    observer = scene_routes._make_script_scene_job_step_observer("observer-job")
    observer({"step_id": "W1_writer_hook", "status": "running"})

    with Session() as db:
        job = db.query(ShortDramaGenerationJob).filter(ShortDramaGenerationJob.id == "observer-job").first()
        assert job is not None
        payload = scene_routes._script_scene_job_public_status(job)

    assert payload["current_workflow_step"] == "candidate_draft"
    assert [item["status"] for item in payload["workflow_steps"]] == [
        "completed",
        "completed",
        "completed",
        "running",
        "pending",
    ]
    assert "W1_writer_hook" not in str(payload)


def test_script_scene_job_returns_candidate_without_exposing_internal_model_details(
    tmp_path,
    monkeypatch,
    isolated_script_job_client,
):
    import json

    from app.models.short_drama_generation_job import ShortDramaGenerationJob
    from app.routers.projects import _helpers as project_helpers
    from app.routers.short_drama import scene_routes
    from app.services.saas_access_service import create_access_key

    _, client, Session = isolated_script_job_client
    workspace_root = tmp_path / "script-scene-job-workspaces"
    workspace_root.mkdir()
    monkeypatch.setattr(project_helpers, "WORKSPACE_ROOT", workspace_root)
    monkeypatch.setattr(project_helpers, "LEGACY_WORKSPACE_ROOT", workspace_root)

    with Session() as db:
        user = create_access_key(owner_name="后台任务用户", initial_credit=Decimal("1.00"), db=db)

    login = client.post("/api/user/access-key/login", json={"access_key": user.plain_key})
    assert login.status_code == 200, login.text
    headers = {"X-User-Session": login.json()["session_token"]}

    created = client.post(
        "/api/v2/projects/",
        json={"name": f"后台任务项目-{uuid4().hex[:8]}", "config": {"total_episodes": 3}},
        headers=headers,
    )
    assert created.status_code == 200, created.text
    project_id = created.json()["id"]
    _seed_source_packet_backend_materials(Session, project_id)

    async def fake_rag(*_args, **_kwargs):
        return [{"kind": "dify", "count": 2}]

    def fake_generate_research_chain(*_args, **_kwargs):
        return {
            "content": "【场1-1 日 内 示例家庭剧】\n林若岚：这份字据，我今天一定要看清楚。",
            "char_count_excluding_punctuation": 28,
            "warnings": [],
            "blocking_issues": [],
            "benchmark_assessment": None,
            "continuity_assessment": None,
            "episode_memory_card": {"episode_no": 1},
            "canon_packet": {"locked_facts": ["林若岚拿到字据"]},
        }

    monkeypatch.setattr(scene_routes, "apply_rag_injection", fake_rag)
    monkeypatch.setattr(scene_routes, "generate_research_script_candidate", fake_generate_research_chain)
    monkeypatch.setattr(scene_routes, "apply_scene_level_gate", lambda _req, approved, _contract: approved)

    start = client.post(
        "/api/admin/short-drama/testing/script-scene/jobs/start",
        json=_research_chain_request(project_id),
        headers=headers,
    )

    assert start.status_code == 200, start.text
    job_id = start.json()["job_id"]

    status = client.get(
        f"/api/admin/short-drama/testing/script-scene/jobs/status/{job_id}",
        headers=headers,
    )

    assert status.status_code == 200, status.text
    payload = status.json()
    public_text = str(payload).lower()

    assert payload["status"] == "candidate_ready"
    assert payload["candidate_returned_to_user"] is True
    assert payload["candidate_needs_user_confirmation"] is True
    assert payload["saved_as_canon"] is False
    assert payload["visible_route_count"] == 1
    assert payload["candidate"]["content"].startswith("【场1-1")
    assert payload["candidate"]["rag_evidence"] == [{"kind": "dify", "count": 2}]
    assert payload["single_episode_time_budget"]["target_seconds"] == 300
    assert payload["current_workflow_step"] == "review_and_save"
    assert [item["label"] for item in payload["workflow_steps"]] == [
        "前提资料确认",
        "本集导演蓝图",
        "四段任务卡",
        "正文候选",
        "审查与保存",
    ]
    assert payload["workflow_steps"][-1]["status"] == "action_required"
    assert "deepseek" not in public_text
    assert "kimi" not in public_text
    assert "retry_count" not in public_text
    assert "internal" not in public_text

    with Session() as db:
        job = db.query(ShortDramaGenerationJob).filter(ShortDramaGenerationJob.id == job_id).one()
        result = json.loads(job.result_json)
        assert result["job_target"] == {
            "project_id": project_id,
            "episode_no": 1,
            "scene_no": 1,
            "segment_id": "",
        }


def test_script_scene_job_uses_research_chain_orchestrator_not_legacy_scene_loop(
    tmp_path,
    monkeypatch,
    isolated_script_job_client,
):
    from app.routers.projects import _helpers as project_helpers
    from app.routers.short_drama import scene_routes
    from app.services.saas_access_service import create_access_key

    _, client, Session = isolated_script_job_client
    workspace_root = tmp_path / "script-scene-job-research-chain-workspaces"
    workspace_root.mkdir()
    monkeypatch.setattr(project_helpers, "WORKSPACE_ROOT", workspace_root)
    monkeypatch.setattr(project_helpers, "LEGACY_WORKSPACE_ROOT", workspace_root)

    with Session() as db:
        user = create_access_key(owner_name="科研链路用户", initial_credit=Decimal("1.00"), db=db)

    login = client.post("/api/user/access-key/login", json={"access_key": user.plain_key})
    assert login.status_code == 200, login.text
    headers = {"X-User-Session": login.json()["session_token"]}

    created = client.post(
        "/api/v2/projects/",
        json={"name": f"科研链路项目-{uuid4().hex[:8]}", "config": {"total_episodes": 3}},
        headers=headers,
    )
    assert created.status_code == 200, created.text
    project_id = created.json()["id"]
    _seed_source_packet_backend_materials(Session, project_id)

    async def fake_rag(*_args, **_kwargs):
        return []

    calls: list[str] = []

    def fake_research_chain(req, **_kwargs):
        calls.append("research_chain")
        assert req.advanced_generation_mode is True
        return {
            "content": "【场1-1 日 内 示例家庭剧】\n林若岚：这份字据，我今天一定要看清楚。",
            "char_count_excluding_punctuation": 28,
            "warnings": [],
            "blocking_issues": [],
            "quality_passed": True,
            "_research_chain": {
                "route_ready": True,
                "execution_steps": [
                    {"step_id": "D1_director_blueprint", "status": "completed"},
                    {"step_id": "W1_writer_hook", "status": "completed"},
                    {"step_id": "Q1_deepseek_review", "status": "completed"},
                ],
            },
        }

    def outer_quality_gate_should_not_run(*_args, **_kwargs):
        raise AssertionError("completed research Q1 should not be reviewed by a second outer gate")

    monkeypatch.setattr(scene_routes, "apply_rag_injection", fake_rag)
    monkeypatch.setattr(scene_routes, "run_research_script_generation", fake_research_chain)
    monkeypatch.setattr(scene_routes, "apply_scene_level_gate", outer_quality_gate_should_not_run)

    start = client.post(
        "/api/admin/short-drama/testing/script-scene/jobs/start",
        json=_research_chain_request(project_id),
        headers=headers,
    )

    assert start.status_code == 200, start.text
    job_id = start.json()["job_id"]
    status = client.get(
        f"/api/admin/short-drama/testing/script-scene/jobs/status/{job_id}",
        headers=headers,
    )

    assert status.status_code == 200, status.text
    payload = status.json()
    assert payload["status"] == "candidate_ready"
    assert payload["candidate"]["content"].startswith("【场1-1")
    assert "research_chain" not in str(payload).lower()
    assert calls == ["research_chain"]


def test_script_scene_job_returns_review_candidate_for_basic_floor_quality_gate(
    tmp_path,
    monkeypatch,
    isolated_script_job_client,
):
    from app.routers.projects import _helpers as project_helpers
    from app.routers.short_drama import scene_routes
    from app.services.saas_access_service import create_access_key

    _, client, Session = isolated_script_job_client
    workspace_root = tmp_path / "script-scene-job-review-workspaces"
    workspace_root.mkdir()
    monkeypatch.setattr(project_helpers, "WORKSPACE_ROOT", workspace_root)
    monkeypatch.setattr(project_helpers, "LEGACY_WORKSPACE_ROOT", workspace_root)

    with Session() as db:
        user = create_access_key(owner_name="复核候选用户", initial_credit=Decimal("1.00"), db=db)

    login = client.post("/api/user/access-key/login", json={"access_key": user.plain_key})
    assert login.status_code == 200, login.text
    headers = {"X-User-Session": login.json()["session_token"]}

    created = client.post(
        "/api/v2/projects/",
        json={"name": f"复核候选项目-{uuid4().hex[:8]}", "config": {"total_episodes": 3}},
        headers=headers,
    )
    assert created.status_code == 200, created.text
    project_id = created.json()["id"]
    _seed_source_packet_backend_materials(Session, project_id)
    _seed_source_packet_locked_official_source(Session, project_id, episode_number=1)

    async def fake_rag(*_args, **_kwargs):
        return [{"kind": "dify", "count": 2}]

    def fake_generate_research_chain(*_args, **_kwargs):
        return {
            "content": "【场2-1 日 内 示例家庭剧】\n林若岚：先查票号，不公开母亲账户。",
            "char_count_excluding_punctuation": 1620,
            "warnings": ["净字数轻微超出，请裁剪后保存。"],
            "blocking_issues": ["净字数超限：当前 1620，要求至多 1550。"],
            "quality_issues": [],
            "quality_passed": True,
            "benchmark_assessment": None,
            "continuity_assessment": None,
            "episode_memory_card": {"episode_no": 2},
            "canon_packet": {"locked_facts": ["林若岚先查票号"]},
        }

    monkeypatch.setattr(scene_routes, "apply_rag_injection", fake_rag)
    monkeypatch.setattr(scene_routes, "generate_research_script_candidate", fake_generate_research_chain)
    monkeypatch.setattr(scene_routes, "apply_scene_level_gate", lambda _req, approved, _contract: approved)

    start = client.post(
        "/api/admin/short-drama/testing/script-scene/jobs/start",
        json=_research_chain_request(
            project_id,
            episode_no=2,
            episode_summary="林若岚承接上一集查票号。",
            word_count_min=1000,
            word_count_max=1550,
        ),
        headers=headers,
    )

    assert start.status_code == 200, start.text
    job_id = start.json()["job_id"]

    status = client.get(
        f"/api/admin/short-drama/testing/script-scene/jobs/status/{job_id}",
        headers=headers,
    )

    assert status.status_code == 200, status.text
    payload = status.json()
    public_text = str(payload).lower()

    assert payload["status"] == "candidate_review_required"
    assert payload["candidate_returned_to_user"] is True
    assert payload["candidate_needs_user_confirmation"] is True
    assert payload["saved_as_canon"] is False
    assert payload["candidate"]["content"].startswith("【场2-1")
    assert payload["candidate"]["rag_evidence"] == [{"kind": "dify", "count": 2}]
    assert "deepseek" not in public_text
    assert "kimi" not in public_text
    assert "retry_count" not in public_text
    assert "internal" not in public_text


def test_segment_job_delivery_uses_segment_bounds_not_full_episode_floor():
    """分段候选不能套整集 1000 字下限，否则钩子段会被错误拦截。"""
    from app.routers.short_drama.scene_routes import _job_delivery_decision
    from app.schemas.short_drama_writing import TestingScriptRequest

    req = TestingScriptRequest(
        project_id="segment-floor-project",
        mode="segment",
        segment_id="hook",
        episode_no=13,
        word_count_min=200,
        word_count_max=300,
        exclude_punctuation_for_count=True,
    )
    decision = _job_delivery_decision(req, {
        "content": "【场13-1 日 内 示例家庭剧堂屋】\n林若岚：账本不是证据，签字人才是证据。\n△她把第二张收据推到桌上。",
        "char_count_excluding_punctuation": 575,
        "warnings": [],
        "blocking_issues": [
            "净字数超限：当前 575，要求至多 300。",
            "头部爆点后果弱：本集契约要求公开压迫和当场后果。",
        ],
        "quality_passed": True,
    })

    assert decision["candidate_returned_to_user"] is True
    assert decision["status"] == "candidate_review_required"
    assert decision["reason"] == "reviewable_candidate"


def test_middle_segment_delivery_allows_open_tail_for_next_segment_continuation():
    """中间分段可以留开放尾巴，因为下一段会承接；不能套完整剧本尾巴门。"""
    from app.routers.short_drama.scene_routes import _job_delivery_decision
    from app.schemas.short_drama_writing import TestingScriptRequest

    req = TestingScriptRequest(
        project_id="segment-open-tail-project",
        mode="segment",
        segment_id="validation",
        episode_no=13,
        word_count_min=240,
        word_count_max=350,
        exclude_punctuation_for_count=True,
    )
    decision = _job_delivery_decision(req, {
        "content": "【场13-2 日 内 示例家庭剧堂屋】\n林若岚：这张清单不是补件，是逼我们认账。\n△她把清单压在旧本子上，许景深刚要开口，门外传来顾知遥的声音，",
        "char_count_excluding_punctuation": 628,
        "warnings": [],
        "blocking_issues": ["净字数超限：当前 628，要求至多 350。"],
        "quality_passed": True,
    })

    assert decision["candidate_returned_to_user"] is True
    assert decision["status"] == "candidate_review_required"
    assert decision["reason"] == "reviewable_candidate"


def test_script_scene_job_repairs_severe_overflow_before_returning_review_candidate(
    tmp_path,
    monkeypatch,
    isolated_script_job_client,
):
    from app.routers.projects import _helpers as project_helpers
    from app.routers.short_drama import scene_routes
    from app.services.saas_access_service import create_access_key

    _, client, Session = isolated_script_job_client
    workspace_root = tmp_path / "script-scene-job-overflow-workspaces"
    workspace_root.mkdir()
    monkeypatch.setattr(project_helpers, "WORKSPACE_ROOT", workspace_root)
    monkeypatch.setattr(project_helpers, "LEGACY_WORKSPACE_ROOT", workspace_root)

    with Session() as db:
        user = create_access_key(owner_name="严重超字用户", initial_credit=Decimal("1.00"), db=db)

    login = client.post("/api/user/access-key/login", json={"access_key": user.plain_key})
    assert login.status_code == 200, login.text
    headers = {"X-User-Session": login.json()["session_token"]}

    created = client.post(
        "/api/v2/projects/",
        json={"name": f"严重超字项目-{uuid4().hex[:8]}", "config": {"total_episodes": 3}},
        headers=headers,
    )
    assert created.status_code == 200, created.text
    project_id = created.json()["id"]
    _seed_source_packet_backend_materials(Session, project_id)
    _seed_source_packet_locked_official_source(Session, project_id, episode_number=1)

    async def fake_rag(*_args, **_kwargs):
        return [{"kind": "dify", "count": 2}]

    def fake_generate_research_chain(*_args, **_kwargs):
        return {
            "content": "【场2-1 日 内 示例家庭剧】\n" + "林若岚：先查票号，先稳住母亲账户，不公开。\n" * 220,
            "char_count_excluding_punctuation": 2378,
            "warnings": [],
            "blocking_issues": [
                "净字数超限：当前 2378，要求至多 1550。",
                "角色【林启明】已出场但没有标准台词，人物锚点不稳。",
            ],
            "quality_issues": [],
            "quality_passed": True,
        }

    monkeypatch.setattr(scene_routes, "apply_rag_injection", fake_rag)
    monkeypatch.setattr(scene_routes, "generate_research_script_candidate", fake_generate_research_chain)
    monkeypatch.setattr(scene_routes, "apply_scene_level_gate", lambda _req, approved, _contract: approved)

    start = client.post(
        "/api/admin/short-drama/testing/script-scene/jobs/start",
        json=_research_chain_request(
            project_id,
            episode_no=2,
            episode_summary="林若岚承接上一集查票号。",
            word_count_min=1000,
            word_count_max=1550,
        ),
        headers=headers,
    )

    assert start.status_code == 200, start.text
    job_id = start.json()["job_id"]

    status = client.get(
        f"/api/admin/short-drama/testing/script-scene/jobs/status/{job_id}",
        headers=headers,
    )

    assert status.status_code == 200, status.text
    payload = status.json()

    assert payload["status"] == "candidate_review_required"
    assert payload["candidate_returned_to_user"] is True
    assert payload["candidate_needs_user_confirmation"] is True
    assert payload["saved_as_canon"] is False
    assert payload["candidate"]["char_count_excluding_punctuation"] <= 1700


def test_script_scene_job_returns_review_candidate_from_internal_quality_gate_error(
    tmp_path,
    monkeypatch,
    isolated_script_job_client,
):
    from fastapi import HTTPException

    from app.routers.projects import _helpers as project_helpers
    from app.routers.short_drama import scene_routes
    from app.services.saas_access_service import create_access_key

    _, client, Session = isolated_script_job_client
    workspace_root = tmp_path / "script-scene-job-internal-quality-gate-workspaces"
    workspace_root.mkdir()
    monkeypatch.setattr(project_helpers, "WORKSPACE_ROOT", workspace_root)
    monkeypatch.setattr(project_helpers, "LEGACY_WORKSPACE_ROOT", workspace_root)

    with Session() as db:
        user = create_access_key(owner_name="内部质量门候选用户", initial_credit=Decimal("1.00"), db=db)

    login = client.post("/api/user/access-key/login", json={"access_key": user.plain_key})
    assert login.status_code == 200, login.text
    headers = {"X-User-Session": login.json()["session_token"]}

    created = client.post(
        "/api/v2/projects/",
        json={"name": f"内部质量门候选项目-{uuid4().hex[:8]}", "config": {"total_episodes": 3}},
        headers=headers,
    )
    assert created.status_code == 200, created.text
    project_id = created.json()["id"]
    _seed_source_packet_backend_materials(Session, project_id)
    _seed_source_packet_locked_official_source(Session, project_id, episode_number=1)

    async def fake_rag(*_args, **_kwargs):
        return [{"kind": "dify", "count": 2}]

    class FakeQualityGateError(HTTPException):
        def __init__(self, candidate):
            super().__init__(
                status_code=400,
                detail={
                    "error_code": "quality_gate_failed",
                    "detail": "连续性深审未通过：正面对抗信号偏弱。",
                    "retryable": True,
                },
            )
            self.candidate = candidate

    def fake_generate_research_chain(*_args, **_kwargs):
        raise FakeQualityGateError({
            "content": "【场2-1 夜 内 周砚临时剪辑台】\n" + "林若岚：我先查票号，证据没稳之前不公开母亲账户。\n" * 90,
            "char_count_excluding_punctuation": 1170,
            "warnings": ["角色【林启明】出场但没有标准台词。"],
            "blocking_issues": ["连续性深审未通过：主角与反派同场但正面对抗信号偏弱。"],
            "quality_issues": [],
            "quality_passed": True,
        })

    monkeypatch.setattr(scene_routes, "apply_rag_injection", fake_rag)
    monkeypatch.setattr(scene_routes, "generate_research_script_candidate", fake_generate_research_chain)

    start = client.post(
        "/api/admin/short-drama/testing/script-scene/jobs/start",
        json=_research_chain_request(
            project_id,
            episode_no=2,
            episode_summary="林若岚承接上一集查票号。",
            word_count_min=1000,
            word_count_max=1550,
        ),
        headers=headers,
    )

    assert start.status_code == 200, start.text
    job_id = start.json()["job_id"]

    status = client.get(
        f"/api/admin/short-drama/testing/script-scene/jobs/status/{job_id}",
        headers=headers,
    )

    assert status.status_code == 200, status.text
    payload = status.json()

    assert payload["status"] == "candidate_review_required"
    assert payload["candidate_returned_to_user"] is True
    assert payload["candidate_needs_user_confirmation"] is True
    assert payload["saved_as_canon"] is False
    assert payload["candidate"]["content"].startswith("【场2-1")
    assert payload["candidate"]["char_count_excluding_punctuation"] == 1170
