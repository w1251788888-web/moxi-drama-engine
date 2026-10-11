"""后续平台 API 接入状态。

红色占位能力已经从产品和 API 层收口；后续只在确定外部平台 API 后重新开放。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends

from app.auth.dependencies import verify_admin

router = APIRouter(prefix="/phase2", tags=["Phase 2 Status"])


@router.get("/status", summary="后续平台 API 接入状态")
async def phase2_status(_: bool = Depends(verify_admin)):
    """返回后续平台能力的收口策略，不再宣传或挂载红色占位功能。"""
    return {
        "policy": "platform_api_later",
        "items": [],
        "msg": "红色占位功能已从前台和 API 收口；后续只在确定平台 API 后重新接入。",
    }
