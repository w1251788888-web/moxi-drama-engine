"""
最小文本生成服务。
支持普通生成（generate_text / generate_json）和流式生成（generate_text_stream）。
"""
from __future__ import annotations

import contextvars
import hashlib
import json
import os
import re
import time
from collections.abc import Iterator
from typing import Any
from urllib.parse import urlparse

import httpx

from app.config import config


MODEL_PROVIDERS_ENV_VAR = "MOXI_MODEL_PROVIDERS_JSON"


class TextGenerationError(RuntimeError):
    """文本生成失败。

    所有子类都暴露 user_message / suggestion / http_status 三个属性，
    供路由层把异常转成可解释的前端提示。
    """

    code: str = "generation_failed"
    user_message: str = "AI 生成失败。"
    suggestion: str = "请稍后重试，或联系管理员检查后端日志。"
    http_status: int = 502


class TextGenerationConfigError(TextGenerationError):
    """模型未配置 / 未开启。"""

    code = "config_missing"
    user_message = "AI 模型尚未配置。"
    suggestion = "前往「我的账号 → 模型设置」完成 base_url、api_key、model 配置后再试。"
    http_status = 503


class TextGenerationAuthError(TextGenerationError):
    """API key 错误或权限不足。"""

    code = "auth_failed"
    user_message = "AI 模型鉴权失败。"
    suggestion = "API Key 无效或已过期，请到「我的账号 → 模型设置」更新后重试。"
    http_status = 502


class TextGenerationRateLimitError(TextGenerationError):
    """上游 429 / 限流。"""

    code = "rate_limited"
    user_message = "AI 模型当前限流。"
    suggestion = "上游模型 429 限流，请等待 30 秒后重试，或切换到备用模型。"
    http_status = 429


class TextGenerationContextLengthError(TextGenerationError):
    """提示词超长 / token 超限。"""

    code = "context_too_long"
    user_message = "提示词长度超过模型上限。"
    suggestion = "正在生成的内容过长。请缩短大纲、减少历史上下文，或换支持更长上下文的模型。"
    http_status = 413


class TextGenerationOutputTruncatedError(TextGenerationError):
    """模型输出被 max_tokens 截断，返回内容不完整。"""

    code = "output_truncated"
    user_message = "模型输出被截断，返回内容不完整。"
    suggestion = "请分阶段确认大纲资料包，或减少单次生成内容；不要把半截结果当成正式大纲。"
    http_status = 502


class TextGenerationNetworkError(TextGenerationError):
    """网络/超时/连接错误。"""

    code = "network_error"
    user_message = "无法连接到 AI 模型。"
    suggestion = "网络异常或上游服务不可达。检查网络或 base_url 是否正确，稍后重试。"
    http_status = 504


class TextGenerationUpstreamError(TextGenerationError):
    """上游 5xx 等其他错误。"""

    code = "upstream_error"
    user_message = "AI 模型上游报错。"
    suggestion = "上游模型暂时不可用，请稍后重试或更换模型。"
    http_status = 502


def _safe_label(value: Any, *, max_length: int = 64) -> str:
    text = str(value or "").strip().lower()
    text = re.sub(r"[^a-z0-9_.:-]+", "_", text)
    return text[:max_length].strip("_")


def _model_label_hash(model: Any) -> str:
    text = str(model or "").strip()
    if not text:
        return ""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _provider_failure_subtype(exc: Exception) -> str:
    if isinstance(exc, httpx.ReadTimeout):
        return "read_timeout"
    if isinstance(exc, httpx.ConnectTimeout):
        return "connect_timeout"
    if isinstance(exc, httpx.PoolTimeout):
        return "pool_timeout"
    if isinstance(exc, httpx.TimeoutException):
        return "timeout"
    if isinstance(exc, httpx.ConnectError):
        return "connect_error"
    if isinstance(exc, httpx.ReadError):
        return "read_error"
    if isinstance(exc, httpx.RemoteProtocolError):
        return "stream_interruption"
    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code if exc.response is not None else 0
        if status in (401, 403):
            return "auth_failed"
        if status == 429:
            return "rate_limited"
        if status in (400, 422):
            return "upstream_bad_request_or_model"
        if status == 408:
            return "request_timeout"
        if status == 413:
            return "context_too_long"
        if 500 <= status < 600:
            return "upstream_http_5xx"
        return "upstream_http_4xx_or_other" if 400 <= status < 500 else "upstream_http_status"
    if isinstance(exc, TextGenerationConfigError):
        return "config_missing"
    if isinstance(exc, TextGenerationAuthError):
        return "auth_failed"
    if isinstance(exc, TextGenerationRateLimitError):
        return "rate_limited"
    if isinstance(exc, TextGenerationContextLengthError):
        return "context_too_long"
    if isinstance(exc, TextGenerationOutputTruncatedError):
        return "output_truncated"
    if isinstance(exc, TextGenerationNetworkError):
        message = str(exc).lower()
        if "first_token_timeout" in message or ("first token" in message and "timeout" in message):
            return "first_token_timeout"
        if "read" in message and "timeout" in message:
            return "read_timeout"
        if "connect" in message and "timeout" in message:
            return "connect_timeout"
        if "timeout" in message or "timed out" in message:
            return "timeout"
        if "connect" in message:
            return "connect_error"
        if "protocol" in message or "stream" in message:
            return "stream_interruption"
        return "network_error"
    if isinstance(exc, TextGenerationUpstreamError):
        return "upstream_error"
    if isinstance(exc, TextGenerationError):
        return _safe_label(exc.code) or "generation_failed"
    return "generation_failed"


