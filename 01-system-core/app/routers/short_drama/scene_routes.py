"""测试页 “生成剧本片段 + 流式生成剧本片段” 路由（从 short_drama_writing.py 抽出）。

2 个路由：

- POST /testing/script-scene         —— 同步生成（含内部审段 + 自动修复闭环）
- POST /testing/script-scene/stream  —— SSE 流式生成（带 progress/token/done/error 事件）

主 router 用 include_router 聚合，URL 不变。
"""
from __future__ import annotations

import asyncio
import json
import re
import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.auth.dependencies import ProjectAccessActor, verify_project_actor
from app import database
from app.database import get_db
from app.models.project_v2 import ProjectV2
from app.models.short_drama_generation_job import ShortDramaGenerationJob
from app.routers.short_drama._billing import (
    charge_short_drama_usage,
    ensure_short_drama_project_access,
    record_short_drama_failure,
)
from app.schemas.short_drama_writing import (
    BenchmarkAssessment,
    ContinuityAssessment,
    TestingScriptRequest,
    TestingScriptResponse,
)
from app.services.short_drama_advanced_generation import resolve_testing_generation_route
from app.services.short_drama_director_blueprint import director_blueprint_hashes
from app.services.short_drama_evaluation_pipeline import apply_scene_level_gate
from app.services.short_drama_final_generation_contract import current_testing_final_generation_contract
from app.services.short_drama_generation_source_packet import GenerationSourceBlocked
from app.services.short_drama_job_recovery import (
    find_reusable_active_script_scene_job,
    mark_orphan_candidate_job_failed_if_needed,
    recover_stale_script_scene_job_if_needed,
)
from app.services.short_drama_rag_injection import apply_rag_injection
from app.services.short_drama_testing_enrich import (
    PreviousOfficialSourceGateError,
    enrich_testing_request_from_project,
)
from app.services.short_drama_atomic_generation import (
    AtomicRouteConfigError,
    DEFAULT_CANDIDATE_FORMAL_MAX_CHARS,
    DEFAULT_CANDIDATE_FORMAL_MIN_CHARS,
    PUBLIC_CANDIDATE_READY,
    PUBLIC_MODEL_RECOVERY_EXHAUSTED,
    PUBLIC_PROGRESS_GENERATING,
    SCRIPT_GENERATION_JOB_CANDIDATE_REVIEW_REQUIRED,
    SCRIPT_GENERATION_JOB_BLOCKED,
    SCRIPT_GENERATION_JOB_CANDIDATE_READY,
    SCRIPT_GENERATION_JOB_FAILED,
    SCRIPT_GENERATION_JOB_RUNNING,
    SINGLE_EPISODE_TIME_BUDGET,
    ScriptGenerationJobState,
    classify_candidate_delivery,
    normalize_research_script_request,
    run_research_script_generation,
    stable_hash,
)
from app.services.short_drama_text_format import count_testing_chars, hard_truncate_by_sentence
from app.services.c19_178_safe_label_gate import C19178GateBlocked, assert_c19_178_runtime_gate
from app.services.text_generation_service import (
    TextGenerationError,
    begin_usage_collection,
    build_provider_runtime_observability,
    end_usage_collection,
)

router = APIRouter()  # 由主 router 加 prefix

SINGLE_EPISODE_TARGET_SECONDS = 300
SINGLE_EPISODE_STAGE_TARGET_SECONDS = 150
SINGLE_EPISODE_TIMEOUT_SECONDS = 600
SCRIPT_SCENE_RUNNING_STALE_AFTER_SECONDS = 900

_SCRIPT_SCENE_JOB_TASKS: set[asyncio.Task] = set()

TEXT_GENERATION_FAILED_SUBTYPE = "text_generation_failed"
TEXT_GENERATION_EMPTY_CANDIDATE_SUBTYPE = "text_generation_empty_candidate"
TEXT_GENERATION_INVALID_CANDIDATE_SUBTYPE = "text_generation_invalid_candidate"
TEXT_GENERATION_TIMEOUT_SUBTYPE = "text_generation_timeout"
TEXT_GENERATION_NETWORK_ERROR_SUBTYPE = "text_generation_network_error"
TEXT_GENERATION_UNKNOWN_SUBTYPE = "text_generation_unknown"


def _assert_c19_178_short_drama_episode_generation_gate(
    db: Session,
    project_id: str,
) -> None:
    normalized_project_id = str(project_id or "").strip()
    if not normalized_project_id:
        return
    project = db.query(ProjectV2).filter(ProjectV2.id == normalized_project_id).first()
    if project is None:
        return
    try:
        assert_c19_178_runtime_gate(db, project=project, target_path="episode5_entry")
    except C19178GateBlocked as exc:
        raise HTTPException(status_code=409, detail=exc.decision.reason_code) from exc


def _previous_official_source_gate_payload(exc: PreviousOfficialSourceGateError) -> dict[str, Any]:
    return {
        "error_code": exc.reason_code,
        "stage": "previous_locked_official_source_gate",
        "target_episode_no": exc.target_episode_no,
        "previous_episode_no": exc.previous_episode_no,
        "retryable": False,
        "suggestion": "请先完成上一集锁稿，确保下一集只承接直接上一集的官方锁定版本。",
    }


def generate_research_script_candidate(
    req: TestingScriptRequest,
    *,
    step_observer=None,
) -> dict[str, Any]:
    return run_research_script_generation(req, step_observer=step_observer)


def _ensure_testing_generation_access(
    db: Session,
    req: TestingScriptRequest,
    actor: ProjectAccessActor,
) -> None:
    ensure_short_drama_project_access(db, req.project_id, actor, require_credit=True)


def _charge_testing_generation(
    db: Session,
    req: TestingScriptRequest,
    actor: ProjectAccessActor,
    usage_metrics: dict[str, Any],
) -> None:
    charge_short_drama_usage(
        db,
        actor,
        usage_metrics,
        provider=str(req.generation_provider or ""),
        model=str(req.generation_model or ""),
        generation_type="testing_script_scene",
        reason="测试页剧本片段生成成功扣费",
    )


def _record_testing_generation_failure(
    db: Session,
    req: TestingScriptRequest,
    actor: ProjectAccessActor,
    exc: Exception,
) -> None:
    record_short_drama_failure(
        db,
        actor,
        provider=str(req.generation_provider or ""),
        model=str(req.generation_model or ""),
        generation_type="testing_script_scene",
        reason=f"测试页剧本片段生成失败，未扣费：{exc}",
    )


def _generation_trace(req: TestingScriptRequest, director_blueprint: dict[str, Any] | None = None) -> dict[str, Any]:
    routes: list[dict[str, Any]] = []
    for step_id in ("director_blueprint", "script_draft", "quality_check"):
        route = resolve_testing_generation_route(req, step_id)
        routes.append({
            "step_id": step_id,
            "role": route.role,
            "role_label": route.role_label,
            "provider": route.generation_kwargs.get("provider", ""),
            "model": route.generation_kwargs.get("model", ""),
            "temperature": route.temperature,
            "enabled": route.enabled,
        })
    blueprint = director_blueprint if isinstance(director_blueprint, dict) else {}
    if not blueprint:
        blueprint = req.director_blueprint if isinstance(req.director_blueprint, dict) else {}
    return {
        "mode": "research_generation",
        "advanced_generation_mode": True,
        "routes": routes,
        "director_blueprint": director_blueprint_hashes(blueprint),
        "single_episode_time_budget": {
            "target_seconds": SINGLE_EPISODE_TARGET_SECONDS,
            "stage_target_seconds": SINGLE_EPISODE_STAGE_TARGET_SECONDS,
            "timeout_seconds": SINGLE_EPISODE_TIMEOUT_SECONDS,
        },
        "public_progress_contract": {
            "hide_internal_model_details": True,
            "user_visible_route_count": 1,
        },
    }


def _sse_event(event: str, data: Any) -> str:
    payload = json.dumps(data, ensure_ascii=False) if not isinstance(data, str) else data
    return f"event: {event}\ndata: {payload}\n\n"


def _text_generation_error_payload(exc: TextGenerationError) -> dict[str, Any]:
    provider_observability = build_provider_runtime_observability(exc)
    return {
        "error_code": exc.code,
        "detail": exc.user_message,
        "suggestion": exc.suggestion,
        "retryable": exc.code in {"network_error", "upstream_error", "rate_limited", "generation_failed"},
        "stage": "text_generation",
        "safe_failure_subtype": provider_observability["safe_failure_subtype"],
        "provider_observability": provider_observability,
    }


