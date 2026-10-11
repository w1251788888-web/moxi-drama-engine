"""角色视觉档案服务

职责：
1. 一键 AI 生成角色视觉档案（基于叙事档案 + 题材 + 风格）
2. 编辑/锁定/撤销锁定
3. 锁定时仅写数据库；外部私有 RAG 归档默认关闭，需运营显式开启
4. 锁定后变更，把所有引用此角色的 Shot 标记 is_stale=True，前端高亮提示重编译
"""
from __future__ import annotations

import json
import logging
import uuid
import asyncio
from datetime import datetime
from typing import Any, Optional

from sqlalchemy.orm import Session

from app.models.character_visual import CharacterVisualBase
from app.models.storyboard import Shot
from app.schemas.character_visual import (
    CharacterVisualText,
    CharacterVisualUpsert,
    OutfitVariant,
)
from app.services.rag_service import get_rag_retriever, private_project_rag_enabled
from app.services.text_generation_service import generate_text, generation_enabled

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────
# 查询
# ─────────────────────────────────────────────────────────


def get_by_character(db: Session, project_id: str, character_id: str) -> Optional[CharacterVisualBase]:
    return (
        db.query(CharacterVisualBase)
        .filter(
            CharacterVisualBase.project_id == project_id,
            CharacterVisualBase.character_id == character_id,
        )
        .first()
    )


def list_by_project(db: Session, project_id: str) -> list[CharacterVisualBase]:
    return (
        db.query(CharacterVisualBase)
        .filter(CharacterVisualBase.project_id == project_id)
        .order_by(CharacterVisualBase.created_at.asc())
        .all()
    )


def list_locked_character_ids(db: Session, project_id: str) -> set[str]:
    rows = (
        db.query(CharacterVisualBase.character_id)
        .filter(
            CharacterVisualBase.project_id == project_id,
            CharacterVisualBase.is_locked == True,  # noqa: E712
        )
        .all()
    )
    return {r[0] for r in rows}


# ─────────────────────────────────────────────────────────
# AI 生成（基于叙事档案）
# ─────────────────────────────────────────────────────────


_VISUAL_GEN_SYSTEM = (
    "你是 AI 短剧视觉指导。给定角色叙事档案、题材、风格，"
    "输出严格 JSON 格式的角色视觉身份基底，避免任何夸张描述，"
    "字段必须有：age_look, gender, face, hair, body, skin, "
    "default_outfit, signature_props, voice_tone, style_tags。"
    "每字段不超过 30 字。"
)


def fallback_visual_text(
    *,
    character_name: str,
    narrative_profile: str,
    genre: str = "",
    style_mode: str = "realistic",
) -> dict[str, str]:
    """Return a deterministic visual draft when the LLM is unavailable or returns invalid JSON."""
    profile = f"{character_name}\n{narrative_profile}\n{genre}".strip()
    gender = "男" if any(word in profile for word in ["男主", "男", "父", "何铮"]) else "女" if any(word in profile for word in ["女主", "女", "母", "吴雪"]) else ""
    age_look = "25-35岁，现代都市感"
    if any(word in profile for word in ["继承人", "总裁", "高位", "企业"]):
        default_outfit = "深色修身西装，低调腕表"
        style_tags = "都市精英、克制、冷感"
    elif any(word in profile for word in ["证据", "逃离", "被迫", "柔弱"]):
        default_outfit = "浅色针织外套，简洁通勤装"
        style_tags = "脆弱感、警觉、现实主义"
    elif any(word in profile for word in ["实验", "医生", "负责人"]):
        default_outfit = "白大褂或深色实验服"
        style_tags = "冷静、危险、理性"
    else:
        default_outfit = "现代日常服装，颜色克制"
        style_tags = "真人短剧、现实主义、易辨识"

    face = "五官清晰，表情有压抑情绪"
    if any(word in profile for word in ["外冷", "冷", "克制"]):
        face = "轮廓清晰，眼神克制疏离"
    elif any(word in profile for word in ["柔弱", "害怕", "逃离"]):
        face = "眉眼紧张，带防备和疲惫感"

    return {
        "age_look": age_look,
        "gender": gender,
        "face": face,
        "hair": "自然黑发，利落不过度造型",
        "body": "中等偏瘦，身形干净",
        "skin": "自然肤色，真实光感",
        "default_outfit": default_outfit,
        "signature_props": "手机、旧证件或关键线索物",
        "voice_tone": "低声克制，情绪爆发时有压迫感",
        "style_tags": style_tags if style_mode == "realistic" else f"{style_tags}、{style_mode}",
    }


