"""场景视觉档案服务（简化版，不做 lock）"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from app.models.character_visual import SceneVisualBase
from app.schemas.character_visual import SceneVisualUpsert

logger = logging.getLogger(__name__)


def get_by_scene(db: Session, project_id: str, scene_id: str) -> Optional[SceneVisualBase]:
    return (
        db.query(SceneVisualBase)
        .filter(
            SceneVisualBase.project_id == project_id,
            SceneVisualBase.scene_id == scene_id,
        )
        .first()
    )


def list_by_project(db: Session, project_id: str, episode: Optional[int] = None) -> list[SceneVisualBase]:
    q = db.query(SceneVisualBase).filter(SceneVisualBase.project_id == project_id)
    if episode is not None:
        q = q.filter(SceneVisualBase.episode == episode)
    return q.order_by(SceneVisualBase.created_at.asc()).all()


def upsert(db: Session, payload: SceneVisualUpsert) -> SceneVisualBase:
    row = get_by_scene(db, payload.project_id, payload.scene_id)
    if not row:
        row = SceneVisualBase(
            id=str(uuid.uuid4()),
            project_id=payload.project_id,
            scene_id=payload.scene_id,
        )
        db.add(row)

    row.episode = payload.episode or row.episode or 0
    row.scene_name = payload.scene_name or row.scene_name
    row.environment = payload.environment or ""
    row.time_of_day = payload.time_of_day or ""
    row.lighting = payload.lighting or ""
    row.color_palette = payload.color_palette or ""
    row.props = payload.props or ""
    row.atmosphere = payload.atmosphere or ""
    row.updated_at = datetime.utcnow()

    db.commit()
    db.refresh(row)
    return row


def delete(db: Session, project_id: str, scene_id: str) -> bool:
    row = get_by_scene(db, project_id, scene_id)
    if not row:
        return False
    db.delete(row)
    db.commit()
    return True
