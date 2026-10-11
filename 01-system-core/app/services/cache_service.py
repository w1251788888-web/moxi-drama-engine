"""
可降级缓存服务。

优先使用 Redis；未配置、未安装客户端或连接失败时自动退回进程内 TTL 缓存。
"""
from __future__ import annotations

import json
import os
import threading
import time
from datetime import date, datetime
from typing import Any, Callable

from app.config import config


DEFAULT_TTL_SECONDS = 15
MAX_TTL_SECONDS = 3600


class _MemoryTTLCache:
    def __init__(self) -> None:
        self._items: dict[str, tuple[float, Any]] = {}
        self._lock = threading.RLock()

    def get(self, key: str) -> Any | None:
        now = time.time()
        with self._lock:
            record = self._items.get(key)
            if not record:
                return None
            expires_at, value = record
            if expires_at <= now:
                self._items.pop(key, None)
                return None
            return value

    def set(self, key: str, value: Any, ttl_seconds: int) -> None:
        ttl = _clamp_ttl(ttl_seconds)
        with self._lock:
            self._items[key] = (time.time() + ttl, value)

    def clear(self, prefix: str | None = None) -> int:
        with self._lock:
            if not prefix:
                count = len(self._items)
                self._items.clear()
                return count
            keys = [key for key in self._items if key.startswith(prefix)]
            for key in keys:
                self._items.pop(key, None)
            return len(keys)

    def size(self) -> int:
        now = time.time()
        with self._lock:
            expired = [key for key, (expires_at, _) in self._items.items() if expires_at <= now]
            for key in expired:
                self._items.pop(key, None)
            return len(self._items)


_memory_cache = _MemoryTTLCache()
_redis_client: Any | None = None
_redis_checked = False
_redis_error: str = ""
_redis_lock = threading.RLock()


def get_or_set_json(
    key: str,
    ttl_seconds: int,
    factory: Callable[[], Any],
) -> Any:
    """读取 JSON 缓存；未命中时执行 factory 并写入缓存。"""
    cached = get_json(key)
    if cached is not None:
        return cached
    value = _to_jsonable(factory())
    set_json(key, value, ttl_seconds)
    return value


def get_json(key: str) -> Any | None:
    namespaced_key = _namespaced_key(key)
    redis_client = _get_redis_client()
    if redis_client is not None:
        try:
            raw = redis_client.get(namespaced_key)
            if raw is not None:
                if isinstance(raw, bytes):
                    raw = raw.decode("utf-8")
                return json.loads(raw)
        except Exception as exc:
            _mark_redis_unavailable(exc)
    return _memory_cache.get(namespaced_key)


def set_json(key: str, value: Any, ttl_seconds: int = DEFAULT_TTL_SECONDS) -> None:
    namespaced_key = _namespaced_key(key)
    payload = _to_jsonable(value)
    redis_client = _get_redis_client()
    if redis_client is not None:
        try:
            redis_client.setex(namespaced_key, _clamp_ttl(ttl_seconds), json.dumps(payload, ensure_ascii=False))
            return
        except Exception as exc:
            _mark_redis_unavailable(exc)
    _memory_cache.set(namespaced_key, payload, ttl_seconds)


def clear_cache(prefix: str | None = None) -> dict[str, Any]:
    namespaced_prefix = _namespaced_key(prefix) if prefix else _namespace()
    memory_deleted = _memory_cache.clear(namespaced_prefix if prefix else None)
    redis_deleted = 0
    redis_client = _get_redis_client()
    if redis_client is not None:
        try:
            pattern = f"{namespaced_prefix}*"
            keys = list(redis_client.scan_iter(match=pattern, count=200))
            if keys:
                redis_deleted = int(redis_client.delete(*keys) or 0)
        except Exception as exc:
            _mark_redis_unavailable(exc)
    return {
        "memory_deleted": memory_deleted,
        "redis_deleted": redis_deleted,
        "prefix": prefix or "",
    }


def dashboard_ttl_seconds() -> int:
    raw = (
        os.getenv("MOXI_DASHBOARD_CACHE_TTL")
        or os.getenv("DASHBOARD_CACHE_TTL")
        or _cache_config().get("dashboard_ttl_seconds")
        or _cache_config().get("ttl_seconds")
        or DEFAULT_TTL_SECONDS
    )
    try:
        return _clamp_ttl(int(raw))
    except Exception:
        return DEFAULT_TTL_SECONDS


def get_cache_status() -> dict[str, Any]:
    redis_url = _redis_url()
    redis_client = _get_redis_client()
    backend = "redis" if redis_client is not None else "memory"
    return {
        "backend": backend,
        "redis_configured": bool(redis_url),
        "redis_available": redis_client is not None,
        "redis_error": _redis_error,
        "memory_entries": _memory_cache.size(),
        "dashboard_ttl_seconds": dashboard_ttl_seconds(),
        "degraded": bool(redis_url) and redis_client is None,
    }


def _get_redis_client():
    global _redis_checked, _redis_client, _redis_error
    redis_url = _redis_url()
    if not redis_url:
        return None
    with _redis_lock:
        if _redis_checked:
            return _redis_client
        _redis_checked = True
        try:
            import redis  # type: ignore
        except Exception as exc:
            _redis_client = None
            _redis_error = f"redis client unavailable: {exc}"
            return None
        try:
            client = redis.Redis.from_url(redis_url, socket_timeout=0.5, socket_connect_timeout=0.5)
            client.ping()
            _redis_client = client
            _redis_error = ""
            return _redis_client
        except Exception as exc:
            _redis_client = None
            _mark_redis_unavailable(exc)
            return None


def _mark_redis_unavailable(exc: Exception) -> None:
    global _redis_client, _redis_error
    _redis_client = None
    _redis_error = str(exc)[:300]


def _cache_config() -> dict[str, Any]:
    raw = config.raw.get("cache", {})
    return raw if isinstance(raw, dict) else {}


def _redis_url() -> str:
    return str(
        os.getenv("MOXI_REDIS_URL")
        or os.getenv("REDIS_URL")
        or _cache_config().get("redis_url")
        or ""
    ).strip()


def _namespace() -> str:
    raw = str(_cache_config().get("namespace") or os.getenv("MOXI_CACHE_NAMESPACE") or "moxi")
    safe = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in raw)
    return f"{safe}:"


def _namespaced_key(key: str | None) -> str:
    return f"{_namespace()}{key or ''}"


def _clamp_ttl(ttl_seconds: int) -> int:
    return max(1, min(int(ttl_seconds or DEFAULT_TTL_SECONDS), MAX_TTL_SECONDS))


def _to_jsonable(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _to_jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_to_jsonable(item) for item in value]
    return value
