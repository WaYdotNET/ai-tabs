"""The session and layout lists of the restore screen, and how `run_choice` opens their windows."""

import asyncio
from datetime import datetime
from pathlib import Path

import pytest
from factories import agent_pane, shell_pane, tab

from ai_tabs import cli, layouts, sessions, store
from ai_tabs.models import Window
from ai_tabs.sessions import Session
from ai_tabs.tui import RestoreApp, RestoreChoice

NO_CHANGES = {"opened": [], "closed": [], "changed": []}
SAVED_AT = datetime(2026, 11, 3, 9, 30, 0)
NEWER = Session("claude", "aaaa1111-2222", "/work/api", "Fix the build", Path("/s/aaaa.jsonl"),
                datetime(2026, 11, 3, 9, 0, 0))
OLDER = Session("omp", "bbbb3333-4444", "/work/web", "Write the docs", Path("/s/bbbb.jsonl"),
                datetime(2026, 11, 2, 18, 0, 0))


def layout_windows(path: str) -> list[Window]:
    """Return one window with a shell tab in a folder and an omp tab."""
    return [Window([0, 0, 800, 600], [tab(shell_pane(path=path), title="shell"), tab(agent_pane("s1"), title="agent")])]


def run_keys(app: RestoreApp, *keys: str) -> list[str]:
    """Run the screen, press the keys, and return the messages of the notifications that it showed."""
    messages: list[str] = []

    async def drive() -> None:
        async with app.run_test(size=(100, 30)) as pilot:
            app.notify = lambda message, **options: messages.append(message)
            await pilot.press(*keys)
            await pilot.pause()

    asyncio.run(drive())
    return messages


@pytest.fixture
def two_sessions(monkeypatch):
    """Make the session list show a Claude Code session and an older omp session."""
    monkeypatch.setattr(sessions, "recent_sessions", lambda days: [NEWER, OLDER])


@pytest.fixture
def opened(monkeypatch) -> list[tuple[str, list[Window]]]:
    """Record the windows that `run_choice` opens, with the place where they open."""
    calls: list[tuple[str, list[Window]]] = []
    monkeypatch.setattr(cli, "iterm_is_running", lambda: True)
    monkeypatch.setattr(cli, "open_in_new_windows", lambda windows: calls.append(("new", windows)))
    monkeypatch.setattr(cli, "open_in_current_window", lambda windows: calls.append(("here", windows)))
    return calls


def test_r_space_enter_returns_a_window_that_resumes_the_selected_session(two_sessions):
    app = RestoreApp(None, open_tabs=True)

    run_keys(app, "r", "down", "space", "enter")

    window = app.return_value.windows[0]
    assert len(window.tabs) == 1
    assert window.tabs[0].panes[0].agent.resume == "cd /work/web && omp --resume /s/bbbb.jsonl"
    assert app.return_value.positions == ["1.1"]


def test_space_on_two_sessions_returns_one_tab_for_each_in_list_order(two_sessions):
    app = RestoreApp(None, open_tabs=True)

    run_keys(app, "r", "down", "space", "up", "space", "enter")

    tabs = app.return_value.windows[0].tabs
    assert tabs[0].panes[0].agent.session_id == "aaaa1111-2222"
    assert tabs[1].panes[0].agent.session_id == "bbbb3333-4444"
    assert app.return_value.positions == ["1.1", "1.2"]


def test_enter_without_a_selection_resumes_the_highlighted_session(two_sessions):
    app = RestoreApp(None, open_tabs=True)

    run_keys(app, "r", "down", "enter")

    assert app.return_value.windows[0].tabs[0].panes[0].agent.session_id == "bbbb3333-4444"


def test_space_twice_clears_the_session_and_enter_resumes_the_highlighted_one(two_sessions):
    app = RestoreApp(None, open_tabs=True)

    run_keys(app, "r", "space", "space", "down", "enter")

    assert len(app.return_value.windows[0].tabs) == 1
    assert app.return_value.windows[0].tabs[0].panes[0].agent.session_id == "bbbb3333-4444"


def test_r_with_no_recent_session_shows_a_warning(monkeypatch):
    monkeypatch.setattr(sessions, "recent_sessions", lambda days: [])
    app = RestoreApp(None, open_tabs=True)

    messages = run_keys(app, "r")

    assert messages == ["No session of the last 7 days to resume."]
    assert app.return_value is None


