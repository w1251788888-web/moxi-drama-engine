"""测试页"剧本输出格式校验 + 角色/关系/状态卡检测器"集合（从 short_drama_writing.py 抽出）。

5 个 detection helper，零 IO、零 DB、零 AI 调用：

- validate_testing_script_output：格式硬校验（场标头、动作行、台词行、字数、头部样板反模式、广播式自报身份等）
- analyze_testing_character_health：每个角色出场/台词/OS 计数 + 主角缺席阻断 + 反派对峙信号检测
- detect_relationship_updates：从正文里识别关系建议（恋人/合作/敌对/亏欠/试探/克制/疏远等）
- detect_state_card_suggestions：识别信息差/权力位置/未完成承诺/禁改事实状态卡建议
- detect_testing_narrative_logic_issues：主角行动视角弱、解说式空钩子尾巴、威胁缺当场后果

被 evaluate_testing_scene、validate / deep-audit / auto-fix 多个 endpoint 共用。
"""
from __future__ import annotations

import re
from typing import Any, Optional, TYPE_CHECKING

from app.services.duration_profile_service import infer_duration_profile
from app.services.short_drama_format_repairs import detect_segment_overlap_issue
from app.services.short_drama_state_cards import normalize_testing_state_cards
from app.services.short_drama_text_format import count_testing_chars, testing_header_key

if TYPE_CHECKING:
    from app.schemas.short_drama_writing import TestingScriptRequest


# ----- 头部样板反模式（正则 + 错误信息） -----
_HEAD_TIER_ANTIPATTERNS: list[tuple[str, str]] = [
    (r"场末钩子[：:]", "出现了\"场末钩子：\"这种解说性标签。头部样板要求停在具体画面。"),
    (r"悬念留于此刻", "出现了\"悬念留于此刻\"这种解说尾巴。头部样板停在具体画面，不解释悬念。"),
    (r"这[^\n，。]{0,6}只是[^\n，。]{0,4}开始", "出现了\"只是开始\"这种放话式尾巴。头部样板用具体画面收尾。"),
    (r"才刚刚?开始|不过是?开始", "出现了\"才刚刚开始/不过是开始\"这种放话式尾巴。头部样板用具体画面收尾。"),
    (r"我不会就这么算了|这(?:件事|事儿|事)没完|咱们走着瞧", "出现了反派放狠话式的模板台词。头部样板用具体动作/物件特写替代。"),
    (r"下集待续|敬请期待|镜头一转", "出现了电视预告式用语。头部样板从不解说留悬念。"),
    (r"\d+\s*(?:积分|金币|经验|声望)", "系统提示出现积分/奖励数值。头部样板要求系统冷感、代价可视化，禁止游戏化数值。"),
    (r"任务完成(?:奖励)?[：:]", "系统提示出现\"任务完成：\"游戏化表达。头部样板要求冷感代价（身体/关系后果）。"),
    (r"属性[+＋]\d+|属性下降|(?:剩余时间|倒计时|限时)[^\n]{0,4}\d+\s*(?:[秒分钟]|小时|天|日)|[+＋\-－]\s*\d+\s*%|\d+\s*%(?:[的后]|\s*(?:概率|效果|加成|惩罚|疏远|好感))|\d+\s*天\s*\d+\s*小时", "系统提示出现数值/倒计时/百分比/时钟播报。头部样板要求冷感单句指令。"),
    (r"失败(?:后果|代价|惩罚)[：:][^\n]{0,20}(?:餐食|金币|积分|经验|能量|体力)(?:减半|扣除|清零|归零)", "系统失败代价写成游戏化数值。头部样板要求代价=身体痛觉/关系/可见后果。"),
]

