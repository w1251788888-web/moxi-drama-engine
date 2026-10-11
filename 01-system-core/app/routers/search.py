"""
全文检索路由。
"""
from __future__ import annotations

import os
from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth.dependencies import verify_admin
from app.config import get_config
from app.database import get_db
from app.services import full_text_search_service, knowledge_chunk_service, semantic_search_service


router = APIRouter(prefix="/search", tags=["Search"])

LOCAL_SEARCH_DISABLED_BACKEND = "local_search_disabled"
LOCAL_CHUNKS_DISABLED_BACKEND = "local_knowledge_chunks_disabled"
LOCAL_DISABLED_MESSAGE = "本地旧 RAG/搜索索引已禁用，请使用 Dify/DeFi RAG 知识库。"


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _nested_get(data: dict[str, Any], *keys: str) -> Any:
    current: Any = data
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _legacy_local_search_enabled() -> bool:
    env = os.getenv("MOXI_ENABLE_LOCAL_SEARCH")
    if env is not None:
        return _truthy(env)
    try:
        cfg = get_config() or {}
    except Exception:
        cfg = {}
    value = _nested_get(cfg, "search", "local_index", "enabled")
    return _truthy(value) if value is not None else False


def _legacy_knowledge_chunks_enabled() -> bool:
    env = os.getenv("MOXI_ENABLE_LOCAL_KNOWLEDGE_CHUNKS")
    if env is not None:
        return _truthy(env)
    try:
        cfg = get_config() or {}
    except Exception:
        cfg = {}
    value = _nested_get(cfg, "rag", "knowledge_chunks", "enabled")
    return _truthy(value) if value is not None else False


def _disabled_search_response(backend: str) -> dict[str, Any]:
    return {
        "items": [],
        "count": 0,
        "indexed_count": 0,
        "backend": backend,
        "rebuilt": False,
        "semantic_degraded": False,
        "semantic_error": LOCAL_DISABLED_MESSAGE,
    }


def _disabled_rebuild_response(backend: str) -> dict[str, Any]:
    return {
        "available": False,
        "backend": backend,
        "indexed_count": 0,
        "doc_type_counts": {},
        "collection": "",
        "persist_path": "",
        "degraded": True,
        "error": LOCAL_DISABLED_MESSAGE,
    }


def _disabled_chunk_search_response() -> dict[str, Any]:
    return {
        "items": [],
        "count": 0,
        "chunk_count": 0,
        "backend": LOCAL_CHUNKS_DISABLED_BACKEND,
        "rebuilt": False,
    }


def _disabled_chunk_context_response(max_chars: int) -> dict[str, Any]:
    return {
        "text": "",
        "items": [],
        "cards": [],
        "count": 0,
        "chunk_count": 0,
        "backend": LOCAL_CHUNKS_DISABLED_BACKEND,
        "max_chars": max_chars,
    }


def _disabled_chunk_rebuild_response() -> dict[str, Any]:
    return {
        "available": False,
        "deleted_count": 0,
        "source_count": 0,
        "chunk_count": 0,
        "doc_type_counts": {},
        "chunk_type_counts": {},
        "chunk_size": 0,
        "chunk_overlap": 0,
        "backends": {},
    }


class SearchResult(BaseModel):
    doc_type: str
    source_id: str
    title: str
    title_snippet: str = ""
    content_snippet: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)
    updated_at: str = ""
    score: float = 0.0
    backend: str = ""


class SearchResponse(BaseModel):
    items: list[SearchResult]
    count: int
    indexed_count: int
    backend: str
    rebuilt: bool = False
    semantic_degraded: bool = False
    semantic_error: str = ""


class SearchRebuildResponse(BaseModel):
    available: bool
    backend: str = ""
    indexed_count: int
    doc_type_counts: dict[str, int] = Field(default_factory=dict)
    collection: str = ""
    persist_path: str = ""
    degraded: bool = False
    error: str = ""


class MaterialIngestionAuditSample(BaseModel):
    path: str
    extension: str
    status: str
    size_bytes: int = 0
    oversized: bool = False
    ocr_candidate: bool = False
    requires_review: bool = False


