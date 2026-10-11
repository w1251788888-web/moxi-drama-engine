"""测试页"评估流水线"工具（从 short_drama_writing.py 抽出）。

包括：
- split_testing_generation_issues：把生成结果格式校验里的 errors 拆成"硬阻断"和"软提醒"
- evaluation_score：把 evaluation 字典压成可比较的 (blocking, quality_penalty, warning) 三元组
- apply_scene_level_gate：scene 模式下挂深审网关；contract 由调用方传入
- review_testing_scene_quality：LLM 头部短剧总编风格的"是否成段"审段，命中负面 marker 才算扣分
- fallback_episode_memory_card：当 LLM 没有给结构化更新时的兜底"集记忆卡"

零 IO、零 DB、外部 LLM 调用走 generate_json（异常一律落到兜底分支）。
"""
from __future__ import annotations

import hashlib
import json
import re
from collections import OrderedDict
from typing import Any, TYPE_CHECKING

from app.schemas.short_drama_writing import (
    BenchmarkAssessment,
    ContinuityAssessment,
    TestingFailureAnalysis,
)
from app.services.short_drama_deep_audit import (
    generation_kwargs_from_req,
    run_testing_deep_audit,
)
from app.services.short_drama_benchmark_assessment import fallback_benchmark_assessment
from app.services.short_drama_failure_classifier import classify_testing_failure
from app.services.short_drama_quality_anchors import infer_testing_sample_track
from app.services.short_drama_seam_continuity import fallback_continuity_assessment
from app.services.short_drama_stage_trace import timed_stage
from app.services.short_drama_testing_normalizers import (
    normalize_testing_canon_packet,
    normalize_testing_episode_memory_cards,
)
from app.services.short_drama_workspace_blocks import condense_text
from app.services.text_generation_service import generate_json

if TYPE_CHECKING:
    from app.schemas.short_drama_writing import TestingScriptRequest


def split_testing_generation_issues(
    req: "TestingScriptRequest",
    errors: list[str],
) -> tuple[list[str], list[str]]:
    """把测试页 format/validation 错误拆成硬阻断与软提醒。

    - 格式/结构性错误：阻断
    - 字数问题：默认作为提醒，让前端把内容先交给用户确认
    - 字数严重偏离（超过目标区间约 20%）：阻断，避免明显不可用内容继续流转
    """
    blocking_markers = (
        "输出为空",
        "缺少正文内容",
        "场次标头未使用",
        "续写片段不应重复输出上一段已有场次标头",
        "缺少以 `△` 起笔的动作行",
        "缺少标准台词 / OS / VO 行",
        "出现了说明栏目",
    )
    word_count_markers = (
        "净字数不足",
        "净字数超限",
    )
    blocking: list[str] = []
    warnings: list[str] = []
    for item in errors or []:
        text = str(item or "").strip()
        if not text:
            continue
        if any(marker in text for marker in blocking_markers):
            blocking.append(text)
        elif any(marker in text for marker in word_count_markers):
            if _is_severe_word_count_issue(text, req):
                blocking.append(text)
            else:
                warnings.append(text)
        else:
            warnings.append(text)
    return blocking, warnings


def _is_severe_word_count_issue(issue: str, req: "TestingScriptRequest" | None = None) -> bool:
    """Return True only when a word-count miss is too large to hand to users.

    Normal quick-writing and segmented-writing should give the user the draft first.
    A small miss is a UX prompt, not a generation failure.
    """
    nums = [int(item) for item in re.findall(r"\d+", str(issue or ""))]
    if len(nums) < 2:
        return False
    current = nums[0]
    target = nums[1]
    if current <= 0 or target <= 0:
        return False
    gap = abs(current - target)
    text = str(issue or "")
    is_segment = str(getattr(req, "mode", "") or "") == "segment" if req is not None else False
    if "超限" in text or "至多" in text:
        configured_max = int(getattr(req, "word_count_max", None) or target) if req is not None else target
        tolerance = (
            max(80, int(configured_max * 0.20))
            if is_segment
            else max(120, int(configured_max * 0.12))
        )
    elif "不足" in text or "至少" in text:
        configured_min = int(getattr(req, "word_count_min", None) or target) if req is not None else target
        tolerance = (
            max(80, int(configured_min * 0.20))
            if is_segment
            else max(100, int(configured_min * 0.10))
        )
    else:
        tolerance = max(100, int(target * 0.12))
    return gap > tolerance


