"""测试页“自动修复”全套（从 short_drama_writing.py 抽出）。

7 个函数：

- build_internal_rewrite_prompt：失败重试时把审段失败原因拼成重写指令
- testing_character_names_by_ids：按 id 集合反查角色名
- testing_fallback_speaker：在请求里挑一个 fallback 主讲人
- insert_testing_line_after_header：在场次标头后插一行（避免重复 / 跳过 △ 行）
- apply_testing_narrative_autofix_fallback：结构化兜底修复（婚书分层、债务口径、关系跳档等）
- build_testing_autofix_directives：根据 evaluation 拼定向修复指令
- auto_fix_testing_script_content：自动修复主流程（结构化兜底 + LLM 重写 + 字数 resize）

`auto_fix_testing_script_content` 调 LLM（generate_text），其余纯函数。
"""
from __future__ import annotations

import re
from typing import Any, TYPE_CHECKING

from fastapi import HTTPException

from app.schemas.short_drama_writing import (
    BenchmarkAssessment,
    ContinuityAssessment,
    TestingScriptAutoFixResponse,
)
from app.services.short_drama_canon_blocks import format_testing_canon_block
from app.services.short_drama_advanced_generation import apply_testing_generation_route
from app.services.short_drama_deep_audit import generation_kwargs_from_req
from app.services.short_drama_final_generation_contract import (
    current_testing_final_generation_contract,
    format_final_generation_contract_block,
)
from app.services.short_drama_evaluate_scene import evaluate_testing_scene
from app.services.short_drama_evaluation_pipeline import (
    apply_scene_level_gate,
    evaluation_score,
    promote_scene_word_count_warnings,
)
from app.services.short_drama_format_repairs import (
    apply_testing_hard_repairs,
    expected_testing_scene_header,
)
from app.services.short_drama_quality_anchors import build_testing_quality_anchor_block
from app.services.short_drama_rule_resolver import resolve_rules_injection
from app.services.short_drama_state_cards import build_testing_state_cards_block
from app.services.short_drama_stage_trace import timed_stage
from app.services.short_drama_testing_failure import (
    build_testing_skill_workflow,
    log_testing_failure_analysis,
)
from app.services.short_drama_testing_rules import (
    build_testing_format_rule,
    build_testing_length_rule,
)
from app.services.short_drama_text_format import is_testing_header_line
from app.services.duration_profile_service import infer_duration_profile
from app.services.text_generation_service import generate_text

if TYPE_CHECKING:
    from app.schemas.short_drama_writing import (
        TestingScriptRequest,
        TestingScriptValidationRequest,
    )


def build_internal_rewrite_prompt(
    base_user_prompt: str,
    evaluation: dict[str, Any],
    *,
    previous_content: str,
) -> str:
    """失败重试时把审段失败原因拼成重写指令。"""
    failure = evaluation.get("failure_analysis") if isinstance(evaluation.get("failure_analysis"), dict) else {}
    failure_type = str(failure.get("failure_type") or "").strip()
    repair_items = [
        *[f"硬伤：{item}" for item in (evaluation.get("blocking_issues") or [])[:5]],
        *[f"审段：{item}" for item in (evaluation.get("quality_issues") or [])[:4]],
    ]
    repair_block = "\n".join(f"- {item}" for item in repair_items if item) or "- 让这段戏更像真正可拍、可推进的短剧段落。"
    extra_directives: list[str] = []
    if failure_type == "anchor_missing":
        extra_directives.extend([
            "- 主角必须有具名标准台词，不要只给动作。",
            "- 若当前冲突已经落到主角身上，主角当场必须说出判断、拒绝或反刺。",
        ])
    if failure_type == "state_drift":
        extra_directives.extend([
            "- 不得改写前文已经成立的关系站位、事实归属或局势结果。",
            "- 若要推进关系或信息，必须写出触发动作和即时后果。",
        ])
    if failure_type == "dramatic_weakness":
        extra_directives.extend([
            "- 不要补解释，优先补动作、卡点、反问、打断和当场后果。",
        ])
    extra_block = "\n".join(extra_directives)
    return (
        f"{base_user_prompt}\n\n"
        "## 内部审段未通过，请整体重写这一版。\n"
        "要求：保留当前剧情方向，但把戏写实、写透、写成动作和后果，不要只是解释。\n"
        f"{repair_block}\n\n"
        + (f"## 失败定向修复\n{extra_block}\n\n" if extra_block else "")
        +
        "## 上一版正文（只用于理解问题，不要机械修补）\n"
        f"{previous_content[:1600]}"
    )


def testing_character_names_by_ids(characters: list[dict[str, Any]], ids: set[str]) -> list[str]:
    """按 id 集合反查角色名。"""
    names: list[str] = []
    for item in characters or []:
        if not isinstance(item, dict):
            continue
        char_id = str(item.get("id") or "").strip()
        name = str(item.get("name") or "").strip()
        if char_id and name and char_id in ids:
            names.append(name)
    return names


