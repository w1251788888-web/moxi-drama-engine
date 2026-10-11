"""Database-backed Skill registry models."""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Index, Integer, String, Text

from app.database import Base


class SkillRegistry(Base):
    """Registered Skill catalog row synced from manifest or curated manually."""

    __tablename__ = "skill_registry"
    __table_args__ = (
        Index("idx_skill_registry_category_status", "category", "status"),
        Index("idx_skill_registry_enabled_status", "is_enabled", "status"),
        Index("idx_skill_registry_updated", "updated_at"),
    )

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String(160), unique=True, nullable=False, index=True)
    display_name = Column(String(200), default="")
    description = Column(Text, default="")
    source = Column(Text, default="")
    target = Column(Text, default="")
    upstream_repo = Column(String(120), default="")
    category = Column(String(80), default="", index=True)
    recommended_for_json = Column(Text, default="[]")
    why = Column(Text, default="")
    mode = Column(String(40), default="")
    status = Column(String(30), default="active", index=True)
    is_enabled = Column(Boolean, default=True, index=True)
    version = Column(Integer, default=1)
    manifest_hash = Column(String(64), default="", index=True)
    metadata_json = Column(Text, default="{}")
    synced_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)


class SkillBinding(Base):
    """Runtime binding from workflow/failure context to a Skill."""

    __tablename__ = "skill_binding"
    __table_args__ = (
        Index("idx_skill_binding_type_key", "binding_type", "binding_key", "is_enabled", "status"),
        Index("idx_skill_binding_skill", "skill_name", "is_enabled", "status"),
        Index("idx_skill_binding_priority", "priority"),
    )

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    skill_id = Column(String(36), index=True, default="")
    skill_name = Column(String(160), nullable=False, index=True)
    binding_type = Column(String(60), nullable=False, index=True)
    binding_key = Column(String(200), default="", index=True)
    priority = Column(Integer, default=100)
    config_json = Column(Text, default="{}")
    metadata_json = Column(Text, default="{}")
    status = Column(String(30), default="active", index=True)
    is_enabled = Column(Boolean, default=True, index=True)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)


class SkillInvocation(Base):
    """Audit trail for each Skill invocation request/result."""

    __tablename__ = "skill_invocation"
    __table_args__ = (
        Index("idx_skill_invocation_skill_created", "skill_name", "created_at"),
        Index("idx_skill_invocation_status_created", "status", "created_at"),
        Index("idx_skill_invocation_context", "context", "failure_type"),
    )

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    skill_id = Column(String(36), index=True, default="")
    skill_name = Column(String(160), nullable=False, index=True)
    binding_id = Column(String(36), index=True, default="")
    actor_type = Column(String(40), default="system", index=True)
    actor_id = Column(String(120), default="", index=True)
    context = Column(String(120), default="general", index=True)
    failure_type = Column(String(120), default="", index=True)
    status = Column(String(30), default="started", index=True)
    input_summary = Column(Text, default="")
    output_summary = Column(Text, default="")
    metadata_json = Column(Text, default="{}")
    started_at = Column(DateTime, default=datetime.now)
    finished_at = Column(DateTime, nullable=True)
    duration_ms = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)


class SkillArtifact(Base):
    """Persisted artifact emitted by a Skill invocation."""

    __tablename__ = "skill_artifact"
    __table_args__ = (
        Index("idx_skill_artifact_invocation", "invocation_id", "created_at"),
        Index("idx_skill_artifact_skill", "skill_name", "artifact_type"),
    )

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    invocation_id = Column(String(36), nullable=False, index=True)
    skill_id = Column(String(36), index=True, default="")
    skill_name = Column(String(160), nullable=False, index=True)
    artifact_type = Column(String(80), default="text", index=True)
    title = Column(String(300), default="")
    content = Column(Text, default="")
    path = Column(Text, default="")
    metadata_json = Column(Text, default="{}")
    created_at = Column(DateTime, default=datetime.now)


class SkillQualityFeedback(Base):
    """Human or system quality feedback for a Skill invocation."""

    __tablename__ = "skill_quality_feedback"
    __table_args__ = (
        Index("idx_skill_quality_invocation", "invocation_id", "created_at"),
        Index("idx_skill_quality_skill", "skill_name", "verdict"),
    )

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    invocation_id = Column(String(36), nullable=False, index=True)
    skill_id = Column(String(36), index=True, default="")
    skill_name = Column(String(160), nullable=False, index=True)
    score = Column(Integer, default=0)
    verdict = Column(String(40), default="pending_review", index=True)
    reviewer_type = Column(String(40), default="admin", index=True)
    reviewer_id = Column(String(120), default="", index=True)
    notes = Column(Text, default="")
    metadata_json = Column(Text, default="{}")
    created_at = Column(DateTime, default=datetime.now)