def build_provider_runtime_observability(
    exc: Exception,
    *,
    timeout_seconds: int | float | None = None,
    first_token_timeout_seconds: int | float | None = None,
    max_retries: int | None = None,
    provider_role: str | None = None,
    route: str | None = None,
    model: str | None = None,
    watchdog_phase: str | None = None,
) -> dict[str, Any]:
    """Return safe provider-runtime observability without raw payload details."""
    timeout_value: int | float | None = None
    if timeout_seconds is not None:
        timeout_value = float(timeout_seconds)
        if timeout_value.is_integer():
            timeout_value = int(timeout_value)
    first_token_timeout_value: int | float | None = None
    if first_token_timeout_seconds is not None:
        first_token_timeout_value = float(first_token_timeout_seconds)
        if first_token_timeout_value.is_integer():
            first_token_timeout_value = int(first_token_timeout_value)
    return {
        "failure_layer": "provider_runtime",
        "safe_failure_subtype": _provider_failure_subtype(exc),
        "timeout_seconds_effective": timeout_value,
        "first_token_timeout_seconds_effective": first_token_timeout_value,
        "max_retries": int(max_retries) if max_retries is not None else None,
        "provider_role": _safe_label(provider_role),
        "route": _safe_label(route),
        "model_label_hash": _model_label_hash(model),
        "watchdog_phase": _safe_label(watchdog_phase),
        "raw_error_present": False,
        "raw_request_present": False,
        "raw_response_present": False,
    }


def classify_generation_exception(exc: Exception) -> TextGenerationError:
    """把任意异常归类为带可解释提示的 TextGenerationError 子类。

    已经是 TextGenerationError 子类的（如 ConfigError）原样返回。
    """
    if isinstance(exc, TextGenerationError):
        return exc

    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code if exc.response is not None else 0
        body = ""
        try:
            body = exc.response.text if exc.response is not None else ""
        except Exception:  # pragma: no cover
            body = ""
        if status in (401, 403):
            return TextGenerationAuthError(f"鉴权失败 (HTTP {status})")
        if status == 429:
            return TextGenerationRateLimitError("上游限流 (HTTP 429)")
        if status == 413 or "context_length" in body.lower() or "too long" in body.lower() or "maximum context" in body.lower():
            return TextGenerationContextLengthError(f"提示词超长 (HTTP {status})")
        if 500 <= status < 600:
            return TextGenerationUpstreamError(f"上游 {status}")
        return TextGenerationUpstreamError(f"HTTP {status}")

    if isinstance(exc, (httpx.TimeoutException, httpx.ConnectError, httpx.ReadError, httpx.NetworkError)):
        return TextGenerationNetworkError(f"网络错误: {_provider_failure_subtype(exc)}")

    return TextGenerationError("未分类错误")


def _raise_if_generation_truncated(data: Any) -> None:
    """Reject partial LLM output when upstream explicitly reports truncation."""
    if not isinstance(data, dict):
        return

    finish_reasons: list[str] = []
    choices = data.get("choices")
    if isinstance(choices, list):
        for choice in choices:
            if isinstance(choice, dict):
                reason = choice.get("finish_reason") or choice.get("stop_reason")
                if reason is not None:
                    finish_reasons.append(str(reason).strip().lower())

    for key in ("finish_reason", "stop_reason", "stopReason"):
        reason = data.get(key)
        if reason is not None:
            finish_reasons.append(str(reason).strip().lower())

    if any(reason in {"length", "max_tokens", "max_output_tokens"} for reason in finish_reasons):
        raise TextGenerationOutputTruncatedError(
            "文本生成接口返回 finish_reason=length，说明输出被 token 上限截断。"
        )


_USAGE_COLLECTOR: contextvars.ContextVar[dict[str, Any] | None] = contextvars.ContextVar(
    "text_generation_usage_collector",
    default=None,
)
_TIKTOKEN_ENCODER = None


def begin_usage_collection(initial: dict[str, Any] | None = None) -> tuple[dict[str, Any], contextvars.Token]:
    collector = initial or {}
    collector.setdefault("call_count", 0)
    collector.setdefault("input_tokens", 0)
    collector.setdefault("cached_input_tokens", 0)
    collector.setdefault("uncached_input_tokens", 0)
    collector.setdefault("output_tokens", 0)
    collector.setdefault("total_tokens", 0)
    collector.setdefault("elapsed_seconds", 0.0)
    collector.setdefault("estimated", False)
    collector.setdefault("calls", [])
    token = _USAGE_COLLECTOR.set(collector)
    return collector, token


