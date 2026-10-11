"""
模块表模型
"""
import uuid
from datetime import datetime
from sqlalchemy import Column, String, Text, DateTime, ForeignKey, Index

from app.database import Base


class Module(Base):
    __tablename__ = "module"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    task_id = Column(String(36), ForeignKey("task.id"), nullable=False, comment="所属任务")
    name = Column(String(200), nullable=False, comment="模块名称")
    description = Column(Text, default="", comment="模块描述")
    created_at = Column(DateTime, default=datetime.now, comment="创建时间")

    __table_args__ = (
        Index("ix_module_task_created", "task_id", "created_at"),
        Index("ix_module_task_name", "task_id", "name"),
    )
