from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def db_session(tmp_path):
    from app.database import Base
    from app.models import (  # noqa: F401
        auto_fix,
        episode_segment,
        outline_job,
        step_version,
        task,
    )

    engine = create_engine(
        f"sqlite:///{tmp_path / 'remaining_repair.db'}",
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


def test_auto_fix_handles_literal_braces_and_closes_old_pending_record(db_session):
    from app.models.auto_fix import AutoFixRecord, FailurePattern, FixStrategy
    from app.models.episode_segment import EpisodeSegment
    from app.services.auto_fix_service import AutoFixService

    segment = EpisodeSegment(
        id=str(uuid4()),
        session_id="session-1",
        episode_no=1,
        segment_type="hook",
        content="太短",
        actual_word_count=2,
        target_word_count=300,
    )
    pattern = FailurePattern(
        id=str(uuid4()),
        pattern_code="WORD_COUNT_INSUFFICIENT",
        pattern_name="字数不足",
        detection_logic=json.dumps({"type": "word_count_ratio", "threshold": 0.8}),
        fix_strategy_code="EXPAND_CONTENT",
        default_priority=9,
    )
    strategy = FixStrategy(
        id=str(uuid4()),
        strategy_code="EXPAND_CONTENT",
        strategy_name="扩写",
        param_template={"focus": "description"},
        user_prompt_template='保留这个 JSON 示例：{}，正文：{content}',
    )
    old_record = AutoFixRecord(
        id=str(uuid4()),
        segment_id=segment.id,
        failure_type="WORD_COUNT_INSUFFICIENT",
        status="pending",
    )
    db_session.add_all([segment, pattern, strategy, old_record])
    db_session.commit()

    result = AutoFixService(db_session).auto_fix(
        segment,
        validation_result={"score": 0.2},
        max_iterations=2,
    )

    assert result.success is True

    records = db_session.query(AutoFixRecord).filter(
        AutoFixRecord.segment_id == segment.id
    ).order_by(AutoFixRecord.created_at.asc()).all()
    assert [record.status for record in records] == ["aborted", "pending"]
    assert records[-1].before_content == "太短"
    assert records[-1].fix_params["max_iterations"] == 2

    prompt = AutoFixService(db_session)._build_fix_prompt(segment, strategy, {})
    assert prompt == '保留这个 JSON 示例：{}，正文：{content}'


def test_outline_job_cleanup_keeps_active_jobs_visible(db_session):
    from app.models.outline_job import OutlineEpisodeJob
    from app.routers.projects.routes_generation import (
        _OUTLINE_EPISODE_JOB_TTL_SECONDS,
        _cleanup_outline_episode_jobs,
    )

    now = datetime(2026, 5, 22, 12, 0, 0)
    old = now - timedelta(seconds=_OUTLINE_EPISODE_JOB_TTL_SECONDS + 60)
    fresh = now - timedelta(seconds=60)
    jobs = [
        OutlineEpisodeJob(id="old-done", status="done", updated_at=old),
        OutlineEpisodeJob(id="old-error", status="error", updated_at=old),
        OutlineEpisodeJob(id="old-pending", status="pending", updated_at=old),
        OutlineEpisodeJob(id="old-running", status="running", updated_at=old),
        OutlineEpisodeJob(id="fresh-done", status="done", updated_at=fresh),
    ]
    db_session.add_all(jobs)
    db_session.commit()

    _cleanup_outline_episode_jobs(db_session, now=now)
    db_session.commit()

    ids = {
        row.id: row
        for row in db_session.query(OutlineEpisodeJob).order_by(OutlineEpisodeJob.id).all()
    }
    assert "old-done" not in ids
    assert "old-error" not in ids
    assert ids["fresh-done"].status == "done"
    assert ids["old-pending"].status == "error"
    assert ids["old-running"].status == "error"
    assert "重新生成" in ids["old-running"].error


def test_session_metadata_save_rejects_stale_writer(db_session):
    from fastapi import HTTPException

    from app.models.task import Task
    from app.services.short_drama_session_metadata import dump_metadata, load_metadata, save_metadata
    from app.services.short_drama_workflow_config import KIND

    task = Task(
        id="session-lock",
        name="会话",
        status="active",
        metadata_json=dump_metadata({"kind": KIND, "steps": {}}),
        metadata_version=0,
    )
    db_session.add(task)
    db_session.commit()

    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=db_session.get_bind())
    db1 = SessionLocal()
    db2 = SessionLocal()
    try:
        writer1 = db1.query(Task).filter(Task.id == "session-lock").first()
        writer2 = db2.query(Task).filter(Task.id == "session-lock").first()

        metadata1 = load_metadata(writer1.metadata_json)
        metadata2 = load_metadata(writer2.metadata_json)
        metadata1["steps"] = {"concept": {"content": "先写入"}}
        metadata2["steps"] = {"characters": {"content": "后写入"}}

        save_metadata(db1, writer1, metadata1)
        with pytest.raises(HTTPException) as exc:
            save_metadata(db2, writer2, metadata2)

        assert exc.value.status_code == 409
    finally:
        db1.close()
        db2.close()

    db_session.expire_all()
    saved = db_session.query(Task).filter(Task.id == "session-lock").first()
    assert saved.metadata_version == 1
    saved_metadata = load_metadata(saved.metadata_json)
    assert saved_metadata["steps"] == {"concept": {"content": "先写入"}}


