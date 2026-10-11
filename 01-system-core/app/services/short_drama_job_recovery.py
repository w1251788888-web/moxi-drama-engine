"""Safe recovery helpers for short-drama generation jobs.

These helpers provide a small durable-worker recovery layer without changing
the DB schema. They use the persisted job row and updated_at timestamp as the
worker heartbeat and never persist prompt, response, or protected script text.
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.models.short_drama_generation_job import ShortDramaGenerationJob
from app.services.short_drama_atomic_generation import (
    PUBLIC_MODEL_RECOVERY_EXHAUSTED,
    SCRIPT_GENERATION_JOB_CANDIDATE_READY,
    SCRIPT_GENERATION_JOB_CANDIDATE_REVIEW_REQUIRED,
    SCRIPT_GENERATION_JOB_FAILED,
    SCRIPT_GENERATION_JOB_RUNNING,
)

SCRIPT_SCENE_ACTIVE_JOB_STATUSES = {"pending", SCRIPT_GENERATION_JOB_RUNNING}
SCRIPT_SCENE_CANDIDATE_STATUSES = {
    SCRIPT_GENERATION_JOB_CANDIDATE_READY,
    SCRIPT_GENERATION_JOB_CANDIDATE_REVIEW_REQUIRED,
}
SCRIPT_SCENE_STALE_JOB_AFTER_SECONDS = 30 * 60


def _load_json_object(raw: str) -> dict[str, Any]:
    try:
        payload = json.loads(raw or "{}")
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _save_internal(db: Session, job: ShortDramaGenerationJob, internal: dict[str, Any]) -> None:
    job.internal_json = json.dumps(internal, ensure_ascii=False, default=str)
    db.commit()


def recover_stale_script_scene_job_if_needed(
    db: Session,
    job: ShortDramaGenerationJob,
    *,
    now: datetime | None = None,
    stale_after_seconds: int = SCRIPT_SCENE_STALE_JOB_AFTER_SECONDS,
) -> bool:
    """Mark a persisted active job failed when its DB heartbeat is stale."""

    if str(job.status or "") not in SCRIPT_SCENE_ACTIVE_JOB_STATUSES:
        return False
    updated_at = job.updated_at or job.created_at
    if updated_at is None:
        return False
    current_time = now or datetime.now()
    age_seconds = max(0, int((current_time - updated_at).total_seconds()))
    if age_seconds < int(stale_after_seconds or 0):
        return False

    internal = _load_json_object(job.internal_json)
    internal["recovery"] = {
        "reason_code": "stale_running_job_recovered_as_failed",
        "worker_state": str(job.status or ""),
        "age_seconds_bucket": _age_bucket(age_seconds),
    }
    job.status = SCRIPT_GENERATION_JOB_FAILED
    job.public_message = PUBLIC_MODEL_RECOVERY_EXHAUSTED
    job.public_progress = 100
    job.error = "stale_running_job_recovered_as_failed"
    _save_internal(db, job, internal)
    return True


def recover_stale_script_scene_jobs(
    db: Session,
    *,
    project_id: str,
    episode_no: int,
    scene_no: int,
    owner_key: str = "",
    owner_is_admin: bool = False,
) -> int:
    query = db.query(ShortDramaGenerationJob).filter(
        ShortDramaGenerationJob.project_id == project_id,
        ShortDramaGenerationJob.episode_no == int(episode_no or 1),
        ShortDramaGenerationJob.scene_no == int(scene_no or 1),
        ShortDramaGenerationJob.status.in_(list(SCRIPT_SCENE_ACTIVE_JOB_STATUSES)),
    )
    if not owner_is_admin:
        query = query.filter(ShortDramaGenerationJob.owner_key == (owner_key or ""))
    recovered = 0
    for job in query.all():
        if recover_stale_script_scene_job_if_needed(db, job):
            recovered += 1
    return recovered


def find_reusable_active_script_scene_job(
    db: Session,
    *,
    project_id: str,
    episode_no: int,
    scene_no: int,
    owner_key: str = "",
    owner_is_admin: bool = False,
) -> ShortDramaGenerationJob | None:
    """Return the newest non-stale active job for this target, if any."""

    recover_stale_script_scene_jobs(
        db,
        project_id=project_id,
        episode_no=episode_no,
        scene_no=scene_no,
        owner_key=owner_key,
        owner_is_admin=owner_is_admin,
    )
    query = db.query(ShortDramaGenerationJob).filter(
        ShortDramaGenerationJob.project_id == project_id,
        ShortDramaGenerationJob.episode_no == int(episode_no or 1),
        ShortDramaGenerationJob.scene_no == int(scene_no or 1),
        ShortDramaGenerationJob.status.in_(list(SCRIPT_SCENE_ACTIVE_JOB_STATUSES)),
    )
    if not owner_is_admin:
        query = query.filter(ShortDramaGenerationJob.owner_key == (owner_key or ""))
    return query.order_by(ShortDramaGenerationJob.updated_at.desc(), ShortDramaGenerationJob.created_at.desc()).first()


def mark_orphan_candidate_job_failed_if_needed(
    db: Session,
    job: ShortDramaGenerationJob,
) -> bool:
    """Reject candidate rows whose result target metadata contradicts the job row."""

    if str(job.status or "") not in SCRIPT_SCENE_CANDIDATE_STATUSES:
        return False
    result = _load_json_object(job.result_json)
    target = result.get("job_target")
    if not isinstance(target, dict) or not target:
        return False
    expected = {
        "project_id": str(job.project_id or ""),
        "episode_no": int(job.episode_no or 1),
        "scene_no": int(job.scene_no or 1),
    }
    actual = {
        "project_id": str(target.get("project_id") or ""),
        "episode_no": int(target.get("episode_no") or 0),
        "scene_no": int(target.get("scene_no") or 0),
    }
    if actual == expected:
        return False

    internal = _load_json_object(job.internal_json)
    internal["recovery"] = {
        "reason_code": "orphan_candidate_result_target_mismatch",
        "expected": expected,
        "actual": actual,
    }
    job.status = SCRIPT_GENERATION_JOB_FAILED
    job.public_message = PUBLIC_MODEL_RECOVERY_EXHAUSTED
    job.public_progress = 100
    job.error = "orphan_candidate_result_target_mismatch"
    _save_internal(db, job, internal)
    return True


def _age_bucket(age_seconds: int) -> str:
    if age_seconds < 60:
        return "lt_1m"
    if age_seconds < 15 * 60:
        return "1m_15m"
    if age_seconds < 60 * 60:
        return "15m_1h"
    if age_seconds < 6 * 60 * 60:
        return "1h_6h"
    return "gte_6h"
