from app.routers.projects._helpers import _normalize_project_config_payload
from app.routers.projects._schemas import ProjectConfig


def test_project_config_accepts_advanced_generation_mode():
    config = ProjectConfig(advanced_generation_mode=True)

    assert config.advanced_generation_mode is True


def test_project_config_normalizes_advanced_generation_mode():
    normalized = _normalize_project_config_payload(
        {"advanced_generation_mode": "yes"},
        project_type="真人短剧-女频",
        audience_axis="女频",
        genre_main="都市",
        genre_sub="逆袭",
    )

    assert normalized["advanced_generation_mode"] is True


def test_project_config_defaults_to_research_model_chain_when_advanced_mode_enabled():
    normalized = _normalize_project_config_payload(
        {"advanced_generation_mode": True, "advanced_generation_profile_id": "short_drama"},
        project_type="真人短剧",
        audience_axis="男频",
        genre_main="都市",
        genre_sub="逆袭",
    )

    providers = normalized["advanced_generation_providers"]
    assert providers["logic"]["provider"] == "deepseek"
    assert providers["logic"]["model"] == "deepseek-v4-pro"
    assert providers["creative"]["provider"] == "kimi"
    assert providers["creative"]["model"] == "kimi-k2.6"
    assert providers["review"]["provider"] == "deepseek"
    assert providers["review"]["model"] == "deepseek-v4-pro"


def test_admin_advanced_generation_defaults_match_research_chain():
    from app.services.saas_admin_query_service import ADVANCED_GENERATION_ROLE_DEFAULTS

    assert ADVANCED_GENERATION_ROLE_DEFAULTS["logic"]["provider"] == "deepseek"
    assert ADVANCED_GENERATION_ROLE_DEFAULTS["logic"]["model"] == "deepseek-v4-pro"
    assert ADVANCED_GENERATION_ROLE_DEFAULTS["creative"]["provider"] == "kimi"
    assert ADVANCED_GENERATION_ROLE_DEFAULTS["creative"]["model"] == "kimi-k2.6"
    assert ADVANCED_GENERATION_ROLE_DEFAULTS["review"]["provider"] == "deepseek"
    assert ADVANCED_GENERATION_ROLE_DEFAULTS["review"]["model"] == "deepseek-v4-pro"
