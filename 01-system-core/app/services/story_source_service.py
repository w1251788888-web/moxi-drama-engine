"""
用户原稿读取与结构化提炼服务
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from docx import Document

from app.services import workspace_service


DEFAULT_SEASON_ARC = [
    {"season": 1, "goal": "进入大学"},
    {"season": 2, "goal": "打怪升级"},
    {"season": 3, "goal": "生孩子掉系统"},
]

DEFAULT_JIAHAO_MEME_LOGIC = {
    "definition": "喜欢哗众取宠、做出奇怪但自认为很帅气行为的男性学生型人物。",
    "core_behaviors": [
        "课间霸占希沃白板播放自认很潮的歌，伪装夜店DJ",
        "在白板或投屏上调出股票界面，假装自己是财富大亨",
        "故作高深点评局势，实则半懂不懂也要维持气场",
        "刻意制造围观来放大自己的存在感和帅气错觉",
    ],
    "writing_use": [
        "作为男主前期低位搞笑标签和围观来源",
        "作为系统任务触发器，让装X行为和收益/惩罚绑定",
        "作为校园名场面回收机制，形成角色辨识度",
    ],
    "format_rules": [
        "按短剧/2D漫剧对白剧本格式输出，不写推文体叙述",
        "每场必须有场景标题、动作行、对白行，动作统一用△独立成行",
        "对白统一使用角色名：台词，系统提示用SYS:独立成行，内心用OS:独立成行",
        "每集优先写成可拍可演可分镜的2分钟漫剧脚本，场次短、切换快、尾钩明确",
    ],
    "quality_rules": [
        "开篇先给男主真实且立刻可见的困难，不先炫设定",
        "文本必须带网感和热梗衍生感，但不能只堆梗，要让梗参与冲突",
        "系统必须有人格，能说话、能怼人、能施压，和人物设定保持一致",
        "每场都要有推进+反刺+尾钩，适配2D漫剧快节奏观看",
    ],
}


def load_story_source(doc_path: str | Path) -> dict[str, Any]:
    path = Path(doc_path).expanduser()
    if not path.exists():
        raise ValueError(f"原稿文件不存在: {path}")
    if path.suffix.lower() != ".docx":
        raise ValueError("当前只支持读取 .docx 原稿")

    imported_path = workspace_service.import_file_to_library(
        path,
        category="story-sources",
        allowed_suffixes=(".docx",),
    )

    document = Document(imported_path)
    paragraphs = [paragraph.text.strip() for paragraph in document.paragraphs if paragraph.text.strip()]
    if not paragraphs:
        raise ValueError("原稿内容为空")

    sections = _collect_sections(paragraphs)
    title = paragraphs[0]
    genres = _split_cn_list(sections.get("题材类型", ""))
    project_brief = {
        "title": title,
        "genres": genres,
        "outline": sections.get("大纲", ""),
        "world": sections.get("世界观", ""),
        "core_setting": sections.get("核心设定", ""),
        "characters": sections.get("人物设定", ""),
    }
    return {
        "title": title,
        "source_doc_path": str(imported_path),
        "source_doc_name": path.name,
        "paragraphs": paragraphs,
        "sections": sections,
        "project_brief": project_brief,
        "season_arc": list(DEFAULT_SEASON_ARC),
        "meme_logic": dict(DEFAULT_JIAHAO_MEME_LOGIC),
        "source_summary": _build_source_summary(project_brief),
    }



def _collect_sections(paragraphs: list[str]) -> dict[str, str]:
    sections: dict[str, list[str]] = {}
    current_key = "正文"
    sections[current_key] = []
    for line in paragraphs[1:]:
        if "：" in line:
            key, value = line.split("：", 1)
            if key in {"题材类型", "大纲", "世界观", "核心设定", "人物设定"}:
                current_key = key
                sections.setdefault(current_key, [])
                if value.strip():
                    sections[current_key].append(value.strip())
                continue
        sections.setdefault(current_key, []).append(line)
    return {key: "\n".join(value).strip() for key, value in sections.items() if value}



def _split_cn_list(raw: str) -> list[str]:
    return [item.strip() for item in raw.replace("，", ",").split(",") if item.strip()]



def _build_source_summary(project_brief: dict[str, Any]) -> str:
    genres = " / ".join(project_brief.get("genres") or []) or "未标注题材"
    return (
        f"《{project_brief.get('title') or '未命名项目'}》属于{genres}方向，"
        f"主打废物男主穿越成陈嘉豪后靠系统和校园装X名场面逆袭，"
        f"目标是在第一季完成从卧龙凤雏学院到八道口技能学院的升学翻身。"
    )
