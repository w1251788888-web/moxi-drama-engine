"""测试页“场景生成主流程 + prompt 装配 + segment-lite prompt”（从 short_drama_writing.py 抽出）。

3 个核心函数：

- build_segment_lite_prompt：分段续写（hook/validation/explosion/resolution）的轻量 prompt
- prepare_testing_script_generation：把 req 装成 (system_prompt, user_prompt, anchor) 三元组
- generate_testing_scene_passed：场景生成主循环（生成 → 评估 → 失败重试 → 自动修复回退）

`generate_testing_scene_passed` 调 LLM（generate_text）+ autofix。其余两个纯函数。
"""
from __future__ import annotations

from string import Template
from typing import Any, Optional, TYPE_CHECKING

from fastapi import HTTPException

from app.schemas.short_drama_writing import (
    TestingFailureAnalysis,
    TestingScriptValidationRequest,
)
from app.services.short_drama_autofix import (
    auto_fix_testing_script_content,
    build_internal_rewrite_prompt,
)
from app.services.short_drama_advanced_generation import apply_testing_generation_route
from app.services.short_drama_canon_blocks import (
    build_testing_episode_memory_block,
    format_testing_canon_block,
)
from app.services.short_drama_deep_audit import generation_kwargs_from_req
from app.services.short_drama_director_blueprint import (
    director_blueprint_trace_extra,
    format_director_blueprint_block,
)
from app.services.short_drama_episode_contract import (
    build_testing_continuity_guardrails,
    format_testing_episode_contract_block,
)
from app.services.short_drama_episode_locks import (
    build_lockword_block,
    build_segment_intent_block,
)
from app.services.short_drama_evaluate_scene import evaluate_testing_scene
from app.services.short_drama_evaluation_pipeline import (
    apply_scene_level_gate,
    evaluation_score,
    promote_scene_word_count_warnings,
)
from app.services.short_drama_final_generation_contract import (
    current_testing_final_generation_contract,
    format_final_generation_contract_block,
)
from app.services.short_drama_format_repairs import apply_testing_hard_repairs
from app.services.short_drama_quality_anchors import build_testing_quality_anchor_block
from app.services.short_drama_rag_cards import (
    build_testing_rag_context,
    build_testing_rule_context,
)
from app.services.short_drama_rule_resolver import (
    load_agent_prompt,
    load_step_template,
    resolve_rules_injection,
)
from app.services.short_drama_segment_blocks import (
    build_testing_segment_character_mini_block,
    build_testing_segment_confirmed_context_block,
    build_testing_segment_focus_block,
    build_testing_segment_guardrail_block,
)
from app.services.short_drama_segment_tasks import resolve_segment_task
from app.services.short_drama_state_cards import (
    build_relationship_guardrail_block,
    build_testing_state_cards_block,
)
from app.services.short_drama_stage_trace import record_stage_trace, timed_stage
from app.services.short_drama_testing_blocks import (
    build_future_episode_brief_block,
    build_previous_episode_brief_block,
    build_relationship_diff_block,
)
from app.services.short_drama_testing_contexts import (
    build_testing_issue_feedback_context,
    build_testing_material_context,
    build_testing_report_context,
)
from app.services.short_drama_testing_failure import log_testing_failure_analysis
from app.services.short_drama_testing_rules import (
    build_testing_format_rule,
    build_testing_length_rule,
)
from app.services.short_drama_text_format import count_testing_chars, hard_truncate_by_sentence
from app.services.short_drama_workflow_config import SCRIPT_DRAFT_MODES
from app.services.short_drama_workspace_blocks import (
    build_workspace_character_block,
    build_workspace_concept_block,
    build_workspace_scene_block,
    derive_workspace_project_type,
)
from app.services.text_generation_service import generate_text

if TYPE_CHECKING:
    from app.schemas.short_drama_writing import TestingScriptRequest


TESTING_SCRIPT_SCENE_PROMPT_FILE = "05_script_test_scene.md"
SCENE_WRITER_TIMEOUT_SECONDS = 90
SCENE_REVIEW_TIMEOUT_SECONDS = 45
SCENE_AUTOFIX_TIMEOUT_SECONDS = 75
SCENE_LENGTH_COMPLETION_TIMEOUT_SECONDS = 60
SCENE_STAGE_MAX_RETRIES = 1


class TestingSceneQualityGateError(HTTPException):
    """HTTP quality-gate error that keeps the best candidate for job delivery."""

    def __init__(self, req: "TestingScriptRequest", candidate: dict[str, Any]):
        self.candidate = candidate if isinstance(candidate, dict) else {}
        super().__init__(
            status_code=400,
            detail=_build_generation_failure_detail(req, self.candidate),
        )


def _safe_failure_analysis(raw: Any) -> dict[str, Any]:
    if raw is None:
        return {}
    if hasattr(raw, "model_dump"):
        try:
            return raw.model_dump()
        except Exception:
            return {}
    return raw if isinstance(raw, dict) else {}


def _word_count_issue_is_minor(req: "TestingScriptRequest", candidate: dict[str, Any]) -> bool:
    """Allow small word-count drift to pass as a warning.

    The generated text can be otherwise valid but exceed the configured upper bound by a
    handful of net characters, or miss the lower bound a little. Treating that as a hard
    generation failure breaks the writing chain and hides a usable result from the user.
    """
    min_count = int(req.word_count_min or 0)
    max_count = int(req.word_count_max or 0)
    if min_count <= 0 and max_count <= 0:
        return False
    issues = [str(item or "").strip() for item in (candidate.get("blocking_issues") or []) if str(item or "").strip()]
    if not issues:
        return False
    if not all(("净字数超限" in item or "要求至多" in item or "净字数不足" in item or "要求至少" in item) for item in issues):
        return False

    current_count = int(candidate.get("char_count_excluding_punctuation") or 0)
    if min_count <= current_count <= max_count:
        return True
    if current_count < min_count:
        tolerance = max(80, int(min_count * 0.2))
        return min_count - current_count <= tolerance
    if max_count > 0:
        tolerance = max(80, int(max_count * 0.2))
        return current_count - max_count <= tolerance
    return False


