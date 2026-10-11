from __future__ import annotations

import sys
from types import SimpleNamespace

from fastapi.testclient import TestClient


def _model_payload() -> dict[str, str]:
    return {
        "provider": "kimi",
        "api_key": "test-key",
        "model": "kimi-k2.6",
        "base_url": "https://api.example.test",
    }


def test_v2_config_write_and_test_routes_require_admin_token():
    from app.main import app

    client = TestClient(app)

    for path in (
        "/api/v2/config/save",
        "/api/v2/config/test",
        "/api/v2/config/providers/deepseek/models",
    ):
        response = client.post(path, json=_model_payload() if not path.endswith("/models") else {"api_key": "test-key", "base_url": "https://api.deepseek.com"})
        assert response.status_code == 403

    response = client.post("/api/v2/config/set-default/kimi")
    assert response.status_code == 403


def test_v2_config_read_routes_remain_available_for_project_creation():
    from app.main import app

    client = TestClient(app)

    providers = client.get("/api/v2/config/providers")
    current = client.get("/api/v2/config/current")

    assert providers.status_code == 200
    assert current.status_code == 200


def test_v2_config_provider_catalog_includes_deepseek():
    from app.main import app

    client = TestClient(app)

    response = client.get("/api/v2/config/providers")
    assert response.status_code == 200
    providers = {item["id"]: item for item in response.json()}
    assert "deepseek" in providers
    assert providers["deepseek"]["base_url"] == "https://api.deepseek.com"
    assert "deepseek-v4-flash" in {item["value"] for item in providers["deepseek"]["models"]}


def test_v2_config_save_and_set_default_still_work_for_admin(monkeypatch):
    from app.api.routes import config as config_routes
    from app.auth.dependencies import verify_admin
    from app.main import app

    saved: dict[str, object] = {}
    config = {
        "text_generation": {},
        "model_providers": {
            "kimi": {
                "default_model": "kimi-k2.5",
                "base_url": "https://api.moonshot.cn",
            },
        },
    }

    monkeypatch.setattr(config_routes, "get_config", lambda: config)
    monkeypatch.setattr(config_routes, "save_config", lambda payload: saved.update({"payload": payload}))
    app.dependency_overrides[verify_admin] = lambda: True
    client = TestClient(app)

    try:
        save_response = client.post("/api/v2/config/save", json=_model_payload())
        default_response = client.post("/api/v2/config/set-default/kimi")
    finally:
        app.dependency_overrides.pop(verify_admin, None)

    assert save_response.status_code == 200
    assert save_response.json()["success"] is True
    assert default_response.status_code == 200
    assert default_response.json()["success"] is True
    assert saved["payload"]["text_generation"]["provider"] == "kimi"
    assert saved["payload"]["model_providers"]["kimi"]["api_key"] == "test-key"


def test_v2_config_test_uses_admin_auth_and_existing_connection_contract(monkeypatch):
    from app.auth.dependencies import verify_admin
    from app.main import app

    class FakeResponse:
        status_code = 200
        text = '{"ok": true}'

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            self.args = args
            self.kwargs = kwargs

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, url, headers):
            assert url == "https://api.example.test/v1/models"
            assert headers["Authorization"] == "Bearer test-key"
            return FakeResponse()

    fake_httpx = SimpleNamespace(AsyncClient=FakeAsyncClient, ConnectError=ConnectionError)
    monkeypatch.setitem(sys.modules, "httpx", fake_httpx)
    app.dependency_overrides[verify_admin] = lambda: True
    client = TestClient(app)

    try:
        response = client.post("/api/v2/config/test", json=_model_payload())
    finally:
        app.dependency_overrides.pop(verify_admin, None)

    assert response.status_code == 200
    assert response.json()["success"] is True


def test_v2_config_fetches_deepseek_model_list_from_official_models_endpoint(monkeypatch):
    from app.api.routes import config as config_routes
    from app.auth.dependencies import verify_admin
    from app.main import app

    class FakeResponse:
        status_code = 200
        text = '{"data":[]}'

        def json(self):
            return {
                "data": [
                    {"id": "deepseek-v4-flash"},
                    {"id": "deepseek-v4-pro"},
                ]
            }

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, url, headers):
            assert url == "https://api.deepseek.com/models"
            assert headers["Authorization"] == "Bearer sk-deepseek"
            return FakeResponse()

    fake_httpx = SimpleNamespace(AsyncClient=FakeAsyncClient, ConnectError=ConnectionError)
    monkeypatch.setitem(sys.modules, "httpx", fake_httpx)
    monkeypatch.setattr(config_routes, "get_config", lambda: {"model_providers": {}})
    app.dependency_overrides[verify_admin] = lambda: True
    client = TestClient(app)

    try:
        response = client.post(
            "/api/v2/config/providers/deepseek/models",
            json={"api_key": "sk-deepseek", "base_url": "https://api.deepseek.com"},
        )
    finally:
        app.dependency_overrides.pop(verify_admin, None)

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert [item["value"] for item in payload["data"]["models"]] == ["deepseek-v4-flash", "deepseek-v4-pro"]


