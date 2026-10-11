"""Project collaboration, invitations, REST suggestions, and locking APIs."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import String, and_, cast, func
from sqlalchemy.orm import Session

from app.auth.dependencies import ProjectAccessActor, verify_project_actor
from app.database import get_db
from app.models.collaboration import CollabEvent, ProjectInvite, ProjectMember, ProjectPermission
from app.models.evidence import ApprovalTask, EvidenceEvent
from app.models.project_v2 import ContentVersion, ContributionLedger, Episode, Scene
from app.routers.projects._helpers import _get_next_version_code, _get_project_for_actor_or_404, _scene_version_file_path, _update_contribution_ledger
from app.services.approval_service import create_approval_task
from app.services.c19_178_safe_label_gate import C19178GateBlocked, assert_c19_178_runtime_gate
from app.services.compliance_scan_service import mark_episode_compliance_stale
from app.services.evidence_event_service import actor_fields, json_loads, record_evidence_event
from app.services.project_access_policy import require_project_permission
from app.services.project_invite_service import accept_project_invite, create_project_invite, invite_to_dict, member_to_dict

router = APIRouter()


class InviteCreateRequest(BaseModel):
    target_contact: str = ""
    target_access_key_id: str = ""
    role: str = "co_writer"
    legal_identity: str = "commissioned_creator"
    scope_type: str = "project"
    scope_id: str = ""
    permissions: list[str] = Field(default_factory=lambda: ["view", "comment", "suggest"])
    allow_download: bool = False
    days_valid: int = 7
    note: str = ""


class CollabEventRequest(BaseModel):
    action: str
    scope_type: str = "project"
    scope_id: str = ""
    episode_number: int = 0
    scene_number: int = 0
    title: str = ""
    body: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class LockEpisodeRequest(BaseModel):
    note: str = ""


def _permissions_for_member(db: Session, member: ProjectMember) -> list[str]:
    rows = db.query(ProjectPermission).filter(ProjectPermission.member_id == member.id).all()
    return [f"{row.scope_type}:{row.scope_id}:{row.permission}" for row in rows]


def _require_invite_recipient(invite: ProjectInvite, actor: ProjectAccessActor) -> str:
    access_key_id = str(actor.access_key_id or "").strip()
    if not access_key_id:
        raise HTTPException(status_code=403, detail="请使用前台用户身份处理协作邀请")
    target_access_key_id = str(invite.target_access_key_id or "").strip()
    if target_access_key_id != access_key_id:
        raise HTTPException(status_code=403, detail="当前账号不是该邀请的接收人")
    return access_key_id


def _count_locked_episodes(db: Session, project_id: str) -> int:
    count = (
        db.query(func.count(func.distinct(ContentVersion.episode_number)))
        .join(
            EvidenceEvent,
            and_(
                EvidenceEvent.project_id == ContentVersion.project_id,
                EvidenceEvent.content_version_id == ContentVersion.id,
                EvidenceEvent.content_hash == ContentVersion.content_hash,
                EvidenceEvent.event_type == "episode_locked",
                EvidenceEvent.target_type == "episode",
                EvidenceEvent.target_id == cast(ContentVersion.episode_number, String),
            ),
        )
        .filter(
            ContentVersion.project_id == project_id,
            ContentVersion.scene_number == 0,
            ContentVersion.content_hash != "",
        )
        .scalar()
    )
    return int(count or 0)


@router.get("/collaboration/invites/pending", summary="查询待接受协作邀请")
async def list_pending_invites(
    actor: ProjectAccessActor = Depends(verify_project_actor),
    db: Session = Depends(get_db),
):
    access_key_id = str(actor.access_key_id or "")
    if not access_key_id:
        return {"items": []}
    rows = db.query(ProjectInvite).filter(
        ProjectInvite.status == "pending",
        ProjectInvite.target_access_key_id == access_key_id,
    ).order_by(ProjectInvite.created_at.desc()).limit(100).all()
    return {"items": [invite_to_dict(row) for row in rows]}


@router.post("/collaboration/invites/{invite_id}/accept", summary="接受协作邀请")
async def accept_invite(
    invite_id: str,
    actor: ProjectAccessActor = Depends(verify_project_actor),
    db: Session = Depends(get_db),
):
    invite = db.query(ProjectInvite).filter(ProjectInvite.id == invite_id).first()
    if invite is None:
        raise HTTPException(status_code=404, detail="邀请不存在")
    _require_invite_recipient(invite, actor)
    try:
        member = accept_project_invite(db, invite=invite, actor=actor)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return member_to_dict(member, _permissions_for_member(db, member))


@router.post("/collaboration/invites/{invite_id}/reject", summary="拒绝协作邀请")
async def reject_invite(
    invite_id: str,
    actor: ProjectAccessActor = Depends(verify_project_actor),
    db: Session = Depends(get_db),
):
    invite = db.query(ProjectInvite).filter(ProjectInvite.id == invite_id).first()
    if invite is None:
        raise HTTPException(status_code=404, detail="邀请不存在")
    _require_invite_recipient(invite, actor)
    invite.status = "rejected"
    invite.updated_at = datetime.now()
    record_evidence_event(
        db,
        project_id=invite.project_id,
        actor=actor,
        event_type="collab_invite_rejected",
        target_type="project_invite",
        target_id=invite.id,
        summary="拒绝协作邀请",
        commit=True,
    )
    return invite_to_dict(invite)


@router.get("/{project_id}/collaboration/summary", summary="协作概览")
async def collaboration_summary(
    project_id: str,
    actor: ProjectAccessActor = Depends(verify_project_actor),
    db: Session = Depends(get_db),
):
    project = _get_project_for_actor_or_404(db, project_id, actor)
    require_project_permission(db, project, actor, "view")
    members = db.query(ProjectMember).filter(ProjectMember.project_id == project_id, ProjectMember.status == "active").all()
    pending_invites = db.query(ProjectInvite).filter(ProjectInvite.project_id == project_id, ProjectInvite.status == "pending").count()
    pending_approvals = db.query(ApprovalTask).filter(ApprovalTask.project_id == project_id, ApprovalTask.status == "pending").count()
    return {
        "project_id": project_id,
        "creation_mode": getattr(project, "creation_mode", "solo"),
        "members": [member_to_dict(member, _permissions_for_member(db, member)) for member in members],
        "pending_invites": pending_invites,
        "pending_approvals": pending_approvals,
        "locked_episodes": _count_locked_episodes(db, project_id),
    }


@router.get("/{project_id}/collaboration/members", summary="查询项目成员")
async def list_members(
    project_id: str,
    actor: ProjectAccessActor = Depends(verify_project_actor),
    db: Session = Depends(get_db),
):
    project = _get_project_for_actor_or_404(db, project_id, actor)
    require_project_permission(db, project, actor, "view")
    rows = db.query(ProjectMember).filter(ProjectMember.project_id == project_id).order_by(ProjectMember.created_at.asc()).all()
    return {"items": [member_to_dict(row, _permissions_for_member(db, row)) for row in rows]}


@router.post("/{project_id}/collaboration/invites", summary="创建协作邀请")
async def create_invite(
    project_id: str,
    req: InviteCreateRequest,
    actor: ProjectAccessActor = Depends(verify_project_actor),
    db: Session = Depends(get_db),
):
    project = _get_project_for_actor_or_404(db, project_id, actor)
    require_project_permission(db, project, actor, "manage")
    if not str(req.target_access_key_id or "").strip():
        raise HTTPException(status_code=400, detail="协作邀请必须绑定被邀请人的密钥ID，避免公开邀请污染其他账号")
    invite, token = create_project_invite(
        db,
        project_id=project_id,
        actor=actor,
        target_contact=req.target_contact,
        target_access_key_id=req.target_access_key_id,
        role=req.role,
        legal_identity=req.legal_identity,
        scope_type=req.scope_type,
        scope_id=req.scope_id,
        permissions=req.permissions,
        allow_download=req.allow_download,
        days_valid=req.days_valid,
        note=req.note,
    )
    return invite_to_dict(invite, include_token=token)


@router.get("/{project_id}/collaboration/invites", summary="查询项目邀请")
async def list_project_invites(
    project_id: str,
    actor: ProjectAccessActor = Depends(verify_project_actor),
    db: Session = Depends(get_db),
):
    project = _get_project_for_actor_or_404(db, project_id, actor)
    require_project_permission(db, project, actor, "manage")
    rows = db.query(ProjectInvite).filter(ProjectInvite.project_id == project_id).order_by(ProjectInvite.created_at.desc()).all()
    return {"items": [invite_to_dict(row) for row in rows]}


@router.post("/{project_id}/collaboration/events", summary="创建协作评论/建议事件")
async def create_collab_event(
    project_id: str,
    req: CollabEventRequest,
    actor: ProjectAccessActor = Depends(verify_project_actor),
    db: Session = Depends(get_db),
):
    project = _get_project_for_actor_or_404(db, project_id, actor)
    needed = "comment" if req.action == "comment" else "suggest"
    require_project_permission(db, project, actor, needed, scope_type=req.scope_type, scope_id=req.scope_id)
    fields = actor_fields(actor)
    event = CollabEvent(
        project_id=project_id,
        actor_type=fields["actor_type"],
        actor_id=fields["actor_id"],
        actor_name=fields["actor_name"],
        action=req.action,
        scope_type=req.scope_type,
        scope_id=req.scope_id,
        episode_number=req.episode_number,
        scene_number=req.scene_number,
        metadata_json=json.dumps({"title": req.title, "body": req.body, **req.metadata}, ensure_ascii=False),
    )
    db.add(event)
    db.flush()
    if req.action in {"suggest", "lock_request"}:
        create_approval_task(
            db,
            project_id=project_id,
            actor=actor,
            task_type="script_suggestion" if req.action == "suggest" else "lock_request",
            title=req.title or ("修改建议" if req.action == "suggest" else "锁稿申请"),
            description=req.body,
            scope_type=req.scope_type,
            scope_id=req.scope_id,
            metadata={"collab_event_id": event.id, "episode_number": req.episode_number, "scene_number": req.scene_number},
            commit=False,
        )
    record_evidence_event(
        db,
        project_id=project_id,
        actor=actor,
        event_type=f"collab_{req.action}",
        target_type=req.scope_type,
        target_id=req.scope_id,
        summary=req.title or req.action,
    )
    db.commit()
    db.refresh(event)
    return {"id": event.id, "status": "created"}


@router.get("/{project_id}/collaboration/events", summary="查询协作事件")
async def list_collab_events(
    project_id: str,
    actor: ProjectAccessActor = Depends(verify_project_actor),
    db: Session = Depends(get_db),
):
    project = _get_project_for_actor_or_404(db, project_id, actor)
    require_project_permission(db, project, actor, "view")
    rows = db.query(CollabEvent).filter(CollabEvent.project_id == project_id).order_by(CollabEvent.created_at.desc()).limit(200).all()
    return {
        "items": [{
            "id": row.id,
            "action": row.action,
            "actor_name": row.actor_name,
            "scope_type": row.scope_type,
            "scope_id": row.scope_id,
            "episode_number": row.episode_number,
            "scene_number": row.scene_number,
            "metadata": json_loads(row.metadata_json, {}),
            "created_at": row.created_at.isoformat() if row.created_at else "",
        } for row in rows]
    }


@router.post("/{project_id}/episodes/{episode_number}/lock", summary="锁定单集最终稿")
async def lock_episode(
    project_id: str,
    episode_number: int,
    req: LockEpisodeRequest,
    actor: ProjectAccessActor = Depends(verify_project_actor),
    db: Session = Depends(get_db),
):
    project = _get_project_for_actor_or_404(db, project_id, actor)
    require_project_permission(db, project, actor, "approve", scope_type="episode", scope_id=str(episode_number))
    try:
        assert_c19_178_runtime_gate(db, project=project, target_path="official_lock")
    except C19178GateBlocked as exc:
        raise HTTPException(status_code=409, detail=exc.decision.reason_code) from exc
    episode = db.query(Episode).filter(Episode.project_id == project_id, Episode.episode_number == episode_number).first()
    if episode is None:
        raise HTTPException(status_code=404, detail="集不存在")
    scenes = db.query(Scene).filter(Scene.episode_id == episode.id).order_by(Scene.scene_number.asc()).all()
    content = "\n\n".join(str(scene.content or "").strip() for scene in scenes if str(scene.content or "").strip())
    content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
    version_code = _get_next_version_code(db, project_id, episode_number, 0)
    path = _scene_version_file_path(project, episode_number=episode_number, scene_number=0, version_code=version_code)
    path.write_text(content, encoding="utf-8")
    fields = actor_fields(actor)
    version = ContentVersion(
        project_id=project_id,
        episode_number=episode_number,
        scene_number=0,
        version_code=version_code,
        parent_version=episode.current_version,
        editor_type="human",
        editor_id=fields["actor_id"],
        editor_name=fields["actor_name"],
        content_path=str(path),
        content_hash=content_hash,
        diff_stats=json.dumps({"added_chars": len(content), "deleted_chars": 0, "added_lines": len(content.splitlines()), "deleted_lines": 0}, ensure_ascii=False),
        contribution_score=max(1, len(content)),
        change_note=req.note or "锁定单集最终稿",
    )
    db.add(version)
    db.flush()
    episode.current_version = version_code
    episode.status = "completed"
    episode.compliance_status = "pending"
    mark_episode_compliance_stale(db, project_id, episode_number)
    _update_contribution_ledger(
        db,
        project_id,
        fields["actor_id"],
        fields["actor_name"],
        "human",
        {"added_chars": len(content), "deleted_chars": 0},
        max(1, len(content)),
        version.id,
        episode_number,
        auto_commit=False,
    )
    ledgers = db.query(ContributionLedger).filter(ContributionLedger.project_id == project_id).all()
    db.add(CollabEvent(
        project_id=project_id,
        actor_type=fields["actor_type"],
        actor_id=fields["actor_id"],
        actor_name=fields["actor_name"],
        action="contribution_snapshot",
        scope_type="episode",
        scope_id=str(episode_number),
        episode_number=episode_number,
        content_version_id=version.id,
        metadata_json=json.dumps({
            "notice": "贡献统计是事实记录，不等于最终版权归属。",
            "content_hash": content_hash,
            "contributors": [
                {
                    "user_id": row.user_id,
                    "user_name": row.user_name,
                    "total_edits": row.total_edits,
                    "words_added": row.words_added,
                    "words_deleted": row.words_deleted,
                    "ai_generations_accepted": row.ai_generations_accepted,
                    "ai_generations_modified": row.ai_generations_modified,
                    "final_score": row.final_score,
                }
                for row in ledgers
            ],
        }, ensure_ascii=False),
    ))
    record_evidence_event(
        db,
        project_id=project_id,
        actor=actor,
        event_type="episode_locked",
        target_type="episode",
        target_id=str(episode_number),
        content_version_id=version.id,
        content_hash=content_hash,
        summary=req.note or "锁定单集最终稿",
    )
    db.commit()
    return {"version_id": version.id, "version_code": version.version_code, "content_hash": content_hash, "status": "locked"}