def testing_fallback_speaker(req: "TestingScriptRequest", *, prefer_supporting: bool = False) -> str:
    """在请求里挑一个 fallback 主讲人（按 protagonist/supporting/antagonist 顺序）。"""
    role_order = ("supporting", "protagonist", "antagonist") if prefer_supporting else ("protagonist", "supporting", "antagonist")
    selected_ids = {str(item or "").strip() for item in (req.selected_character_ids or []) if str(item or "").strip()}
    characters = [item for item in (req.characters or []) if isinstance(item, dict)]
    scoped = [
        item for item in characters
        if not selected_ids or str(item.get("id") or "").strip() in selected_ids
    ] or characters
    for role in role_order:
        for item in scoped:
            if str(item.get("role") or "").strip() == role and str(item.get("name") or "").strip():
                return str(item.get("name") or "").strip()
    for item in scoped:
        name = str(item.get("name") or "").strip()
        if name:
            return name
    return "主角"


def insert_testing_line_after_header(lines: list[str], new_line: str) -> list[str]:
    """在场次标头后插一行（避免重复 / 跳过 △ 行）。"""
    cleaned = str(new_line or "").strip()
    if not cleaned or any(cleaned == str(line or "").strip() for line in lines):
        return lines
    insert_at = 1 if lines and is_testing_header_line(str(lines[0] or "").strip()) else 0
    if insert_at < len(lines) and str(lines[insert_at] or "").lstrip().startswith("△"):
        insert_at += 1
    return [*lines[:insert_at], cleaned, *lines[insert_at:]]


