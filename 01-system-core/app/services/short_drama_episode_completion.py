"""Safe closure for a completed short-drama episode draft."""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.models.evidence import EvidenceEvent
from app.models.project_v2 import ContentVersion, Episode, ProjectV2, Scene
from app.models.short_drama_generation_job import ShortDramaGenerationJob
from app.routers.projects._helpers import _get_next_version_code, _scene_version_file_path
from app.services.evidence_event_service import record_evidence_event


SEGMENT_IDS = ("hook", "validation", "explosion", "resolution")
SEGMENT_CONFIRMATION_NOTE = "分段确认自动保存"
EPISODE_DRAFT_COMPLETION_NOTE = "内部四段审阅完成"
COMPLETION_CHECKPOINT_EVENT_TYPE = "episode_draft_completion_checkpoint"
SEGMENT_CONFIRMATION_EVENT_TYPE = "script_segment_confirmed"
ACTIVE_JOB_STATUSES = {"pending", "running"}
PRIOR_SEGMENT_IDS = ("hook", "validation", "explosion")


def _load_json(serialized: str | None) -> Any:
    if not serialized:
        return {}
    try:
        return json.loads(serialized)
    except Exception:
        return {}


def _job_segment_id(job: ShortDramaGenerationJob) -> str:
    payload = _load_json(job.request_json)
    if not isinstance(payload, dict):
        return ""
    return str(payload.get("segment_id") or "").strip()


def _job_candidate_content(job: ShortDramaGenerationJob) -> str:
    payload = _load_json(job.result_json)
    if not isinstance(payload, dict):
        return ""
    content = payload.get("content")
    if isinstance(content, str):
        return content.strip()
    candidate = payload.get("candidate")
    if isinstance(candidate, dict) and isinstance(candidate.get("content"), str):
        return candidate["content"].strip()
    return ""


def _ordered_segment_ids(values: set[str]) -> list[str]:
    return [segment_id for segment_id in SEGMENT_IDS if segment_id in values]


def _normalize_text_for_match(value: str | None) -> str:
    return re.sub(r"\s+", "", str(value or ""))


def _normalized_contains(container: str, needle: str) -> bool:
    normalized_needle = _normalize_text_for_match(needle)
    if not normalized_needle:
        return False
    return normalized_needle in _normalize_text_for_match(container)


def _frontend_simple_hash(text: str) -> str:
    hash_value = 2166136261
    for char in text:
        hash_value ^= ord(char)
        hash_value = (hash_value * 16777619) & 0xFFFFFFFF
    return format(hash_value, "x")


def _workspace_confirmed_segments(
    project: ProjectV2 | None,
    *,
    episode_number: int,
    scene_number: int,
    scene_content: str,
) -> set[str]:
    if project is None or not project.workspace_path:
        return set()
    project_file = Path(str(project.workspace_path)) / "project.json"
    if not project_file.is_file():
        return set()
    try:
        payload = json.loads(project_file.read_text(encoding="utf-8"))
    except Exception:
        return set()
    if not isinstance(payload, dict):
        return set()
    workflow_context = payload.get("workflow_context")
    if not isinstance(workflow_context, dict):
        return set()
    progress_store = workflow_context.get("script_segment_progress")
    if not isinstance(progress_store, dict):
        return set()
    progress = progress_store.get(str(episode_number)) or progress_store.get(episode_number)
    if not isinstance(progress, dict):
        return set()
    if int(progress.get("episode_no") or 0) != int(episode_number):
        return set()
    if int(progress.get("scene_no") or 0) != int(scene_number):
        return set()

    saved_content = str(progress.get("scene_content") or "")
    if saved_content and _normalize_text_for_match(saved_content) != _normalize_text_for_match(scene_content):
        return set()
    if not saved_content:
        saved_hash = str(progress.get("content_hash") or "")
        if saved_hash:
            current_hashes = {
                _frontend_simple_hash(scene_content),
                hashlib.sha256(scene_content.encode("utf-8")).hexdigest(),
            }
            if saved_hash not in current_hashes:
                return set()

    steps = progress.get("steps")
    if not isinstance(steps, list):
        return set()
    confirmed: set[str] = set()
    for step in steps:
        if not isinstance(step, dict):
            continue
        if str(step.get("status") or "") != "confirmed":
            continue
        segment_id = str(
            step.get("id")
            or step.get("segment_id")
            or step.get("segmentId")
            or "",
        ).strip()
        if segment_id in SEGMENT_IDS:
            confirmed.add(segment_id)
    return confirmed


