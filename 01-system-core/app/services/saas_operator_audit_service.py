"""人类操作者审计服务：记录管理员与前台用户关键业务动作。"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from app.models.admin_session import AdminSession
from app.models.saas_admin import OperatorAuditLog


@dataclass(frozen=True)
class OperatorActor:
    actor_type: str
    actor_id: str
    actor_label: str


@dataclass(frozen=True)
class OperatorAuditItem:
    audit_id: str
    actor_type: str
    actor_id: str
    actor_label: str
    action: str
    target_type: str
    target_id: str
    status: str
    summary: str
    metadata: dict[str, Any]
    created_at: str | None


def _metadata(payload: dict[str, Any] | None) -> str:
    return json.dumps(payload or {}, ensure_ascii=False, default=str, sort_keys=True)


def resolve_admin_actor(db: Session, token: str | None = None) -> OperatorActor:
    normalized = str(token or "").strip()
    if normalized:
        row = db.query(AdminSession).filter(AdminSession.token == normalized).first()
        if row is not None:
            return OperatorActor(actor_type="admin", actor_id=row.id, actor_label="admin")
        return OperatorActor(actor_type="admin", actor_id=f"token:{normalized[:8]}", actor_label="admin")
    return OperatorActor(actor_type="admin", actor_id="admin", actor_label="admin")


def user_actor(*, access_key_id: str, owner_name: str = "") -> OperatorActor:
    return OperatorActor(
        actor_type="user",
        actor_id=str(access_key_id or "").strip(),
        actor_label=str(owner_name or "").strip() or "front_user",
    )


def log_operator_action(
    db: Session,
    *,
    actor: OperatorActor,
    action: str,
    target_type: str = "",
    target_id: str = "",
    status: str = "success",
    summary: str = "",
    metadata: dict[str, Any] | None = None,
) -> OperatorAuditItem:
    row = OperatorAuditLog(
        actor_type=actor.actor_type,
        actor_id=actor.actor_id,
        actor_label=actor.actor_label,
        action=str(action or "").strip(),
        target_type=str(target_type or "").strip(),
        target_id=str(target_id or "").strip(),
        status=str(status or "success").strip(),
        summary=str(summary or "").strip()[:500],
        metadata_json=_metadata(metadata),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return operator_audit_payload(row)


def operator_audit_payload(row: OperatorAuditLog) -> OperatorAuditItem:
    try:
        metadata = json.loads(row.metadata_json or "{}")
    except Exception:
        metadata = {}
    return OperatorAuditItem(
        audit_id=row.id,
        actor_type=row.actor_type,
        actor_id=row.actor_id,
        actor_label=row.actor_label,
        action=row.action,
        target_type=row.target_type,
        target_id=row.target_id,
        status=row.status,
        summary=row.summary,
        metadata=metadata if isinstance(metadata, dict) else {},
        created_at=row.created_at.isoformat() if row.created_at else None,
    )


def list_operator_audit_logs(
    db: Session,
    *,
    actor_type: str = "",
    action: str = "",
    target_type: str = "",
    status: str = "",
    limit: int = 200,
) -> list[OperatorAuditItem]:
    query = db.query(OperatorAuditLog)
    if actor_type:
        query = query.filter(OperatorAuditLog.actor_type == actor_type)
    if action:
        query = query.filter(OperatorAuditLog.action == action)
    if target_type:
        query = query.filter(OperatorAuditLog.target_type == target_type)
    if status:
        query = query.filter(OperatorAuditLog.status == status)
    actual_limit = max(1, min(int(limit or 200), 500))
    rows = query.order_by(OperatorAuditLog.created_at.desc(), OperatorAuditLog.id.desc()).limit(actual_limit).all()
    return [operator_audit_payload(row) for row in rows]
