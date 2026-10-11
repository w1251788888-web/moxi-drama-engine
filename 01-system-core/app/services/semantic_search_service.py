"""
Chroma 语义检索服务。

Chroma 为可选依赖：可用时使用本地持久化 collection；不可用时自动回退到 FTS5。
"""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.config import config
from app.services import full_text_search_service


COLLECTION_NAME = "moxi_search_documents"
EMBEDDING_DIM = 128
DEFAULT_LIMIT = 20
MAX_LIMIT = 100


class LocalHashEmbeddingFunction:
    """轻量本地 embedding，避免技术验证阶段依赖外部模型下载。"""

    def __call__(self, input):  # Chroma embedding function protocol
        return [_hash_embedding(str(item or "")) for item in input]


def rebuild_semantic_index(db: Session) -> dict[str, Any]:
    """重建 Chroma 语义索引；Chroma 不可用时返回降级状态。"""
    client_result = _get_chroma_client()
    if not client_result["available"]:
        return {
            "available": False,
            "backend": "fts5_fallback",
            "indexed_count": 0,
            "collection": COLLECTION_NAME,
            "persist_path": client_result["persist_path"],
            "degraded": True,
            "error": client_result["error"],
        }

    documents = full_text_search_service.iter_indexable_documents(db)
    client = client_result["client"]
    try:
        try:
            client.delete_collection(COLLECTION_NAME)
        except Exception:
            pass
        collection = client.get_or_create_collection(
            name=COLLECTION_NAME,
            embedding_function=LocalHashEmbeddingFunction(),
        )
        if documents:
            collection.upsert(
                ids=[_doc_id(doc) for doc in documents],
                documents=[_doc_text(doc) for doc in documents],
                metadatas=[_chroma_metadata(doc) for doc in documents],
            )
        return {
            "available": True,
            "backend": "chroma",
            "indexed_count": len(documents),
            "doc_type_counts": _count_by_type(documents),
            "collection": COLLECTION_NAME,
            "persist_path": client_result["persist_path"],
            "degraded": False,
            "error": "",
        }
    except Exception as exc:
        return {
            "available": False,
            "backend": "fts5_fallback",
            "indexed_count": 0,
            "collection": COLLECTION_NAME,
            "persist_path": client_result["persist_path"],
            "degraded": True,
            "error": str(exc)[:300],
        }


def semantic_search_documents(
    db: Session,
    query: str,
    doc_types: list[str] | None = None,
    limit: int = DEFAULT_LIMIT,
    auto_rebuild: bool = True,
) -> dict[str, Any]:
    """语义检索；Chroma 不可用或无结果时自动回退 FTS5。"""
    normalized_query = (query or "").strip()
    if not normalized_query:
        return {
            "items": [],
            "count": 0,
            "indexed_count": get_semantic_status().get("indexed_count", 0),
            "backend": "empty_query",
            "rebuilt": False,
            "semantic_degraded": False,
            "semantic_error": "",
        }

    limit = _clamp_limit(limit)
    normalized_types = _normalize_doc_types(doc_types)
    client_result = _get_chroma_client()
    if not client_result["available"]:
        return _fts_fallback(db, normalized_query, normalized_types, limit, auto_rebuild, client_result["error"])

    collection = _get_collection(client_result["client"])
    indexed_count = _safe_collection_count(collection)
    rebuilt = False
    if auto_rebuild and indexed_count == 0:
        rebuild_result = rebuild_semantic_index(db)
        rebuilt = bool(rebuild_result.get("available"))
        collection = _get_collection(client_result["client"])
        indexed_count = int(rebuild_result.get("indexed_count") or 0)

    try:
        query_kwargs: dict[str, Any] = {
            "query_texts": [normalized_query],
            "n_results": limit,
            "include": ["documents", "metadatas", "distances"],
        }
        where = _doc_type_where(normalized_types)
        if where:
            query_kwargs["where"] = where
        raw = collection.query(**query_kwargs)
        items = _normalize_chroma_query_result(raw)
    except Exception as exc:
        return _fts_fallback(db, normalized_query, normalized_types, limit, auto_rebuild, str(exc)[:300])

    if not items:
        fallback = _fts_fallback(db, normalized_query, normalized_types, limit, auto_rebuild, "chroma returned no results")
        fallback["rebuilt"] = rebuilt or bool(fallback.get("rebuilt"))
        return fallback

    return {
        "items": items,
        "count": len(items),
        "indexed_count": indexed_count,
        "backend": "chroma",
        "rebuilt": rebuilt,
        "semantic_degraded": False,
        "semantic_error": "",
    }


def get_semantic_status() -> dict[str, Any]:
    """返回 Chroma 语义检索状态。"""
    client_result = _get_chroma_client()
    if not client_result["available"]:
        return {
            "available": False,
            "backend": "fts5_fallback",
            "indexed_count": 0,
            "collection": COLLECTION_NAME,
            "persist_path": client_result["persist_path"],
            "degraded": True,
            "error": client_result["error"],
        }
    collection = _get_collection(client_result["client"])
    return {
        "available": True,
        "backend": "chroma",
        "indexed_count": _safe_collection_count(collection),
        "collection": COLLECTION_NAME,
        "persist_path": client_result["persist_path"],
        "degraded": False,
        "error": "",
    }


def _get_chroma_client() -> dict[str, Any]:
    persist_path = _persist_path()
    try:
        import chromadb  # type: ignore
    except Exception as exc:
        return {
            "available": False,
            "client": None,
            "persist_path": persist_path,
            "error": f"chromadb unavailable: {exc}",
        }
    try:
        Path(persist_path).mkdir(parents=True, exist_ok=True)
        client = chromadb.PersistentClient(path=persist_path)
        return {"available": True, "client": client, "persist_path": persist_path, "error": ""}
    except Exception as exc:
        return {
            "available": False,
            "client": None,
            "persist_path": persist_path,
            "error": str(exc)[:300],
        }


