"""测试页"逐集深度审计 + 生成参数透传"工具（从 short_drama_writing.py 抽出）。

核心：把 LLM 调用的"系统统筹审段"包装成 BenchmarkAssessment + ContinuityAssessment 二元组。

- generation_kwargs_from_req：从 TestingScriptRequest 拎出 provider/model 透传给 generate_json
- generation_kwargs_from_metadata：从 metadata.project 拎出 provider/model 透传给 generate_json（写作工作流用）
- run_testing_deep_audit：核心深审，命中缓存直接返回，未命中走 LLM；任何异常 fallback 到回退评估

contract 由调用方传入，避免与主 router 形成循环依赖。
"""
from __future__ import annotations

import re
from typing import Any, TYPE_CHECKING

from app.schemas.short_drama_writing import BenchmarkAssessment, ContinuityAssessment
from app.services.short_drama_quality_helpers import project_config_value
from app.services.short_drama_benchmark_assessment import (
    apply_testing_benchmark_caps,
    fallback_benchmark_assessment,
)
from app.services.short_drama_quality_anchors import infer_testing_sample_track
from app.services.scoring_calibration import calibrate_value
from app.services.short_drama_seam_continuity import (
    DEEP_AUDIT_CACHE,
    DEEP_AUDIT_CACHE_MAX,
    apply_testing_seam_gate_to_continuity,
    deep_audit_fingerprint,
    fallback_continuity_assessment,
)
from app.services.short_drama_testing_blocks import (
    build_previous_episode_brief_block,
    build_relationship_diff_block,
    string_list,
)
from app.services.text_generation_service import generate_json

if TYPE_CHECKING:
    from app.schemas.short_drama_writing import TestingScriptRequest


def _append_unique(items: list[str], value: str, limit: int = 4) -> list[str]:
    cleaned = [str(item or "").strip() for item in items if str(item or "").strip()]
    value = str(value or "").strip()
    if value:
        cleaned.append(value)
    return list(dict.fromkeys(cleaned))[:limit]


def _calibrated_score(field: str, score: int) -> int:
    return int(round(calibrate_value(field, float(score or 0), mode="mean")))


def _drop_negated_continuity_risk_clauses(text: str) -> str:
    """Remove clauses that explicitly deny spoiler/drift/break risks."""
    risk_terms = (
        "断裂", "漂移", "剧透", "跳档", "未承接",
    )
    specific_negated_markers = (
        "无剧透", "未剧透", "不存在剧透", "无后续集可剧透",
        "无漂移", "未漂移", "不存在关系漂移", "未出现关系漂移",
    )
    negated_prefixes = (
        "无", "不存在", "未发现", "未检测到", "没有发现", "没有检测到",
        "未出现", "没有出现", "并未出现", "未见", "未构成", "没有构成",
    )
    clauses = re.split(r"([。；;！？!?\n])", str(text or ""))
    kept: list[str] = []
    for idx in range(0, len(clauses), 2):
        clause = clauses[idx]
        delimiter = clauses[idx + 1] if idx + 1 < len(clauses) else ""
        if any(marker in clause for marker in specific_negated_markers) and not any(
            hard_marker in clause for hard_marker in ("未承接", "断裂", "跳档")
        ):
            continue
        if any(prefix in clause for prefix in negated_prefixes) and any(term in clause for term in risk_terms):
            continue
        kept.append(clause + delimiter)
    return "".join(kept)


def apply_testing_deep_audit_calibration(
    benchmark: BenchmarkAssessment,
    continuity: ContinuityAssessment,
) -> tuple[BenchmarkAssessment, ContinuityAssessment]:
    """把内测人评分数校准接进真实测试页深审。

    这一步只做本地数学修正，不增加模型调用。校准结果记录为 human_projection_score，
    用来提示人评分风险；不覆盖模型原始深审分，避免统计投影把 90 分目标变成不可达。
    """
    raw_benchmark_score = int(benchmark.score or 0)
    calibrated_benchmark_score = _calibrated_score("benchmark_total", raw_benchmark_score)
    benchmark.raw_score = raw_benchmark_score
    benchmark.human_projection_score = calibrated_benchmark_score
    benchmark.human_projection_passed = calibrated_benchmark_score >= 70
    if calibrated_benchmark_score != raw_benchmark_score:
        benchmark.calibration_note = (
            f"按内测人评标准做风险投影：{raw_benchmark_score}→{calibrated_benchmark_score}"
        )
    if raw_benchmark_score < 85:
        benchmark.passed = False
        benchmark.gaps = _append_unique(
            benchmark.gaps,
            "模型原始深审分未达通过线，当前对标质感不足。",
        )
    elif calibrated_benchmark_score < 85:
        benchmark.gaps = _append_unique(
            benchmark.gaps,
            "人工锚点投影偏低，作为风险提示记录；不作为硬阻断。",
        )

    raw_continuity_score = int(continuity.score or 0)
    risk_summary = _drop_negated_continuity_risk_clauses(str(continuity.summary or ""))
    calibrated_continuity_score = _calibrated_score("continuity_total", raw_continuity_score)
    continuity.raw_score = raw_continuity_score
    continuity.human_projection_score = calibrated_continuity_score
    continuity.human_projection_passed = calibrated_continuity_score >= 70
    if calibrated_continuity_score != raw_continuity_score:
        continuity.calibration_note = (
            f"按内测人评标准做风险投影：{raw_continuity_score}→{calibrated_continuity_score}"
        )
    if raw_continuity_score < 85:
        continuity.passed = False
        continuity.calibration_only_failure = False
        continuity.plot_risks = _append_unique(
            continuity.plot_risks,
            "模型原始连续性深审分未达通过线。",
        )
    elif calibrated_continuity_score < 85:
        continuity.plot_risks = _append_unique(
            continuity.plot_risks,
            "人工锚点投影偏低，作为风险提示记录；不作为硬阻断。",
        )
    if continuity.passed is False and not (
        continuity.relationship_risks
        or continuity.plot_risks
        or any(marker in risk_summary for marker in ("断裂", "漂移", "剧透", "跳档", "未承接"))
    ):
        continuity.calibration_only_failure = True
    return benchmark, continuity


