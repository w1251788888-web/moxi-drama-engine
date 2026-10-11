from __future__ import annotations

import hashlib
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
        f"sqlite:///{tmp_path / 'export_gate.db'}",
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


def _make_project(db, tmp_path, *, name: str = "export gate fixture"):
    from app.models.project_v2 import ProjectV2

    workspace = tmp_path / f"workspace-{uuid4().hex}"
    workspace.mkdir(parents=True)
    project = ProjectV2(
        id=str(uuid4()),
        name=name,
        project_type="原创短剧",
        audience_axis="混合",
        genre_main="都市",
        total_episodes=1,
        workspace_path=str(workspace),
        created_by="user-1",
    )
    project.set_config({"total_episodes": 1})
    db.add(project)
    db.commit()
    return project, workspace


def _add_locked_source(db, project, workspace: Path, *, content: str = "safe locked official source"):
    from app.models.evidence import EvidenceEvent
    from app.models.project_v2 import ContentVersion

    content_path = workspace / "episodes" / "ep01" / "scenes" / "sc00_v001.md"
    content_path.parent.mkdir(parents=True)
    content_path.write_text(content, encoding="utf-8")
    content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
    version = ContentVersion(
        project_id=project.id,
        episode_number=1,
        scene_number=0,
        version_code="v001",
        editor_type="human",
        editor_id="user-1",
        editor_name="主创",
        content_path=str(content_path),
        content_hash=content_hash,
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
    return version


def _add_compliance_scan(db, project, *, content_version_id: str = "", content_hash: str = "", verdict: str = "pass"):
    from app.models.compliance import ComplianceScan

    scan = ComplianceScan(
        project_id=project.id,
        episode_number=1,
        content_version_id=content_version_id,
        content_hash=content_hash,
        status="completed",
        verdict=verdict,
        summary="safe scan placeholder",
    )
    db.add(scan)
    db.commit()
    return scan


def _blockers(row):
    import json

    return json.loads(row.blockers_json)


def test_export_gate_blocks_pass_scan_without_locked_official_source(db_session, tmp_path):
    from app.services.legal_asset_service import check_export_gate

    project, _workspace = _make_project(db_session, tmp_path)
    _add_compliance_scan(
        db_session,
        project,
        content_version_id="ordinary-or-stale-cv",
        content_hash="b" * 64,
    )

    result = check_export_gate(db_session, project=project)

    assert result.status == "blocked"
    assert "缺少可证明一致的 locked official source，不能正式导出" in _blockers(result)


def test_export_gate_blocks_scan_bound_to_different_source(db_session, tmp_path):
    from app.services.legal_asset_service import check_export_gate

    project, workspace = _make_project(db_session, tmp_path)
    _add_locked_source(db_session, project, workspace)
    _add_compliance_scan(
        db_session,
        project,
        content_version_id="different-cv",
        content_hash="b" * 64,
    )

    result = check_export_gate(db_session, project=project)

    assert result.status == "blocked"
    assert "第 1 集合规扫描未绑定当前 locked official source，不能正式导出" in _blockers(result)


def test_export_gate_blocks_locked_official_hash_mismatch(db_session, tmp_path):
    from app.models.evidence import EvidenceEvent
    from app.services.legal_asset_service import check_export_gate

    project, workspace = _make_project(db_session, tmp_path)
    version = _add_locked_source(db_session, project, workspace)
    version.content_hash = "f" * 64
    event = db_session.query(EvidenceEvent).filter(
        EvidenceEvent.project_id == project.id,
        EvidenceEvent.content_version_id == version.id,
    ).one()
    event.content_hash = version.content_hash
    db_session.commit()
    _add_compliance_scan(
        db_session,
        project,
        content_version_id=version.id,
        content_hash=version.content_hash,
    )

    result = check_export_gate(db_session, project=project)

    assert result.status == "blocked"
    assert "第 1 集 locked official source 不一致：locked_official_hash_mismatch" in _blockers(result)
