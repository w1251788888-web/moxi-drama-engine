"""集纲生成后台任务表。

把原内存版任务表落库：重启不丢、可跨进程/多实例共享、按 owner(access_key) 隔离。
"""
import uuid
from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Integer, String, Text, Index

from app.database import Base


class OutlineEpisodeJob(Base):
    __tablename__ = "outline_episode_job"

    id = Column(String(36), primary_key=True, default=lambda: uuid.uuid4().hex, comment="任务ID(job_id)")
    owner_key = Column(String(64), default="", index=True, comment="发起者 access_key_id；管理员为空")
    owner_is_admin = Column(Boolean, default=False, comment="发起者是否管理员")
    status = Column(String(16), default="pending", index=True, comment="pending/running/done/error")
    progress_done = Column(Integer, default=0, comment="已完成集数")
    progress_total = Column(Integer, default=0, comment="目标集数")
    result_json = Column(Text, default="", comment="完成结果 JSON：episodes/prediction/fallback 等")
    error = Column(Text, default="", comment="失败原因")
    created_at = Column(DateTime, default=datetime.now, index=True, comment="创建时间")
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now, comment="更新时间")

    __table_args__ = (
        Index("ix_outline_job_owner_status", "owner_key", "status"),
    )
