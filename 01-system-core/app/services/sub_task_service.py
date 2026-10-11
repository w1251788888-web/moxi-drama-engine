"""
子任务业务逻辑 — 含状态机校验
"""
import json
import uuid
from datetime import datetime
from sqlalchemy.orm import Session

from app.models.sub_task import SubTask
from app.models.task import Task
from app.models.module import Module
from app.models.agent import Agent
from app.services.acceptance_artifact_service import write_sub_task_acceptance_artifact


# 状态机：合法的状态转移
VALID_TRANSITIONS = {
    "pending": ["assigned"],
    "assigned": ["in_progress", "pending"],
    "in_progress": ["review", "pending"],
    "review": ["done", "rework", "pending"],
    "rework": ["in_progress"],
    "blocked": ["pending"],
    "done": [],
    "cancelled": [],
}


def _dump_metadata(metadata: dict | None) -> str:
    if not metadata:
        return ""
    return json.dumps(metadata, ensure_ascii=False)


def _load_metadata(raw: str | None) -> dict:
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except Exception:
        return {}


def _ensure_assigned_agent(sub_task: SubTask, agent_id: str | None) -> None:
    if agent_id is None:
        return
    if sub_task.assigned_agent != agent_id:
        raise ValueError(
            f"当前 Agent {agent_id} 不是子任务 {sub_task.id} 的指派 Agent，"
            "无法执行该操作"
        )


def create_sub_task(
    db: Session,
    task_id: str,
    name: str,
    description: str = "",
    deliverable: str = "",
    acceptance: str = "",
    priority: str = "medium",
    module_id: str = None,
    assigned_agent: str = None,
    type: str = "once",
    metadata: dict | None = None,
) -> SubTask:
    """创建子任务"""
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise ValueError(f"任务 {task_id} 不存在")

    if module_id:
        module = db.query(Module).filter(Module.id == module_id).first()
        if not module:
            raise ValueError(f"模块 {module_id} 不存在")
        if module.task_id != task_id:
            raise ValueError(f"模块 {module_id} 不属于任务 {task_id}")

    if assigned_agent:
        agent = db.query(Agent).filter(Agent.id == assigned_agent).first()
        if not agent:
            raise ValueError(f"Agent {assigned_agent} 不存在")

    initial_status = "assigned" if assigned_agent else "pending"

    sub_task = SubTask(
        id=str(uuid.uuid4()),
        task_id=task_id,
        module_id=module_id,
        name=name,
        description=description,
        deliverable=deliverable,
        acceptance=acceptance,
        type=type,
        status=initial_status,
        priority=priority,
        assigned_agent=assigned_agent,
        metadata_json=_dump_metadata(metadata),
    )
    db.add(sub_task)
    db.commit()
    db.refresh(sub_task)
    return sub_task


def list_sub_tasks(
    db: Session,
    task_id: str = None,
    module_id: str = None,
    status: str = None,
    assigned_agent: str = None,
) -> list:
    """查询子任务列表，支持多条件过滤"""
    query = db.query(SubTask)
    if task_id:
        query = query.filter(SubTask.task_id == task_id)
    if module_id:
        query = query.filter(SubTask.module_id == module_id)
    if status:
        query = query.filter(SubTask.status == status)
    if assigned_agent:
        query = query.filter(SubTask.assigned_agent == assigned_agent)
    return query.order_by(SubTask.created_at.desc()).all()


def get_sub_task(db: Session, sub_task_id: str) -> SubTask:
    """获取单个子任务"""
    sub_task = db.query(SubTask).filter(SubTask.id == sub_task_id).first()
    return sub_task


def _change_status(db: Session, sub_task_id: str, new_status: str, auto_commit: bool = True, **kwargs) -> SubTask:
    """内部方法：状态转移（含校验）"""
    sub_task = db.query(SubTask).filter(SubTask.id == sub_task_id).first()
    if not sub_task:
        raise ValueError(f"子任务 {sub_task_id} 不存在")

    allowed = VALID_TRANSITIONS.get(sub_task.status, [])
    if new_status not in allowed:
        raise ValueError(
            f"状态转移不合法：{sub_task.status} → {new_status}，"
            f"允许: {', '.join(allowed) if allowed else '无（终态）'}"
        )

    sub_task.status = new_status

    metadata = kwargs.pop("metadata", None)
    if metadata is not None:
        sub_task.metadata_json = _dump_metadata(metadata)

    for key, value in kwargs.items():
        if hasattr(sub_task, key):
            setattr(sub_task, key, value)

    if new_status == "done":
        sub_task.completed_at = datetime.now()

    if auto_commit:
        db.commit()
        db.refresh(sub_task)
        try:
            write_sub_task_acceptance_artifact(db, sub_task_id)
        except Exception:
            pass
    else:
        db.flush()
    return sub_task


