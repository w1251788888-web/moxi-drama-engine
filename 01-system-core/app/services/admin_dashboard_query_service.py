"""
管理端仪表盘查询服务
"""
from datetime import date, datetime as dt, timedelta

from sqlalchemy import asc, case, desc, func, or_
from sqlalchemy.orm import Session, aliased

from app.models.activity_log import ActivityLog
from app.models.agent import Agent
from app.models.request_log import RequestLog
from app.models.review_record import ReviewRecord
from app.models.reward_log import RewardLog
from app.models.sub_task import SubTask
from app.models.task import Task


TASK_STATUSES = ("planning", "active", "in_progress", "completed", "archived", "cancelled")
SUB_TASK_STATUSES = ("pending", "assigned", "in_progress", "review", "rework", "blocked", "done", "cancelled")
AGENT_STATUSES = ("active", "disabled")
AGENT_ROLES = ("planner", "executor", "reviewer", "patrol")
REVIEW_RESULTS = ("approved", "rejected")
REVIEW_WINDOW_DAYS = 7
OPEN_SUB_TASK_STATUSES = ("assigned", "in_progress", "review", "rework", "blocked")
DEFAULT_TREND_DAYS = 7
MAX_TREND_DAYS = 30


def get_dashboard_overview(db: Session) -> dict:
    """查询管理端仪表盘 Phase 1 概览统计"""
    now = dt.now()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    review_window_start = now - timedelta(days=REVIEW_WINDOW_DAYS)

    task_status_distribution = _count_by_column(db, Task.status, TASK_STATUSES)
    sub_task_status_distribution = _count_by_column(db, SubTask.status, SUB_TASK_STATUSES)
    agent_status_distribution = _count_by_column(db, Agent.status, AGENT_STATUSES)
    agent_role_distribution = _count_by_column(db, Agent.role, AGENT_ROLES)
    review_result_distribution = _count_by_column(
        db,
        ReviewRecord.result,
        REVIEW_RESULTS,
        ReviewRecord.created_at >= review_window_start,
    )

    today_completed_sub_task_count = _int_or_zero(
        db.query(func.count(SubTask.id))
        .filter(SubTask.completed_at >= today_start)
        .scalar()
    )

    today_review_row = (
        db.query(
            func.count(ReviewRecord.id).label("today_review_count"),
            func.coalesce(
                func.sum(case((ReviewRecord.result == "rejected", 1), else_=0)),
                0,
            ).label("today_rejected_review_count"),
        )
        .filter(ReviewRecord.created_at >= today_start)
        .first()
    )
    today_review_mapping = today_review_row._mapping
    today_review_count = _int_or_zero(today_review_mapping["today_review_count"])
    today_rejected_review_count = _int_or_zero(today_review_mapping["today_rejected_review_count"])
    today_reject_rate = round(
        (today_rejected_review_count / today_review_count * 100) if today_review_count else 0.0,
        2,
    )

    today_net_score_delta = _int_or_zero(
        db.query(func.coalesce(func.sum(RewardLog.score_delta), 0))
        .filter(RewardLog.created_at >= today_start)
        .scalar()
    )

    return {
        "generated_at": now,
        "review_window_days": REVIEW_WINDOW_DAYS,
        "core_cards": {
            "open_task_count": sum(
                task_status_distribution[status]
                for status in ("planning", "active", "in_progress")
            ),
            "active_sub_task_count": sum(
                sub_task_status_distribution[status]
                for status in ("assigned", "in_progress", "review", "rework", "blocked")
            ),
            "review_queue_count": sub_task_status_distribution["review"],
            "blocked_sub_task_count": sub_task_status_distribution["blocked"],
            "active_agent_count": agent_status_distribution["active"],
            "today_completed_sub_task_count": today_completed_sub_task_count,
        },
        "secondary_cards": {
            "disabled_agent_count": agent_status_distribution["disabled"],
            "today_review_count": today_review_count,
            "today_rejected_review_count": today_rejected_review_count,
            "today_reject_rate": today_reject_rate,
            "today_net_score_delta": today_net_score_delta,
        },
        "distributions": {
            "task_status_distribution": task_status_distribution,
            "sub_task_status_distribution": sub_task_status_distribution,
            "agent_status_distribution": agent_status_distribution,
            "agent_role_distribution": agent_role_distribution,
            "review_result_distribution_7d": review_result_distribution,
        },
    }