def _http_error_payload(exc: HTTPException) -> dict[str, Any]:
    detail = exc.detail
    if isinstance(detail, dict):
        payload = dict(detail)
    else:
        payload = {
            "error_code": "http_error",
            "detail": str(detail or "请求失败。"),
        }
    payload.setdefault("error_code", "http_error")
    payload.setdefault("detail", str(detail or "请求失败。"))
    payload.setdefault("suggestion", "请稍后重试；如果连续失败，请联系管理员查看后台日志。")
    payload.setdefault("retryable", exc.status_code >= 500 or exc.status_code in {408, 409, 429})
    payload.setdefault("stage", "script_scene_request")
    payload.setdefault("http_status", exc.status_code)
    return payload


def _empty_generation_payload(exc: Exception) -> dict[str, Any]:
    return {
        "error_code": "empty_generation",
        "detail": str(exc) or "模型没有返回可用正文，本次未扣费。",
        "suggestion": "请点击重试；如果连续失败，请检查后台 LLM 配置、模型返回格式和大纲/角色输入是否完整。",
        "retryable": True,
        "stage": "content_validation",
    }


def _resolve_testing_output_or_raise(approved: dict[str, Any]) -> tuple[str, int]:
    content = str((approved or {}).get("content") or "").strip()
    char_count = int((approved or {}).get("char_count_excluding_punctuation") or 0)
    if content and char_count <= 0:
        char_count = len(re.sub(r"[\s，。！？、,.!?:：；;\"'“”‘’（）()\[\]【】《》<>-]", "", content))
    if not content or char_count <= 0:
        raise ValueError("模型没有返回可用剧本正文，系统已拦截成功日志并且未扣费。")
    return content, char_count


def _quality_gate_error_payload(req: TestingScriptRequest, approved: dict[str, Any]) -> dict[str, Any]:
    blocking_issues = [str(item or "").strip() for item in (approved.get("blocking_issues") or []) if str(item or "").strip()]
    quality_issues = [str(item or "").strip() for item in (approved.get("quality_issues") or []) if str(item or "").strip()]
    detail_items = blocking_issues or quality_issues
    failure_analysis = approved.get("failure_analysis") or {}
    if hasattr(failure_analysis, "model_dump"):
        try:
            failure_analysis = failure_analysis.model_dump()
        except Exception:
            failure_analysis = {}
    return {
        "error_code": "quality_gate_failed",
        "detail": "；".join(detail_items[:3]) or "内部审段未通过。",
        "suggestion": "可点击重试此段。若连续失败，请补充角色/大纲信息，或降低本段字数目标后再试。",
        "retryable": True,
        "stage": "script_scene_quality_gate",
        "segment_id": str(req.segment_id or ""),
        "episode_no": int(req.episode_no or 0),
        "scene_no": int(req.scene_no or 0),
        "blocking_issues": blocking_issues,
        "quality_issues": quality_issues,
        "warnings": [str(item or "").strip() for item in (approved.get("warnings") or []) if str(item or "").strip()],
        "failure_analysis": failure_analysis if isinstance(failure_analysis, dict) else {},
        "char_count_excluding_punctuation": int(approved.get("char_count_excluding_punctuation") or 0),
    }


def _internal_error_payload(exc: Exception) -> dict[str, Any]:
    return {
        "error_code": "internal_error",
        "detail": f"测试页流式生成失败：{type(exc).__name__}: {str(exc)[:260]}",
        "suggestion": "请重试；若仍失败，请把这条错误发给管理员定位后台日志。",
        "retryable": True,
        "stage": "script_scene_stream",
    }


def _build_script_scene_rag_variables(req: TestingScriptRequest) -> dict[str, Any]:
    selected_ids = {str(item) for item in (req.selected_character_ids or []) if str(item).strip()}
    character_names = [
        str(char.get("name") or "").strip()
        for char in (req.characters or [])
        if isinstance(char, dict)
        and str(char.get("name") or "").strip()
        and (not selected_ids or str(char.get("id") or "") in selected_ids)
    ]
    return {
        "project_type": req.project_type,
        "format_type": req.format_type,
        "audience_axis": req.audience_axis,
        "genre_main": req.genre_main,
        "genre_sub": req.genre_sub,
        "subgenre_track": req.subgenre_track,
        "sample_track": req.sample_track,
        "brief": req.brief,
        "episode_summary": req.episode_summary,
        "episode_conflict": req.episode_conflict,
        "episode_hook": req.episode_hook,
        "character_names": "、".join(character_names[:6]),
        "episode_minutes": str(req.episode_minutes or ""),
        "word_count_min": str(req.word_count_min or ""),
        "word_count_max": str(req.word_count_max or ""),
        "word_count_target": str(req.word_count_target or ""),
        "draft_episode": str(req.episode_no or ""),
        "rag_script_references": req.rag_script_references or "",
        "rag_asset_references": req.rag_asset_references or "",
        "rag_market_signals": req.rag_market_signals or "",
        "rag_novel_chapters": req.rag_novel_chapters or "",
    }


def _apply_rag_into_request(req: TestingScriptRequest, variables: dict[str, Any]) -> TestingScriptRequest:
    return req.model_copy(update={
        "rag_script_references": str(req.rag_script_references or variables.get("rag_script_references") or ""),
        "rag_asset_references": str(req.rag_asset_references or variables.get("rag_asset_references") or ""),
        "rag_market_signals": str(req.rag_market_signals or variables.get("rag_market_signals") or ""),
        "rag_novel_chapters": str(req.rag_novel_chapters or variables.get("rag_novel_chapters") or ""),
    })


def _actor_from_job(job: ShortDramaGenerationJob) -> ProjectAccessActor:
    if bool(job.owner_is_admin):
        return ProjectAccessActor(actor_type="admin")
    return ProjectAccessActor(actor_type="user", access_key_id=str(job.owner_key or ""))


def _job_request_from_json(job: ShortDramaGenerationJob) -> TestingScriptRequest:
    try:
        payload = json.loads(job.request_json or "{}")
    except Exception:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    return TestingScriptRequest(**payload)


def _job_request_segment_id(job: ShortDramaGenerationJob) -> str:
    try:
        payload = json.loads(job.request_json or "{}")
    except Exception:
        payload = {}
    if not isinstance(payload, dict):
        return ""
    return str(payload.get("segment_id") or "").strip()


def _job_request_final_generation_contract(job: ShortDramaGenerationJob) -> dict[str, Any]:
    try:
        payload = json.loads(job.request_json or "{}")
    except Exception:
        payload = {}
    if not isinstance(payload, dict):
        return {}
    contract = payload.get("final_generation_contract")
    return contract if isinstance(contract, dict) else {}


def _existing_generation_source_observability(job: ShortDramaGenerationJob) -> dict[str, Any]:
    try:
        internal = json.loads(job.internal_json or "{}")
    except Exception:
        internal = {}
    if not isinstance(internal, dict):
        return {}
    preserved: dict[str, Any] = {}
    for key in ("generation_source_safe_summary", "ready_guard_passed"):
        if key in internal:
            preserved[key] = internal[key]
    return preserved


def _safe_text_generation_failure_subtype(exc: Exception | None) -> str:
    code = str(getattr(exc, "code", "") or "").lower()
    text = f"{code} {type(exc).__name__} {str(exc)}".lower()
    if "read" in text and "timeout" in text:
        return "read_timeout"
    if "connect" in text and "timeout" in text:
        return "connect_timeout"
    if "timeout" in text or "timed" in text:
        return TEXT_GENERATION_TIMEOUT_SUBTYPE
    if "network" in text or "connection" in text or "connect" in text:
        return TEXT_GENERATION_NETWORK_ERROR_SUBTYPE
    if "empty" in text or "blank" in text:
        return TEXT_GENERATION_EMPTY_CANDIDATE_SUBTYPE
    if "invalid" in text or "format" in text or "parse" in text:
        return TEXT_GENERATION_INVALID_CANDIDATE_SUBTYPE
    if code:
        return TEXT_GENERATION_FAILED_SUBTYPE
    return TEXT_GENERATION_UNKNOWN_SUBTYPE


