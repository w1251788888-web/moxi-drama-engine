from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth.dependencies import verify_admin
from app.database import get_db
from app.services.skill_workflow_service import (
    create_skill_artifact,
    create_skill_binding,
    create_skill_quality_feedback,
    execute_external_skill_runner_request,
    get_db_skill_catalog,
    list_skill_artifacts,
    list_skill_bindings,
    list_skill_invocations,
    list_skill_quality_feedback,
    prepare_external_skill_runner_request,
    recommend_skill_workflow,
    resolve_skill_bindings,
    finish_skill_invocation,
    run_skill_workflow_worker,
    start_skill_invocation,
    summarize_skill_quality_feedback,
    sync_skill_manifest_to_db,
    update_skill_binding,
)


router = APIRouter(prefix="/admin/skill-workflows", tags=["Skill Workflows"])


class SkillWorkflowRecommendRequest(BaseModel):
    failure_type: str = ""
    blocking_issues: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    context: str = "general"


class SkillBindingRequest(BaseModel):
    skill_name: str
    binding_type: str = Field(..., description="global/failure_type/step/project_type/context")
    binding_key: str = ""
    priority: int = 100
    config: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
    is_enabled: bool = True


class SkillBindingUpdateRequest(BaseModel):
    binding_key: str | None = None
    priority: int | None = None
    config: dict[str, Any] | None = None
    metadata: dict[str, Any] | None = None
    status: str | None = None
    is_enabled: bool | None = None


class SkillInvocationStartRequest(BaseModel):
    skill_name: str
    binding_id: str = ""
    actor_type: str = "admin"
    actor_id: str = ""
    context: str = "general"
    failure_type: str = ""
    input_summary: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class SkillInvocationFinishRequest(BaseModel):
    status: str = "success"
    output_summary: str = ""
    metadata: dict[str, Any] | None = None


class SkillArtifactRequest(BaseModel):
    artifact_type: str = "text"
    title: str = ""
    content: str = ""
    path: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class SkillQualityFeedbackRequest(BaseModel):
    score: int = 0
    verdict: str = "pending_review"
    reviewer_type: str = "admin"
    reviewer_id: str = ""
    notes: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class SkillWorkerRunRequest(BaseModel):
    failure_type: str = ""
    blocking_issues: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    context: str = "skill-worker"
    actor_type: str = "system"
    actor_id: str = ""
    max_skills: int = 3


class SkillExternalRunnerRequest(BaseModel):
    skill_name: str
    binding_id: str = ""
    parameters: dict[str, Any] = Field(default_factory=dict)
    context: str = "external-runner"
    actor_type: str = "admin"
    actor_id: str = ""
    runner_name: str = "manual_external_runner"
    timeout_seconds: int | None = None
    confirm_execution: bool = False
    confirmation_phrase: str = ""
    confirmed_by: str = ""


class SkillExternalRunnerExecuteRequest(BaseModel):
    request_invocation_id: str
    runner_name: str = ""
    context: str = "external-runner-executor"
    actor_type: str = "admin"
    actor_id: str = ""
    confirm_execution: bool = False
    confirmation_phrase: str = ""
    confirmed_by: str = ""