def _release_minor_word_count_issue(req: "TestingScriptRequest", candidate: dict[str, Any]) -> dict[str, Any]:
    current_count = int(candidate.get("char_count_excluding_punctuation") or 0)
    min_count = int(req.word_count_min or 0)
    max_count = int(req.word_count_max or 0)
    target_label = f"{min_count}-{max_count}" if min_count and max_count else str(max_count or min_count or "")
    if max_count and current_count > max_count:
        warning = f"净字数与目标区间有偏差：字数超限 {current_count - max_count} 字，当前 {current_count}，目标 {target_label}，已先放行，由用户决定接受或调整。"
    elif min_count and current_count < min_count:
        warning = f"净字数与目标区间有偏差：字数不足 {min_count - current_count} 字，当前 {current_count}，目标 {target_label}，已先放行，由用户决定接受或调整。"
    else:
        warning = f"净字数与目标区间有偏差：当前 {current_count}，目标 {target_label}，已先放行，由用户决定接受或调整。"
    merged_warnings = list(dict.fromkeys([*(candidate.get("warnings") or []), warning]))[:8]
    candidate["warnings"] = merged_warnings
    candidate["blocking_issues"] = []
    candidate["quality_passed"] = True
    return candidate


def _with_stage_budget(
    req: "TestingScriptRequest",
    *,
    timeout_seconds: int,
    max_retries: int = SCENE_STAGE_MAX_RETRIES,
) -> "TestingScriptRequest":
    current_timeout = getattr(req, "generation_timeout_seconds", None)
    current_retries = getattr(req, "generation_max_retries", None)
    updates = {
        "generation_timeout_seconds": int(min(int(current_timeout), timeout_seconds) if current_timeout else timeout_seconds),
        "generation_max_retries": int(min(int(current_retries), max_retries) if current_retries else max_retries),
    }
    return req.model_copy(update=updates)


def _word_count_shortfall_is_only_blocker(req: "TestingScriptRequest", candidate: dict[str, Any]) -> bool:
    issues = [str(item or "").strip() for item in (candidate.get("blocking_issues") or []) if str(item or "").strip()]
    if not issues:
        return False
    if not all(("净字数不足" in item or "要求至少" in item) for item in issues):
        return False
    current_count = int(candidate.get("char_count_excluding_punctuation") or 0)
    min_count = int(req.word_count_min or 0)
    if min_count <= 0 or current_count >= min_count:
        return False
    return not _word_count_issue_is_minor(req, candidate)


def _contract_required_value(contract: dict[str, Any], marker: str) -> str:
    values = contract.get("must_happen")
    if not isinstance(values, list):
        return ""
    for raw in values:
        text = str(raw or "").strip()
        if marker not in text:
            continue
        if "：" in text:
            return text.split("：", 1)[1].strip()
        if ":" in text:
            return text.split(":", 1)[1].strip()
        return text.replace(marker, "").strip(" ：:")
    return ""


def _scene_micro_shortfall_tail(contract: dict[str, Any]) -> str:
    scene = _contract_required_value(contract, "主场景必须落地") or "现场"
    prop = str(contract.get("evidence_object") or "那件证据").strip()
    hook = str(contract.get("ending_hook") or contract.get("outgoing_hook") or contract.get("real_loss") or "下一秒的动静").strip()
    return "\n".join([
        f"△{scene}里，所有人的目光同时落到{prop[:24]}上。",
        f"△{hook[:36]}压到下一秒，没人再能退回原位。",
    ])