def claim_sub_task(db: Session, sub_task_id: str, agent_id: str, session_id: str = None) -> SubTask:
    updated = db.query(SubTask).filter(
        SubTask.id == sub_task_id,
        SubTask.status == "pending",
    ).update(
        {
            SubTask.status: "assigned",
            SubTask.assigned_agent: agent_id,
            SubTask.current_session_id: session_id,
        },
        synchronize_session=False,
    )

    if updated == 0:
        db.rollback()
        db.expire_all()
        sub_task = db.query(SubTask).filter(SubTask.id == sub_task_id).first()
        if not sub_task:
            raise ValueError(f"子任务 {sub_task_id} 不存在")
        allowed = VALID_TRANSITIONS.get(sub_task.status, [])
        raise ValueError(
            f"状态转移不合法：{sub_task.status} → assigned，"
            f"允许: {', '.join(allowed) if allowed else '无（终态）'}"
        )

    db.commit()
    sub_task = db.query(SubTask).filter(SubTask.id == sub_task_id).first()
    if not sub_task:
        raise ValueError(f"子任务 {sub_task_id} 不存在")
    db.refresh(sub_task)
    return sub_task


def start_sub_task(
    db: Session,
    sub_task_id: str,
    session_id: str = None,
    agent_id: str | None = None,
) -> SubTask:
    sub_task = db.query(SubTask).filter(SubTask.id == sub_task_id).first()
    if not sub_task:
        raise ValueError(f"子任务 {sub_task_id} 不存在")
    _ensure_assigned_agent(sub_task, agent_id)

    if sub_task.status not in ("assigned", "rework"):
        raise ValueError(
            f"状态转移不合法：{sub_task.status} → in_progress，"
            f"仅 assigned/rework 状态可以开始执行"
        )

    sub_task.status = "in_progress"
    if session_id:
        sub_task.current_session_id = session_id
    db.commit()
    db.refresh(sub_task)
    return sub_task


def submit_sub_task(db: Session, sub_task_id: str, agent_id: str | None = None) -> SubTask:
    sub_task = db.query(SubTask).filter(SubTask.id == sub_task_id).first()
    if not sub_task:
        raise ValueError(f"子任务 {sub_task_id} 不存在")
    _ensure_assigned_agent(sub_task, agent_id)
    return _change_status(db, sub_task_id, "review")


def submit_sub_task_with_deliverable(
    db: Session,
    sub_task_id: str,
    agent_id: str | None = None,
    *,
    deliverable: str | None = None,
    output_content: str | None = None,
    project_writeback: dict | None = None,
) -> SubTask:
    """Submit a sub task and persist executor output for reviewer-approved writeback."""
    sub_task = db.query(SubTask).filter(SubTask.id == sub_task_id).first()
    if not sub_task:
        raise ValueError(f"子任务 {sub_task_id} 不存在")
    _ensure_assigned_agent(sub_task, agent_id)

    metadata = _load_metadata(sub_task.metadata_json)
    metadata_changed = False

    if deliverable is not None:
        sub_task.deliverable = deliverable
    if output_content is not None:
        metadata["output_content"] = output_content
        metadata_changed = True

    if project_writeback is not None:
        existing = metadata.get("project_writeback") if isinstance(metadata.get("project_writeback"), dict) else {}
        merged = {**existing, **project_writeback}
        if output_content is not None and not merged.get("content"):
            merged["content"] = output_content
        metadata["project_writeback"] = merged
        metadata_changed = True
    elif output_content is not None and isinstance(metadata.get("project_writeback"), dict):
        metadata["project_writeback"] = {
            **metadata["project_writeback"],
            "content": metadata["project_writeback"].get("content") or output_content,
        }
        metadata_changed = True

    if metadata_changed:
        sub_task.metadata_json = _dump_metadata(metadata)

    return _change_status(db, sub_task_id, "review")


