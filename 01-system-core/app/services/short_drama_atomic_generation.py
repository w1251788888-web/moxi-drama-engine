"""Atomic generation step orchestration for user-facing longform script creation.

This module only records and coordinates steps. It does not author script
content. Real content comes from injected model call functions.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Literal

from app.services.short_drama_advanced_generation import resolve_step_generation_route


AtomicStepStatus = Literal["pending", "running", "completed", "failed", "blocked"]
ScriptGenerationJobStatus = Literal[
    "running",
    "candidate_ready",
    "candidate_review_required",
    "repair_required",
    "blocked",
    "failed",
    "done",
]

PUBLIC_PROGRESS_GENERATING = "正在生成本集，请稍候…"
PUBLIC_PROGRESS_FINALIZING = "正在整理正文"
PUBLIC_PROGRESS_SAVING = "正在保存结果"
PUBLIC_INPUT_BLOCKED = "本集前置资料不足，请回到集纲补充主场景、冲突和角色目标后再试。"
PUBLIC_MODEL_RECOVERY_EXHAUSTED = "本集暂时没有生成出可用正文，请回到集纲检查主场景、冲突和角色目标后再试。"
PUBLIC_CANDIDATE_READY = "已生成候选内容，需要人工确认后保存。"
PUBLIC_CANDIDATE_REVIEW_REQUIRED = "已生成候选稿，但需要你确认修改后保存。"
STRICT_ROUTE_ERROR = "invalid_provider_route_config_error"
SCRIPT_GENERATION_JOB_RUNNING = "running"
SCRIPT_GENERATION_JOB_CANDIDATE_READY = "candidate_ready"
SCRIPT_GENERATION_JOB_CANDIDATE_REVIEW_REQUIRED = "candidate_review_required"
SCRIPT_GENERATION_JOB_REPAIR_REQUIRED = "repair_required"
SCRIPT_GENERATION_JOB_BLOCKED = "blocked"
SCRIPT_GENERATION_JOB_FAILED = "failed"
SCRIPT_GENERATION_JOB_DONE = "done"
DEFAULT_CANDIDATE_FORMAL_MIN_CHARS = 1000
DEFAULT_CANDIDATE_FORMAL_MAX_CHARS = 1550
DEFAULT_CANDIDATE_REVIEW_MAX_CHARS = 1700
DIRECTOR_BLUEPRINT_MAX_TOKENS = 12000
SINGLE_EPISODE_TIME_BUDGET = {
    "target_seconds": 300,
    "stage_target_seconds": 150,
    "timeout_seconds": 600,
}
USER_FACING_WORKFLOW_STEPS = [
    {
        "id": "prerequisite_check",
        "label": "前提资料确认",
        "description": "检查大纲、集纲、人物小传和角色关系是否具备生成条件。",
    },
    {
        "id": "director_blueprint",
        "label": "本集导演蓝图",
        "description": "确认本集目标、冲突、主场景、爽点和结尾钩子。",
    },
    {
        "id": "segment_task_cards",
        "label": "四段任务卡",
        "description": "把本集拆成开场、推进、爆发和收束四个写作任务。",
    },
    {
        "id": "candidate_draft",
        "label": "正文候选",
        "description": "生成本集可编辑正文候选，并保留给用户确认。",
    },
    {
        "id": "review_and_save",
        "label": "审查与保存",
        "description": "检查字数、连续性、人物一致性和重复风险，等待用户保存为正史。",
    },
]

STRICT_ATOMIC_STEP_ROUTES = {
    "D1_director_blueprint": ("director_blueprint", "deepseek"),
    "W1_writer_hook": ("script_draft", "kimi"),
    "Q1_deepseek_review": ("quality_check", "deepseek"),
}
DEFAULT_RESEARCH_GENERATION_PROVIDERS = {
    "logic": {"provider": "deepseek", "model": "deepseek-v4-pro"},
    "creative": {"provider": "kimi", "model": "kimi-k2.6"},
    "review": {"provider": "deepseek", "model": "deepseek-v4-pro"},
}
RESEARCH_SCRIPT_CHAIN_STEPS = [
    "S0_input_snapshot",
    "R0_strict_route_check",
    "D1_director_blueprint",
    "W1_writer_hook",
    "Q1_deepseek_review",
]


class AtomicRouteConfigError(RuntimeError):
    """Internal route configuration failed the one-chain research contract."""

    def __init__(
        self,
        *,
        public_message: str,
        internal_detail: str,
        route_plan: dict[str, dict[str, Any]] | None = None,
    ) -> None:
        super().__init__(internal_detail)
        self.public_message = public_message
        self.internal_detail = internal_detail
        self.route_plan = route_plan or {}


def stable_hash(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _clean_issues(candidate: dict[str, Any]) -> list[str]:
    return [
        str(item or "").strip()
        for item in [
            *(candidate.get("blocking_issues") or []),
            *(candidate.get("quality_issues") or []),
        ]
        if str(item or "").strip()
    ]


def _has_basic_script_shape(content: str) -> bool:
    text = str(content or "").strip()
    if not text:
        return False
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    has_scene = any(line.startswith("【场") or line.startswith("场") for line in lines)
    has_dialogue = any("：" in line and not line.startswith("△") for line in lines)
    return has_scene and has_dialogue


_TAIL_SENTENCE_ENDINGS = tuple("。！？!?…；;”」）】")
_TAIL_INCOMPLETE_SUFFIXES = (
    "别只", "只是", "只", "但", "但是", "可", "可是", "却", "和", "与", "把", "被",
    "在", "向", "对", "让", "因为", "为了", "不是", "还", "又", "刚", "才", "从",
    "往", "跟", "给", "到", "就", "要", "会", "能", "没", "没有",
)
_TRUNCATION_DIAGNOSTIC_TOKENS = ("裁剪", "截断", "严重超字")


def _is_scene_header(line: str) -> bool:
    return line.startswith("【场") or line.startswith("场")


def _has_truncated_final_scene(content: str, diagnostics: list[str]) -> bool:
    diagnostic_text = "\n".join(str(item or "") for item in diagnostics)
    if not any(token in diagnostic_text for token in _TRUNCATION_DIAGNOSTIC_TOKENS):
        return False

    lines = [line.strip() for line in str(content or "").splitlines() if line.strip()]
    scene_indexes = [idx for idx, line in enumerate(lines) if _is_scene_header(line)]
    if len(scene_indexes) < 2:
        return False

    final_scene_lines = [
        line for line in lines[scene_indexes[-1] + 1 :]
        if line and line != "---"
    ]
    if not final_scene_lines:
        return True

    has_dialogue = any("：" in line and not line.startswith("△") for line in final_scene_lines)
    return len(final_scene_lines) <= 2 or (len(final_scene_lines) <= 3 and not has_dialogue)


def _has_complete_script_tail(content: str, diagnostics: list[str] | None = None) -> bool:
    lines = [line.strip() for line in str(content or "").splitlines() if line.strip()]
    if not lines:
        return False
    last = lines[-1]
    if _is_scene_header(last):
        return False
    if _has_truncated_final_scene(content, diagnostics or []):
        return False
    if last.endswith(_TAIL_SENTENCE_ENDINGS):
        return True
    if any(last.endswith(token) for token in _TAIL_INCOMPLETE_SUFFIXES):
        return False
    if "：" in last and not last.startswith("△"):
        speech = last.split("：", 1)[1].strip()
        return 1 <= len(speech) <= 12
    return False


def classify_candidate_delivery(
    candidate: dict[str, Any],
    *,
    formal_min_chars: int = DEFAULT_CANDIDATE_FORMAL_MIN_CHARS,
    formal_max_chars: int = DEFAULT_CANDIDATE_FORMAL_MAX_CHARS,
    review_max_chars: int = DEFAULT_CANDIDATE_REVIEW_MAX_CHARS,
    allow_open_tail: bool = False,
) -> dict[str, Any]:
    """Classify whether a draft may be shown to users as a review candidate.

    This is not a scoring pass. It only protects the user experience boundary:
    severely overlong or shapeless output cannot be passed to users as a
    "candidate"; light issues can be shown for human confirmation without canon
    saving.
    """
    content = str(candidate.get("content") or "").strip()
    char_count = int(candidate.get("char_count_excluding_punctuation") or 0)
    issues = _clean_issues(candidate)
    diagnostics = [
        *issues,
        *[
            str(item or "").strip()
            for item in (candidate.get("warnings") or [])
            if str(item or "").strip()
        ],
    ]
    review_ceiling = max(int(review_max_chars or 0), int(formal_max_chars or 0))
    formal_min = max(0, int(formal_min_chars or 0))
    formal_max = max(0, int(formal_max_chars or 0))

    if not content or char_count <= 0:
        return {
            "status": SCRIPT_GENERATION_JOB_BLOCKED,
            "candidate_returned_to_user": False,
            "requires_user_confirmation": False,
            "reason": "empty_candidate",
        }
    if not _has_basic_script_shape(content):
        return {
            "status": SCRIPT_GENERATION_JOB_BLOCKED,
            "candidate_returned_to_user": False,
            "requires_user_confirmation": False,
            "reason": "script_shape_missing",
        }
    if not allow_open_tail and not _has_complete_script_tail(content, diagnostics):
        return {
            "status": SCRIPT_GENERATION_JOB_REPAIR_REQUIRED,
            "candidate_returned_to_user": False,
            "requires_user_confirmation": False,
            "reason": "script_tail_incomplete",
        }
    if formal_min and char_count < formal_min:
        return {
            "status": SCRIPT_GENERATION_JOB_REPAIR_REQUIRED,
            "candidate_returned_to_user": False,
            "requires_user_confirmation": False,
            "reason": "word_count_underflow",
        }
    if review_ceiling and char_count > review_ceiling:
        return {
            "status": SCRIPT_GENERATION_JOB_REPAIR_REQUIRED,
            "candidate_returned_to_user": False,
            "requires_user_confirmation": False,
            "reason": "severe_word_count_overflow",
        }
    if issues or not bool(candidate.get("quality_passed", True)):
        return {
            "status": SCRIPT_GENERATION_JOB_CANDIDATE_REVIEW_REQUIRED,
            "candidate_returned_to_user": True,
            "requires_user_confirmation": True,
            "reason": "reviewable_candidate",
        }
    return {
        "status": SCRIPT_GENERATION_JOB_CANDIDATE_READY,
        "candidate_returned_to_user": True,
        "requires_user_confirmation": True,
        "reason": "candidate_ready",
    }


@dataclass
class ScriptGenerationInternalAttempt:
    step_id: str
    provider: str = ""
    model: str = ""
    retry_count: int = 0
    detail: str = ""
    created_ms: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "step_id": self.step_id,
            "provider": self.provider,
            "model": self.model,
            "retry_count": self.retry_count,
            "detail": self.detail,
            "created_ms": self.created_ms,
        }


@dataclass
class ScriptGenerationJobState:
    """User-facing script generation job protocol.

    It records internal model attempts, but exposes only business-safe status
    to the frontend. Candidate content is not canon until the user confirms it.
    """

    job_id: str
    project_id: str
    episode_no: int
    scene_no: int = 1
    status: ScriptGenerationJobStatus = SCRIPT_GENERATION_JOB_RUNNING
    public_message: str = PUBLIC_PROGRESS_GENERATING
    public_progress: int = 0
    visible_route_count: int = 1
    saved_as_canon: bool = False
    candidate_content: str = ""
    candidate_char_count: int = 0
    candidate_warnings: list[str] = field(default_factory=list)
    current_step_id: str = ""
    started_at_ms: int = field(default_factory=lambda: int(time.time() * 1000))
    updated_at_ms: int = field(default_factory=lambda: int(time.time() * 1000))
    internal_attempts: list[ScriptGenerationInternalAttempt] = field(default_factory=list)
    internal_detail: str = ""

    def _touch(self) -> None:
        self.updated_at_ms = int(time.time() * 1000)

    def mark_running(self, step_id: str, *, public_message: str = PUBLIC_PROGRESS_GENERATING) -> None:
        self.status = SCRIPT_GENERATION_JOB_RUNNING
        self.current_step_id = str(step_id or "").strip()
        self.public_message = public_message or PUBLIC_PROGRESS_GENERATING
        self._touch()

    def record_internal_attempt(
        self,
        *,
        step_id: str,
        provider: str = "",
        model: str = "",
        retry_count: int = 0,
        detail: str = "",
    ) -> None:
        self.internal_attempts.append(
            ScriptGenerationInternalAttempt(
                step_id=str(step_id or "").strip(),
                provider=str(provider or "").strip(),
                model=str(model or "").strip(),
                retry_count=max(0, int(retry_count or 0)),
                detail=str(detail or "").strip(),
                created_ms=int(time.time() * 1000),
            )
        )
        self._touch()

    def mark_recovery_exhausted(self, *, step_id: str, internal_detail: str) -> None:
        self.status = SCRIPT_GENERATION_JOB_BLOCKED
        self.current_step_id = str(step_id or "").strip()
        self.public_message = PUBLIC_MODEL_RECOVERY_EXHAUSTED
        self.internal_detail = str(internal_detail or "").strip()
        self._touch()

    def mark_candidate_ready(
        self,
        *,
        content: str,
        char_count_excluding_punctuation: int = 0,
        warnings: list[str] | None = None,
    ) -> None:
        self.status = SCRIPT_GENERATION_JOB_CANDIDATE_READY
        self.public_message = PUBLIC_CANDIDATE_READY
        self.public_progress = 100
        self.candidate_content = str(content or "").strip()
        self.candidate_char_count = max(0, int(char_count_excluding_punctuation or 0))
        self.candidate_warnings = [str(item or "").strip() for item in (warnings or []) if str(item or "").strip()]
        self.saved_as_canon = False
        self._touch()

    def mark_candidate_review_required(
        self,
        *,
        content: str,
        char_count_excluding_punctuation: int = 0,
        warnings: list[str] | None = None,
    ) -> None:
        self.status = SCRIPT_GENERATION_JOB_CANDIDATE_REVIEW_REQUIRED
        self.public_message = PUBLIC_CANDIDATE_REVIEW_REQUIRED
        self.public_progress = 100
        self.candidate_content = str(content or "").strip()
        self.candidate_char_count = max(0, int(char_count_excluding_punctuation or 0))
        self.candidate_warnings = [str(item or "").strip() for item in (warnings or []) if str(item or "").strip()]
        self.saved_as_canon = False
        self._touch()

    def _workflow_step_index(self) -> int:
        if self.candidate_content or self.status in {
            SCRIPT_GENERATION_JOB_CANDIDATE_READY,
            SCRIPT_GENERATION_JOB_CANDIDATE_REVIEW_REQUIRED,
            SCRIPT_GENERATION_JOB_DONE,
        }:
            return 4
        step_id = str(self.current_step_id or "").strip()
        if step_id.startswith("D1_"):
            return 1
        if step_id.startswith("W1_"):
            return 3
        if step_id.startswith("Q1_"):
            return 4
        progress = max(0, min(100, int(self.public_progress or 0)))
        if progress >= 70:
            return 4
        if progress >= 25:
            return 3
        if progress >= 15:
            return 2
        if progress >= 8:
            return 1
        return 0

    def _workflow_steps(self) -> list[dict[str, str]]:
        current_index = self._workflow_step_index()
        blocked = self.status in {SCRIPT_GENERATION_JOB_BLOCKED, SCRIPT_GENERATION_JOB_FAILED}
        has_candidate = bool(self.candidate_content)
        saved = bool(self.saved_as_canon)
        progress = max(0, min(100, int(self.public_progress or 0)))
        steps: list[dict[str, str]] = []
        for index, item in enumerate(USER_FACING_WORKFLOW_STEPS):
            status = "pending"
            if has_candidate:
                status = "completed" if index < 4 or saved else "action_required"
            elif blocked:
                status = "blocked" if index == current_index else ("completed" if index < current_index else "pending")
            elif self.current_step_id:
                status = "completed" if index < current_index else ("running" if index == current_index else "pending")
            elif 25 <= progress < 70:
                # The backend currently runs blueprint, task cards and candidate
                # draft inside one long model job. Mark them as in progress
                # rather than pretending each sub-node has completed.
                status = "completed" if index == 0 else ("running" if 1 <= index <= 3 else "pending")
            elif index < current_index:
                status = "completed"
            elif index == current_index:
                status = "running"
            steps.append({
                **item,
                "status": status,
            })
        return steps

    def as_public_status(self) -> dict[str, Any]:
        candidate: dict[str, Any] = {}
        if self.candidate_content:
            candidate = {
                "content": self.candidate_content,
                "content_hash": stable_hash(self.candidate_content),
                "char_count_excluding_punctuation": self.candidate_char_count,
                "warnings": list(self.candidate_warnings),
            }
        workflow_steps = self._workflow_steps()
        current_workflow_step = workflow_steps[self._workflow_step_index()]["id"]
        return {
            "job_id": self.job_id,
            "project_id": self.project_id,
            "episode_no": int(self.episode_no or 0),
            "scene_no": int(self.scene_no or 0),
            "status": self.status,
            "public_message": self.public_message,
            "public_progress": int(self.public_progress or 0),
            "visible_route_count": self.visible_route_count,
            "time_budget_scope": "single_episode",
            "single_episode_time_budget": dict(SINGLE_EPISODE_TIME_BUDGET),
            "candidate_returned_to_user": bool(self.candidate_content),
            "candidate_needs_user_confirmation": bool(self.candidate_content and not self.saved_as_canon),
            "saved_as_canon": bool(self.saved_as_canon),
            "current_workflow_step": current_workflow_step,
            "workflow_steps": workflow_steps,
            "candidate": candidate,
        }

    def as_private_status(self) -> dict[str, Any]:
        public = self.as_public_status()
        return {
            **public,
            "current_step_id": self.current_step_id,
            "started_at_ms": self.started_at_ms,
            "updated_at_ms": self.updated_at_ms,
            "internal_detail": self.internal_detail,
            "internal_attempts": [item.as_dict() for item in self.internal_attempts],
        }


@dataclass
class AtomicGenerationStep:
    step_id: str
    model_role: str
    public_progress: str
    status: AtomicStepStatus = "pending"
    input_hash: str = ""
    output_hash: str = ""
    duration_ms: int = 0
    retry_count: int = 0
    blocking_type: str = ""
    internal_detail: str = ""
    public_detail: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "step_id": self.step_id,
            "model_role": self.model_role,
            "public_progress": self.public_progress,
            "status": self.status,
            "input_hash": self.input_hash,
            "output_hash": self.output_hash,
            "duration_ms": self.duration_ms,
            "retry_count": self.retry_count,
            "blocking_type": self.blocking_type,
            "internal_detail": self.internal_detail,
            "public_detail": self.public_detail,
        }


@dataclass
class AtomicGenerationRun:
    project_id: str
    episode_no: int
    scene_no: int = 1
    steps: list[AtomicGenerationStep] = field(default_factory=list)
    final_content: str = ""
    public_status: str = PUBLIC_PROGRESS_GENERATING
    internal_status: str = ""

    def step(self, step_id: str) -> AtomicGenerationStep:
        for item in self.steps:
            if item.step_id == step_id:
                return item
        raise KeyError(step_id)

    def as_dict(self) -> dict[str, Any]:
        return {
            "project_id": self.project_id,
            "episode_no": self.episode_no,
            "scene_no": self.scene_no,
            "public_status": self.public_status,
            "internal_status": self.internal_status,
            "final_content_hash": stable_hash(self.final_content) if self.final_content else "",
            "steps": [item.as_dict() for item in self.steps],
        }


def resolve_strict_atomic_route_plan(
    metadata: dict[str, Any],
    *,
    base_generation_kwargs: dict[str, Any] | None = None,
) -> dict[str, dict[str, Any]]:
    """Resolve the approved DeepSeek/Kimi route for atomic generation.

    This is a route audit. It does not call any model and does not generate
    content.
    """
    plan: dict[str, dict[str, Any]] = {}
    for atomic_step_id, (source_step_id, required_provider) in STRICT_ATOMIC_STEP_ROUTES.items():
        route = resolve_step_generation_route(source_step_id, metadata, base_generation_kwargs)
        provider = str(route.generation_kwargs.get("provider") or "").strip()
        model = str(route.generation_kwargs.get("model") or "").strip()
        valid = bool(route.enabled and provider == required_provider and model)
        plan[atomic_step_id] = {
            "atomic_step_id": atomic_step_id,
            "source_step_id": source_step_id,
            "required_provider": required_provider,
            "provider": provider,
            "model": model,
            "temperature": route.temperature,
            "role": route.role,
            "role_label": route.role_label,
            "enabled": route.enabled,
            "valid": valid,
            "error_code": "" if valid else STRICT_ROUTE_ERROR,
            "reason": route.reason,
        }
    return plan


def strict_atomic_route_plan_ready(plan: dict[str, dict[str, Any]]) -> bool:
    return all(bool(item.get("valid")) for item in plan.values())


def atomic_route_failure_summary(plan: dict[str, dict[str, Any]]) -> list[str]:
    failures: list[str] = []
    for step_id, item in plan.items():
        if item.get("valid"):
            continue
        failures.append(
            f"{step_id}: expected {item.get('required_provider')}, got {item.get('provider') or 'missing'} / {item.get('model') or 'missing'}"
        )
    return failures


def _merge_research_provider_config(raw: Any) -> dict[str, dict[str, Any]]:
    raw_map = raw if isinstance(raw, dict) else {}
    merged: dict[str, dict[str, Any]] = {}
    for role, default_route in DEFAULT_RESEARCH_GENERATION_PROVIDERS.items():
        raw_route = raw_map.get(role) if isinstance(raw_map.get(role), dict) else {}
        provider = str(raw_route.get("provider") or "").strip()
        model = str(raw_route.get("model") or "").strip()
        if not provider:
            provider = str(default_route["provider"])
        if not model and provider == str(default_route["provider"]):
            model = str(default_route["model"])
        merged[role] = {"provider": provider, "model": model}
        if raw_route.get("temperature") is not None:
            try:
                merged[role]["temperature"] = float(raw_route.get("temperature"))
            except Exception:
                pass
    return merged


def normalize_research_script_request(req: Any) -> Any:
    """Force every script-generation request onto the single research chain.

    Old projects may still carry "normal" mode fields. They are accepted as
    compatibility input, but they no longer decide the execution route.
    """
    providers = _merge_research_provider_config(getattr(req, "advanced_generation_providers", {}) or {})
    updates = {
        "advanced_generation_mode": True,
        "advanced_generation_providers": providers,
        "advanced_generation_routes": {},
    }
    if hasattr(req, "model_copy"):
        return req.model_copy(update=updates)
    return req


def _metadata_from_research_request(req: Any) -> dict[str, Any]:
    return {
        "project": {
            "project_type": str(getattr(req, "project_type", "") or ""),
            "config": {
                "advanced_generation_mode": True,
                "advanced_generation_providers": getattr(req, "advanced_generation_providers", {}) or {},
                "advanced_generation_routes": {},
            },
        }
    }


def _research_request_hash(req: Any) -> str:
    return stable_hash({
        "project_id": getattr(req, "project_id", ""),
        "episode_no": getattr(req, "episode_no", 0),
        "scene_no": getattr(req, "scene_no", 0),
        "brief": getattr(req, "brief", ""),
        "episode_summary": getattr(req, "episode_summary", ""),
    })


def _record_research_execution_step(
    *,
    step_id: str,
    route: dict[str, Any],
    input_value: Any,
    output_value: Any,
    started_at: float,
    status: str = "completed",
    error: str = "",
) -> dict[str, Any]:
    return {
        "step_id": step_id,
        "source_step_id": str(route.get("source_step_id") or ""),
        "provider": str(route.get("provider") or ""),
        "model": str(route.get("model") or ""),
        "status": status,
        "input_value": input_value if isinstance(input_value, dict) else {},
        "input_hash": stable_hash(input_value),
        "output_hash": stable_hash(output_value),
        "duration_ms": int((time.perf_counter() - started_at) * 1000),
        "retry_count": 0,
        "error_hash": stable_hash(error) if error else "",
    }


def _notify_research_step(
    step_observer: Callable[[dict[str, Any]], None] | None,
    *,
    step_id: str,
    status: str,
    duration_ms: int | None = None,
) -> None:
    if step_observer is None:
        return
    event: dict[str, Any] = {
        "step_id": step_id,
        "status": status,
    }
    if duration_ms is not None:
        event["duration_ms"] = max(0, int(duration_ms or 0))
    step_observer(event)


def _run_research_step(
    *,
    execution_steps: list[dict[str, Any]],
    step_id: str,
    route: dict[str, Any],
    input_value: Any,
    call: Callable[[], Any],
    step_observer: Callable[[dict[str, Any]], None] | None = None,
) -> Any:
    started_at = time.perf_counter()
    _notify_research_step(step_observer, step_id=step_id, status="running")
    try:
        output_value = call()
    except Exception as exc:
        failed_step = _record_research_execution_step(
            step_id=step_id,
            route=route,
            input_value=input_value,
            output_value={"error_type": type(exc).__name__},
            started_at=started_at,
            status="failed",
            error=f"{type(exc).__name__}: {str(exc)[:300]}",
        )
        execution_steps.append(failed_step)
        _notify_research_step(
            step_observer,
            step_id=step_id,
            status="failed",
            duration_ms=int(failed_step.get("duration_ms") or 0),
        )
        raise
    completed_step = _record_research_execution_step(
        step_id=step_id,
        route=route,
        input_value=input_value,
        output_value=output_value,
        started_at=started_at,
    )
    execution_steps.append(completed_step)
    _notify_research_step(
        step_observer,
        step_id=step_id,
        status="completed",
        duration_ms=int(completed_step.get("duration_ms") or 0),
    )
    return output_value


def _route_generation_kwargs(route: dict[str, Any]) -> dict[str, Any]:
    return {
        "provider": str(route.get("provider") or "").strip(),
        "model": str(route.get("model") or "").strip(),
    }


_DIRECTOR_BLUEPRINT_LABELS = [
    "本集目标",
    "本集任务目标",
    "开场钩子",
    "开场任务卡",
    "谁失去控制",
    "失控点",
    "控制损失",
    "观众当场收益",
    "当场兑现",
    "观众收益",
    "结尾新钩子",
    "结尾钩子",
    "尾钩",
    "写手执行卡",
    "写手任务卡",
    "复核合同",
    "评审合同",
]


def _extract_director_label(raw_text: str, labels: list[str]) -> str:
    text = str(raw_text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not text:
        return ""
    label_group = "|".join(re.escape(label) for label in labels)
    all_label_group = "|".join(re.escape(label) for label in _DIRECTOR_BLUEPRINT_LABELS)
    pattern = re.compile(
        rf"(?:^|\n)\s*(?:[-*#\d\.、\)\s]*)?(?:{label_group})\s*[：:]\s*"
        rf"(.+?)(?=\n\s*(?:[-*#\d\.、\)\s]*)?(?:{all_label_group})\s*[：:]|\Z)",
        re.S,
    )
    match = pattern.search(text)
    if not match:
        return ""
    return re.sub(r"\n{2,}", "\n", match.group(1)).strip()


def _director_blueprint_from_text(raw_text: str) -> dict[str, Any]:
    text = str(raw_text or "").strip()
    episode_objective = _extract_director_label(text, ["本集目标", "本集任务目标"])
    opening_hook = _extract_director_label(text, ["开场钩子", "开场任务卡"])
    control_loss = _extract_director_label(text, ["谁失去控制", "失控点", "控制损失"])
    audience_payoff = _extract_director_label(text, ["观众当场收益", "当场兑现", "观众收益"])
    ending_hook = _extract_director_label(text, ["结尾新钩子", "结尾钩子", "尾钩"])
    writer_brief = _extract_director_label(text, ["写手执行卡", "写手任务卡"]) or text
    review_contract = _extract_director_label(text, ["复核合同", "评审合同"]) or text
    fallback_objective = text[:400]
    blueprint: dict[str, Any] = {
        "episode_objective": episode_objective or fallback_objective,
        "opening_hook": opening_hook,
        "control_loss": control_loss,
        "audience_payoff": audience_payoff,
        "ending_hook": ending_hook,
        "writer_brief": writer_brief,
        "review_contract": review_contract,
        "raw_text": text,
        "source": "deepseek_director",
    }
    if control_loss or audience_payoff:
        blueprint["payoff_target_contract"] = {
            "control_loss": control_loss,
            "audience_visible_payoff": audience_payoff,
        }
    if opening_hook:
        blueprint["segment_plan"] = {
            "hook": {
                "goal": opening_hook,
            },
        }
    return blueprint


def _director_blueprint_from_result(result: dict[str, Any]) -> dict[str, Any]:
    blueprint = result.get("director_blueprint") if isinstance(result, dict) else {}
    if isinstance(blueprint, dict) and blueprint:
        return blueprint
    raw_text = str(result.get("raw_text") or "").strip() if isinstance(result, dict) else ""
    return _director_blueprint_from_text(raw_text)


def _with_director_blueprint(req: Any, director_result: dict[str, Any]) -> Any:
    blueprint = _director_blueprint_from_result(director_result)
    updates = {
        "director_blueprint": blueprint,
        "director_blueprint_hash": stable_hash(blueprint),
        "writer_brief_hash": stable_hash(blueprint.get("writer_brief") or blueprint),
        "review_contract_hash": stable_hash(blueprint.get("review_contract") or blueprint),
    }
    if hasattr(req, "model_copy"):
        return req.model_copy(update=updates)
    return req


def _scene_max_tokens(req: Any) -> int:
    if str(getattr(req, "mode", "") or "") == "segment":
        seg_max_chars = int(
            getattr(req, "word_count_max", None)
            or {"hook": 280, "validation": 330, "explosion": 380, "resolution": 310}.get(
                str(getattr(req, "segment_id", "") or "hook"),
                330,
            )
        )
        return min(1100, max(420, int(seg_max_chars * 1.5) + 80))
    word_count_max = int(getattr(req, "word_count_max", 0) or 0)
    if word_count_max:
        return min(2600, max(800, int(word_count_max * 1.5) + 200))
    return 2200


def _default_director_executor(req: Any, route: dict[str, Any]) -> dict[str, Any]:
    from app.services.text_generation_service import generate_text

    system_prompt = "你是短剧工业化链路中的总导演，只负责为当前集生成可执行导演蓝图，不写剧本正文。"
    user_prompt = "\n".join([
        "请基于以下前置资料输出当前集导演蓝图，必须逐项使用这些标签：本集目标、开场钩子、谁失去控制、观众当场收益、结尾新钩子、写手执行卡、复核合同。",
        "不要写剧本正文，不要替写手输出台词。",
        "",
        f"项目大纲：{str(getattr(req, 'brief', '') or '').strip()}",
        f"本集标题：{str(getattr(req, 'episode_title', '') or '').strip()}",
        f"本集集纲：{str(getattr(req, 'episode_summary', '') or '').strip()}",
        f"本集冲突：{str(getattr(req, 'episode_conflict', '') or '').strip()}",
        f"本集钩子：{str(getattr(req, 'episode_hook', '') or '').strip()}",
        f"连续性备注：{str(getattr(req, 'continuity_notes', '') or '').strip()}",
        f"用户改稿接续：{str(getattr(req, 'manual_edit_context', {}) or {})[:1200]}",
        f"用户分步确认台：{str(getattr(req, 'step_confirmation_packet', {}) or {})[:1600]}",
        f"角色小传：{str(getattr(req, 'characters', []) or [])[:1600]}",
        f"RAG参考：{str(getattr(req, 'rag_context_pack', {}) or {})[:1200]}",
    ])
    raw_text = generate_text(
        system_prompt,
        user_prompt,
        **_route_generation_kwargs(route),
        temperature=0.2,
        max_tokens=DIRECTOR_BLUEPRINT_MAX_TOKENS,
        timeout_seconds=getattr(req, "generation_timeout_seconds", None),
        max_retries=getattr(req, "generation_max_retries", None),
    )
    return {
        "raw_text": raw_text,
        "director_blueprint": _director_blueprint_from_text(str(raw_text or "")),
    }


def _default_writer_executor(req: Any, route: dict[str, Any], director_result: dict[str, Any]) -> dict[str, Any]:
    from app.services.short_drama_advanced_generation import apply_testing_generation_route
    from app.services.short_drama_deep_audit import generation_kwargs_from_req
    from app.services.short_drama_scene_generation import (
        apply_testing_hard_repairs,
        evaluate_testing_scene,
        prepare_testing_script_generation,
        promote_scene_word_count_warnings,
    )
    from app.services.short_drama_text_format import count_testing_chars, hard_truncate_by_sentence
    from app.services.text_generation_service import generate_text

    req_with_blueprint = _with_director_blueprint(req, director_result)
    writer_req, _ = apply_testing_generation_route(
        req_with_blueprint,
        "script_draft",
        float(route.get("temperature") if route.get("temperature") is not None else 0.3),
    )
    system_prompt, user_prompt, quality_anchor_block = prepare_testing_script_generation(writer_req)
    content = generate_text(
        system_prompt,
        user_prompt,
        **generation_kwargs_from_req(writer_req),
        temperature=writer_req.temperature if writer_req.temperature is not None else float(route.get("temperature") or 0.3),
        max_tokens=_scene_max_tokens(writer_req),
    )
    content_text = apply_testing_hard_repairs(writer_req, str(content or "").strip())
    if writer_req.mode == "segment" and writer_req.word_count_max:
        content_text = hard_truncate_by_sentence(
            content_text,
            int(writer_req.word_count_max),
            exclude_punct=bool(writer_req.exclude_punctuation_for_count),
        )
    evaluation = evaluate_testing_scene(writer_req, content_text, quality_anchor_block)
    evaluation = promote_scene_word_count_warnings(writer_req, evaluation)
    evaluation["content"] = str(evaluation.get("content") or content_text).strip()
    evaluation["char_count_excluding_punctuation"] = int(
        evaluation.get("char_count_excluding_punctuation")
        or count_testing_chars(evaluation["content"], exclude_punctuation=bool(writer_req.exclude_punctuation_for_count))
    )
    return evaluation


def _default_review_executor(
    req: Any,
    route: dict[str, Any],
    director_result: dict[str, Any],
    writer_candidate: dict[str, Any],
) -> dict[str, Any]:
    from app.services.short_drama_advanced_generation import apply_testing_generation_route
    from app.services.short_drama_evaluation_pipeline import apply_scene_level_gate
    from app.services.short_drama_final_generation_contract import current_testing_final_generation_contract
    from app.services.short_drama_scene_generation import promote_scene_word_count_warnings

    req_with_blueprint = _with_director_blueprint(req, director_result)
    reviewer_req, _ = apply_testing_generation_route(
        req_with_blueprint,
        "quality_check",
        float(route.get("temperature") if route.get("temperature") is not None else 0.1),
    )
    reviewed = apply_scene_level_gate(
        reviewer_req,
        dict(writer_candidate),
        current_testing_final_generation_contract(reviewer_req),
    )
    reviewed = promote_scene_word_count_warnings(reviewer_req, reviewed)
    reviewed.setdefault("same_blueprint_review", {
        "reviewed": True,
        "director_blueprint_hash": stable_hash(_director_blueprint_from_result(director_result)),
    })
    return reviewed


def run_research_script_generation(
    req: Any,
    *,
    director_executor: Callable[[Any, dict[str, Any]], dict[str, Any]] | None = None,
    writer_executor: Callable[[Any, dict[str, Any], dict[str, Any]], dict[str, Any]] | None = None,
    review_executor: Callable[[Any, dict[str, Any], dict[str, Any], dict[str, Any]], dict[str, Any]] | None = None,
    step_observer: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """Run the single backend research chain with real D1/W1/Q1 step evidence.

    The default executors call the configured DeepSeek/Kimi model route. Tests
    may inject executors, but the orchestration contract stays the same.
    """
    research_req = normalize_research_script_request(req)
    route_plan = resolve_strict_atomic_route_plan(_metadata_from_research_request(research_req))
    if not strict_atomic_route_plan_ready(route_plan):
        detail = "；".join(atomic_route_failure_summary(route_plan))
        raise AtomicRouteConfigError(
            public_message=PUBLIC_MODEL_RECOVERY_EXHAUSTED,
            internal_detail=detail,
            route_plan=route_plan,
        )

    director_executor = director_executor or _default_director_executor
    writer_executor = writer_executor or _default_writer_executor
    review_executor = review_executor or _default_review_executor
    execution_steps: list[dict[str, Any]] = []
    request_hash = _research_request_hash(research_req)

    director_result = _run_research_step(
        execution_steps=execution_steps,
        step_id="D1_director_blueprint",
        route=route_plan["D1_director_blueprint"],
        input_value={"request_hash": request_hash, "step": "director_blueprint"},
        call=lambda: director_executor(research_req, route_plan["D1_director_blueprint"]),
        step_observer=step_observer,
    )
    if not isinstance(director_result, dict):
        director_result = {"raw_text": str(director_result or "")}
    req_with_blueprint = _with_director_blueprint(research_req, director_result)
    from app.services.short_drama_final_generation_contract import (
        attach_rag_evidence_to_final_generation_contract,
        current_testing_final_generation_contract,
    )
    from app.services.short_drama_rag_cards import (
        compile_testing_rag_context_cards,
        select_testing_rag_cards_for_segment,
    )

    req_for_contract = req_with_blueprint.model_copy(update={"final_generation_contract": {}})
    core_generation_contract = current_testing_final_generation_contract(req_for_contract, include_rag=False)
    req_with_core_contract = req_for_contract.model_copy(update={
        "final_generation_contract": core_generation_contract,
    })
    rag_cards = select_testing_rag_cards_for_segment(
        req_with_core_contract,
        compile_testing_rag_context_cards(req_with_core_contract, source_contract=core_generation_contract),
    )
    final_generation_contract = attach_rag_evidence_to_final_generation_contract(
        core_generation_contract,
        rag_cards,
    )
    req_with_blueprint = req_for_contract.model_copy(update={
        "final_generation_contract": final_generation_contract,
    })
    final_generation_contract_hash = str(final_generation_contract.get("final_generation_contract_hash") or "")

    writer_candidate = _run_research_step(
        execution_steps=execution_steps,
        step_id="W1_writer_hook",
        route=route_plan["W1_writer_hook"],
        input_value={
            "request_hash": request_hash,
            "director_output_hash": stable_hash(director_result),
            "final_generation_contract_hash": final_generation_contract_hash,
            "step": "script_draft",
        },
        call=lambda: writer_executor(req_with_blueprint, route_plan["W1_writer_hook"], director_result),
        step_observer=step_observer,
    )
    if not isinstance(writer_candidate, dict):
        writer_candidate = {"content": str(writer_candidate or "")}

    reviewed_candidate = _run_research_step(
        execution_steps=execution_steps,
        step_id="Q1_deepseek_review",
        route=route_plan["Q1_deepseek_review"],
        input_value={
            "request_hash": request_hash,
            "director_output_hash": stable_hash(director_result),
            "writer_output_hash": stable_hash(writer_candidate),
            "final_generation_contract_hash": final_generation_contract_hash,
            "step": "quality_check",
        },
        call=lambda: review_executor(
            req_with_blueprint,
            route_plan["Q1_deepseek_review"],
            director_result,
            writer_candidate,
        ),
        step_observer=step_observer,
    )
    if not isinstance(reviewed_candidate, dict):
        reviewed_candidate = {}

    director_blueprint = _director_blueprint_from_result(director_result)
    result = dict(writer_candidate)
    result.update(reviewed_candidate)
    result["director_blueprint"] = director_blueprint
    result["_research_chain"] = {
        "route_ready": True,
        "request_hash": request_hash,
        "steps": list(RESEARCH_SCRIPT_CHAIN_STEPS),
        "route_plan": route_plan,
        "execution_steps": execution_steps,
        "director_blueprint_hash": stable_hash(director_blueprint),
        "final_generation_contract_hash": final_generation_contract_hash,
        "core_generation_contract_hash": final_generation_contract.get("core_generation_contract_hash") or "",
        "rag_evidence_hash": final_generation_contract.get("rag_evidence_hash") or "",
        "review_hash": stable_hash(reviewed_candidate),
        "candidate_content_hash": stable_hash(result.get("content") or "") if result.get("content") else "",
    }
    return result


def build_minimal_atomic_steps() -> list[AtomicGenerationStep]:
    return [
        AtomicGenerationStep("S0_input_snapshot", "local", "正在生成本集，请稍候…"),
        AtomicGenerationStep("D1_director_blueprint", "deepseek_director", "正在生成本集，请稍候…"),
        AtomicGenerationStep("D1L_blueprint_local_validate", "local", "正在整理正文"),
        AtomicGenerationStep("W1_writer_hook", "kimi_writer", "正在整理正文"),
    ]


def _complete_step(step: AtomicGenerationStep, *, input_value: Any, output_value: Any, started_at: float) -> None:
    step.status = "completed"
    step.input_hash = stable_hash(input_value)
    step.output_hash = stable_hash(output_value)
    step.duration_ms = int((time.perf_counter() - started_at) * 1000)


def _fail_step(
    step: AtomicGenerationStep,
    *,
    input_value: Any,
    started_at: float,
    blocking_type: str,
    internal_detail: str,
    public_detail: str,
    status: AtomicStepStatus = "failed",
) -> None:
    step.status = status
    step.input_hash = stable_hash(input_value)
    step.duration_ms = int((time.perf_counter() - started_at) * 1000)
    step.blocking_type = blocking_type
    step.internal_detail = internal_detail
    step.public_detail = public_detail


def validate_input_snapshot(snapshot: dict[str, Any]) -> list[str]:
    required = {
        "outline": "大纲",
        "episode_contract": "本集集纲",
        "characters": "人物小传",
    }
    missing: list[str] = []
    for key, label in required.items():
        value = snapshot.get(key)
        if isinstance(value, str) and value.strip():
            continue
        if isinstance(value, (list, dict)) and value:
            continue
        missing.append(label)
    return missing


def validate_minimal_blueprint(blueprint: dict[str, Any]) -> list[str]:
    missing: list[str] = []
    if not str(blueprint.get("episode_objective") or "").strip():
        missing.append("本集目标")
    payoff = blueprint.get("payoff_target_contract")
    if not isinstance(payoff, dict) or not payoff:
        missing.append("观众收益")
    segment_plan = blueprint.get("segment_plan")
    if not isinstance(segment_plan, dict) or not isinstance(segment_plan.get("hook"), dict):
        missing.append("开场任务卡")
    return missing


def run_minimal_atomic_probe(
    *,
    project_id: str,
    episode_no: int,
    scene_no: int,
    input_snapshot: dict[str, Any],
    director_blueprint_call: Callable[[dict[str, Any]], dict[str, Any]],
    writer_hook_call: Callable[[dict[str, Any]], str],
) -> AtomicGenerationRun:
    """Run S0 -> D1 -> D1L -> W1 with injected model calls.

    The injected callables are the only places where model content can be
    produced. This keeps Codex as the supervisor of the chain, not the writer.
    """
    run = AtomicGenerationRun(
        project_id=project_id,
        episode_no=max(1, int(episode_no)),
        scene_no=max(1, int(scene_no)),
        steps=build_minimal_atomic_steps(),
    )

    s0 = run.step("S0_input_snapshot")
    started = time.perf_counter()
    s0.status = "running"
    missing = validate_input_snapshot(input_snapshot)
    if missing:
        detail = "前置资料缺失：" + "、".join(missing)
        _fail_step(
            s0,
            input_value=input_snapshot,
            started_at=started,
            blocking_type="input_snapshot_incomplete",
            internal_detail=detail,
            public_detail=PUBLIC_INPUT_BLOCKED,
            status="blocked",
        )
        run.public_status = PUBLIC_INPUT_BLOCKED
        run.internal_status = detail
        return run
    _complete_step(s0, input_value=input_snapshot, output_value=input_snapshot, started_at=started)

    d1 = run.step("D1_director_blueprint")
    started = time.perf_counter()
    d1.status = "running"
    try:
        blueprint = director_blueprint_call(input_snapshot)
    except Exception as exc:
        detail = f"{type(exc).__name__}: {str(exc)[:240]}"
        _fail_step(
            d1,
            input_value=input_snapshot,
            started_at=started,
            blocking_type="director_blueprint_call_failed",
            internal_detail=detail,
            public_detail=PUBLIC_MODEL_RECOVERY_EXHAUSTED,
        )
        run.public_status = PUBLIC_MODEL_RECOVERY_EXHAUSTED
        run.internal_status = detail
        return run
    _complete_step(d1, input_value=input_snapshot, output_value=blueprint, started_at=started)

    d1l = run.step("D1L_blueprint_local_validate")
    started = time.perf_counter()
    d1l.status = "running"
    blueprint_missing = validate_minimal_blueprint(blueprint)
    if blueprint_missing:
        detail = "导演蓝图缺失：" + "、".join(blueprint_missing)
        _fail_step(
            d1l,
            input_value=blueprint,
            started_at=started,
            blocking_type="director_blueprint_incomplete",
            internal_detail=detail,
            public_detail=PUBLIC_INPUT_BLOCKED,
            status="blocked",
        )
        run.public_status = PUBLIC_INPUT_BLOCKED
        run.internal_status = detail
        return run
    _complete_step(d1l, input_value=blueprint, output_value={"blueprint_ready": True}, started_at=started)

    w1 = run.step("W1_writer_hook")
    started = time.perf_counter()
    w1.status = "running"
    try:
        hook_content = str(writer_hook_call(blueprint) or "").strip()
    except Exception as exc:
        detail = f"{type(exc).__name__}: {str(exc)[:240]}"
        _fail_step(
            w1,
            input_value=blueprint,
            started_at=started,
            blocking_type="writer_hook_call_failed",
            internal_detail=detail,
            public_detail=PUBLIC_MODEL_RECOVERY_EXHAUSTED,
        )
        run.public_status = PUBLIC_MODEL_RECOVERY_EXHAUSTED
        run.internal_status = detail
        return run
    if not hook_content:
        _fail_step(
            w1,
            input_value=blueprint,
            started_at=started,
            blocking_type="writer_hook_empty",
            internal_detail="Kimi 写手开场段返回空内容",
            public_detail=PUBLIC_MODEL_RECOVERY_EXHAUSTED,
        )
        run.public_status = PUBLIC_MODEL_RECOVERY_EXHAUSTED
        run.internal_status = "Kimi 写手开场段返回空内容"
        return run
    _complete_step(w1, input_value=blueprint, output_value=hook_content, started_at=started)
    run.final_content = hook_content
    run.public_status = PUBLIC_CANDIDATE_READY
    run.internal_status = "minimal_atomic_probe_completed"
    return run
