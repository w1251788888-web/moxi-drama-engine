"""Shared evidence event helpers."""
from __future__ import annotations

import json
from typing import Any

from sqlalchemy.orm import Session

from app.models.evidence import EvidenceEvent


def json_dumps(value: Any, default: Any = None) -> str:
    return json.dumps(value if value is not None else default, ensure_ascii=False)


def json_loads(raw: str | None, default: Any) -> Any:
    if not raw:
        return default
    try:
        return json.loads(raw)
    except Exception:
        return default


def actor_fields(actor: Any) -> dict[str, str]:
    actor_type = str(getattr(actor, "actor_type", "") or "user")
    actor_id = str(getattr(actor, "access_key_id", "") or "")
    actor_name = str(getattr(actor, "owner_name", "") or actor_id or actor_type)
    if actor_type == "admin":
        actor_id = actor_id or "admin"
        actor_name = actor_name or "管理员"
    return {"actor_type": actor_type, "actor_id": actor_id, "actor_name": actor_name}


def record_evidence_event(
    db: Session,
    *,
    project_id: str,
    actor: Any = None,
    event_type: str,
    target_type: str = "",
    target_id: str = "",
    content_version_id: str = "",
    content_hash: str = "",
    summary: str = "",
    metadata: dict[str, Any] | None = None,
    commit: bool = False,
) -> EvidenceEvent:
    fields = actor_fields(actor) if actor is not None else {"actor_type": "system", "actor_id": "", "actor_name": "系统"}
    row = EvidenceEvent(
        project_id=str(project_id),
        event_type=str(event_type),
        target_type=str(target_type or ""),
        target_id=str(target_id or ""),
        content_version_id=str(content_version_id or ""),
        content_hash=str(content_hash or ""),
        summary=str(summary or ""),
        metadata_json=json_dumps(metadata or {}, {}),
        **fields,
    )
    db.add(row)
    if commit:
        db.commit()
        db.refresh(row)
    return row


def evidence_event_to_dict(row: EvidenceEvent) -> dict[str, Any]:
    return {
        "id": row.id,
        "project_id": row.project_id,
        "actor_type": row.actor_type,
        "actor_id": row.actor_id,
        "actor_name": row.actor_name,
        "event_type": row.event_type,
        "target_type": row.target_type,
        "target_id": row.target_id,
        "content_version_id": row.content_version_id,
        "content_hash": row.content_hash,
        "summary": row.summary,
        "metadata": json_loads(row.metadata_json, {}),
        "created_at": row.created_at.isoformat() if row.created_at else "",
    }
