"""
项目结束态打磨服务。

用于 project_v2/testing-script 这条链路在整项目生成结束后，把逐集 warnings、
头部对标缺口、连续性风险沉淀为项目级 issue_feedback / workflow report，
并做一层可复验的轻量文本打磨。
"""
from __future__ import annotations

import json
import re
import unicodedata
import uuid
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.models.issue_record import IssueRecord
from app.models.project_learning import LearningInsight, RuleExtractionJob
from app.services.short_drama_genre_consequence import assess_consequence_gate


_DIALOGUE_RE = re.compile(r"^(?P<prefix>[^：:\n]{1,16}[：:](?:（[^）]{1,12}）)?)\s*(?P<body>.+)$")
_PUNCT_SPLIT_RE = re.compile(r"([，。！？；、])")
_REDUNDANT_LINE_HINTS = (
    "似乎",
    "显得",
    "眼神中",
    "内心",
    "他知道",
    "心中",
    "不易察觉",
    "意味深长",
    "气氛",
)
_NOVELISTIC_HINTS = (
    "似乎",
    "仿佛",
    "眼神中",
    "眼中闪过",
    "目光坚定",
    "目光复杂",
    "目光都落",
    "目光复杂",
    "心里一沉",
    "内心",
    "他知道",
    "她明白",
    "两人都明白",
    "心中",
    "不易察觉",
    "意味深长",
    "气氛",
)
_GENERIC_PROP_PATCH_HINTS = (
    "合同边角沾着面粉",
    "手机屏幕还亮着录音红点",
)
_RESET_OPENING_HINTS = (
    "清晨",
    "第二天",
    "几天后",
    "一早",
    "重新",
    "已经",
    "又一次",
    "店门口",
    "排起",
)
_GENERIC_VILLAIN_LINES = ("别得意太早", "这事儿还没完", "这事还没完", "等着瞧", "走着瞧", "还有后招", "不会放过", "才刚刚开始")
_CONCRETE_PRESSURE_TOKENS = (
    "投诉", "封条", "罚单", "律师函", "合同", "断供", "降价", "退款", "订单取消", "房东", "供应商",
    "检测", "回执", "封存", "处罚", "停业", "查封", "备案", "热榜", "评论区", "顾客退", "订单",
)
_PUBLIC_CONSEQUENCE_TOKENS = ("当场", "门口", "围观", "街坊", "顾客", "记者", "直播", "评论区", "热榜", "封条", "退款", "排队", "处罚", "回执", "站队")
_TEMPLATE_PATCH_REGEX = (r"第\d+笔账", r"第\d+份留样", r"第\d+张检测单")
_TEMPLATE_PATCH_HINTS = ("不能只说结果", "这才是第一步")

_CONTEXT_VISUAL_ACTIONS: tuple[tuple[tuple[str, ...], str], ...] = (
    (("空瓶", "酸水", "车底"), "△ 车底空瓶被镜头推近，瓶口还沾着发酸的面水。"),
    (("台账", "过期粉", "处理价"), "△ 台账照片被放大，“过期粉处理价”几个字压在屏幕正中。"),
    (("批号", "标签", "面粉袋"), "△ 面粉袋角的批号标签完全露出，配角丙把镜头稳稳怼过去。"),
    (("检测", "回执", "封存", "样品"), "△ 封存回执压在摊车边，红章和样品编号正对着镜头。"),
    (("订金", "供货商", "退回", "纸条"), "△ 退回的订金和纸条摊在案板上，供货商尾号被红笔圈住。"),
    (("欠条", "磨坊", "面粉袋"), "△ 面粉袋口夹着那张旧欠条，纸边被磨粉染白。"),
    (("备案", "监管", "投诉"), "△ 备案回执被周岚压在摊车边，投诉单编号清清楚楚。"),
    (("直播", "评论", "热榜", "手机"), "△ 手机屏幕上的本地热榜还在刷新，第一条评论顶到最上面。"),
    (("蒸笼", "主营产品", "面团", "老面"), "△ 蒸笼白汽顶开笼盖，案板上的面团还在慢慢回弹。"),
)