def ai_generate_visual_text_result(
    *,
    character_name: str,
    narrative_profile: str,
    genre: str = "",
    style_mode: str = "realistic",
) -> dict[str, Any]:
    """Generate a visual draft and report whether it came from the GPT-compatible LLM or fallback."""
    fallback = fallback_visual_text(
        character_name=character_name,
        narrative_profile=narrative_profile,
        genre=genre,
        style_mode=style_mode,
    )
    if not generation_enabled():
        return {
            "visual_text": fallback,
            "backend": "fallback",
            "fallback_reason": "text_generation_disabled",
        }

    user_prompt = (
        f"角色名：{character_name}\n"
        f"叙事档案：\n{narrative_profile or '（无）'}\n"
        f"题材：{genre or '都市短剧'}\n"
        f"风格：{style_mode}\n\n"
        "请输出 JSON，字段顺序固定：\n"
        '{\n'
        '  "age_look": "",\n'
        '  "gender": "",\n'
        '  "face": "",\n'
        '  "hair": "",\n'
        '  "body": "",\n'
        '  "skin": "",\n'
        '  "default_outfit": "",\n'
        '  "signature_props": "",\n'
        '  "voice_tone": "",\n'
        '  "style_tags": ""\n'
        '}\n'
        "只输出 JSON，不要任何其他文字。"
    )
    try:
        raw = generate_text(
            _VISUAL_GEN_SYSTEM,
            user_prompt,
            temperature=0.5,
            max_tokens=800,
            timeout_seconds=18,
            max_retries=1,
        ) or ""
    except Exception as exc:
        logger.warning("ai_generate_visual_text failed: %s", exc)
        return {
            "visual_text": fallback,
            "backend": "fallback",
            "fallback_reason": type(exc).__name__,
        }

    # 抽 JSON
    text = raw.strip()
    if "```" in text:
        # 去除围栏
        parts = text.split("```")
        for p in parts:
            if "{" in p and "}" in p:
                text = p
                break
    if "{" in text and "}" in text:
        try:
            text = text[text.index("{") : text.rindex("}") + 1]
            obj = json.loads(text)
            if isinstance(obj, dict):
                generated = {k: str(v or "") for k, v in obj.items()}
                return {
                    "visual_text": {**fallback, **{k: v for k, v in generated.items() if v}},
                    "backend": "llm",
                    "fallback_reason": "",
                }
        except Exception as exc:
            logger.warning("ai_generate_visual_text parse failed: %s | raw=%s", exc, raw[:200])
    return {
        "visual_text": fallback,
        "backend": "fallback",
        "fallback_reason": "invalid_json",
    }


def ai_generate_visual_text(
    *,
    character_name: str,
    narrative_profile: str,
    genre: str = "",
    style_mode: str = "realistic",
) -> dict:
    """让 LLM 出一份初版视觉档案文本字段；失败时返回确定性的本地草稿。"""
    result = ai_generate_visual_text_result(
        character_name=character_name,
        narrative_profile=narrative_profile,
        genre=genre,
        style_mode=style_mode,
    )
    return dict(result["visual_text"])


# ─────────────────────────────────────────────────────────
# 创建 / 更新
# ─────────────────────────────────────────────────────────


def upsert(db: Session, project_id: str, payload: CharacterVisualUpsert) -> CharacterVisualBase:
    row = get_by_character(db, project_id, payload.character_id)
    is_new = row is None

    if is_new:
        row = CharacterVisualBase(
            id=str(uuid.uuid4()),
            project_id=project_id,
            character_id=payload.character_id,
        )
        db.add(row)

    # 已锁定时不允许修改（要先 unlock）
    if row.is_locked:
        raise ValueError("character_visual_locked")

    row.character_name = payload.character_name or row.character_name
    row.visual_text = json.dumps(payload.visual_text.dict(), ensure_ascii=False)
    row.outfit_variants = json.dumps(
        [v.dict() for v in payload.outfit_variants], ensure_ascii=False
    )
    row.negative_prompt = payload.negative_prompt or ""
    row.reference_images = json.dumps(payload.reference_images or [], ensure_ascii=False)

    if not is_new:
        row.version = (row.version or 1) + 1
    row.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(row)
    return row


