from __future__ import annotations

import importlib.util
from pathlib import Path
from uuid import uuid4

import pytest
import yaml


CONFIG_MODULE_PATH = Path(__file__).resolve().parents[1] / "app" / "config.py"


def _load_config_module(module_name: str):
    spec = importlib.util.spec_from_file_location(module_name, CONFIG_MODULE_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_external_config(config_path: Path, root: Path) -> None:
    config_path.write_text(
        yaml.safe_dump(
            {
                "setup": {"initialized": True},
                "admin": {
                    "password": "bcrypt:$2b$12$abcdefghijklmnopqrstuuuuuuuuuuuuuuuuuuuuuuuuuuuu"
                },
                "database": {"type": "sqlite", "path": str(root / "data" / "tasks.db")},
                "workspace": {"root": str(root / "workspace")},
                "server": {"host": "127.0.0.1", "port": 6565},
                "text_generation": {
                    "enabled": True,
                    "base_url": "https://example.invalid",
                    "api_key": "${MOXI_TEST_PROVIDER_API_KEY}",
                    "model": "unit-test-model",
                },
            },
            allow_unicode=True,
        ),
        encoding="utf-8",
    )


def test_app_config_loads_external_config_path_from_environment(tmp_path, monkeypatch):
    config_path = tmp_path / "external-config.yaml"
    _write_external_config(config_path, tmp_path)
    monkeypatch.setenv("MOXI_CONFIG_PATH", str(config_path))

    module = _load_config_module(f"test_config_external_{uuid4().hex}")

    assert Path(module.config.config_path).resolve() == config_path.resolve()
    assert module.config.database_path == str(tmp_path / "data" / "tasks.db")
    assert module.config.workspace_root == str(tmp_path / "workspace")


def test_app_config_external_config_path_missing_does_not_create_file(tmp_path, monkeypatch):
    missing_path = tmp_path / "missing-config.yaml"
    monkeypatch.setenv("MOXI_CONFIG_PATH", str(missing_path))

    with pytest.raises(FileNotFoundError):
        _load_config_module(f"test_config_missing_{uuid4().hex}")

    assert not missing_path.exists()
