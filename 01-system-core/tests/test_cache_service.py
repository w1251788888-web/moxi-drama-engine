from datetime import datetime


def _reset_cache_service(monkeypatch):
    from app.services import cache_service

    monkeypatch.delenv("MOXI_REDIS_URL", raising=False)
    monkeypatch.delenv("REDIS_URL", raising=False)
    monkeypatch.delenv("MOXI_DASHBOARD_CACHE_TTL", raising=False)
    monkeypatch.setattr(cache_service, "_redis_checked", False)
    monkeypatch.setattr(cache_service, "_redis_client", None)
    monkeypatch.setattr(cache_service, "_redis_error", "")
    cache_service.clear_cache()
    return cache_service


def test_cache_service_degrades_to_memory_without_redis(monkeypatch):
    cache_service = _reset_cache_service(monkeypatch)
    calls = {"count": 0}

    def factory():
        calls["count"] += 1
        return {"generated_at": datetime(2026, 5, 9, 21, 0), "value": calls["count"]}

    first = cache_service.get_or_set_json("test:memory", 30, factory)
    second = cache_service.get_or_set_json("test:memory", 30, factory)
    status = cache_service.get_cache_status()

    assert calls["count"] == 1
    assert first == second
    assert first["generated_at"] == "2026-05-09T21:00:00"
    assert status["backend"] == "memory"
    assert status["redis_configured"] is False
    assert status["degraded"] is False


def test_cache_service_reports_degraded_when_redis_client_missing(monkeypatch):
    cache_service = _reset_cache_service(monkeypatch)
    monkeypatch.setenv("MOXI_REDIS_URL", "redis://127.0.0.1:6379/0")
    monkeypatch.setitem(__import__("sys").modules, "redis", None)
    monkeypatch.setattr(cache_service, "_redis_checked", False)

    status = cache_service.get_cache_status()

    assert status["backend"] == "memory"
    assert status["redis_configured"] is True
    assert status["redis_available"] is False
    assert status["degraded"] is True
    assert "redis" in status["redis_error"].lower()


def test_cache_service_uses_redis_when_available(monkeypatch):
    cache_service = _reset_cache_service(monkeypatch)
    store: dict[str, str] = {}

    class FakeRedisClient:
        def ping(self):
            return True

        def get(self, key):
            return store.get(key)

        def setex(self, key, ttl, value):
            del ttl
            store[key] = value

        def scan_iter(self, match, count=200):
            del count
            prefix = match[:-1] if match.endswith("*") else match
            return [key for key in store if key.startswith(prefix)]

        def delete(self, *keys):
            deleted = 0
            for key in keys:
                if key in store:
                    deleted += 1
                    store.pop(key)
            return deleted

    class FakeRedisModule:
        class Redis:
            @staticmethod
            def from_url(url, socket_timeout=0.5, socket_connect_timeout=0.5):
                del url, socket_timeout, socket_connect_timeout
                return FakeRedisClient()

    monkeypatch.setenv("MOXI_REDIS_URL", "redis://127.0.0.1:6379/0")
    monkeypatch.setitem(__import__("sys").modules, "redis", FakeRedisModule)
    monkeypatch.setattr(cache_service, "_redis_checked", False)

    cache_service.set_json("test:redis", {"value": "ok"}, ttl_seconds=30)
    status = cache_service.get_cache_status()

    assert cache_service.get_json("test:redis") == {"value": "ok"}
    assert status["backend"] == "redis"
    assert status["redis_available"] is True
    assert status["degraded"] is False


def test_admin_cache_routes_are_registered_and_admin_only():
    from fastapi.testclient import TestClient

    from app.auth.dependencies import verify_admin
    from app.main import app

    paths = set(app.openapi().get("paths", {}).keys())
    assert "/api/admin/cache/status" in paths
    assert "/api/admin/cache/clear" in paths

    client = TestClient(app)
    blocked = client.get("/api/admin/cache/status")
    assert blocked.status_code == 403

    app.dependency_overrides[verify_admin] = lambda: True
    try:
        allowed = client.get("/api/admin/cache/status")
        cleared = client.post("/api/admin/cache/clear")
    finally:
        app.dependency_overrides.pop(verify_admin, None)

    assert allowed.status_code == 200, allowed.text
    assert allowed.json()["backend"] in {"memory", "redis"}
    assert cleared.status_code == 200, cleared.text
    assert "memory_deleted" in cleared.json()


def test_dashboard_routes_use_cache_wrapper():
    from pathlib import Path

    source = (
        Path(__file__).resolve().parents[1]
        / "app"
        / "routers"
        / "admin_dashboard.py"
    ).read_text(encoding="utf-8")

    assert "cache_service.get_or_set_json(" in source
    assert "admin_dashboard:overview:v1" in source
    assert "admin_dashboard:highlights:v1" in source
    assert "admin_dashboard:trends:v1" in source
