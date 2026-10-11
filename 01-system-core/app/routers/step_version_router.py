"""步骤版本管理API路由

实现版本树、依赖管理、动态规则、评审循环的REST API
遵循gstack的工作流理念
"""
from __future__ import annotations

from typing import Any, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth.dependencies import verify_admin
from app.database import get_db
from app.services.step_version_service import StepVersionService

router = APIRouter(prefix="/admin/short-drama", tags=["Short Drama Version Management"])


# ─────────────────────────────────────────────────────────
# 请求/响应模型
# ─────────────────────────────────────────────────────────

class CreateVersionRequest(BaseModel):
    base_version_id: Optional[str] = None
    change_type: Literal["ai_generated", "manual_edit", "merged", "forked"] = "ai_generated"
    change_log: str = ""
    context_output: str = ""
    full_output: str = ""
    prompt_file: str = ""
    input_summary: str = ""


class SwitchVersionRequest(BaseModel):
    version_id: str


class AddRuleRequest(BaseModel):
    content: str
    scope: Literal["global", "project", "step", "once"] = "step"
    target_step: Optional[str] = None
    target_episode: Optional[int] = None
    apply_timing: Literal["immediate", "next_generation"] = "next_generation"


class SyncDownstreamRequest(BaseModel):
    from_step: str
    strategy: Literal["smart", "full", "manual"] = "smart"


class CreateReviewRequest(BaseModel):
    version_id: str
    verdict: Literal["pass", "needs_fix", "reject"]
    comments: str = ""
    issues: list[dict] = Field(default_factory=list)
    rewrite_hint: str = ""
    score: Optional[int] = None


class PartialRegenerateRequest(BaseModel):
    base_version_id: str
    target_type: Literal["character", "episode", "scene", "line"]
    target_name: str
    target_field: Optional[str] = None
    prompt: str


# ─────────────────────────────────────────────────────────
# 版本管理API
# ─────────────────────────────────────────────────────────

@router.get("/sessions/{session_id}/steps/{step_id}/versions")
async def get_version_tree(
    session_id: str,
    step_id: str,
    db: Session = Depends(get_db),
    _=Depends(verify_admin),
):
    """获取步骤的版本树"""
    service = StepVersionService(db)
    versions = service.get_version_tree(session_id, step_id)
    return {"versions": versions}


@router.post("/sessions/{session_id}/steps/{step_id}/versions")
async def create_version(
    session_id: str,
    step_id: str,
    req: CreateVersionRequest,
    db: Session = Depends(get_db),
    _=Depends(verify_admin),
):
    """创建新版本"""
    service = StepVersionService(db)
    version = service.create_version(
        session_id=session_id,
        step_id=step_id,
        context_output=req.context_output,
        full_output=req.full_output,
        change_type=req.change_type,
        change_log=req.change_log,
        prompt_file=req.prompt_file,
        input_summary=req.input_summary,
        base_version_id=req.base_version_id,
        created_by="user",
    )
    db.commit()
    return {"version": version.to_dict()}


@router.put("/sessions/{session_id}/steps/{step_id}/current-version")
async def switch_version(
    session_id: str,
    step_id: str,
    req: SwitchVersionRequest,
    db: Session = Depends(get_db),
    _=Depends(verify_admin),
):
    """切换当前版本"""
    service = StepVersionService(db)
    try:
        version = service.switch_version(session_id, step_id, req.version_id)
        db.commit()
        return {"version": version.to_dict()}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/sessions/{session_id}/steps/{step_id}/diff")
async def diff_versions(
    session_id: str,
    step_id: str,
    left: str,
    right: str,
    db: Session = Depends(get_db),
    _=Depends(verify_admin),
):
    """对比两个版本"""
    service = StepVersionService(db)
    try:
        result = service.diff_versions(left, right)
        return result
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


# ─────────────────────────────────────────────────────────
# 依赖管理API
# ─────────────────────────────────────────────────────────

@router.get("/sessions/{session_id}/dependency-check")
async def check_dependencies(
    session_id: str,
    db: Session = Depends(get_db),
    _=Depends(verify_admin),
):
    """检查依赖同步状态"""
    service = StepVersionService(db)
    deps = service.get_dependency_status(session_id)

    # 按状态分组
    pending = [d for d in deps if d["sync_status"] == "pending"]
    synced = [d for d in deps if d["sync_status"] == "synced"]
    conflict = [d for d in deps if d["sync_status"] == "conflict"]

    return {
        "dependencies": deps,
        "summary": {
            "total": len(deps),
            "pending": len(pending),
            "synced": len(synced),
            "conflict": len(conflict),
        },
        "pending_suggestions": [
            {
                "upstream": d["upstream_step"],
                "downstream": d["downstream_step"],
                "suggestion": d["sync_suggestion"],
            }
            for d in pending
        ],
    }


@router.post("/sessions/{session_id}/sync-downstream")
async def sync_downstream(
    session_id: str,
    req: SyncDownstreamRequest,
    db: Session = Depends(get_db),
    _=Depends(verify_admin),
):
    """同步下游步骤"""
    service = StepVersionService(db)
    result = service.sync_downstream(session_id, req.from_step, req.strategy)
    db.commit()
    return result


# ─────────────────────────────────────────────────────────
# 动态规则API
# ─────────────────────────────────────────────────────────