def end_usage_collection(token: contextvars.Token) -> None:
    _USAGE_COLLECTOR.reset(token)


def _generation_settings() -> dict[str, Any]:
    raw = config.raw.get("text_generation") or {}
    if not isinstance(raw, dict):
        return {}
    return raw


def _coerce_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    return default


def generation_enabled() -> bool:
    settings = _generation_settings()
    return _coerce_bool(settings.get("enabled"), False)


def _resolve_generation_endpoint(provider: str, base_url: str, endpoint: str) -> str:
    """按供应商修正默认生成路径；保留用户显式设置的自定义路径。"""
    configured = str(endpoint or "/v1/chat/completions").strip() or "/v1/chat/completions"
    provider_key = str(provider or "").strip().lower()
    if configured != "/v1/chat/completions":
        return configured if configured.startswith("/") else f"/{configured}"

    parsed = urlparse(str(base_url or ""))
    host = (parsed.hostname or "").lower()
    path = parsed.path.rstrip("/")
    if provider_key == "deepseek" and host.endswith("deepseek.com") and not path.endswith("/v1"):
        return "/chat/completions"
    return configured


def _join_generation_url(base_url: str, endpoint: str) -> str:
    base = str(base_url or "").strip().rstrip("/")
    path = str(endpoint or "").strip()
    path = path if path.startswith("/") else f"/{path}"
    if base.endswith("/v1") and path.startswith("/v1/"):
        path = path[3:]
    return f"{base}{path}"


def _safe_probe_http_failure(status_code: int) -> tuple[str, str]:
    if status_code in {401, 403}:
        return "upstream_auth_or_permission", "模型访问鉴权或权限失败。"
    if status_code == 429:
        return "upstream_rate_or_quota", "模型服务限流或额度不足。"
    if status_code == 404:
        return "upstream_endpoint_not_found", "模型接口路径不可用。"
    if status_code in {400, 422}:
        return "upstream_bad_request_or_model", "模型请求参数或模型来源不兼容。"
    if status_code >= 500:
        return "upstream_server_error", "模型上游暂时不可用。"
    if 400 <= status_code < 500:
        return "upstream_http_4xx_or_other", "模型服务返回客户端侧非成功状态。"
    return "upstream_http_other", "模型服务返回非成功状态。"


def check_llm_reachable(
    timeout_seconds: float = 5.0,
    *,
    provider: str | None = None,
    model: str | None = None,
    base_url: str | None = None,
    api_key: str | None = None,
) -> dict[str, Any]:
    """快速探活当前 text_generation 配置是否真的能调通。

    返回 {ok: bool, detail: str, latency_ms: int}
    用于前端在打开 LLM-依赖页面（如分镜）时提前判定，
    避免用户点了按钮再死等 120s 才知道连不通。

    设计为「最小代价」探活：
    - 不真正生成，只发一个最短 prompt + max_tokens=1
    - 短超时（默认 5s），让前端能快速给出反馈
    - 任何异常都吞掉，统一返回 ok=False + 中文 detail
    """
    try:
        settings = get_generation_settings(
            provider=provider,
            model=model,
            base_url=base_url,
            api_key=api_key,
        )
    except TextGenerationConfigError:
        return {
            "ok": False,
            "detail": "管理员模型配置读取失败。",
            "detail_category": "config_provider_lookup_failed",
            "latency_ms": 0,
            "safe_failure_subtype": "config_missing",
        }
    if not settings.get("enabled"):
        return {
            "ok": False,
            "detail": "LLM 服务未启用。",
            "detail_category": "config_disabled",
            "latency_ms": 0,
            "safe_failure_subtype": "config_missing",
        }

    base_url = str(settings.get("base_url") or "").strip().rstrip("/")
    api_key = str(settings.get("api_key") or "").strip()
    model = str(settings.get("model") or "").strip()
    provider = str(settings.get("provider") or "").strip()
    endpoint = _resolve_generation_endpoint(provider, base_url, str(settings.get("endpoint") or "/v1/chat/completions").strip())

    if not base_url:
        return {"ok": False, "detail": "未配置模型服务地址。", "detail_category": "config_missing_base_url", "latency_ms": 0, "safe_failure_subtype": "config_missing"}
    if not api_key:
        return {"ok": False, "detail": "未配置模型访问凭据。", "detail_category": "config_missing_api_key", "latency_ms": 0, "safe_failure_subtype": "config_missing"}
    if not model:
        return {"ok": False, "detail": "未配置模型名称。", "detail_category": "config_missing_model", "latency_ms": 0, "safe_failure_subtype": "config_missing"}

    url = _join_generation_url(base_url, endpoint)
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": "ping"}],
        "max_tokens": 1,
        "temperature": 0,
    }
    payload = _apply_model_compat_payload(payload)

    started = time.perf_counter()
    try:
        with httpx.Client(timeout=timeout_seconds, verify=get_ssl_verify()) as client:
            resp = client.post(url, json=payload, headers=headers)
        latency_ms = int((time.perf_counter() - started) * 1000)
        if resp.status_code != 200:
            category, detail = _safe_probe_http_failure(int(resp.status_code))
            return {
                "ok": False,
                "detail": detail,
                "detail_category": category,
                "latency_ms": latency_ms,
                "safe_failure_subtype": category,
                "status_code": int(resp.status_code),
            }
        return {
            "ok": True,
            "detail": "模型服务已连通。",
            "detail_category": "reachable",
            "latency_ms": latency_ms,
            "safe_failure_subtype": "none",
            "model_label_hash": _model_label_hash(model),
        }
    except httpx.ConnectError as exc:
        return {
            "ok": False,
            "detail": "无法连接模型服务。",
            "detail_category": "connect_error",
            "latency_ms": int((time.perf_counter() - started) * 1000),
            "safe_failure_subtype": _provider_failure_subtype(exc),
        }
    except httpx.TimeoutException as exc:
        return {
            "ok": False,
            "detail": "模型服务探活超时。",
            "detail_category": "timeout",
            "latency_ms": int((time.perf_counter() - started) * 1000),
            "safe_failure_subtype": _provider_failure_subtype(exc),
            "timeout_seconds_effective": timeout_seconds,
        }
    except Exception as exc:  # pragma: no cover
        return {
            "ok": False,
            "detail": "模型服务探活异常。",
            "detail_category": "probe_exception",
            "latency_ms": int((time.perf_counter() - started) * 1000),
            "safe_failure_subtype": _provider_failure_subtype(exc),
        }


