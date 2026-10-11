"""测试页"剧本生成失败分类器"（从 short_drama_writing.py 抽出）。

输入：
- req: 当前测试页请求（要看 segment_id / mode 决定是哪种段）
- evaluation: 之前 _evaluate_testing_scene 算出来的状态字典
  （含 blocking_issues / quality_issues / warnings / ...）

输出：TestingFailureAnalysis Pydantic 对象，承载：
- failure_type：format_break / anchor_missing / dramatic_weakness / state_drift / local_patch_needed
- failed_segment / root_cause / fix_strategy
- repair_scope / rollback_recommendation
- evidence：触发判定的具体问题文本（≤3 条）

纯函数，没有 DB、AI、IO。便于单测和被 generate / validate / deep-audit / auto-fix 共用。
"""
from __future__ import annotations

from typing import Any, TYPE_CHECKING

from app.schemas.short_drama_writing import TestingFailureAnalysis

if TYPE_CHECKING:
    from app.schemas.short_drama_writing import TestingScriptRequest


def _is_patchable_local_issue(issue: str) -> bool:
    """判断单个 blocking_issue 是否属于"局部可修补、无须回滚"的小毛病。"""
    text = str(issue or "").strip()
    if not text:
        return False
    local_style_markers = (
        "OS过密",
        "OS位置不当",
        "抽象结尾",
        "通用物件补丁",
        "小说化描写",
        "放话式尾巴",
        "头部爆点后果弱",
    )
    if any(marker in text for marker in local_style_markers):
        return True
    positive_markers = (
        "场次标头",
        "动作行",
        "标准台词",
        "说明栏目",
        "净字数不足",
        "净字数超限",
        "冗长台词",
        "广播式",
    )
    negative_markers = (
        "输出为空",
        "主角",
        "承接重复",
        "上一段",
        "关系",
        "状态",
        "角色",
        "权力",
        "尾钩",
        "推进",
        "后果",
        "发虚",
        "停在",
    )
    return any(marker in text for marker in positive_markers) and not any(
        marker in text for marker in negative_markers
    )


def classify_testing_failure(
    req: "TestingScriptRequest",
    evaluation: dict[str, Any],
) -> TestingFailureAnalysis:
    """根据 evaluation 状态分类失败类型，给出修复策略与回滚建议。"""
    segment = str(req.segment_id or ("scene" if req.mode != "segment" else "hook"))
    blocking = [str(item).strip() for item in (evaluation.get("blocking_issues") or []) if str(item).strip()]
    quality_issues = [str(item).strip() for item in (evaluation.get("quality_issues") or []) if str(item).strip()]
    warnings = [str(item).strip() for item in (evaluation.get("warnings") or []) if str(item).strip()]
    evidence = (blocking + quality_issues + warnings)[:3]

    failure_type = "dramatic_weakness"
    root_cause = "当前段落有字面内容，但戏剧动作、后果或推进还不够稳。"
    fix_strategy = "补足动作后果，把关系/信息/权力至少推进一层。"
    repair_scope = "segment_rewrite"
    rollback = "rewrite_current_segment"

    format_markers = ("场次标头", "动作行", "缺少标准台词 / OS / VO 行", "说明栏目", "输出为空")
    if any(
        marker in issue
        for issue in blocking
        for marker in format_markers
    ):
        failure_type = "format_break"
        root_cause = "当前段主要卡在剧本格式，不是剧情方向问题。"
        fix_strategy = "先修场标、动作行和台词格式，尽量不改剧情主干。"
        repair_scope = (
            "patchable"
            if blocking and all(_is_patchable_local_issue(issue) for issue in blocking)
            else "segment_rewrite"
        )
        rollback = "rewrite_current_segment"
    elif any(("人物锚点不稳" in issue) or ("情绪锚点不足" in issue) for issue in blocking):
        failure_type = "anchor_missing"
        root_cause = "主角锚点没有立住，当前段的人物声音和情绪抓手都不够稳。"
        fix_strategy = "补主角具名台词或可拍动作，让他的损失、判断或反刺在当场可见。"
        repair_scope = "patchable" if segment == "scene" else "segment_rewrite"
        rollback = "rewrite_current_segment"
    elif any("主角" in issue and "未出场" in issue for issue in blocking):
        failure_type = "anchor_missing"
        root_cause = "主角锚点没有立住，后续段落会继续失焦。"
        fix_strategy = "补主角具名动作或台词，并让他的损失、目标或反刺在当场可见。"
        repair_scope = "segment_rewrite" if segment == "hook" else "rollback_previous"
        rollback = "rewrite_current_segment" if segment == "hook" else "rollback_previous_segment"
    elif any(any(token in issue for token in ("关系", "信息", "权力", "后果", "推进", "尾钩", "发虚", "停在", "动作")) for issue in quality_issues):
        failure_type = "dramatic_weakness"
        root_cause = "这段文字能读，但戏剧推进不够实，动作和后果还没有真正落地。"
        fix_strategy = "不要补解释，直接补试探、反刺、兑现、站队或未完成承诺。"
        repair_scope = "rollback_previous" if segment in ("explosion", "resolution") else "segment_rewrite"
        rollback = "rollback_previous_segment" if segment in ("explosion", "resolution") else "rewrite_current_segment"
    elif blocking and all(_is_patchable_local_issue(issue) for issue in blocking):
        failure_type = "local_patch_needed"
        root_cause = "当前段主要卡在局部可修问题，没必要回滚已确认段落。"
        fix_strategy = "只替换问题OS、抽象尾巴、通用物件补丁或格式字数问题，保留当前剧情骨架。"
        repair_scope = "patchable"
        rollback = "rewrite_current_segment"
    elif any("关系" in issue or "状态" in issue or "角色" in issue for issue in warnings):
        failure_type = "state_drift"
        root_cause = "正文和当前角色/状态卡之间出现了轻微漂移。"
        fix_strategy = "先对齐关系护栏和状态卡，再重写当前段的关键动作。"
        repair_scope = "rollback_previous" if segment != "hook" else "segment_rewrite"
        rollback = "rollback_previous_segment" if segment != "hook" else "rewrite_current_segment"

    return TestingFailureAnalysis(
        failure_type=failure_type,
        failed_segment=segment,
        root_cause=root_cause,
        fix_strategy=fix_strategy,
        repair_scope=repair_scope,
        rollback_recommendation=rollback,
        evidence=evidence,
    )