_BROADCAST_PATTERNS: list[str] = [
    r"(?:我|本人|本座)[^\n，。]{0,8}不再是[^\n，。]{0,14}(?:的|可以)[^\n，。]{0,10}了",
    r"[^\n，。]{0,8}的宝座[^\n]{0,6}坐不稳",
    r"游戏规则变了",
    r"积分到手",
    r"(?:从)?今天(?:起|开始)[，,]?[^\n]{0,40}(?:将|会|就|都|不)[^\n]{0,12}(?:记住|记牢|记好|改变|重生|崛起|开始|不同|任人|被欺负|欺负)",
    r"(?:记住|记牢|记好)[这我你][^\n，。]{0,6}(?:名字|个名字|名|这名)",
    r"最好[^\n，。]{0,4}(?:记(?:住|牢|好)|记(?:好|住|牢))",
    r"(?:给你们|给你|让你们|让你)[^\n，。]{0,4}一个[^\n，。]{0,6}难忘",
    r"(?:卧龙院|凤雏学院|八道口|所有人|你们|他们)[^\n，。]{0,10}(?:将|会|都)[^\n，。]{0,6}记住",
    r"这是我[^\n，。]{0,6}(?:新的)?开始",
    r"英雄重生|废柴逆袭|倒数第一的逆袭",
    r"下次[，,]?就不会这么客气了",
    r"一切都[要将会]改变|我[会要将能]改变一切",
    r"证明(?:自己的?)?价值",
    r"让(?:所有人|你们|他们)[^\n，。]{0,8}刮目相看",
    r"(?:加快|提升)[^\n，。]{0,4}(?:实力|修为)",
    r"我们[^\n，。]{0,2}走着瞧|给(?:我|你)等着瞧",
    r"(?:你们|他们)[^\n，。]{0,4}的(?:噩梦|对手)",
    r"欺骗[^\n，。]{0,4}的代价[，,]?你[^\n，。]{0,4}承受不起",
    r"我(?:要|会|能)让你(?:们)?(?:看看|知道|记住|明白)[^\n，。]{0,10}(?:实力|本事|厉害|笑话|规则)",
    r"(?:让|叫)(?:你|你们|他|他们)[^\n，。]{0,4}看看[^\n，。]{0,4}(?:实力|本事|厉害)",
    r"没有倒数第一[，,]?只有我",
    r"别欺负弱(?:小|者)",
    r"自不量力",
    r"英雄救美",
    r"有什么本事|有何本事",
    r"成全你",
]


