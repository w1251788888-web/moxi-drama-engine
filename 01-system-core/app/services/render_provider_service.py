"""渲染服务商抽象层（二期占位）

一期只做：
1. 配置存储（CRUD）
2. 连通测试（仅 HTTP HEAD/简单请求，不真渲染）
3. 标准化接口约定 generate_image / generate_video，返回 NotImplementedError 说明

二期对接真实平台时，每个 provider 在 PROVIDERS 字典里注册一个 class 实现即可。
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime
from typing import Optional

import httpx
from sqlalchemy.orm import Session

from app.models.storyboard import RenderProviderConfig
from app.schemas.character_visual import RenderProviderUpsert

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────
# 服务商目录（一期固定 9 个，二期按需扩）
# ─────────────────────────────────────────────────────────


PROVIDERS_CATALOG = [
    # name, kind, default_endpoint, doc_hint
    ("jimeng_image",         "image", "https://visual.volcengineapi.com",       "字节即梦 文生图（火山引擎 visual）"),
    ("jimeng_video",         "video", "https://visual.volcengineapi.com",       "字节即梦 文生视频"),
    ("kling_image",          "image", "https://api.klingai.com",                "可灵 图像"),
    ("kling_video",          "video", "https://api.klingai.com",                "可灵 视频"),
    ("hailuo_video",         "video", "https://api.minimaxi.com",               "MiniMax 海螺 视频"),
    ("sora_video",           "video", "https://api.openai.com",                 "OpenAI Sora 视频（待开放）"),
    ("wan_video",            "video", "https://dashscope.aliyuncs.com",          "阿里 通义万相 Wan2.x 视频"),
    ("storydiffusion_local", "local", "http://localhost:7860",                  "StoryDiffusion 本地 Gradio"),
    ("storymem_local",       "local", "http://localhost:7861",                  "StoryMem 本地推理服务"),
]


def get_catalog() -> list[dict]:
    """返回所有可注册的服务商（前端配置页用）"""
    return [
        {"name": name, "provider_kind": kind, "default_endpoint": ep, "doc_hint": hint}
        for name, kind, ep, hint in PROVIDERS_CATALOG
    ]


# ─────────────────────────────────────────────────────────
# CRUD
# ─────────────────────────────────────────────────────────


def list_configs(db: Session, *, redact_key: bool = True) -> list[dict]:
    rows = db.query(RenderProviderConfig).all()
    by_name = {r.name: r for r in rows}
    out = []
    for c in get_catalog():
        existing = by_name.get(c["name"])
        if existing:
            d = existing.to_dict(redact_key=redact_key)
            d["doc_hint"] = c["doc_hint"]
            d["default_endpoint"] = c["default_endpoint"]
            out.append(d)
        else:
            out.append({
                "name": c["name"],
                "provider_kind": c["provider_kind"],
                "api_key": "",
                "endpoint": c["default_endpoint"],
                "enabled": False,
                "extra": {},
                "doc_hint": c["doc_hint"],
                "default_endpoint": c["default_endpoint"],
                "last_test_at": None,
                "last_test_ok": False,
                "last_test_msg": "",
                "updated_at": None,
            })
    return out


def upsert_config(db: Session, payload: RenderProviderUpsert) -> dict:
    row = db.query(RenderProviderConfig).filter(RenderProviderConfig.name == payload.name).first()
    is_new = row is None
    if is_new:
        row = RenderProviderConfig(name=payload.name)
        db.add(row)
    row.provider_kind = payload.provider_kind or row.provider_kind or "image"
    if payload.api_key and not payload.api_key.startswith("****"):
        # 前端回填脱敏字符串时不覆盖
        row.api_key = payload.api_key
    row.endpoint = payload.endpoint or row.endpoint or ""
    row.enabled = bool(payload.enabled)
    row.extra_json = json.dumps(payload.extra or {}, ensure_ascii=False)
    db.commit()
    db.refresh(row)
    return row.to_dict()


# ─────────────────────────────────────────────────────────
# 连通测试（不真渲染）
# ─────────────────────────────────────────────────────────


async def test_connectivity(db: Session, name: str) -> dict:
    row = db.query(RenderProviderConfig).filter(RenderProviderConfig.name == name).first()
    if not row:
        return {"ok": False, "msg": "未配置该服务商"}
    if not row.endpoint:
        return {"ok": False, "msg": "endpoint 未填写"}
    if not row.api_key:
        return {"ok": False, "msg": "api_key 未填写"}

    started = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            # 仅 HEAD/GET 主页，不调具体业务接口
            url = row.endpoint
            try:
                resp = await client.head(url)
            except httpx.RequestError:
                resp = await client.get(url)
            ok = resp.status_code < 500
            msg = f"HTTP {resp.status_code}"
    except Exception as exc:
        ok = False
        msg = str(exc)[:200]

    row.last_test_at = datetime.utcnow()
    row.last_test_ok = ok
    row.last_test_msg = msg
    db.commit()
    return {
        "ok": ok,
        "msg": msg,
        "latency_ms": int((time.perf_counter() - started) * 1000),
    }


# ─────────────────────────────────────────────────────────
# 渲染接口（一期占位，明确抛 NotImplementedError）
# ─────────────────────────────────────────────────────────


class RenderNotImplementedError(Exception):
    """二期才接：明确告诉前端"功能尚未上线"，前端展示占位"""
    pass


async def generate_image(
    db: Session, *, provider: str, prompt: str, negative: str = "", **kwargs
) -> dict:
    """二期实现。一期只做返回占位。"""
    cfg = db.query(RenderProviderConfig).filter(RenderProviderConfig.name == provider).first()
    if not cfg or not cfg.enabled:
        raise RenderNotImplementedError(f"{provider} 未启用或未配置")
    raise RenderNotImplementedError(
        f"{provider} 图像生成接口将在二期接入；目前可在前端复制提示词手动喂给该平台。"
    )


async def generate_video(
    db: Session, *, provider: str, prompt: str, negative: str = "", **kwargs
) -> dict:
    """二期实现。一期占位。"""
    cfg = db.query(RenderProviderConfig).filter(RenderProviderConfig.name == provider).first()
    if not cfg or not cfg.enabled:
        raise RenderNotImplementedError(f"{provider} 未启用或未配置")
    raise RenderNotImplementedError(
        f"{provider} 视频生成接口将在二期接入；目前可在前端复制提示词手动喂给该平台。"
    )