def _complete_scene_length_shortfall(
    *,
    req: "TestingScriptRequest",
    writer_req: "TestingScriptRequest",
    reviewer_req: "TestingScriptRequest",
    original_content: str,
    evaluation: dict[str, Any],
    quality_anchor_block: str,
    contract: dict[str, Any],
) -> dict[str, Any] | None:
    """Only append missing dramatic material when the sole hard blocker is length."""
    if req.mode != "scene" or not _word_count_shortfall_is_only_blocker(req, evaluation):
        return None

    current_count = int(evaluation.get("char_count_excluding_punctuation") or 0)
    min_count = int(req.word_count_min or 0)
    target_count = int(req.word_count_target or req.target_chars or min_count)
    missing_to_min = max(min_count - current_count, 0)
    missing_to_target = max(target_count - current_count, missing_to_min)
    micro_limit = max(90, int(min_count * 0.08))
    if 0 < missing_to_min <= micro_limit:
        with timed_stage(req, "length_micro_completion"):
            micro_content = apply_testing_hard_repairs(
                req,
                f"{original_content.rstrip()}\n{_scene_micro_shortfall_tail(contract)}",
            )
            micro_eval = evaluate_testing_scene(reviewer_req, micro_content, quality_anchor_block)
            micro_eval = apply_scene_level_gate(reviewer_req, micro_eval, contract)
            micro_eval = promote_scene_word_count_warnings(req, micro_eval)
        if int(micro_eval.get("char_count_excluding_punctuation") or 0) >= min_count:
            return micro_eval
    max_tokens = min(1200, max(420, int(missing_to_target * 1.8) + 160))
    completion_prompt = (
        "## 定向补写\n"
        "当前初稿唯一硬伤是净字数不足。请只补写接在原文后面的后续动作和对白，禁止重写、禁止复述原文、禁止解释。\n"
        f"当前净字数约 {current_count}，交付区间下限 {min_count}，中心目标约 {target_count}。\n"
        "补写目标：把本集推进补足到交付区间内，同时延续原场景、原人物、原危机和原钩子。\n"
        "补写内容必须是可拍的动作、短对白、即时后果或新信息，不要写总结。\n\n"
        "## 原文\n"
        f"{original_content}\n\n"
        "## 只输出补写正文\n"
    )
    with timed_stage(req, "length_completion_generate", extra={"timeout_seconds": SCENE_LENGTH_COMPLETION_TIMEOUT_SECONDS}):
        completion = generate_text(
            "你是短剧定向增写助手，只负责补足缺口，不重写原文。",
            completion_prompt,
            **generation_kwargs_from_req(
                _with_stage_budget(
                    writer_req,
                    timeout_seconds=SCENE_LENGTH_COMPLETION_TIMEOUT_SECONDS,
                )
            ),
            temperature=writer_req.temperature if writer_req.temperature is not None else 0.25,
            max_tokens=max_tokens,
        )
    merged_content = apply_testing_hard_repairs(req, f"{original_content.rstrip()}\n{str(completion or '').strip()}")
    with timed_stage(req, "length_completion_local_evaluate"):
        completed_eval = evaluate_testing_scene(reviewer_req, merged_content, quality_anchor_block)
    with timed_stage(req, "length_completion_deep_gate"):
        completed_eval = apply_scene_level_gate(reviewer_req, completed_eval, contract)
    return promote_scene_word_count_warnings(req, completed_eval)


def _scene_overflow_is_only_blocker(req: "TestingScriptRequest", candidate: dict[str, Any]) -> bool:
    if req.mode not in ("scene", "segment") or not int(req.word_count_max or 0):
        return False
    issues = [str(item or "").strip() for item in (candidate.get("blocking_issues") or []) if str(item or "").strip()]
    if not issues:
        return False
    return all(("净字数超限" in item or "要求至多" in item) for item in issues)


def _strict_truncate_by_net_chars(
    text: str,
    max_chars: int,
    *,
    exclude_punct: bool,
) -> str:
    if not text or max_chars <= 0:
        return text
    line_out: list[str] = []
    line_total = 0
    for line in str(text or "").splitlines():
        line_count = count_testing_chars(line, exclude_punctuation=exclude_punct)
        if line_out and line_total + line_count > max_chars:
            break
        if not line_out and line_count > max_chars:
            break
        line_out.append(line)
        line_total += line_count
    line_candidate = "\n".join(line_out).rstrip()
    if line_candidate and count_testing_chars(line_candidate, exclude_punctuation=exclude_punct) <= max_chars:
        if line_candidate.strip() != str(text or "").strip():
            return line_candidate
    candidate = hard_truncate_by_sentence(text, max_chars, exclude_punct=exclude_punct)
    if count_testing_chars(candidate, exclude_punctuation=exclude_punct) <= max_chars:
        return candidate
    out: list[str] = []
    total = 0
    for ch in candidate:
        char_count = count_testing_chars(ch, exclude_punctuation=exclude_punct)
        if total + char_count > max_chars:
            break
        out.append(ch)
        total += char_count
    return "".join(out).rstrip() or candidate


def _trim_scene_overflow(
    *,
    req: "TestingScriptRequest",
    reviewer_req: "TestingScriptRequest",
    evaluation: dict[str, Any],
    quality_anchor_block: str,
    contract: dict[str, Any],
) -> dict[str, Any] | None:
    """Use deterministic trimming before spending another LLM call on pure overflow."""
    if not _scene_overflow_is_only_blocker(req, evaluation):
        return None
    max_count = int(req.word_count_max or 0)
    source = str(evaluation.get("content") or "")
    trimmed = _strict_truncate_by_net_chars(
        source,
        max_count,
        exclude_punct=bool(req.exclude_punctuation_for_count),
    )
    if not trimmed.strip() or trimmed.strip() == source.strip():
        return None
    record_stage_trace(
        req,
        "overflow_trim",
        "end",
        extra={
            "before_chars": int(evaluation.get("char_count_excluding_punctuation") or 0),
            "after_chars": count_testing_chars(trimmed, exclude_punctuation=bool(req.exclude_punctuation_for_count)),
            "max_chars": max_count,
        },
    )
    with timed_stage(req, "overflow_trim_local_evaluate"):
        trimmed_eval = evaluate_testing_scene(reviewer_req, trimmed, quality_anchor_block)
    with timed_stage(req, "overflow_trim_deep_gate"):
        trimmed_eval = apply_scene_level_gate(reviewer_req, trimmed_eval, contract)
    return promote_scene_word_count_warnings(req, trimmed_eval)


