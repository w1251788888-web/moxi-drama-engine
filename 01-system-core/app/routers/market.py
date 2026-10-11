"""
市场验证与题材推荐路由
"""
from __future__ import annotations

import asyncio
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth.dependencies import ProjectAccessActor, verify_admin, verify_project_actor
from app.database import get_db
from app.services import market_insight_service


router = APIRouter(prefix="/admin/market", tags=["Admin Market"])
user_router = APIRouter(prefix="/user/market", tags=["User Market"])


class MarketScanRequest(BaseModel):
    source_urls: Optional[list[str]] = Field(default=None, description="外部趋势数据源 URL 列表")
    payloads: Optional[list[dict[str, Any]]] = Field(default=None, description="直接提交的原始趋势数据")
    style_axis: Optional[str] = Field(default="mixed", description="male/female/mixed")
    top_k: int = Field(default=8, ge=1, le=20)


class StarterPackRequest(BaseModel):
    topic: dict[str, Any] = Field(..., description="推荐题材对象")
    style_axis: Optional[str] = Field(default=None, description="male/female/mixed")


@router.post("/scan", summary="扫描市场热题材")
async def scan_market(req: MarketScanRequest, _: bool = Depends(verify_admin), db: Session = Depends(get_db)):
    del db
    payloads = req.payloads or []
    result = market_insight_service.recommend_topics(
        payloads,
        source_urls=req.source_urls,
        focus_axis=req.style_axis,
        top_k=req.top_k,
    )
    return result


@router.post("/recommend", summary="推荐短剧题材")
async def recommend_market_topics(req: MarketScanRequest, _: bool = Depends(verify_admin), db: Session = Depends(get_db)):
    del db
    payloads = req.payloads or []
    result = market_insight_service.recommend_topics(
        payloads,
        source_urls=req.source_urls,
        focus_axis=req.style_axis,
        top_k=req.top_k,
    )
    return {
        "focus_axis": result["focus_axis"],
        "recommendations": result["recommendations"],
        "fetch_errors": result["fetch_errors"],
    }


@router.post("/starter-pack", summary="一键生成题材 starter pack")
async def generate_starter_pack(req: StarterPackRequest, _: bool = Depends(verify_admin)):
    if not isinstance(req.topic, dict):
        raise HTTPException(status_code=400, detail="topic 必须是对象")
    return market_insight_service.build_starter_pack(req.topic, style_axis=req.style_axis)


class AITopicsRequest(BaseModel):
    style_axis: Optional[str] = Field(default="mixed", description="male/female/mixed")
    keyword: Optional[str] = Field(default=None, description="搜索关键词，用于定向生成相关题材")
    count: int = Field(default=6, ge=1, le=20)


