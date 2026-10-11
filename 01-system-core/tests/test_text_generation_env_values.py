from __future__ import annotations

import json

import pytest


def _configure_text_generation(monkeypatch, service, *, provider: str = "fufuapi") -> None:
    monkeypatch.setattr(
        service.config,
        "_data",
        {
            "text_generation": {
                "enabled": True,
                "provider": provider,
                "base_url": "${MOXI_TEST_BASE_URL}",
                "api_key": "${MOXI_TEST_API_KEY}",
                "model": "${MOXI_TEST_MODEL}",
                "endpoint": "/v1/chat/completions",
            },
            "model_providers": {
                "kimi": {
                    "base_url": "https://kimi-config.example.invalid",
                    "api_key": "kimi-config-key-placeholder",
                    "default_model": "kimi-config-model-placeholder",
                }
            },
        },
        raising=False,
    )
    monkeypatch.setenv("MOXI_TEST_BASE_URL", "https://example.invalid")
    monkeypatch.setenv("MOXI_TEST_API_KEY", "test-key-placeholder")
    monkeypatch.setenv("MOXI_TEST_MODEL", "unit-test-model")


def _configure_active_admin_provider(
    tmp_path,
    monkeypatch,
    *,
    provider: str = "kimi",
    base_url: str = "https://kimi-db.example.invalid",
    api_key: str = "kimi-db-key-placeholder",
    default_model: str = "kimi-db-model-placeholder",
):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app import database
    from app.models.saas_admin import LLMProviderSetting
    from app.services.saas_secret_service import encrypt_secret

    engine = create_engine(
        f"sqlite:///{tmp_path / 'active-llm-provider.db'}",
        connect_args={"check_same_thread": False},
    )
    Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    LLMProviderSetting.__table__.create(bind=engine, checkfirst=True)
    monkeypatch.setattr(database, "SessionLocal", Session)

    with Session() as db:
        db.add(
            LLMProviderSetting(
                provider=provider,
                display_name=provider,
                base_url=base_url,
                api_key_encrypted=encrypt_secret(api_key),
                default_model=default_model,
                is_active=True,
                is_default=True,
            )
        )
        db.commit()

    return Session


def test_default_generation_settings_use_active_admin_provider_as_one_bundle(tmp_path, monkeypatch):
    from app.services import text_generation_service as service

    _configure_text_generation(monkeypatch, service, provider="fufuapi")
    _configure_active_admin_provider(tmp_path, monkeypatch)

    settings = service.get_generation_settings()

    assert settings["provider"] == "kimi"
    assert settings["base_url"] == "https://kimi-db.example.invalid"
    assert settings["api_key"] == "kimi-db-key-placeholder"
    assert settings["model"] == "kimi-db-model-placeholder"


def test_generate_text_without_explicit_provider_uses_active_admin_provider(tmp_path, monkeypatch):
    from app.services import text_generation_service as service

    _configure_text_generation(monkeypatch, service, provider="fufuapi")
    _configure_active_admin_provider(tmp_path, monkeypatch)
    captured = {}

    class FakeResponse:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return {
                "choices": [{"message": {"content": "admin provider selected"}}],
                "usage": {},
            }

    class FakeClient:
        def __init__(self, *, timeout, verify):
            captured["timeout"] = timeout
            captured["verify"] = verify

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def post(self, url, *, headers, json):
            captured["url"] = url
            captured["model"] = json["model"]
            captured["uses_admin_key"] = (
                headers.get("Authorization") == "Bearer kimi-db-key-placeholder"
            )
            return FakeResponse()

    monkeypatch.setattr(service.httpx, "Client", FakeClient)

    result = service.generate_text(
        "system",
        "user",
        max_retries=1,
        timeout_seconds=1,
    )

    assert result == "admin provider selected"
    assert captured["url"] == "https://kimi-db.example.invalid/v1/chat/completions"
    assert captured["model"] == "kimi-db-model-placeholder"
    assert captured["uses_admin_key"] is True


