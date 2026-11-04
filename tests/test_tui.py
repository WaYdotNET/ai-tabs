"""The restore screen: where it starts, pins, search and the choice it returns."""

import asyncio
from datetime import datetime

from factories import agent_pane, shell_pane, tab
from textual.widgets import OptionList

from ai_tabs import store
from ai_tabs.models import Window
from ai_tabs.tui import RestoreApp

NO_CHANGES = {"opened": [], "closed": [], "changed": []}


def three_tabs() -> list[Window]:
    """Return one window with a shell tab and two agent tabs."""
    return [Window([0, 0, 800, 600], [tab(shell_pane(), title="SHELL"), tab(agent_pane("s1", "Fix the build")),
                                      tab(agent_pane("s2", "Write the docs"))])]


def run_keys(app: RestoreApp, *keys: str) -> RestoreApp:
    """Run the screen, press the keys, and return the app after it stops."""

    async def drive() -> None:
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.press(*keys)
            await pilot.pause()

    asyncio.run(drive())
    return app


def dapr_history() -> None:
    """Insert three snapshots: the DAPR agent tab, the same tab with a new title, and a DAPR shell tab."""
    first = [tab(shell_pane(), title="SHELL"), tab(agent_pane("01a1156d", "Fz bus event api plan"), title="DAPR")]
    store.insert_snapshot([Window([0, 0, 800, 600], first)], NO_CHANGES, datetime(2026, 11, 2, 15, 9, 4))
    renamed = [tab(shell_pane(), title="SHELL"), tab(agent_pane("01a1156d", "dapr"), title="DAPR")]
    store.insert_snapshot([Window([0, 0, 800, 600], renamed)], NO_CHANGES, datetime(2026, 11, 2, 16, 16, 46))
    shell_only = [tab(shell_pane(path="/home"), title="DAPR")]
    store.insert_snapshot([Window([0, 0, 800, 600], shell_only)], NO_CHANGES, datetime(2026, 11, 2, 22, 26, 26))


def run_history_keys(app: RestoreApp, *keys: str) -> RestoreApp:
    """Run the screen, press f, wait for the history to load, press the keys, and return the app after it stops."""

    async def drive() -> None:
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.press("f")
            await app.workers.wait_for_complete()
            await pilot.pause()
            await pilot.press(*keys)
            await pilot.pause()

    asyncio.run(drive())
    return app


def run_history_snapshot_count(app: RestoreApp, *keys: str) -> int:
    """Run the screen, press f, wait for the history, press the keys, and return the size of the left list."""
    counts: list[int] = []

    async def drive() -> None:
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.press("f")
            await app.workers.wait_for_complete()
            await pilot.pause()
            await pilot.press(*keys)
            await pilot.pause()
            counts.append(app.screen.query_one("#snapshots", OptionList).option_count)

    asyncio.run(drive())
    return counts[0]


def test_screen_starts_on_the_snapshot_from_before_the_crash():
    before = store.insert_snapshot(three_tabs(), NO_CHANGES, datetime(2026, 11, 2, 21, 48, 18))
    store.insert_snapshot([Window([0, 0, 1, 1], [tab(shell_pane())])], NO_CHANGES, datetime(2026, 11, 2, 22, 5, 40))
    store.set_pin(before, "before-boot")

    app = run_keys(RestoreApp(None, open_tabs=True), "enter")

    assert app.return_value.snapshot_id == before
    assert app.return_value.positions == ["1.1", "1.2", "1.3"]


def test_p_pins_the_snapshot_and_p_again_removes_the_pin():
    only = store.insert_snapshot(three_tabs(), NO_CHANGES, datetime(2026, 11, 2, 10, 0, 0))

    run_keys(RestoreApp(None, open_tabs=True), "p")
    pinned = store.find_snapshot(only).summary.pinned
    run_keys(RestoreApp(None, open_tabs=True), "p")

    assert pinned == "manual"
    assert store.find_snapshot(only).summary.pinned is None