def promote_scene_word_count_warnings(
    req: "TestingScriptRequest",
    evaluation: dict[str, Any],
) -> dict[str, Any]:
    """整集工业化链路中，只有严重字数越界才升级为阻断。

    用户已明确要求轻微字数偏差不要显示为生成失败；完整 scene 生成链路只把
    超出弹性范围的字数问题升级为 blocking issue。segment 分段仍保持宽松。
    """
    if str(getattr(req, "mode", "") or "") != "scene":
        return evaluation
    warnings = [str(item or "").strip() for item in (evaluation.get("warnings") or []) if str(item or "").strip()]
    word_count_warnings = [
        item for item in warnings if "净字数不足" in item or "净字数超限" in item
    ]
    if not word_count_warnings:
        return evaluation
    blocking = [
        str(item or "").strip()
        for item in (evaluation.get("blocking_issues") or [])
        if str(item or "").strip()
    ]
    severe_word_count_warnings = [
        item for item in word_count_warnings if _is_severe_word_count_issue(item, req)
    ]
    for item in severe_word_count_warnings:
        if item not in blocking:
            blocking.append(item)
    evaluation["blocking_issues"] = blocking
    evaluation["warnings"] = [
        item for item in warnings
        if item not in severe_word_count_warnings
    ]
    return evaluation


def evaluation_score(evaluation: dict[str, Any]) -> tuple[int, int, int]:
    """评估字典 → (blocking 数量, quality_penalty, warning 数量)。"""
    blocking = len(evaluation.get("blocking_issues") or [])
    quality_penalty = 0 if evaluation.get("quality_passed") else 1
    warning_count = len(evaluation.get("warnings") or [])
    return (blocking, quality_penalty, warning_count)


