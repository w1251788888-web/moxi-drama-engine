from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.evidence import EvidenceEvent
from app.models.project_v2 import ContentVersion, Episode, ProjectV2, Scene
from app.models.short_drama_generation_job import ShortDramaGenerationJob
from app.services.official_source_consistency import (
    OfficialSourceConsistencyError,
    validate_locked_official_source_consistency,
    validate_locked_official_source_map,
)
from app.services.short_drama_generation_source_packet import (
    GenerationSourceBlocked,
    compile_previous_episode_continuity_packet,
)
from app.services.short_drama_job_recovery import (
    mark_orphan_candidate_job_failed_if_needed,
    recover_stale_script_scene_job_if_needed,
)


def _create_schema(engine):
    ProjectV2.__table__.create(bind=engine)
    Episode.__table__.create(bind=engine)
    Scene.__table__.create(bind=engine)
    ContentVersion.__table__.create(bind=engine)
    EvidenceEvent.__table__.create(bind=engine)
    ShortDramaGenerationJob.__table__.create(bind=engine)


def _session(tmp_path, name: str = "p5-architecture-data-consistency.db"):
    engine = create_engine(
        f"sqlite:///{tmp_path / name}",
        connect_args={"check_same_thread": False},
    )
    _create_schema(engine)
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _add_project_and_episode(db, tmp_path, *, project_id: str = "project-ledger", episode_number: int = 1):
    workspace = tmp_path / f"{project_id}-workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    project = ProjectV2(
        id=project_id,
        name=project_id,
        workspace_path=str(workspace),
        config="{}",
    )
    episode = Episode(
        id=f"{project_id}-episode-{episode_number}",
        project_id=project_id,
        episode_number=episode_number,
        title=f"Episode {episode_number}",
    )
    db.add_all([project, episode])
    db.commit()
    return project, episode, workspace


def _add_locked_version(
    db,
    workspace,
    *,
    project_id: str = "project-ledger",
    episode_number: int = 1,
    version_id: str = "locked-version-1",
    event_id: str = "locked-event-1",
    scene_number: int = 0,
    content: str = "safe official ledger text",
    content_path=None,
    content_hash: str = "",
    create_event: bool = True,
):
    target_path = content_path or (workspace / f"episode-{episode_number}-locked.md")
    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_text(content, encoding="utf-8")
    stored_hash = content_hash or _hash(content)
    version = ContentVersion(
        id=version_id,
        project_id=project_id,
        episode_number=episode_number,
        scene_number=scene_number,
        version_code="v001",
        content_path=str(target_path),
        content_hash=stored_hash,
    )
    db.add(version)
    if create_event:
        db.add(EvidenceEvent(
            id=event_id,
            project_id=project_id,
            event_type="episode_locked",
            target_type="episode",
            target_id=str(episode_number),
            content_version_id=version_id,
            content_hash=stored_hash,
        ))
    db.commit()
    return version, target_path


def test_official_source_rejects_workspace_escape_empty_file_and_non_episode_version(tmp_path):
    Session = _session(tmp_path)
    with Session() as db:
        _project, _episode, workspace = _add_project_and_episode(db, tmp_path)
        outside = tmp_path / "outside-workspace" / "locked.md"
        _add_locked_version(
            db,
            workspace,
            content_path=outside,
            version_id="outside-version",
            event_id="outside-event",
        )

        with pytest.raises(OfficialSourceConsistencyError) as outside_info:
            validate_locked_official_source_consistency(
                db,
                project_id="project-ledger",
                episode_number=1,
                project_workspace_path=str(workspace),
                content_version_id="outside-version",
            )
        assert outside_info.value.reason_code == "locked_official_file_outside_workspace"

    Session = _session(tmp_path, "p5-architecture-empty-file.db")
    with Session() as db:
        _project, _episode, workspace = _add_project_and_episode(db, tmp_path, project_id="project-empty")
        _add_locked_version(
            db,
            workspace,
            project_id="project-empty",
            version_id="empty-version",
            event_id="empty-event",
            content="",
            content_hash=_hash(""),
        )

        with pytest.raises(OfficialSourceConsistencyError) as empty_info:
            validate_locked_official_source_consistency(
                db,
                project_id="project-empty",
                episode_number=1,
                project_workspace_path=str(workspace),
                content_version_id="empty-version",
            )
        assert empty_info.value.reason_code == "locked_official_file_empty"

    Session = _session(tmp_path, "p5-architecture-ordinary-version.db")
    with Session() as db:
        _project, _episode, workspace = _add_project_and_episode(db, tmp_path, project_id="project-ordinary")
        _add_locked_version(
            db,
            workspace,
            project_id="project-ordinary",
            version_id="ordinary-scene-version",
            event_id="ordinary-scene-event",
            scene_number=1,
        )

        with pytest.raises(OfficialSourceConsistencyError) as ordinary_info:
            validate_locked_official_source_consistency(
                db,
                project_id="project-ordinary",
                episode_number=1,
                project_workspace_path=str(workspace),
            )
        assert ordinary_info.value.reason_code == "locked_official_source_missing"


