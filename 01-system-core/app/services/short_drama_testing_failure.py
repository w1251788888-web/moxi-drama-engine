"""测试页"失败分析记录"与"技能工作流推荐"两个轻量 helper（从 short_drama_writing.py 抽出）。

- log_testing_failure_analysis：把一次失败分析写到 telemetry（time-line + learning）
- build_testing_skill_workflow：调 skill_workflow_service.recommend_skill_workflow

两个函数都被多个测试页 endpoint 共用（generate / validate / deep-audit / auto-fix）。
搬到 services 后，未来这些 endpoint 进子文件就不必再"伸手回主 router 拿"。
"""
from __future__ import annotations

from typing import Any, TYPE_CHECKING

from app.services.skill_workflow_service import recommend_skill_workflow

if TYPE_CHECKING:
    from app.schemas.short_drama_writing import TestingFailureAnalysis, TestingScriptRequest


def log_testing_failure_analysis(
    req: "TestingScriptRequest",
    analysis: "TestingFailureAnalysis",
    evaluation: dict[str, Any],
) -> None:
    """把一次失败分析写到 telemetry（不阻塞主链路）。"""
    if not getattr(analysis, "failure_type", None):
        return
    try:
        from app.services.telemetry_service import log_learning, log_timeline_event

        metadata = {
            "segment": analysis.failed_segment,
            "failure_type": analysis.failure_type,
            "repair_scope": analysis.repair_scope,
            "rollback_recommendation": analysis.rollback_recommendation,
            "audience_axis": str(req.audience_axis or ""),
            "genre_main": str(req.genre_main or ""),
            "subgenre_track": str(req.subgenre_track or ""),
            "sample_track": str(req.sample_track or ""),
            "evidence": analysis.evidence,
        }
        log_timeline_event(
            "short_drama_failure",
            "detected",
            branch=analysis.failed_segment or "scene",
            outcome=analysis.failure_type,
            metadata=metadata,
        )
        log_learning(
            "short_drama_failure",
            "pattern",
            f"{analysis.failed_segment}:{analysis.failure_type}",
            f"{analysis.root_cause} 修法：{analysis.fix_strategy}",
            confidence=7,
            source="observed",
        )
    except Exception:
        # telemetry 故障不能影响主流程
        pass


def build_testing_skill_workflow(
    failure_analysis: Any,
    *,
    blocking_issues: list[str] | None = None,
    warnings: list[str] | None = None,
    context: str = "testing_script_scene",
) -> dict[str, Any]:
    """根据 failure_type + 阻断/告警 调技能工作流推荐。"""
    # 兼容传入 TestingFailureAnalysis Pydantic 对象 / 普通 dict / None
    if isinstance(failure_analysis, dict):
        failure_type = str(failure_analysis.get("failure_type") or "").strip()
    elif failure_analysis is None:
        failure_type = ""
    else:
        failure_type = str(getattr(failure_analysis, "failure_type", "") or "").strip()
    return recommend_skill_workflow(
        failure_type=failure_type,
        blocking_issues=[str(item) for item in (blocking_issues or [])],
        warnings=[str(item) for item in (warnings or [])],
        context=context,
    )
