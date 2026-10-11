from __future__ import annotations

import pytest

from app.services import rag_service
from app.services.rag_service import DifyRetriever


class _FakeResponse:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self._payload


class _FakeAsyncClient:
    calls: list[dict] = []

    def __init__(self, *args, **kwargs) -> None:
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None

    async def post(self, url: str, json: dict, headers: dict) -> _FakeResponse:
        self.calls.append(json)
        method = json["retrieval_model"]["search_method"]
        if method == "semantic_search":
            return _FakeResponse({"records": []})
        return _FakeResponse(
            {
                "records": [
                    {
                        "score": 0.42,
                        "segment": {
                            "content": "爆款短剧拆剧样本：剧情段落、集数、情绪序列。",
                            "document": {"name": "hit-breakdown-samples/README.md"},
                            "metadata": {"kind": "market_signal"},
                        },
                    }
                ]
            }
        )


@pytest.mark.asyncio
async def test_dify_retriever_falls_back_to_keyword_when_semantic_empty(monkeypatch):
    _FakeAsyncClient.calls = []
    monkeypatch.setattr(rag_service.httpx, "AsyncClient", _FakeAsyncClient)

    retriever = DifyRetriever(
        base_url="http://dify.local",
        api_key="dataset-test",
        dataset_map={"market_signals": "dataset-id"},
        search_method="semantic_search",
    )

    chunks = await retriever.retrieve("market_signals", "倒计时 金手指", top_k=2)

    assert [c.source for c in chunks] == ["hit-breakdown-samples/README.md"]
    assert "剧情段落" in chunks[0].content
    assert [
        call["retrieval_model"]["search_method"] for call in _FakeAsyncClient.calls
    ] == ["semantic_search", "keyword_search"]


def test_private_project_rag_is_disabled_by_default(monkeypatch):
    monkeypatch.setattr(rag_service, "get_config", lambda: {"rag": {"dify": {"base_url": "http://dify"}}})

    assert rag_service.private_project_rag_enabled() is False


def test_dify_channel_can_be_paused_without_losing_bindings(monkeypatch):
    monkeypatch.setattr(
        rag_service,
        "get_config",
        lambda: {
            "rag": {
                "dify": {
                    "enabled": False,
                    "base_url": "http://dify.local",
                    "api_key": "dataset-token",
                    "datasets": {"asset_library": "dataset-id"},
                    "allow_private_project_writes": True,
                }
            }
        },
    )
    rag_service.reset_rag_retriever()

    retriever = rag_service.get_rag_retriever()

    assert retriever.enabled is False
    assert retriever.config_enabled is False
    assert retriever.base_url == "http://dify.local"
    assert retriever.dataset_map == {"asset_library": "dataset-id"}
    assert rag_service.private_project_rag_enabled() is False
    rag_service.reset_rag_retriever()


@pytest.mark.asyncio
async def test_dify_health_reports_operator_paused_channel():
    retriever = DifyRetriever(
        base_url="http://dify.local",
        api_key="dataset-token",
        dataset_map={"asset_library": "dataset-id"},
        config_enabled=False,
    )

    status = await retriever.health_status()

    assert status["mode"] == "disabled"
    assert status["configured"] is True
    assert status["channel_enabled"] is False
    assert "临时关闭" in status["message"]


@pytest.mark.asyncio
async def test_raptor_indexer_does_not_write_private_project_rag_by_default(monkeypatch):
    from app.services import raptor_indexer

    class FakeRag:
        enabled = True

        async def create_text_document(self, *args, **kwargs):
            raise AssertionError("private project data must not be written to external RAG by default")

    monkeypatch.setattr(raptor_indexer, "get_rag_retriever", lambda: FakeRag())
    monkeypatch.setattr(raptor_indexer, "private_project_rag_enabled", lambda: False)
    monkeypatch.setattr(raptor_indexer, "_gen_episode_summary", lambda *_args, **_kwargs: "本集梗概")
    monkeypatch.setattr(raptor_indexer, "_gen_scene_card", lambda scene, *_args, **_kwargs: scene[:40])

    result = await raptor_indexer.index_episode(
        project_id="project-a",
        episode=1,
        script_text="1-1 日 内 客厅\n何铮：我要查清真相。\n吴雪：你别再逼我。",
    )

    assert result.rag_enabled is False
    assert result.summary_doc_id == ""
    assert result.scene_card_doc_ids == []
    assert result.beat_doc_ids == []
    assert result.error == "private_project_rag_disabled"