def validate_testing_script_output(
    content: str,
    req: "TestingScriptRequest",
) -> tuple[int, list[str]]:
    """格式硬校验，返回 (净字数, errors 列表)。"""
    errors: list[str] = []
    text = str(content or "").strip()
    char_count = count_testing_chars(text, exclude_punctuation=req.exclude_punctuation_for_count)

    if not text:
        return char_count, ["输出为空。"]

    if req.mode == "segment":
        profile = infer_duration_profile(
            episode_minutes=req.episode_minutes,
            explicit_min=req.word_count_min,
            explicit_max=req.word_count_max,
            explicit_target=req.word_count_target or req.target_chars,
            market_format=req.format_type or req.project_type,
        )
        segment = str(req.segment_id or "hook")
        seg_target = int(req.word_count_target or req.target_chars or 0)
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
        if char_count < seg_min:
            errors.append(f"净字数不足：当前 {char_count}，要求至少 {seg_min}。")
        if char_count > seg_max:
            errors.append(f"净字数超限：当前 {char_count}，要求至多 {seg_max}。")
    else:
        profile = infer_duration_profile(
            episode_minutes=req.episode_minutes,
            explicit_min=req.word_count_min,
            explicit_max=req.word_count_max,
            explicit_target=req.word_count_target or req.target_chars,
            market_format=req.format_type or req.project_type,
        )
        if char_count < profile.min_chars:
            errors.append(f"净字数不足：当前 {char_count}，要求至少 {profile.min_chars}。")
        if char_count > profile.max_chars:
            errors.append(f"净字数超限：当前 {char_count}，要求至多 {profile.max_chars}。")

    if not req.enforce_standard_format:
        return char_count, errors

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    require_header = not str(req.current_content or "").strip()
    if req.mode == "segment" and req.segment_id not in (None, "hook"):
        require_header = False

    if require_header:
        if not lines:
            errors.append("缺少正文内容。")
            return char_count, errors

        header_line = lines[0]
        if req.scene_header_style == "bracket":
            if not re.match(r"^【场\d+(?:-\d+)?：.+】$", header_line):
                errors.append("场次标头未使用 bracket 验收格式，例如【场1-1：夜  内  江家书房】。")
        else:
            if not re.match(r"^\d+-\d+\s+\S+\s+[内外]\s+\S+", header_line):
                errors.append("场次标头未使用 plain 格式，例如 1-1  日  外  战场。")
    else:
        previous_header_key = None
        for previous_line in reversed(str(req.current_content or "").splitlines()):
            previous_header_key = testing_header_key(previous_line)
            if previous_header_key:
                break
        for line in lines[:2]:
            current_header_key = testing_header_key(line)
            if current_header_key and previous_header_key and current_header_key == previous_header_key:
                errors.append("续写片段不应重复输出上一段已有场次标头。")
                break

    if not any(line.startswith("△") for line in lines):
        errors.append("缺少以 `△` 起笔的动作行。")
    if not any(
        re.match(r"^[^：\s]{1,20}(?:（[^）]+）)?：.+", line)
        or re.match(r"^[^：\s]{1,20}(?:（[^）]+）)?OS：.+", line)
        or re.match(r"^VO（[^）]+）：.+", line)
        or re.match(r"^[^：\s]{1,20}VO：.+", line)
        for line in lines
    ):
        errors.append("缺少标准台词 / OS / VO 行。")
    if any(line.startswith("动作：") or line.startswith("对白：") for line in lines):
        errors.append("出现了说明栏目，必须直接写成剧本正文。")

    overlap_issue = detect_segment_overlap_issue(req, text)
    if overlap_issue:
        errors.append(overlap_issue)

    for pattern, msg in _HEAD_TIER_ANTIPATTERNS:
        if re.search(pattern, text):
            errors.append(msg)

    for pattern in _BROADCAST_PATTERNS:
        if re.search(pattern, text):
            errors.append("出现广播式自报身份或解说式台词。头部样板用沉默动作或短促台词替代（参考范式 3）。")
            break

    dialogue_over_limit: list[str] = []
    dialogue_re = re.compile(r"^([^：\s△【]{1,20})(?:（[^）]{0,20}）)?(?:OS|VO)?：(.+)$")
    for line in lines:
        m = dialogue_re.match(line)
        if not m:
            continue
        body = m.group(2).strip()
        body_clean = re.sub(r"[（）(),，。！？!?；;：:、\-—…\s\"\"''《》\[\]【】]", "", body)
        if len(body_clean) > 28:
            dialogue_over_limit.append(line[:30])
    if len(dialogue_over_limit) >= 2:
        errors.append(f"出现 {len(dialogue_over_limit)} 句超过 28 字的冗长台词（头部样板单句≤25字），至少其中一句属广播式或解说式。")

    require_header = not str(req.current_content or "").strip()
    if req.mode == "segment" and req.segment_id not in (None, "hook"):
        require_header = False

    if req.enforce_standard_format and require_header and lines:
        header_line = lines[0]
        ep_no = int(req.episode_no or 0)
        sc_no = int(req.scene_no or 0)
        if ep_no > 0 and sc_no > 0 and req.scene_header_style == "bracket":
            expected_prefix = f"【场{ep_no}-{sc_no}"
            if not header_line.startswith(expected_prefix):
                errors.append(f"场次标头与当前任务编号不一致：应以 {expected_prefix} 开头。")

    return char_count, errors


