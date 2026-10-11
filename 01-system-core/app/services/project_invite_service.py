"""Project collaboration invitation helpers."""
from __future__ import annotations

import hashlib
import json
import secrets
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session

from app.models.collaboration import ProjectInvite, ProjectMember, ProjectPermission
from app.services.evidence_event_service import actor_fields, json_loads, record_evidence_event


DEFAULT_INVITE_PERMISSIONS = ["view", "comment", "suggest"]
OWNER_PERMISSIONS = ["view", "comment", "suggest", "edit", "approve", "manage", "export"]


def hash_invite_token(token: str) -> str:
    return hashlib.sha256(str(token or "").encode("utf-8")).hexdigest()


def generate_invite_token() -> str:
    return "MOXI-COLLAB-" + secrets.token_urlsafe(18)


def ensure_owner_member(db: Session, *, project_id: str, actor: Any, legal_identity: str = "rights_owner") -> ProjectMember | None:
    fields = actor_fields(actor)
    access_key_id = fields["actor_id"]
    if not access_key_id or access_key_id == "admin":
        return None
    member = db.query(ProjectMember).filter(
        ProjectMember.project_id == str(project_id),
        ProjectMember.access_key_id == access_key_id,
    ).first()
    if member is None:
        member = ProjectMember(
            project_id=str(project_id),
            access_key_id=access_key_id,
            role="showrunner",
            legal_identity=legal_identity,
            display_name=fields["actor_name"],
            status="active",
            accepted_at=datetime.now(),
        )
        db.add(member)
        db.flush()
    else:
        member.role = "showrunner"
        member.legal_identity = member.legal_identity or legal_identity
        member.display_name = member.display_name or fields["actor_name"]
        member.status = "active"
    existing = {
        row.permission
        for row in db.query(ProjectPermission).filter(
            ProjectPermission.project_id == str(project_id),
            ProjectPermission.member_id == member.id,
            ProjectPermission.scope_type == "project",
            ProjectPermission.scope_id == "",
        ).all()
    }
    for permission in OWNER_PERMISSIONS:
        if permission in existing:
            continue
        db.add(ProjectPermission(
            project_id=str(project_id),
            member_id=member.id,
            scope_type="project",
            scope_id="",
            permission=permission,
        ))
    return member


def create_project_invite(
    db: Session,
    *,
    project_id: str,
    actor: Any,
    target_contact: str = "",
    target_access_key_id: str = "",
    role: str = "co_writer",
    legal_identity: str = "commissioned_creator",
    scope_type: str = "project",
    scope_id: str = "",
    permissions: list[str] | None = None,
    allow_download: bool = False,
    days_valid: int = 7,
    note: str = "",
) -> tuple[ProjectInvite, str]:
    token = generate_invite_token()
    fields = actor_fields(actor)
    row = ProjectInvite(
        project_id=str(project_id),
        invite_token_hash=hash_invite_token(token),
        invite_token_prefix=token[:24],
        target_contact=str(target_contact or "").strip(),
        target_access_key_id=str(target_access_key_id or "").strip(),
        role=str(role or "co_writer"),
        legal_identity=str(legal_identity or "commissioned_creator"),
        scope_type=str(scope_type or "project"),
        scope_id=str(scope_id or ""),
        permissions_json=json.dumps(permissions or DEFAULT_INVITE_PERMISSIONS, ensure_ascii=False),
        allow_download=1 if allow_download else 0,
        invited_by=fields["actor_id"],
        invited_by_name=fields["actor_name"],
        note=str(note or ""),
        expires_at=datetime.now() + timedelta(days=max(1, min(int(days_valid or 7), 365))),
    )
    db.add(row)
    db.flush()
    record_evidence_event(
        db,
        project_id=project_id,
        actor=actor,
        event_type="collab_invite_created",
        target_type="project_invite",
        target_id=row.id,
        summary=f"邀请 {row.target_contact or row.target_access_key_id or row.role}",
        metadata={"role": row.role, "legal_identity": row.legal_identity, "permissions": permissions or DEFAULT_INVITE_PERMISSIONS},
    )
    db.commit()
    db.refresh(row)
    return row, token


