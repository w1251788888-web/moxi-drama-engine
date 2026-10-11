"""测试页 prompt"上下文块"构造器（从 short_drama_writing.py 抽出）。

四个纯函数，只读 TestingScriptRequest 字段：
- string_list：把 list 字段压成最长 4 个、每条 ≤120 字的字符串列表（防止 LLM 输出过长字段污染 prompt）
- build_previous_episode_brief_block：前序最多 9 集摘要拼成多行块
- build_future_episode_brief_block：后续最多 5 集摘要拼成多行块（剧透检测用）
- build_relationship_diff_block：对比 previous_relationship_snapshot 与 characters 当前关系，输出 diff 行

零 IO、零 DB、零 AI 调用。多个 endpoint 共用，搬出来不影响调用链。
"""
from __future__ import annotations

from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from app.schemas.short_drama_writing import TestingScriptRequest


def string_list(value: Any, *, limit: int = 4) -> list[str]:
    """把列表里的字符串元素清理出来：strip + 截断到 120 字 + 最多 limit 条。"""
    if not isinstance(value, list):
        return []
    items: list[str] = []
    for raw in value:
        text = str(raw or "").strip()
        if text:
            items.append(text[:120])
        if len(items) >= limit:
            break
    return items


def build_previous_episode_brief_block(req: "TestingScriptRequest") -> str:
    """前序最多 9 集摘要拼成多行块；空列表给一句兜底文案。"""
    briefs = req.previous_episode_briefs or []
    if not briefs:
        return "暂无前序集摘要。"

    lines: list[str] = []
    for item in briefs[-9:]:
        if not isinstance(item, dict):
            continue
        episode_no = item.get("episode_no") or item.get("ep") or ""
        title = str(item.get("title") or "").strip()
        summary = str(item.get("summary") or "").strip()
        hook = str(item.get("hook") or "").strip()
        conflict = str(item.get("conflict") or "").strip()
        actual_progress = str(
            item.get("actual_progress")
            or item.get("result_summary")
            or item.get("ending_status")
            or item.get("body_excerpt")
            or ""
        ).strip()
        line_parts = [f"第{episode_no}集" if episode_no else "前序集"]
        if title:
            line_parts.append(title)
        if summary:
            line_parts.append(f"摘要：{summary}")
        if conflict:
            line_parts.append(f"冲突：{conflict}")
        if hook:
            line_parts.append(f"钩子：{hook}")
        if actual_progress:
            line_parts.append(f"已落地：{actual_progress[:140]}")
        lines.append("｜".join(line_parts))
    return "\n".join(lines) if lines else "暂无前序集摘要。"


def build_future_episode_brief_block(req: "TestingScriptRequest") -> str:
    """后续最多 5 集摘要拼成多行块；用于深审时检测剧透。"""
    briefs = req.future_episode_briefs or []
    if not briefs:
        return "暂无后续集摘要。"

    lines: list[str] = []
    for item in briefs[:5]:
        if not isinstance(item, dict):
            continue
        episode_no = item.get("episode_no") or item.get("ep") or ""
        title = str(item.get("title") or "").strip()
        summary = str(item.get("summary") or "").strip()
        conflict = str(item.get("conflict") or "").strip()
        hook = str(item.get("hook") or "").strip()
        line_parts = [f"第{episode_no}集" if episode_no else "后续集"]
        if title:
            line_parts.append(title)
        if summary:
            line_parts.append(f"摘要：{summary[:120]}")
        if conflict:
            line_parts.append(f"冲突：{conflict[:80]}")
        if hook:
            line_parts.append(f"钩子：{hook[:80]}")
        lines.append("｜".join(line_parts))
    return "\n".join(lines) if lines else "暂无后续集摘要。"


def build_relationship_diff_block(req: "TestingScriptRequest") -> str:
    """对比 previous_relationship_snapshot 与当前 characters 的关系强度/类型差异。"""
    prev_map: dict[tuple[str, str], dict[str, Any]] = {}
    for item in (req.previous_relationship_snapshot or []):
        if not isinstance(item, dict):
            continue
        s = str(item.get("source") or item.get("source_id") or "").strip()
        t = str(item.get("target") or item.get("target_id") or "").strip()
        if not s or not t:
            continue
        prev_map[(s, t)] = item

    cur_pairs: list[tuple[str, str, str, int]] = []
    for char in (req.characters or []):
        if not isinstance(char, dict):
            continue
        src = str(char.get("id") or char.get("name") or "").strip()
        for rel in (char.get("relationships") or []):
            if not isinstance(rel, dict):
                continue
            tgt = str(rel.get("targetId") or rel.get("target_id") or "").strip()
            if not src or not tgt:
                continue
            try:
                strength = int(rel.get("strength") or 0)
            except Exception:
                strength = 0
            cur_pairs.append((src, tgt, str(rel.get("type") or "").strip(), strength))

    if not prev_map and not cur_pairs:
        return "暂无前次关系快照，无法做关系 diff。"

    diff_lines: list[str] = []
    for src, tgt, rtype, strength in cur_pairs:
        prev = prev_map.get((src, tgt))
        if not prev:
            diff_lines.append(f"+ 新增关系：{src}↔{tgt}（{rtype}，强度{strength}）")
            continue
        prev_strength = int(prev.get("strength") or 0)
        prev_type = str(prev.get("type") or "").strip()
        if prev_type and prev_type != rtype:
            diff_lines.append(f"~ 类型漂移：{src}↔{tgt} {prev_type}→{rtype}（强度{prev_strength}→{strength}）")
        elif strength - prev_strength >= 10:
            diff_lines.append(f"↑ 强度跃升：{src}↔{tgt}（{rtype}）{prev_strength}→{strength}")
        elif prev_strength - strength >= 10:
            diff_lines.append(f"↓ 强度回落：{src}↔{tgt}（{rtype}）{prev_strength}→{strength}")
    if not diff_lines:
        return "本集关系图与前次一致，无显著 diff。"
    return "\n".join(diff_lines[:12])
