from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


@pytest.fixture
def db_session(tmp_path):
    from app.database import Base
    from app.models import (  # noqa: F401
        activity_log,
        agent,
        admin_session,
        auto_fix,
        character_visual,
        collaboration,
        compliance,
        episode_segment,
        evidence,
        issue_record,
        legal_assets,
        material_item,
        module,
        patrol_record,
        project_learning,
        project_v2,
        review_record,
        reward_log,
        rule,
        rule_quality,
        step_version,
        storyboard,
        sub_task,
        task,
    )

    engine = create_engine(
        f"sqlite:///{tmp_path / 'candidate-save-lock-boundaries.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
        engine.dispose()


@pytest.fixture
def project_with_scene(db_session, monkeypatch, tmp_path):
    from app.models.project_v2 import Episode, ProjectV2, Scene
    from app.routers.projects import _helpers

    workspace_root = tmp_path / "03-project-library" / "new-projects"
    monkeypatch.setattr(_helpers, "WORKSPACE_ROOT", workspace_root)
    monkeypatch.setattr(_helpers, "LEGACY_WORKSPACE_ROOT", workspace_root)

    workspace = workspace_root / f"authority-{uuid4().hex}"
    workspace.mkdir(parents=True, exist_ok=True)
    project = ProjectV2(
        id=str(uuid4()),
        name="candidate-save-lock-boundary-project",
        project_type="original-short-drama",
        audience_axis="mixed",
        genre_main="urban",
        total_episodes=2,
        workspace_path=str(workspace),
        created_by="owner-1",
    )
    project.set_config({"total_episodes": 2, "confirmed_total_episodes": 2})
    episode = Episode(
        id=str(uuid4()),
        project_id=project.id,
        episode_number=1,
        title="Boundary episode",
        status="draft",
    )
    scene = Scene(
        id=str(uuid4()),
        episode_id=episode.id,
        scene_number=1,
        scene_code="1-1",
        content="",
        word_count=0,
        status="draft",
    )
    db_session.add_all([project, episode, scene])
    db_session.commit()
    return project, episode, scene


def _actor():
    from app.auth.dependencies import ProjectAccessActor

    return ProjectAccessActor(actor_type="user", access_key_id="owner-1", owner_name="Owner")


async def _save_scene(db_session, project_id: str, content: str):
    from app.routers.projects._schemas import ContentSaveRequest
    from app.routers.projects.routes_episodes_scenes import save_scene_content

    return await save_scene_content(
        project_id,
        1,
        1,
        ContentSaveRequest(
            content=content,
            editor_type="human",
            editor_id="owner-1",
            editor_name="Owner",
            change_note="ordinary scene save boundary proof",
            create_checkpoint=False,
        ),
        actor=_actor(),
        db=db_session,
    )


def test_candidate_job_public_status_is_not_canon():
    from app.models.short_drama_generation_job import ShortDramaGenerationJob
    from app.routers.short_drama.scene_routes import _script_scene_job_public_status
    from app.services.short_drama_atomic_generation import SCRIPT_GENERATION_JOB_CANDIDATE_READY

    job = ShortDramaGenerationJob(
        id="candidate-boundary-job",
        project_id="project-1",
        owner_key="owner-1",
        owner_is_admin=False,
        status=SCRIPT_GENERATION_JOB_CANDIDATE_READY,
        episode_no=1,
        scene_no=1,
        public_message="candidate returned for review",
        public_progress=100,
        result_json=json.dumps(
            {
                "content": "safe candidate placeholder",
                "char_count_excluding_punctuation": 24,
                "warnings": [],
            },
            ensure_ascii=False,
        ),
    )

    public = _script_scene_job_public_status(job)

    assert public["status"] == SCRIPT_GENERATION_JOB_CANDIDATE_READY
    assert public["candidate_returned_to_user"] is True
    assert public["candidate_needs_user_confirmation"] is True
    assert public["saved_as_canon"] is False
    assert public["candidate"]["content"] == "safe candidate placeholder"


@pytest.mark.asyncio
async def test_scene_save_creates_scene_version_not_official_source(db_session, project_with_scene):
    from app.models.evidence import EvidenceEvent
    from app.models.project_v2 import ContentVersion
    from app.services.official_source_consistency import (
        OfficialSourceConsistencyError,
        validate_locked_official_source_consistency,
    )

    project, _episode, _scene = project_with_scene

    await _save_scene(db_session, project.id, "ordinary saved scene placeholder")

    rows = db_session.query(ContentVersion).filter(ContentVersion.project_id == project.id).all()
    assert [row.scene_number for row in rows] == [1]
    assert db_session.query(EvidenceEvent).filter(
        EvidenceEvent.project_id == project.id,
        EvidenceEvent.event_type == "script_content_saved",
    ).count() == 1
    assert db_session.query(EvidenceEvent).filter(
        EvidenceEvent.project_id == project.id,
        EvidenceEvent.event_type == "episode_locked",
    ).count() == 0

    with pytest.raises(OfficialSourceConsistencyError) as exc_info:
        validate_locked_official_source_consistency(
            db_session,
            project_id=project.id,
            episode_number=1,
            project_workspace_path=project.workspace_path,
        )
    assert exc_info.value.reason_code == "locked_official_source_missing"


@pytest.mark.asyncio
async def test_lock_episode_creates_official_scene_zero_source(db_session, project_with_scene):
    from app.models.evidence import EvidenceEvent
    from app.models.project_v2 import ContentVersion
    from app.routers.projects.routes_collaboration import LockEpisodeRequest, lock_episode
    from app.services.official_source_consistency import validate_locked_official_source_consistency

    project, _episode, _scene = project_with_scene

    await _save_scene(db_session, project.id, "official lock source placeholder")
    result = await lock_episode(
        project.id,
        1,
        LockEpisodeRequest(note="official lock boundary proof"),
        actor=_actor(),
        db=db_session,
    )

    versions = db_session.query(ContentVersion).filter(
        ContentVersion.project_id == project.id,
        ContentVersion.episode_number == 1,
    ).order_by(ContentVersion.scene_number.asc()).all()
    assert [row.scene_number for row in versions] == [0, 1]

    official = next(row for row in versions if row.scene_number == 0)
    event = db_session.query(EvidenceEvent).filter(
        EvidenceEvent.project_id == project.id,
        EvidenceEvent.event_type == "episode_locked",
    ).one()
    assert result["version_id"] == official.id == event.content_version_id
    assert result["content_hash"] == official.content_hash == event.content_hash
    assert Path(official.content_path).relative_to(Path(project.workspace_path)) == Path(
        "episodes/ep01/scenes/sc00_v001.md"
    )

    consistency = validate_locked_official_source_consistency(
        db_session,
        project_id=project.id,
        episode_number=1,
        project_workspace_path=project.workspace_path,
    )
    assert consistency.source_map["source"] == "episode_locked_content_version"
    assert consistency.source_map["official_source"] == "episode_locked"
    assert consistency.content_version_id == official.id
