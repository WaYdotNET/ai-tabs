"""Named layouts: storage, name rules and the `ai-tabs layout` commands."""

from datetime import date, datetime

import pytest
from factories import agent_pane, shell_pane, tab, windows_with_tabs
from typer.testing import CliRunner

from ai_tabs import cli, layouts, store
from ai_tabs.cli import app
from ai_tabs.models import Window

runner = CliRunner(env={"COLUMNS": "200"})
SAVED_AT = datetime(2026, 11, 3, 9, 30, 0)
NO_CHANGES = {"opened": [], "closed": [], "changed": []}


def two_windows() -> list[Window]:
    """Return two windows: two shell tabs in the first, one omp tab in the second."""
    first = Window([0, 0, 800, 600], [tab(shell_pane(path="/a"), title="a"), tab(shell_pane(path="/b"), title="b")])
    second = Window([0, 0, 800, 600], [tab(agent_pane("s1"), title="agent")])
    return [first, second]


def insert_snapshot() -> str:
    """Store a snapshot of `two_windows` and return its ID."""
    return store.insert_snapshot(two_windows(), NO_CHANGES, datetime(2026, 11, 2, 10, 0, 0))


def test_saved_layout_loads_with_its_windows_and_time():
    layouts.save_layout("work", two_windows(), SAVED_AT)

    loaded = layouts.find_layout("work")

    assert loaded == layouts.Layout("work", SAVED_AT, two_windows())


def test_first_save_does_not_report_a_replace():
    replaced = layouts.save_layout("work", two_windows(), SAVED_AT)

    assert replaced is False


def test_save_with_an_existing_name_replaces_the_layout():
    layouts.save_layout("work", two_windows(), SAVED_AT)

    replaced = layouts.save_layout("work", windows_with_tabs(1), datetime(2026, 11, 3, 10, 0, 0))

    assert replaced is True
    assert layouts.find_layout("work") == layouts.Layout("work", datetime(2026, 11, 3, 10, 0, 0), windows_with_tabs(1))


def test_all_layouts_are_sorted_by_name():
    layouts.save_layout("zeta", windows_with_tabs(1), SAVED_AT)
    layouts.save_layout("alpha", windows_with_tabs(2), SAVED_AT)

    names = [layout.name for layout in layouts.all_layouts()]

    assert names == ["alpha", "zeta"]


def test_delete_removes_the_layout():
    layouts.save_layout("work", two_windows(), SAVED_AT)

    deleted = layouts.delete_layout("work")

    assert deleted is True
    assert layouts.layout_names() == []


def test_delete_of_an_unknown_name_reports_false():
    assert layouts.delete_layout("missing") is False


def test_prune_does_not_delete_layouts():
    layouts.save_layout("old", two_windows(), datetime(2020, 1, 1, 0, 0, 0))

    store.prune(date(2026, 11, 3))

    assert layouts.layout_names() == ["old"]


@pytest.mark.parametrize("name", ["a", "work-1_v2.0", "x" * 40])
def test_valid_names_have_no_problem(name):
    assert layouts.name_problem(name) is None


def test_name_longer_than_40_characters_is_not_valid():
    assert layouts.name_problem("x" * 41) == (
        "the name has 41 characters. A layout name has 1 to 40 characters: letters, digits, '-', '_' and '.'")


def test_empty_name_is_not_valid():
    assert layouts.name_problem("") == (
        "the name has 0 characters. A layout name has 1 to 40 characters: letters, digits, '-', '_' and '.'")


@pytest.mark.parametrize("name", ["my work", "a/b", "tab:1", "càffè"])
def test_name_with_other_characters_is_not_valid(name):
    assert "has characters that are not permitted" in layouts.name_problem(name)


def test_save_layout_refuses_an_invalid_name():
    with pytest.raises(ValueError, match="not permitted"):
        layouts.save_layout("my work", two_windows(), SAVED_AT)


def test_cli_save_from_a_snapshot_stores_all_its_tabs():
    snapshot_id = insert_snapshot()

    result = runner.invoke(app, ["layout", "save", "work", "--from", snapshot_id])

    assert result.exit_code == 0
    assert "Saved layout work: 3 tabs, 1 agents." in result.output
    assert layouts.find_layout("work").windows == two_windows()


