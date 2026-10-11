"""测试页"头部对标 + 局部硬伤检测"工具（从 short_drama_writing.py 抽出）。

本模块封装"对标头部短剧的硬伤检测 + 评分封顶"逻辑：

- _TESTING_*：检测用关键词/正则常量集合
- detect_testing_local_patch_issues：检测 OS 过密/位置不当、抽象结尾、小说化、模板补丁污染等局部硬伤
- detect_testing_head_quality_issues：检测开篇钩子弱、对白超长、爆点后果弱、反派模板化、终局闭环不足等头部质感硬伤
  （需要外部传入 contract dict，避免与 router 内 _current_testing_episode_contract 形成循环依赖）
- apply_testing_benchmark_caps：把检测出的硬伤翻译成 BenchmarkAssessment 评分封顶
- fallback_benchmark_assessment：LLM 深审走丢时的兜底评分（带 cap 兜底）
- dialogue_body_for_testing：从 "角色：台词" 行提取台词正文

零 AI、零 DB、零 IO。
"""
from __future__ import annotations

import re
from typing import Any, TYPE_CHECKING

from app.schemas.short_drama_writing import BenchmarkAssessment
from app.services.short_drama_quality_anchors import infer_testing_sample_track
from app.services.short_drama_seam_continuity import (
    testing_os_line_count,
    testing_script_body_lines,
)
from app.services.short_drama_genre_consequence import assess_consequence_gate
from app.services.short_drama_testing_blocks import string_list
from app.services.short_drama_text_format import count_testing_chars

if TYPE_CHECKING:
    from app.schemas.short_drama_writing import TestingScriptRequest


_TESTING_GENERIC_PROP_PATCH_HINTS = ("合同边角沾着面粉", "手机屏幕还亮着录音红点")
_TESTING_ABSTRACT_ENDING_HINTS = (
    "真相即将",
    "新的开始",
    "背影坚定",
    "坚定而有力",
    "一定会坚持",
    "不会放弃",
    "事情还没完",
    "才刚刚开始",
    "不过是开始",
    "心更加紧密",
    "预示着",
)
_TESTING_NOVELISTIC_HINTS = (
    "仿佛", "似乎", "眼神中", "目光复杂", "心里一沉", "内心",
    "他知道", "心中", "不易察觉", "意味深长", "气氛",
)
_TESTING_GENERIC_VILLAIN_LINES = (
    "别得意太早", "这事儿还没完", "这事还没完", "等着瞧", "走着瞧",
    "还有后招", "不会放过", "才刚刚开始",
)
_TESTING_CONCRETE_PRESSURE_TOKENS = (
    "投诉", "封条", "罚单", "律师函", "合同", "断供", "降价", "退款", "订单取消", "房东", "涨租",
    "供应商", "检测", "回执", "封存", "处罚", "停业", "查封", "备案", "热榜", "评论区", "排队散",
    "顾客退", "摊车", "订单", "押金", "批号", "原料", "出生证明", "亲子鉴定", "证件", "证据",
    "把柄", "监控", "截图", "录音", "纸角", "纸页", "文件", "抽走", "扯出", "抢走",
)
_TESTING_PUBLIC_CONSEQUENCE_TOKENS = (
    "当场", "门口", "围观", "街坊", "顾客", "记者", "直播", "评论区", "热榜", "封条", "停业", "退款",
    "订单", "排队", "罚款", "处罚", "签收", "回执", "名单", "备案", "站队", "录下", "看见",
    "乘客", "司机", "后视镜", "手机镜头", "镜头", "拍下", "拍着", "回头", "举起手机",
)
_TESTING_TEMPLATE_PATCH_REGEX = (r"第\d+笔账", r"第\d+份留样", r"第\d+张检测单")
_TESTING_TEMPLATE_PATCH_HINTS = ("不能只说结果", "合同边角沾着面粉", "录音红点", "这才是第一步")

