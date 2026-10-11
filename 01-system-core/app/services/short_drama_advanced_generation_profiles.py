"""高级生成模式的静态创作形态配置。"""

from __future__ import annotations

from typing import Any


PROFILE_RULE_FILES = {
    "short_drama": "short_drama_core.md",
    "stage_play": "stage_play_core.md",
    "film": "film_core.md",
    "long_series": "long_series.md",
}

PROFILE_SYSTEM_PROMPTS = {
    "short_drama": "你是短剧创作助手。严格根据用户给出的提示完成生成，不要解释规则。",
    "stage_play": "你是专业话剧编剧和舞台文本顾问。严格根据用户提示输出可排演的舞台创作内容。",
    "film": "你是专业影视剧编剧和剧本统筹。严格根据用户提示输出可拍摄、可拆解的影视创作内容。",
    "long_series": "你是长剧和系列剧总编剧。严格根据用户提示输出重视连续性、人物弧光和季弧的剧集创作内容。",
}

ADVANCED_GENERATION_PROFILES: list[dict[str, Any]] = [
    {
        "id": "short_drama",
        "label": "短剧",
        "status": "active",
        "project_type_aliases": ["真人短剧", "漫剧", "AI真人", "原创短剧", "小说IP改编"],
        "rule_scopes": ["global", "content_type", "genre", "project", "step"],
        "workflow_steps": [
            {"id": "market_check", "label": "市场验证", "purpose": "判断题材方向和爆点是否成立", "output_type": "market_report"},
            {"id": "concept", "label": "概念规划", "purpose": "确定核心设定、主钩子和爽点承诺", "output_type": "concept_brief"},
            {"id": "characters", "label": "角色设计", "purpose": "建立人物关系和冲突张力", "output_type": "character_bible"},
            {"id": "episode_outlines", "label": "分集大纲", "purpose": "拆出连续集钩子和推进节奏", "output_type": "episode_outline"},
            {"id": "script_draft", "label": "剧本初稿", "purpose": "生成可拍的单集正文", "output_type": "script_text"},
            {"id": "quality_check", "label": "质检评分", "purpose": "检查节奏、钩子、人物和可拍性", "output_type": "quality_report"},
            {"id": "storyboard", "label": "分镜提示词", "purpose": "把确认剧本转成画面执行提示", "output_type": "storyboard_plan"},
        ],
        "artifacts": [
            {"id": "series_bible", "label": "项目设定包", "description": "题材、人物、世界观、关系和核心承诺"},
            {"id": "episode_script", "label": "单集剧本", "description": "按集保存的剧本正文"},
            {"id": "storyboard_prompt", "label": "分镜提示词", "description": "面向画面生成或分镜执行的提示词"},
        ],
        "notes": ["这是当前主流程，已接入高级生成入口。"],
    },
    {
        "id": "stage_play",
        "label": "话剧",
        "status": "active",
        "project_type_aliases": ["话剧", "舞台剧", "戏剧"],
        "rule_scopes": ["global", "content_type", "genre", "project", "act", "scene"],
        "workflow_steps": [
            {"id": "theme_intent", "label": "主题立意", "purpose": "确定舞台表达的核心问题", "output_type": "theme_brief"},
            {"id": "act_structure", "label": "幕结构", "purpose": "拆分幕、场和情绪推进", "output_type": "act_outline"},
            {"id": "character_dynamics", "label": "人物关系", "purpose": "建立舞台冲突和关系变化", "output_type": "character_dynamics"},
            {"id": "stage_scene_draft", "label": "场次正文", "purpose": "生成含舞台说明的场次文本", "output_type": "stage_scene_script"},
            {"id": "rehearsal_polish", "label": "排练稿打磨", "purpose": "检查台词、调度和舞台可执行性", "output_type": "rehearsal_notes"},
        ],
        "artifacts": [
            {"id": "act_outline", "label": "幕场大纲", "description": "按幕和场组织的结构稿"},
            {"id": "stage_script", "label": "舞台剧本", "description": "包含台词、动作和舞台说明"},
            {"id": "rehearsal_notes", "label": "排练提示", "description": "面向演员和导演的执行提示"},
        ],
        "notes": ["已接入项目创建和通用生成提示，后续继续细化专属工作台。"],
    },
    {
        "id": "film",
        "label": "影视剧",
        "status": "active",
        "project_type_aliases": ["电影", "影视剧", "长片", "网络电影"],
        "rule_scopes": ["global", "content_type", "genre", "project", "sequence", "scene"],
        "workflow_steps": [
            {"id": "logline", "label": "一句话故事", "purpose": "锁定类型、主冲突和观众承诺", "output_type": "logline"},
            {"id": "treatment", "label": "故事梗概", "purpose": "形成完整故事推进", "output_type": "treatment"},
            {"id": "sequence_outline", "label": "段落结构", "purpose": "按影视段落拆节奏和转折", "output_type": "sequence_outline"},
            {"id": "scene_list", "label": "场景表", "purpose": "整理场景、人物、地点和剧情功能", "output_type": "scene_list"},
            {"id": "screenplay_draft", "label": "剧本正文", "purpose": "生成影视剧本格式正文", "output_type": "screenplay"},
            {"id": "production_breakdown", "label": "制作拆解", "purpose": "提取场景、角色、道具和执行风险", "output_type": "production_breakdown"},
        ],
        "artifacts": [
            {"id": "treatment", "label": "故事梗概", "description": "完整故事和人物弧光说明"},
            {"id": "screenplay", "label": "影视剧本", "description": "按场景组织的剧本正文"},
            {"id": "production_breakdown", "label": "制作拆解", "description": "面向拍摄执行的拆解表"},
        ],
        "notes": ["已接入项目创建和通用生成提示，后续继续细化专属工作台。"],
    },
    {
        "id": "long_series",
        "label": "长剧/系列剧",
        "status": "active",
        "project_type_aliases": ["长剧", "系列剧", "季播剧"],
        "rule_scopes": ["global", "content_type", "genre", "project", "season", "episode", "scene"],
        "workflow_steps": [
            {"id": "series_bible", "label": "剧集圣经", "purpose": "沉淀世界观、人物弧光和长期矛盾", "output_type": "series_bible"},
            {"id": "season_arc", "label": "季弧规划", "purpose": "规划一季的主线、支线和阶段反转", "output_type": "season_arc"},
            {"id": "episode_outlines", "label": "分集大纲", "purpose": "拆出每集功能和连续性钩子", "output_type": "episode_outline"},
            {"id": "continuity_check", "label": "连续性检查", "purpose": "检查人物、时间线和伏笔回收", "output_type": "continuity_report"},
            {"id": "script_draft", "label": "单集剧本", "purpose": "生成单集正文", "output_type": "episode_script"},
        ],
        "artifacts": [
            {"id": "series_bible", "label": "剧集圣经", "description": "长期设定、人物弧光、时间线和规则"},
            {"id": "season_arc", "label": "季弧表", "description": "整季主线和分阶段推进"},
            {"id": "episode_script", "label": "单集剧本", "description": "按集保存的剧本正文"},
        ],
        "notes": ["已接入项目创建和通用生成提示，后续可和现有长剧步骤逐步合并。"],
    },
]