def _get_collection(client):
    return client.get_or_create_collection(
        name=COLLECTION_NAME,
        embedding_function=LocalHashEmbeddingFunction(),
    )


def _fts_fallback(
    db: Session,
    query: str,
    doc_types: list[str],
    limit: int,
    auto_rebuild: bool,
    reason: str,
) -> dict[str, Any]:
    result = full_text_search_service.search_documents(
        db,
        query=query,
        doc_types=doc_types,
        limit=limit,
        auto_rebuild=auto_rebuild,
    )
    result["backend"] = f"semantic_{result.get('backend', 'fts5')}"
    result["semantic_degraded"] = True
    result["semantic_error"] = reason
    return result


def _normalize_chroma_query_result(raw: dict[str, Any]) -> list[dict[str, Any]]:
    metadatas = (raw.get("metadatas") or [[]])[0] or []
    documents = (raw.get("documents") or [[]])[0] or []
    distances = (raw.get("distances") or [[]])[0] or []
    items: list[dict[str, Any]] = []
    for index, metadata in enumerate(metadatas):
        payload = json.loads(metadata.get("payload_json") or "{}")
        content = documents[index] if index < len(documents) else payload.get("content", "")
        distance = float(distances[index]) if index < len(distances) and distances[index] is not None else 0.0
        items.append({
            "doc_type": payload.get("doc_type") or metadata.get("doc_type") or "",
            "source_id": payload.get("source_id") or metadata.get("source_id") or "",
            "title": payload.get("title") or metadata.get("title") or "",
            "title_snippet": payload.get("title") or metadata.get("title") or "",
            "content_snippet": _snippet(str(content or payload.get("content") or "")),
            "metadata": payload.get("metadata") or {},
            "updated_at": payload.get("updated_at") or metadata.get("updated_at") or "",
            "score": distance,
            "backend": "chroma",
        })
    return items


def _chroma_metadata(doc: dict[str, str]) -> dict[str, str]:
    metadata = json.loads(doc.get("metadata_json") or "{}")
    payload = {
        "doc_type": doc["doc_type"],
        "source_id": doc["source_id"],
        "title": doc["title"],
        "content": doc["content"],
        "metadata": metadata,
        "updated_at": doc.get("updated_at") or "",
    }
    return {
        "doc_type": doc["doc_type"],
        "source_id": doc["source_id"],
        "title": doc["title"],
        "kind": str(metadata.get("kind") or ""),
        "updated_at": doc.get("updated_at") or "",
        "payload_json": json.dumps(payload, ensure_ascii=False, default=str),
    }


def _doc_text(doc: dict[str, str]) -> str:
    return f"{doc.get('title') or ''}\n{doc.get('content') or ''}".strip()


def _doc_id(doc: dict[str, str]) -> str:
    return hashlib.sha1(f"{doc['doc_type']}:{doc['source_id']}".encode("utf-8")).hexdigest()


def _hash_embedding(text: str) -> list[float]:
    vector = [0.0] * EMBEDDING_DIM
    normalized = "".join(text.lower().split())
    grams = _char_grams(normalized)
    if not grams:
        return vector
    for gram in grams:
        digest = hashlib.blake2b(gram.encode("utf-8"), digest_size=4).digest()
        slot = int.from_bytes(digest[:2], "big") % EMBEDDING_DIM
        sign = 1.0 if digest[2] % 2 == 0 else -1.0
        vector[slot] += sign
    norm = math.sqrt(sum(value * value for value in vector)) or 1.0
    return [value / norm for value in vector]


def _char_grams(text: str) -> list[str]:
    if not text:
        return []
    grams = [text[index: index + 3] for index in range(max(1, len(text) - 2))]
    if len(text) <= 2:
        grams.append(text)
    return grams


def _doc_type_where(doc_types: list[str]) -> dict[str, Any] | None:
    if not doc_types:
        return None
    if len(doc_types) == 1:
        return {"doc_type": doc_types[0]}
    return {"doc_type": {"$in": doc_types}}


def _normalize_doc_types(doc_types: list[str] | None) -> list[str]:
    allowed = full_text_search_service.ALLOWED_DOC_TYPES
    normalized: list[str] = []
    for item in doc_types or []:
        for part in str(item).split(","):
            doc_type = part.strip()
            if doc_type and doc_type in allowed and doc_type not in normalized:
                normalized.append(doc_type)
    return normalized


def _clamp_limit(limit: int) -> int:
    try:
        value = int(limit)
    except Exception:
        value = DEFAULT_LIMIT
    return max(1, min(value, MAX_LIMIT))


def _safe_collection_count(collection) -> int:
    try:
        return int(collection.count() or 0)
    except Exception:
        return 0


def _count_by_type(documents: list[dict[str, str]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for doc in documents:
        doc_type = doc["doc_type"]
        counts[doc_type] = counts.get(doc_type, 0) + 1
    return counts


def _persist_path() -> str:
    raw = (
        os.getenv("MOXI_CHROMA_PATH")
        or os.getenv("CHROMA_PATH")
        or _chroma_config().get("path")
        or "./data/chroma"
    )
    path = Path(str(raw))
    if not path.is_absolute():
        path = Path(config.base_dir) / path
    return str(path)


def _chroma_config() -> dict[str, Any]:
    raw = config.raw.get("chroma", {})
    return raw if isinstance(raw, dict) else {}


def _snippet(content: str, limit: int = 220) -> str:
    if len(content) <= limit:
        return content
    return f"{content[:limit]}..."
