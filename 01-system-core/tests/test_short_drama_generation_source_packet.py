from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.evidence import EvidenceEvent
from app.models.project_v2 import ContentVersion, Episode, ProjectV2


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
        f"sqlite:///{tmp_path / 'generation-source-packet.db'}",
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
def project_workspace(db_session, tmp_path, monkeypatch):
    from app.services import workspace_service

    workspace_path = tmp_path / "workspace"
    workspace_path.mkdir()
    (workspace_path / "project.json").write_text(
        json.dumps({
            "workflow_context": {
                "outline_state": {},
                "materials": [],
            },
            "characters": [],
            "state_cards": {},
        }, ensure_ascii=False),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        workspace_service,
        "project_workspace_roots",
        lambda *, include_legacy=True: (tmp_path,),
    )
    project = ProjectV2(
        id="project-source-packet",
        name="source packet project",
        config="{}",
        workspace_path=str(workspace_path),
    )
    db_session.add(project)
    db_session.commit()
    return project


def _write_project_json(workspace_path: str, payload: dict) -> None:
    (Path(workspace_path) / "project.json").write_text(
        json.dumps(payload, ensure_ascii=False),
        encoding="utf-8",
    )


def _add_episode(db, project_id: str, episode_number: int) -> Episode:
    episode = Episode(
        id=f"episode-{episode_number}",
        project_id=project_id,
        episode_number=episode_number,
        title=f"Episode {episode_number}",
    )
    db.add(episode)
    db.commit()
    return episode


def _seed_locked_official(
    db,
    workspace,
    *,
    project_id: str,
    episode_number: int,
    content: str = "safe locked official placeholder",
) -> tuple[ContentVersion, str]:
    locked_file = workspace / f"locked-ep{episode_number}.md"
    locked_file.write_text(content, encoding="utf-8")
    content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
    version = ContentVersion(
        id=f"locked-version-ep{episode_number}",
        project_id=project_id,
        episode_number=episode_number,
        scene_number=0,
        version_code="v001",
        content_path=str(locked_file),
        content_hash=content_hash,
    )
    db.add(version)
    db.add(EvidenceEvent(
        id=f"locked-event-ep{episode_number}",
        project_id=project_id,
        event_type="episode_locked",
        target_type="episode",
        target_id=str(episode_number),
        content_version_id=version.id,
        content_hash=content_hash,
    ))
    db.commit()
    return version, content_hash


def test_previous_episode_packet_allows_episode_one_without_previous(db_session, project_workspace):
    from app.services.short_drama_generation_source_packet import compile_previous_episode_continuity_packet

    packet = compile_previous_episode_continuity_packet(
        db_session,
        project_id=project_workspace.id,
        episode_no=1,
        project_workspace_path=project_workspace.workspace_path,
    )

    assert packet["ready"] is True
    assert packet["source"] == "series_start"
    assert packet["previous_episode_no"] == 0


def test_previous_episode_packet_blocks_when_previous_locked_source_missing(db_session, project_workspace):
    from app.services.short_drama_generation_source_packet import (
        GenerationSourceBlocked,
        compile_previous_episode_continuity_packet,
    )

    _add_episode(db_session, project_workspace.id, 1)

    with pytest.raises(GenerationSourceBlocked) as exc:
        compile_previous_episode_continuity_packet(
            db_session,
            project_id=project_workspace.id,
            episode_no=2,
            project_workspace_path=project_workspace.workspace_path,
        )

    assert exc.value.reason_code == "previous_official_source_missing"
    assert exc.value.detail["previous_episode_no"] == 1
    assert exc.value.detail["source_reason"] == "locked_official_source_missing"