def _build_generation_failure_detail(req: "TestingScriptRequest", candidate: dict[str, Any]) -> dict[str, Any]:
    blocking_issues = [str(item or "").strip() for item in (candidate.get("blocking_issues") or []) if str(item or "").strip()]
    quality_issues = [str(item or "").strip() for item in (candidate.get("quality_issues") or []) if str(item or "").strip()]
    warnings = [str(item or "").strip() for item in (candidate.get("warnings") or []) if str(item or "").strip()]
    failure_analysis = _safe_failure_analysis(candidate.get("failure_analysis"))
    detail_items = blocking_issues or quality_issues or warnings
    return {
        "error_code": "quality_gate_failed",
        "detail": "；".join(detail_items[:3]) or "内部审段未通过。",
        "suggestion": "可点击重试此段。若连续失败，请先补充角色关系/大纲信息，或降低本段字数目标后再试。",
        "retryable": True,
        "stage": "script_scene_quality_gate",
        "segment_id": str(req.segment_id or ""),
        "episode_no": int(req.episode_no or 0),
        "scene_no": int(req.scene_no or 0),
        "blocking_issues": blocking_issues,
        "quality_issues": quality_issues,
        "warnings": warnings,
        "failure_analysis": failure_analysis,
        "char_count_excluding_punctuation": int(candidate.get("char_count_excluding_punctuation") or 0),
        "word_count_max": int(req.word_count_max or 0),
    }


def _append_late_error_warning(candidate: dict[str, Any], exc: Exception, *, stage: str) -> dict[str, Any]:
    warnings = [str(item or "").strip() for item in (candidate.get("warnings") or []) if str(item or "").strip()]
    warnings.append(f"{stage}后续尝试异常，已保留上一版候选稿用于质量门诊断：{type(exc).__name__}: {str(exc)[:90]}")
    candidate["warnings"] = list(dict.fromkeys(warnings))[:8]
    return candidate


def _render_testing_scene_prompt(variables: dict[str, str]) -> str:
    template_text = load_step_template(TESTING_SCRIPT_SCENE_PROMPT_FILE)
    template_text = resolve_rules_injection(template_text, variables)
    return Template(template_text).safe_substitute(variables)


def build_testing_manual_edit_context_block(req: "TestingScriptRequest") -> str:
    """Format user-saved edits as continuation facts for the next generation."""
    raw = req.manual_edit_context if isinstance(req.manual_edit_context, dict) else {}
    logs = raw.get("logs") if isinstance(raw.get("logs"), list) else []
    if not logs:
        latest = raw.get("latest") if isinstance(raw.get("latest"), dict) else {}
        logs = [latest] if latest else []
    if not logs:
        return ""

    try:
        current_episode = int(req.episode_no or 0)
    except Exception:
        current_episode = 0

    selected: list[dict[str, Any]] = []
    for item in logs:
        if not isinstance(item, dict):
            continue
        gate = item.get("next_episode_context_sync_gate") if isinstance(item.get("next_episode_context_sync_gate"), dict) else {}
        try:
            log_episode = int(item.get("episode_no") or 0)
            next_episode = int(gate.get("next_episode_no") or 0)
        except Exception:
            log_episode = 0
            next_episode = 0
        if current_episode <= 0 or next_episode == current_episode or log_episode in {current_episode, current_episode - 1}:
            selected.append(item)
        if len(selected) >= 3:
            break
    if not selected:
        selected = [item for item in logs if isinstance(item, dict)][:1]

    lines = [
        "## 用户手动改稿接续（高优先级）",
        "用户保存稿高于模型旧稿。生成时只能承接这些已保存事实，不得复述、覆盖或回滚到改稿前状态。",
    ]
    for item in selected:
        delta = item.get("manual_edit_delta") if isinstance(item.get("manual_edit_delta"), dict) else {}
        patch = item.get("canon_patch") if isinstance(item.get("canon_patch"), dict) else {}
        gate = item.get("next_episode_context_sync_gate") if isinstance(item.get("next_episode_context_sync_gate"), dict) else {}
        episode_no = int(delta.get("episode_no") or item.get("episode_no") or 0)
        scene_no = int(delta.get("scene_no") or item.get("scene_no") or 0)
        next_episode_no = int(gate.get("next_episode_no") or 0)
        current_excerpt = str(delta.get("current_excerpt") or "").strip()
        tail_excerpt = str(delta.get("tail_excerpt") or "").strip()
        manual_added_excerpt = str(delta.get("manual_added_excerpt") or "").strip()
        manual_removed_excerpt = str(delta.get("manual_removed_excerpt") or "").strip()
        locked_facts = [
            str(value or "").strip()
            for value in (patch.get("locked_facts") if isinstance(patch.get("locked_facts"), list) else [])
            if str(value or "").strip()
        ]
        lines.append(
            f"- 第{episode_no or '?'}集第{scene_no or '?'}场用户已保存改稿；"
            f"下一集接续目标：第{next_episode_no or '?'}集；"
            f"净字变化：{int(delta.get('clean_char_delta') or 0)}；"
            f"接续状态：{str(gate.get('status') or 'pending_verification')}"
        )
        if current_excerpt:
            lines.append(f"  最新保存片段：{current_excerpt[:360]}")
        if tail_excerpt:
            lines.append(f"  用户定稿尾部：{tail_excerpt[:360]}")
        if manual_added_excerpt:
            lines.append(f"  用户新增片段：{manual_added_excerpt[:360]}")
        if manual_removed_excerpt:
            lines.append(f"  用户删除/替换片段：{manual_removed_excerpt[:260]}")
        if locked_facts:
            lines.append("  必须承接事实：" + "；".join(locked_facts[:4]))
    return "\n".join(lines)