def analyze_testing_character_health(
    content: str,
    characters: list[dict[str, Any]],
    selected_character_ids: Optional[list[str]] = None,
) -> tuple[list[dict[str, Any]], list[str], list[str], list[str]]:
    """分析每个角色出场/台词/OS 计数，返回 (health_items, warnings, blocking, present_ids)。"""
    text = str(content or "")
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    normalized_count = count_testing_chars(text, exclude_punctuation=True)
    health_items: list[dict[str, Any]] = []
    warnings: list[str] = []
    blocking_issues: list[str] = []
    present_character_ids: list[str] = []
    selected_ids = {str(item).strip() for item in (selected_character_ids or []) if str(item).strip()}

    protagonist: Optional[dict[str, Any]] = None
    antagonist: Optional[dict[str, Any]] = None

    for char in characters or []:
        if not isinstance(char, dict):
            continue
        role = str(char.get("role") or "").strip()
        if role == "protagonist" and protagonist is None:
            protagonist = char
        if role == "antagonist" and antagonist is None:
            antagonist = char

        name = str(char.get("name") or "").strip()
        char_id = str(char.get("id") or "").strip()
        if not name:
            continue

        escaped = re.escape(name)
        total = len(re.findall(escaped, text))
        present = total > 0
        if present and char_id:
            present_character_ids.append(char_id)
        dialogue_count = sum(
            1
            for line in lines
            if re.match(rf"^{escaped}(?:（[^）]+）)?：.+", line) or re.match(rf"^{escaped}(?:\([^)]+\))?:.+", line)
        )
        os_count = sum(
            1
            for line in lines
            if re.match(rf"^{escaped}(?:（[^）]+）)?OS：.+", line) or re.match(rf"^{escaped}(?:\([^)]+\))?OS:.+", line)
        )

        status = "normal"
        reason = ""
        if not present:
            status = "absent" if role in ("protagonist", "antagonist") else "idle"
            reason = "重要角色未出场" if status == "absent" else "未出场"
        elif dialogue_count == 0:
            status = "warning"
            reason = "出场但无台词"
        elif role == "protagonist" and normalized_count > 500 and os_count > 2:
            status = "warning"
            reason = "主角OS偏多"

        if role == "protagonist" and not present and normalized_count > 180:
            blocking_issues.append(f"正文已达到 {normalized_count} 净字，但主角【{name}】仍未出场，主线锚点不足。")
        if present and dialogue_count == 0 and (
            role == "protagonist"
            or (char_id in selected_ids and total >= 2)
        ):
            blocking_issues.append(f"角色【{name}】已出场但没有标准台词，人物锚点不稳。")
        if present and dialogue_count == 0:
            warnings.append(f"角色【{name}】出场但没有标准台词。")
        if role == "protagonist" and present and normalized_count > 500 and os_count > 2:
            warnings.append(f"主角【{name}】在当前篇幅内出现 {os_count} 处 OS，现实题材应优先用动作和物件承载情绪。")

        health_items.append({
            "id": char_id,
            "name": name,
            "role": role,
            "present": present,
            "dialogue_count": dialogue_count,
            "os_count": os_count,
            "total_mentions": total,
            "status": status,
            "reason": reason,
        })

    if antagonist and protagonist and protagonist.get("name") and antagonist.get("name"):
        protagonist_name = str(protagonist.get("name") or "").strip()
        antagonist_name = str(antagonist.get("name") or "").strip()
        if protagonist_name and antagonist_name and protagonist_name in text and antagonist_name in text:
            if not any(keyword in text for keyword in ["阻止", "威胁", "压制", "逼", "对峙", "挑衅", "反击", "报复"]):
                warnings.append(f"主角【{protagonist_name}】与反派【{antagonist_name}】已同场，但正面对抗信号偏弱。")

    return health_items, warnings, blocking_issues, present_character_ids


