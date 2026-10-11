"""Legal asset, rights materials, and package records."""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Column, DateTime, Index, Integer, String, Text

from app.database import Base


class RightsProfile(Base):
    __tablename__ = "rights_profile"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id = Column(String(36), nullable=False, unique=True, index=True)
    project_origin_type = Column(String(40), default="original")
    ai_assist_flag = Column(Integer, default=1)
    rights_status = Column(String(40), default="draft", index=True)
    rights_score = Column(Integer, default=0)
    metadata_json = Column(Text, default="{}")
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)


class CopyrightParty(Base):
    __tablename__ = "copyright_party"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id = Column(String(36), nullable=False, index=True)
    party_name = Column(String(160), nullable=False)
    party_type = Column(String(40), default="person")
    creative_role = Column(String(80), default="")
    legal_identity = Column(String(80), default="")
    rights_share = Column(String(80), default="")
    contact = Column(String(160), default="")
    metadata_json = Column(Text, default="{}")
    created_at = Column(DateTime, default=datetime.now)


class RightsSource(Base):
    __tablename__ = "rights_source"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id = Column(String(36), nullable=False, index=True)
    source_type = Column(String(60), default="original")
    title = Column(String(200), default="")
    rights_holder = Column(String(160), default="")
    license_scope = Column(String(300), default="")
    status = Column(String(40), default="declared", index=True)
    material_id = Column(String(36), default="", index=True)
    metadata_json = Column(Text, default="{}")
    created_at = Column(DateTime, default=datetime.now)


class LegalMaterial(Base):
    __tablename__ = "legal_material"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id = Column(String(36), nullable=False, index=True)
    material_type = Column(String(80), nullable=False, index=True)
    title = Column(String(200), default="")
    status = Column(String(40), default="missing", index=True)
    provider = Column(String(40), default="user")
    content_text = Column(Text, default="")
    file_path = Column(String(500), default="")
    file_hash = Column(String(64), default="")
    metadata_json = Column(Text, default="{}")
    created_at = Column(DateTime, default=datetime.now, index=True)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    __table_args__ = (
        Index("ix_legal_material_project_type_status", "project_id", "material_type", "status"),
    )


class RightsCheckResult(Base):
    __tablename__ = "rights_check_result"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id = Column(String(36), nullable=False, index=True)
    check_type = Column(String(80), default="export_gate", index=True)
    status = Column(String(40), default="warning", index=True)
    score = Column(Integer, default=0)
    blockers_json = Column(Text, default="[]")
    warnings_json = Column(Text, default="[]")
    metadata_json = Column(Text, default="{}")
    created_at = Column(DateTime, default=datetime.now, index=True)


class EvidencePackage(Base):
    __tablename__ = "evidence_package"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id = Column(String(36), nullable=False, index=True)
    package_type = Column(String(60), default="legal", index=True)
    status = Column(String(40), default="generated", index=True)
    package_path = Column(String(500), default="")
    manifest_hash = Column(String(64), default="")
    manifest_json = Column(Text, default="{}")
    created_by = Column(String(120), default="")
    created_at = Column(DateTime, default=datetime.now, index=True)


class ExportRecord(Base):
    __tablename__ = "export_record"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id = Column(String(36), nullable=False, index=True)
    export_type = Column(String(60), default="draft", index=True)
    format = Column(String(30), default="")
    status = Column(String(40), default="created", index=True)
    file_path = Column(String(500), default="")
    file_hash = Column(String(64), default="")
    gate_result_id = Column(String(36), default="", index=True)
    metadata_json = Column(Text, default="{}")
    created_by = Column(String(120), default="")
    created_at = Column(DateTime, default=datetime.now, index=True)
