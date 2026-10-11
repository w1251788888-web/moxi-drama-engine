"""
配置管理API - 支持模型提供商配置动态管理
"""

import ipaddress
import os
from typing import Dict, Any, List
from urllib.parse import urlparse

import yaml
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, Field

from app.auth.dependencies import verify_admin
from app.config import get_config, save_config


router = APIRouter(prefix="/config", tags=["配置管理"])


class ModelProviderConfig(BaseModel):
    """模型提供商配置"""
    provider: str = Field(..., description="提供商ID: kimi/openai/anthropic/deepseek")
    api_key: str = Field(..., description="API密钥")
    model: str = Field(..., description="模型名称")
    base_url: str = Field(..., description="API基础URL")


class ProviderInfo(BaseModel):
    """提供商信息"""
    id: str
    name: str
    icon: str
    base_url: str
    models: List[Dict[str, str]]
    features: List[str]


class ConfigResponse(BaseModel):
    """配置响应"""
    success: bool
    message: str
    data: Dict[str, Any] = {}


class ProviderModelsRequest(BaseModel):
    """拉取供应商模型列表请求。"""
    api_key: str = Field("", description="API密钥；留空时尝试读取已保存配置")
    base_url: str = Field("", description="API基础URL；留空时使用供应商默认或已保存配置")


DANGEROUS_HOSTS = {
    "localhost",
    "metadata",
    "metadata.google.internal",
    "host.docker.internal",
}

DANGEROUS_HOST_SUFFIXES = (
    ".localhost",
    ".local",
    ".internal",
)


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


def _model_base_url_security_config() -> dict[str, Any]:
    config = get_config()
    security = config.get("security", {})
    if not isinstance(security, dict):
        return {}
    model_base_url = security.get("model_base_url", {})
    return model_base_url if isinstance(model_base_url, dict) else {}


def _allow_insecure_model_base_url() -> bool:
    env_value = os.getenv("MOXI_ALLOW_INSECURE_MODEL_BASE_URLS")
    if env_value is not None:
        return _coerce_bool(env_value)
    return _coerce_bool(_model_base_url_security_config().get("allow_insecure"), False)


def _validate_model_base_url(base_url: str) -> str:
    """收紧模型连接测试 URL，避免 SSRF/内网探测。"""
    normalized = str(base_url or "").strip().rstrip("/")
    parsed = urlparse(normalized)

    if parsed.scheme not in {"http", "https"}:
        raise HTTPException(status_code=400, detail="base_url 仅支持 http/https")
    if parsed.scheme != "https" and not _allow_insecure_model_base_url():
        raise HTTPException(status_code=400, detail="base_url 默认必须使用 HTTPS")
    if parsed.username or parsed.password:
        raise HTTPException(status_code=400, detail="base_url 不允许包含用户名或密码")
    if parsed.query or parsed.fragment:
        raise HTTPException(status_code=400, detail="base_url 不允许包含 query 或 fragment")

    host = (parsed.hostname or "").strip().lower().rstrip(".")
    if not host:
        raise HTTPException(status_code=400, detail="base_url 缺少主机名")
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        if host in DANGEROUS_HOSTS or host.endswith(DANGEROUS_HOST_SUFFIXES):
            raise HTTPException(status_code=400, detail="base_url 不允许指向本机或内部主机")
        if "." not in host:
            raise HTTPException(status_code=400, detail="base_url 不允许使用单标签内网主机名")
        return normalized

    if (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    ):
        raise HTTPException(status_code=400, detail="base_url 不允许指向内网、保留或链路本地地址")

    return normalized


def _models_url_for_provider(provider: str, base_url: str) -> str:
    """根据供应商差异拼出模型列表接口，避免 /v1/v1/models。"""
    safe_base_url = _validate_model_base_url(base_url)
    parsed = urlparse(safe_base_url)
    provider_key = str(provider or "").strip().lower()
    host = (parsed.hostname or "").lower()
    path = parsed.path.rstrip("/")

    if provider_key == "deepseek" and host.endswith("deepseek.com") and not path.endswith("/v1"):
        return f"{safe_base_url}/models"
    if safe_base_url.endswith("/v1"):
        return f"{safe_base_url}/models"
    return f"{safe_base_url}/v1/models"


def _headers_for_provider_models(provider: str, api_key: str) -> dict[str, str]:
    provider_key = str(provider or "").strip().lower()
    if provider_key in {"anthropic", "claude"}:
        return {
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "Accept": "application/json",
        }
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def _extract_model_ids(payload: object) -> list[str]:
    if not isinstance(payload, dict):
        return []
    raw_items = payload.get("data")
    if not isinstance(raw_items, list):
        return []
    model_ids: list[str] = []
    for item in raw_items:
        model_id = ""
        if isinstance(item, dict):
            model_id = str(item.get("id") or "").strip()
        elif isinstance(item, str):
            model_id = item.strip()
        if model_id and model_id not in model_ids:
            model_ids.append(model_id)
    return model_ids