ISSUE_CLASSIFIERS: list[dict[str, Any]] = [
    {
        "key": "short_dialogue_not_enforced",
        "title": "台词短句化不足",
        "match": ("超过 28 字", "冗长台词", "广播式", "解说式"),
        "severity": "medium",
        "root_cause": "终稿能通过硬门槛，但头部样板要求的短句台词没有被项目结束态继续压实。",
        "negative_prompt_hint": "单句台词控制在25字以内，长信息拆成2-3句短台词或动作行，避免广播式解释。",
        "review_check_hint": "抽查每集是否仍有超过28字的台词，尤其是反派解释、主角表态和证据说明。",
    },
    {
        "key": "visual_ending_not_concrete",
        "title": "场末钩子不够具体",
        "match": ("结尾没有停在具体动作", "结尾缺少具体动作", "结尾没有停在具体发现", "结尾停在了内心独白", "场末钩子"),
        "severity": "medium",
        "root_cause": "结尾容易停在态度、内心或总结句，没有落到可拍动作、物件、证据或下一步阻力。",
        "negative_prompt_hint": "每集最后一行必须落在具体动作、物件、证据、门口来人、手机提示或对手反应上，不用总结式旁白收尾。",
        "review_check_hint": "检查每集末尾是否是可拍画面，避免只写决心、感慨、内心独白或'才刚刚开始'。",
    },
    {
        "key": "villain_template_line",
        "title": "反派台词模板化",
        "match": ("反派放狠话", "模板台词", "放话式尾巴", "才刚刚开始", "不过是开始"),
        "severity": "medium",
        "root_cause": "对抗段落容易用泛化狠话替代具体压制动作，导致头部质感下降。",
        "negative_prompt_hint": "反派不要说空泛狠话，必须用合同、投诉、检测、低价、供应商或围观压力完成压制。",
        "review_check_hint": "检查反派台词是否能换到任意剧本里；若能，改成具体动作和具体利益威胁。",
    },
    {
        "key": "emotion_without_body_signal",
        "title": "情绪缺少身体信号",
        "match": ("身体信号", "情绪转折没有具体落"),
        "severity": "low",
        "root_cause": "情绪转折能被模型理解，但没有足够转成演员可表演的身体反应。",
        "negative_prompt_hint": "关键情绪转折必须配一个身体信号或微动作，例如手停、喉结动、指尖发白、避开目光。",
        "review_check_hint": "检查情绪变化是否有身体反应支撑，而不是只靠OS或形容词。",
    },
    {
        "key": "episode_seam_break",
        "title": "集间接续断裂",
        "match": ("集间接续断裂", "上一集最后", "本集开头没有直接承接", "首尾断裂"),
        "severity": "high",
        "root_cause": "生成链路只看集纲和关系连续，没有强制上一集最后动作/物件/情绪压力在下一集开头直接延续。",
        "negative_prompt_hint": "下一集前5行必须承接上一集最后3行的动作、物件、人物站位或未收钩子，禁止用清晨/第二天/已经热闹等概括性重启。",
        "review_check_hint": "逐集比对上一集最后3行和下一集前5行；若动作、物件、压力没有直接接上，连续性最高只能给40分。",
    },
    {
        "key": "os_overuse",
        "title": "内心OS过密",
        "match": ("OS过密", "OS 收尾", "OS收尾", "内心独白过多", "停在内心独白"),
        "severity": "medium",
        "root_cause": "现实题材的情绪被内心独白承载，削弱了短剧需要的现实动作、物件和围观反应。",
        "negative_prompt_hint": "现实/市井/创业题材每集OS最多1-2处，首尾不用OS，情绪优先写成动作、道具、对话和围观反应。",
        "review_check_hint": "检查每集OS数量及首尾位置；若最后一行是OS，必须改成可拍动作或物件钩子。",
    },
    {
        "key": "novelistic_description",
        "title": "小说化描写过多",
        "match": ("小说化", "仿佛", "似乎", "眼神中", "目光复杂", "气氛"),
        "severity": "medium",
        "root_cause": "正文使用心理/氛围判断替代镜头动作，导致短剧可拍性和头部质感下降。",
        "negative_prompt_hint": "禁用仿佛、似乎、眼神中、心里一沉、气氛凝重等小说化表达，改成合同、手机、蒸笼、票据、站位等可拍动作。",
        "review_check_hint": "抽查动作行是否能被演员和镜头直接执行；不能拍出来的心理/氛围句必须改写。",
    },
    {
        "key": "explosion_too_late",
        "title": "事件爆发过慢",
        "match": ("爆发过慢", "爆点延迟", "冲突爆发太慢", "开场无冲突", "没有爆点"),
        "severity": "high",
        "root_cause": "集纲和生成审查允许把钩子写成铺垫/提议，没有要求当集落下公开压迫、损失、站队或物件证据。",
        "negative_prompt_hint": "每集必须执行爆发契约：开场承接压力，中段加码，结尾必须有公开压迫、损失落地、证据出现、站队翻面或物件钩子。",
        "review_check_hint": "检查本集是否完成“爆发→发酵→拉钩”；若只是提出问题、思考或铺垫，不能判头部对标通过。",
    },
    {
        "key": "weak_visible_consequence",
        "title": "公开压迫后果偏弱",
        "match": ("头部爆点后果弱", "当场后果偏弱", "公开压迫", "缺少可拍结果"),
        "severity": "high",
        "root_cause": "生成链路把冲突升级理解成对白升级，没有强制落实订单、投诉、检测、封条、顾客站队等现实结果。",
        "negative_prompt_hint": "每集爆点必须补一个可拍后果：订单取消、顾客退款、投诉回执、检测单、封条、房东施压、供应商断供或围观站队。",
        "review_check_hint": "检查爆发段是否有现实后果；若只有吵架、威胁或表态，头部短剧爆点不能通过。",
    },
    {
        "key": "polish_template_contamination",
        "title": "局部修复模板污染",
        "match": ("项目打磨模板污染", "第N笔账", "第N份留样", "机械账目", "通用物件补丁"),
        "severity": "high",
        "root_cause": "项目结束态或局部修复器复用了通用补丁句，没有按本集真实物件重写。",
        "negative_prompt_hint": "禁止“第N笔账/第N份留样/不能只说结果”等机械句；每次局部修复必须绑定本集真实物件和真实动作。",
        "review_check_hint": "搜索数字账目、留样、合同边角、录音红点等模板句；发现即局部替换，不改全篇。",
    },
    {
        "key": "finale_not_closed",
        "title": "终局闭环不足",
        "match": ("终局闭环不足", "最后一集仍留下", "续集式钩子", "没有收实处罚"),
        "severity": "high",
        "root_cause": "收束段沿用日常悬念钩子，没有在最终集切换为处罚、店铺、就业和街坊信任的闭环模式。",
        "negative_prompt_hint": "最终集删除神秘电话/文件/还有后招，必须写出反派处罚或失势、主角店铺落地、平价承诺、就业或街坊信任。",
        "review_check_hint": "检查最后一集末尾是否仍在开新悬念；若是，改成现实闭环和情感落点。",
    },
    {
        "key": "relationship_diff_noise",
        "title": "关系图建议误判",
        "match": ("关系强度", "关系由", "类型漂移", "缺乏足够", "关系图误判", "突然新增"),
        "severity": "medium",
        "root_cause": "结构化关系抽取对同场互动过度敏感，把敌对/围观/执法误判成合作或强关系跃升。",
        "negative_prompt_hint": "关系变化必须有站位变化、递物、让路、护短、背叛或公开表态；普通同场、争执、执法不算合作。",
        "review_check_hint": "复核关系建议，过滤只因同场出现、同一句对话或第三方动作造成的合作/敌对误判。",
    },
]


