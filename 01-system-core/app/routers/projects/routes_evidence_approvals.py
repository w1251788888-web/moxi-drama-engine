"""Project evidence event and approval queue APIs."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth.dependencies import ProjectAccessActor, verify_project_actor
from app.database import get_db
from app.models.evidence import ApprovalTask, EvidenceEvent
from app.routers.projects._helpers import _get_project_for_actor_or_404
from app.services.approval_service import approval_task_to_dict, create_approval_task, decide_approval_task
from app.services.evidence_event_service import evidence_event_to_dict
from app.services.project_access_policy import require_project_permission

router = APIRouter()


class ApprovalCreateRequest(BaseModel):
    task_type: str = "general"
    title: str
    description: str = ""
    scope_type: str = "project"
    scope_id: str = ""
    priority: str = "normal"
    metadata: dict[str, Any] = Field(default_factory=dict)


class ApprovalDecisionRequest(BaseModel):
    decision: str
    note: str = ""


@router.get("/{project_id}/evidence/events", summary="查询项目证据事件")
async def list_evidence_events(
    project_id: str,
    limit: int = 100,
    actor: ProjectAccessActor = Depends(verify_project_actor),
    db: Session = Depends(get_db),
):
    project = _get_project_for_actor_or_404(db, project_id, actor)
    require_project_permission(db, project, actor, "view")
    rows = db.query(EvidenceEvent).filter(EvidenceEvent.project_id == project_id).order_by(EvidenceEvent.created_at.desc()).limit(min(max(limit, 1), 500)).all()
    return {"items": [evidence_event_to_dict(row) for row in rows]}


@router.get("/{project_id}/approvals", summary="查询项目审批队列")
async def list_approval_tasks(
    project_id: str,
    status: str = "",
    actor: ProjectAccessActor = Depends(verify_project_actor),
    db: Session = Depends(get_db),
):
    project = _get_project_for_actor_or_404(db, project_id, actor)
    require_project_permission(db, project, actor, "view")
    query = db.query(ApprovalTask).filter(ApprovalTask.project_id == project_id)
    if status:
        query = query.filter(ApprovalTask.status == status)
    rows = query.order_by(ApprovalTask.created_at.desc()).limit(200).all()
    return {"items": [approval_task_to_dict(row) for row in rows]}


@router.post("/{project_id}/approvals", summary="创建审批任务")
async def create_project_approval(
    project_id: str,
    req: ApprovalCreateRequest,
    actor: ProjectAccessActor = Depends(verify_project_actor),
    db: Session = Depends(get_db),
):
    project = _get_project_for_actor_or_404(db, project_id, actor)
    require_project_permission(db, project, actor, "suggest")
    task = create_approval_task(
        db,
        project_id=project_id,
        actor=actor,
        task_type=req.task_type,
        title=req.title,
        description=req.description,
        scope_type=req.scope_type,
        scope_id=req.scope_id,
        priority=req.priority,
        metadata=req.metadata,
    )
    return approval_task_to_dict(task)


@router.post("/{project_id}/approvals/{approval_id}/decision", summary="处理审批任务")
async def decide_project_approval(
    project_id: str,
    approval_id: str,
    req: ApprovalDecisionRequest,
    actor: ProjectAccessActor = Depends(verify_project_actor),
    db: Session = Depends(get_db),
):
    project = _get_project_for_actor_or_404(db, project_id, actor)
    require_project_permission(db, project, actor, "approve")
    task = db.query(ApprovalTask).filter(ApprovalTask.project_id == project_id, ApprovalTask.id == approval_id).first()
    if task is None:
        raise HTTPException(status_code=404, detail="审批任务不存在")
    try:
        task = decide_approval_task(db, task=task, actor=actor, decision=req.decision, note=req.note)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return approval_task_to_dict(task)