# 提供商信息映射
PROVIDER_INFO = {
    "kimi": {
        "name": "Kimi (月之暗面)",
        "icon": "🌙",
        "url": "https://platform.moonshot.cn",
        "base_url": "https://api.moonshot.cn",
        "models": [
            {"value": "kimi-k2.6", "name": "kimi-k2.6 (推荐)"},
            {"value": "kimi-k2.5", "name": "kimi-k2.5"},
            {"value": "kimi-k2", "name": "kimi-k2"},
            {"value": "kimi-k1.5", "name": "kimi-k1.5"},
            {"value": "kimi-latest", "name": "kimi-latest"}
        ],
        "features": [
            "支持长文本上下文（128K）",
            "中文写作能力强",
            "适合剧本创作",
            "推荐模型：kimi-k2.6"
        ]
    },
    "openai": {
        "name": "OpenAI",
        "icon": "🤖",
        "url": "https://platform.openai.com",
        "base_url": "https://api.openai.com",
        "models": [
            {"value": "gpt-4", "name": "GPT-4"},
            {"value": "gpt-4-turbo", "name": "GPT-4 Turbo"},
            {"value": "gpt-3.5-turbo", "name": "GPT-3.5 Turbo"}
        ],
        "features": [
            "全球领先的AI模型",
            "强大的英文写作能力",
            "稳定的API服务",
            "需要海外支付方式"
        ]
    },
    "anthropic": {
        "name": "Anthropic Claude",
        "icon": "🧠",
        "url": "https://console.anthropic.com",
        "base_url": "https://api.anthropic.com",
        "models": [
            {"value": "claude-3-5-sonnet-20241022", "name": "Claude 3.5 Sonnet"},
            {"value": "claude-3-opus-20240229", "name": "Claude 3 Opus"},
            {"value": "claude-3-haiku-20240307", "name": "Claude 3 Haiku"}
        ],
        "features": [
            "优秀的上下文理解",
            "创作风格多样",
            "安全性和可靠性高",
            "需要申请API权限"
        ]
    },
    "deepseek": {
        "name": "DeepSeek",
        "icon": "🧭",
        "url": "https://platform.deepseek.com",
        "base_url": "https://api.deepseek.com",
        "models": [
            {"value": "deepseek-v4-flash", "name": "DeepSeek V4 Flash (推荐)"},
            {"value": "deepseek-v4-pro", "name": "DeepSeek V4 Pro"},
            {"value": "deepseek-chat", "name": "deepseek-chat (兼容旧名)"},
            {"value": "deepseek-reasoner", "name": "deepseek-reasoner (兼容旧名)"}
        ],
        "features": [
            "OpenAI 兼容接口",
            "支持长上下文与推理模式",
            "适合逻辑规划和大纲推理",
            "可通过官方 /models 接口拉取实时模型列表"
        ]
    }
}


@router.get("/providers", response_model=List[ProviderInfo])
async def get_providers():
    """获取所有支持的模型提供商信息"""
    providers = []
    for provider_id, info in PROVIDER_INFO.items():
        providers.append(ProviderInfo(
            id=provider_id,
            name=info["name"],
            icon=info["icon"],
            base_url=info["base_url"],
            models=info["models"],
            features=info["features"]
        ))
    return providers


@router.post("/providers/{provider}/models", response_model=ConfigResponse)
async def fetch_provider_models(
    provider: str,
    req: ProviderModelsRequest,
    _: bool = Depends(verify_admin),
):
    """从上游实时拉取指定供应商可用模型列表，不保存 API Key。"""
    provider_key = provider.strip()
    config = get_config()
    saved_provider = (config.get("model_providers", {}) or {}).get(provider_key, {})
    static_provider = PROVIDER_INFO.get(provider_key, {})

    api_key = str(req.api_key or saved_provider.get("api_key") or "").strip()
    base_url = str(
        req.base_url
        or saved_provider.get("base_url")
        or static_provider.get("base_url")
        or ""
    ).strip()
    if not api_key:
        raise HTTPException(status_code=400, detail="请先填写 API Key，再拉取模型列表")
    if not base_url:
        raise HTTPException(status_code=400, detail="请先填写 base_url，再拉取模型列表")

    import httpx
    from app.services.text_generation_service import get_ssl_verify

    url = _models_url_for_provider(provider_key, base_url)
    try:
        async with httpx.AsyncClient(timeout=30.0, verify=get_ssl_verify()) as client:
            response = await client.get(url, headers=_headers_for_provider_models(provider_key, api_key))
    except httpx.ConnectError:
        return ConfigResponse(success=False, message="❌ 连接失败: 无法连接到API服务器，请检查网络或base_url")
    except Exception as e:
        return ConfigResponse(success=False, message=f"❌ 模型列表拉取失败: {str(e)}")

    if response.status_code >= 400:
        return ConfigResponse(
            success=False,
            message=f"❌ 模型列表拉取失败: HTTP {response.status_code}",
            data={"status_code": response.status_code, "response": response.text[:500]},
        )

    try:
        model_ids = _extract_model_ids(response.json())
    except ValueError:
        model_ids = []
    if not model_ids:
        return ConfigResponse(success=False, message="❌ 上游返回的模型列表为空")

    return ConfigResponse(
        success=True,
        message=f"已拉取 {len(model_ids)} 个模型",
        data={
            "provider": provider_key,
            "base_url": _validate_model_base_url(base_url),
            "models": [{"value": item, "name": item} for item in model_ids],
        },
    )


