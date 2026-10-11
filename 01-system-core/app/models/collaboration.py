"""Project collaboration, invitation, permissions, and collaboration events."""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Column, DateTime, Index, Integer, String, Text

from app.database import Base


class ProjectMember(Base):
    __tablename__ = "project_member"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id = Column(String(36), nullable=False, index=True)
    access_key_id = Column(String(36), nullable=False, index=True)
    role = Column(String(40), default="co_writer", index=True)
    legal_identity = Column(String(60), default="commissioned_creator")
    display_name = Column(String(120), default="")
    status = Column(String(30), default="active", index=True)
    invited_by = Column(String(120), default="")
    accepted_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.now, index=True)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    __table_args__ = (
        Index("ix_project_member_project_access", "project_id", "access_key_id", unique=True),
        Index("ix_project_member_access_status", "access_key_id", "status"),
    )


class ProjectPermission(Base):
    __tablename__ = "project_permission"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id = Column(String(36), nullable=False, index=True)
    member_id = Column(String(36), nullable=False, index=True)
    scope_type = Column(String(40), default="project", index=True)
    scope_id = Column(String(120), default="", index=True)
    permission = Column(String(40), nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    __table_args__ = (
        Index("ix_project_permission_member_scope", "member_id", "scope_type", "scope_id"),
        Index("ix_project_permission_project_perm", "project_id", "permission"),
    )


class ProjectInvite(Base):
    __tablename__ = "project_invite"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id = Column(String(36), nullable=False, index=True)
    invite_token_hash = Column(String(64), nullable=False, unique=True, index=True)
    invite_token_prefix = Column(String(24), default="", index=True)
    target_contact = Column(String(160), default="", index=True)
    target_access_key_id = Column(String(36), default="", index=True)
    role = Column(String(40), default="co_writer")
    legal_identity = Column(String(60), default="commissioned_creator")
    scope_type = Column(String(40), default="project")
    scope_id = Column(String(120), default="")
    permissions_json = Column(Text, default="[]")
    allow_download = Column(Integer, default=0)
    status = Column(String(30), default="pending", index=True)
    invited_by = Column(String(120), default="")
    invited_by_name = Column(String(160), default="")
    note = Column(Text, default="")
    expires_at = Column(DateTime, nullable=True)
    accepted_by = Column(String(120), default="")
    accepted_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.now, index=True)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    __table_args__ = (
        Index("ix_project_invite_project_status", "project_id", "status", "created_at"),
        Index("ix_project_invite_target_status", "target_access_key_id", "status"),
    )


class CollabEvent(Base):
    __tablename__ = "collab_event"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id = Column(String(36), nullable=False, index=True)
    actor_type = Column(String(30), default="user", index=True)
    actor_id = Column(String(120), default="", index=True)
    actor_name = Column(String(160), default="")
    action = Column(String(60), nullable=False, index=True)
    scope_type = Column(String(40), default="project", index=True)
    scope_id = Column(String(120), default="", index=True)
    episode_number = Column(Integer, default=0, index=True)
    scene_number = Column(Integer, default=0, index=True)
    content_version_id = Column(String(36), default="", index=True)
    diff_stats_json = Column(Text, default="{}")
    metadata_json = Column(Text, default="{}")
    created_at = Column(DateTime, default=datetime.now, index=True)

    __table_args__ = (
        Index("ix_collab_event_project_action_created", "project_id", "action", "created_at"),
        Index("ix_collab_event_project_scope_created", "project_id", "scope_type", "scope_id", "created_at"),
    )


class ContributionAttribution(Base):
    __tablename__ = "contribution_attribution"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    project_id = Column(String(36), nullable=False, index=True)
    episode_number = Column(Integer, default=0, index=True)
    scene_number = Column(Integer, default=0, index=True)
    block_id = Column(String(120), default="", index=True)
    text_hash = Column(String(64), default="", index=True)
    origin_actor_id = Column(String(120), default="", index=True)
    origin_actor_type = Column(String(40), default="human")
    final_actor_id = Column(String(120), default="", index=True)
    contribution_score = Column(Integer, default=0)
    metadata_json = Column(Text, default="{}")
    created_at = Column(DateTime, default=datetime.now, index=True)