_SAFE_TEXT_GENERATION_OBSERVABILITY_FIELDS = (
    "text_generation_detail_category",
    "text_generation_failure_family",
    "text_generation_failure_source",
    "exception_class_safe",
    "provider_call_boundary",
    "candidate_delivery_state",
    "safe_failure_observation_version",
    "text_generation_unknown_reason",
    "text_generation_stage",
    "terminal_write_reason",
    "failure_observed_at",
    "http_status_bucket",
    "timeout_bucket",
    "retry_count_bucket",
)


def _safe_exception_class_name(exc: Exception | None) -> str:
    name = type(exc).__name__ if exc is not None else ""
    return name if re.match(r"^[A-Za-z][A-Za-z0-9_]{0,80}$", name) else "UnknownException"


def _safe_http_status_bucket(exc: Exception | None) -> str:
    code = str(getattr(exc, "code", "") or "").lower()
    if code in {"auth_failed", "rate_limited", "context_too_long"}:
        return "4xx"
    if code == "upstream_error":
        return "5xx"
    return "none"


def _safe_timeout_bucket(exc: Exception | None) -> str:
    text = f"{getattr(exc, 'code', '')} {type(exc).__name__} {str(exc)}".lower()
    if "timeout" not in text and "timed" not in text:
        return "none"
    return "unknown"


def _safe_text_generation_detail_category(exc: Exception | None) -> str:
    code = str(getattr(exc, "code", "") or "").lower()
    text = f"{code} {type(exc).__name__} {str(exc)}".lower()
    if "timeout" in text or "timed" in text:
        return "timeout"
    if "network" in text or "connection" in text or "connect" in text:
        return "network_error"
    if code in {"auth_failed", "rate_limited", "upstream_error"}:
        return "upstream_non_200"
    if code in {"config_missing", "context_too_long"}:
        return "bad_request_or_model"
    if "empty" in text or "blank" in text:
        return "empty_candidate"
    if "invalid" in text or "format" in text or "parse" in text or "json" in text:
        return "invalid_candidate"
    return "unknown_text_generation_error"


def _safe_text_generation_observability(exc: Exception | None) -> dict[str, Any]:
    detail_category = _safe_text_generation_detail_category(exc)
    failure_family = {
        "timeout": "provider_or_runtime",
        "network_error": "provider_or_runtime",
        "upstream_non_200": "provider_or_runtime",
        "bad_request_or_model": "provider_or_runtime",
        "empty_candidate": "candidate_delivery",
        "invalid_candidate": "candidate_delivery",
        "unknown_text_generation_error": "provider_or_runtime",
    }.get(detail_category, "provider_or_runtime")
    failure_source = {
        "timeout": "provider_call",
        "network_error": "provider_call",
        "upstream_non_200": "provider_call",
        "bad_request_or_model": "provider_call",
        "empty_candidate": "candidate_delivery",
        "invalid_candidate": "candidate_parse",
        "unknown_text_generation_error": "provider_call",
    }.get(detail_category, "provider_call")
    candidate_delivery_state = {
        "empty_candidate": "empty_candidate",
        "invalid_candidate": "invalid_candidate",
    }.get(detail_category, "no_candidate_delivered")
    terminal_reason = {
        "empty_candidate": "empty_candidate",
        "invalid_candidate": "invalid_candidate",
    }.get(detail_category, "text_generation_error")
    return {
        "text_generation_detail_category": detail_category,
        "text_generation_failure_family": failure_family,
        "text_generation_failure_source": failure_source,
        "exception_class_safe": _safe_exception_class_name(exc),
        "provider_call_boundary": "during_provider_call",
        "candidate_delivery_state": candidate_delivery_state,
        "safe_failure_observation_version": "v2",
        "text_generation_unknown_reason": (
            "classifier_no_specific_match" if detail_category == "unknown_text_generation_error" else ""
        ),
        "text_generation_stage": "text_generation",
        "terminal_write_reason": terminal_reason,
        "failure_observed_at": "text_generation_exception",
        "http_status_bucket": _safe_http_status_bucket(exc),
        "timeout_bucket": _safe_timeout_bucket(exc),
        "retry_count_bucket": "unknown",
    }


def _safe_failure_internal(
    *,
    stage: str,
    safe_failure_subtype: str,
    reason_code: str | None = None,
    raw_hash: str = "",
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "stage": stage,
        "safe_failure_subtype": safe_failure_subtype or TEXT_GENERATION_UNKNOWN_SUBTYPE,
        "reason_code": reason_code or safe_failure_subtype or TEXT_GENERATION_UNKNOWN_SUBTYPE,
    }
    if raw_hash:
        payload["raw_hash"] = raw_hash
    if extra:
        payload.update(extra)
    return payload


def _write_job_state(
    db: Session,
    job: ShortDramaGenerationJob,
    *,
    status: str,
    public_message: str,
    public_progress: int = 0,
    result: dict[str, Any] | None = None,
    internal: dict[str, Any] | None = None,
    error: str = "",
) -> None:
    job.status = status
    job.public_message = public_message
    job.public_progress = max(0, min(100, int(public_progress or 0)))
    if result is not None:
        job.result_json = json.dumps(result, ensure_ascii=False, default=str)
    if internal is not None:
        preserved = _existing_generation_source_observability(job)
        for key, value in preserved.items():
            internal.setdefault(key, value)
        job.internal_json = json.dumps(internal, ensure_ascii=False, default=str)
    if error:
        job.error = error
    db.commit()


def _expire_stale_running_job_if_needed(db: Session, job: ShortDramaGenerationJob) -> bool:
    if str(job.status or "") != SCRIPT_GENERATION_JOB_RUNNING:
        return False
    updated_at = job.updated_at or job.created_at
    if updated_at is None:
        return False
    elapsed_seconds = max(0, int((datetime.now() - updated_at).total_seconds()))
    if elapsed_seconds < SCRIPT_SCENE_RUNNING_STALE_AFTER_SECONDS:
        return False
    _write_job_state(
        db,
        job,
        status=SCRIPT_GENERATION_JOB_FAILED,
        public_message="生成任务运行态已过期，请重新生成本段。",
        public_progress=100,
        internal=_safe_failure_internal(
            stage="script_scene_job_stale_running",
            safe_failure_subtype="stale_running_job",
            reason_code="stale_running_job",
            extra={
                "stale_after_seconds": SCRIPT_SCENE_RUNNING_STALE_AFTER_SECONDS,
                "last_progress_at": updated_at.isoformat(),
                "terminal_write_reason": "stale_running_job",
            },
        ),
        error="stale_running_job",
    )
    return True


def _contract_conflict_visible_issues(contract: dict[str, Any]) -> list[str]:
    issues: list[str] = []
    for item in contract.get("blocking_conflicts") or []:
        if not isinstance(item, dict):
            continue
        field = str(item.get("field") or "生成依据").strip()
        preferred = str(item.get("preferred_value") or "").strip()
        stale = str(item.get("stale_value") or "").strip()
        if preferred and stale:
            issues.append(f"{field} 存在冲突：当前确认为“{preferred[:40]}”，旧依据为“{stale[:40]}”。")
        else:
            issues.append(f"{field} 存在冲突，请先确认以哪份依据为准。")
    return issues[:6]


def _contract_conflict_internal(contract: dict[str, Any]) -> dict[str, Any]:
    conflicts = contract.get("blocking_conflicts") if isinstance(contract, dict) else []
    visible_issues = _contract_conflict_visible_issues(contract)
    return {
        "stage": "final_generation_contract_conflict",
        "user_action_required": "confirm_generation_contract",
        "contract_conflicts": conflicts if isinstance(conflicts, list) else [],
        "visible_issues": visible_issues,
        "final_generation_contract_hash": str(contract.get("final_generation_contract_hash") or ""),
        "core_generation_contract_hash": str(contract.get("core_generation_contract_hash") or ""),
        "rag_evidence_hash": str(contract.get("rag_evidence_hash") or ""),
    }


def _script_scene_step_public_progress(step_id: str, status: str) -> tuple[str, int]:
    step = str(step_id or "").strip()
    state = str(status or "").strip()
    if step.startswith("D1_"):
        return ("正在梳理本集导演蓝图...", 25 if state == "running" else 35)
    if step.startswith("W1_"):
        return ("正在生成本集正文候选...", 45 if state == "running" else 65)
    if step.startswith("Q1_"):
        return ("正在检查叙事连续性和角色一致性...", 70 if state == "running" else 85)
    return (PUBLIC_PROGRESS_GENERATING, 25)


