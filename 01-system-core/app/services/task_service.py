"""
任务业务逻辑
"""
import json
import uuid
from sqlalchemy.orm import Session

from app.models.task import Task
from app.models.module import Module
from app.services.acceptance_artifact_service import write_task_acceptance_artifact


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


def create_task(db: Session, name: str, description: str = "", type: str = "once", metadata: dict | None = None) -> Task:
    """创建任务"""
    valid_types = {"once", "recurring"}
    if type not in valid_types:
        raise ValueError(f"无效类型 '{type}'，可选: {', '.join(valid_types)}")

    task = Task(
        id=str(uuid.uuid4()),
        name=name,
        description=description,
        type=type,
        metadata_json=_dump_metadata(metadata),
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    return task


def list_tasks(db: Session, status: str = None) -> list:
    """查询任务列表"""
    query = db.query(Task)
    if status:
        query = query.filter(Task.status == status)
    return query.order_by(Task.created_at.desc()).all()


def get_task(db: Session, task_id: str) -> Task:
    """获取单个任务"""
    task = db.query(Task).filter(Task.id == task_id).first()
    return task


def update_task_status(db: Session, task_id: str, status: str) -> Task:
    """更新任务状态"""
    valid_statuses = {"planning", "active", "in_progress", "completed", "archived", "cancelled"}
    if status not in valid_statuses:
        raise ValueError(f"无效状态 '{status}'，可选: {', '.join(valid_statuses)}")

    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise ValueError(f"任务 {task_id} 不存在")

    task.status = status
    db.commit()
    db.refresh(task)

    if status == "completed":
        try:
            write_task_acceptance_artifact(db, task_id)
        except Exception:
            pass
    return task


def update_task(db: Session, task_id: str, name: str = None, description: str = None, metadata: dict | None = None) -> Task:
    """编辑任务（仅 planning/active 状态可编辑）"""
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise ValueError(f"任务 {task_id} 不存在")
    if task.status not in ("planning", "active"):
        raise ValueError(f"任务状态为 {task.status}，只有 planning/active 状态可编辑")

    if name is not None:
        task.name = name
    if description is not None:
        task.description = description
    if metadata is not None:
        task.metadata_json = _dump_metadata(metadata)
    db.commit()
    db.refresh(task)
    return task


def cancel_task(db: Session, task_id: str) -> Task:
    """取消任务"""
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise ValueError(f"任务 {task_id} 不存在")
    if task.status in ("completed", "archived", "cancelled"):
        raise ValueError(f"任务状态为 {task.status}，无法取消")

    task.status = "cancelled"
    db.commit()
    db.refresh(task)
    return task


def create_module(db: Session, task_id: str, name: str, description: str = "") -> Module:
    """创建模块"""
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise ValueError(f"任务 {task_id} 不存在")

    module = Module(
        id=str(uuid.uuid4()),
        task_id=task_id,
        name=name,
        description=description,
    )
    db.add(module)
    db.commit()
    db.refresh(module)
    return module


def list_modules(db: Session, task_id: str) -> list:
    """查询任务下的模块"""
    return db.query(Module).filter(Module.task_id == task_id).all()
