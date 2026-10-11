"""测试页“场景评估主流程 + 剧作契约违反检测 + 结构化更新抽取”（从 short_drama_writing.py 抽出）。

3 个核心函数：

- detect_testing_episode_contract_issues：基于本集契约 + 全剧 must_not，检测正文里的契约违反
- extract_testing_structured_updates：调 LLM 抽取关系/状态/记忆卡/canon 补丁/质检/合规
- evaluate_testing_scene：场景评估主流程，串起所有 detection + 结构化更新 + 失败分析

`extract_testing_structured_updates` 依赖 LLM（generate_json），其余两者纯函数。
"""
from __future__ import annotations

import hashlib
import re
from typing import Any, TYPE_CHECKING

from app.schemas.short_drama_writing import TestingFailureAnalysis
from app.services.short_drama_benchmark_assessment import (
    detect_testing_head_quality_issues,
    detect_testing_local_patch_issues,
)
from app.services.short_drama_canon_blocks import (
    build_inferred_canon_packet,
    build_testing_episode_memory_block,
    format_testing_canon_block,
)
from app.services.short_drama_deep_audit import generation_kwargs_from_req
from app.services.short_drama_detection_helpers import (
    analyze_testing_character_health,
    detect_relationship_updates,
    detect_state_card_suggestions,
    detect_testing_narrative_logic_issues,
    validate_testing_script_output,
)
from app.services.short_drama_episode_contract import (
    build_testing_series_simulation_packet,
)
from app.services.short_drama_episode_locks import extract_episode_keywords
from app.services.short_drama_evaluation_pipeline import (
    STRUCTURED_UPDATE_CACHE,
    STRUCTURED_UPDATE_CACHE_MAX,
    fallback_episode_memory_card,
    review_testing_scene_quality,
    split_testing_generation_issues,
    structured_update_fingerprint,
)
from app.services.short_drama_final_generation_contract import current_testing_final_generation_contract
from app.services.short_drama_failure_classifier import classify_testing_failure
from app.services.short_drama_format_repairs import apply_testing_hard_repairs
from app.services.short_drama_narrative_drift import detect_testing_narrative_drift_issues
from app.services.short_drama_state_cards import build_testing_state_cards_block
from app.services.short_drama_stage_trace import timed_stage
from app.services.short_drama_testing_normalizers import merge_testing_canon_packet
from app.services.short_drama_workspace_blocks import build_workspace_character_block
from app.services.text_generation_service import generate_json

if TYPE_CHECKING:
    from app.schemas.short_drama_writing import TestingScriptRequest


def _compact_contract_text(value: Any) -> str:
    text = str(value or "")
    return re.sub(r"[\s，。！？；：、“”‘’（）()《》【】—…,.!?;:\"'<>-]+", "", text)


def _split_required_scene_nodes(required_scene: str) -> list[str]:
    text = re.sub(r"[（(][^）)]*[）)]", "", str(required_scene or "").strip())
    nodes: list[str] = []
    seen: set[str] = set()
    for raw in re.split(r"\s*(?:→|->|=>|、|/|｜|\||与)\s*", text):
        node = raw.strip()
        compact = _compact_contract_text(node)
        if len(compact) < 2 or compact in seen:
            continue
        nodes.append(node)
        seen.add(compact)
    return nodes


def _scene_core_candidates(required_scene: str) -> list[str]:
    text = re.sub(r"[（(][^）)]*[）)]", "", str(required_scene or "").strip())
    compact_scene = _compact_contract_text(text)
    candidates: list[str] = [compact_scene]
    first_clause = re.split(r"[，,；;。.!?！？]", text, maxsplit=1)[0]
    compact_clause = _compact_contract_text(first_clause)
    if compact_clause:
        candidates.append(compact_clause)
        core = compact_clause.rsplit("的", 1)[-1]
        candidates.append(core)
        for size in range(min(8, len(core)), 1, -1):
            candidates.append(core[-size:])
    if len(compact_scene) <= 12:
        for size in range(min(8, len(compact_scene)), 1, -1):
            candidates.append(compact_scene[-size:])
    return [item for item in dict.fromkeys(candidates) if len(item) >= 2]


def _testing_scene_node_landed(required_scene: str, compact_text: str) -> bool:
    compact_scene = _compact_contract_text(required_scene)
    if len(compact_scene) < 2:
        return True
    if compact_scene in compact_text:
        return True

    return any(candidate in compact_text for candidate in _scene_core_candidates(required_scene))


