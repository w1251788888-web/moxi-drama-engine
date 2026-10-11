from __future__ import annotations

from pathlib import Path
from uuid import uuid4
import zipfile

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
        f"sqlite:///{tmp_path / 'fusion.db'}",
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


def _actor():
    from app.auth.dependencies import ProjectAccessActor

    return ProjectAccessActor(actor_type="user", access_key_id="user-1", owner_name="主创")


def _prepare_lock_workspace(monkeypatch, tmp_path):
    from app.routers.projects import _helpers

    workspace_root = tmp_path / "03-project-library" / "new-projects"
    monkeypatch.setattr(_helpers, "WORKSPACE_ROOT", workspace_root)
    monkeypatch.setattr(_helpers, "LEGACY_WORKSPACE_ROOT", workspace_root)
    return workspace_root


def _make_official_source_project(db, tmp_path, *, created_by: str = "owner-1"):
    from app.models.project_v2 import Episode, ProjectV2, Scene

    workspace = tmp_path / "03-project-library" / "new-projects" / f"authority-{uuid4().hex}"
    workspace.mkdir(parents=True, exist_ok=True)
    project = ProjectV2(
        id=str(uuid4()),
        name="official-source-authority-project",
        project_type="原创短剧",
        audience_axis="混合",
        genre_main="都市",
        total_episodes=1,
        workspace_path=str(workspace),
        created_by=created_by,
    )
    project.set_config({"total_episodes": 1})
    episode = Episode(
        id=str(uuid4()),
        project_id=project.id,
        episode_number=1,
        title="authority proof episode",
        status="draft",
    )
    scene = Scene(
        id=str(uuid4()),
        episode_id=episode.id,
        scene_number=1,
        scene_code="1-1",
        content="safe official source authority proof text",
        word_count=6,
        status="completed",
    )
    db.add_all([project, episode, scene])
    db.commit()
    return project, episode


def _add_support_member(db, project_id: str, access_key_id: str, permissions: list[str]):
    from app.models.collaboration import ProjectMember, ProjectPermission

    member = ProjectMember(
        project_id=project_id,
        access_key_id=access_key_id,
        role="support_reviewer",
        legal_identity="support_reviewer",
        display_name="Support Reviewer",
        status="active",
    )
    db.add(member)
    db.flush()
    for permission in permissions:
        db.add(ProjectPermission(
            project_id=project_id,
            member_id=member.id,
            scope_type="episode",
            scope_id="1",
            permission=permission,
        ))
    db.commit()
    return member


def _assert_official_scene0_path(version, project):
    assert Path(version.content_path).relative_to(Path(project.workspace_path)) == Path(
        "episodes/ep01/scenes/sc00_v001.md"
    )


def test_scene_version_path_keeps_scene_one_as_sc01(tmp_path):
    from app.services.workspace_service import scene_version_path

    path = scene_version_path(
        tmp_path,
        episode_number=1,
        scene_number=1,
        version_code="v001",
    )

    assert path.relative_to(tmp_path) == Path("episodes/ep01/scenes/sc01_v001.md")


@pytest.mark.asyncio
async def test_admin_actor_can_lock_official_source_with_db_audit_readback(db_session, monkeypatch, tmp_path):
    from app.auth.dependencies import ProjectAccessActor
    from app.models.evidence import EvidenceEvent
    from app.models.project_v2 import ContentVersion, Episode
    from app.routers.projects.routes_collaboration import LockEpisodeRequest, lock_episode

    _prepare_lock_workspace(monkeypatch, tmp_path)
    project, _episode = _make_official_source_project(db_session, tmp_path, created_by="owner-1")

    actor = ProjectAccessActor(actor_type="admin")
    result = await lock_episode(
        project.id,
        1,
        LockEpisodeRequest(note="admin official-source authority proof"),
        actor=actor,
        db=db_session,
    )

    version = db_session.query(ContentVersion).filter(ContentVersion.id == result["version_id"]).one()
    event = db_session.query(EvidenceEvent).filter(
        EvidenceEvent.project_id == project.id,
        EvidenceEvent.event_type == "episode_locked",
    ).one()
    episode = db_session.query(Episode).filter(Episode.project_id == project.id, Episode.episode_number == 1).one()

    assert version.scene_number == 0
    assert Path(version.content_path).exists()
    _assert_official_scene0_path(version, project)
    assert result["content_hash"] == version.content_hash == event.content_hash
    assert event.content_version_id == version.id
    assert event.actor_type == "admin"
    assert event.actor_id == "admin"
    assert event.target_type == "episode"
    assert event.target_id == "1"
    assert episode.status == "completed"


