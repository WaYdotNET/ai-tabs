"""Shared fixtures: every test gets its own data folder and configuration file."""

import pytest

from ai_tabs import agents, config


@pytest.fixture(autouse=True)
def isolated_data(tmp_path, monkeypatch):
    """Point the data folder and the configuration file at a temporary folder."""
    monkeypatch.setenv(config.DATA_DIR_ENV, str(tmp_path / "data"))
    monkeypatch.setattr(config, "CONFIG_FILE", tmp_path / "config.toml")
    config.settings.cache_clear()
    agents.running_sessions.cache_clear()
    monkeypatch.setattr(agents, "running_sessions", lambda: frozenset())
    yield tmp_path
    config.settings.cache_clear()