def test_active_admin_provider_does_not_borrow_missing_model_from_legacy_config(tmp_path, monkeypatch):
    from app.services import text_generation_service as service

    _configure_text_generation(monkeypatch, service, provider="fufuapi")
    _configure_active_admin_provider(
        tmp_path,
        monkeypatch,
        default_model="",
    )

    settings = service.get_generation_settings()

    assert settings["provider"] == "kimi"
    assert settings["model"] == ""


def test_default_generation_settings_fallback_to_legacy_when_all_admin_providers_are_inactive(
    tmp_path,
    monkeypatch,
):
    from app.models.saas_admin import LLMProviderSetting
    from app.services import text_generation_service as service

    _configure_text_generation(monkeypatch, service, provider="fufuapi")
    Session = _configure_active_admin_provider(tmp_path, monkeypatch)

    with Session() as db:
        row = db.query(LLMProviderSetting).filter(LLMProviderSetting.provider == "kimi").one()
        row.is_active = False
        db.commit()

    settings = service.get_generation_settings()

    assert settings["provider"] == "fufuapi"
    assert settings["base_url"] == "https://example.invalid"
    assert settings["api_key"] == "test-key-placeholder"
    assert settings["model"] == "unit-test-model"


def test_explicit_provider_overrides_a_different_active_admin_provider(tmp_path, monkeypatch):
    from app.models.saas_admin import LLMProviderSetting
    from app.services import text_generation_service as service
    from app.services.saas_secret_service import encrypt_secret

    _configure_text_generation(monkeypatch, service, provider="fufuapi")
    Session = _configure_active_admin_provider(tmp_path, monkeypatch)

    with Session() as db:
        db.add(
            LLMProviderSetting(
                provider="deepseek",
                display_name="deepseek",
                base_url="https://deepseek-db.example.invalid",
                api_key_encrypted=encrypt_secret("deepseek-db-key-placeholder"),
                default_model="deepseek-db-model-placeholder",
                is_active=False,
                is_default=False,
            )
        )
        db.commit()

    settings = service.get_generation_settings(provider="deepseek")

    assert settings["provider"] == "deepseek"
    assert settings["base_url"] == "https://deepseek-db.example.invalid"
    assert settings["api_key"] == "deepseek-db-key-placeholder"
    assert settings["model"] == "deepseek-db-model-placeholder"


def test_database_provider_lookup_failure_does_not_fallback_to_legacy_config(monkeypatch):
    from app import database
    from app.services import text_generation_service as service

    _configure_text_generation(monkeypatch, service, provider="fufuapi")

    def fail_session_creation():
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(database, "SessionLocal", fail_session_creation)

    with pytest.raises(service.TextGenerationConfigError, match="管理员模型配置读取失败"):
        service.get_generation_settings()


def test_complete_explicit_provider_bundle_does_not_depend_on_database(monkeypatch):
    from app import database
    from app.services import text_generation_service as service

    _configure_text_generation(monkeypatch, service, provider="fufuapi")

    def fail_session_creation():
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(database, "SessionLocal", fail_session_creation)

    settings = service.get_generation_settings(
        provider="explicit-provider",
        base_url="https://explicit.example.invalid",
        api_key="explicit-key-placeholder",
        model="explicit-model-placeholder",
    )

    assert settings["provider"] == "explicit-provider"
    assert settings["base_url"] == "https://explicit.example.invalid"
    assert settings["api_key"] == "explicit-key-placeholder"
    assert settings["model"] == "explicit-model-placeholder"


def test_corrupt_encrypted_admin_key_fails_closed_instead_of_becoming_empty(tmp_path, monkeypatch):
    from app.models.saas_admin import LLMProviderSetting
    from app.services import text_generation_service as service

    _configure_text_generation(monkeypatch, service, provider="fufuapi")
    Session = _configure_active_admin_provider(tmp_path, monkeypatch)

    with Session() as db:
        row = db.query(LLMProviderSetting).filter(LLMProviderSetting.provider == "kimi").one()
        row.api_key_encrypted = "moxi1:not-valid-ciphertext"
        db.commit()

    with pytest.raises(service.TextGenerationConfigError, match="管理员模型配置读取失败"):
        service.get_generation_settings()


