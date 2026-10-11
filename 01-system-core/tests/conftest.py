from __future__ import annotations

import os

import pytest


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if os.getenv("MOXI_RUN_LEGACY_RESEARCH") == "1":
        return

    skip_legacy = pytest.mark.skip(
        reason="legacy research test; set MOXI_RUN_LEGACY_RESEARCH=1 to run"
    )
    for item in items:
        if item.get_closest_marker("legacy_research"):
            item.add_marker(skip_legacy)
