from __future__ import annotations

import importlib.util
import os
import re
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
CORE_ROOT = REPO_ROOT / "01-system-core"
WORDPRESS_CLI = REPO_ROOT / "05-skill-plugins" / "wordpress-skill" / "wordpress-cli.py"
WORDPRESS_SKILL = REPO_ROOT / "05-skill-plugins" / "wordpress-skill" / "SKILL.md"
SECRET_AUDIT = CORE_ROOT / "scripts" / "secret_audit.py"


def _load_wordpress_cli():
    spec = importlib.util.spec_from_file_location("wordpress_cli_test_module", WORDPRESS_CLI)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_secret_audit():
    spec = importlib.util.spec_from_file_location("secret_audit_test_module", SECRET_AUDIT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _route_dependency_names(app, path: str, method: str) -> set[str]:
    from fastapi.routing import APIRoute

    for route in app.routes:
        if not isinstance(route, APIRoute):
            continue
        if route.path == path and method.upper() in route.methods:
            return {
                getattr(dependency.call, "__name__", str(dependency.call))
                for dependency in route.dependant.dependencies
            }
    raise AssertionError(f"Route not found: {method} {path}")


def test_active_source_has_no_unsafe_html_rendering_patterns():
    roots = [
        REPO_ROOT / "01-system-core" / "webui" / "src",
        REPO_ROOT / "01-system-core" / "app",
        REPO_ROOT / "05-skill-plugins",
    ]
    patterns = ("v-html", "innerHTML", "outerHTML", "insertAdjacentHTML", "dangerouslySetInnerHTML")
    offenders: list[str] = []
    for root in roots:
        for path in root.rglob("*"):
            if "third_party" in path.parts:
                continue
            if not path.is_file() or path.suffix.lower() not in {".vue", ".ts", ".tsx", ".js", ".py"}:
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            if any(pattern in text for pattern in patterns):
                offenders.append(os.fspath(path.relative_to(REPO_ROOT)))

    assert offenders == []


def test_cors_uses_configured_whitelist_instead_of_wildcard():
    main_source = (CORE_ROOT / "app" / "main.py").read_text(encoding="utf-8")
    config_source = (CORE_ROOT / "app" / "config.py").read_text(encoding="utf-8")
    example_source = (CORE_ROOT / "config.yaml.example").read_text(encoding="utf-8")

    assert 'allow_origins=["*"]' not in main_source
    assert "allow_origins=['*']" not in main_source
    assert "allow_origins=config.cors_allowed_origins" in main_source
    assert "allow_origin_regex=config.cors_allow_origin_regex" in main_source
    assert "MOXI_CORS_ALLOWED_ORIGINS" in config_source
    assert "security:" in example_source
    assert "allowed_origins:" in example_source


def test_startup_log_redacts_registration_token(tmp_path):
    main_source = (CORE_ROOT / "app" / "main.py").read_text(encoding="utf-8")

    assert "注册令牌: {config.registration_token}" not in main_source
    assert "config.redacted_registration_token" in main_source

    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
agent:
  registration_token: abcd1234efgh5678
  allow_registration: true
setup:
  initialized: true
""".strip(),
        encoding="utf-8",
    )

    from app.config import AppConfig

    local_config = AppConfig(str(config_path))
    assert local_config.registration_token == "abcd1234efgh5678"
    assert local_config.redacted_registration_token == "abcd...5678"


def test_ssl_verify_defaults_to_enabled_and_template_is_safe(monkeypatch):
    example_source = (CORE_ROOT / "config.yaml.example").read_text(encoding="utf-8")
    assert "ssl_verify: true" in example_source
    assert "ssl_verify: false" not in example_source

    from app.services import text_generation_service

    monkeypatch.delenv("MOXI_TEXT_GENERATION_SSL_VERIFY", raising=False)
    monkeypatch.setattr(text_generation_service.config, "_data", {"text_generation": {}}, raising=False)
    assert text_generation_service.get_ssl_verify() is True

    monkeypatch.setattr(
        text_generation_service.config,
        "_data",
        {"text_generation": {"ssl_verify": "false", "enabled": "false"}},
        raising=False,
    )
    assert text_generation_service.get_ssl_verify() is False
    assert text_generation_service.generation_enabled() is False

    monkeypatch.setenv("MOXI_TEXT_GENERATION_SSL_VERIFY", "true")
    assert text_generation_service.get_ssl_verify() is True


def test_cors_allows_local_dev_origin_and_blocks_unknown_origin():
    from fastapi.testclient import TestClient

    from app.main import app

    client = TestClient(app)
    allowed = client.options(
        "/api/health",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert allowed.headers.get("access-control-allow-origin") == "http://localhost:5173"

    blocked = client.options(
        "/api/health",
        headers={
            "Origin": "https://untrusted.example",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert blocked.headers.get("access-control-allow-origin") is None


def test_version_endpoint_exposes_deploy_identity_without_auth(monkeypatch):
    from fastapi.testclient import TestClient

    from app.main import app

    monkeypatch.setenv("MOXI_GIT_SHA", "abcdef1234567890")
    monkeypatch.setenv("MOXI_BUILD_TIME", "2026-05-23T00:00:00Z")
    client = TestClient(app)

    response = client.get("/api/version")

    assert response.status_code == 200
    payload = response.json()
    assert payload["git_sha"] == "abcdef1234567890"
    assert payload["git_sha_short"] == "abcdef123456"
    assert payload["build_time"] == "2026-05-23T00:00:00Z"
    assert set(payload["features"]) == {"dify_enabled", "knowledge_chunks_enabled", "graphiti_enabled"}


def test_legacy_learning_routes_reject_anonymous_requests():
    from fastapi.testclient import TestClient

    from app.main import app

    client = TestClient(app)

    for method, path in [
        ("get", "/api/project-learning/materials/demo-project"),
        ("get", "/api/rule-quality/pending-promotions"),
        ("get", "/api/auto-fix/analysis"),
    ]:
        response = getattr(client, method)(path)
        assert response.status_code == 403, path


def test_secret_audit_masks_findings_and_skips_excluded_paths(tmp_path):
    module = _load_secret_audit()
    secret = "sk-liveMOXI1234567890abcdefSECRET"
    token = "production-token-1234567890abcdef"

    (tmp_path / "config.yaml").write_text(
        f"text_generation:\n  api_key: {secret}\n",
        encoding="utf-8",
    )
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "runtime.log").write_text(
        f"registration_token={token}\n",
        encoding="utf-8",
    )
    excluded_dir = tmp_path / "data" / "static"
    excluded_dir.mkdir()
    (excluded_dir / "ignored.log").write_text(
        "api_key=sk-ignoredMOXI1234567890abcdefSECRET\n",
        encoding="utf-8",
    )

    findings = module.scan(tmp_path)
    rendered = "\n".join(f"{finding.type} {finding.file}:{finding.line} {finding.snippet}" for finding in findings)

    assert len(findings) == 2
    assert "config.yaml:2" in rendered
    assert "data/runtime.log:1" in rendered
    assert "data/static/ignored.log" not in rendered
    assert secret not in rendered
    assert token not in rendered
    assert "sk-l...CRET" in rendered
    assert "prod...cdef" in rendered


def test_secret_audit_json_output_does_not_leak_full_secret(tmp_path, capsys):
    module = _load_secret_audit()
    secret = "ghp_MOXI1234567890abcdefSECRET"
    (tmp_path / ".env.production").write_text(
        f"GITHUB_TOKEN={secret}\n",
        encoding="utf-8",
    )

    exit_code = module.main(["--root", os.fspath(tmp_path), "--json"])
    output = capsys.readouterr().out

    assert exit_code == 1
    assert secret not in output
    assert "ghp_...CRET" in output
    assert '"type": "github_token"' in output
    assert '"file": ".env.production"' in output
