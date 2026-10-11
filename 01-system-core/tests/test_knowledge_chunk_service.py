from tests.test_full_text_search import _isolate_file_libraries, _make_search_session


def _make_chunk_session(tmp_path, monkeypatch):
    from app.models.knowledge_chunk import KnowledgeChunk

    _isolate_file_libraries(monkeypatch, tmp_path)
    db = _make_search_session()
    KnowledgeChunk.__table__.create(bind=db.get_bind())
    return db


def test_langchain_text_splitter_backend_is_used_when_dependency_is_installed():
    import pytest

    pytest.importorskip("langchain_text_splitters")

    from app.services.knowledge_chunk_service import get_chunking_backend, split_text

    text = "第一场：人物进入冲突。\n\n第二场：误会升级。\n\n第三场：付费墙反转。" * 12
    chunks, backend = split_text(text, chunk_size=120, chunk_overlap=20)

    assert get_chunking_backend() == "langchain"
    assert backend == "langchain"
    assert len(chunks) >= 2


def test_rebuild_knowledge_chunks_from_unified_documents(monkeypatch, tmp_path):
    from app.models.knowledge_chunk import KnowledgeChunk
    from app.services import full_text_search_service
    from app.services.knowledge_chunk_service import rebuild_knowledge_chunks, search_knowledge_chunks

    db = _make_chunk_session(tmp_path, monkeypatch)
    rule_root = full_text_search_service.RULE_MARKDOWN_ROOT
    skill_root = full_text_search_service.SKILL_LIBRARY_ROOT
    (rule_root / "core").mkdir()
    (rule_root / "core" / "hooks.md").write_text(
        "黄金三秒钩子需要身份错位、强冲突、反转承诺。\n\n" * 10,
        encoding="utf-8",
    )
    (skill_root / "short-drama-writer").mkdir()
    (skill_root / "short-drama-writer" / "SKILL.md").write_text(
        "# 短剧写作技能\n\n用于爆款短剧大纲、角色关系和前三集样稿生成。" * 4,
        encoding="utf-8",
    )

    try:
        result = rebuild_knowledge_chunks(db, chunk_size=160, chunk_overlap=20)

        assert result["available"] is True
        assert result["source_count"] == 2
        assert result["chunk_count"] >= 2
        assert result["doc_type_counts"] == {"rule": 1, "skill": 1}
        assert result["chunk_type_counts"]["rule"] >= 1
        assert result["chunk_type_counts"]["skill"] >= 1
        assert set(result["backends"]) <= {"builtin", "langchain"}

        rows = db.query(KnowledgeChunk).order_by(KnowledgeChunk.source_type, KnowledgeChunk.chunk_index).all()
        assert rows
        assert all(row.content_chars == len(row.content) for row in rows)
        assert all(row.chunk_hash and len(row.chunk_hash) == 64 for row in rows)
        assert any(row.source_path.endswith("short-drama-writer/SKILL.md") for row in rows)

        skill_hits = search_knowledge_chunks(db, "爆款短剧", doc_types=["skill"], limit=5)
        assert len(skill_hits) == 1
        assert skill_hits[0].source_type == "skill"
    finally:
        db.close()


def test_rebuild_knowledge_chunks_is_idempotent(monkeypatch, tmp_path):
    from app.models.knowledge_chunk import KnowledgeChunk
    from app.services import full_text_search_service
    from app.services.knowledge_chunk_service import rebuild_knowledge_chunks

    db = _make_chunk_session(tmp_path, monkeypatch)
    rule_root = full_text_search_service.RULE_MARKDOWN_ROOT
    (rule_root / "rhythm.md").write_text("短剧节奏：每场必须推进冲突。\n\n" * 8, encoding="utf-8")

    try:
        first = rebuild_knowledge_chunks(db, chunk_size=140, chunk_overlap=10)
        second = rebuild_knowledge_chunks(db, chunk_size=140, chunk_overlap=10)
        count = db.query(KnowledgeChunk).count()

        assert first["chunk_count"] == second["chunk_count"]
        assert second["deleted_count"] == first["chunk_count"]
        assert count == second["chunk_count"]
    finally:
        db.close()


