"""分镜规划服务

职责：
1. eligibility 检查：剧本必须 confirmed + 出场角色必须 locked
2. 切镜：把已确认剧本切成 ShotSpec[]，落库
3. 多候选评分：仅对 conflict/reveal/payoff 镜头跑 N=3 候选 + LLM 评分
4. 检索 RAG 跨集上下文增强 prompt
5. 重生成单镜
"""
from __future__ import annotations

import json
import logging
import time
import uuid
from typing import Optional

from sqlalchemy.orm import Session

from app.models.storyboard import Shot
from app.models.character_visual import CharacterVisualBase, SceneVisualBase
from app.schemas.storyboard import (
    ShotSpec, ShotCamera, ShotEntityAction, ShotDelta, ShotAudioHint,
    EligibilityResponse, BeatRole,
)
from app.services import script_confirm_service, character_visual_service
from app.services.raptor_indexer import retrieve_cross_episode_context
from app.services.text_generation_service import generate_text, generation_enabled

logger = logging.getLogger(__name__)


KEY_BEAT_ROLES_FOR_MULTI_CANDIDATE = {"conflict", "reveal", "payoff"}
DEFAULT_CANDIDATE_COUNT = 3


# ─────────────────────────────────────────────────────────
# Eligibility 检查
# ─────────────────────────────────────────────────────────


def check_eligibility(
    db: Session,
    *,
    session_id: str,
    project_id: str,
    episode: int,
) -> EligibilityResponse:
    """检查本集是否满足生成分镜条件"""
    confirmed = script_confirm_service.get_confirmed_version(db, session_id, episode)
    cur = script_confirm_service.get_current_version(db, session_id, episode)

    if not cur:
        return EligibilityResponse(eligible=False, reason="no_script", detail="本集尚无剧本")
    if not confirmed:
        return EligibilityResponse(
            eligible=False, reason="not_confirmed",
            detail="本集剧本尚未确认保存，请先在剧本写作 Tab 点击「确认保存」"
        )
    if confirmed.id != cur.id:
        return EligibilityResponse(
            eligible=False, reason="stale",
            detail="本集剧本在确认后被修改，请重新确认",
            confirmed_version=confirmed.version_number or "",
        )

    # 抽取出场角色名（启发式：剧本里"角色名："对白模式）
    script_text = (confirmed.full_output or confirmed.context_output or "").strip()
    appearing_names = _extract_dialogue_speakers(script_text)
    if not appearing_names:
        # 没有解析到对白角色，跳过角色锁定校验（允许纯空镜剧本）
        return EligibilityResponse(
            eligible=True, reason="ok", confirmed_version=confirmed.version_number or "",
        )

    # 检查这些名字对应的角色是否都已锁定 visual base
    locked_rows = (
        db.query(CharacterVisualBase)
        .filter(
            CharacterVisualBase.project_id == project_id,
            CharacterVisualBase.is_locked == True,  # noqa: E712
        )
        .all()
    )
    locked_names = {(r.character_name or "").strip() for r in locked_rows}
    missing = sorted(n for n in appearing_names if n and n not in locked_names)

    if missing:
        return EligibilityResponse(
            eligible=False,
            reason="no_locked_characters",
            detail=f"以下角色尚未锁定视觉档案：{ '、'.join(missing) }",
            confirmed_version=confirmed.version_number or "",
            missing_locked_characters=missing,
        )

    return EligibilityResponse(
        eligible=True, reason="ok", confirmed_version=confirmed.version_number or "",
    )


def _extract_dialogue_speakers(script_text: str) -> set[str]:
    """从剧本里抓"角色名：xxx"模式的说话人名"""
    speakers: set[str] = set()
    for line in (script_text or "").split("\n"):
        line = line.strip()
        if not line or line.startswith(("△", "[", "（", "(")):
            continue
        if "：" in line:
            name = line.split("：", 1)[0].strip()
            # 过滤掉常见非角色标签
            if name and len(name) <= 12 and not any(c in name for c in (" ", ".", ",", "/", "\\")):
                # 排除 OS / VO 等技术标识
                if name in {"OS", "VO", "△", "音效", "字幕"}:
                    continue
                speakers.add(name.replace("（", "").replace("）", ""))
    return speakers


