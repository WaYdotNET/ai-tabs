"""The restore screen: where it starts, pins, search and the choice it returns."""

import asyncio
from datetime import datetime

from factories import agent_pane, shell_pane, tab

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
