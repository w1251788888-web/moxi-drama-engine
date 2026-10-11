"""
gstack 遥测集成入口 - 在应用启动时初始化

使用方法:
    from app.telemetry_integration import init_telemetry, track_endpoint

    # 在应用启动时调用
    init_telemetry()

    # 在路由中使用装饰器
    @router.post("/some-endpoint")
    @track_endpoint("market_validation")
    async def some_endpoint(...):
        ...
"""
from __future__ import annotations

import functools
import time
from typing import Any, Callable

from fastapi import Request


def init_telemetry() -> dict[str, Any]:
    """
    初始化遥测系统 - 应在应用启动时调用

    Returns:
        包含会话信息和项目记忆状态的字典
    """
    from app.services.telemetry_service import (
        touch_session,
        cleanup_old_sessions,
        get_project_memory_summary,
        log_timeline_event,
        get_active_session_count,
    )

    # 清理过期会话
    cleaned = cleanup_old_sessions(max_age_minutes=120)

    # 标记当前会话
    touch_session()

    # 获取项目记忆
    summary = get_project_memory_summary()

    # 记录启动事件
    log_timeline_event(
        skill="system",
        event="started",
        branch="main",
        metadata={
            "cleaned_sessions": cleaned,
            "active_sessions": summary.get("active_sessions", 0),
        },
    )

    return summary


def track_endpoint(skill_name: str):
    """
    FastAPI 路由装饰器 - 自动记录端点调用情况

    用法:
        @router.post("/tasks")
        @track_endpoint("task_creation")
        async def create_task(...):
            ...
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def async_wrapper(*args, **kwargs) -> Any:
            from app.services.telemetry_service import (
                log_skill_usage,
                log_timeline_event,
                touch_session,
            )

            touch_session()
            start = time.time()
            outcome = "success"

            try:
                result = await func(*args, **kwargs)
                return result
            except Exception as e:
                outcome = f"error:{type(e).__name__}"
                raise
            finally:
                duration = int(time.time() - start)
                log_skill_usage(skill_name, outcome, duration)
                log_timeline_event(
                    skill=skill_name,
                    event="completed",
                    outcome=outcome,
                    duration_s=duration,
                )

        return async_wrapper
    return decorator


def track_workflow_step(step_name: str, step_type: str = "workflow"):
    """
    工作流步骤装饰器 - 用于 market_workflow_service 等长时间运行任务

    用法:
        @track_workflow_step("sample_generation", "short_drama_lab")
        async def generate_sample(...):
            ...
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def async_wrapper(*args, **kwargs) -> Any:
            from app.services.telemetry_service import (
                log_skill_usage,
                log_timeline_event,
                log_learning,
                touch_session,
            )

            touch_session()
            start = time.time()
            outcome = "success"

            try:
                result = await func(*args, **kwargs)
                return result
            except Exception as e:
                outcome = f"error:{type(e).__name__}"
                # 记录失败经验
                log_learning(
                    skill=step_type,
                    insight_type="fix",
                    key=f"{step_name}_failure",
                    insight=f"{step_name} failed with {type(e).__name__}: {str(e)[:200]}",
                    confidence=7,
                    source="observed",
                )
                raise
            finally:
                duration = int(time.time() - start)
                log_skill_usage(f"{step_type}:{step_name}", outcome, duration)
                log_timeline_event(
                    skill=step_type,
                    event=f"step_completed:{step_name}",
                    outcome=outcome,
                    duration_s=duration,
                )

        return async_wrapper
    return decorator


def get_welcome_context() -> dict[str, Any]:
    """
    获取会话欢迎上下文 - 用于 Claude Code 启动时显示

    Returns:
        包含项目状态的字典
    """
    from app.services.telemetry_service import (
        get_project_memory_summary,
        get_last_session_info,
        get_recent_learnings,
        touch_session,
    )

    touch_session()

    summary = get_project_memory_summary()
    last_session = summary.get("last_session")

    context = {
        "project": "墨戏生花 (moxishenghua)",
        "last_session": None,
        "recent_learnings": [],
        "skill_usage_30d": summary.get("skill_stats", {}),
        "active_sessions": summary.get("active_sessions", 0),
        "recommendations": [],
    }

    if last_session:
        context["last_session"] = {
            "skill": last_session.get("skill"),
            "outcome": last_session.get("outcome"),
            "branch": last_session.get("branch"),
            "when": last_session.get("ts"),
        }

        # 根据上次会话推荐下一步
        last_skill = last_session.get("skill", "")
        if last_skill == "plan-eng-review":
            context["recommendations"].append("上次进行了架构评审，接下来可能是 /ship 或 /qa")
        elif last_skill == "office-hours":
            context["recommendations"].append("上次进行了产品讨论，查看 ceo-plans 目录获取计划")
        elif last_skill == "investigate":
            context["recommendations"].append("上次进行了问题排查，确认是否需要 /qa 验证修复")

    # 加载最近学习
    learnings = get_recent_learnings(limit=3)
    if learnings:
        context["recent_learnings"] = [
            {
                "skill": entry.get("skill"),
                "key": entry.get("key"),
                "insight": entry.get("insight", "")[:80] + "...",
            }
            for entry in learnings
        ]

    return context


def format_welcome_message(context: dict[str, Any] | None = None) -> str:
    """格式化欢迎消息"""
    if context is None:
        context = get_welcome_context()

    lines = []
    lines.append(f"Welcome back to {context['project']}")

    last = context.get("last_session")
    if last:
        lines.append(f"Last session: /{last['skill']} ({last['outcome']}) on {last['branch']}")

    learnings = context.get("recent_learnings", [])
    if learnings:
        lines.append(f"\nRecent learnings ({len(learnings)} entries):")
        for entry in learnings:
            lines.append(f"  - [{entry['skill']}] {entry['key']}")

    recommendations = context.get("recommendations", [])
    if recommendations:
        lines.append(f"\nRecommendations:")
        for rec in recommendations:
            lines.append(f"  → {rec}")

    if context.get("active_sessions", 0) > 1:
        lines.append(f"\nNote: {context['active_sessions']} active sessions")

    return "\n".join(lines)


# ============ CLI 检查脚本 ============
if __name__ == "__main__":
    # 作为独立脚本运行时，输出会话上下文 (供 bash 解析)
    import sys
    import json

    # 解析命令行参数
    cmd = sys.argv[1] if len(sys.argv) > 1 else "welcome"

    if cmd == "welcome":
        print(format_welcome_message())
    elif cmd == "json":
        print(json.dumps(get_welcome_context(), ensure_ascii=False, indent=2))
    elif cmd == "init":
        result = init_telemetry()
        print(f"Telemetry initialized. Active sessions: {result.get('active_sessions', 0)}")
    elif cmd == "check":
        from app.services.telemetry_service import get_skill_usage_stats
        stats = get_skill_usage_stats(days=7)
        print(f"Skill usage (last 7 days): {stats['total']} total")
        if stats["by_skill"]:
            print("By skill:")
            for skill, count in sorted(stats["by_skill"].items(), key=lambda x: -x[1])[:5]:
                print(f"  - {skill}: {count}")
    else:
        print(f"Unknown command: {cmd}")
        print("Usage: python -m app.telemetry_integration [welcome|json|init|check]")
