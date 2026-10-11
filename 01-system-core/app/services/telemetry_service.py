"""
gstack 兼容遥测服务 - 跨会话记忆与技能使用记录
存储位置: ~/.gstack/projects/moxishenghua/
"""
from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from app.config import config


# ============ 路径配置 ============
def _get_gstack_home() -> Path:
    """获取 gstack 主目录"""
    return Path.home() / ".gstack"


def _get_project_slug() -> str:
    """获取项目标识符"""
    return "moxishenghua"


def _get_project_dir() -> Path:
    """获取项目数据目录"""
    project_dir = _get_gstack_home() / "projects" / _get_project_slug()
    project_dir.mkdir(parents=True, exist_ok=True)
    return project_dir


def _get_analytics_dir() -> Path:
    """获取分析数据目录"""
    analytics_dir = _get_gstack_home() / "analytics"
    analytics_dir.mkdir(parents=True, exist_ok=True)
    return analytics_dir


def _get_sessions_dir() -> Path:
    """获取会话标记目录"""
    sessions_dir = _get_gstack_home() / "sessions"
    sessions_dir.mkdir(parents=True, exist_ok=True)
    return sessions_dir


# ============ 会话管理 ============
def get_session_id() -> str:
    """获取当前会话 ID (基于进程ID+时间戳)"""
    return f"{os.getpid()}-{int(datetime.now().timestamp())}"


def touch_session() -> None:
    """标记当前会话活跃 (用于并发会话计数)"""
    sessions_dir = _get_sessions_dir()
    session_file = sessions_dir / str(os.getpid())
    session_file.touch(exist_ok=True)


def cleanup_old_sessions(max_age_minutes: int = 120) -> int:
    """清理过期的会话标记文件"""
    sessions_dir = _get_sessions_dir()
    if not sessions_dir.exists():
        return 0

    now = datetime.now().timestamp()
    max_age_seconds = max_age_minutes * 60
    cleaned = 0

    for f in sessions_dir.iterdir():
        if f.is_file():
            try:
                mtime = f.stat().st_mtime
                if now - mtime > max_age_seconds:
                    f.unlink()
                    cleaned += 1
            except OSError:
                pass
    return cleaned


def get_active_session_count() -> int:
    """获取活跃会话数"""
    cleanup_old_sessions()
    sessions_dir = _get_sessions_dir()
    if not sessions_dir.exists():
        return 0
    return sum(1 for f in sessions_dir.iterdir() if f.is_file())