_TESTING_OPENING_PRESSURE_TOKENS = (
    "羞辱", "威胁", "逼", "赶出", "退婚", "解约", "开除", "封杀", "追债", "掌掴",
    "踩", "扔", "抢", "跪", "罚", "死", "倒计时", "系统", "金手指", "觉醒", "重生",
    "穿越", "废物", "不配", "滚", "跪下", "围观", "当场", "合同", "封条", "罚单",
)
_TESTING_SATISFACTION_BEAT_TOKENS = (
    "打脸", "反击", "亮出", "揭开", "证据", "录音", "回执", "封条", "查封", "处罚",
    "退款", "订单取消", "围观", "站队", "震惊", "跪", "认错", "道歉", "系统", "觉醒",
    "升级", "碾压", "翻盘", "身份", "真相", "名单", "检测", "热榜", "直播", "当场",
    "倒计时", "停住", "做完", "解开", "答对", "对了", "正确", "笑声卡住", "全班",
    "举手机", "白光", "裂纹", "排名墙", "红圈", "草稿纸",
)


def _testing_consequence_context(req: "TestingScriptRequest") -> str:
    return "\n".join([
        str(req.project_type or ""),
        str(req.audience_axis or ""),
        str(req.genre_main or ""),
        str(req.genre_sub or ""),
        str(req.brief or ""),
        str(req.worldview or ""),
        str(req.conflict or ""),
        str(req.episode_summary or ""),
        str(req.episode_conflict or ""),
        str(req.episode_hook or ""),
    ])


def detect_testing_local_patch_issues(req: "TestingScriptRequest", content_text: str) -> list[str]:
    """检测局部硬伤：OS 过密/位置不当、抽象结尾、小说化描写、模板补丁污染。"""
    lines = testing_script_body_lines(content_text)
    if not lines:
        return []

    issues: list[str] = []
    os_count = testing_os_line_count(content_text)
    if os_count > 2:
        issues.append(f"OS过密：本集出现 {os_count} 处内心独白，现实题材最多保留1-2处。")
    head_tail_lines = [*lines[:3], *lines[-3:]]
    if any(re.match(r"^[^：:\n]{1,16}(?:（[^）]{1,12}）)?OS[：:].+", line) for line in head_tail_lines):
        issues.append("OS位置不当：开头或结尾不应使用OS承载情绪，需改成动作、物件或对手反应。")

    generic_hits = sum(content_text.count(hint) for hint in _TESTING_GENERIC_PROP_PATCH_HINTS)
    if generic_hits >= 2:
        issues.append("通用物件补丁重复：出现固定合同/录音红点补丁，需改成本集真实物件、证据或动作。")

    tail_block = "\n".join(lines[-3:])
    if any(hint in tail_block for hint in _TESTING_ABSTRACT_ENDING_HINTS):
        issues.append("抽象结尾：最后3行停在决心、预示或概括情绪，需落到可拍动作/物件/证据。")

    novelistic_count = sum(content_text.count(hint) for hint in _TESTING_NOVELISTIC_HINTS)
    if novelistic_count >= 3:
        issues.append(f"小说化描写过多：出现 {novelistic_count} 处仿佛/似乎/眼神中/气氛等不可拍表达。")
    if any(re.search(pattern, content_text) for pattern in _TESTING_TEMPLATE_PATCH_REGEX) or any(
        hint in content_text for hint in _TESTING_TEMPLATE_PATCH_HINTS
    ):
        issues.append("项目打磨模板污染：出现机械账目/留样/通用物件补丁，需改成本集真实动作和真实物件。")
    return list(dict.fromkeys(issues))[:4]


def dialogue_body_for_testing(line: str) -> str:
    """从 '角色：台词' / '角色:台词' 行里提取台词正文部分。"""
    if "：" in line:
        return line.split("：", 1)[1].strip()
    if ":" in line:
        return line.split(":", 1)[1].strip()
    return ""


