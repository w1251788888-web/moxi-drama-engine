"""
奖励记录表模型
"""
import uuid
from datetime import datetime
from sqlalchemy import Column, String, Integer, DateTime, ForeignKey

from app.database import Base


class RewardLog(Base):
    __tablename__ = "reward_log"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    agent_id = Column(String(36), ForeignKey("agent.id"), nullable=False, index=True, comment="关联 Agent")
    sub_task_id = Column(String(36), ForeignKey("sub_task.id"), nullable=True, comment="关联子任务")
    reason = Column(String(100), nullable=False, comment="原因: 按时完成/验收高分/超时/返工 等")
    score_delta = Column(Integer, nullable=False, comment="分值变化（正加负扣）")
    created_at = Column(DateTime, default=datetime.now, comment="记录时间")
