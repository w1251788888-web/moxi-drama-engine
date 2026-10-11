"""Project compliance review APIs."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth.dependencies import ProjectAccessActor, verify_project_actor
from app.database import get_db
from app.models.compliance import ComplianceFinding, ComplianceScan
from app.models.project_v2 import Episode
from app.routers.projects._helpers import _get_project_for_actor_or_404
from app.services.c19_178_safe_label_gate import C19178GateBlocked, assert_c19_178_runtime_gate
from app.services.compliance_scan_service import decide_finding, finding_to_dict, propose_patch, scan_episode, scan_to_dict
from app.services.project_access_policy import require_project_permission

router = APIRouter()


class FindingDecisionRequest(BaseModel):
    decision: str
    note: str = ""


@router.get("/{project_id}/compliance/episodes", summary="查询每集合规状态")
async def list_compliance_episodes(
    project_id: str,
    actor: ProjectAccessActor = Depends(verify_project_actor),
    db: Session = Depends(get_db),
):
    project = _get_project_for_actor_or_404(db, project_id, actor)
    require_project_permission(db, project, actor, "view")
    episodes = db.query(Episode).filter(Episode.project_id == project_id).order_by(Episode.episode_number.asc()).all()
    items = []
    for ep in episodes:
        scan = db.query(ComplianceScan).filter(
            ComplianceScan.project_id == project_id,
            ComplianceScan.episode_number == ep.episode_number,
        ).order_by(ComplianceScan.created_at.desc()).first()
        count = db.query(ComplianceFinding).filter(
            ComplianceFinding.project_id == project_id,
            ComplianceFinding.episode_number == ep.episode_number,
            ComplianceFinding.status == "open",
        ).count()
        items.append({
            "episode_number": ep.episode_number,
            "title": ep.title,
            "status": ep.compliance_status or "pending",
            "latest_scan_id": scan.id if scan else "",
            "verdict": scan.verdict if scan else "pending",
            "open_findings": count,
        })
    return {"items": items}


@router.post("/{project_id}/compliance/episodes/{episode_number}/scan", summary="扫描单集合规")
async def scan_compliance_episode(
    project_id: str,
    episode_number: int,
    actor: ProjectAccessActor = Depends(verify_project_actor),
    db: Session = Depends(get_db),
):
    project = _get_project_for_actor_or_404(db, project_id, actor)
    require_project_permission(db, project, actor, "comment", scope_type="episode", scope_id=str(episode_number))
    try:
        assert_c19_178_runtime_gate(db, project=project, target_path="compliance_scan")
    except C19178GateBlocked as exc:
        raise HTTPException(status_code=409, detail=exc.decision.reason_code) from exc
    scan = scan_episode(db, project_id=project_id, episode_number=episode_number, actor=actor)
    findings = db.query(ComplianceFinding).filter(ComplianceFinding.scan_id == scan.id).all()
    return scan_to_dict(scan, findings)


@router.get("/{project_id}/compliance/findings", summary="查询合规问题")
async def list_compliance_findings(
    project_id: str,
    episode_number: int = 0,
    actor: ProjectAccessActor = Depends(verify_project_actor),
    db: Session = Depends(get_db),
):
    project = _get_project_for_actor_or_404(db, project_id, actor)
    require_project_permission(db, project, actor, "view")
    query = db.query(ComplianceFinding).filter(ComplianceFinding.project_id == project_id)
    if episode_number:
        query = query.filter(ComplianceFinding.episode_number == episode_number)
    rows = query.order_by(ComplianceFinding.created_at.desc()).limit(300).all()
    return {"items": [finding_to_dict(row) for row in rows]}


@router.post("/{project_id}/compliance/findings/{finding_id}/decision", summary="人工审核合规问题")
async def decide_compliance_finding(
    project_id: str,
    finding_id: str,
    req: FindingDecisionRequest,
    actor: ProjectAccessActor = Depends(verify_project_actor),
    db: Session = Depends(get_db),
):
    project = _get_project_for_actor_or_404(db, project_id, actor)
    require_project_permission(db, project, actor, "approve")
    finding = db.query(ComplianceFinding).filter(ComplianceFinding.project_id == project_id, ComplianceFinding.id == finding_id).first()
    if finding is None:
        raise HTTPException(status_code=404, detail="合规问题不存在")
    try:
        finding = decide_finding(db, finding=finding, actor=actor, decision=req.decision, note=req.note)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return finding_to_dict(finding)


@router.post("/{project_id}/compliance/findings/{finding_id}/patch", summary="生成 AI 修改建议占位")
async def create_compliance_patch(
    project_id: str,
    finding_id: str,
    actor: ProjectAccessActor = Depends(verify_project_actor),
    db: Session = Depends(get_db),
):
    project = _get_project_for_actor_or_404(db, project_id, actor)
    require_project_permission(db, project, actor, "suggest")
    finding = db.query(ComplianceFinding).filter(ComplianceFinding.project_id == project_id, ComplianceFinding.id == finding_id).first()
    if finding is None:
        raise HTTPException(status_code=404, detail="合规问题不存在")
    patch = propose_patch(db, finding=finding, actor=actor)
    return {"id": patch.id, "before_text": patch.before_text, "after_text": patch.after_text, "status": patch.status}
