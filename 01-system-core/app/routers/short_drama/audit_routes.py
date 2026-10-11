"""测试页 “验证 / 深度审计 / 自动修复” 三个 endpoint 子包（从 short_drama_writing.py 抽出）。

3 个路由：

- POST /testing/script-scene/validate    —— 走完整 scene 评估 + scene-level gate
- POST /testing/script-scene/deep-audit  —— 跑 benchmark/continuity 深审，可吃 RAG 注入
- POST /testing/script-scene/auto-fix    —— 自动修复主流程（结构化兜底 + LLM 重写）

主 router 用 include_router 聚合，URL 不变。
"""
from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.auth.dependencies import ProjectAccessActor, verify_project_actor
from app.database import get_db
from app.routers.short_drama._billing import (
    charge_short_drama_usage,
    ensure_short_drama_project_access,
    record_short_drama_failure,
)
from app.schemas.short_drama_writing import (
    BenchmarkAssessment,
    ContinuityAssessment,
    TestingFailureAnalysis,
    TestingScriptAutoFixResponse,
    TestingScriptDeepAuditResponse,
    TestingScriptValidationRequest,
    TestingScriptValidationResponse,
)
from app.services.short_drama_autofix import auto_fix_testing_script_content
from app.services.short_drama_deep_audit import run_testing_deep_audit
from app.services.short_drama_evaluate_scene import evaluate_testing_scene
from app.services.short_drama_evaluation_pipeline import apply_scene_level_gate
from app.services.short_drama_final_generation_contract import current_testing_final_generation_contract
from app.services.short_drama_quality_anchors import build_testing_quality_anchor_block
from app.services.short_drama_rag_injection import apply_rag_injection
from app.services.short_drama_testing_enrich import enrich_testing_request_from_project
from app.services.short_drama_testing_failure import (
    build_testing_skill_workflow,
    log_testing_failure_analysis,
)
from app.services.text_generation_service import TextGenerationError, begin_usage_collection, end_usage_collection

router = APIRouter()  # 由主 router 加 prefix


def _ensure_testing_project_access(
    db: Session,
    req: TestingScriptValidationRequest,
    actor: ProjectAccessActor,
    *,
    require_credit: bool = True,
) -> None:
    ensure_short_drama_project_access(
        db,
        req.project_id,
        actor,
        require_credit=require_credit,
    )


def _charge_testing_audit(
    db: Session,
    actor: ProjectAccessActor,
    usage_metrics: dict[str, Any],
    *,
    generation_type: str,
    reason: str,
) -> None:
    charge_short_drama_usage(
        db,
        actor,
        usage_metrics,
        generation_type=generation_type,
        reason=reason,
    )


def _record_testing_audit_failure(
    db: Session,
    actor: ProjectAccessActor,
    exc: Exception,
    *,
    generation_type: str,
) -> None:
    record_short_drama_failure(
        db,
        actor,
        generation_type=generation_type,
        reason=f"测试页审校链路失败，未扣费：{exc}",
    )


@router.post(
    "/testing/script-scene/validate",
    response_model=TestingScriptValidationResponse,
    summary="测试页剧本规则校验",
)
async def validate_testing_script_scene(
    req: TestingScriptValidationRequest,
    actor: ProjectAccessActor = Depends(verify_project_actor),
    db: Session = Depends(get_db),
):
    _ensure_testing_project_access(db, req, actor, require_credit=False)
    req = enrich_testing_request_from_project(req, db)
    content = str(req.scene_content or "").strip()
    if not content:
        return TestingScriptValidationResponse(
            char_count_excluding_punctuation=0,
            skill_workflow=build_testing_skill_workflow(
                None,
                blocking_issues=[],
                warnings=[],
                context="testing_validate",
            ),
        )
    _ensure_testing_project_access(db, req, actor, require_credit=True)

    validation_req = req
    usage_metrics, usage_token = begin_usage_collection({"scope": "testing_validate"})
    try:
        evaluation = evaluate_testing_scene(
            validation_req, content, build_testing_quality_anchor_block(validation_req)
        )
        evaluation = apply_scene_level_gate(
            validation_req, evaluation, current_testing_final_generation_contract(validation_req)
        )
    except Exception as exc:
        _record_testing_audit_failure(db, actor, exc, generation_type="testing_script_validate")
        raise
    finally:
        end_usage_collection(usage_token)
    blocking_issues = list(evaluation["blocking_issues"])
    warnings = list(evaluation["warnings"])

    selected_ids = {str(item) for item in (req.selected_character_ids or []) if str(item).strip()}
    if len(evaluation["present_character_ids"]) >= 2 and not selected_ids:
        warnings.append("当前场景存在多人互动，但尚未明确勾选出场角色，建议同步角色图谱后再继续精写。")

    skill_workflow = build_testing_skill_workflow(
        evaluation["failure_analysis"],
        blocking_issues=blocking_issues,
        warnings=warnings,
        context="testing_validate",
    )

    response = TestingScriptValidationResponse(
        char_count_excluding_punctuation=evaluation["char_count_excluding_punctuation"],
        warnings=warnings,
        blocking_issues=blocking_issues,
        present_character_ids=evaluation["present_character_ids"],
        health_items=evaluation["health_items"],
        relationship_suggestions=evaluation["relationship_suggestions"],
        state_card_suggestions=evaluation["state_card_suggestions"],
        benchmark_assessment=evaluation.get("benchmark_assessment") or BenchmarkAssessment(),
        continuity_assessment=evaluation.get("continuity_assessment") or ContinuityAssessment(),
        failure_analysis=evaluation["failure_analysis"],
        skill_workflow=skill_workflow,
        episode_memory_card=evaluation.get("episode_memory_card") or {},
        canon_packet=evaluation.get("canon_packet") or {},
    )
    if response.blocking_issues:
        log_testing_failure_analysis(validation_req, response.failure_analysis, evaluation)
    _charge_testing_audit(
        db,
        actor,
        usage_metrics,
        generation_type="testing_script_validate",
        reason="测试页剧本规则校验成功扣费",
    )
    return response