def _make_script_scene_job_step_observer(job_id: str):
    def _observe(event: dict[str, Any]) -> None:
        step_id = str((event or {}).get("step_id") or "").strip()
        status = str((event or {}).get("status") or "").strip()
        if not step_id or status not in {"running", "completed", "failed"}:
            return
        db = database.SessionLocal()
        try:
            job = db.query(ShortDramaGenerationJob).filter(ShortDramaGenerationJob.id == job_id).first()
            if job is None or str(job.status or "") not in {"pending", SCRIPT_GENERATION_JOB_RUNNING}:
                return
            try:
                internal = json.loads(job.internal_json or "{}")
            except Exception:
                internal = {}
            if not isinstance(internal, dict):
                internal = {}
            events = internal.get("workflow_step_events")
            if not isinstance(events, list):
                events = []
            item = {
                "step_id": step_id,
                "status": status,
            }
            if "duration_ms" in (event or {}):
                item["duration_ms"] = max(0, int((event or {}).get("duration_ms") or 0))
            events.append(item)
            public_message, public_progress = _script_scene_step_public_progress(step_id, status)
            internal["current_step_id"] = step_id
            internal["current_step_status"] = status
            internal["workflow_step_events"] = events[-20:]
            _write_job_state(
                db,
                job,
                status=SCRIPT_GENERATION_JOB_RUNNING,
                public_message=public_message,
                public_progress=public_progress,
                internal=internal,
            )
        finally:
            db.close()

    return _observe


def _job_candidate_formal_bounds(req: TestingScriptRequest) -> tuple[int, int]:
    if str(req.mode or "").strip() == "segment":
        return max(0, int(req.word_count_min or 0)), max(0, int(req.word_count_max or 0))
    formal_min = max(DEFAULT_CANDIDATE_FORMAL_MIN_CHARS, int(req.word_count_min or 0))
    formal_max = max(DEFAULT_CANDIDATE_FORMAL_MAX_CHARS, int(req.word_count_max or 0))
    return formal_min, formal_max


def _candidate_warnings(approved: dict[str, Any]) -> list[str]:
    return [
        str(item or "").strip()
        for item in [
            *(approved.get("warnings") or []),
            *(approved.get("blocking_issues") or []),
            *(approved.get("quality_issues") or []),
        ]
        if str(item or "").strip()
    ][:10]


def _testing_script_response_payload(
    req: TestingScriptRequest,
    approved: dict[str, Any],
    *,
    usage_metrics: dict[str, Any],
    rag_evidence: list[dict[str, Any]],
) -> dict[str, Any]:
    content, char_count = _resolve_testing_output_or_raise(approved)
    benchmark_assessment = approved.get("benchmark_assessment") or BenchmarkAssessment()
    continuity_assessment = approved.get("continuity_assessment") or ContinuityAssessment()
    director_blueprint = approved.get("director_blueprint") if isinstance(approved.get("director_blueprint"), dict) else {}
    response = TestingScriptResponse(
        content=content,
        char_count_excluding_punctuation=char_count,
        overflow_content=str(approved.get("overflow_content") or ""),
        warnings=_candidate_warnings(approved),
        benchmark_assessment=benchmark_assessment,
        continuity_assessment=continuity_assessment,
        episode_memory_card=approved.get("episode_memory_card") or {},
        canon_packet=approved.get("canon_packet") or {},
        usage_metrics=usage_metrics,
        rag_evidence=rag_evidence,
        director_blueprint=director_blueprint,
        generation_trace=_generation_trace(req, director_blueprint),
    ).model_dump()
    response["job_target"] = {
        "project_id": str(req.project_id or ""),
        "episode_no": int(req.episode_no or 1),
        "scene_no": int(req.scene_no or 1),
        "segment_id": str(req.segment_id or ""),
    }
    return response


def _try_repair_candidate_for_user_review(
    req: TestingScriptRequest,
    approved: dict[str, Any],
) -> dict[str, Any] | None:
    formal_min, formal_max = _job_candidate_formal_bounds(req)
    decision = classify_candidate_delivery(
        approved,
        formal_min_chars=formal_min,
        formal_max_chars=formal_max,
    )
    if decision.get("status") != "repair_required" or decision.get("reason") != "severe_word_count_overflow":
        return None
    content = str(approved.get("content") or "").strip()
    if not content:
        return None
    repaired_content = hard_truncate_by_sentence(
        content,
        formal_max,
        exclude_punct=bool(req.exclude_punctuation_for_count),
    ).strip()
    if not repaired_content or repaired_content == content:
        return None
    repaired = dict(approved)
    repaired["content"] = repaired_content
    repaired["char_count_excluding_punctuation"] = count_testing_chars(
        repaired_content,
        exclude_punctuation=bool(req.exclude_punctuation_for_count),
    )
    repaired["blocking_issues"] = [
        str(item or "").strip()
        for item in (approved.get("blocking_issues") or [])
        if str(item or "").strip() and "净字数" not in str(item)
    ]
    repaired["warnings"] = list(dict.fromkeys([
        *(approved.get("warnings") or []),
        "后台已先裁剪严重超字候选，请人工复核承接和结尾后再保存。",
    ]))[:10]
    return repaired


def _job_delivery_decision(req: TestingScriptRequest, approved: dict[str, Any]) -> dict[str, Any]:
    formal_min, formal_max = _job_candidate_formal_bounds(req)
    allow_open_tail = (
        str(req.mode or "").strip() == "segment"
        and str(req.segment_id or "").strip() != "resolution"
    )
    return classify_candidate_delivery(
        approved,
        formal_min_chars=formal_min,
        formal_max_chars=formal_max,
        allow_open_tail=allow_open_tail,
    )


def _has_completed_research_q1(approved: dict[str, Any]) -> bool:
    chain = approved.get("_research_chain") if isinstance(approved, dict) else {}
    if not isinstance(chain, dict):
        return False
    steps = chain.get("execution_steps")
    if not isinstance(steps, list):
        return False
    return any(
        isinstance(item, dict)
        and str(item.get("step_id") or "") == "Q1_deepseek_review"
        and str(item.get("status") or "") == "completed"
        for item in steps
    )


def _apply_outer_quality_gate_if_needed(
    req: TestingScriptRequest,
    approved: dict[str, Any],
) -> dict[str, Any]:
    if _has_completed_research_q1(approved):
        return approved
    return apply_scene_level_gate(req, approved, current_testing_final_generation_contract(req))


def _candidate_from_quality_gate_exception(exc: HTTPException) -> dict[str, Any] | None:
    candidate = getattr(exc, "candidate", None)
    if isinstance(candidate, dict) and candidate.get("content"):
        return candidate
    detail = exc.detail if isinstance(exc.detail, dict) else {}
    detail_candidate = detail.get("candidate") if isinstance(detail, dict) else None
    if isinstance(detail_candidate, dict) and detail_candidate.get("content"):
        return detail_candidate
    return None


def _review_candidate_delivery_payload(
    req: TestingScriptRequest,
    approved: dict[str, Any],
    *,
    usage_metrics: dict[str, Any],
    rag_evidence: list[dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]] | None:
    delivery_decision = _job_delivery_decision(req, approved)
    deliverable = approved
    if delivery_decision.get("status") == "repair_required":
        repaired = _try_repair_candidate_for_user_review(req, approved)
        if repaired is not None:
            repaired_decision = _job_delivery_decision(req, repaired)
            if repaired_decision.get("candidate_returned_to_user"):
                deliverable = repaired
                delivery_decision = repaired_decision
    if not delivery_decision.get("candidate_returned_to_user"):
        return None
    response = _testing_script_response_payload(
        req,
        deliverable,
        usage_metrics=usage_metrics,
        rag_evidence=rag_evidence,
    )
    return response, delivery_decision, deliverable


def _write_review_candidate_job_state(
    db: Session,
    job: ShortDramaGenerationJob,
    *,
    response: dict[str, Any],
    delivery_decision: dict[str, Any],
    deliverable: dict[str, Any],
    stage: str,
) -> None:
    _write_job_state(
        db,
        job,
        status=SCRIPT_GENERATION_JOB_CANDIDATE_REVIEW_REQUIRED,
        public_message="已生成候选稿，但需要你确认修改后保存。",
        public_progress=100,
        result=response,
        internal={
            "stage": stage,
            "delivery_decision": delivery_decision,
            "blocking_issues": deliverable.get("blocking_issues") or [],
            "quality_issues": deliverable.get("quality_issues") or [],
            "research_chain": deliverable.get("_research_chain") or {},
            "candidate_content_hash": stable_hash(response.get("content") or ""),
        },
    )


