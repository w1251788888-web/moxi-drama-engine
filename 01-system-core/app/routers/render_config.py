"""渲染服务商配置 + 占位渲染接口

接口：
- GET    /api/render-config/catalog               # 内置 9 个服务商目录
- GET    /api/render-config/list                  # 当前所有配置（脱敏）
- PUT    /api/render-config/upsert                # 保存某个服务商配置
- POST   /api/render-config/test/{name}           # 连通测试
- POST   /api/render-config/render-image          # 占位：返回 501 + 提示
- POST   /api/render-config/render-video          # 占位：返回 501 + 提示
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth.dependencies import verify_admin
from app.database import get_db
from app.schemas.character_visual import RenderProviderUpsert
from app.services import render_provider_service as rp_svc

router = APIRouter(prefix="/render-config", tags=["Render Provider Config"])


@router.get("/catalog", summary="内置服务商目录")
async def catalog(_: bool = Depends(verify_admin)):
    return {"items": rp_svc.get_catalog()}


@router.get("/list", summary="当前所有配置（API Key 脱敏）")
async def list_all(
    db: Session = Depends(get_db), _: bool = Depends(verify_admin),
):
    return {"items": rp_svc.list_configs(db, redact_key=True)}


@router.put("/upsert", summary="保存某个服务商配置")
async def upsert(
    req: RenderProviderUpsert,
    db: Session = Depends(get_db),
    _: bool = Depends(verify_admin),
):
    return rp_svc.upsert_config(db, req)


@router.post("/test/{name}", summary="连通测试（不真渲染）")
async def test(
    name: str,
    db: Session = Depends(get_db),
    _: bool = Depends(verify_admin),
):
    return await rp_svc.test_connectivity(db, name)


# ─────────────────────────────────────────────────────────
# 占位渲染接口
# ─────────────────────────────────────────────────────────


class RenderRequest(BaseModel):
    provider: str
    prompt: str
    negative: str = ""
    duration_sec: float = 3.0
    aspect_ratio: str = "9:16"


@router.post("/render-image", summary="生成图片（二期占位）")
async def render_image(
    req: RenderRequest,
    db: Session = Depends(get_db),
    _: bool = Depends(verify_admin),
):
    try:
        return await rp_svc.generate_image(
            db, provider=req.provider, prompt=req.prompt, negative=req.negative,
            aspect_ratio=req.aspect_ratio,
        )
    except rp_svc.RenderNotImplementedError as exc:
        raise HTTPException(status_code=501, detail=str(exc))


@router.post("/render-video", summary="生成视频（二期占位）")
async def render_video(
    req: RenderRequest,
    db: Session = Depends(get_db),
    _: bool = Depends(verify_admin),
):
    try:
        return await rp_svc.generate_video(
            db, provider=req.provider, prompt=req.prompt, negative=req.negative,
            duration_sec=req.duration_sec, aspect_ratio=req.aspect_ratio,
        )
    except rp_svc.RenderNotImplementedError as exc:
        raise HTTPException(status_code=501, detail=str(exc))