def _latest_candidate_jobs(
    db: Session,
    *,
    project_id: str,
    episode_number: int,
    scene_number: int,
    workspace_confirmed_segments: set[str] | None = None,
) -> tuple[dict[str, ShortDramaGenerationJob], dict[str, int]]:
    confirmed_segments = workspace_confirmed_segments or set()
    rows = db.query(ShortDramaGenerationJob).filter(
        ShortDramaGenerationJob.project_id == project_id,
        ShortDramaGenerationJob.episode_no == episode_number,
        ShortDramaGenerationJob.scene_no == scene_number,
        ShortDramaGenerationJob.status.in_(["candidate_ready", "candidate_review_required"]),
    ).order_by(
        desc(ShortDramaGenerationJob.updated_at),
        desc(ShortDramaGenerationJob.created_at),
    ).all()
    latest: dict[str, ShortDramaGenerationJob] = {}
    candidate_lengths: dict[str, int] = {}
    for row in rows:
        segment_id = _job_segment_id(row)
        if segment_id not in SEGMENT_IDS or segment_id in latest:
            continue
        content = _job_candidate_content(row)
        if row.status != "candidate_ready":
            if row.status != "candidate_review_required":
                continue
            if segment_id not in confirmed_segments or not content:
                continue
        latest[segment_id] = row
        candidate_lengths[segment_id] = len(content)
    return latest, candidate_lengths


def _count_scene_versions(
    db: Session,
    *,
    project_id: str,
    episode_number: int,
    scene_number: int,
    note: str,
) -> int:
    return db.query(ContentVersion).filter(
        ContentVersion.project_id == project_id,
        ContentVersion.episode_number == episode_number,
        ContentVersion.scene_number == scene_number,
        ContentVersion.change_note == note,
    ).count()


def _confirmed_segments_from_evidence(
    db: Session,
    *,
    project_id: str,
    episode_number: int,
    scene_number: int,
) -> set[str]:
    rows = db.query(EvidenceEvent).filter(
        EvidenceEvent.project_id == project_id,
        EvidenceEvent.event_type == SEGMENT_CONFIRMATION_EVENT_TYPE,
        EvidenceEvent.target_type == "script_segment",
    ).all()
    confirmed: set[str] = set()
    target_prefix = f"{episode_number}:{scene_number}:"
    for row in rows:
        segment_id = ""
        target_id = str(row.target_id or "")
        if target_id.startswith(target_prefix):
            segment_id = target_id.removeprefix(target_prefix)
        metadata = _load_json(row.metadata_json)
        if isinstance(metadata, dict):
            meta_episode = int(metadata.get("episode_number") or 0)
            meta_scene = int(metadata.get("scene_number") or 0)
            meta_segment = str(metadata.get("segment_id") or "").strip()
            if meta_episode == int(episode_number) and meta_scene == int(scene_number):
                segment_id = meta_segment or segment_id
        if segment_id in SEGMENT_IDS:
            confirmed.add(segment_id)
    return confirmed


def _version_content(version: ContentVersion) -> str:
    path = Path(str(version.content_path or ""))
    if not path.is_file():
        return ""
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return ""


def _legacy_confirmed_segments_from_versions(
    db: Session,
    *,
    project_id: str,
    episode_number: int,
    scene_number: int,
    candidate_jobs: dict[str, ShortDramaGenerationJob],
) -> set[str]:
    rows = db.query(ContentVersion).filter(
        ContentVersion.project_id == project_id,
        ContentVersion.episode_number == episode_number,
        ContentVersion.scene_number == scene_number,
        ContentVersion.change_note == SEGMENT_CONFIRMATION_NOTE,
    ).order_by(ContentVersion.created_at, ContentVersion.version_code).all()
    confirmed: set[str] = set()
    candidate_content = {
        segment_id: _job_candidate_content(candidate_jobs[segment_id])
        for segment_id in SEGMENT_IDS
        if segment_id in candidate_jobs
    }
    for version in rows:
        saved_content = _version_content(version)
        if not saved_content:
            continue
        for segment_id in PRIOR_SEGMENT_IDS:
            content = candidate_content.get(segment_id, "")
            if _normalized_contains(saved_content, content):
                confirmed.add(segment_id)
    return confirmed