def get_dashboard_highlights(
    db: Session,
    limit: int = 5,
    inactive_hours: int = 24,
) -> dict:
    """查询管理端仪表盘 Phase 2 高亮面板"""
    now = dt.now()
    inactive_cutoff = now - timedelta(hours=inactive_hours)

    request_stats = _build_agent_last_request_subquery(db)
    activity_stats = _build_agent_last_activity_subquery(db)
    workload_stats = _build_agent_open_workload_subquery(db)
    last_seen_expr = _build_agent_last_seen_expr(
        request_stats.c.last_request_at,
        activity_stats.c.last_activity_at,
    )

    return {
        "generated_at": now,
        "limit": limit,
        "inactive_hours": inactive_hours,
        "blocked_sub_tasks": _list_sub_task_highlights(db, "blocked", limit),
        "pending_review_sub_tasks": _list_sub_task_highlights(db, "review", limit),
        "busy_agents": _list_busy_agents(db, limit, workload_stats, request_stats, activity_stats),
        "low_activity_agents": _list_low_activity_agents(
            db,
            limit,
            inactive_cutoff,
            workload_stats,
            request_stats,
            activity_stats,
            last_seen_expr,
        ),
        "recent_reviews": _list_recent_reviews(db, limit),
    }


def get_dashboard_trends(db: Session, days: int = DEFAULT_TREND_DAYS) -> dict:
    """查询管理端仪表盘 Phase 3 趋势统计"""
    actual_days = max(1, min(days, MAX_TREND_DAYS))
    start_dt, end_dt, dates = _build_trend_window(actual_days)

    return {
        "generated_at": dt.now(),
        "days": actual_days,
        "start_date": dates[0].isoformat(),
        "end_date": dates[-1].isoformat(),
        "sub_task_created_trend": _build_count_trend(
            dates,
            _query_count_trend_rows(db, SubTask.id, SubTask.created_at, start_dt, end_dt),
        ),
        "sub_task_completed_trend": _build_count_trend(
            dates,
            _query_count_trend_rows(db, SubTask.id, SubTask.completed_at, start_dt, end_dt),
        ),
        "review_trend": _build_review_trend(
            dates,
            _query_review_trend_rows(db, start_dt, end_dt),
        ),
        "score_delta_trend": _build_score_trend(
            dates,
            _query_score_trend_rows(db, start_dt, end_dt),
        ),
        "request_trend": _build_count_trend(
            dates,
            _query_count_trend_rows(db, RequestLog.id, RequestLog.timestamp, start_dt, end_dt),
        ),
        "activity_trend": _build_count_trend(
            dates,
            _query_count_trend_rows(db, ActivityLog.id, ActivityLog.created_at, start_dt, end_dt),
        ),
    }


def _count_by_column(db: Session, column, allowed_values: tuple[str, ...], *filters) -> dict:
    """按固定枚举字段分组计数，并补齐缺失枚举值"""
    counts = {value: 0 for value in allowed_values}

    query = db.query(column.label("value"), func.count().label("count"))
    if filters:
        query = query.filter(*filters)

    rows = query.group_by(column).all()
    for row in rows:
        if row.value in counts:
            counts[row.value] = _int_or_zero(row.count)

    return counts


def _int_or_zero(value) -> int:
    """把可空聚合值安全转成 int"""
    return int(value or 0)


def _build_trend_window(days: int) -> tuple[dt, dt, list[date]]:
    """构建趋势时间窗口和连续日期桶"""
    today = dt.now().date()
    start_date = today - timedelta(days=days - 1)
    dates = [start_date + timedelta(days=index) for index in range(days)]
    start_dt = dt.combine(start_date, dt.min.time())
    end_dt = dt.combine(today + timedelta(days=1), dt.min.time())
    return start_dt, end_dt, dates


