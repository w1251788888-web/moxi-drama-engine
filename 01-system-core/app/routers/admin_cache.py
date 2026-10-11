"""
管理端缓存状态路由。
"""
from fastapi import APIRouter, Depends, Query

from app.auth.dependencies import verify_admin
from app.services import cache_service


router = APIRouter(prefix="/admin/cache", tags=["Admin Cache"])


@router.get("/status", summary="查看缓存后端状态")
async def cache_status(_: bool = Depends(verify_admin)):
    return cache_service.get_cache_status()


@router.post("/clear", summary="清理缓存")
async def clear_cache(
    prefix: str | None = Query(None, description="可选缓存 key 前缀，不含命名空间"),
    _: bool = Depends(verify_admin),
):
    result = cache_service.clear_cache(prefix=prefix)
    return {
        **result,
        "status": cache_service.get_cache_status(),
    }
