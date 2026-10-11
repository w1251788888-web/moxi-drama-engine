"""run-step / save-step / 工作台模板变量装配（从 short_drama_writing.py 抽出）。

1 个核心函数：

- build_base_template_vars：从 metadata 装出 prompt 模板需要的所有变量
  （project/inputs/materials/issue_feedback/state_cards_block/used_beats/cliffhanger/
   episode_outlines_block/beat_sheet/scene_list/script_draft/novel_analysis/
   commercial_score/primary_archetype/...）

依赖：state_cards、quality_helpers、material lab、step_payload、episode_slicers，全部已在 services。
"""
from __future__ import annotations

from typing import Any

from app.services.short_drama_episode_slicers import (
    slice_beat_sheet_by_episode,
    slice_novel_anchor_by_episode,
)
from app.services.short_drama_lab_service import (
    _build_selected_material_borrow_focus,
    _build_selected_material_do_not_copy,
    _build_selected_material_heat_signals,
    _build_selected_material_reference,
    _build_selected_material_risk_guardrails,
)
from app.services.short_drama_quality_helpers import (
    extract_step_text,
    project_config_value,
)
from app.services.short_drama_state_cards import build_testing_state_cards_block
from app.services.short_drama_step_payload import get_step_payload


def build_base_template_vars(
    metadata: dict,
    *,
    draft_episode: int,
    known_template_keys: tuple[str, ...],
) -> dict[str, str]:
    """从 metadata 装出 prompt 模板需要的所有变量。"""
    project = metadata.get("project") or {}
    inputs = metadata.get("inputs") or {}

    materials = metadata.get("materials") or []
    if not isinstance(materials, list):
        materials = []

    issue_feedback = metadata.get("issue_feedback") or {}
    if not isinstance(issue_feedback, dict):
        issue_feedback = {}

    retrieval_bias = issue_feedback.get("retrieval_bias") or {}
    if not isinstance(retrieval_bias, dict):
        retrieval_bias = {}

    prefer_points = [str(item).strip() for item in (retrieval_bias.get("prefer_borrow_points") or []) if str(item).strip()]
    negative_hints: list[str] = []
    if issue_feedback.get("summary"):
        negative_hints.append(str(issue_feedback.get("summary")))
    for item in issue_feedback.get("negative_prompt_hints") or []:
        text = str(item).strip()
        if text:
            negative_hints.append(text)
    if retrieval_bias.get("avoid_summary_like"):
        negative_hints.append("避免把文本写成总结、梗概或概括，必须落到具体场景、动作和人物反应。")
    if retrieval_bias.get("avoid_generic_risk"):
        negative_hints.append("避免使用空泛、保守、模板化表达，必须保留角色声音和场面张力。")

    review_focus_items = [str(item).strip() for item in (issue_feedback.get("review_focus") or []) if str(item).strip()]
    if not review_focus_items:
        for item in issue_feedback.get("open_issues") or []:
            if isinstance(item, dict):
                title = str(item.get("title") or item.get("issue_key") or "").strip()
                check_hint = str(item.get("review_check_hint") or "").strip()
                if title or check_hint:
                    review_focus_items.append("：".join(part for part in [title, check_hint] if part))

    storyboard_requirements = [
        "分镜要服务拍摄执行，逐场给出镜头目标、景别、关键动作、情绪推进和画面钩子。",
        "优先突出公开翻盘、围观反应、关系失衡、亮牌时刻等可视爆点。",
        "镜头语言只辅助执行，不要改写剧情，不要脱离 scene_list 和 script_draft 新编剧情。",
    ]

    base: dict[str, Any] = {
        "project_type": project.get("project_type", ""),
        "episode_count": project.get("episode_count", ""),
        "episode_minutes": project.get("episode_minutes", ""),
        "audience_axis": project.get("audience_axis", ""),
        "genre_main": project.get("genre_main", ""),
        "genre_sub": project.get("genre_sub", ""),
        "subgenre_track": project_config_value(project, "subgenre_track") or "",
        "sample_track": project_config_value(project, "sample_track") or "",
        "rule_profile": project.get("rule_profile", ""),
        "constraints": project.get("constraints", ""),
        "brief": inputs.get("brief", ""),
        "world_rules": inputs.get("world_rules", ""),
        "relationship_guardrails": inputs.get("relationship_guardrails", ""),
        "golden_finger_rules": inputs.get("golden_finger_rules", ""),
        "conflict_plan": inputs.get("conflict_plan", ""),
        "material_references": _build_selected_material_reference(materials),
        "material_borrow_focus": _build_selected_material_borrow_focus(materials),
        "material_heat_signals": _build_selected_material_heat_signals(materials),
        "material_risk_guardrails": _build_selected_material_risk_guardrails(materials),
        "material_do_not_copy": _build_selected_material_do_not_copy(materials),
        "issue_feedback_summary": str(issue_feedback.get("summary") or "当前项目暂无历史问题反馈。"),
        "negative_prompt_hints": "\n".join(f"- {item}" for item in dict.fromkeys(negative_hints) if item),
        "review_focus": "\n".join(f"- {item}" for item in dict.fromkeys(review_focus_items) if item) or "- 暂无额外审查重点。",
        "storyboard_requirements": "\n".join(f"- {item}" for item in storyboard_requirements),
        "draft_episode": str(draft_episode),
    }
    if prefer_points:
        base["material_borrow_focus"] = "\n".join([base["material_borrow_focus"], "- 历史问题优先借鉴点：" + "；".join(prefer_points)]).strip()

    state_cards = project.get("state_cards") or inputs.get("state_cards") or {}
    try:
        _project_ep = int(inputs.get("episode_no") or project.get("episode_no") or 0)
    except Exception:
        _project_ep = 0
    base["state_cards_block"] = build_testing_state_cards_block(
        state_cards,
        project.get("characters") or [],
        set(),
        current_episode=_project_ep,
    )
    # ── P2-修复10: 把 1..(draft_episode-1) 集累计的 state_card_delta 合并追加 ──
    try:
        cur_ep = int(draft_episode)
    except Exception:
        cur_ep = 0
    if cur_ep > 1:
        deltas: list[str] = []
        episodes = metadata.get("episodes") or {}
        if isinstance(episodes, dict):
            for k in sorted(episodes.keys(), key=lambda x: int(x) if str(x).isdigit() else 0):
                try:
                    n = int(k)
                except Exception:
                    continue
                if n <= 0 or n >= cur_ep:
                    continue
                node = episodes.get(k) or {}
                d = node.get("state_card_delta") if isinstance(node, dict) else None
                if not isinstance(d, dict) or not d:
                    continue
                bullets = []
                for axis in ("relationship", "info_chain", "power_shift", "open_promise", "no_change"):
                    val = d.get(axis)
                    if val:
                        bullets.append(f"  - {axis}: {val}")
                if bullets:
                    deltas.append(f"第{n}集 delta:\n" + "\n".join(bullets))
        if deltas:
            base["state_cards_block"] = (base["state_cards_block"] or "") + "\n\n## 历史集累计变更（state_card_delta）\n" + "\n\n".join(deltas)

    # ── 修复 20: used_beats_block 累计 1..(cur_ep-1) 集已用爆点 ────────
    if cur_ep > 1:
        used_lines: list[str] = []
        episodes2 = metadata.get("episodes") or {}
        if isinstance(episodes2, dict):
            for k in sorted(episodes2.keys(), key=lambda x: int(x) if str(x).isdigit() else 0):
                try:
                    n = int(k)
                except Exception:
                    continue
                if n <= 0 or n >= cur_ep:
                    continue
                node = episodes2.get(k) or {}
                used = node.get("used_beats") if isinstance(node, dict) else None
                if not isinstance(used, list):
                    continue
                for ub in used:
                    if not isinstance(ub, dict):
                        continue
                    line = f"  - 第{n}集 | 场景:{ub.get('scene','')} | 动作:{ub.get('action','')} | 目标:{ub.get('target','')} | 类型:{ub.get('type','')}"
                    used_lines.append(line)
        if used_lines:
            base["used_beats_block"] = (
                "## 历史已用爆点池（严禁本集再次使用同一场景+同一动作+同一目标的组合）\n"
                + "\n".join(used_lines[-40:])
            )
        else:
            base["used_beats_block"] = ""
    else:
        base["used_beats_block"] = ""

    # ── 修复 21: previous_cliffhanger 注入上集集尾倒钩 ───────────────
    if cur_ep > 1:
        prev_node = (metadata.get("episodes") or {}).get(str(cur_ep - 1)) or {}
        cliff = prev_node.get("cliffhanger_concrete") if isinstance(prev_node, dict) else None
        if isinstance(cliff, dict) and cliff:
            base["previous_cliffhanger"] = (
                f"## 上集集尾倒钩（本集第一场必须从此承接）\n"
                f"- 场所：{cliff.get('scene_location','')}\n"
                f"- 在场角色：{', '.join(cliff.get('characters_present',[])) if isinstance(cliff.get('characters_present'),list) else ''}\n"
                f"- 集尾定格：{cliff.get('freeze_frame','')}\n"
                f"- 下集开场必须承接：{cliff.get('next_episode_must_pick_up','')}\n"
                f"严禁开场跳到新场所或重启剧情；本集第一场必须以此定格画面为起点。"
            )
        else:
            base["previous_cliffhanger"] = ""
    else:
        base["previous_cliffhanger"] = ""

    # ── 打通：大纲编辑器"已确认进入主链"的内容作为剧本生成的权威来源 ──
    # 编辑器把已确认大纲存进 workflow_context.outline_state（项目级，多人协作共享）。
    # commit 后用它覆盖 concept/世界观/金手指/冲突/人物/集纲，确保剧本生成全部调用编辑器成果。
    # 这里先于下方 steps 的 setdefault 赋值，从而优先生效；整段 try 兜底，任何异常都不影响既有链路。
    try:
        _wc = metadata.get("workflow_context") if isinstance(metadata.get("workflow_context"), dict) else {}
        _ostate = _wc.get("outline_state") if isinstance(_wc.get("outline_state"), dict) else {}
        if _ostate.get("main_chain_committed"):
            _od = _ostate.get("outline_data") if isinstance(_ostate.get("outline_data"), dict) else {}
            _ochars = _ostate.get("outline_characters") if isinstance(_ostate.get("outline_characters"), list) else []

            def _ed_text(value: Any) -> str:
                return str(value or "").strip()

            if _ed_text(_od.get("worldview")):
                base["world_rules"] = _ed_text(_od.get("worldview"))
            if _ed_text(_od.get("goldenFinger")):
                base["golden_finger_rules"] = _ed_text(_od.get("goldenFinger"))
            if _ed_text(_od.get("conflict")):
                base["conflict_plan"] = _ed_text(_od.get("conflict"))

            _concept_parts = []
            if _ed_text(_od.get("logline")):
                _concept_parts.append(f"一句话梗概：{_ed_text(_od.get('logline'))}")
            if _ed_text(_od.get("worldview")):
                _concept_parts.append(f"世界观：{_ed_text(_od.get('worldview'))}")
            if _ed_text(_od.get("goldenFinger")):
                _concept_parts.append(f"金手指/差异化：{_ed_text(_od.get('goldenFinger'))}")
            if _ed_text(_od.get("conflict")):
                _concept_parts.append(f"核心冲突/爽点：{_ed_text(_od.get('conflict'))}")
            if _concept_parts:
                base["concept"] = "\n".join(_concept_parts)

            def _character_line(_c: dict[str, Any]) -> str:
                _parts = [
                    _ed_text(_c.get("info")),
                    _ed_text(_c.get("public_mask")) and f"公开面具：{_ed_text(_c.get('public_mask'))}",
                    _ed_text(_c.get("motivation")) and f"动机：{_ed_text(_c.get('motivation'))}",
                    _ed_text(_c.get("voiceprint")) and f"声纹：{_ed_text(_c.get('voiceprint'))}",
                    _ed_text(_c.get("inner_need")) and f"内在需求：{_ed_text(_c.get('inner_need'))}",
                    _ed_text(_c.get("resource")) and f"资源/筹码：{_ed_text(_c.get('resource'))}",
                    _ed_text(_c.get("limit_or_cost")) and f"限制/代价：{_ed_text(_c.get('limit_or_cost'))}",
                    _ed_text(_c.get("wound_or_flaw")) and f"伤口/弱点：{_ed_text(_c.get('wound_or_flaw'))}",
                    _ed_text(_c.get("arc") or _c.get("arc_checkpoints"))
                    and f"人物弧线：{_ed_text(_c.get('arc') or _c.get('arc_checkpoints'))}",
                    _ed_text(_c.get("first_appearance_function"))
                    and f"首次出场功能：{_ed_text(_c.get('first_appearance_function'))}",
                    _ed_text(_c.get("first_scene_function"))
                    and f"第一场功能：{_ed_text(_c.get('first_scene_function'))}",
                    _ed_text(_c.get("relationship_tension")) and f"关系张力：{_ed_text(_c.get('relationship_tension'))}",
                    _ed_text(_c.get("secret")) and f"底牌/秘密：{_ed_text(_c.get('secret'))}",
                ]
                _bio = "；".join(part for part in _parts if part)
                return f"- {_ed_text(_c.get('name'))}（{_ed_text(_c.get('role'))}）：{_bio}"

            _char_lines = [
                _character_line(c)
                for c in _ochars
                if isinstance(c, dict) and _ed_text(c.get("name"))
            ]
            if _char_lines:
                base["characters"] = "\n".join(_char_lines)

            def _eo_no(_e: Any) -> int:
                try:
                    return int(_e.get("ep") or _e.get("episodeNumber") or _e.get("episode") or 0)
                except Exception:
                    return 0

            _eps = [
                e for e in (_od.get("episodes") or [])
                if isinstance(e, dict) and _eo_no(e) > 0
            ]
            if _eps:
                try:
                    _cur_ep = int(draft_episode) if draft_episode else 0
                except Exception:
                    _cur_ep = 0
                if _cur_ep > 0:
                    _cur = next((e for e in _eps if _eo_no(e) == _cur_ep), None)
                    if _cur:
                        base["current_episode_outline"] = (
                            f"## 本集集纲（来自大纲编辑器，已确认进入主链，必须严格遵守）\n"
                            f"- 集号：第 {_eo_no(_cur)} 集 | 标题：{_ed_text(_cur.get('title'))}\n"
                            f"- 主线事件：{_ed_text(_cur.get('summary'))}\n"
                            f"- 主冲突：{_ed_text(_cur.get('conflict'))}\n"
                            f"- 主场景：{_ed_text(_cur.get('main_scene'))}\n"
                            f"- 关系变化：{_ed_text(_cur.get('relationship_change'))}\n"
                            f"- 信息揭露：{_ed_text(_cur.get('info_revealed'))}\n"
                            f"- 爽点类型：{_ed_text(_cur.get('satisfaction_type'))}\n"
                            f"- 本集阶段：{_ed_text(_cur.get('stage'))}\n"
                            f"- 可拍动作：{_ed_text(_cur.get('visible_action'))}\n"
                            f"- 证据/动作物：{_ed_text(_cur.get('evidence_object'))}\n"
                            f"- 权力/代价变化：{_ed_text(_cur.get('power_or_cost_delta'))}\n"
                            f"- 转折/爆点：{_ed_text(_cur.get('turning'))}\n"
                            f"- 集末倒钩：{_ed_text(_cur.get('hook'))}\n"
                            f"- 信息释放边界：{_ed_text(_cur.get('hook_boundary'))}"
                        )
                _block_lines = ["## 全季集纲（来自大纲编辑器，已确认进入主链）"]
                for e in sorted(_eps, key=_eo_no):
                    _en = _eo_no(e)
                    if _cur_ep == 0 or abs(_en - _cur_ep) <= 3:
                        _prefix = "👉【当前集】" if _en == _cur_ep and _cur_ep > 0 else "  "
                        _block_lines.append(
                            f"{_prefix} 第{_en}集 {_ed_text(e.get('title'))}: {_ed_text(e.get('summary'))[:80]}"
                            f" | 场景:{_ed_text(e.get('main_scene'))[:24]}"
                            f" | 关系:{_ed_text(e.get('relationship_change'))[:36]}"
                            f" | 信息:{_ed_text(e.get('info_revealed'))[:36]}"
                            f" | 爽点:{_ed_text(e.get('satisfaction_type'))[:24]}"
                            f" | 可拍动作:{_ed_text(e.get('visible_action'))[:36]}"
                            f" | 证据/动作物:{_ed_text(e.get('evidence_object'))[:28]}"
                            f" | 权力/代价变化:{_ed_text(e.get('power_or_cost_delta'))[:36]}"
                            f" | 倒钩:{_ed_text(e.get('hook'))[:50]}"
                            f" | 信息释放边界:{_ed_text(e.get('hook_boundary'))[:50]}"
                        )
                base["episode_outlines_block"] = "\n".join(_block_lines)
    except Exception:
        pass

    steps = metadata.get("steps") or {}
    if isinstance(steps, dict):
        base.setdefault("concept", extract_step_text(steps.get("concept")))
        base.setdefault("characters", extract_step_text(steps.get("characters")))
        # 修复30: 注入 episode_outlines（全集骨架 + 本集切片）
        eo_step = steps.get("episode_outlines") or {}
        if isinstance(eo_step, dict):
            outlines_list = eo_step.get("episode_outlines") or []
            try:
                ep_int_for_outline = int(draft_episode) if draft_episode else 0
            except Exception:
                ep_int_for_outline = 0
            cur_outline = ""
            if ep_int_for_outline > 0:
                for o in outlines_list:
                    if isinstance(o, dict) and str(o.get("episode")) == str(ep_int_for_outline):
                        cur_outline = (
                            f"## 本集集纲（来自 episode_outlines 步骤，必须严格遵守）\n"
                            f"- 集号：第 {o.get('episode')} 集 | 标题：{o.get('title','')}\n"
                            f"- 主线事件：{o.get('main_event','')}\n"
                            f"- 主冲突：{o.get('main_conflict','')}\n"
                            f"- 关系变化：{o.get('relationship_change','')}\n"
                            f"- 信息揭露：{o.get('info_revealed','')}\n"
                            f"- 集末倒钩：{o.get('cliffhanger','')}\n"
                            f"- 承接前集：{', '.join(o.get('callbacks', []) or []) or '无'}\n"
                            f"- 本集埋伏笔：{', '.join(o.get('seeds', []) or []) or '无'}\n"
                            f"- 主角小目标：{o.get('subgoal_for_protagonist','')}\n"
                            f"- 反派小目标：{o.get('subgoal_for_antagonist','')}"
                        )
                        break
            base.setdefault("current_episode_outline", cur_outline)
            block_lines = ["## 剧情滑动窗口（RAG动态检索：前后剧情文脉）"]
            for o in outlines_list:
                if isinstance(o, dict):
                    ep_num_str = str(o.get('episode', '0')).strip()
                    try:
                        ep_num = int(ep_num_str) if ep_num_str else 0
                    except Exception:
                        ep_num = 0
                    if ep_int_for_outline == 0 or abs(ep_num - ep_int_for_outline) <= 3:
                        prefix = "👉【当前集】" if ep_num == ep_int_for_outline and ep_int_for_outline > 0 else "  "
                        block_lines.append(
                            f"{prefix} 第{o.get('episode','?')}集 {o.get('title','')}: {o.get('main_event','')[:80]} | 倒钩:{o.get('cliffhanger','')[:50]}"
                        )
            base.setdefault("episode_outlines_block", "\n".join(block_lines) if outlines_list else "")
        else:
            base.setdefault("current_episode_outline", "")
            base.setdefault("episode_outlines_block", "")
        # beat_sheet 全文（项目级，所有集共用）
        beat_sheet_full = extract_step_text(steps.get("beat_sheet"))
        try:
            ep_int = int(draft_episode)
        except Exception:
            ep_int = 0
        sliced_beat = slice_beat_sheet_by_episode(beat_sheet_full, ep_int) if ep_int > 0 else ""
        if sliced_beat:
            base.setdefault("beat_sheet", sliced_beat)
            base.setdefault("episode_beat", sliced_beat)
        else:
            base.setdefault("beat_sheet", beat_sheet_full)
            base.setdefault("episode_beat", "")
        sl_payload = get_step_payload(metadata, "scene_list", ep_int)
        base.setdefault("scene_list", extract_step_text(sl_payload) if sl_payload else "")
        sd_payload = get_step_payload(metadata, "script_draft", ep_int)
        base.setdefault("script_draft", extract_step_text(sd_payload) if sd_payload else "")
        base.setdefault("novel_analysis", extract_step_text(steps.get("novel_analysis")))
        base.setdefault("locked_characters", extract_step_text(steps.get("character_lock")))
        base.setdefault("market_check", extract_step_text(steps.get("market_check")))
        if ep_int > 0:
            anchor_text = slice_novel_anchor_by_episode(extract_step_text(steps.get("novel_analysis")), ep_int)
            if anchor_text:
                base.setdefault("episode_novel_anchor", anchor_text)
        base.setdefault("episode_novel_anchor", str(metadata.get("inputs", {}).get("episode_novel_anchor") or ""))
        concept_step = steps.get("concept") or {}
        if isinstance(concept_step, dict):
            try:
                concept_payload = concept_step
                cs = concept_payload.get("commercial_score")
                if cs is not None:
                    base.setdefault("commercial_score", str(cs))
                pa = concept_payload.get("primary_archetype")
                if pa:
                    base.setdefault("primary_archetype", str(pa))
                sa = concept_payload.get("secondary_archetype")
                if sa:
                    base.setdefault("secondary_archetype", str(sa))
            except Exception:
                pass
        base.setdefault("commercial_score", "")
        base.setdefault("primary_archetype", "")
        base.setdefault("secondary_archetype", "")
        base.setdefault("scene_header_style", str(project.get("scene_header_style") or "bracket"))

    result: dict[str, str] = {}
    for key in known_template_keys:
        value = base.get(key, "")
        result[key] = str(value) if value is not None else ""
    return result
