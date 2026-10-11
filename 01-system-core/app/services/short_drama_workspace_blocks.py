"""短剧工作台 prompt 块构造器（从 short_drama_writing.py 抽出）。

- condense_text: 去多空白 + 长度截断 + 加省略号
- derive_workspace_project_type: 项目类型默认值推断
- build_workspace_character_block: 角色卡 prompt 块
- build_workspace_concept_block: 概念/题眼/钩子 prompt 块
- build_workspace_scene_block: 整集写作任务 prompt 块

纯字符串构造，无 IO 无副作用。
"""
from __future__ import annotations

import re
from typing import Any


def condense_text(text: str, *, limit: int = 160) -> str:
    compact = re.sub(r"\s+", " ", str(text or "").strip())
    if len(compact) <= limit:
        return compact
    return compact[: max(20, limit - 1)].rstrip() + "…"



def derive_workspace_project_type(project_type: str, audience_axis: str, format_type: str) -> str:
    if str(project_type or "").strip():
        return str(project_type).strip()
    axis = str(audience_axis or "").strip() or "混合"
    fmt = str(format_type or "").strip() or "真人短剧"
    return f"{fmt}-{axis}"



def build_workspace_character_block(characters: list[dict[str, Any]], selected_ids: set[str]) -> str:
    if not characters:
        return "暂无结构化角色卡，请严格根据已知名字和关系写作，不要自造新核心角色。"

    role_map = {
        "protagonist": "主角",
        "antagonist": "反派",
        "supporting": "配角",
        "minor": "次要角色",
    }

    by_id = {str(char.get("id") or ""): char for char in characters if isinstance(char, dict)}
    focus_ids: list[str] = []
    focus_names: set[str] = set()

    def _append_focus(char_id: str) -> None:
        if char_id and char_id in by_id and char_id not in focus_ids:
            focus_ids.append(char_id)

    for char in characters:
        role = str(char.get("role") or "").strip()
        char_id = str(char.get("id") or "").strip()
        if role in ("protagonist", "antagonist"):
            _append_focus(char_id)
    for item in selected_ids:
        _append_focus(str(item))

    for char_id in list(focus_ids):
        char = by_id.get(char_id) or {}
        for rel in (char.get("relationships") or []):
            if not isinstance(rel, dict):
                continue
            target_id = str(rel.get("targetId") or rel.get("target_id") or "").strip()
            _append_focus(target_id)

    if not focus_ids:
        focus_ids = [str(char.get("id") or "") for char in characters[:3] if str(char.get("id") or "").strip()]

    chunks: list[str] = []
    for char_id in focus_ids[:5]:
        char = by_id.get(char_id) or {}
        char_id = str(char.get("id") or "")
        name = str(char.get("name") or "").strip()
        if not name:
            continue
        if name in focus_names:
            continue
        focus_names.add(name)

        presence = "本场出场" if char_id and char_id in selected_ids else "本场未明确出场"
        role = role_map.get(str(char.get("role") or "").strip(), str(char.get("role") or "角色"))
        header = f"【{name}】（{role}，{presence}）"

        parts: list[str] = []
        age_value = char.get("age")
        age_text = ""
        if isinstance(age_value, (int, float)) and int(age_value) > 0:
            age_text = f"{int(age_value)}岁"
        else:
            raw_age = str(age_value or "").strip()
            if raw_age:
                age_text = raw_age

        personality = str(char.get("personality") or "").strip()
        traits = str(char.get("traits") or "").strip()
        temperament = personality or traits

        # 优先使用 info 字段（大纲阶段直接提取的完整原文），
        # 但年龄/性格仍要显式露出，避免模型只抓剧情抓手、不记人物稳定锚点。
        info = str(char.get("info") or "").strip()
        if info:
            parts.append(f"- 人物抓手：{condense_text(info, limit=120)}")
            if age_text:
                parts.append(f"- 年龄设定：{condense_text(age_text, limit=24)}")
            if temperament:
                parts.append(f"- 性格锚点：{condense_text(temperament, limit=52)}")
        else:
            # 兼容旧格式：从细分字段拼合
            for label, keys in [
                ("年龄设定", ["age"]),
                ("职业/身份", ["occupation"]),
                ("外貌", ["appearance"]),
                ("背景", ["background"]),
                ("性格锚点", ["personality", "traits"]),
                ("说话方式", ["voice_style"]),
                ("动机", ["motivation"]),
                ("弧线", ["arc"]),
                ("补充", ["notes"]),
            ]:
                val = ""
                for k in keys:
                    current = char.get(k)
                    if k == "age":
                        if age_text:
                            val = age_text
                            break
                        continue
                    val = str(current or "").strip()
                    if val:
                        break
                if val:
                    parts.append(f"- {label}：{condense_text(val, limit=52)}")
                if len(parts) >= 4:
                    break

        # 关系
        relations = char.get("relationships") or []
        if isinstance(relations, list) and relations:
            rel_items = []
            for rel in relations:
                if not isinstance(rel, dict):
                    continue
                tgt = str(rel.get("targetName") or rel.get("target_name") or "").strip()
                rtype = str(rel.get("type") or "").strip()
                rdesc = str(rel.get("description") or "").strip()
                if tgt:
                    rel_items.append(f"与{tgt}（{rtype or '关系待定'}{('，' + condense_text(rdesc, limit=24)) if rdesc else ''}）")
                if len(rel_items) >= 2:
                    break
            if rel_items:
                parts.append(f"- 关系：{'、'.join(rel_items)}")

        body = "\n".join(parts) if parts else "（暂无详细信息）"
        chunks.append(f"{header}\n{body}")

    return "\n\n".join(chunks) or "暂无结构化角色卡，请严格根据已知名字和关系写作，不要自造新核心角色。"



