"""Safe consistency checks for locked official source artifacts.

This module validates metadata and file integrity only. It must not log or
persist protected source text; callers may use the returned content in-memory
for generation context after the consistency gate passes.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.models.evidence import EvidenceEvent
from app.models.project_v2 import ContentVersion
from app.services import workspace_service


class OfficialSourceConsistencyError(RuntimeError):
    """Raised when a locked official source artifact cannot be proven safe."""

    def __init__(
        self,
        reason_code: str,
        *,
        project_id: str,
        episode_number: int,
        content_version_id: str = "",
    ) -> None:
        self.reason_code = reason_code
        self.project_id = project_id
        self.episode_number = episode_number
        self.content_version_id = content_version_id
        super().__init__(reason_code)


@dataclass(frozen=True)
class LockedOfficialSourceConsistency:
    project_id: str
    episode_number: int
    content_version_id: str
    content_hash: str
    episode_locked_event_id: str
    content_path: str
    content: str

    @property
    def source_map(self) -> dict[str, Any]:
        return {
            "source": "episode_locked_content_version",
            "official_source": "episode_locked",
            "episode_number": self.episode_number,
            "content_version_id": self.content_version_id,
            "content_hash": self.content_hash,
            "episode_locked_event_id": self.episode_locked_event_id,
        }


def validate_locked_official_source_consistency(
    db: Session,
    *,
    project_id: str,
    episode_number: int,
    project_workspace_path: str,
    content_version_id: str = "",
) -> LockedOfficialSourceConsistency:
    """Validate DB row, lock event, file path, and content hash for one episode."""

    query = db.query(ContentVersion).filter(
        ContentVersion.project_id == project_id,
        ContentVersion.episode_number == episode_number,
        ContentVersion.scene_number == 0,
        ContentVersion.content_hash != "",
    )
    if content_version_id:
        query = query.filter(ContentVersion.id == content_version_id)
    version = query.order_by(ContentVersion.created_at.desc()).first()
    if version is None:
        raise OfficialSourceConsistencyError(
            "locked_official_source_missing",
            project_id=project_id,
            episode_number=episode_number,
            content_version_id=content_version_id,
        )

    event = (
        db.query(EvidenceEvent)
        .filter(
            EvidenceEvent.project_id == project_id,
            EvidenceEvent.event_type == "episode_locked",
            EvidenceEvent.target_type == "episode",
            EvidenceEvent.target_id == str(episode_number),
            EvidenceEvent.content_version_id == version.id,
            EvidenceEvent.content_hash == version.content_hash,
        )
        .order_by(EvidenceEvent.created_at.desc())
        .first()
    )
    if event is None:
        raise OfficialSourceConsistencyError(
            "locked_official_event_missing",
            project_id=project_id,
            episode_number=episode_number,
            content_version_id=str(version.id or ""),
        )

    workspace_root_text = str(project_workspace_path or "").strip()
    if not workspace_root_text:
        raise OfficialSourceConsistencyError(
            "locked_official_workspace_missing",
            project_id=project_id,
            episode_number=episode_number,
            content_version_id=str(version.id or ""),
        )

    content_path_text = str(version.content_path or "").strip()
    content_path = Path(content_path_text)
    workspace_root = Path(workspace_root_text).expanduser().resolve(strict=False)
    resolved_content_path = content_path.expanduser().resolve(strict=False)
    if resolved_content_path != workspace_root and not workspace_service.path_is_relative_to(resolved_content_path, workspace_root):
        raise OfficialSourceConsistencyError(
            "locked_official_file_outside_workspace",
            project_id=project_id,
            episode_number=episode_number,
            content_version_id=str(version.id or ""),
        )
    if not content_path_text or not resolved_content_path.exists() or not resolved_content_path.is_file():
        raise OfficialSourceConsistencyError(
            "locked_official_file_missing",
            project_id=project_id,
            episode_number=episode_number,
            content_version_id=str(version.id or ""),
        )

    content = resolved_content_path.read_text(encoding="utf-8").strip()
    if not content:
        raise OfficialSourceConsistencyError(
            "locked_official_file_empty",
            project_id=project_id,
            episode_number=episode_number,
            content_version_id=str(version.id or ""),
        )

    actual_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
    expected_hash = str(version.content_hash or "")
    if actual_hash != expected_hash:
        raise OfficialSourceConsistencyError(
            "locked_official_hash_mismatch",
            project_id=project_id,
            episode_number=episode_number,
            content_version_id=str(version.id or ""),
        )

    return LockedOfficialSourceConsistency(
        project_id=project_id,
        episode_number=episode_number,
        content_version_id=str(version.id or ""),
        content_hash=expected_hash,
        episode_locked_event_id=str(event.id or ""),
        content_path=str(resolved_content_path),
        content=content,
    )


def validate_locked_official_source_map(
    source_map: dict[str, Any] | None,
    consistency: LockedOfficialSourceConsistency,
) -> dict[str, Any]:
    """Reject missing or stale source-map metadata for a proven locked source."""

    if not isinstance(source_map, dict) or not source_map:
        raise OfficialSourceConsistencyError(
            "locked_official_source_map_missing",
            project_id=consistency.project_id,
            episode_number=consistency.episode_number,
            content_version_id=consistency.content_version_id,
        )

    expected = consistency.source_map
    for key in ("source", "official_source", "episode_number", "content_version_id", "content_hash", "episode_locked_event_id"):
        if str(source_map.get(key, "")) != str(expected.get(key, "")):
            raise OfficialSourceConsistencyError(
                "locked_official_source_map_mismatch",
                project_id=consistency.project_id,
                episode_number=consistency.episode_number,
                content_version_id=consistency.content_version_id,
            )
    return dict(source_map)


def validate_locked_official_source_recovery_proof(
    db: Session,
    *,
    project_id: str,
    episode_number: int,
    project_workspace_path: str,
    content_path: str = "",
    content_hash: str = "",
    episode_locked_event_id: str = "",
    content_version_id: str = "",
) -> dict[str, Any]:
    """Prove locked source recovery in both DB->file and file/hash->DB directions."""

    consistency = validate_locked_official_source_consistency(
        db,
        project_id=project_id,
        episode_number=episode_number,
        project_workspace_path=project_workspace_path,
        content_version_id=content_version_id,
    )

    expected_path = Path(consistency.content_path).expanduser().resolve(strict=False)
    requested_path = Path(content_path or consistency.content_path).expanduser().resolve(strict=False)
    requested_hash = str(content_hash or consistency.content_hash)
    if requested_path != expected_path or requested_hash != consistency.content_hash:
        raise OfficialSourceConsistencyError(
            "locked_official_file_hash_db_lookup_missing",
            project_id=project_id,
            episode_number=episode_number,
            content_version_id=consistency.content_version_id,
        )

    matching_versions = (
        db.query(ContentVersion)
        .filter(
            ContentVersion.project_id == project_id,
            ContentVersion.episode_number == episode_number,
            ContentVersion.scene_number == 0,
            ContentVersion.content_hash == requested_hash,
        )
        .all()
    )
    version = next(
        (
            item
            for item in matching_versions
            if Path(str(item.content_path or "")).expanduser().resolve(strict=False) == requested_path
            and str(item.id or "") == consistency.content_version_id
        ),
        None,
    )
    if version is None:
        raise OfficialSourceConsistencyError(
            "locked_official_file_hash_db_lookup_missing",
            project_id=project_id,
            episode_number=episode_number,
            content_version_id=consistency.content_version_id,
        )

    event_id = str(episode_locked_event_id or consistency.episode_locked_event_id)
    event = (
        db.query(EvidenceEvent)
        .filter(
            EvidenceEvent.id == event_id,
            EvidenceEvent.project_id == project_id,
            EvidenceEvent.event_type == "episode_locked",
            EvidenceEvent.target_type == "episode",
            EvidenceEvent.target_id == str(episode_number),
            EvidenceEvent.content_version_id == consistency.content_version_id,
            EvidenceEvent.content_hash == consistency.content_hash,
        )
        .first()
    )
    if event is None:
        raise OfficialSourceConsistencyError(
            "locked_official_event_missing",
            project_id=project_id,
            episode_number=episode_number,
            content_version_id=consistency.content_version_id,
        )

    source_map = validate_locked_official_source_map(consistency.source_map, consistency)
    return {
        "project_id": project_id,
        "episode_number": episode_number,
        "content_version_id": consistency.content_version_id,
        "content_hash": consistency.content_hash,
        "episode_locked_event_id": event_id,
        "content_path": str(requested_path),
        "source_map": source_map,
        "checks": {
            "db_to_file": True,
            "file_hash_to_db": True,
            "event_to_content_version": True,
            "event_to_source_map": True,
        },
    }