def test_sse_stream_has_cancel_and_partial_persistence_guards():
    step_routes = (ROOT / "app" / "routers" / "short_drama" / "step_routes.py").read_text(encoding="utf-8")
    sse_service = (ROOT / "app" / "services" / "short_drama_sse.py").read_text(encoding="utf-8")

    assert "cancel_event: threading.Event | None = None" in sse_service
    assert "except asyncio.CancelledError" in sse_service
    assert "cancel_event.set()" in sse_service
    assert "_save_partial_stream_text" in step_routes
    assert '"stream_status": "partial"' in step_routes
    assert '"partial": True' in step_routes
    assert '"stream_status": "done"' in step_routes


def test_script_draft_updates_continuity_memory_without_quality_check():
    from app.routers.short_drama.step_routes import _apply_script_draft_runtime_memory

    metadata: dict = {}
    context_output = json.dumps(
        {
            "cliffhanger": "沈玉瑶握住玉佩，下一集必须从玉佩发光承接。",
            "state_card_delta": {"relationship": "周砚开始相信沈玉瑶"},
            "used_beats": [{"scene": "古玩店", "action": "玉佩发光", "target": "确认身份"}],
        },
        ensure_ascii=False,
    )

    _apply_script_draft_runtime_memory(
        metadata,
        episode_no=1,
        payload={},
        context_output=context_output,
        full_output="【场1-1 夜 内 古玩店】\n沈玉瑶握住玉佩，玉佩忽然发光。",
        updated_at="2026-05-22T12:00:00",
    )

    ep_node = metadata["episodes"]["1"]
    assert ep_node["state_card_delta"]["relationship"] == "周砚开始相信沈玉瑶"
    assert ep_node["used_beats"][0]["action"] == "玉佩发光"
    cliff = ep_node["cliffhanger_concrete"]
    assert cliff["freeze_prop"] == "沈玉瑶握住玉佩，下一集必须从玉佩发光承接。"
    assert cliff["next_episode_must_pick_up"] == cliff["freeze_prop"]
    assert cliff["freeze_action"]


def test_project_generation_jobs_expose_quality_gate_warning():
    route = (ROOT / "app" / "routers" / "projects" / "routes_generation.py").read_text(encoding="utf-8")
    schema = (ROOT / "app" / "routers" / "projects" / "_schemas.py").read_text(encoding="utf-8")
    model = (ROOT / "app" / "models" / "project_v2.py").read_text(encoding="utf-8")
    web_type = (ROOT / "webui" / "src" / "api" / "modules" / "projects.ts").read_text(encoding="utf-8")

    assert "run_acceptance_checks" in route
    assert "build_acceptance_gate_warning" in route
    assert "job.gate_warning = build_acceptance_gate_warning" in route
    assert "gate_warning=job.gate_warning or" in route
    assert "gate_warning: str = \"\"" in schema
    assert "gate_warning = Column(Text, default=\"\")" in model
    assert "gate_warning?: string" in web_type


def test_scene_creation_has_database_unique_guard_and_retry():
    model = (ROOT / "app" / "models" / "project_v2.py").read_text(encoding="utf-8")
    database = (ROOT / "app" / "database.py").read_text(encoding="utf-8")
    route = (ROOT / "app" / "routers" / "projects" / "routes_episodes_scenes.py").read_text(encoding="utf-8")

    assert 'UniqueConstraint("episode_id", "scene_number", name="uq_scene_episode_number")' in model
    assert "ensure_scene_episode_number_uniqueness(conn)" in database
    assert "CREATE UNIQUE INDEX IF NOT EXISTS uq_scene_episode_number" in database
    assert "except IntegrityError" in route
    assert "场景编号冲突，请重试" in route


def test_overflow_content_is_returned_instead_of_silently_discarded():
    schema = (ROOT / "app" / "schemas" / "short_drama_writing.py").read_text(encoding="utf-8")
    scene_generation = (ROOT / "app" / "services" / "short_drama_scene_generation.py").read_text(encoding="utf-8")
    scene_routes = (ROOT / "app" / "routers" / "short_drama" / "scene_routes.py").read_text(encoding="utf-8")
    web_settings = (ROOT / "webui" / "src" / "api" / "modules" / "settings.ts").read_text(encoding="utf-8")

    assert "overflow_content: str = \"\"" in schema
    assert 'fixed_eval["overflow_content"] = fixed.overflow_content' in scene_generation
    assert "有部分内容已作为下一集顺延建议返回" in scene_generation
    assert "overflow_content=str(approved.get(\"overflow_content\") or \"\")" in scene_routes
    assert "overflow_content?: string" in web_settings
