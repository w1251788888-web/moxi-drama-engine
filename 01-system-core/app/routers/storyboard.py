"""分镜路由

接口：
- GET  /api/storyboard/eligibility       ?session_id=&project_id=&episode=
- POST /api/storyboard/plan              {session_id, project_id, episode, target_shot_count?, enable_multi_candidate?}
- GET  /api/storyboard/list              ?project_id=&episode=
- POST /api/storyboard/compile           {shot_id, platforms[]}
- POST /api/storyboard/compile-batch     {project_id, episode, platforms[]}
- POST /api/storyboard/regenerate-shot   {shot_id, pick_candidate_idx?}
- GET  /api/storyboard/prompts           ?shot_id=    （取已缓存的多平台 prompt）
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.auth.dependencies import ProjectAccessActor, verify_project_actor
from app.database import get_db
from app.models.project_v2 import ProjectV2
from app.models.storyboard import Shot
from app.schemas.storyboard import (
    StoryboardPlanRequest, CompileRequest, CompileBatchRequest,
    RegenerateShotRequest, EligibilityResponse,
)
from app.services.project_access_policy import require_project_permission
from app.services import storyboard_service as sb_svc
from app.services import prompt_compiler_service as pc_svc

router = APIRouter(prefix="/storyboard", tags=["Storyboard & Prompt Compile"])


def _require_storyboard_project(
    db: Session,
    *,
    project_id: str,
    actor: ProjectAccessActor,
    permission: str,
) -> ProjectV2:
    project = db.query(ProjectV2).filter(ProjectV2.id == str(project_id)).first()
    if project is None:
        raise HTTPException(status_code=404, detail="项目不存在")
    require_project_permission(db, project, actor, permission)
    return project


def _require_storyboard_shot(
    db: Session,
    *,
    shot_id: str,
    actor: ProjectAccessActor,
    permission: str,
) -> Shot:
    shot = db.query(Shot).filter(Shot.id == str(shot_id)).first()
    if shot is None:
        raise HTTPException(status_code=404, detail="镜头不存在")
    _require_storyboard_project(db, project_id=shot.project_id, actor=actor, permission=permission)
    return shot


@router.get("/eligibility", response_model=EligibilityResponse, summary="检查是否可生成分镜")
async def eligibility(
    session_id: str = Query(...),
    project_id: str = Query(...),
    episode: int = Query(...),
    db: Session = Depends(get_db),
    actor: ProjectAccessActor = Depends(verify_project_actor),
):
    _require_storyboard_project(db, project_id=project_id, actor=actor, permission="view")
    return sb_svc.check_eligibility(
        db, session_id=session_id, project_id=project_id, episode=episode,
    )


@router.post("/plan", summary="生成本集分镜")
async def plan(
    req: StoryboardPlanRequest,
    db: Session = Depends(get_db),
    actor: ProjectAccessActor = Depends(verify_project_actor),
):
    _require_storyboard_project(db, project_id=req.project_id, actor=actor, permission="edit")
    # 这里 session_id 与 project_id 一对一时可以共用；当前从前端 payload 取 session_id
    # 兼容：如 req 没有 session_id，直接用 project_id 作为 session_id
    session_id = getattr(req, "session_id", None) or req.project_id
    result = await sb_svc.plan_shots(
        db,
        session_id=session_id,
        project_id=req.project_id,
        episode=req.episode,
        target_count=req.target_shot_count,
        enable_multi_candidate=req.enable_multi_candidate,
    )
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result)
    return result


@router.get("/list", summary="列出本集所有镜头")
async def list_shots(
    project_id: str = Query(...),
    episode: int = Query(...),
    db: Session = Depends(get_db),
    actor: ProjectAccessActor = Depends(verify_project_actor),
):
    _require_storyboard_project(db, project_id=project_id, actor=actor, permission="view")
    return {"items": sb_svc.list_shots(db, project_id=project_id, episode=episode)}


@router.post("/compile", summary="编译单镜到指定平台")
async def compile_shot(
    req: CompileRequest,
    db: Session = Depends(get_db),
    actor: ProjectAccessActor = Depends(verify_project_actor),
):
    _require_storyboard_shot(db, shot_id=req.shot_id, actor=actor, permission="edit")
    try:
        packs = pc_svc.compile_shot(db, shot_id=req.shot_id, platforms=req.platforms)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return {"ok": True, "shot_id": req.shot_id, "packs": [p.model_dump() for p in packs]}


@router.post("/compile-batch", summary="批量编译本集所有镜头")
async def compile_batch(
    req: CompileBatchRequest,
    db: Session = Depends(get_db),
    actor: ProjectAccessActor = Depends(verify_project_actor),
):
    _require_storyboard_project(db, project_id=req.project_id, actor=actor, permission="edit")
    return pc_svc.compile_episode(
        db, project_id=req.project_id, episode=req.episode, platforms=req.platforms,
    )


@router.post("/regenerate-shot", summary="重新生成或选择候选")
async def regenerate(
    req: RegenerateShotRequest,
    db: Session = Depends(get_db),
    actor: ProjectAccessActor = Depends(verify_project_actor),
):
    _require_storyboard_shot(db, shot_id=req.shot_id, actor=actor, permission="edit")
    res = await sb_svc.regenerate_shot(
        db, shot_id=req.shot_id, pick_candidate_idx=req.pick_candidate_idx,
    )
    if not res.get("ok"):
        raise HTTPException(status_code=400, detail=res.get("error") or "regenerate_failed")
    return res


@router.get("/prompts", summary="取已缓存的多平台 prompt")
async def list_prompts(
    shot_id: str = Query(...),
    db: Session = Depends(get_db),
    actor: ProjectAccessActor = Depends(verify_project_actor),
):
    _require_storyboard_shot(db, shot_id=shot_id, actor=actor, permission="view")
    return {"items": pc_svc.list_compiled_prompts(db, shot_id=shot_id)}
