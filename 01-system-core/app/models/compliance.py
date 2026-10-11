"""Content compliance review models."""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Column, DateTime, Float, Index, Integer, String, Text

from app.database import Base


class ComplianceRuleSet(Base):
    __tablename__ = "compliance_rule_set"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String(160), nullable=False)
    version = Column(String(40), default="v1")
    source = Column(String(300), default="")
    status = Column(String(30), default="active", index=True)
    rules_json = Column(Text, default="[]")
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)


class ComplianceScan(Base):
    __tablename__ = "compliance_scan"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id = Column(String(36), nullable=False, index=True)
    episode_number = Column(Integer, default=0, index=True)
    content_version_id = Column(String(36), default="", index=True)
    content_hash = Column(String(64), default="", index=True)
    status = Column(String(30), default="completed", index=True)
    verdict = Column(String(30), default="pass", index=True)
    summary = Column(Text, default="")
    metadata_json = Column(Text, default="{}")
    created_at = Column(DateTime, default=datetime.now, index=True)

    __table_args__ = (
        Index("ix_compliance_scan_project_episode_created", "project_id", "episode_number", "created_at"),
    )


class ComplianceFinding(Base):
    __tablename__ = "compliance_finding"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    scan_id = Column(String(36), nullable=False, index=True)
    project_id = Column(String(36), nullable=False, index=True)
    rule_id = Column(String(80), default="", index=True)
    severity = Column(String(30), default="warning", index=True)
    category = Column(String(120), default="")
    episode_number = Column(Integer, default=0, index=True)
    scene_number = Column(Integer, default=0, index=True)
    start_offset = Column(Integer, default=0)
    end_offset = Column(Integer, default=0)
    quote = Column(Text, default="")
    reason = Column(Text, default="")
    suggestion = Column(Text, default="")
    confidence = Column(Float, default=0.5)
    content_version_id = Column(String(36), default="", index=True)
    content_hash = Column(String(64), default="", index=True)
    status = Column(String(30), default="open", index=True)
    human_decision = Column(String(40), default="")
    human_note = Column(Text, default="")
    decided_by = Column(String(120), default="")
    decided_at = Column(DateTime, nullable=True)
    metadata_json = Column(Text, default="{}")
    created_at = Column(DateTime, default=datetime.now, index=True)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    __table_args__ = (
        Index("ix_compliance_finding_project_episode_status", "project_id", "episode_number", "status"),
    )


class CompliancePatch(Base):
    __tablename__ = "compliance_patch"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    finding_id = Column(String(36), nullable=False, index=True)
    project_id = Column(String(36), nullable=False, index=True)
    before_text = Column(Text, default="")
    after_text = Column(Text, default="")
    status = Column(String(30), default="proposed", index=True)
    created_by = Column(String(120), default="")
    created_at = Column(DateTime, default=datetime.now)
