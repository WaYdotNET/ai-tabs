"""Configuration precedence, reading old snapshot data, and the change list between snapshots."""

from pathlib import Path

from factories import agent_pane, shell_pane, tab

from ai_tabs import config
from ai_tabs.diff import changes
from ai_tabs.models import Window, windows_from_data


def test_environment_folder_wins_over_the_configuration_file(isolated_data):
    config.write_config({"data_dir": "/from/config"})

    assert config.settings().data_dir == isolated_data / "data"


def test_configuration_file_sets_the_folders(monkeypatch, isolated_data):
    monkeypatch.delenv(config.DATA_DIR_ENV)
    config.write_config({"data_dir": str(isolated_data / "db"), "markdown_dir": "/vault/tabs"})

    current = config.settings()

    assert current.database == isolated_data / "db/ai-tabs.sqlite"
    assert current.markdown_dir == Path("/vault/tabs")
    assert current.backup_dir == isolated_data / "db/backups"
    assert current.backup_keep == 7


def test_writing_the_configuration_keeps_the_other_keys():
    config.write_config({"markdown_dir": "/vault/tabs"})
    config.write_config({"backup_keep": 3})

    assert config.read_config() == {"markdown_dir": "/vault/tabs", "backup_keep": 3}


def test_snapshot_data_from_before_profiles_and_layouts_still_loads():
    old = [{"frame": [0, 0, 800, 600], "tabs": [{"title": "T", "color": None, "panes": [
        {"name": "zsh", "tty": "/dev/ttys001", "path": "/work", "agent": None}]}]}]

    loaded = windows_from_data(old)

    pane = loaded[0].tabs[0].panes[0]
    assert (pane.profile, pane.columns, pane.rows, loaded[0].tabs[0].layout) == (None, None, None, None)


def test_a_new_session_title_is_a_change_not_a_close_and_an_open():
    before = [Window([0, 0, 1, 1], [tab(agent_pane("s1", "Old title"))])]
    after = [Window([0, 0, 1, 1], [tab(agent_pane("s1", "New title"))])]

    diff = changes(before, after)

    assert diff["opened"] == [] and diff["closed"] == []
    assert diff["changed"] == ["**omp**: omp “Old title” in `/work` → **omp**: omp “New title” in `/work`"]


def test_panes_that_appear_and_disappear_are_opened_and_closed():
    before = [Window([0, 0, 1, 1], [tab(shell_pane("/dev/ttys001", "/a"))])]
    after = [Window([0, 0, 1, 1], [tab(shell_pane("/dev/ttys002", "/b"))])]

    diff = changes(before, after)

    assert diff["opened"] == ["**zsh**: shell in `/b`"]
    assert diff["closed"] == ["**zsh**: shell in `/a`"]