def _query_count_trend_rows(db: Session, id_column, datetime_column, start_dt: dt, end_dt: dt):
    """按日期查询单指标数量趋势"""
    return (
        db.query(
            func.date(datetime_column).label("day"),
            func.count(id_column).label("count"),
        )
        .filter(datetime_column.isnot(None), datetime_column >= start_dt, datetime_column < end_dt)
        .group_by(func.date(datetime_column))
        .all()
    )


def _query_review_trend_rows(db: Session, start_dt: dt, end_dt: dt):
    """按日期查询审查趋势"""
    return (
        db.query(
            func.date(ReviewRecord.created_at).label("day"),
            func.count(ReviewRecord.id).label("total"),
            func.coalesce(
                func.sum(case((ReviewRecord.result == "approved", 1), else_=0)),
                0,
            ).label("approved"),
            func.coalesce(
                func.sum(case((ReviewRecord.result == "rejected", 1), else_=0)),
                0,
            ).label("rejected"),
        )
        .filter(ReviewRecord.created_at >= start_dt, ReviewRecord.created_at < end_dt)
        .group_by(func.date(ReviewRecord.created_at))
        .all()
    )


def _query_score_trend_rows(db: Session, start_dt: dt, end_dt: dt):
    """按日期查询积分变化趋势"""
    return (
        db.query(
            func.date(RewardLog.created_at).label("day"),
            func.coalesce(
                func.sum(case((RewardLog.score_delta > 0, RewardLog.score_delta), else_=0)),
                0,
            ).label("positive_score_delta"),
            func.coalesce(
                func.sum(case((RewardLog.score_delta < 0, RewardLog.score_delta), else_=0)),
                0,
            ).label("negative_score_delta"),
            func.coalesce(func.sum(RewardLog.score_delta), 0).label("net_score_delta"),
        )
        .filter(RewardLog.created_at >= start_dt, RewardLog.created_at < end_dt)
        .group_by(func.date(RewardLog.created_at))
        .all()
    )


def _build_count_trend(dates: list[date], rows) -> list[dict]:
    """把查询行补成连续计数趋势"""
    row_map = {str(row.day): _int_or_zero(row.count) for row in rows}
    return [
        {
            "date": day.isoformat(),
            "count": row_map.get(day.isoformat(), 0),
        }
        for day in dates
    ]


def _build_review_trend(dates: list[date], rows) -> list[dict]:
    """把查询行补成连续审查趋势"""
    row_map = {
        str(row.day): {
            "total": _int_or_zero(row.total),
            "approved": _int_or_zero(row.approved),
            "rejected": _int_or_zero(row.rejected),
        }
        for row in rows
    }
    return [
        {
            "date": day.isoformat(),
            "total": row_map.get(day.isoformat(), {}).get("total", 0),
            "approved": row_map.get(day.isoformat(), {}).get("approved", 0),
            "rejected": row_map.get(day.isoformat(), {}).get("rejected", 0),
        }
        for day in dates
    ]


def _build_score_trend(dates: list[date], rows) -> list[dict]:
    """把查询行补成连续积分趋势"""
    row_map = {
        str(row.day): {
            "positive_score_delta": _int_or_zero(row.positive_score_delta),
            "negative_score_delta": _int_or_zero(row.negative_score_delta),
            "net_score_delta": _int_or_zero(row.net_score_delta),
        }
        for row in rows
    }
    return [
        {
            "date": day.isoformat(),
            "positive_score_delta": row_map.get(day.isoformat(), {}).get("positive_score_delta", 0),
            "negative_score_delta": row_map.get(day.isoformat(), {}).get("negative_score_delta", 0),
            "net_score_delta": row_map.get(day.isoformat(), {}).get("net_score_delta", 0),
        }
        for day in dates
    ]


