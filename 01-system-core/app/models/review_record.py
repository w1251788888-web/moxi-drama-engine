"""
审查记录表模型
"""
import uuid
from datetime import datetime
from sqlalchemy import Column, String, Text, Integer, DateTime, ForeignKey

from app.database import Base


class ReviewRecord(Base):
    __tablename__ = "review_record"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    sub_task_id = Column(String(36), ForeignKey("sub_task.id"), nullable=False, index=True, comment="关联子任务")
    reviewer_agent = Column(String(36), ForeignKey("agent.id"), nullable=False, comment="审查 Agent")
    round = Column(Integer, nullable=False, comment="第几轮审查")
    result = Column(String(20), nullable=False, comment="结果: approved/rejected")
    score = Column(Integer, nullable=False, comment="评分 1-5")
    issues = Column(Text, default="", comment="问题描述（驳回时必填）")
    comment = Column(Text, default="", comment="审查意见")
    rework_agent = Column(String(36), ForeignKey("agent.id"), nullable=True, comment="返工指派 Agent")
    created_at = Column(DateTime, default=datetime.now, comment="审查时间")