def get_ssl_verify() -> bool:
    """读取 text_generation.ssl_verify 配置（默认 True）。
    设为 False 可绕过 TLS 证书验证，适用于企业代理/自签名证书环境。
    """
    env_value = os.getenv("MOXI_TEXT_GENERATION_SSL_VERIFY")
    if env_value is not None:
        return _coerce_bool(env_value, True)
    return _coerce_bool(_generation_settings().get("ssl_verify"), True)


def _resolve_env_value(value: str) -> str:
    if value.startswith("${") and value.endswith("}"):
        return os.getenv(value[2:-1], "")
    return value


def _env_provider_settings(provider: str | None) -> dict[str, Any]:
    provider_key = str(provider or "").strip()
    if not provider_key:
        return {}
    raw = os.getenv(MODEL_PROVIDERS_ENV_VAR, "")
    if not raw:
        return {}
    try:
        providers = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    if not isinstance(providers, dict):
        return {}
    value = providers.get(provider_key) or {}
    return value if isinstance(value, dict) else {}


def _provider_settings(provider: str | None) -> dict[str, Any]:
    if not provider:
        return {}
    raw = config.raw.get("model_providers") or {}
    if not isinstance(raw, dict):
        raw = {}
    value = raw.get(provider) or {}
    config_settings = value if isinstance(value, dict) else {}
    env_settings = _env_provider_settings(provider)
    if not env_settings:
        return config_settings
    return {**config_settings, **env_settings}


def _database_provider_settings(provider: str | None) -> dict[str, Any]:
    provider_key = str(provider or "").strip()
    try:
        from app import database
        from app.models.saas_admin import LLMProviderSetting
        from app.services.saas_secret_service import decrypt_secret, encrypt_secret

        with database.SessionLocal() as db:
            query = db.query(LLMProviderSetting)
            if provider_key:
                row = query.filter(LLMProviderSetting.provider == provider_key).first()
            else:
                row = (
                    query
                    .filter(LLMProviderSetting.is_active.is_(True))
                    .order_by(
                        LLMProviderSetting.is_default.desc(),
                        LLMProviderSetting.updated_at.desc(),
                    )
                    .first()
                )
            if row is None:
                return {}
            encrypted_api_key = str(row.api_key_encrypted or "")
            decrypted_api_key = decrypt_secret(encrypted_api_key)
            if (
                encrypted_api_key.startswith("moxi1:")
                and (
                    not decrypted_api_key
                    or encrypt_secret(decrypted_api_key) != encrypted_api_key
                )
            ):
                raise TextGenerationConfigError("管理员模型配置读取失败")
            return {
                "provider": str(row.provider or ""),
                "base_url": str(row.base_url or ""),
                "api_key": decrypted_api_key,
                "default_model": str(row.default_model or ""),
            }
    except TextGenerationConfigError:
        raise
    except Exception as exc:
        raise TextGenerationConfigError("管理员模型配置读取失败") from exc