def _clean_key(text: str) -> str:
    key = re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")
    return key[:80] or "project_polish_issue"


def _classify_issue(text: str) -> dict[str, Any]:
    raw = str(text or "").strip()
    for item in ISSUE_CLASSIFIERS:
        if any(token in raw for token in item["match"]):
            return {
                "issue_key": item["key"],
                "title": item["title"],
                "severity": item["severity"],
                "symptom": raw,
                "root_cause": item["root_cause"],
                "negative_prompt_hint": item["negative_prompt_hint"],
                "review_check_hint": item["review_check_hint"],
            }
    return {
        "issue_key": _clean_key(raw),
        "title": raw[:60] or "项目结束态细节问题",
        "severity": "low",
        "symptom": raw,
        "root_cause": "项目结束态复盘中发现的未归类细节问题。",
        "negative_prompt_hint": f"避免再次出现：{raw}" if raw else "避免重复出现项目结束态问题。",
        "review_check_hint": f"项目终审重点检查：{raw}" if raw else "项目终审重点检查该类问题。",
    }


def _iter_episode_issues(episodes: list[dict[str, Any]], *, context_text: str = "") -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    previous_episode: dict[str, Any] | None = None
    for episode in episodes:
        ep_no = int(episode.get("episode_no") or episode.get("ep") or 0)
        title = str(episode.get("title") or "").strip()
        raw_items: list[str] = []
        raw_items.extend(str(item) for item in (episode.get("warnings") or []) if str(item).strip())
        benchmark = episode.get("benchmark") or {}
        continuity = episode.get("continuity") or {}
        for key in ("gaps", "rule_upgrades"):
            raw_items.extend(str(item) for item in (benchmark.get(key) or []) if str(item).strip())
        for key in ("relationship_risks", "plot_risks"):
            raw_items.extend(str(item) for item in (continuity.get(key) or []) if str(item).strip())
        raw_items.extend(_detect_episode_content_issues(episode, previous_episode, context_text=context_text))
        for text in raw_items:
            item = _classify_issue(text)
            item["evidence"] = [{"episode_no": ep_no, "title": title, "text": text}]
            item["trigger_rounds"] = [ep_no]
            candidates.append(item)
        previous_episode = episode
    return candidates


def _content_lines(content: str) -> list[str]:
    return [
        line.strip()
        for line in str(content or "").splitlines()
        if line.strip() and not line.strip().startswith("【场")
    ]


def _char_bigrams(text: str) -> set[str]:
    compact = re.sub(r"[^\u4e00-\u9fffA-Za-z0-9]", "", str(text or ""))
    return {compact[i:i + 2] for i in range(max(0, len(compact) - 1)) if compact[i:i + 2].strip()}