def build_workspace_concept_block(
    brief: str,
    worldview: str,
    conflict: str,
    episode_title: str,
    episode_summary: str,
    episode_conflict: str,
    episode_hook: str,
    golden_finger: str = "",
) -> str:
    parts = [
        f"- 项目题眼：{condense_text(brief, limit=90)}" if brief.strip() else "",
        f"- 核心设定/金手指：{condense_text(golden_finger, limit=80)}" if golden_finger.strip() else "",
        f"- 世界观/赛道：{condense_text(worldview, limit=80)}" if worldview.strip() else "",
        f"- 核心冲突：{condense_text(conflict, limit=90)}" if conflict.strip() else "",
        f"- 当前集标题：{condense_text(episode_title, limit=40)}" if episode_title.strip() else "",
        f"- 当前集摘要：{condense_text(episode_summary, limit=90)}" if episode_summary.strip() else "",
        f"- 当前集冲突：{condense_text(episode_conflict, limit=80)}" if episode_conflict.strip() else "",
        f"- 当前集钩子：{condense_text(episode_hook, limit=60)}" if episode_hook.strip() else "",
    ]
    text = "\n".join(item for item in parts if item)
    return text or "测试页未提供完整概念信息，请优先遵守当前集冲突和角色关系。"



def build_workspace_scene_block(
    episode_no: int,
    scene_no: int,
    episode_title: str,
    episode_summary: str,
    episode_conflict: str,
    episode_hook: str,
    selected_names: list[str],
    continuity_notes: str,
    task_instruction: str,
) -> str:
    parts = [
        f"- 当前目标：第{episode_no}集整集正文（前端只保存到一个集级写作容器；正文内部可自然包含多场戏）",
        f"- 本集标题：{condense_text(episode_title, limit=40)}" if episode_title.strip() else "",
        f"- 本集摘要：{condense_text(episode_summary, limit=90)}" if episode_summary.strip() else "",
        f"- 本集冲突：{condense_text(episode_conflict, limit=72)}" if episode_conflict.strip() else "",
        f"- 本集钩子：{condense_text(episode_hook, limit=60)}" if episode_hook.strip() else "",
        f"- 本集焦点角色：{'、'.join(selected_names)}" if selected_names else "- 本集焦点角色：未指定，按已写正文和当前冲突谨慎判断",
        f"- 连贯性提醒：{condense_text(continuity_notes, limit=90)}" if continuity_notes.strip() else "",
        f"- 本轮写作任务：{condense_text(task_instruction, limit=120)}",
    ]
    return "\n".join(item for item in parts if item)

