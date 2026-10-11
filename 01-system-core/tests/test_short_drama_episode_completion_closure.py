from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import types
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


SEGMENT_IDS = ("hook", "validation", "explosion", "resolution")
SEGMENT_TEXT = {
    "hook": "HOOK_UNIT_TEST_TEXT",
    "validation": "VALIDATION_UNIT_TEST_TEXT",
    "explosion": "EXPLOSION_UNIT_TEST_TEXT",
    "resolution": "RESOLUTION_UNIT_TEST_TEXT",
}


class _TestingConfig:
    database_path = str(Path(tempfile.gettempdir()) / "moxi-completion-closure-test.db")
    database_type = "sqlite"
    raw: dict = {}
    project_name = "moxi-test"
    server_host = "127.0.0.1"
    server_port = 6565
    workspace_root = str(Path(tempfile.gettempdir()) / "moxi-completion-closure-workspaces")
    redacted_registration_token = ""
    cors_allowed_origins: list[str] = []
    cors_allow_origin_regex = None
    notification_config: dict = {}
    feed_retention_days = 30
    public_feed_enabled = False
    allow_registration = False
    registration_token = ""
    server_external_url = ""
    cli_version = ""
    market_insights: dict = {}

    def get(self, _key, default=None):
        return default

    def get_safe_config(self):
        return {}

    def has_external_url(self) -> bool:
        return False

    def is_initialized(self) -> bool:
        return True

    def mark_initialized(self) -> None:
        return None

    def model_dump(self):
        return {}

    def save(self) -> None:
        return None

    def update(self, *_args, **_kwargs) -> None:
        return None

    def update_password(self, *_args, **_kwargs) -> None:
        return None

    def verify_admin_password(self, *_args, **_kwargs) -> bool:
        return False


_config_module = types.ModuleType("app.config")
_config_module.config = _TestingConfig()
_config_module.get_config = lambda: _config_module.config
_config_module.save_config = lambda *_args, **_kwargs: None
sys.modules.setdefault("app.config", _config_module)


@pytest.fixture()
def completion_db(tmp_path, monkeypatch):
    from app import database
    from app.models import (  # noqa: F401
        activity_log,
        agent,
        admin_session,
        auto_fix,
        character_visual,
        episode_segment,
        evidence,
        issue_record,
        material_item,
        module,
        patrol_record,
        project_learning,
        project_v2,
        review_record,
        reward_log,
        rule,
        rule_quality,
        short_drama_generation_job,
        step_version,
        storyboard,
        sub_task,
        task,
    )
    from app.routers.projects import _helpers as project_helpers

    workspace_root = tmp_path / "completion-workspaces"
    workspace_root.mkdir()
    monkeypatch.setattr(project_helpers, "WORKSPACE_ROOT", workspace_root)
    monkeypatch.setattr(project_helpers, "LEGACY_WORKSPACE_ROOT", workspace_root)

    engine = create_engine(
        f"sqlite:///{tmp_path / 'completion-closure.db'}",
        connect_args={"check_same_thread": False},
    )
    database.Base.metadata.create_all(bind=engine)
    Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    monkeypatch.setattr(database, "engine", engine)
    monkeypatch.setattr(database, "SessionLocal", Session)
    db = Session()
    try:
        yield db, workspace_root
    finally:
        db.close()
        engine.dispose()


