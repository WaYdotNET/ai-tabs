"""The Markdown export of a snapshot, and the settings window of the restore screen."""

import asyncio
from datetime import datetime

from factories import agent_pane, tab
from typer.testing import CliRunner

from ai_tabs import config, store
from ai_tabs.cli import app
from ai_tabs.models import Window
from ai_tabs.tui import RestoreApp

CHANGES = {"opened": ["**BUILD**: omp “Fix the build” in `/work`"], "closed": [], "changed": []}


def build_snapshot() -> str:
    """Store one snapshot with one agent tab and return its ID."""
    windows = [Window([0, 0, 800, 600], [tab(agent_pane("s1", "Fix the build"), title="BUILD")])]
    return store.insert_snapshot(windows, CHANGES, datetime(2026, 11, 2, 10, 0, 0))


def test_export_writes_one_file_per_snapshot_in_a_day_folder(isolated_data):
    snapshot_id = build_snapshot()

    result = CliRunner().invoke(app, ["export", snapshot_id, "--to", str(isolated_data / "out")])

    exported = (isolated_data / "out/2026-11-02/10-00-00.md").read_text()
    assert result.exit_code == 0
    assert exported.startswith("---\nid: 2026-11-02/10-00-00\ncreated: 2026-11-02 10:00:00\ntabs: 1\nagents: 1\n")
    assert "- Opened: **BUILD**: omp “Fix the build” in `/work`" in exported
    assert "cd /work && omp --resume s1" in exported


def test_export_without_options_writes_latest_to_export_dir():
    build_snapshot()
    config.write_config({"export_dir": str(config.settings().data_dir / "exports")})

    result = CliRunner().invoke(app, ["export"])

    assert result.exit_code == 0
    assert (config.settings().export_dir / "2026-11-02/10-00-00.md").exists()


def test_config_set_refuses_an_invalid_value():
    result = CliRunner().invoke(app, ["config", "set", "backup_keep", "none"])

    assert result.exit_code == 2
    assert "backup_keep must be a whole number greater than 0" in result.output
    assert config.read_config() == {}


def run_settings(*keys: str) -> RestoreApp:
    """Open the settings window on the restore screen, press the keys, and return the app."""
    build_snapshot()
    app_under_test = RestoreApp(None, open_tabs=True)

    async def drive() -> None:
        async with app_under_test.run_test(size=(120, 40)) as pilot:
            await pilot.press("o")
            await pilot.pause()
            app_under_test.screen.query_one("#setting-history_days").value = "90"
            await pilot.press(*keys)
            await pilot.pause()

    asyncio.run(drive())
    return app_under_test


def test_settings_window_saves_the_fields_to_the_configuration_file():
    run_settings("ctrl+s")

    assert config.read_config() == {"history_days": 90}


def test_settings_window_cancel_keeps_the_configuration_file():
    run_settings("escape")

    assert config.read_config() == {}


def test_settings_window_keeps_the_saved_backup_times_as_a_list():
    config.write_config({"backup_times": ["08:00", "18:00"]})

    run_settings("ctrl+s")

    assert config.read_config() == {"backup_times": ["08:00", "18:00"], "history_days": 90}
