"""测试页"集间接续 + 连续性回退评估"工具（从 short_drama_writing.py 抽出）。

本模块负责"集间接续(seam)检测"、"连续性回退评估(fallback continuity)"以及深审缓存指纹/容器：

- testing_script_body_lines / testing_os_line_count：剧本正文行清洗 + OS 行计数
- testing_char_bigrams / testing_overlap_ratio：字符 bigram 集合 & 重叠率，用于检测前一集尾巴和当前集开头的"接续断裂"
- previous_testing_tail_block：从 episode_memory_cards / previous_episode_briefs 里取出前一集真实尾巴
- assess_testing_episode_seam：对比上一集尾 vs 本集前5行，命中"重置开场词" + 重叠率 < 0.08 时给出断裂提示
- apply_testing_seam_gate_to_continuity：把 seam 风险灌进 ContinuityAssessment（封顶 40 分）
- fallback_continuity_assessment：当深审 LLM 走丢时，按关系/字数风险算回退分
- deep_audit_fingerprint + DEEP_AUDIT_CACHE / DEEP_AUDIT_CACHE_MAX：基于 req+正文 hash 的深审缓存键和容器

零 AI 调用、零 DB、零 IO。多个 endpoint（generate / validate / deep-audit / auto-fix）共用，
搬到 services 后主 router 拆分时不会再"互相伸手"。
"""
from __future__ import annotations

import hashlib
import json
import re
from collections import OrderedDict
from typing import Any, TYPE_CHECKING

from app.schemas.short_drama_writing import BenchmarkAssessment, ContinuityAssessment
from app.services.short_drama_testing_blocks import string_list
from app.services.short_drama_testing_normalizers import normalize_testing_episode_memory_cards
from app.services.short_drama_text_format import is_testing_header_line

if TYPE_CHECKING:
    from app.schemas.short_drama_writing import TestingScriptRequest


_TESTING_RESET_OPENING_HINTS = (
    "清晨", "第二天", "几天后", "一早", "重新", "已经", "店门口", "排起", "又一次",
)


def testing_script_body_lines(text: str) -> list[str]:
    """剔除场标头与空行后剩下的剧本正文行。"""
    return [
        line.strip()
        for line in str(text or "").splitlines()
        if line.strip() and not is_testing_header_line(line.strip())
    ]


def testing_os_line_count(text: str) -> int:
    """统计 OS 行数（用于检测内心独白是否过密）。"""
    return sum(
        1
        for line in str(text or "").splitlines()
        if re.match(r"^[^：:\n]{1,16}(?:（[^）]{1,12}）)?OS[：:].+", line.strip())
    )


def testing_char_bigrams(text: str) -> set[str]:
    """字符 bigram 集合（去掉非中英数字字符）。"""
    compact = re.sub(r"[^一-鿿A-Za-z0-9]", "", str(text or ""))
    return {compact[idx:idx + 2] for idx in range(max(0, len(compact) - 1))}


def testing_overlap_ratio(left: str, right: str) -> float:
    """两段文本 bigram 集合的重叠比例（0~1，1 表示完全相同）。"""
    left_tokens = testing_char_bigrams(left)
    right_tokens = testing_char_bigrams(right)
    if not left_tokens or not right_tokens:
        return 1.0
    return len(left_tokens & right_tokens) / max(1, min(len(left_tokens), len(right_tokens)))


def previous_testing_tail_block(req: "TestingScriptRequest") -> str:
    """从 episode_memory_cards / previous_episode_briefs 中提取前一集真实尾巴。"""
    previous_cards = normalize_testing_episode_memory_cards(req.episode_memory_cards or [])
    target = int(req.episode_no or 0)
    for card in reversed(previous_cards):
        if int(card.get("episode_no") or 0) < target:
            text = str(card.get("ending_state") or card.get("tail_excerpt") or card.get("body_excerpt") or card.get("summary") or "").strip()
            if text:
                return text
    for item in reversed(req.previous_episode_briefs or []):
        if not isinstance(item, dict):
            continue
        text = str(
            item.get("ending_state")
            or item.get("tail_excerpt")
            or item.get("body_excerpt")
            or item.get("actual_progress")
            or item.get("result_summary")
            or item.get("hook")
            or item.get("summary")
            or ""
        ).strip()
        if text:
            return text
    return ""