# ============ 时间线记录 ============
def log_timeline_event(
    skill: str,
    event: str,
    branch: str = "unknown",
    outcome: str = "",
    duration_s: int = 0,
    metadata: dict[str, Any] | None = None,
) -> None:
    """记录时间线事件 (本地存储，不上传)"""
    project_dir = _get_project_dir()
    timeline_file = project_dir / "timeline.jsonl"

    entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "skill": skill,
        "event": event,
        "branch": branch,
        "outcome": outcome,
        "duration_s": duration_s,
        "session": get_session_id(),
        **(metadata or {}),
    }

    with open(timeline_file, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def get_recent_timeline_events(limit: int = 20) -> list[dict[str, Any]]:
    """获取最近的时间线事件"""
    project_dir = _get_project_dir()
    timeline_file = project_dir / "timeline.jsonl"

    if not timeline_file.exists():
        return []

    try:
        with open(timeline_file, "r", encoding="utf-8") as f:
            lines = f.readlines()
        events = [json.loads(line) for line in lines if line.strip()]
        return events[-limit:]
    except (json.JSONDecodeError, OSError):
        return []


def get_last_session_info(branch: str | None = None) -> dict[str, Any] | None:
    """获取最后一次会话信息"""
    events = get_recent_timeline_events(limit=50)

    # 按 session 去重，找最后一次 completed
    seen_sessions = set()
    for event in reversed(events):
        session_id = event.get("session", "")
        if branch and event.get("branch") != branch:
            continue
        if event.get("event") == "completed" and session_id not in seen_sessions:
            return event
        seen_sessions.add(session_id)
    return None


# ============ 技能使用记录 ============
def log_skill_usage(
    skill: str,
    outcome: str = "success",
    duration_s: int = 0,
    metadata: dict[str, Any] | None = None,
) -> None:
    """记录技能使用情况"""
    analytics_dir = _get_analytics_dir()
    usage_file = analytics_dir / "skill-usage.jsonl"

    entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "skill": skill,
        "repo": "moxishenghua",
        "outcome": outcome,
        "duration_s": duration_s,
        "session": get_session_id(),
        **(metadata or {}),
    }

    with open(usage_file, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def get_skill_usage_stats(days: int = 7) -> dict[str, Any]:
    """获取技能使用统计"""
    analytics_dir = _get_analytics_dir()
    usage_file = analytics_dir / "skill-usage.jsonl"

    if not usage_file.exists():
        return {"total": 0, "by_skill": {}, "by_outcome": {}}

    stats = {"total": 0, "by_skill": {}, "by_outcome": {}}
    cutoff = datetime.now(timezone.utc).timestamp() - (days * 24 * 3600)

    try:
        with open(usage_file, "r", encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                entry = json.loads(line)
                entry_ts = datetime.fromisoformat(entry["ts"].replace("Z", "+00:00")).timestamp()
                if entry_ts < cutoff:
                    continue

                stats["total"] += 1
                skill = entry.get("skill", "unknown")
                outcome = entry.get("outcome", "unknown")

                stats["by_skill"][skill] = stats["by_skill"].get(skill, 0) + 1
                stats["by_outcome"][outcome] = stats["by_outcome"].get(outcome, 0) + 1
    except (json.JSONDecodeError, OSError):
        pass

    return stats


# ============ 学习记录 ============
def log_learning(
    skill: str,
    insight_type: str,
    key: str,
    insight: str,
    confidence: int = 8,
    source: str = "observed",
) -> None:
    """
    记录操作性学习发现

    Args:
        skill: 相关技能名称
        insight_type: 学习类型 (operational, pattern, fix)
        key: 简短标识符
        insight: 详细描述
        confidence: 置信度 1-10
        source: 来源 (observed, learned, discovered)
    """
    project_dir = _get_project_dir()
    learnings_file = project_dir / "learnings.jsonl"

    entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "skill": skill,
        "type": insight_type,
        "key": key,
        "insight": insight,
        "confidence": confidence,
        "source": source,
        "session": get_session_id(),
    }

    with open(learnings_file, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def search_learnings(
    query: str = "",
    skill: str | None = None,
    limit: int = 10,
) -> list[dict[str, Any]]:
    """搜索学习记录"""
    project_dir = _get_project_dir()
    learnings_file = project_dir / "learnings.jsonl"

    if not learnings_file.exists():
        return []

    results = []
    query_lower = query.lower()

    try:
        with open(learnings_file, "r", encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                entry = json.loads(line)

                # 过滤
                if skill and entry.get("skill") != skill:
                    continue
                if query and query_lower not in json.dumps(entry, ensure_ascii=False).lower():
                    continue

                results.append(entry)
    except (json.JSONDecodeError, OSError):
        pass

    # 按置信度和时间排序
    results.sort(key=lambda x: (x.get("confidence", 0), x.get("ts", "")), reverse=True)
    return results[:limit]


def get_recent_learnings(skill: str | None = None, limit: int = 5) -> list[dict[str, Any]]:
    """获取最近的学习记录"""
    project_dir = _get_project_dir()
    learnings_file = project_dir / "learnings.jsonl"

    if not learnings_file.exists():
        return []

    entries = []
    try:
        with open(learnings_file, "r", encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                entry = json.loads(line)
                if skill and entry.get("skill") != skill:
                    continue
                entries.append(entry)
    except (json.JSONDecodeError, OSError):
        pass

    # 按时间倒序
    entries.sort(key=lambda x: x.get("ts", ""), reverse=True)
    return entries[:limit]


# ============ 项目记忆汇总 ============
def get_project_memory_summary() -> dict[str, Any]:
    """获取项目记忆汇总 (用于会话恢复)"""
    project_dir = _get_project_dir()

    # 读取时间线最新事件
    recent_events = get_recent_timeline_events(limit=10)

    # 读取最近学习
    recent_learnings = get_recent_learnings(limit=5)

    # 读取技能统计
    skill_stats = get_skill_usage_stats(days=30)

    # 尝试读取最近一次检查点
    checkpoints_dir = project_dir / "checkpoints"
    latest_checkpoint = None
    if checkpoints_dir.exists():
        checkpoint_files = sorted(checkpoints_dir.glob("*.md"), key=lambda x: x.stat().st_mtime, reverse=True)
        if checkpoint_files:
            latest_checkpoint = str(checkpoint_files[0])

    # 读取 CEO 计划
    ceo_plans_dir = project_dir / "ceo-plans"
    latest_ceo_plan = None
    if ceo_plans_dir.exists():
        plan_files = sorted(ceo_plans_dir.glob("*.md"), key=lambda x: x.stat().st_mtime, reverse=True)
        if plan_files:
            latest_ceo_plan = str(plan_files[0])

    return {
        "project": "moxishenghua",
        "last_session": get_last_session_info(),
        "recent_events": recent_events,
        "recent_learnings": recent_learnings,
        "skill_stats": skill_stats,
        "latest_checkpoint": latest_checkpoint,
        "latest_ceo_plan": latest_ceo_plan,
        "active_sessions": get_active_session_count(),
    }


def print_welcome_back_message() -> str:
    """打印欢迎回来消息 (供 CLI 使用)"""
    summary = get_project_memory_summary()

    lines = []
    lines.append(f"Welcome back to 墨戏生花 (moxishenghua)")

    last_session = summary.get("last_session")
    if last_session:
        skill = last_session.get("skill", "unknown")
        outcome = last_session.get("outcome", "unknown")
        branch = last_session.get("branch", "unknown")
        lines.append(f"Last session: /{skill} ({outcome}) on {branch}")

    # 显示最近学习
    learnings = summary.get("recent_learnings", [])
    if learnings:
        lines.append(f"\nRecent learnings ({len(learnings)} loaded):")
        for entry in learnings[:3]:
            lines.append(f"  - [{entry.get('skill')}] {entry.get('key')}: {entry.get('insight', '')[:60]}...")

    # 显示活跃会话
    active = summary.get("active_sessions", 0)
    if active > 1:
        lines.append(f"\nNote: {active} active sessions (including this one)")

    return "\n".join(lines)


# ============ 装饰器 (便捷使用) ============
def track_skill(skill_name: str):
    """装饰器：自动记录技能使用情况"""
    import functools
    import time

    def decorator(func):
        @functools.wraps(func)
        async def async_wrapper(*args, **kwargs):
            touch_session()
            start = time.time()
            outcome = "success"
            try:
                result = await func(*args, **kwargs)
                return result
            except Exception as e:
                outcome = f"error: {type(e).__name__}"
                raise
            finally:
                duration = int(time.time() - start)
                log_skill_usage(skill_name, outcome, duration)
                log_timeline_event(skill_name, "completed", outcome=outcome, duration_s=duration)

        @functools.wraps(func)
        def sync_wrapper(*args, **kwargs):
            touch_session()
            start = time.time()
            outcome = "success"
            try:
                result = func(*args, **kwargs)
                return result
            except Exception as e:
                outcome = f"error: {type(e).__name__}"
                raise
            finally:
                duration = int(time.time() - start)
                log_skill_usage(skill_name, outcome, duration)
                log_timeline_event(skill_name, "completed", outcome=outcome, duration_s=duration)

        # 根据原函数类型返回对应的 wrapper
        import inspect
        if inspect.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper
    return decorator