def test_previous_episode_packet_reads_locked_official_source(db_session, project_workspace, tmp_path):
    from app.services.short_drama_generation_source_packet import compile_previous_episode_continuity_packet

    _add_episode(db_session, project_workspace.id, 1)
    version, content_hash = _seed_locked_official(
        db_session,
        Path(project_workspace.workspace_path),
        project_id=project_workspace.id,
        episode_number=1,
        content="first line\nfinal official locked tail",
    )

    packet = compile_previous_episode_continuity_packet(
        db_session,
        project_id=project_workspace.id,
        episode_no=2,
        project_workspace_path=project_workspace.workspace_path,
    )

    assert packet["ready"] is True
    assert packet["source"] == "episode_locked_content_version"
    assert packet["source_label"] == "episode_locked_content_version"
    assert packet["official_source"] == "episode_locked"
    assert packet["previous_episode_no"] == 1
    assert packet["content_version_id"] == version.id
    assert packet["content_hash"] == content_hash
    assert packet["episode_locked_event_id"] == "locked-event-ep1"
    assert packet["source_map"]["source"] == "episode_locked_content_version"
    assert packet["tail_excerpt"] == "final official locked tail"
    assert "first line" in packet["body_excerpt"]


def test_previous_episode_briefs_do_not_satisfy_official_source_gate(db_session, project_workspace):
    from app.services.short_drama_generation_source_packet import (
        GenerationSourceBlocked,
        compile_previous_episode_continuity_packet,
    )

    _add_episode(db_session, project_workspace.id, 1)

    with pytest.raises(GenerationSourceBlocked) as exc:
        compile_previous_episode_continuity_packet(
            db_session,
            project_id=project_workspace.id,
            episode_no=2,
            project_workspace_path=project_workspace.workspace_path,
            previous_episode_briefs=[
                {"episode_no": 1, "summary": "stale previous brief must not become official source"},
            ],
        )

    assert exc.value.reason_code == "previous_official_source_missing"
    assert exc.value.detail["ignored_inputs"] == ["previous_episode_briefs"]


def test_manual_edit_context_cannot_override_locked_official_source(db_session, project_workspace, tmp_path):
    from app.services.short_drama_generation_source_packet import compile_previous_episode_continuity_packet

    _add_episode(db_session, project_workspace.id, 1)
    version, _content_hash = _seed_locked_official(
        db_session,
        Path(project_workspace.workspace_path),
        project_id=project_workspace.id,
        episode_number=1,
        content="official continuity only",
    )

    packet = compile_previous_episode_continuity_packet(
        db_session,
        project_id=project_workspace.id,
        episode_no=2,
        project_workspace_path=project_workspace.workspace_path,
        manual_edit_context={
            "content_version_id": "manual-stale-version",
            "continuity_from_previous": "manual context must not replace official source",
        },
    )

    assert packet["source"] == "episode_locked_content_version"
    assert packet["content_version_id"] == version.id
    assert packet["authority_trace"]["manual_edit_context"]["source"] == "supplement_only"
    assert packet["authority_trace"]["manual_edit_context"]["used_as_official_source"] is False
    assert "manual_edit_context_ignored_for_previous_official_source" in packet["warnings"]


def test_generation_source_packet_reports_missing_backend_materials(db_session, project_workspace):
    from app.services.short_drama_generation_source_packet import compile_generation_source_packet

    packet = compile_generation_source_packet(
        db_session,
        project_id=project_workspace.id,
        episode_no=1,
        project_workspace_path=project_workspace.workspace_path,
        frontend_packet={
            "user_confirmed_generation_packet": {
                "characters": [{"name": "frontend-only-character"}],
                "confirmed_total_episodes": 12,
            },
        },
    )

    assert packet["source"] == "backend_compiled_generation_source_packet"
    assert packet["source_packet_version"] == "generation_source_packet.v1"
    assert packet["episode_no"] == 1
    assert packet["authority_trace"]["previous_episode_continuity"]["source"] == "series_start"
    assert "characters_missing" in packet["blocking_issues"]
    assert "confirmed_total_episodes_missing" in packet["blocking_issues"]
    assert packet["authority_trace"]["frontend_packet"]["source"] == "compatibility_input_only"
    assert packet["authority_trace"]["frontend_packet"]["used_as_authority_source"] is False


