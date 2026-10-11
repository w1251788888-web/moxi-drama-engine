"""短剧测试页文本格式 / 字数 / 截断 工具（从 short_drama_writing.py 抽出）。

- normalize_counting_text: 去空白和标点（按需）
- count_testing_chars: 净字数计数
- hard_truncate_by_sentence: 净字超额时按句号边界硬截
- is_testing_header_line: 判断是否场标题行（【场1-1：...】或 1-1 夜 内 ...）
- testing_header_key: 提取场标的 episode/scene 编号，用于判断是否重复场标

所有函数纯字符串处理。
"""
from __future__ import annotations

import re
import unicodedata


def normalize_counting_text(text: str, *, exclude_punctuation: bool) -> str:
    chars: list[str] = []
    for ch in str(text or ""):
        if ch.isspace():
            continue
        cat = unicodedata.category(ch)
        if exclude_punctuation and (cat.startswith("P") or cat.startswith("S")):
            continue
        chars.append(ch)
    return "".join(chars)


def count_testing_chars(text: str, *, exclude_punctuation: bool) -> int:
    return len(normalize_counting_text(text, exclude_punctuation=exclude_punctuation))


def hard_truncate_by_sentence(text: str, max_chars: int, *, exclude_punct: bool = True) -> str:
    """段级硬截断：当净字数超过 max 的可接受缓冲时，按句号/换行确定性裁剪。

    分段精写本来就应该短而准；这里给一个很小的缓冲，避免模型轻微超字数时
    被切在半句里，同时防止 200 字段落漂成整集体量。中性、无 LLM 调用。
    """
    if not text or max_chars <= 0:
        return text
    current = count_testing_chars(text, exclude_punctuation=exclude_punct)
    buffer = min(30, max(10, int(max_chars * 0.12)))
    if current <= max_chars + buffer:
        return text
    cap = max_chars + buffer
    out_lines: list[str] = []
    accum = 0
    sentence_breakers = "。！？!?…；;"
    for line in text.splitlines():
        line_chars = count_testing_chars(line, exclude_punctuation=exclude_punct)
        if accum + line_chars <= cap:
            out_lines.append(line)
            accum += line_chars
            continue
        remaining = cap - accum
        if remaining < 20:
            break
        truncated_line = ""
        safe_line = ""
        for ch in line:
            truncated_line += ch
            seg_count = count_testing_chars(truncated_line, exclude_punctuation=exclude_punct)
            if ch in sentence_breakers and seg_count >= remaining * 0.7:
                safe_line = truncated_line
                break
            if ch in sentence_breakers:
                safe_line = truncated_line
            if seg_count >= remaining:
                break
        if safe_line.strip():
            out_lines.append(safe_line.rstrip())
        break
    result = "\n".join(out_lines).rstrip()
    return result if result else text


def is_testing_header_line(line: str) -> bool:
    text = str(line or "").strip()
    if not text:
        return False
    return bool(
        re.match(r"^【场\d+(?:-\d+)?：.+】$", text)
        or re.match(r"^\d+(?:-\d+)?\s+\S+\s+[内外]\s+\S+", text)
    )


def testing_header_key(line: str) -> tuple[int, int] | None:
    """Return ``(episode, scene)`` for a testing script header when present."""
    text = str(line or "").strip()
    if not text:
        return None
    bracket = re.match(r"^【场(\d+)(?:-(\d+))?：.+】$", text)
    if bracket:
        return (int(bracket.group(1)), int(bracket.group(2) or 1))
    plain = re.match(r"^(\d+)(?:-(\d+))?\s+\S+\s+[内外]\s+\S+", text)
    if plain:
        return (int(plain.group(1)), int(plain.group(2) or 1))
    return None