def generation_kwargs_from_req(req: "TestingScriptRequest") -> dict[str, Any]:
    """从 TestingScriptRequest 拎出模型路由与阶段预算透传给 LLM 调用。"""
    kwargs: dict[str, Any] = {}
    provider = str(getattr(req, "generation_provider", "") or "").strip()
    model = str(getattr(req, "generation_model", "") or "").strip()
    if provider:
        kwargs["provider"] = provider
    if model:
        kwargs["model"] = model
    timeout_seconds = getattr(req, "generation_timeout_seconds", None)
    if timeout_seconds:
        kwargs["timeout_seconds"] = int(timeout_seconds)
    max_retries = getattr(req, "generation_max_retries", None)
    if max_retries:
        kwargs["max_retries"] = int(max_retries)
    return kwargs


def generation_kwargs_from_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    """从 metadata.project 拎出 provider/model 透传给 LLM 调用。"""
    kwargs: dict[str, Any] = {}
    project = metadata.get("project") or {}
    if not isinstance(project, dict):
        return kwargs

    provider = str(project_config_value(project, "generation_provider") or "").strip()
    model = str(project_config_value(project, "generation_model") or "").strip()
    if provider:
        kwargs["provider"] = provider
    if model:
        kwargs["model"] = model
    return kwargs