def test_generation_source_packet_uses_backend_workspace_sources(db_session, project_workspace):
    from app.services.short_drama_generation_source_packet import compile_generation_source_packet

    project_workspace.set_config({"confirmed_total_episodes": 6})
    db_session.add(project_workspace)
    db_session.commit()
    _write_project_json(project_workspace.workspace_path, {
        "workflow_context": {
            "outline_state": {"source": "backend-outline-state"},
            "materials": [{"id": "material-1"}],
        },
        "characters": [
            {"name": "backend-character", "role": "protagonist"},
        ],
        "state_cards": {"episode_1": {"status": "ready"}},
    })

    packet = compile_generation_source_packet(
        db_session,
        project_id=project_workspace.id,
        episode_no=1,
        project_workspace_path=project_workspace.workspace_path,
        frontend_packet={"characters": [{"name": "frontend-only-character"}]},
    )

    assert packet["blocking_issues"] == []
    assert packet["confirmed_total_episodes"] == 6
    assert packet["characters_count"] == 1
    assert packet["state_cards_keys"] == ["episode_1"]
    assert packet["outline_source"]["outline_state"]["source"] == "backend-outline-state"
    assert packet["authority_trace"]["characters"]["source"] == "project_workspace.characters"
    assert packet["authority_trace"]["confirmed_total_episodes"]["source"] == "project.config.confirmed_total_episodes"


def test_generation_source_packet_reuses_previous_episode_continuity_packet(
    db_session,
    project_workspace,
    monkeypatch,
):
    from app.services import short_drama_generation_source_packet as source_packet_service

    calls: list[dict[str, object]] = []

    def fake_previous_episode_packet(db, **kwargs):
        calls.append(kwargs)
        return {
            "source": "episode_locked_content_version",
            "content_version_id": "locked-by-package-2",
            "ready": True,
        }

    monkeypatch.setattr(
        source_packet_service,
        "compile_previous_episode_continuity_packet",
        fake_previous_episode_packet,
    )
    project_workspace.set_config({"confirmed_total_episodes": 6})
    db_session.add(project_workspace)
    db_session.commit()
    _write_project_json(project_workspace.workspace_path, {
        "characters": [{"name": "backend-character"}],
        "state_cards": {},
        "workflow_context": {"outline_state": {}},
    })

    packet = source_packet_service.compile_generation_source_packet(
        db_session,
        project_id=project_workspace.id,
        episode_no=2,
        project_workspace_path=project_workspace.workspace_path,
    )

    assert calls == [{
        "project_id": project_workspace.id,
        "episode_no": 2,
        "project_workspace_path": project_workspace.workspace_path,
        "previous_episode_briefs": None,
        "manual_edit_context": None,
    }]
    assert packet["previous_episode_continuity"]["content_version_id"] == "locked-by-package-2"
    assert packet["authority_trace"]["previous_episode_continuity"]["source"] == "episode_locked_content_version"