@router.post("/sessions/{session_id}/rules")
async def add_dynamic_rule(
    session_id: str,
    req: AddRuleRequest,
    db: Session = Depends(get_db),
    _=Depends(verify_admin),
):
    """添加动态规则"""
    service = StepVersionService(db)
    rule = service.add_dynamic_rule(
        content=req.content,
        scope=req.scope,
        session_id=session_id,
        target_step=req.target_step,
        target_episode=req.target_episode,
        apply_timing=req.apply_timing,
    )
    db.commit()
    return {"rule": rule.to_dict()}


@router.get("/sessions/{session_id}/rules")
async def get_active_rules(
    session_id: str,
    step_id: Optional[str] = None,
    db: Session = Depends(get_db),
    _=Depends(verify_admin),
):
    """获取生效中的规则"""
    service = StepVersionService(db)
    rules = service.get_active_rules(session_id, step_id)
    return {"rules": [r.to_dict() for r in rules]}


@router.delete("/rules/{rule_id}")
async def deactivate_rule(
    rule_id: str,
    db: Session = Depends(get_db),
    _=Depends(verify_admin),
):
    """停用规则"""
    from app.models.step_version import DynamicRule

    rule = db.query(DynamicRule).filter_by(id=rule_id).first()
    if not rule:
        raise HTTPException(status_code=404, detail="规则不存在")

    rule.is_active = 0
    db.commit()
    return {"success": True}


# ─────────────────────────────────────────────────────────
# 评审循环API
# ─────────────────────────────────────────────────────────

@router.post("/sessions/{session_id}/reviews")
async def create_review(
    session_id: str,
    req: CreateReviewRequest,
    db: Session = Depends(get_db),
    _=Depends(verify_admin),
):
    """创建评审记录"""
    service = StepVersionService(db)
    review = service.create_review(
        version_id=req.version_id,
        session_id=session_id,
        verdict=req.verdict,
        comments=req.comments,
        issues=req.issues,
        rewrite_hint=req.rewrite_hint,
        review_type="manual",
        reviewed_by="user",
        score=req.score,
    )
    db.commit()
    return {"review": review.to_dict()}


@router.get("/versions/{version_id}/reviews")
async def get_version_reviews(
    version_id: str,
    db: Session = Depends(get_db),
    _=Depends(verify_admin),
):
    """获取版本的评审记录"""
    service = StepVersionService(db)
    reviews = service.get_reviews_for_version(version_id)
    return {"reviews": [r.to_dict() for r in reviews]}


@router.get("/versions/{version_id}/review-status")
async def get_review_status(
    version_id: str,
    db: Session = Depends(get_db),
    _=Depends(verify_admin),
):
    """获取评审状态（是否需要重写）"""
    service = StepVersionService(db)
    needs_rewrite, hint = service.needs_rewrite(version_id)
    latest = service.get_latest_review(version_id)

    return {
        "needs_rewrite": needs_rewrite,
        "rewrite_hint": hint,
        "latest_review": latest.to_dict() if latest else None,
    }


# ─────────────────────────────────────────────────────────
# 局部重写API
# ─────────────────────────────────────────────────────────

@router.post("/sessions/{session_id}/steps/{step_id}/partial-regenerate")
async def partial_regenerate(
    session_id: str,
    step_id: str,
    req: PartialRegenerateRequest,
    db: Session = Depends(get_db),
    _=Depends(verify_admin),
):
    """局部重写（只修改指定部分）"""
    service = StepVersionService(db)

    # 获取基础版本
    from app.models.step_version import StepVersion

    base = db.query(StepVersion).filter_by(id=req.base_version_id).first()
    if not base:
        raise HTTPException(status_code=404, detail="基础版本不存在")

    # TODO: 调用AI服务进行局部重写
    # 这里先返回占位实现
    return {
        "success": True,
        "message": f"将针对 {req.target_type}/{req.target_name} 进行局部重写",
        "target": {
            "type": req.target_type,
            "name": req.target_name,
            "field": req.target_field,
        },
        "prompt": req.prompt,
        "base_version": base.version_number,
    }


# ─────────────────────────────────────────────────────────
# 综合状态API
# ─────────────────────────────────────────────────────────

@router.get("/sessions/{session_id}/workflow-status")
async def get_workflow_status(
    session_id: str,
    db: Session = Depends(get_db),
    _=Depends(verify_admin),
):
    """获取完整的工作流状态（用于前端整体展示）"""
    service = StepVersionService(db)

    # 步骤顺序
    steps = [
        "concept",
        "characters",
        "beat_sheet",
        "scene_list",
        "script_draft",
        "storyboard",
    ]

    step_status = []
    for step_id in steps:
        current = service.get_current_version(session_id, step_id)
        versions = service.get_version_tree(session_id, step_id)

        status = {
            "step_id": step_id,
            "has_content": current is not None,
            "current_version": current.to_dict() if current else None,
            "version_count": len(versions),
            "versions": versions,
        }

        if current:
            needs_rewrite, hint = service.needs_rewrite(current.id)
            status["needs_rewrite"] = needs_rewrite
            status["rewrite_hint"] = hint

        step_status.append(status)

    # 依赖状态
    deps = service.get_dependency_status(session_id)
    pending_deps = [d for d in deps if d["sync_status"] == "pending"]

    # 活跃规则
    rules = service.get_active_rules(session_id)

    return {
        "steps": step_status,
        "dependencies": {
            "total": len(deps),
            "pending": len(pending_deps),
            "items": pending_deps,
        },
        "active_rules_count": len(rules),
    }