@router.post(
    "/testing/script-scene/deep-audit",
    response_model=TestingScriptDeepAuditResponse,
    summary="测试页逐集对标与连续性深度审计",
)
async def deep_audit_testing_script_scene(
    req: TestingScriptValidationRequest,
    actor: ProjectAccessActor = Depends(verify_project_actor),
    db: Session = Depends(get_db),
):
    _ensure_testing_project_access(db, req, actor, require_credit=False)
    req = enrich_testing_request_from_project(req, db)
    content = str(req.scene_content or req.episode_content or "").strip()
    if not content and not str(req.episode_content or "").strip():
        return TestingScriptDeepAuditResponse()
    _ensure_testing_project_access(db, req, actor, require_credit=True)
    variables = {
        "audience_axis": req.audience_axis,
        "genre_main": req.genre_main,
        "genre_sub": req.genre_sub,
        "subgenre_track": req.subgenre_track,
        "sample_track": req.sample_track,
        "draft_episode": str(req.episode_no or ""),
        "brief": req.brief,
        "rag_review_references": req.rag_review_references or "",
    }
    usage_metrics, usage_token = begin_usage_collection({"scope": "testing_deep_audit"})
    try:
        await apply_rag_injection(
            "quality_check",
            {"project": {"id": req.project_id, "project_id": req.project_id}},
            variables,
            db=db,
        )
        req = req.model_copy(update={
            "rag_review_references": str(req.rag_review_references or variables.get("rag_review_references") or ""),
        })

        def _run_deep_audit_sync() -> tuple[BenchmarkAssessment, ContinuityAssessment, dict[str, Any]]:
            evaluation = evaluate_testing_scene(req, content, build_testing_quality_anchor_block(req))
            benchmark, continuity = run_testing_deep_audit(
                req, evaluation, current_testing_final_generation_contract(req)
            )
            return benchmark, continuity, evaluation

        benchmark_assessment, continuity_assessment, evaluation = await asyncio.to_thread(
            _run_deep_audit_sync
        )
    except Exception as exc:
        _record_testing_audit_failure(db, actor, exc, generation_type="testing_script_deep_audit")
        raise
    finally:
        end_usage_collection(usage_token)
    failure_analysis = (
        evaluation.get("failure_analysis")
        if isinstance(evaluation.get("failure_analysis"), TestingFailureAnalysis)
        else TestingFailureAnalysis(**(evaluation.get("failure_analysis") or {}))
        if isinstance(evaluation.get("failure_analysis"), dict)
        else TestingFailureAnalysis()
    )
    skill_workflow = build_testing_skill_workflow(
        failure_analysis,
        blocking_issues=evaluation.get("blocking_issues") or [],
        warnings=evaluation.get("warnings") or [],
        context="testing_deep_audit",
    )
    _charge_testing_audit(
        db,
        actor,
        usage_metrics,
        generation_type="testing_script_deep_audit",
        reason="测试页深度审计成功扣费",
    )
    return TestingScriptDeepAuditResponse(
        benchmark_assessment=benchmark_assessment,
        continuity_assessment=continuity_assessment,
        failure_analysis=failure_analysis,
        skill_workflow=skill_workflow,
    )


@router.post(
    "/testing/script-scene/auto-fix",
    response_model=TestingScriptAutoFixResponse,
    summary="测试页一键修复阻断项",
)
async def auto_fix_testing_script_scene(
    req: TestingScriptValidationRequest,
    actor: ProjectAccessActor = Depends(verify_project_actor),
    db: Session = Depends(get_db),
):
    _ensure_testing_project_access(db, req, actor, require_credit=True)
    req = enrich_testing_request_from_project(req, db)
    usage_metrics, usage_token = begin_usage_collection({"scope": "testing_auto_fix"})
    try:
        response = await asyncio.to_thread(
            auto_fix_testing_script_content, req, str(req.scene_content or "").strip()
        )
        _charge_testing_audit(
            db,
            actor,
            usage_metrics,
            generation_type="testing_script_auto_fix",
            reason="测试页自动修复成功扣费",
        )
        return response
    except HTTPException:
        raise
    except TextGenerationError as exc:
        _record_testing_audit_failure(db, actor, exc, generation_type="testing_script_auto_fix")
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        _record_testing_audit_failure(db, actor, exc, generation_type="testing_script_auto_fix")
        raise
    finally:
        end_usage_collection(usage_token)