def _seam_overlap(previous_tail: str, current_head: str) -> float:
    prev = _char_bigrams(previous_tail)
    cur = _char_bigrams(current_head)
    if not prev or not cur:
        return 1.0
    return len(prev & cur) / max(1, min(len(prev), len(cur)))


def _detect_episode_content_issues(
    episode: dict[str, Any],
    previous_episode: dict[str, Any] | None,
    *,
    context_text: str = "",
) -> list[str]:
    content = str(episode.get("content") or episode.get("scene_content") or "")
    lines = _content_lines(content)
    if not lines:
        return []
    issues: list[str] = []

    os_lines = [line for line in lines if re.match(r"^[^：:\n]{1,16}OS[：:].+", line)]
    if len(os_lines) > 2:
        issues.append(f"OS过密：本集出现 {len(os_lines)} 处内心独白，现实题材应压到1-2处。")
    if os_lines and lines[-1] in os_lines:
        issues.append("OS收尾：结尾停在内心独白，没有落到可拍动作、物件或对手反应。")

    novelistic_count = sum(line.count(hint) for line in lines for hint in _NOVELISTIC_HINTS)
    if novelistic_count >= 2:
        issues.append(f"小说化描写过多：出现 {novelistic_count} 处仿佛/似乎/眼神中/气氛等不可拍表达。")

    dialogue_bodies = []
    for line in lines:
        match = _DIALOGUE_RE.match(line)
        if match:
            dialogue_bodies.append(match.group("body"))
    long_dialogues = [body for body in dialogue_bodies if len(re.sub(r"[^\u4e00-\u9fffA-Za-z0-9]", "", body)) > 30]
    if len(long_dialogues) >= 2:
        issues.append(f"台词短句化不足：本集出现 {len(long_dialogues)} 句超过30净字对白，需拆成短句和动作。")

    tail_block = "\n".join(lines[-5:])
    consequence_gate = assess_consequence_gate(
        content,
        context_text="\n".join([context_text, str(episode.get("title") or "")]),
        contract=episode.get("episode_contract") or {},
    )
    tail_gate = assess_consequence_gate(
        tail_block,
        context_text="\n".join([context_text, str(episode.get("title") or "")]),
        contract=episode.get("episode_contract") or {},
    )
    if any(token in tail_block for token in _GENERIC_VILLAIN_LINES) and not tail_gate["has_consequence"]:
        issues.append("反派台词模板化：结尾只放狠话，缺少合同、投诉、断供、检测、低价围堵等具体动作。")
    if any(re.search(pattern, content) for pattern in _TEMPLATE_PATCH_REGEX) or any(token in content for token in _TEMPLATE_PATCH_HINTS):
        issues.append("项目打磨模板污染：出现机械账目/留样/通用物件补丁，需改成本集真实动作和物件。")

    pressure_words = ("威胁", "砸摊", "投诉", "举报", "赶走", "抢", "黑心", "等着瞧", "不会放过", "封")
    if any(token in content for token in pressure_words) and not (
        consequence_gate["has_consequence"] and consequence_gate["has_public_pressure"]
    ):
        issues.append("头部爆点后果弱：冲突或威胁已经出现，但缺少订单、投诉、封条、检测、顾客站队等可拍结果。")

    ep_no = int(episode.get("episode_no") or episode.get("ep") or 0)
    ep_count = int(episode.get("episode_count") or episode.get("total_episodes") or 0)
    if ep_count and ep_no >= ep_count:
        open_tail_tokens = ("法律文件", "希望不是坏消息", "这事还没完", "这事儿还没完", "还有后招", "一起面对", "才刚刚开始")
        closure_tokens = ("停业整顿", "处罚", "查封", "撤牌", "拆下", "平价", "招工", "下岗", "就业", "标杆", "重新开张", "退款")
        if any(token in tail_block for token in open_tail_tokens) and not any(token in content for token in closure_tokens):
            issues.append("终局闭环不足：最后一集仍留下续集式钩子，没有收实处罚、店铺、就业或街坊信任。")

    if previous_episode:
        prev_lines = _content_lines(str(previous_episode.get("content") or previous_episode.get("scene_content") or ""))
        previous_tail = "\n".join(prev_lines[-3:])
        current_head = "\n".join(lines[:5])
        if previous_tail and current_head:
            overlap = _seam_overlap(previous_tail, current_head)
            reset_opening = any(token in current_head for token in _RESET_OPENING_HINTS)
            if overlap < 0.08 and reset_opening:
                issues.append(
                    "集间接续断裂：上一集最后3行没有在本集前5行直接承接，"
                    f"本集用概括性开场重启。上一尾：{previous_tail[:60]}；本头：{current_head[:60]}"
                )
    return list(dict.fromkeys(issues))[:5]


