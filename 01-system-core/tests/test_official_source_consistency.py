import hashlib

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.evidence import EvidenceEvent
from app.models.project_v2 import ContentVersion, Episode, ProjectV2
from app.services.official_source_consistency import (
    OfficialSourceConsistencyError,
    validate_locked_official_source_consistency,
    validate_locked_official_source_map,
    validate_locked_official_source_recovery_proof,
)


def _create_schema(engine):
    ProjectV2.__table__.create(bind=engine)
    Episode.__table__.create(bind=engine)
    ContentVersion.__table__.create(bind=engine)
    EvidenceEvent.__table__.create(bind=engine)


def _session(tmp_path, name="official-source-consistency.db"):
    engine = create_engine(
        f"sqlite:///{tmp_path / name}",
        connect_args={"check_same_thread": False},
    )
    _create_schema(engine)
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)


def _seed_locked_official(
    db,
    tmp_path,
    *,
    project_id="project-consistency",
    episode_number=3,
    version_id="locked-version-ep3",
    event_id="locked-event-ep3",
    content="safe locked official placeholder",
    create_event=True,
    content_hash=None,
):
    locked_file = tmp_path / f"locked-ep{episode_number}.md"
    locked_file.write_text(content, encoding="utf-8")
    actual_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
    stored_hash = content_hash or actual_hash
    db.add(ProjectV2(
        id=project_id,
        name="consistency project",
        config="{}",
        workspace_path=str(tmp_path),
    ))
    db.add(Episode(
        id=f"episode-{episode_number}",
        project_id=project_id,
        episode_number=episode_number,
        title=f"Episode {episode_number}",
    ))
    version = ContentVersion(
        id=version_id,
        project_id=project_id,
        episode_number=episode_number,
        scene_number=0,
        version_code="v001",
        content_path=str(locked_file),
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
    return locked_file, actual_hash


def test_locked_official_consistency_happy_path_returns_safe_source_map(tmp_path):
    Session = _session(tmp_path)
    with Session() as db:
        _locked_file, locked_hash = _seed_locked_official(db, tmp_path)

        result = validate_locked_official_source_consistency(
            db,
            project_id="project-consistency",
            episode_number=3,
            project_workspace_path=str(tmp_path),
        )

        assert result.content_version_id == "locked-version-ep3"
        assert result.content_hash == locked_hash
        assert result.episode_locked_event_id == "locked-event-ep3"
        assert result.source_map == {
            "source": "episode_locked_content_version",
            "official_source": "episode_locked",
            "episode_number": 3,
            "content_version_id": "locked-version-ep3",
            "content_hash": locked_hash,
            "episode_locked_event_id": "locked-event-ep3",
        }
        assert db.query(ContentVersion).count() == 1
        assert db.query(EvidenceEvent).count() == 1


def test_locked_official_consistency_rejects_hash_mismatch_without_mutation(tmp_path):
    Session = _session(tmp_path)
    with Session() as db:
        _seed_locked_official(db, tmp_path, content_hash="0" * 64)

        with pytest.raises(OfficialSourceConsistencyError) as exc_info:
            validate_locked_official_source_consistency(
                db,
                project_id="project-consistency",
                episode_number=3,
                project_workspace_path=str(tmp_path),
            )

        assert exc_info.value.reason_code == "locked_official_hash_mismatch"
        assert db.query(ContentVersion).count() == 1
        assert db.query(EvidenceEvent).count() == 1


def test_locked_official_consistency_rejects_missing_file_without_mutation(tmp_path):
    Session = _session(tmp_path)
    with Session() as db:
        locked_file, _locked_hash = _seed_locked_official(db, tmp_path)
        locked_file.unlink()

        with pytest.raises(OfficialSourceConsistencyError) as exc_info:
            validate_locked_official_source_consistency(
                db,
                project_id="project-consistency",
                episode_number=3,
                project_workspace_path=str(tmp_path),
            )

        assert exc_info.value.reason_code == "locked_official_file_missing"
        assert db.query(ContentVersion).count() == 1
        assert db.query(EvidenceEvent).count() == 1


def test_locked_official_consistency_rejects_missing_evidence_event_without_mutation(tmp_path):
    Session = _session(tmp_path)
    with Session() as db:
        _seed_locked_official(db, tmp_path, create_event=False)

        with pytest.raises(OfficialSourceConsistencyError) as exc_info:
            validate_locked_official_source_consistency(
                db,
                project_id="project-consistency",
                episode_number=3,
                project_workspace_path=str(tmp_path),
            )

        assert exc_info.value.reason_code == "locked_official_event_missing"
        assert db.query(ContentVersion).count() == 1
        assert db.query(EvidenceEvent).count() == 0


def test_locked_official_source_map_rejects_missing_or_stale_map(tmp_path):
    Session = _session(tmp_path)
    with Session() as db:
        _locked_file, locked_hash = _seed_locked_official(db, tmp_path)
        result = validate_locked_official_source_consistency(
            db,
            project_id="project-consistency",
            episode_number=3,
            project_workspace_path=str(tmp_path),
        )

        with pytest.raises(OfficialSourceConsistencyError) as missing_info:
            validate_locked_official_source_map({}, result)
        assert missing_info.value.reason_code == "locked_official_source_map_missing"

        stale_map = dict(result.source_map)
        stale_map["content_hash"] = "1" * 64
        with pytest.raises(OfficialSourceConsistencyError) as stale_info:
            validate_locked_official_source_map(stale_map, result)
        assert stale_info.value.reason_code == "locked_official_source_map_mismatch"

        valid = validate_locked_official_source_map(result.source_map, result)
        assert valid["content_hash"] == locked_hash


def test_locked_official_recovery_proof_checks_db_file_hash_event_and_source_map(tmp_path):
    Session = _session(tmp_path)
    with Session() as db:
        locked_file, locked_hash = _seed_locked_official(db, tmp_path)

        proof = validate_locked_official_source_recovery_proof(
            db,
            project_id="project-consistency",
            episode_number=3,
            project_workspace_path=str(tmp_path),
            content_path=str(locked_file),
            content_hash=locked_hash,
            episode_locked_event_id="locked-event-ep3",
        )

        assert proof["checks"] == {
            "db_to_file": True,
            "file_hash_to_db": True,
            "event_to_content_version": True,
            "event_to_source_map": True,
        }
        assert proof["content_version_id"] == "locked-version-ep3"
        assert proof["episode_locked_event_id"] == "locked-event-ep3"
        assert proof["content_path"] == str(locked_file.resolve(strict=False))
        assert proof["content_hash"] == locked_hash
        assert proof["source_map"]["source"] == "episode_locked_content_version"
        assert "content" not in proof
        assert db.query(ContentVersion).count() == 1
        assert db.query(EvidenceEvent).count() == 1


def test_locked_official_recovery_proof_rejects_file_hash_without_db_row(tmp_path):
    Session = _session(tmp_path)
    with Session() as db:
        locked_file, _locked_hash = _seed_locked_official(db, tmp_path)

        with pytest.raises(OfficialSourceConsistencyError) as exc_info:
            validate_locked_official_source_recovery_proof(
                db,
                project_id="project-consistency",
                episode_number=3,
                project_workspace_path=str(tmp_path),
                content_path=str(locked_file),
                content_hash="2" * 64,
                episode_locked_event_id="locked-event-ep3",
            )

        assert exc_info.value.reason_code == "locked_official_file_hash_db_lookup_missing"
        assert db.query(ContentVersion).count() == 1
        assert db.query(EvidenceEvent).count() == 1


def test_locked_official_recovery_proof_rejects_event_content_version_mismatch(tmp_path):
    Session = _session(tmp_path)
    with Session() as db:
        locked_file, locked_hash = _seed_locked_official(db, tmp_path)
        event = db.query(EvidenceEvent).filter_by(id="locked-event-ep3").one()
        event.content_version_id = "stale-version"
        db.commit()

        with pytest.raises(OfficialSourceConsistencyError) as exc_info:
            validate_locked_official_source_recovery_proof(
                db,
                project_id="project-consistency",
                episode_number=3,
                project_workspace_path=str(tmp_path),
                content_path=str(locked_file),
                content_hash=locked_hash,
                episode_locked_event_id="locked-event-ep3",
            )

        assert exc_info.value.reason_code == "locked_official_event_missing"
        assert db.query(ContentVersion).count() == 1
        assert db.query(EvidenceEvent).count() == 1
