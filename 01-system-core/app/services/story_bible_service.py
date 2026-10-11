"""
故事圣经/前置设定构建服务
"""
from __future__ import annotations

from typing import Any

from app.services.text_generation_service import generate_json, generation_enabled


def _fallback_story_bible(source_payload: dict[str, Any] | None = None) -> dict[str, Any]:
    source_payload = source_payload or {}
    project_brief = source_payload.get("project_brief") or {}
    title = project_brief.get("title") or source_payload.get("title") or "未命名项目"
    characters_text = project_brief.get("characters") or ""
    world_text = project_brief.get("world") or ""
    core_setting = project_brief.get("core_setting") or ""
    outline = project_brief.get("outline") or ""
    return {
        "mode": "fallback",
        "title": title,
        "character_bible": [
            {
                "name": "主角",
                "identity": "待细化",
                "goal": "完成主线逆袭/关系推进",
                "weakness": "当前大纲未完全展开",
                "speaking_style": "嘴硬但有辨识度",
                "secret": core_setting or "待补全",
                "arc": "从低位到翻盘",
                "source": "auto_expand",
            }
        ],
        "world_bible": {
            "setting": world_text or "待补全世界观",
            "rules": ["补充世界规则边界", "明确资源和舆论结构"],
            "constraints": [outline[:80] or "按项目大纲推进"],
            "source": "auto_expand",
        },
        "golden_finger_bible": {
            "exists": bool(core_setting),
            "origin": core_setting or "待确认",
            "trigger": "待补全",
            "benefit": "推动剧情关键翻盘",
            "cost": "必须设定代价与暴露风险",
            "upgrade_path": "待补全",
            "source": "auto_expand",
        },
        "relationship_matrix": [
            {
                "pair": "主角-核心对手/核心关系人",
                "current_state": "待梳理",
                "ceiling": "遵守关系慢推与事件跃迁",
                "conflict": "从大纲抽取主要冲突",
                "source": "auto_expand",
            }
        ],
        "conflict_map": {
            "main_conflict": outline or "待补全主线冲突",
            "stage_conflicts": [],
            "antagonist_pressure": [],
            "source": "auto_expand",
        },
        "outline_backfill": {
            "characters": characters_text,
            "world": world_text,
            "core_setting": core_setting,
            "insertions": [],
            "notes": ["当前为兜底结果，建议后续接入模型生成更完整设定。"],
        },
    }


def build_story_bible(
    *,
    mode: str,
    source_payload: dict[str, Any] | None = None,
    project_name: str = "",
    extra_requirements: str = "",
) -> dict[str, Any]:
    source_payload = source_payload or {}
    project_brief = source_payload.get("project_brief") or {}
    prompt_payload = {
        "mode": mode,
        "project_name": project_name or project_brief.get("title") or source_payload.get("title") or "未命名项目",
        "source_payload": source_payload,
        "requirements": extra_requirements,
        "output_schema": {
            "character_bible": [
                {"name": "", "identity": "", "goal": "", "weakness": "", "speaking_style": "", "secret": "", "arc": "", "source": "original|auto_expand"}
            ],
            "world_bible": {"setting": "", "rules": [], "constraints": [], "source": "original|auto_expand"},
            "golden_finger_bible": {"exists": True, "origin": "", "trigger": "", "benefit": "", "cost": "", "upgrade_path": "", "source": "original|auto_expand"},
            "relationship_matrix": [{"pair": "", "current_state": "", "ceiling": "", "conflict": "", "source": "original|auto_expand"}],
            "conflict_map": {"main_conflict": "", "stage_conflicts": [], "antagonist_pressure": [], "source": "original|auto_expand"},
            "outline_backfill": {"characters": "", "world": "", "core_setting": "", "insertions": [], "notes": []},
        },
    }

    if not generation_enabled():
        return _fallback_story_bible(source_payload)

    system_prompt = (
        "你是剧本前置设定构建器。只做结构化抽取与补全，不改写用户底层规则。"
        "当用户已提供大纲时，优先抽取已有内容，再补空白，不覆盖明确设定。"
        "输出必须是 JSON 对象。"
    )
    user_prompt = (
        "请根据输入构建角色库、世界观库、金手指库、关系矩阵、冲突地图，并生成可写回大纲的补充内容。"
        "要求：1) 区分 original 与 auto_expand；2) 只补空白，不覆盖明确设定；3) 回写内容要精简。\n\n"
        f"输入：{prompt_payload}"
    )
    try:
        result = generate_json(system_prompt, user_prompt, temperature=0.3)
    except Exception:
        return _fallback_story_bible(source_payload)
    result.setdefault("mode", mode)
    result.setdefault("title", prompt_payload["project_name"])
    return result


def merge_outline_with_backfill(source_payload: dict[str, Any], story_bible: dict[str, Any]) -> dict[str, str]:
    project_brief = source_payload.get("project_brief") or {}
    backfill = story_bible.get("outline_backfill") or {}
    return {
        "title": project_brief.get("title") or source_payload.get("title") or "未命名项目",
        "outline": project_brief.get("outline") or "",
        "characters": (project_brief.get("characters") or "").strip() + ("\n\n" + backfill.get("characters", "").strip() if backfill.get("characters") else ""),
        "world": (project_brief.get("world") or "").strip() + ("\n\n" + backfill.get("world", "").strip() if backfill.get("world") else ""),
        "core_setting": (project_brief.get("core_setting") or "").strip() + ("\n\n" + backfill.get("core_setting", "").strip() if backfill.get("core_setting") else ""),
    }
