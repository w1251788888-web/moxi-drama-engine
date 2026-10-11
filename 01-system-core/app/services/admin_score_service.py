"""
管理端积分写操作服务
"""
from sqlalchemy.orm import Session

from app.models.agent import Agent
from app.services import reward_service


class AdminScoreWriteError(ValueError):
    """管理端积分写操作通用错误"""


def adjust_score(
    db: Session,
    agent_id: str,
    score_delta: int,
    reason: str,
    sub_task_id: str = None,
) -> dict:
    """管理员手动调分，并返回最新总分"""
    normalized_reason = (reason or "").strip()
    final_reason = f"[管理端调分] {normalized_reason}"
    if score_delta == 0:
        raise AdminScoreWriteError("score_delta 不能为 0")
    if not normalized_reason:
        raise AdminScoreWriteError("reason 不能为空")
    if len(final_reason) > 100:
        raise AdminScoreWriteError("reason 长度不能超过 100 个字符")

    try:
        reward_log = reward_service.add_reward(
            db,
            agent_id=agent_id,
            reason=final_reason,
            score_delta=score_delta,
            sub_task_id=sub_task_id,
        )
    except ValueError as exc:
        raise AdminScoreWriteError(str(exc)) from exc

    agent = db.query(Agent).filter(Agent.id == agent_id).first()
    if not agent:
        raise AdminScoreWriteError(f"Agent {agent_id} 不存在")

    return {
        "id": reward_log.id,
        "agent_id": reward_log.agent_id,
        "sub_task_id": reward_log.sub_task_id,
        "reason": reward_log.reason,
        "score_delta": reward_log.score_delta,
        "created_at": reward_log.created_at,
        "current_total_score": int(agent.total_score or 0),
    }
