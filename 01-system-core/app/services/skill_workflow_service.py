from __future__ import annotations

import json
import hashlib
import os
import re
import subprocess
import sys
from functools import lru_cache
from pathlib import Path
from typing import Any
from datetime import datetime

from sqlalchemy.orm import Session

from app.models.skill_registry import (
    SkillArtifact,
    SkillBinding,
    SkillInvocation,
    SkillQualityFeedback,
    SkillRegistry,
)


REPO_ROOT = Path(__file__).resolve().parents[3]
MANIFEST_PATH = REPO_ROOT / "05-skill-plugins" / "integrated-skills" / "manifest.json"


SKILL_STAGE_LIBRARY: dict[str, dict[str, Any]] = {
    "planning": {
        "title": "方案压实",
        "why": "先把问题定义、边界和实施步骤锁住，避免修着修着又回到拍脑袋。",
        "skill_names": [
            "superpowers-brainstorming",
            "superpowers-writing-plans",
        ],
        "action_hint": "先明确目标边界，再拆成可执行小任务。",
    },
    "debugging": {
        "title": "根因排查",
        "why": "先找根因，再动手修。避免为了赶时间一直修表象。",
        "skill_names": [
            "superpowers-systematic-debugging",
        ],
        "action_hint": "先复现、取证、定根因，再决定是局部修补还是整段重写。",
    },
    "quality": {
        "title": "回归补强",
        "why": "把这次修复沉淀成回归测试和校验器，避免同类问题再次出现。",
        "skill_names": [
            "superpowers-test-driven-development",
        ],
        "action_hint": "优先补失败用例和回归校验，再补实现。",
    },
    "verification": {
        "title": "完成前核验",
        "why": "在宣告修好之前，必须有新鲜验证证据，避免假修复。",
        "skill_names": [
            "superpowers-verification-before-completion",
        ],
        "action_hint": "跑完整验证链路，再宣布完成或进入长测。",
    },
    "review": {
        "title": "结构化复审",
        "why": "大改动进入长测前，需要再过一遍结构化复审，尽量把高风险问题留在测试前。",
        "skill_names": [
            "superpowers-requesting-code-review",
        ],
        "action_hint": "在进入长测前，按需求和 diff 做一次正式复审。",
    },
    "discovery": {
        "title": "技能检索",
        "why": "类似问题先查有没有成熟技能，减少重复试错和 token 浪费。",
        "skill_names": [
            "openspace-skill-discovery",
        ],
        "action_hint": "先搜是否已有成熟技能，再决定自己修还是委派。",
    },
    "delegation": {
        "title": "复杂任务委派",
        "why": "复杂链路、跨环境任务或修复卡壳时，交给 OpenSpace 做外部 worker 更稳。",
        "skill_names": [
            "openspace-delegate-task",
        ],
        "action_hint": "把复杂修复、测试辅助或自动修复链任务委派出去执行。",
    },
}


FAILURE_STAGE_RECIPES: dict[str, list[str]] = {
    "format_break": ["debugging", "quality", "verification"],
    "anchor_missing": ["debugging", "verification"],
    "state_drift": ["debugging", "discovery", "delegation", "verification"],
    "dramatic_weakness": ["planning", "debugging", "verification"],
    "local_patch_needed": ["debugging", "quality", "verification"],
    "success": ["verification"],
    "default": ["debugging", "verification"],
}

VALID_BINDING_TYPES = {"global", "failure_type", "step", "project_type", "context"}
VALID_INVOCATION_STATUSES = {"started", "success", "failed", "cancelled"}
VALID_FEEDBACK_VERDICTS = {"pending_review", "useful", "not_useful", "needs_followup", "blocked"}
EXTERNAL_RUNNER_CONFIRMATION_PHRASE = "CONFIRM_EXTERNAL_SKILL_RUN"
EXTERNAL_RUNNER_EXECUTION_CONFIRMATION_PHRASE = "EXECUTE_EXTERNAL_SKILL_RUN"
DEFAULT_EXTERNAL_RUNNER_TIMEOUT_SECONDS = 30
MAX_EXTERNAL_RUNNER_TIMEOUT_SECONDS = 120
MAX_EXTERNAL_RUNNER_PAYLOAD_CHARS = 12000
MAX_EXTERNAL_RUNNER_STDIO_CHARS = 6000
SENSITIVE_FIELD_MARKERS = (
    "api_key",
    "apikey",
    "access_key",
    "authorization",
    "cookie",
    "password",
    "private_key",
    "secret",
    "session",
    "token",
)

SAFE_EXTERNAL_RUNNER_COMMANDS: dict[str, dict[str, Any]] = {
    "skill_echo_probe": {
        "description": "内置 Skill runner 探针，只回显脱敏后的参数键和执行边界。",
        "command": [sys.executable, "-m", "app.services.skill_external_runner_probe"],
        "cwd": REPO_ROOT / "01-system-core",
    },
}


@lru_cache(maxsize=1)
def load_skill_manifest() -> dict[str, Any]:
    if not MANIFEST_PATH.exists():
        return {"skill_count": 0, "skills": []}
    try:
        return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {"skill_count": 0, "skills": []}


def get_skill_catalog() -> list[dict[str, Any]]:
    manifest = load_skill_manifest()
    skills = manifest.get("skills")
    if not isinstance(skills, list):
        return []
    return [item for item in skills if isinstance(item, dict)]


def sync_skill_manifest_to_db(db: Session) -> dict[str, Any]:
    """Sync the curated Skill manifest into the durable registry."""
    manifest = load_skill_manifest()
    manifest_skills = manifest.get("skills")
    if not isinstance(manifest_skills, list):
        manifest_skills = []

    seen_names: set[str] = set()
    created = 0
    updated = 0
    unchanged = 0
    now = datetime.now()

    for item in manifest_skills:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        seen_names.add(name)
        payload_hash = _skill_manifest_hash(item)
        row = db.query(SkillRegistry).filter(SkillRegistry.name == name).first()
        if row is None:
            row = SkillRegistry(name=name)
            db.add(row)
            created += 1
        elif row.manifest_hash == payload_hash and row.status == "active":
            row.synced_at = now
            unchanged += 1
            continue
        else:
            updated += 1

        _apply_manifest_skill(row, item, payload_hash, now)

    archived = 0
    if seen_names:
        rows = db.query(SkillRegistry).filter(SkillRegistry.name.notin_(seen_names)).all()
        for row in rows:
            if row.status != "archived":
                row.status = "archived"
                row.is_enabled = False
                row.synced_at = now
                archived += 1

    db.commit()
    return {
        "source": str(MANIFEST_PATH),
        "manifest_skill_count": len([item for item in manifest_skills if isinstance(item, dict)]),
        "created_count": created,
        "updated_count": updated,
        "unchanged_count": unchanged,
        "archived_count": archived,
        "registry_count": db.query(SkillRegistry).count(),
    }


def get_db_skill_catalog(
    db: Session,
    *,
    include_disabled: bool = False,
    auto_sync: bool = True,
) -> list[dict[str, Any]]:
    """Return Skills from the database registry, syncing from manifest if empty."""
    if auto_sync and db.query(SkillRegistry.id).limit(1).first() is None:
        sync_skill_manifest_to_db(db)

    query = db.query(SkillRegistry)
    if not include_disabled:
        query = query.filter(
            SkillRegistry.status == "active",
            SkillRegistry.is_enabled == True,  # noqa: E712
        )
    rows = query.order_by(SkillRegistry.category.asc(), SkillRegistry.name.asc()).all()
    return [serialize_skill_registry(row) for row in rows]