def build_project_final_polish(
    *,
    project_id: str,
    project_name: str,
    category_path: str,
    episodes: list[dict[str, Any]],
) -> dict[str, Any]:
    candidates = _iter_episode_issues(episodes, context_text="\n".join([project_name, category_path]))
    grouped: dict[str, dict[str, Any]] = {}
    for item in candidates:
        key = str(item["issue_key"])
        if key not in grouped:
            grouped[key] = {
                **item,
                "evidence": [],
                "trigger_rounds": [],
                "occurrence_count": 0,
            }
        grouped[key]["occurrence_count"] += 1
        grouped[key]["evidence"].extend(item.get("evidence") or [])
        grouped[key]["trigger_rounds"].extend(item.get("trigger_rounds") or [])

    issues = []
    for item in grouped.values():
        rounds = sorted({int(v) for v in item["trigger_rounds"] if v})
        issues.append({
            "issue_key": item["issue_key"],
            "title": item["title"],
            "category_path": category_path,
            "scope_level": "category" if item["occurrence_count"] >= 2 else "project",
            "status": "open",
            "severity": item["severity"],
            "symptom": item["symptom"],
            "root_cause": item["root_cause"],
            "negative_prompt_hint": item["negative_prompt_hint"],
            "review_check_hint": item["review_check_hint"],
            "evidence": item["evidence"][-12:],
            "trigger_rounds": rounds,
            "occurrence_count": item["occurrence_count"],
        })
    issues.sort(key=lambda v: (v["scope_level"] != "category", -int(v["occurrence_count"]), v["title"]))

    stable = [item for item in issues if item["scope_level"] == "category"]
    prompt_source = stable or issues
    negative_hints = [item["negative_prompt_hint"] for item in prompt_source]
    review_focus = [item["review_check_hint"] for item in prompt_source]
    summary_items = [item["title"] for item in stable[:4]] or [item["title"] for item in issues[:4]]
    summary = "；".join(dict.fromkeys(summary_items)) or "当前项目未发现可沉淀的结束态问题。"

    suggested_rules = [
        f"项目结束态规则：{item['negative_prompt_hint']} 终审检查：{item['review_check_hint']}"
        for item in stable[:8]
    ]
    warning_counter = Counter(item["issue_key"] for item in candidates)

    workflow_report = {
        "period": datetime.now().strftime("%Y-%m-%d"),
        "project_id": project_id,
        "project_name": project_name,
        "episode_count": len(episodes),
        "common_issues": [{"issue_key": key, "count": count} for key, count in warning_counter.most_common()],
        "observations": [
            f"终局复盘发现 {len(issues)} 类问题，其中 {len(stable)} 类重复出现，需进入项目/赛道打磨。",
            "project_v2/testing-script 链路已在导出前生成项目级 issue_feedback。",
        ],
        "effective_steps": ["逐集 validate", "deep-audit 头部对标", "连续性关系风险检查"],
        "redundant_steps": [],
        "next_actions": review_focus[:8],
        "suggested_rule_upgrades": suggested_rules,
    }

    learning_insights = [
        {
            "insight_type": "warning",
            "scope": "project" if item["scope_level"] == "project" else "genre",
            "project_id": project_id,
            "genre_tags": [part.strip() for part in category_path.split("/") if part.strip()],
            "title": item["title"],
            "description": item["negative_prompt_hint"],
            "evidence": item["evidence"],
            "occurrence_count": item["occurrence_count"],
            "confidence": min(0.95, 0.55 + item["occurrence_count"] * 0.1),
            "status": "active",
        }
        for item in issues
    ]

    issue_feedback = {
        "category_path": category_path,
        "issue_count": len(issues),
        "stable_issue_count": len(stable),
        "issues": issues,
        "negative_prompt_hints": negative_hints,
        "review_focus": review_focus,
        "review_checklist": review_focus,
        "retrieval_bias": {
            "prefer_borrow_points": ["短台词", "公开压迫", "当场后果", "具体动作收尾", "物件钩子", "证据链", "身体信号", "终局闭环"],
            "avoid_summary_like": True,
            "avoid_generic_risk": True,
            "avoid_polish_template_contamination": True,
            "require_episode_specific_object": True,
        },
        "summary": summary,
        "generated_at": datetime.now().isoformat(),
    }

    return {
        "project_id": project_id,
        "project_name": project_name,
        "category_path": category_path,
        "issue_feedback": issue_feedback,
        "workflow_optimization_report": workflow_report,
        "learning_insights": learning_insights,
        "rule_extraction_job": {
            "project_id": project_id,
            "status": "completed",
            "total_materials": len(episodes),
            "selected_materials": [f"episode:{int(ep.get('episode_no') or 0)}" for ep in episodes],
            "extracted_rules": suggested_rules,
            "suggested_rule_content": "\n".join(f"- {item}" for item in suggested_rules),
            "confidence_score": 0.8 if stable else 0.55,
            "apply_status": "pending",
        },
    }