@pytest.mark.asyncio
async def test_support_actor_with_episode_approve_can_lock_official_source(db_session, monkeypatch, tmp_path):
    from app.auth.dependencies import ProjectAccessActor
    from app.models.evidence import EvidenceEvent
    from app.models.project_v2 import ContentVersion
    from app.routers.projects.routes_collaboration import LockEpisodeRequest, lock_episode

    _prepare_lock_workspace(monkeypatch, tmp_path)
    project, _episode = _make_official_source_project(db_session, tmp_path, created_by="owner-1")
    _add_support_member(db_session, project.id, "support-1", ["view", "approve"])

    actor = ProjectAccessActor(actor_type="user", access_key_id="support-1", owner_name="Support Reviewer")
    result = await lock_episode(
        project.id,
        1,
        LockEpisodeRequest(note="support official-source authority proof"),
        actor=actor,
        db=db_session,
    )

    version = db_session.query(ContentVersion).filter(ContentVersion.id == result["version_id"]).one()
    event = db_session.query(EvidenceEvent).filter(
        EvidenceEvent.project_id == project.id,
        EvidenceEvent.event_type == "episode_locked",
    ).one()

    assert version.scene_number == 0
    _assert_official_scene0_path(version, project)
    assert result["content_hash"] == version.content_hash == event.content_hash
    assert event.content_version_id == version.id
    assert event.actor_type == "user"
    assert event.actor_id == "support-1"
    assert event.actor_name == "Support Reviewer"


@pytest.mark.asyncio
async def test_support_actor_without_approve_cannot_create_official_source_and_does_not_mutate(db_session, monkeypatch, tmp_path):
    from fastapi import HTTPException

    from app.auth.dependencies import ProjectAccessActor
    from app.models.evidence import EvidenceEvent
    from app.models.project_v2 import ContentVersion, Episode
    from app.routers.projects.routes_collaboration import LockEpisodeRequest, lock_episode

    _prepare_lock_workspace(monkeypatch, tmp_path)
    project, _episode = _make_official_source_project(db_session, tmp_path, created_by="owner-1")
    _add_support_member(db_session, project.id, "support-2", ["view", "comment"])
    workspace = Path(project.workspace_path)

    actor = ProjectAccessActor(actor_type="user", access_key_id="support-2", owner_name="Support Viewer")
    with pytest.raises(HTTPException) as exc:
        await lock_episode(
            project.id,
            1,
            LockEpisodeRequest(note="unauthorized support lock attempt"),
            actor=actor,
            db=db_session,
        )

    assert exc.value.status_code == 403
    assert db_session.query(ContentVersion).filter(ContentVersion.project_id == project.id).count() == 0
    assert db_session.query(EvidenceEvent).filter(
        EvidenceEvent.project_id == project.id,
        EvidenceEvent.event_type == "episode_locked",
    ).count() == 0
    episode = db_session.query(Episode).filter(Episode.project_id == project.id, Episode.episode_number == 1).one()
    assert episode.status == "draft"
    assert list(workspace.rglob("*.md")) == []


