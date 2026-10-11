"""测试页“字数规则 + 格式规则”构造（从 short_drama_writing.py 抽出）。

2 个纯函数，零 IO/AI/DB：

- build_testing_length_rule：根据时长/分段类型/请求字段算出本轮净字数目标区间
- build_testing_format_rule：构造场次标头/动作行/台词/独白/续写的格式约束

被 generate / auto-fix / structured update 等多个 endpoint 共用。
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from app.services.duration_profile_service import infer_duration_profile

if TYPE_CHECKING:
    from app.schemas.short_drama_writing import TestingScriptRequest


def build_testing_length_rule(req: "TestingScriptRequest") -> str:
    profile = infer_duration_profile(
        episode_minutes=req.episode_minutes,
        explicit_min=req.word_count_min,
        explicit_max=req.word_count_max,
        explicit_target=req.word_count_target or req.target_chars,
        market_format=req.format_type or req.project_type,
    )

    if req.mode == "segment":
        segment = str(req.segment_id or "hook")
        seg_target = int(req.word_count_target or 0)
        if not seg_target:
            segment_ratio = {
                "hook": 0.24,
                "validation": 0.26,
                "explosion": 0.30,
                "resolution": 0.20,
            }.get(segment, 0.25)
            seg_target = max(120, int(round(profile.target_chars * segment_ratio)))
        seg_min = int(req.word_count_min or max(120, seg_target - 50))
        seg_max = int(req.word_count_max or max(seg_min + 40, seg_target + 50))
        count_scope = "不含标点符号和空白" if req.exclude_punctuation_for_count else "含标点符号"
        return (
            f"【字数交付区间】当前只写 {segment} 分段，本段净字数应落在 {seg_min}～{seg_max} 字之间（{count_scope}，目标约 {seg_target} 字）。"
            " 请以目标字数为中心写作，不要把上限当成目标。"
            " 低于下限会导致本段信息量不足；高于上限会挤压后续分段。"
            " 接近区间边界的轻微偏差可以交给用户确认，但不要把明显不足的内容当成合格初稿。"
            " 写到目标字数附近就自然停笔，不要再加新动作、新对白、新人物。"
            " 四段累计完成后，再回到整场总字数校验。"
            " 若剧情装不下，必须把推进留给后续分段，本段绝对不可写成整集体量。"
        )

    count_scope = "不含标点符号和空白" if req.exclude_punctuation_for_count else "含标点符号"
    target_text = f"，目标约 {profile.target_chars} 字"
    return (
        f"本轮输出净字数交付区间为 {profile.min_chars}～{profile.max_chars} 字（{count_scope}{target_text}，按 90秒=1200纯字符基准换算，当前时长约 {profile.duration_seconds} 秒）。"
        " 请以目标字数为中心写作，不要把上限当成目标。"
        " 低于下限通常意味着剧情动作、对白或场面推进没有写够；高于上限通常意味着本集塞入过多信息。"
        " 接近区间边界的轻微偏差可以交给用户确认；明显低于下限不能当成合格初稿。"
        " 优先保证剧情、冲突和场面完整。"
        " 若剧情装不下，宁可把多余推进拆到下一集，也不要把本集硬挤爆。"
    )


def build_testing_format_rule(req: "TestingScriptRequest") -> str:
    # 续写片段（非 hook 的分段模式）：允许剧情自然进入新场，但禁止重复上一段场标。
    is_continuation = req.mode == "segment" and req.segment_id not in (None, "hook")
    if is_continuation:
        return "\n".join([
            "- 续写片段：优先直接从△动作描述或角色对白承接上一段",
            "- 如果剧情确实切换到新地点/新时间/新场面，可以自然另起下一场场次标头；不得重复上一段已有场标",
            "- 动作行：△动作描述内容（独占一行）",
            "- 台词：角色名：台词内容",
            "- 独白：角色名OS：内容  或  角色名（情绪）OS：内容",
        ])

    # 开场场景（hook 段或普通场景模式）：完整格式规则
    header_example = "【场1-1：夜  内  江家书房】" if req.scene_header_style == "bracket" else "1-1  日  外  战场"
    rules = [
        f"- 场次标头使用 `{req.scene_header_style}` 模式，示例：{header_example}",
        "- 动作行必须以 `△` 起笔，禁止写成 [动作：xxx] 或 [对白：xxx] 说明栏格式",
        "- 台词写法：角色名：台词内容",
        "- 内心独白写法：角色名OS：内容  或  角色名（情绪）OS：内容",
        "- 离镜画外音写法：VO（角色名）：内容",
    ]
    if str(req.current_content or "").strip():
        rules.append("- 当前已有正文，本轮只续写新增片段，不得重复前文；如进入新场，可自然另起下一场场次标头。")
    else:
        rules.append("- 当前编辑区为空，本轮起笔从本集第一场场次标头开始，直接进入动作和对白。")
    return "\n".join(rules)
