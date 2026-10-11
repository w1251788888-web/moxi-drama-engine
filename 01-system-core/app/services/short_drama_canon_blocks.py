"""测试页"canon 包推断 + canon/记忆卡 prompt 块"工具（从 short_drama_writing.py 抽出）。

3 个纯函数，零 IO/AI/DB：

- build_inferred_canon_packet：从 req 推断 canon 包（hard_constraints / relationship_limits /
  information_schedule / locked_facts / timeline_anchors），并合并已有 req.canon_packet
- format_testing_canon_block：把 canon 包格式化成 prompt 用的"- 不可变硬约束：..."块
- build_testing_episode_memory_block：把前序集记忆卡按"第N集｜title｜结果｜关系变化｜未收钩子"格式化

被多个 endpoint 共用（generate / validate / deep-audit / auto-fix / structured updates）。
"""
from __future__ import annotations

from typing import Any, TYPE_CHECKING

from app.services.short_drama_state_cards import normalize_testing_state_cards
from app.services.short_drama_testing_normalizers import (
    merge_testing_canon_packet,
    normalize_testing_episode_memory_cards,
)

if TYPE_CHECKING:
    from app.schemas.short_drama_writing import TestingScriptRequest


def build_inferred_canon_packet(req: "TestingScriptRequest") -> dict[str, Any]:
    """从 req 推断 canon 包并合并已有 req.canon_packet。"""
    hard_constraints: list[str] = []
    relationship_limits: list[str] = []
    information_schedule: list[str] = []
    locked_facts: list[str] = []
    timeline_anchors: list[str] = []

    for item in str(req.relationship_guardrails or "").splitlines():
        text = str(item or "").strip(" -\n\t")
        if text:
            relationship_limits.append(text)

    if str(req.conflict or "").strip():
        hard_constraints.append(f"核心冲突：{str(req.conflict).strip()}")
    if str(req.episode_conflict or "").strip():
        timeline_anchors.append(f"第{int(req.episode_no or 0)}集冲突：{str(req.episode_conflict).strip()}")
    if str(req.episode_hook or "").strip():
        timeline_anchors.append(f"第{int(req.episode_no or 0)}集钩子：{str(req.episode_hook).strip()}")

    state_cards_norm = normalize_testing_state_cards(req.state_cards or {})
    for card in (state_cards_norm.get("locked_fact_cards") or [])[:8]:
        title = str(card.get("title") or "").strip()
        summary = str(card.get("summary") or "").strip()
        joined = "：".join(part for part in [title, summary] if part)
        if joined:
            locked_facts.append(joined[:120])
    for card in (state_cards_norm.get("promise_cards") or [])[:6]:
        title = str(card.get("title") or "").strip()
        summary = str(card.get("summary") or "").strip()
        joined = "：".join(part for part in [title, summary] if part)
        if joined:
            hard_constraints.append(f"承诺线：{joined[:120]}")

    for item in (req.future_episode_briefs or [])[:5]:
        if not isinstance(item, dict):
            continue
        ep = item.get("episode_no") or item.get("ep") or ""
        summary = str(item.get("summary") or "").strip()
        if summary:
            information_schedule.append(f"第{ep}集后续预留：{summary[:120]}")

    return merge_testing_canon_packet({
        "premise": str(req.brief or "").strip(),
        "hard_constraints": hard_constraints[:12],
        "relationship_limits": relationship_limits[:12],
        "information_schedule": information_schedule[:10],
        "locked_facts": locked_facts[:10],
        "timeline_anchors": timeline_anchors[:10],
        "last_updated_episode": int(req.episode_no or 0),
        "notes": str(req.episode_novel_anchor or "").strip(),
    }, req.canon_packet or {})


def format_testing_canon_block(req: "TestingScriptRequest") -> str:
    """把 canon 包格式化成 prompt 用的"- 不可变硬约束：..."块。"""
    canon = build_inferred_canon_packet(req)
    lines: list[str] = []
    if canon.get("premise"):
        lines.append(f"- 故事前提：{canon['premise']}")
    for label, key, limit in (
        ("不可变硬约束", "hard_constraints", 5),
        ("关系边界", "relationship_limits", 5),
        ("信息揭晓顺序", "information_schedule", 4),
        ("锁定事实", "locked_facts", 4),
        ("时间线锚点", "timeline_anchors", 4),
    ):
        values = canon.get(key) if isinstance(canon.get(key), list) else []
        if values:
            lines.append(f"- {label}：" + "；".join(str(item)[:100] for item in values[:limit] if str(item).strip()))
    if canon.get("notes"):
        lines.append(f"- 备注：{str(canon['notes'])[:140]}")
    return "\n".join(lines) if lines else "暂无 canon 包。"


def build_testing_episode_memory_block(req: "TestingScriptRequest", *, limit: int = 3) -> str:
    """把前序集记忆卡按"第N集｜title｜结果｜关系变化｜未收钩子"格式化成 prompt 块。"""
    cards = normalize_testing_episode_memory_cards(req.episode_memory_cards or req.previous_episode_briefs or [])
    if not cards:
        return "暂无系列记忆卡。"
    lines: list[str] = []
    for item in cards[-limit:]:
        line_parts = [f"第{item['episode_no']}集"]
        if item.get("title"):
            line_parts.append(str(item.get("title")))
        if item.get("summary"):
            line_parts.append(f"结果：{str(item.get('summary'))[:120]}")
        if item.get("ending_state"):
            line_parts.append(f"结尾局面：{str(item.get('ending_state'))[:80]}")
        relation_delta = item.get("relationship_delta") if isinstance(item.get("relationship_delta"), list) else []
        if relation_delta:
            line_parts.append("关系变化：" + "；".join(str(v)[:60] for v in relation_delta[:2] if str(v).strip()))
        unresolved_hooks = item.get("unresolved_hooks") if isinstance(item.get("unresolved_hooks"), list) else []
        if unresolved_hooks:
            line_parts.append("未收钩子：" + "；".join(str(v)[:60] for v in unresolved_hooks[:2] if str(v).strip()))
        if item.get("body_excerpt"):
            line_parts.append(f"正文落点：{str(item.get('body_excerpt'))[:120]}")
        lines.append("｜".join(line_parts))
    return "\n".join(lines) if lines else "暂无系列记忆卡。"