def _seed_episode_ready_for_completion(
    db,
    workspace_root: Path,
    *,
    confirm_count: int = 3,
    confirmation_version_contents: list[str] | None = None,
    include_segments: tuple[str, ...] = SEGMENT_IDS,
    scene_content: str | None = None,
    official_version: bool = False,
    active_job: bool = False,
):
    from app.models.project_v2 import ContentVersion, Episode, ProjectV2, Scene
    from app.models.short_drama_generation_job import ShortDramaGenerationJob

    project_id = str(uuid4())
    workspace = workspace_root / project_id
    workspace.mkdir(parents=True)
    project = ProjectV2(
        id=project_id,
        name=f"completion-{project_id[:8]}",
        total_episodes=3,
        workspace_path=str(workspace),
    )
    project.set_config({"total_episodes": 3})
    db.add(project)
    episode = Episode(
        id=str(uuid4()),
        project_id=project_id,
        episode_number=1,
        status="writing",
        current_version="v001",
    )
    db.add(episode)
    content = scene_content
    if content is None:
        content = "\n".join(SEGMENT_TEXT[segment_id] for segment_id in SEGMENT_IDS)
    scene = Scene(
        id=str(uuid4()),
        episode_id=episode.id,
        scene_number=1,
        scene_code="1-1",
        content=content,
        status="draft",
        word_count=len(content),
    )
    db.add(scene)
    db.flush()

    def add_version(
        version_index: int,
        note: str,
        scene_number: int = 1,
        version_content: str | None = None,
    ):
        saved_content = content if version_content is None else version_content
        path = workspace / f"episode-1-scene-{scene_number}-v{version_index:03d}.md"
        path.write_text(saved_content, encoding="utf-8")
        db.add(ContentVersion(
            project_id=project_id,
            episode_number=1,
            scene_number=scene_number,
            version_code=f"v{version_index:03d}",
            editor_type="ai",
            editor_id="unit-test",
            editor_name="unit-test",
            content_path=str(path),
            content_hash=hashlib.sha256(saved_content.encode("utf-8")).hexdigest(),
            change_note=note,
        ))

    version_index = 1
    for index in range(confirm_count):
        version_content = None
        if confirmation_version_contents and index < len(confirmation_version_contents):
            version_content = confirmation_version_contents[index]
        add_version(version_index, "分段确认自动保存", version_content=version_content)
        version_index += 1
    add_version(version_index, "分段草稿自动保存")
    version_index += 1
    if official_version:
        add_version(version_index, "锁定单集最终稿", scene_number=0)

    for segment_id in include_segments:
        db.add(ShortDramaGenerationJob(
            id=f"{segment_id}-{project_id[:8]}",
            project_id=project_id,
            owner_key="unit-test-key",
            owner_is_admin=False,
            status="candidate_ready",
            episode_no=1,
            scene_no=1,
            public_progress=100,
            request_json=json.dumps({
                "project_id": project_id,
                "episode_no": 1,
                "scene_no": 1,
                "segment_id": segment_id,
            }, ensure_ascii=False),
            result_json=json.dumps({
                "content": SEGMENT_TEXT[segment_id],
            }, ensure_ascii=False),
        ))

    if active_job:
        db.add(ShortDramaGenerationJob(
            id=f"active-{project_id[:8]}",
            project_id=project_id,
            owner_key="unit-test-key",
            owner_is_admin=False,
            status="running",
            episode_no=1,
            scene_no=1,
            request_json=json.dumps({
                "project_id": project_id,
                "episode_no": 1,
                "scene_no": 1,
                "segment_id": "resolution",
            }, ensure_ascii=False),
        ))

    db.commit()
    return project_id


def _write_workspace_segment_progress(
    workspace_root: Path,
    project_id: str,
    *,
    episode_number: int = 1,
    scene_number: int = 1,
    scene_content: str | None = None,
    confirmed_segments: tuple[str, ...] = SEGMENT_IDS,
    draft_completion_close_status: str | None = None,
):
    content = scene_content
    if content is None:
        content = "\n".join(SEGMENT_TEXT[segment_id] for segment_id in SEGMENT_IDS)
    workspace = workspace_root / project_id
    project_file = workspace / "project.json"
    payload = {
        "workflow_context": {
            "script_segment_progress": {
                str(episode_number): {
                    "episode_no": episode_number,
                    "scene_no": scene_number,
                    "scene_content": content,
                    "content_hash": hashlib.sha256(content.encode("utf-8")).hexdigest(),
                    "has_progress": True,
                    "steps": [
                        {
                            "id": segment_id,
                            "status": "confirmed" if segment_id in confirmed_segments else "reviewing",
                            "editedContent": SEGMENT_TEXT[segment_id],
                        }
                        for segment_id in SEGMENT_IDS
                    ],
                },
            },
        },
    }
    if draft_completion_close_status is not None:
        payload["workflow_context"]["script_segment_progress"][str(episode_number)][
            "draft_completion_close_status"
        ] = draft_completion_close_status
    project_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _add_segment_confirmation_event(db, project_id: str, segment_id: str):
    from app.models.evidence import EvidenceEvent

    db.add(EvidenceEvent(
        project_id=project_id,
        actor_type="user",
        actor_id="unit-test-access-key",
        actor_name="收口测试用户",
        event_type="script_segment_confirmed",
        target_type="script_segment",
        target_id=f"1:1:{segment_id}",
        summary="分段确认自动保存",
        metadata_json=json.dumps({
            "episode_number": 1,
            "scene_number": 1,
            "segment_id": segment_id,
            "candidate_length": len(SEGMENT_TEXT[segment_id]),
        }, ensure_ascii=False),
    ))
    db.commit()


