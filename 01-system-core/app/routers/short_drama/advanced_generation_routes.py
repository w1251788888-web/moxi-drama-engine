"""高级生成模式配置路由。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from app.auth.dependencies import ProjectAccessActor, verify_advanced_generation_actor
from app.schemas.short_drama_writing import (
    AdvancedGenerationOrchestrationPlanResponse,
    AdvancedGenerationOrchestrationRequest,
    AdvancedGenerationOrchestrationStatusResponse,
    AdvancedGenerationPlanRequest,
    AdvancedGenerationPlanResponse,
    AdvancedGenerationProfile,
    AdvancedGenerationProfileListResponse,
)
from app.services.advanced_workflow_orchestration_service import (
    build_writer_reviewer_decision_orchestration,
    get_orchestration_status,
)
from app.services.short_drama_advanced_generation import (
    MODE_ID,
    MODE_LABEL,
    build_advanced_generation_plan,
    get_advanced_generation_profile,
    list_advanced_generation_profiles,
)


router = APIRouter()


@router.get(
    "/advanced-generation/profiles",
    response_model=AdvancedGenerationProfileListResponse,
    summary="列出高级生成模式创作形态",
)
async def list_profiles(_: ProjectAccessActor = Depends(verify_advanced_generation_actor)):
    profiles = list_advanced_generation_profiles()
    return AdvancedGenerationProfileListResponse(
        mode_id=MODE_ID,
        mode_label=MODE_LABEL,
        profiles=profiles,
    )


@router.get(
    "/advanced-generation/profiles/{profile_id}",
    response_model=AdvancedGenerationProfile,
    summary="查看高级生成模式创作形态",
)
async def get_profile(profile_id: str, _: ProjectAccessActor = Depends(verify_advanced_generation_actor)):
    try:
        return get_advanced_generation_profile(profile_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post(
    "/advanced-generation/plan",
    response_model=AdvancedGenerationPlanResponse,
    summary="预览高级生成模式步骤路由",
)
async def preview_plan(req: AdvancedGenerationPlanRequest, _: ProjectAccessActor = Depends(verify_advanced_generation_actor)):
    return build_advanced_generation_plan(
        req.metadata,
        base_generation_kwargs=req.base_generation_kwargs,
    )


@router.get(
    "/advanced-generation/orchestration/status",
    response_model=AdvancedGenerationOrchestrationStatusResponse,
    summary="查看高级生成模式 LangChain/LangGraph 编排状态",
)
async def orchestration_status(_: ProjectAccessActor = Depends(verify_advanced_generation_actor)):
    return get_orchestration_status()


@router.post(
    "/advanced-generation/orchestration/plan",
    response_model=AdvancedGenerationOrchestrationPlanResponse,
    summary="预览 writer-reviewer-decision 编排",
)
async def preview_orchestration(
    req: AdvancedGenerationOrchestrationRequest,
    _: ProjectAccessActor = Depends(verify_advanced_generation_actor),
):
    return build_writer_reviewer_decision_orchestration(
        req.metadata,
        base_generation_kwargs=req.base_generation_kwargs,
        max_review_rounds=req.max_review_rounds,
    )
