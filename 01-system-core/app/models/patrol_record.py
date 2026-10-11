"""
巡查记录表模型
"""
import uuid
from datetime import datetime
from sqlalchemy import Column, String, Text, DateTime, ForeignKey

from app.database import Base


class PatrolRecord(Base):
    __tablename__ = "patrol_record"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    type = Column(String(30), nullable=False, comment="异常类型: timeout/stuck/orphan/rework_overflow/score_drop")
    severity = Column(String(10), nullable=False, comment="严重级别: warning/critical")
    sub_task_id = Column(String(36), ForeignKey("sub_task.id"), nullable=True, index=True, comment="关联子任务")
    agent_id = Column(String(36), ForeignKey("agent.id"), nullable=True, comment="关联 Agent")
    description = Column(Text, nullable=False, comment="异常描述")
    action_taken = Column(Text, default="", comment="采取的行动")
    status = Column(String(20), default="open", index=True, comment="状态: open/resolved/ignored")
    created_at = Column(DateTime, default=datetime.now, comment="发现时间")
    resolved_at = Column(DateTime, nullable=True, comment="解决时间")