def _grant_episode_permissions(
    db,
    project_id: str,
    permissions: tuple[str, ...],
    *,
    scope_type: str = "episode",
    scope_id: str = "1",
):
    from app.models.collaboration import ProjectMember, ProjectPermission

    member = ProjectMember(
        id=str(uuid4()),
        project_id=project_id,
        access_key_id="unit-test-access-key",
        role="co_writer",
        status="active",
        display_name="收口测试用户",
    )
    db.add(member)
    db.flush()
    for permission in permissions:
        db.add(ProjectPermission(
            project_id=project_id,
            member_id=member.id,
            scope_type=scope_type,
            scope_id=scope_id,
            permission=permission,
        ))
    db.commit()


@pytest.fixture()
def completion_route_client(completion_db):
    from fastapi.testclient import TestClient

    from app.auth.dependencies import verify_project_actor
    from app.database import get_db
    from app.main import app

    db, workspace_root = completion_db

    def override_db():
        yield db

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[verify_project_actor] = _closure_actor
    try:
        yield TestClient(app), db, workspace_root
    finally:
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(verify_project_actor, None)


def _closure_actor():
    from app.auth.dependencies import ProjectAccessActor

    return ProjectAccessActor(
        actor_type="user",
        access_key_id="unit-test-access-key",
        owner_name="收口测试用户",
    )


def _count_versions(db, project_id: str, note: str) -> int:
    from app.models.project_v2 import ContentVersion

    return db.query(ContentVersion).filter(
        ContentVersion.project_id == project_id,
        ContentVersion.episode_number == 1,
        ContentVersion.scene_number == 1,
        ContentVersion.change_note == note,
    ).count()


def test_episode_draft_completion_closure_blocks_duplicate_legacy_confirmations(completion_db):
    from app.services.short_drama_episode_completion import complete_episode_draft_save_closure

    db, workspace_root = completion_db
    project_id = _seed_episode_ready_for_completion(
        db,
        workspace_root,
        confirm_count=3,
        confirmation_version_contents=[SEGMENT_TEXT["hook"]] * 3,
    )

    result = complete_episode_draft_save_closure(
        db,
        project_id=project_id,
        episode_number=1,
        scene_number=1,
        actor=_closure_actor(),
    )

    assert result["status"] == "blocked"
    assert "prior_segment_confirmation_evidence_missing:validation" in result["blocking_issues"]
    assert "prior_segment_confirmation_evidence_missing:explosion" in result["blocking_issues"]
    assert result["legacy_confirmation_count"] == 3


def test_episode_draft_completion_closure_accepts_structured_prior_segment_confirmations(completion_db):
    from app.services.short_drama_episode_completion import complete_episode_draft_save_closure

    db, workspace_root = completion_db
    project_id = _seed_episode_ready_for_completion(db, workspace_root, confirm_count=0)
    for segment_id in ("hook", "validation", "explosion"):
        _add_segment_confirmation_event(db, project_id, segment_id)

    result = complete_episode_draft_save_closure(
        db,
        project_id=project_id,
        episode_number=1,
        scene_number=1,
        actor=_closure_actor(),
    )

    assert result["status"] == "completed"
    assert result["created_confirmation_count"] == 1
    assert result["confirmed_segment_ids"] == list(SEGMENT_IDS)


