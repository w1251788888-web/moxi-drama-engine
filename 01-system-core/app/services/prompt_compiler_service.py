"""提示词编译器：ShotSpec + CharacterVisualBase + SceneVisualBase → 五平台 PromptPack

设计原则（Sora System Card / Kling 提示词指南 / 社区共识）：
- 不重复角色外貌：从 visual_base 拉取，编译时拼装
- 平台模板独立：每个平台有自己的字段顺序与关键词偏好
- 负面词逐角色合并 + 平台默认负面词
- 每个 adapter ≈ 50-80 行，纯函数

输入：
- shot_spec: ShotSpec 实例或 dict
- char_bases: list[CharacterVisualBase]（已锁定）
- scene_base: SceneVisualBase | None
- platform: str

输出：PromptPack（prompt_text/negative_prompt/params）
"""
from __future__ import annotations

import json
import logging
from typing import Optional

from sqlalchemy.orm import Session

from app.models.character_visual import CharacterVisualBase, SceneVisualBase
from app.models.storyboard import Shot, ShotPrompt
from app.schemas.storyboard import PromptPack

logger = logging.getLogger(__name__)


SUPPORTED_PLATFORMS = ["jimeng", "kling", "hailuo", "sora", "generic"]


# ─────────────────────────────────────────────────────────
# 工具函数：把基底拼成段落
# ─────────────────────────────────────────────────────────


def _outfit_for_entity(char_base: CharacterVisualBase, outfit_variant_id: Optional[str]) -> str:
    """根据 outfit_variant_id 选服装；空则用 default_outfit"""
    visual = json.loads(char_base.visual_text or "{}")
    default_outfit = visual.get("default_outfit") or ""
    if not outfit_variant_id:
        return default_outfit
    variants = json.loads(char_base.outfit_variants or "[]")
    for v in variants:
        if v.get("id") == outfit_variant_id:
            return v.get("desc") or default_outfit
    return default_outfit


def _character_descriptor(char_base: CharacterVisualBase, outfit: str, action: str, expression: str) -> str:
    """单角色完整描述：name + 五官 + 发型 + 体型 + 当前服装 + 动作 + 表情"""
    v = json.loads(char_base.visual_text or "{}")
    parts = []
    name = char_base.character_name or ""
    if name:
        parts.append(name)
    if v.get("age_look"):
        parts.append(v["age_look"])
    if v.get("gender"):
        parts.append(v["gender"])
    if v.get("face"):
        parts.append(v["face"])
    if v.get("hair"):
        parts.append(v["hair"])
    if v.get("body"):
        parts.append(v["body"])
    if v.get("skin"):
        parts.append(v["skin"])
    if outfit:
        parts.append(f"穿{outfit}")
    if v.get("signature_props"):
        parts.append(v["signature_props"])
    if action:
        parts.append(action)
    if expression:
        parts.append(expression)
    return "，".join(p for p in parts if p)


def _scene_descriptor(scene: Optional[SceneVisualBase]) -> str:
    if not scene:
        return ""
    parts = []
    if scene.environment:
        parts.append(scene.environment)
    if scene.time_of_day:
        parts.append(scene.time_of_day)
    if scene.lighting:
        parts.append(scene.lighting)
    if scene.color_palette:
        parts.append(scene.color_palette)
    if scene.atmosphere:
        parts.append(scene.atmosphere)
    return "，".join(parts)


def _camera_descriptor(camera: dict, *, with_brackets: bool = False) -> str:
    """运镜描述

    with_brackets=True 时使用可灵风格 [景别:中景][运镜:推进]
    """
    SHOT_SIZE_CN = {
        "ELS": "大远景", "LS": "全景", "MS": "中景",
        "MCU": "中近景", "CU": "特写", "ECU": "大特写",
    }
    ANGLE_CN = {
        "eye": "平视", "high": "俯拍", "low": "仰拍",
        "over_shoulder": "过肩", "top": "顶视", "dutch": "倾斜",
    }
    MOVE_CN = {
        "static": "固定", "push_in": "推进", "pull_out": "拉出",
        "pan_left": "左摇", "pan_right": "右摇",
        "tilt_up": "上摇", "tilt_down": "下摇",
        "tracking": "跟拍", "handheld": "手持",
        "crane": "升降", "zoom_in": "变焦推", "zoom_out": "变焦拉",
    }
    ss = SHOT_SIZE_CN.get(camera.get("shot_size") or "", camera.get("shot_size") or "")
    ang = ANGLE_CN.get(camera.get("angle") or "", camera.get("angle") or "")
    mv = MOVE_CN.get(camera.get("movement") or "", camera.get("movement") or "")
    if with_brackets:
        bits = []
        if ss: bits.append(f"[景别:{ss}]")
        if ang: bits.append(f"[机位:{ang}]")
        if mv: bits.append(f"[运镜:{mv}]")
        return "".join(bits)
    bits = [b for b in [ss, ang, mv] if b]
    return "，".join(bits)


