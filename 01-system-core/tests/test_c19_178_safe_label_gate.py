from __future__ import annotations

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
        short_drama_generation_job,
        step_version,
        storyboard,
        sub_task,
        task,
    )

    engine = create_engine(
        f"sqlite:///{tmp_path / 'c19_178_gate.db'}",
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


def _actor(**overrides):
    from app.auth.dependencies import ProjectAccessActor

    values = {
        "actor_type": "user",
        "access_key_id": "owner-1",
        "owner_name": "Owner",
        "allow_copy_export": True,
    }
    values.update(overrides)
    return ProjectAccessActor(**values)


def _make_project(db, tmp_path, *, gate_required: bool = True):
    from app.models.project_v2 import Episode, ProjectV2, Scene

    project_suffix = uuid4().hex
    workspace = tmp_path / "03-project-library" / "new-projects" / project_suffix
    workspace.mkdir(parents=True, exist_ok=True)
    project = ProjectV2(
        id=str(uuid4()),
        name=f"c19-178-safe-label-project-{project_suffix}",
        project_type="原创短剧",
        audience_axis="混合",
        genre_main="都市",
        total_episodes=1,
        workspace_path=str(workspace),
        created_by="owner-1",
    )
    config = {"total_episodes": 1}
    if gate_required:
        config["c19_178_external_human_review"] = {
            "required": True,
            "status": "awaiting_external_human_reviewer_decision",
            "candidate_job_suffix": "da228919",
            "candidate_hash_short": "d2cfa2b2ede36f31",
            "concern_label": "ending_carryover_signal_weak",
        }
    project.set_config(config)
    episode = Episode(
        id=str(uuid4()),
        project_id=project.id,
        episode_number=1,
        title="safe gate proof episode",
        status="draft",
    )
    scene = Scene(
        id=str(uuid4()),
        episode_id=episode.id,
        scene_number=1,
        scene_code="1-1",
        content="safe C19.178 gate proof text",
        word_count=5,
        status="completed",
    )
    db.add_all([project, episode, scene])
    db.commit()
    return project


def _first_scene(db, project):
    from app.models.project_v2 import Episode, Scene

    episode = db.query(Episode).filter(Episode.project_id == project.id, Episode.episode_number == 1).one()
    return db.query(Scene).filter(Scene.episode_id == episode.id, Scene.scene_number == 1).one()


def _patch_workspace_roots(monkeypatch, tmp_path):
    from app.routers.projects import _helpers
    from app.services import workspace_service

    workspace_root = tmp_path / "03-project-library" / "new-projects"
    legacy_workspace_root = tmp_path / "03-project-library" / "新建项目"
    monkeypatch.setattr(_helpers, "WORKSPACE_ROOT", workspace_root)
    monkeypatch.setattr(_helpers, "LEGACY_WORKSPACE_ROOT", legacy_workspace_root)
    monkeypatch.setattr(workspace_service, "WORKSPACE_ROOT", workspace_root)
    monkeypatch.setattr(workspace_service, "LEGACY_WORKSPACE_ROOT", legacy_workspace_root)
    return workspace_root


def test_missing_external_label_blocks_all_high_boundary_paths(db_session, tmp_path):
    from app.services.c19_178_safe_label_gate import evaluate_c19_178_runtime_gate

    project = _make_project(db_session, tmp_path, gate_required=True)

    for path in [
        "readonly_quality_audit",
        "materialization",
        "official_lock",
        "compliance_scan",
        "export_package",
        "episode5_entry",
        "gate_a",
        "gate_b",
        "gate_c",
        "gate_d",
    ]:
        decision = evaluate_c19_178_runtime_gate(db_session, project=project, target_path=path)
        assert decision.allowed is False
        assert decision.reason_code == "external_human_reviewer_decision_label_missing"


def test_invalid_label_is_rejected_and_does_not_create_intake_event(db_session, tmp_path):
    from app.models.evidence import EvidenceEvent
    from app.services.c19_178_safe_label_gate import record_c19_178_external_safe_label

    project = _make_project(db_session, tmp_path, gate_required=True)

    with pytest.raises(ValueError, match="invalid_external_human_reviewer_decision_label"):
        record_c19_178_external_safe_label(
            db_session,
            project=project,
            actor=_actor(),
            decision_label="human_claims_quality_pass",
            reason_code="unsafe_escalation",
            reviewer_role="external_reviewer",
            no_excerpts_confirmed=True,
        )

    assert db_session.query(EvidenceEvent).filter(EvidenceEvent.project_id == project.id).count() == 0


def test_all_allowed_labels_route_only_to_intended_branch_matrix(db_session, tmp_path):
    from app.services.c19_178_safe_label_gate import (
        C19_178_BRANCH_BY_LABEL,
        C19_178_HIGH_BOUNDARY_PATHS,
        evaluate_c19_178_runtime_gate,
        record_c19_178_external_safe_label,
    )

    all_authorized_branches = {branch for branches in C19_178_BRANCH_BY_LABEL.values() for branch in branches}
    matrix_paths = sorted(C19_178_HIGH_BOUNDARY_PATHS | all_authorized_branches)

    observed = {}
    for label, authorized_branches in sorted(C19_178_BRANCH_BY_LABEL.items()):
        project = _make_project(db_session, tmp_path, gate_required=True)
        record_c19_178_external_safe_label(
            db_session,
            project=project,
            actor=_actor(),
            decision_label=label,
            reason_code="external_reviewer_safe_label",
            reviewer_role="external_reviewer",
            reviewed_artifact_suffix="da228919",
            candidate_hash_short="d2cfa2b2ede36f31",
            no_excerpts_confirmed=True,
        )
        db_session.commit()

        observed[label] = {}
        for path in matrix_paths:
            decision = evaluate_c19_178_runtime_gate(db_session, project=project, target_path=path)
            observed[label][path] = decision.allowed
            if path in authorized_branches:
                assert decision.allowed is True
                assert decision.reason_code == "external_human_reviewer_decision_label_authorizes_branch"
                assert decision.allowed_branch == path
            else:
                assert decision.allowed is False
                assert decision.reason_code == "external_human_reviewer_decision_label_does_not_authorize_path"
                assert decision.allowed_branch == ",".join(sorted(authorized_branches))

    assert observed == {
        label: {path: path in branches for path in matrix_paths}
        for label, branches in sorted(C19_178_BRANCH_BY_LABEL.items())
    }


def test_safe_label_intake_rejects_protected_text_like_metadata_and_stores_only_safe_labels(db_session, tmp_path):
    from app.models.evidence import EvidenceEvent
    from app.services.c19_178_safe_label_gate import record_c19_178_external_safe_label
    from app.services.evidence_event_service import json_loads

    project = _make_project(db_session, tmp_path, gate_required=True)

    with pytest.raises(ValueError, match="no_excerpts_confirmation_required"):
        record_c19_178_external_safe_label(
            db_session,
            project=project,
            actor=_actor(),
            decision_label="human_accepts_concern_for_quality_audit",
            reason_code="external_reviewer_safe_label",
            reviewer_role="external_reviewer",
            no_excerpts_confirmed=False,
        )

    event = record_c19_178_external_safe_label(
        db_session,
        project=project,
        actor=_actor(),
        decision_label="human_requests_controlled_regeneration_plan",
        reason_code="external_reviewer_safe_label",
        reviewer_role="external_reviewer",
        reviewed_artifact_suffix="da228919",
        candidate_hash_short="d2cfa2b2ede36f31",
        no_excerpts_confirmed=True,
    )
    db_session.commit()

    stored = db_session.query(EvidenceEvent).filter(EvidenceEvent.id == event.id).one()
    metadata = json_loads(stored.metadata_json, {})
    serialized = stored.metadata_json

    assert metadata["decision_label"] == "human_requests_controlled_regeneration_plan"
    assert metadata["protected_material_persisted"] is False
    for forbidden in ["script_excerpt", "prompt", "raw_error", "provider_url", "authorization"]:
        assert forbidden not in serialized.lower()


def test_nonlogging_review_surface_accepts_safe_metadata_without_protected_text(db_session, tmp_path):
    from app.models.evidence import EvidenceEvent
    from app.services.c19_178_safe_label_gate import record_c19_178_external_safe_label
    from app.services.evidence_event_service import json_loads

    project = _make_project(db_session, tmp_path, gate_required=True)

    event = record_c19_178_external_safe_label(
        db_session,
        project=project,
        actor=_actor(),
        decision_label="human_accepts_concern_for_quality_audit",
        reason_code="external_reviewer_safe_label",
        reviewer_role="external_reviewer",
        reviewed_artifact_suffix="da228919",
        candidate_hash_short="d2cfa2b2ede36f31",
        no_excerpts_confirmed=True,
        safe_review_metadata={
            "review_channel": "external_handoff",
            "reviewer_type": "human_reviewer",
            "artifact": {
                "job_suffix": "da228919",
                "length_bucket": "2000-2499",
            },
        },
    )
    db_session.commit()

    stored = db_session.query(EvidenceEvent).filter(EvidenceEvent.id == event.id).one()
    metadata = json_loads(stored.metadata_json, {})
    serialized = stored.metadata_json.lower()

    assert metadata["safe_review_metadata"]["review_channel"] == "external_handoff"
    assert metadata["safe_review_metadata"]["artifact"]["length_bucket"] == "2000-2499"
    assert "begin_protected_text" not in serialized
    assert "protected_episode_text" not in serialized
    assert "script_excerpt" not in serialized


def test_nonlogging_review_surface_rejects_protected_text_like_metadata_without_event(db_session, tmp_path):
    from app.models.evidence import EvidenceEvent
    from app.services.c19_178_safe_label_gate import record_c19_178_external_safe_label

    project = _make_project(db_session, tmp_path, gate_required=True)

    with pytest.raises(ValueError, match="protected_material_field_not_allowed|protected_material_value_not_allowed"):
        record_c19_178_external_safe_label(
            db_session,
            project=project,
            actor=_actor(),
            decision_label="human_accepts_concern_for_quality_audit",
            reason_code="external_reviewer_safe_label",
            reviewer_role="external_reviewer",
            reviewed_artifact_suffix="da228919",
            candidate_hash_short="d2cfa2b2ede36f31",
            no_excerpts_confirmed=True,
            safe_review_metadata={
                "review_channel": "external_handoff",
                "review_note": "BEGIN_PROTECTED_TEXT synthetic placeholder must never persist",
            },
        )

    assert db_session.query(EvidenceEvent).filter(EvidenceEvent.project_id == project.id).count() == 0


def test_nonlogging_review_surface_rejects_raw_payload_and_log_keys(db_session, tmp_path):
    from app.models.evidence import EvidenceEvent
    from app.services.c19_178_safe_label_gate import record_c19_178_external_safe_label

    project = _make_project(db_session, tmp_path, gate_required=True)

    for forbidden_metadata in [
        {"raw_request_body": "synthetic-placeholder"},
        {"browser_snapshot": "synthetic-placeholder"},
        {"nested": {"script_excerpt": "synthetic-placeholder"}},
    ]:
        with pytest.raises(ValueError, match="protected_material_field_not_allowed"):
            record_c19_178_external_safe_label(
                db_session,
                project=project,
                actor=_actor(),
                decision_label="human_requests_user_edit_or_note",
                reason_code="external_reviewer_safe_label",
                reviewer_role="external_reviewer",
                no_excerpts_confirmed=True,
                safe_review_metadata=forbidden_metadata,
            )

    assert db_session.query(EvidenceEvent).filter(EvidenceEvent.project_id == project.id).count() == 0


@pytest.mark.asyncio
async def test_missing_label_blocks_official_lock_and_prevents_mutation(db_session, monkeypatch, tmp_path):
    from fastapi import HTTPException

    from app.models.evidence import EvidenceEvent
    from app.models.project_v2 import ContentVersion, Episode
    from app.routers.projects import _helpers
    from app.routers.projects.routes_collaboration import LockEpisodeRequest, lock_episode

    workspace_root = tmp_path / "03-project-library" / "new-projects"
    monkeypatch.setattr(_helpers, "WORKSPACE_ROOT", workspace_root)
    monkeypatch.setattr(_helpers, "LEGACY_WORKSPACE_ROOT", workspace_root)
    project = _make_project(db_session, tmp_path, gate_required=True)

    with pytest.raises(HTTPException) as exc:
        await lock_episode(
            project.id,
            1,
            LockEpisodeRequest(note="blocked by missing external safe label"),
            actor=_actor(),
            db=db_session,
        )

    assert exc.value.status_code == 409
    assert exc.value.detail == "external_human_reviewer_decision_label_missing"
    assert db_session.query(ContentVersion).filter(ContentVersion.project_id == project.id).count() == 0
    assert db_session.query(EvidenceEvent).filter(EvidenceEvent.project_id == project.id).count() == 0
    episode = db_session.query(Episode).filter(Episode.project_id == project.id, Episode.episode_number == 1).one()
    assert episode.status == "draft"
    assert list(Path(project.workspace_path).rglob("*.md")) == []


@pytest.mark.asyncio
async def test_missing_label_blocks_scan_and_export_without_side_effects(db_session, tmp_path):
    from fastapi import HTTPException

    from app.models.compliance import ComplianceScan
    from app.models.legal_assets import EvidencePackage
    from app.routers.projects.routes_compliance import scan_compliance_episode
    from app.routers.projects.routes_legal_assets import EvidencePackageRequest, create_evidence_package

    project = _make_project(db_session, tmp_path, gate_required=True)

    with pytest.raises(HTTPException) as scan_exc:
        await scan_compliance_episode(project.id, 1, actor=_actor(), db=db_session)
    with pytest.raises(HTTPException) as export_exc:
        await create_evidence_package(project.id, EvidencePackageRequest(package_type="legal"), actor=_actor(), db=db_session)

    assert scan_exc.value.status_code == 409
    assert export_exc.value.status_code == 409
    assert db_session.query(ComplianceScan).filter(ComplianceScan.project_id == project.id).count() == 0
    assert db_session.query(EvidencePackage).filter(EvidencePackage.project_id == project.id).count() == 0


@pytest.mark.asyncio
async def test_existing_non_c19_178_lock_path_is_not_blocked(db_session, monkeypatch, tmp_path):
    from app.models.evidence import EvidenceEvent
    from app.models.project_v2 import ContentVersion
    from app.routers.projects import _helpers
    from app.routers.projects.routes_collaboration import LockEpisodeRequest, lock_episode

    workspace_root = tmp_path / "03-project-library" / "new-projects"
    monkeypatch.setattr(_helpers, "WORKSPACE_ROOT", workspace_root)
    monkeypatch.setattr(_helpers, "LEGACY_WORKSPACE_ROOT", workspace_root)
    project = _make_project(db_session, tmp_path, gate_required=False)

    result = await lock_episode(
        project.id,
        1,
        LockEpisodeRequest(note="ordinary lock regression"),
        actor=_actor(),
        db=db_session,
    )

    version = db_session.query(ContentVersion).filter(ContentVersion.id == result["version_id"]).one()
    event = db_session.query(EvidenceEvent).filter(
        EvidenceEvent.project_id == project.id,
        EvidenceEvent.event_type == "episode_locked",
    ).one()
    assert version.scene_number == 0
    assert event.content_version_id == version.id


def test_safe_label_gate_never_dispatches_c19_179(db_session, tmp_path):
    from app.models.evidence import EvidenceEvent
    from app.services.c19_178_safe_label_gate import (
        C19_178_BRANCH_BY_LABEL,
        evaluate_c19_178_runtime_gate,
        record_c19_178_external_safe_label,
    )

    for label in sorted(C19_178_BRANCH_BY_LABEL):
        project = _make_project(db_session, tmp_path, gate_required=True)
        record_c19_178_external_safe_label(
            db_session,
            project=project,
            actor=_actor(),
            decision_label=label,
            reason_code="external_reviewer_safe_label",
            reviewer_role="external_reviewer",
            reviewed_artifact_suffix="da228919",
            candidate_hash_short="d2cfa2b2ede36f31",
            no_excerpts_confirmed=True,
        )
        db_session.commit()

        decision = evaluate_c19_178_runtime_gate(db_session, project=project, target_path="episode5_entry")

        assert decision.allowed is False
        assert "c19_179" not in decision.reason_code.lower()
    assert db_session.query(EvidenceEvent).filter(EvidenceEvent.event_type.ilike("%c19_179%")).count() == 0


@pytest.mark.asyncio
async def test_missing_label_blocks_marked_materialization_without_scene_mutation(db_session, monkeypatch, tmp_path):
    from fastapi import HTTPException

    from app.models.evidence import EvidenceEvent
    from app.models.project_v2 import ContentVersion, Scene
    from app.routers.projects._schemas import ContentSaveRequest
    from app.routers.projects.routes_episodes_scenes import save_scene_content

    _patch_workspace_roots(monkeypatch, tmp_path)
    project = _make_project(db_session, tmp_path, gate_required=True)
    scene = _first_scene(db_session, project)
    before_content = scene.content

    with pytest.raises(HTTPException) as exc:
        await save_scene_content(
            project.id,
            1,
            1,
            ContentSaveRequest(
                content="synthetic candidate materialization placeholder",
                editor_type="human",
                change_note="确认候选并保存",
                c19_178_materialization=True,
            ),
            actor=_actor(),
            db=db_session,
        )

    assert exc.value.status_code == 409
    assert exc.value.detail == "external_human_reviewer_decision_label_missing"
    db_session.expire_all()
    saved_scene = db_session.query(Scene).filter(Scene.id == scene.id).one()
    assert saved_scene.content == before_content
    assert db_session.query(ContentVersion).filter(ContentVersion.project_id == project.id).count() == 0
    assert db_session.query(EvidenceEvent).filter(EvidenceEvent.project_id == project.id).count() == 0
    assert list(Path(project.workspace_path).rglob("*.md")) == []


@pytest.mark.asyncio
async def test_missing_label_does_not_block_ordinary_human_scene_save(db_session, monkeypatch, tmp_path):
    from app.models.project_v2 import ContentVersion
    from app.routers.projects._schemas import ContentSaveRequest
    from app.routers.projects.routes_episodes_scenes import save_scene_content

    _patch_workspace_roots(monkeypatch, tmp_path)
    project = _make_project(db_session, tmp_path, gate_required=True)

    result = await save_scene_content(
        project.id,
        1,
        1,
        ContentSaveRequest(
            content="ordinary human safe edit placeholder",
            editor_type="human",
            change_note="普通手动保存",
            create_checkpoint=False,
        ),
        actor=_actor(),
        db=db_session,
    )

    version = db_session.query(ContentVersion).filter(ContentVersion.id == result.id).one()
    assert version.editor_type == "human"
    assert version.change_note == "普通手动保存"


@pytest.mark.asyncio
async def test_missing_label_blocks_restore_of_generated_version_without_new_version(db_session, monkeypatch, tmp_path):
    from fastapi import HTTPException

    from app.models.project_v2 import ContentVersion, Scene
    from app.routers.projects.routes_episodes_scenes import restore_version

    _patch_workspace_roots(monkeypatch, tmp_path)
    project = _make_project(db_session, tmp_path, gate_required=True)
    scene = _first_scene(db_session, project)
    version_file = Path(project.workspace_path) / "synthetic-generated-version.md"
    version_file.write_text("synthetic generated version placeholder", encoding="utf-8")
    generated_version = ContentVersion(
        project_id=project.id,
        episode_number=1,
        scene_number=1,
        version_code="v900",
        editor_type="ai",
        editor_id="ai-writer",
        editor_name="AI",
        content_path=str(version_file),
        content_hash="0" * 64,
        diff_stats="{}",
        contribution_score=1,
        change_note="synthetic generated candidate",
    )
    db_session.add(generated_version)
    db_session.commit()

    with pytest.raises(HTTPException) as exc:
        await restore_version(
            project.id,
            1,
            1,
            "v900",
            actor=_actor(),
            db=db_session,
        )

    assert exc.value.status_code == 409
    assert exc.value.detail == "external_human_reviewer_decision_label_missing"
    assert db_session.query(ContentVersion).filter(ContentVersion.project_id == project.id).count() == 1
    db_session.refresh(scene)
    assert scene.content == "safe C19.178 gate proof text"


@pytest.mark.asyncio
async def test_missing_label_blocks_project_generation_job_before_creation(db_session, tmp_path):
    from fastapi import BackgroundTasks, HTTPException

    from app.models.project_v2 import GenerationJob
    from app.routers.projects._schemas import GenerationRequest
    from app.routers.projects.routes_generation import create_generation_job

    project = _make_project(db_session, tmp_path, gate_required=True)

    with pytest.raises(HTTPException) as exc:
        await create_generation_job(
            project.id,
            GenerationRequest(job_type="scene_draft", episode_number=5),
            BackgroundTasks(),
            actor=_actor(actor_type="admin"),
            db=db_session,
        )

    assert exc.value.status_code == 409
    assert exc.value.detail == "external_human_reviewer_decision_label_missing"
    assert db_session.query(GenerationJob).filter(GenerationJob.project_id == project.id).count() == 0


@pytest.mark.asyncio
async def test_missing_label_blocks_short_drama_job_before_creation(db_session, tmp_path):
    from fastapi import BackgroundTasks, HTTPException

    from app.models.short_drama_generation_job import ShortDramaGenerationJob
    from app.routers.short_drama.scene_routes import start_testing_script_scene_job
    from app.schemas.short_drama_writing import TestingScriptRequest

    project = _make_project(db_session, tmp_path, gate_required=True)

    with pytest.raises(HTTPException) as exc:
        await start_testing_script_scene_job(
            TestingScriptRequest(project_id=project.id, episode_no=5, scene_no=1),
            BackgroundTasks(),
            actor=_actor(actor_type="admin"),
            db=db_session,
        )

    assert exc.value.status_code == 409
    assert exc.value.detail == "external_human_reviewer_decision_label_missing"
    assert db_session.query(ShortDramaGenerationJob).filter(ShortDramaGenerationJob.project_id == project.id).count() == 0
