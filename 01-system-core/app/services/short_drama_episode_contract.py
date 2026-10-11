"""测试页“剧作契约 + 全剧推演沙盘 + 连续性 guardrails”（从 short_drama_writing.py 抽出）。

6 个纯函数，零 IO/AI/DB：

- infer_testing_contract_guardrails：基于 brief/conflict/canon 推断 must_not（关键词触发）
- episode_contract_from_brief：把单集 brief dict 编译成 episode_contract 结构
- build_testing_series_simulation_packet：合并已有 sim packet + 前/当/后续集推断契约
- current_testing_episode_contract：从 packet 里挑出本集契约
- build_testing_frontmatter_execution_contract：把一句话梗概/世界观/角色/字数目标编译成初稿施工锚点
- format_testing_episode_contract_block：把契约格式化成 prompt 用的 “- 本集契约：...” 块
- build_testing_continuity_guardrails：写本集连续性硬规则（OS、闭环、关系推进等）
"""
from __future__ import annotations

import json
from collections import OrderedDict
from typing import Any, TYPE_CHECKING

from app.services.short_drama_canon_blocks import build_inferred_canon_packet
from app.services.short_drama_testing_normalizers import (
    as_clean_text_list,
    normalize_testing_episode_contract,
    normalize_testing_episode_memory_cards,
    normalize_testing_series_simulation_packet,
)

if TYPE_CHECKING:
    from app.schemas.short_drama_writing import TestingScriptRequest


def infer_testing_contract_guardrails(req: "TestingScriptRequest") -> list[str]:
    """基于 brief/世界观/冲突/canon 推断 must_not 列表（关键词触发）。"""
    source_text = "\n".join([
        str(req.brief or ""),
        str(req.worldview or ""),
        str(req.conflict or ""),
        str(req.genre_main or ""),
        str(req.genre_sub or ""),
        str(req.episode_summary or ""),
        str(req.episode_conflict or ""),
        str(req.episode_hook or ""),
        json.dumps(req.canon_packet or {}, ensure_ascii=False),
    ])
    guardrails = [
        "不能重演前序集已经落地的开场动作、公开表态或冲突结论，必须从上一集结果继续推进。",
        "不能提前兑现后续集摘要里的大反转、定案、身份揭露、感情定性或最终胜负。",
        "关系变化必须有触发动作、台词反应和当场后果，不能直接把关系改成新状态。",
        "民间线索、个人判断、传闻和官方结论必须分层，不能从线索直接跳到权威裁定。",
    ]
    if any(token in source_text for token in ("债务", "欠债", "欠款", "借据", "债主", "顶债", "抵债", "还债", "还钱")):
        guardrails.append("债务/责任口径必须单义：原始债、挂名债、篡改债、女主承认的数额必须分层，不能在同一集漂移。")
    if any(token in source_text for token in ("婚书", "契约", "文书", "判词", "族规", "家法", "登记", "盖章", "手印", "民政")):
        guardrails.append("婚书/契约/口头承诺/族规/官府或机构文书必须分层，不能混成同一种法律效力。")
    if any(token in source_text for token in ("证据", "账本", "账页", "缺页", "录音", "监控", "仓单", "日志", "口供", "传唤", "监管", "县里", "官府", "警方", "立案", "冻结")):
        guardrails.append("证据链只能按发现、验真、递交、第三方核验、权威动作逐步推进，不能省掉中间桥。")
    if any(token in source_text for token in ("身份", "血脉", "亲子", "真假", "替身", "嫡", "继承")):
        guardrails.append("身份线必须区分怀疑、线索、证人、物证和公开确认，不能一句话直接坐实。")
    if any(token in source_text for token in ("系统", "金手指", "异能", "修为", "境界", "法宝")):
        guardrails.append("系统/金手指/修炼规则必须保持同一套代价和生效边界，不能临场改规则救场。")
    return list(dict.fromkeys(guardrails))[:10]


