"""测试页"叙事漂移检测器"（从 short_drama_writing.py 抽出）。

只在 mode=scene 时启用。识别 5 类剧情漂移：

- 本集开局与前集已落地结果重复度过高（重复开局）
- 同一笔核心债务被多个主体口径承担，缺少澄清谁是真主体（核心债务漂移）
- 关键文书/规则同时出现在民间/族内/官方多个层级，缺少效力分层澄清（婚书/文书体系混乱）
- 民间线索直接跳成官方闭环证据，缺少送证/核验/移交的桥接动作（官方闭环证据跳跃）
- 关键人物立场在缺少触发事件和过渡反应的情况下突然翻转（角色转向跳变）

所有判定都是基于关键词集合 + difflib + 字符串匹配，零 AI/IO/DB。
"""
from __future__ import annotations

import difflib
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.schemas.short_drama_writing import TestingScriptRequest


def normalize_testing_story_text(text: str) -> str:
    """把任意文本压成"只剩中英文 + 数字"的紧凑串，用于做 fuzzy 字符比对。"""
    return re.sub(r"[\s\W_]+", "", str(text or ""), flags=re.UNICODE)


def contains_testing_story_markers(text: str, markers: list[str]) -> bool:
    """字符串包含任一 marker 即为命中。"""
    return any(marker in text for marker in markers)


# ----- 重复开局：重置型动作节点 -----
_RESET_MARKERS = [
    "顶债", "婚书", "退婚文书", "拖着", "带走", "当众", "截下", "赵家门",
    "围观", "上车", "暴雨", "雨夜", "拦车", "拉住", "闯进", "堵门",
    "跟我走", "带回家", "先住我这", "宣布", "下跪", "签字", "回家",
]

# ----- 核心债务漂移 -----
_DEBT_SCOPE_MARKERS = [
    "债", "顶债", "债本", "赌债", "木料款", "欠条", "欠账", "欠款", "贷款",
    "主贷人", "借款人", "担保", "代偿", "赔偿", "医药费", "工程款", "公账",
]
_DEBT_CLARIFIERS = [
    "原始", "篡改", "改口", "嘴上", "账上", "实际上", "其实", "伪造", "冒名",
    "只认", "改成", "转嫁", "挂名", "担保人", "代签", "被写成", "被挂到",
]
_DEBT_GROUPS = {
    "长辈责任": ["你爹", "她爹", "父债", "父亲的债", "你妈", "她妈", "母亲的债", "家里欠的", "苏父", "木料款"],
    "手足责任": ["弟债", "替弟", "你弟", "弟欠", "赌债", "你妹", "你哥", "哥哥欠的", "姐姐欠的", "弟弟欠的", "妹妹欠的"],
    "配偶责任": ["前夫", "前妻", "丈夫欠的", "老公欠的", "老婆欠的", "配偶的债", "婚内欠款"],
    "本人/冒名责任": ["写的是她的名字", "写的是苏小禾", "写的是苏棠", "她名字", "苏小禾", "苏棠名字", "主贷人是你", "借款人是你", "写的是你妈的名字", "写的是我的名字", "本人签的"],
    "组织责任": ["公司", "公账", "厂里", "店里", "项目组", "工作室", "平台欠的", "公司的账", "公司的公账"],
}

# ----- 婚书/文书体系分层 -----
_LAYERED_SETTING_GROUPS = {
    "民间/私下文书": ["介绍信", "私契", "退婚文书", "退婚书", "婚书", "口头婚约", "婚约", "契书"],
    "族内/组织裁定": ["族规", "族中正约", "宗族裁定", "家法", "祖谱", "印匣", "族老"],
    "官方/制度结论": ["民政局", "钢印", "正式婚书", "登记", "结婚证", "官府判词", "判词", "官契", "盖章"],
}
_LAYERED_SETTING_CLARIFIERS = [
    "不是一回事", "两层", "三层", "村里认", "县里认", "挡债用", "正式登记", "补办",
    "先挡", "后补", "只算", "不能当", "不等于", "才算", "族里认", "官府才认",
    "官府才算", "村里认不算", "族里认不算", "不等于官府", "只是挡债用", "只是族里留底",
    "只是私下约定", "要到官府",
]

# ----- 官方闭环证据 -----
_OFFICIAL_EVIDENCE_MARKERS = [
    "工作组", "清查组", "传唤", "县里", "入库记录", "出库记录", "回执", "立案",
    "日志", "监管组", "监管局", "法院", "警方", "公安", "纪检", "仲裁",
    "冻结", "查封", "处罚决定", "调查结论",
]
_LOCAL_EVIDENCE_MARKERS = [
    "半本账", "残页", "火场", "口供", "目击", "账本", "证词", "过磅单",
    "录音", "截图", "聊天记录", "仓单", "照片", "监控",
]
_BRIDGE_MARKERS = [
    "送到", "递交", "提交", "报案", "移交", "备案", "上报", "交到", "上传", "送检", "交给", "递到",
    "封存", "待核验", "登记", "受理", "回执",
]

