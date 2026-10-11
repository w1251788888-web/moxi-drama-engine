"""短剧测试页 workflow context / canon packet / episode contract 规范化函数。

从 short_drama_writing.py 抽出。所有函数都是纯数据变换，无 IO。
"""
from __future__ import annotations

from typing import Any

_GENERIC_OUTLINE_SCENES = {
    "公司会议室",
    "地下车库",
    "医院走廊",
    "直播间",
    "家族老宅",
    "废弃实验室",
    "警局门口",
    "新闻发布会",
    "餐厅包厢",
    "旧仓库",
    "法庭外",
    "学校礼堂",
    "酒店电梯",
    "码头",
    "董事会",
    "出租屋",
}


def testing_workflow_context_defaults() -> dict[str, Any]:
    return {
        "materials": [],
        "issue_feedback": {},
        "rule_profile": "",
        "world_rules": "",
        "golden_finger_rules": "",
        "conflict_plan": "",
        "quality_report": {},
        "compliance_report": {},
        "episode_novel_anchor": "",
        "rag_context": {},
        "series_simulation_packet": {},
        "rag_context_cards": [],
        "manual_edit_context": {},
        "step_confirmation_overrides": {},
    }


def normalize_testing_episode_memory_cards(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        return []
    cards: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        try:
            episode_no = int(item.get("episode_no") or item.get("ep") or 0)
        except Exception:
            episode_no = 0
        if episode_no <= 0:
            continue
        cards.append({
            "episode_no": episode_no,
            "title": str(item.get("title") or "").strip(),
            "summary": str(item.get("summary") or "").strip(),
            "opening_state": str(item.get("opening_state") or "").strip(),
            "ending_state": str(item.get("ending_state") or "").strip(),
            "relationship_delta": item.get("relationship_delta") if isinstance(item.get("relationship_delta"), list) else [],
            "information_delta": item.get("information_delta") if isinstance(item.get("information_delta"), list) else [],
            "power_delta": item.get("power_delta") if isinstance(item.get("power_delta"), list) else [],
            "unresolved_hooks": item.get("unresolved_hooks") if isinstance(item.get("unresolved_hooks"), list) else [],
            "spoiler_guard": item.get("spoiler_guard") if isinstance(item.get("spoiler_guard"), list) else [],
            "tail_excerpt": str(item.get("tail_excerpt") or "").strip(),
            "body_excerpt": str(item.get("body_excerpt") or item.get("actual_progress") or "").strip(),
            "quality_summary": str(item.get("quality_summary") or "").strip(),
        })
    cards.sort(key=lambda row: int(row.get("episode_no") or 0))
    return cards


def normalize_testing_canon_packet(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        return {}
    packet = {
        "premise": str(raw.get("premise") or "").strip(),
        "hard_constraints": raw.get("hard_constraints") if isinstance(raw.get("hard_constraints"), list) else [],
        "relationship_limits": raw.get("relationship_limits") if isinstance(raw.get("relationship_limits"), list) else [],
        "information_schedule": raw.get("information_schedule") if isinstance(raw.get("information_schedule"), list) else [],
        "locked_facts": raw.get("locked_facts") if isinstance(raw.get("locked_facts"), list) else [],
        "timeline_anchors": raw.get("timeline_anchors") if isinstance(raw.get("timeline_anchors"), list) else [],
        "last_updated_episode": int(raw.get("last_updated_episode") or 0) if str(raw.get("last_updated_episode") or "").strip() else 0,
        "notes": str(raw.get("notes") or "").strip(),
    }
    extras = {str(key): value for key, value in raw.items() if key not in packet}
    return {**packet, **extras}


def as_clean_text_list(raw: Any, *, limit: int = 8, item_limit: int = 140) -> list[str]:
    if not isinstance(raw, list):
        raw = [raw] if raw else []
    result: list[str] = []
    for item in raw:
        text = str(item or "").strip()
        if text:
            result.append(text[:item_limit])
        if len(result) >= limit:
            break
    return result


def _is_frontend_inferred_contract(source: str) -> bool:
    return source in {"frontend_outline_simulation", "frontend_outline_inferred", "frontend_outline"}


def _contract_context_text(raw: dict[str, Any]) -> str:
    fields = [
        raw.get("title"),
        raw.get("summary"),
        raw.get("episode_summary"),
        raw.get("start_state"),
        raw.get("opening_state"),
        raw.get("incoming_hook"),
        raw.get("previous_hook"),
        raw.get("ending_state"),
        raw.get("outgoing_hook"),
        raw.get("next_hook"),
        raw.get("ending_hook"),
        raw.get("hook"),
        raw.get("public_pressure"),
        raw.get("real_loss"),
        raw.get("evidence_object"),
        raw.get("villain_pressure_action"),
    ]
    text_items: list[str] = []
    for value in fields:
        if value:
            text_items.append(str(value))
    for item in raw.get("must_happen") or []:
        item_text = str(item or "")
        if not item_text.startswith("主场景必须落地："):
            text_items.append(item_text)
    return "\n".join(text_items)


def _filter_unsupported_generic_scene_requirements(raw: dict[str, Any], must_happen: list[str]) -> list[str]:
    source = str(raw.get("source") or "inferred").strip()
    if not _is_frontend_inferred_contract(source):
        return must_happen

    context_text = _contract_context_text(raw)
    filtered: list[str] = []
    for item in must_happen:
        if not item.startswith("主场景必须落地："):
            filtered.append(item)
            continue
        scene = item.split("：", 1)[1].strip()
        if scene in _GENERIC_OUTLINE_SCENES and scene not in context_text:
            continue
        filtered.append(item)
    return filtered


def normalize_testing_episode_contract(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        return {}
    try:
        episode_no = int(raw.get("episode_no") or raw.get("ep") or 0)
    except Exception:
        episode_no = 0
    must_happen = as_clean_text_list(raw.get("must_happen"), limit=10)
    contract = {
        "episode_no": episode_no,
        "title": str(raw.get("title") or "").strip(),
        "start_state": str(raw.get("start_state") or raw.get("opening_state") or "").strip(),
        "incoming_hook": str(raw.get("incoming_hook") or raw.get("previous_hook") or raw.get("open_hook") or "").strip(),
        "must_happen": _filter_unsupported_generic_scene_requirements(raw, must_happen),
        "must_not_happen": as_clean_text_list(raw.get("must_not_happen") or raw.get("must_not"), limit=12),
        "relationship_delta": as_clean_text_list(raw.get("relationship_delta"), limit=8),
        "character_delta": as_clean_text_list(raw.get("character_delta") or raw.get("role_delta"), limit=8),
        "information_delta": as_clean_text_list(raw.get("information_delta"), limit=8),
        "public_pressure": str(raw.get("public_pressure") or raw.get("pressure") or raw.get("public_conflict") or "").strip(),
        "real_loss": str(raw.get("real_loss") or raw.get("consequence") or raw.get("visible_consequence") or "").strip(),
        "evidence_object": str(raw.get("evidence_object") or raw.get("object_hook") or raw.get("prop_hook") or "").strip(),
        "villain_pressure_action": str(raw.get("villain_pressure_action") or raw.get("antagonist_action") or "").strip(),
        "dialogue_style_contract": str(raw.get("dialogue_style_contract") or raw.get("dialogue_contract") or "").strip(),
        "rag_benchmark_pattern": str(raw.get("rag_benchmark_pattern") or raw.get("benchmark_pattern") or "").strip(),
        "evidence_chain_step": str(raw.get("evidence_chain_step") or "").strip(),
        "ending_state": str(raw.get("ending_state") or "").strip(),
        "outgoing_hook": str(raw.get("outgoing_hook") or raw.get("next_hook") or "").strip(),
        "ending_hook": str(raw.get("ending_hook") or raw.get("hook") or "").strip(),
        "source": str(raw.get("source") or "inferred").strip(),
    }
    extras = {str(key): value for key, value in raw.items() if key not in contract}
    return {**contract, **extras}


def normalize_testing_series_simulation_packet(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        return {}
    contracts: list[dict[str, Any]] = []
    for item in raw.get("episode_contracts") or raw.get("contracts") or []:
        contract = normalize_testing_episode_contract(item)
        if int(contract.get("episode_no") or 0) > 0:
            contracts.append(contract)
    contracts.sort(key=lambda row: int(row.get("episode_no") or 0))
    return {
        "source": str(raw.get("source") or "frontend_outline").strip(),
        "simulation_goal": str(raw.get("simulation_goal") or raw.get("goal") or "").strip(),
        "global_must_not": as_clean_text_list(raw.get("global_must_not"), limit=12),
        "locked_series_facts": as_clean_text_list(raw.get("locked_series_facts"), limit=12),
        "episode_contracts": contracts,
    }


def merge_testing_canon_packet(base: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    merged = normalize_testing_canon_packet(base)
    normalized_patch = normalize_testing_canon_packet(patch)
    for key, value in normalized_patch.items():
        if isinstance(value, list):
            current = merged.get(key) if isinstance(merged.get(key), list) else []
            merged[key] = list(dict.fromkeys([*(str(item).strip() for item in current if str(item).strip()), *(str(item).strip() for item in value if str(item).strip())]))
        elif isinstance(value, dict):
            current = merged.get(key) if isinstance(merged.get(key), dict) else {}
            current.update(value)
            merged[key] = current
        elif value:
            merged[key] = value
    return merged