def test_generation_source_packet_keeps_current_episode_materials_with_previous_official_source(
    db_session,
    project_workspace,
    monkeypatch,
):
    from app.services import short_drama_generation_source_packet as source_packet_service

    def fake_previous_episode_packet(db, **kwargs):
        return {
            "source": "episode_locked_content_version",
            "content_version_id": "locked-episode-one-version",
            "episode_locked_event_id": "locked-event-one",
            "ready": True,
        }

    monkeypatch.setattr(
        source_packet_service,
        "compile_previous_episode_continuity_packet",
        fake_previous_episode_packet,
    )
    project_workspace.set_config({"confirmed_total_episodes": 12})
    db_session.add(project_workspace)
    db_session.commit()
    _write_project_json(project_workspace.workspace_path, {
        "workflow_context": {
            "outline_state": {
                "episodes": [
                    {"episode_no": 1, "summary": "SAFE_EPISODE_ONE_PLAN"},
                    {"episode_no": 2, "summary": "SAFE_EPISODE_TWO_PLAN"},
                ],
                "series_simulation_packet": {"source": "safe-series-simulation"},
            },
            "materials": [{"id": "safe-material"}],
        },
        "characters": [
            {"name": "SAFE_CHARACTER_A", "role": "protagonist"},
            {"name": "SAFE_CHARACTER_B", "role": "support"},
        ],
        "state_cards": {
            "relationship_timeline": [{"episode_no": 2, "change": "SAFE_RELATIONSHIP_ADVANCE"}],
        },
    })

    packet = source_packet_service.compile_generation_source_packet(
        db_session,
        project_id=project_workspace.id,
        episode_no=2,
        project_workspace_path=project_workspace.workspace_path,
        previous_episode_briefs=[{"source": "frontend-reference-only"}],
    )

    source_packet_service.validate_generation_source_packet_ready(packet)
    assert packet["previous_episode_continuity"]["source"] == "episode_locked_content_version"
    assert packet["previous_episode_continuity"]["content_version_id"] == "locked-episode-one-version"
    assert packet["outline_source"]["source"] == "workspace.workflow_context.outline_state"
    assert packet["outline_source"]["outline_state"]["episodes"][1]["summary"] == "SAFE_EPISODE_TWO_PLAN"
    assert packet["characters_count"] == 2
    assert packet["materials_count"] == 1
    assert packet["state_cards_keys"] == ["relationship_timeline"]
    assert packet["authority_trace"]["frontend_packet"]["used_as_authority_source"] is False


def test_generation_source_packet_rebases_release_workspace_path_before_checking_characters(
    db_session,
    tmp_path,
    monkeypatch,
):
    from app.services import short_drama_generation_source_packet as source_packet_service
    from app.services import workspace_service

    project_name = "SAFE_RELEASE_REBASED_PROJECT"
    current_root = tmp_path / "current-release" / "03-project-library" / "new-projects"
    legacy_root = tmp_path / "current-release" / "03-project-library" / "新建项目"
    current_workspace = current_root / "users" / "safe-user" / project_name
    stale_workspace = tmp_path / "old-release" / "03-project-library" / "new-projects" / "users" / "safe-user" / project_name
    current_workspace.mkdir(parents=True)
    _write_project_json(str(current_workspace), {
        "workflow_context": {
            "outline_state": {"episodes": [{"episode_no": 1, "summary": "SAFE_EPISODE_PLAN"}]},
            "materials": [],
        },
        "characters": [{"name": "SAFE_CHARACTER", "role": "protagonist"}],
        "state_cards": {},
    })
    monkeypatch.setattr(workspace_service, "WORKSPACE_ROOT", current_root)
    monkeypatch.setattr(workspace_service, "LEGACY_WORKSPACE_ROOT", legacy_root)
    monkeypatch.setattr(
        workspace_service,
        "project_workspace_roots",
        lambda *, include_legacy=True: (current_root, legacy_root),
    )
    project = ProjectV2(
        id="project-release-rebase",
        name=project_name,
        config=json.dumps({"confirmed_total_episodes": 3}, ensure_ascii=False),
        workspace_path=str(stale_workspace),
    )
    db_session.add(project)
    db_session.commit()

    packet = source_packet_service.compile_generation_source_packet(
        db_session,
        project_id=project.id,
        episode_no=1,
        project_workspace_path=project.workspace_path,
    )

    source_packet_service.validate_generation_source_packet_ready(packet)
    assert packet["characters_count"] == 1
    db_session.refresh(project)
    assert project.workspace_path == str(current_workspace.resolve(strict=False))