def _build_agent_last_request_subquery(db: Session):
    """按 Agent 聚合最近请求时间"""
    return (
        db.query(
            RequestLog.agent_id.label("agent_id"),
            func.max(RequestLog.timestamp).label("last_request_at"),
        )
        .filter(RequestLog.agent_id.isnot(None))
        .group_by(RequestLog.agent_id)
        .subquery()
    )


def _build_agent_last_activity_subquery(db: Session):
    """按 Agent 聚合最近活动时间"""
    return (
        db.query(
            ActivityLog.agent_id.label("agent_id"),
            func.max(ActivityLog.created_at).label("last_activity_at"),
        )
        .filter(ActivityLog.agent_id.isnot(None))
        .group_by(ActivityLog.agent_id)
        .subquery()
    )


def _build_agent_open_workload_subquery(db: Session):
    """按 Agent 聚合开放子任务数量"""
    return (
        db.query(
            SubTask.assigned_agent.label("agent_id"),
            func.coalesce(
                func.sum(case((SubTask.status.in_(OPEN_SUB_TASK_STATUSES), 1), else_=0)),
                0,
            ).label("open_sub_task_count"),
        )
        .filter(SubTask.assigned_agent.isnot(None))
        .group_by(SubTask.assigned_agent)
        .subquery()
    )


def _build_agent_last_seen_expr(last_request_col, last_activity_col):
    """组合最近请求和最近活动时间，得到 Agent 的最近活跃时间"""
    return case(
        (last_request_col.is_(None), last_activity_col),
        (last_activity_col.is_(None), last_request_col),
        (last_request_col >= last_activity_col, last_request_col),
        else_=last_activity_col,
    )


def _list_sub_task_highlights(db: Session, status: str, limit: int) -> list[dict]:
    """查询 blocked/review 高亮子任务"""
    assigned_agent = aliased(Agent)
    rows = (
        db.query(
            SubTask.id.label("id"),
            Task.id.label("task_id"),
            Task.name.label("task_name"),
            SubTask.name.label("name"),
            SubTask.status.label("status"),
            SubTask.assigned_agent.label("assigned_agent"),
            assigned_agent.name.label("assigned_agent_name"),
            SubTask.updated_at.label("updated_at"),
            SubTask.rework_count.label("rework_count"),
        )
        .join(Task, Task.id == SubTask.task_id)
        .outerjoin(assigned_agent, assigned_agent.id == SubTask.assigned_agent)
        .filter(SubTask.status == status)
        .order_by(desc(SubTask.updated_at), desc(SubTask.id))
        .limit(limit)
        .all()
    )
    return [_serialize_sub_task_highlight_row(row) for row in rows]


def _list_busy_agents(db: Session, limit: int, workload_stats, request_stats, activity_stats) -> list[dict]:
    """查询当前最忙的 Agent 列表"""
    open_count = func.coalesce(workload_stats.c.open_sub_task_count, 0)
    disabled_last = case((Agent.status == "disabled", 1), else_=0)

    rows = (
        db.query(
            Agent.id.label("id"),
            Agent.name.label("name"),
            Agent.role.label("role"),
            Agent.status.label("status"),
            Agent.total_score.label("total_score"),
            open_count.label("open_sub_task_count"),
            request_stats.c.last_request_at.label("last_request_at"),
            activity_stats.c.last_activity_at.label("last_activity_at"),
        )
        .outerjoin(workload_stats, workload_stats.c.agent_id == Agent.id)
        .outerjoin(request_stats, request_stats.c.agent_id == Agent.id)
        .outerjoin(activity_stats, activity_stats.c.agent_id == Agent.id)
        .filter(open_count > 0)
        .order_by(
            desc(open_count),
            asc(disabled_last),
            desc(request_stats.c.last_request_at),
            desc(activity_stats.c.last_activity_at),
            asc(Agent.created_at),
        )
        .limit(limit)
        .all()
    )
    return [_serialize_agent_highlight_row(row) for row in rows]