def episode_contract_from_brief(req: "TestingScriptRequest", brief: dict[str, Any], *, source: str) -> dict[str, Any]:
    """把单集 brief dict 编译成 episode_contract 结构。"""
    try:
        episode_no = int(brief.get("episode_no") or brief.get("ep") or req.episode_no or 0)
    except Exception:
        episode_no = int(req.episode_no or 0)
    title = str(brief.get("title") or (req.episode_title if episode_no == int(req.episode_no or 0) else "") or "").strip()
    summary = str(brief.get("summary") or (req.episode_summary if episode_no == int(req.episode_no or 0) else "") or "").strip()
    conflict = str(brief.get("conflict") or (req.episode_conflict if episode_no == int(req.episode_no or 0) else "") or "").strip()
    hook = str(brief.get("hook") or (req.episode_hook if episode_no == int(req.episode_no or 0) else "") or "").strip()
    actual = str(brief.get("actual_progress") or brief.get("result_summary") or brief.get("ending_status") or brief.get("body_excerpt") or "").strip()
    public_pressure = str(brief.get("public_pressure") or brief.get("pressure") or brief.get("public_conflict") or "").strip()
    real_loss = str(brief.get("real_loss") or brief.get("visible_consequence") or brief.get("consequence") or "").strip()
    evidence_object = str(brief.get("evidence_object") or brief.get("object_hook") or brief.get("prop_hook") or "").strip()
    villain_pressure_action = str(brief.get("villain_pressure_action") or brief.get("antagonist_action") or "").strip()
    rag_benchmark_pattern = str(brief.get("rag_benchmark_pattern") or brief.get("benchmark_pattern") or "").strip()

    previous_cards = normalize_testing_episode_memory_cards(req.episode_memory_cards or req.previous_episode_briefs or [])
    previous = next((card for card in reversed(previous_cards) if int(card.get("episode_no") or 0) < episode_no), {})
    start_state = str(previous.get("ending_state") or previous.get("summary") or "").strip()
    if not start_state:
        prev_briefs = [item for item in (req.previous_episode_briefs or []) if isinstance(item, dict)]
        if prev_briefs:
            prev = prev_briefs[-1]
            start_state = str(prev.get("ending_state") or prev.get("tail_excerpt") or prev.get("actual_progress") or prev.get("summary") or "").strip()
    if previous and str(previous.get("tail_excerpt") or previous.get("body_excerpt") or "").strip():
        start_state = str(previous.get("ending_state") or previous.get("tail_excerpt") or previous.get("body_excerpt") or "").strip()
    if not start_state:
        start_state = "承接前序已经落地的结果，不重启同一场开局。"
    combined = "\n".join([summary, conflict, hook, str(req.conflict or ""), str(req.brief or "")])

    if not public_pressure:
        if any(token in combined for token in ("投诉", "砸摊", "举报", "围观", "当众", "直播", "黑心", "连锁", "房东", "封", "赶走")):
            public_pressure = "本集必须出现公开压迫或第三方见证，让主角的处境被本题材内成立的旁观者、权力方或关系方看见。"
        else:
            public_pressure = "本集必须把压力写到现实现场，不只停在人物心里或口头争执。"
    if not real_loss:
        if any(token in combined for token in ("早餐", "馒头", "摊", "订单", "配方", "连锁", "债", "钱", "生意")):
            real_loss = "本集必须落下本赛道成立的可见后果：生意、名声、现金、物件、证据、场地、合作或第三方站队至少动一项。"
        else:
            real_loss = "本集必须有当场代价或局势变化，不能只提出问题。"
    if not evidence_object:
        if any(token in combined for token in ("馒头", "老面", "酵母", "面团", "蒸笼", "配方")):
            evidence_object = "优先使用大纲中已有的食物、器具、票据、证据、手机信息或现场物件承载钩子，禁止凭空换赛道。"
        elif any(token in combined for token in ("证据", "账", "录音", "合同", "回执", "检测")):
            evidence_object = "用本集真实证据物件承载推进，不要套用通用合同/录音补丁。"
        else:
            evidence_object = "结尾钩子必须落到本集真实物件、动作、证据或手机提示。"
    if not villain_pressure_action:
        if any(token in combined for token in ("连锁", "早餐", "品牌", "黑心", "供应商", "投诉")):
            villain_pressure_action = "反派压制必须具体到本赛道成立的商业动作、资源截断、证据造假、第三方施压或舆论反咬。"
        else:
            villain_pressure_action = "反派不能只放狠话，必须给出具体动作或利益威胁。"
    if not rag_benchmark_pattern:
        rag_benchmark_pattern = "对标头部短剧：开场压力可见，中段证据/关系推进，爆点有当场后果，结尾物件拉钩。"

    must_happen = as_clean_text_list([
        summary and f"兑现本集摘要：{summary}",
        conflict and f"推进本集核心冲突：{conflict}",
        hook and f"结尾钩子落到具体画面：{hook}",
        public_pressure and f"公开压迫必须落地：{public_pressure}",
        real_loss and f"当场后果必须可见：{real_loss}",
    ], limit=6)
    relationship_delta = [
        "若本集关系推进，只能小步变化，并写出触发动作、反应和代价。"
    ]
    information_delta = [
        "本集只推进当前集应揭露的信息，不提前吃掉后续集大反转。"
    ]
    if actual:
        information_delta.append(f"已落地结果：{actual[:120]}")

    evidence_step = ""
    if any(token in combined for token in ("证据", "账", "录音", "监控", "仓单", "日志", "口供", "传唤", "监管", "官府", "警方", "立案", "冻结")):
        evidence_step = "本集证据链必须只推进一到两步：发现/验真/递交/第三方核验/权威动作，禁止从线索直接跳最终定案。"
    elif any(token in combined for token in ("婚书", "契约", "文书", "判词", "登记", "手印", "族规", "家法")):
        evidence_step = "本集文书线必须先说明私约、见证、登记、裁定的层级，再让它产生对应效力。"

    return normalize_testing_episode_contract({
        "episode_no": episode_no,
        "title": title,
        "start_state": start_state,
        "must_happen": must_happen,
        "must_not_happen": infer_testing_contract_guardrails(req),
        "relationship_delta": relationship_delta,
        "character_delta": as_clean_text_list(brief.get("character_delta") or ["人物立场变化必须由动作触发，不能靠OS自我宣布。"], limit=4),
        "information_delta": information_delta,
        "incoming_hook": start_state,
        "public_pressure": public_pressure,
        "real_loss": real_loss,
        "evidence_object": evidence_object,
        "villain_pressure_action": villain_pressure_action,
        "dialogue_style_contract": str(brief.get("dialogue_style_contract") or "现实短剧台词短句化，单句尽量25字以内；长信息拆成短对白和动作。").strip(),
        "rag_benchmark_pattern": rag_benchmark_pattern,
        "evidence_chain_step": evidence_step,
        "ending_state": summary,
        "outgoing_hook": hook,
        "ending_hook": hook,
        "source": source,
    })


