"""Legal asset matrix, rights checks, and evidence package APIs."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth.dependencies import ProjectAccessActor, verify_project_actor
from app.database import get_db
from app.routers.projects._helpers import _get_project_for_actor_or_404
from app.services.c19_178_safe_label_gate import C19178GateBlocked, assert_c19_178_runtime_gate
from app.services.legal_asset_service import (
    build_ai_statement,
    build_material_matrix,
    check_export_gate,
    generate_evidence_package,
    package_to_dict,
    rights_check_to_dict,
    upsert_legal_material,
)
from app.services.project_access_policy import require_project_permission

router = APIRouter()


class LegalMaterialRequest(BaseModel):
    material_type: str
    title: str = ""
    content_text: str = ""
    provider: str = "user"
    status: str = "ready"


class EvidencePackageRequest(BaseModel):
    package_type: str = "legal"


@router.get("/{project_id}/legal-assets/matrix", summary="查询法律资料矩阵")
async def legal_material_matrix(
    project_id: str,
    actor: ProjectAccessActor = Depends(verify_project_actor),
    db: Session = Depends(get_db),
):
    project = _get_project_for_actor_or_404(db, project_id, actor)
    require_project_permission(db, project, actor, "view")
    return build_material_matrix(db, project)


@router.post("/{project_id}/legal-assets/materials", summary="补录法律资料")
async def save_legal_material(
    project_id: str,
    req: LegalMaterialRequest,
    actor: ProjectAccessActor = Depends(verify_project_actor),
    db: Session = Depends(get_db),
):
    project = _get_project_for_actor_or_404(db, project_id, actor)
    require_project_permission(db, project, actor, "comment")
    row = upsert_legal_material(
        db,
        project_id=project_id,
        material_type=req.material_type,
        title=req.title,
        content_text=req.content_text,
        provider=req.provider,
        status=req.status,
        actor=actor,
    )
    return {"id": row.id, "material_type": row.material_type, "status": row.status, "file_hash": row.file_hash}


@router.get("/{project_id}/legal-assets/rights-check", summary="执行确权完整度检查")
async def rights_check(
    project_id: str,
    actor: ProjectAccessActor = Depends(verify_project_actor),
    db: Session = Depends(get_db),
):
    project = _get_project_for_actor_or_404(db, project_id, actor)
    require_project_permission(db, project, actor, "view")
    return rights_check_to_dict(check_export_gate(db, project=project))


@router.get("/{project_id}/legal-assets/export-gate", summary="正式导出门禁")
async def export_gate(
    project_id: str,
    actor: ProjectAccessActor = Depends(verify_project_actor),
    db: Session = Depends(get_db),
):
    project = _get_project_for_actor_or_404(db, project_id, actor)
    require_project_permission(db, project, actor, "view")
    return rights_check_to_dict(check_export_gate(db, project=project))


@router.get("/{project_id}/legal-assets/ai-statement", summary="AI 创作过程说明")
async def ai_statement(
    project_id: str,
    actor: ProjectAccessActor = Depends(verify_project_actor),
    db: Session = Depends(get_db),
):
    project = _get_project_for_actor_or_404(db, project_id, actor)
    require_project_permission(db, project, actor, "view")
    return {"content": build_ai_statement(db, project)}


@router.post("/{project_id}/legal-assets/packages", summary="生成法律资产包")
async def create_evidence_package(
    project_id: str,
    req: EvidencePackageRequest,
    actor: ProjectAccessActor = Depends(verify_project_actor),
    db: Session = Depends(get_db),
):
    project = _get_project_for_actor_or_404(db, project_id, actor)
    if not actor.can_copy_export:
        raise HTTPException(status_code=403, detail="当前密钥未开启复制导出权限，请联系管理员开启")
    require_project_permission(db, project, actor, "export")
    try:
        assert_c19_178_runtime_gate(db, project=project, target_path="export_package")
    except C19178GateBlocked as exc:
        raise HTTPException(status_code=409, detail=exc.decision.reason_code) from exc
    gate = check_export_gate(db, project=project)
    if gate.status == "blocked":
        raise HTTPException(status_code=409, detail="正式导出被门禁拦截，请先补齐合规与法律资料")
    package = generate_evidence_package(db, project=project, package_type=req.package_type, actor=actor)
    return package_to_dict(package)
