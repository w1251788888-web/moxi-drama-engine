from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest


def _allow_advanced_generation(app):
    from app.auth.dependencies import ProjectAccessActor, verify_advanced_generation_actor

    app.dependency_overrides[verify_advanced_generation_actor] = lambda: ProjectAccessActor(actor_type="admin")
    return verify_advanced_generation_actor


def test_list_advanced_generation_profiles_normal_path():
    from app.services.short_drama_advanced_generation import (
        MODE_ID,
        list_advanced_generation_profiles,
    )

    profiles = list_advanced_generation_profiles()

    assert MODE_ID == "advanced_generation"
    assert profiles[0]["id"] == "short_drama"
    assert profiles[0]["status"] == "active"
    assert any(profile["id"] == "stage_play" for profile in profiles)
    assert any(profile["id"] == "film" for profile in profiles)
    assert all(profile["status"] == "active" for profile in profiles)


def test_get_advanced_generation_profile_error_path():
    from app.services.short_drama_advanced_generation import get_advanced_generation_profile

    with pytest.raises(ValueError, match="未知高级生成模式"):
        get_advanced_generation_profile("unknown")


def test_advanced_generation_resolves_step_model_route_when_enabled():
    from app.services.short_drama_advanced_generation import resolve_step_generation_route

    metadata = {
        "project": {
            "config": {
                "advanced_generation_mode": True,
                "advanced_generation_providers": {
                    "logic": {"provider": "anthropic", "model": "claude-sonnet-4-5", "temperature": 0.2},
                    "creative": {"provider": "kimi", "model": "kimi-k2.6", "temperature": 0.85},
                    "review": {"provider": "anthropic", "model": "claude-sonnet-4-5", "temperature": 0.0},
                },
            }
        }
    }

    concept = resolve_step_generation_route("concept", metadata, {"provider": "kimi", "model": "moonshot-v1-128k"}, 0.7)
    script = resolve_step_generation_route("script_draft", metadata, {"provider": "kimi", "model": "moonshot-v1-128k"}, 0.7)
    review = resolve_step_generation_route("quality_check", metadata, {"provider": "kimi", "model": "moonshot-v1-128k"}, 0.7)

    assert concept.enabled is True
    assert concept.role == "logic"
    assert concept.generation_kwargs == {"provider": "anthropic", "model": "claude-sonnet-4-5"}
    assert concept.temperature == 0.2
    assert script.role == "creative"
    assert script.generation_kwargs == {"provider": "kimi", "model": "kimi-k2.6"}
    assert script.temperature == 0.85
    assert review.role == "review"
    assert review.temperature == 0.0


def test_advanced_generation_keeps_project_model_when_disabled():
    from app.services.short_drama_advanced_generation import resolve_step_generation_route

    route = resolve_step_generation_route(
        "quality_check",
        {"project": {"config": {"advanced_generation_mode": False}}},
        {"provider": "kimi", "model": "moonshot-v1-128k"},
        0.4,
    )

    assert route.enabled is False
    assert route.generation_kwargs == {"provider": "kimi", "model": "moonshot-v1-128k"}
    assert route.temperature == 0.4


def test_advanced_generation_resolves_testing_request_route():
    from app.schemas.short_drama_writing import TestingScriptRequest
    from app.services.short_drama_advanced_generation import resolve_testing_generation_route

    req = TestingScriptRequest(
        advanced_generation_mode=True,
        generation_provider="kimi",
        generation_model="moonshot-v1-128k",
        advanced_generation_providers={
            "creative": {"provider": "kimi", "model": "kimi-k2.6", "temperature": 0.85},
            "review": {"provider": "anthropic", "model": "claude-sonnet-4-5", "temperature": 0.0},
        },
    )

    creative = resolve_testing_generation_route(req, "script_draft", 0.55)
    review = resolve_testing_generation_route(req, "quality_check", 0.1)

    assert creative.enabled is True
    assert creative.role == "creative"
    assert creative.generation_kwargs == {"provider": "kimi", "model": "kimi-k2.6"}
    assert creative.temperature == 0.85
    assert review.role == "review"
    assert review.generation_kwargs == {"provider": "anthropic", "model": "claude-sonnet-4-5"}
    assert review.temperature == 0.0