# ----- 角色转向跳变 -----
_NEGATIVE_STANCE_MARKERS = [
    "逼离婚", "净身出户", "羞辱", "赶出去", "不认这个儿媳", "不认你",
    "反对你们", "逼辞职", "要封杀", "要毁了你", "休妻", "退婚", "站在她那边",
]
_POSITIVE_FLIP_MARKERS = [
    "唯一认的儿媳", "是我错了", "都算我错", "我信你", "我支持你", "我站你这边",
    "你留下", "别走", "不离了", "我来作证", "以后听你的", "我认你",
]
_TURN_TRIGGER_MARKERS = [
    "因为", "原来", "才知道", "看到", "听见", "录音", "证据", "诊断书", "病危",
    "救了", "真相", "遗书", "鉴定", "判词", "回执", "账本", "照片", "监控",
    "短信", "DNA", "亲子鉴定",
]


def detect_testing_narrative_drift_issues(
    req: "TestingScriptRequest",
    content: str,
) -> list[str]:
    """对 scene 模式正文做 5 类叙事漂移检测，返回去重后最多 3 条 issue。"""
    if req.mode != "scene":
        return []

    text = str(content or "").strip()
    if not text:
        return []

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    opening = "\n".join(lines[:6]).strip()
    opening_norm = normalize_testing_story_text(opening)
    issues: list[str] = []

    previous_briefs = [
        item for item in (req.previous_episode_briefs or []) if isinstance(item, dict)
    ]

    # 1. 重复开局
    if int(req.episode_no or 0) >= 2 and opening_norm and previous_briefs:
        for item in previous_briefs[-2:]:
            prev_text = " ".join(
                str(item.get(key) or "").strip()
                for key in ("summary", "actual_progress", "result_summary", "ending_status", "body_excerpt")
            ).strip()
            prev_norm = normalize_testing_story_text(prev_text[:260])
            if not prev_norm:
                continue
            similarity = difflib.SequenceMatcher(None, opening_norm[:220], prev_norm[:220]).ratio()
            if similarity >= 0.78:
                issues.append("本集开局与前集已落地结果重复度过高，像把上一集起点重新开了一遍。")
                break
        if not issues:
            shared_markers = []
            for marker in _RESET_MARKERS:
                if marker not in opening:
                    continue
                if any(marker in " ".join(str(item.get(key) or "") for key in ("summary", "actual_progress", "body_excerpt")) for item in previous_briefs[-2:]):
                    shared_markers.append(marker)
            if len(shared_markers) >= 3:
                issues.append("本集开场重复调用了前集已经完成的核心动作节点，容易形成重复开局。")

    # 2. 核心债务漂移
    debt_hits = [
        label for label, markers in _DEBT_GROUPS.items()
        if contains_testing_story_markers(text, markers)
    ]
    if (
        len(debt_hits) >= 2
        and contains_testing_story_markers(text, _DEBT_SCOPE_MARKERS)
        and not contains_testing_story_markers(text, _DEBT_CLARIFIERS)
    ):
        issues.append("同一笔核心债务在正文里落到了多个主体口径，但没有交代谁是真责任主体、谁是被篡改或转嫁的说法。")

    # 3. 婚书/文书体系分层
    layered_setting_hits = [
        label for label, markers in _LAYERED_SETTING_GROUPS.items()
        if contains_testing_story_markers(text, markers)
    ]
    if len(layered_setting_hits) >= 2 and not contains_testing_story_markers(text, _LAYERED_SETTING_CLARIFIERS):
        issues.append("关键文书/规则同时落在多个层级，但没有讲清各自效力，容易造成设定分层混乱。")

    # 4. 官方闭环证据跳跃
    if (
        contains_testing_story_markers(text, _OFFICIAL_EVIDENCE_MARKERS)
        and contains_testing_story_markers(text, _LOCAL_EVIDENCE_MARKERS)
        and not contains_testing_story_markers(text, _BRIDGE_MARKERS)
    ):
        issues.append("民间线索直接跳成官方闭环证据，缺少送证、核验或移交的桥接动作。")

    # 5. 角色转向跳变
    previous_context = normalize_testing_story_text(
        " ".join(
            filter(
                None,
                [
                    str(getattr(req, "previous_summary", "") or "").strip(),
                    str(getattr(req, "previous_episode_text", "") or "").strip(),
                    " ".join(
                        str(item.get("summary") or "").strip()
                        for item in previous_briefs[-2:]
                        if isinstance(item, dict)
                    ),
                ],
            )
        )
    )
    if (
        previous_context
        and contains_testing_story_markers(previous_context, _NEGATIVE_STANCE_MARKERS)
        and contains_testing_story_markers(text, _POSITIVE_FLIP_MARKERS)
        and not contains_testing_story_markers(text, _TURN_TRIGGER_MARKERS)
    ):
        issues.append("关键人物立场在缺少触发事件和过渡反应的情况下突然翻转，容易造成角色转向跳变。")

    return list(dict.fromkeys(issue for issue in issues if issue))[:3]
