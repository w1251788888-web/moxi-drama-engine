"""C19.178 external human-review safe-label intake and runtime guard.

This module stores and reads only safe metadata labels. It must not persist
protected episode text, excerpts, prompts, raw request/response bodies, or
provider/runtime secrets.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from app.models.evidence import EvidenceEvent
from app.models.project_v2 import ProjectV2
from app.services.evidence_event_service import json_loads, record_evidence_event

C19_178_GATE_CONFIG_KEY = "c19_178_external_human_review"
C19_178_DECISION_EVENT_TYPE = "external_human_reviewer_decision_label"

ALLOWED_C19_178_SAFE_LABELS = {
    "human_accepts_concern_for_quality_audit",
    "human_requests_user_edit_or_note",
    "human_requests_controlled_regeneration_plan",
    "human_decision_inconclusive_needs_more_review",
}

C19_178_BRANCH_BY_LABEL = {
    "human_accepts_concern_for_quality_audit": {"readonly_quality_audit"},
    "human_requests_user_edit_or_note": {"user_edit_or_note_planning"},
    "human_requests_controlled_regeneration_plan": {"controlled_regeneration_planning"},
    "human_decision_inconclusive_needs_more_review": {"external_human_review_handoff"},
}

C19_178_HIGH_BOUNDARY_PATHS = {
    "readonly_quality_audit",
    "materialization",
    "official_lock",
    "compliance_scan",
    "export_package",
    "episode5_entry",
    "gate_a",
    "gate_b",
    "gate_c",
    "gate_d",
}

FORBIDDEN_METADATA_KEYS = {
    "text",
    "protected_text",
    "episode_text",
    "review_text",
    "full_text",
    "excerpt",
    "script_excerpt",
    "hook_text",
    "outline_text",
    "character_bio",
    "prompt",
    "request",
    "raw_request",
    "raw_request_body",
    "response",
    "raw_response",
    "raw_response_body",
    "raw_error",
    "raw_payload",
    "provider_url",
    "authorization",
    "auth",
    "api_key",
    "secret",
    "cert",
    "ca",
    "package_payload",
    "manifest_body",
    "browser_snapshot",
    "screenshot",
    "log",
    "logs",
}

SAFE_CODE_PATTERN = re.compile(r"^[a-zA-Z0-9_.:-]{0,120}$")
SAFE_HASH_PATTERN = re.compile(r"^[a-fA-F0-9]{0,64}$")
SAFE_REVIEW_METADATA_VALUE_PATTERN = re.compile(r"^[a-zA-Z0-9_.:-]{0,160}$")
PROTECTED_VALUE_MARKERS = (
    "begin_protected_text",
    "protected_episode_text",
    "protected_text",
    "script_excerpt",
    "full_text",
    "episode_text",
    "hook_text",
    "outline_text",
    "character_bio",
    "raw_request",
    "raw_response",
    "raw_error",
    "provider_url",
    "authorization",
    "api_key",
    "package_payload",
    "manifest_body",
    "browser_snapshot",
)


@dataclass(frozen=True)
class C19178GateDecision:
    allowed: bool
    reason_code: str
    selected_label: str = ""
    allowed_branch: str = ""
    target_path: str = ""


class C19178GateBlocked(RuntimeError):
    def __init__(self, decision: C19178GateDecision):
        self.decision = decision
        super().__init__(decision.reason_code)


def c19_178_gate_required(project: ProjectV2) -> bool:
    config = project.get_config() if hasattr(project, "get_config") else {}
    gate = config.get(C19_178_GATE_CONFIG_KEY)
    if not isinstance(gate, dict):
        return False
    status = str(gate.get("status") or "").strip()
    return bool(gate.get("required")) or status in {
        "awaiting_external_human_reviewer_decision",
        "external_human_reviewer_decision_label_missing",
        "continuity_concern_needs_external_decision",
    }


def _validate_no_protected_metadata(metadata: dict[str, Any]) -> None:
    for key, value in metadata.items():
        normalized_key = str(key or "").strip().lower()
        if normalized_key in FORBIDDEN_METADATA_KEYS:
            raise ValueError("protected_material_field_not_allowed")
        if isinstance(value, dict):
            _validate_no_protected_metadata(value)
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    _validate_no_protected_metadata(item)
                elif isinstance(item, str) and len(item) > 160:
                    raise ValueError("unsafe_metadata_value_too_long")
        elif isinstance(value, str) and len(value) > 160:
            raise ValueError("unsafe_metadata_value_too_long")


def _sanitize_nonlogging_review_metadata_value(value: Any) -> Any:
    if isinstance(value, dict):
        return sanitize_nonlogging_review_metadata(value)
    if isinstance(value, list):
        return [_sanitize_nonlogging_review_metadata_value(item) for item in value]
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, (int, float)):
        return value
    if not isinstance(value, str):
        raise ValueError("unsafe_metadata_value_type")
    if len(value) > 160:
        raise ValueError("unsafe_metadata_value_too_long")
    lowered = value.lower()
    if any(marker in lowered for marker in PROTECTED_VALUE_MARKERS):
        raise ValueError("protected_material_value_not_allowed")
    if not SAFE_REVIEW_METADATA_VALUE_PATTERN.fullmatch(value):
        raise ValueError("unsafe_metadata_value")
    return value


def sanitize_nonlogging_review_metadata(metadata: dict[str, Any] | None) -> dict[str, Any]:
    if metadata is None:
        return {}
    if not isinstance(metadata, dict):
        raise ValueError("unsafe_metadata_payload")
    sanitized: dict[str, Any] = {}
    for key, value in metadata.items():
        normalized_key = str(key or "").strip()
        if not normalized_key or len(normalized_key) > 120:
            raise ValueError("unsafe_metadata_key")
        lowered_key = normalized_key.lower()
        if lowered_key in FORBIDDEN_METADATA_KEYS:
            raise ValueError("protected_material_field_not_allowed")
        if not SAFE_CODE_PATTERN.fullmatch(normalized_key):
            raise ValueError("unsafe_metadata_key")
        sanitized[normalized_key] = _sanitize_nonlogging_review_metadata_value(value)
    return sanitized


def record_c19_178_external_safe_label(
    db: Session,
    *,
    project: ProjectV2,
    actor: Any,
    decision_label: str,
    reason_code: str,
    reviewer_role: str,
    reviewed_artifact_suffix: str = "",
    candidate_hash_short: str = "",
    no_excerpts_confirmed: bool = True,
    safe_review_metadata: dict[str, Any] | None = None,
) -> EvidenceEvent:
    label = str(decision_label or "").strip()
    if label not in ALLOWED_C19_178_SAFE_LABELS:
        raise ValueError("invalid_external_human_reviewer_decision_label")
    if not no_excerpts_confirmed:
        raise ValueError("no_excerpts_confirmation_required")
    if not SAFE_CODE_PATTERN.fullmatch(str(reason_code or "")):
        raise ValueError("unsafe_reason_code")
    if not SAFE_CODE_PATTERN.fullmatch(str(reviewer_role or "")):
        raise ValueError("unsafe_reviewer_role")
    if not SAFE_CODE_PATTERN.fullmatch(str(reviewed_artifact_suffix or "")):
        raise ValueError("unsafe_artifact_suffix")
    if not SAFE_HASH_PATTERN.fullmatch(str(candidate_hash_short or "")):
        raise ValueError("unsafe_candidate_hash_short")
    metadata = {
        "decision_label": label,
        "reason_code": str(reason_code or ""),
        "reviewer_role": str(reviewer_role or ""),
        "reviewed_artifact_suffix": str(reviewed_artifact_suffix or ""),
        "candidate_hash_short": str(candidate_hash_short or ""),
        "no_excerpts_confirmed": True,
        "allowed_branch": sorted(C19_178_BRANCH_BY_LABEL.get(label, set())),
        "protected_material_persisted": False,
    }
    clean_review_metadata = sanitize_nonlogging_review_metadata(safe_review_metadata)
    if clean_review_metadata:
        metadata["safe_review_metadata"] = clean_review_metadata
    _validate_no_protected_metadata(metadata)
    return record_evidence_event(
        db,
        project_id=project.id,
        actor=actor,
        event_type=C19_178_DECISION_EVENT_TYPE,
        target_type="c19_178_external_human_decision",
        target_id=str(reviewed_artifact_suffix or project.id),
        summary=f"C19.178 external safe label: {label}",
        metadata=metadata,
    )


def latest_c19_178_external_safe_label(db: Session, project_id: str) -> str:
    row = db.query(EvidenceEvent).filter(
        EvidenceEvent.project_id == project_id,
        EvidenceEvent.event_type == C19_178_DECISION_EVENT_TYPE,
    ).order_by(EvidenceEvent.created_at.desc()).first()
    if row is None:
        return ""
    metadata = json_loads(row.metadata_json, {})
    label = str(metadata.get("decision_label") or "").strip() if isinstance(metadata, dict) else ""
    if label not in ALLOWED_C19_178_SAFE_LABELS:
        return ""
    if not bool(metadata.get("no_excerpts_confirmed")):
        return ""
    return label


def evaluate_c19_178_runtime_gate(db: Session, *, project: ProjectV2, target_path: str) -> C19178GateDecision:
    path = str(target_path or "").strip()
    if not c19_178_gate_required(project):
        return C19178GateDecision(allowed=True, reason_code="c19_178_gate_not_required", target_path=path)
    label = latest_c19_178_external_safe_label(db, project.id)
    if not label:
        return C19178GateDecision(
            allowed=False,
            reason_code="external_human_reviewer_decision_label_missing",
            target_path=path,
        )
    allowed_paths = C19_178_BRANCH_BY_LABEL.get(label, set())
    if path in allowed_paths:
        return C19178GateDecision(
            allowed=True,
            reason_code="external_human_reviewer_decision_label_authorizes_branch",
            selected_label=label,
            allowed_branch=path,
            target_path=path,
        )
    return C19178GateDecision(
        allowed=False,
        reason_code="external_human_reviewer_decision_label_does_not_authorize_path",
        selected_label=label,
        allowed_branch=",".join(sorted(allowed_paths)),
        target_path=path,
    )


def assert_c19_178_runtime_gate(db: Session, *, project: ProjectV2, target_path: str) -> None:
    decision = evaluate_c19_178_runtime_gate(db, project=project, target_path=target_path)
    if not decision.allowed:
        raise C19178GateBlocked(decision)
