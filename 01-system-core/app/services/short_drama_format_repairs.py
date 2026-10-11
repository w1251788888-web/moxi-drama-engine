"""测试页"剧本格式硬修复 + 场标头规范化"工具（从 short_drama_writing.py 抽出）。

四个纯文本工具，零 IO、零 DB、零 AI：

- normalize_testing_generated_content：当 mode=segment 且非 hook 时，只去掉重复场标头，允许自然进入新场
- expected_testing_scene_header：根据 req.scene_header_style 生成期望的场次标头（【场1-1：...】 或 1-1  日 内 ...）
- apply_testing_hard_repairs：把生成结果做最小硬修复（裁剪空行、补/换场标头、把"动作："转成"△"、必要时补一行△动作）
- detect_segment_overlap_issue：检测 segment 模式下当前段开头与上一段尾巴的字面重复（>=0.55 视为重写）

被 generate / validate / deep-audit / auto-fix 多个 endpoint 共用，搬到 services 后调用方都用 import。
"""
from __future__ import annotations

import difflib
import re
from typing import TYPE_CHECKING

from app.services.short_drama_text_format import is_testing_header_line, testing_header_key

if TYPE_CHECKING:
    from app.schemas.short_drama_writing import TestingScriptRequest


def _last_testing_header_key(text: str) -> tuple[int, int] | None:
    for line in reversed(str(text or "").splitlines()):
        key = testing_header_key(line)
        if key:
            return key
    return None


def _drop_first_line(lines: list[str]) -> list[str]:
    if lines:
        lines.pop(0)
        while lines and not lines[0].strip():
            lines.pop(0)
    return lines


def normalize_testing_generated_content(req: "TestingScriptRequest", content: str) -> str:
    """Trim duplicate continuation headers while preserving legitimate new scenes."""
    text = str(content or "").strip()
    if not text:
        return ""

    if req.mode == "segment" and req.segment_id not in (None, "hook"):
        lines = [line.rstrip() for line in text.splitlines()]
        while lines and not lines[0].strip():
            lines.pop(0)
        if lines:
            first_key = testing_header_key(lines[0])
            last_key = _last_testing_header_key(str(req.current_content or ""))
            if first_key and last_key and first_key == last_key:
                lines = _drop_first_line(lines)
        text = "\n".join(lines).strip()

    return text


def expected_testing_scene_header(req: "TestingScriptRequest", existing_line: str = "") -> str:
    """生成期望的场次标头（兼容 bracket 与 plain 两种风格）。"""
    ep_no = max(1, int(req.episode_no or 1))
    sc_no = max(1, int(req.scene_no or 1))
    raw = str(existing_line or "").strip()
    fallback_suffix = "日  内  本集主场"

    if req.scene_header_style == "bracket":
        suffix = ""
        match = re.match(r"^【?场?\d+(?:-\d+)?[：:](.+?)】?$", raw)
        if match:
            suffix = str(match.group(1) or "").strip()
        elif raw and "：" in raw:
            suffix = raw.split("：", 1)[-1].strip("】 ").strip()
        elif raw and ":" in raw:
            suffix = raw.split(":", 1)[-1].strip("】 ").strip()
        suffix = suffix or fallback_suffix
        return f"【场{ep_no}-{sc_no}：{suffix}】"

    suffix = ""
    match = re.match(r"^\d+-\d+\s+(.+)$", raw)
    if match:
        suffix = str(match.group(1) or "").strip()
    suffix = suffix or fallback_suffix
    return f"{ep_no}-{sc_no}  {suffix}"


def apply_testing_hard_repairs(req: "TestingScriptRequest", content: str) -> str:
    """对生成结果做最小硬修复：裁空行、修场标头、把"动作："转成"△"、必要时补一行△动作。"""
    text = normalize_testing_generated_content(req, content)
    if not text:
        return text

    lines = [line.rstrip() for line in text.splitlines()]
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    if not lines:
        return ""

    require_header = not str(req.current_content or "").strip()
    if req.mode == "segment" and req.segment_id not in (None, "hook"):
        require_header = False

    if require_header:
        if is_testing_header_line(lines[0]):
            expected_header = expected_testing_scene_header(req, lines[0])
            if lines[0].strip() != expected_header:
                lines[0] = expected_header
        else:
            lines.insert(0, expected_testing_scene_header(req))
    elif lines and is_testing_header_line(lines[0]):
        first_key = testing_header_key(lines[0])
        last_key = _last_testing_header_key(str(req.current_content or ""))
        if first_key and last_key and first_key == last_key:
            lines = _drop_first_line(lines)

    action_line_exists = any(str(line or "").lstrip().startswith("△") for line in lines)
    for idx, line in enumerate(lines):
        stripped = str(line or "").strip()
        if not stripped:
            continue
        if stripped.startswith("动作："):
            lines[idx] = "△ " + stripped.split("：", 1)[-1].strip()
            action_line_exists = True

    if not action_line_exists:
        for idx, line in enumerate(lines):
            stripped = str(line or "").strip()
            if not stripped or is_testing_header_line(stripped):
                continue
            if re.match(r"^[^：\s]{1,20}(?:（[^）]+）)?(?:OS|VO)?：.+", stripped):
                continue
            lines[idx] = "△ " + stripped.lstrip("△ ").strip()
            action_line_exists = True
            break

    return "\n".join(line for line in lines if str(line or "").strip()).strip()


def detect_segment_overlap_issue(req: "TestingScriptRequest", content: str) -> str:
    """segment 模式下检测当前段开头与上一段尾巴的字面重复（>=0.55 视为'重写而非推进'）。"""
    if req.mode != "segment" or (req.segment_id or "hook") == "hook":
        return ""

    previous = str(req.current_content or "").strip()
    current = str(content or "").strip()
    if not previous or not current:
        return ""

    previous_tail = re.sub(r"\s+", "", previous[-220:])
    current_head = re.sub(r"\s+", "", current[:220])
    if not previous_tail or not current_head:
        return ""

    similarity = difflib.SequenceMatcher(None, previous_tail, current_head).ratio()
    if similarity >= 0.55:
        return f"当前{req.segment_id}段与上一段承接重复度过高（{similarity:.2f}），像在重写上一段而不是往前推进。"
    return ""
