from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.auth.dependencies import get_current_agent
from app.database import Base, get_db
from app.models import agent as agent_model  # noqa: F401
from app.models import episode_segment as episode_segment_model  # noqa: F401
from app.models import module as module_model  # noqa: F401
from app.models import step_version as step_version_model  # noqa: F401
from app.models import sub_task as sub_task_model  # noqa: F401
from app.models import task as task_model  # noqa: F401
from app.models.agent import Agent
from app.models.sub_task import SubTask
from app.models.task import Task
from app.routers.sub_tasks import router as sub_tasks_router
from app.services import sub_task_service


@pytest.fixture
def db_session_factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'sub_tasks.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(bind=engine)
    TestingSessionLocal = sessionmaker(
        autocommit=False,
        autoflush=False,
        bind=engine,
        expire_on_commit=False,
    )
    try:
        yield TestingSessionLocal
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


@pytest.fixture
def db(db_session_factory):
    session = db_session_factory()
    try:
        yield session
    finally:
        session.close()


def _seed_agent(db, agent_id: str, role: str = "executor") -> Agent:
    agent = Agent(
        id=agent_id,
        name=f"{agent_id} name",
        role=role,
        status="active",
        api_key=f"api-key-{agent_id}",
    )
    db.add(agent)
    return agent


def _seed_task(db, task_id: str = "task-1") -> Task:
    task = Task(id=task_id, name=f"{task_id} name", status="active")
    db.add(task)
    return task


def _seed_sub_task(
    db,
    sub_task_id: str,
    *,
    task_id: str = "task-1",
    name: str | None = None,
    status: str = "pending",
    priority: str = "medium",
    assigned_agent: str | None = None,
    created_at: datetime | None = None,
) -> SubTask:
    sub_task = SubTask(
        id=sub_task_id,
        task_id=task_id,
        name=name or f"{sub_task_id} name",
        status=status,
        priority=priority,
        assigned_agent=assigned_agent,
        created_at=created_at or datetime.now(),
    )
    db.add(sub_task)
    return sub_task


def test_update_sub_task_returns_refreshed_sub_task(db):
    _seed_task(db)
    _seed_sub_task(db, "sub-1", name="旧名称")
    db.commit()

    updated = sub_task_service.update_sub_task(
        db,
        "sub-1",
        name="新名称",
        priority="high",
    )

    assert isinstance(updated, SubTask)
    assert updated.id == "sub-1"
    assert updated.name == "新名称"
    assert updated.priority == "high"


def test_claim_sub_task_uses_conditional_update_to_prevent_duplicate_claim(
    db_session_factory,
):
    setup_db = db_session_factory()
    _seed_task(setup_db)
    _seed_agent(setup_db, "executor-1")
    _seed_agent(setup_db, "executor-2")
    _seed_sub_task(setup_db, "sub-1", status="pending")
    setup_db.commit()
    setup_db.close()

    first_db = db_session_factory()
    second_db = db_session_factory()
    try:
        first_claim = sub_task_service.claim_sub_task(
            first_db,
            "sub-1",
            agent_id="executor-1",
            session_id="session-1",
        )
        assert first_claim.status == "assigned"
        assert first_claim.assigned_agent == "executor-1"

        with pytest.raises(ValueError, match="状态转移不合法"):
            sub_task_service.claim_sub_task(
                second_db,
                "sub-1",
                agent_id="executor-2",
                session_id="session-2",
            )

        verify_db = db_session_factory()
        try:
            sub_task = verify_db.query(SubTask).filter(SubTask.id == "sub-1").one()
            assert sub_task.status == "assigned"
            assert sub_task.assigned_agent == "executor-1"
            assert sub_task.current_session_id == "session-1"
        finally:
            verify_db.close()
    finally:
        first_db.close()
        second_db.close()


def test_start_and_submit_require_assigned_agent(db):
    _seed_task(db)
    _seed_agent(db, "owner")
    _seed_agent(db, "intruder")
    _seed_sub_task(db, "sub-1", status="assigned", assigned_agent="owner")
    db.commit()

    with pytest.raises(ValueError, match="不是子任务"):
        sub_task_service.start_sub_task(db, "sub-1", agent_id="intruder")

    started = sub_task_service.start_sub_task(
        db,
        "sub-1",
        session_id="session-owner",
        agent_id="owner",
    )
    assert started.status == "in_progress"

    with pytest.raises(ValueError, match="不是子任务"):
        sub_task_service.submit_sub_task(db, "sub-1", agent_id="intruder")

    submitted = sub_task_service.submit_sub_task(db, "sub-1", agent_id="owner")
    assert submitted.status == "review"


def test_sub_task_routes_enforce_current_agent_for_start_and_submit(
    db_session_factory,
):
    setup_db = db_session_factory()
    _seed_task(setup_db)
    owner = _seed_agent(setup_db, "owner")
    intruder = _seed_agent(setup_db, "intruder")
    _seed_sub_task(setup_db, "sub-1", status="assigned", assigned_agent=owner.id)
    setup_db.commit()
    setup_db.close()

    current_agent = {"value": intruder}
    app = FastAPI()
    app.include_router(sub_tasks_router)

    def override_db():
        session = db_session_factory()
        try:
            yield session
        finally:
            session.close()

    async def override_current_agent():
        return current_agent["value"]

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_agent] = override_current_agent

    client = TestClient(app)
    blocked_start = client.post("/sub-tasks/sub-1/start", json={"session_id": "bad"})
    assert blocked_start.status_code == 400
    assert "不是子任务" in blocked_start.json()["detail"]

    current_agent["value"] = owner
    started = client.post("/sub-tasks/sub-1/start", json={"session_id": "owner"})
    assert started.status_code == 200, started.text
    assert started.json()["status"] == "in_progress"

    current_agent["value"] = intruder
    blocked_submit = client.post("/sub-tasks/sub-1/submit")
    assert blocked_submit.status_code == 400
    assert "不是子任务" in blocked_submit.json()["detail"]

    current_agent["value"] = owner
    submitted = client.post("/sub-tasks/sub-1/submit")
    assert submitted.status_code == 200, submitted.text
    assert submitted.json()["status"] == "review"


def test_poll_uses_sqlalchemy_case_priority_ordering(db_session_factory):
    setup_db = db_session_factory()
    _seed_task(setup_db)
    executor = _seed_agent(setup_db, "executor-1")
    base_time = datetime.now()
    _seed_sub_task(
        setup_db,
        "low-sub",
        priority="low",
        created_at=base_time - timedelta(minutes=5),
    )
    _seed_sub_task(
        setup_db,
        "high-sub",
        priority="high",
        created_at=base_time,
    )
    setup_db.commit()
    setup_db.close()

    app = FastAPI()
    app.include_router(sub_tasks_router)

    def override_db():
        session = db_session_factory()
        try:
            yield session
        finally:
            session.close()

    async def override_current_agent():
        return executor

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_agent] = override_current_agent

    client = TestClient(app)
    response = client.post("/sub-tasks/poll")

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["found"] is True
    assert payload["sub_task"]["id"] == "high-sub"
    assert payload["sub_task"]["assigned_agent"] == executor.id