@pytest.mark.asyncio
async def test_advanced_generation_dependency_blocks_unentitled_user():
    from fastapi import HTTPException

    from app.auth.dependencies import ProjectAccessActor, verify_advanced_generation_actor

    with pytest.raises(HTTPException) as exc:
        await verify_advanced_generation_actor(ProjectAccessActor(actor_type="user", advanced_generation_enabled=False))

    assert exc.value.status_code == 403
    assert "高级生成权限" in exc.value.detail

    entitled = await verify_advanced_generation_actor(
        ProjectAccessActor(actor_type="user", access_key_id="key-1", advanced_generation_enabled=True)
    )
    assert entitled.access_key_id == "key-1"


def test_advanced_generation_plan_endpoint_returns_route_preview():
    from fastapi.testclient import TestClient

    from app.main import app

    override_key = _allow_advanced_generation(app)
    try:
        client = TestClient(app)
        resp = client.post(
            "/api/admin/short-drama/advanced-generation/plan",
            json={
                "metadata": {
                    "project": {
                        "config": {
                            "advanced_generation_mode": True,
                            "advanced_generation_providers": {
                                "review": {"provider": "anthropic", "model": "claude-sonnet-4-5"}
                            },
                        }
                    }
                },
                "base_generation_kwargs": {"provider": "kimi", "model": "kimi-k2.6"},
            },
        )
    finally:
        app.dependency_overrides.pop(override_key, None)

    assert resp.status_code == 200, resp.text
    payload = resp.json()
    assert payload["enabled"] is True
    quality_route = next(item for item in payload["routes"] if item["step_id"] == "quality_check")
    assert quality_route["role"] == "review"
    assert quality_route["provider"] == "anthropic"
    assert quality_route["model"] == "claude-sonnet-4-5"


def test_advanced_workflow_orchestration_degrades_without_langgraph(monkeypatch):
    from app.services.advanced_workflow_orchestration_service import (
        build_writer_reviewer_decision_orchestration,
        get_orchestration_status,
    )

    monkeypatch.setitem(sys.modules, "langchain", None)
    monkeypatch.setitem(sys.modules, "langgraph", None)
    monkeypatch.setitem(sys.modules, "langgraph.graph", None)

    metadata = {
        "project": {
            "config": {
                "advanced_generation_mode": True,
                "advanced_generation_providers": {
                    "creative": {"provider": "kimi", "model": "kimi-k2.6", "temperature": 0.85},
                    "review": {"provider": "anthropic", "model": "claude-sonnet-4-5", "temperature": 0.0},
                },
            }
        }
    }

    status = get_orchestration_status()
    plan = build_writer_reviewer_decision_orchestration(
        metadata,
        {"provider": "kimi", "model": "moonshot-v1-128k"},
        max_review_rounds=2,
    )

    assert status["backend"] == "builtin_fallback"
    assert status["degraded"] is True
    assert plan["backend"] == "builtin_fallback"
    assert plan["enabled"] is True
    assert [node["id"] for node in plan["nodes"]] == ["writer", "reviewer", "decision"]
    assert plan["nodes"][0]["provider"] == "kimi"
    assert plan["nodes"][0]["model"] == "kimi-k2.6"
    assert plan["nodes"][1]["provider"] == "anthropic"
    assert plan["nodes"][1]["model"] == "claude-sonnet-4-5"
    assert {"from": "decision", "to": "writer", "condition": "needs_revision_and_rounds_lt_2"} in plan["edges"]
    assert plan["probe_trace"] == ["writer", "reviewer", "decision"]