def build_testing_series_simulation_packet(req: "TestingScriptRequest") -> dict[str, Any]:
    """合并已有 sim packet + 前/当/后续集推断契约 -> 全剧沙盘。"""
    explicit = normalize_testing_series_simulation_packet(req.series_simulation_packet or {})
    contracts_by_ep: OrderedDict[int, dict[str, Any]] = OrderedDict()
    for item in explicit.get("episode_contracts") or []:
        ep = int(item.get("episode_no") or 0)
        if ep > 0:
            contracts_by_ep[ep] = item

    for item in (req.previous_episode_briefs or []):
        if isinstance(item, dict):
            contract = episode_contract_from_brief(req, item, source="previous_outline")
            ep = int(contract.get("episode_no") or 0)
            if ep > 0 and ep not in contracts_by_ep:
                contracts_by_ep[ep] = contract

    current_contract = episode_contract_from_brief(req, {
        "episode_no": req.episode_no,
        "title": req.episode_title,
        "summary": req.episode_summary,
        "conflict": req.episode_conflict,
        "hook": req.episode_hook,
    }, source="current_outline")
    if req.episode_contract:
        explicit_current = normalize_testing_episode_contract(req.episode_contract or {})
        merged_current = dict(current_contract)
        for key, value in explicit_current.items():
            if isinstance(value, list):
                if value:
                    merged_current[key] = value
            elif value:
                merged_current[key] = value
        contracts_by_ep[int(req.episode_no or 0)] = normalize_testing_episode_contract(merged_current)
    else:
        contracts_by_ep[int(req.episode_no or 0)] = current_contract

    for item in (req.future_episode_briefs or []):
        if isinstance(item, dict):
            contract = episode_contract_from_brief(req, item, source="future_outline")
            ep = int(contract.get("episode_no") or 0)
            if ep > 0 and ep not in contracts_by_ep:
                contracts_by_ep[ep] = contract

    contracts = [contracts_by_ep[key] for key in sorted(contracts_by_ep)]
    canon = build_inferred_canon_packet(req)
    locked_facts = as_clean_text_list(canon.get("locked_facts"), limit=10)
    return {
        "source": explicit.get("source") or "outline_inferred",
        "simulation_goal": explicit.get("simulation_goal") or "先以全剧沙盘锁定因果、关系、信息揭露和规则边界，再生成正文。",
        "global_must_not": list(dict.fromkeys([*(explicit.get("global_must_not") or []), *infer_testing_contract_guardrails(req)]))[:12],
        "locked_series_facts": list(dict.fromkeys([*(explicit.get("locked_series_facts") or []), *locked_facts]))[:12],
        "episode_contracts": contracts,
    }


def current_testing_episode_contract(req: "TestingScriptRequest") -> dict[str, Any]:
    """从 packet 里挑出本集契约；找不到回 fallback。"""
    target = int(req.episode_no or 0)
    packet = build_testing_series_simulation_packet(req)
    for item in packet.get("episode_contracts") or []:
        if int(item.get("episode_no") or 0) == target:
            return normalize_testing_episode_contract(item)
    return episode_contract_from_brief(req, {}, source="fallback")


