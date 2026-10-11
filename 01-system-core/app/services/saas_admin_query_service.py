"""SaaS 后台查询服务：看板、模型配置、流水、日志、异常。"""
from __future__ import annotations

import json
from decimal import Decimal, ROUND_HALF_UP
from urllib.parse import urlparse
import httpx
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.api.routes.config import _validate_model_base_url
from app.models.project_v2 import ModelProvider
from app.models.saas_admin import AdminFeatureFlag, CreditLedger, LLMProviderSetting, UserAccessKey
from app.services.saas_secret_service import decrypt_secret, encrypt_secret, mask_secret
from app.services.text_generation_service import get_ssl_verify


DEFAULT_PROVIDERS = [
    ("kimi", "Kimi", "https://api.moonshot.cn/v1", "kimi-k2.6", ["kimi-k2.6", "moonshot-v1-128k"]),
    ("openai", "OpenAI", "https://api.openai.com/v1", "gpt-4o", ["gpt-4o", "gpt-4o-mini"]),
    ("claude", "Claude", "https://api.anthropic.com/v1", "claude-sonnet-4-5", ["claude-sonnet-4-5"]),
    ("deepseek", "DeepSeek", "https://api.deepseek.com", "deepseek-v4-flash", ["deepseek-v4-flash", "deepseek-v4-pro", "deepseek-chat", "deepseek-reasoner"]),
    ("qwen", "通义千问", "https://dashscope.aliyuncs.com/compatible-mode/v1", "qwen-plus", ["qwen-plus", "qwen-max"]),
    ("custom", "自定义接口", "", "", []),
]
DEFAULT_PROVIDER_BY_KEY = {item[0]: item for item in DEFAULT_PROVIDERS}

ADVANCED_GENERATION_CONFIG_KEY = "advanced_generation_model_routes"

ADVANCED_GENERATION_ROLE_DEFAULTS = {
    "logic": {
        "label": "逻辑规划模型",
        "provider": "deepseek",
        "model": "deepseek-v4-pro",
        "temperature": 0.25,
        "duty": "负责市场验证、题材判断、主线逻辑、大纲拆解，优先保证结构稳定。",
        "steps": ["项目初始化检查", "市场验证", "概念生成", "分集大纲"],
    },
    "creative": {
        "label": "创作执笔模型",
        "provider": "kimi",
        "model": "kimi-k2.6",
        "temperature": 0.85,
        "duty": "负责人物塑造、节拍设计、分场和剧本正文，优先保证中文表达和戏剧张力。",
        "steps": ["角色库", "节拍表", "分场列表", "剧本初稿", "分镜草案"],
    },
    "review": {
        "label": "质量评审模型",
        "provider": "deepseek",
        "model": "deepseek-v4-pro",
        "temperature": 0.0,
        "duty": "负责质量审稿、逻辑一致性、合规风险和返修建议，优先保证严谨审查。",
        "steps": ["质量检查", "叙事一致性", "合规检查"],
    },
}

ADVANCED_GENERATION_ROLE_ORDER = ["logic", "creative", "review"]


class LLMProviderModelRefreshError(ValueError):
    """Raised when an upstream model list cannot be loaded safely."""


