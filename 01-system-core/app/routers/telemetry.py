"""
遥测数据路由 - 提供跨会话记忆与学习记录的 API 接口
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.auth.dependencies import get_current_agent, verify_admin
from app.models.agent import Agent
from app.services import telemetry_service


router = APIRouter(prefix="/telemetry", tags=["Telemetry"])


# ============================================================
# 响应模型
# ============================================================

class TimelineEventResponse(BaseModel):
    ts: str
    skill: str
    event: str
    branch: str = ""
    outcome: str = ""
    duration_s: int = 0
    session: str = ""


class LearningEntryResponse(BaseModel):
    ts: str
    skill: str
    type: str
    key: str
    insight: str
    confidence: int = 8
    source: str = ""


class SkillUsageStatsResponse(BaseModel):
    total: int
    by_skill: dict[str, int]
    by_outcome: dict[str, int]


class ProjectMemorySummaryResponse(BaseModel):
    project: str
    last_session: dict[str, Any] | None
    recent_events: list[dict[str, Any]]
    recent_learnings: list[dict[str, Any]]
    skill_usage_30d: SkillUsageStatsResponse
    active_sessions: int
    latest_checkpoint: str | None
    latest_ceo_plan: str | None


class WelcomeContextResponse(BaseModel):
    project: str
    last_session: dict[str, Any] | None
    recent_learnings: list[dict[str, Any]]
    skill_usage_30d: dict[str, Any]
    active_sessions: int
    recommendations: list[str]


class LogLearningRequest(BaseModel):
    skill: str = Field(..., description="相关技能名称")
    insight_type: str = Field("operational", description="学习类型: operational/pattern/fix")
    key: str = Field(..., description="简短标识符")
    insight: str = Field(..., description="详细描述")
    confidence: int = Field(8, ge=1, le=10, description="置信度 1-10")
    source: str = Field("observed", description="来源: observed/learned/discovered")


# ============================================================
# 公共接口 (需要登录)
# ============================================================

@router.get("/welcome", response_model=WelcomeContextResponse, summary="获取欢迎上下文")
async def get_welcome_context(
    agent: Agent = Depends(get_current_agent),
) -> WelcomeContextResponse:
    """获取会话欢迎信息 - 用于 Claude Code 启动时显示项目状态"""
    from app.telemetry_integration import get_welcome_context
    context = get_welcome_context()
    return WelcomeContextResponse(**context)


@router.get("/timeline", response_model=list[TimelineEventResponse], summary="获取时间线事件")
async def get_timeline(
    limit: int = 20,
    agent: Agent = Depends(get_current_agent),
) -> list[TimelineEventResponse]:
    """获取最近的时间线事件"""
    events = telemetry_service.get_recent_timeline_events(limit=limit)
    return [TimelineEventResponse(**e) for e in events]


@router.get("/learnings", response_model=list[LearningEntryResponse], summary="获取学习记录")
async def get_learnings(
    limit: int = 10,
    skill: str | None = None,
    agent: Agent = Depends(get_current_agent),
) -> list[LearningEntryResponse]:
    """获取最近的学习记录"""
    entries = telemetry_service.get_recent_learnings(skill=skill, limit=limit)
    return [LearningEntryResponse(**e) for e in entries]


@router.get("/stats", response_model=SkillUsageStatsResponse, summary="获取技能使用统计")
async def get_stats(
    days: int = 7,
    agent: Agent = Depends(get_current_agent),
) -> SkillUsageStatsResponse:
    """获取指定天数内的技能使用统计"""
    stats = telemetry_service.get_skill_usage_stats(days=days)
    return SkillUsageStatsResponse(**stats)


@router.get("/summary", response_model=ProjectMemorySummaryResponse, summary="获取项目记忆汇总")
async def get_summary(
    agent: Agent = Depends(get_current_agent),
) -> ProjectMemorySummaryResponse:
    """获取完整的项目记忆汇总 - 用于会话恢复"""
    summary = telemetry_service.get_project_memory_summary()
    return ProjectMemorySummaryResponse(**summary)


# ============================================================
# 管理接口 (需要管理员权限)
# ============================================================

@router.post("/learnings", summary="记录学习发现")
async def log_learning(
    req: LogLearningRequest,
    _: bool = Depends(verify_admin),
) -> dict[str, str]:
    """管理员记录操作性学习发现 (用于跨会话记忆沉淀)"""
    telemetry_service.log_learning(
        skill=req.skill,
        insight_type=req.insight_type,
        key=req.key,
        insight=req.insight,
        confidence=req.confidence,
        source=req.source,
    )
    return {"message": "学习记录已保存"}


@router.post("/event", summary="记录时间线事件")
async def log_event(
    skill: str,
    event: str,
    branch: str = "main",
    outcome: str = "",
    duration_s: int = 0,
    _: bool = Depends(verify_admin),
) -> dict[str, str]:
    """管理员手动记录时间线事件"""
    telemetry_service.log_timeline_event(
        skill=skill,
        event=event,
        branch=branch,
        outcome=outcome,
        duration_s=duration_s,
    )
    return {"message": "事件已记录"}


@router.delete("/cache", summary="清理过期会话缓存")
async def cleanup_sessions(
    max_age_minutes: int = 120,
    _: bool = Depends(verify_admin),
) -> dict[str, int]:
    """清理过期的会话标记文件"""
    cleaned = telemetry_service.cleanup_old_sessions(max_age_minutes=max_age_minutes)
    return {"cleaned_sessions": cleaned}