def _latest_scene_version_by_note(
    db: Session,
    *,
    project_id: str,
    episode_number: int,
    scene_number: int,
    note: str,
) -> ContentVersion | None:
    return db.query(ContentVersion).filter(
        ContentVersion.project_id == project_id,
        ContentVersion.episode_number == episode_number,
        ContentVersion.scene_number == scene_number,
        ContentVersion.change_note == note,
    ).order_by(desc(ContentVersion.created_at), desc(ContentVersion.version_code)).first()


def _create_safe_scene_version(
    db: Session,
    *,
    project: ProjectV2,
    episode: Episode,
    scene: Scene,
    episode_number: int,
    scene_number: int,
    content: str,
    note: str,
    written_paths: list[Path] | None = None,
) -> ContentVersion:
    version_code = _get_next_version_code(db, project.id, episode_number, scene_number)
    path = _scene_version_file_path(
        project,
        episode_number=episode_number,
        scene_number=scene_number,
        version_code=version_code,
    )
    path.write_text(content, encoding="utf-8")
    if written_paths is not None:
        written_paths.append(path)
    content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
    version = ContentVersion(
        project_id=project.id,
        episode_number=episode_number,
        scene_number=scene_number,
        version_code=version_code,
        parent_version=episode.current_version or "",
        editor_type="ai",
        editor_id="episode_draft_completion_closure",
        editor_name="本集草稿完成收口",
        content_path=str(path),
        content_hash=content_hash,
        diff_stats=json.dumps({
            "added_chars": 0,
            "deleted_chars": 0,
            "added_lines": 0,
            "deleted_lines": 0,
            "closure_save": True,
        }, ensure_ascii=False),
        contribution_score=0,
        change_note=note,
    )
    db.add(version)
    db.flush()
    episode.current_version = version_code
    episode.updated_at = datetime.now()
    scene.word_count = len(content)
    scene.updated_at = datetime.now()
    project.updated_at = datetime.now()
    return version


def _safe_result(
    *,
    status: str,
    episode_number: int,
    scene_number: int,
    created_confirmation_count: int = 0,
    reused_confirmation_count: int = 0,
    completion_checkpoint_created: bool = False,
    completion_checkpoint_reused: bool = False,
    active_job_count: int = 0,
    content_version_id: str = "",
    blocking_issues: list[str] | None = None,
    candidate_lengths: dict[str, int] | None = None,
    confirmed_segment_ids: list[str] | None = None,
    structured_confirmed_segment_ids: list[str] | None = None,
    legacy_confirmed_segment_ids: list[str] | None = None,
    legacy_confirmation_count: int = 0,
) -> dict[str, Any]:
    return {
        "status": status,
        "episode_number": episode_number,
        "scene_number": scene_number,
        "segment_ids": list(SEGMENT_IDS),
        "created_confirmation_count": created_confirmation_count,
        "reused_confirmation_count": reused_confirmation_count,
        "completion_checkpoint_created": completion_checkpoint_created,
        "completion_checkpoint_reused": completion_checkpoint_reused,
        "active_job_count": active_job_count,
        "content_version_id": content_version_id,
        "blocking_issues": blocking_issues or [],
        "candidate_lengths": candidate_lengths or {},
        "confirmed_segment_ids": confirmed_segment_ids or [],
        "structured_confirmed_segment_ids": structured_confirmed_segment_ids or [],
        "legacy_confirmed_segment_ids": legacy_confirmed_segment_ids or [],
        "legacy_confirmation_count": legacy_confirmation_count,
    }


