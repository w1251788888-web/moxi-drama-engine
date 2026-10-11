"""测试页“分段任务焦点 / 角色 mini 卡 / 已确认前文 / 分段护栏”块（从 short_drama_writing.py 抽出）。

4 个纯函数，零 IO/AI/DB：

- build_testing_segment_focus_block：把当前集摘要/冲突/钩子/连续性提醒拼成 prompt 焦点
- build_testing_segment_character_mini_block：给当前段写一个 4 人以内的角色 mini 卡
- build_testing_segment_confirmed_context_block：把 req.current_content 折叠成 head+tail（>10 行省略中间）
- build_testing_segment_guardrail_block：按 hook/explosion/resolution/默认 写分段护栏
"""
from __future__ import annotations

from typing import Any, TYPE_CHECKING

from app.services.short_drama_final_generation_contract import current_testing_final_generation_contract
from app.services.short_drama_workspace_blocks import condense_text

if TYPE_CHECKING:
    from app.schemas.short_drama_writing import TestingScriptRequest


def _current_segment_card(req: "TestingScriptRequest") -> dict[str, Any]:
    packet = req.step_confirmation_packet if isinstance(req.step_confirmation_packet, dict) else {}
    cards = packet.get("segment_cards") if isinstance(packet.get("segment_cards"), dict) else {}
    items = cards.get("items") if isinstance(cards.get("items"), list) else []
    target = str(req.segment_id or "hook").strip()
    aliases = {
        "hook": {"hook", "钩子段", "钩子"},
        "validation": {"validation", "验证段", "验证"},
        "explosion": {"explosion", "爆发段", "爆发"},
        "resolution": {"resolution", "收束段", "结尾段", "正文候选与保存", "收束"},
    }.get(target, {target})

    for item in items:
        if not isinstance(item, dict):
            continue
        keys = {
            str(item.get("key") or "").strip(),
            str(item.get("id") or "").strip(),
            str(item.get("segment_id") or "").strip(),
            str(item.get("step_id") or "").strip(),
            str(item.get("title") or "").strip(),
        }
        if target in keys or any(alias in keys for alias in aliases):
            return item
    return {}


def build_testing_segment_focus_block(req: "TestingScriptRequest") -> str:
    """把当前集摘要/冲突/钩子/连续性提醒拼成 prompt 焦点。"""
    lines = [
        f"- 当前任务：第{int(req.episode_no or 0)}集 {str(req.episode_title or '').strip()}｜{str(req.segment_id or 'hook').strip()} 段",
    ]
    segment_card = _current_segment_card(req)
    card_body = condense_text(str(segment_card.get("body") or ""), limit=1400)
    if card_body:
        title = str(segment_card.get("title") or req.segment_id or "当前段").strip()
        source = str(segment_card.get("source") or "").strip()
        source_label = f"｜来源：{source}" if source else ""
        lines.extend(
            [
                f"- 当前分段任务卡（最高优先级）：{title}{source_label}",
                f"- 只写当前分段卡，不提前写其它分段：{card_body}",
            ]
        )
    for label, value, limit in (
        ("本集摘要", req.episode_summary, 120),
        ("本集冲突", req.episode_conflict, 100),
        ("本集钩子", req.episode_hook, 90),
        ("连续性提醒", req.continuity_notes, 100),
    ):
        text = condense_text(value, limit=limit)
        if text:
            lines.append(f"- {label}：{text}")
    return "\n".join(lines)


def build_testing_segment_character_mini_block(
    characters: list[dict[str, Any]],
    selected_ids: set[str],
) -> str:
    """给当前段写一个 4 人以内的角色 mini 卡。"""
    lines: list[str] = []
    scoped = [
        item for item in (characters or [])
        if isinstance(item, dict) and (not selected_ids or str(item.get("id") or "").strip() in selected_ids)
    ]
    for item in scoped[:4]:
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        role = str(item.get("role") or "").strip()
        info = condense_text(str(item.get("info") or item.get("personality") or ""), limit=70)
        parts = [name]
        if role:
            parts.append(role)
        if info:
            parts.append(info)
        lines.append("- " + "｜".join(parts))
    return "\n".join(lines) if lines else "沿用当前任务已选角色。"


def build_testing_segment_confirmed_context_block(req: "TestingScriptRequest") -> str:
    """把 req.current_content 折叠成 head+tail（>10 行省略中间）。"""
    text = str(req.current_content or "").strip()
    if not text:
        return "暂无已确认前文，本段直接按任务目标起笔。"
    lines = [line.rstrip() for line in text.splitlines() if str(line or "").strip()]
    if len(lines) <= 10:
        return "\n".join(lines)
    head = lines[:4]
    tail = lines[-5:]
    return "\n".join([*head, "……（中间已确认内容省略，但视为已成立，禁止改写）", *tail])


def build_testing_segment_guardrail_block(req: "TestingScriptRequest") -> str:
    """按 hook/explosion/resolution/默认 写分段护栏。"""
    contract = current_testing_final_generation_contract(req, include_rag=False)
    lines = [
        "- 已确认前文优先级最高，只能承接，不能回写。",
        "- 本集剧作契约高于临场发挥，不能把禁止事项写成事实。",
        "- 若推进关系、信息、权力，必须写出触发动作和即时后果。",
    ]
    segment = str(req.segment_id or "scene").strip()
    if segment == "hook":
        pressure = str(contract.get("who_loses_control") or contract.get("public_pressure") or "").strip()
        loss = str(contract.get("audience_visible_payoff") or contract.get("real_loss") or "").strip()
        lines.append(f"- 本段必须让压力可见：{pressure[:120] or '第三方见证、当场反应、物件变化、站位变化或公开阻力至少出现一项。'}")
        lines.append(f"- 本段必须露出主角正在失去什么：{loss[:120] or '关系、身份、证据、资源、名声、主动权或选择权至少动一项。'}")
    elif segment == "explosion":
        loss = str(contract.get("audience_visible_payoff") or contract.get("real_loss") or "").strip()
        action = str(contract.get("villain_pressure_action") or "").strip()
        lines.append(f"- 本段爆点必须落下当场后果：{loss[:130] or '不能只吵赢，必须出现损失、翻盘、站队或权力变化。'}")
        lines.append(f"- 反派压制必须具体：{action[:130] or '用本题材内成立的动作压人，不要只写空泛威胁或口头放狠话。'}")
    elif segment == "resolution":
        prop = str(contract.get("evidence_object") or "").strip()
        hook = str(contract.get("ending_hook") or contract.get("outgoing_hook") or "").strip()
        lines.append(f"- 本段结尾必须用本集真实物件/动作拉钩：{prop[:130] or hook[:130] or '本集已出现的证据、物件、动作、信息提示或人物到场。'}")
        if int(req.episode_no or 0) >= int(req.episode_count or 0):
            lines.append("- 终局段禁止续集钩子，必须把处罚、店铺、就业、街坊信任或价格承诺收实。")
    else:
        dialogue = str(contract.get("dialogue_style_contract") or "").strip()
        if dialogue:
            lines.append(f"- 台词风格：{dialogue[:120]}")
    relationship_lines = [
        str(item or "").strip(" -\n\t")
        for item in str(req.relationship_guardrails or "").splitlines()
        if str(item or "").strip()
    ]
    if relationship_lines:
        lines.extend(f"- 关系护栏：{item[:90]}" for item in relationship_lines[:3])
    return "\n".join(lines)
