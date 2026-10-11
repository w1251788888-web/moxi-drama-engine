"""测试页“RAG 上下文卡片编译/选段/格式化”（从 short_drama_writing.py 抽出）。

7 个纯函数，零 IO/AI/DB：

- make_testing_rag_card：构造一张统一结构的 RAG 卡片
- infer_testing_top_script_pattern_cards：基于 brief/contract 推断头部短剧模式卡
- compile_testing_rag_context_cards：把当前请求所有重上下文编译成一组带权威等级的 RAG 卡
- select_testing_rag_cards_for_segment：按 segment_id 选 8 张最相关的卡
- format_testing_rag_context_pack：把选好的卡格式化成 prompt 块（按 budget 截断）
- build_testing_rule_context：拼出规则画像/世界规则/金手指/冲突计划/小说锚点
- build_testing_rag_context：拼出完整 RAG 上下文（compact / 全量 两种模式）
"""
from __future__ import annotations

from typing import Any, TYPE_CHECKING

from app.services.short_drama_canon_blocks import build_inferred_canon_packet
from app.services.short_drama_state_cards import (
    build_relationship_guardrail_block,
    build_testing_state_cards_block,
)
from app.services.short_drama_testing_contexts import (
    build_testing_issue_feedback_context,
)
from app.services.short_drama_testing_normalizers import (
    normalize_testing_episode_memory_cards,
)
from app.services.short_drama_workspace_blocks import condense_text

if TYPE_CHECKING:
    from app.schemas.short_drama_writing import TestingScriptRequest


def make_testing_rag_card(
    context_type: str,
    title: str,
    content: str,
    *,
    authority: int,
    episode_no: int = 0,
    tags: list[str] | None = None,
    source: str = "runtime",
) -> dict[str, Any]:
    """构造一张统一结构的 RAG 卡片。"""
    text = condense_text(content, limit=360)
    if not text:
        return {}
    return {
        "context_type": context_type,
        "title": condense_text(title, limit=80),
        "content": text,
        "authority_level": int(authority),
        "episode_no": int(episode_no or 0),
        "tags": tags or [],
        "source": source,
    }


def infer_testing_top_script_pattern_cards(req: "TestingScriptRequest") -> list[dict[str, Any]]:
    """基于 brief/contract 推断头部短剧模式卡。"""
    ep_no = int(req.episode_no or 0)
    from app.services.short_drama_final_generation_contract import current_testing_final_generation_contract

    contract = current_testing_final_generation_contract(req, include_rag=False)
    combined = "\n".join([
        str(req.brief or ""),
        str(req.conflict or ""),
        str(req.episode_summary or ""),
        str(req.episode_conflict or ""),
        str(req.episode_hook or ""),
        str(contract.get("episode_goal") or ""),
        str(contract.get("required_main_scene") or ""),
        str(contract.get("audience_visible_payoff") or ""),
        str(contract.get("rag_benchmark_pattern") or ""),
    ])
    cards: list[dict[str, Any]] = []

    def push(title: str, content: str, tags: list[str], authority: int = 87) -> None:
        card = make_testing_rag_card(
            "top_script_pattern",
            title,
            content,
            authority=authority,
            episode_no=ep_no,
            tags=tags,
            source="top_script_benchmark_compiler",
        )
        if card:
            cards.append(card)

    push(
        "开场压迫卡",
        "头部短剧开场不先解释背景，先让观众看见主角被谁压、失去什么、谁在见证。前5行优先出现本集真实场景里的动作、站位、物件、台词或公开反应。",
        ["hook", "public_pressure", "opening"],
        authority=90,
    )
    push(
        "当场后果卡",
        "爆点必须落成后果：关系破裂、身份变化、证据外露、权力位置改变、第三方站队、现实损失或新阻力被看见。不能只停在吵赢或放狠话。",
        ["explosion", "consequence", "visible_loss"],
        authority=92,
    )
    push(
        "短台词卡",
        "现实短剧台词要短、硬、可演。单句尽量25字以内；证据说明拆成短对白加动作，避免长段解释、广播式控诉和小说旁白。",
        ["dialogue", "style", "realistic"],
        authority=84,
    )
    push(
        "物件钩子卡",
        "结尾钩子必须绑定本集已经出现或大纲明确给出的真实物件、动作、证据、信息提示或人物到场。禁止凭空套用别的赛道物件，禁止'事情才刚开始'式空尾。",
        ["resolution", "object_hook", "ending"],
        authority=91,
    )
    push(
        "反派具体动作卡",
        "反派或阻力方不能只放狠话，必须给出本题材内成立的具体动作：夺走资源、制造误会、截断证据、公开羞辱、逼迫选择、改写规则或推来新威胁。",
        ["villain", "specific_pressure", "conflict"],
        authority=88,
    )
    push(
        "可拍动作卡",
        "情绪优先落在可拍动作、场面站位、物件变化和人物即时反应上；OS最多点到为止，首尾不用OS，不用抽象总结替代画面。",
        ["realistic", "os_control", "action"],
        authority=86,
    )
    if ep_no >= max(1, int(req.episode_count or 0) - 1) or any(token in combined for token in ("大结局", "终局", "彻底", "击垮", "标杆", "就业")):
        push(
            "终局闭环卡",
            "终局必须收口：核心反派或核心阻力受到可见结果，主角的目标、关系、身份或承诺落地。不要在最后留下神秘文件、神秘电话或'还有后招'式续集钩子。",
            ["finale", "closure", "ending"],
            authority=94,
        )
    if any(token in combined for token in ("餐饮", "门店", "连锁", "配方", "摆摊", "复购")):
        push(
            "市井商业赛道卡",
            "本赛道头部质感来自市井商业对抗：老面口感、街坊复购、短视频订单、检测报告、劣质原料曝光、平价早餐店和下岗工人就业，要把爽点写成现实结果。",
            ["breakfast", "specific_track", "rag_benchmark"],
            authority=93,
        )
    return cards


