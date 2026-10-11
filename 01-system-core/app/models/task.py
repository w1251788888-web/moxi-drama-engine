"""
任务表模型
"""
import uuid
from datetime import datetime
from sqlalchemy import Column, String, Text, DateTime, Index, Integer

from app.database import Base


class Task(Base):
    __tablename__ = "task"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String(200), nullable=False, comment="任务名称")
    description = Column(Text, default="", comment="任务描述")
    type = Column(String(20), default="once", comment="任务类型: once/recurring")
    status = Column(String(20), default="planning", index=True, comment="状态: planning/active/in_progress/completed/archived")
    metadata_json = Column(Text, default="", comment="扩展元数据 JSON")
    metadata_version = Column(Integer, default=0, nullable=False, comment="metadata_json 乐观锁版本")
    created_at = Column(DateTime, default=datetime.now, comment="创建时间")
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now, comment="更新时间")

    __table_args__ = (
        Index("ix_task_status_created", "status", "created_at"),
        Index("ix_task_status_updated", "status", "updated_at"),
        Index("ix_task_type_created", "type", "created_at"),
    )