def _script_scene_job_public_status(job: ShortDramaGenerationJob) -> dict[str, Any]:
    result: dict[str, Any] = {}
    try:
        result = json.loads(job.result_json or "{}")
    except Exception:
        result = {}
    if not isinstance(result, dict):
        result = {}
    internal: dict[str, Any] = {}
    try:
        internal = json.loads(job.internal_json or "{}")
    except Exception:
        internal = {}
    if not isinstance(internal, dict):
        internal = {}
    request_contract = _job_request_final_generation_contract(job)

    state = ScriptGenerationJobState(
        job_id=str(job.id),
        project_id=str(job.project_id or ""),
        episode_no=int(job.episode_no or 1),
        scene_no=int(job.scene_no or 1),
        status=SCRIPT_GENERATION_JOB_RUNNING,
        public_message=job.public_message or PUBLIC_PROGRESS_GENERATING,
        public_progress=int(job.public_progress or 0),
        saved_as_canon=False,
        current_step_id=str(internal.get("current_step_id") or ""),
    )
    if job.status == SCRIPT_GENERATION_JOB_CANDIDATE_READY and result.get("content"):
        state.mark_candidate_ready(
            content=str(result.get("content") or ""),
            char_count_excluding_punctuation=int(result.get("char_count_excluding_punctuation") or 0),
            warnings=[str(item or "").strip() for item in (result.get("warnings") or []) if str(item or "").strip()],
        )
    elif job.status == SCRIPT_GENERATION_JOB_CANDIDATE_REVIEW_REQUIRED and result.get("content"):
        state.mark_candidate_review_required(
            content=str(result.get("content") or ""),
            char_count_excluding_punctuation=int(result.get("char_count_excluding_punctuation") or 0),
            warnings=[str(item or "").strip() for item in (result.get("warnings") or []) if str(item or "").strip()],
        )
    public = state.as_public_status()
    public["status"] = str(job.status or "pending")
    public["public_message"] = job.public_message or public["public_message"]
    public["public_progress"] = int(job.public_progress or public.get("public_progress") or 0)
    public["segment_id"] = _job_request_segment_id(job)
    public["single_episode_time_budget"] = dict(SINGLE_EPISODE_TIME_BUDGET)
    public["visible_issues"] = internal.get("visible_issues") or result.get("visible_issues") or []
    public["user_action_required"] = internal.get("user_action_required") or result.get("user_action_required") or ""
    public["contract_conflicts"] = (
        internal.get("contract_conflicts")
        or result.get("contract_conflicts")
        or request_contract.get("contract_conflicts")
        or []
    )
    public["blocking_conflicts"] = (
        internal.get("blocking_conflicts")
        or result.get("blocking_conflicts")
        or request_contract.get("blocking_conflicts")
        or []
    )
    public["reason_code"] = internal.get("reason_code") or result.get("reason_code") or ""
    public["detail"] = internal.get("detail") or result.get("detail") or {}
    public["safe_failure_subtype"] = internal.get("safe_failure_subtype") or result.get("safe_failure_subtype") or ""
    for field in _SAFE_TEXT_GENERATION_OBSERVABILITY_FIELDS:
        if field in internal or field in result:
            public[field] = internal.get(field) or result.get(field) or ""
    public["generation_source_safe_summary"] = (
        internal.get("generation_source_safe_summary")
        or result.get("generation_source_safe_summary")
        or {}
    )
    public["ready_guard_passed"] = bool(internal.get("ready_guard_passed") or result.get("ready_guard_passed"))
    public["word_count_warning"] = internal.get("word_count_warning") or result.get("word_count_warning")
    public["final_generation_contract_hash"] = (
        internal.get("final_generation_contract_hash")
        or result.get("final_generation_contract_hash")
        or request_contract.get("final_generation_contract_hash")
        or ""
    )
    if public.get("candidate"):
        public["candidate"]["rag_evidence"] = result.get("rag_evidence") or []
        public["candidate"]["episode_memory_card"] = result.get("episode_memory_card") or {}
        public["candidate"]["canon_packet"] = result.get("canon_packet") or {}
    return public


async def _script_scene_generation_job_run(job_id: str) -> None:
    from app.database import SessionLocal

    db = SessionLocal()
    try:
        job = db.query(ShortDramaGenerationJob).filter(ShortDramaGenerationJob.id == job_id).first()
        if job is None:
            return
        req = _job_request_from_json(job)
        actor = _actor_from_job(job)
        _write_job_state(
            db,
            job,
            status=SCRIPT_GENERATION_JOB_RUNNING,
            public_message="正在准备本集生成资料，请稍候...",
            public_progress=5,
        )

        try:
            req = enrich_testing_request_from_project(req, db)
        except PreviousOfficialSourceGateError as exc:
            _write_job_state(
                db,
                job,
                status=SCRIPT_GENERATION_JOB_BLOCKED,
                public_message="上一集官方锁定来源未通过，已停止本次生成。",
                public_progress=100,
                internal=_previous_official_source_gate_payload(exc),
                error=exc.reason_code,
            )
            return
        req = normalize_research_script_request(req)
        variables = _build_script_scene_rag_variables(req)
        rag_evidence = await apply_rag_injection(
            "script_draft",
            {"project": {"id": req.project_id, "project_id": req.project_id}},
            variables,
            db=db,
        )
        req = _apply_rag_into_request(req, variables)
        job.request_json = req.model_dump_json()
        _write_job_state(
            db,
            job,
            status=SCRIPT_GENERATION_JOB_RUNNING,
            public_message="正在生成本集正文...",
            public_progress=25,
        )

        usage_metrics, usage_token = begin_usage_collection({"scope": "testing_script_scene_job"})
        try:
            approved = await asyncio.to_thread(
                generate_research_script_candidate,
                req,
                step_observer=_make_script_scene_job_step_observer(job_id),
            )
        except AtomicRouteConfigError as exc:
            _record_testing_generation_failure(db, req, actor, exc)
            _write_job_state(
                db,
                job,
                status=SCRIPT_GENERATION_JOB_BLOCKED,
                public_message=exc.public_message,
                public_progress=100,
                internal={
                    "stage": "research_route_config",
                    "raw_hash": stable_hash(exc.internal_detail),
                    "route_plan_hash": stable_hash(exc.route_plan),
                },
                error=exc.public_message,
            )
            return
        except TextGenerationError as exc:
            _record_testing_generation_failure(db, req, actor, exc)
            safe_subtype = _safe_text_generation_failure_subtype(exc)
            _write_job_state(
                db,
                job,
                status=SCRIPT_GENERATION_JOB_FAILED,
                public_message=PUBLIC_MODEL_RECOVERY_EXHAUSTED,
                public_progress=100,
                internal=_safe_failure_internal(
                    stage="text_generation",
                    safe_failure_subtype=safe_subtype,
                    reason_code=safe_subtype,
                    raw_hash=stable_hash(str(exc)),
                    extra={
                        "error_code": exc.code,
                        "provider_observability": {
                            "safe_failure_subtype": safe_subtype,
                        },
                        **_safe_text_generation_observability(exc),
                    },
                ),
                error=exc.user_message,
            )
            return
        except HTTPException as exc:
            candidate = _candidate_from_quality_gate_exception(exc)
            if candidate:
                review_delivery = _review_candidate_delivery_payload(
                    req,
                    candidate,
                    usage_metrics=usage_metrics,
                    rag_evidence=rag_evidence,
                )
                if review_delivery is not None:
                    response, delivery_decision, deliverable = review_delivery
                    _write_review_candidate_job_state(
                        db,
                        job,
                        response=response,
                        delivery_decision=delivery_decision,
                        deliverable=deliverable,
                        stage="script_scene_internal_quality_gate",
                    )
                    return
            _record_testing_generation_failure(db, req, actor, exc)
            _write_job_state(
                db,
                job,
                status=SCRIPT_GENERATION_JOB_FAILED,
                public_message=PUBLIC_MODEL_RECOVERY_EXHAUSTED,
                public_progress=100,
                internal=_safe_failure_internal(
                    stage="script_scene_internal_quality_gate",
                    safe_failure_subtype=TEXT_GENERATION_INVALID_CANDIDATE_SUBTYPE,
                    reason_code="script_scene_internal_quality_gate_failed",
                    extra={
                        "error_payload": _http_error_payload(exc),
                        "candidate_present": bool(candidate),
                    },
                ),
                error=str(exc.detail)[:500],
            )
            return
        except Exception as exc:
            _record_testing_generation_failure(db, req, actor, exc)
            _write_job_state(
                db,
                job,
                status=SCRIPT_GENERATION_JOB_FAILED,
                public_message=PUBLIC_MODEL_RECOVERY_EXHAUSTED,
                public_progress=100,
                internal=_safe_failure_internal(
                    stage="script_scene_job",
                    safe_failure_subtype=TEXT_GENERATION_UNKNOWN_SUBTYPE,
                    reason_code="script_scene_job_failed",
                    raw_hash=stable_hash(str(exc)),
                    extra={"error_type": type(exc).__name__},
                ),
                error=str(exc)[:500],
            )
            return
        finally:
            end_usage_collection(usage_token)

        _write_job_state(
            db,
            job,
            status=SCRIPT_GENERATION_JOB_RUNNING,
            public_message="正在检查叙事连续性和角色一致性...",
            public_progress=70,
        )
        approved = _apply_outer_quality_gate_if_needed(req, approved)
        if approved.get("blocking_issues"):
            review_delivery = _review_candidate_delivery_payload(
                req,
                approved,
                usage_metrics=usage_metrics,
                rag_evidence=rag_evidence,
            )
            if review_delivery is not None:
                response, delivery_decision, deliverable = review_delivery
                _write_review_candidate_job_state(
                    db,
                    job,
                    response=response,
                    delivery_decision=delivery_decision,
                    deliverable=deliverable,
                    stage="script_scene_quality_gate",
                )
                return
            delivery_decision = _job_delivery_decision(req, approved)
            detail = "；".join(str(item) for item in (approved.get("blocking_issues") or [])[:3])
            _record_testing_generation_failure(db, req, actor, Exception(detail))
            _write_job_state(
                db,
                job,
                status=SCRIPT_GENERATION_JOB_BLOCKED,
                public_message=PUBLIC_MODEL_RECOVERY_EXHAUSTED,
                public_progress=100,
                internal={
                    "stage": "script_scene_quality_gate",
                    "delivery_decision": delivery_decision,
                    "blocking_issues": approved.get("blocking_issues") or [],
                    "quality_issues": approved.get("quality_issues") or [],
                },
                error=detail,
            )
            return

        try:
            content, char_count = _resolve_testing_output_or_raise(approved)
        except ValueError as exc:
            _record_testing_generation_failure(db, req, actor, exc)
            _write_job_state(
                db,
                job,
                status=SCRIPT_GENERATION_JOB_FAILED,
                public_message=PUBLIC_MODEL_RECOVERY_EXHAUSTED,
                public_progress=100,
                internal={"stage": "content_validation", "raw_hash": stable_hash(str(exc))},
                error=str(exc)[:500],
            )
            return

        _charge_testing_generation(db, req, actor, usage_metrics)
        response = _testing_script_response_payload(
            req,
            approved,
            usage_metrics=usage_metrics,
            rag_evidence=rag_evidence,
        )
        _write_job_state(
            db,
            job,
            status=SCRIPT_GENERATION_JOB_CANDIDATE_READY,
            public_message=PUBLIC_CANDIDATE_READY,
            public_progress=100,
            result=response,
            internal={
                "generation_trace": response.get("generation_trace") or {},
                "research_chain": approved.get("_research_chain") or {},
                "usage_metrics": usage_metrics,
                "candidate_content_hash": stable_hash(content),
            },
        )
    finally:
        db.close()


