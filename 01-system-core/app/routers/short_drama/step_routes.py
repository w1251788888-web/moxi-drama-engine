"""测试页 “run-step / save-step / run-step-stream” 三个重型路由（从 short_drama_writing.py 抽出）。

3 个 endpoint：

- POST /sessions/{task_id}/run-step          —— 同步生成单个写作步骤（含 quality_check 二次重生 + acceptance_checks 验收）
- POST /sessions/{task_id}/save-step         —— 手工保存（不走 LLM）
- GET  /sessions/{task_id}/run-step-stream   —— SSE 流式生成单个写作步骤

主 router 用 include_router 聚合，URL 不变。

注意：本文件保留 _X 前缀别名，跟主 router 旧名一致，方便回归对照；
真正的实现都来自 services 层。
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import re
import threading
import unicodedata
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy.orm import Session

from app.auth.dependencies import verify_admin
from app.config import config
from app.database import get_db
from app.models.material_item import MaterialItem
from app.models.project_v2 import ProjectV2
from app.models.task import Task
from app.services import task_service
from app.services.acceptance_criteria_service import run_acceptance_checks
from app.services.issue_feedback_service import build_issue_feedback_snapshot
from app.services.material_library_service import material_to_dict, select_project_materials
from app.services.short_drama_advanced_generation import (
    resolve_step_generation_route as _resolve_step_generation_route,
)
from app.services.short_drama_deep_audit import (
    generation_kwargs_from_metadata as _generation_kwargs_from_metadata,
)
from app.services.short_drama_quality_helpers import (
    build_acceptance_gate_warning as _build_acceptance_gate_warning,
    build_step_result_extras as _build_step_result_extras,
    coerce_generation_text as _coerce_generation_text,
    derive_quality_step_guidance as _derive_quality_step_guidance,
    extract_step_text as _extract_step_text,
    normalize_quality_dimension as _normalize_quality_dimension,
    project_config_value as _project_config_value,
)
from app.services.short_drama_session_metadata import (
    build_startup_checklist as _build_startup_checklist,
    get_session_task as _get_session_task,
    now_iso as _now_iso,
    save_metadata as _save_metadata,
)
from app.services.short_drama_session_hydrate import (
    hydrate_session_project_runtime_context as _hydrate_session_project_runtime_context,
)
from app.services.short_drama_sse import (
    sse_event as _sse_event,
    stream_sync_text_generation as _stream_sync_text_generation,
)
from app.services.short_drama_step_config import (
    KNOWN_TEMPLATE_KEYS,
    resolve_step_temperature as _resolve_step_temperature,
)
from app.services.short_drama_step_payload import (
    is_per_episode_step as _is_per_episode_step,
    set_step_payload as _set_step_payload,
)
from app.services.short_drama_step_prompts import (
    render_step_prompt as _render_step_prompt,
    step_generation_payload as _step_generation_payload_svc,
)
from app.services.short_drama_export import normalize_script_text as _normalize_script_text
from app.services.short_drama_workflow_config import (
    KIND,
    SCRIPT_DRAFT_MODES,
    STEP_ID,
    STEP_LABELS,
    STEP_PROMPT_FILE,
    STEP_SYSTEM_PROMPT_FILE,
    workflow_step_order_for_project as _workflow_step_order_for_project,
)
from app.services.skill_workflow_service import recommend_skill_workflow
from app.services.text_generation_service import (
    TextGenerationError,
    begin_usage_collection,
    end_usage_collection,
    generate_json,
    generate_text,
)
from app.schemas.short_drama_writing import (
    RunStepRequest,
    SaveStepRequest,
    StepResult,
)


router = APIRouter()  # 由主 router 加 prefix


def _require_project_episode_count(project_obj: dict[str, Any]) -> int:
    try:
        total_eps = int(project_obj.get("confirmed_total_episodes") or project_obj.get("episode_count") or 0)
    except Exception as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "error_code": "episode_count_unconfirmed",
                "message": "请先确认总集数；用户确认多少集，系统就按多少集生成。",
            },
        ) from exc
    if total_eps < 1:
        raise HTTPException(
            status_code=409,
            detail={
                "error_code": "episode_count_unconfirmed",
                "message": "请先确认总集数；用户确认多少集，系统就按多少集生成。",
            },
        )
    return max(1, min(200, total_eps))


async def _step_generation_payload(
    step_id: STEP_ID,
    metadata: dict,
    req_vars: dict[str, Any],
    *,
    draft_episode: int,
    db: Session | None = None,
) -> tuple[dict[str, str], str, str, list[dict[str, Any]]]:
    return await _step_generation_payload_svc(
        step_id,
        metadata,
        req_vars,
        draft_episode=draft_episode,
        known_template_keys=KNOWN_TEMPLATE_KEYS,
        db=db,
    )


def _parse_generation_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if not isinstance(value, str):
        return {}
    text = value.strip()
    if not text:
        return {}
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else ""
        text = text.rsplit("```", 1)[0].strip()
    try:
        parsed = json.loads(text)
    except Exception:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _coerce_character_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item or "").strip()]
    if isinstance(value, str):
        return [item.strip() for item in re.split(r"[、,，/|]", value) if item.strip()]
    return []


def _tail_excerpt(text: str, *, max_chars: int = 120) -> str:
    lines = [line.strip() for line in str(text or "").splitlines() if line.strip()]
    if not lines:
        return ""
    return "\n".join(lines[-3:])[-max_chars:]


def _coerce_cliffhanger_concrete(source: dict[str, Any], full_output: str, context_output: str) -> dict[str, Any]:
    raw = source.get("cliffhanger_concrete")
    cliff = dict(raw) if isinstance(raw, dict) else {}
    hook_text = str(
        source.get("cliffhanger")
        or source.get("ending_hook")
        or source.get("hook")
        or source.get("集末钩子")
        or cliff.get("next_episode_must_pick_up")
        or cliff.get("freeze_prop")
        or ""
    ).strip()
    tail = hook_text or _tail_excerpt(full_output) or _tail_excerpt(context_output)
    if not tail and not cliff:
        return {}

    scene = str(
        cliff.get("freeze_scene")
        or cliff.get("scene_location")
        or source.get("scene_location")
        or source.get("场所")
        or ""
    ).strip()
    characters = _coerce_character_list(
        cliff.get("freeze_characters")
        or cliff.get("characters_present")
        or source.get("characters_present")
        or source.get("角色名清单")
        or source.get("characters")
        or []
    )
    action = str(
        cliff.get("freeze_action")
        or cliff.get("freeze_frame")
        or source.get("freeze_frame")
        or tail
    ).strip()
    pickup = str(
        cliff.get("freeze_prop")
        or cliff.get("next_episode_must_pick_up")
        or source.get("next_episode_must_pick_up")
        or hook_text
        or tail
    ).strip()

    return {
        **cliff,
        "freeze_scene": scene,
        "freeze_characters": characters,
        "freeze_prop": pickup,
        "freeze_action": action,
        # 兼容 short_drama_template_vars 的旧字段名。
        "scene_location": scene,
        "characters_present": characters,
        "freeze_frame": action,
        "next_episode_must_pick_up": pickup,
    }


def _apply_script_draft_runtime_memory(
    metadata: dict,
    *,
    episode_no: int | None,
    payload: dict[str, Any],
    context_output: str,
    full_output: str,
    updated_at: str,
) -> None:
    """Let script_draft itself feed continuity, without waiting for quality_check."""
    try:
        ep_no = int(episode_no or 0)
    except Exception:
        ep_no = 0
    if ep_no <= 0:
        return

    context_payload = _parse_generation_object(context_output)
    source: dict[str, Any] = {}
    source.update(payload if isinstance(payload, dict) else {})
    source.update(context_payload)

    episodes = metadata.setdefault("episodes", {})
    if not isinstance(episodes, dict):
        episodes = {}
        metadata["episodes"] = episodes
    ep_node = episodes.setdefault(str(ep_no), {})
    if not isinstance(ep_node, dict):
        ep_node = {}
        episodes[str(ep_no)] = ep_node

    delta = source.get("state_card_delta") or source.get("状态变化") or {}
    if isinstance(delta, dict) and delta:
        ep_node["state_card_delta"] = delta
        ep_node["state_card_delta_at"] = updated_at

    used = source.get("used_beats") or source.get("已用爆点") or []
    if isinstance(used, list) and used:
        ep_node["used_beats"] = used
        ep_node["used_beats_at"] = updated_at

    cliff = _coerce_cliffhanger_concrete(source, full_output, context_output)
    if cliff:
        ep_node["cliffhanger_concrete"] = cliff
        ep_node["cliffhanger_concrete_at"] = updated_at


@router.post("/sessions/{task_id}/run-step", response_model=StepResult, summary="生成写作步骤")
async def run_step(task_id: str, req: RunStepRequest, _: bool = Depends(verify_admin), db: Session = Depends(get_db)):
    task, metadata = _get_session_task(db, task_id)
    metadata = _hydrate_session_project_runtime_context(db, metadata)
    generation_kwargs = _generation_kwargs_from_metadata(metadata)

    metadata.setdefault("steps", {})
    if not isinstance(metadata["steps"], dict):
        metadata["steps"] = {}

    variables, system_prompt, user_prompt, rag_evidence = await _step_generation_payload(
        req.step_id,
        metadata,
        req.template_vars,
        draft_episode=req.draft_episode,
        db=db,
    )

    try:
        # 修复12：按步骤性质选温度（结构化 0.0 / 创作 0.7 / 节拍 0.4），传入的 req.temperature 优先
        effective_temp = _resolve_step_temperature(req.step_id, req.temperature)
        advanced_route = _resolve_step_generation_route(
            req.step_id,
            metadata,
            generation_kwargs,
            effective_temp,
        )
        generation_kwargs = advanced_route.generation_kwargs
        if req.temperature is None:
            effective_temp = advanced_route.temperature
        # ── 修复30/35/36/37: episode_outlines 分批生成（5 集/批，6 批稳定档） ──
        if req.step_id == "episode_outlines":
            project_obj = metadata.get("project") or {}
            total_eps = _require_project_episode_count(project_obj)
            # 修复37: 5 集/批，单批输出约 2500-3000 token，距 Kimi 上限留足余量；同时与 beat_sheet 批节奏对齐
            batch_size = 5
            all_outlines: list[dict] = []
            full_outputs: list[str] = []
            ctx_outputs: list[str] = []
            prev_summary = ""

            def _extract_outlines_from_payload(bp_obj: dict) -> list[dict]:
                """修复36: 从 LLM payload 抽 outlines，兼容三种格式：
                1. 标准嵌套：{episode_outlines: [{...},...]}
                2. 单集顶层（max_tokens 不够时 LLM 简化）：{episode, title, main_event, ...}
                3. full_output 里嵌套数组：从 markdown 文本里 regex 抓 [...]
                """
                if not isinstance(bp_obj, dict):
                    return []
                # 格式 1
                outs = bp_obj.get("episode_outlines")
                if isinstance(outs, list) and outs:
                    return [o for o in outs if isinstance(o, dict)]
                # 格式 2：顶层就是单集对象
                if "episode" in bp_obj and "main_event" in bp_obj:
                    return [bp_obj]
                # 格式 3：从 full_output 文本里 regex 找 JSON 数组
                fo_text = ""
                try:
                    fo_text = bp_obj.get("full_output", "") or ""
                    if not isinstance(fo_text, str):
                        fo_text = str(fo_text)
                except Exception:
                    fo_text = ""
                if fo_text:
                    import re as _r3, json as _j3
                    matches = _r3.findall(r'\[\s*\{[^\[\]]*?"episode"\s*:.*?\}\s*\]', fo_text, flags=_r3.DOTALL)
                    for m in matches:
                        try:
                            parsed = _j3.loads(m)
                            if isinstance(parsed, list) and parsed:
                                return [o for o in parsed if isinstance(o, dict)]
                        except Exception:
                            continue
                return []

            def _committed_episode_outlines() -> list[dict]:
                """统一单一事实源：大纲编辑器已"确认进主链"时，直接把其集纲映射成本步骤标准结构，
                不再调用 02b 重新生成（与剧本生成读到的集纲完全一致）。"""
                try:
                    ostate = (metadata.get("workflow_context") or {}).get("outline_state") or {}
                    if not (isinstance(ostate, dict) and ostate.get("main_chain_committed")):
                        return []
                    od = ostate.get("outline_data") or {}
                    eps_src = od.get("episodes") if isinstance(od.get("episodes"), list) else []
                    mapped: list[dict] = []
                    for e in eps_src:
                        if not isinstance(e, dict):
                            continue
                        try:
                            ep_n = int(e.get("ep") or e.get("episodeNumber") or e.get("episode") or 0)
                        except Exception:
                            ep_n = 0
                        if ep_n <= 0 or ep_n > total_eps:
                            continue
                        mapped.append({
                            "episode": ep_n,
                            "title": str(e.get("title") or "").strip(),
                            "main_event": str(e.get("summary") or "").strip(),
                            "main_conflict": str(e.get("conflict") or "").strip(),
                            "relationship_change": str(e.get("relationship_change") or "").strip(),
                            "info_revealed": str(e.get("info_revealed") or "").strip(),
                            "cliffhanger": str(e.get("hook") or "").strip(),
                            "main_scene": str(e.get("main_scene") or "").strip(),
                            "satisfaction_type": str(e.get("satisfaction_type") or "").strip(),
                            "stage": str(e.get("stage") or "").strip(),
                            "visible_action": str(e.get("visible_action") or "").strip(),
                            "evidence_object": str(e.get("evidence_object") or "").strip(),
                            "power_or_cost_delta": str(e.get("power_or_cost_delta") or "").strip(),
                            "hook_boundary": str(e.get("hook_boundary") or "").strip(),
                        })
                    return mapped
                except Exception:
                    return []

            committed_outlines = _committed_episode_outlines()
            if committed_outlines:
                all_outlines = list(committed_outlines)
                full_outputs.append("（直接采用大纲编辑器已确认进主链的集纲，未调用模型重新生成）")
                ctx_outputs.append(f"采用编辑器已确认集纲，共 {len(committed_outlines)} 集")
            # 有已确认集纲时 batch_iter 为空 → 跳过 02b 重新生成；否则照常分批生成
            batch_iter = [] if committed_outlines else range(1, total_eps + 1, batch_size)
            for batch_start in batch_iter:
                batch_end = min(batch_start + batch_size - 1, total_eps)
                batch_vars = dict(variables)
                batch_vars["batch_start"] = str(batch_start)
                batch_vars["batch_end"] = str(batch_end)
                batch_vars["prev_batches_summary"] = prev_summary or "（首批，无前置摘要）"
                batch_user_prompt = _render_step_prompt("episode_outlines", batch_vars)
                try:
                    # 修复35/37: 5 集/批，单批输出 ≈ 2500-3000 字 ≈ 5000-6000 tokens；max_tokens=8000 留 30% 余量
                    bp = generate_json(
                        system_prompt, batch_user_prompt,
                        temperature=effective_temp,
                        max_tokens=8000,
                        **generation_kwargs,
                    )
                except TextGenerationError as exc:
                    raise HTTPException(status_code=400, detail=f"episode_outlines 第 {batch_start}-{batch_end} 集生成失败：{exc}")
                outs = _extract_outlines_from_payload(bp)
                for o in outs:
                    if isinstance(o, dict) and o.get("episode") is not None:
                        all_outlines.append(o)
                bf = _coerce_generation_text(bp.get("full_output")) or ""
                bc = _coerce_generation_text(bp.get("context_output")) or ""
                full_outputs.append(f"\n<!-- batch {batch_start}-{batch_end} -->\n" + bf)
                ctx_outputs.append(bc)
                # 摘要供下批（用 outs 而非 bp.get，因为 bp 可能没有数组）
                summary_lines = []
                for o in outs[-batch_size:]:
                    if isinstance(o, dict):
                        summary_lines.append(f"第{o.get('episode','?')}集: {o.get('title','')} - {str(o.get('main_event',''))[:60]}")
                prev_summary = (prev_summary + "\n" + "\n".join(summary_lines))[-2500:]

            # ── 修复31: 完整性硬校验 + 兜底解析 + 缺集补轮 + 硬阻断 ─────────
            def _normalize_outlines(items: list) -> list[dict]:
                """对 episode_outlines 做容错归一：兼容 episode 是字符串、对象嵌套等。"""
                out: list[dict] = []
                if not isinstance(items, list):
                    return out
                for o in items:
                    if not isinstance(o, dict):
                        continue
                    ep_v = o.get("episode") or o.get("episode_no") or o.get("ep")
                    try:
                        ep_n = int(str(ep_v).strip()) if ep_v is not None else 0
                    except Exception:
                        ep_n = 0
                    if ep_n <= 0 or ep_n > total_eps:
                        continue
                    o2 = dict(o)
                    o2["episode"] = ep_n
                    out.append(o2)
                # 去重保留首次出现
                seen: set[int] = set()
                dedup: list[dict] = []
                for o in out:
                    if o["episode"] in seen:
                        continue
                    seen.add(o["episode"])
                    dedup.append(o)
                return dedup

            all_outlines = _normalize_outlines(all_outlines)
            # 兜底：若 LLM 把数组放到 full_output 文本里，从最后一批 raw 里再尝试 JSON 解析
            if not all_outlines:
                import re as _re_o, json as _json_o
                joined = "\n".join(full_outputs)
                # 找最大的 [...] 数组
                m = _re_o.search(r'\[\s*\{.*?\}\s*\]', joined, flags=_re_o.DOTALL)
                if m:
                    try:
                        parsed = _json_o.loads(m.group(0))
                        all_outlines = _normalize_outlines(parsed)
                    except Exception:
                        pass

            present_eps = sorted({o["episode"] for o in all_outlines})
            missing = [n for n in range(1, total_eps + 1) if n not in present_eps]

            # 最多补 2 轮（每轮按缺集分小批补）
            for retry_round in range(2):
                if not missing:
                    break
                # 把缺集按连续段切成小批
                groups: list[tuple[int, int]] = []
                run_start = missing[0]
                prev = missing[0]
                for n in missing[1:]:
                    if n == prev + 1:
                        prev = n
                    else:
                        groups.append((run_start, prev))
                        run_start = n
                        prev = n
                groups.append((run_start, prev))
                for miss_start, miss_end in groups:
                    rb_vars = dict(variables)
                    rb_vars["batch_start"] = str(miss_start)
                    rb_vars["batch_end"] = str(miss_end)
                    rb_vars["prev_batches_summary"] = (prev_summary + f"\n\n【强制补齐】缺失集号: {list(range(miss_start, miss_end+1))}，必须只输出这几集")[-3000:]
                    rb_user_prompt = _render_step_prompt("episode_outlines", rb_vars)
                    try:
                        rbp = generate_json(system_prompt, rb_user_prompt, temperature=0.0, max_tokens=8000, **generation_kwargs)
                        new_outs = _normalize_outlines(_extract_outlines_from_payload(rbp))
                        for o in new_outs:
                            if o["episode"] in missing:
                                all_outlines.append(o)
                    except Exception:
                        continue
                # 再去重 + 重新计算缺集
                seen2: set[int] = set()
                dedup2: list[dict] = []
                for o in all_outlines:
                    if o["episode"] in seen2:
                        continue
                    seen2.add(o["episode"])
                    dedup2.append(o)
                all_outlines = dedup2
                present_eps = sorted({o["episode"] for o in all_outlines})
                missing = [n for n in range(1, total_eps + 1) if n not in present_eps]

            sorted_outlines = sorted(all_outlines, key=lambda o: o["episode"])

            # ── 修复67: 同批/全集 main_event + title 防重校验 ──────────────
            duplicate_warnings: list[str] = []
            seen_titles: dict[str, int] = {}
            seen_events: list[tuple[int, str]] = []

            def _ngram_similarity(a: str, b: str) -> float:
                if not a or not b:
                    return 0.0
                ca = set(a[i:i+2] for i in range(len(a) - 1))
                cb = set(b[i:i+2] for i in range(len(b) - 1))
                if not ca or not cb:
                    return 0.0
                return len(ca & cb) / max(len(ca), len(cb))

            for o in sorted_outlines:
                ep_n = o.get("episode")
                title = str(o.get("title") or "").strip()
                event = str(o.get("main_event") or "").strip()
                if title and title in seen_titles:
                    duplicate_warnings.append(f"title 重复: 第{seen_titles[title]}集与第{ep_n}集同名'{title}'")
                seen_titles[title] = ep_n
                # main_event 双字 ngram 相似度 ≥ 0.7 视为重复
                for prev_ep, prev_event in seen_events:
                    sim = _ngram_similarity(event, prev_event)
                    if sim >= 0.7:
                        duplicate_warnings.append(
                            f"main_event 高度相似（{sim:.0%}）: 第{prev_ep}集'{prev_event[:40]}' vs 第{ep_n}集'{event[:40]}'"
                        )
                seen_events.append((ep_n, event))

            payload = {
                "full_output": "\n".join(full_outputs),
                "context_output": "\n\n".join(ctx_outputs)[:2500],
                "episode_outlines": sorted_outlines,
                "_outline_completeness": {
                    "expected": total_eps,
                    "actual": len(present_eps),
                    "missing": missing,
                },
                "_duplicate_warnings": duplicate_warnings,
            }
            if duplicate_warnings:
                payload["_outline_duplicate_warning"] = (
                    f"集纲多样性问题：{len(duplicate_warnings)} 处重复 — " + "; ".join(duplicate_warnings[:5])
                )
                # 注：此 warning 后续在 step_payload 处理段会被读取并写入 gate_warning

            # 硬阻断：缺集 ≥ 1 直接 422，不再 warn 让流程继续
            if missing:
                # 先保存当前部分输出，供 UI 排查
                updated_at = _now_iso()
                _set_step_payload(metadata, "episode_outlines", 0, {
                    "template_vars": variables,
                    "context_output": payload["context_output"],
                    "full_output": payload["full_output"],
                    "episode_outlines": sorted_outlines,
                    "_outline_completeness": payload["_outline_completeness"],
                    "manual_override": False,
                    "updated_at": updated_at,
                })
                metadata["updated_at"] = updated_at
                _save_metadata(db, task, metadata)
                raise HTTPException(
                    status_code=422,
                    detail=(
                        f"episode_outlines 集纲完整性不足：要求 {total_eps} 集，"
                        f"经 2 轮补轮后仍缺 {len(missing)} 集 "
                        f"{missing[:15]}{'...' if len(missing) > 15 else ''}。"
                        f"请检查 LLM 输出格式或重跑本步骤。"
                    ),
                )

        elif req.step_id == "beat_sheet":
            project_obj = metadata.get("project") or {}
            total_eps = _require_project_episode_count(project_obj)
            batch_size = 5
            full_outputs: list[str] = []
            ctx_outputs: list[str] = []
            prev_summary = ""
            for batch_start in range(1, total_eps + 1, batch_size):
                batch_end = min(batch_start + batch_size - 1, total_eps)
                batch_vars = dict(variables)
                batch_vars["batch_start"] = str(batch_start)
                batch_vars["batch_end"] = str(batch_end)
                batch_vars["prev_batches_summary"] = prev_summary or "（首批，无前置摘要）"
                # 渲染 prompt
                batch_user_prompt = _render_step_prompt("beat_sheet", batch_vars)
                try:
                    # 修复35: beat_sheet 单批 5 集 × 6-10 节拍 × 100 字 ≈ 5000-10000 tokens
                    batch_payload = generate_json(
                        system_prompt,
                        batch_user_prompt,
                        temperature=effective_temp,
                        max_tokens=10000,
                        **generation_kwargs,
                    )
                except TextGenerationError as exc:
                    raise HTTPException(status_code=400, detail=f"beat_sheet 第 {batch_start}-{batch_end} 集生成失败：{exc}")
                bf = _coerce_generation_text(batch_payload.get("full_output")) or ""
                bc = _coerce_generation_text(batch_payload.get("context_output")) or ""
                full_outputs.append(f"\n<!-- batch {batch_start}-{batch_end} -->\n" + bf)
                ctx_outputs.append(bc)
                # 提炼简短摘要供下批使用
                import re as _re_b
                ep_blocks = _re_b.findall(r"###\s*第\s*(\d+)\s*集[^#]*?(?=###|\Z)", bf, flags=_re_b.DOTALL)
                prev_summary = (prev_summary + "\n" + bc[:600])[-1500:]  # 累积摘要，限 1500 字
            # 合并最终 payload
            payload = {
                "full_output": "\n".join(full_outputs),
                "context_output": "\n\n".join(ctx_outputs)[:2000],
            }
            # 完整性硬校验
            import re as _re_c
            ep_count_in_output = len(set(_re_c.findall(r"###\s*第\s*(\d+)\s*集", payload["full_output"])))
            if ep_count_in_output < total_eps:
                # 不阻断但写大警告
                payload["_beat_completeness_warning"] = (
                    f"beat_sheet 完整性不足：要求 {total_eps} 集，实际仅检测到 {ep_count_in_output} 集"
                )
        else:
            # 修复47: 给足 max_tokens 让 LLM 真能写满字数硬约束
            # script_draft 漫剧 90 秒目标约 1200 纯字符，加 context_output 等总 ≈ 4000+ token
            # 其它结构化步骤一般 ≤ 2000 token，统一设 6000 给足余量但不浪费
            step_max_tokens = 6000 if req.step_id == "script_draft" else 4000
            payload = generate_json(system_prompt, user_prompt, temperature=effective_temp, max_tokens=step_max_tokens, **generation_kwargs)
    except TextGenerationError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    # ── 修复 13：长度/格式不达标自动重生成（最多 1 次） ─────────────────
    # 仅对 script_draft 生效；用强约束 prompt 重写一次，不达标则保留原稿，把警告写到 gate_warning
    def _check_script_draft_quality(_payload: dict) -> tuple[int, int, int, list[str]]:
        """返回 (净字数, 下限, 上限, 格式问题列表)。"""
        text = _coerce_generation_text(_payload.get("full_output")) or ""
        try:
            net = len("".join(ch for ch in text if not ch.isspace() and ch not in "，。！？、；：""''「」『』（）【】《》()[]{},.!?;:'\""))
        except Exception:
            net = len(text)
        proj = metadata.get("project") or {}
        ptype = str(proj.get("project_type") or "")
        if "漫剧" in ptype:
            mn, mx = 1150, 1250
        else:
            try:
                em = float(proj.get("episode_minutes") or 1.5)
            except Exception:
                em = 1.5
            target = em * 150
            mn, mx = int(target * 0.85), int(target * 1.15)
        # 简易格式扫描
        import re as _re_l
        lines_l = [ln.strip() for ln in text.split("\n") if ln.strip()]
        sh_re = _re_l.compile(r"^(?:【\s*场\s*\d+|\d+[-－]\d+\s+[日夜][\s]+[内外])")
        dlg_re = _re_l.compile(r"^[^△▲\s][^：:]{0,12}[（(].*?[)）][：:]|^[^△▲\s][^：:]{0,12}[：:]")
        act_re = _re_l.compile(r"^[△▲]")
        sh_n = sum(1 for ln in lines_l if sh_re.search(ln))
        dlg_n = sum(1 for ln in lines_l if dlg_re.search(ln))
        act_n = sum(1 for ln in lines_l if act_re.search(ln))
        total = len(lines_l) or 1
        problems_l: list[str] = []
        if sh_n < 1:
            problems_l.append("缺少场次标头")
        if dlg_n < 3:
            problems_l.append(f"标准台词不足（{dlg_n}<3）")
        if act_n / total > 0.5:
            problems_l.append(f"旁白△占比过高（{act_n/total:.0%}）")
        return net, mn, mx, problems_l

    if req.step_id == "script_draft":
        # ── 修复23/38：JSON 漂移防护（重写版，多维度检测） ──────────────────
        # 漂移特征（满足任一条即触发重生成）：
        # 1. full_output 整体能 json.loads 成 dict（即整个文件就是 JSON 包装，不管里面有没有 △）
        # 2. 前 100 字以 `{` 或 `[` 开头 + 含成对 ":" 引号键
        # 3. 元数据字段 ≥3 但 △ 仅在 JSON value 里（即剧本元素被嵌套在 JSON 内）
        sd_text = _coerce_generation_text(payload.get("full_output")) or ""
        sd_stripped = sd_text.strip()
        import re as _re_jd, json as _json_jd

        is_drift = False
        drift_reason = ""
        # 检测 1：整体是 JSON 对象/数组
        if sd_stripped.startswith(("{", "[")):
            try:
                parsed = _json_jd.loads(sd_stripped)
                if isinstance(parsed, (dict, list)):
                    is_drift = True
                    drift_reason = "整段 full_output 被解析成 JSON 对象/数组（应为纯剧本文本）"
            except Exception:
                # JSON 解析失败但仍以 { 开头 + 含成对引号键 → 也判定漂移
                if _re_jd.search(r'^\s*\{\s*"[^"]+"\s*:\s*', sd_stripped[:300]):
                    is_drift = True
                    drift_reason = "前 300 字呈 JSON 对象结构（应为纯剧本文本）"

        # 检测 2（旧逻辑兜底）：JSON 外壳 + 元数据键
        if not is_drift:
            meta_field_count = len(_re_jd.findall(r'["\']?(角色名清单|集末钩子|爽感爆发点列表|本集冲突链|声纹卡校验结果|context_output)["\']?\s*[:：]', sd_text))
            # 检测"裸 △"行（行首是 △ 而不是 JSON value 里的 △）
            naked_action_lines = 0
            for ln in sd_text.split("\n")[:50]:
                if _re_jd.match(r'^\s*[△▲]', ln):
                    naked_action_lines += 1
            naked_dialog_lines = 0
            for ln in sd_text.split("\n")[:50]:
                if _re_jd.match(r'^\s*[^\s"\'：:{}\[\],][^：:{}\[\]]{1,8}[：:][^：:{}\[\]]{2,}', ln):
                    naked_dialog_lines += 1
            if meta_field_count >= 3 and (naked_action_lines + naked_dialog_lines) < 2:
                is_drift = True
                drift_reason = f"元数据键 {meta_field_count} 个，但行首裸 △/台词仅 {naked_action_lines + naked_dialog_lines} 行"

        if is_drift:
            try:
                drift_directive = (
                    "\n\n【严重错误：上一稿被检测为 JSON/元数据漂移】\n"
                    f"原因：{drift_reason}\n"
                    "上一稿用 JSON 嵌套结构包装了剧本（场次写成 JSON key、台词塞到 description 字段值里）"
                    "或纯输出了元数据列表，没有写可直接拍摄的纯文本剧本。\n"
                    "本次重写硬约束：\n"
                    "  • full_output 字段必须是【纯剧本文本】，行首使用 `【场N：日/夜 内/外 地点】` 这种场次标头\n"
                    "  • 动作行必须以 `△` 起笔，独立成行\n"
                    "  • 台词必须形如 `角色名：内容` 或 `角色名（情绪）：内容`，独立成行\n"
                    "  • OS 形如 `角色名OS：内容`\n"
                    "  • 严禁把场次写成 `\"场1\": {...}` 这种 JSON key\n"
                    "  • 严禁用 `{ ... }` 包裹整段剧本\n"
                    "  • 元数据（角色清单/集末钩子/爽感爆发点）只能放在 context_output JSON 里，不能进 full_output\n"
                    "  • full_output 第一个字符不能是 `{` 或 `[`\n"
                )
                payload_redo = generate_json(
                    system_prompt + drift_directive,
                    user_prompt + drift_directive,
                    temperature=max(0.4, (effective_temp or 0.7) - 0.1),
                    max_tokens=6000,  # 修复47: 给足 token 让重写真能写到 90 秒目标长度
                    **generation_kwargs,
                )
                redo_text = _coerce_generation_text(payload_redo.get("full_output")) or ""
                redo_stripped = redo_text.strip()
                # 接受新稿条件：不再以 { 或 [ 开头，且有 ≥1 行裸 △ 或 标准台词
                redo_first_ok = redo_stripped and not redo_stripped.startswith(("{", "["))
                redo_has_naked = any(_re_jd.match(r'^\s*[△▲]', ln) for ln in redo_text.split("\n")[:50])
                if redo_first_ok and redo_has_naked:
                    payload = payload_redo
            except TextGenerationError:
                pass
        # 重新读 full_output 用于后续检查
        net0, mn0, mx0, fmt0 = _check_script_draft_quality(payload)
        length_bad = (net0 < mn0) or (net0 > mx0)
        if length_bad or fmt0:
            issues_desc = []
            if net0 < mn0:
                gap = mn0 - net0
                issues_desc.append(
                    f"净字数 {net0} 低于下限 {mn0}（差 {gap} 字）。"
                    f"必须主动扩写：增加 2-4 个新的可拍场面/动作行/对白细节，让正文从 {net0} 字扩展到 {mn0}-{mx0}。"
                )
            elif net0 > mx0:
                issues_desc.append(f"净字数 {net0} 超过上限 {mx0}，需重写压缩：删冗余对白、合并动作描述。")
            if fmt0:
                issues_desc.extend([f"格式：{p}" for p in fmt0])
            retry_directive = (
                "\n\n【强制重写约束 — 修复51 字数最高优先级】上一稿存在以下问题，请整体重写本集剧本：\n"
                + "\n".join(f"- {x}" for x in issues_desc)
                + f"\n\n字数硬约束（最高优先级）：净字数（不含标点空白）必须落在 [{mn0}, {mx0}] 区间，原稿字数{'不足时主动扩写' if net0 < mn0 else ('超限时主动压缩' if net0 > mx0 else '维持')}。"
                + "\n格式硬约束：必须有 ≥1 个场次标头（【场N：…】或 N 日内 …）、≥3 行标准台词（角色：内容 或 角色（动作）：内容）、△ 旁白行占比 ≤ 50%。"
            )
            try:
                payload2 = generate_json(
                    system_prompt + retry_directive,
                    user_prompt + retry_directive,
                    temperature=max(0.3, (effective_temp or 0.7) - 0.2),
                    max_tokens=6000,  # 修复47
                    **generation_kwargs,
                )
                net1, mn1, mx1, fmt1 = _check_script_draft_quality(payload2)
                # 接受新稿的条件：长度区间内 且 格式问题数 <= 原稿；或长度更接近区间且格式问题不增加
                def _len_dist(n, mn, mx): return 0 if mn <= n <= mx else (mn - n if n < mn else n - mx)
                if (mn1 <= net1 <= mx1 and len(fmt1) <= len(fmt0)) or (
                    _len_dist(net1, mn1, mx1) < _len_dist(net0, mn0, mx0) and len(fmt1) <= len(fmt0)
                ):
                    payload = payload2
            except TextGenerationError:
                pass  # 重生成失败保留原稿，gate_warning 仍会被设上

    # ── 门控逻辑 ────────────────────────────────────────────────────────────
    # market_check：根据 verdict 硬阻断 / 软警告
    gate_warning: str | None = None
    if req.step_id == "market_check":
        mc_result = payload.get("market_check_result") or {}
        verdict = str(mc_result.get("verdict") or "").strip().lower()
        # 修复32: 用户尚未接入真实市场数据，市场判断先不做硬阻断也不做软警告
        if verdict == MARKET_CHECK_REJECT_VERDICT and not MARKET_CHECK_WARN_DISABLED:
            updated_at = _now_iso()
            _set_step_payload(metadata, "market_check", 0, {
                "template_vars": variables,
                "context_output": json.dumps(mc_result, ensure_ascii=False),
                "full_output": json.dumps(payload, ensure_ascii=False),
                "market_check_result": mc_result,
                "manual_override": False,
                "updated_at": updated_at,
            })
            metadata["updated_at"] = updated_at
            _save_metadata(db, task, metadata)
            suggestions = mc_result.get("optimization_suggestions") or []
            detail_msg = (
                f"市场可行性检查未通过（≤1项通过），请修改项目 brief 后重新执行本步骤。"
                f"优化建议：{'; '.join(str(s) for s in suggestions) if suggestions else '详见 market_check_result'}"
            )
            raise HTTPException(status_code=422, detail=detail_msg)
        elif verdict == MARKET_CHECK_WARN_VERDICT and not MARKET_CHECK_WARN_DISABLED:
            suggestions = mc_result.get("optimization_suggestions") or []
            gate_warning = (
                f"市场可行性警告（仅2项通过）：{mc_result.get('verdict_reason', '')} "
                f"建议：{'; '.join(str(s) for s in suggestions)}"
            )
            # ── P1-修复6: 阈值收紧 + 改进建议反哺 negative_prompt_hints ──
            # 必须命中"题材热度"或"对标验证"中至少 1 项；否则升级为硬阻断
            check_items = mc_result.get("check_items") or {}
            critical_keys = ("topic_heat", "benchmark_validation", "题材热度", "对标验证")
            critical_pass = False
            if isinstance(check_items, dict):
                for k in critical_keys:
                    val = check_items.get(k)
                    if isinstance(val, dict):
                        if val.get("passed") is True or str(val.get("status") or "").lower() in ("pass", "passed", "ok", "true"):
                            critical_pass = True
                            break
                    elif isinstance(val, bool) and val:
                        critical_pass = True
                        break
            # 兜底：如果模型没填 check_items，从 verdict_reason 文本里粗略匹配
            if not critical_pass and not check_items:
                reason_text = str(mc_result.get("verdict_reason") or "")
                if ("题材热度" in reason_text and "未通过" not in reason_text.split("题材热度", 1)[-1][:8]) or (
                    "对标验证" in reason_text and "未通过" not in reason_text.split("对标验证", 1)[-1][:8]
                ):
                    critical_pass = True
            if not critical_pass and check_items:
                # 关键项未通过 → 硬阻断
                updated_at = _now_iso()
                _set_step_payload(metadata, "market_check", 0, {
                    "template_vars": variables,
                    "context_output": json.dumps(mc_result, ensure_ascii=False),
                    "full_output": json.dumps(payload, ensure_ascii=False),
                    "market_check_result": mc_result,
                    "manual_override": False,
                    "updated_at": updated_at,
                })
                metadata["updated_at"] = updated_at
                _save_metadata(db, task, metadata)
                detail_msg = (
                    f"市场可行性核心项未通过（题材热度/对标验证至少需通过一项），请修改 brief 后重新执行。"
                    f"优化建议：{'; '.join(str(s) for s in suggestions) if suggestions else '详见 market_check_result'}"
                )
                raise HTTPException(status_code=422, detail=detail_msg)
            # 关键项通过 → 软警告通过，但把建议注入 negative_prompt_hints 供下游修正
            if suggestions:
                issue_feedback = metadata.setdefault("issue_feedback", {})
                hints = issue_feedback.setdefault("negative_prompt_hints", [])
                if isinstance(hints, list):
                    for s in suggestions:
                        text = f"市场可行性建议：{str(s).strip()}"
                        if text and text not in hints:
                            hints.append(text)

    # ── P2-修复11/34: character_lock 实化校验（兼容多种主角写法） ────────────
    def _is_protagonist_role(role: str) -> bool:
        """主角判定：兼容 主角/男主/女主/男主角/女主角/protagonist/lead/MC 等多种表达"""
        r = (role or "").lower().replace(" ", "")
        return any(kw in r for kw in [
            "主角", "男主", "女主", "主人公", "主线", "主体",
            "protagonist", "lead", "mc", "hero", "heroine",
        ])

    if req.step_id == "character_lock":
        cl_result = payload.get("character_lock_result") or {}
        locked = cl_result.get("locked_characters") or []
        cl_problems: list[str] = []
        if not isinstance(locked, list) or len(locked) < 2:
            cl_problems.append(f"角色锁定数量不足：要求≥2，实际 {len(locked) if isinstance(locked, list) else 0}")
        protagonist_count = 0
        empty_name_count = 0
        if isinstance(locked, list):
            for c in locked:
                if not isinstance(c, dict):
                    continue
                if not str(c.get("canonical_name") or "").strip():
                    empty_name_count += 1
                role = str(c.get("role_type") or "")
                if _is_protagonist_role(role):
                    protagonist_count += 1
        if empty_name_count > 0:
            cl_problems.append(f"存在 {empty_name_count} 个角色 canonical_name 为空")
        if protagonist_count == 0:
            # 列出所有 role_type 帮排查
            seen_roles = sorted({str(c.get("role_type") or "") for c in locked if isinstance(c, dict)})
            cl_problems.append(f"未识别到任何主角（已扫描 role_type: {seen_roles}，未匹配 主角/男主/女主/protagonist 等关键词）")
        # 主角必须出现在 brief 或 novel_analysis 中
        brief_text = str((metadata.get("inputs") or {}).get("brief") or "")
        novel_text = _extract_step_text((metadata.get("steps") or {}).get("novel_analysis"))
        scope_text = (brief_text + "\n" + (novel_text or "")).strip()
        if scope_text and isinstance(locked, list):
            missing_in_scope = []
            for c in locked:
                if not isinstance(c, dict):
                    continue
                if not _is_protagonist_role(str(c.get("role_type") or "")):
                    continue
                name = str(c.get("canonical_name") or "").strip()
                if name and name not in scope_text:
                    aliases = c.get("aliases_from_novel") or []
                    if not any(str(a or "").strip() and str(a) in scope_text for a in aliases):
                        missing_in_scope.append(name)
            if missing_in_scope:
                cl_problems.append(f"主角未在 brief/novel_analysis 出现：{', '.join(missing_in_scope)}")
        if cl_problems:
            updated_at = _now_iso()
            _set_step_payload(metadata, "character_lock", 0, {
                "template_vars": variables,
                "context_output": json.dumps(cl_result, ensure_ascii=False),
                "full_output": json.dumps(payload, ensure_ascii=False),
                "manual_override": False,
                "updated_at": updated_at,
                "lock_problems": cl_problems,
            })
            metadata["updated_at"] = updated_at
            _save_metadata(db, task, metadata)
            raise HTTPException(status_code=422, detail="角色锁定校验未通过：" + "；".join(cl_problems))

    # concept：commercial_score 软警告
    if req.step_id == "concept":
        try:
            cs = int(payload.get("commercial_score") or 0)
        except (ValueError, TypeError):
            cs = 0
        if cs < CONCEPT_COMMERCIAL_SCORE_WARN_THRESHOLD:
            warnings_list = payload.get("commercial_warnings") or []
            gate_warning = (
                f"商业性预判偏低（{cs}/10），建议在进入角色/节拍表前优化概念。"
                + (f" 风险点：{'; '.join(str(w) for w in warnings_list)}" if warnings_list else "")
            )

    # ── 提取 context/full_output ────────────────────────────────────────────
    context_output = _coerce_generation_text(payload.get("context_output"))
    full_output = _coerce_generation_text(payload.get("full_output"))

    # ── 修复50: script_draft 入库前最后兜底——把 LLM 漂移的 JSON 嵌套强制清洗成纯剧本 ──
    # 即使 LLM 把元数据放到 full_output（修复 49 的 prompt 没挡住），这里也能把 JSON 解析回剧本文本
    if req.step_id == "script_draft" and full_output:
        fo_strip = full_output.strip()
        if fo_strip.startswith(("{", "[")):
            try:
                cleaned = _normalize_script_text(fo_strip)
                if cleaned and not cleaned.strip().startswith(("{", "[")):
                    full_output = cleaned
                    # 同步更新 payload 让后续 acceptance_checks 用清洗后的文本算字数
                    payload["full_output"] = cleaned
            except Exception:
                pass

    # 纯结构化步骤不要求 context_output/full_output，直接保存 JSON 序列化结果
    STRUCTURED_ONLY_STEPS = {"project_init_check", "market_check", "quality_check", "narrative_consistency", "compliance_check"}
    if req.step_id not in STRUCTURED_ONLY_STEPS:
        if not context_output or not full_output:
            if isinstance(payload, dict) and payload:
                fallback_text = json.dumps(payload, ensure_ascii=False, indent=2)
                context_output = context_output or fallback_text
                full_output = full_output or fallback_text
            else:
                raise HTTPException(status_code=400, detail="生成结果缺少 context_output/full_output")
    else:
        # 对于纯结构化步骤，用 JSON 序列化整个 payload 作为 full_output
        if not context_output:
            context_output = json.dumps(payload, ensure_ascii=False, indent=2)
        if not full_output:
            full_output = context_output

    updated_at = _now_iso()
    step_payload: dict[str, Any] = {
        "template_vars": variables,
        "context_output": context_output,
        "full_output": full_output,
        "manual_override": False,
        "updated_at": updated_at,
        "rag_evidence": rag_evidence,
    }

    # market_check：保存原始结构化结果供下游注入
    if req.step_id == "market_check":
        step_payload["market_check_result"] = payload.get("market_check_result") or {}

    # 修复30: 保存 episode_outlines 数组到 step_payload，供下游 _build_base_template_vars 取用
    if req.step_id == "episode_outlines":
        outlines = payload.get("episode_outlines") or []
        if isinstance(outlines, list):
            step_payload["episode_outlines"] = outlines
        if "_outline_completeness" in payload:
            step_payload["_outline_completeness"] = payload["_outline_completeness"]
        if "_outline_completeness_warning" in payload:
            step_payload["_outline_completeness_warning"] = payload["_outline_completeness_warning"]
            gate_warning = (gate_warning + " | " + payload["_outline_completeness_warning"]) if gate_warning else payload["_outline_completeness_warning"]
        # 修复67: 同批 main_event/title 重复警告
        if "_outline_duplicate_warning" in payload:
            step_payload["_outline_duplicate_warning"] = payload["_outline_duplicate_warning"]
            gate_warning = (gate_warning + " | " + payload["_outline_duplicate_warning"]) if gate_warning else payload["_outline_duplicate_warning"]
        if "_duplicate_warnings" in payload:
            step_payload["_duplicate_warnings"] = payload["_duplicate_warnings"]

    # concept：保存 commercial_score 供 quality_check 参考
    if req.step_id == "concept":
        try:
            step_payload["commercial_score"] = int(payload.get("commercial_score") or 0)
        except (ValueError, TypeError):
            step_payload["commercial_score"] = 0

    # quality_check：保存完整评分报告，并追加 feedback_record 到历史
    if req.step_id == "quality_check":
        raw_report = payload.get("quality_report") or {}
        # H10 校准：对 human_aligned_scores 应用偏差后处理（基于 82 集人评配对实测）
        if isinstance(raw_report, dict) and isinstance(raw_report.get("human_aligned_scores"), dict):
            try:
                from app.services.scoring_calibration import apply_calibration
                aligned = raw_report["human_aligned_scores"]
                # inline=False：保留模型原始分（calibrated_*）方便审计
                raw_report["human_aligned_scores"] = apply_calibration(aligned, mode="mean", inline=False)
            except Exception as exc:
                # 校准失败不阻断主流程
                print(f"[apply_calibration] failed: {exc}")
        step_payload["quality_report"] = raw_report
        feedback_record = payload.get("feedback_record")
        if feedback_record:
            issue_feedback = metadata.setdefault("issue_feedback", {})
            history = issue_feedback.setdefault("feedback_history", [])
            for rec in (feedback_record if isinstance(feedback_record, list) else [feedback_record]):
                if isinstance(rec, dict):
                    rec["timestamp"] = updated_at
                    history.append(rec)
        # ── P2-修复10/20/21: 跨集 delta + cliffhanger + used_beats 滚动更新 ──
        ep_no = req.draft_episode or 0
        if ep_no > 0:
            episodes = metadata.setdefault("episodes", {})
            if not isinstance(episodes, dict):
                episodes = {}
                metadata["episodes"] = episodes
            ep_node = episodes.setdefault(str(ep_no), {})
            if isinstance(ep_node, dict):
                delta = payload.get("state_card_delta") or {}
                if isinstance(delta, dict) and delta:
                    ep_node["state_card_delta"] = delta
                    ep_node["state_card_delta_at"] = updated_at
                cliff = payload.get("cliffhanger_concrete") or {}
                if isinstance(cliff, dict) and cliff:
                    # 修复55: cliffhanger_concrete 4 字段必填（freeze_scene/characters/prop/action）
                    REQUIRED_CLIFF_FIELDS = ("freeze_scene", "freeze_characters", "freeze_prop", "freeze_action")
                    missing_cliff = [f for f in REQUIRED_CLIFF_FIELDS if not str(cliff.get(f) or "").strip()]
                    # 兼容老字段名
                    if "scene_location" in cliff and "freeze_scene" not in cliff:
                        cliff["freeze_scene"] = cliff.get("scene_location")
                    if "characters_present" in cliff and "freeze_characters" not in cliff:
                        cliff["freeze_characters"] = cliff.get("characters_present")
                    if "freeze_frame" in cliff and "freeze_action" not in cliff:
                        cliff["freeze_action"] = cliff.get("freeze_frame")
                    if "next_episode_must_pick_up" in cliff and "freeze_prop" not in cliff:
                        cliff["freeze_prop"] = cliff.get("next_episode_must_pick_up")
                    # 重新检查
                    missing_cliff = [f for f in REQUIRED_CLIFF_FIELDS if not str(cliff.get(f) or "").strip()]
                    # 检查是否含空话词
                    cliff_text = " ".join(str(v) for v in cliff.values() if v)
                    EMPTY_PHRASES = ("故事继续", "真相未明", "危机来临", "期待下集", "下集见分晓", "未完待续")
                    has_empty = any(ep in cliff_text for ep in EMPTY_PHRASES)
                    if missing_cliff or has_empty:
                        warning_msg = f"cliffhanger_concrete 不合格：缺字段 {missing_cliff}，含空话={has_empty}"
                        gate_warning = (gate_warning + " | " + warning_msg) if gate_warning else warning_msg
                        cliff["_validation_problem"] = warning_msg
                    ep_node["cliffhanger_concrete"] = cliff
                used = payload.get("used_beats") or []
                if isinstance(used, list) and used:
                    ep_node["used_beats"] = used

    if req.step_id == "script_draft":
        project = metadata.get("project") or {}
        track = str(project.get("genre_sub") or project.get("genre_main") or "短剧")
        # 修复28: 把 character_lock 锁定的角色名传给 acceptance（提升 NER 精度）
        project_chars: list[str] = []
        cl_step = (metadata.get("steps") or {}).get("character_lock") or {}
        if isinstance(cl_step, dict):
            cl_full = _coerce_generation_text(cl_step.get("full_output")) or ""
            try:
                import json as _json_cd
                cl_data = _json_cd.loads(cl_full) if cl_full.strip().startswith("{") else None
                if isinstance(cl_data, dict):
                    locked = (cl_data.get("character_lock_result") or {}).get("locked_characters") or []
                    for c in locked:
                        if isinstance(c, dict):
                            nm = str(c.get("canonical_name") or "").strip()
                            if nm:
                                project_chars.append(nm)
                            for alias in (c.get("aliases_from_novel") or []):
                                a = str(alias or "").strip()
                                if a:
                                    project_chars.append(a)
            except Exception:
                pass
        # 兼容：从 project.characters 取兜底
        if not project_chars:
            for c in (project.get("characters") or []):
                if isinstance(c, dict):
                    nm = str(c.get("name") or c.get("canonical_name") or "").strip()
                    if nm:
                        project_chars.append(nm)
        step_payload["acceptance_checks"] = run_acceptance_checks(
            {"text": full_output, "summary": context_output},
            track=track,
            previous_episodes=None,
            project_characters=project_chars or None,
        )
        gate_warning = _build_acceptance_gate_warning(step_payload["acceptance_checks"], gate_warning or "")

        # ── P1-修复4: 长度合同硬约束 ──────────────────────────────────────
        # 漫剧 90 秒：目标约 1200 纯字符；真人短剧：episode_minutes×150 ± 15%
        try:
            net_chars = len("".join(ch for ch in (full_output or "") if not ch.isspace() and ch not in "，。！？、；：""''「」『』（）【】《》()[]{},.!?;:'\""))
        except Exception:
            net_chars = len(full_output or "")
        ptype = str(project.get("project_type") or "")
        if "漫剧" in ptype:
            min_len, max_len = 1150, 1250
        else:
            try:
                em = float(project.get("episode_minutes") or 1.5)
            except Exception:
                em = 1.5
            target = em * 150
            min_len = int(target * 0.85)
            max_len = int(target * 1.15)
        step_payload["length_contract"] = {
            "net_chars": net_chars,
            "min_len": min_len,
            "max_len": max_len,
            "in_range": min_len <= net_chars <= max_len,
        }
        if net_chars < min_len:
            length_msg = f"长度合同未达标（净字数 {net_chars} < 下限 {min_len}），需重写补齐密度而非追加灌水。"
            gate_warning = (gate_warning + " | " + length_msg) if gate_warning else length_msg
        elif net_chars > max_len:
            length_msg = f"长度合同超限（净字数 {net_chars} > 上限 {max_len}），需重写压缩，禁止灌水。"
            gate_warning = (gate_warning + " | " + length_msg) if gate_warning else length_msg

        # ── P1-修复8: 格式校验器（场次标头/角色行/旁白比） ──────────────
        import re as _re
        lines = [ln.strip() for ln in (full_output or "").split("\n") if ln.strip()]
        scene_header_re = _re.compile(r"^(?:【\s*场\s*\d+|\d+[-－]\d+\s+[日夜][\s]+[内外])")
        dialogue_re = _re.compile(r"^[^△▲\s][^：:]{0,12}[（(].*?[)）][：:]|^[^△▲\s][^：:]{0,12}[：:]")
        action_re = _re.compile(r"^[△▲]")
        scene_count = sum(1 for ln in lines if scene_header_re.search(ln))
        dialogue_count = sum(1 for ln in lines if dialogue_re.search(ln))
        action_count = sum(1 for ln in lines if action_re.search(ln))
        total_lines = len(lines) or 1
        format_issues = []
        if scene_count < 1:
            format_issues.append(f"格式：缺少场次标头（要求≥1，实际 {scene_count}）")
        if dialogue_count < 3:
            format_issues.append(f"格式：标准台词/角色行不足（要求≥3，实际 {dialogue_count}）")
        if action_count / total_lines > 0.5:
            format_issues.append(f"格式：旁白△行占比过高（{action_count}/{total_lines}={action_count/total_lines:.0%}>50%），需补台词")
        step_payload["format_check"] = {
            "scene_header_count": scene_count,
            "dialogue_count": dialogue_count,
            "action_count": action_count,
            "total_lines": total_lines,
            "issues": format_issues,
        }
        if format_issues:
            fmt_msg = "；".join(format_issues)
            gate_warning = (gate_warning + " | " + fmt_msg) if gate_warning else fmt_msg
        _apply_script_draft_runtime_memory(
            metadata,
            episode_no=req.draft_episode,
            payload=payload,
            context_output=context_output or "",
            full_output=full_output or "",
            updated_at=updated_at,
        )

    step_extras = _build_step_result_extras(req.step_id, payload, gate_warning=gate_warning or "")
    step_payload.update({k: v for k, v in step_extras.items() if v})

    _set_step_payload(metadata, req.step_id, req.draft_episode, step_payload)
    metadata["updated_at"] = updated_at
    _build_startup_checklist(metadata)

    _save_metadata(db, task, metadata)

    result = StepResult(
        step_id=req.step_id,
        context_output=context_output,
        full_output=full_output,
        updated_at=updated_at,
        manual_override=False,
        gate_warning=step_extras["gate_warning"],
        quality_verdict=step_extras["quality_verdict"],
        repair_scope=step_extras["repair_scope"],
        revision_summary=step_extras["revision_summary"],
        rag_evidence=rag_evidence,
    )
    from fastapi.responses import JSONResponse
    return JSONResponse(content=result.model_dump())



@router.post("/sessions/{task_id}/save-step", response_model=StepResult, summary="手工保存写作步骤")
async def save_step(task_id: str, req: SaveStepRequest, _: bool = Depends(verify_admin), db: Session = Depends(get_db)):
    task, metadata = _get_session_task(db, task_id)

    metadata.setdefault("steps", {})
    if not isinstance(metadata["steps"], dict):
        metadata["steps"] = {}

    updated_at = _now_iso()
    step_payload = {
        "template_vars": {},
        "context_output": req.context_output or "",
        "full_output": req.full_output or "",
        "manual_override": bool(req.manual_override),
        "updated_at": updated_at,
    }

    _set_step_payload(metadata, req.step_id, req.episode_no or 0, step_payload)
    if req.step_id == "script_draft":
        _apply_script_draft_runtime_memory(
            metadata,
            episode_no=req.episode_no,
            payload=_parse_generation_object(req.context_output or ""),
            context_output=req.context_output or "",
            full_output=req.full_output or "",
            updated_at=updated_at,
        )
    metadata["updated_at"] = updated_at
    _build_startup_checklist(metadata)

    _save_metadata(db, task, metadata)

    return StepResult(
        step_id=req.step_id,
        context_output=step_payload["context_output"],
        full_output=step_payload["full_output"],
        updated_at=updated_at,
        manual_override=step_payload["manual_override"],
    )


# 以下 export 相关三件套已抽到 app.services.short_drama_export：
#   _resolve_export_episode_range / _normalize_script_text / _export_txt / _export_docx
# 这里保留同名的 _ 前缀别名，是给本文件其它地方仍按旧名调用的兼容层。
from app.services.short_drama_export import (  # noqa: E402
    export_docx as _export_docx,
    export_txt as _export_txt,
    normalize_script_text as _normalize_script_text,
    resolve_export_episode_range as _resolve_export_episode_range,
)


# 上述四个 helper 与 export_session 路由已抽到 app.routers.short_drama.export_routes


# ============================================================
# SSE 流式生成端点
# ============================================================

# _sse_event / _stream_sync_text_generation 已抽到 app.services.short_drama_sse
from app.services.short_drama_sse import (  # noqa: E402
    sse_event as _sse_event,
    stream_sync_text_generation as _stream_sync_text_generation,
)


@router.get(
    "/sessions/{task_id}/run-step-stream",
    summary="流式生成写作步骤（SSE）",
    response_class=StreamingResponse,
)
async def run_step_stream(
    task_id: str,
    step_id: str = Query(..., description="步骤 ID"),
    draft_episode: int | None = Query(None, description="第几集（draft 步骤用）"),
    temperature: float | None = Query(None, description="生成温度"),
    _: bool = Depends(verify_admin),
    db: Session = Depends(get_db),
):
    """
    流式（SSE）版本的步骤生成接口。
    返回 text/event-stream，包含三类事件：
    - event: token  — AI 实时输出的文本 token
    - event: done   — 生成完成，data 为完整的 StepResult JSON
    - event: error  — 生成失败，data.detail 为错误信息
    """
    try:
        task, metadata = _get_session_task(db, task_id)
        metadata = _hydrate_session_project_runtime_context(db, metadata)
        generation_kwargs = _generation_kwargs_from_metadata(metadata)
    except HTTPException as exc:
        async def _err():
            yield _sse_event("error", {"detail": exc.detail})
        return StreamingResponse(_err(), media_type="text/event-stream")

    async def _generate():
        cancel_event = threading.Event()
        full_text = ""

        def _save_partial_stream_text(partial_text: str, variables: dict[str, Any], rag_evidence: list[dict[str, Any]]) -> None:
            if not str(partial_text or "").strip():
                return
            updated_at = _now_iso()
            metadata.setdefault("steps", {})
            if not isinstance(metadata["steps"], dict):
                metadata["steps"] = {}
            step_payload = {
                "template_vars": variables,
                "context_output": partial_text,
                "full_output": partial_text,
                "manual_override": False,
                "updated_at": updated_at,
                "rag_evidence": rag_evidence,
                "stream_status": "partial",
                "partial": True,
            }
            _set_step_payload(metadata, str(req_step_id), draft_episode or 0, step_payload)
            metadata["updated_at"] = updated_at
            _save_metadata(db, task, metadata)

        try:
            yield _sse_event("progress", {"message": f"正在准备 {step_id} 步骤提示词..."})

            req_step_id = step_id  # type: ignore[assignment]
            variables, system_prompt, user_prompt, rag_evidence = await _step_generation_payload(
                req_step_id,
                metadata,
                {},
                draft_episode=draft_episode,
                db=db,
            )

            yield _sse_event("progress", {"message": "AI 开始生成，请稍候..."})
            effective_temp = _resolve_step_temperature(str(req_step_id), temperature)
            advanced_route = _resolve_step_generation_route(
                str(req_step_id),
                metadata,
                generation_kwargs,
                effective_temp,
            )
            route_generation_kwargs = advanced_route.generation_kwargs
            if temperature is None:
                effective_temp = advanced_route.temperature

            full_text = ""
            async for token in _stream_sync_text_generation(
                system_prompt,
                user_prompt,
                temperature=effective_temp,
                generation_kwargs=route_generation_kwargs,
                cancel_event=cancel_event,
            ):
                full_text += token
                yield _sse_event("token", {"text": token})
                await asyncio.sleep(0)  # 让出事件循环，保证 SSE 帧逐条下发

            # ── 后处理（门控逻辑）──────────────────────────────────────────
            try:
                import re as _re
                # 尝试解析 JSON
                try:
                    payload = json.loads(full_text)
                except json.JSONDecodeError:
                    cleaned = full_text.strip()
                    if cleaned.startswith("```"):
                        cleaned = cleaned.split("\n", 1)[1] if "\n" in cleaned else ""
                        cleaned = cleaned.rsplit("```", 1)[0].strip()
                    payload = json.loads(cleaned)
            except Exception:
                # 非 JSON 步骤（纯文本），包装成标准结构
                payload = {"context_output": full_text, "full_output": full_text}

            context_output = _coerce_generation_text(payload.get("context_output")) or full_text
            full_output = _coerce_generation_text(payload.get("full_output")) or full_text

            updated_at = _now_iso()
            gate_warning = ""
            metadata.setdefault("steps", {})
            if not isinstance(metadata["steps"], dict):
                metadata["steps"] = {}

            step_payload: dict[str, Any] = {
                "template_vars": variables,
                "context_output": context_output,
                "full_output": full_output,
                "manual_override": False,
                "updated_at": updated_at,
                "rag_evidence": rag_evidence,
                "stream_status": "done",
                "partial": False,
            }
            if req_step_id == "market_check":
                step_payload["market_check_result"] = payload.get("market_check_result") or {}
            if req_step_id == "concept":
                try:
                    step_payload["commercial_score"] = int(payload.get("commercial_score") or 0)
                except (ValueError, TypeError):
                    step_payload["commercial_score"] = 0
            if req_step_id == "quality_check":
                step_payload["quality_report"] = payload.get("quality_report") or {}
                feedback_record = payload.get("feedback_record")
                if feedback_record:
                    issue_feedback = metadata.setdefault("issue_feedback", {})
                    history = issue_feedback.setdefault("feedback_history", [])
                    for rec in (feedback_record if isinstance(feedback_record, list) else [feedback_record]):
                        if isinstance(rec, dict):
                            rec["timestamp"] = updated_at
                            history.append(rec)
            if req_step_id == "script_draft":
                project = metadata.get("project") or {}
                track = str(project.get("genre_sub") or project.get("genre_main") or "短剧")
                step_payload["acceptance_checks"] = run_acceptance_checks(
                    {"text": full_output, "summary": context_output},
                    track=track,
                    previous_episodes=None,
                )
                gate_warning = _build_acceptance_gate_warning(step_payload["acceptance_checks"], gate_warning or "")
                _apply_script_draft_runtime_memory(
                    metadata,
                    episode_no=draft_episode,
                    payload=payload,
                    context_output=context_output or "",
                    full_output=full_output or "",
                    updated_at=updated_at,
                )
            step_extras = _build_step_result_extras(req_step_id, payload, gate_warning=gate_warning or "")
            step_payload.update({k: v for k, v in step_extras.items() if v})
            _set_step_payload(metadata, str(req_step_id), draft_episode or 0, step_payload)
            metadata["updated_at"] = updated_at
            _save_metadata(db, task, metadata)

            yield _sse_event("done", {
                "step_id": req_step_id,
                "context_output": context_output,
                "full_output": full_output,
                "updated_at": updated_at,
                "manual_override": False,
                "gate_warning": step_extras["gate_warning"],
                "quality_verdict": step_extras["quality_verdict"],
                "repair_scope": step_extras["repair_scope"],
                "revision_summary": step_extras["revision_summary"],
                "rag_evidence": rag_evidence,
            })

        except TextGenerationError as exc:
            yield _sse_event("error", {"detail": str(exc)})
        except asyncio.CancelledError:
            cancel_event.set()
            try:
                if full_text:
                    _save_partial_stream_text(full_text, variables, rag_evidence)
            finally:
                raise
        except Exception as exc:
            yield _sse_event("error", {"detail": f"生成失败: {exc}"})

    return StreamingResponse(
        _generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",       # 禁止 nginx 缓冲
            "Connection": "keep-alive",
        },
    )