def apply_testing_narrative_autofix_fallback(
    req: "TestingScriptValidationRequest",
    content: str,
    blocking_issues: list[str],
) -> str:
    """Deterministic last-mile repairs for structural narrative blockers.

    These are intentionally small bridge/definition inserts. They keep the
    creative text mostly intact but ensure the exact failed causal link is no
    longer left for the model to infer.
    """
    text = apply_testing_hard_repairs(req, str(content or "").strip())
    if not text:
        return text

    issues = [str(item or "").strip() for item in (blocking_issues or []) if str(item or "").strip()]
    if not issues:
        return text

    lines = [line.rstrip() for line in text.splitlines() if str(line or "").strip()]
    if not lines:
        return text

    protagonist = testing_fallback_speaker(req)
    helper = testing_fallback_speaker(req, prefer_supporting=True)
    continuity_gate_issue = any("连续性深审未通过" in issue for issue in issues)
    truth_reveal_issue = any(
        any(token in issue for token in ("提前暴露", "前置释放", "死因", "复仇线", "核心真相", "提前说穿", "身份真相", "旧案", "幕后黑手", "定案"))
        for issue in issues
    )
    future_preplay_issue = any(
        any(token in issue for token in ("预演", "提前消耗", "未来集", "后续集", "情节点", "同质"))
        for issue in issues
    )
    official_bridge_issue = any(
        ("官方闭环证据" in issue)
        or any(token in issue for token in ("官方闭环", "送证", "核验", "移交", "备案"))
        for issue in issues
    )
    relationship_leap_issue = any(
        ("角色转向" in issue)
        or any(token in issue for token in ("强度跃升", "态度从", "立场", "关系跳档", "过渡动作", "翻转", "并肩抗敌"))
        for issue in issues
    )

    if any("关键文书/规则" in issue or "婚书/文书体系" in issue for issue in issues):
        definition_line = (
            f"{protagonist}（压低声音）：这几份东西不是一回事，私契只是私下约定，"
            "族中正约只是族里留底，官府判词才算外头能认的定论。"
        )
        lines = insert_testing_line_after_header(lines, definition_line)

        rewritten: list[str] = []
        for line in lines:
            stripped = str(line or "").strip()
            if (
                ("官府判词" in stripped or "判词" in stripped)
                and any(marker in stripped for marker in ("从今日起", "唯一正室", "立刻", "今天就得认", "自然也作数"))
                and "递到" not in stripped
                and "过堂" not in stripped
            ):
                speaker = stripped.split("：", 1)[0] if "：" in stripped else protagonist
                if protagonist and protagonist in speaker:
                    rewritten.append(f"{speaker}：判词还要等官府过堂落印，今晚这一步，只是先把私契和族中正约递到明面上。")
                else:
                    rewritten.append(f"{speaker}：只要官府还没过堂落印，族里就不能把私契、正约和判词混成一回事。")
                continue
            rewritten.append(line)
        lines = rewritten

    if official_bridge_issue:
        bridge_line = (
            f"{helper}（递出回执）：昨夜材料已经提交到受理处，仓单、录音和口供都做了备案，"
            "今天只是先现场核验，不是直接落最终结论。"
        )
        replaced_bridge = False
        rewritten = []
        for line in lines:
            stripped = str(line or "").strip()
            if any(marker in stripped for marker in ("还没送出去", "还没递交", "还没提交", "还没上报", "没送出去")):
                speaker = stripped.split("：", 1)[0] if "：" in stripped else helper
                rewritten.append(f"{speaker}：昨夜已经提交到受理处了，回执在这里，今天先核验来源。")
                replaced_bridge = True
                continue
            if (
                any(marker in stripped for marker in ("已经完成复核", "今天就冻结", "今天正式立案", "调查结论已经出来", "今天就立案"))
                and any(marker in stripped for marker in ("监管", "工作组", "清查组", "调查组", "警方", "法院", "冻结", "立案"))
            ):
                speaker = stripped.split("：", 1)[0] if "：" in stripped else "调查人员"
                rewritten.append(f"{speaker}：我们收到提交材料，先备案核验；复核通过后，再决定是否立案或冻结。")
                replaced_bridge = True
                continue
            rewritten.append(line)
        lines = rewritten
        if not replaced_bridge:
            lines = insert_testing_line_after_header(lines, bridge_line)

    if any("核心债务" in issue for issue in issues):
        debt_line = (
            f"{protagonist}（盯住欠条）：先把口径锁死，原始责任只有一笔，"
            "其他名字都是挂名、篡改或转嫁，不能混成同一笔账。"
        )
        lines = insert_testing_line_after_header(lines, debt_line)

    if relationship_leap_issue:
        if helper == protagonist:
            turn_line = f"{protagonist}（盯着桌面）：你不是忽然改口，得把你刚看到的证据说清楚，不然我不信。"
        else:
            turn_line = f"{helper}（把证据推到桌上）：她刚看见这份证据，才知道前面一直站错了边。"
        lines = insert_testing_line_after_header(lines, turn_line)
        motion_line = (
            f"△{protagonist}没有立刻贴过去，只把手里的纸按在掌心，脚下仍与{helper}隔着半步，"
            "像先借这一把力顶眼前，不肯把试探一步写成同盟。"
        )
        lines = insert_testing_line_after_header(lines, motion_line)

    if continuity_gate_issue:
        issue_text = " ".join(issues)
        rewritten = []
        for line in lines:
            stripped = str(line or "").strip()
            candidate = stripped
            if "三天" in issue_text and "三年" in candidate:
                candidate = candidate.replace("三年", "三天")
            if any(marker in candidate for marker in ("一起查", "共同查", "默契配合", "早有合作基础", "合作基础", "并肩抗敌", "同盟")):
                if "：" in candidate:
                    speaker = candidate.split("：", 1)[0]
                    candidate = f"{speaker}：这一步先把眼前这张纸对清楚，别的账，等过了今天再各自去查。"
                else:
                    candidate = f"△{protagonist}和{helper}谁也没先靠近，只隔着桌角把眼前这一步对清。"
            if truth_reveal_issue and any(marker in candidate for marker in ("死因", "旧案", "幕后黑手", "就是他干的", "真相已经明了", "真相已明", "我爹的命", "仇", "定案", "就是你", "就是他")):
                if "：" in candidate:
                    speaker = candidate.split("：", 1)[0]
                    candidate = f"{speaker}：这话我先记下，眼前只看这纸边和你刚才那一下反应，别的真相还不能现在说死。"
                else:
                    candidate = f"△{protagonist}心里一沉，却没把那层旧事当场掀开，只先记住纸边和{helper}忽快的一下脉跳。"
            if future_preplay_issue and any(marker in candidate for marker in ("明天", "后天", "改天", "回头就", "之后就", "到时候", "以后我就", "等我", "带你", "迁户", "一起查到底", "堵门", "拦人", "截人", "吉普车")):
                if "：" in candidate:
                    speaker = candidate.split("：", 1)[0]
                    candidate = f"{speaker}：今晚先把眼前这一步顶过去，后头的事还不能在这会儿先说成安排。"
                else:
                    candidate = f"△{protagonist}没把后头那一步提前摆到台面上，只把眼前这口气硬生生压住。"
            rewritten.append(candidate)
        lines = rewritten

        continuity_line = (
            f"△{protagonist}把那句冲到嘴边的话压了回去，视线只在那张纸边停了一瞬，"
            "没顺着一个细节就把对方当成已经站到自己这边。"
        )
        lines = insert_testing_line_after_header(lines, continuity_line)

    if truth_reveal_issue:
        spoiler_boundary_line = f"△{protagonist}把话压回去，只盯住纸边和对方刚才那一下反应，没有把旧账当场说死。"
        lines = insert_testing_line_after_header(lines, spoiler_boundary_line)

    if future_preplay_issue:
        future_boundary_line = f"△{protagonist}没有接后头的安排，只把眼前那张纸按在桌上，先逼对方给现在这一关说法。"
        lines = insert_testing_line_after_header(lines, future_boundary_line)

    if any("重复开局" in issue or "重新开" in issue for issue in issues):
        progress_line = f"△{protagonist}没有重演上一场的开局，只把上一集留下的东西推回桌面，让对方接着给结果。"
        lines = insert_testing_line_after_header(lines, progress_line)
        rewritten = []
        for line in lines:
            stripped = str(line or "").strip()
            if any(marker in stripped for marker in ("跟我走", "带回家", "先住我这", "当众把她带回家")):
                if "：" in stripped:
                    speaker = stripped.split("：", 1)[0]
                    rewritten.append(f"{speaker}：人已经带回来了，现在说清楚下一步怎么安置。")
                else:
                    rewritten.append(f"△ {protagonist}站在门内，没有再被带走，新的问题压到眼前。")
                continue
            if any(marker in stripped for marker in ("暴雨", "雨夜", "拦车", "一把拉住")) and not is_testing_header_line(stripped):
                rewritten.append(f"△ 门内的灯还亮着，上一场雨夜的狼狈没有散，新的对峙已经压到屋里。")
                continue
            if any(marker in stripped for marker in ("围观的人", "围观")):
                rewritten.append("△ 屋里一静，门外的议论被关在雨声后面。")
                continue
            rewritten.append(line)
        lines = rewritten

    compacted: list[str] = []
    seen_recent: set[str] = set()
    for line in lines:
        stripped = str(line or "").strip()
        if not stripped:
            continue
        if stripped in seen_recent:
            continue
        compacted.append(line)
        seen_recent.add(stripped)
        if len(seen_recent) > 6:
            seen_recent = {str(item or "").strip() for item in compacted[-6:]}

    return apply_testing_hard_repairs(req, "\n".join(line for line in compacted if str(line or "").strip()))