def detect_testing_head_quality_issues(
    req: "TestingScriptRequest",
    content_text: str,
    contract: dict[str, Any] | None = None,
) -> list[str]:
    """检测头部短剧质感硬伤：开篇钩子、台词长度、爆点后果、反派模板、终局闭环。

    contract: 由调用方传入的"当前集契约"，避免与主 router 形成循环依赖。
    """
    text = str(content_text or "").strip()
    lines = testing_script_body_lines(text)
    if not text or not lines:
        return []

    issues: list[str] = []
    contract = contract or {}
    segment = str(req.segment_id or ("scene" if req.mode == "scene" else "")).strip()
    is_manga_like = any(
        marker in str(value or "")
        for value in (req.project_type, req.format_type)
        for marker in ("漫剧", "AI漫剧", "沙雕漫", "拟真")
    )
    opening_text = "\n".join(lines[:5])
    if (
        is_manga_like
        and int(req.episode_no or 1) <= 3
        and segment in {"hook", "scene"}
        and not any(token in opening_text for token in _TESTING_OPENING_PRESSURE_TOKENS)
    ):
        issues.append("开篇钩子弱：漫剧前三集开头前5行缺少羞辱/威胁/代价/身份差/异常或金手指触发。")
    dialogue_bodies = [dialogue_body_for_testing(line) for line in lines if dialogue_body_for_testing(line)]
    long_dialogues = [body for body in dialogue_bodies if count_testing_chars(body, exclude_punctuation=True) > 30]
    if len(long_dialogues) >= 2:
        issues.append(f"头部台词短句化不足：出现 {len(long_dialogues)} 句超过30净字的对白，应拆成短句和动作。")

    consequence_gate = assess_consequence_gate(
        text,
        context_text=_testing_consequence_context(req),
        contract=contract,
    )
    has_pressure = bool(consequence_gate["has_public_pressure"])
    has_consequence = bool(consequence_gate["has_consequence"])
    pressure_required = bool(contract.get("public_pressure") or contract.get("real_loss")) or segment in {"hook", "explosion", "scene"}
    if pressure_required:
        if segment == "hook":
            if not has_pressure:
                issues.append("开篇钩子弱：钩子段缺少当场压迫、抢夺、逼问、发现或被迫选择，无法支撑用户继续确认下一段。")
        elif segment in {"explosion", "scene"} and not (has_pressure and has_consequence):
            issues.append("头部爆点后果弱：本集契约要求公开压迫和当场后果，但正文缺少本题材内成立的可拍代价、证据变化、关系变化或第三方反应。")

    if is_manga_like and segment == "scene":
        try:
            duration_seconds = int(round(float(req.episode_minutes or 1.5) * 60))
        except Exception:
            duration_seconds = 90
        expected_beats = 2 if duration_seconds <= 90 else 3
        beat_hits = sum(1 for token in _TESTING_SATISFACTION_BEAT_TOKENS if token in text)
        if beat_hits < expected_beats:
            issues.append(
                f"爽点密度不足：当前约{duration_seconds}秒漫剧至少需要{expected_beats}个可见爽点/信息增量，正文只命中{beat_hits}个。"
            )

    tail_text = "\n".join(lines[-4:])
    tail_gate = assess_consequence_gate(
        tail_text,
        context_text=_testing_consequence_context(req),
        contract=contract,
    )
    if any(token in tail_text for token in _TESTING_GENERIC_VILLAIN_LINES) and not tail_gate["has_consequence"]:
        issues.append("反派压制模板化：结尾或反派台词只放狠话，缺少合同、投诉、断供、检测、低价围堵等具体动作。")

    if any(re.search(pattern, text) for pattern in _TESTING_TEMPLATE_PATCH_REGEX) or any(hint in text for hint in _TESTING_TEMPLATE_PATCH_HINTS):
        issues.append("项目打磨模板污染：出现机械账目/留样/通用物件补丁，需改成本集真实动作和真实物件。")

    if int(req.episode_no or 0) >= int(req.episode_count or 0):
        finale_tail = "\n".join(lines[-6:])
        open_tail_tokens = ("法律文件", "希望不是坏消息", "这事还没完", "这事儿还没完", "还有后招", "一起面对", "才刚刚开始")
        closure_tokens = ("停业整顿", "处罚", "查封", "撤牌", "拆下", "平价", "招工", "下岗", "就业", "标杆", "重新开张", "退款")
        if any(token in finale_tail for token in open_tail_tokens) and not any(token in text for token in closure_tokens):
            issues.append("终局闭环不足：最后一集仍留下续集式钩子，没有收实处罚、店铺、就业或街坊信任。")

    return list(dict.fromkeys(issues))[:5]


