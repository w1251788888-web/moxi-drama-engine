"""Final generation contract compiler for the research writing chain.

This module is intentionally pure: no AI calls, no DB, no file IO. It turns the
many request-side truth sources into one auditable contract so generation,
retrieval, review, and user-facing status can later read the same evidence.
"""
from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from app.schemas.short_drama_writing import TestingScriptRequest


_VOLATILE_HASH_KEYS = {
    "final_generation_contract_hash",
    "generated_at",
    "updated_at",
    "warnings",
    "visible_issues",
    "public_message",
}

_CONFIRMATION_SCAFFOLD_TEXTS = {
    "请明确本集必须完成的剧情推进。",
    "请明确本集谁在关系、证据、舆论或局面上失去控制。",
    "请明确观众这一集能看到的信息增量、反转或情绪兑现。",
    "人物关系变化必须由动作触发，不能突然变脸。",
    "请明确结尾落在哪个具体动作、台词、物件或信息上。",
    "请明确本集主要发生在哪个可拍摄空间，以及谁必须在场。",
}


def _clean_text(value: Any, *, limit: int = 1200) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    return text[:limit]


def _is_confirmation_scaffold_text(value: str) -> bool:
    text = _clean_text(value)
    if not text:
        return False
    normalized = text.rstrip("。.!！")
    return any(
        normalized == scaffold.rstrip("。.!！")
        for scaffold in _CONFIRMATION_SCAFFOLD_TEXTS
    )


def _stable_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _hashable_contract(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): _hashable_contract(item)
            for key, item in value.items()
            if str(key) not in _VOLATILE_HASH_KEYS
        }
    if isinstance(value, list):
        return [_hashable_contract(item) for item in value]
    return value


def final_generation_contract_hash(contract: dict[str, Any]) -> str:
    payload = _stable_json(_hashable_contract(contract if isinstance(contract, dict) else {}))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _hash_is_valid(contract: dict[str, Any]) -> bool:
    supplied = _clean_text(contract.get("final_generation_contract_hash"), limit=128)
    if not supplied:
        return False
    return supplied == final_generation_contract_hash(contract)


def _copy_if_valid_existing(req: "TestingScriptRequest") -> dict[str, Any]:
    raw = getattr(req, "final_generation_contract", {}) or {}
    if isinstance(raw, dict) and _hash_is_valid(raw):
        return deepcopy(raw)
    return {}


def _items_to_map(
    value: Any,
    *,
    allowed_steps: tuple[str, ...] | None = None,
    current_step: str = "",
) -> dict[str, str]:
    if allowed_steps is not None and current_step and current_step not in allowed_steps:
        return {}
    result: dict[str, str] = {}
    if isinstance(value, dict):
        items = value.get("items")
        if isinstance(items, list):
            for item in items:
                if not isinstance(item, dict):
                    continue
                item_step = _clean_text(item.get("step_id") or item.get("stepId") or current_step, limit=80)
                if allowed_steps is not None and item_step and item_step not in allowed_steps:
                    continue
                key = _clean_text(item.get("itemKey") or item.get("key"), limit=120)
                body = _clean_text(item.get("body") or item.get("value") or item.get("text"))
                if key and body:
                    result[key] = body
        for key, body in value.items():
            if key in {"items", "summary", "note"}:
                continue
            if isinstance(body, (str, int, float)):
                text = _clean_text(body)
                if text:
                    result[str(key)] = text
    return result


def _packet_step_map(
    packet: Any,
    step: str,
    *,
    allowed_steps: tuple[str, ...] | None = None,
) -> dict[str, str]:
    if not isinstance(packet, dict):
        return {}
    if allowed_steps is not None and step not in allowed_steps:
        return {}
    section = packet.get(step)
    if isinstance(section, dict):
        return _items_to_map(section, allowed_steps=allowed_steps, current_step=step)
    return {}


def _packet_value(
    packet: Any,
    aliases: tuple[str, ...],
    *,
    allowed_steps: tuple[str, ...] | None = None,
) -> tuple[str, str]:
    if not isinstance(packet, dict):
        return "", ""
    maps = [
        _items_to_map(packet, allowed_steps=allowed_steps),
        _packet_step_map(packet, "blueprint", allowed_steps=allowed_steps),
        _packet_step_map(packet, "prerequisite", allowed_steps=allowed_steps),
        _packet_step_map(packet, "segment_cards", allowed_steps=allowed_steps),
        _packet_step_map(packet, "candidate_save", allowed_steps=allowed_steps),
    ]
    for mapping in maps:
        for alias in aliases:
            text = mapping.get(alias)
            if text and not _is_confirmation_scaffold_text(text):
                return text, alias
    return "", ""