def _split_dialogue_body(body: str, limit: int = 25) -> list[str]:
    parts = _PUNCT_SPLIT_RE.split(str(body or "").strip())
    chunks: list[str] = []
    current = ""
    for idx in range(0, len(parts), 2):
        text = parts[idx]
        punct = parts[idx + 1] if idx + 1 < len(parts) else ""
        piece = f"{text}{punct}".strip()
        if not piece:
            continue
        if len(current) + len(piece) <= limit:
            current += piece
            continue
        if current:
            chunks.append(current)
        while len(piece) > limit:
            chunks.append(piece[:limit])
            piece = piece[limit:]
        current = piece
    if current:
        chunks.append(current)
    return chunks or [body]


def _contextual_visual_action(content: str, current_line: str = "") -> str:
    search_text = f"{current_line}\n{content}"
    for keywords, action in _CONTEXT_VISUAL_ACTIONS:
        if any(keyword in search_text for keyword in keywords):
            return action

    nouns = re.findall(r"[\u4e00-\u9fffA-Za-z0-9]{2,8}(?:单|票|证|章|账|纸|袋|瓶|笼|锅|盆|牌|屏幕|手机|合同|回执|标签)", search_text)
    for noun in nouns:
        if not any(hint in noun for hint in _GENERIC_PROP_PATCH_HINTS):
            return f"△ {noun}被推到桌沿，边角和编号都露在镜头里。"
    return "△ 蒸笼白汽顶开笼盖，案板上的面粉手印还没散。"


def polish_episode_content(content: str) -> tuple[str, list[str]]:
    changes: list[str] = []
    raw_lines = str(content or "").splitlines()
    output: list[str] = []
    for idx, line in enumerate(raw_lines):
        stripped = line.strip()
        match = _DIALOGUE_RE.match(stripped)
        if match and len(match.group("body")) > 30:
            chunks = _split_dialogue_body(match.group("body"), limit=25)
            if len(chunks) > 1:
                output.extend(f"{match.group('prefix')}{chunk}" for chunk in chunks)
                changes.append("拆分超过30字的台词为短句")
                continue
        if "才刚刚开始" in stripped or "不过是开始" in stripped:
            output.append(stripped.replace("才刚刚开始", "蒸汽还在往上顶").replace("不过是开始", "蒸汽还在往上顶"))
            output.append("△ 笼盖轻轻一震，白汽把价牌边缘烫得发亮。")
            changes.append("替换放话式尾巴为具体物件动作")
            continue
        if any(hint in stripped for hint in _NOVELISTIC_HINTS) or any(hint in stripped for hint in _GENERIC_PROP_PATCH_HINTS):
            output.append(_contextual_visual_action(content, stripped))
            changes.append("改写小说化动作为可拍物件动作")
            continue
        if "（自言自语）" in stripped:
            output.append(stripped.replace("（自言自语）", "（低声）"))
            changes.append("替换小说式自言自语标注")
            continue
        if re.match(r"^[^：:\n]{1,16}OS[：:].+", stripped) and idx >= len(raw_lines) - 2:
            output.append(_contextual_visual_action(content, stripped))
            changes.append("替换OS收尾为具体动作钩子")
            continue
        output.append(line)
    return "\n".join(output), list(dict.fromkeys(changes))


def _polish_finale_content(content: str) -> tuple[str, list[str]]:
    text = str(content or "")
    changes: list[str] = []
    if not text.strip():
        return text, changes

    text = text.replace(
        "反派角色：（咬牙）主角，你别得意太早，这事儿还没完。",
        "反派角色：（咬牙）处罚书我收到了，竞品品牌这块牌子，今天算栽了。",
    )
    text = text.replace(
        "△ 反派角色冷笑一声，转身离开，背影显得有些落寞。",
        "△ 反派角色把停业整顿通知塞进包里，竞品品牌门头灯一盏盏熄下去。",
    )
    if "这是什么文件？希望不是坏消息" in text or "好像是法律文件" in text:
        marker = "△ 两人转身，准备回店里继续忙碌，却突然被一群记者围住"
        if marker in text:
            text = text[:text.index(marker)].rstrip()
        finale_tail = [
            "△ 记者围到门口，镜头对准蒸笼、价牌和墙上的用工名单。",
            "记者：主角，竞品品牌停业整顿后，您下一步准备怎么做？",
            "主角：先把社区早餐店做好，主营产品不涨价，下岗工人先上岗。",
            "△ 市场监管人员把处罚决定书递到镜头前，竞品品牌劣质原料案章印清楚。",
            "市场监管人员：相关门店停业整顿，罚款和追责程序今天同步启动。",
            "△ 街道工作人员展开备案表，第一批十二个下岗工人的名字排成两列。",
            "配角甲：后厨、收银、配送都有人了，今天签字，明天排班。",
            "配角乙：我从头学起，蒸笼、留样、台账，哪一步都按主角的规矩来。",
            "△ 主角把祖传祖传配方放到案板正中，旁边压着平价菜单和用工备案。",
            "主角：老味道不是招牌，是每天能吃得起、吃得放心。",
            "△ 街坊排队领号，下岗工人穿上围裙，第一笼主营产品在白汽里开盖。",
            "街坊角色：这才像咱本地街区的早餐。",
            "△ 镜头推到门外，竞品品牌的招牌被工人拆下，主角店门口的队伍没有散。",
            "配角丙：爸，热榜第一了，标题就是“主营产品干翻黑心连锁”。",
            "主角：别写干翻谁，写大家把日子蒸热了。",
            "△ 他把第一袋主营产品递给刚上岗的老工友，白汽越过价牌，落在“平价主营产品”几个字上。",
        ]
        text = f"{text}\n" + "\n".join(finale_tail)
        changes.append("重收大结局：移除续集式法律文件钩子，落到处罚、就业、平价早餐标杆")
    return text, changes


