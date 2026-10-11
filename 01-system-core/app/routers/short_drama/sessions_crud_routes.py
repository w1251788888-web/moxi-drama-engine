"""短剧写作会话 CRUD 路由（从 short_drama_writing.py 抽出）。

只包含 create / list / get / update 四个最基础的会话管理 endpoint，
依赖全部走 services 层，不再耦合主 router 内部的私有 helper。

抽出的好处：
- 主 router 文件不用再持有 session 维护代码（260+ 行）
- 这一组 endpoint 单独测试 / 重构 / 替换持久化层都不会"误伤"其他写作流程
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.auth.dependencies import verify_admin
from app.database import get_db
from app.models.task import Task
from app.schemas.short_drama_writing import (
    SessionCreateRequest,
    SessionDetail,
    SessionListItem,
    SessionUpdateRequest,
)
from app.services import task_service
from app.services.short_drama_session_metadata import (
    build_startup_checklist,
    deep_merge,
    dump_metadata,
    get_session_task,
    load_metadata,
    now_iso,
    save_metadata,
)
from app.services.short_drama_workflow_config import KIND

router = APIRouter()  # 由主 router 加 prefix


@router.post("/sessions", response_model=SessionDetail, summary="创建短剧写作会话")
async def create_session(req: SessionCreateRequest, _: bool = Depends(verify_admin), db: Session = Depends(get_db)):
    metadata: dict[str, Any] = {
        "kind": KIND,
        "project": req.project or {},
        "inputs": req.inputs or {},
        "materials": [],
        "issue_feedback": {},
        "startup_checklist": [],
        "steps": {},
        "exports": [],
        "created_at": now_iso(),
        "updated_at": now_iso(),
    }
    build_startup_checklist(metadata)

    task = task_service.create_task(db, name=req.name, description=req.description, type="once", metadata={})
    # 用本 router 的 dump 统一 JSON 格式
    task.metadata_json = dump_metadata(metadata)
    db.commit()
    db.refresh(task)

    return SessionDetail(
        id=task.id,
        name=task.name,
        description=task.description or "",
        status=task.status,
        created_at=task.created_at,
        updated_at=task.updated_at,
        metadata=metadata,
    )


@router.get("/sessions", response_model=list[SessionListItem], summary="列出短剧写作会话")
async def list_sessions(
    limit: int = 50,
    _: bool = Depends(verify_admin),
    db: Session = Depends(get_db),
):
    limit = max(1, min(limit, 200))

    # 兼容历史空格与新写入的无空格
    q = (
        db.query(Task)
        .filter(
            (Task.metadata_json.like(f"%\"kind\":\"{KIND}\"%"))
            | (Task.metadata_json.like(f"%\"kind\": \"{KIND}\"%"))
        )
        .order_by(Task.updated_at.desc())
        .limit(limit)
    )

    items: list[SessionListItem] = []
    for task in q.all():
        metadata = load_metadata(task.metadata_json)
        if metadata.get("kind") != KIND:
            continue
        items.append(
            SessionListItem(
                id=task.id,
                name=task.name,
                description=task.description or "",
                status=task.status,
                created_at=task.created_at,
                updated_at=task.updated_at,
                metadata=metadata,
            )
        )
    return items


@router.get("/sessions/{task_id}", response_model=SessionDetail, summary="获取短剧写作会话")
async def get_session(task_id: str, _: bool = Depends(verify_admin), db: Session = Depends(get_db)):
    task, metadata = get_session_task(db, task_id)
    return SessionDetail(
        id=task.id,
        name=task.name,
        description=task.description or "",
        status=task.status,
        created_at=task.created_at,
        updated_at=task.updated_at,
        metadata=metadata,
    )


@router.put("/sessions/{task_id}", response_model=SessionDetail, summary="更新短剧写作会话")
async def update_session(task_id: str, req: SessionUpdateRequest, _: bool = Depends(verify_admin), db: Session = Depends(get_db)):
    task, metadata = get_session_task(db, task_id)

    if req.metadata is None and req.patch is None:
        raise HTTPException(status_code=400, detail="metadata 或 patch 至少提供一个")

    if req.metadata is not None:
        if not isinstance(req.metadata, dict):
            raise HTTPException(status_code=400, detail="metadata 必须是对象")
        metadata = req.metadata
    if req.patch is not None:
        if not isinstance(req.patch, dict):
            raise HTTPException(status_code=400, detail="patch 必须是对象")
        metadata = deep_merge(metadata, req.patch)

    metadata["kind"] = KIND
    metadata["updated_at"] = now_iso()
    build_startup_checklist(metadata)

    save_metadata(db, task, metadata)

    return SessionDetail(
        id=task.id,
        name=task.name,
        description=task.description or "",
        status=task.status,
        created_at=task.created_at,
        updated_at=task.updated_at,
        metadata=metadata,
    )
