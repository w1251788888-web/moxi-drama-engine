"""协同编辑技术验证路由。"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.auth.dependencies import verify_admin
from app.services.yjs_collaboration_service import (
    build_yjs_collaboration_plan,
    get_yjs_collaboration_status,
)


router = APIRouter(prefix="/collaboration", tags=["Collaboration"])


class YjsStatusResponse(BaseModel):
    feature_id: str
    feature_label: str
    available: bool
    backend: str
    degraded: bool
    package_json: str
    dependencies: dict[str, str] = Field(default_factory=dict)
    missing_dependencies: list[str] = Field(default_factory=list)
    transport: str = ""
    fallback: str = ""
    error: str = ""


class YjsDocumentPlan(BaseModel):
    id: str
    label: str
    ydoc_key: str
    fallback_api: str
    conflict_policy: str


class YjsPresencePlan(BaseModel):
    enabled_when_available: bool
    fields: list[str] = Field(default_factory=list)
    fallback: str = ""


class YjsPlanResponse(YjsStatusResponse):
    entrypoint: str
    documents: list[YjsDocumentPlan] = Field(default_factory=list)
    presence: YjsPresencePlan
    acceptance_gates: list[str] = Field(default_factory=list)


@router.get("/yjs/status", response_model=YjsStatusResponse, summary="查看 Yjs 协同编辑能力状态")
async def yjs_status(_: bool = Depends(verify_admin)):
    return get_yjs_collaboration_status()


@router.get("/yjs/plan", response_model=YjsPlanResponse, summary="查看 Yjs 协同编辑接入计划")
async def yjs_plan(_: bool = Depends(verify_admin)):
    return build_yjs_collaboration_plan()