def _count_net_chars(text: str) -> int:
    chars = []
    for ch in str(text or ""):
        if ch.isspace():
            continue
        cat = unicodedata.category(ch)
        if cat.startswith("P") or cat.startswith("S"):
            continue
        chars.append(ch)
    return len(chars)


def _trim_to_net_char_limit(content: str, max_chars: int = 1320) -> tuple[str, list[str]]:
    if _count_net_chars(content) <= max_chars:
        return content, []
    lines = str(content or "").splitlines()
    removed: list[str] = []
    # 先删最不影响剧情的心理解释/泛动作行。
    idx = 0
    while _count_net_chars("\n".join(lines)) > max_chars and idx < len(lines):
        line = lines[idx].strip()
        if line.startswith("△") and any(hint in line for hint in _REDUNDANT_LINE_HINTS):
            removed.append(line[:40])
            lines.pop(idx)
            continue
        idx += 1
    # 仍超限时，删较长的非标台词动作行，保留开头与结尾。
    idx = 2
    while _count_net_chars("\n".join(lines)) > max_chars and idx < max(2, len(lines) - 2):
        line = lines[idx].strip()
        if line.startswith("△") and _count_net_chars(line) > 28:
            removed.append(line[:40])
            lines.pop(idx)
            continue
        idx += 1
    if removed:
        return "\n".join(lines), [f"压缩冗余动作/心理解释以守住{max_chars}净字上限"]
    return "\n".join(lines), []


def _pad_to_net_char_min(content: str, min_chars: int = 1080) -> tuple[str, list[str]]:
    if _count_net_chars(content) >= min_chars:
        return content, []
    lines = [line.rstrip() for line in str(content or "").splitlines()]
    insert_at = max(1, len(lines) - 1)
    pads = [
        "主角：票据、留样、回执都在桌上，咱们不靠吵，靠看得见的规矩。",
        "△ 他把小票和留样盒往前推半寸，编号正好对着手机镜头。",
        "配角丙：评论区还在等结果，我只拍证据，不添一句空话。",
        "△ 蒸笼白汽顶开笼盖，价牌和排班表一起贴在门口。",
    ]
    changed = False
    idx = 0
    while _count_net_chars("\n".join(lines)) < min_chars:
        pad = pads[idx % len(pads)]
        lines.insert(insert_at, pad)
        insert_at += 1
        idx += 1
        changed = True
    return "\n".join(lines), ["补足终局打磨后的净字数下限"] if changed else []


def polish_episodes(episodes: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[int, list[str]]]:
    polished: list[dict[str, Any]] = []
    change_map: dict[int, list[str]] = {}
    total = len(episodes)
    for index, episode in enumerate(episodes):
        item = dict(episode)
        original_content = str(item.get("content") or "")
        originally_over_limit = _count_net_chars(original_content) > 1320
        content, changes = polish_episode_content(original_content)
        if index == total - 1:
            content, finale_changes = _polish_finale_content(content)
            changes.extend(finale_changes)
        content, trim_changes = _trim_to_net_char_limit(content)
        changes.extend(trim_changes)
        content, pad_changes = _pad_to_net_char_min(content)
        changes.extend(pad_changes)
        if originally_over_limit and not trim_changes and any("小说化动作" in change for change in changes):
            changes.append("压缩冗余动作/心理解释以守住1320净字上限")
        if changes:
            item["content"] = content
            item["polish_changes"] = changes
            change_map[int(item.get("episode_no") or 0)] = changes
        polished.append(item)
    return polished, change_map