def test_escape_on_the_session_list_keeps_the_restore_screen_open(two_sessions):
    snapshot_id = store.insert_snapshot(layout_windows("/a"), NO_CHANGES, datetime(2026, 11, 2, 10, 0, 0))
    app = RestoreApp(None, open_tabs=True)

    run_keys(app, "r", "escape", "enter")

    assert app.return_value.snapshot_id == snapshot_id
    assert app.return_value.windows is None


def test_l_enter_returns_the_windows_of_the_highlighted_layout():
    layouts.save_layout("alpha", layout_windows("/a"), SAVED_AT)
    layouts.save_layout("beta", layout_windows("/b"), SAVED_AT)
    app = RestoreApp(None, open_tabs=True)

    run_keys(app, "l", "down", "enter")

    assert app.return_value.windows == layout_windows("/b")
    assert app.return_value.positions == ["1.1", "1.2"]
    assert app.return_value.snapshot_id == ""


def test_l_with_no_layouts_explains_how_to_save_one():
    app = RestoreApp(None, open_tabs=True)

    messages = run_keys(app, "l")

    assert messages == ["There are no layouts. Save one with `ai-tabs layout save NAME`."]
    assert app.return_value is None


def test_escape_on_the_layout_list_keeps_the_restore_screen_open():
    layouts.save_layout("alpha", layout_windows("/a"), SAVED_AT)
    snapshot_id = store.insert_snapshot(layout_windows("/b"), NO_CHANGES, datetime(2026, 11, 2, 10, 0, 0))
    app = RestoreApp(None, open_tabs=True)

    run_keys(app, "l", "escape", "enter")

    assert app.return_value.snapshot_id == snapshot_id
    assert app.return_value.windows is None


def test_inside_iterm2_a_layout_asks_where_and_down_enter_opens_it_in_this_window(monkeypatch):
    monkeypatch.setenv("ITERM_SESSION_ID", "w0t0p0:ABC")
    layouts.save_layout("alpha", layout_windows("/a"), SAVED_AT)
    app = RestoreApp(None, open_tabs=True)

    run_keys(app, "l", "enter", "down", "enter")

    assert app.return_value.here is True
    assert app.return_value.windows == layout_windows("/a")


def test_inside_iterm2_escape_on_the_where_question_after_sessions_keeps_the_screen_open(monkeypatch, two_sessions):
    monkeypatch.setenv("ITERM_SESSION_ID", "w0t0p0:ABC")
    app = RestoreApp(None, open_tabs=True)

    run_keys(app, "r", "enter", "escape")

    assert app.return_value is None


def test_dry_run_returns_the_layout_without_the_where_question(monkeypatch):
    monkeypatch.setenv("ITERM_SESSION_ID", "w0t0p0:ABC")
    layouts.save_layout("alpha", layout_windows("/a"), SAVED_AT)
    app = RestoreApp(None, open_tabs=False)

    run_keys(app, "l", "enter")

    assert app.return_value.open_tabs is False
    assert app.return_value.here is False


def test_run_choice_with_windows_opens_those_windows(opened):
    choice = RestoreChoice("", ["1.1", "1.2"], open_tabs=True, windows=layout_windows("/a"))

    cli.run_choice(choice)

    assert opened == [("new", layout_windows("/a"))]


def test_run_choice_with_windows_here_opens_them_in_this_window(opened):
    choice = RestoreChoice("", ["1.1", "1.2"], open_tabs=True, here=True, windows=layout_windows("/a"))

    cli.run_choice(choice)

    assert opened == [("here", layout_windows("/a"))]


def test_run_choice_with_windows_lets_only_the_first_pane_of_a_session_resume_it(opened):
    twice = [Window([0, 0, 800, 600], [tab(agent_pane("s1"), title="one"), tab(agent_pane("s1"), title="two")])]
    choice = RestoreChoice("", ["1.1", "1.2"], open_tabs=True, windows=twice)

    cli.run_choice(choice)

    tabs = opened[0][1][0].tabs
    assert tabs[0].panes[0].agent.resume == "cd /work && omp --resume s1"
    assert tabs[1].panes[0].agent.resume == "cd /work  # omp session s1 is also in tab 1.1"


def test_run_choice_dry_run_with_windows_prints_the_commands_and_opens_nothing(opened, capsys):
    choice = RestoreChoice("", ["1.1", "1.2"], open_tabs=False, windows=layout_windows("/a"))

    cli.run_choice(choice)

    output = capsys.readouterr().out
    assert opened == []
    assert "cd /a" in output
    assert "cd /work && omp --resume s1" in output
