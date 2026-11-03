"""Shared fixtures: every test gets its own data folder, configuration file and agent databases."""

import pytest

from ai_tabs import agents, config, sessions


@pytest.fixture(autouse=True)
def isolated_data(tmp_path, monkeypatch):
    """Point the data folder, the configuration file and the opencode and hermes databases at a temporary folder.

    The tests also run outside iTerm2.
    """
    monkeypatch.delenv("ITERM_SESSION_ID", raising=False)
    monkeypatch.setenv(config.DATA_DIR_ENV, str(tmp_path / "data"))
    monkeypatch.setattr(config, "CONFIG_FILE", tmp_path / "config.toml")
    monkeypatch.setattr(sessions, "OPENCODE_DB", tmp_path / "opencode.db")
    monkeypatch.setattr(sessions, "HERMES_DB", tmp_path / "hermes.db")
    monkeypatch.setattr(agents, "OPENCODE_DB", tmp_path / "opencode.db")
    monkeypatch.setattr(agents, "HERMES_DB", tmp_path / "hermes.db")
    config.settings.cache_clear()
    agents.running_sessions.cache_clear()
    monkeypatch.setattr(agents, "running_sessions", lambda: frozenset())
    yield tmp_path
    config.settings.cache_clear()