def _short_text(value: Any, limit: int = 180) -> str:
    return str(value or "").strip().replace("\n", " ")[:limit]


def build_testing_frontmatter_execution_contract(req: "TestingScriptRequest") -> list[str]:
    """把前置资料编译成初稿施工锚点。

    这里不是新增故事内容，而是把已经存在的“一句话梗概、世界观、角色、字数”
    从松散背景升级成写手必须执行的约束，减少后置自动修稿。
    """
    lines: list[str] = []
    brief = _short_text(req.brief, 180)
    worldview = _short_text(req.worldview or req.world_rules, 180)
    conflict = _short_text(req.conflict or req.conflict_plan, 180)
    golden_finger = _short_text(req.golden_finger or req.golden_finger_rules, 150)
    if any((brief, worldview, conflict, golden_finger, req.characters)):
        lines.append("- 前置信息执行锚点：以下内容是硬约束，不是背景材料；正文必须围绕它们写，不得临场换设定。")
    if brief:
        lines.append(f"- 一句话梗概：{brief}")
    if worldview:
        lines.append(f"- 世界观边界：{worldview}")
    if golden_finger:
        lines.append(f"- 规则/金手指边界：{golden_finger}")
    if conflict:
        lines.append(f"- 总冲突方向：{conflict}")

    selected_ids = {str(item) for item in (req.selected_character_ids or []) if str(item).strip()}
    role_lines: list[str] = []
    for char in req.characters or []:
        if not isinstance(char, dict):
            continue
        char_id = str(char.get("id") or "").strip()
        if selected_ids and char_id and char_id not in selected_ids:
            continue
        name = _short_text(char.get("name"), 24)
        if not name:
            continue
        role = _short_text(char.get("role") or "角色", 24)
        info = _short_text(char.get("info") or char.get("background"), 70)
        role_lines.append(f"{name}={role}" + (f"：{info}" if info else ""))
        if len(role_lines) >= 6:
            break
    if role_lines:
        lines.append("- 角色执行：" + "；".join(role_lines))

    target = int(req.word_count_target or req.target_chars or 0)
    min_count = int(req.word_count_min or 0)
    max_count = int(req.word_count_max or 0)
    if target or min_count or max_count:
        interval = f"{min_count}-{max_count}" if min_count and max_count else str(target or max_count or min_count)
        target_label = f"约{target}" if target else interval
        lines.append(
            f"- 初稿一次成稿策略：先锁主场景、主动作、主信息、主关系变化，再写对白；目标净字符{target_label}，硬区间{interval}；超出时优先删解释、OS和旁白，不新增后续集事件。"
        )
        lines.append("- OS控制：OS最多1处，且不能放开头或结尾；情绪优先写成动作、物件、站位、手机信息、票据文书或对手反应。")
    if req.future_episode_briefs:
        future_titles = []
        for item in (req.future_episode_briefs or [])[:3]:
            if isinstance(item, dict):
                title = _short_text(item.get("title") or item.get("summary") or item.get("hook"), 40)
                if title:
                    future_titles.append(title)
        suffix = "；".join(future_titles)
        lines.append(
            "- 后续集只用于避剧透：只知道边界，不提前兑现后续反转、终局动作、正式定案或关系定性"
            + (f"；后续参考：{suffix}" if suffix else "")
        )
    return lines[:10]


