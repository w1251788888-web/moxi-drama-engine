"""Durable knowledge chunking service.

This service builds on the unified document source used by FTS5/semantic search.
LangChain text splitters are optional; when they are unavailable, a deterministic
built-in splitter keeps the pipeline usable.
"""
from __future__ import annotations

import hashlib
import json
import re
import warnings
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models.knowledge_chunk import KnowledgeChunk
from app.services import full_text_search_service


DEFAULT_CHUNK_SIZE = 1200
DEFAULT_CHUNK_OVERLAP = 120
DEFAULT_CONTEXT_MAX_CHARS = 4000
MIN_CHUNK_SIZE = 120
MAX_CHUNK_SIZE = 6000
MAX_CHUNK_OVERLAP = 1000


@dataclass(frozen=True)
class ChunkingOptions:
    chunk_size: int = DEFAULT_CHUNK_SIZE
    chunk_overlap: int = DEFAULT_CHUNK_OVERLAP


def normalize_chunking_options(
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    chunk_overlap: int = DEFAULT_CHUNK_OVERLAP,
) -> ChunkingOptions:
    size = _clamp_int(chunk_size, MIN_CHUNK_SIZE, MAX_CHUNK_SIZE, DEFAULT_CHUNK_SIZE)
    overlap = _clamp_int(chunk_overlap, 0, min(MAX_CHUNK_OVERLAP, size // 2), min(DEFAULT_CHUNK_OVERLAP, size // 2))
    return ChunkingOptions(chunk_size=size, chunk_overlap=overlap)


def get_chunking_backend() -> str:
    """Return the preferred chunking backend without importing it globally."""
    try:
        _load_langchain_splitter()
        return "langchain"
    except Exception:
        return "builtin"


def split_text(
    text: str,
    *,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    chunk_overlap: int = DEFAULT_CHUNK_OVERLAP,
) -> tuple[list[str], str]:
    """Split text into stable chunks and return (chunks, backend)."""
    options = normalize_chunking_options(chunk_size, chunk_overlap)
    normalized = _normalize_text(text)
    if not normalized:
        return [], get_chunking_backend()

    splitter = None
    try:
        splitter_cls = _load_langchain_splitter()
        splitter = splitter_cls(
            chunk_size=options.chunk_size,
            chunk_overlap=options.chunk_overlap,
            separators=["\n\n", "\n", "。", "；", "，", " ", ""],
        )
    except Exception:
        splitter = None

    if splitter is not None:
        chunks = [_normalize_text(item) for item in splitter.split_text(normalized)]
        chunks = [item for item in chunks if item]
        if chunks:
            return chunks, "langchain"

    return _builtin_split(normalized, options), "builtin"


def rebuild_knowledge_chunks(
    db: Session,
    *,
    doc_types: list[str] | None = None,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    chunk_overlap: int = DEFAULT_CHUNK_OVERLAP,
) -> dict[str, Any]:
    """Rebuild durable chunks from the unified searchable document source."""
    options = normalize_chunking_options(chunk_size, chunk_overlap)
    normalized_types = _normalize_doc_types(doc_types)
    query = db.query(KnowledgeChunk)
    if normalized_types:
        query = query.filter(KnowledgeChunk.source_type.in_(normalized_types))
    deleted = query.delete(synchronize_session=False)

    rows: list[KnowledgeChunk] = []
    source_count = 0
    doc_type_counts: dict[str, int] = {}
    chunk_type_counts: dict[str, int] = {}
    backends: dict[str, int] = {}

    for doc in full_text_search_service.iter_indexable_documents(db):
        doc_type = str(doc.get("doc_type") or "").strip()
        if normalized_types and doc_type not in normalized_types:
            continue
        source_count += 1
        doc_type_counts[doc_type] = doc_type_counts.get(doc_type, 0) + 1
        chunks, backend = split_text(
            "\n\n".join(part for part in (doc.get("title", ""), doc.get("content", "")) if part),
            chunk_size=options.chunk_size,
            chunk_overlap=options.chunk_overlap,
        )
        backends[backend] = backends.get(backend, 0) + len(chunks)
        metadata = _json_loads(doc.get("metadata_json"), {})
        source_path = _source_path(metadata)
        for index, chunk in enumerate(chunks):
            row = _build_chunk_row(
                doc=doc,
                metadata=metadata,
                source_path=source_path,
                chunk_index=index,
                chunk=chunk,
                chunker=backend,
                options=options,
            )
            rows.append(row)
            chunk_type_counts[doc_type] = chunk_type_counts.get(doc_type, 0) + 1

    if rows:
        db.add_all(rows)
    db.commit()
    return {
        "available": True,
        "deleted_count": int(deleted or 0),
        "source_count": source_count,
        "chunk_count": len(rows),
        "doc_type_counts": doc_type_counts,
        "chunk_type_counts": chunk_type_counts,
        "chunk_size": options.chunk_size,
        "chunk_overlap": options.chunk_overlap,
        "backends": backends,
    }


def search_knowledge_chunks(
    db: Session,
    query: str,
    *,
    doc_types: list[str] | None = None,
    limit: int = 20,
    offset: int = 0,
    auto_rebuild: bool = False,
) -> list[KnowledgeChunk]:
    """Small LIKE search helper for diagnostics and future prompt assembly."""
    normalized = str(query or "").strip()
    if not normalized:
        return []
    normalized_types = _normalize_doc_types(doc_types)
    limit_value = _clamp_int(limit, 1, 100, 20)
    offset_value = max(0, int(offset or 0))

    if auto_rebuild and db.query(KnowledgeChunk.id).limit(1).first() is None:
        rebuild_knowledge_chunks(db, doc_types=normalized_types or None)

    rows = db.query(KnowledgeChunk).filter(KnowledgeChunk.status == "active")
    if normalized_types:
        rows = rows.filter(KnowledgeChunk.source_type.in_(normalized_types))
    return (
        rows.filter(or_(
            KnowledgeChunk.title.like(f"%{normalized}%"),
            KnowledgeChunk.content.like(f"%{normalized}%"),
            KnowledgeChunk.source_path.like(f"%{normalized}%"),
        ))
        .order_by(KnowledgeChunk.updated_at.desc(), KnowledgeChunk.source_type.asc(), KnowledgeChunk.chunk_index.asc())
        .offset(offset_value)
        .limit(limit_value)
        .all()
    )


def search_knowledge_chunk_documents(
    db: Session,
    query: str,
    *,
    doc_types: list[str] | None = None,
    limit: int = 20,
    offset: int = 0,
    auto_rebuild: bool = False,
) -> dict[str, Any]:
    """Return serialized chunk search results for API and diagnostics."""
    rows = search_knowledge_chunks(
        db,
        query,
        doc_types=doc_types,
        limit=limit,
        offset=offset,
        auto_rebuild=auto_rebuild,
    )
    return {
        "items": [serialize_knowledge_chunk(row) for row in rows],
        "count": len(rows),
        "chunk_count": db.query(KnowledgeChunk).count(),
        "backend": "knowledge_chunks_like",
        "rebuilt": bool(auto_rebuild and rows),
    }


def build_knowledge_chunk_context(
    db: Session,
    query: str,
    *,
    doc_types: list[str] | None = None,
    limit: int = 6,
    max_chars: int = DEFAULT_CONTEXT_MAX_CHARS,
    header: str = "# 本地知识分块召回",
    auto_rebuild: bool = False,
) -> dict[str, Any]:
    """Build a compact, source-cited context block for future prompt assembly."""
    rows = search_knowledge_chunks(
        db,
        query,
        doc_types=doc_types,
        limit=limit,
        auto_rebuild=auto_rebuild,
    )
    text = format_knowledge_chunks_for_prompt(rows, query=query, header=header, max_chars=max_chars)
    return {
        "text": text,
        "items": [serialize_knowledge_chunk(row) for row in rows],
        "cards": knowledge_chunks_to_rag_cards(rows),
        "count": len(rows),
        "chunk_count": db.query(KnowledgeChunk).count(),
        "backend": "knowledge_chunks_like",
        "max_chars": _clamp_int(max_chars, 500, 12000, DEFAULT_CONTEXT_MAX_CHARS),
    }


def build_knowledge_chunk_context_pack(
    db: Session,
    query: str,
    *,
    doc_types: list[str] | None = None,
    limit: int = 6,
    authority: int = 72,
    auto_rebuild: bool = False,
) -> dict[str, Any]:
    """Return cards compatible with short-drama rag_context_pack.cards."""
    rows = search_knowledge_chunks(
        db,
        query,
        doc_types=doc_types,
        limit=limit,
        auto_rebuild=auto_rebuild,
    )
    return {
        "cards": knowledge_chunks_to_rag_cards(rows, authority=authority),
        "query": str(query or "").strip(),
        "count": len(rows),
        "chunk_count": db.query(KnowledgeChunk).count(),
        "backend": "knowledge_chunks_like",
    }


def knowledge_chunks_to_rag_cards(
    rows: list[KnowledgeChunk],
    *,
    authority: int = 72,
    episode_no: int = 0,
) -> list[dict[str, Any]]:
    """Convert durable chunks into the card shape accepted by short-drama RAG packs."""
    cards: list[dict[str, Any]] = []
    for row in rows:
        content = _truncate_for_prompt(row.content, 360)
        if not content:
            continue
        metadata = _json_loads(row.metadata_json, {})
        source = row.source_path or str(metadata.get("path") or metadata.get("workspace_path") or row.source_id)
        tags = ["local_knowledge", str(row.source_type or "unknown")]
        skill_name = metadata.get("skill_name") if isinstance(metadata, dict) else None
        if skill_name:
            tags.append(str(skill_name))
        cards.append({
            "context_type": "local_knowledge_chunk",
            "title": _truncate_for_prompt(row.title or source or row.source_id, 80),
            "content": content,
            "authority_level": int(authority),
            "episode_no": int(episode_no or 0),
            "tags": tags,
            "source": f"{source or row.source_id}#chunk-{row.chunk_index}",
        })
    return cards


def format_knowledge_chunks_for_prompt(
    rows: list[KnowledgeChunk],
    *,
    query: str = "",
    header: str = "# 本地知识分块召回",
    max_chars: int = DEFAULT_CONTEXT_MAX_CHARS,
) -> str:
    """Format chunks into a compact prompt block without changing generation flow."""
    if not rows:
        return ""

    budget = _clamp_int(max_chars, 500, 12000, DEFAULT_CONTEXT_MAX_CHARS)
    lines = [str(header or "# 本地知识分块召回").strip()]
    normalized_query = str(query or "").strip()
    if normalized_query:
        lines.append(f"检索词：{normalized_query}")
    lines.append("使用要求：仅把以下内容作为参考证据，不得覆盖项目已锁定设定。")

    used_chars = sum(len(line) for line in lines)
    for index, row in enumerate(rows, start=1):
        metadata = _json_loads(row.metadata_json, {})
        source = row.source_path or str(metadata.get("path") or metadata.get("workspace_path") or row.source_id)
        title = row.title or source or row.source_id
        content_budget = max(120, min(900, budget - used_chars - 180))
        if content_budget <= 120:
            break
        excerpt = _truncate_for_prompt(row.content, content_budget)
        block = (
            f"\n[{index}] {row.source_type}:{title}\n"
            f"来源：{source or row.source_id}#chunk-{row.chunk_index}\n"
            f"{excerpt}"
        )
        if used_chars + len(block) > budget:
            break
        lines.append(block)
        used_chars += len(block)
    return "\n".join(lines).strip()


def get_knowledge_chunk_status(db: Session) -> dict[str, Any]:
    rows = db.query(KnowledgeChunk.source_type, KnowledgeChunk.status).all()
    by_type: dict[str, int] = {}
    by_status: dict[str, int] = {}
    for source_type, status in rows:
        by_type[source_type] = by_type.get(source_type, 0) + 1
        by_status[status] = by_status.get(status, 0) + 1
    return {
        "available": True,
        "chunk_count": len(rows),
        "chunk_type_counts": by_type,
        "status_counts": by_status,
        "backend": get_chunking_backend(),
    }


def serialize_knowledge_chunk(row: KnowledgeChunk) -> dict[str, Any]:
    metadata = _json_loads(row.metadata_json, {})
    return {
        "id": row.id,
        "source_type": row.source_type,
        "source_id": row.source_id,
        "source_path": row.source_path or "",
        "chunk_index": row.chunk_index,
        "title": row.title or "",
        "content": row.content or "",
        "content_chars": int(row.content_chars or len(row.content or "")),
        "chunk_hash": row.chunk_hash or "",
        "chunker": row.chunker or "",
        "metadata": metadata if isinstance(metadata, dict) else {},
        "updated_at": row.updated_at.isoformat() if row.updated_at else "",
    }


def _build_chunk_row(
    *,
    doc: dict[str, str],
    metadata: dict[str, Any],
    source_path: str,
    chunk_index: int,
    chunk: str,
    chunker: str,
    options: ChunkingOptions,
) -> KnowledgeChunk:
    source_type = str(doc.get("doc_type") or "")
    source_id = str(doc.get("source_id") or "")
    chunk_hash = hashlib.sha256(chunk.encode("utf-8")).hexdigest()
    row_id = hashlib.sha256(f"{source_type}|{source_id}|{chunk_index}|{chunk_hash}".encode("utf-8")).hexdigest()[:36]
    row_metadata = {
        **metadata,
        "source_updated_at": doc.get("updated_at", ""),
        "chunk_size": options.chunk_size,
        "chunk_overlap": options.chunk_overlap,
        "chunk_hash": chunk_hash,
    }
    return KnowledgeChunk(
        id=row_id,
        source_type=source_type,
        source_id=source_id,
        source_path=source_path,
        chunk_index=chunk_index,
        chunk_hash=chunk_hash,
        title=str(doc.get("title") or ""),
        content=chunk,
        content_chars=len(chunk),
        chunker=chunker,
        metadata_json=json.dumps(row_metadata, ensure_ascii=False, default=str),
        status="active",
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )


def _builtin_split(text: str, options: ChunkingOptions) -> list[str]:
    if len(text) <= options.chunk_size:
        return [text]

    paragraphs = [item.strip() for item in re.split(r"\n{2,}", text) if item.strip()]
    raw_chunks: list[str] = []
    current = ""
    for paragraph in paragraphs:
        pieces = _split_long_piece(paragraph, options)
        for piece in pieces:
            candidate = f"{current}\n\n{piece}".strip() if current else piece
            if len(candidate) <= options.chunk_size:
                current = candidate
                continue
            if current:
                raw_chunks.append(current)
            current = piece
    if current:
        raw_chunks.append(current)

    if options.chunk_overlap <= 0 or len(raw_chunks) <= 1:
        return raw_chunks

    chunks = [raw_chunks[0]]
    for index in range(1, len(raw_chunks)):
        tail = _tail_text(raw_chunks[index - 1], options.chunk_overlap)
        chunk = f"{tail}\n\n{raw_chunks[index]}".strip() if tail else raw_chunks[index]
        chunks.append(chunk)
    return chunks


def _split_long_piece(text: str, options: ChunkingOptions) -> list[str]:
    if len(text) <= options.chunk_size:
        return [text]
    step = max(1, options.chunk_size - options.chunk_overlap)
    pieces = []
    for start in range(0, len(text), step):
        piece = text[start:start + options.chunk_size].strip()
        if piece:
            pieces.append(piece)
        if start + options.chunk_size >= len(text):
            break
    return pieces


def _tail_text(text: str, size: int) -> str:
    if size <= 0:
        return ""
    return text[-size:].strip()


def _truncate_for_prompt(text: str, max_chars: int) -> str:
    normalized = _normalize_text(text)
    if len(normalized) <= max_chars:
        return normalized
    return normalized[:max(0, max_chars - 1)].rstrip() + "…"


def _load_langchain_splitter():
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore",
            message=r"Core Pydantic V1 functionality isn't compatible with Python 3\.14 or greater\.",
            category=UserWarning,
        )
        warnings.filterwarnings(
            "ignore",
            message=r"The pynvml package is deprecated\.",
            category=FutureWarning,
        )
        try:
            from langchain_text_splitters import RecursiveCharacterTextSplitter

            return RecursiveCharacterTextSplitter
        except Exception:
            from langchain.text_splitter import RecursiveCharacterTextSplitter

            return RecursiveCharacterTextSplitter


def _source_path(metadata: dict[str, Any]) -> str:
    if metadata.get("library") and metadata.get("path"):
        return f"{metadata.get('library')}/{metadata.get('path')}"
    return str(metadata.get("workspace_path") or metadata.get("path") or "")


def _normalize_text(text: str) -> str:
    value = str(text or "").replace("\r\n", "\n").replace("\r", "\n")
    value = re.sub(r"[ \t]+", " ", value)
    value = re.sub(r"\n{3,}", "\n\n", value)
    return value.strip()


def _normalize_doc_types(doc_types: list[str] | None) -> list[str]:
    allowed = full_text_search_service.ALLOWED_DOC_TYPES
    normalized: list[str] = []
    for item in doc_types or []:
        for part in str(item).split(","):
            doc_type = part.strip()
            if doc_type in allowed and doc_type not in normalized:
                normalized.append(doc_type)
    return normalized


def _json_loads(raw: str | None, default: Any) -> Any:
    if not raw:
        return default
    try:
        return json.loads(raw)
    except Exception:
        return default


def _clamp_int(value: int, minimum: int, maximum: int, default: int) -> int:
    try:
        parsed = int(value)
    except Exception:
        parsed = default
    return max(minimum, min(parsed, maximum))