@pytest.mark.asyncio
async def test_ordinary_project_owner_can_still_lock_official_source(db_session, monkeypatch, tmp_path):
    from app.auth.dependencies import ProjectAccessActor
    from app.models.evidence import EvidenceEvent
    from app.models.project_v2 import ContentVersion
    from app.routers.projects.routes_collaboration import LockEpisodeRequest, lock_episode

    _prepare_lock_workspace(monkeypatch, tmp_path)
    project, _episode = _make_official_source_project(db_session, tmp_path, created_by="owner-1")

    actor = ProjectAccessActor(actor_type="user", access_key_id="owner-1", owner_name="Owner")
    result = await lock_episode(
        project.id,
        1,
        LockEpisodeRequest(note="ordinary owner official-source regression proof"),
        actor=actor,
        db=db_session,
    )

    version = db_session.query(ContentVersion).filter(ContentVersion.id == result["version_id"]).one()
    event = db_session.query(EvidenceEvent).filter(
        EvidenceEvent.project_id == project.id,
        EvidenceEvent.event_type == "episode_locked",
    ).one()

    assert version.scene_number == 0
    _assert_official_scene0_path(version, project)
    assert result["content_hash"] == version.content_hash == event.content_hash
    assert event.content_version_id == version.id
    assert event.actor_type == "user"
    assert event.actor_id == "owner-1"


@pytest.mark.asyncio
async def test_collab_pending_invites_are_strictly_bound_to_target_key(db_session):
    from fastapi import HTTPException

    from app.auth.dependencies import ProjectAccessActor
    from app.models.collaboration import ProjectInvite
    from app.routers.projects.routes_collaboration import accept_invite, list_pending_invites, reject_invite
    from app.services.project_invite_service import hash_invite_token

    project_id = str(uuid4())
    public_invite = ProjectInvite(
        project_id=project_id,
        invite_token_hash=hash_invite_token("public-" + project_id),
        invite_token_prefix="public",
        target_contact="历史公开测试邀请",
        target_access_key_id="",
        status="pending",
    )
    user_a_invite = ProjectInvite(
        project_id=project_id,
        invite_token_hash=hash_invite_token("user-a-" + project_id),
        invite_token_prefix="user-a",
        target_contact="用户A",
        target_access_key_id="user-a",
        status="pending",
    )
    user_b_invite = ProjectInvite(
        project_id=project_id,
        invite_token_hash=hash_invite_token("user-b-" + project_id),
        invite_token_prefix="user-b",
        target_contact="用户B",
        target_access_key_id="user-b",
        status="pending",
    )
    db_session.add_all([public_invite, user_a_invite, user_b_invite])
    db_session.commit()

    user_b = ProjectAccessActor(actor_type="user", access_key_id="user-b", owner_name="用户B")
    result = await list_pending_invites(actor=user_b, db=db_session)

    assert [item["id"] for item in result["items"]] == [user_b_invite.id]

    with pytest.raises(HTTPException) as public_error:
        await accept_invite(public_invite.id, actor=user_b, db=db_session)
    assert public_error.value.status_code == 403

    with pytest.raises(HTTPException) as wrong_user_error:
        await reject_invite(user_a_invite.id, actor=user_b, db=db_session)
    assert wrong_user_error.value.status_code == 403