def format_testing_episode_contract_block(req: "TestingScriptRequest") -> str:
    """把本集契约格式化成 prompt 用的 “- 本集契约：...” 块。"""
    packet = build_testing_series_simulation_packet(req)
    contract = current_testing_episode_contract(req)
    lines = [
        "- 全剧推演沙盘：已根据大纲、前序落地结果、后续剧透边界和角色关系生成本集剧作契约。",
        f"- 推演目标：{packet.get('simulation_goal') or '先推演后写作，正文必须执行本集契约。'}",
        f"- 本集契约：第{int(contract.get('episode_no') or req.episode_no or 0)}集 {contract.get('title') or req.episode_title or ''}".strip(),
    ]
    lines.extend(build_testing_frontmatter_execution_contract(req))
    if contract.get("start_state"):
        lines.append(f"- 开场承接：{str(contract['start_state'])[:160]}")
    for label, key, limit in (
        ("承接钩子", "incoming_hook", 140),
        ("公开压迫", "public_pressure", 160),
        ("当场后果", "real_loss", 160),
        ("证据/物件钩子", "evidence_object", 160),
        ("反派具体压制", "villain_pressure_action", 160),
        ("头部对标模式", "rag_benchmark_pattern", 180),
        ("台词契约", "dialogue_style_contract", 150),
    ):
        value = str(contract.get(key) or "").strip()
        if value:
            lines.append(f"- {label}：{value[:limit]}")
    for label, key, limit in (
        ("必须发生", "must_happen", 4),
        ("禁止事项", "must_not_happen", 8),
        ("关系变化", "relationship_delta", 3),
        ("角色变化", "character_delta", 3),
        ("信息变化", "information_delta", 3),
    ):
        values = contract.get(key) if isinstance(contract.get(key), list) else []
        if values:
            lines.append(f"- {label}：" + "；".join(str(item)[:120] for item in values[:limit] if str(item).strip()))
    if contract.get("evidence_chain_step"):
        lines.append(f"- 证据/规则推进：{str(contract['evidence_chain_step'])[:160]}")
    if contract.get("ending_state"):
        lines.append(f"- 本集目标状态：{str(contract['ending_state'])[:140]}")
    if contract.get("ending_hook"):
        lines.append(f"- 本集钩子边界：{str(contract['ending_hook'])[:120]}")
    if contract.get("outgoing_hook"):
        lines.append(f"- 下一集承接钩子：{str(contract['outgoing_hook'])[:120]}")
    lines.append("- 头部短剧硬执行：开场接上集，压力必须公开，爆点必须有当场后果，结尾必须落到本集真实物件/动作/证据。")
    global_must_not = packet.get("global_must_not") if isinstance(packet.get("global_must_not"), list) else []
    if global_must_not:
        lines.append("- 全剧沙盘禁区：" + "；".join(str(item)[:100] for item in global_must_not[:8] if str(item).strip()))
    return "\n".join(lines)


def build_testing_continuity_guardrails(req: "TestingScriptRequest") -> str:
    """写本集连续性硬规则（OS、闭环、关系推进等）。"""
    previous_tail = ""
    for item in reversed(req.previous_episode_briefs or []):
        if not isinstance(item, dict):
            continue
        raw_tail = str(item.get("ending_state") or item.get("tail_excerpt") or "").strip()
        if not raw_tail:
            body_lines = [
                str(line or "").strip()
                for line in str(item.get("body_excerpt") or "").splitlines()
                if str(line or "").strip()
            ]
            raw_tail = "\n".join(body_lines[-3:])
        if raw_tail:
            previous_tail = raw_tail
            break

    lines = [
        f"- 当前只允许兑现第{int(req.episode_no or 0)}集自己的摘要、冲突、钩子，不得把后续集的大事件提前写出来。",
        "- 本集开头前5行必须直接承接上一集最后3行的动作、物件、站位或未收钩子；禁止用“清晨/第二天/已经热闹/重新开始”概括性跳开。",
        "- 现实/市井/创业题材 OS 最多1-2处，首尾不用OS；情绪优先落到本集真实物件、手机信息、票据文书、站位和现场反应。",
        "- 每集必须形成短剧小闭环：开场承压/继承上集 → 中段升级 → 爆发或损失落地 → 结尾用具体物件/动作拉下一集。",
        "- 若关系发生推进、翻面、破裂或强度跃升，必须在本场写出可拍动作、台词冲突和即时后果；没有证据就保持原关系位置。",
        "- 已确认前文优先级高于梗概；只能承接前文结果继续推进，不能把已经发生的局面改写成另一种版本。",
        "- 全剧推演沙盘优先于临场发挥；正文必须执行本集剧作契约，不能把契约中的禁止事项写成事实。",
    ]
    if previous_tail and not str(req.current_content or "").strip():
        lines.insert(
            2,
            f"- 本集开场必须显性带入这个上一集尾巴里的至少一个具体物件/动作/站位：{previous_tail[:220]}",
        )
    if req.mode == "segment" and str(req.current_content or "").strip():
        lines.insert(
            2,
            "- 本段前5行必须承接已确认前文最后3行的动作/台词/站位，不能换一个新开局重写。",
        )
    continuity_notes = str(req.continuity_notes or "").strip()
    if continuity_notes:
        lines.append(f"- 当前连续性提醒：{continuity_notes[:160]}")
    if req.future_episode_briefs:
        lines.append("- 后续集摘要只用于避剧透，尤其禁止提前揭晓身份、翻盘结果、关键物证归属和感情定性。")
    if req.previous_relationship_snapshot:
        lines.append("- 关系快照只提供上一刻的基线，不是让你口头改关系；一切变化必须落在镜头可拍的行动上。")
    return "\n".join(lines)