def _money(value: object) -> float:
    return float(Decimal(str(value or 0)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _models_url(base_url: str, provider: str = "") -> str:
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


def _provider_model_headers(provider: str, api_key: str) -> dict[str, str]:
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


def _safe_json_loads(raw: str | None, fallback: object) -> object:
    try:
        return json.loads(raw or "")
    except Exception:
        return fallback


def _provider_lookup(providers: list[dict]) -> dict[str, dict]:
    return {str(item.get("provider") or ""): item for item in providers}


def _model_for_provider(provider_row: dict | None, preferred_model: str) -> str:
    if not provider_row:
        return preferred_model
    models = provider_row.get("models") if isinstance(provider_row.get("models"), list) else []
    default_model = str(provider_row.get("default_model") or "").strip()
    if preferred_model and preferred_model in models:
        return preferred_model
    return default_model or (str(models[0]).strip() if models else preferred_model)


def _advanced_role_payload(role: str, saved_role: dict, providers_by_key: dict[str, dict]) -> dict:
    defaults = ADVANCED_GENERATION_ROLE_DEFAULTS[role]
    provider = str(saved_role.get("provider") or defaults["provider"]).strip()
    provider_row = providers_by_key.get(provider)
    if provider_row is None:
        provider = str(defaults["provider"])
        provider_row = providers_by_key.get(provider)
    model = _model_for_provider(provider_row, str(saved_role.get("model") or defaults["model"]).strip())
    try:
        temperature = float(saved_role.get("temperature", defaults["temperature"]))
    except (TypeError, ValueError):
        temperature = float(defaults["temperature"])
    duty = str(saved_role.get("duty") or defaults["duty"]).strip()
    return {
        "role": role,
        "label": defaults["label"],
        "provider": provider,
        "provider_name": str(provider_row.get("display_name") or provider) if provider_row else provider,
        "model": model,
        "temperature": temperature,
        "duty": duty,
        "steps": list(defaults["steps"]),
        "has_api_key": bool(provider_row.get("has_api_key")) if provider_row else False,
        "api_key_masked": str(provider_row.get("api_key_masked") or "") if provider_row else "",
        "is_active": bool(provider_row.get("is_active")) if provider_row else False,
    }


def ensure_default_llm_providers(db: Session) -> None:
    for provider, display_name, base_url, default_model, models in DEFAULT_PROVIDERS:
        exists = db.query(LLMProviderSetting).filter(LLMProviderSetting.provider == provider).first()
        if exists:
            if (
                provider == "deepseek"
                and not exists.api_key_encrypted
                and (
                    str(exists.base_url or "").rstrip("/") in {"", "https://api.deepseek.com/v1"}
                    or str(exists.default_model or "") in {"", "deepseek-chat", "deepseek-reasoner"}
                )
            ):
                exists.base_url = base_url
                exists.default_model = default_model
                exists.models_json = json.dumps(models, ensure_ascii=False)
            continue
        db.add(LLMProviderSetting(
            provider=provider,
            display_name=display_name,
            base_url=base_url,
            default_model=default_model,
            models_json=json.dumps(models, ensure_ascii=False),
            is_active=False,
            is_default=(provider == "kimi"),
        ))
    db.commit()


def normalize_active_llm_provider(db: Session) -> None:
    active_rows = (
        db.query(LLMProviderSetting)
        .filter(LLMProviderSetting.is_active.is_(True))
        .order_by(LLMProviderSetting.is_default.desc(), LLMProviderSetting.updated_at.desc())
        .all()
    )
    if len(active_rows) <= 1:
        return
    keeper = active_rows[0]
    for row in active_rows[1:]:
        row.is_active = False
    db.query(ModelProvider).filter(ModelProvider.provider_type != keeper.provider).update({
        ModelProvider.is_active: False,
    })
    provider_row = db.query(ModelProvider).filter(ModelProvider.provider_type == keeper.provider).first()
    if provider_row is not None:
        provider_row.is_active = True
    db.commit()


def llm_provider_payload(row: LLMProviderSetting) -> dict:
    try:
        models = json.loads(row.models_json or "[]")
    except Exception:
        models = []
    return {
        "id": row.id,
        "provider": row.provider,
        "display_name": row.display_name,
        "base_url": row.base_url,
        "default_model": row.default_model,
        "models": models,
        "is_active": bool(row.is_active),
        "is_default": bool(row.is_default),
        "has_api_key": bool(row.api_key_encrypted),
        "api_key_masked": mask_secret(row.api_key_encrypted),
        "input_cost_cny_per_1k": float(row.input_cost_cny_per_1k or Decimal("0.002")),
        "output_cost_cny_per_1k": float(row.output_cost_cny_per_1k or Decimal("0.008")),
        "billing_multiplier": float(row.billing_multiplier or Decimal("5")),
        "minimum_actual_cost_cny": float(row.minimum_actual_cost_cny or Decimal("0.01")),
    }


def list_llm_providers(db: Session) -> list[dict]:
    ensure_default_llm_providers(db)
    normalize_active_llm_provider(db)
    rows = db.query(LLMProviderSetting).order_by(LLMProviderSetting.provider.asc()).all()
    return [llm_provider_payload(row) for row in rows]


def save_llm_provider(db: Session, provider: str, payload: dict) -> dict:
    ensure_default_llm_providers(db)
    row = db.query(LLMProviderSetting).filter(LLMProviderSetting.provider == provider).first()
    if row is None:
        row = LLMProviderSetting(provider=provider)
        db.add(row)
    row.display_name = str(payload.get("display_name") or row.display_name or provider)
    row.base_url = str(payload.get("base_url") or "")
    row.default_model = str(payload.get("default_model") or "")
    models = payload.get("models") if isinstance(payload.get("models"), list) else []
    row.models_json = json.dumps([str(item) for item in models if str(item).strip()], ensure_ascii=False)
    if str(payload.get("api_key") or "").strip():
        row.api_key_encrypted = encrypt_secret(str(payload.get("api_key")))
    row.is_active = bool(payload.get("is_active"))
    if row.is_active:
        db.query(LLMProviderSetting).filter(LLMProviderSetting.provider != row.provider).update({
            LLMProviderSetting.is_active: False,
        })
    if payload.get("is_default"):
        db.query(LLMProviderSetting).update({LLMProviderSetting.is_default: False})
        row.is_default = True
    row.input_cost_cny_per_1k = Decimal(str(payload.get("input_cost_cny_per_1k") or "0.002"))
    row.output_cost_cny_per_1k = Decimal(str(payload.get("output_cost_cny_per_1k") or "0.008"))
    row.billing_multiplier = Decimal(str(payload.get("billing_multiplier") or "5"))
    row.minimum_actual_cost_cny = Decimal(str(payload.get("minimum_actual_cost_cny") or "0.01"))
    _sync_model_provider(db, row)
    db.commit()
    db.refresh(row)
    return llm_provider_payload(row)


async def refresh_llm_provider_models(db: Session, provider: str) -> dict:
    ensure_default_llm_providers(db)
    provider_key = str(provider or "").strip()
    row = db.query(LLMProviderSetting).filter(LLMProviderSetting.provider == provider_key).first()
    if row is None:
        raise LLMProviderModelRefreshError(f"{provider_key or 'LLM'} 供应商配置不存在")
    display_name = row.display_name or row.provider
    if not row.api_key_encrypted:
        raise LLMProviderModelRefreshError(f"{display_name} API Key 未填写，无法自动拉取模型列表")

    default_row = DEFAULT_PROVIDER_BY_KEY.get(row.provider)
    fallback_base_url = default_row[2] if default_row else ""
    url = _models_url(row.base_url or fallback_base_url, row.provider)
    headers = _provider_model_headers(row.provider, decrypt_secret(row.api_key_encrypted))
    try:
        async with httpx.AsyncClient(timeout=20.0, verify=get_ssl_verify()) as client:
            response = await client.get(url, headers=headers)
    except httpx.RequestError as exc:
        raise LLMProviderModelRefreshError(f"{display_name} 模型列表拉取失败：{exc}") from exc

    if response.status_code >= 400:
        raise LLMProviderModelRefreshError(f"{display_name} 模型列表拉取失败：HTTP {response.status_code}")

    try:
        payload = response.json()
    except ValueError as exc:
        raise LLMProviderModelRefreshError(f"{display_name} 模型列表响应不是有效 JSON") from exc

    model_ids = _extract_model_ids(payload)
    if not model_ids:
        raise LLMProviderModelRefreshError(f"{display_name} 接口返回的模型列表为空")

    row.models_json = json.dumps(model_ids, ensure_ascii=False)
    if not row.default_model or row.default_model not in model_ids:
        row.default_model = model_ids[0]
    _sync_model_provider(db, row)
    db.commit()
    db.refresh(row)
    return llm_provider_payload(row)


async def refresh_kimi_models(db: Session) -> dict:
    return await refresh_llm_provider_models(db, "kimi")


def get_advanced_generation_config(db: Session) -> dict:
    providers = list_llm_providers(db)
    providers_by_key = _provider_lookup(providers)
    flag = db.query(AdminFeatureFlag).filter(AdminFeatureFlag.key == ADVANCED_GENERATION_CONFIG_KEY).first()
    saved = _safe_json_loads(flag.note if flag else "", {})
    if not isinstance(saved, dict):
        saved = {}
    saved_roles = saved.get("roles") if isinstance(saved.get("roles"), dict) else {}
    return {
        "enabled": bool(saved.get("enabled", True)),
        "profile_id": str(saved.get("profile_id") or "short_drama"),
        "roles": [
            _advanced_role_payload(
                role,
                saved_roles.get(role) if isinstance(saved_roles.get(role), dict) else {},
                providers_by_key,
            )
            for role in ADVANCED_GENERATION_ROLE_ORDER
        ],
        "updated_at": flag.updated_at.isoformat() if flag and flag.updated_at else None,
    }


def save_advanced_generation_config(db: Session, payload: dict) -> dict:
    ensure_default_llm_providers(db)
    incoming_roles = payload.get("roles") if isinstance(payload.get("roles"), list) else []
    incoming_by_role = {
        str(item.get("role") or ""): item
        for item in incoming_roles
        if isinstance(item, dict)
    }
    roles: dict[str, dict] = {}
    for role in ADVANCED_GENERATION_ROLE_ORDER:
        defaults = ADVANCED_GENERATION_ROLE_DEFAULTS[role]
        incoming = incoming_by_role.get(role, {})
        try:
            temperature = float(incoming.get("temperature", defaults["temperature"]))
        except (TypeError, ValueError):
            temperature = float(defaults["temperature"])
        roles[role] = {
            "provider": str(incoming.get("provider") or defaults["provider"]).strip(),
            "model": str(incoming.get("model") or defaults["model"]).strip(),
            "temperature": max(0.0, min(2.0, temperature)),
            "duty": str(incoming.get("duty") or defaults["duty"]).strip(),
        }

    saved = {
        "enabled": bool(payload.get("enabled", True)),
        "profile_id": str(payload.get("profile_id") or "short_drama").strip() or "short_drama",
        "roles": roles,
    }
    flag = db.query(AdminFeatureFlag).filter(AdminFeatureFlag.key == ADVANCED_GENERATION_CONFIG_KEY).first()
    if flag is None:
        flag = AdminFeatureFlag(
            key=ADVANCED_GENERATION_CONFIG_KEY,
            label="高级生成链路模型分工",
        )
        db.add(flag)
    flag.enabled = bool(saved["enabled"])
    flag.note = json.dumps(saved, ensure_ascii=False)
    db.commit()
    return get_advanced_generation_config(db)


def _sync_model_provider(db: Session, row: LLMProviderSetting) -> None:
    provider_row = db.query(ModelProvider).filter(ModelProvider.provider_type == row.provider).first()
    if provider_row is None and row.display_name:
        provider_row = db.query(ModelProvider).filter(ModelProvider.name == row.display_name).first()
    if provider_row is None:
        provider_row = ModelProvider(
            name=row.display_name or row.provider,
            provider_type=row.provider,
        )
        db.add(provider_row)
    provider_row.name = row.display_name or provider_row.name or row.provider
    provider_row.base_url = row.base_url
    if row.api_key_encrypted:
        provider_row.api_key = decrypt_secret(row.api_key_encrypted)
    provider_row.default_model = row.default_model
    provider_row.set_models(json.loads(row.models_json or "[]"))
    provider_row.is_active = bool(row.is_active)
    if row.is_active:
        db.query(ModelProvider).filter(ModelProvider.provider_type != row.provider).update({
            ModelProvider.is_active: False,
        })
    if row.is_default:
        db.query(ModelProvider).update({ModelProvider.is_default: False})
        provider_row.is_default = True
    provider_row.input_cost_cny_per_1k = row.input_cost_cny_per_1k
    provider_row.output_cost_cny_per_1k = row.output_cost_cny_per_1k
    provider_row.billing_multiplier = row.billing_multiplier
    provider_row.minimum_actual_cost_cny = row.minimum_actual_cost_cny


def overview_payload(db: Session) -> dict:
    active_keys = db.query(UserAccessKey).filter(UserAccessKey.status == "active").count()
    generation_count = db.query(CreditLedger).filter(CreditLedger.event_type == "charge").count()
    failed_count = db.query(CreditLedger).filter(CreditLedger.status != "success").count()
    total_credit = db.query(func.coalesce(func.sum(CreditLedger.amount), 0)).scalar() or 0
    actual_cost = db.query(func.coalesce(func.sum(CreditLedger.actual_cost_cny), 0)).scalar() or 0
    return {
        "billing_rule": "实际成本 × 5",
        "credit_unit": "1额度 = 1元人民币",
        "cards": [
            {"label": "今日生成", "value": int(generation_count)},
            {"label": "今日扣费", "value": _money(abs(total_credit))},
            {"label": "活跃密钥", "value": int(active_keys)},
            {"label": "异常事件", "value": int(failed_count)},
        ],
        "cost_health": {
            "actual_cost_cny": _money(actual_cost),
            "billed_credit": _money(abs(total_credit)),
            "gross_margin_credit": _money(abs(total_credit) - Decimal(str(actual_cost or 0))),
        },
        "sections": ["LLM接口配置", "用户密钥管理", "额度流水", "生成日志", "异常中心", "高级生成链路"],
    }


def ledger_payload(row: CreditLedger) -> dict:
    return {
        "id": row.id,
        "access_key_id": row.access_key_id,
        "event_type": row.event_type,
        "amount": _money(row.amount),
        "balance_after": _money(row.balance_after),
        "actual_cost_cny": _money(row.actual_cost_cny),
        "billing_multiplier": _money(row.billing_multiplier),
        "provider": row.provider,
        "model": row.model,
        "prompt_tokens": row.prompt_tokens,
        "completion_tokens": row.completion_tokens,
        "generation_type": row.generation_type,
        "status": row.status,
        "human_reason": row.human_reason,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def list_credit_ledger(db: Session, *, status: str = "") -> list[dict]:
    query = db.query(CreditLedger).order_by(CreditLedger.created_at.desc())
    if status:
        query = query.filter(CreditLedger.status == status)
    return [ledger_payload(row) for row in query.limit(200).all()]


def list_generation_logs(db: Session) -> list[dict]:
    rows = db.query(CreditLedger).filter(CreditLedger.event_type == "charge").order_by(CreditLedger.created_at.desc()).limit(200).all()
    return [ledger_payload(row) for row in rows]


def list_exceptions(db: Session) -> list[dict]:
    rows = db.query(CreditLedger).filter(CreditLedger.status != "success").order_by(CreditLedger.created_at.desc()).limit(200).all()
    return [ledger_payload(row) for row in rows]