def build_testing_autofix_directives(
    req: "TestingScriptValidationRequest",
    evaluation: TestingScriptAutoFixResponse,
    *,
    original: str,
) -> list[str]:
    """根据 evaluation 拼定向修复指令。"""
    blocking = [str(item or "").strip() for item in (evaluation.blocking_issues or []) if str(item or "").strip()]
    warnings = [str(item or "").strip() for item in (evaluation.warnings or []) if str(item or "").strip()]
    health_items = [item for item in (evaluation.health_items or []) if isinstance(item, dict)]
    selected_ids = {str(item).strip() for item in (req.selected_character_ids or []) if str(item).strip()}
    selected_names = testing_character_names_by_ids(req.characters or [], selected_ids)
    present_ids = {str(item or "").strip() for item in (evaluation.present_character_ids or []) if str(item or "").strip()}
    unexpected_present_ids = {item for item in present_ids if selected_ids and item not in selected_ids}
    unexpected_present_names = testing_character_names_by_ids(req.characters or [], unexpected_present_ids)
    missing_dialogue_names = [
        str(item.get("name") or "").strip()
        for item in health_items
        if item.get("present") and int(item.get("dialogue_count") or 0) == 0 and str(item.get("name") or "").strip()
    ]
    overused_os_names = [
        str(item.get("name") or "").strip()
        for item in health_items
        if str(item.get("role") or "").strip() == "protagonist"
        and item.get("present")
        and int(item.get("os_count") or 0) > 2
        and str(item.get("name") or "").strip()
    ]
    continuity_gate_issue = any("连续性深审未通过" in issue for issue in blocking)
    overused_os_issue = any("OS" in issue and ("偏多" in issue or "过密" in issue) for issue in blocking + warnings)
    truth_reveal_issue = any(
        any(token in issue for token in ("提前暴露", "前置释放", "死因", "复仇线", "核心真相", "提前说穿", "身份真相", "旧案", "幕后黑手", "定案"))
        for issue in blocking
    )
    future_preplay_issue = any(
        any(token in issue for token in ("预演", "提前消耗", "未来集", "后续集", "情节点", "同质"))
        for issue in blocking
    )
    official_bridge_issue = any(
        ("官方闭环证据" in issue)
        or any(token in issue for token in ("官方闭环", "送证", "核验", "移交", "备案"))
        for issue in blocking
    )
    relationship_leap_issue = any(
        ("角色转向" in issue)
        or any(token in issue for token in ("强度跃升", "态度从", "立场", "关系跳档", "过渡动作", "翻转", "并肩抗敌"))
        for issue in blocking
    )
    head_consequence_issue = any("头部爆点后果弱" in issue or "当场后果偏弱" in issue for issue in blocking + warnings)
    opening_weak_issue = any("开篇钩子弱" in issue for issue in blocking + warnings)
    satisfaction_density_issue = any("爽点密度不足" in issue for issue in blocking + warnings)
    villain_template_issue = any("反派压制模板化" in issue or "反派台词模板化" in issue for issue in blocking + warnings)
    patch_template_issue = any("项目打磨模板污染" in issue for issue in blocking + warnings)
    finale_closure_issue = any("终局闭环不足" in issue for issue in blocking + warnings)
    dialogue_short_issue = any("台词短句化不足" in issue for issue in blocking + warnings)

    directives: list[str] = []
    if any("场次标头" in issue for issue in blocking):
        directives.append(f"场次标头必须严格修成：{expected_testing_scene_header(req, original.splitlines()[0] if original else '')}")
    if any("缺少以 `△` 起笔的动作行" in issue for issue in blocking):
        directives.append("正文里至少保留 1 行以 △ 起笔的动作行，优先放在开场或关键情绪反应处。")
    if any("缺少标准台词 / OS / VO 行" in issue for issue in blocking):
        directives.append("正文里必须出现标准台词或 OS 行，不能只有概述性动作。")
    if any("净字数超限" in issue for issue in blocking):
        directives.append("必须裁掉重复解释、重复情绪、可顺延到下段/下集的信息，严格收进字数上限。")
    if any("净字数不足" in issue for issue in blocking):
        directives.append("必须补足到字数区间，优先补具体动作、标准台词、当场后果，不要补总结旁白。")
    if opening_weak_issue:
        directives.append("漫剧前三集开头前5行必须补可见压力：羞辱、威胁、代价、身份差、异常或金手指触发至少命中1类，且要落成动作/台词，不要写成背景介绍。")
    if satisfaction_density_issue:
        try:
            duration_seconds = int(round(float(req.episode_minutes or 1.5) * 60))
        except Exception:
            duration_seconds = 90
        expected_beats = 2 if duration_seconds <= 90 else 3
        directives.append(f"当前约{duration_seconds}秒漫剧至少{expected_beats}个可见爽点/信息增量：开场压迫、反击/亮证、围观站队、身份或规则反转、当场处罚/道歉/翻盘中至少补够。")
    if missing_dialogue_names:
        directives.append(f"这些已出场角色必须各自至少补 1 句标准台词或 OS：{'、'.join(dict.fromkeys(missing_dialogue_names))}。")
    if overused_os_names or overused_os_issue:
        names = "、".join(dict.fromkeys(overused_os_names)) or "主角"
        directives.append(f"压缩{names}的内心OS，现实题材最多保留1-2处，首尾必须改成动作、物件或对手反应。")
    if any("OS位置不当" in issue for issue in blocking):
        directives.append("只替换开头/结尾附近的OS，不要改主线：改成手停、物件露出、票据压桌、手机提示或对手反应。")
    if any("抽象结尾" in issue for issue in blocking):
        directives.append("只改最后1-3行，结尾必须落在本集真实物件、证据、动作或新阻力上，禁止决心/预示/总结句收尾。")
    if any("通用物件补丁" in issue for issue in blocking):
        directives.append("删除固定的“合同边角沾着面粉/录音红点”补丁，改成本集真实出现的空瓶、台账、批号、检测回执、订金纸条等物件。")
    if patch_template_issue:
        directives.append("删除“第N笔账/第N份留样/不能只说结果”等机械打磨句，改成本集真实发生的物件、动作和当场反应。")
    if any("小说化描写" in issue for issue in blocking):
        directives.append("只替换仿佛、似乎、眼神中、气氛等小说化句子，改为可拍动作和具体道具，不要扩写解释。")
    if head_consequence_issue:
        directives.append("必须补一个本题材内成立的可拍后果：关系变化、证据外露、资源被夺、身份坐标改变、第三方站队或现实代价任选其一，不要只升级争吵。")
    if villain_template_issue:
        directives.append("反派压制必须从空泛狠话改成具体动作：夺资源、截证据、制造误会、公开羞辱、逼迫选择、改写规则或推来新威胁。")
    if dialogue_short_issue:
        directives.append("把超过30净字的长台词拆成2-3句短对白，中间插入动作或物件反应，避免广播式说明。")
    if finale_closure_issue:
        directives.append("最后一集必须收实：写出连锁方处罚/停业/撤牌、社区早餐店落地、平价承诺或下岗工人就业；删除神秘文件、电话和续集式空钩子。")
    if selected_names:
        directives.append(f"本场优先围绕这些已勾选角色推进，不要把戏写飘：{'、'.join(selected_names)}。")
    if unexpected_present_names:
        directives.append(f"这些未勾选角色若非必要请删掉；必须保留时也要补标准台词且不能改动关系站位：{'、'.join(unexpected_present_names)}。")
    if evaluation.failure_analysis.failure_type == "state_drift":
        directives.append("必须重新对齐关系护栏、状态卡和当前正文，不得临时发明新的关系翻转、信息揭露或权力变化。")
    if continuity_gate_issue:
        directives.append("必须严格承接上一集已落地结果，不能提前兑现后续集钩子，也不能把关系线突然跳档。")
        directives.append("涉及时间、金额、年限、次数等口径时，必须沿用前文已落地说法，不能把短时夸大成长时。")
        directives.append("若双方仍在试探期，禁止直接写成‘一起查/共同查/默契配合/早有合作基础’，只能写成临时借力、各算各账。")
    if truth_reveal_issue:
        directives.append("涉及林父死因、幕后黑手、核心复仇账或身份真相时，只能保留怀疑、异样和身体反应，禁止直接说成定案。")
        directives.append("不得原样保留‘死因就是…/就是赵有财…/真相已明/仇已经对上’这类定性句，必须改成先记下疑点、暂不掀底。")
    if future_preplay_issue:
        directives.append("不得提前写出后续集才会发生的明确安排、路线、场面模板或动作承诺；当前集只能处理眼前这一步。")
        directives.append("删改‘明天/后天/回头就/到时候/等我带你…/一起查到底/堵门拦人’这类未来承诺句，改成只处理当前阻力。")
    if any("剧作契约冲突" in issue or "契约阻断" in issue for issue in blocking):
        directives.append("必须回到“全剧推演沙盘/本集剧作契约”：开场承接上一集结果，只兑现本集必须发生，删除提前定案、提前揭底或关系跳档。")
    if any("本集开局与前集已落地结果重复度过高" in issue for issue in blocking):
        directives.append("本集开场必须从上一集结果继续往前推，不能重演已经完成过的开局动作。")
    if any("核心债务" in issue for issue in blocking):
        directives.append("必须锁死债务唯一主口径，并明确说明其他说法只是篡改、嫁祸或施压话术。")
    if any("关键文书/规则" in issue or "婚书/文书体系" in issue for issue in blocking):
        directives.append("必须补一句法理定义，讲清当前出现的文书分别属于哪一层关系，不能混写成同一回事。")
        directives.append("涉及文书/规则的原句必须重写，至少明确写出“哪份只是私下/族内层，哪份才算官方层”，不能原样保留冲突句。")
    if official_bridge_issue:
        directives.append("必须补出送证、核验、移交或备案动作，让地方线索转成官方证据有桥可见。")
        directives.append("不得原样保留“已经复核完/今天就冻结/今天就立案”这类结果句；必须改成先提交、再受理、再核验的过程句。")
    if relationship_leap_issue:
        directives.append("必须补出导致转口的触发事实、人物反应和当场后果，不能让角色无缘无故突然倒向另一边。")
        directives.append("若关系强度跃升，必须写出站位变化、递物/挡人/让路等可拍动作，且人物台词里要保留迟疑或试探，不能一步跳成同盟。")
    if not directives and warnings:
        directives.append(f"优先修掉这些提醒里最硬的一层：{'；'.join(warnings[:4])}")
    return directives