def _merge_negatives(char_bases: list[CharacterVisualBase], extra: list[str]) -> str:
    parts = []
    for cb in char_bases:
        if cb.negative_prompt:
            parts.append(cb.negative_prompt.strip())
    parts.extend([e for e in extra if e])
    seen = set()
    out = []
    for p in parts:
        for token in p.replace("，", ",").split(","):
            t = token.strip()
            if t and t not in seen:
                seen.add(t)
                out.append(t)
    return "、".join(out)


# ─────────────────────────────────────────────────────────
# 五个平台 adapter
# ─────────────────────────────────────────────────────────


def _adapter_jimeng(
    *, shot: dict, chars: list[tuple[CharacterVisualBase, dict]],
    scene: Optional[SceneVisualBase], duration_sec: float
) -> PromptPack:
    """即梦/Seedance：自然语言段落式，开头放主体，整段中文"""
    parts = []
    # 角色段
    for cb, e in chars:
        outfit = _outfit_for_entity(cb, e.get("outfit_variant_id"))
        parts.append(_character_descriptor(cb, outfit, e.get("action") or "", e.get("expression") or ""))
    # 场景段
    sd = _scene_descriptor(scene)
    if sd:
        parts.append(f"场景：{sd}")
    # 镜头独有
    delta = shot.get("shot_delta") or {}
    cam_desc = _camera_descriptor(shot.get("camera") or {})
    bits = []
    if cam_desc:
        bits.append(cam_desc)
    if delta.get("framing"):
        bits.append(delta["framing"])
    if delta.get("lighting_delta"):
        bits.append(delta["lighting_delta"])
    if delta.get("mood"):
        bits.append(f"情绪：{delta['mood']}")
    if bits:
        parts.append("，".join(bits))
    # 音频提示（即梦支持音效描述）
    audio = shot.get("audio") or {}
    if any(audio.values()):
        a_bits = [audio.get("sfx") or "", audio.get("bgm_mood") or "", audio.get("voice_mood") or ""]
        parts.append("音频：" + "，".join(b for b in a_bits if b))

    prompt = "。".join(parts) + "。"
    negative = _merge_negatives(
        [cb for cb, _ in chars],
        ["畸变", "崩坏", "多余手指", "面部模糊"],
    )
    return PromptPack(
        platform="jimeng",
        prompt_text=prompt,
        negative_prompt=negative,
        params={
            "duration_sec": duration_sec,
            "aspect_ratio": "9:16",
            "resolution": "1080x1920",
            "seed_policy": "inherit_previous",
        },
    )


def _adapter_kling(
    *, shot: dict, chars: list[tuple[CharacterVisualBase, dict]],
    scene: Optional[SceneVisualBase], duration_sec: float
) -> PromptPack:
    """可灵：支持 [景别:xx][运镜:xx] 显式标签语法，关键词优先级最高"""
    cam_tags = _camera_descriptor(shot.get("camera") or {}, with_brackets=True)
    parts = [cam_tags] if cam_tags else []
    for cb, e in chars:
        outfit = _outfit_for_entity(cb, e.get("outfit_variant_id"))
        parts.append(_character_descriptor(cb, outfit, e.get("action") or "", e.get("expression") or ""))
    sd = _scene_descriptor(scene)
    if sd:
        parts.append(sd)
    delta = shot.get("shot_delta") or {}
    if delta.get("mood"):
        parts.append(f"情绪[{delta['mood']}]")
    if delta.get("lighting_delta"):
        parts.append(delta["lighting_delta"])
    prompt = "，".join(p for p in parts if p)
    negative = _merge_negatives(
        [cb for cb, _ in chars],
        ["低清", "面部畸变", "多人融合"],
    )
    return PromptPack(
        platform="kling",
        prompt_text=prompt,
        negative_prompt=negative,
        params={
            "duration_sec": duration_sec,
            "aspect_ratio": "9:16",
            "resolution": "1080x1920",
            "mode": "pro",
        },
    )


