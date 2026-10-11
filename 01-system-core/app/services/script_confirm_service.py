"""剧本"确认保存"服务

职责：
1. 把指定集的当前 step_version 标记为 is_confirmed
2. 同集旧 confirmed 版本自动降级（同集只允许一个 confirmed）
3. 触发 RAPTOR 三层切片；外部私有 RAG 默认关闭，需显式开启才写入 project_{id}
4. 撤销确认时尽量删除已存在的 RAG 文档（best-effort）
5. 修改已确认版本会自动降级（由调用方在写入新版本时处理）

业务边界：
- step_id 形如 "script_writing" + episode 编号；这里采用 "script_ep{N}" 约定。
  如果你现有的 step_id 命名不同，调整 STEP_ID_PREFIX 即可。
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from app.models.step_version import StepVersion
from app.services.raptor_indexer import index_episode, RaptorIndexResult
from app.services.rag_service import get_rag_retriever

logger = logging.getLogger(__name__)


STEP_ID_PREFIX = "script_ep"  # 约定：第 N 集剧本的 step_id = script_ep{N}


def step_id_for_episode(episode: int) -> str:
    return f"{STEP_ID_PREFIX}{episode}"


# ─────────────────────────────────────────────────────────
# 查询
# ─────────────────────────────────────────────────────────


def get_current_version(db: Session, session_id: str, episode: int) -> Optional[StepVersion]:
    """取本集的当前激活版本（is_current=1）"""
    return (
        db.query(StepVersion)
        .filter(
            StepVersion.session_id == session_id,
            StepVersion.step_id == step_id_for_episode(episode),
            StepVersion.is_current == 1,
        )
        .first()
    )


def get_confirmed_version(db: Session, session_id: str, episode: int) -> Optional[StepVersion]:
    """取本集已确认版本"""
    return (
        db.query(StepVersion)
        .filter(
            StepVersion.session_id == session_id,
            StepVersion.step_id == step_id_for_episode(episode),
            StepVersion.is_confirmed == 1,
        )
        .first()
    )


def confirm_status(db: Session, session_id: str, episode: int) -> dict:
    """前端调用：当前确认状态"""
    cur = get_current_version(db, session_id, episode)
    confirmed = get_confirmed_version(db, session_id, episode)

    if not cur:
        return {"status": "no_script", "msg": "本集尚无剧本内容"}
    if not confirmed:
        return {"status": "draft", "msg": "本集剧本尚未确认", "current_version": cur.version_number}

    # 已确认：检查当前内容是否与已确认版本一致
    if cur.id == confirmed.id:
        return {
            "status": "confirmed",
            "msg": "本集剧本已确认",
            "confirmed_version": confirmed.version_number,
            "confirmed_at": confirmed.confirmed_at.isoformat() if confirmed.confirmed_at else None,
            "rag_doc_ids": json.loads(confirmed.rag_doc_ids or "{}"),
        }
    # 已确认但用户又改了：状态退回 stale，提示重新确认
    return {
        "status": "stale",
        "msg": "本集剧本在确认后被修改，请重新确认",
        "confirmed_version": confirmed.version_number,
        "current_version": cur.version_number,
    }


# ─────────────────────────────────────────────────────────
# 确认 / 撤销
# ─────────────────────────────────────────────────────────


async def confirm_script(
    db: Session,
    *,
    session_id: str,
    episode: int,
    project_id: str,
    character_name_to_id: dict[str, str] | None = None,
) -> dict:
    """确认本集当前激活版本，触发本地切片；外部 RAG 写入默认关闭。

    同集旧 confirmed 版本会被自动降级（is_confirmed=0），并尽量删 RAG 文档。
    """
    cur = get_current_version(db, session_id, episode)
    if not cur or not (cur.full_output or cur.context_output or "").strip():
        return {"ok": False, "error": "no_script"}

    # 1) 同集旧 confirmed 降级
    olds = (
        db.query(StepVersion)
        .filter(
            StepVersion.session_id == session_id,
            StepVersion.step_id == step_id_for_episode(episode),
            StepVersion.is_confirmed == 1,
            StepVersion.id != cur.id,
        )
        .all()
    )
    rag = get_rag_retriever()
    for old in olds:
        # 尝试删 RAG 文档（best-effort）
        old_ids = json.loads(old.rag_doc_ids or "{}")
        all_doc_ids: list[str] = []
        if old_ids.get("summary"):
            all_doc_ids.append(old_ids["summary"])
        all_doc_ids += list(old_ids.get("scene_cards") or [])
        all_doc_ids += list(old_ids.get("beats") or [])
        await _best_effort_delete_rag_docs(rag, project_id=project_id, doc_ids=all_doc_ids)

        old.is_confirmed = 0
        old.rag_doc_ids = "{}"
    if olds:
        db.commit()

    # 2) 写 RAG 三层切片
    script_text = (cur.full_output or cur.context_output or "").strip()
    index_result: RaptorIndexResult = await index_episode(
        project_id=project_id,
        episode=episode,
        script_text=script_text,
        character_name_to_id=character_name_to_id or {},
    )

    # 3) 标记当前版本
    cur.is_confirmed = 1
    cur.confirmed_at = datetime.utcnow()
    cur.rag_doc_ids = json.dumps(index_result.as_step_version_payload(), ensure_ascii=False)
    db.commit()

    return {
        "ok": True,
        "version_number": cur.version_number,
        "confirmed_at": cur.confirmed_at.isoformat(),
        "rag_enabled": index_result.rag_enabled,
        "rag_doc_count": len(index_result.docs),
        "rag_doc_ids_persisted": index_result.as_step_version_payload(),
        "rag_error": index_result.error,
    }


async def unconfirm_script(
    db: Session,
    *,
    session_id: str,
    episode: int,
    project_id: str,
) -> dict:
    """撤销本集确认。"""
    confirmed = get_confirmed_version(db, session_id, episode)
    if not confirmed:
        return {"ok": False, "error": "not_confirmed"}

    # 删 RAG 文档（best-effort）
    rag = get_rag_retriever()
    ids = json.loads(confirmed.rag_doc_ids or "{}")
    all_doc_ids: list[str] = []
    if ids.get("summary"):
        all_doc_ids.append(ids["summary"])
    all_doc_ids += list(ids.get("scene_cards") or [])
    all_doc_ids += list(ids.get("beats") or [])
    await _best_effort_delete_rag_docs(rag, project_id=project_id, doc_ids=all_doc_ids)

    confirmed.is_confirmed = 0
    confirmed.confirmed_at = None
    confirmed.rag_doc_ids = "{}"
    db.commit()

    return {"ok": True}


async def _best_effort_delete_rag_docs(rag, *, project_id: str, doc_ids: list[str]) -> None:
    """尝试删 Dify 文档；失败仅记日志，不抛异常。"""
    if not (rag and rag.enabled and doc_ids):
        return
    if not hasattr(rag, "delete_document"):
        # rag_service 加 delete_document 之前的兼容
        return
    for did in doc_ids:
        try:
            await rag.delete_document(dataset=f"project_{project_id}", document_id=did)
        except Exception as exc:
            logger.warning("rag delete doc failed (id=%s): %s", did, exc)