# ─────────────────────────────────────────────────────────
# 切镜（核心 LLM 调用）
# ─────────────────────────────────────────────────────────


_SHOT_PLAN_SYSTEM = (
    "你是 AI 短剧分镜导演。给定已确认的本集剧本和角色视觉档案，"
    "你要把这一集切成结构化分镜（每镜 2-6 秒）。"
    "输出严格 JSON 数组，每个元素遵守给定 ShotSpec schema。"
    "镜头数量遵循用户指定，且必须合计接近本集时长（按每镜 3 秒估算）。"
    "不要复述角色外貌（编译器会从 visual_base 拉取）；只在 shot_delta 写本镜独有信息。"
)


def _build_shot_plan_prompt(
    *,
    episode: int,
    script_text: str,
    target_count: int,
    locked_chars: list[CharacterVisualBase],
    scene_bases: list[SceneVisualBase],
    cross_episode_ctx: str = "",
) -> str:
    char_summary = "\n".join(
        f"- {c.character_name}（id={c.character_id}）：{(json.loads(c.visual_text or '{}').get('style_tags') or '')[:40]}"
        for c in locked_chars
    ) or "（无）"
    scene_summary = "\n".join(
        f"- {s.scene_id}：{s.environment[:40]}"
        for s in scene_bases
    ) or "（无）"

    schema_hint = (
        "{\n"
        '  "shot_id": "s001",\n'
        '  "scene_id": "scene_01_01",\n'
        '  "order": 1,\n'
        '  "duration_sec": 3.0,\n'
        '  "beat_role": "establish|setup|conflict|reaction|reveal|transition|payoff",\n'
        '  "entities": [{"character_id": "ch_001", "outfit_variant_id": null, "action": "", "expression": ""}],\n'
        '  "scene_ref": "scene_01_01",\n'
        '  "camera": {"shot_size": "MS", "angle": "eye", "movement": "static", "lens_mm": 35, "notes": ""},\n'
        '  "shot_delta": {"framing": "", "lighting_delta": "", "mood": "", "extra": ""},\n'
        '  "dialogue": "",\n'
        '  "audio": {"sfx": "", "bgm_mood": "", "voice_mood": ""},\n'
        '  "anchor_frame_ref": ""\n'
        "}"
    )

    parts = [
        f"【第 {episode} 集剧本（已确认）】",
        script_text,
        "",
        "【已锁定角色（仅引用 character_id，不要重复描述外貌）】",
        char_summary,
        "",
        "【已建场景基底】",
        scene_summary,
    ]
    if cross_episode_ctx:
        parts += ["", "【前序集上下文（参考，不要直接复述）】", cross_episode_ctx]

    parts += [
        "",
        f"【目标镜头数】约 {target_count} 个（允许 ±2）",
        "",
        "【ShotSpec Schema 单条示例】",
        schema_hint,
        "",
        "请输出 JSON 数组，**只输出数组本身**，不要任何解释、不要 markdown 围栏。",
    ]
    return "\n".join(parts)


def _parse_shot_array(raw: str) -> list[dict]:
    """从 LLM 返回里抽 JSON 数组"""
    text = (raw or "").strip()
    if "```" in text:
        for p in text.split("```"):
            if "[" in p and "]" in p:
                text = p
                break
    if "[" in text and "]" in text:
        try:
            text = text[text.index("[") : text.rindex("]") + 1]
            arr = json.loads(text)
            if isinstance(arr, list):
                return arr
        except Exception as exc:
            logger.warning("parse shot array failed: %s | raw=%s", exc, raw[:300])
    return []


