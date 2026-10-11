"""剧本"确认保存"路由

接口：
- POST /api/script/confirm        {session_id, episode, project_id, character_name_to_id?}
- POST /api/script/unconfirm      {session_id, episode, project_id}
- GET  /api/script/confirm-status ?session_id=&episode=
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth.dependencies import verify_admin
from app.database import get_db
from app.services import script_confirm_service as svc

router = APIRouter(prefix="/script", tags=["Script Confirm"])


class ConfirmRequest(BaseModel):
    session_id: str
    episode: int
    project_id: str
    # 角色名 -> character_id 字典，用于 RAPTOR 检索元数据
    character_name_to_id: dict[str, str] = Field(default_factory=dict)


class UnconfirmRequest(BaseModel):
    session_id: str
    episode: int
    project_id: str


@router.post("/confirm", summary="确认本集剧本（私有 RAG 默认关闭）")
async def confirm(
    req: ConfirmRequest,
    db: Session = Depends(get_db),
    _: bool = Depends(verify_admin),
):
    result = await svc.confirm_script(
        db,
        session_id=req.session_id,
        episode=req.episode,
        project_id=req.project_id,
        character_name_to_id=req.character_name_to_id or {},
    )
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("error") or "confirm_failed")
    return result


@router.post("/unconfirm", summary="撤销本集确认")
async def unconfirm(
    req: UnconfirmRequest,
    db: Session = Depends(get_db),
    _: bool = Depends(verify_admin),
):
    result = await svc.unconfirm_script(
        db,
        session_id=req.session_id,
        episode=req.episode,
        project_id=req.project_id,
    )
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("error") or "unconfirm_failed")
    return result


@router.get("/confirm-status", summary="查询本集确认状态")
async def status(
    session_id: str = Query(...),
    episode: int = Query(...),
    db: Session = Depends(get_db),
    _: bool = Depends(verify_admin),
):
    return svc.confirm_status(db, session_id=session_id, episode=episode)