def test_search_then_space_selects_only_the_matching_tab():
    store.insert_snapshot(three_tabs(), NO_CHANGES, datetime(2026, 11, 2, 10, 0, 0))

    app = run_keys(RestoreApp(None, open_tabs=False), "a", "slash", *"docs", "escape", "space", "enter")

    assert app.return_value.positions == ["1.3"]
    assert app.return_value.open_tabs is False


def test_enter_with_nothing_selected_keeps_the_screen_open():
    store.insert_snapshot(three_tabs(), NO_CHANGES, datetime(2026, 11, 2, 10, 0, 0))

    app = run_keys(RestoreApp(None, open_tabs=True), "a", "enter")

    assert app.return_value is None


def test_inside_iterm2_enter_asks_where_and_down_enter_opens_in_this_window(monkeypatch):
    monkeypatch.setenv("ITERM_SESSION_ID", "w0t0p0:ABC")
    store.insert_snapshot(three_tabs(), NO_CHANGES, datetime(2026, 11, 2, 10, 0, 0))

    app = run_keys(RestoreApp(None, open_tabs=True), "enter", "down", "enter")

    assert app.return_value.here is True
    assert app.return_value.positions == ["1.1", "1.2", "1.3"]


def test_inside_iterm2_enter_twice_opens_in_new_windows(monkeypatch):
    monkeypatch.setenv("ITERM_SESSION_ID", "w0t0p0:ABC")
    store.insert_snapshot(three_tabs(), NO_CHANGES, datetime(2026, 11, 2, 10, 0, 0))

    app = run_keys(RestoreApp(None, open_tabs=True), "enter", "enter")

    assert app.return_value.here is False


def test_escape_on_the_where_question_keeps_the_screen_open(monkeypatch):
    monkeypatch.setenv("ITERM_SESSION_ID", "w0t0p0:ABC")
    store.insert_snapshot(three_tabs(), NO_CHANGES, datetime(2026, 11, 2, 10, 0, 0))

    app = run_keys(RestoreApp(None, open_tabs=True), "enter", "escape")

    assert app.return_value is None


def test_f_finds_the_agent_tab_in_an_older_snapshot_and_enter_restores_it():
    dapr_history()

    app = run_history_keys(RestoreApp(None, open_tabs=False), *"dapr", "enter")

    assert app.return_value.snapshot_id == "2026-11-02/16-16-46"
    assert app.return_value.positions == ["1.2"]


def test_tab_moves_to_the_snapshots_and_down_picks_an_older_one():
    dapr_history()

    app = run_history_keys(RestoreApp(None, open_tabs=False), *"dapr", "tab", "down", "enter")

    assert app.return_value.snapshot_id == "2026-11-02/15-09-04"


def test_right_expands_and_enter_on_a_variant_uses_its_newest_snapshot():
    dapr_history()

    app = run_history_keys(RestoreApp(None, open_tabs=False), *"dapr", "escape", "right", "down", "down", "enter")

    assert app.return_value.snapshot_id == "2026-11-02/15-09-04"
    assert app.return_value.positions == ["1.2"]


def test_escape_on_the_results_returns_to_the_restore_screen_unchanged():
    dapr_history()

    app = run_history_keys(RestoreApp(None, open_tabs=False), *"dapr", "escape", "escape", "enter")

    assert app.return_value.snapshot_id == "2026-11-02/22-26-26"
    assert app.return_value.positions == ["1.1"]


def test_f_in_the_search_field_is_a_letter_of_the_query():
    dapr_history()

    app = run_history_keys(RestoreApp(None, open_tabs=False), *"fz", "enter")

    assert app.return_value.snapshot_id == "2026-11-02/15-09-04"


def test_enter_without_results_keeps_the_screen_open():
    dapr_history()

    app = run_history_keys(RestoreApp(None, open_tabs=False), "enter")

    assert app.return_value is None


def test_a_query_without_a_match_empties_the_snapshot_list():
    dapr_history()

    shown = run_history_snapshot_count(RestoreApp(None, open_tabs=False), *"dapr", *"zzz")

    assert shown == 0