def build_testing_step_confirmation_block(req: "TestingScriptRequest") -> str:
    """Format user-reviewed step confirmation content for the writer chain."""
    packet = req.step_confirmation_packet if isinstance(req.step_confirmation_packet, dict) else {}
    confirmed = (
        req.user_confirmed_generation_packet
        if isinstance(req.user_confirmed_generation_packet, dict)
        else {}
    )
    items = packet.get("items") if isinstance(packet.get("items"), list) else []
    normalized: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()
        body = str(item.get("body") or "").strip()
        if not title and not body:
            continue
        normalized.append(
            {
                "step_id": str(item.get("step_id") or "").strip(),
                "title": title,
                "body": body,
                "source": str(item.get("source") or "").strip(),
            }
        )
        if len(normalized) >= 12:
            break
    if not normalized and not confirmed:
        return ""

    lines = [
        "## 用户分步确认台（高优先级）",
        "以下内容来自用户在生成前确认台里看到或修改过的前置判断。若与旧蓝图、旧集纲推断冲突，以用户确认台为准；但不得覆盖用户已保存正文正史。",
    ]
    episode_no = packet.get("episode_no")
    if episode_no:
        lines.append(f"- 当前确认集数：第{episode_no}集")
    for item in normalized:
        source = f"｜{item['source']}" if item.get("source") else ""
        step = f"[{item['step_id']}]" if item.get("step_id") else ""
        lines.append(f"- {step}{item['title']}{source}：{item['body'][:700]}")
    if confirmed:
        compact = str(confirmed)
        lines.append(f"- 结构化确认包：{compact[:1200]}")
    return "\n".join(lines)


def _legacy_episode_contract_block_for_writer(
    req: "TestingScriptRequest",
    legacy_block: str,
) -> str:
    """保留旧契约的非冲突背景，移除已被最终合同覆盖的旧值。"""
    contract = current_testing_final_generation_contract(req, include_rag=False)
    conflicts = [
        item
        for item in (contract.get("contract_conflicts") or [])
        if isinstance(item, dict) and item.get("auto_resolved") is True
    ]
    if not conflicts:
        return str(legacy_block or "").strip()

    sanitized = str(legacy_block or "").strip()
    covered_fields: list[str] = []
    for item in conflicts:
        field = str(item.get("field") or "").strip()
        stale_value = str(item.get("stale_value") or "").strip()
        if field:
            covered_fields.append(field)
        if stale_value:
            sanitized = sanitized.replace(stale_value, f"[{field or '旧字段'}已由最终生成合同覆盖]")

    field_text = "、".join(dict.fromkeys(covered_fields)) or "冲突字段"
    lines = [
        "旧契约已由后端自动归并：以下旧资料只保留非冲突背景，不再作为写作真源。",
        f"已覆盖字段：{field_text}。",
        "写作只执行上方最终生成合同；若旧契约仍出现不同说法，以最终生成合同为准。",
    ]
    if sanitized:
        lines.append(sanitized)
    return "\n".join(lines)


def build_segment_lite_prompt(variables: dict[str, str], task_instruction: str) -> str:
    """为分段续写（validation/explosion/resolution）构建轻量级 prompt。

    跳过全量规则注入（system prompt 已覆盖写作原则），只保留生成必要的上下文。
    """
    existing_text = str(variables.get("script_draft", "") or "").strip()
    lines = [
        f"项目：{variables.get('audience_axis', '')} {variables.get('genre_main', '')}  类型：{variables.get('project_type', '')}",
        "",
        "## 当前段焦点",
        variables.get("segment_focus_block", ""),
        "",
        "## Canon 包",
        variables.get("canon_packet_block", ""),
        "",
        "## 用户手动改稿接续",
        variables.get("manual_edit_context_block", ""),
        "",
        "## 用户分步确认台",
        variables.get("step_confirmation_block", ""),
        "",
        "## 最终生成合同 / 本集剧作契约",
        variables.get("final_generation_contract_block", ""),
        "",
        "## 旧契约兜底",
        variables.get("legacy_episode_contract_block", variables.get("episode_contract_block", "")),
        "",
        "## 导演工程蓝图",
        variables.get("director_blueprint_block", ""),
        "",
        "## 焦点角色",
        variables.get("segment_character_block", ""),
        "",
        "## RAG 高权重卡",
        variables.get("rag_context_block", ""),
        "",
        "## 已确认前文（只能承接，绝对不要重写或改写）",
        variables.get("segment_confirmed_context_block", "") or existing_text or "暂无已确认前文，本段直接按任务目标起笔。",
        "",
        "## 连续性与护栏",
        variables.get("segment_guardrail_block", ""),
        "",
        "## 字数硬约束",
        variables.get("length_requirements", ""),
        "",
        "## 格式规则",
        variables.get("format_requirements", ""),
        "",
        "## 本轮写作目标",
        task_instruction,
        "",
        "## 审段锚点",
        variables.get("segment_quality_anchors", ""),
        "",
        "## 续写铁律",
        "- 你现在是在续写下一段，不是在重写上一段。",
        "- 已确认前文中的动作、关系位置、信息差和权力位置必须继承。",
        "- 你只能从上一段的结果继续往前推，不能把上一段改写成另一场戏。",
    ]
    return "\n".join(lines)


