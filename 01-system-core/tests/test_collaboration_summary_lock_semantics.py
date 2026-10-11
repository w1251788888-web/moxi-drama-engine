from __future__ import annotations

import hashlib
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
        evidence,
        episode_segment,
        issue_record,
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
        f"sqlite:///{tmp_path / 'collaboration-summary.db'}",
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


def _make_project(db, *, name: str, workspace: Path):
    from app.models.project_v2 import ProjectV2

    project = ProjectV2(
        id=str(uuid4()),
        name=name,
        description="锁稿摘要测试项目",
        project_type="真人短剧-男频",
        audience_axis="男频",
        genre_main="都市",
        genre_sub="逆袭",
        total_episodes=5,
        workspace_path=str(workspace),
    )
    project.set_config({"total_episodes": 5, "episode_seconds": 90})
    db.add(project)
    db.commit()
    db.refresh(project)
    return project


def _admin_actor():
    from app.auth.dependencies import ProjectAccessActor

    return ProjectAccessActor(actor_type="admin")


@pytest.mark.asyncio
async def test_collaboration_summary_does_not_count_completed_episode_without_official_lock(
    db_session,
    tmp_path,
):
    from app.models.project_v2 import Episode
    from app.routers.projects.routes_collaboration import collaboration_summary

    workspace = tmp_path / "协作摘要未锁稿项目"
    workspace.mkdir(parents=True)
    (workspace / "project.json").write_text(
        json.dumps({"name": "协作摘要未锁稿项目"}, ensure_ascii=False),
        encoding="utf-8",
    )
    project = _make_project(db_session, name="协作摘要未锁稿项目", workspace=workspace)
    episode = Episode(
        id=str(uuid4()),
        project_id=project.id,
        episode_number=1,
        title="第一集",
        total_scenes=1,
        completed_scenes=1,
        status="completed",
    )
    db_session.add(episode)
    db_session.commit()

    summary = await collaboration_summary(project.id, actor=_admin_actor(), db=db_session)

    assert summary["locked_episodes"] == 0


@pytest.mark.asyncio
async def test_collaboration_summary_counts_only_real_official_lock_evidence(
    db_session,
    tmp_path,
):
    from app.models.evidence import EvidenceEvent
    from app.models.project_v2 import ContentVersion, Episode
    from app.routers.projects.routes_collaboration import collaboration_summary

    workspace = tmp_path / "协作摘要已锁稿项目"
    workspace.mkdir(parents=True)
    (workspace / "project.json").write_text(
        json.dumps({"name": "协作摘要已锁稿项目"}, ensure_ascii=False),
        encoding="utf-8",
    )
    locked_file = workspace / "episodes" / "ep01" / "scenes" / "sc00_v001.md"
    locked_file.parent.mkdir(parents=True, exist_ok=True)
    locked_content = "第1集正式锁稿安全占位正文"
    locked_file.write_text(locked_content, encoding="utf-8")
    locked_hash = hashlib.sha256(locked_content.encode("utf-8")).hexdigest()

    project = _make_project(db_session, name="协作摘要已锁稿项目", workspace=workspace)
    episode = Episode(
        id=str(uuid4()),
        project_id=project.id,
        episode_number=1,
        title="第一集",
        total_scenes=1,
        completed_scenes=1,
        status="completed",
    )
    version = ContentVersion(
        id=str(uuid4()),
        project_id=project.id,
        episode_number=1,
        scene_number=0,
        version_code="v001",
        content_path=str(locked_file),
        content_hash=locked_hash,
    )
    event = EvidenceEvent(
        id=str(uuid4()),
        project_id=project.id,
        event_type="episode_locked",
        target_type="episode",
        target_id="1",
        content_version_id=version.id,
        content_hash=locked_hash,
    )
    db_session.add_all([episode, version, event])
    db_session.commit()

    summary = await collaboration_summary(project.id, actor=_admin_actor(), db=db_session)

    assert summary["locked_episodes"] == 1
