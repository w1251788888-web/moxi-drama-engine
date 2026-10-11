"""短剧测试页 状态卡 / 关系护栏 块构造（从 short_drama_writing.py 抽出）。

- strength_tier_rule: 关系强度跨阈值时追加 guardrail 句
- build_relationship_guardrail_block: 关系护栏 prompt 块
- normalize_testing_state_cards: 状态卡 raw → 标准 dict
- card_availability_status: 卡片在当前集是否可用 / locked / pending
- build_testing_state_cards_block: 状态卡 prompt 块（本集可用 + 禁动用清单）

纯字符串构造 + dict 操作，无 IO。
"""
from __future__ import annotations

from typing import Any


def strength_tier_rule(
    source_name: str, target_name: str, rel_type: str, strength: Any
) -> str:
    """关系 strength 跨阈值（60/75/90）时追加增量 guardrail 句。"""
    try:
        s = int(strength) if strength is not None else 0
    except Exception:
        s = 0
    if s < 60:
        return ""
    if s >= 90:
        return (
            f"- 强度{s}（≥90·临界）：{source_name} 与 {target_name} 的【{rel_type}】已处于关系临界点，"
            "本集任何推进都必须落在'重大代价/不可逆动作/正面摊牌'级别（病倒/送别/咽下去/递手未接），"
            "禁止再用聊天、回忆、独白这种轻量推进。"
        )
    if s >= 75:
        return (
            f"- 强度{s}（≥75·高压）：{source_name} 与 {target_name} 的【{rel_type}】已积压过深，"
            "本集若要推进，必须落到具体物件/动作（递茶、塞钱、关灯、收拾药袋）上，半步到一步，禁止跳级。"
        )
    return (
        f"- 强度{s}（≥60·拉紧）：{source_name} 与 {target_name} 的【{rel_type}】处于持续累积阶段，"
        "本集允许试探性接触（嘴硬/绕话题/没说出口的关心），禁止突然撕破或冷处理。"
    )



def build_relationship_guardrail_block(characters: list[dict[str, Any]], selected_ids: set[str], continuity_notes: str) -> str:
    if not characters:
        return "暂无结构化角色图谱，禁止自造新的主线关系。"

    by_id = {str(char.get("id") or ""): char for char in characters if isinstance(char, dict)}
    selected_list = [cid for cid in selected_ids if cid in by_id]
    guardrails: list[str] = []
    seen_pairs: set[tuple[str, str]] = set()

    protagonist = next((char for char in characters if str(char.get("role") or "") == "protagonist"), None)
    antagonist = next((char for char in characters if str(char.get("role") or "") == "antagonist"), None)

    if protagonist:
        guardrails.append(f"- 主线锚点：主角【{str(protagonist.get('name') or '').strip() or '未命名'}】必须维持人物目标和情绪逻辑，不得突然失智、失声或放弃主线。")
    if antagonist:
        guardrails.append(f"- 对抗锚点：反派【{str(antagonist.get('name') or '').strip() or '未命名'}】若出场，必须带来阻碍、压迫、诱导或代价，不能沦为背景板。")

    for source_id in selected_list:
        source = by_id.get(source_id) or {}
        source_name = str(source.get("name") or "").strip()
        relations = source.get("relationships") or []
        if not isinstance(relations, list):
            continue
        for rel in relations:
            if not isinstance(rel, dict):
                continue
            target_id = str(rel.get("targetId") or rel.get("target_id") or "").strip()
            if target_id not in selected_ids or target_id not in by_id:
                continue
            target = by_id[target_id]
            target_name = str(target.get("name") or "").strip()
            if not source_name or not target_name:
                continue
            pair_key = tuple(sorted([source_name, target_name]))
            if pair_key in seen_pairs:
                continue
            seen_pairs.add(pair_key)
            rel_type = str(rel.get("type") or "").strip() or "关系待定"
            rel_desc = str(rel.get("description") or "").strip()
            rel_strength = rel.get("strength")
            detail_parts = [rel_type]
            if isinstance(rel_strength, (int, float)):
                detail_parts.append(f"强度{int(rel_strength)}")
            if rel_desc:
                detail_parts.append(rel_desc)
            detail = "，".join(detail_parts)
            guardrails.append(
                f"- 关系护栏：{source_name} 与 {target_name} 当前定义为【{detail}】。未经明确触发动作、对白冲突和当场后果，不得突然改写这条关系。"
            )
            tier_rule = strength_tier_rule(source_name, target_name, rel_type, rel_strength)
            if tier_rule:
                guardrails.append(tier_rule)

    if not seen_pairs and len(selected_list) >= 2:
        names = [str(by_id[cid].get("name") or "").strip() for cid in selected_list if str(by_id[cid].get("name") or "").strip()]
        if names:
            guardrails.append(f"- 当前出场角色为：{'、'.join(names)}。角色库未定义他们的直接关系时，写法必须更克制，禁止生硬跳成恋爱/生死/背叛等重大关系变化。")

    if continuity_notes.strip():
        guardrails.append(f"- 连贯性约束：{continuity_notes.strip()}")

    guardrails.append("- 若本场要推进关系，只能推进半步到一步，并且必须把变化落到可拍动作、台词冲突和即时后果。")
    return "\n".join(guardrails)



