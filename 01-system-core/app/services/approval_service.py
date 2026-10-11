"""Project approval queue helpers."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.models.evidence import ApprovalTask
from app.services.evidence_event_service import actor_fields, json_dumps, json_loads, record_evidence_event


VALID_DECISIONS = {"approved", "rejected", "rework", "accepted", "dismissed"}


def create_approval_task(
    db: Session,
    *,
    project_id: str,
    actor: Any,
    task_type: str,
    title: str,
    description: str = "",
    scope_type: str = "project",
    scope_id: str = "",
    priority: str = "normal",
    metadata: dict[str, Any] | None = None,
    commit: bool = True,
) -> ApprovalTask:
    fields = actor_fields(actor)
    row = ApprovalTask(
        project_id=str(project_id),
        task_type=str(task_type),
        title=str(title),
        description=str(description or ""),
        scope_type=str(scope_type or "project"),
        scope_id=str(scope_id or ""),
        priority=str(priority or "normal"),
        requester_id=fields["actor_id"],
        requester_name=fields["actor_name"],
        metadata_json=json_dumps(metadata or {}, {}),
    )
    db.add(row)
    db.flush()
    record_evidence_event(
        db,
        project_id=project_id,
        actor=actor,
        event_type="approval_created",
        target_type="approval_task",
        target_id=row.id,
        summary=title,
        metadata={"task_type": task_type, **(metadata or {})},
    )
    if commit:
        db.commit()
        db.refresh(row)
    return row


def decide_approval_task(
    db: Session,
    *,
    task: ApprovalTask,
    actor: Any,
    decision: str,
    note: str = "",
    commit: bool = True,
) -> ApprovalTask:
    normalized = str(decision or "").strip()
    if normalized not in VALID_DECISIONS:
        raise ValueError("审批结论只能是 approved/rejected/rework/accepted/dismissed")
    fields = actor_fields(actor)
    task.status = "resolved" if normalized in {"approved", "rejected", "accepted", "dismissed"} else "rework"
    task.decision = normalized
    task.decision_note = str(note or "")
    task.reviewer_id = fields["actor_id"]
    task.reviewer_name = fields["actor_name"]
    task.decided_at = datetime.now()
    task.updated_at = datetime.now()
    record_evidence_event(
        db,
        project_id=task.project_id,
        actor=actor,
        event_type="approval_decided",
        target_type="approval_task",
        target_id=task.id,
        summary=f"{task.title}: {normalized}",
        metadata={"decision": normalized, "note": note},
    )
    if commit:
        db.commit()
        db.refresh(task)
    return task


def approval_task_to_dict(row: ApprovalTask) -> dict[str, Any]:
    return {
        "id": row.id,
        "project_id": row.project_id,
        "task_type": row.task_type,
        "title": row.title,
        "description": row.description,
        "status": row.status,
        "priority": row.priority,
        "scope_type": row.scope_type,
        "scope_id": row.scope_id,
        "requester_id": row.requester_id,
        "requester_name": row.requester_name,
        "reviewer_id": row.reviewer_id,
        "reviewer_name": row.reviewer_name,
        "decision": row.decision,
        "decision_note": row.decision_note,
        "metadata": json_loads(row.metadata_json, {}),
        "created_at": row.created_at.isoformat() if row.created_at else "",
        "updated_at": row.updated_at.isoformat() if row.updated_at else "",
        "decided_at": row.decided_at.isoformat() if row.decided_at else "",
    }
