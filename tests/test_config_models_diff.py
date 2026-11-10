"""Settings precedence and validation, reading old snapshot data, and the change list."""

from pathlib import Path

import pytest
from factories import agent_pane, shell_pane, tab
from typer.testing import CliRunner

from ai_tabs import config
from ai_tabs.cli import app
from ai_tabs.diff import changes
from ai_tabs.models import Window, windows_from_data


def test_environment_folder_wins_over_the_configuration_file(isolated_data):
    config.write_config({"data_dir": "/from/config"})

    assert config.settings().data_dir == isolated_data / "data"
    assert config.setting_source("data_dir") == "environment"


def test_configuration_file_sets_the_folders_and_the_rest_takes_defaults(monkeypatch, isolated_data):
    monkeypatch.delenv(config.DATA_DIR_ENV)
    config.write_config({"data_dir": str(isolated_data / "db"), "export_dir": "/vault/tabs"})

    current = config.settings()

    assert current.database == isolated_data / "db/ai-tabs.sqlite"
    assert current.export_dir == Path("/vault/tabs")
    assert current.backup_dir == isolated_data / "db/backups"
    assert (current.export_latest, current.backup_keep, current.history_days, current.snapshot_interval) == (
        False, 7, 30, 300)
    assert config.setting_source("export_dir") == "file"
    assert config.setting_source("backup_dir") == "default"


def test_writing_the_configuration_keeps_the_other_keys():
    config.write_config({"export_dir": "/vault/tabs"})
    config.write_config({"backup_keep": 3})

    assert config.read_config() == {"export_dir": "/vault/tabs", "backup_keep": 3}


def test_unset_gives_a_setting_its_default_again():
    config.write_config({"history_days": 90, "backup_keep": 3})

    config.unset_config("history_days")

    assert config.read_config() == {"backup_keep": 3}
    assert config.settings().history_days == 30


def test_settings_parse_folders_booleans_and_numbers():
    assert config.parse_setting("export_dir", "/vault/./tabs") == "/vault/tabs"
    assert config.parse_setting("export_latest", "TRUE") is True
    assert config.parse_setting("snapshot_interval", "120") == 120
    assert config.parse_setting("backup_times", "17:00, 9:00") == ["09:00", "17:00"]


def test_backup_times_drop_a_repeated_time():
    assert config.parse_setting("backup_times", "09:00,9:00") == ["09:00"]


@pytest.mark.parametrize(("key", "text", "message"), [
    ("colour", "red", "unknown setting 'colour'"),
    ("export_latest", "yes", "export_latest must be true or false"),
    ("backup_keep", "0", "backup_keep must be a whole number greater than 0"),
    ("history_days", "-3", "history_days must be a whole number greater than 0"),
    ("backup_times", "25:00", "backup_times must be a time of day from 00:00 to 23:59"),
    ("backup_times", "09:00,12:60", "backup_times must be a time of day from 00:00 to 23:59"),
    ("backup_times", "noon", "backup_times must be a time of day from 00:00 to 23:59"),
    ("backup_times", "09:00,", "backup_times must be a time of day from 00:00 to 23:59"),
    ("backup_times", "", "backup_times must hold at least one time of day HH:MM"),
])
def test_invalid_settings_are_refused(key, text, message):
    with pytest.raises(ValueError, match=message):
        config.parse_setting(key, text)


def test_backup_times_default_to_9_00_and_17_00():
    assert config.settings().backup_times == ["09:00", "17:00"]


def test_config_set_saves_backup_times_as_a_list():
    result = CliRunner().invoke(app, ["config", "set", "backup_times", "9:00,17:00"])

    assert result.exit_code == 0
    assert config.read_config() == {"backup_times": ["09:00", "17:00"]}


def test_config_set_prints_backup_times_as_text_with_commas():
    result = CliRunner().invoke(app, ["config", "set", "backup_times", "9:00,17:00"])

    assert result.output == "backup_times = 09:00,17:00\n"


def test_config_set_refuses_an_hour_after_23():
    result = CliRunner().invoke(app, ["config", "set", "backup_times", "25:00"])

    assert result.exit_code == 2
    assert config.read_config() == {}


def test_config_set_refuses_empty_backup_times():
    result = CliRunner().invoke(app, ["config", "set", "backup_times", ""])

    assert result.exit_code == 2
    assert config.read_config() == {}


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