def _project_workspace_path_for_generation_source(db: Session, project_id: str) -> str:
    from app.models.project_v2 import ProjectV2 as SourcePacketProject

    project = db.query(SourcePacketProject).filter(SourcePacketProject.id == str(project_id or "")).first()
    return str(project.workspace_path or "") if project is not None else ""


def _safe_generation_source_request(req: TestingScriptRequest) -> dict[str, Any]:
    return {
        "project_id": str(req.project_id or ""),
        "episode_no": int(req.episode_no or 1),
        "scene_no": int(req.scene_no or 1),
        "segment_id": str(getattr(req, "segment_id", "") or ""),
    }


def _generation_source_blocked_http_detail(exc) -> dict[str, Any]:
    return {
        "stage": "generation_source_packet",
        "reason_code": str(getattr(exc, "reason_code", "") or "generation_source_packet_blocked"),
        "detail": getattr(exc, "detail", {}) or {},
        "retryable": False,
        "user_action_required": "complete_generation_source_packet",
    }


def _compile_ready_testing_generation_source_packet(
    db: Session,
    req: TestingScriptRequest,
    *,
    frontend_packet: dict[str, Any] | None = None,
) -> tuple[TestingScriptRequest, dict[str, Any]]:
    from app.services.short_drama_generation_source_packet import (
        compile_generation_source_packet,
        validate_generation_source_packet_ready,
    )

    generation_source_packet = compile_generation_source_packet(
        db,
        project_id=str(req.project_id or ""),
        episode_no=int(req.episode_no or 1),
        project_workspace_path=_project_workspace_path_for_generation_source(
            db,
            str(req.project_id or ""),
        ),
        frontend_packet=frontend_packet if frontend_packet is not None else req.model_dump(),
        previous_episode_briefs=req.previous_episode_briefs,
        manual_edit_context=req.manual_edit_context,
    )
    validate_generation_source_packet_ready(generation_source_packet)
    return (
        req.model_copy(update={
            "generation_source_packet": generation_source_packet,
            "final_generation_contract": {},
        }),
        generation_source_packet,
    )


@router.post(
    "/testing/script-scene/source-packet/preview",
    summary="预检测试页剧本生成资料包，不创建生成任务",
)
async def preview_testing_script_scene_source_packet(
    req: TestingScriptRequest,
    actor: ProjectAccessActor = Depends(verify_project_actor),
    db: Session = Depends(get_db),
):
    from app.services.short_drama_generation_source_packet import (
        GenerationSourceBlocked,
        compile_generation_source_packet,
        generation_source_packet_safe_summary,
        validate_generation_source_packet_ready,
    )

    _ensure_testing_generation_access(db, req, actor)
    try:
        precheck_req = enrich_testing_request_from_project(req, db)
        precheck_req = normalize_research_script_request(precheck_req)
        generation_source_packet = compile_generation_source_packet(
            db,
            project_id=str(precheck_req.project_id or req.project_id or ""),
            episode_no=int(precheck_req.episode_no or req.episode_no or 1),
            project_workspace_path=_project_workspace_path_for_generation_source(
                db,
                str(precheck_req.project_id or req.project_id or ""),
            ),
            frontend_packet=req.model_dump(),
            previous_episode_briefs=precheck_req.previous_episode_briefs,
            manual_edit_context=precheck_req.manual_edit_context,
        )
        validate_generation_source_packet_ready(generation_source_packet)
    except GenerationSourceBlocked as exc:
        return {
            "status": "blocked",
            "reason_code": exc.reason_code,
            "detail": exc.detail,
        }

    return {
        "status": "ready",
        "safe_summary": generation_source_packet.get("safe_summary")
        or generation_source_packet_safe_summary(generation_source_packet),
        "blocking_issues": [],
        "warnings": list(generation_source_packet.get("warnings") or []),
    }