def assess_testing_episode_seam(req: "TestingScriptRequest", episode_text: str) -> list[str]:
    """对比上一集尾巴 vs 当前集开头，识别"集间接续断裂"。第1集直接放过。"""
    if int(req.episode_no or 0) <= 1:
        return []
    previous_tail = "\n".join(testing_script_body_lines(previous_testing_tail_block(req))[-3:])
    current_head = "\n".join(testing_script_body_lines(episode_text)[:5])
    if not previous_tail or not current_head:
        return []
    overlap = testing_overlap_ratio(previous_tail, current_head)
    reset_opening = any(token in current_head for token in _TESTING_RESET_OPENING_HINTS)
    if overlap < 0.08 and reset_opening:
        return [
            "集间接续断裂：上一集尾部/未收钩子没有在本集前5行直接承接；"
            f"上一尾：{previous_tail[:70]}；本头：{current_head[:70]}"
        ]
    return []


def apply_testing_seam_gate_to_continuity(
    req: "TestingScriptRequest",
    continuity: ContinuityAssessment,
    episode_text: str,
) -> ContinuityAssessment:
    """把 seam 断裂风险塞进 ContinuityAssessment 并封顶 40 分。"""
    seam_risks = assess_testing_episode_seam(req, episode_text)
    if not seam_risks:
        return continuity
    continuity.plot_risks = list(dict.fromkeys([*(continuity.plot_risks or []), *seam_risks]))[:4]
    continuity.score = min(int(continuity.score or 0) or 94, 40)
    continuity.passed = False
    continuity.summary = "集间接续断裂，当前连续性按头部短剧标准封顶40分。"
    return continuity


def fallback_continuity_assessment(
    req: "TestingScriptRequest",
    evaluation: dict[str, Any],
) -> ContinuityAssessment:
    """LLM 深审走丢时的兜底连续性评估。"""
    relationship_risks = [
        item for item in string_list(evaluation.get("warnings"), limit=4)
        if "关系" in item or "主角" in item or "反派" in item
    ]
    plot_risks = [
        item for item in string_list(evaluation.get("blocking_issues"), limit=4)
        if "字数" in item or "续写" in item or "场次" in item
    ]
    span_start = 1
    briefs = req.previous_episode_briefs or []
    if briefs:
        first = briefs[max(-len(briefs), -9)]
        try:
            span_start = int(first.get("episode_no") or first.get("ep") or 1)
        except Exception:
            span_start = 1
    checked_span = f"{span_start}-{max(span_start, int(req.episode_no or span_start))}"
    penalty = min(len(relationship_risks), 3) * 10 + min(len(plot_risks), 3) * 8
    score = max(50, 94 - penalty)
    continuity = ContinuityAssessment(
        checked_episode_span=checked_span,
        score=score,
        passed=score >= 85,
        summary="已按关系护栏和当前集规划做连续性回退校验。",
        preserved_anchors=string_list([
            req.episode_conflict,
            req.episode_hook,
            req.continuity_notes,
        ], limit=3),
        relationship_risks=relationship_risks,
        plot_risks=plot_risks,
    )
    return apply_testing_seam_gate_to_continuity(
        req,
        continuity,
        str(req.episode_content or evaluation.get("content") or ""),
    )


# ----- 深审缓存（按 req + 正文 hash 索引）-----
DEEP_AUDIT_CACHE: "OrderedDict[str, tuple[BenchmarkAssessment, ContinuityAssessment]]" = OrderedDict()
DEEP_AUDIT_CACHE_MAX = 64


def deep_audit_fingerprint(req: "TestingScriptRequest", episode_text: str) -> str:
    """为深审缓存生成 sha1 指纹（覆盖集号/标题/摘要/赛道/正文/前后文摘要/关系快照）。"""
    payload = {
        "ep": int(req.episode_no or 0),
        "title": req.episode_title or "",
        "summary": req.episode_summary or "",
        "subgenre": req.subgenre_track or "",
        "sample": req.sample_track or "",
        "text": episode_text,
        "prev": [
            (int(b.get("episode_no") or b.get("ep") or 0), str(b.get("summary") or "")[:120])
            for b in (req.previous_episode_briefs or [])[-9:] if isinstance(b, dict)
        ],
        "future": [
            (int(b.get("episode_no") or b.get("ep") or 0), str(b.get("summary") or "")[:120])
            for b in (req.future_episode_briefs or [])[:5] if isinstance(b, dict)
        ],
        "rel_snap": sorted(
            (str(s.get("source") or ""), str(s.get("target") or ""), str(s.get("type") or ""), int(s.get("strength") or 0))
            for s in (req.previous_relationship_snapshot or []) if isinstance(s, dict)
        ),
    }
    blob = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha1(blob).hexdigest()
