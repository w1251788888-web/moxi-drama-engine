import json
import sys
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest


ROOT = Path(__file__).resolve().parents[1]
WEBUI = ROOT / "webui" / "src"
sys.path.append(str(Path(__file__).resolve().parent))


def _read_webui(path: str) -> str:
    return (WEBUI / path).read_text(encoding="utf-8")


@pytest.fixture()
def isolated_script_job_client(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app import database
    from app.database import get_db
    from app.main import app

    engine = create_engine(
        f"sqlite:///{tmp_path / 'p5-task5-outline-character-entry.db'}",
        connect_args={"check_same_thread": False},
    )
    Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    database.Base.metadata.create_all(bind=engine)

    monkeypatch.setattr(database, "engine", engine)
    monkeypatch.setattr(database, "SessionLocal", Session)

    def override_db():
        db = Session()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_db
    try:
        yield app, TestClient(app), Session
    finally:
        app.dependency_overrides.pop(get_db, None)
        engine.dispose()


def test_p5_task5_page_entry_request_carries_outline_episode_and_character_materials():
    workspace = _read_webui("views/ProjectWorkspaceView.vue")
    settings = _read_webui("api/modules/settings.ts")
    draft = _read_webui("features/workspace/composables/useScriptDraftGeneration.ts")

    main_entry = workspace.split("useScriptDraftGeneration({", 1)[1].split("ingestWorkflowUpdates:", 1)[0]
    request_body = workspace.split("function _buildRuleBackedScriptRequest", 1)[1].split("function _scriptSegmentProgressStore", 1)[0]

    assert "buildRequest: currentContent => ({" in main_entry
    assert "_buildRuleBackedScriptRequest({" in main_entry
    assert "startRuleBackedScriptJob(requestPayload)" in main_entry
    assert "const requestPayload = {" in draft
    assert "...options.buildRequest(options.getSceneContent())" in draft
    assert "const job = await options.startScriptJob(requestPayload)" in draft
    assert "'/admin/short-drama/testing/script-scene/jobs/start'" in settings

    for snippet in [
        "brief: outlineData.value.logline",
        "golden_finger: outlineData.value.goldenFinger",
        "worldview: outlineData.value.worldview",
        "conflict: outlineData.value.conflict",
        "episode_count: confirmedEpisodeCount",
        "episode_title: epInfo?.title",
        "episode_summary: epInfo?.summary",
        "episode_conflict: epInfo?.conflict",
        "episode_hook: epInfo?.hook || epInfo?.turning",
        "characters: (characters.value as any[]).map",
        "info: char.info",
        "occupation: char.occupation",
        "background: char.background",
        "motivation: char.motivation",
        "traits: char.traits",
        "personality: char.personality",
        "voice_style: char.voice_style",
        "inner_need: char.inner_need",
        "relationship_tension: char.relationship_tension",
        "relationships: char.relationships",
        "previous_episode_briefs: _buildPreviousEpisodeBriefs(9, episodeNo)",
        "future_episode_briefs: _buildFutureEpisodeBriefs(5, episodeNo)",
        "previous_relationship_snapshot: _buildPreviousRelationshipSnapshot()",
        "relationship_timeline_context: _buildRelationshipTimelineContext(episodeNo)",
        "episode_memory_cards: episodeMemoryCards.value",
        "canon_packet: canonPacket.value",
        "step_confirmation_packet: stepConfirmationPacket",
        "user_confirmed_generation_packet: _buildUserConfirmedGenerationPacket(stepConfirmationPacket)",
        "series_simulation_packet: seriesSimulationPacket",
        "episode_contract: episodeContract",
    ]:
        assert snippet in request_body


def test_p5_task5_backend_job_request_json_preserves_effective_outline_and_character_fields(
    tmp_path,
    monkeypatch,
    isolated_script_job_client,
):
    from app.models.short_drama_generation_job import ShortDramaGenerationJob
    from app.routers.projects import _helpers as project_helpers
    from app.routers.short_drama import scene_routes
    from app.services.saas_access_service import create_access_key
    from test_short_drama_scene_generation_jobs import (
        _seed_source_packet_backend_materials,
        _seed_source_packet_locked_official_source,
    )

    _, client, Session = isolated_script_job_client
    workspace_root = tmp_path / "p5-task5-outline-character-entry-workspaces"
    workspace_root.mkdir()
    monkeypatch.setattr(project_helpers, "WORKSPACE_ROOT", workspace_root)
    monkeypatch.setattr(project_helpers, "LEGACY_WORKSPACE_ROOT", workspace_root)

    with Session() as db:
        user = create_access_key(owner_name="p5 task5 entry proof user", initial_credit=Decimal("1.00"), db=db)

    login = client.post("/api/user/access-key/login", json={"access_key": user.plain_key})
    assert login.status_code == 200, login.text
    headers = {"X-User-Session": login.json()["session_token"]}

    created = client.post(
        "/api/v2/projects/",
        json={"name": f"p5-task5-entry-proof-{uuid4().hex[:8]}", "config": {"total_episodes": 6}},
        headers=headers,
    )
    assert created.status_code == 200, created.text
    project_id = created.json()["id"]
    _seed_source_packet_backend_materials(Session, project_id, confirmed_total_episodes=6)
    _seed_source_packet_locked_official_source(Session, project_id, episode_number=2)

    async def fake_rag(*_args, **_kwargs):
        return []

    def fake_generate_research_chain(*_args, **_kwargs):
        return {
            "content": "SAFE_P5_TASK5_ENTRY_CANDIDATE",
            "char_count_excluding_punctuation": 28,
            "warnings": [],
            "blocking_issues": [],
            "benchmark_assessment": None,
            "continuity_assessment": None,
            "episode_memory_card": {"episode_no": 3},
            "canon_packet": {"locked_facts": ["SAFE_P5_TASK5_ENTRY_FACT"]},
        }

    monkeypatch.setattr(scene_routes, "apply_rag_injection", fake_rag)
    monkeypatch.setattr(scene_routes, "generate_research_script_candidate", fake_generate_research_chain)
    monkeypatch.setattr(scene_routes, "apply_scene_level_gate", lambda _req, approved, _contract: approved)

    request_payload = {
        "project_id": project_id,
        "project_type": "short_drama",
        "audience_axis": "女频",
        "genre_main": "都市",
        "format_type": "真人短剧",
        "episode_count": 6,
        "episode_no": 3,
        "scene_no": 1,
        "brief": "女主回到家族企业查账。",
        "golden_finger": "能看见账本里的隐藏时间线。",
        "worldview": "传统商号与现代资本并行。",
        "conflict": "家族信任与商业真相冲突。",
        "episode_title": "旧账重开",
        "episode_summary": "女主拿到第三集关键账册。",
        "episode_conflict": "董事会逼她交出账册。",
        "episode_hook": "账册夹层出现父亲笔迹。",
        "characters": [
            {
                "id": "heroine",
                "name": "林若岚",
                "role": "protagonist",
                "info": "家族企业继承人，擅长审计。",
                "occupation": "审计师",
                "background": "父亲失踪后回到企业。",
                "motivation": "查清账本真相。",
                "traits": ["冷静", "敏锐"],
                "personality": "外冷内热",
                "voice_style": "克制直接",
                "inner_need": "重新相信家人。",
                "relationship_tension": "与叔父互相试探。",
                "relationships": [{"target": "林叔衡", "type": "叔侄对抗"}],
            }
        ],
        "previous_episode_briefs": [{"episode_no": 2, "summary": "上一集锁定线索。"}],
        "future_episode_briefs": [{"episode_no": 4, "summary": "下一集董事会升级。"}],
        "previous_relationship_snapshot": [{"source": "林若岚", "target": "林叔衡", "state": "试探"}],
        "relationship_timeline_context": [{"episode_no": 3, "change": "对抗升级"}],
        "episode_memory_cards": [{"episode_no": 2, "ending_state": "账册被带走"}],
        "canon_packet": {"locked_source": "episode_locked_content_version"},
        "step_confirmation_packet": {"blueprint": {"items": [{"itemKey": "key_scene", "body": "账册夹层"}]}},
        "user_confirmed_generation_packet": {"blueprint": {"items": [{"itemKey": "key_scene", "body": "账册夹层"}]}},
        "series_simulation_packet": {"episode_contracts": [{"episode_no": 3, "must_happen": ["真实冲突"]}]},
        "episode_contract": {
            "episode_no": 3,
            "must_happen": ["主场景必须落地：董事会会议室"],
        },
    }
    # Deliberately introduce a stale-contract conflict. User-confirmed material must
    # win without discarding the conflict evidence or any request fields.
    request_payload["user_confirmed_generation_packet"] = {
        "blueprint": {"items": [{"itemKey": "required_main_scene", "body": "账册夹层"}]}
    }

    start = client.post(
        "/api/admin/short-drama/testing/script-scene/jobs/start",
        json=request_payload,
        headers=headers,
    )
    assert start.status_code == 200, start.text
    assert start.json()["status"] in {"pending", "running", "candidate_ready"}

    status = client.get(
        f"/api/admin/short-drama/testing/script-scene/jobs/status/{start.json()['job_id']}",
        headers=headers,
    )
    assert status.status_code == 200, status.text
    assert status.json()["status"] == "candidate_ready"
    assert status.json()["blocking_conflicts"] == []
    assert status.json()["contract_conflicts"]
    assert all(item.get("auto_resolved") is True for item in status.json()["contract_conflicts"])

    with Session() as db:
        jobs = db.query(ShortDramaGenerationJob).filter(ShortDramaGenerationJob.project_id == project_id).all()
        assert len(jobs) == 1
        saved_request = json.loads(jobs[0].request_json)

    for key in [
        "brief",
        "golden_finger",
        "worldview",
        "conflict",
        "episode_title",
        "episode_summary",
        "episode_conflict",
        "episode_hook",
        "characters",
        "previous_episode_briefs",
        "future_episode_briefs",
        "previous_relationship_snapshot",
        "episode_memory_cards",
        "canon_packet",
        "step_confirmation_packet",
        "user_confirmed_generation_packet",
        "series_simulation_packet",
        "episode_contract",
        "final_generation_contract",
    ]:
        assert saved_request.get(key)

    assert saved_request["characters"][0]["name"] == "林若岚"
    assert saved_request["characters"][0]["info"] == "家族企业继承人，擅长审计。"
    assert saved_request["episode_count"] == 6
    assert saved_request["episode_no"] == 3
    assert "relationship_timeline_context" not in saved_request