def apply_testing_benchmark_caps(
    req: "TestingScriptRequest",
    benchmark: BenchmarkAssessment,
    evaluation: dict[str, Any],
    episode_text: str,
    contract: dict[str, Any] | None = None,
) -> BenchmarkAssessment:
    """把局部硬伤翻译成 BenchmarkAssessment 评分封顶。"""
    text = str(episode_text or evaluation.get("content") or req.episode_content or "")
    local_issues = list(dict.fromkeys([
        *detect_testing_local_patch_issues(req, text),
        *detect_testing_head_quality_issues(req, text, contract),
    ]))
    if not local_issues:
        return benchmark

    cap = int(benchmark.score or 0) or 92
    cap_reasons: list[str] = []
    for issue in local_issues:
        if "通用物件补丁" in issue:
            cap = min(cap, 70)
            cap_reasons.append("通用物件补丁重复：终稿打磨污染当前集物件，RAG头部对标封顶70。")
        elif "OS过密" in issue or "OS位置不当" in issue:
            cap = min(cap, 75)
            cap_reasons.append("OS控制未达头部短剧标准，现实冲突被内心独白稀释。")
        elif "抽象结尾" in issue:
            cap = min(cap, 78)
            cap_reasons.append("结尾未停在可拍动作/物件/证据，头部爆点质感封顶78。")
        elif "小说化描写" in issue:
            cap = min(cap, 80)
            cap_reasons.append("小说化描写过多，现实可拍性与短剧质感封顶80。")
        elif "头部爆点后果弱" in issue:
            cap = min(cap, 72)
            cap_reasons.append("公开压迫或当场后果没有落成可拍结果，头部短剧爆点封顶72。")
        elif "反派压制模板化" in issue:
            cap = min(cap, 74)
            cap_reasons.append("反派只放狠话而没有现实压制动作，头部对抗质感封顶74。")
        elif "项目打磨模板污染" in issue:
            cap = min(cap, 70)
            cap_reasons.append("局部修复留下机械模板句，RAG头部对标封顶70。")
        elif "终局闭环不足" in issue:
            cap = min(cap, 76)
            cap_reasons.append("终局仍保留续集式钩子，闭环质感封顶76。")

    benchmark.score = min(int(benchmark.score or 0) or cap, cap)
    benchmark.gaps = list(dict.fromkeys([*(benchmark.gaps or []), *cap_reasons]))[:4]
    benchmark.rule_upgrades = list(dict.fromkeys([
        *(benchmark.rule_upgrades or []),
        "项目结束态打磨必须优先替换OS、抽象尾巴和通用物件补丁；不得把固定道具句跨集复用。",
    ]))[:4]
    if benchmark.score < 85 or benchmark.gaps:
        benchmark.passed = False
    if cap_reasons:
        benchmark.summary = "当前文本存在可局部修复的头部质感硬伤，已按人工对标标准封顶。"[:160]
    return benchmark


def fallback_benchmark_assessment(
    req: "TestingScriptRequest",
    evaluation: dict[str, Any],
    contract: dict[str, Any] | None = None,
) -> BenchmarkAssessment:
    """LLM 深审走丢时的兜底头部对标评分（带 cap 兜底）。"""
    track_name, _ = infer_testing_sample_track(req)
    blocking = len(evaluation.get("blocking_issues") or [])
    quality_issues = string_list(evaluation.get("quality_issues"), limit=3)
    warnings = string_list(evaluation.get("warnings"), limit=2)
    score = 92
    score -= min(blocking, 3) * 12
    score -= min(len(quality_issues), 3) * 6
    score -= min(len(warnings), 2) * 3
    score = max(45, min(98, score))
    gaps = string_list(evaluation.get("blocking_issues"), limit=3) or quality_issues
    matched_signals = [
        "已命中当前赛道推进器",
        "当前文本满足基础格式与节奏底线",
    ]
    if evaluation.get("quality_passed"):
        matched_signals.append("内部审段已判定为可放行文本")
    benchmark = BenchmarkAssessment(
        track_name=track_name,
        score=score,
        passed=score >= 85 and not blocking,
        summary="已按头部短剧锚点做回退评估。" if not gaps else "当前文本与头部样板仍有明显差距。",
        matched_signals=matched_signals[:3],
        gaps=gaps,
        rule_upgrades=[
            "若同类问题重复出现，应把缺口沉淀进项目规则层。",
        ] if gaps else [],
    )
    return apply_testing_benchmark_caps(
        req,
        benchmark,
        evaluation,
        str(req.episode_content or evaluation.get("content") or ""),
        contract,
    )