def detect_relationship_updates(
    content: str,
    characters: list[dict[str, Any]],
    present_ids: list[str],
) -> list[dict[str, Any]]:
    """从正文里识别关系建议（恋人/合作/敌对/亏欠/试探/克制/疏远等）。"""
    text = str(content or "")
    if not text or len(present_ids) < 2:
        return []

    by_id = {str(char.get("id") or ""): char for char in characters if isinstance(char, dict)}
    suggestion_rules = [
        ("恋人", 15, ["拥抱", "抱住", "吻", "亲住", "表白", "喜欢你", "我爱你", "心跳", "脸红"]),
        ("合作", 12, ["联手", "合作", "一起", "并肩", "结盟", "站在同一边", "帮你"]),
        ("敌对", 15, ["背叛", "翻脸", "决裂", "威胁", "出卖", "仇", "报复", "杀了你", "滚开"]),
        ("亏欠", 8, ["塞钱", "转账", "留饭", "收拾药袋", "替你", "替他", "替她", "替妈", "替爸", "我来", "没事"]),
        ("试探", 6, ["绕开", "岔开", "嘴硬", "咽下去", "递茶", "递碗", "盛饭", "盛汤", "顿了顿", "停了一下", "没接话", "没说话", "沉默"]),
        ("克制", 7, ["背身", "转身就走", "把手收回", "没接", "挂了电话", "压低声音", "低下头", "别过脸", "把话咽回去"]),
        ("疏远", 5, ["很久没联系", "好几年没回", "陌生", "客气得很", "像外人", "不知道说什么", "不知道该说什么"]),
    ]
    suggestions: list[dict[str, Any]] = []
    seen_pairs: set[tuple[str, str, str]] = set()

    for idx, source_id in enumerate(present_ids):
        source = by_id.get(source_id) or {}
        source_name = str(source.get("name") or "").strip()
        if not source_name or source_name not in text:
            continue
        for target_id in present_ids[idx + 1:]:
            target = by_id.get(target_id) or {}
            target_name = str(target.get("name") or "").strip()
            if not target_name or target_name not in text:
                continue

            existing_relation = next((
                rel for rel in (source.get("relationships") or [])
                if isinstance(rel, dict) and str(rel.get("targetId") or "") == target_id
            ), None)
            existing_type = str((existing_relation or {}).get("type") or "").strip()
            existing_strength = int((existing_relation or {}).get("strength") or 0)

            for relation_type, strength_delta, keywords in suggestion_rules:
                matched = [kw for kw in keywords if kw in text]
                if not matched:
                    continue
                if existing_type == relation_type and existing_strength >= min(100, 60 + strength_delta):
                    continue
                pair_key = tuple(sorted([source_id, target_id]) + [relation_type])
                if pair_key in seen_pairs:
                    continue
                seen_pairs.add(pair_key)
                suggestions.append({
                    "key": "__".join(sorted([source_id, target_id])) + f"__{relation_type}",
                    "source_id": source_id,
                    "target_id": target_id,
                    "source_name": source_name,
                    "target_name": target_name,
                    "suggested_type": relation_type,
                    "suggested_strength": min(100, max(existing_strength, 55) + strength_delta),
                    "description": "、".join(matched[:2]) + "等明确互动信号",
                    "evidence_keywords": matched[:3],
                    "existing_type": existing_type,
                    "existing_strength": existing_strength,
                })
                break

    return suggestions


