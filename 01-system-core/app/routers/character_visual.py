"""角色视觉档案 + 场景视觉档案 路由

接口：
- POST /api/character-visual/generate         {project_id, character_id, character_name, narrative_profile, genre?, style_mode?}
- GET  /api/character-visual/list?project_id=
- GET  /api/character-visual/by-character?project_id=&character_id=
- PUT  /api/character-visual/upsert           {project_id, payload}
- POST /api/character-visual/lock             {project_id, character_id}
- POST /api/character-visual/unlock           {project_id, character_id}

- GET  /api/scene-visual/list?project_id=&episode=
- POST /api/scene-visual/upsert
- DELETE /api/scene-visual/{scene_id}?project_id=
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.auth.dependencies import ProjectAccessActor, verify_project_actor
from app.routers.projects._helpers import _get_project_for_actor_or_404
from app.database import get_db
from app.schemas.character_visual import (
    CharacterVisualUpsert,
    SceneVisualUpsert,
)
from app.services import character_visual_service as cv_svc
from app.services import scene_visual_service as scv_svc


router = APIRouter(tags=["Character & Scene Visual Base"])


# ─────────────────────────────────────────────────────────
# Character Visual
# ─────────────────────────────────────────────────────────


class GenerateVisualRequest(BaseModel):
    project_id: str
    character_id: str
    character_name: str = ""
    narrative_profile: str = ""
    genre: str = ""
    style_mode: str = "realistic"


class UpsertVisualRequest(BaseModel):
    project_id: str
    payload: CharacterVisualUpsert


class LockRequest(BaseModel):
    project_id: str
    character_id: str


@router.post("/character-visual/generate", summary="AI 一键生成角色视觉档案文本字段")
async def generate_visual(
    req: GenerateVisualRequest,
    db: Session = Depends(get_db),
    actor: ProjectAccessActor = Depends(verify_project_actor),
):
    _get_project_for_actor_or_404(db, req.project_id, actor)
    result = await run_in_threadpool(
        cv_svc.ai_generate_visual_text_result,
        character_name=req.character_name,
        narrative_profile=req.narrative_profile,
        genre=req.genre,
        style_mode=req.style_mode,
    )
    return {"ok": True, **result}


@router.get("/character-visual/list", summary="按项目列出所有角色视觉档案")
async def list_visual(
    project_id: str = Query(...),
    db: Session = Depends(get_db),
    actor: ProjectAccessActor = Depends(verify_project_actor),
):
    _get_project_for_actor_or_404(db, project_id, actor)
    rows = cv_svc.list_by_project(db, project_id)
    return {"items": [r.to_dict() for r in rows]}


@router.get("/character-visual/by-character", summary="按角色 id 取视觉档案")
async def get_visual(
    project_id: str = Query(...),
    character_id: str = Query(...),
    db: Session = Depends(get_db),
    actor: ProjectAccessActor = Depends(verify_project_actor),
):
    _get_project_for_actor_or_404(db, project_id, actor)
    row = cv_svc.get_by_character(db, project_id, character_id)
    if not row:
        raise HTTPException(status_code=404, detail="not_found")
    return row.to_dict()


@router.put("/character-visual/upsert", summary="保存（创建或更新）角色视觉档案")
async def upsert_visual(
    req: UpsertVisualRequest,
    db: Session = Depends(get_db),
    actor: ProjectAccessActor = Depends(verify_project_actor),
):
    _get_project_for_actor_or_404(db, req.project_id, actor)
    try:
        row = cv_svc.upsert(db, req.project_id, req.payload)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    # 如果是已有档案的修改，标记相关镜头为 stale
    stale_count = cv_svc.mark_dependent_shots_stale(db, req.project_id, req.payload.character_id)
    out = row.to_dict()
    out["shots_marked_stale"] = stale_count
    return out


@router.post("/character-visual/lock", summary="锁定角色视觉档案")
async def lock_visual(
    req: LockRequest,
    db: Session = Depends(get_db),
    actor: ProjectAccessActor = Depends(verify_project_actor),
):
    _get_project_for_actor_or_404(db, req.project_id, actor)
    res = await cv_svc.lock(db, req.project_id, req.character_id)
    if not res.get("ok"):
        raise HTTPException(status_code=400, detail=res.get("error") or "lock_failed")
    return res


@router.post("/character-visual/unlock", summary="撤销锁定")
async def unlock_visual(
    req: LockRequest,
    db: Session = Depends(get_db),
    actor: ProjectAccessActor = Depends(verify_project_actor),
):
    _get_project_for_actor_or_404(db, req.project_id, actor)
    res = await cv_svc.unlock(db, req.project_id, req.character_id)
    if not res.get("ok"):
        raise HTTPException(status_code=400, detail=res.get("error") or "unlock_failed")
    return res


# ─────────────────────────────────────────────────────────
# Scene Visual
# ─────────────────────────────────────────────────────────


@router.get("/scene-visual/list", summary="列出场景视觉档案")
async def list_scenes(
    project_id: str = Query(...),
    episode: Optional[int] = Query(None),
    db: Session = Depends(get_db),
    actor: ProjectAccessActor = Depends(verify_project_actor),
):
    _get_project_for_actor_or_404(db, project_id, actor)
    rows = scv_svc.list_by_project(db, project_id, episode)
    return {"items": [r.to_dict() for r in rows]}


@router.post("/scene-visual/upsert", summary="保存场景视觉档案")
async def upsert_scene(
    req: SceneVisualUpsert,
    db: Session = Depends(get_db),
    actor: ProjectAccessActor = Depends(verify_project_actor),
):
    _get_project_for_actor_or_404(db, req.project_id, actor)
    row = scv_svc.upsert(db, req)
    return row.to_dict()


@router.delete("/scene-visual/{scene_id}", summary="删除场景视觉档案")
async def delete_scene(
    scene_id: str,
    project_id: str = Query(...),
    db: Session = Depends(get_db),
    actor: ProjectAccessActor = Depends(verify_project_actor),
):
    _get_project_for_actor_or_404(db, project_id, actor)
    ok = scv_svc.delete(db, project_id, scene_id)
    return {"ok": ok}