def get_generation_settings(
    *,
    provider: str | None = None,
    model: str | None = None,
    base_url: str | None = None,
    api_key: str | None = None,
) -> dict[str, Any]:
    settings = _generation_settings()
    enabled = _coerce_bool(settings.get("enabled"), False)
    requested_provider = str(provider or "").strip()
    explicit_bundle_complete = all(
        str(value or "").strip()
        for value in (requested_provider, base_url, api_key, model)
    )
    database_settings = (
        {}
        if explicit_bundle_complete
        else _database_provider_settings(requested_provider or None)
    )
    resolved_provider = str(
        requested_provider
        or database_settings.get("provider")
        or settings.get("provider")
        or ""
    ).strip()
    provider_settings = _provider_settings(resolved_provider)
    explicit_provider_requested = bool(requested_provider)
    has_provider_specific_settings = bool(provider_settings or database_settings)

    if str(base_url or "").strip():
        resolved_base_url = str(base_url or "")
    elif "base_url" in database_settings:
        resolved_base_url = str(database_settings.get("base_url") or "")
    elif "base_url" in provider_settings:
        resolved_base_url = str(provider_settings.get("base_url") or "")
    elif explicit_provider_requested and not has_provider_specific_settings:
        resolved_base_url = ""
    else:
        resolved_base_url = str(settings.get("base_url") or "")
    base_url = _resolve_env_value(resolved_base_url).rstrip("/")

    if str(api_key or "").strip():
        resolved_api_key = str(api_key or "")
    elif "api_key" in database_settings:
        resolved_api_key = str(database_settings.get("api_key") or "")
    elif "api_key" in provider_settings:
        resolved_api_key = str(provider_settings.get("api_key") or "")
    elif explicit_provider_requested and not has_provider_specific_settings:
        resolved_api_key = ""
    else:
        resolved_api_key = str(settings.get("api_key") or "")
    api_key = _resolve_env_value(resolved_api_key)

    if str(model or "").strip():
        resolved_model = str(model or "")
    elif "default_model" in database_settings:
        resolved_model = str(database_settings.get("default_model") or "")
    elif provider_settings.get("default_model"):
        resolved_model = str(provider_settings.get("default_model") or "")
    elif explicit_provider_requested and not has_provider_specific_settings:
        resolved_model = ""
    else:
        resolved_model = str(settings.get("model") or "")
    model = _resolve_env_value(resolved_model)
    timeout = int(settings.get("timeout_seconds") or 120)
    endpoint = _resolve_generation_endpoint(
        resolved_provider,
        base_url,
        str(settings.get("endpoint") or "/v1/chat/completions"),
    )
    temperature = float(settings.get("temperature") or 0.7)
    max_retries = int(settings.get("max_retries") or 3)
    retry_backoff_seconds = float(settings.get("retry_backoff_seconds") or 2)
    # ssl_verify=False 可绕过证书验证（适用于企业代理、自签名证书等环境）
    ssl_verify = get_ssl_verify()

    return {
        "enabled": enabled,
        "provider": resolved_provider,
        "base_url": base_url,
        "api_key": api_key,
        "model": model,
        "timeout_seconds": timeout,
        "endpoint": endpoint,
        "temperature": temperature,
        "max_retries": max_retries,
        "retry_backoff_seconds": retry_backoff_seconds,
        "ssl_verify": ssl_verify,
    }


def _require_settings(
    *,
    provider: str | None = None,
    model: str | None = None,
    base_url: str | None = None,
    api_key: str | None = None,
) -> dict[str, Any]:
    settings = get_generation_settings(
        provider=provider,
        model=model,
        base_url=base_url,
        api_key=api_key,
    )
    if not settings["enabled"]:
        raise TextGenerationConfigError("text_generation.enabled 未开启")
    if not settings["base_url"]:
        raise TextGenerationConfigError("text_generation.base_url 未配置")
    if not settings["api_key"]:
        raise TextGenerationConfigError("text_generation.api_key 未配置")
    if not settings["model"]:
        raise TextGenerationConfigError("text_generation.model 未配置")
    return settings


def _is_kimi_k25_series(model: str) -> bool:
    normalized = str(model or "").strip().lower()
    return normalized.startswith("kimi-k2.5") or normalized.startswith("kimi-k2.6")


def _apply_model_compat_payload(payload: dict[str, Any]) -> dict[str, Any]:
    model = str(payload.get("model") or "").strip()
    if not _is_kimi_k25_series(model):
        return payload

    adjusted = dict(payload)
    thinking = adjusted.get("thinking")
    if not isinstance(thinking, dict):
        # 文本工作流默认关闭 K2.5/K2.6 思考模式，保持和现有短剧生成链一致的速度与可控性。
        thinking = {"type": "disabled"}
        adjusted["thinking"] = thinking

    thinking_type = str(thinking.get("type") or "").strip().lower()
    adjusted["temperature"] = 0.6 if thinking_type == "disabled" else 1.0
    return adjusted


def _estimate_token_count(text: str) -> int:
    raw = str(text or "")
    if not raw.strip():
        return 0
    global _TIKTOKEN_ENCODER
    try:
        if _TIKTOKEN_ENCODER is None:
            import tiktoken  # type: ignore

            _TIKTOKEN_ENCODER = tiktoken.get_encoding("cl100k_base")
        return int(len(_TIKTOKEN_ENCODER.encode(raw)))
    except Exception:
        compact = "".join(ch for ch in raw if not ch.isspace())
        return max(1, int(len(compact) * 1.45))