def test_episode_draft_completion_closure_cleans_version_file_when_evidence_write_fails(completion_db, monkeypatch):
    from app.models.project_v2 import ContentVersion
    from app.services import short_drama_episode_completion as completion_service
    from app.services.short_drama_episode_completion import (
        EPISODE_DRAFT_COMPLETION_NOTE,
        SEGMENT_CONFIRMATION_NOTE,
        complete_episode_draft_save_closure,
    )

    db, workspace_root = completion_db
    project_id = _seed_episode_ready_for_completion(db, workspace_root, confirm_count=0)
    for segment_id in ("hook", "validation", "explosion"):
        _add_segment_confirmation_event(db, project_id, segment_id)
    before_files = {path.name for path in workspace_root.rglob("*.md")}
    before_confirm_count = _count_versions(db, project_id, SEGMENT_CONFIRMATION_NOTE)
    before_completion_count = _count_versions(db, project_id, EPISODE_DRAFT_COMPLETION_NOTE)

    def fail_record_evidence_event(*_args, **_kwargs):
        raise RuntimeError("unit-test evidence write failed")

    monkeypatch.setattr(completion_service, "record_evidence_event", fail_record_evidence_event)

    with pytest.raises(RuntimeError, match="unit-test evidence write failed"):
        complete_episode_draft_save_closure(
            db,
            project_id=project_id,
            episode_number=1,
            scene_number=1,
            actor=_closure_actor(),
        )

    after_files = {path.name for path in workspace_root.rglob("*.md")}
    assert after_files == before_files
    assert _count_versions(db, project_id, SEGMENT_CONFIRMATION_NOTE) == before_confirm_count
    assert _count_versions(db, project_id, EPISODE_DRAFT_COMPLETION_NOTE) == before_completion_count
    assert db.query(ContentVersion).filter(
        ContentVersion.project_id == project_id,
        ContentVersion.editor_id == "episode_draft_completion_closure",
    ).count() == 0


def test_episode_draft_completion_closure_accepts_normalized_resolution_content(completion_db):
    from app.models.short_drama_generation_job import ShortDramaGenerationJob
    from app.services.short_drama_episode_completion import complete_episode_draft_save_closure

    db, workspace_root = completion_db
    project_id = _seed_episode_ready_for_completion(
        db,
        workspace_root,
        confirm_count=0,
        scene_content="\n".join([
            SEGMENT_TEXT["hook"],
            SEGMENT_TEXT["validation"],
            SEGMENT_TEXT["explosion"],
            "RESOLUTION\nUNIT   TEST\nTEXT",
        ]),
    )
    for segment_id in ("hook", "validation", "explosion"):
        _add_segment_confirmation_event(db, project_id, segment_id)
    resolution_job = db.query(ShortDramaGenerationJob).filter(
        ShortDramaGenerationJob.project_id == project_id,
        ShortDramaGenerationJob.id.like("resolution-%"),
    ).first()
    resolution_job.result_json = json.dumps({"content": "RESOLUTION UNIT TEST TEXT"}, ensure_ascii=False)
    db.commit()

    result = complete_episode_draft_save_closure(
        db,
        project_id=project_id,
        episode_number=1,
        scene_number=1,
        actor=_closure_actor(),
    )

    assert result["status"] == "completed"


def test_episode_draft_completion_closure_blocks_when_resolution_content_absent_after_normalization(completion_db):
    from app.services.short_drama_episode_completion import complete_episode_draft_save_closure

    db, workspace_root = completion_db
    project_id = _seed_episode_ready_for_completion(
        db,
        workspace_root,
        confirm_count=0,
        scene_content="\n".join([
            SEGMENT_TEXT["hook"],
            SEGMENT_TEXT["validation"],
            SEGMENT_TEXT["explosion"],
            "DIFFERENT_ENDING_TEXT",
        ]),
    )
    for segment_id in ("hook", "validation", "explosion"):
        _add_segment_confirmation_event(db, project_id, segment_id)

    result = complete_episode_draft_save_closure(
        db,
        project_id=project_id,
        episode_number=1,
        scene_number=1,
        actor=_closure_actor(),
    )

    assert result["status"] == "blocked"
    assert "resolution_candidate_not_in_scene_content" in result["blocking_issues"]


