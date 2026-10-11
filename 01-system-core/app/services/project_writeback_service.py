"""Reviewer-approved project writeback helpers."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.models.project_v2 import Checkpoint, ContentVersion, Episode, ProjectV2, Scene
from app.models.review_record import ReviewRecord
from app.models.sub_task import SubTask


def _load_metadata(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except Exception:
        return {}
    return value if isinstance(value, dict) else {}


def _dump_metadata(metadata: dict[str, Any]) -> str:
    return json.dumps(metadata, ensure_ascii=False) if metadata else ""


def _remember_transaction_file(db: Session, path: Path) -> None:
    files = db.info.setdefault("project_writeback_files", [])
    if str(path) not in files:
        files.append(str(path))


def cleanup_project_writeback_files(db: Session) -> None:
    """删除本事务已写但未成功提交的写回文件。"""
    files = list(db.info.pop("project_writeback_files", []) or [])
    for raw_path in files:
        try:
            Path(raw_path).unlink(missing_ok=True)
        except Exception:
            pass


def clear_project_writeback_files(db: Session) -> None:
    db.info.pop("project_writeback_files", None)


def _write_transaction_file(db: Session, path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    _remember_transaction_file(db, path)


def _int_field(payload: dict[str, Any], key: str) -> int:
    try:
        value = int(payload.get(key))
    except Exception as exc:
        raise ValueError(f"项目写回字段 {key} 必须是整数") from exc
    if value <= 0:
        raise ValueError(f"项目写回字段 {key} 必须大于 0")
    return value


def _writeback_payload(sub_task: SubTask) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    metadata = _load_metadata(sub_task.metadata_json)
    payload = metadata.get("project_writeback")
    if not isinstance(payload, dict):
        return None, metadata
    if payload.get("enabled") is False:
        return None, metadata
    return payload, metadata


def apply_approved_review_writeback(
    db: Session,
    *,
    sub_task: SubTask,
    review: ReviewRecord,
) -> ContentVersion | None:
    """Apply executor output to a project scene after a reviewer approval.

    This is intentionally opt-in. A sub task must carry metadata like:
    {
      "project_writeback": {
        "project_id": "...",
        "episode_number": 1,
        "scene_number": 1
      },
      "output_content": "..."
    }
    """
    payload, metadata = _writeback_payload(sub_task)
    if payload is None:
        return None

    project_id = str(payload.get("project_id") or "").strip()
    if not project_id:
        raise ValueError("项目写回缺少 project_id")

    episode_number = _int_field(payload, "episode_number")
    scene_number = _int_field(payload, "scene_number")
    content = str(payload.get("content") or metadata.get("output_content") or "").strip()
    if not content:
        raise ValueError("项目写回缺少正文内容 content/output_content")

    # Lazy import to avoid app.services -> review_service -> project helpers circular import.
    from app.routers.projects._helpers import (
        _calculate_contribution_score,
        _calculate_diff,
        _checkpoint_file_path,
        _get_next_checkpoint_code,
        _get_next_version_code,
        _scene_version_file_path,
        _update_contribution_ledger,
    )

    project = db.query(ProjectV2).filter(ProjectV2.id == project_id).first()
    if not project:
        raise ValueError(f"项目写回目标项目不存在: {project_id}")

    episode = (
        db.query(Episode)
        .filter(Episode.project_id == project_id, Episode.episode_number == episode_number)
        .first()
    )
    if not episode:
        raise ValueError(f"项目写回目标集不存在: 第{episode_number}集")

    scene = (
        db.query(Scene)
        .filter(Scene.episode_id == episode.id, Scene.scene_number == scene_number)
        .first()
    )
    if not scene:
        raise ValueError(f"项目写回目标场景不存在: 第{episode_number}集第{scene_number}场")

    old_content = scene.content or ""
    diff_stats = _calculate_diff(old_content, content)
    editor_type = str(payload.get("editor_type") or "skill_reviewer")
    editor_id = str(payload.get("editor_id") or review.reviewer_agent or "")
    editor_name = str(payload.get("editor_name") or "Reviewer")
    change_note = str(
        payload.get("change_note")
        or f"Reviewer approved sub task writeback: {sub_task.name}"
    )
    create_checkpoint = bool(payload.get("create_checkpoint", True))

    contribution_score = _calculate_contribution_score(diff_stats, editor_type)
    version_code = _get_next_version_code(db, project_id, episode_number, scene_number)
    scene_file = _scene_version_file_path(
        project,
        episode_number=episode_number,
        scene_number=scene_number,
        version_code=version_code,
    )
    _write_transaction_file(db, scene_file, content)

    version = ContentVersion(
        project_id=project_id,
        episode_number=episode_number,
        scene_number=scene_number,
        version_code=version_code,
        parent_version=episode.current_version,
        editor_type=editor_type,
        editor_id=editor_id,
        editor_name=editor_name,
        content_path=str(scene_file),
        content_hash=hashlib.sha256(content.encode()).hexdigest(),
        diff_stats=json.dumps(diff_stats, ensure_ascii=False),
        contribution_score=contribution_score,
        change_note=change_note,
    )
    db.add(version)
    db.flush()

    scene.content = content
    scene.word_count = len(content)
    scene.status = "completed"
    scene.primary_author = editor_id or scene.primary_author
    scene.ai_generated = editor_type in {"ai", "skill_writer", "skill_reviewer"}
    scene.ai_modified = False
    scene.updated_at = datetime.now()

    episode.current_version = version_code
    episode.updated_at = datetime.now()
    project.updated_at = datetime.now()

    _update_contribution_ledger(
        db,
        project_id,
        editor_id,
        editor_name,
        editor_type,
        diff_stats,
        contribution_score,
        version.id,
        episode_number,
        auto_commit=False,
    )

    checkpoint_id = ""
    if create_checkpoint:
        checkpoint_code = _get_next_checkpoint_code(db, project_id)
        checkpoint_file = _checkpoint_file_path(project, checkpoint_code)
        checkpoint_data = {
            "project_id": project_id,
            "episode_number": episode_number,
            "scene_number": scene_number,
            "version_id": version.id,
            "content_path": str(scene_file),
            "editor": editor_name,
            "review_id": review.id,
            "sub_task_id": sub_task.id,
            "note": change_note,
            "created_at": datetime.now().isoformat(),
        }
        _write_transaction_file(db, checkpoint_file, json.dumps(checkpoint_data, ensure_ascii=False, indent=2))
        checkpoint = Checkpoint(
            project_id=project_id,
            checkpoint_code=checkpoint_code,
            episode_number=episode_number,
            scene_number=scene_number,
            data_path=str(checkpoint_file),
            note=change_note,
            created_by=editor_id,
            auto_created=True,
        )
        db.add(checkpoint)
        db.flush()
        checkpoint_id = checkpoint.id
        version.checkpoint_id = checkpoint.id
        scene.checkpoint_id = checkpoint.id

    metadata["project_writeback_result"] = {
        "project_id": project_id,
        "episode_number": episode_number,
        "scene_number": scene_number,
        "version_id": version.id,
        "version_code": version.version_code,
        "checkpoint_id": checkpoint_id,
        "review_id": review.id,
        "applied_at": datetime.now().isoformat(),
    }
    sub_task.metadata_json = _dump_metadata(metadata)
    db.flush()
    return version
