from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.services.official_source_consistency import (
    OfficialSourceConsistencyError,
    validate_locked_official_source_consistency,
)


class GenerationSourceBlocked(RuntimeError):
    """Raised when a generation source packet cannot be safely compiled."""

    def __init__(self, reason_code: str, *, detail: dict[str, Any] | None = None) -> None:
        self.reason_code = str(reason_code or "")
        self.detail = detail or {}
        super().__init__(self.reason_code)


def _body_excerpt(text: str, limit: int = 700) -> str:
    compact = " ".join(line.strip() for line in str(text or "").splitlines() if line.strip())
    return compact[-limit:].strip()


def _tail_excerpt(text: str, limit: int = 260) -> str:
    lines = [line.strip() for line in str(text or "").splitlines() if line.strip()]
    if not lines:
        return ""
    return lines[-1][-limit:].strip()


def _ignored_inputs(
    *,
    previous_episode_briefs: Any = None,
    manual_edit_context: Any = None,
) -> list[str]:
    ignored: list[str] = []
    if isinstance(previous_episode_briefs, list) and previous_episode_briefs:
        ignored.append("previous_episode_briefs")
    if isinstance(manual_edit_context, dict) and manual_edit_context:
        ignored.append("manual_edit_context")
    return ignored


def compile_previous_episode_continuity_packet(
    db: Session,
    *,
    project_id: str,
    episode_no: int,
    project_workspace_path: str,
    previous_episode_briefs: list[dict[str, Any]] | None = None,
    manual_edit_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    target_episode_no = max(1, int(episode_no or 1))
    if target_episode_no <= 1:
        return {
            "packet_version": "previous_episode_continuity_packet.v1",
            "episode_no": target_episode_no,
            "previous_episode_no": 0,
            "source": "series_start",
            "source_label": "series_start",
            "ready": True,
            "warnings": [],
            "authority_trace": {
                "previous_episode": {"source": "series_start"},
            },
        }

    previous_episode_no = target_episode_no - 1
    ignored_inputs = _ignored_inputs(
        previous_episode_briefs=previous_episode_briefs,
        manual_edit_context=manual_edit_context,
    )
    try:
        official = validate_locked_official_source_consistency(
            db,
            project_id=project_id,
            episode_number=previous_episode_no,
            project_workspace_path=project_workspace_path,
        )
    except OfficialSourceConsistencyError as exc:
        raise GenerationSourceBlocked(
            "previous_official_source_missing",
            detail={
                "project_id": project_id,
                "episode_no": target_episode_no,
                "previous_episode_no": previous_episode_no,
                "source_reason": exc.reason_code,
                "ignored_inputs": ignored_inputs,
            },
        ) from exc

    warnings: list[str] = []
    if isinstance(manual_edit_context, dict) and manual_edit_context:
        warnings.append("manual_edit_context_ignored_for_previous_official_source")
    if isinstance(previous_episode_briefs, list) and previous_episode_briefs:
        warnings.append("previous_episode_briefs_ignored_for_previous_official_source")

    return {
        "packet_version": "previous_episode_continuity_packet.v1",
        "episode_no": target_episode_no,
        "previous_episode_no": previous_episode_no,
        "source": "episode_locked_content_version",
        "source_label": "episode_locked_content_version",
        "official_source": "episode_locked",
        "content_version_id": official.content_version_id,
        "content_hash": official.content_hash,
        "episode_locked_event_id": official.episode_locked_event_id,
        "source_map": official.source_map,
        "body_excerpt": _body_excerpt(official.content),
        "tail_excerpt": _tail_excerpt(official.content),
        "ready": True,
        "warnings": warnings,
        "authority_trace": {
            "previous_episode": {
                "source": "episode_locked_content_version",
                "official_source": "episode_locked",
                "content_version_id": official.content_version_id,
            },
            "previous_episode_briefs": {
                "source": "reference_only",
                "used_as_official_source": False,
            },
            "manual_edit_context": {
                "source": "supplement_only",
                "used_as_official_source": False,
            },
        },
    }


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _safe_previous_episode_summary(previous: dict[str, Any]) -> dict[str, Any]:
    content_hash_prefix = str(previous.get("content_hash") or "")[:12]
    return {
        "source": str(previous.get("source") or ""),
        "previous_episode_no": int(previous.get("previous_episode_no") or 0),
        "content_version_id": str(previous.get("content_version_id") or ""),
        "content_hash": content_hash_prefix,
        "content_hash_prefix": content_hash_prefix,
        "episode_locked_event_id": str(previous.get("episode_locked_event_id") or ""),
        "ready": bool(previous.get("ready")),
    }


def generation_source_packet_safe_summary(packet: dict[str, Any]) -> dict[str, Any]:
    previous = _as_dict(packet.get("previous_episode_continuity"))
    frontend_trace = _as_dict(_as_dict(packet.get("authority_trace")).get("frontend_packet"))
    blocking_issues = list(packet.get("blocking_issues") or [])
    warnings = list(packet.get("warnings") or [])
    return {
        "source": str(packet.get("source") or ""),
        "source_packet_version": str(packet.get("source_packet_version") or ""),
        "project_id": str(packet.get("project_id") or ""),
        "episode_no": int(packet.get("episode_no") or 0),
        "confirmed_total_episodes": packet.get("confirmed_total_episodes"),
        "characters_count": int(packet.get("characters_count") or 0),
        "materials_count": int(packet.get("materials_count") or 0),
        "state_cards_keys": list(packet.get("state_cards_keys") or []),
        "blocking_issues": blocking_issues,
        "blocking_issues_count": len(blocking_issues),
        "warnings": warnings,
        "warnings_count": len(warnings),
        "ready": not blocking_issues,
        "previous_episode_continuity": _safe_previous_episode_summary(previous),
        "frontend_packet": {
            "source": str(frontend_trace.get("source") or ""),
            "input_present": bool(frontend_trace.get("input_present")),
            "used_as_authority_source": bool(frontend_trace.get("used_as_authority_source")),
        },
    }


def generation_source_packet_job_safe_summary(
    packet: dict[str, Any],
    *,
    scene_no: int = 1,
    segment_id: str = "",
) -> dict[str, Any]:
    summary = generation_source_packet_safe_summary(packet)
    return {
        "source": str(summary.get("source") or ""),
        "source_packet_version": str(summary.get("source_packet_version") or ""),
        "project_id": str(summary.get("project_id") or ""),
        "episode_no": int(summary.get("episode_no") or 0),
        "scene_no": max(1, int(scene_no or 1)),
        "segment_id": str(segment_id or ""),
        "ready": bool(summary.get("ready")),
        "previous_episode_continuity": summary.get("previous_episode_continuity") or {},
        "blocking_issues_count": int(summary.get("blocking_issues_count") or 0),
        "warnings_count": int(summary.get("warnings_count") or 0),
        "frontend_packet": summary.get("frontend_packet") or {},
    }


def validate_generation_source_packet_ready(packet: dict[str, Any]) -> None:
    issues = list(packet.get("blocking_issues") or [])
    if issues:
        raise GenerationSourceBlocked(
            "generation_source_packet_blocked",
            detail={"blocking_issues": issues},
        )

    episode_no = int(packet.get("episode_no") or 0)
    if episode_no <= 1:
        return None

    previous = _as_dict(packet.get("previous_episode_continuity"))
    if (
        str(previous.get("source") or "") != "episode_locked_content_version"
        or not bool(previous.get("ready"))
        or not str(previous.get("content_version_id") or "")
        or not str(previous.get("episode_locked_event_id") or "")
    ):
        raise GenerationSourceBlocked(
            "previous_official_source_missing",
            detail={
                "episode_no": episode_no,
                "previous_episode_no": int(previous.get("previous_episode_no") or 0),
                "actual_source": str(previous.get("source") or ""),
            },
        )
    return None


def compile_generation_source_packet(
    db: Session,
    *,
    project_id: str,
    episode_no: int,
    project_workspace_path: str,
    frontend_packet: dict[str, Any] | None = None,
    previous_episode_briefs: list[dict[str, Any]] | None = None,
    manual_edit_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Compile the backend-owned source packet used before final generation."""
    from app.services.short_drama_testing_enrich import load_testing_project_payload

    target_episode_no = max(1, int(episode_no or 1))
    project_payload, workspace_payload = load_testing_project_payload(db, project_id)
    config_payload = _as_dict(project_payload.get("config"))
    workflow_context = _as_dict(workspace_payload.get("workflow_context"))
    outline_state = _as_dict(workflow_context.get("outline_state"))
    materials = _as_list(workflow_context.get("materials"))
    characters = _as_list(workspace_payload.get("characters"))
    state_cards = _as_dict(workspace_payload.get("state_cards"))
    frontend = _as_dict(frontend_packet)

    previous_packet = compile_previous_episode_continuity_packet(
        db,
        project_id=project_id,
        episode_no=target_episode_no,
        project_workspace_path=project_workspace_path,
        previous_episode_briefs=previous_episode_briefs,
        manual_edit_context=manual_edit_context,
    )

    blocking_issues: list[str] = []
    if not characters:
        blocking_issues.append("characters_missing")
    if not config_payload.get("confirmed_total_episodes"):
        blocking_issues.append("confirmed_total_episodes_missing")

    packet = {
        "source_packet_version": "generation_source_packet.v1",
        "source": "backend_compiled_generation_source_packet",
        "project_id": project_id,
        "episode_no": target_episode_no,
        "confirmed_total_episodes": config_payload.get("confirmed_total_episodes"),
        "outline_source": {
            "source": "workspace.workflow_context.outline_state",
            "outline_state": outline_state,
        },
        "characters_count": len(characters),
        "state_cards_keys": sorted(str(key) for key in state_cards.keys()),
        "materials_count": len(materials),
        "previous_episode_continuity": previous_packet,
        "frontend_user_confirmed_packet_present": bool(frontend.get("user_confirmed_generation_packet")),
        "authority_trace": {
            "story_materials": {
                "source": "workspace.workflow_context.outline_state",
            },
            "characters": {
                "source": "project_workspace.characters",
                "count": len(characters),
            },
            "state_cards": {
                "source": "project_workspace.state_cards",
                "keys": sorted(str(key) for key in state_cards.keys()),
            },
            "rag_materials": {
                "source": "workspace.workflow_context.materials",
                "count": len(materials),
            },
            "confirmed_total_episodes": {
                "source": "project.config.confirmed_total_episodes",
            },
            "previous_episode_continuity": {
                "source": previous_packet.get("source"),
            },
            "frontend_packet": {
                "source": "compatibility_input_only",
                "input_present": bool(frontend),
                "used_as_authority_source": False,
            },
        },
        "blocking_issues": blocking_issues,
        "warnings": [],
    }
    packet["safe_summary"] = generation_source_packet_safe_summary(packet)
    return packet