def test_episode_draft_completion_closure_accepts_confirmed_workspace_review_candidate(completion_db):
    from app.models.project_v2 import ContentVersion
    from app.models.short_drama_generation_job import ShortDramaGenerationJob
    from app.services.short_drama_episode_completion import (
        EPISODE_DRAFT_COMPLETION_NOTE,
        complete_episode_draft_save_closure,
    )

    db, workspace_root = completion_db
    project_id = _seed_episode_ready_for_completion(db, workspace_root, confirm_count=0)
    explosion_job = db.query(ShortDramaGenerationJob).filter(
        ShortDramaGenerationJob.project_id == project_id,
        ShortDramaGenerationJob.id.like("explosion-%"),
    ).one()
    explosion_job.status = "candidate_review_required"
    _write_workspace_segment_progress(workspace_root, project_id)
    db.commit()

    result = complete_episode_draft_save_closure(
        db,
        project_id=project_id,
        episode_number=1,
        scene_number=1,
        actor=_closure_actor(),
    )

    assert result["status"] == "completed"
    assert result["candidate_lengths"]["explosion"] == len(SEGMENT_TEXT["explosion"])
    assert result["confirmed_segment_ids"] == list(SEGMENT_IDS)
    assert db.query(ContentVersion).filter(
        ContentVersion.project_id == project_id,
        ContentVersion.change_note == EPISODE_DRAFT_COMPLETION_NOTE,
    ).count() == 1


def test_episode_draft_completion_closure_blocks_unconfirmed_review_candidate(completion_db):
    from app.models.short_drama_generation_job import ShortDramaGenerationJob
    from app.services.short_drama_episode_completion import complete_episode_draft_save_closure

    db, workspace_root = completion_db
    project_id = _seed_episode_ready_for_completion(db, workspace_root, confirm_count=0)
    explosion_job = db.query(ShortDramaGenerationJob).filter(
        ShortDramaGenerationJob.project_id == project_id,
        ShortDramaGenerationJob.id.like("explosion-%"),
    ).one()
    explosion_job.status = "candidate_review_required"
    _write_workspace_segment_progress(
        workspace_root,
        project_id,
        confirmed_segments=("hook", "validation", "resolution"),
    )
    db.commit()

    result = complete_episode_draft_save_closure(
        db,
        project_id=project_id,
        episode_number=1,
        scene_number=1,
        actor=_closure_actor(),
    )

    assert result["status"] == "blocked"
    assert "segment_candidate_missing:explosion" in result["blocking_issues"]


def test_episode_draft_completion_closure_blocks_empty_confirmed_review_candidate(completion_db):
    from app.models.short_drama_generation_job import ShortDramaGenerationJob
    from app.services.short_drama_episode_completion import complete_episode_draft_save_closure

    db, workspace_root = completion_db
    project_id = _seed_episode_ready_for_completion(db, workspace_root, confirm_count=0)
    explosion_job = db.query(ShortDramaGenerationJob).filter(
        ShortDramaGenerationJob.project_id == project_id,
        ShortDramaGenerationJob.id.like("explosion-%"),
    ).one()
    explosion_job.status = "candidate_review_required"
    explosion_job.result_json = json.dumps({"content": ""}, ensure_ascii=False)
    _write_workspace_segment_progress(workspace_root, project_id)
    db.commit()

    result = complete_episode_draft_save_closure(
        db,
        project_id=project_id,
        episode_number=1,
        scene_number=1,
        actor=_closure_actor(),
    )

    assert result["status"] == "blocked"
    assert "segment_candidate_missing:explosion" in result["blocking_issues"]


def test_episode_draft_completion_route_requires_approve_and_edit(completion_route_client):
    client, db, workspace_root = completion_route_client
    project_id = _seed_episode_ready_for_completion(db, workspace_root)
    _grant_episode_permissions(db, project_id, ("approve",))

    response = client.post(f"/api/v2/projects/{project_id}/episodes/1/draft-completion/close")

    assert response.status_code == 403


