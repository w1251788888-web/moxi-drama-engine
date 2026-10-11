"""Graphiti 时序知识图谱适配层（Phase 2）

定位：剧情/角色/关系/伏笔的时序事实库，替代 W2-B/C/D 的自研逻辑。
- LLM：复用 config.yaml 里的 Kimi（OpenAI 兼容协议）
- 嵌入：占位 stub（PoC 阶段，仅用图结构；后续可换 bge-m3）
- 失败安全：连接失败时返回 None，主流程退回旧 _snapshot_relationships 逻辑
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class GraphitiSettings:
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "moxi_pass_2026"
    llm_base_url: str = "https://api.moonshot.cn/v1"
    llm_api_key: str = ""
    llm_model: str = "moonshot-v1-32k"
    enabled: bool = True
    embedder_kind: str = "bge-m3"  # bge-m3 | stub
    embedder_model: str = "BAAI/bge-m3"


def _make_stub_embedder(dim: int = 1024):
    """占位嵌入器：blake2b 派生 dim 维伪向量，仅供 PoC。"""
    from graphiti_core.embedder.client import EmbedderClient

    class _StubEmbedderImpl(EmbedderClient):
        def __init__(self) -> None:
            self.dim = dim
            self.config = type("EmbedConfig", (), {"embedding_dim": dim})()

        async def create(self, input_data):
            if isinstance(input_data, list):
                txt = " ".join(str(t) for t in input_data)
            else:
                txt = str(input_data)
            digest = hashlib.blake2b(txt.encode("utf-8"), digest_size=64).digest()
            seq = (digest * ((self.dim * 4) // len(digest) + 1))[: self.dim * 4]
            return [((b - 128) / 128.0) for b in seq[: self.dim]]

        async def create_batch(self, input_data_list):
            return [await self.create(s) for s in input_data_list]

    return _StubEmbedderImpl()


_BGE_MODEL_CACHE: dict[str, Any] = {}


def _make_bge_embedder(model_name: str = "BAAI/bge-m3", dim: int = 1024):
    """sentence-transformers 真实嵌入器，单例缓存模型。"""
    from graphiti_core.embedder.client import EmbedderClient

    class _BGEEmbedderImpl(EmbedderClient):
        def __init__(self) -> None:
            self.dim = dim
            self.config = type("EmbedConfig", (), {"embedding_dim": dim})()
            if model_name not in _BGE_MODEL_CACHE:
                from sentence_transformers import SentenceTransformer
                _BGE_MODEL_CACHE[model_name] = SentenceTransformer(model_name)
            self._model = _BGE_MODEL_CACHE[model_name]

        def _encode(self, texts: list[str]) -> list[list[float]]:
            arr = self._model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
            return [[float(x) for x in row] for row in arr]

        async def create(self, input_data):
            # Graphiti always expects a single vector back, even when input is a list.
            if isinstance(input_data, list):
                text = " ".join(str(t) for t in input_data)
            else:
                text = str(input_data)
            return self._encode([text])[0]

        async def create_batch(self, input_data_list):
            return self._encode([str(t) for t in input_data_list])

    return _BGEEmbedderImpl()


class GraphitiMemory:
    """对外暴露同步接口，内部跑 asyncio。主流程零改造。"""

    def __init__(self, settings: GraphitiSettings) -> None:
        self.settings = settings
        self._graphiti = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._initialized = False

    def _ensure_loop(self) -> asyncio.AbstractEventLoop:
        if self._loop is None or self._loop.is_closed():
            self._loop = asyncio.new_event_loop()
        return self._loop

    def initialize(self) -> bool:
        if self._initialized:
            return True
        if not self.settings.enabled or not self.settings.llm_api_key:
            logger.info("graphiti disabled or no llm api key")
            return False
        try:
            from graphiti_core import Graphiti
            from graphiti_core.llm_client.config import LLMConfig
            from graphiti_core.llm_client.openai_generic_client import OpenAIGenericClient as OpenAIClient
            from graphiti_core.cross_encoder.openai_reranker_client import OpenAIRerankerClient

            llm_config = LLMConfig(
                api_key=self.settings.llm_api_key,
                base_url=self.settings.llm_base_url,
                model=self.settings.llm_model,
                small_model=self.settings.llm_model,
            )
            llm_client = OpenAIClient(config=llm_config)
            cross_encoder = OpenAIRerankerClient(config=llm_config)
            if self.settings.embedder_kind == "bge-m3":
                try:
                    embedder = _make_bge_embedder(self.settings.embedder_model)
                except Exception as exc:
                    logger.warning("bge embedder failed, fallback stub: %s", exc)
                    embedder = _make_stub_embedder()
            else:
                embedder = _make_stub_embedder()

            self._graphiti = Graphiti(
                uri=self.settings.neo4j_uri,
                user=self.settings.neo4j_user,
                password=self.settings.neo4j_password,
                llm_client=llm_client,
                embedder=embedder,
                cross_encoder=cross_encoder,
            )
            loop = self._ensure_loop()
            loop.run_until_complete(self._graphiti.build_indices_and_constraints())
            self._initialized = True
            logger.info("graphiti initialized")
            return True
        except Exception as exc:  # pragma: no cover
            logger.warning("graphiti init failed: %s", exc)
            self._graphiti = None
            return False

    def add_episode(
        self,
        *,
        project_id: str,
        episode_no: int,
        title: str,
        content: str,
        reference_time: datetime | None = None,
    ) -> bool:
        if not self.initialize():
            return False
        from graphiti_core.nodes import EpisodeType

        ref = reference_time or datetime.now(timezone.utc)
        try:
            loop = self._ensure_loop()
            loop.run_until_complete(
                self._graphiti.add_episode(  # type: ignore[union-attr]
                    name=f"{project_id}-ep{episode_no:03d}-{title}",
                    episode_body=content,
                    source=EpisodeType.text,
                    reference_time=ref,
                    source_description=f"剧本第{episode_no}集：{title}",
                    group_id=project_id,
                )
            )
            return True
        except Exception as exc:
            logger.warning("graphiti add_episode failed ep=%s: %s", episode_no, exc)
            return False

    def search_facts(self, *, project_id: str, query: str, limit: int = 8) -> list[dict[str, Any]]:
        if not self.initialize():
            return []
        try:
            from graphiti_core.search.search_config import (
                EdgeReranker,
                EdgeSearchConfig,
                EdgeSearchMethod,
                SearchConfig,
            )

            methods = [EdgeSearchMethod.bm25]
            if self.settings.embedder_kind == "bge-m3":
                methods.append(EdgeSearchMethod.cosine_similarity)
            bm25_only = SearchConfig(
                edge_config=EdgeSearchConfig(
                    search_methods=methods,
                    reranker=EdgeReranker.rrf,
                ),
                limit=limit,
            )
            loop = self._ensure_loop()
            results_obj = loop.run_until_complete(
                self._graphiti._search(  # type: ignore[union-attr]
                    query=query,
                    group_ids=[project_id],
                    config=bm25_only,
                )
            )
            results = getattr(results_obj, "edges", []) or []
            facts: list[dict[str, Any]] = []
            for edge in results:
                facts.append({
                    "fact": getattr(edge, "fact", ""),
                    "valid_at": str(getattr(edge, "valid_at", "") or ""),
                    "invalid_at": str(getattr(edge, "invalid_at", "") or ""),
                    "source_node": str(getattr(edge, "source_node_uuid", "")),
                    "target_node": str(getattr(edge, "target_node_uuid", "")),
                })
            return facts
        except Exception as exc:
            logger.warning("graphiti search failed: %s", exc)
            return []

    def close(self) -> None:
        if self._graphiti is not None and self._loop is not None:
            try:
                self._loop.run_until_complete(self._graphiti.close())  # type: ignore[union-attr]
            except Exception:
                pass
            try:
                self._loop.close()
            except Exception:
                pass
        self._graphiti = None
        self._initialized = False
