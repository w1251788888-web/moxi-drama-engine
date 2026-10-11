"""按集切片 beat_sheet / novel_analysis 的纯函数（从 short_drama_writing.py 抽出）。

2 个纯函数，零 IO/AI/DB：

- slice_beat_sheet_by_episode：从全量 beat_sheet 文本中切出指定集的段落
- slice_novel_anchor_by_episode：从 novel_analysis 全文里切出本集对应的原著锚点行

兼容多种章节头：### 第 1 集 / ## 第1集 / 第 1 集 / EP1 / Episode 1
"""
from __future__ import annotations

import re


# 兼容多种章节头：### 第 1 集 / ## 第1集 / 第 1 集 / EP1 / Episode 1
_BEAT_EP_HEAD_RE = re.compile(
    r"(?:^|\n)\s*(?:#+\s*)?[\*_]*\s*(?:第\s*(\d{1,3})\s*集|EP\s*(\d{1,3})|Episode\s*(\d{1,3}))[\*_]*[^\n]*",
    flags=re.IGNORECASE,
)


def slice_beat_sheet_by_episode(beat_sheet_text: str, episode_no: int) -> str:
    """从全量 beat_sheet 文本中切出第 episode_no 集的段落；切不到返回空串。"""
    if not beat_sheet_text or episode_no <= 0:
        return ""
    text = str(beat_sheet_text)
    matches: list[tuple[int, int, int]] = []  # (ep_no, start_pos, end_pos_of_header)
    for m in _BEAT_EP_HEAD_RE.finditer(text):
        ep_str = m.group(1) or m.group(2) or m.group(3)
        try:
            ep_n = int(ep_str)
        except Exception:
            continue
        matches.append((ep_n, m.start(), m.end()))
    if not matches:
        return ""
    target_idx = -1
    for i, (ep_n, _s, _e) in enumerate(matches):
        if ep_n == episode_no:
            target_idx = i
            break
    if target_idx < 0:
        return ""
    start = matches[target_idx][1]
    end = matches[target_idx + 1][1] if target_idx + 1 < len(matches) else len(text)
    return text[start:end].strip()


# 兼容形如 "第1集：原著第X章……" / "EP3 — 章节 4-6 ……" 等表格行/段落
_NOVEL_ANCHOR_LINE_RE = re.compile(
    r"^[\s\|\-]*(?:第\s*(\d{1,3})\s*集|EP\s*(\d{1,3})|Episode\s*(\d{1,3}))[\s\|\-:：→\-]+(.+?)\s*$",
    flags=re.IGNORECASE | re.MULTILINE,
)


def slice_novel_anchor_by_episode(novel_analysis_text: str, episode_no: int) -> str:
    """从 novel_analysis 全文里切出本集对应的原著锚点行。"""
    if not novel_analysis_text or episode_no <= 0:
        return ""
    text = str(novel_analysis_text)
    for m in _NOVEL_ANCHOR_LINE_RE.finditer(text):
        ep_str = m.group(1) or m.group(2) or m.group(3)
        try:
            ep_n = int(ep_str)
        except Exception:
            continue
        if ep_n == episode_no:
            return f"第{episode_no}集 → {m.group(4).strip()}"
    return ""