def _adapter_hailuo(
    *, shot: dict, chars: list[tuple[CharacterVisualBase, dict]],
    scene: Optional[SceneVisualBase], duration_sec: float
) -> PromptPack:
    """海螺：偏镜头语言，景别+运镜放最前，prompt 控制在 200 字内"""
    cam_desc = _camera_descriptor(shot.get("camera") or {})
    head = cam_desc + "。" if cam_desc else ""

    # 角色段（紧凑）
    char_bits = []
    for cb, e in chars:
        outfit = _outfit_for_entity(cb, e.get("outfit_variant_id"))
        v = json.loads(cb.visual_text or "{}")
        compact = "，".join(b for b in [
            cb.character_name,
            v.get("age_look") or "",
            v.get("face") or "",
            f"穿{outfit}" if outfit else "",
            (e.get("action") or ""),
            (e.get("expression") or ""),
        ] if b)
        char_bits.append(compact)
    body = "；".join(char_bits)

    sd = _scene_descriptor(scene)
    delta = shot.get("shot_delta") or {}
    tail_bits = [b for b in [sd, delta.get("lighting_delta"), delta.get("mood")] if b]
    tail = "。".join(tail_bits)

    prompt = (head + body + ("。" + tail if tail else ""))[:240]
    negative = _merge_negatives([cb for cb, _ in chars], ["失真", "扭曲"])
    return PromptPack(
        platform="hailuo",
        prompt_text=prompt,
        negative_prompt=negative,
        params={
            "duration_sec": duration_sec,
            "aspect_ratio": "9:16",
            "resolution": "1080x1920",
        },
    )


def _adapter_sora(
    *, shot: dict, chars: list[tuple[CharacterVisualBase, dict]],
    scene: Optional[SceneVisualBase], duration_sec: float
) -> PromptPack:
    """Sora：整段电影描述，越像 IMDb 剧情简介越好。英文化倾向但保留中文也可"""
    char_descs = []
    for cb, e in chars:
        outfit = _outfit_for_entity(cb, e.get("outfit_variant_id"))
        char_descs.append(_character_descriptor(cb, outfit, e.get("action") or "", e.get("expression") or ""))

    sd = _scene_descriptor(scene)
    delta = shot.get("shot_delta") or {}
    cam_desc = _camera_descriptor(shot.get("camera") or {})

    sentences = []
    if sd:
        sentences.append(f"在{sd}的环境中")
    if char_descs:
        sentences.append("，".join(char_descs))
    if cam_desc:
        sentences.append(f"镜头{cam_desc}")
    if delta.get("framing"):
        sentences.append(delta["framing"])
    if delta.get("lighting_delta"):
        sentences.append(delta["lighting_delta"])
    if delta.get("mood"):
        sentences.append(f"画面情绪{delta['mood']}")
    dialogue = (shot.get("dialogue") or "").strip()
    if dialogue:
        sentences.append(f"角色低声说：{dialogue}")

    prompt = "。".join(sentences) + "。"
    negative = ""  # Sora 不接受 negative，留空
    return PromptPack(
        platform="sora",
        prompt_text=prompt,
        negative_prompt=negative,
        params={
            "duration_sec": duration_sec,
            "aspect_ratio": "9:16",
        },
    )


def _adapter_generic(
    *, shot: dict, chars: list[tuple[CharacterVisualBase, dict]],
    scene: Optional[SceneVisualBase], duration_sec: float
) -> PromptPack:
    """通用版：六段式标签化（主体/场景/风格/灯光/色彩/负面）"""
    subject_bits = []
    for cb, e in chars:
        outfit = _outfit_for_entity(cb, e.get("outfit_variant_id"))
        subject_bits.append(_character_descriptor(cb, outfit, e.get("action") or "", e.get("expression") or ""))

    sd = _scene_descriptor(scene)
    delta = shot.get("shot_delta") or {}
    cam_desc = _camera_descriptor(shot.get("camera") or {})

    style_tags = []
    for cb, _ in chars:
        v = json.loads(cb.visual_text or "{}")
        if v.get("style_tags"):
            style_tags.append(v["style_tags"])
    style = "，".join(set(style_tags))

    lighting = (scene.lighting if scene else "") + (("，" + delta["lighting_delta"]) if delta.get("lighting_delta") else "")
    color = scene.color_palette if scene else ""

    sections = [
        f"【主体】{ '；'.join(subject_bits) }",
        f"【场景】{sd}",
        f"【镜头】{cam_desc}",
        f"【风格】{style}",
        f"【灯光】{lighting}",
        f"【色彩】{color}",
    ]
    if delta.get("mood"):
        sections.append(f"【情绪】{delta['mood']}")
    prompt = "\n".join(s for s in sections if not s.endswith("】"))
    negative = _merge_negatives([cb for cb, _ in chars], [])
    return PromptPack(
        platform="generic",
        prompt_text=prompt,
        negative_prompt=negative,
        params={
            "duration_sec": duration_sec,
            "aspect_ratio": "9:16",
        },
    )


