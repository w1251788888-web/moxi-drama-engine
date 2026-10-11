"""LLM 探活 endpoint。

给前端在打开 LLM-依赖的页面（分镜、剧本生成、自动修复等）时调用，
快速判断 LLM 是否真的连通，避免用户点击后死等几十秒才知道连不上。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends

from app.auth.dependencies import ProjectAccessActor, verify_project_actor
from app.services.text_generation_service import check_llm_reachable

router = APIRouter()


@router.get(
    "/admin/ai/health",
    summary="探活 LLM 是否连通（5 秒内返回）",
)
async def ai_health(_: ProjectAccessActor = Depends(verify_project_actor)):
    """快速探活配置中的 text_generation 是否真能调通。

    返回 {ok, detail, latency_ms}：
    - ok=True：LLM 已连通，前端可以放心调 LLM 接口
    - ok=False：未连通，前端应禁用 LLM 按钮 + 顶部红字显示 detail

    这是普通用户工作台也会用到的“按钮可用性探活”，不能只限管理员。
    """
    return check_llm_reachable(timeout_seconds=5.0)