def _normalize_shot_dict(d: dict, order: int) -> dict:
    """补齐缺失字段，确保能转成 ShotSpec"""
    d = dict(d or {})
    d.setdefault("shot_id", f"s{order:03d}")
    d.setdefault("order", order)
    d.setdefault("duration_sec", 3.0)
    d.setdefault("beat_role", "setup")
    d.setdefault("scene_id", d.get("scene_ref") or "")
    d.setdefault("scene_ref", d.get("scene_id") or "")
    d.setdefault("entities", [])
    d.setdefault("camera", {})
    d.setdefault("shot_delta", {})
    d.setdefault("audio", {})
    d.setdefault("dialogue", "")
    d.setdefault("anchor_frame_ref", "")
    # entities 去掉非法 character_id
    fixed_entities = []
    for e in d.get("entities") or []:
        if isinstance(e, dict) and e.get("character_id"):
            fixed_entities.append({
                "character_id": str(e.get("character_id")),
                "outfit_variant_id": e.get("outfit_variant_id"),
                "action": str(e.get("action") or ""),
                "expression": str(e.get("expression") or ""),
            })
    d["entities"] = fixed_entities
    # camera 默认值
    cam = d.get("camera") or {}
    cam.setdefault("shot_size", "MS")
    cam.setdefault("angle", "eye")
    cam.setdefault("movement", "static")
    d["camera"] = cam
    return d


# ─────────────────────────────────────────────────────────
# 主入口：plan
# ─────────────────────────────────────────────────────────


async def plan_shots(
    db: Session,
    *,
    session_id: str,
    project_id: str,
    episode: int,
    target_count: int = 14,
    enable_multi_candidate: bool = True,
) -> dict:
    """切镜并落库。返回 {ok, shots, rag_used, elapsed_ms, msg}"""
    started = time.perf_counter()

    elig = check_eligibility(db, session_id=session_id, project_id=project_id, episode=episode)
    if not elig.eligible:
        return {
            "ok": False,
            "error": elig.reason,
            "detail": elig.detail,
            "missing": elig.missing_locked_characters,
        }

    confirmed = script_confirm_service.get_confirmed_version(db, session_id, episode)
    script_text = (confirmed.full_output or confirmed.context_output or "").strip()

    locked_chars = (
        db.query(CharacterVisualBase)
        .filter(
            CharacterVisualBase.project_id == project_id,
            CharacterVisualBase.is_locked == True,  # noqa: E712
        )
        .all()
    )
    scene_bases = (
        db.query(SceneVisualBase)
        .filter(SceneVisualBase.project_id == project_id)
        .all()
    )

    # 跨集上下文（best-effort）
    cross_ctx = ""
    if episode > 1:
        try:
            cross_ctx = await retrieve_cross_episode_context(
                project_id=project_id,
                current_episode=episode,
                query="主角 关键转折 前情",
                top_k=3,
                layer_filter="scene_card",
            )
        except Exception as exc:
            logger.warning("cross episode ctx failed: %s", exc)

    if not generation_enabled():
        return {"ok": False, "error": "ai_disabled", "detail": "AI 生成服务未启用"}

    prompt = _build_shot_plan_prompt(
        episode=episode,
        script_text=script_text,
        target_count=target_count,
        locked_chars=locked_chars,
        scene_bases=scene_bases,
        cross_episode_ctx=cross_ctx,
    )
    try:
        raw = generate_text(_SHOT_PLAN_SYSTEM, prompt, temperature=0.6, max_tokens=4500)
    except Exception as exc:
        logger.warning("shot plan LLM failed: %s", exc)
        return {"ok": False, "error": "llm_failed", "detail": str(exc)}

    arr = _parse_shot_array(raw or "")
    if not arr:
        return {"ok": False, "error": "parse_failed", "detail": "无法解析模型返回的 JSON 数组"}

    # 清空本集旧镜头
    db.query(Shot).filter(
        Shot.project_id == project_id, Shot.episode == episode
    ).delete()
    db.commit()

    # 落库
    shots_out: list[dict] = []
    for i, item in enumerate(arr):
        norm = _normalize_shot_dict(item, order=i + 1)

        candidates: list[dict] = []
        if enable_multi_candidate and norm.get("beat_role") in KEY_BEAT_ROLES_FOR_MULTI_CANDIDATE:
            candidates = await _generate_alternates(norm, n=DEFAULT_CANDIDATE_COUNT - 1)

        shot = Shot(
            id=str(uuid.uuid4()),
            project_id=project_id,
            episode=episode,
            scene_id=norm.get("scene_id") or "",
            shot_order=i + 1,
            spec_json=json.dumps(norm, ensure_ascii=False),
            candidates_json=json.dumps(candidates, ensure_ascii=False),
            selected_candidate_idx=0,
            is_stale=False,
            rag_context_snapshot=cross_ctx[:2000] if cross_ctx else "",
        )
        db.add(shot)
        db.flush()
        shots_out.append(shot.to_dict())

    db.commit()
    return {
        "ok": True,
        "shots": shots_out,
        "rag_used": bool(cross_ctx),
        "elapsed_ms": int((time.perf_counter() - started) * 1000),
        "msg": f"已生成 {len(shots_out)} 个镜头",
    }