def detect_state_card_suggestions(
    content: str,
    characters: list[dict[str, Any]],
    present_ids: list[str],
    state_cards: dict[str, Any],
) -> list[dict[str, Any]]:
    """识别信息差/权力位置/未完成承诺/禁改事实状态卡建议（最多 5 条）。"""
    text = str(content or "")
    normalized = normalize_testing_state_cards(state_cards)
    suggestions: list[dict[str, Any]] = []
    seen_keys: set[str] = set()

    by_id = {str(char.get("id") or ""): char for char in characters if isinstance(char, dict)}
    present_names = [str((by_id.get(pid) or {}).get("name") or "").strip() for pid in present_ids]
    present_names = [name for name in present_names if name]
    pair_label = " / ".join(present_names[:2]) if len(present_names) >= 2 else (present_names[0] if present_names else "当前场景")

    existing_titles = {
        str(card.get("title") or card.get("label") or "").strip()
        for cards in normalized.values()
        for card in cards
        if isinstance(card, dict) and str(card.get("title") or card.get("label") or "").strip()
    }

    lines = [line.strip() for line in text.splitlines() if line.strip()]

    def _build_evidence(keywords: list[str]) -> str:
        for line in lines:
            if any(keyword in line for keyword in keywords):
                cleaned = re.sub(r"\s+", " ", line)
                return cleaned[:90]
        compact = re.sub(r"\s+", " ", text)
        return compact[:90]

    def _push(kind: str, title: str, summary: str, related_ids: list[str], extra: dict[str, Any] | None = None):
        key = f"{kind}:{title}"
        if key in seen_keys or title in existing_titles:
            return
        seen_keys.add(key)
        payload = {
            "key": key,
            "kind": kind,
            "title": title,
            "summary": summary,
            "related_character_ids": related_ids,
        }
        if extra:
            payload.update(extra)
        suggestions.append(payload)

    info_tokens = ["不知道", "瞒着", "秘密", "误会", "认错", "身份", "真相", "录音", "监控", "证据"]
    power_tokens = ["命令", "规矩", "压", "跪", "滚", "闭嘴", "听我的", "资格", "家法", "站住", "护着", "让开"]
    promise_tokens = ["等我", "我会", "答应我", "一定", "下次", "婚约", "还钱", "回来", "带你", "别走"]
    locked_tokens = ["不能", "从未", "一直", "早就", "根本不是", "不是他", "不是她"]

    if len(present_ids) >= 2 and any(token in text for token in info_tokens):
        evidence = _build_evidence(info_tokens)
        _push(
            "info",
            f"{pair_label} 信息差",
            f"依据：{evidence}。本场出现秘密、误判、身份或证据信号，建议锁定谁知道、谁不知道。",
            present_ids[:3],
            {"evidence": evidence},
        )

    if len(present_ids) >= 2 and any(token in text for token in power_tokens):
        evidence = _build_evidence(power_tokens)
        _push(
            "power",
            f"{pair_label} 权力位置",
            f"依据：{evidence}。本场出现规矩压制、命令、护短或站位变化，建议锁定谁暂时占上风。",
            present_ids[:3],
            {"evidence": evidence},
        )

    if any(token in text for token in promise_tokens):
        evidence = _build_evidence(promise_tokens)
        _push(
            "promise",
            f"{pair_label} 未完成承诺",
            f"依据：{evidence}。本场有承诺、婚约、归来、还债或留人信号，建议后文回收。",
            present_ids[:3],
            {"evidence": evidence},
        )

    if len(present_names) >= 2 and any(token in text for token in locked_tokens):
        evidence = _build_evidence(locked_tokens)
        _push(
            "locked_fact",
            f"{pair_label} 禁改事实",
            f"依据：{evidence}。本场可能已经坐实关键事实，建议后文不要自我推翻。",
            present_ids[:3],
            {"evidence": evidence},
        )

    return suggestions[:5]


def detect_testing_narrative_logic_issues(
    req: "TestingScriptRequest",
    content: str,
    health_items: list[dict[str, Any]],
) -> list[str]:
    """识别叙事逻辑问题：主角行动视角弱、解说式空钩子尾巴、威胁缺当场后果。"""
    text = str(content or "")
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return []

    issues: list[str] = []
    protagonist = next(
        (
            item for item in health_items
            if str(item.get("role") or "").strip() == "protagonist" and item.get("present")
        ),
        None,
    )
    total_dialogue_lines = sum(1 for line in lines if "：" in line or ":" in line)
    if (
        protagonist
        and count_testing_chars(text, exclude_punctuation=True) >= 350
        and int(protagonist.get("dialogue_count") or 0) + int(protagonist.get("os_count") or 0) <= 1
        and total_dialogue_lines >= 3
    ):
        issues.append(f"主角【{str(protagonist.get('name') or '').strip() or '未命名'}】行动视角偏弱，人物像在旁观，主线驱动力不足。")

    summary_tail_markers = [
        "这只是开始", "故事才刚开始", "一切才刚开始", "命运的齿轮", "新的危机", "更大的风暴",
        "悬念留到下集", "敬请期待", "下集待续", "未完待续",
    ]
    tail_text = "\n".join(lines[-3:])
    if any(marker in tail_text for marker in summary_tail_markers):
        issues.append("结尾停在解说式空钩子，没有落到可拍动作、发现或未完成反应上。")

    threat_markers = ["威胁", "等着瞧", "不会放过", "报复", "我要你", "给我滚", "你死定了", "你完了"]
    consequence_markers = ["冲过去", "甩开", "砸", "打", "拦住", "报警", "围上来", "看见", "录下", "摔碎", "转账", "签字", "跪", "追上"]
    latter_half = text[len(text) // 2:] if text else ""
    if any(marker in text for marker in threat_markers) and not any(marker in latter_half for marker in consequence_markers):
        issues.append("威胁或冲突已经抛出，但当场后果偏弱，容易造成因果断档。")

    return list(dict.fromkeys(issue for issue in issues if issue))[:3]
