"""
Dify RAG 检索服务

设计原则：
- 对 pipeline 零破坏：未配置 / Dify 不可达 / 查询失败时，返回空字符串，主流程不受影响
- 不替代规则注入（policy-based injection 继续走 pipeline.toml）
- 只做"非结构化长文本 / 跨项目复用 / 历史记忆 / 外部数据"四类检索

典型数据集（需用户在 Dify UI 手动创建）：
- asset_library      跨项目高分桥段/人设/钩子库
- novel_{project_id} 小说 IP 改编专用（每个 IP 一个，需显式开启私有 RAG）
- project_{project_id} 项目内历史集记忆（默认关闭，不能作为用户项目事实源）
- market_signals     热榜/评论/DataEye 数据

使用：
    from app.services.rag_service import get_rag_retriever
    rag = get_rag_retriever()
    ctx = await rag.retrieve(dataset="asset_library", query="男频 羞辱逆袭 开场", top_k=5)
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

import httpx

from app.config import get_config

logger = logging.getLogger(__name__)

DIFY_API_QUERY_MAX_CHARS = 250


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _falsy(value: Any) -> bool:
    if isinstance(value, bool):
        return not value
    return str(value or "").strip().lower() in {"0", "false", "no", "off", "disabled"}


def _dify_config_enabled(dify_cfg: dict[str, Any]) -> bool:
    """Operator switch for the external Dify/DeFi knowledge channel.

    Important distinction:
    - enabled=false means the online channel is paused.
    - base_url/api_key/datasets are still kept so the admin can reconnect later
      by flipping the switch, without rewriting all dataset bindings.
    """
    env_value = os.getenv("MOXI_DIFY_ENABLED", os.getenv("MOXI_RAG_DIFY_ENABLED", ""))
    if env_value != "":
        return not _falsy(env_value)
    if "enabled" in dify_cfg:
        return not _falsy(dify_cfg.get("enabled"))
    return True


def private_project_rag_enabled() -> bool:
    """Whether external RAG may store/read private project memory.

    The default is intentionally false: user/project records live in DB and the
    per-actor workspace folder. Dify/RAG is only a public/reference recall layer
    unless an operator explicitly opts into private project memory.
    """
    try:
        cfg = get_config() or {}
    except Exception:
        cfg = {}
    dify_cfg = ((cfg.get("rag") or {}).get("dify") or {})
    if not _dify_config_enabled(dify_cfg):
        return False
    return _truthy(dify_cfg.get("allow_private_project_writes"))


@dataclass
class RAGChunk:
    content: str
    score: float
    source: str = ""
    metadata: dict | None = None

    def as_reference(self) -> str:
        src = f"【{self.source}】" if self.source else ""
        return f"{src}{self.content}".strip()


class DifyRetriever:
    """Dify Knowledge API 客户端。未配置时所有检索调用返回空列表。"""

    def __init__(
        self,
        base_url: str = "",
        api_key: str = "",
        dataset_map: dict[str, str] | None = None,
        timeout: float = 8.0,
        search_method: str = "hybrid_search",
        config_enabled: bool = True,
    ) -> None:
        self.base_url = (base_url or "").rstrip("/")
        self.api_key = api_key or ""
        self.dataset_map = dataset_map or {}
        self.timeout = timeout
        self.search_method = search_method or "hybrid_search"
        self.config_enabled = bool(config_enabled)

    @property
    def enabled(self) -> bool:
        return bool(self.config_enabled and self.base_url and self.api_key)

    async def health_status(self) -> dict[str, Any]:
        """Return an admin-safe status snapshot for the Dify knowledge base.

        This method is intentionally read-only and short-timeout. It gives the
        admin console enough detail to explain why knowledge recall is degraded
        without leaking API keys or blocking the main generation pipeline.
        """
        dataset_names = sorted(self.dataset_map.keys())
        status: dict[str, Any] = {
            "ok": False,
            "mode": "disabled",
            "backend": "dify",
            "configured": self.enabled,
            "channel_enabled": self.config_enabled,
            "base_url": self.base_url,
            "datasets_configured": len(dataset_names),
            "dataset_names": dataset_names,
            "dify_dataset_total": None,
            "matched_dataset_count": 0,
            "unmatched_dataset_names": dataset_names,
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "message": "Dify 知识库未配置，剧本生成会自动跳过知识库增强。",
        }
        if not self.config_enabled:
            status["configured"] = bool(self.base_url and self.api_key)
            status["message"] = "Dify/DeFi 知识库通道已临时关闭；接口和数据集配置仍保留，部署完成后可立即重新开启。"
            return status
        if not self.enabled:
            return status

        url = f"{self.base_url}/v1/datasets"
        headers = {"Authorization": f"Bearer {self.api_key}"}
        try:
            timeout = httpx.Timeout(min(max(self.timeout, 1.0), 3.0), connect=1.5)
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.get(url, headers=headers, params={"page": 1, "limit": 100})
                resp.raise_for_status()
                data = resp.json()
        except httpx.HTTPStatusError as exc:
            status.update(
                {
                    "mode": "degraded",
                    "error_type": "http_error",
                    "status_code": exc.response.status_code,
                    "message": "Dify 已配置，但接口返回错误；主生成链路会自动降级，不会阻断用户创作。",
                }
            )
            return status
        except Exception as exc:
            status.update(
                {
                    "mode": "degraded",
                    "error_type": type(exc).__name__,
                    "message": "Dify 已配置，但当前无法连接；主生成链路会自动降级，不会阻断用户创作。",
                }
            )
            return status

        remote_items = data.get("data") or []
        remote_ids = {
            str(item.get("id") or "").strip()
            for item in remote_items
            if str(item.get("id") or "").strip()
        }
        matched_names = [
            name for name in dataset_names
            if str(self.dataset_map.get(name) or "").strip() in remote_ids
        ]
        unmatched_names = [name for name in dataset_names if name not in matched_names]
        status.update(
            {
                "ok": True,
                "mode": "connected",
                "dify_dataset_total": int(data.get("total") or len(remote_items)),
                "matched_dataset_count": len(matched_names),
                "unmatched_dataset_names": unmatched_names,
                "message": "Dify 知识库已连接，生成链路可使用知识库增强。",
            }
        )
        if unmatched_names:
            status["message"] = "Dify 可连接，但部分本地配置的数据集没有在 Dify 返回列表中匹配到。"
        return status

    async def retrieve(
        self,
        dataset: str,
        query: str,
        top_k: int = 5,
        score_threshold: float = 0.0,
    ) -> list[RAGChunk]:
        """
        dataset: 逻辑名（如 'asset_library'），内部映射到 Dify dataset_id
        query:   检索语句
        """
        chunks, _ = await self.retrieve_with_diagnostics(dataset, query, top_k, score_threshold)
        return chunks

    async def retrieve_with_diagnostics(
        self,
        dataset: str,
        query: str,
        top_k: int = 5,
        score_threshold: float = 0.0,
    ) -> tuple[list[RAGChunk], dict[str, Any]]:
        """Retrieve chunks and return an internal diagnostic record.

        User-facing generation should not block on RAG, but operators need to
        know whether a miss was empty recall, disabled config, timeout, or an
        avoidable request issue such as an overlong Dify query.
        """
        query_text = str(query or "").strip()
        diagnostics: dict[str, Any] = {
            "backend": "dify",
            "dataset": dataset,
            "query_chars": len(query_text),
            "status": "ok",
        }
        if not self.enabled:
            diagnostics["status"] = "disabled"
            return [], diagnostics
        if not query_text:
            diagnostics["status"] = "empty_query"
            return [], diagnostics
        if len(query_text) > DIFY_API_QUERY_MAX_CHARS:
            diagnostics["status"] = "query_too_long"
            diagnostics["error"] = f"query_chars>{DIFY_API_QUERY_MAX_CHARS}"
            return [], diagnostics
        dataset_id = self.dataset_map.get(dataset) or dataset
        diagnostics["dataset_id"] = dataset_id
        if not dataset_id:
            diagnostics["status"] = "missing_dataset"
            return [], diagnostics

        url = f"{self.base_url}/v1/datasets/{dataset_id}/retrieve"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        methods = [self.search_method]
        if self.search_method != "keyword_search":
            methods.append("keyword_search")

        data: dict[str, Any] = {}
        records: list[dict[str, Any]] = []
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                for method in methods:
                    payload = {
                        "query": query_text,
                        "retrieval_model": {
                            "search_method": method,
                            "reranking_enable": method == "hybrid_search",
                            "top_k": top_k,
                            "score_threshold_enabled": score_threshold > 0,
                            "score_threshold": score_threshold,
                        },
                    }
                    resp = await client.post(url, json=payload, headers=headers)
                    resp.raise_for_status()
                    data = resp.json()
                    records = data.get("records") or []
                    diagnostics["method"] = method
                    if records or method == methods[-1]:
                        break
        except httpx.HTTPStatusError as exc:
            body = ""
            status_code = None
            try:
                status_code = exc.response.status_code
                body = exc.response.text
            except Exception:
                pass
            diagnostics["status"] = "http_error"
            diagnostics["status_code"] = status_code
            diagnostics["error"] = body[:240] or str(exc)[:240]
            logger.warning("RAG retrieve failed (dataset=%s): %s", dataset, exc)
            return [], diagnostics
        except Exception as exc:
            diagnostics["status"] = "error"
            diagnostics["error"] = f"{type(exc).__name__}: {str(exc)[:220]}"
            logger.warning("RAG retrieve failed (dataset=%s): %s", dataset, exc)
            return [], diagnostics

        chunks: list[RAGChunk] = []
        for item in records:
            seg = item.get("segment") or {}
            doc = seg.get("document") or {}
            content = seg.get("content") or ""
            if not content:
                continue
            chunks.append(
                RAGChunk(
                    content=content,
                    score=float(item.get("score") or seg.get("score") or 0.0),
                    source=doc.get("name") or "",
                    metadata=seg.get("metadata") or None,
                )
            )
        if not chunks:
            diagnostics["status"] = "empty"
        diagnostics["count"] = len(chunks)
        return chunks, diagnostics

    def resolve_dataset_id(self, dataset: str) -> str:
        """Resolve a logical dataset name to a Dify dataset id.

        If the logical name is not mapped, keep the original value so existing
        dynamic dataset usages keep the same safe-fail behavior.
        """
        return self.dataset_map.get(dataset) or dataset

    async def create_text_document(
        self,
        dataset: str,
        name: str,
        text: str,
        *,
        indexing_technique: str = "high_quality",
    ) -> dict[str, Any]:
        """Create a text document in a Dify dataset.

        This is intentionally best-effort friendly for workflow callers: callers
        can catch the returned error instead of letting RAG indexing interrupt
        script generation.
        """
        if not self.enabled:
            return {"ok": False, "error": "rag_disabled"}
        dataset_id = self.resolve_dataset_id(dataset)
        if not dataset_id:
            return {"ok": False, "error": "dataset_missing"}
        if not str(text or "").strip():
            return {"ok": False, "error": "empty_text"}

        url = f"{self.base_url}/v1/datasets/{dataset_id}/document/create-by-text"
        payload = {
            "name": str(name or "rag_context").strip()[:180],
            "text": str(text or "").strip(),
            "indexing_technique": indexing_technique,
            "process_rule": {"mode": "automatic"},
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        try:
            async with httpx.AsyncClient(timeout=max(self.timeout, 20.0)) as client:
                resp = await client.post(url, json=payload, headers=headers)
                resp.raise_for_status()
                return {"ok": True, "data": resp.json()}
        except Exception as exc:
            logger.warning("RAG create document failed (dataset=%s): %s", dataset, exc)
            return {"ok": False, "error": str(exc)}

    async def delete_document(
        self,
        dataset: str,
        document_id: str,
    ) -> dict[str, Any]:
        """删除 Dify 数据集中的某个文档。失败返回 {ok: False, error: ...}。"""
        if not self.enabled:
            return {"ok": False, "error": "rag_disabled"}
        if not document_id:
            return {"ok": False, "error": "missing_document_id"}
        dataset_id = self.resolve_dataset_id(dataset)
        if not dataset_id:
            return {"ok": False, "error": "dataset_missing"}

        url = f"{self.base_url}/v1/datasets/{dataset_id}/documents/{document_id}"
        headers = {"Authorization": f"Bearer {self.api_key}"}
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.delete(url, headers=headers)
                if resp.status_code in (200, 204):
                    return {"ok": True}
                return {"ok": False, "error": f"http_{resp.status_code}", "body": resp.text}
        except Exception as exc:
            logger.warning("RAG delete document failed (dataset=%s, doc=%s): %s", dataset, document_id, exc)
            return {"ok": False, "error": str(exc)}

    async def retrieve_as_text(
        self,
        dataset: str,
        query: str,
        top_k: int = 5,
        score_threshold: float = 0.0,
        header: str = "",
    ) -> str:
        chunks = await self.retrieve(dataset, query, top_k, score_threshold)
        if not chunks:
            return ""
        body = "\n\n---\n\n".join(c.as_reference() for c in chunks)
        return f"{header}\n\n{body}".strip() if header else body

    async def retrieve_as_text_with_diagnostics(
        self,
        dataset: str,
        query: str,
        top_k: int = 5,
        score_threshold: float = 0.0,
        header: str = "",
    ) -> tuple[str, dict[str, Any]]:
        chunks, diagnostics = await self.retrieve_with_diagnostics(dataset, query, top_k, score_threshold)
        if not chunks:
            return "", diagnostics
        body = "\n\n---\n\n".join(c.as_reference() for c in chunks)
        return (f"{header}\n\n{body}".strip() if header else body), diagnostics


_INSTANCE: Optional[DifyRetriever] = None


def get_rag_retriever() -> DifyRetriever:
    """
    读取 config.yaml 中 rag.dify 段：
        rag:
          dify:
            base_url: http://localhost
            api_key: dataset-xxxx
            datasets:
              asset_library: <dataset_id_in_dify>
              market_signals: <dataset_id_in_dify>
    """
    global _INSTANCE
    if _INSTANCE is not None:
        return _INSTANCE
    try:
        cfg = get_config() or {}
    except Exception:
        cfg = {}
    dify_cfg = ((cfg.get("rag") or {}).get("dify") or {})
    _INSTANCE = DifyRetriever(
        base_url=dify_cfg.get("base_url", ""),
        api_key=dify_cfg.get("api_key", ""),
        dataset_map=dify_cfg.get("datasets") or {},
        timeout=float(dify_cfg.get("timeout", 8.0)),
        search_method=str(dify_cfg.get("search_method") or "hybrid_search"),
        config_enabled=_dify_config_enabled(dify_cfg),
    )
    if _INSTANCE.enabled:
        logger.info("RAG retriever enabled (base_url=%s, datasets=%s)",
                    _INSTANCE.base_url, list(_INSTANCE.dataset_map.keys()))
    else:
        logger.info("RAG retriever disabled (no dify config)")
    return _INSTANCE


def reset_rag_retriever() -> None:
    """用于配置热更新后重置单例。"""
    global _INSTANCE
    _INSTANCE = None