def test_source_map_must_bind_locked_content_version_hash_and_event(tmp_path):
    Session = _session(tmp_path)
    with Session() as db:
        _project, _episode, workspace = _add_project_and_episode(db, tmp_path)
        version, _path = _add_locked_version(db, workspace)
        consistency = validate_locked_official_source_consistency(
            db,
            project_id="project-ledger",
            episode_number=1,
            project_workspace_path=str(workspace),
        )

        valid_map = validate_locked_official_source_map(consistency.source_map, consistency)
        assert valid_map["source"] == "episode_locked_content_version"
        assert valid_map["content_version_id"] == version.id
        assert valid_map["content_hash"] == version.content_hash
        assert valid_map["episode_locked_event_id"] == "locked-event-1"

        for key in ("source", "content_version_id", "content_hash", "episode_locked_event_id"):
            stale_map = dict(consistency.source_map)
            stale_map[key] = "stale-value"
            with pytest.raises(OfficialSourceConsistencyError) as stale_info:
                validate_locked_official_source_map(stale_map, consistency)
            assert stale_info.value.reason_code == "locked_official_source_map_mismatch"


def test_previous_episode_gate_rejects_candidate_ordinary_scene_and_previous_brief(tmp_path):
    Session = _session(tmp_path)
    with Session() as db:
        project, episode, workspace = _add_project_and_episode(db, tmp_path)
        db.add(Scene(
            id="ordinary-scene-1",
            episode_id=episode.id,
            scene_number=1,
            scene_code="1-1",
            content="ordinary scene text is not official source",
            status="completed",
        ))
        db.add(ShortDramaGenerationJob(
            id="candidate-job-1",
            project_id=project.id,
            owner_key="owner-1",
            status="candidate_ready",
            episode_no=1,
            scene_no=1,
            result_json=json.dumps({
                "content": "candidate text is not official source",
                "job_target": {"project_id": project.id, "episode_no": 1, "scene_no": 1},
            }, ensure_ascii=False),
        ))
        db.commit()

        with pytest.raises(GenerationSourceBlocked) as exc:
            compile_previous_episode_continuity_packet(
                db,
                project_id=project.id,
                episode_no=2,
                project_workspace_path=str(workspace),
                previous_episode_briefs=[
                    {"episode_no": 1, "summary": "old brief is not official source"},
                ],
                manual_edit_context={
                    "latest": {"current_excerpt": "manual context is not official source"}
                },
            )

        assert exc.value.reason_code == "previous_official_source_missing"
        assert exc.value.detail["source_reason"] == "locked_official_source_missing"
        assert exc.value.detail["ignored_inputs"] == ["previous_episode_briefs", "manual_edit_context"]
        assert db.query(ContentVersion).count() == 0
        assert db.query(EvidenceEvent).count() == 0


def test_job_recovery_marks_bad_jobs_without_writing_official_source(tmp_path):
    Session = _session(tmp_path)
    with Session() as db:
        db.add(ShortDramaGenerationJob(
            id="stale-running-ledger-job",
            project_id="project-ledger",
            owner_key="owner-1",
            status="running",
            episode_no=2,
            scene_no=1,
            public_message="running",
            public_progress=50,
            created_at=datetime.now() - timedelta(hours=2),
            updated_at=datetime.now() - timedelta(hours=2),
        ))
        db.add(ShortDramaGenerationJob(
            id="orphan-candidate-ledger-job",
            project_id="project-ledger",
            owner_key="owner-1",
            status="candidate_review_required",
            episode_no=2,
            scene_no=1,
            public_message="candidate",
            public_progress=100,
            result_json=json.dumps({
                "content": "candidate placeholder",
                "job_target": {"project_id": "wrong-project", "episode_no": 2, "scene_no": 1},
            }, ensure_ascii=False),
        ))
        db.commit()

        stale = db.query(ShortDramaGenerationJob).filter_by(id="stale-running-ledger-job").one()
        orphan = db.query(ShortDramaGenerationJob).filter_by(id="orphan-candidate-ledger-job").one()

        assert recover_stale_script_scene_job_if_needed(db, stale) is True
        assert mark_orphan_candidate_job_failed_if_needed(db, orphan) is True

        assert db.query(ContentVersion).count() == 0
        assert db.query(EvidenceEvent).count() == 0
        assert stale.status == "failed"
        assert orphan.status == "failed"
        stale_internal = json.loads(stale.internal_json)
        orphan_internal = json.loads(orphan.internal_json)
        assert stale_internal["recovery"]["reason_code"] == "stale_running_job_recovered_as_failed"
        assert orphan_internal["recovery"]["reason_code"] == "orphan_candidate_result_target_mismatch"