_ADAPTERS = {
    "jimeng": _adapter_jimeng,
    "kling": _adapter_kling,
    "hailuo": _adapter_hailuo,
    "sora": _adapter_sora,
    "generic": _adapter_generic,
}


# ─────────────────────────────────────────────────────────
# 主入口
# ─────────────────────────────────────────────────────────


def compile_shot(
    db: Session,
    *,
    shot_id: str,
    platforms: list[str],
) -> list[PromptPack]:
    """编译单镜到指定平台。结果同时缓存到 shot_prompts 表"""
    shot = db.query(Shot).filter(Shot.id == shot_id).first()
    if not shot:
        raise ValueError("shot_not_found")

    spec = json.loads(shot.spec_json or "{}")
    duration = float(spec.get("duration_sec") or 3.0)

    # 拉所有出场角色基底（必须已锁定）
    entities = spec.get("entities") or []
    char_bases: list[tuple[CharacterVisualBase, dict]] = []
    for ent in entities:
        cid = ent.get("character_id")
        if not cid:
            continue
        cb = (
            db.query(CharacterVisualBase)
            .filter(
                CharacterVisualBase.project_id == shot.project_id,
                CharacterVisualBase.character_id == cid,
            )
            .first()
        )
        if cb and cb.is_locked:
            char_bases.append((cb, ent))

    # 拉场景基底
    scene_ref = spec.get("scene_ref") or shot.scene_id or ""
    scene = None
    if scene_ref:
        scene = (
            db.query(SceneVisualBase)
            .filter(
                SceneVisualBase.project_id == shot.project_id,
                SceneVisualBase.scene_id == scene_ref,
            )
            .first()
        )

    out: list[PromptPack] = []
    base_snapshot = {
        cb.character_id: {"version": cb.version, "locked_at": cb.locked_at.isoformat() if cb.locked_at else ""}
        for cb, _ in char_bases
    }

    for platform in platforms:
        adapter = _ADAPTERS.get(platform)
        if not adapter:
            logger.warning("unknown platform: %s", platform)
            continue
        pack = adapter(shot=spec, chars=char_bases, scene=scene, duration_sec=duration)
        out.append(pack)

        # upsert 缓存
        existing = (
            db.query(ShotPrompt)
            .filter(ShotPrompt.shot_id == shot_id, ShotPrompt.platform == platform)
            .first()
        )
        if existing:
            existing.prompt_text = pack.prompt_text
            existing.negative_prompt = pack.negative_prompt
            existing.params_json = json.dumps(pack.params, ensure_ascii=False)
            existing.base_version_snapshot = json.dumps(base_snapshot, ensure_ascii=False)
        else:
            row = ShotPrompt(
                shot_id=shot_id,
                platform=platform,
                prompt_text=pack.prompt_text,
                negative_prompt=pack.negative_prompt,
                params_json=json.dumps(pack.params, ensure_ascii=False),
                base_version_snapshot=json.dumps(base_snapshot, ensure_ascii=False),
            )
            db.add(row)

    # 编译完清掉 stale 标记
    if shot.is_stale:
        shot.is_stale = False
    db.commit()
    return out


def compile_episode(
    db: Session,
    *,
    project_id: str,
    episode: int,
    platforms: list[str],
) -> dict:
    """批量编译本集所有镜头"""
    shots = (
        db.query(Shot)
        .filter(Shot.project_id == project_id, Shot.episode == episode)
        .order_by(Shot.shot_order.asc())
        .all()
    )
    out = []
    for s in shots:
        try:
            packs = compile_shot(db, shot_id=s.id, platforms=platforms)
            out.append({"shot_id": s.id, "shot_order": s.shot_order, "packs": [p.model_dump() for p in packs]})
        except Exception as exc:
            logger.warning("compile shot %s failed: %s", s.id, exc)
            out.append({"shot_id": s.id, "shot_order": s.shot_order, "error": str(exc)})
    return {"ok": True, "items": out}


def list_compiled_prompts(db: Session, *, shot_id: str) -> list[dict]:
    rows = (
        db.query(ShotPrompt)
        .filter(ShotPrompt.shot_id == shot_id)
        .all()
    )
    return [r.to_dict() for r in rows]