def complete_sub_task(db: Session, sub_task_id: str, auto_commit: bool = True) -> SubTask:
    """完成子任务并生成验收文件（任务完成时一次性生成）"""
    sub_task = _change_status(db, sub_task_id, "done", auto_commit=auto_commit)

    # 触发任务级验收文件生成（仅当任务的所有子任务都完成时）
    # 注意：这里只是触发，实际生成由验收服务处理，避免循环依赖
    try:
        from app.services.acceptance_artifact_service import write_task_acceptance_artifact
        write_task_acceptance_artifact(db, sub_task.task_id)
    except Exception as e:
        # 异常记录日志而非静默吞掉
        import logging
        logging.warning(f"验收文件生成失败 (task={sub_task.task_id}, sub_task={sub_task_id}): {e}")

    return sub_task


def rework_sub_task(db: Session, sub_task_id: str, rework_agent: str = None, auto_commit: bool = True) -> SubTask:
    sub_task = db.query(SubTask).filter(SubTask.id == sub_task_id).first()
    if not sub_task:
        raise ValueError(f"子任务 {sub_task_id} 不存在")

    kwargs = {}
    if rework_agent:
        agent = db.query(Agent).filter(Agent.id == rework_agent).first()
        if not agent:
            raise ValueError(f"Agent {rework_agent} 不存在")
        kwargs["assigned_agent"] = rework_agent
    kwargs["rework_count"] = sub_task.rework_count + 1

    return _change_status(db, sub_task_id, "rework", auto_commit=auto_commit, **kwargs)


def restart_sub_task(
    db: Session,
    sub_task_id: str,
    session_id: str = None,
    agent_id: str | None = None,
) -> SubTask:
    return start_sub_task(db, sub_task_id, session_id, agent_id)


def update_session(db: Session, sub_task_id: str, session_id: str) -> SubTask:
    sub_task = db.query(SubTask).filter(SubTask.id == sub_task_id).first()
    if not sub_task:
        raise ValueError(f"子任务 {sub_task_id} 不存在")
    if sub_task.status != "in_progress":
        raise ValueError(f"只有 in_progress 状态才能更新会话，当前: {sub_task.status}")

    sub_task.current_session_id = session_id
    db.commit()
    db.refresh(sub_task)
    return sub_task


def block_sub_task(db: Session, sub_task_id: str) -> SubTask:
    sub_task = db.query(SubTask).filter(SubTask.id == sub_task_id).first()
    if not sub_task:
        raise ValueError(f"子任务 {sub_task_id} 不存在")

    if sub_task.status not in ("in_progress", "assigned", "rework"):
        raise ValueError(f"只能对 in_progress/assigned/rework 状态的子任务标记 blocked")

    sub_task.status = "blocked"
    sub_task.current_session_id = None
    db.commit()
    db.refresh(sub_task)
    return sub_task


def reassign_sub_task(db: Session, sub_task_id: str, agent_id: str) -> SubTask:
    agent = db.query(Agent).filter(Agent.id == agent_id).first()
    if not agent:
        raise ValueError(f"Agent {agent_id} 不存在")

    sub_task = _change_status(db, sub_task_id, "pending")
    sub_task.assigned_agent = agent_id
    sub_task.status = "assigned"
    sub_task.current_session_id = None
    db.commit()
    db.refresh(sub_task)
    return sub_task


def update_sub_task(
    db: Session,
    sub_task_id: str,
    name: str = None,
    description: str = None,
    deliverable: str = None,
    acceptance: str = None,
    priority: str = None,
    metadata: dict | None = None,
) -> SubTask:
    sub_task = db.query(SubTask).filter(SubTask.id == sub_task_id).first()
    if not sub_task:
        raise ValueError(f"子任务 {sub_task_id} 不存在")

    if name is not None:
        sub_task.name = name
    if description is not None:
        sub_task.description = description
    if deliverable is not None:
        sub_task.deliverable = deliverable
    if acceptance is not None:
        sub_task.acceptance = acceptance
    if priority is not None:
        sub_task.priority = priority
    if metadata is not None:
        sub_task.metadata_json = _dump_metadata(metadata)

    db.commit()
    db.refresh(sub_task)
    return sub_task


def cancel_sub_task(db: Session, sub_task_id: str) -> SubTask:
    """取消子任务"""
    sub_task = db.query(SubTask).filter(SubTask.id == sub_task_id).first()
    if not sub_task:
        raise ValueError(f"子任务 {sub_task_id} 不存在")
    if sub_task.status in ("done", "cancelled"):
        raise ValueError(f"子任务状态为 {sub_task.status}，无法取消")

    sub_task.status = "cancelled"
    sub_task.current_session_id = None
    db.commit()
    db.refresh(sub_task)
    return sub_task