def test_text_generation_url_join_avoids_double_v1_and_uses_deepseek_current_endpoint():
    from app.services.text_generation_service import _join_generation_url, _resolve_generation_endpoint

    assert (
        _join_generation_url("https://api.moonshot.cn/v1", "/v1/chat/completions")
        == "https://api.moonshot.cn/v1/chat/completions"
    )
    assert (
        _resolve_generation_endpoint("deepseek", "https://api.deepseek.com", "/v1/chat/completions")
        == "/chat/completions"
    )


def test_v2_config_test_allows_https_public_ipv6_literal(monkeypatch):
    from app.auth.dependencies import verify_admin
    from app.main import app

    class FakeResponse:
        status_code = 200
        text = '{"ok": true}'

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, url, headers):
            assert url == "https://[2001:4860:4860::8888]/v1/models"
            return FakeResponse()

    fake_httpx = SimpleNamespace(AsyncClient=FakeAsyncClient, ConnectError=ConnectionError)
    monkeypatch.setitem(sys.modules, "httpx", fake_httpx)
    app.dependency_overrides[verify_admin] = lambda: True
    client = TestClient(app)

    try:
        response = client.post(
            "/api/v2/config/test",
            json={**_model_payload(), "base_url": "https://[2001:4860:4860::8888]"},
        )
    finally:
        app.dependency_overrides.pop(verify_admin, None)

    assert response.status_code == 200
    assert response.json()["success"] is True


def test_v2_config_save_and_test_reject_unsafe_base_urls(monkeypatch):
    from app.api.routes import config as config_routes
    from app.auth.dependencies import verify_admin
    from app.main import app

    monkeypatch.setattr(config_routes, "get_config", lambda: {"security": {}})
    monkeypatch.setattr(
        config_routes,
        "save_config",
        lambda payload: (_ for _ in ()).throw(AssertionError("save_config should not be called")),
    )
    app.dependency_overrides[verify_admin] = lambda: True
    client = TestClient(app)

    try:
        for base_url in (
            "http://api.example.test",
            "https://localhost:6565",
            "http://127.0.0.1:6565",
            "http://169.254.169.254/latest/meta-data",
            "https://metadata.google.internal",
            "https://internal-host",
            "https://api.local",
            "https://[::1]",
            "https://[fc00::1]",
            "file:///tmp/model-api",
            "https://user:pass@api.example.test",
            "https://api.example.test?debug=true",
            "https://api.example.test#models",
        ):
            payload = {**_model_payload(), "base_url": base_url}
            test_response = client.post("/api/v2/config/test", json=payload)
            save_response = client.post("/api/v2/config/save", json=payload)
            assert test_response.status_code == 400, base_url
            assert save_response.status_code == 400, base_url
    finally:
        app.dependency_overrides.pop(verify_admin, None)


def test_v2_config_test_can_explicitly_allow_insecure_url_for_local_debug(monkeypatch):
    from app.api.routes import config as config_routes
    from app.auth.dependencies import verify_admin
    from app.main import app

    class FakeResponse:
        status_code = 200
        text = '{"ok": true}'

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, url, headers):
            assert url == "http://api.example.test/v1/models"
            return FakeResponse()

    fake_httpx = SimpleNamespace(AsyncClient=FakeAsyncClient, ConnectError=ConnectionError)
    monkeypatch.setitem(sys.modules, "httpx", fake_httpx)
    monkeypatch.setenv("MOXI_ALLOW_INSECURE_MODEL_BASE_URLS", "true")
    monkeypatch.setattr(config_routes, "get_config", lambda: {"security": {}})
    app.dependency_overrides[verify_admin] = lambda: True
    client = TestClient(app)

    try:
        response = client.post(
            "/api/v2/config/test",
            json={**_model_payload(), "base_url": "http://api.example.test"},
        )
    finally:
        app.dependency_overrides.pop(verify_admin, None)

    assert response.status_code == 200
    assert response.json()["success"] is True