def _line_field(text: str, labels: tuple[str, ...]) -> str:
    for raw_line in str(text or "").splitlines():
        line = raw_line.strip()
        for label in labels:
            marker = f"{label}："
            if marker in line:
                return _clean_text(line.split(marker, 1)[1])
    return ""


def _episode_contract_value(contract: Any, aliases: tuple[str, ...]) -> tuple[str, str]:
    if not isinstance(contract, dict):
        return "", ""
    for alias in aliases:
        value = contract.get(alias)
        if isinstance(value, list):
            value = "\n".join(str(item) for item in value if str(item).strip())
        text = _clean_text(value)
        if text:
            return text, alias
    for field in ("must_happen", "summary", "episode_summary"):
        value = contract.get(field)
        if isinstance(value, list):
            value = "\n".join(str(item) for item in value if str(item).strip())
        if text := _line_field(str(value or ""), aliases):
            return text, field
    must_happen = contract.get("must_happen")
    if isinstance(must_happen, list):
        marker_aliases = {
            "required_main_scene": ("主场景必须落地", "主场景"),
            "audience_visible_payoff": ("当场后果必须可见", "当场收益", "当场后果"),
            "who_loses_control": ("公开压迫必须落地", "谁失去控制", "失控点"),
            "ending_hook": ("结尾钩子落到具体画面", "结尾钩子"),
        }
        matched_markers: tuple[str, ...] = ()
        for canonical, markers in marker_aliases.items():
            if canonical in aliases or any(alias in aliases for alias in markers):
                matched_markers = markers
                break
        for raw in must_happen:
            line = _clean_text(raw)
            if not line:
                continue
            for marker in matched_markers:
                if marker not in line:
                    continue
                if "：" in line:
                    return _clean_text(line.split("：", 1)[1]), "must_happen"
                if ":" in line:
                    return _clean_text(line.split(":", 1)[1]), "must_happen"
                return _clean_text(line.replace(marker, "").strip(" ：:")), "must_happen"
    return "", ""


def _director_nested_value(blueprint: dict[str, Any], path: tuple[str, ...]) -> str:
    value: Any = blueprint
    for key in path:
        if not isinstance(value, dict):
            return ""
        value = value.get(key)
    return _clean_text(value)


def _director_value(blueprint: Any, aliases: tuple[str, ...]) -> tuple[str, str]:
    if not isinstance(blueprint, dict):
        return "", ""
    for alias in aliases:
        text = _clean_text(blueprint.get(alias))
        if text:
            return text, alias
    nested_paths = {
        "who_loses_control": (
            ("payoff_target_contract", "control_loss"),
            ("episode_visible_stakes_contract", "visible_stakes_or_loss"),
        ),
        "audience_visible_payoff": (
            ("payoff_target_contract", "audience_visible_payoff"),
            ("payoff_target_contract", "visible_gain"),
            ("evidence_chain", "visible_consequence"),
        ),
        "ending_hook": (
            ("continuity_contract", "outgoing_hook"),
            ("continuity_contract", "ending_hook"),
        ),
    }
    for canonical, paths in nested_paths.items():
        if canonical not in aliases:
            continue
        for path in paths:
            text = _director_nested_value(blueprint, path)
            if text:
                return text, ".".join(path)
    return "", ""


def _field_from_sources(
    *,
    field: str,
    user_packet: dict[str, Any],
    step_packet: dict[str, Any],
    director_blueprint: dict[str, Any],
    episode_contract: dict[str, Any],
    aliases: tuple[str, ...],
) -> tuple[str, str]:
    value, source_key = _packet_value(user_packet, aliases, allowed_steps=("blueprint",))
    if value:
        return value, f"user_confirmed_generation_packet.{source_key}"
    value, source_key = _packet_value(step_packet, aliases, allowed_steps=("blueprint",))
    if value:
        return value, f"step_confirmation_packet.{source_key}"
    value, source_key = _director_value(director_blueprint, (field, *aliases))
    if value:
        return value, f"director_blueprint.{source_key}"
    value, source_key = _episode_contract_value(episode_contract, aliases)
    if value:
        return value, f"episode_contract.{source_key}"
    return "", ""


def _manual_edit_latest(req: "TestingScriptRequest") -> dict[str, Any]:
    context = getattr(req, "manual_edit_context", {}) or {}
    if not isinstance(context, dict):
        return {}
    latest = context.get("latest")
    if isinstance(latest, dict):
        return latest
    logs = context.get("logs")
    if isinstance(logs, list):
        for item in logs:
            if isinstance(item, dict):
                return item
    return {}


