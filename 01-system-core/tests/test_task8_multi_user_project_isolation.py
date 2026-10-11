from __future__ import annotations

import hashlib
import json
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


@pytest.fixture()
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
        f"sqlite:///{tmp_path / 'task8-isolation.db'}",
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


def _actor(access_key_id: str):
    from app.auth.dependencies import ProjectAccessActor

    return ProjectAccessActor(actor_type="user", access_key_id=access_key_id, owner_name=access_key_id)


def _seed_project_bundle(db, tmp_path, *, owner: str, name: str):
    from app.models.compliance import ComplianceFinding, ComplianceScan
    from app.models.evidence import ApprovalTask, EvidenceEvent
    from app.models.legal_assets import LegalMaterial, RightsProfile
    from app.models.project_v2 import ContentVersion, ContributionLedger, Episode, GenerationJob, ProjectV2, Scene

    project_id = str(uuid4())
    workspace = tmp_path / "workspaces" / owner / project_id
    workspace.mkdir(parents=True, exist_ok=True)
    project_data = {
        "name": name,
        "characters": [{"name": f"{name}-character"}],
        "state_cards": {"episode_states": [{"episode": 1, "status": "locked"}]},
        "workflow_context": {"confirmed_total_episodes": 1},
    }
    (workspace / "project.json").write_text(json.dumps(project_data), encoding="utf-8")

    project = ProjectV2(
        id=project_id,
        name=name,
        project_type="original_short_drama",
        audience_axis="mixed",
        genre_main="urban",
        total_episodes=1,
        current_episode=1,
        workspace_path=str(workspace),
        created_by=owner,
    )
    project.set_config({"confirmed_total_episodes": 1, "total_episodes": 1})
    episode = Episode(
        id=str(uuid4()),
        project_id=project_id,
        episode_number=1,
        title=f"{name}-episode",
        summary=f"{name}-safe-summary",
        status="completed",
        compliance_status="pass",
    )
    scene = Scene(
        id=str(uuid4()),
        episode_id=episode.id,
        scene_number=1,
        scene_code="1-1",
        content="safe seeded scene content",
        word_count=4,
        status="completed",
    )
    locked_path = workspace / "episodes" / "ep01" / "scenes" / "sc00_v001.md"
    locked_path.parent.mkdir(parents=True, exist_ok=True)
    locked_path.write_text("safe locked source content", encoding="utf-8")
    content_hash = hashlib.sha256(locked_path.read_bytes()).hexdigest()
    version = ContentVersion(
        id=str(uuid4()),
        project_id=project_id,
        episode_number=1,
        scene_number=0,
        version_code="v001",
        editor_type="human",
        editor_id=owner,
        editor_name=owner,
        content_path=str(locked_path),
        content_hash=content_hash,
        change_note="locked source fixture",
    )
    result_path = workspace / "jobs" / "job-result.md"
    result_path.parent.mkdir(parents=True, exist_ok=True)
    result_path.write_text("safe generated fixture content", encoding="utf-8")
    job = GenerationJob(
        id=str(uuid4()),
        project_id=project_id,
        job_type="script_draft",
        episode_number=1,
        status="completed",
        progress=100,
        result_path=str(result_path),
        created_by=owner,
    )
    scan = ComplianceScan(
        id=str(uuid4()),
        project_id=project_id,
        episode_number=1,
        content_version_id=version.id,
        content_hash=content_hash,
        verdict="pass",
    )
    finding = ComplianceFinding(
        id=str(uuid4()),
        scan_id=scan.id,
        project_id=project_id,
        episode_number=1,
        content_version_id=version.id,
        content_hash=content_hash,
        reason="safe fixture finding",
    )
    material = LegalMaterial(
        id=str(uuid4()),
        project_id=project_id,
        material_type="script_source",
        title="safe fixture material",
        status="ready",
        content_text="safe legal material",
    )
    rights = RightsProfile(
        id=str(uuid4()),
        project_id=project_id,
        rights_status="ready",
        rights_score=90,
    )
    event = EvidenceEvent(
        id=str(uuid4()),
        project_id=project_id,
        actor_type="user",
        actor_id=owner,
        event_type="episode_locked",
        target_type="content_version",
        target_id=version.id,
        content_version_id=version.id,
        content_hash=content_hash,
        summary="safe fixture event",
    )
    approval = ApprovalTask(
        id=str(uuid4()),
        project_id=project_id,
        task_type="safe_fixture",
        title="safe fixture approval",
        requester_id=owner,
    )
    ledger = ContributionLedger(
        id=str(uuid4()),
        project_id=project_id,
        user_id=owner,
        user_name=owner,
        final_score=10,
    )
    db.add_all([project, episode, scene, version, job, scan, finding, material, rights, event, approval, ledger])
    db.commit()
    return {
        "project": project,
        "episode": episode,
        "scene": scene,
        "version": version,
        "job": job,
        "workspace": workspace,
    }


async def _assert_http_status(expected_status: int, call):
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc:
        await call()
    assert exc.value.status_code == expected_status