def _extract_usage_metrics(data: dict[str, Any], payload: dict[str, Any], *, elapsed_seconds: float, provider: str) -> dict[str, Any]:
    usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}
    prompt_tokens = int(
        usage.get("prompt_tokens")
        or usage.get("input_tokens")
        or usage.get("prompt_token_count")
        or 0
    )
    completion_tokens = int(
        usage.get("completion_tokens")
        or usage.get("output_tokens")
        or usage.get("completion_token_count")
        or 0
    )
    cached_tokens = int(
        usage.get("prompt_cache_hit_tokens")
        or usage.get("cache_read_input_tokens")
        or usage.get("cached_input_tokens")
        or usage.get("input_cached_tokens")
        or usage.get("cached_tokens")
        or 0
    )
    uncached_tokens = int(
        usage.get("prompt_cache_miss_tokens")
        or usage.get("cache_creation_input_tokens")
        or usage.get("uncached_input_tokens")
        or usage.get("input_miss_tokens")
        or 0
    )
    total_tokens = int(usage.get("total_tokens") or 0)
    estimated = False

    if not prompt_tokens:
        prompt_text = "\n".join(
            str(item.get("content") or "")
            for item in (payload.get("messages") or [])
            if isinstance(item, dict)
        )
        prompt_tokens = _estimate_token_count(prompt_text)
        estimated = True
    if not completion_tokens:
        completion_tokens = _estimate_token_count(_extract_text_content(data))
        estimated = True
    if not uncached_tokens:
        uncached_tokens = max(prompt_tokens - cached_tokens, 0)
    if not total_tokens:
        total_tokens = prompt_tokens + completion_tokens

    return {
        "provider": str(provider or ""),
        "model": str(payload.get("model") or ""),
        "input_tokens": prompt_tokens,
        "cached_input_tokens": cached_tokens,
        "uncached_input_tokens": uncached_tokens,
        "output_tokens": completion_tokens,
        "total_tokens": total_tokens,
        "elapsed_seconds": round(float(elapsed_seconds), 3),
        "estimated": estimated,
        "raw_usage": usage,
    }


def _record_usage_metrics(metrics: dict[str, Any]) -> None:
    collector = _USAGE_COLLECTOR.get()
    if not isinstance(collector, dict):
        return
    collector["call_count"] = int(collector.get("call_count") or 0) + 1
    collector["input_tokens"] = int(collector.get("input_tokens") or 0) + int(metrics.get("input_tokens") or 0)
    collector["cached_input_tokens"] = int(collector.get("cached_input_tokens") or 0) + int(metrics.get("cached_input_tokens") or 0)
    collector["uncached_input_tokens"] = int(collector.get("uncached_input_tokens") or 0) + int(metrics.get("uncached_input_tokens") or 0)
    collector["output_tokens"] = int(collector.get("output_tokens") or 0) + int(metrics.get("output_tokens") or 0)
    collector["total_tokens"] = int(collector.get("total_tokens") or 0) + int(metrics.get("total_tokens") or 0)
    collector["elapsed_seconds"] = round(float(collector.get("elapsed_seconds") or 0.0) + float(metrics.get("elapsed_seconds") or 0.0), 3)
    collector["estimated"] = bool(collector.get("estimated")) or bool(metrics.get("estimated"))
    calls = collector.get("calls")
    if not isinstance(calls, list):
        calls = []
        collector["calls"] = calls
    calls.append(metrics)


def generate_text(
    system_prompt: str,
    user_prompt: str,
    *,
    provider: str | None = None,
    model: str | None = None,
    base_url: str | None = None,
    api_key: str | None = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
    timeout_seconds: int | float | None = None,
    max_retries: int | None = None,
) -> str:
    settings = _require_settings(
        provider=provider,
        model=model,
        base_url=base_url,
        api_key=api_key,
    )
    payload: dict[str, Any] = {
        "model": settings["model"],
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": settings["temperature"] if temperature is None else temperature,
    }
    if max_tokens is not None:
        payload["max_tokens"] = max_tokens
    payload = _apply_model_compat_payload(payload)
    headers = {
        "Authorization": f"Bearer {settings['api_key']}",
        "Content-Type": "application/json",
    }
    url = _join_generation_url(settings["base_url"], settings["endpoint"])
    effective_timeout_seconds = float(timeout_seconds or settings["timeout_seconds"])
    effective_max_retries = max(1, int(max_retries or settings["max_retries"]))
    timeout = httpx.Timeout(effective_timeout_seconds)
    last_error: Exception | None = None

    ssl_verify = settings["ssl_verify"]
    for attempt in range(1, effective_max_retries + 1):
        try:
            started_at = time.perf_counter()
            with httpx.Client(timeout=timeout, verify=ssl_verify) as client:
                response = client.post(url, headers=headers, json=payload)
                response.raise_for_status()
            elapsed_seconds = time.perf_counter() - started_at
            try:
                data = response.json()
            except Exception as exc:
                raise TextGenerationError(f"文本生成响应不是合法 JSON: {exc}") from exc

            _raise_if_generation_truncated(data)
            content = _extract_text_content(data)
            if not content:
                raise TextGenerationError("文本生成接口返回为空")
            _record_usage_metrics(
                _extract_usage_metrics(
                    data,
                    payload,
                    elapsed_seconds=elapsed_seconds,
                    provider=settings["provider"],
                )
            )
            return content.strip()
        except Exception as exc:
            last_error = exc
            if not _should_retry_generation(exc) or attempt >= effective_max_retries:
                break
            time.sleep(settings["retry_backoff_seconds"] * attempt)

    if last_error is not None:
        classified = classify_generation_exception(last_error)
        if classified is not last_error:
            raise classified from last_error
        raise TextGenerationError(f"调用文本生成接口失败: {last_error}") from last_error
    raise TextGenerationError("调用文本生成接口失败：未知原因")