# ─────────────────────────────────────────────────────────
# 锁定 / 撤销锁定
# ─────────────────────────────────────────────────────────


async def lock(db: Session, project_id: str, character_id: str) -> dict:
    row = get_by_character(db, project_id, character_id)
    if not row:
        return {"ok": False, "error": "not_found"}
    if row.is_locked:
        return {"ok": True, "already_locked": True}

    row.is_locked = True
    row.locked_at = datetime.utcnow()
    row.rag_doc_id = ""
    db.commit()
    locked_at = row.locked_at

    # 写入 RAG（可选，best-effort）。默认关闭，避免用户私有档案进入外部知识库。
    rag_doc_id = ""
    private_rag_status = "disabled"
    rag = get_rag_retriever()
    rag_dataset = f"project_{project_id}_characters"
    if rag.enabled and private_project_rag_enabled() and rag_dataset in rag.dataset_map:
        private_rag_status = "enabled"
        try:
            payload_text = (
                f"[character_visual_base]\n"
                f"name: {row.character_name}\n"
                f"version: {row.version}\n"
                f"visual_text: {row.visual_text}\n"
                f"outfit_variants: {row.outfit_variants}\n"
                f"negative: {row.negative_prompt}\n"
            )
            ret = await asyncio.wait_for(
                rag.create_text_document(
                    dataset=rag_dataset,
                    name=f"{character_id}_v{row.version}",
                    text=payload_text,
                ),
                timeout=2.0,
            )
            if ret.get("ok"):
                d = (ret.get("data") or {}).get("document") or {}
                rag_doc_id = d.get("id") or ""
                row.rag_doc_id = rag_doc_id
                db.commit()
        except Exception as exc:
            logger.warning("character lock RAG write failed: %s", exc)
    elif rag.enabled and private_project_rag_enabled():
        private_rag_status = "dataset_missing"
        logger.info("character lock RAG write skipped: dataset %s is not mapped", rag_dataset)

    return {
        "ok": True,
        "locked_at": locked_at.isoformat(),
        "rag_doc_id": rag_doc_id,
        "private_rag": private_rag_status,
    }


async def unlock(db: Session, project_id: str, character_id: str) -> dict:
    row = get_by_character(db, project_id, character_id)
    if not row:
        return {"ok": False, "error": "not_found"}
    if not row.is_locked:
        return {"ok": True, "already_unlocked": True}

    # 删 RAG 文档（best-effort）
    if row.rag_doc_id:
        rag = get_rag_retriever()
        if rag.enabled and hasattr(rag, "delete_document"):
            try:
                await rag.delete_document(
                    dataset=f"project_{project_id}_characters", document_id=row.rag_doc_id
                )
            except Exception as exc:
                logger.warning("character unlock RAG delete failed: %s", exc)

    row.is_locked = False
    row.locked_at = None
    row.rag_doc_id = ""

    # 标记所有引用此角色的 Shot 为 stale（提示重编译）
    affected_shots = (
        db.query(Shot)
        .filter(Shot.project_id == project_id)
        .all()
    )
    stale_count = 0
    for shot in affected_shots:
        try:
            spec = json.loads(shot.spec_json or "{}")
            entities = spec.get("entities") or []
            if any((e.get("character_id") == character_id) for e in entities):
                shot.is_stale = True
                stale_count += 1
        except Exception:
            continue

    db.commit()
    return {"ok": True, "shots_marked_stale": stale_count}


def mark_dependent_shots_stale(db: Session, project_id: str, character_id: str) -> int:
    """供 upsert 后调用：内容变更后标记所有相关镜头为 stale"""
    affected_shots = (
        db.query(Shot)
        .filter(Shot.project_id == project_id)
        .all()
    )
    stale_count = 0
    for shot in affected_shots:
        try:
            spec = json.loads(shot.spec_json or "{}")
            entities = spec.get("entities") or []
            if any((e.get("character_id") == character_id) for e in entities):
                shot.is_stale = True
                stale_count += 1
        except Exception:
            continue
    if stale_count:
        db.commit()
    return stale_count