@router.post(
    "/testing/script-scene/jobs/start",
    summary="启动测试页剧本片段后台生成任务",
)
async def start_testing_script_scene_job(
    req: TestingScriptRequest,
    background_tasks: BackgroundTasks,
    actor: ProjectAccessActor = Depends(verify_project_actor),
    db: Session = Depends(get_db),
):
    _ensure_testing_generation_access(db, req, actor)
    _assert_c19_178_short_drama_episode_generation_gate(db, req.project_id)
    try:
        precheck_req = enrich_testing_request_from_project(req, db)
    except PreviousOfficialSourceGateError as exc:
        raise HTTPException(status_code=409, detail=_previous_official_source_gate_payload(exc)) from exc
    precheck_req = normalize_research_script_request(precheck_req)
    from app.services.short_drama_generation_source_packet import (
        GenerationSourceBlocked,
        compile_generation_source_packet,
        generation_source_packet_job_safe_summary,
        generation_source_packet_safe_summary,
        validate_generation_source_packet_ready,
    )

    try:
        generation_source_packet = compile_generation_source_packet(
            db,
            project_id=str(precheck_req.project_id or req.project_id or ""),
            episode_no=int(precheck_req.episode_no or req.episode_no or 1),
            project_workspace_path=_project_workspace_path_for_generation_source(
                db,
                str(precheck_req.project_id or req.project_id or ""),
            ),
            frontend_packet=req.model_dump(),
            previous_episode_briefs=precheck_req.previous_episode_briefs,
            manual_edit_context=precheck_req.manual_edit_context,
        )
        validate_generation_source_packet_ready(generation_source_packet)
    except GenerationSourceBlocked as exc:
        generation_source_packet = {
            "source": "backend_compiled_generation_source_packet",
            "source_packet_version": "generation_source_packet.v1",
            "project_id": str(precheck_req.project_id or req.project_id or ""),
            "episode_no": int(precheck_req.episode_no or req.episode_no or 1),
            "blocking_issues": [exc.reason_code],
            "warnings": [],
            "previous_episode_continuity": {
                "source": "",
                "previous_episode_no": max(0, int(precheck_req.episode_no or req.episode_no or 1) - 1),
                "ready": False,
            },
            "authority_trace": {
                "frontend_packet": {
                    "source": "compatibility_input_only",
                    "input_present": True,
                    "used_as_authority_source": False,
                },
            },
        }
        safe_summary = generation_source_packet_safe_summary(generation_source_packet)
        job_safe_summary = generation_source_packet_job_safe_summary(
            generation_source_packet,
            scene_no=int(precheck_req.scene_no or req.scene_no or 1),
            segment_id=str(getattr(precheck_req, "segment_id", "") or getattr(req, "segment_id", "") or ""),
        )
        job_id = uuid.uuid4().hex
        job = ShortDramaGenerationJob(
            id=job_id,
            project_id=str(req.project_id or ""),
            owner_key=getattr(actor, "access_key_id", "") or "",
            owner_is_admin=bool(getattr(actor, "is_admin", False)),
            status=SCRIPT_GENERATION_JOB_BLOCKED,
            episode_no=int(req.episode_no or 1),
            scene_no=int(req.scene_no or 1),
            public_message="本集生成前提资料不完整，请先补齐后再生成。",
            public_progress=100,
            request_json=json.dumps(_safe_generation_source_request(precheck_req), ensure_ascii=False, default=str),
            internal_json=json.dumps(
                {
                    "stage": "generation_source_packet",
                    "reason_code": exc.reason_code,
                    "detail": exc.detail,
                    "safe_summary": safe_summary,
                    "generation_source_safe_summary": job_safe_summary,
                    "ready_guard_passed": False,
                    "visible_issues": [{
                        "reason_code": exc.reason_code,
                        "detail": exc.detail,
                    }],
                    "user_action_required": "complete_generation_source_packet",
                },
                ensure_ascii=False,
                default=str,
            ),
            error=exc.reason_code,
        )
        db.add(job)
        db.commit()
        return _script_scene_job_public_status(job)
    precheck_req = precheck_req.model_copy(update={
        "generation_source_packet": generation_source_packet,
        "final_generation_contract": {},
    })

    generation_source_internal = {
        "stage": "generation_source_packet",
        "ready_guard_passed": True,
        "generation_source_safe_summary": generation_source_packet_job_safe_summary(
            generation_source_packet,
            scene_no=int(precheck_req.scene_no or req.scene_no or 1),
            segment_id=str(getattr(precheck_req, "segment_id", "") or getattr(req, "segment_id", "") or ""),
        ),
    }
    precheck_contract = current_testing_final_generation_contract(precheck_req, include_rag=False)
    conflict_internal = _contract_conflict_internal(precheck_contract) if precheck_contract.get("blocking_conflicts") else {}
    if conflict_internal:
        conflict_internal = {**generation_source_internal, **conflict_internal}
    request_for_job = precheck_req.model_copy(update={"final_generation_contract": precheck_contract})
    if not conflict_internal:
        reusable_job = find_reusable_active_script_scene_job(
            db,
            project_id=str(req.project_id or ""),
            episode_no=int(req.episode_no or 1),
            scene_no=int(req.scene_no or 1),
            owner_key=getattr(actor, "access_key_id", "") or "",
            owner_is_admin=bool(getattr(actor, "is_admin", False)),
        )
        if reusable_job is not None:
            return _script_scene_job_public_status(reusable_job)

    job_id = uuid.uuid4().hex
    job = ShortDramaGenerationJob(
        id=job_id,
        project_id=str(req.project_id or ""),
        owner_key=getattr(actor, "access_key_id", "") or "",
        owner_is_admin=bool(getattr(actor, "is_admin", False)),
        status=SCRIPT_GENERATION_JOB_BLOCKED if conflict_internal else "pending",
        episode_no=int(req.episode_no or 1),
        scene_no=int(req.scene_no or 1),
        public_message=(
            "本集生成依据存在冲突，请先确认以哪一份为准。"
            if conflict_internal
            else PUBLIC_PROGRESS_GENERATING
        ),
        public_progress=100 if conflict_internal else 0,
        request_json=request_for_job.model_dump_json(),
        internal_json=json.dumps(
            conflict_internal or generation_source_internal,
            ensure_ascii=False,
            default=str,
        ),
        error="本集生成依据存在冲突，请先确认以哪一份为准。" if conflict_internal else "",
    )
    db.add(job)
    db.commit()

    if not conflict_internal:
        background_tasks.add_task(_script_scene_generation_job_run, job_id)
    return _script_scene_job_public_status(job)


@router.get(
    "/testing/script-scene/jobs/latest",
    summary="查询当前集最近可恢复的剧本候选任务",
)
async def testing_script_scene_latest_job_status(
    project_id: str,
    episode_no: int = 1,
    scene_no: int = 1,
    segment_id: str = "",
    actor: ProjectAccessActor = Depends(verify_project_actor),
    db: Session = Depends(get_db),
):
    normalized_project_id = str(project_id or "").strip()
    normalized_segment_id = str(segment_id or "").strip()
    ensure_short_drama_project_access(db, normalized_project_id, actor, require_credit=False)
    query = db.query(ShortDramaGenerationJob).filter(
        ShortDramaGenerationJob.project_id == normalized_project_id,
        ShortDramaGenerationJob.episode_no == max(1, int(episode_no or 1)),
        ShortDramaGenerationJob.scene_no == max(1, int(scene_no or 1)),
        ShortDramaGenerationJob.status.in_([
            SCRIPT_GENERATION_JOB_CANDIDATE_READY,
            SCRIPT_GENERATION_JOB_CANDIDATE_REVIEW_REQUIRED,
        ]),
    )
    candidates = query.order_by(
        ShortDramaGenerationJob.updated_at.desc(),
        ShortDramaGenerationJob.created_at.desc(),
    ).limit(20).all()
    job = None
    for item in candidates:
        if normalized_segment_id and _job_request_segment_id(item) != normalized_segment_id:
            continue
        if mark_orphan_candidate_job_failed_if_needed(db, item):
            continue
        job = item
        break
    if job is None:
        raise HTTPException(status_code=404, detail="暂无可恢复候选稿")
    return _script_scene_job_public_status(job)


@router.get(
    "/testing/script-scene/jobs/status/{job_id}",
    summary="查询测试页剧本片段后台生成任务状态",
)
async def testing_script_scene_job_status(
    job_id: str,
    actor: ProjectAccessActor = Depends(verify_project_actor),
    db: Session = Depends(get_db),
):
    job = db.query(ShortDramaGenerationJob).filter(ShortDramaGenerationJob.id == job_id).first()
    if job is None:
        raise HTTPException(status_code=404, detail="任务不存在或已过期，请重新生成")
    if not getattr(actor, "is_admin", False):
        if (job.owner_key or "") != (getattr(actor, "access_key_id", "") or ""):
            raise HTTPException(status_code=404, detail="任务不存在或已过期，请重新生成")
    _expire_stale_running_job_if_needed(db, job)
    mark_orphan_candidate_job_failed_if_needed(db, job)
    return _script_scene_job_public_status(job)