_JSON_TOPLEVEL_HINT = (
    "\n\n[强制约束] 你必须只输出一个 JSON 对象（顶层是 { }），"
    "禁止任何前后缀解释，禁止使用 markdown 代码块标记，"
    "禁止顶层是数组或字符串，禁止以中文标点替代 JSON 标点。"
)


def generate_json(
    system_prompt: str,
    user_prompt: str,
    *,
    provider: str | None = None,
    model: str | None = None,
    base_url: str | None = None,
    api_key: str | None = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
    timeout_seconds: int | float | None = None,
    max_retries: int | None = None,
) -> dict[str, Any]:
    """生成 JSON 对象，包含三层容错：清洗 → 数组/字符串包装 → 顶层重试。"""

    last_error: Exception | None = None
    last_raw_content: str = ""

    for attempt in range(1, 3):  # 顶层最多 2 轮（首轮 + 强化提示重试）
        sys_prompt = system_prompt
        if attempt > 1:
            # 第二轮在 system_prompt 末尾追加强约束，温度也压到 0
            sys_prompt = (system_prompt or "").rstrip() + _JSON_TOPLEVEL_HINT
            attempt_temperature: float | None = 0.0
        else:
            attempt_temperature = temperature

        try:
            content = generate_text(
                sys_prompt,
                user_prompt,
                provider=provider,
                model=model,
                base_url=base_url,
                api_key=api_key,
                temperature=attempt_temperature,
                max_tokens=max_tokens,
                timeout_seconds=timeout_seconds,
                max_retries=max_retries,
            )
        except Exception as exc:  # 包括网络/上游异常 — 直接抛，不在此层吞
            raise

        last_raw_content = content
        parsed = _parse_json_payload(content)

        # 第 1 步：清洗失败 → 触发已有 LLM 自修复
        if parsed is None:
            try:
                repaired_content = _repair_json_output(
                    content,
                    provider=provider,
                    model=model,
                    base_url=base_url,
                    api_key=api_key,
                    max_tokens=max_tokens,
                    timeout_seconds=timeout_seconds,
                    max_retries=max_retries,
                )
                parsed = _parse_json_payload(repaired_content)
            except Exception as repair_exc:
                last_error = repair_exc
                continue  # 进第 2 轮重试

        # 第 2 步：包装非对象类型
        if isinstance(parsed, list):
            parsed = {"items": parsed}
        elif isinstance(parsed, str):
            parsed = {"text": parsed}

        # 第 3 步：仍非 dict（None / 其他基本类型）→ 进重试或最后抛
        if not isinstance(parsed, dict):
            last_error = TextGenerationError(
                f"文本生成 JSON 顶层非对象（实际类型 {type(parsed).__name__}）"
            )
            continue

        return parsed

    # 两轮全失败：把原始内容作为 text 字段兜底返回，下游 step 至少能拿到内容做修复闭环
    if last_raw_content:
        return {
            "text": last_raw_content,
            "_json_fallback": True,
            "_json_fallback_reason": str(last_error) if last_error else "JSON 解析两轮失败",
        }
    raise TextGenerationError(
        f"文本生成 JSON 顶层必须是对象（已重试 2 轮）：{last_error}"
    ) from last_error


def _parse_json_payload(content: str) -> Any | None:
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        try:
            return _extract_first_json_object(content)
        except TextGenerationError:
            return None


def _repair_json_like(text: str) -> str:
    """修复 LLM 常见 JSON 格式问题：中文引号、尾逗号、未加引号的键名。"""
    import re
    repaired = text.strip()
    # 去除 markdown 代码块标记
    if repaired.startswith("```"):
        repaired = repaired.split("\n", 1)[1] if "\n" in repaired else ""
        if repaired.endswith("```"):
            repaired = repaired[:-3]
        repaired = repaired.strip()
    # 中文引号替换为英文引号
    repaired = repaired.replace("“", '"').replace("”", '"').replace("‘", "'").replace("’", "'")
    # 去除尾逗号：{"a":1,} / [1,2,]
    repaired = re.sub(r",\s*([}\]])", r"\1", repaired)
    # 为常见未加引号的键名补引号
    pattern = re.compile(r'([{,]\s*)([A-Za-z_][A-Za-z0-9_-]*)(\s*:)')
    repaired = pattern.sub(r'\1"\2"\3', repaired)
    return repaired