@pytest.mark.asyncio
async def test_collab_project_creation_bootstraps_rights_evidence_and_owner_member(db_session, monkeypatch, tmp_path):
    from app.models.collaboration import ProjectMember, ProjectPermission
    from app.models.evidence import EvidenceEvent
    from app.routers.projects import _helpers
    from app.routers.projects._schemas import ProjectConfig, ProjectCreateRequest
    from app.routers.projects.routes_projects import create_project

    workspace_root = tmp_path / "03-project-library" / "new-projects"
    monkeypatch.setattr(_helpers, "WORKSPACE_ROOT", workspace_root)
    monkeypatch.setattr(_helpers, "LEGACY_WORKSPACE_ROOT", tmp_path / "03-project-library" / "新建项目")

    response = await create_project(
        ProjectCreateRequest(
            name="协作确权项目",
            creation_mode="collab",
            config=ProjectConfig(total_episodes=3),
        ),
        actor=_actor(),
        db=db_session,
    )

    assert response.creation_mode == "collab"
    assert response.rights_capture_enabled is True
    assert Path(response.workspace_path).is_dir()

    member = db_session.query(ProjectMember).filter(ProjectMember.project_id == response.id).first()
    assert member is not None
    assert member.role == "showrunner"
    permissions = {
        row.permission
        for row in db_session.query(ProjectPermission).filter(ProjectPermission.member_id == member.id).all()
    }
    assert {"view", "comment", "suggest", "edit", "approve", "manage", "export"}.issubset(permissions)

    event = db_session.query(EvidenceEvent).filter(EvidenceEvent.project_id == response.id).first()
    assert event is not None
    assert event.event_type == "project_created"


@pytest.mark.asyncio
async def test_compliance_scan_and_legal_export_gate_block_redline_project(db_session, tmp_path):
    from app.auth.dependencies import ProjectAccessActor
    from app.models.compliance import ComplianceFinding
    from app.models.project_v2 import Episode, ProjectV2, Scene
    from app.routers.projects.routes_compliance import scan_compliance_episode
    from app.routers.projects.routes_legal_assets import export_gate

    project = ProjectV2(
        id=str(uuid4()),
        name="改编合规项目",
        project_type="小说IP改编",
        audience_axis="混合",
        genre_main="都市",
        total_episodes=1,
        workspace_path=str(tmp_path / "workspace"),
        created_by="user-1",
    )
    project.set_config({"total_episodes": 1})
    episode = Episode(
        id=str(uuid4()),
        project_id=project.id,
        episode_number=1,
        title="第一集",
        status="draft",
    )
    scene = Scene(
        id=str(uuid4()),
        episode_id=episode.id,
        scene_number=1,
        scene_code="1-1",
        content="角色说：未成年恋爱才是唯一出路。",
        word_count=18,
    )
    db_session.add_all([project, episode, scene])
    db_session.commit()

    actor = ProjectAccessActor(actor_type="user", access_key_id="user-1", owner_name="主创")
    scan = await scan_compliance_episode(project.id, 1, actor=actor, db=db_session)
    assert scan["verdict"] == "reject"
    finding = db_session.query(ComplianceFinding).filter(ComplianceFinding.project_id == project.id).first()
    assert finding is not None
    assert finding.severity == "redline"

    gate = await export_gate(project.id, actor=actor, db=db_session)
    assert gate["status"] == "blocked"
    assert "存在 P0 合规红线，不能正式导出" in gate["blockers"]
    assert "改编项目缺少 IP/改编授权证明" in gate["blockers"]