def _manual_edit_canon(latest: dict[str, Any]) -> tuple[str, str]:
    if not latest:
        return "", ""
    delta = latest.get("manual_edit_delta") if isinstance(latest.get("manual_edit_delta"), dict) else {}
    canon_patch = latest.get("canon_patch") if isinstance(latest.get("canon_patch"), dict) else {}
    facts = canon_patch.get("locked_facts") if isinstance(canon_patch.get("locked_facts"), list) else []
    parts = [
        _clean_text(latest.get("current_excerpt")),
        _clean_text(delta.get("tail_added")),
        _clean_text(delta.get("current_excerpt")),
        _clean_text(latest.get("tail_excerpt")),
        "\n".join(_clean_text(item) for item in facts if _clean_text(item)),
    ]
    text = "\n".join(part for part in parts if part)
    return text, "manual_edit_context.latest" if text else ""


def _conflict(
    *,
    field: str,
    preferred_source: str,
    stale_source: str,
    preferred_value: str,
    stale_value: str,
    confirmed_after_conflict_review: bool,
) -> dict[str, Any]:
    auto_resolved = preferred_source.startswith((
        "user_confirmed_generation_packet",
        "step_confirmation_packet",
        "director_blueprint",
    ))
    return {
        "type": "stale_episode_contract",
        "field": field,
        "preferred_source": preferred_source,
        "stale_source": stale_source,
        "preferred_value": preferred_value,
        "stale_value": stale_value,
        "auto_resolved": auto_resolved,
        "resolution_strategy": "prefer_confirmed_generation_contract" if auto_resolved else "",
        "user_action_required": False if auto_resolved else not confirmed_after_conflict_review,
    }


def _conflict_resolution(req: "TestingScriptRequest") -> dict[str, Any]:
    packets = [
        getattr(req, "user_confirmed_generation_packet", {}) or {},
        getattr(req, "step_confirmation_packet", {}) or {},
    ]
    for packet in packets:
        if not isinstance(packet, dict):
            continue
        raw = packet.get("conflict_resolution")
        if isinstance(raw, dict) and raw.get("confirmed_after_conflict_review") is True:
            return {
                "confirmed_after_conflict_review": True,
                "resolved_by": _clean_text(raw.get("resolved_by")),
                "resolved_at": _clean_text(raw.get("resolved_at")),
                "resolution_source": _clean_text(raw.get("resolution_source") or "user_confirmation"),
            }
    return {
        "confirmed_after_conflict_review": False,
        "resolved_by": "",
        "resolved_at": "",
        "resolution_source": "",
    }


def _generation_source_packet(req: "TestingScriptRequest") -> dict[str, Any]:
    packet = getattr(req, "generation_source_packet", {}) or {}
    return packet if isinstance(packet, dict) else {}


def _previous_episode_continuity_packet(
    req: "TestingScriptRequest",
    generation_source_packet: dict[str, Any],
) -> tuple[dict[str, Any], str]:
    previous = generation_source_packet.get("previous_episode_continuity")
    if isinstance(previous, dict) and previous:
        return previous, "generation_source_packet.previous_episode_continuity"
    fallback = getattr(req, "previous_episode_continuity_packet", {}) or {}
    if isinstance(fallback, dict) and fallback:
        return fallback, "previous_episode_continuity_packet"
    return {}, ""


def _previous_episode_continuity_text(packet: dict[str, Any]) -> str:
    for key in ("body_excerpt", "tail_excerpt", "actual_progress", "ending_state"):
        text = _clean_text(packet.get(key))
        if text:
            return text
    return ""


def _record_generation_source_trace(
    *,
    req: "TestingScriptRequest",
    contract: dict[str, Any],
    trace: dict[str, Any],
) -> None:
    source_packet = _generation_source_packet(req)
    if source_packet:
        trace["generation_source_packet"] = {
            "source": _clean_text(source_packet.get("source"), limit=160),
            "source_packet_version": _clean_text(source_packet.get("source_packet_version"), limit=160),
        }
        source_authority = source_packet.get("authority_trace")
        if isinstance(source_authority, dict):
            frontend = source_authority.get("frontend_packet")
            if isinstance(frontend, dict):
                trace["frontend_packet"] = {
                    "source": _clean_text(frontend.get("source"), limit=160),
                    "used_as_authority_source": bool(frontend.get("used_as_authority_source") is True),
                }

    previous_packet, previous_source = _previous_episode_continuity_packet(req, source_packet)
    if not previous_packet:
        return

    trace["previous_episode_continuity"] = {
        "source": _clean_text(previous_packet.get("source"), limit=160),
        "content_version_id": _clean_text(previous_packet.get("content_version_id"), limit=160),
    }
    previous_text = _previous_episode_continuity_text(previous_packet)
    if previous_text:
        contract["continuity_from_previous"] = previous_text
        trace["continuity_from_previous"] = previous_source


