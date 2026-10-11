"""Evidence and approval records shared by collaboration, compliance, and legal assets."""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Column, DateTime, Index, String, Text

from app.database import Base


class EvidenceEvent(Base):
    __tablename__ = "evidence_event"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id = Column(String(36), nullable=False, index=True)
    actor_type = Column(String(30), default="user", index=True)
    actor_id = Column(String(120), default="", index=True)
    actor_name = Column(String(160), default="")
    event_type = Column(String(80), nullable=False, index=True)
    target_type = Column(String(80), default="", index=True)
    target_id = Column(String(120), default="", index=True)
    content_version_id = Column(String(36), default="", index=True)
    content_hash = Column(String(64), default="", index=True)
    summary = Column(String(500), default="")
    metadata_json = Column(Text, default="{}")
    created_at = Column(DateTime, default=datetime.now, index=True)

    __table_args__ = (
        Index("ix_evidence_project_event_created", "project_id", "event_type", "created_at"),
        Index("ix_evidence_project_target_created", "project_id", "target_type", "target_id", "created_at"),
    )


class ApprovalTask(Base):
    __tablename__ = "approval_task"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id = Column(String(36), nullable=False, index=True)
    task_type = Column(String(60), nullable=False, index=True)
    title = Column(String(200), nullable=False)
    description = Column(Text, default="")
    status = Column(String(30), default="pending", index=True)
    priority = Column(String(20), default="normal")
    scope_type = Column(String(40), default="project", index=True)
    scope_id = Column(String(120), default="", index=True)
    requester_id = Column(String(120), default="", index=True)
    requester_name = Column(String(160), default="")
    reviewer_id = Column(String(120), default="", index=True)
    reviewer_name = Column(String(160), default="")
    decision = Column(String(40), default="")
    decision_note = Column(Text, default="")
    metadata_json = Column(Text, default="{}")
    created_at = Column(DateTime, default=datetime.now, index=True)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)
    decided_at = Column(DateTime, nullable=True)

    __table_args__ = (
        Index("ix_approval_project_status_created", "project_id", "status", "created_at"),
        Index("ix_approval_project_type_status", "project_id", "task_type", "status"),
    )