def _extract_first_json_object(content: str) -> dict[str, Any]:
    cleaned = _repair_json_like(content)
    decoder = json.JSONDecoder()
    for index, char in enumerate(cleaned):
        if char not in ("{", "["):
            continue
        try:
            parsed, _ = decoder.raw_decode(cleaned[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
        if isinstance(parsed, list) and parsed:
            # 如果顶层是数组，尝试取第一个对象元素
            first_obj = next((item for item in parsed if isinstance(item, dict)), None)
            if first_obj:
                return first_obj
    raise TextGenerationError("文本生成结果不是合法 JSON")


def _repair_json_output(
    raw_content: str,
    *,
    provider: str | None = None,
    model: str | None = None,
    base_url: str | None = None,
    api_key: str | None = None,
    max_tokens: int | None = None,
    timeout_seconds: int | float | None = None,
    max_retries: int | None = None,
) -> str:
    repair_system_prompt = (
        "你是 JSON 修复器。"
        "请把用户提供的内容修复成一个合法 JSON 对象。"
        "禁止补充解释、禁止使用 markdown 代码块、禁止输出对象以外的任何文字。"
    )
    repair_user_prompt = (
        "下面是需要修复成合法 JSON 对象的文本。"
        "请尽量保留原字段名和字段值，只修复语法与转义问题；若存在多余前后缀，删除它们。\n\n"
        f"{raw_content}"
    )
    repaired = generate_text(
        repair_system_prompt,
        repair_user_prompt,
        provider=provider,
        model=model,
        base_url=base_url,
        api_key=api_key,
        temperature=0.0,
        max_tokens=max_tokens or 2048,
        timeout_seconds=timeout_seconds,
        max_retries=max_retries,
    )
    return repaired.strip()


def generate_text_stream(
    system_prompt: str,
    user_prompt: str,
    *,
    provider: str | None = None,
    model: str | None = None,
    base_url: str | None = None,
    api_key: str | None = None,
    temperature: float | None = None,
    first_token_timeout_seconds: int | float | None = None,
) -> Iterator[str]:
    """
    流式调用 OpenAI 兼容接口，逐 token yield 文本内容。
    使用 httpx.stream() 实现 Server-Sent Events 底层通信。

    示例用法：
        for token in generate_text_stream(sys, usr):
            print(token, end="", flush=True)
    """
    settings = _require_settings(
        provider=provider,
        model=model,
        base_url=base_url,
        api_key=api_key,
    )
    payload = {
        "model": settings["model"],
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": settings["temperature"] if temperature is None else temperature,
        "stream": True,
    }
    payload = _apply_model_compat_payload(payload)
    headers = {
        "Authorization": f"Bearer {settings['api_key']}",
        "Content-Type": "application/json",
        "Accept": "text/event-stream",
    }
    url = _join_generation_url(settings["base_url"], settings["endpoint"])
    timeout = httpx.Timeout(float(settings["timeout_seconds"]))
    ssl_verify = settings["ssl_verify"]

    first_token_emitted = False
    try:
        with httpx.Client(timeout=timeout, verify=ssl_verify) as client:
            with client.stream("POST", url, headers=headers, json=payload) as response:
                response.raise_for_status()
                for line in response.iter_lines():
                    if not line or line == "data: [DONE]":
                        continue
                    if line.startswith("data: "):
                        raw = line[6:]
                        try:
                            chunk = json.loads(raw)
                        except json.JSONDecodeError:
                            continue
                        delta = chunk.get("choices", [{}])[0].get("delta", {})
                        content = delta.get("content") or ""
                        if content:
                            first_token_emitted = True
                            yield content
    except httpx.TimeoutException as exc:
        if not first_token_emitted and first_token_timeout_seconds is not None:
            raise TextGenerationNetworkError("first_token_timeout") from exc
        raise classify_generation_exception(exc) from exc


def _should_retry_generation(exc: Exception) -> bool:
    if isinstance(exc, (httpx.ReadTimeout, httpx.ConnectTimeout, httpx.ConnectError, httpx.RemoteProtocolError)):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in {408, 429, 500, 502, 503, 504}
    message = str(exc).lower()
    return (
        "timed out" in message
        or "502" in message
        or "503" in message
        or "504" in message
        or "文本生成接口返回为空" in message
        or "empty" in message
    )


def _extract_text_content(data: Any) -> str:
    if not isinstance(data, dict):
        return ""

    choices = data.get("choices")
    if isinstance(choices, list) and choices:
        message = choices[0].get("message") if isinstance(choices[0], dict) else None
        if isinstance(message, dict):
            content = message.get("content")
            if isinstance(content, str):
                return content
            if isinstance(content, list):
                texts: list[str] = []
                for item in content:
                    if isinstance(item, dict):
                        text = item.get("text")
                        if isinstance(text, str):
                            texts.append(text)
                if texts:
                    return "\n".join(texts)

    output = data.get("output")
    if isinstance(output, list):
        texts: list[str] = []
        for item in output:
            if not isinstance(item, dict):
                continue
            content = item.get("content")
            if not isinstance(content, list):
                continue
            for block in content:
                if isinstance(block, dict) and isinstance(block.get("text"), str):
                    texts.append(block["text"])
        if texts:
            return "\n".join(texts)

    if isinstance(data.get("text"), str):
        return data["text"]
    return ""
