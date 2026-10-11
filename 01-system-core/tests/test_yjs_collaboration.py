import json


def _write_package_json(path, dependencies):
    path.write_text(json.dumps({"dependencies": dependencies}), encoding="utf-8")


def test_yjs_collaboration_status_degrades_when_dependencies_are_missing(tmp_path):
    from app.services.yjs_collaboration_service import get_yjs_collaboration_status

    package_json = tmp_path / "package.json"
    _write_package_json(package_json, {"vue": "^3.5.0"})

    status = get_yjs_collaboration_status(package_json)

    assert status["available"] is False
    assert status["backend"] == "rest_autosave_fallback"
    assert status["degraded"] is True
    assert "yjs" in status["missing_dependencies"]
    assert "REST autosave" in status["fallback"]


def test_yjs_collaboration_status_detects_declared_yjs_transport(tmp_path):
    from app.services.yjs_collaboration_service import get_yjs_collaboration_status

    package_json = tmp_path / "package.json"
    _write_package_json(package_json, {
        "vue": "^3.5.0",
        "yjs": "^13.6.0",
        "y-websocket": "^2.0.0",
    })

    status = get_yjs_collaboration_status(package_json)

    assert status["available"] is True
    assert status["backend"] == "yjs_client_ready"
    assert status["degraded"] is False
    assert status["dependencies"]["yjs"] == "^13.6.0"
    assert status["transport"] == "y-websocket"
    assert status["missing_dependencies"] == []


def test_yjs_collaboration_plan_keeps_rest_fallback_contract(tmp_path):
    from app.services.yjs_collaboration_service import build_yjs_collaboration_plan

    package_json = tmp_path / "package.json"
    _write_package_json(package_json, {})

    plan = build_yjs_collaboration_plan(package_json)

    assert plan["entrypoint"] == "script_scene_editor"
    assert {doc["id"] for doc in plan["documents"]} == {
        "scene_content",
        "workflow_context",
        "state_cards",
    }
    assert any("/scenes/{scene_number}/save" in doc["fallback_api"] for doc in plan["documents"])
    assert any("REST autosave" in gate for gate in plan["acceptance_gates"])


def test_yjs_collaboration_router_is_registered_and_uses_auth_override():
    from fastapi.testclient import TestClient

    from app.auth.dependencies import verify_admin
    from app.main import app

    app.dependency_overrides[verify_admin] = lambda: True
    try:
        client = TestClient(app)
        status_resp = client.get("/api/collaboration/yjs/status")
        plan_resp = client.get("/api/collaboration/yjs/plan")
    finally:
        app.dependency_overrides.pop(verify_admin, None)

    assert status_resp.status_code == 200, status_resp.text
    assert plan_resp.status_code == 200, plan_resp.text
    assert status_resp.json()["feature_id"] == "yjs_collaboration"
    assert plan_resp.json()["documents"]
