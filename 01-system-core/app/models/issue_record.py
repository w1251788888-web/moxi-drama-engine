"""
问题清单记录表模型
"""
import uuid
from datetime import datetime
from sqlalchemy import Column, String, Text, DateTime, Integer, ForeignKey

from app.database import Base


class IssueRecord(Base):
    __tablename__ = "issue_record"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    task_id = Column(String(36), nullable=False, index=True, comment="来源任务")
    sub_task_id = Column(String(36), ForeignKey("sub_task.id"), nullable=True, index=True, comment="来源子任务")
    issue_key = Column(String(120), nullable=False, index=True, comment="归一化问题键")
    title = Column(String(200), nullable=False, comment="问题标题")
    category_path = Column(String(120), nullable=False, index=True, comment="分类路径")
    scope_level = Column(String(30), nullable=False, default="project_only", index=True, comment="作用域级别")
    status = Column(String(20), nullable=False, default="open", index=True, comment="状态: open/promoted/archived")
    severity = Column(String(20), nullable=False, default="medium", comment="严重程度")
    symptom = Column(Text, default="", comment="表征")
    root_cause = Column(Text, default="", comment="原因判断")
    evidence_json = Column(Text, default="[]", comment="证据 JSON")
    trigger_rounds_json = Column(Text, default="[]", comment="触发轮次 JSON")
    negative_prompt_hint = Column(Text, default="", comment="负经验提示")
    review_check_hint = Column(Text, default="", comment="评审检查提示")
    retrieval_hint_json = Column(Text, default="{}", comment="召回偏置提示 JSON")
    occurrence_count = Column(Integer, default=1, comment="累计出现次数")
    last_seen_at = Column(DateTime, default=datetime.now, comment="最近出现时间")
    created_at = Column(DateTime, default=datetime.now, comment="创建时间")
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now, comment="更新时间")