class MaterialIngestionAuditResponse(BaseModel):
    available: bool
    root: str
    ocr_enabled: bool
    ocr_env: str
    ocr_langs: str
    supported_extensions: list[str] = Field(default_factory=list)
    max_indexable_file_bytes: int
    max_extracted_file_chars: int
    max_pdf_pages: int
    max_ocr_pdf_pages: int
    max_ocr_image_pixels: int
    total_files: int
    supported_files: int
    oversized_files: int
    ocr_candidate_files: int
    review_required_files: int
    status_counts: dict[str, int] = Field(default_factory=dict)
    extension_counts: dict[str, int] = Field(default_factory=dict)
    samples: list[MaterialIngestionAuditSample] = Field(default_factory=list)
    error: str = ""


class KnowledgeChunkResult(BaseModel):
    id: str
    source_type: str
    source_id: str
    source_path: str = ""
    chunk_index: int
    title: str = ""
    content: str = ""
    content_chars: int = 0
    chunk_hash: str = ""
    chunker: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)
    updated_at: str = ""


class KnowledgeChunkSearchResponse(BaseModel):
    items: list[KnowledgeChunkResult]
    count: int
    chunk_count: int
    backend: str
    rebuilt: bool = False


class RagContextCard(BaseModel):
    context_type: str
    title: str
    content: str
    authority_level: int
    episode_no: int = 0
    tags: list[str] = Field(default_factory=list)
    source: str = ""


class KnowledgeChunkContextResponse(BaseModel):
    text: str
    items: list[KnowledgeChunkResult]
    cards: list[RagContextCard] = Field(default_factory=list)
    count: int
    chunk_count: int
    backend: str
    max_chars: int


class KnowledgeChunkStatusResponse(BaseModel):
    available: bool
    chunk_count: int
    chunk_type_counts: dict[str, int] = Field(default_factory=dict)
    status_counts: dict[str, int] = Field(default_factory=dict)
    backend: str = ""


class KnowledgeChunkRebuildResponse(BaseModel):
    available: bool
    deleted_count: int = 0
    source_count: int = 0
    chunk_count: int = 0
    doc_type_counts: dict[str, int] = Field(default_factory=dict)
    chunk_type_counts: dict[str, int] = Field(default_factory=dict)
    chunk_size: int = 0
    chunk_overlap: int = 0
    backends: dict[str, int] = Field(default_factory=dict)