def _testing_scene_landed(required_scene: str, compact_text: str) -> bool:
    compact_scene = _compact_contract_text(required_scene)
    if len(compact_scene) < 2:
        return True
    if compact_scene in compact_text:
        return True

    scene_nodes = _split_required_scene_nodes(required_scene)
    if len(scene_nodes) >= 2:
        return all(_testing_scene_node_landed(node, compact_text) for node in scene_nodes)

    return _testing_scene_node_landed(required_scene, compact_text)


def _contract_required_values(contract: dict[str, Any], marker: str) -> list[str]:
    values = contract.get("must_happen")
    if not isinstance(values, list):
        return []
    result: list[str] = []
    for raw in values:
        text = str(raw or "").strip()
        if marker not in text:
            continue
        if "：" in text:
            value = text.split("：", 1)[1].strip()
        elif ":" in text:
            value = text.split(":", 1)[1].strip()
        else:
            value = text.replace(marker, "").strip(" ：:")
        if value:
            result.append(value)
    return list(dict.fromkeys(result))[:3]


def detect_testing_episode_contract_issues(
    req: "TestingScriptRequest",
    content: str,
) -> list[str]:
    """基于本集契约 + 全剧 must_not，检测正文里的契约违反。"""
    text = str(content or "").strip()
    if not text:
        return []

    contract = current_testing_final_generation_contract(req)
    packet = build_testing_series_simulation_packet(req)
    compact_text = _compact_contract_text(text)
    guard_text = "\n".join([
        *[str(item) for item in (contract.get("must_not_happen") or [])],
        *[str(item) for item in (packet.get("global_must_not") or [])],
    ])
    issues: list[str] = []

    # 分段精写只生成四段中的一个片段，不能要求钩子段一次性落完整集
    # 的所有主场景节点；整集保存/整集快写仍会保留这个硬门。
    if str(getattr(req, "mode", "") or "scene") == "scene":
        scene_requirements = [
            str(contract.get("required_main_scene") or "").strip(),
            *_contract_required_values(contract, "主场景必须落地"),
        ]
        for scene in list(dict.fromkeys(item for item in scene_requirements if item)):
            if not _testing_scene_landed(scene, compact_text):
                issues.append(f"剧作契约冲突：主场景未落地，契约要求“{scene[:40]}”，正文没有出现。")

    if any(marker in guard_text for marker in ("不能重演", "重复", "重启")):
        previous_briefs = [item for item in (req.previous_episode_briefs or []) if isinstance(item, dict)]
        opening = "\n".join([line.strip() for line in text.splitlines() if line.strip()][:6])
        if previous_briefs and any(marker in opening for marker in ("又一次", "重新", "再一次", "还是那辆", "还是那份", "又被拖", "又被逼")):
            prev_text = " ".join(
                str(item.get(key) or "")
                for item in previous_briefs[-2:]
                for key in ("summary", "actual_progress", "body_excerpt")
            )
            shared = [
                marker for marker in ("拖", "车", "婚书", "签字", "按手印", "围观", "堵门", "发布会", "退婚", "追债", "账本", "录音", "证据")
                if marker in opening and marker in prev_text
            ]
            if len(shared) >= 2:
                issues.append("剧作契约冲突：开场重演前序已落地动作，没有从本集契约的开场承接继续推进。")

    if any(marker in guard_text for marker in ("提前兑现", "后续集", "大反转", "身份揭露", "最终胜负")):
        future_text = " ".join(
            str(item.get(key) or "")
            for item in (req.future_episode_briefs or [])[:3]
            if isinstance(item, dict)
            for key in ("summary", "conflict", "hook")
        )
        future_keywords = [
            token for token in ("真凶", "幕后", "最终", "定案", "公开身份", "亲子鉴定", "正式结婚", "冻结全部", "认祖归宗", "继承权", "大结局")
            if token in future_text
        ]
        if future_keywords and any(token in text for token in future_keywords):
            issues.append("剧作契约冲突：正文提前兑现了后续集沙盘预留的大反转或终局信息。")
        future_event_keywords = [
            token for token in extract_episode_keywords(future_text)
            if token and token not in extract_episode_keywords(req.episode_summary or "", req.episode_conflict or "", req.episode_hook or "")
        ]
        future_commitment_tokens = ("明天", "后天", "改天", "回头就", "之后就", "到时候", "以后我就", "等我", "带你", "迁户", "一起查到底", "堵门", "拦人", "截人", "吉普车")
        if future_event_keywords and any(token in text for token in future_event_keywords) and any(token in text for token in future_commitment_tokens):
            issues.append("剧作契约冲突：正文提前预演了后续集核心事件或动作模板，提前消耗了未来集情节点。")

    if any(marker in guard_text for marker in ("证据链", "官方", "权威", "裁定", "定案")):
        official_result_tokens = ("定案", "冻结全部", "正式立案", "调查结论", "处罚决定", "判决", "裁定", "盖章确认", "全部查封")
        bridge_tokens = ("提交", "递交", "备案", "受理", "核验", "送检", "移交", "回执", "转交", "报案")
        if any(token in text for token in official_result_tokens) and not any(token in text for token in bridge_tokens):
            issues.append("剧作契约冲突：本集证据/规则推进越过了递交、核验或受理桥，直接写成权威结论。")

    if any(marker in guard_text for marker in ("关系变化", "感情定性", "新状态", "直接把关系")):
        relationship_jump_tokens = ("我爱你", "我们结婚", "正式在一起", "你是我唯一", "从今以后我都听你的", "我永远站你这边")
        trigger_tokens = ("因为", "看见", "听见", "证据", "救了", "挡下", "代价", "回执", "录音", "账本", "鉴定")
        if any(token in text for token in relationship_jump_tokens) and not any(token in text for token in trigger_tokens):
            issues.append("剧作契约冲突：关系跳档缺少触发动作、台词反应和当场代价。")

    if any(marker in guard_text for marker in ("系统/金手指", "修炼规则", "代价", "生效边界")):
        rule_break_tokens = ("无需代价", "不用代价", "没有代价", "直接突破", "连升三境", "规则今天改了", "临时改规则", "破例生效")
        rule_bridge_tokens = ("代价", "反噬", "限制", "倒计时", "惩罚", "条件", "冷却", "消耗", "失去")
        if any(token in text for token in rule_break_tokens) and not any(token in text.replace("无需代价", "") for token in rule_bridge_tokens):
            issues.append("剧作契约冲突：系统/金手指/修炼规则临场改效力，缺少代价、条件或生效边界。")

    return list(dict.fromkeys(issue for issue in issues if issue))[:3]