def test_episode_draft_completion_route_returns_safe_completed_summary(completion_route_client):
    from app.models.project_v2 import ContentVersion
    from app.models.short_drama_generation_job import ShortDramaGenerationJob

    client, db, workspace_root = completion_route_client
    project_id = _seed_episode_ready_for_completion(db, workspace_root, confirm_count=0)
    for segment_id in ("hook", "validation", "explosion"):
        _add_segment_confirmation_event(db, project_id, segment_id)
    _grant_episode_permissions(db, project_id, ("approve", "edit"))
    before_job_count = db.query(ShortDramaGenerationJob).filter(
        ShortDramaGenerationJob.project_id == project_id,
    ).count()

    response = client.post(f"/api/v2/projects/{project_id}/episodes/1/draft-completion/close")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "completed"
    assert payload["created_confirmation_count"] == 1
    assert db.query(ShortDramaGenerationJob).filter(
        ShortDramaGenerationJob.project_id == project_id,
    ).count() == before_job_count
    assert db.query(ContentVersion).filter(
        ContentVersion.project_id == project_id,
        ContentVersion.episode_number == 1,
        ContentVersion.scene_number == 0,
    ).count() == 0
    safe_payload = json.dumps(payload, ensure_ascii=False).lower()
    for forbidden in ("unit_test_text", "prompt", "request", "response", "raw", "provider", "api_key", "session"):
        assert forbidden not in safe_payload


def test_episode_draft_completion_route_accepts_current_project_content_permissions(completion_route_client):
    client, db, workspace_root = completion_route_client
    project_id = _seed_episode_ready_for_completion(db, workspace_root, confirm_count=0)
    for segment_id in ("hook", "validation", "explosion"):
        _add_segment_confirmation_event(db, project_id, segment_id)
    _grant_episode_permissions(
        db,
        project_id,
        ("write", "manage_content"),
        scope_type="project",
        scope_id="",
    )

    response = client.post(f"/api/v2/projects/{project_id}/episodes/1/draft-completion/close")

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["status"] == "completed"
    assert payload["completion_checkpoint_created"] is True


def test_episode_draft_completion_route_returns_safe_blocked_summary(completion_route_client):
    client, db, workspace_root = completion_route_client
    project_id = _seed_episode_ready_for_completion(
        db,
        workspace_root,
        confirm_count=0,
        include_segments=("hook", "validation", "resolution"),
    )
    for segment_id in ("hook", "validation", "explosion"):
        _add_segment_confirmation_event(db, project_id, segment_id)
    _grant_episode_permissions(db, project_id, ("approve", "edit"))

    response = client.post(f"/api/v2/projects/{project_id}/episodes/1/draft-completion/close")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "blocked"
    assert "segment_candidate_missing:explosion" in payload["blocking_issues"]
    safe_payload = json.dumps(payload, ensure_ascii=False).lower()
    for forbidden in ("unit_test_text", "prompt", "request", "response", "raw", "provider", "api_key", "session"):
        assert forbidden not in safe_payload


def test_episode_draft_completion_closure_adds_missing_resolution_confirmation_and_checkpoint(completion_db):
    from app.models.evidence import EvidenceEvent
    from app.models.project_v2 import ContentVersion
    from app.models.short_drama_generation_job import ShortDramaGenerationJob
    from app.services.short_drama_episode_completion import (
        EPISODE_DRAFT_COMPLETION_NOTE,
        SEGMENT_CONFIRMATION_NOTE,
        complete_episode_draft_save_closure,
    )

    db, workspace_root = completion_db
    project_id = _seed_episode_ready_for_completion(db, workspace_root)
    before_job_count = db.query(ShortDramaGenerationJob).filter(
        ShortDramaGenerationJob.project_id == project_id,
    ).count()

    result = complete_episode_draft_save_closure(
        db,
        project_id=project_id,
        episode_number=1,
        scene_number=1,
        actor=_closure_actor(),
    )

    assert result["status"] == "completed"
    assert result["segment_ids"] == list(SEGMENT_IDS)
    assert result["created_confirmation_count"] == 1
    assert result["reused_confirmation_count"] == 3
    assert result["completion_checkpoint_created"] is True
    assert result["active_job_count"] == 0
    assert result["blocking_issues"] == []
    assert _count_versions(db, project_id, SEGMENT_CONFIRMATION_NOTE) == 4
    assert _count_versions(db, project_id, EPISODE_DRAFT_COMPLETION_NOTE) == 1
    assert db.query(ContentVersion).filter(
        ContentVersion.project_id == project_id,
        ContentVersion.episode_number == 1,
        ContentVersion.scene_number == 0,
    ).count() == 0
    assert db.query(ShortDramaGenerationJob).filter(
        ShortDramaGenerationJob.project_id == project_id,
    ).count() == before_job_count

    checkpoint = db.query(EvidenceEvent).filter(
        EvidenceEvent.project_id == project_id,
        EvidenceEvent.event_type == "episode_draft_completion_checkpoint",
    ).first()
    assert checkpoint is not None
    metadata = json.loads(checkpoint.metadata_json or "{}")
    assert metadata["segment_ids"] == list(SEGMENT_IDS)
    safe_payload = json.dumps(result, ensure_ascii=False) + checkpoint.metadata_json
    assert "RESOLUTION_UNIT_TEST_TEXT" not in safe_payload
    assert "prompt" not in safe_payload.lower()
    assert "raw" not in safe_payload.lower()
    assert "provider" not in safe_payload.lower()