def test_generation_source_safe_summary_excludes_internal_text_and_raw_fields():
    from app.services import short_drama_generation_source_packet as source_packet

    packet = {
        "source_packet_version": "generation_source_packet.v1",
        "source": "backend_compiled_generation_source_packet",
        "episode_no": 2,
        "blocking_issues": [],
        "warnings": [],
        "previous_episode_continuity": {
            "source": "episode_locked_content_version",
            "previous_episode_no": 1,
            "content_version_id": "official-version-id",
            "content_hash": "abcdef1234567890",
            "episode_locked_event_id": "episode-locked-event-id",
            "ready": True,
            "body_excerpt": "PROTECTED_BODY_TEXT",
            "tail_excerpt": "PROTECTED_TAIL_TEXT",
            "raw_prompt": "PROTECTED_RAW_PROMPT",
            "raw_response": "PROTECTED_RAW_RESPONSE",
        },
    }

    summary = source_packet.generation_source_packet_safe_summary(packet)

    serialized = json.dumps(summary, ensure_ascii=False).lower()
    for forbidden in (
        "protected_body_text",
        "protected_tail_text",
        "raw_prompt",
        "raw_response",
        "raw_request",
        "raw_error",
        "provider",
        "secret",
        "credential",
        "session",
    ):
        assert forbidden not in serialized
    assert summary["previous_episode_continuity"]["source"] == "episode_locked_content_version"
    assert summary["previous_episode_continuity"]["content_version_id"] == "official-version-id"
    assert summary["previous_episode_continuity"]["content_hash_prefix"] == "abcdef123456"
    assert summary["previous_episode_continuity"]["episode_locked_event_id"] == "episode-locked-event-id"


def test_generation_source_job_safe_summary_uses_safe_summary_without_internal_text():
    from app.services import short_drama_generation_source_packet as source_packet

    packet = {
        "source_packet_version": "generation_source_packet.v1",
        "source": "backend_compiled_generation_source_packet",
        "episode_no": 2,
        "blocking_issues": [],
        "warnings": [],
        "previous_episode_continuity": {
            "source": "episode_locked_content_version",
            "previous_episode_no": 1,
            "content_version_id": "official-version-id",
            "content_hash": "abcdef1234567890",
            "episode_locked_event_id": "episode-locked-event-id",
            "ready": True,
            "body_excerpt": "PROTECTED_BODY_TEXT",
            "tail_excerpt": "PROTECTED_TAIL_TEXT",
        },
    }

    summary = source_packet.generation_source_packet_job_safe_summary(packet)

    serialized = json.dumps(summary, ensure_ascii=False).lower()
    assert summary["ready"] is True
    assert summary["previous_episode_continuity"]["content_version_id"] == "official-version-id"
    assert "protected_body_text" not in serialized
    assert "protected_tail_text" not in serialized


def test_validate_generation_source_packet_ready_blocks_missing_previous_official_source():
    from app.services.short_drama_generation_source_packet import (
        GenerationSourceBlocked,
        validate_generation_source_packet_ready,
    )

    packet = {
        "episode_no": 2,
        "blocking_issues": [],
        "previous_episode_continuity": {
            "source": "previous_episode_briefs",
            "previous_episode_no": 1,
            "ready": False,
        },
    }

    with pytest.raises(GenerationSourceBlocked) as exc:
        validate_generation_source_packet_ready(packet)

    assert exc.value.reason_code == "previous_official_source_missing"


def test_validate_generation_source_packet_ready_allows_backend_official_source():
    from app.services.short_drama_generation_source_packet import validate_generation_source_packet_ready

    packet = {
        "episode_no": 2,
        "blocking_issues": [],
        "previous_episode_continuity": {
            "source": "episode_locked_content_version",
            "previous_episode_no": 1,
            "content_version_id": "official-version-id",
            "episode_locked_event_id": "episode-locked-event-id",
            "ready": True,
        },
    }

    assert validate_generation_source_packet_ready(packet) is None