def extract_testing_structured_updates(req: "TestingScriptRequest", content: str, present_ids: list[str]) -> dict[str, Any]:
    """调 LLM 抽取关系/状态/记忆卡/canon 补丁/质检/合规。带 LRU 缓存。"""
    text = str(content or "").strip()
    if not text:
        return {}
    fp = structured_update_fingerprint(req, text, present_ids)
    cached = STRUCTURED_UPDATE_CACHE.get(fp)
    if cached is not None:
        STRUCTURED_UPDATE_CACHE.move_to_end(fp)
        return cached

    system_prompt = (
        "你是短剧系列统筹与连续性编辑。"
        "请只输出一个 JSON 对象，不要解释，不要 markdown。"
        "你的任务是从当前正文中提取已经被镜头坐实的关系变化、状态变化、集级记忆与 canon 变更。"
        "若证据不足，必须返回空数组，不允许脑补。"
    )
    user_prompt = (
        f"项目：{req.series_title or '未命名项目'}\n"
        f"当前集：第{int(req.episode_no or 0)}集\n"
        f"当前场：第{int(req.scene_no or 0)}场\n"
        f"当前模式：{req.mode}\n\n"
        "【人物与关系基线】\n"
        f"{build_workspace_character_block(req.characters or [], set(str(i) for i in present_ids))}\n\n"
        "【状态卡基线】\n"
        f"{build_testing_state_cards_block(req.state_cards or {}, req.characters or [], set(str(i) for i in present_ids), current_episode=int(req.episode_no or 0))}\n\n"
        "【Series Memory】\n"
        f"{build_testing_episode_memory_block(req, limit=3)}\n\n"
        "【Canon 包】\n"
        f"{format_testing_canon_block(req)}\n\n"
        "【当前正文】\n"
        f"{text[:2600]}\n\n"
        "输出 JSON：\n"
        "{\n"
        '  "relationship_updates": [{"source_id":"","target_id":"","suggested_type":"","suggested_strength":0,"description":"","evidence":"","confidence":0}],\n'
        '  "state_card_updates": [{"kind":"relationship|info|power|promise|locked_fact","title":"","summary":"","related_character_ids":[""],"state":"active|locked","evidence":"","confidence":0}],\n'
        '  "episode_memory_card": {"episode_no": 0, "title": "", "summary": "", "opening_state": "", "ending_state": "", "relationship_delta": [""], "information_delta": [""], "power_delta": [""], "unresolved_hooks": [""], "spoiler_guard": [""], "body_excerpt": "", "quality_summary": ""},\n'
        '  "canon_patch": {"hard_constraints": [""], "relationship_limits": [""], "information_schedule": [""], "locked_facts": [""], "timeline_anchors": [""], "notes": ""},\n'
        '  "quality_report": {"summary": "", "focus": "", "next_fix": ""},\n'
        '  "compliance_report": {"summary": "", "risks": [""]}\n'
        "}\n\n"
        "要求：\n"
        "- 只抽取正文里已经真正发生的变化，不要把大纲计划当成已发生。\n"
        "- relationship_updates 必须有动作/台词证据，且 source_id/target_id 必须来自现有角色。\n"
        "- episode_memory_card.summary 必须写“本集已落地结果”，不是本集计划。\n"
        "- canon_patch 只写新锁定的事实或必须升级为硬约束的内容。"
    )

    by_id = {str(char.get("id") or ""): char for char in (req.characters or []) if isinstance(char, dict)}
    by_name = {str(char.get("name") or "").strip(): str(char.get("id") or "") for char in (req.characters or []) if isinstance(char, dict) and str(char.get("name") or "").strip()}
    try:
        payload = generate_json(
            system_prompt,
            user_prompt,
            temperature=0.1,
            max_tokens=900,
            **generation_kwargs_from_req(req),
        )
    except Exception:
        return {}

    relationship_suggestions: list[dict[str, Any]] = []
    for idx, item in enumerate(payload.get("relationship_updates") or []):
        if not isinstance(item, dict):
            continue
        source_id = str(item.get("source_id") or "").strip() or by_name.get(str(item.get("source_name") or "").strip(), "")
        target_id = str(item.get("target_id") or "").strip() or by_name.get(str(item.get("target_name") or "").strip(), "")
        relation_type = str(item.get("suggested_type") or "").strip()
        if not source_id or not target_id or not relation_type or source_id not in by_id or target_id not in by_id:
            continue
        try:
            confidence = float(item.get("confidence") or 0)
        except Exception:
            confidence = 0.0
        if confidence < 0.45:
            continue
        source_name = str((by_id.get(source_id) or {}).get("name") or source_id)
        target_name = str((by_id.get(target_id) or {}).get("name") or target_id)
        relationship_suggestions.append({
            "key": f"structured_rel_{idx}_{source_id}_{target_id}_{relation_type}",
            "source_id": source_id,
            "source_name": source_name,
            "target_id": target_id,
            "target_name": target_name,
            "suggested_type": relation_type,
            "suggested_strength": max(1, min(100, int(item.get("suggested_strength") or 60))),
            "description": str(item.get("description") or item.get("evidence") or "").strip()[:160],
            "evidence": str(item.get("evidence") or "").strip()[:120],
            "confidence": confidence,
        })

    state_card_suggestions: list[dict[str, Any]] = []
    for idx, item in enumerate(payload.get("state_card_updates") or []):
        if not isinstance(item, dict):
            continue
        kind = str(item.get("kind") or "").strip()
        if kind not in {"relationship", "info", "power", "promise", "locked_fact"}:
            continue
        related_ids = [str(v).strip() for v in (item.get("related_character_ids") or []) if str(v).strip()]
        try:
            confidence = float(item.get("confidence") or 0)
        except Exception:
            confidence = 0.0
        if confidence < 0.45:
            continue
        state_card_suggestions.append({
            "key": f"structured_state_{idx}_{kind}_{hashlib.sha1(str(item.get('title') or '').encode('utf-8')).hexdigest()[:8]}",
            "kind": kind,
            "title": str(item.get("title") or "").strip()[:60],
            "summary": str(item.get("summary") or item.get("evidence") or "").strip()[:160],
            "related_character_ids": related_ids,
            "state": str(item.get("state") or ("locked" if kind == "locked_fact" else "active")).strip(),
            "evidence": str(item.get("evidence") or "").strip()[:120],
            "confidence": confidence,
        })

    episode_memory_card = payload.get("episode_memory_card") if isinstance(payload.get("episode_memory_card"), dict) else {}
    canon_patch = payload.get("canon_patch") if isinstance(payload.get("canon_patch"), dict) else {}
    result = {
        "relationship_suggestions": relationship_suggestions[:6],
        "state_card_suggestions": state_card_suggestions[:8],
        "episode_memory_card": episode_memory_card,
        "canon_packet": merge_testing_canon_packet(build_inferred_canon_packet(req), canon_patch),
        "quality_report": payload.get("quality_report") if isinstance(payload.get("quality_report"), dict) else {},
        "compliance_report": payload.get("compliance_report") if isinstance(payload.get("compliance_report"), dict) else {},
    }
    STRUCTURED_UPDATE_CACHE[fp] = result
    if len(STRUCTURED_UPDATE_CACHE) > STRUCTURED_UPDATE_CACHE_MAX:
        STRUCTURED_UPDATE_CACHE.popitem(last=False)
    return result


