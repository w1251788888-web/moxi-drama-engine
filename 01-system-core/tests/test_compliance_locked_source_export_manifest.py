from __future__ import annotations

import hashlib
import json
import zipfile
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
        f"sqlite:///{tmp_path / 'locked_scan_manifest.db'}",
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


def _make_project_with_scene_and_locked_source(
    db,
    tmp_path,
    *,
    scene_content: str,
    locked_content: str,
):
    from app.models.evidence import EvidenceEvent
    from app.models.project_v2 import ContentVersion, Episode, ProjectV2, Scene

    workspace = tmp_path / f"workspace-{uuid4().hex}"
    content_path = workspace / "episodes" / "ep01" / "scenes" / "sc00_v001.md"
    content_path.parent.mkdir(parents=True)
    content_path.write_text(locked_content, encoding="utf-8")
    locked_hash = hashlib.sha256(locked_content.encode("utf-8")).hexdigest()

    project = ProjectV2(
        id=str(uuid4()),
        name="locked-scan-manifest-fixture",
        project_type="原创短剧",
        audience_axis="混合",
        genre_main="都市",
        total_episodes=1,
        workspace_path=str(workspace),
        created_by="user-1",
    )
    project.set_config({"total_episodes": 1})
    episode = Episode(
        id=str(uuid4()),
        project_id=project.id,
        episode_number=1,
        title="fixture episode",
        status="completed",
    )
    scene = Scene(
        id=str(uuid4()),
        episode_id=episode.id,
        scene_number=1,
        scene_code="1-1",
        content=scene_content,
        status="completed",
    )
    db.add_all([project, episode, scene])
    db.flush()
    version = ContentVersion(
        project_id=project.id,
        episode_number=1,
        scene_number=0,
        version_code="v001",
        editor_type="human",
        editor_id="user-1",
        editor_name="主创",
        content_path=str(content_path),
        content_hash=locked_hash,
    )
    db.add(version)
    db.flush()
    db.add(EvidenceEvent(
        project_id=project.id,
        event_type="episode_locked",
        target_type="episode",
        target_id="1",
        content_version_id=version.id,
        content_hash=version.content_hash,
    ))
    db.commit()
    return project, version


def test_compliance_scan_reads_locked_official_source_not_ordinary_scene(db_session, tmp_path):
    from app.services.compliance_scan_service import scan_episode

    project, version = _make_project_with_scene_and_locked_source(
        db_session,
        tmp_path,
        scene_content="synthetic ordinary scene probe contains 未成年恋爱 marker",
        locked_content="safe locked official placeholder without risk marker",
    )

    scan = scan_episode(db_session, project_id=project.id, episode_number=1)

    assert scan.verdict == "pass"
    assert scan.content_version_id == version.id
    assert scan.content_hash == version.content_hash


def test_evidence_package_manifest_records_locked_source_and_scan_binding(db_session, monkeypatch, tmp_path):
    from app.auth.dependencies import ProjectAccessActor
    from app.models.compliance import ComplianceScan
    from app.services import workspace_service
    from app.services.legal_asset_service import generate_evidence_package

    monkeypatch.setattr(workspace_service, "PROJECT_LIBRARY_ROOT", tmp_path / "project-library")
    project, version = _make_project_with_scene_and_locked_source(
        db_session,
        tmp_path,
        scene_content="ordinary scene placeholder",
        locked_content="safe locked official placeholder for manifest binding",
    )
    scan = ComplianceScan(
        project_id=project.id,
        episode_number=1,
        content_version_id=version.id,
        content_hash=version.content_hash,
        status="completed",
        verdict="pass",
        summary="safe scan placeholder",
    )
    db_session.add(scan)
    db_session.commit()

    package = generate_evidence_package(
        db_session,
        project=project,
        package_type="legal",
        actor=ProjectAccessActor(actor_type="user", access_key_id="user-1", owner_name="主创"),
    )

    with zipfile.ZipFile(package.package_path) as zf:
        manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
        compliance_report = json.loads(zf.read("compliance_report.json").decode("utf-8"))

    locked_sources = manifest["locked_official_sources"]
    assert locked_sources == [
        {
            "episode_number": 1,
            "content_version_id": version.id,
            "content_hash": version.content_hash,
            "episode_locked_event_id": locked_sources[0]["episode_locked_event_id"],
            "source": "episode_locked_content_version",
            "official_source": "episode_locked",
        }
    ]
    bindings = manifest["compliance_scan_bindings"]
    assert bindings == [
        {
            "episode_number": 1,
            "scan_id": scan.id,
            "scan_content_version_id": version.id,
            "scan_content_hash": version.content_hash,
            "locked_content_version_id": version.id,
            "locked_content_hash": version.content_hash,
            "binding_status": "matched_locked_official_source",
        }
    ]
    report_scan = compliance_report["scans"][0]
    assert report_scan["id"] == scan.id
    assert report_scan["content_version_id"] == version.id
    assert report_scan["content_hash"] == version.content_hash
    assert report_scan["locked_source_binding"]["binding_status"] == "matched_locked_official_source"