def serialize_skill_registry(row: SkillRegistry) -> dict[str, Any]:
    return {
        "id": row.id,
        "name": row.name,
        "display_name": row.display_name or row.name,
        "description": row.description or "",
        "source": row.source or "",
        "target": row.target or "",
        "upstream_repo": row.upstream_repo or "",
        "category": row.category or "",
        "recommended_for": _json_loads(row.recommended_for_json, []),
        "why": row.why or "",
        "mode": row.mode or "",
        "status": row.status or "",
        "is_enabled": bool(row.is_enabled),
        "version": int(row.version or 1),
        "manifest_hash": row.manifest_hash or "",
        "metadata": _json_loads(row.metadata_json, {}),
        "synced_at": row.synced_at.isoformat() if row.synced_at else "",
        "updated_at": row.updated_at.isoformat() if row.updated_at else "",
    }


def create_skill_binding(
    db: Session,
    *,
    skill_name: str,
    binding_type: str,
    binding_key: str = "",
    priority: int = 100,
    config: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
    is_enabled: bool = True,
) -> dict[str, Any]:
    skill = _get_skill_by_name(db, skill_name)
    normalized_type = _normalize_binding_type(binding_type)
    row = SkillBinding(
        skill_id=skill.id,
        skill_name=skill.name,
        binding_type=normalized_type,
        binding_key=str(binding_key or "").strip(),
        priority=_safe_int(priority, default=100, minimum=0, maximum=10000),
        config_json=json.dumps(config or {}, ensure_ascii=False, default=str),
        metadata_json=json.dumps(metadata or {}, ensure_ascii=False, default=str),
        is_enabled=bool(is_enabled),
        status="active",
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return serialize_skill_binding(row)


def update_skill_binding(
    db: Session,
    binding_id: str,
    *,
    binding_key: str | None = None,
    priority: int | None = None,
    config: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
    status: str | None = None,
    is_enabled: bool | None = None,
) -> dict[str, Any]:
    row = db.query(SkillBinding).filter(SkillBinding.id == binding_id).first()
    if not row:
        raise ValueError(f"Skill binding {binding_id} 不存在")
    if binding_key is not None:
        row.binding_key = str(binding_key or "").strip()
    if priority is not None:
        row.priority = _safe_int(priority, default=100, minimum=0, maximum=10000)
    if config is not None:
        row.config_json = json.dumps(config, ensure_ascii=False, default=str)
    if metadata is not None:
        row.metadata_json = json.dumps(metadata, ensure_ascii=False, default=str)
    if status is not None:
        row.status = _normalize_status(status)
    if is_enabled is not None:
        row.is_enabled = bool(is_enabled)
    db.commit()
    db.refresh(row)
    return serialize_skill_binding(row)


def list_skill_bindings(
    db: Session,
    *,
    skill_name: str = "",
    binding_type: str = "",
    binding_key: str = "",
    include_disabled: bool = False,
    limit: int = 100,
) -> list[dict[str, Any]]:
    query = db.query(SkillBinding)
    if skill_name:
        query = query.filter(SkillBinding.skill_name == skill_name)
    if binding_type:
        query = query.filter(SkillBinding.binding_type == _normalize_binding_type(binding_type))
    if binding_key:
        query = query.filter(SkillBinding.binding_key == binding_key)
    if not include_disabled:
        query = query.filter(
            SkillBinding.status == "active",
            SkillBinding.is_enabled == True,  # noqa: E712
        )
    rows = (
        query.order_by(SkillBinding.priority.asc(), SkillBinding.updated_at.desc())
        .limit(_safe_int(limit, default=100, minimum=1, maximum=500))
        .all()
    )
    return [serialize_skill_binding(row) for row in rows]


def resolve_skill_bindings(
    db: Session,
    *,
    failure_type: str = "",
    step_id: str = "",
    project_type: str = "",
    context: str = "",
    limit: int = 20,
) -> list[dict[str, Any]]:
    candidates = [
        ("global", ""),
        ("failure_type", str(failure_type or "").strip()),
        ("step", str(step_id or "").strip()),
        ("project_type", str(project_type or "").strip()),
        ("context", str(context or "").strip()),
    ]
    clauses = [(kind, key) for kind, key in candidates if kind == "global" or key]
    if not clauses:
        clauses = [("global", "")]

    rows: list[SkillBinding] = []
    for binding_type, binding_key in clauses:
        query = db.query(SkillBinding).filter(
            SkillBinding.binding_type == binding_type,
            SkillBinding.status == "active",
            SkillBinding.is_enabled == True,  # noqa: E712
        )
        if binding_type == "global":
            query = query.filter(SkillBinding.binding_key == "")
        else:
            query = query.filter(SkillBinding.binding_key == binding_key)
        rows.extend(query.all())

    rows.sort(key=lambda row: (int(row.priority or 100), row.binding_type, row.skill_name))
    deduped: list[SkillBinding] = []
    seen: set[str] = set()
    for row in rows:
        if row.id in seen:
            continue
        seen.add(row.id)
        deduped.append(row)
        if len(deduped) >= limit:
            break
    return [serialize_skill_binding(row) for row in deduped]


def serialize_skill_binding(row: SkillBinding) -> dict[str, Any]:
    return {
        "id": row.id,
        "skill_id": row.skill_id or "",
        "skill_name": row.skill_name or "",
        "binding_type": row.binding_type or "",
        "binding_key": row.binding_key or "",
        "priority": int(row.priority or 100),
        "config": _json_loads(row.config_json, {}),
        "metadata": _json_loads(row.metadata_json, {}),
        "status": row.status or "",
        "is_enabled": bool(row.is_enabled),
        "created_at": row.created_at.isoformat() if row.created_at else "",
        "updated_at": row.updated_at.isoformat() if row.updated_at else "",
    }


def start_skill_invocation(
    db: Session,
    *,
    skill_name: str,
    binding_id: str = "",
    actor_type: str = "system",
    actor_id: str = "",
    context: str = "general",
    failure_type: str = "",
    input_summary: str = "",
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    skill = _get_skill_by_name(db, skill_name)
    binding = None
    if binding_id:
        binding = db.query(SkillBinding).filter(SkillBinding.id == binding_id).first()
        if not binding:
            raise ValueError(f"Skill binding {binding_id} 不存在")
    row = SkillInvocation(
        skill_id=skill.id,
        skill_name=skill.name,
        binding_id=binding.id if binding else "",
        actor_type=str(actor_type or "system").strip()[:40],
        actor_id=str(actor_id or "").strip()[:120],
        context=str(context or "general").strip()[:120],
        failure_type=str(failure_type or "").strip()[:120],
        status="started",
        input_summary=str(input_summary or ""),
        metadata_json=json.dumps(metadata or {}, ensure_ascii=False, default=str),
        started_at=datetime.now(),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return serialize_skill_invocation(row)


def finish_skill_invocation(
    db: Session,
    invocation_id: str,
    *,
    status: str = "success",
    output_summary: str = "",
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    row = db.query(SkillInvocation).filter(SkillInvocation.id == invocation_id).first()
    if not row:
        raise ValueError(f"Skill invocation {invocation_id} 不存在")
    finished_at = datetime.now()
    row.status = _normalize_invocation_status(status)
    row.output_summary = str(output_summary or "")
    if metadata is not None:
        row.metadata_json = json.dumps(metadata, ensure_ascii=False, default=str)
    row.finished_at = finished_at
    if row.started_at:
        row.duration_ms = max(0, int((finished_at - row.started_at).total_seconds() * 1000))
    db.commit()
    db.refresh(row)
    return serialize_skill_invocation(row)


def list_skill_invocations(
    db: Session,
    *,
    skill_name: str = "",
    status: str = "",
    context: str = "",
    limit: int = 50,
) -> list[dict[str, Any]]:
    query = db.query(SkillInvocation)
    if skill_name:
        query = query.filter(SkillInvocation.skill_name == skill_name)
    if status:
        query = query.filter(SkillInvocation.status == _normalize_invocation_status(status))
    if context:
        query = query.filter(SkillInvocation.context == context)
    rows = (
        query.order_by(SkillInvocation.created_at.desc())
        .limit(_safe_int(limit, default=50, minimum=1, maximum=200))
        .all()
    )
    return [serialize_skill_invocation(row) for row in rows]


def serialize_skill_invocation(row: SkillInvocation) -> dict[str, Any]:
    return {
        "id": row.id,
        "skill_id": row.skill_id or "",
        "skill_name": row.skill_name or "",
        "binding_id": row.binding_id or "",
        "actor_type": row.actor_type or "",
        "actor_id": row.actor_id or "",
        "context": row.context or "",
        "failure_type": row.failure_type or "",
        "status": row.status or "",
        "input_summary": row.input_summary or "",
        "output_summary": row.output_summary or "",
        "metadata": _json_loads(row.metadata_json, {}),
        "started_at": row.started_at.isoformat() if row.started_at else "",
        "finished_at": row.finished_at.isoformat() if row.finished_at else "",
        "duration_ms": int(row.duration_ms or 0),
        "created_at": row.created_at.isoformat() if row.created_at else "",
        "updated_at": row.updated_at.isoformat() if row.updated_at else "",
    }


def create_skill_artifact(
    db: Session,
    *,
    invocation_id: str,
    artifact_type: str = "text",
    title: str = "",
    content: str = "",
    path: str = "",
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    invocation = db.query(SkillInvocation).filter(SkillInvocation.id == invocation_id).first()
    if not invocation:
        raise ValueError(f"Skill invocation {invocation_id} 不存在")
    row = SkillArtifact(
        invocation_id=invocation.id,
        skill_id=invocation.skill_id or "",
        skill_name=invocation.skill_name,
        artifact_type=str(artifact_type or "text").strip()[:80],
        title=str(title or "").strip()[:300],
        content=str(content or ""),
        path=str(path or ""),
        metadata_json=json.dumps(metadata or {}, ensure_ascii=False, default=str),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return serialize_skill_artifact(row)


def list_skill_artifacts(
    db: Session,
    *,
    invocation_id: str = "",
    skill_name: str = "",
    artifact_type: str = "",
    limit: int = 50,
) -> list[dict[str, Any]]:
    query = db.query(SkillArtifact)
    if invocation_id:
        query = query.filter(SkillArtifact.invocation_id == invocation_id)
    if skill_name:
        query = query.filter(SkillArtifact.skill_name == skill_name)
    if artifact_type:
        query = query.filter(SkillArtifact.artifact_type == artifact_type)
    rows = (
        query.order_by(SkillArtifact.created_at.desc())
        .limit(_safe_int(limit, default=50, minimum=1, maximum=200))
        .all()
    )
    return [serialize_skill_artifact(row) for row in rows]


def serialize_skill_artifact(row: SkillArtifact) -> dict[str, Any]:
    return {
        "id": row.id,
        "invocation_id": row.invocation_id or "",
        "skill_id": row.skill_id or "",
        "skill_name": row.skill_name or "",
        "artifact_type": row.artifact_type or "",
        "title": row.title or "",
        "content": row.content or "",
        "path": row.path or "",
        "metadata": _json_loads(row.metadata_json, {}),
        "created_at": row.created_at.isoformat() if row.created_at else "",
    }


def create_skill_quality_feedback(
    db: Session,
    *,
    invocation_id: str,
    score: int = 0,
    verdict: str = "pending_review",
    reviewer_type: str = "admin",
    reviewer_id: str = "",
    notes: str = "",
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    invocation = db.query(SkillInvocation).filter(SkillInvocation.id == invocation_id).first()
    if not invocation:
        raise ValueError(f"Skill invocation {invocation_id} 不存在")
    row = SkillQualityFeedback(
        invocation_id=invocation.id,
        skill_id=invocation.skill_id or "",
        skill_name=invocation.skill_name,
        score=_safe_int(score, default=0, minimum=0, maximum=100),
        verdict=_normalize_feedback_verdict(verdict),
        reviewer_type=str(reviewer_type or "admin").strip()[:40],
        reviewer_id=str(reviewer_id or "").strip()[:120],
        notes=str(notes or ""),
        metadata_json=json.dumps(metadata or {}, ensure_ascii=False, default=str),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return serialize_skill_quality_feedback(row)


def list_skill_quality_feedback(
    db: Session,
    *,
    invocation_id: str = "",
    skill_name: str = "",
    verdict: str = "",
    limit: int = 50,
) -> list[dict[str, Any]]:
    query = db.query(SkillQualityFeedback)
    if invocation_id:
        query = query.filter(SkillQualityFeedback.invocation_id == invocation_id)
    if skill_name:
        query = query.filter(SkillQualityFeedback.skill_name == skill_name)
    if verdict:
        query = query.filter(SkillQualityFeedback.verdict == _normalize_feedback_verdict(verdict))
    rows = (
        query.order_by(SkillQualityFeedback.created_at.desc())
        .limit(_safe_int(limit, default=50, minimum=1, maximum=200))
        .all()
    )
    return [serialize_skill_quality_feedback(row) for row in rows]


def serialize_skill_quality_feedback(row: SkillQualityFeedback) -> dict[str, Any]:
    return {
        "id": row.id,
        "invocation_id": row.invocation_id or "",
        "skill_id": row.skill_id or "",
        "skill_name": row.skill_name or "",
        "score": int(row.score or 0),
        "verdict": row.verdict or "",
        "reviewer_type": row.reviewer_type or "",
        "reviewer_id": row.reviewer_id or "",
        "notes": row.notes or "",
        "metadata": _json_loads(row.metadata_json, {}),
        "created_at": row.created_at.isoformat() if row.created_at else "",
    }


def summarize_skill_quality_feedback(
    db: Session,
    *,
    skill_name: str = "",
    limit: int = 1000,
    min_feedback: int = 2,
) -> dict[str, Any]:
    """Aggregate Skill feedback into binding priority hints without mutating bindings."""
    query = db.query(SkillQualityFeedback)
    if skill_name:
        query = query.filter(SkillQualityFeedback.skill_name == skill_name)
    rows = (
        query.order_by(SkillQualityFeedback.created_at.desc())
        .limit(_safe_int(limit, default=1000, minimum=1, maximum=2000))
        .all()
    )
    min_count = _safe_int(min_feedback, default=2, minimum=1, maximum=50)
    invocation_ids = {row.invocation_id for row in rows if row.invocation_id}
    invocations = {}
    if invocation_ids:
        invocations = {
            row.id: row
            for row in db.query(SkillInvocation).filter(SkillInvocation.id.in_(invocation_ids)).all()
        }

    verdict_totals: dict[str, int] = {name: 0 for name in sorted(VALID_FEEDBACK_VERDICTS)}
    grouped: dict[str, dict[str, Any]] = {}
    for row in rows:
        name = row.skill_name or ""
        if not name:
            continue
        item = grouped.setdefault(
            name,
            {
                "skill_name": name,
                "feedback_count": 0,
                "score_sum": 0,
                "verdict_counts": {verdict: 0 for verdict in sorted(VALID_FEEDBACK_VERDICTS)},
                "failure_type_counts": {},
                "last_feedback_at": "",
            },
        )
        verdict = row.verdict or "pending_review"
        score = int(row.score or 0)
        item["feedback_count"] += 1
        item["score_sum"] += score
        item["verdict_counts"][verdict] = int(item["verdict_counts"].get(verdict, 0)) + 1
        verdict_totals[verdict] = int(verdict_totals.get(verdict, 0)) + 1
        if row.created_at and (not item["last_feedback_at"] or row.created_at.isoformat() > item["last_feedback_at"]):
            item["last_feedback_at"] = row.created_at.isoformat()

        invocation = invocations.get(row.invocation_id or "")
        failure_type = str(getattr(invocation, "failure_type", "") or "").strip()
        if failure_type:
            failure_counts = item["failure_type_counts"]
            failure_counts[failure_type] = int(failure_counts.get(failure_type, 0)) + 1

    items = []
    for item in grouped.values():
        count = int(item["feedback_count"] or 0)
        verdict_counts = item["verdict_counts"]
        failure_counts = item.pop("failure_type_counts")
        item["average_score"] = round(float(item.pop("score_sum") or 0) / count, 1) if count else 0
        item["useful_rate"] = round(float(verdict_counts.get("useful", 0)) / count, 3) if count else 0
        item["negative_rate"] = (
            round(float(verdict_counts.get("not_useful", 0) + verdict_counts.get("blocked", 0)) / count, 3)
            if count
            else 0
        )
        item["failure_type_breakdown"] = [
            {"failure_type": key, "count": value}
            for key, value in sorted(failure_counts.items(), key=lambda pair: (-pair[1], pair[0]))
        ]
        item["binding_priority_hint"] = _build_feedback_priority_hint(item, min_count)
        items.append(item)

    items.sort(key=lambda item: (-int(item["feedback_count"]), -float(item["average_score"]), item["skill_name"]))
    total = sum(int(item["feedback_count"]) for item in items)
    average = (
        round(sum(float(item["average_score"]) * int(item["feedback_count"]) for item in items) / total, 1)
        if total
        else 0
    )
    return {
        "generated_at": datetime.now().isoformat(),
        "source": "skill_quality_feedback",
        "total_feedback_count": total,
        "skill_count": len(items),
        "average_score": average,
        "verdict_counts": verdict_totals,
        "min_feedback": min_count,
        "items": items,
    }


def run_skill_workflow_worker(
    db: Session,
    *,
    failure_type: str = "",
    blocking_issues: list[str] | None = None,
    warnings: list[str] | None = None,
    context: str = "skill-worker",
    actor_type: str = "system",
    actor_id: str = "",
    max_skills: int = 3,
) -> dict[str, Any]:
    """Create auditable Skill execution-plan records from DB-backed recommendations."""
    recommendation = recommend_skill_workflow(
        failure_type=failure_type,
        blocking_issues=blocking_issues or [],
        warnings=warnings or [],
        context=context,
        db=db,
    )
    selected_names: list[str] = []
    seen: set[str] = set()
    limit = _safe_int(max_skills, default=3, minimum=1, maximum=10)
    available_names = {str(item.get("name") or "") for item in get_db_skill_catalog(db)}
    for item in recommendation.get("recommended_skills", []):
        name = str(item.get("name") or "").strip()
        if not name or name in seen or name not in available_names:
            continue
        seen.add(name)
        selected_names.append(name)
        if len(selected_names) >= limit:
            break

    invocations: list[dict[str, Any]] = []
    artifacts: list[dict[str, Any]] = []
    for skill_name in selected_names:
        invocation = start_skill_invocation(
            db,
            skill_name=skill_name,
            actor_type=actor_type,
            actor_id=actor_id,
            context=context,
            failure_type=str(recommendation.get("failure_type") or failure_type or ""),
            input_summary=f"Skill worker 根据 {recommendation.get('failure_type')} 生成执行计划",
            metadata={
                "worker": "skill_workflow_worker",
                "matched_binding_count": len(recommendation.get("matched_bindings", [])),
            },
        )
        artifact = create_skill_artifact(
            db,
            invocation_id=invocation["id"],
            artifact_type="workflow_plan",
            title=f"{skill_name} 执行计划",
            content=_build_worker_artifact_content(skill_name, recommendation),
            metadata={
                "worker": "skill_workflow_worker",
                "catalog_source": recommendation.get("catalog_source"),
                "matched_bindings": recommendation.get("matched_bindings", []),
            },
        )
        finished = finish_skill_invocation(
            db,
            invocation["id"],
            status="success",
            output_summary="已生成内部编排执行计划，等待人工或外部 worker 继续执行。",
            metadata={
                "worker": "skill_workflow_worker",
                "artifact_id": artifact["id"],
            },
        )
        invocations.append(finished)
        artifacts.append(artifact)

    return {
        "worker": "skill_workflow_worker",
        "catalog_source": recommendation.get("catalog_source"),
        "failure_type": recommendation.get("failure_type"),
        "planned_count": len(invocations),
        "recommendation": recommendation,
        "invocations": invocations,
        "artifacts": artifacts,
    }


def prepare_external_skill_runner_request(
    db: Session,
    *,
    skill_name: str,
    binding_id: str = "",
    parameters: dict[str, Any] | None = None,
    context: str = "external-runner",
    actor_type: str = "admin",
    actor_id: str = "",
    runner_name: str = "manual_external_runner",
    timeout_seconds: int | None = None,
    confirm_execution: bool = False,
    confirmation_phrase: str = "",
    confirmed_by: str = "",
) -> dict[str, Any]:
    """Create an auditable external-runner request after strict gate checks.

    This function does not execute local scripts or third-party code. It creates a
    sanitized request artifact that a separately approved external runner may pick up.
    """
    skill = _get_skill_by_name(db, skill_name)
    if skill.status != "active" or not bool(skill.is_enabled):
        raise ValueError(f"Skill {skill.name} 未启用，不能进入外部 runner")

    binding = _resolve_external_runner_binding(db, skill, binding_id)
    policy = _external_runner_policy(skill, binding)
    if not policy["enabled"]:
        raise ValueError(f"Skill {skill.name} 未配置 external_runner.enabled=true")

    confirmer = str(confirmed_by or actor_id or "").strip()
    if policy["requires_confirmation"]:
        if not confirm_execution or str(confirmation_phrase or "").strip() != EXTERNAL_RUNNER_CONFIRMATION_PHRASE:
            raise ValueError(f"外部 Skill runner 需要人工确认短语 {EXTERNAL_RUNNER_CONFIRMATION_PHRASE}")
        if not confirmer:
            raise ValueError("外部 Skill runner 需要记录 confirmed_by")

    validated_parameters = _validate_external_runner_parameters(parameters or {}, policy)
    redacted_parameters = _redact_sensitive_payload(validated_parameters)
    timeout = _validate_external_runner_timeout(timeout_seconds, policy)
    normalized_runner = str(runner_name or "manual_external_runner").strip()[:120] or "manual_external_runner"
    now = datetime.now().isoformat()
    request_metadata = {
        "worker": "external_skill_runner_gate",
        "runner_name": normalized_runner,
        "binding_id": binding.id if binding else "",
        "timeout_seconds": timeout,
        "confirmed_by": confirmer,
        "confirmation_phrase": "[CONFIRMED]",
        "allowed_parameters": policy["allowed_parameters"],
        "allowed_runners": policy["allowed_runners"],
        "execution_enabled": policy["execution_enabled"],
        "will_execute": False,
        "created_at": now,
    }

    invocation = start_skill_invocation(
        db,
        skill_name=skill.name,
        binding_id=binding.id if binding else "",
        actor_type=actor_type,
        actor_id=actor_id,
        context=context,
        failure_type="external_skill_runner_gate",
        input_summary=f"外部 Skill runner 门禁请求：{normalized_runner}",
        metadata={
            **request_metadata,
            "parameters": redacted_parameters,
        },
    )
    artifact = create_skill_artifact(
        db,
        invocation_id=invocation["id"],
        artifact_type="external_runner_request",
        title=f"{skill.name} 外部 runner 门禁请求",
        content=_build_external_runner_request_artifact(
            skill_name=skill.name,
            runner_name=normalized_runner,
            timeout_seconds=timeout,
            parameters=redacted_parameters,
            metadata=request_metadata,
        ),
        metadata={
            **request_metadata,
            "parameters": redacted_parameters,
        },
    )
    finished = finish_skill_invocation(
        db,
        invocation["id"],
        status="success",
        output_summary="已通过外部 Skill runner 门禁并生成请求产物；本系统未执行外部脚本。",
        metadata={
            **request_metadata,
            "artifact_id": artifact["id"],
        },
    )

    return {
        "worker": "external_skill_runner_gate",
        "status": "ready_for_external_runner",
        "will_execute": False,
        "skill_name": skill.name,
        "runner_name": normalized_runner,
        "binding_id": binding.id if binding else "",
        "timeout_seconds": timeout,
        "parameters": redacted_parameters,
        "invocation": finished,
        "artifact": artifact,
    }


def execute_external_skill_runner_request(
    db: Session,
    *,
    request_invocation_id: str,
    runner_name: str = "",
    context: str = "external-runner-executor",
    actor_type: str = "admin",
    actor_id: str = "",
    confirm_execution: bool = False,
    confirmation_phrase: str = "",
    confirmed_by: str = "",
) -> dict[str, Any]:
    """Execute a prepared external-runner request through a fixed safe command.

    Execution stays deliberately narrow: a binding must opt in with
    external_runner.execution_enabled=true and allowed_runners, the command is
    selected from SAFE_EXTERNAL_RUNNER_COMMANDS, and the prepared request can be
    consumed only once.
    """
    request = db.query(SkillInvocation).filter(SkillInvocation.id == str(request_invocation_id or "")).first()
    if not request:
        raise ValueError(f"外部 runner 请求 {request_invocation_id} 不存在")
    request_metadata = _json_loads(request.metadata_json, {})
    if request_metadata.get("worker") != "external_skill_runner_gate":
        raise ValueError("request_invocation_id 不是外部 runner 门禁请求")
    if request_metadata.get("execution_invocation_id"):
        raise ValueError("外部 runner 请求已执行，不能重复确认")
    if _find_existing_external_runner_execution(db, request.id):
        raise ValueError("外部 runner 请求已存在执行记录，不能重复确认")

    skill = _get_skill_by_name(db, request.skill_name)
    binding = _resolve_external_runner_binding(db, skill, str(request_metadata.get("binding_id") or request.binding_id or ""))
    policy = _external_runner_policy(skill, binding)
    if not policy["execution_enabled"]:
        raise ValueError("外部 runner 执行未开启，需 external_runner.execution_enabled=true")

    prepared_runner = str(request_metadata.get("runner_name") or "").strip()
    normalized_runner = str(runner_name or prepared_runner or "").strip()
    if not normalized_runner:
        raise ValueError("外部 runner 缺少 runner_name")
    if prepared_runner and normalized_runner != prepared_runner:
        raise ValueError("执行 runner_name 必须与准备阶段一致")
    _validate_external_runner_name(normalized_runner, policy)

    confirmer = str(confirmed_by or actor_id or "").strip()
    if not confirm_execution or str(confirmation_phrase or "").strip() != EXTERNAL_RUNNER_EXECUTION_CONFIRMATION_PHRASE:
        raise ValueError(f"执行外部 Skill runner 需要确认短语 {EXTERNAL_RUNNER_EXECUTION_CONFIRMATION_PHRASE}")
    if not confirmer:
        raise ValueError("执行外部 Skill runner 需要记录 confirmed_by")

    artifact = db.query(SkillArtifact).filter(SkillArtifact.id == str(request_metadata.get("artifact_id") or "")).first()
    prepared_payload = _load_external_runner_request_payload(artifact)
    parameters = _as_dict(prepared_payload.get("parameters"))
    timeout = _validate_external_runner_timeout(_safe_int(request_metadata.get("timeout_seconds"), default=policy["timeout_seconds"], minimum=1, maximum=MAX_EXTERNAL_RUNNER_TIMEOUT_SECONDS), policy)
    execution_metadata = {
        "worker": "external_skill_runner_executor",
        "request_invocation_id": request.id,
        "runner_name": normalized_runner,
        "binding_id": binding.id if binding else "",
        "confirmed_by": confirmer,
        "confirmation_phrase": "[CONFIRMED]",
        "timeout_seconds": timeout,
        "command_key": normalized_runner,
        "will_execute": True,
    }
    invocation = start_skill_invocation(
        db,
        skill_name=skill.name,
        binding_id=binding.id if binding else "",
        actor_type=actor_type,
        actor_id=actor_id,
        context=context,
        failure_type="external_skill_runner_execute",
        input_summary=f"受控执行外部 Skill runner：{normalized_runner}",
        metadata={
            **execution_metadata,
            "parameters": _redact_sensitive_payload(parameters),
        },
    )
    result = _run_safe_external_runner(
        runner_name=normalized_runner,
        skill_name=skill.name,
        request_invocation_id=request.id,
        parameters=parameters,
        timeout_seconds=timeout,
    )
    artifact = create_skill_artifact(
        db,
        invocation_id=invocation["id"],
        artifact_type="external_runner_execution",
        title=f"{skill.name} 受控 runner 执行记录",
        content=_build_external_runner_execution_artifact(
            skill_name=skill.name,
            runner_name=normalized_runner,
            request_invocation_id=request.id,
            execution=result,
            metadata=execution_metadata,
        ),
        metadata={
            **execution_metadata,
            "execution": result,
        },
    )
    finished = finish_skill_invocation(
        db,
        invocation["id"],
        status="success" if result["status"] == "success" else "failed",
        output_summary=_external_runner_output_summary(result),
        metadata={
            **execution_metadata,
            "artifact_id": artifact["id"],
            "execution": result,
        },
    )
    _mark_external_runner_request_executed(db, request, finished, artifact, result)
    return {
        "worker": "external_skill_runner_executor",
        "status": result["status"],
        "will_execute": True,
        "skill_name": skill.name,
        "runner_name": normalized_runner,
        "binding_id": binding.id if binding else "",
        "request_invocation_id": request.id,
        "timeout_seconds": timeout,
        "parameters": _redact_sensitive_payload(parameters),
        "execution": result,
        "request_invocation": serialize_skill_invocation(request),
        "invocation": finished,
        "artifact": artifact,
    }


def _build_worker_artifact_content(skill_name: str, recommendation: dict[str, Any]) -> str:
    actions = recommendation.get("next_actions") or []
    bindings = recommendation.get("matched_bindings") or []
    lines = [
        f"# {skill_name} 执行计划",
        "",
        f"- failure_type: {recommendation.get('failure_type')}",
        f"- context: {recommendation.get('context')}",
        f"- matched_bindings: {len(bindings)}",
        "",
        "## 下一步",
    ]
    lines.extend([f"- {action}" for action in actions])
    return "\n".join(lines)


def _build_external_runner_request_artifact(
    *,
    skill_name: str,
    runner_name: str,
    timeout_seconds: int,
    parameters: dict[str, Any],
    metadata: dict[str, Any],
) -> str:
    payload = {
        "skill_name": skill_name,
        "runner_name": runner_name,
        "timeout_seconds": timeout_seconds,
        "parameters": parameters,
        "metadata": metadata,
        "will_execute": False,
        "dispatch_note": "本产物仅表示门禁通过；真实外部 runner 执行需单独受控调度。",
    }
    return json.dumps(payload, ensure_ascii=False, indent=2, default=str)


def _build_external_runner_execution_artifact(
    *,
    skill_name: str,
    runner_name: str,
    request_invocation_id: str,
    execution: dict[str, Any],
    metadata: dict[str, Any],
) -> str:
    payload = {
        "skill_name": skill_name,
        "runner_name": runner_name,
        "request_invocation_id": request_invocation_id,
        "execution": execution,
        "metadata": metadata,
        "will_execute": True,
        "dispatch_note": "本产物表示已通过受控 executor 执行固定白名单 runner。",
    }
    return json.dumps(_redact_sensitive_payload(payload), ensure_ascii=False, indent=2, default=str)


def _run_safe_external_runner(
    *,
    runner_name: str,
    skill_name: str,
    request_invocation_id: str,
    parameters: dict[str, Any],
    timeout_seconds: int,
) -> dict[str, Any]:
    spec = SAFE_EXTERNAL_RUNNER_COMMANDS.get(runner_name)
    if not spec:
        raise ValueError(f"runner {runner_name} 不在系统固定命令白名单内")
    command = [str(part) for part in spec.get("command") or []]
    if not command:
        raise ValueError(f"runner {runner_name} 缺少固定命令")
    cwd = Path(spec.get("cwd") or (REPO_ROOT / "01-system-core")).resolve()
    core_root = (REPO_ROOT / "01-system-core").resolve()
    if not _is_path_inside(cwd, core_root):
        raise ValueError("外部 runner cwd 超出 01-system-core 路径边界")

    payload = {
        "skill_name": skill_name,
        "runner_name": runner_name,
        "request_invocation_id": request_invocation_id,
        "parameters": _redact_sensitive_payload(parameters),
    }
    started_at = datetime.now()
    try:
        completed = subprocess.run(
            command,
            input=json.dumps(payload, ensure_ascii=False, default=str),
            text=True,
            cwd=str(cwd),
            env=_safe_external_runner_env(core_root),
            shell=False,
            capture_output=True,
            timeout=timeout_seconds,
            check=False,
        )
        duration_ms = max(0, int((datetime.now() - started_at).total_seconds() * 1000))
        stdout, stdout_truncated = _truncate_stdio(completed.stdout or "")
        stderr, stderr_truncated = _truncate_stdio(completed.stderr or "")
        return {
            "status": "success" if completed.returncode == 0 else "failed",
            "returncode": completed.returncode,
            "timed_out": False,
            "duration_ms": duration_ms,
            "stdout": stdout,
            "stderr": stderr,
            "stdout_truncated": stdout_truncated,
            "stderr_truncated": stderr_truncated,
            "command_key": runner_name,
        }
    except subprocess.TimeoutExpired as exc:
        duration_ms = max(0, int((datetime.now() - started_at).total_seconds() * 1000))
        stdout, stdout_truncated = _truncate_stdio(exc.stdout or "")
        stderr, stderr_truncated = _truncate_stdio(exc.stderr or "")
        return {
            "status": "timeout",
            "returncode": None,
            "timed_out": True,
            "duration_ms": duration_ms,
            "stdout": stdout,
            "stderr": stderr,
            "stdout_truncated": stdout_truncated,
            "stderr_truncated": stderr_truncated,
            "command_key": runner_name,
        }


def _safe_external_runner_env(core_root: Path) -> dict[str, str]:
    return {
        "PATH": os.environ.get("PATH", ""),
        "PYTHONPATH": str(core_root),
        "LANG": os.environ.get("LANG", "C.UTF-8"),
        "LC_ALL": os.environ.get("LC_ALL", "C.UTF-8"),
    }


def _truncate_stdio(raw: str) -> tuple[str, bool]:
    text = _redact_text(str(raw or ""))
    if len(text) <= MAX_EXTERNAL_RUNNER_STDIO_CHARS:
        return text, False
    return text[:MAX_EXTERNAL_RUNNER_STDIO_CHARS] + "\n[TRUNCATED]", True


def _redact_text(raw: str) -> str:
    marker_pattern = "|".join(re.escape(marker) for marker in SENSITIVE_FIELD_MARKERS)
    return re.sub(
        rf"(?i)((?:{marker_pattern})[\"']?\s*[:=]\s*[\"']?)([^\"'\s,}}]+)",
        r"\1[REDACTED]",
        raw,
    )


def _external_runner_output_summary(result: dict[str, Any]) -> str:
    status = result.get("status")
    if status == "success":
        return "受控外部 Skill runner 执行成功，已记录 stdout/stderr 截断摘要。"
    if status == "timeout":
        return "受控外部 Skill runner 执行超时，已记录 timeout 状态。"
    return "受控外部 Skill runner 执行失败，已记录退出码和截断输出。"


def _load_external_runner_request_payload(artifact: SkillArtifact | None) -> dict[str, Any]:
    if not artifact or artifact.artifact_type != "external_runner_request":
        raise ValueError("外部 runner 请求缺少 external_runner_request 产物")
    payload = _json_loads(artifact.content, {})
    if not isinstance(payload, dict) or payload.get("will_execute") is not False:
        raise ValueError("外部 runner 请求产物格式无效")
    return payload


def _mark_external_runner_request_executed(
    db: Session,
    request: SkillInvocation,
    invocation: dict[str, Any],
    artifact: dict[str, Any],
    execution: dict[str, Any],
) -> None:
    metadata = _json_loads(request.metadata_json, {})
    metadata.update({
        "execution_status": execution.get("status"),
        "execution_invocation_id": invocation["id"],
        "execution_artifact_id": artifact["id"],
        "execution_finished_at": datetime.now().isoformat(),
    })
    request.metadata_json = json.dumps(metadata, ensure_ascii=False, default=str)
    db.commit()
    db.refresh(request)


def _find_existing_external_runner_execution(db: Session, request_invocation_id: str) -> bool:
    rows = (
        db.query(SkillInvocation)
        .filter(SkillInvocation.failure_type == "external_skill_runner_execute")
        .order_by(SkillInvocation.created_at.desc())
        .limit(200)
        .all()
    )
    for row in rows:
        metadata = _json_loads(row.metadata_json, {})
        if metadata.get("request_invocation_id") == request_invocation_id:
            return True
    return False


def _resolve_external_runner_binding(db: Session, skill: SkillRegistry, binding_id: str = "") -> SkillBinding | None:
    if binding_id:
        binding = db.query(SkillBinding).filter(SkillBinding.id == binding_id).first()
        if not binding:
            raise ValueError(f"Skill binding {binding_id} 不存在")
        if binding.skill_name != skill.name:
            raise ValueError("外部 runner 绑定与 skill_name 不匹配")
        if binding.status != "active" or not bool(binding.is_enabled):
            raise ValueError("外部 runner 绑定未启用")
        return binding

    rows = (
        db.query(SkillBinding)
        .filter(
            SkillBinding.skill_name == skill.name,
            SkillBinding.status == "active",
            SkillBinding.is_enabled == True,  # noqa: E712
        )
        .order_by(SkillBinding.priority.asc(), SkillBinding.updated_at.desc())
        .all()
    )
    for row in rows:
        config = _json_loads(row.config_json, {})
        if isinstance(config, dict) and _as_dict(config.get("external_runner")).get("enabled") is True:
            return row
    return None


def _external_runner_policy(skill: SkillRegistry, binding: SkillBinding | None) -> dict[str, Any]:
    skill_metadata = _json_loads(skill.metadata_json, {})
    skill_policy = _as_dict(_as_dict(skill_metadata).get("external_runner"))
    binding_config = _json_loads(binding.config_json, {}) if binding else {}
    binding_policy = _as_dict(_as_dict(binding_config).get("external_runner"))
    policy = {**skill_policy, **binding_policy}
    allowed_parameters = policy.get("allowed_parameters") or policy.get("allowed_params") or []
    if not isinstance(allowed_parameters, list):
        allowed_parameters = []
    allowed_runners = policy.get("allowed_runners") or policy.get("runner_whitelist") or []
    if not isinstance(allowed_runners, list):
        allowed_runners = []
    param_schema = _as_dict(policy.get("param_schema"))
    required_parameters = list(policy.get("required_parameters") or [])
    for key, spec in param_schema.items():
        if isinstance(spec, dict) and spec.get("required") is True and key not in required_parameters:
            required_parameters.append(key)
    max_timeout = _safe_int(
        policy.get("max_timeout_seconds"),
        default=MAX_EXTERNAL_RUNNER_TIMEOUT_SECONDS,
        minimum=1,
        maximum=MAX_EXTERNAL_RUNNER_TIMEOUT_SECONDS,
    )
    default_timeout = _safe_int(
        policy.get("timeout_seconds"),
        default=DEFAULT_EXTERNAL_RUNNER_TIMEOUT_SECONDS,
        minimum=1,
        maximum=max_timeout,
    )
    return {
        "enabled": policy.get("enabled") is True,
        "execution_enabled": policy.get("execution_enabled") is True,
        "requires_confirmation": policy.get("requires_confirmation", True) is not False,
        "allowed_parameters": [str(item).strip() for item in allowed_parameters if str(item).strip()],
        "allowed_runners": [str(item).strip() for item in allowed_runners if str(item).strip()],
        "required_parameters": [str(item).strip() for item in required_parameters if str(item).strip()],
        "param_schema": param_schema,
        "timeout_seconds": default_timeout,
        "max_timeout_seconds": max_timeout,
        "max_payload_chars": _safe_int(
            policy.get("max_payload_chars"),
            default=MAX_EXTERNAL_RUNNER_PAYLOAD_CHARS,
            minimum=100,
            maximum=MAX_EXTERNAL_RUNNER_PAYLOAD_CHARS,
        ),
    }


def _validate_external_runner_name(runner_name: str, policy: dict[str, Any]) -> None:
    allowed_runners = set(policy.get("allowed_runners") or [])
    if not allowed_runners:
        raise ValueError("外部 runner 执行未配置固定 runner 白名单")
    if runner_name not in allowed_runners:
        raise ValueError(f"runner {runner_name} 不在绑定白名单内")
    if runner_name not in SAFE_EXTERNAL_RUNNER_COMMANDS:
        raise ValueError(f"runner {runner_name} 不在系统固定命令白名单内")


def _validate_external_runner_parameters(parameters: dict[str, Any], policy: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(parameters, dict):
        raise ValueError("外部 runner parameters 必须是 JSON 对象")
    allowed = set(policy["allowed_parameters"])
    if not allowed and parameters:
        raise ValueError("外部 runner 未配置参数白名单，不能传入 parameters")
    normalized: dict[str, Any] = {}
    for raw_key, value in parameters.items():
        key = str(raw_key or "").strip()
        if key not in allowed:
            raise ValueError(f"参数 {key} 不在外部 runner 白名单内")
        spec = _as_dict(policy["param_schema"].get(key))
        normalized[key] = _validate_external_runner_value(key, value, spec, int(policy["max_payload_chars"]))
    for required_key in policy["required_parameters"]:
        if required_key not in normalized or normalized[required_key] in ("", None):
            raise ValueError(f"缺少外部 runner 必填参数 {required_key}")
    return normalized


def _validate_external_runner_value(key: str, value: Any, spec: dict[str, Any], max_payload_chars: int) -> Any:
    expected_type = str(spec.get("type") or spec.get("kind") or "").strip()
    if expected_type == "string" and not isinstance(value, str):
        raise ValueError(f"参数 {key} 必须是 string")
    if expected_type == "integer" and (isinstance(value, bool) or not isinstance(value, int)):
        raise ValueError(f"参数 {key} 必须是 integer")
    if expected_type == "number" and (isinstance(value, bool) or not isinstance(value, (int, float))):
        raise ValueError(f"参数 {key} 必须是 number")
    if expected_type == "boolean" and not isinstance(value, bool):
        raise ValueError(f"参数 {key} 必须是 boolean")
    if expected_type == "array" and not isinstance(value, list):
        raise ValueError(f"参数 {key} 必须是 array")
    if expected_type == "object" and not isinstance(value, dict):
        raise ValueError(f"参数 {key} 必须是 object")

    if isinstance(value, str):
        max_length = _safe_int(spec.get("max_length"), default=4000, minimum=1, maximum=max_payload_chars)
        if len(value) > max_length:
            raise ValueError(f"参数 {key} 超过 max_length {max_length}")
    if isinstance(value, list):
        max_items = _safe_int(spec.get("max_items"), default=50, minimum=0, maximum=500)
        if len(value) > max_items:
            raise ValueError(f"参数 {key} 超过 max_items {max_items}")

    encoded = json.dumps(value, ensure_ascii=False, default=str)
    if len(encoded) > max_payload_chars:
        raise ValueError(f"参数 {key} 超过外部 runner payload 上限")
    return value


def _validate_external_runner_timeout(timeout_seconds: int | None, policy: dict[str, Any]) -> int:
    max_timeout = int(policy["max_timeout_seconds"])
    if timeout_seconds is None:
        return int(policy["timeout_seconds"])
    parsed = _safe_int(timeout_seconds, default=int(policy["timeout_seconds"]), minimum=1, maximum=MAX_EXTERNAL_RUNNER_TIMEOUT_SECONDS)
    if parsed > max_timeout:
        raise ValueError(f"timeout_seconds 不能超过 {max_timeout}")
    return parsed


def _redact_sensitive_payload(value: Any) -> Any:
    if isinstance(value, dict):
        redacted: dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key)
            if _is_sensitive_field(key_text):
                redacted[key_text] = "[REDACTED]"
            else:
                redacted[key_text] = _redact_sensitive_payload(item)
        return redacted
    if isinstance(value, list):
        return [_redact_sensitive_payload(item) for item in value]
    return value


def _is_sensitive_field(key: str) -> bool:
    lowered = key.lower()
    return any(marker in lowered for marker in SENSITIVE_FIELD_MARKERS)


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _is_path_inside(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _skill_by_name(catalog: list[dict[str, Any]] | None = None) -> dict[str, dict[str, Any]]:
    return {
        str(item.get("name")): item
        for item in (catalog if catalog is not None else get_skill_catalog())
        if isinstance(item.get("name"), str)
    }


def _build_stage(stage_key: str, index: dict[str, dict[str, Any]]) -> dict[str, Any]:
    base = SKILL_STAGE_LIBRARY[stage_key]
    skills: list[dict[str, Any]] = []
    for skill_name in base["skill_names"]:
        info = index.get(skill_name, {"name": skill_name, "source": "", "target": ""})
        skills.append(
            {
                "name": skill_name,
                "source": info.get("source", ""),
                "target": info.get("target", ""),
                "upstream_repo": info.get("upstream_repo", ""),
                "category": info.get("category", ""),
                "why": info.get("why", ""),
            }
        )
    return {
        "stage": stage_key,
        "title": base["title"],
        "why": base["why"],
        "action_hint": base["action_hint"],
        "skills": skills,
    }


def recommend_skill_workflow(
    *,
    failure_type: str = "",
    blocking_issues: list[str] | None = None,
    warnings: list[str] | None = None,
    context: str = "",
    db: Session | None = None,
) -> dict[str, Any]:
    failure_key = str(failure_type or "").strip() or "default"
    recipe = FAILURE_STAGE_RECIPES.get(failure_key) or FAILURE_STAGE_RECIPES["default"]
    catalog = get_db_skill_catalog(db) if db is not None else get_skill_catalog()
    index = _skill_by_name(catalog)
    stages = [_build_stage(stage_key, index) for stage_key in recipe]
    matched_bindings = (
        resolve_skill_bindings(db, failure_type=failure_key, context=context, limit=20)
        if db is not None
        else []
    )

    next_actions: list[str] = []
    if stages:
        next_actions.append(f"先执行“{stages[0]['title']}”阶段，不要直接跳到写补丁。")
    for stage in stages:
        next_actions.append(f"{stage['title']}：{stage['action_hint']}")
    if blocking_issues:
        next_actions.append("优先围绕阻断项修复，提醒项留到阻断解除后处理。")
    if warnings and not blocking_issues:
        next_actions.append("当前以提醒项为主，优先做状态对齐和轻量修复。")

    unique_skills: list[dict[str, Any]] = []
    seen: set[str] = set()
    for stage in stages:
        for skill in stage["skills"]:
            name = str(skill.get("name") or "")
            if not name or name in seen:
                continue
            seen.add(name)
            unique_skills.append(skill)
    for binding in matched_bindings:
        name = str(binding.get("skill_name") or "")
        if not name or name in seen:
            continue
        seen.add(name)
        info = index.get(name, {"name": name})
        unique_skills.append({
            "name": name,
            "source": info.get("source", ""),
            "target": info.get("target", ""),
            "upstream_repo": info.get("upstream_repo", ""),
            "category": info.get("category", ""),
            "why": info.get("why", ""),
            "binding": binding,
        })

    return {
        "context": context or "general",
        "failure_type": failure_key,
        "blocking_issue_count": len(blocking_issues or []),
        "warning_count": len(warnings or []),
        "catalog_source": "database" if db is not None else "manifest",
        "matched_bindings": matched_bindings,
        "stages": stages,
        "recommended_skills": unique_skills,
        "next_actions": next_actions,
    }


def _apply_manifest_skill(row: SkillRegistry, item: dict[str, Any], payload_hash: str, synced_at: datetime) -> None:
    row.display_name = str(item.get("display_name") or item.get("name") or row.name)
    row.description = str(item.get("description") or "")
    row.source = str(item.get("source") or "")
    row.target = str(item.get("target") or "")
    row.upstream_repo = str(item.get("upstream_repo") or "")
    row.category = str(item.get("category") or "")
    row.recommended_for_json = json.dumps(item.get("recommended_for") or [], ensure_ascii=False)
    row.why = str(item.get("why") or "")
    row.mode = str(item.get("mode") or "")
    row.status = "active"
    row.is_enabled = True
    row.version = int(row.version or 1)
    row.manifest_hash = payload_hash
    row.metadata_json = json.dumps(
        {
            "source_kind": "manifest",
            "manifest_path": str(MANIFEST_PATH),
            "raw": item,
        },
        ensure_ascii=False,
        default=str,
    )
    row.synced_at = synced_at


def _skill_manifest_hash(item: dict[str, Any]) -> str:
    payload = json.dumps(item, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _build_feedback_priority_hint(item: dict[str, Any], min_feedback: int) -> dict[str, Any]:
    count = int(item.get("feedback_count") or 0)
    average = float(item.get("average_score") or 0)
    useful_rate = float(item.get("useful_rate") or 0)
    negative_rate = float(item.get("negative_rate") or 0)
    verdict_counts = item.get("verdict_counts") if isinstance(item.get("verdict_counts"), dict) else {}
    failure_breakdown = item.get("failure_type_breakdown") if isinstance(item.get("failure_type_breakdown"), list) else []
    failure_type = ""
    if failure_breakdown:
        first = failure_breakdown[0]
        if isinstance(first, dict):
            failure_type = str(first.get("failure_type") or "").strip()

    binding_type = "failure_type" if failure_type else "global"
    binding_key = failure_type if failure_type else ""
    if count < min_feedback:
        return {
            "action": "observe",
            "suggested_priority_delta": 0,
            "binding_type": binding_type,
            "binding_key": binding_key,
            "reason": f"反馈样本 {count} 条，未达到 {min_feedback} 条阈值，先继续观察。",
        }
    if negative_rate >= 0.4 or average < 50:
        return {
            "action": "demote",
            "suggested_priority_delta": 20,
            "binding_type": binding_type,
            "binding_key": binding_key,
            "reason": "低分或阻断反馈占比较高，建议降低默认触发优先级并复核绑定条件。",
        }
    if average >= 85 and useful_rate >= 0.6:
        return {
            "action": "promote",
            "suggested_priority_delta": -10,
            "binding_type": binding_type,
            "binding_key": binding_key,
            "reason": "高分且 useful 占比较高，适合提升对应失败类型的默认触发优先级。",
        }
    if int(verdict_counts.get("needs_followup", 0) or 0) > 0:
        return {
            "action": "review",
            "suggested_priority_delta": 5,
            "binding_type": binding_type,
            "binding_key": binding_key,
            "reason": "存在 needs_followup 反馈，建议先复核执行产物和绑定范围。",
        }
    return {
        "action": "hold",
        "suggested_priority_delta": 0,
        "binding_type": binding_type,
        "binding_key": binding_key,
        "reason": "当前反馈稳定但未达到提升或降级阈值，维持现有优先级。",
    }


def _json_loads(raw: str | None, default: Any) -> Any:
    if not raw:
        return default
    try:
        return json.loads(raw)
    except Exception:
        return default


def _get_skill_by_name(db: Session, skill_name: str) -> SkillRegistry:
    normalized = str(skill_name or "").strip()
    if not normalized:
        raise ValueError("skill_name 不能为空")
    skill = db.query(SkillRegistry).filter(SkillRegistry.name == normalized).first()
    if skill is None and db.query(SkillRegistry.id).limit(1).first() is None:
        sync_skill_manifest_to_db(db)
        skill = db.query(SkillRegistry).filter(SkillRegistry.name == normalized).first()
    if not skill:
        raise ValueError(f"Skill {normalized} 不存在")
    return skill


def _normalize_binding_type(binding_type: str) -> str:
    normalized = str(binding_type or "").strip()
    if normalized not in VALID_BINDING_TYPES:
        raise ValueError(f"无效 binding_type '{binding_type}'，可选: {', '.join(sorted(VALID_BINDING_TYPES))}")
    return normalized


def _normalize_invocation_status(status: str) -> str:
    normalized = str(status or "").strip()
    if normalized not in VALID_INVOCATION_STATUSES:
        raise ValueError(f"无效 invocation status '{status}'，可选: {', '.join(sorted(VALID_INVOCATION_STATUSES))}")
    return normalized


def _normalize_status(status: str) -> str:
    normalized = str(status or "").strip()
    if normalized not in {"active", "archived"}:
        raise ValueError("status 只能是 active 或 archived")
    return normalized


def _normalize_feedback_verdict(verdict: str) -> str:
    normalized = str(verdict or "").strip()
    if normalized not in VALID_FEEDBACK_VERDICTS:
        raise ValueError(f"无效 feedback verdict '{verdict}'，可选: {', '.join(sorted(VALID_FEEDBACK_VERDICTS))}")
    return normalized


def _safe_int(value: Any, *, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except Exception:
        parsed = default
    return max(minimum, min(parsed, maximum))