def prepare_testing_script_generation(req: "TestingScriptRequest") -> tuple[str, str, str]:
    """把 req 装成 (system_prompt, user_prompt, anchor) 三元组。"""
    selected_ids = {str(item) for item in (req.selected_character_ids or []) if str(item).strip()}

    if req.mode == "segment":
        base_task = resolve_segment_task(
            req.segment_id or "hook",
            str(req.subgenre_track or ""),
            str(req.sample_track or ""),
        )
        intent_block = build_segment_intent_block(req)
        lockword_block = build_lockword_block(req)
        prefix_parts = [p for p in (intent_block, lockword_block) if p]
        task_instruction = ("\n\n".join(prefix_parts) + "\n\n" + base_task) if prefix_parts else base_task
    elif str(req.current_content or "").strip():
        task_instruction = (
            "紧接已有正文续写当前集，不重复前文，不回顾摘要；当前存储行是整集写作容器，"
            "可以在正文内部自然进入下一场或后续场次，把本集应完成的剧情继续写完整。"
            " 结尾必须停在可追问的具体动作、具体台词或新发现上，不能虚收。"
        )
    else:
        task_instruction = (
            "这是当前集完整初稿写作，必须优先兑现本集摘要里最强的公开冲突、羞辱、威胁或异常，"
            "从本集开场直接进入动作和对白；一集内部可以按剧情需要自然分成多场戏，"
            "但不要让前端手动场次限制内容体量。结尾必须挂住一个可继续追问的具体动作、台词或异常。"
        )
        if any(
            token in str(req.episode_summary or "")
            for token in ("发布会", "宴会", "直播", "当众", "围观", "裁员", "退婚", "追债", "羞辱", "打脸", "站队")
        ):
            task_instruction += " 如果本集摘要已经给出发布会/裁员/退婚/追债/围观等公开事件，就优先把那个公开现场写出来，而不是先写事后独处反应。"

    selected_names = [
        str(char.get("name") or "").strip()
        for char in (req.characters or [])
        if isinstance(char, dict)
        and str(char.get("id") or "") in selected_ids
        and str(char.get("name") or "").strip()
    ]

    project_type = derive_workspace_project_type(req.project_type, req.audience_axis, req.format_type)
    quality_anchor_block = build_testing_quality_anchor_block(req)
    final_generation_contract_block = format_final_generation_contract_block(req, for_writer=True)
    legacy_episode_contract_block = _legacy_episode_contract_block_for_writer(
        req,
        format_testing_episode_contract_block(req),
    )
    variables = {
        "project_type": project_type,
        "episode_count": str(req.episode_count),
        "episode_minutes": str(req.episode_minutes),
        "audience_axis": str(req.audience_axis or "").strip(),
        "genre_main": str(req.genre_main or "").strip(),
        "genre_sub": str(req.genre_sub or "").strip(),
        "subgenre_track": str(req.subgenre_track or "").strip(),
        "sample_track": str(req.sample_track or "").strip(),
        "scene_header_style": str(req.scene_header_style or "bracket").strip(),
        "constraints": (
            "工作台整集写作模式：只输出当前集正文，允许正文内部自然包含多场戏，不输出解释。"
            if req.mode == "scene"
            else "分段精写模式：只写当前分段，不输出解释。"
        ),
        "relationship_guardrails": (
            str(req.relationship_guardrails or "").strip()
            or build_relationship_guardrail_block(req.characters or [], selected_ids, req.continuity_notes)
        ),
        "state_cards_block": build_testing_state_cards_block(req.state_cards or {}, req.characters or [], selected_ids, current_episode=int(req.episode_no or 0)),
        "length_requirements": build_testing_length_rule(req),
        "format_requirements": build_testing_format_rule(req),
        "brief": task_instruction,
        "previous_episode_briefs_block": build_previous_episode_brief_block(req),
        "future_episode_briefs_block": build_future_episode_brief_block(req),
        "relationship_snapshot_block": build_relationship_diff_block(req),
        "continuity_guardrails": build_testing_continuity_guardrails(req),
        "canon_packet_block": format_testing_canon_block(req),
        "manual_edit_context_block": build_testing_manual_edit_context_block(req),
        "step_confirmation_block": build_testing_step_confirmation_block(req),
        "final_generation_contract_block": final_generation_contract_block,
        "episode_contract_block": "\n\n".join([
            final_generation_contract_block,
            "## 旧契约兜底\n" + legacy_episode_contract_block,
        ]),
        "legacy_episode_contract_block": legacy_episode_contract_block,
        "director_blueprint_block": format_director_blueprint_block(req, for_writer=True),
        "episode_memory_block": build_testing_episode_memory_block(req, limit=3),
        "material_context_block": build_testing_material_context(req),
        "issue_feedback_block": build_testing_issue_feedback_context(req),
        "rule_context_block": build_testing_rule_context(req),
        "report_context_block": build_testing_report_context(req),
        "rag_context_block": build_testing_rag_context(req, compact=req.mode == "segment"),
        "segment_focus_block": build_testing_segment_focus_block(req),
        "segment_character_block": build_testing_segment_character_mini_block(req.characters or [], selected_ids),
        "segment_confirmed_context_block": build_testing_segment_confirmed_context_block(req),
        "segment_guardrail_block": build_testing_segment_guardrail_block(req),
        "concept": build_workspace_concept_block(
            req.brief,
            req.worldview,
            req.conflict,
            req.episode_title,
            req.episode_summary,
            req.episode_conflict,
            req.episode_hook,
            req.golden_finger,
        ),
        "characters": build_workspace_character_block(req.characters or [], selected_ids),
        "scene_list": build_workspace_scene_block(
            req.episode_no,
            req.scene_no,
            req.episode_title,
            req.episode_summary,
            req.episode_conflict,
            req.episode_hook,
            selected_names,
            req.continuity_notes,
            task_instruction,
        ),
        "segment_quality_anchors": quality_anchor_block,
        "script_draft": str(req.current_content or "").strip(),
    }
    system_prompt = load_agent_prompt(SCRIPT_DRAFT_MODES["standard"])
    if req.mode == "segment":
        segment_prompt = build_segment_lite_prompt(variables, task_instruction)
        return system_prompt, segment_prompt, quality_anchor_block
    return system_prompt, _render_testing_scene_prompt(variables), quality_anchor_block