def normalize_testing_state_cards(raw: Any) -> dict[str, list[dict[str, Any]]]:
    base = {
        "relationship_cards": [],
        "info_cards": [],
        "power_cards": [],
        "promise_cards": [],
        "locked_fact_cards": [],
    }
    if not isinstance(raw, dict):
        return base
    normalized: dict[str, list[dict[str, Any]]] = {}
    for key, default in base.items():
        value = raw.get(key)
        normalized[key] = value if isinstance(value, list) else list(default)
    return normalized



def card_availability_status(card: dict[str, Any], current_episode: int) -> str:
    """返回 'available' / 'locked' / 'pending'(指未到揭露集)。"""
    raw = str(card.get("availability") or "").strip().lower()
    if raw == "locked":
        return "locked"
    try:
        surface_at = int(card.get("surface_at_episode") or 0)
    except Exception:
        surface_at = 0
    if surface_at and current_episode and current_episode < surface_at:
        return "pending"
    if raw in {"surfaced", "available", ""}:
        return "available"
    return "available"



def build_testing_state_cards_block(
    state_cards: dict[str, Any],
    characters: list[dict[str, Any]],
    selected_ids: set[str],
    current_episode: int = 0,
) -> str:
    normalized = normalize_testing_state_cards(state_cards)
    selected_ids = {str(item) for item in selected_ids if str(item).strip()}
    if not normalized or not any(normalized.values()):
        return "暂无显式状态卡；生成时必须严格遵守角色护栏、关系护栏和未完成承诺，不得自行改写既有事实。"

    by_id = {str(char.get("id") or ""): str(char.get("name") or "").strip() for char in characters if isinstance(char, dict)}
    known_character_ids = {cid for cid in by_id if cid}

    def _card_relevant(card: dict[str, Any]) -> bool:
        related_ids = {
            str(item).strip()
            for item in (
                list(card.get("character_ids") or [])
                + list(card.get("related_character_ids") or [])
                + [card.get("source_id"), card.get("target_id"), card.get("holder_id"), card.get("dominant_id"), card.get("subordinate_id")]
            )
            if str(item or "").strip()
        }
        if related_ids and known_character_ids and not (related_ids & known_character_ids):
            return False
        return not selected_ids or not related_ids or bool(related_ids & selected_ids)

    sections: list[str] = []
    title_map = {
        "relationship_cards": "关系状态卡",
        "info_cards": "信息状态卡",
        "power_cards": "权力状态卡",
        "promise_cards": "未完成承诺卡",
        "locked_fact_cards": "禁改事实卡",
    }

    locked_lines: list[str] = []
    for key, title in title_map.items():
        relevant = [card for card in normalized.get(key, []) if isinstance(card, dict) and _card_relevant(card)]
        if not relevant:
            continue
        sections.append(f"【{title}】")
        for card in relevant[:8]:
            label = str(card.get("title") or card.get("label") or "").strip()
            summary = str(card.get("summary") or card.get("description") or "").strip()
            state = str(card.get("state") or card.get("status") or "").strip()
            related_ids = [
                str(item).strip()
                for item in (
                    list(card.get("character_ids") or [])
                    + list(card.get("related_character_ids") or [])
                    + [card.get("source_id"), card.get("target_id"), card.get("holder_id"), card.get("dominant_id"), card.get("subordinate_id")]
                )
                if str(item or "").strip()
            ]
            related_names = [by_id.get(item, item) for item in related_ids if by_id.get(item, item)]
            availability = card_availability_status(card, current_episode)
            parts = []
            if label:
                parts.append(label)
            if state:
                parts.append(f"状态：{state}")
            if related_names:
                parts.append("关联角色：" + "、".join(dict.fromkeys(related_names)))
            if availability == "locked":
                parts.append("【本集禁止动用】")
                locked_lines.append(f"- {label or title}（locked）")
            elif availability == "pending":
                target_ep = card.get("surface_at_episode")
                parts.append(f"【需到第{target_ep}集才能揭露，本集禁止提前消耗】")
                locked_lines.append(f"- {label or title}（surface_at_episode={target_ep}）")
            if summary:
                parts.append(summary)
            sections.append("- " + "；".join(parts))

    if locked_lines:
        sections.append("【本集禁动用清单】")
        sections.extend(locked_lines)
        sections.append("禁止把上述卡片承载的事件、台词、物件、信息提前到本集；写到边缘必须绕开。")

    return "\n".join(sections) if sections else "暂无显式状态卡；生成时必须严格遵守角色护栏、关系护栏和未完成承诺，不得自行改写既有事实。"