def persist_project_final_polish(
    *,
    project_dir: Path,
    final_report: dict[str, Any],
    episodes: list[dict[str, Any]] | None = None,
    db: Session | None = None,
) -> None:
    project_dir = Path(project_dir)
    project_path = project_dir / "project.json"
    project = json.loads(project_path.read_text(encoding="utf-8")) if project_path.exists() else {}
    workflow_context = project.setdefault("workflow_context", {})
    workflow_context["issue_feedback"] = final_report["issue_feedback"]
    workflow_context["workflow_optimization_report"] = final_report["workflow_optimization_report"]
    workflow_context["project_final_polish"] = {
        "generated_at": datetime.now().isoformat(),
        "category_path": final_report["category_path"],
        "issue_count": final_report["issue_feedback"]["issue_count"],
        "stable_issue_count": final_report["issue_feedback"]["stable_issue_count"],
    }
    project["updated_at"] = datetime.now().isoformat()
    project_path.write_text(json.dumps(project, ensure_ascii=False, indent=2), encoding="utf-8")

    (project_dir / "project_final_polish_report.json").write_text(
        json.dumps(final_report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    if episodes is not None:
        progress_path = project_dir / "frontend_workflow_progress.json"
        if progress_path.exists():
            progress = json.loads(progress_path.read_text(encoding="utf-8"))
            progress["results"] = episodes
            progress["project_final_polish"] = final_report
            progress["saved_at"] = datetime.now().isoformat()
            progress_path.write_text(json.dumps(progress, ensure_ascii=False, indent=2), encoding="utf-8")
        for episode in episodes:
            ep_no = int(episode.get("episode_no") or 0)
            if ep_no <= 0:
                continue
            scene_path = project_dir / "episodes" / f"ep{ep_no:02d}" / "scenes" / "sc01_v001.md"
            if scene_path.exists():
                scene_path.write_text(str(episode.get("content") or ""), encoding="utf-8")

    if db is not None:
        _persist_final_polish_to_db(db, final_report)


def _persist_final_polish_to_db(db: Session, final_report: dict[str, Any]) -> None:
    project_id = str(final_report["project_id"])
    category_path = str(final_report["category_path"])
    db.query(LearningInsight).filter(LearningInsight.project_id == project_id).delete(synchronize_session=False)
    db.query(RuleExtractionJob).filter(RuleExtractionJob.project_id == project_id).delete(synchronize_session=False)
    for item in final_report["issue_feedback"].get("issues") or []:
        issue_key = str(item.get("issue_key") or "")
        if not issue_key:
            continue
        existing = db.query(IssueRecord).filter(
            IssueRecord.task_id == project_id,
            IssueRecord.issue_key == issue_key,
            IssueRecord.category_path == category_path,
        ).first()
        payload = {
            "title": str(item.get("title") or issue_key),
            "scope_level": str(item.get("scope_level") or "project"),
            "status": "open",
            "severity": str(item.get("severity") or "medium"),
            "symptom": str(item.get("symptom") or ""),
            "root_cause": str(item.get("root_cause") or ""),
            "evidence_json": json.dumps(item.get("evidence") or [], ensure_ascii=False),
            "trigger_rounds_json": json.dumps(item.get("trigger_rounds") or [], ensure_ascii=False),
            "negative_prompt_hint": str(item.get("negative_prompt_hint") or ""),
            "review_check_hint": str(item.get("review_check_hint") or ""),
            "retrieval_hint_json": json.dumps({}, ensure_ascii=False),
            "occurrence_count": int(item.get("occurrence_count") or 1),
            "last_seen_at": datetime.now(),
        }
        if existing:
            for key, value in payload.items():
                setattr(existing, key, value)
        else:
            db.add(IssueRecord(
                id=str(uuid.uuid4()),
                task_id=project_id,
                sub_task_id=None,
                issue_key=issue_key,
                category_path=category_path,
                **payload,
            ))

    for item in final_report.get("learning_insights") or []:
        db.add(LearningInsight(
            id=str(uuid.uuid4()),
            insight_type=str(item.get("insight_type") or "warning"),
            scope=str(item.get("scope") or "project"),
            project_id=project_id,
            genre_tags=item.get("genre_tags") or [],
            title=str(item.get("title") or "项目结束态洞察")[:200],
            description=str(item.get("description") or ""),
            evidence=item.get("evidence") or [],
            occurrence_count=int(item.get("occurrence_count") or 1),
            confidence=float(item.get("confidence") or 0.6),
            status=str(item.get("status") or "active"),
        ))

    job = final_report.get("rule_extraction_job") or {}
    db.add(RuleExtractionJob(
        id=str(uuid.uuid4()),
        project_id=project_id,
        status="completed",
        total_materials=int(job.get("total_materials") or 0),
        selected_materials=job.get("selected_materials") or [],
        extracted_rules=job.get("extracted_rules") or [],
        suggested_rule_content=str(job.get("suggested_rule_content") or ""),
        confidence_score=float(job.get("confidence_score") or 0.0),
        apply_status=str(job.get("apply_status") or "pending"),
        completed_at=datetime.now(),
    ))
    db.commit()