def evaluate_testing_scene(
    req: "TestingScriptRequest",
    content: str,
    quality_anchor_block: str,
) -> dict[str, Any]:
    """场景评估主流程：format/角色/叙事漂移/契约/局部打磨/头部对标/llm 审段 → 输出评估包。"""
    contract = current_testing_final_generation_contract(req)
    content_text = apply_testing_hard_repairs(req, str(content or "").strip())
    char_count, format_errors = validate_testing_script_output(content_text, req)
    health_items, health_warnings, health_blocking, present_ids = analyze_testing_character_health(
        content_text,
        req.characters or [],
        req.selected_character_ids or [],
    )
    relationship_suggestions = detect_relationship_updates(content_text, req.characters or [], present_ids)
    state_card_suggestions = detect_state_card_suggestions(content_text, req.characters or [], present_ids, req.state_cards or {})
    format_blocking, format_warnings = split_testing_generation_issues(req, format_errors)
    blocking_issues = list(dict.fromkeys([*format_blocking, *health_blocking]))
    warnings = list(dict.fromkeys([*format_warnings, *health_warnings]))
    if str(getattr(req, "mode", "") or "") == "segment":
        blocking_issues, warnings = _demote_segment_dialogue_anchor_blockers(
            blocking_issues,
            warnings,
            health_items,
        )
    narrative_drift_issues = detect_testing_narrative_drift_issues(req, content_text)
    if narrative_drift_issues:
        blocking_issues = list(dict.fromkeys([*blocking_issues, *narrative_drift_issues]))
        warnings = list(dict.fromkeys([
            *warnings,
            *(f"叙事阻断：{item}" for item in narrative_drift_issues),
        ]))[:8]
    contract_issues = detect_testing_episode_contract_issues(req, content_text)
    if contract_issues:
        blocking_issues = list(dict.fromkeys([*blocking_issues, *contract_issues]))
        warnings = list(dict.fromkeys([
            *warnings,
            *(f"契约阻断：{item}" for item in contract_issues),
        ]))[:8]
    local_patch_issues = detect_testing_local_patch_issues(req, content_text)
    if local_patch_issues:
        blocking_issues = list(dict.fromkeys([*blocking_issues, *local_patch_issues]))
        warnings = list(dict.fromkeys([
            *warnings,
            *(f"局部打磨：{item}" for item in local_patch_issues),
        ]))[:8]
    head_quality_issues = detect_testing_head_quality_issues(req, content_text, contract)
    hard_head_markers = ("开篇钩子弱", "爽点密度不足", "头部爆点后果弱", "反派压制模板化", "项目打磨模板污染", "终局闭环不足")
    hard_head_issues = [item for item in head_quality_issues if any(marker in item for marker in hard_head_markers)]
    soft_head_issues = [item for item in head_quality_issues if item not in hard_head_issues]
    if hard_head_issues:
        blocking_issues = list(dict.fromkeys([*blocking_issues, *hard_head_issues]))
        warnings = list(dict.fromkeys([
            *warnings,
            *(f"头部对标阻断：{item}" for item in hard_head_issues),
        ]))[:8]
    if soft_head_issues:
        warnings = list(dict.fromkeys([
            *warnings,
            *(f"头部对标提醒：{item}" for item in soft_head_issues),
        ]))[:8]
    quality_passed = True
    quality_issues: list[str] = []
    lightweight_validation = bool(getattr(req, "autofix_lightweight_validation", False))

    if not blocking_issues and not lightweight_validation:
        quality_issues.extend(detect_testing_narrative_logic_issues(req, content_text, health_items))
        quality_issues.extend(soft_head_issues)
        with timed_stage(req, "quality_review"):
            llm_quality_passed, llm_quality_issues = review_testing_scene_quality(req, content_text, quality_anchor_block)
        quality_issues.extend(llm_quality_issues)
        quality_issues = list(dict.fromkeys(item for item in quality_issues if str(item).strip()))[:3]
        quality_passed = llm_quality_passed and not quality_issues
        if str(getattr(req, "mode", "") or "") == "segment" and not blocking_issues and quality_issues:
            quality_passed = True
        if quality_issues:
            warnings.extend(f"审段提醒：{item}" for item in quality_issues)

    can_promote_runtime_state = not blocking_issues
    structured_updates: dict[str, Any] = {}
    if req.mode == "scene" and not blocking_issues and not lightweight_validation:
        with timed_stage(req, "structured_updates"):
            structured_updates = extract_testing_structured_updates(req, content_text, present_ids)
        relationship_suggestions = structured_updates.get("relationship_suggestions") or relationship_suggestions
        state_card_suggestions = structured_updates.get("state_card_suggestions") or state_card_suggestions
    if blocking_issues:
        # A blocked scene is not canon. Do not let bad drafts promote relationship/state changes.
        relationship_suggestions = []
        state_card_suggestions = []

    episode_memory_card = (
        structured_updates.get("episode_memory_card")
        if can_promote_runtime_state and isinstance(structured_updates.get("episode_memory_card"), dict)
        else {}
    )
    if can_promote_runtime_state and not episode_memory_card:
        episode_memory_card = fallback_episode_memory_card(req, content_text, {
            "warnings": warnings,
            "blocking_issues": blocking_issues,
            "quality_issues": quality_issues,
        })
    canon_packet = (
        structured_updates.get("canon_packet")
        if can_promote_runtime_state and isinstance(structured_updates.get("canon_packet"), dict)
        else build_inferred_canon_packet(req)
        if can_promote_runtime_state
        else {}
    )

    result = {
        "content": content_text,
        "char_count_excluding_punctuation": char_count,
        "warnings": list(dict.fromkeys(warnings))[:5],
        "blocking_issues": blocking_issues,
        "present_character_ids": present_ids,
        "health_items": health_items,
        "relationship_suggestions": relationship_suggestions,
        "state_card_suggestions": state_card_suggestions,
        "quality_passed": quality_passed,
        "quality_issues": quality_issues[:3],
        "episode_memory_card": episode_memory_card,
        "canon_packet": canon_packet,
        "quality_report": structured_updates.get("quality_report") if isinstance(structured_updates.get("quality_report"), dict) else {},
        "compliance_report": structured_updates.get("compliance_report") if isinstance(structured_updates.get("compliance_report"), dict) else {},
    }
    result["failure_analysis"] = classify_testing_failure(req, result) if (blocking_issues or not quality_passed) else TestingFailureAnalysis()
    return result


def _demote_segment_dialogue_anchor_blockers(
    blocking_issues: list[str],
    warnings: list[str],
    health_items: list[dict[str, Any]],
) -> tuple[list[str], list[str]]:
    """分段审查只要求当前小段可承接；整集台词完整性留给最终整集门。"""
    demotable_names = {
        str(item.get("name") or "").strip()
        for item in health_items
        if isinstance(item, dict)
        and str(item.get("name") or "").strip()
        and item.get("present") is True
        and int(item.get("dialogue_count") or 0) == 0
    }
    if not demotable_names:
        return blocking_issues, warnings

    remaining: list[str] = []
    demoted: list[str] = []
    for issue in blocking_issues:
        text = str(issue or "").strip()
        if "已出场但没有标准台词" in text and any(name in text for name in demotable_names):
            demoted.append(text)
            continue
        remaining.append(text)
    if not demoted:
        return blocking_issues, warnings
    merged_warnings = list(dict.fromkeys([
        *warnings,
        *(f"分段提醒：{item}" for item in demoted),
    ]))[:8]
    return list(dict.fromkeys(remaining)), merged_warnings