@router.get("/catalog", summary="查看当前接入的第三方技能目录")
async def get_catalog(
    include_disabled: bool = False,
    _: bool = Depends(verify_admin),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    skills = get_db_skill_catalog(db, include_disabled=include_disabled)
    return {"source": "database", "skill_count": len(skills), "skills": skills}


@router.post("/sync", summary="从 manifest 同步技能目录到数据库")
async def sync_catalog(
    _: bool = Depends(verify_admin),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return sync_skill_manifest_to_db(db)


@router.post("/recommend", summary="根据失败类型返回推荐的技能工作流")
async def recommend_workflow(
    req: SkillWorkflowRecommendRequest,
    _: bool = Depends(verify_admin),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return recommend_skill_workflow(
        failure_type=req.failure_type,
        blocking_issues=req.blocking_issues,
        warnings=req.warnings,
        context=req.context,
        db=db,
    )


@router.post("/worker/run", summary="运行内部 Skill 编排 worker")
async def run_worker(
    req: SkillWorkerRunRequest,
    _: bool = Depends(verify_admin),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    try:
        return run_skill_workflow_worker(
            db,
            failure_type=req.failure_type,
            blocking_issues=req.blocking_issues,
            warnings=req.warnings,
            context=req.context,
            actor_type=req.actor_type,
            actor_id=req.actor_id,
            max_skills=req.max_skills,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/runner/prepare", summary="准备外部 Skill runner 门禁请求")
async def prepare_external_runner(
    req: SkillExternalRunnerRequest,
    _: bool = Depends(verify_admin),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    try:
        return prepare_external_skill_runner_request(
            db,
            skill_name=req.skill_name,
            binding_id=req.binding_id,
            parameters=req.parameters,
            context=req.context,
            actor_type=req.actor_type,
            actor_id=req.actor_id,
            runner_name=req.runner_name,
            timeout_seconds=req.timeout_seconds,
            confirm_execution=req.confirm_execution,
            confirmation_phrase=req.confirmation_phrase,
            confirmed_by=req.confirmed_by,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/runner/execute", summary="受控执行外部 Skill runner 请求")
async def execute_external_runner(
    req: SkillExternalRunnerExecuteRequest,
    _: bool = Depends(verify_admin),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    try:
        return execute_external_skill_runner_request(
            db,
            request_invocation_id=req.request_invocation_id,
            runner_name=req.runner_name,
            context=req.context,
            actor_type=req.actor_type,
            actor_id=req.actor_id,
            confirm_execution=req.confirm_execution,
            confirmation_phrase=req.confirmation_phrase,
            confirmed_by=req.confirmed_by,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/bindings", summary="查看 Skill 绑定")
async def get_bindings(
    skill_name: str = "",
    binding_type: str = "",
    binding_key: str = "",
    include_disabled: bool = False,
    limit: int = 100,
    _: bool = Depends(verify_admin),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    items = list_skill_bindings(
        db,
        skill_name=skill_name,
        binding_type=binding_type,
        binding_key=binding_key,
        include_disabled=include_disabled,
        limit=limit,
    )
    return {"count": len(items), "items": items}


@router.post("/bindings", summary="创建 Skill 绑定")
async def create_binding(
    req: SkillBindingRequest,
    _: bool = Depends(verify_admin),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    try:
        return create_skill_binding(
            db,
            skill_name=req.skill_name,
            binding_type=req.binding_type,
            binding_key=req.binding_key,
            priority=req.priority,
            config=req.config,
            metadata=req.metadata,
            is_enabled=req.is_enabled,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.put("/bindings/{binding_id}", summary="更新 Skill 绑定")
async def update_binding(
    binding_id: str,
    req: SkillBindingUpdateRequest,
    _: bool = Depends(verify_admin),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    try:
        return update_skill_binding(
            db,
            binding_id,
            binding_key=req.binding_key,
            priority=req.priority,
            config=req.config,
            metadata=req.metadata,
            status=req.status,
            is_enabled=req.is_enabled,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/bindings/resolve", summary="按上下文解析可用 Skill 绑定")
async def resolve_bindings(
    failure_type: str = "",
    step_id: str = "",
    project_type: str = "",
    context: str = "",
    limit: int = 20,
    _: bool = Depends(verify_admin),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    items = resolve_skill_bindings(
        db,
        failure_type=failure_type,
        step_id=step_id,
        project_type=project_type,
        context=context,
        limit=limit,
    )
    return {"count": len(items), "items": items}


@router.post("/invocations", summary="记录 Skill 调用开始")
async def start_invocation(
    req: SkillInvocationStartRequest,
    _: bool = Depends(verify_admin),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    try:
        return start_skill_invocation(
            db,
            skill_name=req.skill_name,
            binding_id=req.binding_id,
            actor_type=req.actor_type,
            actor_id=req.actor_id,
            context=req.context,
            failure_type=req.failure_type,
            input_summary=req.input_summary,
            metadata=req.metadata,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/invocations", summary="查看 Skill 调用记录")
async def get_invocations(
    skill_name: str = "",
    status: str = "",
    context: str = "",
    limit: int = 50,
    _: bool = Depends(verify_admin),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    items = list_skill_invocations(
        db,
        skill_name=skill_name,
        status=status,
        context=context,
        limit=limit,
    )
    return {"count": len(items), "items": items}


@router.put("/invocations/{invocation_id}/finish", summary="记录 Skill 调用完成")
async def finish_invocation(
    invocation_id: str,
    req: SkillInvocationFinishRequest,
    _: bool = Depends(verify_admin),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    try:
        return finish_skill_invocation(
            db,
            invocation_id,
            status=req.status,
            output_summary=req.output_summary,
            metadata=req.metadata,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/invocations/{invocation_id}/artifacts", summary="记录 Skill 调用产物")
async def create_artifact(
    invocation_id: str,
    req: SkillArtifactRequest,
    _: bool = Depends(verify_admin),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    try:
        return create_skill_artifact(
            db,
            invocation_id=invocation_id,
            artifact_type=req.artifact_type,
            title=req.title,
            content=req.content,
            path=req.path,
            metadata=req.metadata,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/invocations/{invocation_id}/feedback", summary="记录 Skill 调用质量反馈")
async def create_quality_feedback(
    invocation_id: str,
    req: SkillQualityFeedbackRequest,
    _: bool = Depends(verify_admin),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    try:
        return create_skill_quality_feedback(
            db,
            invocation_id=invocation_id,
            score=req.score,
            verdict=req.verdict,
            reviewer_type=req.reviewer_type,
            reviewer_id=req.reviewer_id,
            notes=req.notes,
            metadata=req.metadata,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/artifacts", summary="查看 Skill 调用产物")
async def get_artifacts(
    invocation_id: str = "",
    skill_name: str = "",
    artifact_type: str = "",
    limit: int = 50,
    _: bool = Depends(verify_admin),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    items = list_skill_artifacts(
        db,
        invocation_id=invocation_id,
        skill_name=skill_name,
        artifact_type=artifact_type,
        limit=limit,
    )
    return {"count": len(items), "items": items}


@router.get("/quality-feedback", summary="查看 Skill 质量反馈")
async def get_quality_feedback(
    invocation_id: str = "",
    skill_name: str = "",
    verdict: str = "",
    limit: int = 50,
    _: bool = Depends(verify_admin),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    items = list_skill_quality_feedback(
        db,
        invocation_id=invocation_id,
        skill_name=skill_name,
        verdict=verdict,
        limit=limit,
    )
    return {"count": len(items), "items": items}


@router.get("/quality-feedback/summary", summary="聚合 Skill 质量反馈并生成优先级建议")
async def get_quality_feedback_summary(
    skill_name: str = "",
    limit: int = 1000,
    min_feedback: int = 2,
    _: bool = Depends(verify_admin),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return summarize_skill_quality_feedback(
        db,
        skill_name=skill_name,
        limit=limit,
        min_feedback=min_feedback,
    )
