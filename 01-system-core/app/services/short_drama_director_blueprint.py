"""Director blueprint helpers for the short-drama generation chain.

The blueprint is a production candidate for separating three jobs:
logic planning, creative drafting, and final review. These helpers are pure
functions so local research can test the contract without calling a model.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from app.schemas.short_drama_writing import TestingScriptRequest


def stable_director_blueprint_hash(data: Any) -> str:
    text = json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def director_blueprint_hashes(blueprint: dict[str, Any]) -> dict[str, str]:
    if not isinstance(blueprint, dict) or not blueprint:
        return {
            "director_blueprint_hash": "",
            "writer_brief_hash": "",
            "review_contract_hash": "",
            "blueprint_version": "",
        }
    return {
        "director_blueprint_hash": stable_director_blueprint_hash(blueprint),
        "writer_brief_hash": stable_director_blueprint_hash(blueprint.get("writer_brief") or ""),
        "review_contract_hash": stable_director_blueprint_hash(blueprint.get("review_contract") or {}),
        "blueprint_version": str(blueprint.get("blueprint_version") or "").strip(),
    }


def director_blueprint_trace_extra(req: "TestingScriptRequest") -> dict[str, str]:
    blueprint = getattr(req, "director_blueprint", {}) or {}
    if not isinstance(blueprint, dict) or not blueprint:
        return {}
    return director_blueprint_hashes(blueprint)


def episode_contract_shadow_from_director_blueprint(blueprint: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(blueprint, dict) or not blueprint:
        return {}
    return {
        "episode_objective": blueprint.get("episode_objective", ""),
        "segment_plan": blueprint.get("segment_plan", {}),
        "role_execution_contract": blueprint.get("role_execution_contract", []),
        "confrontation_contract": blueprint.get("confrontation_contract", {}),
        "evidence_chain": blueprint.get("evidence_chain", {}),
        "continuity_contract": blueprint.get("continuity_contract", {}),
        "compatibility_note": "director_blueprint shadow for old episode_contract readers",
    }


def _role_contract_lines(items: Any) -> list[str]:
    if not isinstance(items, list):
        return []
    lines: list[str] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or item.get("role") or "").strip()
        function = str(item.get("minimum_function") or item.get("must_do") or "").strip()
        if name or function:
            lines.append(f"- {name}：{function}".strip("："))
    return lines


def format_director_blueprint_block(req: "TestingScriptRequest", *, for_writer: bool = True) -> str:
    blueprint = getattr(req, "director_blueprint", {}) or {}
    if not isinstance(blueprint, dict) or not blueprint:
        return ""

    hashes = director_blueprint_hashes(blueprint)
    if for_writer:
        evidence = blueprint.get("evidence_chain") if isinstance(blueprint.get("evidence_chain"), dict) else {}
        word_budget = blueprint.get("word_budget_contract") if isinstance(blueprint.get("word_budget_contract"), dict) else {}
        emotion_intensity = (
            blueprint.get("episode_emotion_intensity_contract")
            if isinstance(blueprint.get("episode_emotion_intensity_contract"), dict)
            else {}
        )
        emotion_lines = []
        if emotion_intensity:
            emotion_lines = [
                "## 情绪强度执行",
                json.dumps(emotion_intensity, ensure_ascii=False, sort_keys=True),
            ]
        lines = [
            "# 导演工程蓝图：写手执行卡",
            f"director_blueprint_hash={hashes['director_blueprint_hash']}",
            f"writer_brief_hash={hashes['writer_brief_hash']}",
            str(blueprint.get("writer_brief") or "").strip(),
            "## 本集任务目标",
            str(blueprint.get("episode_objective") or "").strip(),
            "## 分段施工图",
            json.dumps(blueprint.get("segment_plan") or {}, ensure_ascii=False, sort_keys=True),
            "## 角色最低责任",
            *(_role_contract_lines(blueprint.get("role_execution_contract")) or ["- 未配置"]),
            "## 证据链执行",
            f"- 出现：{evidence.get('evidence_appears', '')}",
            f"- 转移：{evidence.get('evidence_transfers', '')}",
            f"- 核验：{evidence.get('evidence_verified', '')}",
            f"- 留痕：{evidence.get('evidence_recorded', '')}",
            f"- 可见后果：{evidence.get('visible_consequence', '')}",
            *emotion_lines,
            "## 字数预算",
            json.dumps(word_budget, ensure_ascii=False, sort_keys=True),
            "只输出正文，不输出验收过程或解释。",
        ]
        return "\n".join(line for line in lines if str(line).strip())

    review = blueprint.get("review_contract") if isinstance(blueprint.get("review_contract"), dict) else {}
    lines = [
        "# 导演工程蓝图：评审合同",
        f"director_blueprint_hash={hashes['director_blueprint_hash']}",
        f"review_contract_hash={hashes['review_contract_hash']}",
        "review_contract:",
        json.dumps(review, ensure_ascii=False, sort_keys=True),
        "判断标准：只检查正文是否执行同一张导演蓝图；失败时返回失败字段和局部修复建议。",
    ]
    return "\n".join(line for line in lines if str(line).strip())