async def _generate_ai_topics_payload(req: AITopicsRequest) -> dict[str, Any]:
    """使用 AI 生成当前热门题材洞察和个性化推荐，供灵感实验室展示。"""
    from app.services.text_generation_service import generate_json, generation_enabled, TextGenerationError

    if not generation_enabled():
        raise HTTPException(status_code=503, detail="AI 生成服务未启用")

    style_map = {"male": "男频（男主视角、逆袭、权谋、修仙）", "female": "女频（女主视角、甜宠、虐恋、复仇）", "mixed": "男女频均衡覆盖"}
    style_desc = style_map.get(req.style_axis or "mixed", style_map["mixed"])

    system_prompt = """你是一位专业的短剧市场分析师，熟悉抖音、快手、微信视频号短剧平台的热门题材趋势和竞品格局。
请根据当前市场热度生成完整的短剧题材洞察数据。严格按 JSON 格式返回，不要包含任何代码块标记（```）。
所有数值字段必须是数字类型，不要加引号。"""

    keyword_hint = f"\n重点围绕关键词「{req.keyword}」展开，优先生成与此相关的题材，并在 searchSummary 中给出针对该关键词的市场分析。" if req.keyword else ""
    search_summary_hint = f'  "searchSummary": "针对「{req.keyword}」的市场分析（50字内，包含热度判断和空白机会）",' if req.keyword else '  "searchSummary": "",'
    user_prompt = f"""请生成 {req.count} 个热门短剧题材方向，风格偏向：{style_desc}。{keyword_hint}

严格按以下 JSON 格式返回完整数据（所有数值为整数，不带引号）：
{{
{search_summary_hint}
  "hotWords": [
    {{"word": "逆袭", "weight": 95}},
    {{"word": "重生", "weight": 88}}
  ],
  "trending": [
    {{
      "id": 1,
      "title": "题材名称（2-6字）",
      "heat": 90,
      "change": "+10%",
      "category": "male|female|mixed",
      "tags": ["标签1", "标签2", "标签3"],
      "platforms": ["抖音", "快手"],
      "vacancy": 65,
      "trendHistory": [78, 80, 82, 84, 86, 88, 90, 92]
    }}
  ],
  "recommended": [
    {{
      "id": 1,
      "title": "《推荐剧名示例》",
      "type": "题材类型",
      "score": 92,
      "reason": "推荐理由（20字内）",
      "novelty": 85,
      "competition": 35,
      "marketGap": 72,
      "platforms": {{"douyin": 60, "kuaishou": 25, "wechat": 15}}
    }}
  ],
  "cases": [
    {{
      "id": 1,
      "title": "《爆款案例标题》",
      "category": "题材类别",
      "views": "1.5亿",
      "hook": "核心钩子（10字内）",
      "structure": "结构公式",
      "nodes": [
        {{"label": "开局钩（3字）", "desc": "简述（8字内）", "type": "hook"}},
        {{"label": "升级（3字）", "desc": "简述（8字内）", "type": "escalation"}},
        {{"label": "高潮（3字）", "desc": "简述（8字内）", "type": "climax"}},
        {{"label": "结尾（3字）", "desc": "简述（8字内）", "type": "ending"}}
      ],
      "emotionCurve": [20, 45, 35, 65, 50, 78, 70, 90, 85, 75],
      "highlights": ["第X集爽点描述 ★★★★★", "第Y集爽点描述 ★★★★"]
    }}
  ],
  "inspirations": [
    {{"id": 1, "quadrant": "character", "type": "人物", "title": "灵感标题", "desc": "简短描述（15字内）", "heat": 88, "tags": ["标签1", "标签2"]}},
    {{"id": 2, "quadrant": "setting",   "type": "场景", "title": "灵感标题", "desc": "简短描述（15字内）", "heat": 82, "tags": ["标签1", "标签2"]}},
    {{"id": 3, "quadrant": "conflict",  "type": "冲突", "title": "灵感标题", "desc": "简短描述（15字内）", "heat": 90, "tags": ["标签1", "标签2"]}},
    {{"id": 4, "quadrant": "hook",      "type": "钩子", "title": "灵感标题", "desc": "简短描述（15字内）", "heat": 85, "tags": ["标签1", "标签2"]}}
  ]
}}

字段说明：
- hotWords：10-14个热词，weight 为热度权重 0-100
- trending：{req.count} 条，vacancy=市场空白度(0-100，越高越好)，trendHistory=8个历史热度值
- recommended：4条，competition=竞品指数(越低越好)，marketGap=市场空白度(越高越好)，platforms各平台占比之和=100
- cases：3条，nodes 4-5个节点，emotionCurve 必须是10个整数，highlights 3-4条
- inspirations：每个 quadrant(character/setting/conflict/hook)各至少1条，共 {max(req.count, 8)} 条（每象限2条）
    - 数据必须真实反映当前短剧市场趋势，不要生成虚假数字"""

    try:
        result = await asyncio.to_thread(
            generate_json,
            system_prompt,
            user_prompt,
            temperature=0.8,
            max_tokens=3000,
        )
    except TextGenerationError as exc:
        raise HTTPException(status_code=400, detail=f"AI 生成失败: {exc}")

    return result


@router.post("/ai-topics", summary="AI 生成热门题材与推荐（灵感实验室专用）")
async def ai_generate_topics(req: AITopicsRequest, _: bool = Depends(verify_admin)):
    return await _generate_ai_topics_payload(req)


@user_router.post("/ai-topics", summary="AI 生成热门题材与推荐（前台灵感实验室）")
async def user_ai_generate_topics(
    req: AITopicsRequest,
    _: ProjectAccessActor = Depends(verify_project_actor),
):
    return await _generate_ai_topics_payload(req)