def test_episode_draft_completion_closure_is_idempotent(completion_db):
    from app.services.short_drama_episode_completion import (
        EPISODE_DRAFT_COMPLETION_NOTE,
        SEGMENT_CONFIRMATION_NOTE,
        complete_episode_draft_save_closure,
    )

    db, workspace_root = completion_db
    project_id = _seed_episode_ready_for_completion(db, workspace_root)

    first = complete_episode_draft_save_closure(
        db,
        project_id=project_id,
        episode_number=1,
        scene_number=1,
        actor=_closure_actor(),
    )
    second = complete_episode_draft_save_closure(
        db,
        project_id=project_id,
        episode_number=1,
        scene_number=1,
        actor=_closure_actor(),
    )

    assert first["status"] == "completed"
    assert second["status"] == "completed"
    assert second["created_confirmation_count"] == 0
    assert second["reused_confirmation_count"] == 4
    assert second["completion_checkpoint_created"] is False
    assert second["completion_checkpoint_reused"] is True
    assert _count_versions(db, project_id, SEGMENT_CONFIRMATION_NOTE) == 4
    assert _count_versions(db, project_id, EPISODE_DRAFT_COMPLETION_NOTE) == 1


def test_episode_draft_completion_closure_blocks_when_active_job_exists(completion_db):
    from app.services.short_drama_episode_completion import complete_episode_draft_save_closure

    db, workspace_root = completion_db
    project_id = _seed_episode_ready_for_completion(db, workspace_root, active_job=True)

    result = complete_episode_draft_save_closure(
        db,
        project_id=project_id,
        episode_number=1,
        scene_number=1,
        actor=_closure_actor(),
    )

    assert result["status"] == "blocked"
    assert "active_generation_job_exists" in result["blocking_issues"]


def test_episode_draft_completion_closure_blocks_when_segment_candidate_missing(completion_db):
    from app.services.short_drama_episode_completion import complete_episode_draft_save_closure

    db, workspace_root = completion_db
    project_id = _seed_episode_ready_for_completion(
        db,
        workspace_root,
        include_segments=("hook", "validation", "resolution"),
    )

    result = complete_episode_draft_save_closure(
        db,
        project_id=project_id,
        episode_number=1,
        scene_number=1,
        actor=_closure_actor(),
    )

    assert result["status"] == "blocked"
    assert "segment_candidate_missing:explosion" in result["blocking_issues"]