def auto_fix_testing_script_content(req: "TestingScriptValidationRequest", original: str) -> TestingScriptAutoFixResponse:
    """自动修复主流程：结构化兜底 + LLM 重写 + 字数 resize。"""
    if not original:
        raise HTTPException(status_code=400, detail="当前正文为空，无法自动修复。")
    original = apply_testing_hard_repairs(req, original)

    def _validate_payload(content_text: str) -> TestingScriptAutoFixResponse:
        content_text = apply_testing_hard_repairs(req, content_text)
        validation_req = req.model_copy(update={
            "scene_content": content_text,
            "autofix_lightweight_validation": True,
        })
        with timed_stage(validation_req, "autofix_validate"):
            evaluation = evaluate_testing_scene(validation_req, content_text, build_testing_quality_anchor_block(validation_req))
        evaluation = promote_scene_word_count_warnings(validation_req, evaluation)
        if not validation_req.autofix_lightweight_validation:
            evaluation = apply_scene_level_gate(
                validation_req,
                evaluation,
                current_testing_final_generation_contract(validation_req),
            )
        failure_analysis = evaluation["failure_analysis"]
        skill_workflow = build_testing_skill_workflow(
            failure_analysis,
            blocking_issues=evaluation["blocking_issues"],
            warnings=evaluation["warnings"],
            context="testing_auto_fix",
        )
        return TestingScriptAutoFixResponse(
            success=not evaluation["blocking_issues"],
            content=content_text,
            char_count_excluding_punctuation=evaluation["char_count_excluding_punctuation"],
            warnings=evaluation["warnings"],
            blocking_issues=evaluation["blocking_issues"],
            present_character_ids=evaluation["present_character_ids"],
            health_items=evaluation["health_items"],
            relationship_suggestions=evaluation["relationship_suggestions"],
            state_card_suggestions=evaluation["state_card_suggestions"],
            benchmark_assessment=evaluation.get("benchmark_assessment") or BenchmarkAssessment(),
            continuity_assessment=evaluation.get("continuity_assessment") or ContinuityAssessment(),
            failure_analysis=failure_analysis,
            skill_workflow=skill_workflow,
            episode_memory_card=evaluation.get("episode_memory_card") or {},
            canon_packet=evaluation.get("canon_packet") or {},
            message="当前正文无需修复。" if not evaluation["blocking_issues"] else "仍存在阻断项。",
        )

    def _is_length_only_blocked(response: TestingScriptAutoFixResponse) -> bool:
        issues = [str(item or "").strip() for item in (response.blocking_issues or []) if str(item or "").strip()]
        if not issues:
            return False
        return all(("净字数不足" in item) or ("净字数超限" in item) for item in issues)

    initial = _validate_payload(original)
    if not initial.blocking_issues:
        initial.success = True
        initial.message = "当前正文没有阻断项，无需自动修复。"
        return initial

    narrative_tokens = ("核心债务", "重复开局", "重新开", "婚书/文书体系", "关键文书/规则", "官方闭环证据", "角色转向", "连续性深审未通过", "剧作契约冲突", "契约阻断", "头部爆点后果弱", "反派压制模板化", "项目打磨模板污染", "终局闭环不足")
    if any(
        token in str(item or "")
        for item in (initial.blocking_issues or [])
        for token in narrative_tokens
    ):
        fallback_content = apply_testing_narrative_autofix_fallback(req, original, initial.blocking_issues)
        fallback_candidate = _validate_payload(fallback_content)
        if len(fallback_candidate.blocking_issues) < len(initial.blocking_issues):
            initial = fallback_candidate
            original = fallback_candidate.content
        if not fallback_candidate.blocking_issues:
            fallback_candidate.success = True
            fallback_candidate.message = "阻断项已通过结构化兜底修复。"
            return fallback_candidate

    style_ex = "【场1-1：夜  内  书房】" if req.scene_header_style == "bracket" else "1-1  夜  内  书房"
    target_min = int(req.word_count_min or 0)
    target_max = int(req.word_count_max or 0)
    if target_min and target_max:
        length_directive = (
            f"【字数硬约束 — 最高优先级】重写后净字数（不含标点空白）必须落在 {target_min}-{target_max} 字。"
            f"如果原稿字数低于 {target_min}，必须主动扩写：增补具体动作行（△...）、补充关键对白、把概述句拆成可拍场面，直到达到 {target_min}-{target_max}。"
            f"如果原稿字数高于 {target_max}，必须压缩：删冗余对白、合并动作描述、删与冲突无关的细节。"
            "扩写或压缩的选择由『目标字数』决定，**不要参考原稿长度**作为约束。"
        )
    else:
        length_directive = "保持叙事密度，不要灌水也不要拖沓。"

    audience_axis = req.audience_axis or "男频"
    global_rules = resolve_rules_injection("{{rules:short_drama_core}}\n{{rules:audience_rules}}", {"audience_axis": audience_axis})

    system_prompt = (
        "你是短剧剧本修复器。任务：修复当前正文中的阻断项 + 让字数严格落入目标硬区间。\n"
        f"【全局短剧规则】（修复时必须遵守）：\n{global_rules}\n\n"
        "禁止解释，禁止列清单，禁止输出修复说明。\n"
        "【格式要求】：\n"
        "请将修复后的正文放在 <fixed_content> 标签内。\n"
        "如果因为字数限制删除了部分原定剧情（比如次要情节、铺垫或次要冲突），请将其总结在 <overflow_content> 标签内，以便顺延到下一集。如果没有删减关键剧情，<overflow_content> 可留空。\n"
        f"{length_directive}\n"
        "其它修复优先级：1. 场次与剧本格式；2. 动作行/台词行；3. 主角未出场；4. 标准台词与现实动作；5. 连续性与关系状态。"
        "若阻断项来自头部对标，必须局部补强公开压迫、当场后果、反派具体动作、物件钩子或终局闭环，不得整段重启剧情。"
        "如果主角未出场，允许在不改变主剧情方向的前提下补一个极短入场动作或台词。"
        "如果角色已经出场但没有标准台词，补一条短促、人物化、可拍的标准台词或 OS。"
        "现实/市井/创业题材不要为了补情绪而硬加 OS；OS 最多1-2处，首尾优先改成动作、物件、票据、手机提示或围观反应。"
        "如果阻断项属于连续性/设定/因果问题，必须改写触发该问题的关键句，不能只表面润色。"
        "若命中官方证据桥接、文书分层或角色转向问题，正文里必须新增可见的桥接句或定义句。"
        f"场次标头格式参考：{style_ex}"
    )
    fix_rules = "\n".join(f"- {item}" for item in initial.blocking_issues[:5])
    targeted_directives = build_testing_autofix_directives(req, initial, original=original)
    targeted_block = "\n".join(f"- {item}" for item in targeted_directives) or "- 优先把正文修回可拍、可承接、可放行状态。"
    user_prompt = (
        "请修复下面这段短剧正文中的阻断项，保留原有剧情和绝大多数有效表达。\n\n"
        f"## 必须修掉的阻断项\n{fix_rules}\n\n"
        f"## 定向修复动作\n{targeted_block}\n\n"
        "## 格式规则\n"
        f"{build_testing_format_rule(req)}\n\n"
        "## 字数规则\n"
        f"{build_testing_length_rule(req)}\n\n"
        "## 关系护栏\n"
        f"{str(req.relationship_guardrails or '').strip() or '无'}\n\n"
        "## 状态卡\n"
        f"{build_testing_state_cards_block(req.state_cards or {}, req.characters or [], set(req.selected_character_ids or []), current_episode=int(req.episode_no or 0))}\n\n"
        "## Canon 包\n"
        f"{format_testing_canon_block(req)}\n\n"
        "## 最终生成合同 / 本集剧作契约\n"
        f"{format_final_generation_contract_block(req, for_writer=True)}\n\n"
        "## 当前正文（请直接在此基础上修复）\n"
        f"{original}\n\n"
        "请按要求使用 <fixed_content> 和 <overflow_content> 标签输出，不要任何其他解释。"
    )

    best = initial
    attempt_limit = 3 if any(
        token in str(item or "")
        for item in (initial.blocking_issues or [])
        for token in narrative_tokens
    ) else 2
    if getattr(req, "autofix_single_pass", False):
        attempt_limit = 1
    rewrite_req, _ = apply_testing_generation_route(req, "script_draft", 0.2)
    for _ in range(attempt_limit):
        with timed_stage(rewrite_req, "autofix_llm_rewrite"):
            fixed = generate_text(
                system_prompt,
                user_prompt,
                **generation_kwargs_from_req(rewrite_req),
                temperature=0.2,
                max_tokens=5000,
            )

        fixed_str = str(fixed or "").strip()
        overflow_content = ""
        overflow_match = re.search(r"<overflow_content>(.*?)</overflow_content>", fixed_str, re.DOTALL)
        if overflow_match:
            overflow_content = overflow_match.group(1).strip()

        fixed_match = re.search(r"<fixed_content>(.*?)</fixed_content>", fixed_str, re.DOTALL)
        if fixed_match:
            fixed_str = fixed_match.group(1).strip()
        else:
            fixed_str = re.sub(r"<overflow_content>.*?</overflow_content>", "", fixed_str, flags=re.DOTALL).strip()

        candidate = _validate_payload(apply_testing_hard_repairs(req, fixed_str))
        candidate.overflow_content = overflow_content

        if len(candidate.blocking_issues) < len(best.blocking_issues):
            best = candidate
        if not candidate.blocking_issues:
            candidate.success = True
            candidate.message = "阻断项已自动修复。"
            return candidate
        retry_directives = build_testing_autofix_directives(req, candidate, original=candidate.content)
        user_prompt = (
            "上一版修复后仍然存在阻断项，请继续在不改变剧情主干的前提下整体重写并修掉这些问题。\n\n"
            f"## 仍需修复\n{chr(10).join(f'- {item}' for item in candidate.blocking_issues[:5])}\n\n"
            f"## 继续定向修复\n{chr(10).join(f'- {item}' for item in retry_directives[:8])}\n\n"
            "## 当前待修正文\n"
            f"{candidate.content}"
        )

    if any(
        token in str(item or "")
        for item in (best.blocking_issues or [])
        for token in narrative_tokens
    ):
        fallback_content = apply_testing_narrative_autofix_fallback(req, best.content or original, best.blocking_issues)
        fallback_candidate = _validate_payload(fallback_content)
        if len(fallback_candidate.blocking_issues) < len(best.blocking_issues):
            best = fallback_candidate
        if not fallback_candidate.blocking_issues:
            fallback_candidate.success = True
            fallback_candidate.message = "阻断项已通过结构化兜底修复。"
            return fallback_candidate

    if req.mode == "scene" and _is_length_only_blocked(best):
        profile = infer_duration_profile(
            episode_minutes=req.episode_minutes,
            explicit_min=req.word_count_min,
            explicit_max=req.word_count_max,
            explicit_target=req.word_count_target or req.target_chars,
            market_format=req.format_type or req.project_type,
        )
        target_length = profile.target_chars
        hard_min = profile.min_chars
        hard_max = profile.max_chars
        resize_tokens = min(4000, max(2000, int(hard_max * 2.5)))
        resize_system_prompt = (
            "你是短剧终稿压缩修复器。你的目标只有一个：在不改掉主线因果、人物关系、情绪锚点和结尾钩子的前提下，"
            "把正文严格修到字数区间内。\n"
            f"【全局短剧规则】（修复时必须遵守）：\n{global_rules}\n\n"
            "禁止解释，禁止总结，禁止列清单。\n"
            "【格式要求】：\n"
            "请将修复后的正文放在 <fixed_content> 标签内。\n"
            "如果因为字数限制删除了部分原定剧情（比如某些次要情节、铺垫或本集的次要冲突），请将其总结在 <overflow_content> 标签内，以便顺延到下一集。如果没有删减关键剧情，<overflow_content> 可留空。\n"
        )
        resize_source = best.content or original
        resize_attempt_limit = 1 if getattr(req, "autofix_single_pass", False) else 3
        for _ in range(resize_attempt_limit):
            resize_prompt = (
                "请把下面这段短剧终稿修到严格字数区间内，同时保住主线推进、核心情绪和本集结尾钩子。\n\n"
                f"## 硬字数区间\n必须控制在 {hard_min}～{hard_max} 字之间，目标约 {target_length} 字。\n\n"
                "## 保留优先级\n"
                "- 必留：主角出场、返乡/探病/债务主线、核心关系变化、结尾钩子。\n"
                "- 可删：重复抒情、重复解释、次要动作、可挪到下一集的补充信息。\n\n"
                "## 格式规则\n"
                f"{build_testing_format_rule(req)}\n\n"
                "## 当前待修正文\n"
                f"{resize_source}\n\n"
                "请按要求使用 <fixed_content> 和 <overflow_content> 标签输出，不要任何其他解释。"
            )
            with timed_stage(req, "autofix_resize"):
                resized = generate_text(
                    resize_system_prompt,
                    resize_prompt,
                    **generation_kwargs_from_req(req),
                    temperature=0.1,
                    max_tokens=resize_tokens,
                )

            resized_str = str(resized or "").strip()
            overflow_content = ""
            overflow_match = re.search(r"<overflow_content>(.*?)</overflow_content>", resized_str, re.DOTALL)
            if overflow_match:
                overflow_content = overflow_match.group(1).strip()

            fixed_match = re.search(r"<fixed_content>(.*?)</fixed_content>", resized_str, re.DOTALL)
            if fixed_match:
                resized_str = fixed_match.group(1).strip()
            else:
                resized_str = re.sub(r"<overflow_content>.*?</overflow_content>", "", resized_str, flags=re.DOTALL).strip()

            candidate = _validate_payload(apply_testing_hard_repairs(req, resized_str))
            candidate.overflow_content = overflow_content

            if evaluation_score(candidate.model_dump()) < evaluation_score(best.model_dump()):
                best = candidate
            if not candidate.blocking_issues:
                candidate.success = True
                candidate.message = "阻断项已自动修复。"
                return candidate
            resize_source = candidate.content or resize_source

    best.success = False
    best.message = "已尝试自动修复，但仍有阻断项，请根据提示继续人工微调。"
    log_testing_failure_analysis(req, best.failure_analysis, {
        "blocking_issues": best.blocking_issues,
        "warnings": best.warnings,
        "failure_analysis": best.failure_analysis,
    })
    return best