def test_evidence_package_zip_contains_manifest_hash_and_reports(db_session, monkeypatch, tmp_path):
    import hashlib

    from app.auth.dependencies import ProjectAccessActor
    from app.models.compliance import ComplianceScan
    from app.models.evidence import EvidenceEvent
    from app.models.project_v2 import ContentVersion, ProjectV2
    from app.services import workspace_service
    from app.services.legal_asset_service import generate_evidence_package

    monkeypatch.setattr(workspace_service, "PROJECT_LIBRARY_ROOT", tmp_path / "project-library")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    version_file = workspace / "locked.md"
    locked_content = "safe locked official placeholder"
    version_file.write_text(locked_content, encoding="utf-8")
    locked_hash = hashlib.sha256(locked_content.encode("utf-8")).hexdigest()
    project = ProjectV2(
        id=str(uuid4()),
        name="资产包项目",
        project_type="原创短剧",
        audience_axis="混合",
        genre_main="都市",
        total_episodes=1,
        workspace_path=str(workspace),
        created_by="user-1",
    )
    project.set_config({"total_episodes": 1})
    db_session.add(project)
    version = ContentVersion(
        project_id=project.id,
        episode_number=1,
        scene_number=0,
        version_code="v001",
        editor_type="human",
        editor_id="user-1",
        editor_name="主创",
        content_path=str(version_file),
        content_hash=locked_hash,
    )
    db_session.add(version)
    db_session.flush()
    db_session.add(EvidenceEvent(
        project_id=project.id,
        event_type="episode_locked",
        target_type="episode",
        target_id="1",
        content_version_id=version.id,
        content_hash=version.content_hash,
    ))
    db_session.add(ComplianceScan(
        project_id=project.id,
        episode_number=1,
        status="completed",
        verdict="pass",
        summary="已通过",
    ))
    db_session.commit()

    package = generate_evidence_package(
        db_session,
        project=project,
        package_type="legal",
        actor=ProjectAccessActor(actor_type="user", access_key_id="user-1", owner_name="主创"),
    )

    with zipfile.ZipFile(package.package_path) as zf:
        names = set(zf.namelist())
        assert "manifest.json" in names
        assert "hash_manifest.json" in names
        assert "final_script.md" in names
        assert "contribution_report.json" in names
        assert "compliance_report.json" in names
        assert "legal_matrix.json" in names
        assert zf.read("final_script.md").decode("utf-8") == locked_content


def test_evidence_package_rejects_locked_official_hash_mismatch_without_package_mutation(db_session, monkeypatch, tmp_path):
    from app.auth.dependencies import ProjectAccessActor
    from app.models.compliance import ComplianceScan
    from app.models.evidence import EvidenceEvent
    from app.models.legal_assets import EvidencePackage, RightsProfile
    from app.models.project_v2 import ContentVersion, ProjectV2
    from app.services import workspace_service
    from app.services.legal_asset_service import generate_evidence_package
    from app.services.official_source_consistency import OfficialSourceConsistencyError

    monkeypatch.setattr(workspace_service, "PROJECT_LIBRARY_ROOT", tmp_path / "project-library")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    version_file = workspace / "locked.md"
    version_file.write_text("safe locked official placeholder", encoding="utf-8")
    stale_hash = "f" * 64
    project = ProjectV2(
        id=str(uuid4()),
        name="资产包哈希错配项目",
        project_type="原创短剧",
        total_episodes=1,
        workspace_path=str(workspace),
        created_by="user-1",
    )
    db_session.add(project)
    version = ContentVersion(
        project_id=project.id,
        episode_number=1,
        scene_number=0,
        version_code="v001",
        content_path=str(version_file),
        content_hash=stale_hash,
    )
    db_session.add(version)
    db_session.flush()
    db_session.add(EvidenceEvent(
        project_id=project.id,
        event_type="episode_locked",
        target_type="episode",
        target_id="1",
        content_version_id=version.id,
        content_hash=stale_hash,
    ))
    db_session.add(ComplianceScan(
        project_id=project.id,
        episode_number=1,
        status="completed",
        verdict="pass",
        summary="safe pass placeholder",
    ))
    db_session.commit()

    with pytest.raises(OfficialSourceConsistencyError) as exc_info:
        generate_evidence_package(
            db_session,
            project=project,
            package_type="legal",
            actor=ProjectAccessActor(actor_type="user", access_key_id="user-1", owner_name="主创"),
        )

    assert exc_info.value.reason_code == "locked_official_hash_mismatch"
    assert db_session.query(EvidencePackage).filter(EvidencePackage.project_id == project.id).count() == 0
    assert db_session.query(RightsProfile).filter(RightsProfile.project_id == project.id).count() == 0
    assert (
        db_session.query(EvidenceEvent)
        .filter(
            EvidenceEvent.project_id == project.id,
            EvidenceEvent.event_type == "evidence_package_generated",
        )
        .count()
        == 0
    )