def test_llm_reachable_reports_database_provider_lookup_failure_safely(monkeypatch):
    from app import database
    from app.services import text_generation_service as service

    _configure_text_generation(monkeypatch, service, provider="fufuapi")

    def fail_session_creation():
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(database, "SessionLocal", fail_session_creation)

    result = service.check_llm_reachable(timeout_seconds=1)

    assert result == {
        "ok": False,
        "detail": "管理员模型配置读取失败。",
        "detail_category": "config_provider_lookup_failed",
        "latency_ms": 0,
        "safe_failure_subtype": "config_missing",
    }


def test_generation_settings_resolve_text_generation_env_placeholders(monkeypatch):
    from app.services import text_generation_service as service

    _configure_text_generation(monkeypatch, service)
    monkeypatch.setattr(service, "_database_provider_settings", lambda provider: {})

    settings = service.get_generation_settings()

    assert settings["base_url"] == "https://example.invalid"
    assert settings["api_key"] == "test-key-placeholder"
    assert settings["model"] == "unit-test-model"


def test_generation_settings_resolve_provider_env_bridge(monkeypatch):
    from app.services import text_generation_service as service

    _configure_text_generation(monkeypatch, service)
    monkeypatch.setattr(service, "_database_provider_settings", lambda provider: {})
    monkeypatch.setenv(
        "MOXI_MODEL_PROVIDERS_JSON",
        json.dumps(
            {
                "kimi": {
                    "base_url": "https://kimi-env.example.invalid",
                    "api_key": "kimi-env-key-placeholder",
                    "default_model": "kimi-env-model-placeholder",
                },
                "deepseek": {
                    "base_url": "https://deepseek-env.example.invalid",
                    "api_key": "deepseek-env-key-placeholder",
                    "default_model": "deepseek-env-model-placeholder",
                },
            }
        ),
    )

    kimi_settings = service.get_generation_settings(provider="kimi")
    deepseek_settings = service.get_generation_settings(provider="deepseek")

    assert kimi_settings["base_url"] == "https://kimi-env.example.invalid"
    assert kimi_settings["api_key"] == "kimi-env-key-placeholder"
    assert kimi_settings["model"] == "kimi-env-model-placeholder"
    assert deepseek_settings["base_url"] == "https://deepseek-env.example.invalid"
    assert deepseek_settings["api_key"] == "deepseek-env-key-placeholder"
    assert deepseek_settings["model"] == "deepseek-env-model-placeholder"


def test_kimi_keeps_database_provider_bundle_when_config_model_differs(monkeypatch):
    from app.services import text_generation_service as service

    _configure_text_generation(monkeypatch, service)
    monkeypatch.setattr(
        service,
        "_database_provider_settings",
        lambda provider: {
            "base_url": "https://kimi-db.example.invalid",
            "api_key": "kimi-db-key-placeholder",
            "default_model": "kimi-db-model-placeholder",
        } if provider == "kimi" else {},
    )

    settings = service.get_generation_settings(provider="kimi")
    explicit = service.get_generation_settings(provider="kimi", model="explicit-kimi-model-placeholder")

    assert settings["base_url"] == "https://kimi-db.example.invalid"
    assert settings["api_key"] == "kimi-db-key-placeholder"
    assert settings["model"] == "kimi-db-model-placeholder"
    assert explicit["model"] == "explicit-kimi-model-placeholder"