@router.get("", response_model=SearchResponse, summary="全文检索规则、素材、项目和技能文档")
async def search(
    q: str = Query(..., min_length=1, description="搜索关键词"),
    types: str | None = Query(None, description="逗号分隔: rule,material,project,skill"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    auto_rebuild: bool = Query(True, description="索引为空时自动重建"),
    _: bool = Depends(verify_admin),
    db: Session = Depends(get_db),
):
    if not _legacy_local_search_enabled():
        return _disabled_search_response(LOCAL_SEARCH_DISABLED_BACKEND)
    doc_types = [item.strip() for item in (types or "").split(",") if item.strip()]
    return full_text_search_service.search_documents(
        db,
        query=q,
        doc_types=doc_types,
        limit=limit,
        offset=offset,
        auto_rebuild=auto_rebuild,
    )


@router.get("/status", response_model=SearchRebuildResponse, summary="查看全文索引状态")
async def search_status(
    _: bool = Depends(verify_admin),
    db: Session = Depends(get_db),
):
    if not _legacy_local_search_enabled():
        return _disabled_rebuild_response(LOCAL_SEARCH_DISABLED_BACKEND)
    return full_text_search_service.get_search_status(db)


@router.get("/semantic", response_model=SearchResponse, summary="语义检索规则、素材、项目和技能文档")
async def semantic_search(
    q: str = Query(..., min_length=1, description="搜索关键词"),
    types: str | None = Query(None, description="逗号分隔: rule,material,project,skill"),
    limit: int = Query(20, ge=1, le=100),
    auto_rebuild: bool = Query(True, description="语义索引为空时自动重建"),
    _: bool = Depends(verify_admin),
    db: Session = Depends(get_db),
):
    if not _legacy_local_search_enabled():
        return _disabled_search_response(f"semantic_{LOCAL_SEARCH_DISABLED_BACKEND}")
    doc_types = [item.strip() for item in (types or "").split(",") if item.strip()]
    return semantic_search_service.semantic_search_documents(
        db,
        query=q,
        doc_types=doc_types,
        limit=limit,
        auto_rebuild=auto_rebuild,
    )


@router.get("/semantic/status", response_model=SearchRebuildResponse, summary="查看语义检索状态")
async def semantic_search_status(
    _: bool = Depends(verify_admin),
):
    if not _legacy_local_search_enabled():
        return _disabled_rebuild_response(f"semantic_{LOCAL_SEARCH_DISABLED_BACKEND}")
    return semantic_search_service.get_semantic_status()


@router.post("/semantic/rebuild", response_model=SearchRebuildResponse, summary="重建语义检索索引")
async def rebuild_semantic_search_index(
    _: bool = Depends(verify_admin),
    db: Session = Depends(get_db),
):
    if not _legacy_local_search_enabled():
        return _disabled_rebuild_response(f"semantic_{LOCAL_SEARCH_DISABLED_BACKEND}")
    return semantic_search_service.rebuild_semantic_index(db)


@router.post("/rebuild", response_model=SearchRebuildResponse, summary="重建全文检索索引")
async def rebuild_search_index(
    _: bool = Depends(verify_admin),
    db: Session = Depends(get_db),
):
    if not _legacy_local_search_enabled():
        return _disabled_rebuild_response(LOCAL_SEARCH_DISABLED_BACKEND)
    return full_text_search_service.rebuild_search_index(db)


@router.get("/material-ingestion/audit", response_model=MaterialIngestionAuditResponse, summary="审计素材库摄取边界")
async def material_ingestion_audit(
    limit: int = Query(200, ge=1, le=1000),
    _: bool = Depends(verify_admin),
):
    return full_text_search_service.get_material_ingestion_audit(limit=limit)


@router.get("/chunks/status", response_model=KnowledgeChunkStatusResponse, summary="查看知识分块状态")
async def knowledge_chunk_status(
    _: bool = Depends(verify_admin),
    db: Session = Depends(get_db),
):
    if not _legacy_knowledge_chunks_enabled():
        return {
            "available": False,
            "chunk_count": 0,
            "chunk_type_counts": {},
            "status_counts": {},
            "backend": LOCAL_CHUNKS_DISABLED_BACKEND,
        }
    return knowledge_chunk_service.get_knowledge_chunk_status(db)


@router.get("/chunks", response_model=KnowledgeChunkSearchResponse, summary="检索持久化知识分块")
async def knowledge_chunk_search(
    q: str = Query(..., min_length=1, description="搜索关键词"),
    types: str | None = Query(None, description="逗号分隔: rule,material,project,skill"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    auto_rebuild: bool = Query(False, description="分块为空时自动重建"),
    _: bool = Depends(verify_admin),
    db: Session = Depends(get_db),
):
    if not _legacy_knowledge_chunks_enabled():
        return _disabled_chunk_search_response()
    doc_types = [item.strip() for item in (types or "").split(",") if item.strip()]
    return knowledge_chunk_service.search_knowledge_chunk_documents(
        db,
        query=q,
        doc_types=doc_types,
        limit=limit,
        offset=offset,
        auto_rebuild=auto_rebuild,
    )


@router.get("/chunks/context", response_model=KnowledgeChunkContextResponse, summary="生成可注入提示词的知识分块上下文")
async def knowledge_chunk_context(
    q: str = Query(..., min_length=1, description="搜索关键词"),
    types: str | None = Query(None, description="逗号分隔: rule,material,project,skill"),
    limit: int = Query(6, ge=1, le=20),
    max_chars: int = Query(4000, ge=500, le=12000),
    header: str = Query("# 本地知识分块召回"),
    auto_rebuild: bool = Query(False, description="分块为空时自动重建"),
    _: bool = Depends(verify_admin),
    db: Session = Depends(get_db),
):
    if not _legacy_knowledge_chunks_enabled():
        return _disabled_chunk_context_response(max_chars)
    doc_types = [item.strip() for item in (types or "").split(",") if item.strip()]
    return knowledge_chunk_service.build_knowledge_chunk_context(
        db,
        query=q,
        doc_types=doc_types,
        limit=limit,
        max_chars=max_chars,
        header=header,
        auto_rebuild=auto_rebuild,
    )


@router.post("/chunks/rebuild", response_model=KnowledgeChunkRebuildResponse, summary="重建持久化知识分块")
async def rebuild_knowledge_chunks(
    types: str | None = Query(None, description="逗号分隔: rule,material,project,skill"),
    chunk_size: int = Query(1200, ge=120, le=6000),
    chunk_overlap: int = Query(120, ge=0, le=1000),
    _: bool = Depends(verify_admin),
    db: Session = Depends(get_db),
):
    if not _legacy_knowledge_chunks_enabled():
        return _disabled_chunk_rebuild_response()
    doc_types = [item.strip() for item in (types or "").split(",") if item.strip()]
    return knowledge_chunk_service.rebuild_knowledge_chunks(
        db,
        doc_types=doc_types,
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
    )
