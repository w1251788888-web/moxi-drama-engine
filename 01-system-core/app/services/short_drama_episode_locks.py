"""测试页“关键名词锁 + 本段意图”工具（从 short_drama_writing.py 抽出）。

3 个纯函数，零 IO/AI/DB：

- extract_episode_keywords：从摘要/冲突/钩子里抽取强约束名词（金额、事件物件、时间节点）
- build_lockword_block：构造关键名词锁块（本集必须见到 + 后续集禁止提前消耗）
- build_segment_intent_block：把 episode_summary 自动拆为 4 段意图

被分段生成（hook/validation/explosion/resolution）prompt 共用。
"""
from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.schemas.short_drama_writing import TestingScriptRequest


_LOCKWORD_ANCHORS = (
    "债务", "医院", "住院", "车票", "罚单", "短信", "电话", "转账", "清明",
    "上坟", "送站", "回乡", "彩礼", "葬礼", "拆迁", "补偿", "戒指", "遗书",
    "抚养费", "离婚", "结婚", "签字", "手术", "化疗", "检查", "确诊", "工地",
    "工厂", "工资", "裁员", "赔偿", "借条", "欠条", "存折", "存款", "押金", "定金",
)
_LOCKWORD_PATTERN = re.compile("|".join(_LOCKWORD_ANCHORS))
_NUM_LOCKWORD_PATTERN = re.compile(r"\d+(?:\.\d+)?\s*(?:万|千|百|元|块|天|周|月|年)")


def extract_episode_keywords(*texts: str) -> list[str]:
    """从摘要/冲突/钩子里抽取强约束名词（金额、事件物件、时间节点）。"""
    seen: dict[str, None] = {}
    for raw in texts:
        if not raw:
            continue
        for match in _LOCKWORD_PATTERN.findall(str(raw)):
            seen.setdefault(match.strip(), None)
        for match in _NUM_LOCKWORD_PATTERN.findall(str(raw)):
            seen.setdefault(match.strip(), None)
    return [k for k in seen.keys() if k][:12]


def build_lockword_block(req: "TestingScriptRequest") -> str:
    """构造关键名词锁：当前集必须见到的核心物件 + 未来集禁止提前消耗的剧透名词。"""
    must_show = extract_episode_keywords(
        req.episode_summary, req.episode_conflict, req.episode_hook
    )
    forbidden_set: dict[str, None] = {}
    cur_no = int(req.episode_no or 0)
    for item in (req.future_episode_briefs or []):
        if not isinstance(item, dict):
            continue
        try:
            ep = int(item.get("episode_no") or item.get("ep") or 0)
        except Exception:
            ep = 0
        if ep <= cur_no:
            continue
        for kw in extract_episode_keywords(
            str(item.get("summary") or ""),
            str(item.get("conflict") or ""),
            str(item.get("hook") or ""),
        ):
            if kw not in must_show:
                forbidden_set.setdefault(kw, None)
    forbidden = list(forbidden_set.keys())[:12]
    if not must_show and not forbidden:
        return ""
    lines = ["【关键名词锁】"]
    if must_show:
        lines.append("必须在本段或本集内出现（自然落地，不要堆砌）：" + "、".join(must_show))
    if forbidden:
        lines.append("禁止本集提前消耗（属于后续集情节点）：" + "、".join(forbidden))
    return "\n".join(lines)


_SEGMENT_INTENT_TEMPLATES: dict[str, str] = {
    "hook": "把摘要里最早能落地的真实生活动作/困境摊开，只兑现摘要的开端部分。",
    "validation": "围绕摘要中段的关系试探与现实摩擦推进半步，不允许把后段事件提前。",
    "explosion": "兑现摘要里最关键的情感临界点（病倒/错过/咽下去/转账/拥抱），但严格在摘要范围内。",
    "resolution": "落在摘要末尾的余波与未完成上，只为下一集留余地，不预告新事件。",
}


def build_segment_intent_block(req: "TestingScriptRequest") -> str:
    """把 episode_summary 自动拆为 4 段意图，本段只做本段份内事。"""
    sid = str(req.segment_id or "").strip().lower()
    intent = _SEGMENT_INTENT_TEMPLATES.get(sid)
    if not intent:
        return ""
    summary = str(req.episode_summary or "").strip()
    if not summary:
        return f"【本段意图】{intent}"
    return (
        f"【本段意图】{intent}\n"
        f"参考摘要：{summary[:160]}\n"
        "禁止把摘要里属于其他段的事件提前或推后到本段。"
    )