@router.post(
    "/testing/script-scene",
    response_model=TestingScriptResponse,
    summary="测试页按真实规则生成剧本片段",
)
async def generate_testing_script_scene(
    req: TestingScriptRequest,
    actor: ProjectAccessActor = Depends(verify_project_actor),
    db: Session = Depends(get_db),
):
    _ensure_testing_generation_access(db, req, actor)
    _assert_c19_178_short_drama_episode_generation_gate(db, req.project_id)
    try:
        req = enrich_testing_request_from_project(req, db)
    except PreviousOfficialSourceGateError as exc:
        raise HTTPException(status_code=409, detail=_previous_official_source_gate_payload(exc)) from exc
    req = normalize_research_script_request(req)
    try:
        req, _generation_source_packet = _compile_ready_testing_generation_source_packet(
            db,
            req,
            frontend_packet=req.model_dump(),
        )
    except GenerationSourceBlocked as exc:
        raise HTTPException(status_code=409, detail=_generation_source_blocked_http_detail(exc)) from exc
    variables = _build_script_scene_rag_variables(req)
    rag_evidence = await apply_rag_injection(
        "script_draft",
        {"project": {"id": req.project_id, "project_id": req.project_id}},
        variables,
        db=db,
    )
    req = _apply_rag_into_request(req, variables)
    usage_metrics, usage_token = begin_usage_collection({"scope": "testing_script_scene"})
    try:
        approved = await asyncio.to_thread(generate_research_script_candidate, req)
    except AtomicRouteConfigError as exc:
        _record_testing_generation_failure(db, req, actor, exc)
        raise HTTPException(
            status_code=409,
            detail={
                "error_code": "research_route_config_error",
                "detail": exc.public_message,
                "suggestion": "请检查本集集纲、角色小传和项目生成配置后重试。",
                "retryable": True,
                "stage": "research_route_config",
            },
        ) from exc
    except TextGenerationError as exc:
        _record_testing_generation_failure(db, req, actor, exc)
        raise HTTPException(status_code=exc.http_status, detail=_text_generation_error_payload(exc))
    except Exception as exc:
        _record_testing_generation_failure(db, req, actor, exc)
        raise
    finally:
        end_usage_collection(usage_token)
    approved = _apply_outer_quality_gate_if_needed(req, approved)
    benchmark_assessment = approved.get("benchmark_assessment") or BenchmarkAssessment()
    continuity_assessment = approved.get("continuity_assessment") or ContinuityAssessment()
    if approved.get("blocking_issues"):
        _record_testing_generation_failure(
            db,
            req,
            actor,
            Exception("；".join(str(item) for item in (approved.get("blocking_issues") or [])[:2])),
        )
        raise HTTPException(
            status_code=400,
            detail=_quality_gate_error_payload(req, approved),
        )
    try:
        content, char_count = _resolve_testing_output_or_raise(approved)
    except ValueError as exc:
        _record_testing_generation_failure(db, req, actor, exc)
        raise HTTPException(status_code=502, detail=_empty_generation_payload(exc)) from exc

    _charge_testing_generation(db, req, actor, usage_metrics)
    director_blueprint = approved.get("director_blueprint") if isinstance(approved.get("director_blueprint"), dict) else {}

    return TestingScriptResponse(
        content=content,
        char_count_excluding_punctuation=char_count,
        overflow_content=str(approved.get("overflow_content") or ""),
        warnings=list(approved["warnings"]),
        benchmark_assessment=benchmark_assessment,
        continuity_assessment=continuity_assessment,
        episode_memory_card=approved.get("episode_memory_card") or {},
        canon_packet=approved.get("canon_packet") or {},
        usage_metrics=usage_metrics,
        rag_evidence=rag_evidence,
        director_blueprint=director_blueprint,
        generation_trace=_generation_trace(req, director_blueprint),
    )


@router.post(
    "/testing/script-scene/stream",
    summary="测试页流式生成剧本片段",
    response_class=StreamingResponse,
)
async def generate_testing_script_scene_stream(
    req: TestingScriptRequest,
    actor: ProjectAccessActor = Depends(verify_project_actor),
    db: Session = Depends(get_db),
):
    _ensure_testing_generation_access(db, req, actor)
    _assert_c19_178_short_drama_episode_generation_gate(db, req.project_id)
    try:
        req = enrich_testing_request_from_project(req, db)
    except PreviousOfficialSourceGateError as exc:
        raise HTTPException(status_code=409, detail=_previous_official_source_gate_payload(exc)) from exc
    req = normalize_research_script_request(req)
    try:
        req, _generation_source_packet = _compile_ready_testing_generation_source_packet(
            db,
            req,
            frontend_packet=req.model_dump(),
        )
    except GenerationSourceBlocked as exc:
        raise HTTPException(status_code=409, detail=_generation_source_blocked_http_detail(exc)) from exc
    variables = _build_script_scene_rag_variables(req)
    rag_evidence = await apply_rag_injection(
        "script_draft",
        {"project": {"id": req.project_id, "project_id": req.project_id}},
        variables,
        db=db,
    )
    req = _apply_rag_into_request(req, variables)

    async def _generate():
        try:
            yield _sse_event("progress", {"message": "正在准备本集生成资料，请稍候..."})
            usage_metrics, usage_token = begin_usage_collection({"scope": "testing_script_scene_stream"})
            task = asyncio.create_task(asyncio.to_thread(generate_research_script_candidate, req))
            tick = 0
            progress_messages = [
                "正在生成本集正文…",
                "正在检查叙事连续性和角色一致性…",
                "正在整理候选内容…",
                "正在确认本集是否可以交给你审阅…",
            ]
            while not task.done():
                await asyncio.sleep(2)
                yield _sse_event("progress", {"message": progress_messages[tick % len(progress_messages)]})
                tick += 1
            try:
                approved = await task
            finally:
                end_usage_collection(usage_token)
            approved = _apply_outer_quality_gate_if_needed(req, approved)
            if approved.get("blocking_issues"):
                _record_testing_generation_failure(
                    db,
                    req,
                    actor,
                    Exception("；".join(str(item) for item in (approved.get("blocking_issues") or [])[:2])),
                )
                yield _sse_event(
                    "error",
                    _quality_gate_error_payload(req, approved),
                )
                return
            try:
                content, char_count = _resolve_testing_output_or_raise(approved)
            except ValueError as exc:
                _record_testing_generation_failure(db, req, actor, exc)
                yield _sse_event("error", _empty_generation_payload(exc))
                return
            _charge_testing_generation(db, req, actor, usage_metrics)
            benchmark_assessment = approved.get("benchmark_assessment") or BenchmarkAssessment()
            continuity_assessment = approved.get("continuity_assessment") or ContinuityAssessment()
            director_blueprint = approved.get("director_blueprint") if isinstance(approved.get("director_blueprint"), dict) else {}
            full_text = content
            yield _sse_event("progress", {"message": "本集候选内容已准备好，正在输出正文..."})

            for token in re.findall(r".{1,12}", full_text, flags=re.DOTALL):
                yield _sse_event("token", {"text": token})
                await asyncio.sleep(0.01)

            payload = TestingScriptResponse(
                content=full_text.strip(),
                char_count_excluding_punctuation=char_count,
                overflow_content=str(approved.get("overflow_content") or ""),
                warnings=list(approved["warnings"]),
                benchmark_assessment=benchmark_assessment,
                continuity_assessment=continuity_assessment,
                episode_memory_card=approved.get("episode_memory_card") or {},
                canon_packet=approved.get("canon_packet") or {},
                rag_evidence=rag_evidence,
                director_blueprint=director_blueprint,
                generation_trace=_generation_trace(req, director_blueprint),
            ).model_dump()
            yield _sse_event("done", payload)
        except TextGenerationError as exc:
            _record_testing_generation_failure(db, req, actor, exc)
            yield _sse_event("error", _text_generation_error_payload(exc))
        except AtomicRouteConfigError as exc:
            _record_testing_generation_failure(db, req, actor, exc)
            yield _sse_event("error", {
                "error_code": "research_route_config_error",
                "detail": exc.public_message,
                "suggestion": "请检查本集集纲、角色小传和项目生成配置后重试。",
                "retryable": True,
                "stage": "research_route_config",
            })
        except HTTPException as exc:
            yield _sse_event("error", _http_error_payload(exc))
        except Exception as exc:  # pragma: no cover - 运行时容错
            _record_testing_generation_failure(db, req, actor, exc)
            yield _sse_event("error", _internal_error_payload(exc))

    return StreamingResponse(_generate(), media_type="text/event-stream")