@pytest.mark.asyncio
async def test_user_a_cannot_read_or_write_user_b_project_surfaces(db_session, tmp_path):
    from app.models.evidence import ApprovalTask
    from app.models.legal_assets import LegalMaterial
    from app.models.project_v2 import Episode, GenerationJob
    from app.routers.projects._schemas import CharacterStoreRequest, SceneCreateRequest
    from app.routers.projects.routes_compliance import list_compliance_episodes, list_compliance_findings
    from app.routers.projects.routes_contributions import get_contributions
    from app.routers.projects.routes_episodes_scenes import create_scene, get_episode, list_scene_versions, list_scenes
    from app.routers.projects.routes_evidence_approvals import list_approval_tasks, list_evidence_events
    from app.routers.projects.routes_generation import get_generation_status
    from app.routers.projects.routes_legal_assets import ai_statement, export_gate, legal_material_matrix
    from app.routers.projects.routes_projects import get_project, list_projects
    from app.routers.projects.routes_stores import get_project_characters, save_project_characters

    user_a_bundle = _seed_project_bundle(db_session, tmp_path, owner="user-a", name="project-a")
    user_b_bundle = _seed_project_bundle(db_session, tmp_path, owner="user-b", name="project-b")
    actor_a = _actor("user-a")
    project_b = user_b_bundle["project"]

    visible_projects = await list_projects(actor=actor_a, db=db_session)
    assert [item.id for item in visible_projects] == [user_a_bundle["project"].id]

    read_attempts = [
        lambda: get_project(project_b.id, actor=actor_a, db=db_session),
        lambda: get_project_characters(project_b.id, actor=actor_a, db=db_session),
        lambda: get_episode(project_b.id, 1, actor=actor_a, db=db_session),
        lambda: list_scenes(project_b.id, 1, actor=actor_a, db=db_session),
        lambda: list_scene_versions(project_b.id, 1, 0, actor=actor_a, db=db_session),
        lambda: get_generation_status(project_b.id, user_b_bundle["job"].id, actor=actor_a, db=db_session),
        lambda: list_compliance_episodes(project_b.id, actor=actor_a, db=db_session),
        lambda: list_compliance_findings(project_b.id, actor=actor_a, db=db_session),
        lambda: legal_material_matrix(project_b.id, actor=actor_a, db=db_session),
        lambda: export_gate(project_b.id, actor=actor_a, db=db_session),
        lambda: ai_statement(project_b.id, actor=actor_a, db=db_session),
        lambda: list_evidence_events(project_b.id, actor=actor_a, db=db_session),
        lambda: list_approval_tasks(project_b.id, actor=actor_a, db=db_session),
        lambda: get_contributions(project_b.id, actor=actor_a, db=db_session),
    ]
    for attempt in read_attempts:
        await _assert_http_status(403, attempt)

    before_episodes = db_session.query(Episode).filter(Episode.project_id == project_b.id).count()
    before_materials = db_session.query(LegalMaterial).filter(LegalMaterial.project_id == project_b.id).count()
    before_jobs = db_session.query(GenerationJob).filter(GenerationJob.project_id == project_b.id).count()
    before_approvals = db_session.query(ApprovalTask).filter(ApprovalTask.project_id == project_b.id).count()

    await _assert_http_status(
        403,
        lambda: save_project_characters(
            project_b.id,
            CharacterStoreRequest(characters=[{"name": "blocked"}]),
            actor=actor_a,
            db=db_session,
        ),
    )
    await _assert_http_status(
        403,
        lambda: create_scene(
            project_b.id,
            1,
            SceneCreateRequest(scene_number=2, scene_code="1-2", content="blocked"),
            actor=actor_a,
            db=db_session,
        ),
    )

    assert db_session.query(Episode).filter(Episode.project_id == project_b.id).count() == before_episodes
    assert db_session.query(LegalMaterial).filter(LegalMaterial.project_id == project_b.id).count() == before_materials
    assert db_session.query(GenerationJob).filter(GenerationJob.project_id == project_b.id).count() == before_jobs
    assert db_session.query(ApprovalTask).filter(ApprovalTask.project_id == project_b.id).count() == before_approvals


@pytest.mark.asyncio
async def test_owned_project_route_cannot_cross_read_other_project_job_or_version(db_session, tmp_path):
    from app.routers.projects.routes_episodes_scenes import get_version_diff
    from app.routers.projects.routes_generation import get_generation_status

    project_a = _seed_project_bundle(db_session, tmp_path, owner="user-a", name="owned-project-a")
    project_b = _seed_project_bundle(db_session, tmp_path, owner="user-a", name="owned-project-b")
    actor_a = _actor("user-a")

    await _assert_http_status(
        404,
        lambda: get_generation_status(
            project_a["project"].id,
            project_b["job"].id,
            actor=actor_a,
            db=db_session,
        ),
    )
    await _assert_http_status(
        404,
        lambda: get_version_diff(
            project_a["project"].id,
            project_b["version"].id,
            actor=actor_a,
            db=db_session,
        ),
    )

    job = await get_generation_status(project_b["project"].id, project_b["job"].id, actor=actor_a, db=db_session)
    assert job.job_id == project_b["job"].id
    assert job.status == "completed"