def test_episode_draft_completion_closure_accepts_confirmed_workspace_recovery_for_review_required_candidate(completion_db):
    from app.models.evidence import EvidenceEvent
    from app.models.project_v2 import ContentVersion
    from app.models.short_drama_generation_job import ShortDramaGenerationJob
    from app.services.short_drama_episode_completion import (
        EPISODE_DRAFT_COMPLETION_NOTE,
        complete_episode_draft_save_closure,
    )

    db, workspace_root = completion_db
    project_id = _seed_episode_ready_for_completion(db, workspace_root, confirm_count=3)
    _write_workspace_segment_progress(workspace_root, project_id)
    explosion_job = db.query(ShortDramaGenerationJob).filter(
        ShortDramaGenerationJob.project_id == project_id,
        ShortDramaGenerationJob.id.like("explosion-%"),
    ).first()
    assert explosion_job is not None
    explosion_job.status = "candidate_review_required"
    db.commit()

    result = complete_episode_draft_save_closure(
        db,
        project_id=project_id,
        episode_number=1,
        scene_number=1,
        actor=_closure_actor(),
    )

    assert result["status"] == "completed"
    assert "segment_candidate_missing:explosion" not in result["blocking_issues"]
    assert db.query(EvidenceEvent).filter(
        EvidenceEvent.project_id == project_id,
        EvidenceEvent.event_type == "episode_draft_completion_checkpoint",
    ).count() == 1
    assert db.query(ContentVersion).filter(
        ContentVersion.project_id == project_id,
        ContentVersion.episode_number == 1,
        ContentVersion.scene_number == 1,
        ContentVersion.change_note == EPISODE_DRAFT_COMPLETION_NOTE,
    ).count() == 1


def test_episode_draft_completion_closure_blocks_review_required_candidate_without_workspace_confirmed(completion_db):
    from app.models.short_drama_generation_job import ShortDramaGenerationJob
    from app.services.short_drama_episode_completion import complete_episode_draft_save_closure

    db, workspace_root = completion_db
    project_id = _seed_episode_ready_for_completion(db, workspace_root, confirm_count=3)
    _write_workspace_segment_progress(
        workspace_root,
        project_id,
        confirmed_segments=("hook", "validation", "resolution"),
    )
    explosion_job = db.query(ShortDramaGenerationJob).filter(
        ShortDramaGenerationJob.project_id == project_id,
        ShortDramaGenerationJob.id.like("explosion-%"),
    ).first()
    assert explosion_job is not None
    explosion_job.status = "candidate_review_required"
    db.commit()

    result = complete_episode_draft_save_closure(
        db,
        project_id=project_id,
        episode_number=1,
        scene_number=1,
        actor=_closure_actor(),
    )

    assert result["status"] == "blocked"
    assert "segment_candidate_missing:explosion" in result["blocking_issues"]


def test_episode_draft_completion_closure_blocks_review_required_candidate_without_content(completion_db):
    from app.models.short_drama_generation_job import ShortDramaGenerationJob
    from app.services.short_drama_episode_completion import complete_episode_draft_save_closure

    db, workspace_root = completion_db
    project_id = _seed_episode_ready_for_completion(db, workspace_root, confirm_count=3)
    _write_workspace_segment_progress(workspace_root, project_id)
    explosion_job = db.query(ShortDramaGenerationJob).filter(
        ShortDramaGenerationJob.project_id == project_id,
        ShortDramaGenerationJob.id.like("explosion-%"),
    ).first()
    assert explosion_job is not None
    explosion_job.status = "candidate_review_required"
    explosion_job.result_json = json.dumps({}, ensure_ascii=False)
    db.commit()

    result = complete_episode_draft_save_closure(
        db,
        project_id=project_id,
        episode_number=1,
        scene_number=1,
        actor=_closure_actor(),
    )

    assert result["status"] == "blocked"
    assert "segment_candidate_missing:explosion" in result["blocking_issues"]


def test_episode_draft_completion_closure_blocks_when_scene_content_empty(completion_db):
    from app.services.short_drama_episode_completion import complete_episode_draft_save_closure

    db, workspace_root = completion_db
    project_id = _seed_episode_ready_for_completion(db, workspace_root, scene_content="")

    result = complete_episode_draft_save_closure(
        db,
        project_id=project_id,
        episode_number=1,
        scene_number=1,
        actor=_closure_actor(),
    )

    assert result["status"] == "blocked"
    assert "scene_content_empty" in result["blocking_issues"]


def test_episode_draft_completion_closure_blocks_when_official_version_exists(completion_db):
    from app.services.short_drama_episode_completion import complete_episode_draft_save_closure

    db, workspace_root = completion_db
    project_id = _seed_episode_ready_for_completion(db, workspace_root, official_version=True)

    result = complete_episode_draft_save_closure(
        db,
        project_id=project_id,
        episode_number=1,
        scene_number=1,
        actor=_closure_actor(),
    )

    assert result["status"] == "blocked"
    assert "official_episode_version_exists" in result["blocking_issues"]
