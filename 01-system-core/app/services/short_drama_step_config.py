"""run-step 用的“温度策略 + 模板键白名单”常量（从 short_drama_writing.py 抽出）。

零 IO/AI/DB，纯静态：

- STEP_TEMPERATURE_PROFILE：按 step_id 选默认 temperature（结构化步骤=0.0/创作步骤=0.7）
- resolve_step_temperature：调用方传了温度就尊重，否则按 step 类型选
- KNOWN_TEMPLATE_KEYS：白名单允许 prompt 模板用的变量名
"""
from __future__ import annotations

from typing import Optional


# 温度策略分层（结构化=0.0，节拍/分场=0.4，创作=0.7）
STEP_TEMPERATURE_PROFILE: dict[str, float] = {
    "project_init_check": 0.0,
    "novel_analysis": 0.3,
    "character_lock": 0.0,
    "market_check": 0.0,
    "concept": 0.2,
    "characters": 0.4,
    "episode_outlines": 0.3,
    "beat_sheet": 0.4,
    "scene_list": 0.5,
    "script_draft": 0.7,
    "quality_check": 0.0,
    "narrative_consistency": 0.0,
    "compliance_check": 0.0,
    "storyboard": 0.5,
}


def resolve_step_temperature(step_id: str, override: Optional[float]) -> Optional[float]:
    """如果调用方传了温度，尊重；否则按步骤性质选择。"""
    if override is not None:
        return override
    return STEP_TEMPERATURE_PROFILE.get(step_id)


# Bug Fix #5: 补齐 episode_novel_anchor / novel_analysis / market_check 等变量
KNOWN_TEMPLATE_KEYS: tuple[str, ...] = (
    "project_type",
    "episode_count",
    "episode_minutes",
    "audience_axis",
    "genre_main",
    "genre_sub",
    "subgenre_track",
    "sample_track",
    "rule_profile",
    "constraints",
    "brief",
    "novel_input",
    "novel_analysis",
    "locked_characters",
    "market_check",
    "concept",
    "characters",
    "world_rules",
    "relationship_guardrails",
    "state_cards_block",
    "golden_finger_rules",
    "conflict_plan",
    "material_references",
    "material_borrow_focus",
    "material_heat_signals",
    "material_risk_guardrails",
    "material_do_not_copy",
    "issue_feedback_summary",
    "negative_prompt_hints",
    "review_focus",
    "storyboard_requirements",
    "beat_sheet",
    "scene_list",
    "script_draft",
    "quality_report",
    "compliance_report",
    "draft_episode",
    "episode_novel_anchor",
    "episode_beat",
    "batch_start",
    "batch_end",
    "prev_batches_summary",
    "episode_outlines_block",
    "current_episode_outline",
    "used_beats_block",
    "previous_cliffhanger",
    "scene_header_style",
    "commercial_score",
    "primary_archetype",
    "secondary_archetype",
    "rag_asset_references",
    "rag_market_signals",
    "rag_novel_chapters",
    "rag_script_references",
    "rag_character_references",
    "rag_beat_references",
    "rag_review_references",
)