@router.get("/current")
async def get_current_config():
    """获取当前配置"""
    config = get_config()

    # 获取当前活动的提供商
    provider = config.get("text_generation", {}).get("provider", "kimi")
    model = config.get("text_generation", {}).get("model", "kimi-k2.6")
    base_url = config.get("text_generation", {}).get("base_url", "")

    # 获取模型提供商配置（不含敏感信息）
    providers_config = config.get("model_providers", {})
    provider_names = list(providers_config.keys())

    return {
        "provider": provider,
        "model": model,
        "base_url": base_url,
        "available_providers": provider_names
    }


@router.post("/save", response_model=ConfigResponse)
async def save_model_config(
    config_data: ModelProviderConfig,
    _: bool = Depends(verify_admin),
):
    """保存模型配置到config.yaml"""
    safe_base_url = _validate_model_base_url(config_data.base_url)

    try:
        config = get_config()

        # 更新主配置
        if "text_generation" not in config:
            config["text_generation"] = {}

        config["text_generation"]["provider"] = config_data.provider
        config["text_generation"]["model"] = config_data.model
        config["text_generation"]["base_url"] = safe_base_url
        config["text_generation"]["api_key"] = config_data.api_key

        # 更新模型提供商配置
        if "model_providers" not in config:
            config["model_providers"] = {}

        if config_data.provider not in config["model_providers"]:
            config["model_providers"][config_data.provider] = {}

        provider_config = config["model_providers"][config_data.provider]
        provider_config["api_key"] = config_data.api_key
        provider_config["default_model"] = config_data.model
        provider_config["base_url"] = safe_base_url

        # 保存配置
        save_config(config)

        return ConfigResponse(
            success=True,
            message=f"配置已保存，当前使用: {config_data.provider} - {config_data.model}",
            data={
                "provider": config_data.provider,
                "model": config_data.model
            }
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"保存配置失败: {str(e)}")


@router.post("/test", response_model=ConfigResponse)
async def test_model_connection(
    config_data: ModelProviderConfig,
    _: bool = Depends(verify_admin),
):
    """测试模型连接"""
    safe_base_url = _validate_model_base_url(config_data.base_url)

    import httpx
    from app.services.text_generation_service import get_ssl_verify

    try:
        # 测试请求 - 获取模型列表
        async with httpx.AsyncClient(timeout=30.0, verify=get_ssl_verify()) as client:
            response = await client.get(
                _models_url_for_provider(config_data.provider, safe_base_url),
                headers=_headers_for_provider_models(config_data.provider, config_data.api_key),
            )

            if response.status_code == 200:
                return ConfigResponse(
                    success=True,
                    message="✅ 连接测试成功！API Key有效",
                    data={"status_code": response.status_code}
                )
            else:
                return ConfigResponse(
                    success=False,
                    message=f"❌ 连接测试失败: HTTP {response.status_code}",
                    data={"status_code": response.status_code, "response": response.text}
                )

    except httpx.ConnectError:
        return ConfigResponse(
            success=False,
            message="❌ 连接失败: 无法连接到API服务器，请检查网络或base_url"
        )
    except Exception as e:
        return ConfigResponse(
            success=False,
            message=f"❌ 测试失败: {str(e)}"
        )


@router.post("/set-default/{provider}")
async def set_default_provider(
    provider: str,
    _: bool = Depends(verify_admin),
):
    """设置默认提供商"""

    config = get_config()

    if "model_providers" not in config or provider not in config["model_providers"]:
        raise HTTPException(status_code=404, detail=f"提供商 '{provider}' 未配置")

    # 更新所有提供商的is_default
    for p_id, p_config in config["model_providers"].items():
        p_config["is_default"] = (p_id == provider)

    # 更新主配置
    provider_config = config["model_providers"][provider]
    if "text_generation" not in config:
        config["text_generation"] = {}
    config["text_generation"]["provider"] = provider
    config["text_generation"]["model"] = provider_config.get("default_model", "")
    config["text_generation"]["base_url"] = provider_config.get("base_url", "")

    save_config(config)

    return ConfigResponse(
        success=True,
        message=f"已设置 {provider} 为默认提供商"
    )