def run_testing_deep_audit(
    req: "TestingScriptRequest",
    evaluation: dict[str, Any],
    contract: dict[str, Any] | None = None,
) -> tuple[BenchmarkAssessment, ContinuityAssessment]:
    """核心深审：命中缓存直接返回；未命中走 LLM；任何异常 fallback。"""
    track_name, _ = infer_testing_sample_track(req)
    episode_text = str(req.episode_content or evaluation.get("content") or "").strip()
    if not episode_text:
        return (
            fallback_benchmark_assessment(req, evaluation, contract),
            fallback_continuity_assessment(req, evaluation),
        )

    fp = deep_audit_fingerprint(req, episode_text)
    cached = DEEP_AUDIT_CACHE.get(fp)
    if cached is not None:
        DEEP_AUDIT_CACHE.move_to_end(fp)
        return cached

    system_prompt = (
        "你是头部短剧总编兼系列统筹。"
        "请只输出一个 JSON 对象，结构为 benchmark 与 continuity 两部分。"
        "benchmark 评估当前集是否真正对标头部短剧质感；continuity 评估当前集与前序最多10集的角色关系、剧情推进是否漂移，并明确判定是否提前消耗了未来集情节点（剧透）。"
        "分数使用 0-100，85 分以上才算通过；一旦发现剧透，continuity.passed 必须为 false。"
        "头部短剧硬标准：上一集尾部和本集开头必须直接接续；现实题材OS稀疏且不能收尾；开场3-5秒必须有冲突压力；结尾必须停在可拍动作/物件/证据。"
        "若本集开头没有承接上一集最后动作/物件/站位，continuity.score 最高40且 passed=false。"
        "禁止输出解释、禁止 markdown、禁止多余字段。"
    )

    future_brief_lines: list[str] = []
    for item in (req.future_episode_briefs or [])[:5]:
        if not isinstance(item, dict):
            continue
        ep = item.get("episode_no") or item.get("ep") or ""
        title = str(item.get("title") or "").strip()
        summary = str(item.get("summary") or "").strip()
        if summary:
            future_brief_lines.append(f"第{ep}集 {title}｜摘要：{summary[:120]}")
    future_brief_block = "\n".join(future_brief_lines) if future_brief_lines else "暂无后续集摘要。"
    user_prompt = (
        f"项目：{req.series_title or '未命名项目'}\n"
        f"当前对标赛道：{track_name}\n"
        f"当前集：第{req.episode_no}集\n"
        f"当前集标题：{req.episode_title}\n"
        f"当前集摘要：{req.episode_summary}\n"
        f"当前集冲突：{req.episode_conflict}\n"
        f"当前集钩子：{req.episode_hook}\n\n"
        "【关系护栏】\n"
        f"{req.relationship_guardrails or '无'}\n\n"
        "【前序9集内摘要】\n"
        f"{build_previous_episode_brief_block(req)}\n\n"
        "【首尾接续硬判】\n"
        "请重点比对上一集最后3行/未收钩子与当前集前5行：若不是同一动作、同一物件、同一压力继续推进，必须判连续性不通过。\n\n"
        "【后续集摘要（仅用于剧透检测，禁止把后续事件写进本集）】\n"
        f"{future_brief_block}\n\n"
        "【关系图 diff（前次快照→本集结束）】\n"
        f"{build_relationship_diff_block(req)}\n\n"
        "【RAG 知识库头部剧本/质检对标基线】\n"
        f"{str(req.rag_review_references or req.rag_script_references or '未检索到 RAG 对标文本。')[:2600]}\n\n"
        "判定加项：若 diff 出现强度跃升≥20、类型漂移、或核心关系突然新增/消失，但当前集正文里看不到对应的可拍动作/台词/后果，"
        "则 continuity.passed=false 并把对应关系写进 relationship_risks。\n"
        "【当前集正文】\n"
        f"{episode_text[:3200]}\n\n"
        "判定规则：若当前集正文出现明显属于'后续集摘要'里的核心事件/物件/地点/金额/对白（即剧透），"
        "则 continuity.spoiler_detected=true 且 continuity.passed=false，并把具体剧透点写进 plot_risks。"
        "输出 JSON：\n"
        "{\n"
        '  "benchmark": {\n'
        '    "score": 0,\n'
        '    "passed": true,\n'
        '    "summary": "",\n'
        '    "matched_signals": ["最多3条"],\n'
        '    "gaps": ["最多3条"],\n'
        '    "rule_upgrades": ["若发现应沉淀进项目规则层的规则，最多3条"]\n'
        "  },\n"
        '  "continuity": {\n'
        '    "checked_episode_span": "",\n'
        '    "score": 0,\n'
        '    "passed": true,\n'
        '    "summary": "",\n'
        '    "preserved_anchors": ["最多3条"],\n'
        '    "relationship_risks": ["最多3条"],\n'
        '    "plot_risks": ["最多3条"]\n'
        "  }\n"
        "}"
    )

    try:
        payload = generate_json(
            system_prompt,
            user_prompt,
            temperature=0.15,
            max_tokens=900,
            **generation_kwargs_from_req(req),
        )
        benchmark_raw = payload.get("benchmark") if isinstance(payload, dict) and isinstance(payload.get("benchmark"), dict) else {}
        continuity_raw = payload.get("continuity") if isinstance(payload, dict) and isinstance(payload.get("continuity"), dict) else {}
        benchmark = BenchmarkAssessment(
            track_name=track_name,
            score=int(benchmark_raw.get("score") or 0),
            passed=bool(benchmark_raw.get("passed")),
            summary=str(benchmark_raw.get("summary") or "").strip(),
            matched_signals=string_list(benchmark_raw.get("matched_signals")),
            gaps=string_list(benchmark_raw.get("gaps")),
            rule_upgrades=string_list(benchmark_raw.get("rule_upgrades")),
        )
        continuity = ContinuityAssessment(
            checked_episode_span=str(continuity_raw.get("checked_episode_span") or "").strip(),
            score=int(continuity_raw.get("score") or 0),
            passed=bool(continuity_raw.get("passed")),
            summary=str(continuity_raw.get("summary") or "").strip(),
            preserved_anchors=string_list(continuity_raw.get("preserved_anchors")),
            relationship_risks=string_list(continuity_raw.get("relationship_risks")),
            plot_risks=string_list(continuity_raw.get("plot_risks")),
        )
        if not benchmark.track_name:
            benchmark.track_name = track_name
        if not continuity.checked_episode_span:
            continuity.checked_episode_span = fallback_continuity_assessment(req, evaluation).checked_episode_span
        benchmark = apply_testing_benchmark_caps(req, benchmark, evaluation, episode_text, contract)
        continuity = apply_testing_seam_gate_to_continuity(req, continuity, episode_text)
        benchmark, continuity = apply_testing_deep_audit_calibration(benchmark, continuity)
        DEEP_AUDIT_CACHE[fp] = (benchmark, continuity)
        if len(DEEP_AUDIT_CACHE) > DEEP_AUDIT_CACHE_MAX:
            DEEP_AUDIT_CACHE.popitem(last=False)
        return benchmark, continuity
    except Exception:
        return (
            fallback_benchmark_assessment(req, evaluation, contract),
            fallback_continuity_assessment(req, evaluation),
        )