def _list_low_activity_agents(
    db: Session,
    limit: int,
    inactive_cutoff: dt,
    workload_stats,
    request_stats,
    activity_stats,
    last_seen_expr,
) -> list[dict]:
    """查询长时间不活跃的 Agent 列表"""
    no_activity_first = case((last_seen_expr.is_(None), 0), else_=1)

    rows = (
        db.query(
            Agent.id.label("id"),
            Agent.name.label("name"),
            Agent.role.label("role"),
            Agent.status.label("status"),
            Agent.total_score.label("total_score"),
            func.coalesce(workload_stats.c.open_sub_task_count, 0).label("open_sub_task_count"),
            request_stats.c.last_request_at.label("last_request_at"),
            activity_stats.c.last_activity_at.label("last_activity_at"),
        )
        .outerjoin(workload_stats, workload_stats.c.agent_id == Agent.id)
        .outerjoin(request_stats, request_stats.c.agent_id == Agent.id)
        .outerjoin(activity_stats, activity_stats.c.agent_id == Agent.id)
        .filter(or_(last_seen_expr.is_(None), last_seen_expr < inactive_cutoff))
        .order_by(
            asc(no_activity_first),
            asc(last_seen_expr),
            asc(Agent.created_at),
        )
        .limit(limit)
        .all()
    )
    return [_serialize_agent_highlight_row(row) for row in rows]


def _list_recent_reviews(db: Session, limit: int) -> list[dict]:
    """查询最近审查记录"""
    reviewer_agent = aliased(Agent)
    rows = (
        db.query(
            ReviewRecord.id.label("id"),
            Task.id.label("task_id"),
            Task.name.label("task_name"),
            ReviewRecord.sub_task_id.label("sub_task_id"),
            SubTask.name.label("sub_task_name"),
            ReviewRecord.reviewer_agent.label("reviewer_agent"),
            reviewer_agent.name.label("reviewer_agent_name"),
            ReviewRecord.result.label("result"),
            ReviewRecord.score.label("score"),
            ReviewRecord.created_at.label("created_at"),
        )
        .join(SubTask, SubTask.id == ReviewRecord.sub_task_id)
        .join(Task, Task.id == SubTask.task_id)
        .outerjoin(reviewer_agent, reviewer_agent.id == ReviewRecord.reviewer_agent)
        .order_by(desc(ReviewRecord.created_at), desc(ReviewRecord.id))
        .limit(limit)
        .all()
    )
    return [_serialize_recent_review_row(row) for row in rows]


def _serialize_sub_task_highlight_row(row) -> dict:
    """序列化高亮子任务列表项"""
    mapping = row._mapping
    return {
        "id": mapping["id"],
        "task_id": mapping["task_id"],
        "task_name": mapping["task_name"],
        "name": mapping["name"],
        "status": mapping["status"],
        "assigned_agent": mapping["assigned_agent"],
        "assigned_agent_name": mapping["assigned_agent_name"],
        "updated_at": mapping["updated_at"],
        "rework_count": _int_or_zero(mapping["rework_count"]),
    }


def _serialize_agent_highlight_row(row) -> dict:
    """序列化高亮 Agent 列表项"""
    mapping = row._mapping
    return {
        "id": mapping["id"],
        "name": mapping["name"],
        "role": mapping["role"],
        "status": mapping["status"],
        "total_score": _int_or_zero(mapping["total_score"]),
        "open_sub_task_count": _int_or_zero(mapping["open_sub_task_count"]),
        "last_request_at": mapping["last_request_at"],
        "last_activity_at": mapping["last_activity_at"],
    }


def _serialize_recent_review_row(row) -> dict:
    """序列化最近审查列表项"""
    mapping = row._mapping
    return {
        "id": mapping["id"],
        "task_id": mapping["task_id"],
        "task_name": mapping["task_name"],
        "sub_task_id": mapping["sub_task_id"],
        "sub_task_name": mapping["sub_task_name"],
        "reviewer_agent": mapping["reviewer_agent"],
        "reviewer_agent_name": mapping["reviewer_agent_name"],
        "result": mapping["result"],
        "score": _int_or_zero(mapping["score"]),
        "created_at": mapping["created_at"],
    }