async def _generate_alternates(base_shot: dict, n: int) -> list[dict]:
    """对关键镜头多生成 n 个候选（变镜头语言/构图，但保 entities/dialogue 不变）"""
    if n <= 0 or not generation_enabled():
        return []
    base_brief = json.dumps({
        "entities": base_shot.get("entities"),
        "dialogue": base_shot.get("dialogue"),
        "duration_sec": base_shot.get("duration_sec"),
        "beat_role": base_shot.get("beat_role"),
    }, ensure_ascii=False)
    prompt = (
        f"基于下面镜头的核心情节，生成 {n} 个不同镜头语言的替代候选。"
        f"角色和台词不变，只换 camera / shot_delta / framing 等。"
        f"输出 JSON 数组，每个元素是完整 ShotSpec。\n\n基准：\n{base_brief}\n\n"
        "只输出数组。"
    )
    try:
        raw = generate_text(_SHOT_PLAN_SYSTEM, prompt, temperature=0.85, max_tokens=2000)
        arr = _parse_shot_array(raw or "")
        out = []
        for i, item in enumerate(arr[:n]):
            norm = _normalize_shot_dict(item, order=base_shot.get("order") or 1)
            # 保持核心字段对齐基准
            norm["entities"] = base_shot["entities"]
            norm["dialogue"] = base_shot.get("dialogue") or ""
            out.append(norm)
        return out
    except Exception as exc:
        logger.warning("alternates failed: %s", exc)
        return []


# ─────────────────────────────────────────────────────────
# 单镜重生成 / 选候选
# ─────────────────────────────────────────────────────────


async def regenerate_shot(
    db: Session,
    *,
    shot_id: str,
    pick_candidate_idx: Optional[int] = None,
) -> dict:
    shot = db.query(Shot).filter(Shot.id == shot_id).first()
    if not shot:
        return {"ok": False, "error": "not_found"}

    if pick_candidate_idx is not None:
        candidates = json.loads(shot.candidates_json or "[]")
        if pick_candidate_idx < 0 or pick_candidate_idx >= len(candidates):
            return {"ok": False, "error": "invalid_candidate_idx"}
        # 把选中的 candidate 升级为主 spec，原 spec 退到 candidates[0]
        old_spec = json.loads(shot.spec_json or "{}")
        new_spec = candidates[pick_candidate_idx]
        new_candidates = [old_spec] + [c for i, c in enumerate(candidates) if i != pick_candidate_idx]
        shot.spec_json = json.dumps(new_spec, ensure_ascii=False)
        shot.candidates_json = json.dumps(new_candidates, ensure_ascii=False)
        shot.is_stale = False
        db.commit()
        return {"ok": True, "shot": shot.to_dict()}

    # 否则：重新生成（基于原 spec 微调，保持 entities/dialogue）
    base = json.loads(shot.spec_json or "{}")
    alts = await _generate_alternates(base, n=1)
    if not alts:
        return {"ok": False, "error": "regenerate_failed"}
    shot.spec_json = json.dumps(alts[0], ensure_ascii=False)
    shot.is_stale = False
    db.commit()
    return {"ok": True, "shot": shot.to_dict()}


def list_shots(db: Session, *, project_id: str, episode: int) -> list[dict]:
    rows = (
        db.query(Shot)
        .filter(Shot.project_id == project_id, Shot.episode == episode)
        .order_by(Shot.shot_order.asc())
        .all()
    )
    return [r.to_dict() for r in rows]