def generate_testing_scene_passed(req: "TestingScriptRequest") -> dict[str, Any]:
    """场景生成主循环（生成 → 评估 → 失败重试 → 自动修复回退）。"""
    trace_extra = director_blueprint_trace_extra(req)
    with timed_stage(req, "prepare_prompt", extra=trace_extra):
        system_prompt, base_user_prompt, quality_anchor_block = prepare_testing_script_generation(req)
    prompt_for_attempt = base_user_prompt
    best_candidate: Optional[dict[str, Any]] = None
    # 真实前端链路外层已经有 validate / auto-fix 闭环，这里保留必要兜底即可，
    # 避免长模型在同一轮里做过多内部重试，拖慢整段生成体验。
    attempt_count = 2 if req.mode == "segment" else 3
    max_tokens = 2200
    if req.mode == "segment":
        seg_max_chars = int(
            req.word_count_max
            or {"hook": 280, "validation": 330, "explosion": 380, "resolution": 310}.get(
                str(req.segment_id or "hook"), 330
            )
        )
        max_tokens = min(1100, max(420, int(seg_max_chars * 1.5) + 80))
    elif req.word_count_max:
        max_tokens = min(2600, max(800, int(int(req.word_count_max) * 1.5) + 200))

    contract = current_testing_final_generation_contract(req)
    base_temperature = req.temperature if req.temperature is not None else 0.3
    writer_req, _ = apply_testing_generation_route(req, "script_draft", base_temperature)
    reviewer_req, _ = apply_testing_generation_route(req, "quality_check", 0.1)
    writer_req = _with_stage_budget(writer_req, timeout_seconds=SCENE_WRITER_TIMEOUT_SECONDS)
    reviewer_req = _with_stage_budget(reviewer_req, timeout_seconds=SCENE_REVIEW_TIMEOUT_SECONDS)

    for attempt in range(attempt_count):
        attempt_no = attempt + 1
        try:
            with timed_stage(
                writer_req,
                "writer_generate",
                attempt=attempt_no,
                extra={**trace_extra, "timeout_seconds": SCENE_WRITER_TIMEOUT_SECONDS, "max_tokens": max_tokens},
            ):
                content = generate_text(
                    system_prompt,
                    prompt_for_attempt,
                    **generation_kwargs_from_req(writer_req),
                    temperature=writer_req.temperature if writer_req.temperature is not None else base_temperature,
                    max_tokens=max_tokens,
                )
        except Exception as exc:
            if best_candidate:
                best_candidate = _append_late_error_warning(best_candidate, exc, stage="写手重写")
                record_stage_trace(
                    req,
                    "scene_generation",
                    "error",
                    attempt=attempt_no,
                    extra={
                        **trace_extra,
                        "char_count": int(best_candidate.get("char_count_excluding_punctuation") or 0),
                        "blocking_count": len(best_candidate.get("blocking_issues") or []),
                        "first_blocking": str((best_candidate.get("blocking_issues") or [""])[0])[:120],
                        "error": f"{type(exc).__name__}: {str(exc)[:180]}",
                    },
                )
                break
            raise
        with timed_stage(req, "hard_repairs", attempt=attempt_no):
            content_text = apply_testing_hard_repairs(req, str(content or "").strip())
        if req.mode == "segment" and req.word_count_max:
            content_text = hard_truncate_by_sentence(content_text, int(req.word_count_max), exclude_punct=bool(req.exclude_punctuation_for_count))
        with timed_stage(reviewer_req, "local_evaluate", attempt=attempt_no):
            evaluation = evaluate_testing_scene(reviewer_req, content_text, quality_anchor_block)
        with timed_stage(reviewer_req, "deep_gate", attempt=attempt_no):
            evaluation = apply_scene_level_gate(reviewer_req, evaluation, contract)
        evaluation = promote_scene_word_count_warnings(req, evaluation)
        record_stage_trace(
            req,
            "gate_result",
            "end",
            attempt=attempt_no,
            extra={
                **trace_extra,
                "char_count": int(evaluation.get("char_count_excluding_punctuation") or 0),
                "blocking_count": len(evaluation.get("blocking_issues") or []),
                "quality_issue_count": len(evaluation.get("quality_issues") or []),
                "warning_count": len(evaluation.get("warnings") or []),
                "quality_passed": bool(evaluation.get("quality_passed")),
                "first_blocking": str((evaluation.get("blocking_issues") or [""])[0])[:120],
                "blocking_preview": "；".join(str(item)[:80] for item in (evaluation.get("blocking_issues") or [])[:3]),
            },
        )
        if best_candidate is None or evaluation_score(evaluation) < evaluation_score(best_candidate):
            best_candidate = evaluation

        if not evaluation["blocking_issues"] and evaluation["quality_passed"]:
            record_stage_trace(
                req,
                "scene_generation",
                "end",
                attempt=attempt_no,
                extra={
                    **trace_extra,
                    "char_count": int(evaluation.get("char_count_excluding_punctuation") or 0),
                    "blocking_count": len(evaluation.get("blocking_issues") or []),
                    "warning_count": len(evaluation.get("warnings") or []),
                },
            )
            return evaluation

        if evaluation["blocking_issues"]:
            if _word_count_issue_is_minor(req, evaluation):
                return _release_minor_word_count_issue(req, evaluation)
            try:
                completed_eval = _complete_scene_length_shortfall(
                    req=req,
                    writer_req=writer_req,
                    reviewer_req=reviewer_req,
                    original_content=content_text,
                    evaluation=evaluation,
                    quality_anchor_block=quality_anchor_block,
                    contract=contract,
                )
            except Exception as exc:
                completed_eval = None
                evaluation["warnings"] = list(dict.fromkeys([
                    *(evaluation.get("warnings") or []),
                    f"定向补写未完成，转入完整修复：{str(exc)[:80]}",
                ]))[:8]
            if completed_eval is not None:
                if evaluation_score(completed_eval) < evaluation_score(best_candidate):
                    best_candidate = completed_eval
                if not completed_eval["blocking_issues"] and completed_eval["quality_passed"]:
                    return completed_eval
            trimmed_eval = _trim_scene_overflow(
                req=req,
                reviewer_req=reviewer_req,
                evaluation=evaluation,
                quality_anchor_block=quality_anchor_block,
                contract=contract,
            )
            if trimmed_eval is not None:
                if evaluation_score(trimmed_eval) < evaluation_score(best_candidate):
                    best_candidate = trimmed_eval
                if not trimmed_eval["blocking_issues"] and trimmed_eval["quality_passed"]:
                    return trimmed_eval
            autofix_payload = _with_stage_budget(
                writer_req,
                timeout_seconds=SCENE_AUTOFIX_TIMEOUT_SECONDS,
            ).model_dump()
            autofix_payload.update({
                "autofix_single_pass": True,
                "scene_content": content_text,
            })
            try:
                with timed_stage(
                    writer_req,
                    "autofix_total",
                    attempt=attempt_no,
                    extra={**trace_extra, "timeout_seconds": SCENE_AUTOFIX_TIMEOUT_SECONDS},
                ):
                    fixed = auto_fix_testing_script_content(
                        TestingScriptValidationRequest(**autofix_payload),
                        content_text,
                    )
            except Exception as exc:
                if best_candidate:
                    best_candidate = _append_late_error_warning(best_candidate, exc, stage="自动修复")
                    record_stage_trace(
                        req,
                        "scene_generation",
                        "error",
                        attempt=attempt_no,
                        extra={
                            **trace_extra,
                            "char_count": int(best_candidate.get("char_count_excluding_punctuation") or 0),
                            "blocking_count": len(best_candidate.get("blocking_issues") or []),
                            "first_blocking": str((best_candidate.get("blocking_issues") or [""])[0])[:120],
                            "error": f"{type(exc).__name__}: {str(exc)[:180]}",
                        },
                    )
                    break
                raise
            with timed_stage(reviewer_req, "autofix_final_local_evaluate", attempt=attempt_no):
                fixed_eval = evaluate_testing_scene(reviewer_req, fixed.content, quality_anchor_block)
            with timed_stage(reviewer_req, "autofix_final_deep_gate", attempt=attempt_no):
                fixed_eval = apply_scene_level_gate(reviewer_req, fixed_eval, contract)
            fixed_eval = promote_scene_word_count_warnings(req, fixed_eval)
            if fixed.overflow_content:
                fixed_eval["overflow_content"] = fixed.overflow_content
                fixed_eval.setdefault("warnings", []).append("有部分内容已作为下一集顺延建议返回，请人工确认后再使用。")
            if evaluation_score(fixed_eval) < evaluation_score(best_candidate):
                best_candidate = fixed_eval
            if not fixed_eval["blocking_issues"] and fixed_eval["quality_passed"]:
                record_stage_trace(
                    req,
                    "scene_generation",
                    "end",
                    attempt=attempt_no,
                    extra={
                        **trace_extra,
                        "char_count": int(fixed_eval.get("char_count_excluding_punctuation") or 0),
                        "blocking_count": len(fixed_eval.get("blocking_issues") or []),
                        "warning_count": len(fixed_eval.get("warnings") or []),
                    },
                )
                return fixed_eval
            prompt_for_attempt = build_internal_rewrite_prompt(
                base_user_prompt,
                fixed_eval,
                previous_content=fixed_eval["content"],
            )
            continue

        prompt_for_attempt = build_internal_rewrite_prompt(
            base_user_prompt,
            evaluation,
            previous_content=evaluation["content"],
        )

    if best_candidate and not best_candidate["blocking_issues"] and best_candidate["quality_passed"]:
        return best_candidate

    if best_candidate and _word_count_issue_is_minor(req, best_candidate):
        return _release_minor_word_count_issue(req, best_candidate)

    # 回退路径：所有尝试均通过硬阻断检查但软审段未过，视为"带提醒通过"。
    if best_candidate and not best_candidate.get("blocking_issues"):
        soft_msgs = [f"审段提醒：{item}" for item in (best_candidate.get("quality_issues") or [])]
        merged_warnings = list(dict.fromkeys([*(best_candidate.get("warnings") or []), *soft_msgs]))[:8]
        best_candidate["warnings"] = merged_warnings
        best_candidate["quality_passed"] = True
        return best_candidate

    if best_candidate and (best_candidate.get("blocking_issues") or not best_candidate.get("quality_passed")):
        log_testing_failure_analysis(req, best_candidate.get("failure_analysis") or TestingFailureAnalysis(), best_candidate)
        try:
            import json as _json
            from pathlib import Path as _Path
            _dbg = _Path("/tmp/moxi_last_failure.json")
            _serializable = {
                "content": best_candidate.get("content"),
                "blocking_issues": best_candidate.get("blocking_issues"),
                "quality_issues": best_candidate.get("quality_issues"),
                "quality_passed": best_candidate.get("quality_passed"),
                "warnings": best_candidate.get("warnings"),
                "char_count_excluding_punctuation": best_candidate.get("char_count_excluding_punctuation"),
            }
            _dbg.write_text(_json.dumps(_serializable, ensure_ascii=False, indent=2))
        except Exception:
            pass
    raise TestingSceneQualityGateError(req, best_candidate or {})
