"""
素材库路由
"""
from __future__ import annotations

from datetime import datetime as dt
from typing import Optional, List, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_agent, verify_admin
from app.database import get_db
from app.models.agent import Agent
from app.services import material_library_service

router = APIRouter(prefix="/materials", tags=["Material"])


class MaterialCreateRequest(BaseModel):
    source_platform: str
    source_url: str = ""
    content_type: str = "短剧"
    title: str
    summary: str
    heat_score: float = 0.0
    heat_reason: str = ""
    data_points: List[Any] = Field(default_factory=list)
    structure_tags: List[str] = Field(default_factory=list)
    style_tags: List[str] = Field(default_factory=list)
    project_fit_tags: List[str] = Field(default_factory=list)
    citations: List[str] = Field(default_factory=list)
    selection_score: Optional[float] = None
    status: Optional[str] = None
    raw_payload: dict = Field(default_factory=dict)


class MaterialResponse(BaseModel):
    id: str
    source_platform: str
    source_url: str
    content_type: str
    title: str
    summary: str
    heat_score: float
    heat_reason: str
    data_points: List[Any] = Field(default_factory=list)
    structure_tags: List[str] = Field(default_factory=list)
    style_tags: List[str] = Field(default_factory=list)
    project_fit_tags: List[str] = Field(default_factory=list)
    selection_score: float
    status: str
    citations: List[str] = Field(default_factory=list)
    raw_payload: dict = Field(default_factory=dict)
    created_at: Optional[dt] = None
    updated_at: Optional[dt] = None


class MaterialStatusRequest(BaseModel):
    status: str = Field(..., description="candidate/approved/rejected")


@router.get("", response_model=List[MaterialResponse], summary="查看素材库")
async def list_materials(
    status: Optional[str] = None,
    content_type: Optional[str] = None,
    source_platform: Optional[str] = None,
    limit: int = 50,
    agent: Agent = Depends(get_current_agent),
    db: Session = Depends(get_db),
):
    items = material_library_service.list_material_items(
        db,
        status=status,
        content_type=content_type,
        source_platform=source_platform,
        limit=limit,
    )
    return [material_library_service.material_to_dict(item) for item in items]


@router.post("", response_model=MaterialResponse, summary="写入素材")
async def create_material(
    req: MaterialCreateRequest,
    _: bool = Depends(verify_admin),
    db: Session = Depends(get_db),
):
    payload = req.model_dump()
    if payload.get("selection_score") is None or payload.get("status") is None:
        payload = material_library_service.refine_material_payload(payload, content_type=payload.get("content_type") or "短剧")
    item = material_library_service.create_material_item(db, payload)
    return material_library_service.material_to_dict(item)


@router.put("/{item_id}/status", response_model=MaterialResponse, summary="更新素材状态")
async def update_material_status(
    item_id: str,
    req: MaterialStatusRequest,
    _: bool = Depends(verify_admin),
    db: Session = Depends(get_db),
):
    try:
        item = material_library_service.update_material_status(db, item_id, req.status)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return material_library_service.material_to_dict(item)