def accept_project_invite(db: Session, *, invite: ProjectInvite, actor: Any) -> ProjectMember:
    if invite.status != "pending":
        raise ValueError("邀请已处理")
    if invite.expires_at and invite.expires_at < datetime.now():
        invite.status = "expired"
        invite.updated_at = datetime.now()
        db.commit()
        raise ValueError("邀请已过期")
    fields = actor_fields(actor)
    access_key_id = fields["actor_id"]
    if not access_key_id or access_key_id == "admin":
        raise ValueError("请使用前台用户身份接受协作邀请")
    target_access_key_id = str(invite.target_access_key_id or "").strip()
    if not target_access_key_id:
        raise ValueError("该邀请未绑定接收账号，不能直接接受")
    if target_access_key_id != access_key_id:
        raise ValueError("当前账号不是该邀请的接收人")

    member = db.query(ProjectMember).filter(
        ProjectMember.project_id == invite.project_id,
        ProjectMember.access_key_id == access_key_id,
    ).first()
    if member is None:
        member = ProjectMember(
            project_id=invite.project_id,
            access_key_id=access_key_id,
            role=invite.role,
            legal_identity=invite.legal_identity,
            display_name=fields["actor_name"],
            status="active",
            invited_by=invite.invited_by,
            accepted_at=datetime.now(),
        )
        db.add(member)
        db.flush()
    else:
        member.role = invite.role
        member.legal_identity = invite.legal_identity
        member.display_name = member.display_name or fields["actor_name"]
        member.status = "active"
        member.accepted_at = datetime.now()

    permissions = json_loads(invite.permissions_json, DEFAULT_INVITE_PERMISSIONS)
    db.query(ProjectPermission).filter(ProjectPermission.member_id == member.id).delete()
    for permission in permissions:
        db.add(ProjectPermission(
            project_id=invite.project_id,
            member_id=member.id,
            scope_type=invite.scope_type,
            scope_id=invite.scope_id,
            permission=str(permission),
        ))

    invite.status = "accepted"
    invite.accepted_by = access_key_id
    invite.accepted_at = datetime.now()
    invite.updated_at = datetime.now()
    record_evidence_event(
        db,
        project_id=invite.project_id,
        actor=actor,
        event_type="collab_invite_accepted",
        target_type="project_invite",
        target_id=invite.id,
        summary=f"{fields['actor_name']} 接受协作邀请",
        metadata={"member_id": member.id, "permissions": permissions},
    )
    db.commit()
    db.refresh(member)
    return member


def invite_to_dict(invite: ProjectInvite, *, include_token: str = "") -> dict[str, Any]:
    return {
        "id": invite.id,
        "project_id": invite.project_id,
        "invite_token": include_token,
        "target_contact": invite.target_contact,
        "target_access_key_id": invite.target_access_key_id,
        "role": invite.role,
        "legal_identity": invite.legal_identity,
        "scope_type": invite.scope_type,
        "scope_id": invite.scope_id,
        "permissions": json_loads(invite.permissions_json, []),
        "allow_download": bool(invite.allow_download),
        "status": invite.status,
        "invited_by": invite.invited_by,
        "invited_by_name": invite.invited_by_name,
        "note": invite.note,
        "expires_at": invite.expires_at.isoformat() if invite.expires_at else "",
        "accepted_by": invite.accepted_by,
        "created_at": invite.created_at.isoformat() if invite.created_at else "",
    }


def member_to_dict(member: ProjectMember, permissions: list[str] | None = None) -> dict[str, Any]:
    return {
        "id": member.id,
        "project_id": member.project_id,
        "access_key_id": member.access_key_id,
        "role": member.role,
        "legal_identity": member.legal_identity,
        "display_name": member.display_name,
        "status": member.status,
        "invited_by": member.invited_by,
        "permissions": permissions or [],
        "accepted_at": member.accepted_at.isoformat() if member.accepted_at else "",
        "created_at": member.created_at.isoformat() if member.created_at else "",
    }