def _word_policy(req: "TestingScriptRequest") -> dict[str, Any]:
    target = int(getattr(req, "word_count_target", None) or getattr(req, "target_chars", None) or 0)
    min_count = int(getattr(req, "word_count_min", None) or 0)
    max_count = int(getattr(req, "word_count_max", None) or 0)
    return {
        "target": target,
        "min": min_count,
        "max": max_count,
        "minor_overflow_tolerance": 0.12,
        "minor_underflow_tolerance": 0.10,
    }


def _base_contract(req: "TestingScriptRequest") -> dict[str, Any]:
    return {
        "contract_version": "final_generation_contract.v1",
        "episode_no": int(getattr(req, "episode_no", 0) or 0),
        "core_generation_contract_hash": "",
        "rag_evidence_hash": "",
        "field_authority_order": {
            "continuity_from_previous": [
                "generation_source_packet.previous_episode_continuity",
                "previous_episode_continuity_packet",
                "manual_edit_context",
                "episode_memory_cards",
                "previous_episode_briefs",
                "user_confirmed_generation_packet",
                "series_simulation_packet",
                "episode_contract",
            ],
            "current_episode_task": [
                "user_confirmed_generation_packet",
                "step_confirmation_packet",
                "director_blueprint",
                "locked_outline",
                "series_simulation_packet",
                "episode_contract",
            ],
            "review_and_quality_contract": [
                "user_confirmed_generation_packet",
                "director_blueprint",
                "step_confirmation_packet",
                "series_simulation_packet",
                "episode_contract",
            ],
        },
        "episode_goal": "",
        "required_main_scene": "",
        "who_loses_control": "",
        "audience_visible_payoff": "",
        "character_boundaries": "",
        "ending_hook": "",
        "continuity_from_previous": "",
        "previous_user_canon": "",
        "segment_plan": [],
        "relationship_timeline_context": getattr(req, "relationship_timeline_context", {}) or {},
        "word_count_policy": _word_policy(req),
        "rag_query_contract": {},
        "review_contract": {},
        "authority_trace": {},
        "contract_conflicts": [],
        "blocking_conflicts": [],
        "conflict_resolution": _conflict_resolution(req),
        "warnings": [],
        "final_generation_contract_hash": "",
    }


def _add_episode_contract_conflict(
    *,
    contract: dict[str, Any],
    trace: dict[str, Any],
    episode_contract: dict[str, Any],
    field: str,
    aliases: tuple[str, ...],
    confirmed_after_review: bool,
) -> None:
    stale_value, stale_source_key = _episode_contract_value(episode_contract, aliases)
    preferred = contract.get(field) or ""
    preferred_source = trace.get(field, "")
    if (
        stale_value
        and preferred
        and stale_value != preferred
        and preferred_source
        and not str(preferred_source).startswith("episode_contract")
    ):
        item = _conflict(
            field=field,
            preferred_source=preferred_source,
            stale_source=f"episode_contract.{stale_source_key}",
            preferred_value=preferred,
            stale_value=stale_value,
            confirmed_after_conflict_review=confirmed_after_review,
        )
        contract["contract_conflicts"].append(item)
        if item["user_action_required"]:
            contract["blocking_conflicts"].append(item)