def complete_episode_draft_save_closure(
    db: Session,
    *,
    project_id: str,
    episode_number: int,
    scene_number: int = 1,
    actor: Any = None,
) -> dict[str, Any]:
    """Close an episode draft when generation and save evidence agree.

    The closure writes only safe save evidence. It never creates generation jobs,
    calls a model, creates a locked episode version, starts compliance, or exports.
    """
    project = db.query(ProjectV2).filter(ProjectV2.id == project_id).first()
    episode = db.query(Episode).filter(
        Episode.project_id == project_id,
        Episode.episode_number == episode_number,
    ).first()
    scene = None
    if episode is not None:
        scene = db.query(Scene).filter(
            Scene.episode_id == episode.id,
            Scene.scene_number == scene_number,
        ).first()

    blocking_issues: list[str] = []
    if project is None:
        blocking_issues.append("project_missing")
    if episode is None:
        blocking_issues.append("episode_missing")
    if scene is None:
        blocking_issues.append("scene_missing")
    content = str(getattr(scene, "content", "") or "") if scene is not None else ""
    if scene is not None and not content.strip():
        blocking_issues.append("scene_content_empty")

    active_job_count = db.query(ShortDramaGenerationJob).filter(
        ShortDramaGenerationJob.project_id == project_id,
        ShortDramaGenerationJob.episode_no == episode_number,
        ShortDramaGenerationJob.scene_no == scene_number,
        ShortDramaGenerationJob.status.in_(list(ACTIVE_JOB_STATUSES)),
    ).count()
    if active_job_count:
        blocking_issues.append("active_generation_job_exists")

    official_count = db.query(ContentVersion).filter(
        ContentVersion.project_id == project_id,
        ContentVersion.episode_number == episode_number,
        ContentVersion.scene_number == 0,
    ).count()
    if official_count:
        blocking_issues.append("official_episode_version_exists")

    workspace_confirmed_segments = _workspace_confirmed_segments(
        project,
        episode_number=episode_number,
        scene_number=scene_number,
        scene_content=content,
    )
    candidate_jobs, candidate_lengths = _latest_candidate_jobs(
        db,
        project_id=project_id,
        episode_number=episode_number,
        scene_number=scene_number,
        workspace_confirmed_segments=workspace_confirmed_segments,
    )
    for segment_id in SEGMENT_IDS:
        if segment_id not in candidate_jobs:
            blocking_issues.append(f"segment_candidate_missing:{segment_id}")
        elif candidate_lengths.get(segment_id, 0) <= 0:
            blocking_issues.append(f"segment_candidate_empty:{segment_id}")

    resolution_job = candidate_jobs.get("resolution")
    resolution_content = _job_candidate_content(resolution_job) if resolution_job is not None else ""
    if resolution_content and content and not _normalized_contains(content, resolution_content):
        blocking_issues.append("resolution_candidate_not_in_scene_content")

    legacy_confirmation_count = _count_scene_versions(
        db,
        project_id=project_id,
        episode_number=episode_number,
        scene_number=scene_number,
        note=SEGMENT_CONFIRMATION_NOTE,
    )
    structured_confirmed_segments = _confirmed_segments_from_evidence(
        db,
        project_id=project_id,
        episode_number=episode_number,
        scene_number=scene_number,
    )
    legacy_confirmed_segments = _legacy_confirmed_segments_from_versions(
        db,
        project_id=project_id,
        episode_number=episode_number,
        scene_number=scene_number,
        candidate_jobs=candidate_jobs,
    )
    confirmed_segments = structured_confirmed_segments | legacy_confirmed_segments | workspace_confirmed_segments
    missing_prior_segments = [
        segment_id for segment_id in PRIOR_SEGMENT_IDS
        if segment_id not in confirmed_segments
    ]
    for segment_id in missing_prior_segments:
        blocking_issues.append(f"prior_segment_confirmation_evidence_missing:{segment_id}")

    if blocking_issues:
        return _safe_result(
            status="blocked",
            episode_number=episode_number,
            scene_number=scene_number,
            active_job_count=active_job_count,
            blocking_issues=blocking_issues,
            candidate_lengths=candidate_lengths,
            confirmed_segment_ids=_ordered_segment_ids(confirmed_segments),
            structured_confirmed_segment_ids=_ordered_segment_ids(structured_confirmed_segments),
            legacy_confirmed_segment_ids=_ordered_segment_ids(legacy_confirmed_segments),
            legacy_confirmation_count=legacy_confirmation_count,
        )

    assert project is not None
    assert episode is not None
    assert scene is not None

    created_confirmation_count = 0
    written_paths: list[Path] = []
    try:
        if "resolution" not in confirmed_segments:
            confirmation_version = _create_safe_scene_version(
                db,
                project=project,
                episode=episode,
                scene=scene,
                episode_number=episode_number,
                scene_number=scene_number,
                content=content,
                note=SEGMENT_CONFIRMATION_NOTE,
                written_paths=written_paths,
            )
            created_confirmation_count = 1
            record_evidence_event(
                db,
                project_id=project_id,
                actor=actor,
                event_type=SEGMENT_CONFIRMATION_EVENT_TYPE,
                target_type="script_segment",
                target_id=f"{episode_number}:{scene_number}:resolution",
                content_version_id=confirmation_version.id,
                content_hash=confirmation_version.content_hash,
                summary=SEGMENT_CONFIRMATION_NOTE,
                metadata={
                    "episode_number": episode_number,
                    "scene_number": scene_number,
                    "segment_id": "resolution",
                    "job_id": str(resolution_job.id if resolution_job is not None else ""),
                    "candidate_length": candidate_lengths.get("resolution", 0),
                    "scene_content_hash": confirmation_version.content_hash,
                },
                commit=False,
            )
            structured_confirmed_segments.add("resolution")
            confirmed_segments.add("resolution")
        else:
            confirmation_version = _latest_scene_version_by_note(
                db,
                project_id=project_id,
                episode_number=episode_number,
                scene_number=scene_number,
                note=SEGMENT_CONFIRMATION_NOTE,
            )

        completion_version = _latest_scene_version_by_note(
            db,
            project_id=project_id,
            episode_number=episode_number,
            scene_number=scene_number,
            note=EPISODE_DRAFT_COMPLETION_NOTE,
        )
        completion_checkpoint = db.query(EvidenceEvent).filter(
            EvidenceEvent.project_id == project_id,
            EvidenceEvent.event_type == COMPLETION_CHECKPOINT_EVENT_TYPE,
            EvidenceEvent.target_type == "episode",
            EvidenceEvent.target_id == str(episode_number),
        ).order_by(desc(EvidenceEvent.created_at)).first()
        completion_checkpoint_created = False
        if completion_version is None:
            completion_version = _create_safe_scene_version(
                db,
                project=project,
                episode=episode,
                scene=scene,
                episode_number=episode_number,
                scene_number=scene_number,
                content=content,
                note=EPISODE_DRAFT_COMPLETION_NOTE,
                written_paths=written_paths,
            )
        if completion_checkpoint is None:
            completion_checkpoint_created = True
            segment_job_ids = {
                segment_id: str(candidate_jobs[segment_id].id)
                for segment_id in SEGMENT_IDS
                if segment_id in candidate_jobs
            }
            record_evidence_event(
                db,
                project_id=project_id,
                actor=actor,
                event_type=COMPLETION_CHECKPOINT_EVENT_TYPE,
                target_type="episode",
                target_id=str(episode_number),
                content_version_id=completion_version.id,
                content_hash=completion_version.content_hash,
                summary=EPISODE_DRAFT_COMPLETION_NOTE,
                metadata={
                    "episode_number": episode_number,
                    "scene_number": scene_number,
                    "segment_ids": list(SEGMENT_IDS),
                    "segment_job_ids": segment_job_ids,
                    "candidate_lengths": candidate_lengths,
                    "confirmed_segment_ids": _ordered_segment_ids(confirmed_segments),
                    "structured_confirmed_segment_ids": _ordered_segment_ids(structured_confirmed_segments),
                    "legacy_confirmed_segment_ids": _ordered_segment_ids(legacy_confirmed_segments),
                    "legacy_confirmation_count": legacy_confirmation_count,
                    "active_job_count": 0,
                    "scene_content_hash": completion_version.content_hash,
                },
                commit=False,
            )

        db.commit()
    except Exception:
        db.rollback()
        for path in written_paths:
            try:
                path.unlink(missing_ok=True)
            except Exception:
                pass
        raise
    db.refresh(completion_version)
    return _safe_result(
        status="completed",
        episode_number=episode_number,
        scene_number=scene_number,
        created_confirmation_count=created_confirmation_count,
        reused_confirmation_count=max(0, len(confirmed_segments) - created_confirmation_count),
        completion_checkpoint_created=completion_checkpoint_created,
        completion_checkpoint_reused=not completion_checkpoint_created,
        active_job_count=0,
        content_version_id=completion_version.id,
        candidate_lengths=candidate_lengths,
        confirmed_segment_ids=_ordered_segment_ids(confirmed_segments),
        structured_confirmed_segment_ids=_ordered_segment_ids(structured_confirmed_segments),
        legacy_confirmed_segment_ids=_ordered_segment_ids(legacy_confirmed_segments),
        legacy_confirmation_count=legacy_confirmation_count,
    )
