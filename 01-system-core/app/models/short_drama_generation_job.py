"""Short drama script-scene generation background jobs."""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Index, Integer, String, Text

from app.database import Base


class ShortDramaGenerationJob(Base):
    __tablename__ = "short_drama_generation_job"

    id = Column(String(36), primary_key=True, default=lambda: uuid.uuid4().hex)
    project_id = Column(String(36), default="", index=True)
    owner_key = Column(String(64), default="", index=True)
    owner_is_admin = Column(Boolean, default=False)
    status = Column(String(24), default="pending", index=True)
    episode_no = Column(Integer, default=1)
    scene_no = Column(Integer, default=1)
    public_message = Column(Text, default="")
    public_progress = Column(Integer, default=0)
    request_json = Column(Text, default="")
    result_json = Column(Text, default="")
    internal_json = Column(Text, default="")
    error = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.now, index=True)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    __table_args__ = (
        Index("ix_short_drama_generation_job_owner_status", "owner_key", "status"),
        Index("ix_short_drama_generation_job_project_episode", "project_id", "episode_no"),
    )
