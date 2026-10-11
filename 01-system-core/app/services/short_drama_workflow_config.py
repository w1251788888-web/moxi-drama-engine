"""短剧写作流程配置。

这个文件只放流程表、步骤名、Prompt 文件名等静态配置。
路由文件只负责接请求和回响应，避免继续变成大杂烩。
"""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any, Literal, Optional


KIND = "short_drama_writing_session"


def pipeline_path() -> Path:
    return Path(__file__).resolve().parents[3] / "02-creation-rules" / "pipeline.toml"


def load_pipeline_config() -> dict[str, Any]:
    try:
        with pipeline_path().open("rb") as fp:
            return tomllib.load(fp)
    except Exception:
        return {}


PIPELINE_CONFIG = load_pipeline_config()
PIPELINE_STEP_DEFS = {
    str(step.get("id") or "").strip(): step
    for step in (PIPELINE_CONFIG.get("step") or [])
    if isinstance(step, dict) and str(step.get("id") or "").strip()
}
PIPELINE_SHORT_DRAMA_WRITING_STEPS = PIPELINE_CONFIG.get("short_drama_writing_steps") or {}


def pipeline_file_name(step_id: str, key: str) -> Optional[str]:
    step = PIPELINE_STEP_DEFS.get(step_id) or {}
    raw = str(step.get(key) or "").strip()
    return Path(raw).name if raw else None


def workflow_step_order_for_project(project: dict[str, Any]) -> list[str]:
    project_type = str(project.get("project_type") or "").strip()
    if "小说IP改编" in project_type:
        order = PIPELINE_SHORT_DRAMA_WRITING_STEPS.get("ordered_novel_adaptation") or []
    elif "长剧" in project_type or "系列剧" in project_type:
        order = PIPELINE_SHORT_DRAMA_WRITING_STEPS.get("ordered_long_series") or []
    else:
        order = PIPELINE_SHORT_DRAMA_WRITING_STEPS.get("ordered_original") or []
    return [str(item).strip() for item in order if str(item).strip()]


STEP_ID = Literal[
    "project_init_check",
    "novel_analysis",
    "character_lock",
    "market_check",
    "concept",
    "characters",
    "episode_outlines",
    "beat_sheet",
    "scene_list",
    "script_draft",
    "quality_check",
    "narrative_consistency",
    "compliance_check",
    "storyboard",
]


STEP_PROMPT_FILE: dict[str, Optional[str]] = {
    "project_init_check": pipeline_file_name("project_init_check", "prompt_path") or "00_project_init_check.md",
    "novel_analysis": pipeline_file_name("novel_analysis", "prompt_path") or "00_novel_analysis.md",
    "character_lock": pipeline_file_name("character_lock", "prompt_path") or "00_character_lock.md",
    "market_check": pipeline_file_name("market_check", "prompt_path") or "00_market_check.md",
    "concept": pipeline_file_name("concept", "prompt_path") or "01_concept.md",
    "characters": pipeline_file_name("characters", "prompt_path") or "02_characters.md",
    "episode_outlines": pipeline_file_name("episode_outlines", "prompt_path") or "02b_episode_outlines.md",
    "beat_sheet": pipeline_file_name("beat_sheet", "prompt_path") or "03_beat_sheet.md",
    "scene_list": pipeline_file_name("scene_list", "prompt_path") or "04_scene_list.md",
    "script_draft": pipeline_file_name("script_draft", "prompt_path") or "05_script_draft.md",
    "quality_check": pipeline_file_name("quality_check", "prompt_path") or "07_quality_check.md",
    "narrative_consistency": pipeline_file_name("narrative_consistency", "prompt_path") or "08_narrative_consistency.md",
    "compliance_check": pipeline_file_name("compliance_check", "prompt_path") or "08_compliance_check.md",
    "storyboard": pipeline_file_name("storyboard", "prompt_path") or "06_storyboard_prompts.md",
}

STEP_SYSTEM_PROMPT_FILE: dict[str, Optional[str]] = {
    "project_init_check": None,
    "novel_analysis": None,
    "character_lock": None,
    "market_check": None,
    "concept": pipeline_file_name("concept", "system_prompt_path") or "planner-script-concept.md",
    "characters": pipeline_file_name("characters", "system_prompt_path") or "executor-script-characters.md",
    "episode_outlines": None,
    "beat_sheet": None,
    "scene_list": None,
    "script_draft": pipeline_file_name("script_draft", "system_prompt_path") or "executor-script-draft.md",
    "quality_check": pipeline_file_name("quality_check", "system_prompt_path") or "reviewer-quality-score.md",
    "narrative_consistency": None,
    "compliance_check": pipeline_file_name("compliance_check", "system_prompt_path") or "compliance-checker.md",
    "storyboard": None,
}

SCRIPT_DRAFT_MODES: dict[str, str] = {
    "standard": "executor-script-draft.md",
    "premium": "executor-script-premium.md",
    "comic": "executor-script-comic.md",
}

STEP_LABELS: dict[str, str] = {
    "project_init_check": "项目初始化",
    "novel_analysis": "原著分析",
    "character_lock": "角色锁定",
    "market_check": "市场可行性",
    "concept": "概念规划",
    "characters": "角色设计",
    "episode_outlines": "30 集集纲",
    "beat_sheet": "节拍表",
    "scene_list": "分场表",
    "script_draft": "剧本初稿",
    "quality_check": "质检评分",
    "narrative_consistency": "叙事一致性审查",
    "compliance_check": "合规审查",
    "storyboard": "分镜提示词",
}