def compile_testing_final_generation_contract(
    req: "TestingScriptRequest",
    *,
    include_rag: bool = True,
) -> dict[str, Any]:
    existing = _copy_if_valid_existing(req)
    if existing:
        return existing

    user_packet = getattr(req, "user_confirmed_generation_packet", {}) or {}
    step_packet = getattr(req, "step_confirmation_packet", {}) or {}
    director_blueprint = getattr(req, "director_blueprint", {}) or {}
    episode_contract = getattr(req, "episode_contract", {}) or {}
    contract = _base_contract(req)
    trace = contract["authority_trace"]
    _record_generation_source_trace(req=req, contract=contract, trace=trace)

    manual_text, manual_source = _manual_edit_canon(_manual_edit_latest(req))
    if manual_text and not contract.get("continuity_from_previous"):
        contract["previous_user_canon"] = manual_text
        contract["continuity_from_previous"] = manual_text
        trace["previous_user_canon"] = manual_source
        trace["continuity_from_previous"] = manual_source

    field_aliases = {
        "episode_goal": ("episode_goal", "goal", "episode_objective", "本集目标"),
        "required_main_scene": ("required_main_scene", "main_scene", "scene", "主场景"),
        "who_loses_control": ("who_loses_control", "control_loss", "visible_stakes", "谁失去控制"),
        "audience_visible_payoff": ("audience_visible_payoff", "audience_payoff", "payoff", "观众当场收益"),
        "character_boundaries": ("character_boundaries", "character_boundary", "relationship_context", "人物边界"),
        "ending_hook": ("ending_hook", "outgoing_hook", "hook", "结尾钩子"),
    }
    for field, aliases in field_aliases.items():
        value, source = _field_from_sources(
            field=field,
            user_packet=user_packet,
            step_packet=step_packet,
            director_blueprint=director_blueprint if isinstance(director_blueprint, dict) else {},
            episode_contract=episode_contract if isinstance(episode_contract, dict) else {},
            aliases=aliases,
        )
        if value:
            contract[field] = value
            trace[field] = source

    if isinstance(director_blueprint, dict):
        segment_plan = director_blueprint.get("segment_plan")
        if isinstance(segment_plan, list):
            contract["segment_plan"] = segment_plan
        elif isinstance(segment_plan, dict):
            contract["segment_plan"] = [
                {"segment_id": key, "body": value}
                for key, value in segment_plan.items()
            ]

    confirmed_after_review = bool(contract["conflict_resolution"].get("confirmed_after_conflict_review"))
    episode_contract_for_conflict = episode_contract if isinstance(episode_contract, dict) else {}
    for field, aliases in {
        "required_main_scene": ("main_scene", "required_main_scene", "主场景"),
        "character_boundaries": ("character_boundaries", "character_boundary", "relationship_context", "人物边界"),
        "ending_hook": ("ending_hook", "outgoing_hook", "hook", "结尾钩子"),
    }.items():
        _add_episode_contract_conflict(
            contract=contract,
            trace=trace,
            episode_contract=episode_contract_for_conflict,
            field=field,
            aliases=aliases,
            confirmed_after_review=confirmed_after_review,
        )

    core_copy = deepcopy(contract)
    core_copy["rag_query_contract"] = {}
    core_copy["rag_evidence_hash"] = ""
    core_copy["final_generation_contract_hash"] = ""
    contract["core_generation_contract_hash"] = final_generation_contract_hash(core_copy)
    if include_rag:
        contract["rag_evidence_hash"] = final_generation_contract_hash(contract.get("rag_query_contract") or {})
    contract["final_generation_contract_hash"] = final_generation_contract_hash(contract)
    return contract


def current_testing_final_generation_contract(
    req: "TestingScriptRequest",
    *,
    include_rag: bool = True,
) -> dict[str, Any]:
    return compile_testing_final_generation_contract(req, include_rag=include_rag)


def attach_rag_evidence_to_final_generation_contract(
    core_contract: dict[str, Any],
    rag_cards: list[dict[str, Any]],
) -> dict[str, Any]:
    contract = deepcopy(core_contract if isinstance(core_contract, dict) else {})
    evidence = rag_cards if isinstance(rag_cards, list) else []
    contract["rag_query_contract"] = {
        "card_count": len(evidence),
        "cards": evidence[:8],
    }
    contract["rag_evidence_hash"] = final_generation_contract_hash(contract["rag_query_contract"])
    contract["final_generation_contract_hash"] = final_generation_contract_hash(contract)
    return contract


def format_final_generation_contract_block(req: "TestingScriptRequest", *, for_writer: bool = True) -> str:
    contract = current_testing_final_generation_contract(req, include_rag=False)
    lines = [
        "# 最终生成合同",
        f"final_generation_contract_hash={contract.get('final_generation_contract_hash') or ''}",
        f"- 第{int(contract.get('episode_no') or 0)}集目标：{contract.get('episode_goal') or '未提供'}",
        f"- 主场景：{contract.get('required_main_scene') or '未提供'}",
        f"- 谁失去控制：{contract.get('who_loses_control') or '未提供'}",
        f"- 观众当场收益：{contract.get('audience_visible_payoff') or '未提供'}",
        f"- 人物边界：{contract.get('character_boundaries') or '未提供'}",
        f"- 结尾钩子：{contract.get('ending_hook') or '未提供'}",
    ]
    if contract.get("continuity_from_previous"):
        lines.append(f"- 上一集用户定稿承接：{_clean_text(contract.get('continuity_from_previous'), limit=300)}")
    if for_writer:
        lines.append("写手必须执行本合同；旧 episode_contract 只能作兜底，不得覆盖用户确认和用户定稿。")
    return "\n".join(line for line in lines if str(line).strip())
