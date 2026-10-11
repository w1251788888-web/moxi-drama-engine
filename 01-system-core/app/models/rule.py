"""
规则提示词表模型
"""
import uuid
from datetime import datetime
from sqlalchemy import Column, String, Text, DateTime, ForeignKey

from app.database import Base


class Rule(Base):
    __tablename__ = "rule"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    scope = Column(String(20), nullable=False, index=True, comment="作用域: global/task/sub_task")
    task_id = Column(String(36), ForeignKey("task.id"), nullable=True, index=True, comment="关联任务（task/sub_task 级别时填）")
    sub_task_id = Column(String(36), ForeignKey("sub_task.id"), nullable=True, comment="关联子任务（sub_task 级别时填）")
    rule_type = Column(String(30), nullable=False, default="core_rule", index=True, comment="规则类型: core_rule/material_guideline/suggestion")
    status = Column(String(20), nullable=False, default="active", index=True, comment="状态: active/candidate/archived")
    source = Column(String(30), nullable=False, default="manual", comment="来源: manual/project_review/crawler_summary")
    content = Column(Text, nullable=False, comment="规则提示词内容（Markdown）")
    created_at = Column(DateTime, default=datetime.now, comment="创建时间")
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now, comment="更新时间")