def compile_testing_rag_context_cards(
    req: "TestingScriptRequest",
    source_contract: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Compile heavy runtime context into typed cards before prompt assembly.

    This is the local compiler layer. Dify retrieval can still add external
    chunks, but the core project truth is first normalized into cards with
    authority levels so generation does not need the full 30-episode payload.
    """
    cards: list[dict[str, Any]] = []

    def push(card: dict[str, Any]) -> None:
        if card and card.get("content"):
            cards.append(card)

    ep_no = int(req.episode_no or 0)
    if isinstance(source_contract, dict) and source_contract:
        contract = source_contract
    else:
        from app.services.short_drama_final_generation_contract import current_testing_final_generation_contract

        contract = current_testing_final_generation_contract(req, include_rag=False)
    from app.services.short_drama_final_generation_contract import format_final_generation_contract_block

    push(make_testing_rag_card(
        "episode_contract",
        f"第{ep_no}集最终生成合同",
        "\n".join([
            format_final_generation_contract_block(req, for_writer=False),
            f"- 合同哈希：{contract.get('final_generation_contract_hash') or ''}",
            f"- 主场景：{contract.get('required_main_scene') or '未提供'}",
            f"- 当场收益：{contract.get('audience_visible_payoff') or '未提供'}",
            f"- 人物边界：{contract.get('character_boundaries') or '未提供'}",
            f"- 结尾钩子：{contract.get('ending_hook') or '未提供'}",
        ]),
        authority=98,
        episode_no=ep_no,
        tags=["contract", "final_generation_contract", "user_confirmed"],
        source="final_generation_contract",
    ))

    canon = build_inferred_canon_packet(req)
    for key, label in (
        ("hard_constraints", "硬设定"),
        ("locked_facts", "锁定事实"),
        ("relationship_limits", "关系边界"),
        ("information_schedule", "信息揭晓顺序"),
        ("timeline_anchors", "时间线锚点"),
    ):
        values = canon.get(key) if isinstance(canon.get(key), list) else []
        if values:
            push(make_testing_rag_card(
                f"canon_{key}",
                label,
                "；".join(str(item) for item in values[:8]),
                authority=95,
                episode_no=ep_no,
                tags=["canon", key],
                source="canon_packet",
            ))

    for item in normalize_testing_episode_memory_cards(req.episode_memory_cards or req.previous_episode_briefs or [])[-4:]:
        item_ep = int(item.get("episode_no") or 0)
        text = "；".join(
            part for part in [
                str(item.get("summary") or "").strip(),
                str(item.get("ending_state") or "").strip(),
                str(item.get("body_excerpt") or "").strip(),
            ] if part
        )
        push(make_testing_rag_card(
            "episode_memory",
            f"第{item_ep}集已落地结果",
            text,
            authority=100,
            episode_no=item_ep,
            tags=["memory", "landed"],
            source="episode_memory",
        ))

    for item in (req.future_episode_briefs or [])[:4]:
        if not isinstance(item, dict):
            continue
        item_ep = int(item.get("episode_no") or item.get("ep") or 0)
        text = "；".join(
            str(item.get(key) or "").strip()
            for key in ("summary", "conflict", "hook")
            if str(item.get(key) or "").strip()
        )
        push(make_testing_rag_card(
            "future_spoiler_boundary",
            f"第{item_ep}集后续边界",
            text,
            authority=96,
            episode_no=item_ep,
            tags=["future", "spoiler_guard"],
            source="outline",
        ))

    relationship_text = str(req.relationship_guardrails or "").strip() or build_relationship_guardrail_block(
        req.characters or [],
        {str(item) for item in (req.selected_character_ids or [])},
        req.continuity_notes,
    )
    push(make_testing_rag_card(
        "relationship_state",
        "当前角色关系护栏",
        relationship_text,
        authority=92,
        episode_no=ep_no,
        tags=["relationship", "graph"],
        source="relationship_graph",
    ))

    state_block = build_testing_state_cards_block(
        req.state_cards or {},
        req.characters or [],
        {str(item) for item in (req.selected_character_ids or [])},
        current_episode=ep_no,
    )
    if state_block and "暂无显式状态卡" not in state_block:
        push(make_testing_rag_card(
            "state_cards",
            "状态卡",
            state_block,
            authority=93,
            episode_no=ep_no,
            tags=["state_cards"],
            source="state_cards",
        ))

    issue_context = build_testing_issue_feedback_context(req)
    if issue_context and "暂无历史问题" not in issue_context:
        push(make_testing_rag_card(
            "known_issue_pattern",
            "历史易错问题",
            issue_context,
            authority=80,
            episode_no=ep_no,
            tags=["issues", "regression"],
            source="issue_feedback",
        ))

    evidence_text = str(
        contract.get("evidence_chain_step")
        or contract.get("audience_visible_payoff")
        or ""
    ).strip()
    if evidence_text:
        push(make_testing_rag_card(
            "evidence_chain",
            "本集证据/规则链",
            evidence_text,
            authority=91,
            episode_no=ep_no,
            tags=["evidence", "rules"],
            source="episode_contract",
        ))

    for card in infer_testing_top_script_pattern_cards(req):
        push(card)

    for label, value, tags, context_type, authority in (
        ("头部剧本外部样本", req.rag_script_references, ["top_script", "external_sample"], "top_script_external", 82),
        ("质检对标外部样本", req.rag_review_references, ["top_script", "review_benchmark"], "top_script_external", 82),
        ("桥段/素材外部参考", req.rag_asset_references, ["asset", "beat_reference"], "external_asset_reference", 79),
        ("原著/章节外部参考", req.rag_novel_chapters, ["novel", "adaptation_anchor"], "external_novel_anchor", 78),
    ):
        text = str(value or "").strip()
        if text:
            push(make_testing_rag_card(
                context_type,
                label,
                text[:1400],
                authority=authority,
                episode_no=ep_no,
                tags=tags,
                source="external_rag",
            ))

    external_pack = req.rag_context_pack if isinstance(req.rag_context_pack, dict) else {}
    for item in external_pack.get("cards") or []:
        if isinstance(item, dict):
            push(make_testing_rag_card(
                str(item.get("context_type") or "external_rag"),
                str(item.get("title") or "外部RAG卡片"),
                str(item.get("content") or ""),
                authority=int(item.get("authority_level") or 60),
                episode_no=int(item.get("episode_no") or ep_no),
                tags=[str(tag) for tag in (item.get("tags") or []) if str(tag).strip()],
                source=str(item.get("source") or "external_rag"),
            ))

    # De-duplicate by type/title/content prefix while preserving authority order.
    cards.sort(key=lambda row: int(row.get("authority_level") or 0), reverse=True)
    seen: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for card in cards:
        key = f"{card.get('context_type')}|{card.get('title')}|{str(card.get('content') or '')[:80]}"
        if key in seen:
            continue
        seen.add(key)
        deduped.append(card)
    return deduped[:24]


def select_testing_rag_cards_for_segment(req: "TestingScriptRequest", cards: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """按 segment_id 选 8 张最相关的卡。"""
    segment = str(req.segment_id or "scene").strip()
    wanted_by_segment = {
        "hook": {"episode_contract", "episode_memory", "canon_hard_constraints", "relationship_state", "known_issue_pattern", "top_script_pattern", "top_script_external", "external_asset_reference", "external_novel_anchor"},
        "validation": {"episode_contract", "relationship_state", "state_cards", "canon_relationship_limits", "canon_locked_facts", "top_script_pattern", "top_script_external", "external_asset_reference", "external_novel_anchor"},
        "explosion": {"episode_contract", "evidence_chain", "canon_hard_constraints", "state_cards", "known_issue_pattern", "top_script_pattern", "top_script_external", "external_asset_reference", "external_novel_anchor"},
        "resolution": {"episode_contract", "future_spoiler_boundary", "canon_information_schedule", "episode_memory", "relationship_state", "top_script_pattern", "top_script_external", "external_asset_reference", "external_novel_anchor"},
        "scene": {"episode_contract", "episode_memory", "future_spoiler_boundary", "relationship_state", "state_cards", "evidence_chain", "known_issue_pattern", "top_script_pattern", "top_script_external", "external_asset_reference", "external_novel_anchor"},
    }
    wanted = wanted_by_segment.get(segment) or wanted_by_segment["scene"]
    selected = [card for card in cards if str(card.get("context_type") or "") in wanted]
    if len(selected) < 5:
        selected.extend(card for card in cards if card not in selected)
    priority_by_segment = {
        "hook": {"episode_contract": 0, "episode_memory": 1, "top_script_external": 2, "external_asset_reference": 3, "external_novel_anchor": 4, "top_script_pattern": 5, "relationship_state": 6},
        "validation": {"episode_contract": 0, "relationship_state": 1, "state_cards": 2, "top_script_external": 3, "external_novel_anchor": 4, "external_asset_reference": 5, "top_script_pattern": 6},
        "explosion": {"episode_contract": 0, "evidence_chain": 1, "top_script_external": 2, "external_asset_reference": 3, "external_novel_anchor": 4, "top_script_pattern": 5, "state_cards": 6},
        "resolution": {"episode_contract": 0, "future_spoiler_boundary": 1, "episode_memory": 2, "top_script_external": 3, "external_novel_anchor": 4, "external_asset_reference": 5, "relationship_state": 6, "top_script_pattern": 7},
        "scene": {"episode_contract": 0, "episode_memory": 1, "future_spoiler_boundary": 2, "top_script_external": 3, "external_asset_reference": 4, "external_novel_anchor": 5, "top_script_pattern": 6},
    }
    priorities = priority_by_segment.get(segment) or priority_by_segment["scene"]
    selected.sort(key=lambda row: (
        priorities.get(str(row.get("context_type") or ""), 20),
        -int(row.get("authority_level") or 0),
    ))
    return selected[:8]


def format_testing_rag_context_pack(req: "TestingScriptRequest", *, budget: int = 2600) -> str:
    """把选好的卡格式化成 prompt 块（按 budget 截断）。"""
    cards = select_testing_rag_cards_for_segment(req, compile_testing_rag_context_cards(req))
    if not cards:
        return "暂无 RAG 上下文卡片。"
    lines = [
        "RAG上下文调度：以下为按当前段落定向召回/编译的高权重卡片，不是素材散文；权威等级越高越不能违背。"
    ]
    used = len(lines[0])
    for card in cards:
        item = (
            f"- [{card.get('authority_level')}] {card.get('context_type')}｜{card.get('title')}："
            f"{str(card.get('content') or '').strip()}"
        )
        if used + len(item) > budget:
            break
        lines.append(item)
        used += len(item)
    return "\n".join(lines)


def build_testing_rule_context(req: "TestingScriptRequest") -> str:
    """拼出规则画像/世界规则/金手指/冲突计划/小说锚点。"""
    lines: list[str] = []
    for label, value in (
        ("规则画像", req.rule_profile),
        ("世界规则", req.world_rules),
        ("金手指规则", req.golden_finger_rules),
        ("冲突计划", req.conflict_plan),
        ("小说改编锚点", req.episode_novel_anchor),
    ):
        text = str(value or "").strip()
        if text:
            lines.append(f"- {label}：{text[:180]}")
    return "\n".join(lines) if lines else "暂无额外规则上下文。"


def build_testing_rag_context(
    req: "TestingScriptRequest",
    *,
    compact: bool = False,
    budget: int | None = None,
) -> str:
    """拼出完整 RAG 上下文（compact / 全量 两种模式）。"""
    lines: list[str] = []
    if budget is None:
        if req.mode == "segment":
            budget = 1500 if str(req.segment_id or "hook") == "hook" else 1100
        else:
            budget = 2600
    compiled = format_testing_rag_context_pack(req, budget=budget)
    if compiled and "暂无 RAG" not in compiled:
        lines.append(f"## 项目重上下文 RAG 调度包\n{compiled}")
    if compact:
        return "\n\n".join(lines) if lines else "暂无 RAG 补充上下文。"
    for label, value in (
        ("头部剧本 RAG", req.rag_script_references),
        ("桥段/素材 RAG", req.rag_asset_references),
        ("市场信号 RAG", req.rag_market_signals),
        ("原著/章节 RAG", req.rag_novel_chapters),
        ("质检对标 RAG", req.rag_review_references),
    ):
        text = str(value or "").strip()
        if text:
            lines.append(f"## {label}\n{text[:1200]}")
    return "\n\n".join(lines) if lines else "暂无 RAG 补充上下文。"
