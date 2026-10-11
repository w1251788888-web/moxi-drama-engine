"""Project collaboration permission checks."""
from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models.collaboration import ProjectMember, ProjectPermission
from app.models.project_v2 import ProjectV2

PERMISSION_ORDER = {
    "view": 1,
    "comment": 2,
    "suggest": 3,
    "edit": 4,
    "approve": 5,
    "export": 6,
    "manage": 7,
}


def _actor_access_key_id(actor: Any) -> str:
    return str(getattr(actor, "access_key_id", "") or "").strip()


def is_project_owner_or_admin(project: ProjectV2, actor: Any) -> bool:
    if bool(getattr(actor, "is_admin", False)) or str(getattr(actor, "actor_type", "")) == "admin":
        return True
    access_key_id = _actor_access_key_id(actor)
    return bool(access_key_id and str(project.created_by or "") == access_key_id)


def get_active_member(db: Session, project_id: str, actor: Any) -> ProjectMember | None:
    access_key_id = _actor_access_key_id(actor)
    if not access_key_id:
        return None
    return db.query(ProjectMember).filter(
        ProjectMember.project_id == str(project_id),
        ProjectMember.access_key_id == access_key_id,
        ProjectMember.status == "active",
    ).first()


def has_project_permission(
    db: Session,
    project: ProjectV2,
    actor: Any,
    permission: str,
    *,
    scope_type: str = "project",
    scope_id: str = "",
) -> bool:
    if is_project_owner_or_admin(project, actor):
        return True
    member = get_active_member(db, project.id, actor)
    if member is None:
        return False
    if member.role == "showrunner":
        return True
    requested_rank = PERMISSION_ORDER.get(permission, 0)
    if requested_rank <= 0:
        return False
    rows = db.query(ProjectPermission).filter(
        ProjectPermission.project_id == project.id,
        ProjectPermission.member_id == member.id,
    ).all()
    for row in rows:
        if PERMISSION_ORDER.get(row.permission, 0) < requested_rank:
            continue
        if row.scope_type == "project":
            return True
        if row.scope_type == scope_type and (not row.scope_id or row.scope_id == str(scope_id or "")):
            return True
        if row.scope_type == "episode" and scope_type == "scene" and str(scope_id or "").startswith(f"{row.scope_id}:"):
            return True
    return False


def require_project_permission(
    db: Session,
    project: ProjectV2,
    actor: Any,
    permission: str,
    *,
    scope_type: str = "project",
    scope_id: str = "",
) -> None:
    if not has_project_permission(db, project, actor, permission, scope_type=scope_type, scope_id=scope_id):
        raise HTTPException(status_code=403, detail="无权执行该项目操作")