def test_deepseek_keeps_database_model_priority(monkeypatch):
    from app.services import text_generation_service as service

    _configure_text_generation(monkeypatch, service)
    monkeypatch.setenv(
        "MOXI_MODEL_PROVIDERS_JSON",
        json.dumps(
            {
                "deepseek": {
                    "base_url": "https://deepseek-env.example.invalid",
                    "api_key": "deepseek-env-key-placeholder",
                    "default_model": "deepseek-env-model-placeholder",
                }
            }
        ),
    )
    monkeypatch.setattr(
        service,
        "_database_provider_settings",
        lambda provider: {
            "base_url": "https://deepseek-db.example.invalid",
            "api_key": "deepseek-db-key-placeholder",
            "default_model": "deepseek-db-model-placeholder",
        } if provider == "deepseek" else {},
    )

    settings = service.get_generation_settings(provider="deepseek")

    assert settings["base_url"] == "https://deepseek-db.example.invalid"
    assert settings["api_key"] == "deepseek-db-key-placeholder"
    assert settings["model"] == "deepseek-db-model-placeholder"


def test_missing_explicit_provider_does_not_fallback_to_global(monkeypatch):
    from app.services import text_generation_service as service

    _configure_text_generation(monkeypatch, service)
    monkeypatch.setattr(service, "_database_provider_settings", lambda provider: {})

    settings = service.get_generation_settings(provider="missing-provider")

    assert settings["provider"] == "missing-provider"
    assert settings["base_url"] == ""
    assert settings["api_key"] == ""
    assert settings["model"] == ""


def test_llm_reachable_applies_kimi_model_compatibility(monkeypatch):
    from app.services import text_generation_service as service

    _configure_text_generation(monkeypatch, service)
    monkeypatch.setattr(service, "_database_provider_settings", lambda provider: {})
    captured = {}

    class FakeResponse:
        status_code = 200

    class FakeClient:
        def __init__(self, *, timeout, verify):
            captured["timeout"] = timeout
            captured["verify"] = verify

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def post(self, url, *, json, headers):
            captured["payload"] = json
            return FakeResponse()

    monkeypatch.setattr(service.httpx, "Client", FakeClient)

    result = service.check_llm_reachable(
        timeout_seconds=1,
        provider="kimi",
        model="kimi-k2.6",
    )

    assert result["ok"] is True
    assert captured["payload"]["thinking"] == {"type": "disabled"}
    assert captured["payload"]["temperature"] == 0.6


def test_llm_reachable_uses_provider_bridge_and_safe_non_200_category(monkeypatch):
    from app.services import text_generation_service as service

    _configure_text_generation(monkeypatch, service)
    monkeypatch.setattr(service, "_database_provider_settings", lambda provider: {})
    monkeypatch.setenv(
        "MOXI_MODEL_PROVIDERS_JSON",
        json.dumps(
            {
                "kimi": {
                    "base_url": "https://kimi-env.example.invalid/v1",
                    "api_key": "kimi-env-key-placeholder",
                    "default_model": "kimi-env-model-placeholder",
                }
            }
        ),
    )
    captured = {}

    class FakeResponse:
        status_code = 400
        text = "RAW_PROVIDER_BODY_MUST_NOT_LEAK"

    class FakeClient:
        def __init__(self, *, timeout, verify):
            captured["timeout"] = timeout
            captured["verify"] = verify

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def post(self, url, *, json, headers):
            captured["url"] = url
            captured["payload"] = json
            captured["authorization_is_placeholder"] = (
                headers.get("Authorization") == "Bearer kimi-env-key-placeholder"
            )
            return FakeResponse()

    monkeypatch.setattr(service.httpx, "Client", FakeClient)

    result = service.check_llm_reachable(timeout_seconds=1.5, provider="kimi")

    assert result["ok"] is False
    assert result["detail_category"] == "upstream_bad_request_or_model"
    assert result["safe_failure_subtype"] == "upstream_bad_request_or_model"
    assert result["status_code"] == 400
    assert "RAW_PROVIDER_BODY_MUST_NOT_LEAK" not in result["detail"]
    assert captured["url"] == "https://kimi-env.example.invalid/v1/chat/completions"
    assert captured["payload"]["model"] == "kimi-env-model-placeholder"
    assert captured["authorization_is_placeholder"] is True