def test_cli_save_again_says_that_it_replaced_the_layout():
    snapshot_id = insert_snapshot()
    runner.invoke(app, ["layout", "save", "work", "--from", snapshot_id])

    result = runner.invoke(app, ["layout", "save", "work", "--from", snapshot_id])

    assert result.exit_code == 0
    assert "Replaced layout work: 3 tabs, 1 agents." in result.output


def test_cli_save_with_tab_keeps_only_those_tabs():
    snapshot_id = insert_snapshot()

    result = runner.invoke(app, ["layout", "save", "work", "--from", snapshot_id, "-t", "1.2", "-t", "2.1"])

    assert result.exit_code == 0
    saved = layouts.find_layout("work").windows
    assert [[saved_tab.title for saved_tab in window.tabs] for window in saved] == [["b"], ["agent"]]


def test_cli_save_with_an_unknown_tab_stops_and_saves_nothing():
    snapshot_id = insert_snapshot()

    result = runner.invoke(app, ["layout", "save", "work", "--from", snapshot_id, "-t", "3.1"])

    assert result.exit_code == 2
    assert "unknown tab 3.1" in result.output
    assert layouts.layout_names() == []


def test_cli_save_with_an_invalid_name_says_why():
    snapshot_id = insert_snapshot()

    result = runner.invoke(app, ["layout", "save", "my work", "--from", snapshot_id])

    assert result.exit_code == 2
    assert "not permitted" in result.output
    assert layouts.layout_names() == []


def test_cli_list_shows_name_date_tabs_and_agents():
    layouts.save_layout("work", two_windows(), SAVED_AT)

    result = runner.invoke(app, ["layout", "list"])

    assert result.exit_code == 0
    assert result.output.split("\n")[3].split() == ["│", "work", "│", "2026-11-03", "09:30:00", "│", "3", "│", "1", "│"]


def test_cli_show_prints_the_command_of_each_pane():
    layouts.save_layout("work", two_windows(), SAVED_AT)

    result = runner.invoke(app, ["layout", "show", "work"])

    assert result.exit_code == 0
    assert "cd /a" in result.output
    assert "cd /work && omp --resume s1" in result.output


def test_cli_open_dry_run_prints_the_commands_and_opens_nothing(monkeypatch):
    layouts.save_layout("work", two_windows(), SAVED_AT)
    monkeypatch.setattr(cli, "open_in_new_windows", lambda windows: pytest.fail("opened windows"))

    result = runner.invoke(app, ["layout", "open", "work", "--dry-run"])

    assert result.exit_code == 0
    assert "cd /b" in result.output


def test_cli_open_here_opens_the_layout_in_this_window(monkeypatch):
    layouts.save_layout("work", two_windows(), SAVED_AT)
    opened = []
    monkeypatch.setattr(cli, "iterm_is_running", lambda: True)
    monkeypatch.setattr(cli, "open_in_current_window", opened.append)

    result = runner.invoke(app, ["layout", "open", "work", "--here"])

    assert result.exit_code == 0
    assert opened == [two_windows()]


def test_cli_unknown_name_lists_the_known_names():
    layouts.save_layout("beta", two_windows(), SAVED_AT)
    layouts.save_layout("alpha", two_windows(), SAVED_AT)

    result = runner.invoke(app, ["layout", "show", "gamma"])

    assert result.exit_code == 2
    assert "no layout 'gamma'; known layouts: alpha, beta" in result.output


def test_cli_delete_removes_the_layout():
    layouts.save_layout("work", two_windows(), SAVED_AT)

    result = runner.invoke(app, ["layout", "delete", "work"])

    assert result.exit_code == 0
    assert "Deleted layout work." in result.output
    assert layouts.layout_names() == []


def test_cli_delete_of_an_unknown_name_stops():
    result = runner.invoke(app, ["layout", "delete", "work"])

    assert result.exit_code == 2
    assert "known layouts: none" in result.output