def test_knowledge_chunk_context_formats_source_cited_prompt_block(monkeypatch, tmp_path):
    from app.services import full_text_search_service
    from app.services.knowledge_chunk_service import (
        build_knowledge_chunk_context_pack,
        build_knowledge_chunk_context,
        rebuild_knowledge_chunks,
    )

    db = _make_chunk_session(tmp_path, monkeypatch)
    rule_root = full_text_search_service.RULE_MARKDOWN_ROOT
    (rule_root / "core").mkdir()
    (rule_root / "core" / "paywall.md").write_text(
        "付费墙必须冻结场景、角色、道具和动作，让观众明确下一秒要发生什么。\n\n" * 6,
        encoding="utf-8",
    )

    try:
        rebuild_knowledge_chunks(db, chunk_size=180, chunk_overlap=20)
        context = build_knowledge_chunk_context(
            db,
            "付费墙",
            doc_types=["rule"],
            limit=3,
            max_chars=900,
        )

        assert context["count"] >= 1
        assert context["backend"] == "knowledge_chunks_like"
        assert context["text"].startswith("# 本地知识分块召回")
        assert "使用要求：仅把以下内容作为参考证据" in context["text"]
        assert "02-creation-rules/core/paywall.md#chunk-" in context["text"]
        assert len(context["text"]) <= 900
        assert context["items"][0]["source_type"] == "rule"
        assert context["items"][0]["metadata"]["path"] == "core/paywall.md"
        assert context["cards"][0]["context_type"] == "local_knowledge_chunk"
        assert "#chunk-" in context["cards"][0]["source"]

        pack = build_knowledge_chunk_context_pack(db, "付费墙", doc_types=["rule"], limit=2)
        assert pack["cards"][0]["authority_level"] == 72
        assert "local_knowledge" in pack["cards"][0]["tags"]
    finally:
        db.close()


def test_knowledge_chunk_router_rebuild_search_and_context(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient

    from app.auth.dependencies import verify_admin
    from app.database import get_db
    from app.main import app
    from app.services import full_text_search_service

    db = _make_chunk_session(tmp_path, monkeypatch)
    skill_root = full_text_search_service.SKILL_LIBRARY_ROOT
    (skill_root / "short-drama-writer").mkdir()
    (skill_root / "short-drama-writer" / "SKILL.md").write_text(
        "# 短剧写作技能\n\n用于爆款短剧大纲、角色关系、付费墙和前三集样稿生成。" * 5,
        encoding="utf-8",
    )

    def override_db():
        yield db

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[verify_admin] = lambda: True
    monkeypatch.setenv("MOXI_ENABLE_LOCAL_KNOWLEDGE_CHUNKS", "1")
    try:
        client = TestClient(app)

        rebuild = client.post(
            "/api/search/chunks/rebuild",
            params={"types": "skill", "chunk_size": 160, "chunk_overlap": 20},
        )
        assert rebuild.status_code == 200, rebuild.text
        rebuild_payload = rebuild.json()
        assert rebuild_payload["source_count"] == 1
        assert rebuild_payload["chunk_count"] >= 1
        assert rebuild_payload["chunk_type_counts"]["skill"] >= 1

        status = client.get("/api/search/chunks/status")
        assert status.status_code == 200, status.text
        assert status.json()["chunk_type_counts"]["skill"] >= 1

        search = client.get(
            "/api/search/chunks",
            params={"q": "爆款短剧", "types": "skill", "limit": 5},
        )
        assert search.status_code == 200, search.text
        search_payload = search.json()
        assert search_payload["backend"] == "knowledge_chunks_like"
        assert search_payload["count"] >= 1
        assert search_payload["items"][0]["source_path"].endswith("short-drama-writer/SKILL.md")

        context = client.get(
            "/api/search/chunks/context",
            params={"q": "付费墙", "types": "skill", "limit": 2, "max_chars": 1000},
        )
        assert context.status_code == 200, context.text
        context_payload = context.json()
        assert context_payload["text"].startswith("# 本地知识分块召回")
        assert "不得覆盖项目已锁定设定" in context_payload["text"]
        assert context_payload["cards"][0]["context_type"] == "local_knowledge_chunk"
        assert context_payload["count"] >= 1
    finally:
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(verify_admin, None)
        db.close()


def test_knowledge_chunk_model_is_registered_in_metadata():
    from app.database import Base
    from app.models.knowledge_chunk import KnowledgeChunk

    assert KnowledgeChunk.__tablename__ == "knowledge_chunks"
    assert "knowledge_chunks" in Base.metadata.tables