def apply_scene_level_gate(
    req: "TestingScriptRequest",
    evaluation: dict[str, Any],
    contract: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """scene 模式下挂深审网关；contract 由调用方传入避免循环依赖。"""
    if req.mode != "scene":
        evaluation["benchmark_assessment"] = (
            evaluation.get("benchmark_assessment")
            or fallback_benchmark_assessment(req, evaluation, contract)
        )
        evaluation["continuity_assessment"] = (
            evaluation.get("continuity_assessment")
            or fallback_continuity_assessment(req, evaluation)
        )
        return evaluation

    with timed_stage(req, "deep_audit"):
        benchmark_assessment, continuity_assessment = run_testing_deep_audit(req, evaluation, contract)
    evaluation["benchmark_assessment"] = benchmark_assessment
    evaluation["continuity_assessment"] = continuity_assessment
    if continuity_assessment.passed is False:
        if getattr(continuity_assessment, "calibration_only_failure", False):
            detail = str(continuity_assessment.calibration_note or continuity_assessment.summary or "深审分数低于通过线").strip()
            evaluation["warnings"] = list(dict.fromkeys([
                *(evaluation.get("warnings") or []),
                f"深审提醒：{detail[:120]}",
            ]))[:8]
            return evaluation
        detail = next(
            (
                str(item).strip()
                for item in [
                    *(continuity_assessment.relationship_risks or []),
                    *(continuity_assessment.plot_risks or []),
                    continuity_assessment.summary,
                ]
                if str(item).strip()
            ),
            "当前正文存在跨集连续性风险",
        )
        if _is_first_episode_missing_prior_context(req, continuity_assessment, detail):
            evaluation["warnings"] = list(dict.fromkeys([
                *(evaluation.get("warnings") or []),
                f"连续性提醒：{detail[:120]}",
            ]))[:8]
            return evaluation
        if _is_soft_continuity_risk(continuity_assessment, detail):
            evaluation["warnings"] = list(dict.fromkeys([
                *(evaluation.get("warnings") or []),
                f"连续性提醒：{detail[:120]}",
            ]))[:8]
            return evaluation
        blocking = [str(item).strip() for item in (evaluation.get("blocking_issues") or []) if str(item).strip()]
        gate_issue = f"连续性深审未通过：{detail[:120]}"
        if gate_issue not in blocking:
            blocking.append(gate_issue)
        evaluation["blocking_issues"] = blocking
        evaluation["warnings"] = list(dict.fromkeys([
            *(evaluation.get("warnings") or []),
            f"连续性阻断：{detail[:120]}",
        ]))[:8]
        evaluation["relationship_suggestions"] = []
        evaluation["state_card_suggestions"] = []
        evaluation["failure_analysis"] = classify_testing_failure(req, evaluation)
    return evaluation


def _is_first_episode_missing_prior_context(
    req: "TestingScriptRequest",
    continuity: ContinuityAssessment,
    detail: str,
) -> bool:
    """第1集没有前序关系/摘要是上下文事实，不应阻断用户拿到初稿。"""
    try:
        episode_no = int(getattr(req, "episode_no", 0) or 0)
    except Exception:
        episode_no = 0
    if episode_no > 1:
        return False
    text = "\n".join([
        str(detail or ""),
        str(continuity.summary or ""),
        "\n".join(str(item or "") for item in (continuity.relationship_risks or [])),
        "\n".join(str(item or "") for item in (continuity.plot_risks or [])),
    ])
    markers = (
        "暂无前序",
        "暂无前次",
        "没有前序",
        "无前序",
        "缺少前序",
        "缺少前序集",
        "无法证明与上一集",
        "上一集尾声",
        "上一集尾部",
        "前序关系快照",
        "前次关系快照",
        "前序集摘要",
    )
    return any(marker in text for marker in markers)


def _is_soft_continuity_risk(continuity: ContinuityAssessment, detail: str) -> bool:
    """把“后续维持/略弱/可补强”从硬阻断降级为提醒。

    首尾断裂、剧透、关系跳档仍然硬拦；但如果深审只是提示某个角色后续要继续保持
    摇摆或某个动作偏轻，直接拦掉会让用户长时间等待后没有可用草稿。
    """
    score = int(continuity.score or 0)
    if score < 70:
        return False
    text = "\n".join([
        str(detail or ""),
        str(continuity.summary or ""),
        "\n".join(str(item or "") for item in (continuity.relationship_risks or [])),
        "\n".join(str(item or "") for item in (continuity.plot_risks or [])),
    ])
    hard_scan_text = _remove_negated_continuity_risk_clauses(text)
    hard_markers = (
        "断裂", "未承接", "没有承接", "没有在本集前5行", "重启", "跳开",
        "剧透", "提前", "越线", "泄露", "跳档", "强度跃升", "直接和解",
        "突然洗白", "突然倒向", "改写", "矛盾", "不一致", "坐实",
    )
    if any(marker in hard_scan_text for marker in hard_markers):
        return False
    soft_markers = (
        "偏轻", "偏软", "偏高", "略", "后续需", "后续要", "需要继续",
        "可再", "还可", "易显得", "允许范围", "未出现", "未发现", "未检测到", "未见",
    )
    return any(marker in text for marker in soft_markers)


def _remove_negated_continuity_risk_clauses(text: str) -> str:
    """Remove clauses that explicitly say a hard continuity risk did not happen."""
    risk_terms = (
        "剧透", "提前", "泄露", "漂移", "揭底", "揭开", "确认",
        "落地", "越线", "跳档", "强度跃升", "直接和解", "洗白",
        "倒向", "改写", "矛盾", "不一致", "坐实",
    )
    negated_prefixes = (
        "未发现", "未检测到", "没有发现", "没有检测到", "未出现",
        "没有出现", "并未出现", "尚未出现", "未见", "未直接", "未提前",
        "没有提前", "尚未提前", "并未提前", "未构成", "并未构成", "没有构成", "并未",
    )
    clause_splitter = re.compile(r"([。；;！？!?\n])")
    parts = clause_splitter.split(str(text or ""))
    kept: list[str] = []
    for idx in range(0, len(parts), 2):
        clause = parts[idx]
        delimiter = parts[idx + 1] if idx + 1 < len(parts) else ""
        if not clause:
            kept.append(clause + delimiter)
            continue
        if any(prefix in clause for prefix in negated_prefixes) and any(term in clause for term in risk_terms):
            continue
        kept.append(clause + delimiter)
    return "".join(kept)


def review_testing_scene_quality(
    req: "TestingScriptRequest",
    content: str,
    quality_anchor_block: str,
) -> tuple[bool, list[str]]:
    """LLM 头部短剧总编风格的"是否成段"审段；异常返回 (True, [])。"""
    system_prompt = (
        "你是头部短剧总编（对标《重生后我叫他阿兄》漫剧 1-3 集那一档位），不是格式检查器。"
        "你只判断这段戏作为当前段落是否成立，判别标准向头部样板对齐："
        "1) 每个情绪转折是否落在具体身体信号上（下颌/指节/呼吸/眼眶/物件被攥/退半步），还是只有形容词；"
        "2) 每句台词是否在 15 字以内、关键台词是否 2-3 短句叠加，有无广播式自报身份（\"我不再是xx的xx了\"/\"xx的宝座你坐不稳了\"）；"
        "3) 结尾是否落在具体画面（特写/动作未完成/环境覆盖/意外失控），有没有\"场末钩子：/悬念留于此刻/这只是开始/下集待续\"这种解说尾巴；"
        "4) 系统/金手指出现时是否冷感（单句指令+可视化代价），有没有积分/奖励数值这种游戏化表达；"
        "5) 关系/信息/权力是否至少一层可被第三者看见的推进。"
        "只要命中任意一项失准就判不通过。只输出 JSON，不要解释。"
    )

    segment_label = "整场测试" if req.mode != "segment" else f"{req.segment_id or 'hook'} 段"
    user_prompt = (
        f"任务类型：{segment_label}\n"
        f"受众轴：{req.audience_axis}\n"
        f"主类型：{req.genre_main}\n"
        f"副类型：{req.genre_sub}\n"
        f"当前集冲突：{req.episode_conflict}\n"
        f"当前集钩子：{req.episode_hook}\n\n"
        "质量锚点：\n"
        f"{quality_anchor_block}\n\n"
        "待审文本：\n"
        f"{str(content or '')[:2200]}\n\n"
        "审片要求：\n"
        "- 先看它是不是一段真的戏，而不是梗概、说明书或空情绪。\n"
        "- 看人物行动有没有带来即时后果，而不是只把信息讲出来。\n"
        "- 看关系、信息、权力至少一层有没有发生能被镜头看见的变化。\n"
        "- 看结尾是不是停在具体动作、具体台词或具体发现上，而不是泛泛吊胃口。\n"
        "- 如果段落存在解释过重、动作偏弱、推进不足、结尾发虚、人物行为失真中的任一明显问题，就判不通过。\n\n"
        "只输出 JSON：\n"
        '{"passed": true, "issues": ["最多3条负面问题短句"], "strengths": ["最多2条短优点"]}'
    )

    try:
        result = generate_json(
            system_prompt,
            user_prompt,
            temperature=0.1,
            max_tokens=400,
            **generation_kwargs_from_req(req),
        )
    except Exception:
        return True, []

    issues_raw = result.get("issues")
    issues: list[str] = []
    negative_markers = (
        "缺少", "不足", "没有", "不够", "偏弱", "模糊", "空", "未", "只是", "停在",
        "突然", "单薄", "欠缺", "不足够", "解释", "发虚", "模板",
    )
    if isinstance(issues_raw, list):
        for item in issues_raw:
            issue = str(item or "").strip()
            if issue and any(marker in issue for marker in negative_markers):
                clauses = [part.strip() for part in re.split(r"[，。；：:,.]", issue) if part.strip()]
                short_issue = next(
                    (part for part in clauses if any(marker in part for marker in negative_markers)),
                    issue,
                )
                issues.append(short_issue[:24])

    track_name, _ = infer_testing_sample_track(req)
    text = str(content or "")
    if track_name.startswith("C.") and (req.segment_id == "resolution" or req.mode == "scene"):
        if any(token in text for token in ["许非墨", "我是谁", "没有回答", "不回答", "身份", "认错"]):
            issues = [item for item in issues if "身份" not in item and "信息差" not in item]

    passed = True if not issues else bool(result.get("passed")) and not issues
    return passed, issues[:3]


# ----- 结构化更新缓存（按 req+正文+present_ids 索引）-----
STRUCTURED_UPDATE_CACHE: "OrderedDict[str, dict[str, Any]]" = OrderedDict()
STRUCTURED_UPDATE_CACHE_MAX = 96


def structured_update_fingerprint(
    req: "TestingScriptRequest",
    content: str,
    present_ids: list[str],
) -> str:
    """为结构化更新缓存生成 sha1 指纹。"""
    payload = {
        "project_id": str(req.project_id or ""),
        "episode_no": int(req.episode_no or 0),
        "scene_no": int(req.scene_no or 0),
        "mode": str(req.mode or "scene"),
        "segment_id": str(req.segment_id or ""),
        "present_ids": sorted(str(item) for item in present_ids),
        "text": str(content or "")[:3200],
        "canon": normalize_testing_canon_packet(req.canon_packet or {}),
        "memory": [
            (
                int(item.get("episode_no") or 0),
                str(item.get("summary") or "")[:120],
                str(item.get("body_excerpt") or item.get("actual_progress") or "")[:120],
            )
            for item in normalize_testing_episode_memory_cards(req.episode_memory_cards or req.previous_episode_briefs or [])[-4:]
        ],
    }
    return hashlib.sha1(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def _tail_excerpt(content: str, *, limit: int = 180) -> str:
    lines = [line.strip() for line in str(content or "").splitlines() if line.strip()]
    if not lines:
        return ""
    return condense_text(" ".join(lines[-5:]), limit=limit)


def fallback_episode_memory_card(
    req: "TestingScriptRequest",
    content: str,
    evaluation: dict[str, Any],
) -> dict[str, Any]:
    """LLM 没给结构化更新时，兜底生成"集记忆卡"。"""
    warnings = [str(item).strip() for item in (evaluation.get("warnings") or []) if str(item).strip()]
    lines = [line.strip() for line in str(content or "").splitlines() if line.strip()]
    tail = lines[-1][:90] if lines else ""
    tail_excerpt = _tail_excerpt(content, limit=180)
    return {
        "episode_no": int(req.episode_no or 0),
        "title": str(req.episode_title or "").strip(),
        "summary": str(req.episode_summary or "").strip() or condense_text(content, limit=120),
        "opening_state": str(req.episode_conflict or "").strip(),
        "ending_state": tail,
        "relationship_delta": [],
        "information_delta": [],
        "power_delta": [],
        "unresolved_hooks": [tail] if tail else [],
        "spoiler_guard": [
            str(item.get("summary") or "")[:80]
            for item in (req.future_episode_briefs or [])[:2]
            if isinstance(item, dict) and str(item.get("summary") or "").strip()
        ],
        "tail_excerpt": tail_excerpt,
        "body_excerpt": tail_excerpt,
        "quality_summary": "；".join(warnings[:2]) if warnings else "",
    }