def test_advanced_workflow_orchestration_uses_langgraph_when_available(monkeypatch):
    class FakeCompiledGraph:
        def __init__(self, nodes):
            self.nodes = nodes

        def invoke(self, state):
            for node_name in ("writer", "reviewer", "decision"):
                state = self.nodes[node_name](state)
            return state

    class FakeStateGraph:
        def __init__(self, _schema):
            self.nodes = {}

        def add_node(self, name, func):
            self.nodes[name] = func

        def set_entry_point(self, _name):
            return None

        def add_edge(self, _source, _target):
            return None

        def add_conditional_edges(self, _source, _condition, _path_map):
            return None

        def compile(self):
            return FakeCompiledGraph(self.nodes)

    monkeypatch.setitem(sys.modules, "langchain", SimpleNamespace(__version__="0.3.fake"))
    monkeypatch.setitem(sys.modules, "langgraph", SimpleNamespace(__version__="0.2.fake"))
    monkeypatch.setitem(
        sys.modules,
        "langgraph.graph",
        SimpleNamespace(END="__end__", StateGraph=FakeStateGraph),
    )

    from app.services.advanced_workflow_orchestration_service import (
        build_writer_reviewer_decision_orchestration,
        get_orchestration_status,
    )

    status = get_orchestration_status()
    plan = build_writer_reviewer_decision_orchestration(
        {"project": {"config": {"advanced_generation_mode": True}}},
        {"provider": "kimi", "model": "moonshot-v1-128k"},
    )

    assert status["backend"] == "langgraph"
    assert status["compiled"] is True
    assert plan["backend"] == "langgraph"
    assert plan["available"] is True
    assert plan["compiled"] is True
    assert plan["probe_trace"] == ["writer", "reviewer", "decision"]


def test_advanced_generation_orchestration_endpoint_returns_plan(monkeypatch):
    from fastapi.testclient import TestClient

    from app.main import app

    monkeypatch.setitem(sys.modules, "langchain", None)
    monkeypatch.setitem(sys.modules, "langgraph", None)
    monkeypatch.setitem(sys.modules, "langgraph.graph", None)

    override_key = _allow_advanced_generation(app)
    try:
        client = TestClient(app)
        status_resp = client.get("/api/admin/short-drama/advanced-generation/orchestration/status")
        plan_resp = client.post(
            "/api/admin/short-drama/advanced-generation/orchestration/plan",
            json={
                "metadata": {"project": {"config": {"advanced_generation_mode": True}}},
                "base_generation_kwargs": {"provider": "kimi", "model": "moonshot-v1-128k"},
                "max_review_rounds": 3,
            },
        )
    finally:
        app.dependency_overrides.pop(override_key, None)

    assert status_resp.status_code == 200, status_resp.text
    assert plan_resp.status_code == 200, plan_resp.text
    payload = plan_resp.json()
    assert payload["workflow_id"] == "writer_reviewer_decision"
    assert payload["backend"] == "builtin_fallback"
    assert payload["max_review_rounds"] == 3
    assert payload["entrypoint"] == "writer"
    assert {"from": "writer", "to": "reviewer", "condition": "draft_created"} in payload["edges"]


def test_advanced_generation_profiles_endpoint_normal_path():
    from fastapi.testclient import TestClient

    from app.main import app

    override_key = _allow_advanced_generation(app)
    try:
        client = TestClient(app)
        resp = client.get("/api/admin/short-drama/advanced-generation/profiles")
    finally:
        app.dependency_overrides.pop(override_key, None)

    assert resp.status_code == 200, resp.text
    payload = resp.json()
    assert payload["mode_id"] == "advanced_generation"
    assert {item["id"] for item in payload["profiles"]} >= {"short_drama", "stage_play", "film"}


def test_advanced_generation_profile_endpoint_error_path():
    from fastapi.testclient import TestClient

    from app.main import app

    override_key = _allow_advanced_generation(app)
    try:
        client = TestClient(app)
        resp = client.get("/api/admin/short-drama/advanced-generation/profiles/nope")
    finally:
        app.dependency_overrides.pop(override_key, None)

    assert resp.status_code == 404
    assert "未知高级生成模式" in resp.json()["detail"]
